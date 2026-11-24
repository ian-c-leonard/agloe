"""The COMPILER: the answers of spec/rules.md, found with a solver.

The reference checker tries every choice of PERSONs and orders. This module asks CP-SAT for the
choice instead. It then hands that choice to the reference checker's own functions, which time it
and check it against the CONSTRAINTs. So whenever this module says that something works, the
rules as the reference checker applies them have agreed.

Only the search is different. The three answers, ROBUST and the evidence are worked out by
``answers.check``, with this module's search in place of the reference checker's.

For INFEASIBLE, the search for the conflict asks whether anything can still work once records
are taken out. Each such question takes one model at most. Where taking FACTs out leaves it
open whether an OPTION SATISFIES a WANT, the solver chooses that too. Where LOCKs put a PERSON
into two OPTIONs at once, no model is needed.

The solver counts in 64-bit numbers. A TRIP with very long durations and very many routes can
need more than that, and so can very many purchases at very high prices beside a cap. The
reference checker's own search then answers for the whole TRIP. That search tries everything,
so it is meant for small TRIPs.
"""

from collections.abc import Iterable, Iterator, Mapping, Sequence, Set
from dataclasses import replace
from hashlib import sha256
from heapq import heappop, heappush
from itertools import combinations
from math import inf

from ortools.sat.python import cp_model

from agloe import answers, reference
from agloe.answers import Answer, Report
from agloe.file import (
    Complete,
    File,
    StartsFrom,
    Want,
)
from agloe.reference import Itinerary, Remaining, Where, World

_MOST_AT_ONCE = 60  # yes-or-no choices ranked in one solve: their weights must fit in 64 bits
_FURTHEST = 2**62  # a time further than this from the first fixed time does not fit in 64 bits
# How CP-SAT starts when it refuses a model because its variables can take too many values.
_TOO_MANY_VALUES = "The sum of all variable domains do not fit on an int64_t"

type _Who = tuple[tuple[str, ...], ...]  # the PERSONs in each OPTION
type _Orders = tuple[tuple[int, ...], ...]  # the OPTIONs each PERSON does, in order
type _By = dict[tuple[int, int], reference.Route]  # the WAYs a PERSON takes after an OPTION
# When a PERSON starts an unlisted WAY of those routes that a COMPLETE FACT could rule out, by
# the place of the WAY in its route.
type _Falls = dict[tuple[int, int, int], int]
# The OPTIONs that happen, in the order the solver has them happen: by start, then by turn.
type _InOrder = tuple[int, ...]
type _Empty = frozenset[int]  # the OPTIONs that happen with nobody in them
type _Choice = tuple[_Who, _Orders, _By | None, _Falls | None, _InOrder | None, _Empty]
# What the solver answered for each model it was asked about, by the digest of the model.
type _Asked = dict[bytes, tuple[cp_model.CpSolver, object]]
type _Amount = cp_model.LinearExpr | int  # seconds: a plain number, or one the solver works out
type _Taken = list[tuple[cp_model.IntVar, reference.Route]]  # routes, each with its choice
# The same with the time each route arrives. None: nobody knows, and nothing follows it.
type _Reached = list[tuple[cp_model.IntVar, reference.Route, _Amount | None]]


class DoesNotFit(Exception):
    """The numbers of a TRIP's model do not fit in the 64 bits the solver counts with."""


def check(file: File) -> Report:
    """The answer for this TRIP, with its evidence. The same Report as the reference checker's."""
    *_, report = reports(file, ahead=False)
    if not isinstance(report, Report):
        raise AssertionError("a check ended with no Report")
    return report


def reports(file: File, ahead: bool = True) -> Iterator[Answer | Report]:
    """The answer as soon as it is proved, and then the Report that ``check`` gives.

    The series is the reference checker's: ``answers.reports`` says when each answer is
    proved, and what ``ahead`` is for.

    Where the numbers of a FILE do not fit the solver, the reference checker starts over. Both
    are exact, so its answer is the one the solver proved. What was given before is not given
    again.
    """
    given: list[Answer | Report] = []
    try:
        asked: _Asked = {}
        for report in answers.reports(
            file,
            shown,
            lambda left, world: works(left, world, asked),
            lambda left: can_work(left, asked),
            ahead,
        ):
            given.append(report)
            yield report
    except DoesNotFit:
        rest = answers.reports(file, ahead=ahead)
        for said in given:
            if next(rest) != said:
                raise AssertionError("the solver proved an answer that the rules refuse") from None
        yield from rest


def shown(file: File, world: World) -> Itinerary | None:
    """The ITINERARY that "Which ITINERARY is shown" puts first in this world, or None."""
    world = _with_the_ways_that_can_start(file, world)
    if reference.passed_by_the_bookings(file, world):
        return None
    if _locked_twice_at_once(file, world) or _has_to_take_two_apart(file, world):
        return None
    search = _Search(file, world)
    choice = search.first_in_file_order()
    return None if choice is None else _checked(file, world, choice, search.known)


def works(file: File, world: World, asked: _Asked | None = None) -> bool:
    """Whether any ITINERARY works in this world. ``asked`` is as for ``can_work``."""
    world = _with_the_ways_that_can_start(file, world)
    if reference.passed_by_the_bookings(file, world):
        return False
    if _locked_twice_at_once(file, world) or _has_to_take_two_apart(file, world):
        return False
    choice = _plan(_Search(file, world, plain=True), asked)
    if choice is not None:
        _checked(file, world, choice, any_will_do=True)
    return choice is not None


def can_work(remaining: Remaining, asked: _Asked | None = None) -> bool:
    """Whether any ITINERARY works in some best case of what is left of a FILE.

    The best cases differ only in the pairs that are left open: whether an OPTION SATISFIES a
    WANT that is a must for one PERSON and a must-not for another. The solver chooses that
    for each pair, with the plan. So one question takes one model at most, however many
    pairs are open. The reference checker then checks the plan in the best case the solver
    chose.

    ``asked`` holds what the solver answered for each model it was given before in the same
    check. A FACT that is taken out often changes nothing in the model: it said what the best
    case takes anyway. The same model has the same answer, so the solver is asked once. The
    plan is read from that answer for what is left this time, and checked against it.

    """
    file = remaining.file
    world, open_pairs = reference.best_case_left(remaining)
    world = _with_the_ways_that_can_start(file, world)
    if reference.passed_by_the_bookings(file, world):
        return False
    if _locked_twice_at_once(file, world) or _has_to_take_two_apart(file, world, open_pairs):
        return False
    search = _Search(file, world, open_pairs, plain=True)
    choice = _plan(search, asked)
    if choice is None:
        return False
    does = search.turned_out
    chosen = replace(
        world, satisfies=world.satisfies | does, might_satisfy=world.might_satisfy | does
    )
    _checked(file, chosen, choice, any_will_do=True)
    return True


def _with_the_ways_that_can_start(file: File, world: World) -> World:
    """This world with no unlisted WAY, where none of them can ever be taken.

    Every WAY starts within the TRIP: no earlier than the TRIP starts, and no later than it
    ends. Where one FACT says that the ways between all PLACEs are COMPLETE, for a span that
    holds the whole TRIP, no unlisted WAY can start at any time a WAY can start. So the same
    ITINERARIES work with no unlisted WAY in the world, and they are the only ones. The model
    is much smaller without the routes that nobody can take.

    This needs both times of the TRIP and the FACT in the FILE as it is asked about. A FILE
    with one of them taken out is left as it is.
    """
    if world.unlisted is not None and not world.unlisted:
        return world
    opens, closes = file.trip_start(), file.trip_end()
    if opens is None or closes is None:
        return world
    whole = any(
        isinstance(fact, Complete)
        and fact.origin is None
        and fact.destination is None
        and fact.earliest <= opens.at
        and closes.at <= fact.latest
        for fact in file.facts
    )
    return replace(world, unlisted=frozenset()) if whole else world


def _locked_twice_at_once(file: File, world: World) -> bool:
    """Whether LOCKs put some PERSON into two OPTIONs whose times rule each other out.

    A PERSON does one OPTION after another, so the later one starts no earlier than the
    first one ends. Two OPTIONs that both start at fixed times in this world can be done in
    an order only where that holds for it, and nothing follows an OPTION with no known end.
    Where neither order holds, no ITINERARY that works in this world has the PERSON in both,
    and the LOCKs ask for both. So nothing works, and no model is needed to see it.

    Several LOCKs can name one OPTION for a PERSON. That is one OPTION, taken once.
    """
    locked: dict[str, dict[str, reference.Terms]] = {}
    for lock in file.locks:
        terms = world.terms[lock.option]
        if terms.fixed_start is not None:
            for person in lock.persons:
                locked.setdefault(person, {})[lock.option] = terms

    def follows(first: reference.Terms, then: reference.Terms) -> bool:
        if first.fixed_start is None or then.fixed_start is None or first.longest is None:
            return False
        return then.fixed_start >= first.fixed_start + first.shortest

    return any(
        not follows(one, other) and not follows(other, one)
        for theirs in locked.values()
        for one, other in combinations(theirs.values(), 2)
    )


def _has_to_take_two_apart(
    file: File, world: World, open_pairs: Sequence[tuple[str, str]] = ()
) -> bool:
    """Whether some PERSON has to take part in two OPTIONs that nobody can take part in both.

    ``reference.NoTimeBetween`` says which two OPTIONs those are in this world: both start at
    fixed times, and neither leaves the time to do the other after it. ``_have_to_take`` says
    which OPTIONs a PERSON has to take part in.

    Where a PERSON has to take part in two such OPTIONs, nothing works in this world, and no
    model is needed to see it.
    """
    have_to = _have_to_take(file, world, open_pairs)
    if all(len(theirs) < 2 for theirs in have_to.values()):
        return False
    no_time = reference.NoTimeBetween(file, world)
    return any(
        no_time.apart(one, other)
        for theirs in have_to.values()
        for one, other in combinations(sorted(theirs), 2)
    )


def _have_to_take(
    file: File, world: World, open_pairs: Iterable[tuple[str, str]] = ()
) -> dict[str, set[int]]:
    """The OPTIONs each PERSON has to take part in, in every ITINERARY that works in this world.

    They are given by position in the FILE. A PERSON has to take part in an OPTION that a
    LOCK names them in. They also have to take part in the one OPTION that can meet a must of
    theirs, where only one can: one that SATISFIES the WANT in this world, or one of the
    ``open_pairs``, which may. That holds unless this world has another OPTION for the WANT
    and the PERSON. A WANT to end the TRIP at a PLACE asks for no OPTION.

    An OPTION that somebody has to take part in happens. Where it requires a CAPABILITY of one
    PERSON, and one PERSON alone has it in this world, that PERSON has to take part in it too.

    A PERSON can have to take part in more than these. Nothing here says that they do not.
    """
    position = {option.id: index for index, option in enumerate(file.options)}
    have_to: dict[str, set[int]] = {}
    for lock in file.locks:
        for person in lock.persons:
            have_to.setdefault(person, set()).add(position[lock.option])
    might = world.satisfies | frozenset(open_pairs)
    for want in file.wants:
        if want.ends_at is not None or not want.musts:
            continue
        able = [index for option, index in position.items() if (option, want.id) in might]
        if len(able) == 1:
            for person in want.musts:
                if (want.id, person) not in world.another_option:
                    have_to.setdefault(person, set()).add(able[0])
    happening = {index for theirs in have_to.values() for index in theirs}
    for (option, capability), of in world.requires.items():
        if of == "one" and position[option] in happening:
            has = [person.id for person in file.persons if (person.id, capability) in world.has]
            if len(has) == 1:
                have_to.setdefault(has[0], set()).add(position[option])
    return have_to


def _plan(search: _Search, asked: _Asked | None) -> _Choice | None:
    """A choice that works in the model of this search, or None where none does.

    Where ``asked`` already holds the solver's answer for a model with the same text, the
    choice is read from that answer. It is read through this search: two FILEs can give
    models with the same text and still take different WAYs between the same PLACEs.
    """
    if asked is None:
        return search.any()
    key = sha256(str(search.model.proto).encode()).digest()
    if key not in asked:
        asked[key] = search.ask()
    return search.read(*asked[key])


def _checked(
    file: File,
    world: World,
    choice: _Choice,
    known: reference.Routes | None = None,
    any_will_do: bool = False,
) -> Itinerary:
    """The solver's choice, timed and checked by the reference checker.

    For the ITINERARY shown, the reference checker picks the WAYs itself, in the order of the
    rules page, from the routes already worked out. Otherwise it checks the WAYs the solver
    picked. Where a COMPLETE FACT rules an unlisted WAY out for a span, it takes that WAY
    before or after the span as the solver did, and tries no other side. The times are its
    own, by the usual rule. With ``any_will_do`` the question is only whether the choice
    works, and the first ITINERARY that the reference checker finds for it answers that.
    It then tries the OPTIONs that matter to each OBJECT in the order the solver has them
    first, and works out the hand-overs for that order itself. The solver's times keep that
    order, so the reference checker need not look for another.
    """
    who, orders, by, falls, in_order, empty = choice
    itinerary = reference.scheduled(
        file, world, who, orders, by, known, falls, any_will_do, in_order, empty
    )
    if itinerary is None:
        raise AssertionError("the solver chose PERSONs and orders that the rules refuse")
    return itinerary


def _solver(relax: bool = True) -> cp_model.CpSolver:
    """A solver set up to give the same result every time.

    ``relax`` keeps its linear relaxation, which it needs to prove a best value in good
    time. The plain questions, with nothing to make smaller, are asked without it. On the
    trips measured that is as quick or quicker, with a model that says outright that no two
    OPTIONs of a PERSON overlap.

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
        self,
        file: File,
        world: World,
        open_pairs: Sequence[tuple[str, str]] = (),
        plain: bool = False,
    ) -> None:
        """Build the model of this world.

        ``open_pairs`` are left to the solver: each an OPTION and a WANT, and whether the
        OPTION SATISFIES the WANT. The world must say that they do not. ``plain`` says that
        the model is for the plain question whether anything works, with nothing to make
        smaller.
        """
        self.file, self.world, self.plain = file, world, plain
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
        # When an unlisted WAY of a route starts, where a COMPLETE FACT could rule it out: for
        # the choice that takes the route, the route and the place of the WAY in it.
        self.moments: dict[tuple[int, reference.Route, int], cp_model.IntVar] = {}
        self.known = reference.Routes(file, world)
        # For each OBJECT and each OPTION that can hand it over, the choice for each PERSON
        # that they take it there.
        self.given_to: dict[tuple[str, int], list[cp_model.IntVar]] = {}
        # The earliest anything is at each PLACE, setting out from a PLACE at a time or at
        # any time.
        self._crossing: dict[tuple[str, int | None], dict[str, int]] = {}
        self._legs: dict[str, list[tuple[str, int, int | None]]] | None = None
        self._closed: dict[tuple[str, str], list[tuple[int, int]]] = {}
        self._worth_trying: dict[tuple[str, str, bool], list[reference.Route]] = {}
        for number in range(len(file.persons)):
            self._lay_out_path(number)
        for thing, matter in self.matters.items():
            self._follow(thing, matter)

    def _read_the_world(self) -> None:
        """What the world says about each OPTION and WAY."""
        file, world = self.file, self.world
        self.terms = [world.terms[option.id] for option in file.options]
        self.no_time = reference.NoTimeBetween(file, world)
        self.have_to = _have_to_take(file, world, self.does)
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
        # Each OBJECT that some OPTION requires or refuses in this world, unless another
        # transfer brings it, with the OPTIONs that matter to it: those that require it,
        # refuse it or do something with it, by position in the FILE. Where an OBJECT is
        # turns on nothing else.
        self.matters: dict[str, list[int]] = {}
        # Where an OPTION needs a right for an OBJECT and nothing covers the OBJECT, nobody
        # who takes part has it and it is not handed over there, as where the OPTION
        # refuses it. It is not carried there either.
        self.barred = world.refuses | world.uncovered
        checked = world.needs | self.barred
        for thing in file.objects:
            touched = [
                index
                for index, option in enumerate(file.options)
                if (option.id, thing.id) in checked or (option.id, thing.id) in world.does
            ]
            asked = any((option.id, thing.id) in checked for option in file.options)
            if asked and thing.id not in world.brought:
                self.matters[thing.id] = touched

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
        carries = self._could_carry()
        supplies = self._could_supply(meets, carries)
        # An OPTION can happen with nobody in it. The model leaves that open only where it
        # can serve a purpose, as ``could_run_alone`` says: any other OPTION happens just
        # where a PERSON takes part.
        alone = set(reference.could_run_alone(file, self.world))
        for index, option in enumerate(file.options):
            if index in alone:
                for row in self.takes:
                    model.add_implication(row[index], self.used[index])
            else:
                model.add_max_equality(self.used[index], [0, *(row[index] for row in self.takes)])
            for number, person in enumerate(file.persons):
                takes = self.takes[number][index]
                asked = any(
                    lock.option == option.id and person.id in lock.persons for lock in file.locks
                )
                if asked:
                    model.add(takes == 1)
                # A PERSON gains nothing by staying somewhere unless a LOCK asks them to, the
                # stay could meet a must of theirs, they have a CAPABILITY that the stay
                # requires of one PERSON, or they can have an OBJECT that the stay requires,
                # hands over, keeps or carries: they can bring it, take it or leave it there.
                # Without the stay they are in the same PLACE at the same times, and every
                # CONSTRAINT is as easy to meet or easier. So the model leaves such stays out.
                wanted = index in meets[number] or (number, index) in supplies
                wanted = wanted or (number, index) in carries
                if not self.usable[index] or (not self.moves[index] and not asked and not wanted):
                    self._rule_out(number, index)
        self._hold_to_the_requirements()
        self._hold_to_the_rights()

    def _could_carry(self) -> set[tuple[int, int]]:
        """Each PERSON and OPTION where the PERSON can gain by taking part because of an OBJECT.

        The OPTION requires the OBJECT, hands it over, keeps it or carries it, and the PERSON
        can have the OBJECT at some time: so they can bring it, take it or leave it there. A
        PERSON can have it who has it when the TRIP starts, or might, or who can take part
        in an OPTION that hands it over. Nobody comes to have it by a carry. Nobody else
        ever has it, so whether they take part in a stay changes nothing about where the
        OBJECT is: a stay that carries an OBJECT that lies there leaves it where it lay.
        An OPTION that moves is different, and the model leaves nobody out of one.

        An OPTION that only might keep the OBJECT gives nobody a reason. Where whoever has
        the OBJECT stays out of it, the OBJECT might be in fewer places afterwards. It is
        at hand wherever it was at hand with more, and no PERSON has it who did not have it
        with more. An OPTION that refuses the OBJECT gives nobody a reason either. Nobody
        who has the OBJECT takes part in it, and nobody takes the OBJECT there, so whoever
        comes changes nothing about where the OBJECT is. Whoever has to leave the OBJECT
        somewhere first has their reason for the stay that keeps it.

        ``self.holders`` keeps, for each OBJECT that matters, the PERSONs who can have it.
        """
        file, world = self.file, self.world
        everybody = range(len(file.persons))
        self.holders: dict[str, set[int]] = {}
        carries: set[tuple[int, int]] = set()
        for thing, matter in self.matters.items():
            holders = set(self._might_start_with(thing))
            gain: list[int] = []
            for index in matter:
                option = file.options[index].id
                does = world.does.get((option, thing), "nothing")
                if (option, thing) in self.barred:
                    continue
                if does in ("hands_over", "any"):
                    holders |= {n for n in everybody if not self._shut_out(n, index)}
                acts = does in ("hands_over", "keeps", "carries", "any")
                if (option, thing) in world.needs or acts:
                    gain.append(index)
            self.holders[thing] = holders
            carries.update((number, index) for number in holders for index in gain)
        return carries

    def _might_start_with(self, thing: str) -> list[int]:
        """The PERSONs who might have an OBJECT when the TRIP starts, by position in the FILE.

        The PERSON that the world says has it. Everybody, where the world leaves the start
        to pick, and where nobody knows where the OBJECT starts.
        """
        start = self.world.starts.get(thing)
        return [
            number
            for number, person in enumerate(self.file.persons)
            if start is None or start.person == person.id
        ]

    def _shut_out(self, number: int, index: int) -> bool:
        """Whether this PERSON takes no part in this OPTION, whoever else does.

        The OPTION cannot happen, a must-not keeps the PERSON out of it, they lack a
        CAPABILITY that it requires of each PERSON, or it needs a right that they do not have
        and can pay for no place of. More than this can keep a PERSON out. This only says who
        is sure to be out, so that the model can leave out what turns on them.
        """
        file, world = self.file, self.world
        option, person = file.options[index].id, file.persons[number].id
        if not self.usable[index] or (number, index) in self.left_out:
            return True
        for (asking, capability), of in world.requires.items():
            if asking == option and of == "each" and (person, capability) not in world.has:
                return True
        if option not in world.needs_right or (option, person) in world.rights:
            return False
        return not any((offer.id, person) in world.payable for offer in file.offers(option))

    def _could_supply(
        self, meets: Sequence[set[int]], carries: Set[tuple[int, int]]
    ) -> set[tuple[int, int]]:
        """Each PERSON and stay where the PERSON may have to come to meet a requirement.

        The stay requires a CAPABILITY of one PERSON, and the PERSON has it. Two cases are
        left out. Nobody comes where nobody else has a reason to be there: a LOCK, a must
        that the stay could meet, as ``meets`` says for each PERSON, or an OBJECT that they
        can bring, take or leave there, as ``carries`` says. Without them the stay need not
        happen at all. And nobody comes for a CAPABILITY that a PERSON whom a LOCK names in
        the stay has: that requirement is met whenever the stay happens.

        An OPTION that moves is in the result too, and nothing reads it there: the model
        leaves nobody out of one.
        """
        file, world = self.file, self.world
        position = {option.id: index for index, option in enumerate(file.options)}
        locked: dict[str, set[str]] = {}
        for lock in file.locks:
            locked.setdefault(lock.option, set()).update(lock.persons)
        happens = {index for theirs in meets for index in theirs}
        happens |= {index for _, index in carries}
        supplies: set[tuple[int, int]] = set()
        for (option, capability), of in world.requires.items():
            index = position[option]
            named = locked.get(option, set())
            if of != "one" or not (named or index in happens):
                continue
            if any((person, capability) in world.has for person in named):
                continue
            supplies.update(
                (number, index)
                for number, person in enumerate(file.persons)
                if (person.id, capability) in world.has
            )
        return supplies

    def _hold_to_the_requirements(self) -> None:
        """Each requirement of an OPTION is met by the PERSONs who take part in it.

        Where an OPTION requires a CAPABILITY of each PERSON, nobody without it takes part.
        Where it requires it of one PERSON, it happens only with a PERSON who has it.
        """
        model, file, world = self.model, self.file, self.world
        position = {option.id: index for index, option in enumerate(file.options)}
        for (option, capability), of in world.requires.items():
            index = position[option]
            able = [
                n for n, person in enumerate(file.persons) if (person.id, capability) in world.has
            ]
            if of == "one":
                model.add_bool_or(
                    [self.used[index].negated(), *(self.takes[n][index] for n in able)]
                )
                continue
            for number in range(len(file.persons)):
                if number not in able and (number, index) not in self.left_out:
                    self._rule_out(number, index)

    def _follow(self, thing: str, matter: Sequence[int]) -> None:
        """One OBJECT is at hand where it is required or handed over, and nobody has it where
        an OPTION refuses it.

        The OPTIONs that matter to it and happen form a path, in the order they happen: a
        circuit through a point that stands for the start of the TRIP. An OPTION that comes
        later on the path has a later turn and starts no earlier. Each PERSON's own order
        gives turns too, so the path keeps to every one of them.

        Along the path the model carries where the OBJECT might be: with each PERSON, at each
        PLACE where one of these OPTIONs starts, in each OPTION that carries it, or somewhere
        else. That is one place in a possible world, and several where an OPTION might keep
        the OBJECT. An OPTION that requires the OBJECT needs each of those places at hand:
        a PERSON who takes part, or the PLACE where it starts. So does a hand-over, and
        after it the PERSON who took the OBJECT has it. So does a carry, and after it the
        OBJECT is in the OPTION. An OPTION that refuses the OBJECT needs none of those
        places to be a PERSON who takes part. An OPTION that keeps it moves it from whoever
        takes part to the PLACE where the OPTION starts. Where the world leaves the start
        to pick, the solver picks it, and where an OPTION might do anything, the solver
        picks what it does. Where nobody knows where the OBJECT starts, it might be in
        every place at once.

        An OBJECT that is in an OPTION lies at the PLACE where that OPTION ends once it is
        over. So an OPTION on the path can find it there, where it starts no earlier than
        that end. The solver picks which OPTION does. The rules ask that only of the first
        OPTION that uses the OBJECT. An OPTION before it does nothing with the OBJECT
        either way, so the model lets any OPTION find it there, and the same plans work.

        The reference checker works out the order, the hand-overs and the carries again for
        the choice the solver makes, and checks them. So this only has to say when some
        order, some hand-overs and some carries work.
        """
        model, file, world = self.model, self.file, self.world
        options = file.options
        moves = any((option.id, thing) in world.does for option in options)
        carriers = [
            index
            for index in matter
            if world.does.get((options[index].id, thing))
            in ("carries", "any", "might_take", "might_carry")
        ]
        picked = thing in world.starts_anywhere and thing not in world.starts
        if not picked and not carriers and not (moves and self.holders[thing]):
            # Nothing does anything with it, or nobody can ever have it and nothing carries
            # it. So it stays where it starts. An OPTION that requires it happens only
            # there, or with the PERSON who has it. Nobody who has it, or might, takes part
            # in an OPTION that refuses it. Where nobody knows where it starts, it is at
            # hand for nothing, and everybody might have it.
            start = world.starts.get(thing, Where())
            might_have = [self.takes[number] for number in self._might_start_with(thing)]
            holder = might_have if start.person is not None else []
            for index in matter:
                required = (options[index].id, thing) in world.needs
                if required and start.place != options[index].origin:
                    model.add_bool_or([self.used[index].negated(), *(row[index] for row in holder)])
                if (options[index].id, thing) in self.barred:
                    for row in might_have:
                        model.add(row[index] == 0)
            return
        origins = {options[index].origin for index in matter}
        spots = [
            *(Where(person=person.id) for person in file.persons),
            *(Where(place=place.id) for place in file.places if place.id in origins),
            Where(),
            *(Where(option=options[index].id) for index in carriers),
        ]
        somewhere_else = spots.index(Where())

        def some(what: str) -> list[cp_model.IntVar]:
            return [model.new_bool_var(f"{thing} {what} {n}") for n in range(len(spots))]

        # Where it starts. A PLACE where none of these OPTIONs starts is as good as anywhere
        # else: the OBJECT is at hand for nothing there, and nothing moves it. It starts in
        # no OPTION, so those spots are no choice.
        starts = [model.new_bool_var(f"{thing} starts {n}") for n in range(somewhere_else + 1)]
        at_first: list[cp_model.IntVar | int] = [*starts, *(0 for _ in carriers)]
        if picked:
            model.add_exactly_one(starts)
        elif thing in world.starts:
            stated = world.starts[thing]
            begins = spots.index(stated) if stated in spots else somewhere_else
            for n, spot in enumerate(starts):
                model.add(spot == (n == begins))
        else:
            model.add_bool_and(starts)  # nobody knows where it starts: it might be anywhere

        before = {index: some(f"before {options[index].id}") for index in matter}
        after = {index: some(f"after {options[index].id}") for index in matter}
        found = {
            index: self._arrive(thing, index, carriers, spots, before[index]) for index in matter
        }
        node = {index: n for n, index in enumerate(matter)}
        start_of_trip = len(matter)
        untouched = model.new_bool_var(f"nothing touches {thing}")
        arcs: list[tuple[int, int, cp_model.LiteralT]] = [(start_of_trip, start_of_trip, untouched)]
        handed: dict[int, cp_model.IntVar] = {}  # the choice that it is handed over in an OPTION
        loaded: dict[int, cp_model.IntVar] = {}  # the choice that it is carried in an OPTION
        for index in matter:
            arcs.append((node[index], node[index], self.used[index].negated()))
            first = model.new_bool_var(f"{thing} first {options[index].id}")
            last = model.new_bool_var(f"{thing} last {options[index].id}")
            arcs += [(start_of_trip, node[index], first), (node[index], start_of_trip, last)]
            for n in range(len(spots)):
                _when(model.add(before[index][n] == at_first[n]), first)
            for other in matter:
                early, late = self.terms[index].fixed_start, self.terms[other].fixed_start
                if other == index or (early is not None and late is not None and early > late):
                    continue  # an OPTION with a later fixed start never comes first
                then = model.new_bool_var(f"{thing}: {options[other].id} after {options[index].id}")
                arcs.append((node[index], node[other], then))
                _when(model.add(self.turn[other] >= self.turn[index] + 1), then)
                _when(model.add(self.start[other] >= self.start[index]), then)
                for n in range(len(spots)):
                    _when(model.add(before[other][n] == after[index][n]), then)
            given, loads = self._pass_through(thing, index, spots, found[index], after[index])
            if given is not None:
                handed[index] = given
            if loads is not None:
                loaded[index] = loads
        model.add_circuit(arcs)
        self._leave_time_to_cross(thing, matter, handed, loaded)
        self._clear_before_a_refusal(thing, matter, handed, loaded, picked)

    def _arrive(
        self,
        thing: str,
        index: int,
        carriers: Sequence[int],
        spots: Sequence[Where],
        before: Sequence[cp_model.IntVar],
    ) -> list[cp_model.IntVar]:
        """Where an OBJECT might be when an OPTION starts, once what was carried has arrived.

        ``before`` says, for each of ``spots``, whether the OBJECT might be there as the
        OPTION before this one on its path left it. The result says the same for when
        this OPTION starts. An OBJECT that is in an OPTION can be found at the PLACE where
        that OPTION ends instead, where this OPTION starts no earlier than that end. The
        solver picks whether it is. An OPTION with no limit to how long it takes never
        ends for sure, so nothing is found after it.

        A PLACE where none of the OPTIONs that matter starts is as good as anywhere else.
        """
        model, options = self.model, self.file.options
        somewhere_else = spots.index(Where())
        arrived: dict[int, list[cp_model.IntVar]] = {}  # at each spot, from each carry
        there = list(before)
        for carrier in carriers:
            if carrier == index or self.endless[carrier]:
                continue
            aboard = spots.index(Where(option=options[carrier].id))
            ends_at = Where(place=options[carrier].destination)
            lands = spots.index(ends_at) if ends_at in spots else somewhere_else
            name = f"{thing} has arrived from {options[carrier].id} for {options[index].id}"
            came = model.new_bool_var(name)
            over = self.start[carrier] + self.lasts[carrier]
            _when(model.add(self.start[index] >= over), came)
            still = model.new_bool_var(f"{thing} is still in {options[carrier].id}: {name}")
            model.add(still + came == before[aboard])
            there[aboard] = still
            arrived.setdefault(lands, []).append(came)
        for lands, came in arrived.items():
            lies = model.new_bool_var(f"{thing} lies at {lands} for {options[index].id}")
            model.add_max_equality(lies, [before[lands], *came])
            there[lands] = lies
        return there

    def _clear_before_a_refusal(
        self,
        thing: str,
        matter: Sequence[int],
        handed: Mapping[int, cp_model.IntVar],
        loaded: Mapping[int, cp_model.IntVar],
        picked: bool,
    ) -> None:
        """Whoever has an OBJECT is rid of it before they take part in an OPTION that refuses it.

        The path of the OBJECT already says this. Said outright, the solver need not find it
        out by trying every order.

        A PERSON has the OBJECT, or might, from the start of the TRIP where they have it
        then or might, and from an OPTION in which they take it. They still might have it
        until they take part in an OPTION that takes it from them: one that keeps it, or one
        in which it is handed over or carried. A hand-over needs every place the OBJECT
        might be in at hand, and so does a carry, so whoever might have it takes part
        there. An OPTION that only might keep the OBJECT takes it from nobody for sure, and
        one that refuses it takes it from no PERSON. So such a PERSON takes part in an
        OPTION that refuses the OBJECT only where they take part in one of those others
        before it. A PERSON's own OPTIONs have turns in the order they do them. A carry in
        an OPTION that refuses the OBJECT is among the others here, and it helps nobody: the
        path lets no PERSON who has the OBJECT take part there.

        This says less than the path does. An OPTION that takes the OBJECT from a PERSON
        before they take it does not help them, and neither does a hand-over to themselves:
        then they take it again, and the same holds from there on.

        ``handed`` holds, for each OPTION that can hand the OBJECT over, the choice that it
        does, and ``loaded`` the same for each OPTION that can carry it. ``picked`` says
        that the world leaves the start to pick: then nobody is known to have the OBJECT
        when the TRIP starts.

        Two OPTIONs that a PERSON takes part in start in the order of their turns. So where
        both start at fixed times, the one with the later start never comes first, and
        nothing is said about that order.
        """
        model, world, options = self.model, self.world, self.file.options
        fixed = [each.fixed_start for each in self.terms]

        def can_come_before(first: int, then: int) -> bool:
            early, late = fixed[first], fixed[then]
            return early is None or late is None or early <= late

        refusing = [index for index in matter if (options[index].id, thing) in self.barred]
        keeping = [
            index
            for index in matter
            if index not in refusing
            and world.does.get((options[index].id, thing)) in ("keeps", "any")
        ]
        after = {
            (first, then): model.new_bool_var(f"{options[then].id} after {options[first].id}")
            for first in handed
            for then in refusing
            if can_come_before(first, then)
        }
        for (first, then), later in after.items():
            _when(model.add(self.turn[first] >= self.turn[then] + 1), later.negated())

        def rid_of_it(number: int, since: int | None, until: int) -> list[cp_model.IntVar]:
            """Each way this PERSON can be rid of the OBJECT before one OPTION.

            ``since`` is the OPTION in which they take it, where they do. That one is no way.
            """
            row = self.takes[number]
            ways: list[cp_model.IntVar] = []
            for other in dict.fromkeys((*keeping, *handed, *loaded)):
                if other in (since, until) or not can_come_before(other, until):
                    continue
                if since is not None and not can_come_before(since, other):
                    continue
                name = f"{number} is rid of {thing} in {options[other].id}"
                way = model.new_bool_var(f"{name} before {options[until].id}")
                model.add_implication(way, row[other])
                _when(model.add(self.turn[until] >= self.turn[other] + 1), way)
                if other not in keeping:
                    # It is handed over there, or carried.
                    done = [choice[other] for choice in (handed, loaded) if other in choice]
                    model.add_bool_or([way.negated(), *done])
                ways.append(way)
            return ways

        for then in refusing:
            for number in [] if picked else self._might_start_with(thing):
                ways = rid_of_it(number, None, then)
                model.add_bool_or([self.takes[number][then].negated(), *ways])
            for first in handed:
                if (first, then) not in after:
                    continue  # the hand-over comes after the OPTION that refuses the OBJECT
                for number, takes_it in enumerate(self.given_to[thing, first]):
                    ways = rid_of_it(number, first, then)
                    unless = [takes_it.negated(), self.takes[number][then].negated()]
                    model.add_bool_or([*unless, after[first, then].negated(), *ways])

    def _leave_time_to_cross(
        self,
        thing: str,
        matter: Sequence[int],
        handed: Mapping[int, cp_model.IntVar],
        loaded: Mapping[int, cp_model.IntVar],
    ) -> None:
        """An OBJECT is at hand in two PLACEs only with the time to get from one to the other.

        ``handed`` holds, for each OPTION that can hand the OBJECT over, the choice that it
        does, and ``loaded`` the same for each OPTION that can carry it. The path of the
        OBJECT already says all of this. Said outright, the solver need not find it out by
        trying.

        The OBJECT is at the PLACE where an OPTION starts, at the time it starts, where the
        OPTION requires it and where it is handed over or carried in it: it lies there, or
        a PERSON who takes part has it. It gets from PLACE to PLACE only with a PERSON or
        in an OPTION that carries it, and that is an OPTION that moves. So between two
        such OPTIONs at different PLACEs lies at least the least time anything needs from
        the one to the other, as ``_across`` gives it.

        An OBJECT that lies at a PLACE leaves it only by a hand-over or a carry in an OPTION
        that starts there. Whoever takes it stays in that OPTION until it is over, and an
        OBJECT that is carried is in the OPTION until then. So where the OBJECT is at hand
        at another PLACE, some such OPTION hands it over or carries it, early enough to be
        over and across by then. The same holds for an OBJECT that is nowhere the FILE
        knows of: nothing hands it over or carries it, and it is at hand nowhere.
        """
        model, world, options = self.model, self.world, self.file.options
        fixed = [each.fixed_start for each in self.terms]
        trip_starts = self.file.trip_start()
        opens = None if trip_starts is None else trip_starts.at

        def there_by(
            before: int, after: int, origin: str, takes_first: int, when: list[cp_model.LiteralT]
        ) -> bool:
            """The second OPTION starts late enough for the OBJECT to get there from the first.

            ``origin`` is where the OBJECT sets out, once the first OPTION has started and
            ``takes_first`` more seconds have gone by. ``when`` says when that holds. The
            result is False where nothing gets there at all.

            The least time on the way counts from when the first OPTION starts. Where it
            starts at no fixed time, the TRIP's start says more: the OBJECT cannot set out
            before then, and a ride that has left by then is no help however long the first
            OPTION waits.
            """
            destination = options[after].origin
            starts = fixed[before]
            set_out = None if starts is None else starts + takes_first
            takes = self._across(origin, destination, set_out)
            if takes is None:
                return False
            _when(model.add(self.start[after] >= self.start[before] + takes_first + takes), *when)
            if starts is None and opens is not None:
                least = self._across(origin, destination, opens + takes_first)
                if least is None:
                    return False
                arrives = opens + takes_first + least - self.zero
                _when(model.add(self.start[after] >= arrives), *when)
            return True

        at_hand = [
            (index, self.used[index])
            for index in matter
            if (options[index].id, thing) in world.needs
        ]
        at_hand += [*handed.items(), *loaded.items()]
        for (one, here), (other, there) in combinations(at_hand, 2):
            if options[one].origin == options[other].origin:
                continue
            first = model.new_bool_var(f"{thing} in {options[one].id} before {options[other].id}")
            if not there_by(one, other, options[one].origin, 0, [here, there, first]):
                model.add_bool_or([here.negated(), there.negated(), first.negated()])
            if not there_by(other, one, options[other].origin, 0, [here, there, first.negated()]):
                model.add_bool_or([here.negated(), there.negated(), first])
        start = world.starts.get(thing, Where())
        if (thing in world.starts_anywhere and thing not in world.starts) or start.person:
            return  # the solver picks where it starts, or a PERSON has it
        for index, here in at_hand:
            if options[index].origin == start.place:
                continue
            early_enough: list[cp_model.IntVar] = []
            for source, given in (*handed.items(), *loaded.items()):
                if options[source].origin != start.place or source == index:
                    continue
                # The OBJECT comes from this hand-over or carry: it is over and across by then.
                name = f"{thing} comes to {options[index].id} from {options[source].id}"
                from_there = model.new_bool_var(name)
                model.add_implication(from_there, given)
                over = self.lasts[source]
                if there_by(source, index, options[source].destination, over, [from_there]):
                    early_enough.append(from_there)
                else:
                    model.add(from_there == 0)
            model.add_bool_or([here.negated(), *early_enough])

    def _across(self, origin: str, destination: str, since: int | None = None) -> int | None:
        """The least time anything needs from one PLACE to another, or None where none gets there.

        A PERSON changes PLACE by a WAY or by an OPTION that moves. An OBJECT changes PLACE
        with a PERSON, or in an OPTION that moves and carries it, with a PERSON in it or
        with nobody. Each takes at least its shortest time. A WAY or an OPTION with no limit
        to how long it takes is left out: nothing follows it, so nothing it carries is at
        hand anywhere afterwards.

        ``since`` is when the crossing sets out, where that is known. Then an unlisted WAY
        leaves only outside the spans in which COMPLETE FACTs rule it out, and an OPTION
        that moves at a fixed time is taken only where it starts no earlier than the
        crossing got to it. With no time to set out, none of that is looked at. Either way
        the real time can be longer and is never shorter.

        The times from one PLACE are worked out once, and only from the PLACEs asked about.
        """
        if (origin, since) not in self._crossing:
            self._crossing[origin, since] = self._from(origin, since)
        reached = self._crossing[origin, since].get(destination)
        return None if reached is None else reached - (since or 0)

    def _from(self, origin: str, since: int | None) -> dict[str, int]:
        """For ``_across``: the earliest anything is at each PLACE, setting out from one.

        With ``since`` that is a time, for setting out then. Without it, it is the least
        time on the way, counted from zero.
        """
        file, world = self.file, self.world
        if self._legs is None:
            # From each PLACE: where a listed WAY or an OPTION that moves leads, how long it
            # takes at least, and for an OPTION that moves its position in the FILE.
            legs: dict[str, list[tuple[str, int, int | None]]] = {}
            for way in file.ways:
                shortest, longest = world.takes[way.id]
                if longest is None:
                    continue
                legs.setdefault(way.origin, []).append((way.destination, shortest, None))
                if way.both_ways:
                    legs.setdefault(way.destination, []).append((way.origin, shortest, None))
            for index, option in enumerate(file.options):
                if self.moves[index] and self.usable[index] and not self.endless[index]:
                    ride = (option.destination, self.lasts[index], index)
                    legs.setdefault(option.origin, []).append(ride)
            self._legs = legs
        places = [place.id for place in file.places]
        unlisted = world.unlisted is None or bool(world.unlisted)

        def leaves(here: str, there: str, at: int) -> int | None:
            """When an unlisted WAY of this world can first leave, from this time on."""
            if world.unlisted is not None and (here, there) not in world.unlisted:
                return None
            if since is None:
                return at
            if (here, there) not in self._closed:
                self._closed[here, there] = reference.spans_closed(file, here, there)
            for earliest, latest in self._closed[here, there]:
                if earliest <= at <= latest:
                    return latest + 1
            return at

        def sets_out(ride: int | None, at: int) -> int | None:
            """When a listed WAY or an OPTION that moves can first be taken, from this time on."""
            start = None if ride is None else self.terms[ride].fixed_start
            if start is None or since is None:
                return at
            return start if start >= at else None

        earliest = {origin: since or 0}
        ahead = [(since or 0, origin)]
        while ahead:
            at, here = heappop(ahead)
            if at > earliest[here]:
                continue
            onward = [
                (there, leaving + takes)
                for there, takes, ride in self._legs.get(here, ())
                for leaving in [sets_out(ride, at)]
                if leaving is not None
            ]
            if unlisted:
                onward += [
                    (there, leaving + world.unlisted_takes)
                    for there in places
                    if there != here
                    for leaving in [leaves(here, there, at)]
                    if leaving is not None
                ]
            for there, arrives in onward:
                if arrives < earliest.get(there, inf):
                    earliest[there] = arrives
                    heappush(ahead, (arrives, there))
        return earliest

    def _pass_through(
        self,
        thing: str,
        index: int,
        spots: Sequence[Where],
        before: Sequence[cp_model.IntVar],
        after: Sequence[cp_model.IntVar],
    ) -> tuple[cp_model.IntVar | None, cp_model.IntVar | None]:
        """What one OPTION that happens asks of an OBJECT, and where the OBJECT is after it.

        ``before`` and ``after`` say, for each of ``spots``, whether the OBJECT might be
        there just before the OPTION starts, and from its start on. The first spots are the
        PERSONs, in the FILE's order. The result is the choice that the OBJECT is handed over
        in the OPTION, or None where the OPTION hands nothing over, and the choice that it
        is carried in the OPTION, or None where the OPTION carries nothing.

        The OPTION first checks what it requires and what it refuses, then keeps what it
        keeps, and then the OBJECT is handed over or carried in it. One that might keep the
        OBJECT leaves it in both places: with whoever has it, and at the PLACE where the
        OPTION starts. One that refuses the OBJECT takes it from no PERSON: it can only
        carry it from the PLACE where it starts.
        """
        model, world = self.model, self.world
        option = self.file.options[index]
        used = self.used[index]
        takes = [row[index] for row in self.takes]
        persons = range(len(takes))
        here = next(n for n, spot in enumerate(spots) if spot.place == option.origin)
        refused = (option.id, thing) in self.barred
        uncovered = (option.id, thing) in world.uncovered

        def at_hand(*when: cp_model.LiteralT) -> None:
            """Under these conditions, each place where the OBJECT might be is at hand."""
            for n, spot in enumerate(spots):
                if spot.person is not None:
                    _when(model.add_bool_or([before[n].negated(), takes[n]]), *when)
                elif n != here:
                    _when(model.add(before[n] == 0), *when)

        if (option.id, thing) in world.needs:
            at_hand(used)
        action = world.does.get((option.id, thing), "nothing")
        loads: cp_model.IntVar | None = None
        if action in ("carries", "any"):
            # The choice that the OBJECT is carried: the OPTION happens, the OBJECT is at
            # hand, and then it is in the OPTION and nowhere else.
            loads = model.new_bool_var(f"{thing} carried in {option.id}")
            model.add_implication(loads, used)
            if uncovered:
                model.add(loads == 0)  # nothing covers the OBJECT here, so it is not carried
            at_hand(loads)
            aboard = spots.index(Where(option=option.id))
            for n in range(len(spots)):
                _when(model.add(after[n] == (n == aboard)), loads)
        # An OPTION that requires the OBJECT and carries it takes it along whenever it
        # happens: that is no choice. Where nobody is sure that it requires the OBJECT, it
        # might, unless the plan chooses the carry.
        along = reference.goes_along(world, option.id, thing)
        if along == "sure" and loads is not None:
            model.add_implication(used, loads)
        # So might an OPTION that requires the OBJECT, and of which nobody knows what it
        # does with it. Then the OBJECT might be in the OPTION afterwards.
        might_take = action in ("might_take", "might_carry") or along == "might"
        in_it = spots.index(Where(option=option.id)) if might_take else -1
        if refused:
            # Nobody who takes part has the OBJECT just before, or might. So the OPTION
            # takes it from no PERSON: it keeps the OBJECT from nobody, and nobody takes
            # it there. It can carry the OBJECT from the PLACE where it starts, and it
            # might take along what lies there.
            for n in persons:
                model.add_bool_or([before[n].negated(), takes[n].negated()])
            if uncovered and might_take:
                # It might take along what lies where it starts, with nothing to cover it.
                _when(model.add(before[here] == 0), used)
            left: list[cp_model.LiteralT] = [used] if loads is None else [used, loads.negated()]
            for n in range(len(spots)):
                _when(model.add(after[n] == before[here if n == in_it else n]), *left)
            return None, loads
        # What is left to choose: which PERSON has the OBJECT handed over, where the OPTION
        # hands it over, whether it is carried, where the OPTION carries it, and whether
        # the OPTION keeps it, where it might do anything.
        gives: list[cp_model.IntVar] = []
        given: cp_model.IntVar | None = None
        # The OPTION happens, with no hand-over and no carry in it.
        quiet: list[cp_model.LiteralT] = [used] if loads is None else [used, loads.negated()]
        if action in ("hands_over", "any"):
            gives = [model.new_bool_var(f"{thing} to {n} in {option.id}") for n in persons]
            self.given_to[thing, index] = gives
            given = model.new_bool_var(f"{thing} handed over in {option.id}")
            model.add_max_equality(given, [0, *gives])
            for n in persons:
                model.add_implication(gives[n], takes[n])
                at_hand(gives[n])
            for n, spot in enumerate(spots):
                # After a hand-over the PERSON who took it has it, and it is nowhere else.
                taken = gives[n] if spot.person is not None else 0
                _when(model.add(after[n] == taken), used, given)
            quiet = [*quiet, given.negated()]
        keeping, leaving = quiet, quiet
        if action == "any":
            keeps = model.new_bool_var(f"{option.id} keeps {thing}")
            model.add_at_most_one([*gives, keeps, *([] if loads is None else [loads])])
            keeping, leaving = [*quiet, keeps], [*quiet, keeps.negated()]
        elif gives:
            model.add_at_most_one(gives)
        # A PERSON who takes part and has the OBJECT, or might.
        held = [model.new_bool_var(f"{n} has {thing} in {option.id}") for n in persons]
        for n in persons:
            model.add_min_equality(held[n], [before[n], takes[n]])
        any_held = model.new_bool_var(f"somebody has {thing} in {option.id}")
        model.add_max_equality(any_held, [0, *held])

        def same(n: int, *when: cp_model.LiteralT) -> None:
            _when(model.add(after[n] == before[n]), *when)

        def joined(n: int, *when: cp_model.LiteralT) -> None:
            """It is in this spot afterwards where it was at hand, and nowhere else: it lay
            where the OPTION starts, or somebody who takes part had it."""
            _when(model.add_bool_or([after[n], before[here].negated()]), *when)
            _when(model.add_bool_or([after[n], any_held.negated()]), *when)
            _when(model.add(after[n] <= before[here] + any_held), *when)

        for n, spot in enumerate(spots):
            if action in ("keeps", "any"):
                if spot.person is not None:
                    _when(model.add(after[n] + held[n] == before[n]), *keeping)
                elif n == here:
                    joined(n, *keeping)
                else:
                    same(n, *keeping)
                if action == "any":
                    same(n, *leaving)
            elif action in ("might_keep", "might_take") and n == here:
                joined(n, *quiet)
            elif n == in_it:
                # It might be in the OPTION where it was at hand.
                joined(n, *quiet)
            else:
                same(n, *quiet)
        return given, loads

    def _rule_out(self, number: int, index: int) -> None:
        """This PERSON takes no part in this OPTION, whatever else is chosen.

        So no travel is built for them to it or from it.
        """
        self.model.add(self.takes[number][index] == 0)
        self.left_out.add((number, index))

    def _hold_to_the_rights(self) -> None:
        """Nobody takes part without a right in an OPTION that needs one, and no cap is passed."""
        file, world = self.file, self.world
        people = list(enumerate(file.persons))
        # What the purchases draw on each cap: the price, and the choice that draws it.
        self.drawn: dict[tuple[str, str], list[tuple[int, cp_model.IntVar]]] = {
            key: [] for key in file.caps
        }
        for index, option in enumerate(file.options):
            if option.id in world.needs_right:
                without = [n for n, person in people if (option.id, person.id) not in world.rights]
                self._share_out(index, without)
        self._hold_to_the_caps()

    def _hold_to_the_caps(self) -> None:
        """No cap is passed: what the BOOKINGs charged, plus what is bought, is within it.

        ``World.spent`` says the most that the BOOKINGs might have charged to each cap in
        this world. The rest of the cap is room for the purchases that draw on it. A place
        that costs more than the room is never paid from that BUDGET. ``shown``, ``works``
        and ``can_work`` build no model where the BOOKINGs pass a cap by themselves.

        The amounts are whole ten-thousandths, and the largest a FILE can state takes 54 bits.
        So a sum of many can pass what the solver counts with, and then the TRIP does not fit.
        """
        model = self.model
        for key, cap in self.file.caps.items():
            charged = self.world.spent.get(key, 0)
            if charged is None or charged > cap.limit.units:
                raise AssertionError("a model was built where the BOOKINGs pass a cap")
            room = cap.limit.units - charged
            fitting: list[tuple[int, cp_model.IntVar]] = []
            for units, pick in self.drawn[key]:
                if units > room:
                    model.add(pick == 0)
                else:
                    fitting.append((units, pick))
            if sum(units for units, _ in fitting) >= 2**62:
                raise DoesNotFit("the amounts of this TRIP are too large to add up")
            if sum(units for units, _ in fitting) > room:
                model.add(sum(units * pick for units, pick in fitting) <= room)

    def _share_out(self, index: int, without: Sequence[int]) -> None:
        """Each of these PERSONs who takes part in an OPTION takes a place they can pay for.

        They are the PERSONs with no right of their own to it. No place is taken twice.

        A PERSON who is ruled out of the OPTION needs no place. A PERSON who can pay for no
        place stays out, and an OFFER that none of them can pay for is left out. Where each of
        the others can pay for a place of every other OFFER, the places are alike, and it is
        enough to count them. Otherwise the model chooses an OFFER for each PERSON. Where a
        cap counts a purchase that one of them could make, it chooses the BUDGET too: each
        takes one of the pairs that ``reference.pairs_to_pay`` gives.
        """
        model, world, option = self.model, self.world, self.file.options[index]
        people = self.file.persons
        without = [number for number in without if (number, index) not in self.left_out]
        pairs = {
            number: reference.pairs_to_pay(self.file, world, option.id, people[number].id)
            for number in (without if self.file.caps else ())
        }
        if any(key is not None for able in pairs.values() for _, _, key, _ in able):
            # A cap counts some of these purchases, so the model chooses a BUDGET as well.
            filled: dict[str, list[cp_model.IntVar]] = {}
            for number in without:
                picks: list[cp_model.IntVar] = []
                for offer, budget, key, units in pairs[number]:
                    name = f"{people[number].id} takes a place of {offer} paid from {budget}"
                    pick = model.new_bool_var(name)
                    picks.append(pick)
                    filled.setdefault(offer, []).append(pick)
                    if key is not None:
                        self.drawn[key].append((units, pick))
                if not picks:
                    self._rule_out(number, index)
                    continue
                model.add(sum(picks) >= self.takes[number][index])
            for offer in self.file.offers(option.id):
                if len(filled.get(offer.id, ())) > offer.places:
                    model.add(sum(filled[offer.id]) <= offer.places)
            return
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
        if self.plain:
            self._keep_apart(number)
            self._take_one_of_two_apart(number)
        self.nothing.append(nothing)
        self.follows.append(follows)
        self.routes.append(between)

    def _take_one_of_two_apart(self, number: int) -> None:
        """This PERSON takes part in no OPTION that is apart from one they have to take part in.

        ``reference.NoTimeBetween`` says which two OPTIONs are apart: both start at fixed
        times in this world, and neither leaves the time to do the other after it, with the
        travel between them. ``_have_to_take`` says which OPTIONs the PERSON has to take
        part in. The path rules the other OPTION out too, but only route by route. Said
        outright, the solver sees at once that the PERSON is in no plan with it, however
        many OPTIONs with no fixed time could lie between the two on a path.

        Only the pairs with an OPTION that the PERSON has to take part in are stated. Stating
        every pair made a day of many rides slower to check, and gained nothing there.

        Like ``_keep_apart``, this is only in the model of a plain question.
        """
        takes = self.takes[number]
        theirs = self.have_to.get(self.file.persons[number].id, ())
        fixed = [
            index
            for index, terms in enumerate(self.terms)
            if terms.fixed_start is not None and (number, index) not in self.left_out
        ]
        for one in sorted(theirs):
            for other in fixed:
                if self.no_time.apart(one, other):
                    self.model.add(takes[other] == 0)

    def _keep_apart(self, number: int) -> None:
        """No two OPTIONs that this PERSON takes part in overlap.

        The path says so already: each OPTION on it starts no earlier than the one before it
        ends. Said outright, the solver sees at once that two talks that take time cannot both
        be taken at the same hour, however many others lie between them on a path. An OPTION
        that takes no time can be at the start or at the end of another one and never inside
        it, by the path and by the solver's own rule for intervals. An OPTION with no limit to
        how long it takes is left to the path.

        This is only in the model of a plain question. It helps the solver prove that nothing
        works. Where the solver looks for a best value, it made the search longer on trips
        with many OPTIONs that overlap.
        """
        model, takes = self.model, self.takes[number]
        person = self.file.persons[number]
        spans: list[cp_model.IntervalVar] = []
        for index, option in enumerate(self.file.options):
            if (number, index) in self.left_out or self.endless[index]:
                continue
            name = f"{person.id} in {option.id}"
            start, lasts = self.start[index], self.lasts[index]
            spans.append(
                model.new_optional_fixed_size_interval_var(start, lasts, takes[index], name)
            )
        if len(spans) > 1:
            model.add_no_overlap(spans)

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

        None when no route leads there, or when nobody knows how early a PERSON has to be
        there.
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
                if self.plain and self.facts:
                    # The check of the plan asks which side of each span this WAY is on.
                    self.moments[chosen.index, route, place] = moment
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
        return self.read(*self.ask())

    def ask(self) -> tuple[cp_model.CpSolver, object]:
        """The solver's answer to the plain question: does anything work?"""
        return self._solve(relax=False)

    def read(self, solver: cp_model.CpSolver, status: object) -> _Choice | None:
        """The choice in an answer to the plain question, or None where nothing works.

        The answer can be one that the solver gave for another model with the same text.
        """
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
        falls: _Falls = {}

        def takes(number: int, position: int, routes: _Taken) -> None:
            """Note the route this PERSON takes after an OPTION, and when its WAYs start."""
            for chosen, route in routes:
                if solver.boolean_value(chosen):
                    by[number, position] = route
                    for place in range(len(route)):
                        moment = self.moments.get((chosen.index, route, place))
                        if moment is not None:
                            falls[number, position, place] = solver.value(moment) + self.zero

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
                takes(number, len(order) - 1, self.routes[number].get((here, ahead[0]), []))
                order.append(ahead[0])
                here = ahead[0]
            # The route after the last OPTION.
            takes(number, len(order) - 1, self.routes[number].get((here, count), []))
            orders.append(tuple(order))
        attended = {index for order in orders for index in order}
        empty = frozenset(
            index
            for index in range(count)
            if index not in attended and solver.boolean_value(self.used[index])
        )

        def comes(index: int) -> tuple[int, int]:
            return (solver.value(self.start[index]), solver.value(self.turn[index]))

        in_order = tuple(sorted(attended | empty, key=comes))
        return self._who(orders), tuple(orders), by, falls, in_order, empty

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
        # An OPTION that somebody has to take part in happens: that is not left to choose.
        happens = {index for theirs in self.have_to.values() for index in theirs}
        open_to_choice = [index for index in range(count) if index not in happens]
        settled = self._settle([self.used[index] for index in open_to_choice])
        chosen = happens | {
            index for index, yes in zip(open_to_choice, settled, strict=True) if yes
        }

        # Each PERSON in turn: the OPTION listed first that can come next, or nothing more.
        ends = count  # the two ends of a path, as one point of its circuit
        orders: list[tuple[int, ...]] = []
        for number in range(len(file.persons)):
            only = self._only_order(number)
            if only is not None:
                orders.append(only)
                continue
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
        attended = {index for order in orders for index in order}
        return self._who(orders), tuple(orders), None, None, None, frozenset(chosen - attended)

    def _only_order(self, number: int) -> tuple[int, ...] | None:
        """The OPTIONs this PERSON does, where they have nothing to choose, or None.

        A PERSON can take part in one OPTION at most, and has to take part in it:
        ``_have_to_take`` says so. Or they can take part in none. Something works in this
        model, so they do just that, and no question about their order is put to the solver.
        """
        can = [
            index for index in range(len(self.file.options)) if (number, index) not in self.left_out
        ]
        theirs = self.have_to.get(self.file.persons[number].id, set())
        return tuple(can) if len(can) < 2 and theirs.issuperset(can) else None

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

    def _settle(self, choices: Sequence[cp_model.IntVar]) -> list[bool]:
        """Fix these yes-or-no choices: "yes" wherever it can be, the earlier choices first.

        The result says how each was fixed, in the order given.
        """
        fixed: list[bool] = []
        for begin in range(0, len(choices), _MOST_AT_ONCE):
            some = choices[begin : begin + _MOST_AT_ONCE]
            weighed = sum(each * 2 ** (len(some) - 1 - place) for place, each in enumerate(some))
            most = self._least(-weighed)
            if most is None:
                raise AssertionError("a model that had an answer has none now")
            for place, each in enumerate(some):
                yes = (-most >> (len(some) - 1 - place)) & 1
                self.model.add(each == yes)
                fixed.append(bool(yes))
        return fixed

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
