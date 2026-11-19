"""The COMPILER: the answers of spec/rules.md, found with a solver.

The reference checker tries every choice of PERSONs and orders. This module asks CP-SAT for the
choice instead. It then hands that choice to the reference checker's own functions, which time it
and check it against the CONSTRAINTs. So whenever this module says that something works, the
rules as the reference checker applies them have agreed.

Only the search is different. The three answers, ROBUST and the evidence are worked out by
``answers.check``, with this module's search in place of the reference checker's.

For INFEASIBLE, the solver also names the FACTs and DECISIONs its proof used. The reference
checker then looks for the conflict among those alone.

The solver counts in 64-bit numbers. A TRIP with very long durations and very many routes can
need more than that. The reference checker's own search then answers for the whole TRIP. That
search tries everything, so it is meant for small TRIPs.
"""

from collections.abc import Sequence
from dataclasses import replace
from itertools import combinations
from math import inf

from ortools.sat.python import cp_model

from agloe import answers, reference
from agloe.answers import Report
from agloe.file import (
    Booking,
    Complete,
    Cutoff,
    Duration,
    File,
    NeedsRight,
    Offer,
    Start,
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
type _Amount = cp_model.LinearExpr | int  # seconds: a plain number, or one the solver works out
type _End = tuple[str, list[cp_model.IntVar]]  # a PLACE, and the records that make it hold
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
        return answers.check(file, shown=shown, works=works, stuck=stuck)
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


def stuck(remaining: Remaining) -> frozenset[str] | None:
    """FACTs, WANTs and DECISIONs that rule out every ITINERARY by themselves, or None.

    The question is asked in the best case of what is left of a FILE. The set returned is small:
    no record can be taken out of it. It need not be the conflict the report names, which is
    found in the FILE's order. This search goes the other way, from the last record to the
    first. That takes the DECISIONs out before the FACTs, and with fewer LOCKs to honor each
    proof is quick.

    Where something works, the solver has chosen a plan and a possible world for it: which
    OPTIONs SATISFY which WANTs, where nobody knows. The reference checker then checks that
    plan in that world.
    """
    file = remaining.file
    world = reference.best_case(file)
    search = _Search(file, world, remaining)
    records = [record.id for record in (*file.facts, *file.wants, *file.decisions)]
    choice, needed = search.clash(records)
    if choice is not None:
        does = search.turned_out
        rights = world.rights | remaining.might_cover()
        chosen = replace(world, satisfies=does, might_satisfy=does, rights=rights)
        _checked(file, chosen, choice)
        return None
    while True:  # ask again with only the records the proof used, until it uses them all
        choice, fewer = search.clash([record for record in records if record in needed])
        if choice is not None:
            raise AssertionError("records the solver's proof used do not rule out every choice")
        if fewer == needed:
            break
        needed = fewer
    kept = [record for record in records if record in needed]
    for record in reversed(list(kept)):
        if record in needed:
            choice, fewer = search.clash([other for other in kept if other != record])
            if choice is not None:
                continue
            needed = fewer
        kept.remove(record)
    return frozenset(kept)


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


def _solver() -> cp_model.CpSolver:
    """A solver set up to give the same result every time.

    Its simplification step is switched off. In OR-Tools 9.15 that step reported that nothing
    works for a model that had an answer. A wrong "nothing works" is the one mistake nothing
    else here would catch, since a choice the solver finds is always checked by the rules.
    """
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 1
    solver.parameters.cp_model_presolve = False
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

    Each PERSON's OPTIONs form a path. The path is a circuit through a starting point that stands
    for "before the first OPTION and after the last". Where the next OPTION starts somewhere
    else, WAYs take the PERSON there, by one of the routes the world has. Start times
    exist in the model only to prove that some timing fits; the times shown come from the
    reference checker.
    """

    def __init__(self, file: File, world: World, remaining: Remaining | None = None) -> None:
        """Build the model. With ``remaining``, each record applies only if switched on.

        That is for the search for a conflict. ``remaining`` is what is left of the FILE, and
        the world must be its best case. A FACT that is switched off is unknown, and turns out
        as in the best case. So does what a FACT stated that was taken out before: whether an
        OPTION SATISFIES a WANT, and whom a BOOKING covers.
        """
        self.file, self.world = file, world
        self.unsaid = frozenset[tuple[str, str]]() if remaining is None else remaining.unsaid
        self.open_to_all = frozenset[str]() if remaining is None else remaining.open_to_all
        # Whether each OPTION SATISFIES each WANT, where the solver chooses the world too, and
        # how that turned out in the last answer it gave.
        self.does: dict[tuple[str, str], cp_model.IntVar] = {}
        self.turned_out: frozenset[tuple[str, str]] = frozenset()
        self.model = cp_model.CpModel()
        self.switch: dict[str, cp_model.IntVar] = {}
        if remaining is not None:
            for record in (*file.facts, *file.wants, *file.decisions):
                self.switch[record.id] = self.model.new_bool_var(f"given {record.id}")
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
        """What the world says about each OPTION and WAY.

        How long each one takes and how early a PERSON must arrive are plain numbers, or numbers
        that count only when their FACT is switched on.
        """
        file, world = self.file, self.world
        self.terms = [world.terms[option.id] for option in file.options]
        self.usable = [each.fixed_start is not None or each.free_start for each in self.terms]
        self.endless = [each.longest is None for each in self.terms]
        self.moves = [option.origin != option.destination for option in file.options]

        def switch_of(record: Start | Duration | Cutoff | None) -> cp_model.IntVar | None:
            return None if record is None else self.switch.get(record.id)

        self.lasts: list[_Amount] = []
        self.margins: list[_Amount | None] = []
        for option, each in zip(file.options, self.terms, strict=True):
            given = switch_of(file.duration(option.id))
            self.lasts.append(each.shortest if given is None else each.shortest * given)
            given = switch_of(file.cutoff(option.id))
            margin = each.margin if given is None or not each.margin else each.margin * given
            self.margins.append(margin)
        self.when_fixed = [switch_of(file.start(option.id)) for option in file.options]
        # How long each WAY takes. None: there is no limit, and nobody knows when it ends.
        self.way_lasts: dict[str | None, _Amount | None] = {None: world.unlisted_takes}
        for way in file.ways:
            given = switch_of(file.duration(way.id))
            shortest, longest = world.takes[way.id]
            lasts = shortest if given is None else shortest * given
            self.way_lasts[way.id] = None if longest is None else lasts
        unlisted = world.unlisted is None or bool(world.unlisted)
        self.facts = [fact for fact in file.facts if isinstance(fact, Complete)] if unlisted else []
        self.given = [self.switch.get(fact.id) for fact in self.facts]

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

        known = [
            each.fixed_start if given is None else None
            for each, given in zip(terms, self.when_fixed, strict=True)
        ]
        self.start = [
            model.new_int_var(self.earliest, self.latest, f"start {option.id}")
            if moment is None
            else model.new_constant(moment - self.zero)
            for option, moment in zip(options, known, strict=True)
        ]
        for index, (each, given) in enumerate(zip(terms, self.when_fixed, strict=True)):
            if given is not None and each.fixed_start is not None:
                _when(model.add(self.start[index] == each.fixed_start - self.zero), given)
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
                asking = [
                    self.switch.get(lock.id)
                    for lock in file.locks
                    if lock.option == option.id and person.id in lock.persons
                ]
                for given in asking:
                    if given is None:
                        model.add(takes == 1)
                    else:
                        _when(model.add(takes == 1), given)
                # A PERSON gains nothing by staying somewhere unless a LOCK asks them to, or
                # the stay could meet a must of theirs. Without the stay they are in the same
                # PLACE at the same times, and every CONSTRAINT is as easy to meet or easier.
                # So the model leaves such stays out.
                wanted = index in meets[number]
                if not self.usable[index] or (not self.moves[index] and not asking and not wanted):
                    self._rule_out(number, index)
                elif not self.moves[index] and not wanted:
                    switches = [each for each in asking if each is not None]
                    if len(switches) == len(asking):
                        model.add_bool_or([takes.negated(), *switches])
        self._hold_to_the_rights()

    def _rule_out(self, number: int, index: int) -> None:
        """This PERSON takes no part in this OPTION, whatever else is chosen.

        So no travel is built for them to it or from it. An OPTION that is only ruled out while
        some record is switched on does not come here.
        """
        self.model.add(self.takes[number][index] == 0)
        self.left_out.add((number, index))

    def _hold_to_the_rights(self) -> None:
        """Nobody takes part without a right in an OPTION that needs one.

        Where records can be switched off, the best case decides, and it has a right for a
        PERSON unless the FILE rules that out. That takes three kinds of FACT, all switched on:
        that the OPTION needs a right, that the rights to it are COMPLETE, and every BOOKING
        and OFFER for it. A BOOKING or an OFFER that is off, or was taken out before, might
        have a right for anybody. So a PERSON whom some BOOKING for the OPTION covers is never
        kept out, and the others are kept to the places on OFFER.
        """
        file, world = self.file, self.world
        people = list(enumerate(file.persons))
        if not self.switch:
            for index, option in enumerate(file.options):
                if option.id in world.needs_right:
                    without = [
                        n for n, person in people if (option.id, person.id) not in world.rights
                    ]
                    self._share_out(index, without)
            return
        needs = {fact.option: fact for fact in file.facts if isinstance(fact, NeedsRight)}
        for index, option in enumerate(file.options):
            needed, whole = needs.get(option.id), file.rights_complete(option.id)
            if needed is None or not needed.needed or whole is None:
                continue
            if option.id in self.open_to_all:
                continue
            listed = [
                self.switch[fact.id]
                for fact in file.facts
                if isinstance(fact, Booking | Offer) and fact.option == option.id
            ]
            closed = [self.switch[needed.id], self.switch[whole.id], *listed]
            without = [n for n, person in people if file.booking(option.id, person.id) is None]
            self._share_out(index, without, closed)

    def _share_out(
        self, index: int, without: Sequence[int], given: Sequence[cp_model.IntVar] = ()
    ) -> None:
        """Each of these PERSONs who takes part in an OPTION takes a place they can pay for.

        They are the PERSONs with no right of their own to it. No place is taken twice.
        ``given`` holds the records that all have to be switched on for this to hold.

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
            if not able[number] and given:
                _when(model.add(self.takes[number][index] == 0), *given)
            elif not able[number]:
                self._rule_out(number, index)
        buyers = [number for number in without if able[number]]
        wanted = {offer.id for number in buyers for offer in able[number]}
        offers = [offer for offer in self.file.offers(option.id) if offer.id in wanted]
        places = sum(offer.places for offer in offers)
        if all(len(able[number]) == len(offers) for number in buyers):
            if places < len(buyers):
                limit = model.add(sum(self.takes[number][index] for number in buyers) <= places)
                if given:
                    _when(limit, *given)
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
            has_a_place = model.add(sum(picks) >= takes)
            if given:
                _when(has_a_place, *given)
        for offer in offers:
            if len(taken[offer.id]) > offer.places:
                model.add(sum(taken[offer.id]) <= offer.places)

    def _hold_to_the_wants(self) -> list[set[int]]:
        """Every must is met and every must-not is kept. Returns what could meet a must.

        That is, for each PERSON, the OPTIONs that could meet a must of theirs.
        """
        if self.switch:
            return self._hold_to_the_wants_with_switches()
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
            for number, person in enumerate(file.persons):
                elsewhere = (want.id, person.id) in world.another_option
                if person.id in want.musts and not elsewhere:
                    meets[number].update(would)
                    model.add_bool_or([self.takes[number][index] for index in would])
        return meets

    def _delivered(self) -> list[Want]:
        """The WANTs about something an OPTION can deliver. The path settles the others."""
        return [want for want in self.file.wants if want.ends_at is None]

    def _hold_to_the_wants_with_switches(self) -> list[set[int]]:
        """The same where each FACT and WANT applies only if switched on, in the best case.

        A FACT that is switched off is unknown. So whether an OPTION SATISFIES a WANT is the
        solver's to choose here: it picks the possible world as well as the plan. A FACT about
        the two settles it while that FACT is switched on. So does a FACT that the WANT's set is
        COMPLETE, for an OPTION that never had a FACT about the WANT: it does not SATISFY it.

        A must needs an OPTION of the FILE only while a FACT says that the WANT's set is
        COMPLETE. Otherwise another OPTION meets it.
        """
        model, file = self.model, self.file
        meets: list[set[int]] = [set() for _ in file.persons]
        for want in self._delivered():
            asked = self.switch[want.id]
            whole = file.complete_for(want.id)
            closed = None if whole is None else self.switch[whole.id]
            does: list[cp_model.IntVar] = []
            for option in file.options:
                satisfies = model.new_bool_var(f"{option.id} satisfies {want.id}")
                does.append(satisfies)
                self.does[option.id, want.id] = satisfies
                stated = file.satisfies(option.id, want.id)
                if stated is not None:
                    turns_out = 1 if stated.degree > 0 else 0
                    _when(model.add(satisfies == turns_out), self.switch[stated.id])
                elif closed is not None and (option.id, want.id) not in self.unsaid:
                    _when(model.add(satisfies == 0), closed)
            for number, person in enumerate(file.persons):
                takes = self.takes[number]
                if person.id in want.must_nots:
                    for index, satisfies in enumerate(does):
                        model.add_bool_or(
                            [asked.negated(), takes[index].negated(), satisfies.negated()]
                        )
                if person.id in want.musts and closed is not None:
                    meets[number].update(range(len(file.options)))
                    met: list[cp_model.IntVar] = []
                    for index, satisfies in enumerate(does):
                        here = model.new_bool_var(f"{person.id} gets {want.id} by {index}")
                        model.add_implication(here, takes[index])
                        model.add_implication(here, satisfies)
                        met.append(here)
                    model.add_bool_or([asked.negated(), closed.negated(), *met])
        return meets

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
                elif option.destination != there[0]:
                    # Nobody knows when the OPTION ends, so the PERSON never leaves it.
                    self._never(last, there[1])
        if start is not None:
            # A PERSON who takes part in nothing stays where they start from, or travels on.
            between[ends, ends] = [
                taken
                for there in asked
                for taken in self._ends_there(nothing, there, start[0], given=start[1])
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
        elif not (isinstance(margin, int) and margin == 0):
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
        reached = self._travels(next_, (), here, there, free)
        return next_, self._arrives_for(after, reached, moved, arrived)

    def _sets_out(
        self,
        start: _End | None,
        first: cp_model.IntVar,
        index: int,
        moved: Sequence[cp_model.IntVar],
        arrived: Sequence[cp_model.IntVar],
    ) -> _Taken:
        """The routes from where a PERSON's path begins to the OPTION they do first."""
        origin = self.file.options[index].origin
        if start is None or start[0] == origin:
            return []
        here, given = start
        if self.margins[index] is None:
            self._never(first, given)  # no PERSON who travels there is known to be in time
            return []
        reached = self._travels(first, given, here, origin, None)
        return self._arrives_for(index, reached, moved, arrived)

    def _ends_there(
        self,
        taken: cp_model.IntVar,
        end: _End,
        here: str,
        free: _Amount | None = None,
        given: Sequence[cp_model.IntVar] = (),
    ) -> _Taken:
        """The routes from where a PERSON is to where their path has to end.

        They take one while ``taken`` holds, with everything in ``given`` and the records that
        ask for that end. The PERSON can leave after ``free``, or at any time where it is None.
        """
        there, asked = end
        if here == there:
            return []
        reached = self._travels(taken, [*given, *asked], here, there, free, last=True)
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
        given: Sequence[cp_model.IntVar],
        here: str,
        there: str,
        free: _Amount | None,
        last: bool = False,
    ) -> _Reached:
        """Travel by WAYs from one PLACE to another.

        While ``taken`` and everything in ``given`` hold, the PERSON takes exactly one route
        from ``here`` to ``there``, after ``free``. Otherwise they take none. Where no route
        leads there, the two cannot hold together. ``last`` says that the PERSON does nothing
        after it. Returns each route with the choice that takes it and the time it arrives.
        """
        model = self.model
        needed = self._both(taken, given)
        possible = self._routes(here, there, last)
        via = [needed]
        if len(possible) != 1:
            names = [f"{taken.name} by route {place}" for place in range(len(possible))]
            via = [model.new_bool_var(name) for name in names]
            model.add(sum(via) == needed)
        return [
            (chosen, route, self._takes_the_ways(route, chosen, free))
            for route, chosen in zip(possible, via, strict=True)
        ]

    def _both(self, taken: cp_model.IntVar, given: Sequence[cp_model.IntVar]) -> cp_model.IntVar:
        """A choice that holds exactly when ``taken`` and everything in ``given`` hold."""
        if not given:
            return taken
        needed = self.model.new_bool_var(f"{taken.name}, as given")
        self.model.add_min_equality(needed, [taken, *given])
        return needed

    def _never(self, taken: cp_model.IntVar, given: Sequence[cp_model.IntVar]) -> None:
        """``taken`` and everything in ``given`` cannot hold together."""
        self.model.add_bool_or([each.negated() for each in (taken, *given)])

    def _given(self, record: str) -> list[cp_model.IntVar]:
        """The switch of a record, where records can be switched off. Else nothing."""
        return [self.switch[record]] if record in self.switch else []

    def _begins_at(self, person: str) -> _End | None:
        """Where a PERSON's path begins, where a FACT says so. None: wherever it suits."""
        stated = self.file.starts_from(person)
        return None if stated is None else (stated.place, self._given(stated.id))

    def _has_to_end_at(self, person: str) -> list[_End]:
        """Each PLACE where a PERSON's path has to end, with the records that ask for it.

        A WANT can ask its holders to end the TRIP at a PLACE. It asks while it is given, and a
        PLACE is asked for while any WANT that names it is. No path ends at two PLACEs. A PERSON
        who does nothing, with no FACT about where they start from, is where they have to end.
        """
        model = self.model
        naming: dict[str, list[cp_model.IntVar]] = {}
        for want in reference.has_to_end_at(self.file, person):
            naming.setdefault(want.ends_at or "", []).extend(self._given(want.id))
        asked: list[_End] = []
        for place, given in naming.items():
            if len(given) > 1:
                given = [model.new_bool_var(f"{person} has to end at {place}")]
                model.add_max_equality(given[0], naming[place])
            asked.append((place, given))
        for (_, one), (_, other) in combinations(asked, 2):
            model.add_bool_or([each.negated() for each in (*one, *other)])
        return asked

    def _keep_within_the_trip(
        self, begins: _Amount, lasts: _Amount | None, happens: cp_model.IntVar
    ) -> None:
        """What happens starts no earlier than the TRIP starts and ends no later than it ends.

        ``lasts`` is None for something with no limit to how long it takes. That is never over
        in time, so it cannot happen where the TRIP has an end. Each limit applies only while
        its DECISION is given.
        """
        model, file = self.model, self.file
        opens, closes = file.trip_start(), file.trip_end()
        if opens is not None:
            given = self.switch.get(opens.id)
            when = [happens] if given is None else [happens, given]
            _when(model.add(begins >= opens.at - self.zero), *when)
        if closes is not None:
            given = self.switch.get(closes.id)
            when = [happens] if given is None else [happens, given]
            if lasts is None:
                model.add_bool_or([each.negated() for each in when])
            else:
                _when(model.add(begins + lasts <= closes.at - self.zero), *when)

    def _routes(self, here: str, there: str, last: bool = False) -> list[reference.Route]:
        """The routes from one PLACE to another worth choosing between, worked out once.

        ``last`` says that the PERSON does nothing after the route. Where no COMPLETE FACT can
        rule a WAY out and no FACT can be switched off, only the time and the number of WAYs of
        a route matter, so the quickest of each length is enough.
        """
        if (here, there, last) not in self._worth_trying:
            possible = self.known.between(here, there, last)
            if not self.facts and not self.switch:
                possible = _quickest(self.world, possible)
            self._worth_trying[here, there, last] = possible
        return self._worth_trying[here, there, last]

    def clash(self, given: Sequence[str]) -> tuple[_Choice | None, frozenset[str]]:
        """A choice that works with only these FACTs and DECISIONs, or the ones that rule one out.

        Every other record is switched off. The records returned are those of ``given`` that the
        solver's proof needed. They rule out every choice by themselves: a record that is
        switched on never makes a TRIP easier. There may be fewer that would do.
        """
        names = {switch.index: record for record, switch in self.switch.items()}
        self.model.add_assumptions(
            [
                switch if record in given else switch.negated()
                for record, switch in self.switch.items()
            ]
        )
        solver, status = self._solve()
        self.model.clear_assumptions()
        if status != cp_model.INFEASIBLE:
            choice = self._found(solver, status)
            self.turned_out = frozenset(
                pair for pair, satisfies in self.does.items() if solver.boolean_value(satisfies)
            )
            return choice, frozenset()
        needed = frozenset(
            names[index]
            for index in solver.sufficient_assumptions_for_infeasibility()
            if index in names
        )
        if not needed:
            raise AssertionError("the solver ruled out every choice without using any record")
        return None, needed

    def any(self) -> _Choice | None:
        """Some choice of PERSONs and orders that works, or None when none does."""
        solver, status = self._solve()
        if status == cp_model.INFEASIBLE:
            return None
        return self._found(solver, status)

    def _solve(self) -> tuple[cp_model.CpSolver, object]:
        """The solver's answer for the model as it stands."""
        solver = _solver()
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

        Only the FACTs about travel straight between these two PLACEs count, and only those that
        are given.
        """
        model = self.model
        for fact, given in zip(self.facts, self.given, strict=True):
            if not fact.covers(origin, destination):
                continue
            applies = [when] if given is None else [when, given]
            sooner = model.new_bool_var(f"{moment.name} starts before the span of {fact.id}")
            _when(model.add(moment <= fact.earliest - 1 - self.zero), *applies, sooner)
            _when(model.add(moment >= fact.latest + 1 - self.zero), *applies, sooner.negated())

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
