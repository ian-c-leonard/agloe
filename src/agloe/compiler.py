"""The COMPILER: the answers of spec/rules.md, found with a solver.

The reference checker tries every choice of PERSONs and orders. This module asks CP-SAT for the
choice instead. It then hands that choice to the reference checker's own functions, which time it
and check it against the CONSTRAINTs. So whenever this module says that something works, the
rules as the reference checker applies them have agreed.

Only the search is different. The three answers, ROBUST and the evidence are worked out by
``answers.check``, with this module's search in place of the reference checker's.

For INFEASIBLE, the search for the conflict asks whether anything can still work once records
are taken out. The solver answers each such question with one model. Where taking FACTs out
leaves it open whether an OPTION SATISFIES a WANT, the solver chooses that too.

The solver counts in 64-bit numbers. A TRIP with very long durations and very many routes can
need more than that. The reference checker's own search then answers for the whole TRIP. That
search tries everything, so it is meant for small TRIPs.
"""

from collections.abc import Sequence
from dataclasses import replace
from hashlib import sha256
from math import inf

from ortools.sat.python import cp_model

from agloe import answers, reference
from agloe.answers import Report
from agloe.file import (
    Complete,
    File,
    StartsFrom,
    Want,
)
from agloe.reference import Itinerary, Remaining, World

_MOST_AT_ONCE = 60  # yes-or-no choices ranked in one solve: their weights must fit in 64 bits
_FURTHEST = 2**62  # a time further than this from the first fixed time does not fit in 64 bits
# How CP-SAT starts when it refuses a model because its variables can take too many values.
_TOO_MANY_VALUES = "The sum of all variable domains do not fit on an int64_t"

type _Who = tuple[tuple[str, ...], ...]  # the PERSONs in each OPTION
type _Orders = tuple[tuple[int, ...], ...]  # the OPTIONs each PERSON does, in order
type _By = dict[tuple[int, int], reference.Route]  # the WAYs a PERSON takes after an OPTION
type _Choice = tuple[_Who, _Orders, _By | None]
# For each model the solver was asked about, by its digest: the plan and the open pairs that
# held in it, or None where nothing works.
type _Asked = dict[bytes, tuple[_Choice, frozenset[tuple[str, str]]] | None]
type _Amount = cp_model.LinearExpr | int  # seconds: a plain number, or one the solver works out
type _Taken = list[tuple[cp_model.IntVar, reference.Route]]  # routes, each with its choice
# The same with the time each route arrives. None: nobody knows, and nothing follows it.
type _Reached = list[tuple[cp_model.IntVar, reference.Route, _Amount | None]]


class DoesNotFit(Exception):
    """The numbers of a TRIP's model do not fit in the 64 bits the solver counts with."""


def check(file: File) -> Report:
    """The answer for this TRIP, with its evidence. The same Report as the reference checker's.

    A FILE with a cap goes to the reference checker: the solver does not yet share out what
    each BUDGET can still spend.
    """
    if file.caps:
        return answers.check(file)
    try:
        asked: _Asked = {}
        return answers.check(file, shown, works, lambda left: can_work(left, asked))
    except DoesNotFit:
        return answers.check(file)


def shown(file: File, world: World) -> Itinerary | None:
    """The ITINERARY that "Which ITINERARY is shown" puts first in this world, or None."""
    search = _Search(file, world)
    choice = search.first_in_file_order()
    return None if choice is None else _checked(file, world, choice, search.known)


def works(file: File, world: World) -> bool:
    """Whether any ITINERARY works in this world."""
    choice = _Search(file, world).any()
    if choice is not None:
        _checked(file, world, choice)
    return choice is not None


def can_work(remaining: Remaining, asked: _Asked | None = None) -> bool:
    """Whether any ITINERARY works in some best case of what is left of a FILE.

    The best cases differ only in the pairs that are left open: whether an OPTION SATISFIES a
    WANT that is a must for one PERSON and a must-not for another. The solver chooses that
    for each pair, with the plan. So one question takes one model, however many pairs are
    open. The reference checker then checks the plan in the best case the solver chose.

    ``asked`` holds what the solver answered for each model it was given before. A FACT that
    is taken out often changes nothing in the model: it said what the best case takes anyway.
    The same model has the same answer, so the solver is asked once. The plan is still
    checked against what is left this time.

    Like ``shown`` and ``works``, this is for a FILE with no cap: ``check`` hands a FILE with
    a cap to the reference checker.
    """
    file = remaining.file
    world, open_pairs = reference.best_case_left(remaining)
    search = _Search(file, world, open_pairs)
    key = sha256(str(search.model.proto).encode()).digest()
    if asked is None or key not in asked:
        choice = search.any()
        found = None if choice is None else (choice, search.turned_out)
        if asked is None:
            asked = {}
        asked[key] = found
    found = asked[key]
    if found is None:
        return False
    choice, does = found
    chosen = replace(
        world, satisfies=world.satisfies | does, might_satisfy=world.might_satisfy | does
    )
    _checked(file, chosen, choice)
    return True


def _checked(
    file: File, world: World, choice: _Choice, known: reference.Routes | None = None
) -> Itinerary:
    """The solver's choice, timed and checked by the reference checker.

    For the ITINERARY shown, the reference checker picks the WAYs itself, in the order of the
    rules page, from the routes already worked out. Otherwise it checks the WAYs the solver
    picked.
    """
    itinerary = reference.scheduled(file, world, *choice, known)
    if itinerary is None:
        raise AssertionError("the solver chose PERSONs and orders that the rules refuse")
    return itinerary


def _solver(relax: bool = True) -> cp_model.CpSolver:
    """A solver set up to give the same result every time.

    ``relax`` keeps its linear relaxation, which it needs to prove a best value in good
    time. A question with nothing to make smaller is answered faster without it.

    Its simplification step is switched off. In OR-Tools 9.15 that step reported that nothing
    works for a model that had an answer. A wrong "nothing works" is the one mistake nothing
    else here would catch, since a choice the solver finds is always checked by the rules.

    It calls a value the best only once it has proved that. By default it also stops when
    its bounds, held as floating-point numbers, come within a ten-thousandth of each other.
    Two whole numbers above two to the power 53 can be one floating-point number, and the
    tie break weighs up to sixty choices in one whole number. So both gap limits are zero.
    """
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 1
    solver.parameters.cp_model_presolve = False
    solver.parameters.absolute_gap_limit = 0.0
    solver.parameters.relative_gap_limit = 0.0
    if not relax:
        solver.parameters.linearization_level = 0
    return solver


def _quickest(world: World, routes: Sequence[reference.Route]) -> list[reference.Route]:
    """The routes worth choosing between when only their time and their number of WAYs matter.

    For each number of WAYs the quickest route is kept, unless a route with fewer WAYs is at
    least as quick. A WAY SATISFIES no WANT, so nothing else about a route can matter. A route
    with a WAY that has no limit to how long it takes is slower than any other. The reference
    checker still names the WAYs of the ITINERARY shown.
    """

    def takes(way: str | None) -> float:
        if way is None:
            return world.unlisted_takes
        shortest, longest = world.takes[way]
        return inf if longest is None else shortest

    def time(route: reference.Route) -> float:
        return sum(takes(way) for way, _, _ in route)

    kept: list[reference.Route] = []
    for route in sorted(routes, key=lambda route: (len(route), time(route))):
        if not kept or time(route) < time(kept[-1]):
            kept.append(route)
    return kept


def _when(constraint: cp_model.Constraint, *conditions: cp_model.LiteralT) -> None:
    """Make a constraint apply only when every condition holds."""
    constraint.only_enforce_if(list(conditions))  # pyright: ignore[reportUnknownMemberType]


class _Search:
    """One world as a CP-SAT model: who takes part in which OPTION, and in what order.

    With open pairs, the model stands for each world that differs only in them, and the
    solver chooses among those worlds too.

    Each PERSON's OPTIONs form a path. The path is a circuit through a starting point that stands
    for "before the first OPTION and after the last". Where the next OPTION starts somewhere
    else, WAYs take the PERSON there, by one of the routes the world has. Start times
    exist in the model only to prove that some timing fits; the times shown come from the
    reference checker.
    """

    def __init__(
        self, file: File, world: World, open_pairs: Sequence[tuple[str, str]] = ()
    ) -> None:
        """Build the model of this world.

        ``open_pairs`` are left to the solver: each an OPTION and a WANT, and whether the
        OPTION SATISFIES the WANT. The world must say that they do not.
        """
        self.file, self.world = file, world
        self.model = cp_model.CpModel()
        # The choice for each open pair, and the pairs that held in the last answer.
        self.does = {
            pair: self.model.new_bool_var(f"{pair[0]} satisfies {pair[1]}") for pair in open_pairs
        }
        self.turned_out: frozenset[tuple[str, str]] = frozenset()
        self._read_the_world()
        self._count_time()
        self._choose_who_takes_part()
        for index in range(len(file.options)):
            lasts = None if self.endless[index] else self.lasts[index]
            self._keep_within_the_trip(self.start[index], lasts, self.used[index])
        self.follows: list[dict[tuple[int, int], cp_model.IntVar]] = []
        self.nothing: list[cp_model.IntVar] = []
        # For each PERSON, the routes between two OPTIONs in different PLACEs, each with the
        # choice that takes it.
        self.routes: list[dict[tuple[int, int], _Taken]] = []
        self.legs: list[tuple[cp_model.IntVar, int]] = []  # a route taken, and how many WAYs it has
        self.known = reference.Routes(file, world)
        self._worth_trying: dict[tuple[str, str, bool], list[reference.Route]] = {}
        for number in range(len(file.persons)):
            self._lay_out_path(number)

    def _read_the_world(self) -> None:
        """What the world says about each OPTION and WAY."""
        file, world = self.file, self.world
        self.terms = [world.terms[option.id] for option in file.options]
        self.usable = [each.fixed_start is not None or each.free_start for each in self.terms]
        self.endless = [each.longest is None for each in self.terms]
        self.moves = [option.origin != option.destination for option in file.options]
        self.lasts = [each.shortest for each in self.terms]
        self.margins = [each.margin for each in self.terms]
        # How long each WAY takes. None: there is no limit, and nobody knows when it ends.
        self.way_lasts: dict[str | None, int | None] = {None: world.unlisted_takes}
        for way in file.ways:
            shortest, longest = world.takes[way.id]
            self.way_lasts[way.id] = None if longest is None else shortest
        unlisted = world.unlisted is None or bool(world.unlisted)
        self.facts = [fact for fact in file.facts if isinstance(fact, Complete)] if unlisted else []

    def _count_time(self) -> None:
        """When each OPTION starts, and its turn among OPTIONs that share an instant.

        The model counts time from the earliest fixed time, to keep its numbers small. Every
        start that matters lies within ``room`` of a fixed start or of the end of a span. A start
        is a plain number where a FACT fixes it for good, and the solver's otherwise.
        """
        model, options, terms, world = self.model, self.file.options, self.terms, self.world
        fixed = [each.fixed_start for each in terms if each.fixed_start is not None]
        spans = [moment for fact in self.facts for moment in (fact.earliest - 1, fact.latest + 1)]
        spans += [bound.at for bound in (self.file.trip_start(), self.file.trip_end()) if bound]
        self.zero = min([*fixed, *spans], default=0)
        room = sum(each.shortest for each in terms) + sum(each.margin or 0 for each in terms) + 1
        slowest = max([world.unlisted_takes, *(shortest for shortest, _ in world.takes.values())])
        # Travel after each OPTION, and at each end of a path that the FILE gives an end.
        ends = any(isinstance(fact, StartsFrom) for fact in self.file.facts)
        ends += any(want.ends_at is not None for want in self.file.wants)
        room += (len(options) + ends) * max(len(self.file.places), 1) * slowest
        self.room = room
        self.earliest, self.latest = -room, max([*fixed, *spans], default=0) - self.zero + room
        if self.latest + room >= _FURTHEST:
            raise DoesNotFit("the times this TRIP can reach are too far apart")

        self.start = [
            model.new_int_var(self.earliest, self.latest, f"start {option.id}")
            if each.fixed_start is None
            else model.new_constant(each.fixed_start - self.zero)
            for option, each in zip(options, terms, strict=True)
        ]
        last = max(len(options) - 1, 0)
        self.turn = [model.new_int_var(0, last, f"turn {option.id}") for option in options]

    def _choose_who_takes_part(self) -> None:
        """Who takes part in each OPTION. LOCKs are honored, and an unusable OPTION is left out."""
        model, file = self.model, self.file
        self.takes = [
            [model.new_bool_var(f"takes {person.id} {option.id}") for option in file.options]
            for person in file.persons
        ]
        self.used = [model.new_bool_var(f"used {option.id}") for option in file.options]
        self.left_out: set[tuple[int, int]] = set()  # each PERSON and OPTION that is ruled out
        meets = self._hold_to_the_wants()
        for index, option in enumerate(file.options):
            model.add_max_equality(self.used[index], [0, *(row[index] for row in self.takes)])
            for number, person in enumerate(file.persons):
                takes = self.takes[number][index]
                asked = any(
                    lock.option == option.id and person.id in lock.persons for lock in file.locks
                )
                if asked:
                    model.add(takes == 1)
                # A PERSON gains nothing by staying somewhere unless a LOCK asks them to, or
                # the stay could meet a must of theirs. Without the stay they are in the same
                # PLACE at the same times, and every CONSTRAINT is as easy to meet or easier.
                # So the model leaves such stays out.
                wanted = index in meets[number]
                if not self.usable[index] or (not self.moves[index] and not asked and not wanted):
                    self._rule_out(number, index)
        self._hold_to_the_rights()

    def _rule_out(self, number: int, index: int) -> None:
        """This PERSON takes no part in this OPTION, whatever else is chosen.

        So no travel is built for them to it or from it.
        """
        self.model.add(self.takes[number][index] == 0)
        self.left_out.add((number, index))

    def _hold_to_the_rights(self) -> None:
        """Nobody takes part without a right in an OPTION that needs one."""
        file, world = self.file, self.world
        people = list(enumerate(file.persons))
        for index, option in enumerate(file.options):
            if option.id in world.needs_right:
                without = [n for n, person in people if (option.id, person.id) not in world.rights]
                self._share_out(index, without)

    def _share_out(self, index: int, without: Sequence[int]) -> None:
        """Each of these PERSONs who takes part in an OPTION takes a place they can pay for.

        They are the PERSONs with no right of their own to it. No place is taken twice.

        A PERSON who is ruled out of the OPTION needs no place. A PERSON who can pay for no
        place stays out, and an OFFER that none of them can pay for is left out. Where each of
        the others can pay for a place of every other OFFER, the places are alike, and it is
        enough to count them. Otherwise the model chooses an OFFER for each PERSON.
        """
        model, world, option = self.model, self.world, self.file.options[index]
        people = self.file.persons
        without = [number for number in without if (number, index) not in self.left_out]
        able = {
            number: [
                offer
                for offer in self.file.offers(option.id)
                if (offer.id, people[number].id) in world.payable
            ]
            for number in without
        }
        for number in without:
            if not able[number]:
                self._rule_out(number, index)
        buyers = [number for number in without if able[number]]
        wanted = {offer.id for number in buyers for offer in able[number]}
        offers = [offer for offer in self.file.offers(option.id) if offer.id in wanted]
        places = sum(offer.places for offer in offers)
        if all(len(able[number]) == len(offers) for number in buyers):
            if places < len(buyers):
                model.add(sum(self.takes[number][index] for number in buyers) <= places)
            return
        taken: dict[str, list[cp_model.IntVar]] = {offer.id: [] for offer in offers}
        for number in buyers:
            takes = self.takes[number][index]
            picks = [
                model.new_bool_var(f"{people[number].id} takes a place of {offer.id}")
                for offer in able[number]
            ]
            for offer, pick in zip(able[number], picks, strict=True):
                taken[offer.id].append(pick)
            model.add(sum(picks) >= takes)
        for offer in offers:
            if len(taken[offer.id]) > offer.places:
                model.add(sum(taken[offer.id]) <= offer.places)

    def _hold_to_the_wants(self) -> list[set[int]]:
        """Every must is met and every must-not is kept. Returns what could meet a must.

        That is, for each PERSON, the OPTIONs that could meet a must of theirs. An OPTION of
        an open pair meets a must only where the solver chooses that it SATISFIES the WANT,
        and then no PERSON for whom the WANT is a must-not takes part in it.
        """
        model, file, world = self.model, self.file, self.world
        meets: list[set[int]] = [set() for _ in file.persons]
        for want in self._delivered():
            for index, option in enumerate(file.options):
                if (option.id, want.id) in world.might_satisfy:
                    for number, person in enumerate(file.persons):
                        if person.id in want.must_nots:
                            self._rule_out(number, index)
            would = [
                index
                for index, option in enumerate(file.options)
                if (option.id, want.id) in world.satisfies
            ]
            open_here = [
                (index, self.does[option.id, want.id])
                for index, option in enumerate(file.options)
                if (option.id, want.id) in self.does
            ]
            for number, person in enumerate(file.persons):
                takes = self.takes[number]
                if person.id in want.must_nots:
                    for index, does in open_here:
                        model.add_bool_or([takes[index].negated(), does.negated()])
                elsewhere = (want.id, person.id) in world.another_option
                if person.id in want.musts and not elsewhere:
                    meets[number].update([*would, *(index for index, _ in open_here)])
                    met: list[cp_model.IntVar] = [takes[index] for index in would]
                    for index, does in open_here:
                        here = model.new_bool_var(f"{person.id} gets {want.id} by {index}")
                        model.add_implication(here, takes[index])
                        model.add_implication(here, does)
                        met.append(here)
                    model.add_bool_or(met)
        return meets

    def _delivered(self) -> list[Want]:
        """The WANTs about something an OPTION can deliver. The path settles the others."""
        return [want for want in self.file.wants if want.ends_at is None]

    def _lay_out_path(self, number: int) -> None:
        """One PERSON's path: a circuit through the OPTIONs they do.

        The two ends of the path are one point of the circuit. A PERSON travels from where
        their path begins to the OPTION they do first, and from the one they do last to where
        their path has to end. ``moved`` says whether the PERSON has moved by the end of an
        OPTION, and ``arrived`` when they last arrived. These are only ever pushed one way:
        towards "has moved" and "arrived later". That way is the one that forbids more, so the
        solver gains nothing by going further than the truth.
        """
        model, options = self.model, self.file.options
        person, takes = self.file.persons[number], self.takes[number]
        ends = len(options)  # the two ends of the path, as one point of the circuit
        nothing = model.new_bool_var(f"{person.id} takes part in nothing")
        arcs: list[tuple[int, int, cp_model.LiteralT]] = [(ends, ends, nothing)]
        follows: dict[tuple[int, int], cp_model.IntVar] = {}
        between: dict[tuple[int, int], _Taken] = {}
        start, asked = self._begins_at(person.id), self._has_to_end_at(person.id)
        moved = [model.new_bool_var(f"{person.id} moved by {o.id}") for o in options]
        arrived = [
            model.new_int_var(self.earliest, self.latest + self.room, f"{person.id} at {o.id}")
            for o in options
        ]
        for index, option in enumerate(options):
            model.add_implication(takes[index], nothing.negated())
            arcs.append((index, index, takes[index].negated()))
            first = model.new_bool_var(f"{person.id} starts with {option.id}")
            last = model.new_bool_var(f"{person.id} ends with {option.id}")
            follows[ends, index], follows[index, ends] = first, last
            arcs += [(ends, index, first), (index, ends, last)]
            done = None if self.endless[index] else self.start[index] + self.lasts[index]
            if self.moves[index]:
                _when(model.add(moved[index] == 1), takes[index])
                if done is not None:
                    _when(model.add(arrived[index] >= done), takes[index])
            if (number, index) in self.left_out:
                continue  # the PERSON does not take part in it, so they travel neither to it nor on
            between[ends, index] = self._sets_out(start, first, index, moved, arrived)
            between[index, ends] = []
            for there in asked:
                if done is not None:
                    between[index, ends] += self._ends_there(last, there, option.destination, done)
                elif option.destination != there:
                    # Nobody knows when the OPTION ends, so the PERSON never leaves it.
                    model.add(last == 0)
        if start is not None:
            # A PERSON who takes part in nothing stays where they start from, or travels on.
            between[ends, ends] = [
                taken for there in asked for taken in self._ends_there(nothing, there, start)
            ]

        for before, earlier in enumerate(options):
            for after, later in enumerate(options):
                if before == after or self.endless[before]:
                    continue
                if (number, before) in self.left_out or (number, after) in self.left_out:
                    continue
                name = f"{person.id}: {later.id} after {earlier.id}"
                if earlier.destination == later.origin:
                    next_ = self._goes_straight_on(name, before, after, moved, arrived)
                else:
                    taken = self._goes_by_ways(name, before, after, moved, arrived)
                    if taken is None:
                        continue
                    next_, between[before, after] = taken
                follows[before, after] = next_
                arcs.append((before, after, next_))
                _when(model.add(self.turn[after] >= self.turn[before] + 1), next_)
        model.add_circuit(arcs)
        self.nothing.append(nothing)
        self.follows.append(follows)
        self.routes.append(between)

    def _goes_straight_on(
        self,
        name: str,
        before: int,
        after: int,
        moved: Sequence[cp_model.IntVar],
        arrived: Sequence[cp_model.IntVar],
    ) -> cp_model.IntVar:
        """The choice that a PERSON does one OPTION right after another in the same PLACE."""
        model, margin = self.model, self.margins[after]
        next_ = model.new_bool_var(name)
        _when(model.add(self.start[after] >= self.start[before] + self.lasts[before]), next_)
        if not self.moves[after]:
            _when(model.add(moved[after] >= moved[before]), next_)
            _when(model.add(arrived[after] >= arrived[before]), next_)
        if margin is None:
            model.add_implication(next_, moved[before].negated())
        elif margin:
            _when(model.add(self.start[after] >= arrived[before] + margin), next_, moved[before])
        return next_

    def _goes_by_ways(
        self,
        name: str,
        before: int,
        after: int,
        moved: Sequence[cp_model.IntVar],
        arrived: Sequence[cp_model.IntVar],
    ) -> tuple[cp_model.IntVar, _Taken] | None:
        """The choice that a PERSON goes from one OPTION to the next by WAYs, and by which route.

        None when no route leads there, or when no PERSON who travels could be in time.
        """
        options = self.file.options
        here, there = options[before].destination, options[after].origin
        if not self._routes(here, there) or self.margins[after] is None:
            return None
        next_ = self.model.new_bool_var(name)
        free = self.start[before] + self.lasts[before]
        reached = self._travels(next_, here, there, free)
        return next_, self._arrives_for(after, reached, moved, arrived)

    def _sets_out(
        self,
        start: str | None,
        first: cp_model.IntVar,
        index: int,
        moved: Sequence[cp_model.IntVar],
        arrived: Sequence[cp_model.IntVar],
    ) -> _Taken:
        """The routes from where a PERSON's path begins to the OPTION they do first."""
        origin = self.file.options[index].origin
        if start is None or start == origin:
            return []
        if self.margins[index] is None:
            self.model.add(first == 0)  # no PERSON who travels there is known to be in time
            return []
        reached = self._travels(first, start, origin, None)
        return self._arrives_for(index, reached, moved, arrived)

    def _ends_there(
        self,
        taken: cp_model.IntVar,
        there: str,
        here: str,
        free: _Amount | None = None,
    ) -> _Taken:
        """The routes from where a PERSON is to where their path has to end.

        They take one while ``taken`` holds. The PERSON can leave after ``free``, or at any
        time where it is None.
        """
        if here == there:
            return []
        reached = self._travels(taken, here, there, free, last=True)
        return [(chosen, route) for chosen, route, _ in reached]

    def _arrives_for(
        self,
        after: int,
        reached: _Reached,
        moved: Sequence[cp_model.IntVar],
        arrived: Sequence[cp_model.IntVar],
    ) -> _Taken:
        """A PERSON who travels to an OPTION gets there its access cutoff before it starts."""
        model, margin = self.model, self.margins[after]
        for chosen, _, arrival in reached:
            if margin is None or arrival is None:
                raise AssertionError("no PERSON who travels there is known to be in time")
            _when(model.add(self.start[after] >= arrival + margin), chosen)
            if not self.moves[after]:
                _when(model.add(moved[after] == 1), chosen)
                _when(model.add(arrived[after] >= arrival), chosen)
        return [(chosen, route) for chosen, route, _ in reached]

    def _takes_the_ways(
        self, route: reference.Route, chosen: cp_model.IntVar, free: _Amount | None
    ) -> _Amount | None:
        """The WAYs of one route, taken one after another while ``chosen`` holds.

        ``free`` is when the PERSON can leave, or None where nothing holds them back. Returns
        when the last WAY ends, or None where it has no limit: then nobody knows.
        """
        model = self.model
        for place, (way, origin, destination) in enumerate(route):
            moment = model.new_int_var(self.earliest, self.latest, f"{chosen.name} leg {place}")
            if free is not None:
                _when(model.add(moment >= free), chosen)
            if way is None:
                self._outside_every_span(moment, origin, destination, chosen)
            lasts = self.way_lasts[way]
            self._keep_within_the_trip(moment, lasts, chosen)
            free = None if lasts is None else moment + lasts
        self.legs.append((chosen, len(route)))
        return free

    def _travels(
        self,
        taken: cp_model.IntVar,
        here: str,
        there: str,
        free: _Amount | None,
        last: bool = False,
    ) -> _Reached:
        """Travel by WAYs from one PLACE to another.

        While ``taken`` holds, the PERSON takes exactly one route from ``here`` to ``there``,
        after ``free``. Otherwise they take none. Where no route leads there, ``taken`` cannot
        hold. ``last`` says that the PERSON does nothing after it. Returns each route with the
        choice that takes it and the time it arrives.
        """
        model = self.model
        possible = self._routes(here, there, last)
        via = [taken]
        if len(possible) != 1:
            names = [f"{taken.name} by route {place}" for place in range(len(possible))]
            via = [model.new_bool_var(name) for name in names]
            model.add(sum(via) == taken)
        return [
            (chosen, route, self._takes_the_ways(route, chosen, free))
            for route, chosen in zip(possible, via, strict=True)
        ]

    def _begins_at(self, person: str) -> str | None:
        """Where a PERSON's path begins, where a FACT says so. None: wherever it suits."""
        stated = self.file.starts_from(person)
        return None if stated is None else stated.place

    def _has_to_end_at(self, person: str) -> list[str]:
        """Each PLACE where a PERSON's path has to end.

        A WANT can ask its holders to end the TRIP at a PLACE. No path ends at two PLACEs, so
        nothing works where two WANTs name different ones for a PERSON. A PERSON who does
        nothing, with no FACT about where they start from, is where they have to end.
        """
        wants = reference.has_to_end_at(self.file, person)
        asked = list(dict.fromkeys(want.ends_at or "" for want in wants))
        if len(asked) > 1:
            self.model.add_bool_or([])
        return asked

    def _keep_within_the_trip(
        self, begins: _Amount, lasts: int | None, happens: cp_model.IntVar
    ) -> None:
        """What happens starts no earlier than the TRIP starts and ends no later than it ends.

        ``lasts`` is None for something with no limit to how long it takes. That is never over
        in time, so it cannot happen where the TRIP has an end.
        """
        model, file = self.model, self.file
        opens, closes = file.trip_start(), file.trip_end()
        if opens is not None:
            _when(model.add(begins >= opens.at - self.zero), happens)
        if closes is not None:
            if lasts is None:
                model.add_bool_or([happens.negated()])
            else:
                _when(model.add(begins + lasts <= closes.at - self.zero), happens)

    def _routes(self, here: str, there: str, last: bool = False) -> list[reference.Route]:
        """The routes from one PLACE to another worth choosing between, worked out once.

        ``last`` says that the PERSON does nothing after the route. Where no COMPLETE FACT can
        rule a WAY out, only the time and the number of WAYs of a route matter, so the quickest
        of each length is enough.
        """
        if (here, there, last) not in self._worth_trying:
            possible = self.known.between(here, there, last)
            if not self.facts:
                possible = _quickest(self.world, possible)
            self._worth_trying[here, there, last] = possible
        return self._worth_trying[here, there, last]

    def any(self) -> _Choice | None:
        """Some choice of PERSONs and orders that works, or None when none does."""
        solver, status = self._solve(relax=False)
        if status == cp_model.INFEASIBLE:
            return None
        self.turned_out = frozenset(
            pair for pair, does in self.does.items() if solver.boolean_value(does)
        )
        return self._found(solver, status)

    def _solve(self, relax: bool = True) -> tuple[cp_model.CpSolver, object]:
        """The solver's answer for the model as it stands."""
        solver = _solver(relax)
        status = solver.solve(self.model)
        if status == cp_model.MODEL_INVALID:
            why = self.model.validate()
            if not why.startswith(_TOO_MANY_VALUES):
                raise AssertionError(f"the solver refused the model: {why}")
            raise DoesNotFit(why)
        return solver, status

    def _found(self, solver: cp_model.CpSolver, status: object) -> _Choice:
        """The choice of PERSONs and orders in the answer the solver gave."""
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            raise AssertionError("the solver stopped early")
        count = len(self.file.options)
        orders: list[tuple[int, ...]] = []
        by: _By = {}
        for number, follows in enumerate(self.follows):
            order: list[int] = []
            here = count
            while True:
                ahead = [
                    index
                    for index in range(count)
                    if (here, index) in follows and solver.boolean_value(follows[here, index])
                ]
                if not ahead:
                    break
                for chosen, route in self.routes[number].get((here, ahead[0]), ()):
                    if solver.boolean_value(chosen):
                        by[number, len(order) - 1] = route
                order.append(ahead[0])
                here = ahead[0]
            for chosen, route in self.routes[number].get((here, count), ()):
                if solver.boolean_value(chosen):
                    by[number, len(order) - 1] = route  # the route after the last OPTION
            orders.append(tuple(order))
        return self._who(orders), tuple(orders), by

    def first_in_file_order(self) -> _Choice | None:
        """The choice of PERSONs and orders that "Which ITINERARY is shown" puts first."""
        model, file = self.model, self.file
        count = len(file.options)
        ways_taken = sum(route * length for route, length in self.legs)
        taking_part = sum(each for row in self.takes for each in row) + ways_taken
        fewest = self._least(taking_part * (count + 1) + sum(self.used))
        if fewest is None:
            return None
        model.add(taking_part * (count + 1) + sum(self.used) == fewest)
        self._settle(self.used)

        # Each PERSON in turn: the OPTION listed first that can come next, or nothing more.
        ends = count  # the two ends of a path, as one point of its circuit
        orders: list[tuple[int, ...]] = []
        for number in range(len(file.persons)):
            follows = self.follows[number]
            order: list[int] = []
            here = ends
            while True:
                stop = self.nothing[number] if here == ends else follows[here, ends]
                ahead = {
                    index: follows[here, index]
                    for index in range(count)
                    if index not in order and (here, index) in follows
                }
                found = self._least(sum(index * arc for index, arc in ahead.items()) - stop)
                if found is None or found not in (-1, *ahead):
                    raise AssertionError("a path the solver accepted has no next OPTION")
                if found == -1:
                    model.add(stop == 1)
                    break
                model.add(ahead[found] == 1)
                order.append(found)
                here = found
            orders.append(tuple(order))
        return self._who(orders), tuple(orders), None

    def _who(self, orders: Sequence[tuple[int, ...]]) -> tuple[tuple[str, ...], ...]:
        """The PERSONs in each OPTION, given the OPTIONs each PERSON does."""
        return tuple(
            tuple(
                person.id
                for number, person in enumerate(self.file.persons)
                if index in orders[number]
            )
            for index in range(len(self.file.options))
        )

    def _outside_every_span(
        self, moment: cp_model.IntVar, origin: str, destination: str, when: cp_model.IntVar
    ) -> None:
        """An unlisted WAY taken under ``when`` starts outside the span of each COMPLETE FACT.

        Only the FACTs about travel straight between these two PLACEs count.
        """
        model = self.model
        for fact in self.facts:
            if not fact.covers(origin, destination):
                continue
            sooner = model.new_bool_var(f"{moment.name} starts before the span of {fact.id}")
            _when(model.add(moment <= fact.earliest - 1 - self.zero), when, sooner)
            _when(model.add(moment >= fact.latest + 1 - self.zero), when, sooner.negated())

    def _settle(self, choices: Sequence[cp_model.IntVar]) -> None:
        """Fix these yes-or-no choices: "yes" wherever it can be, the earlier choices first."""
        for begin in range(0, len(choices), _MOST_AT_ONCE):
            some = choices[begin : begin + _MOST_AT_ONCE]
            weighed = sum(each * 2 ** (len(some) - 1 - place) for place, each in enumerate(some))
            most = self._least(-weighed)
            if most is None:
                raise AssertionError("a model that had an answer has none now")
            for place, each in enumerate(some):
                self.model.add(each == (-most >> (len(some) - 1 - place)) & 1)

    def _least(self, amount: cp_model.LinearExprT) -> int | None:
        """The least value this amount can take, or None when the model has no answer."""
        self.model.minimize(amount)
        solver, status = self._solve()
        self.model.clear_objective()
        if status == cp_model.INFEASIBLE:
            return None
        if status != cp_model.OPTIMAL:
            raise AssertionError(f"the solver stopped early: {solver.status_name(status)}")
        return solver.value(amount)
