"""The COMPILER: the answers of spec/rules.md, found with a solver.

The reference checker tries every choice of PERSONs and orders. This module asks CP-SAT for the
choice instead. It then hands that choice to the reference checker's own functions, which time it
and check it against the CONSTRAINTs. So whenever this module says that something works, the
rules as the reference checker applies them have agreed.

Only the search is different. The three answers, ROBUST and the evidence are worked out by
``answers.check``, with this module's search in place of the reference checker's.

For INFEASIBLE, the solver also names the FACTs and DECISIONs its proof used. The reference
checker then looks for the conflict among those alone.
"""

from collections.abc import Sequence
from dataclasses import replace

from ortools.sat.python import cp_model

from agloe import answers, reference
from agloe.answers import Report
from agloe.file import Complete, Cutoff, Duration, File, Start
from agloe.reference import Itinerary, Remaining, World

_MOST_AT_ONCE = 60  # yes-or-no choices ranked in one solve: their weights must fit in 64 bits

type _Who = tuple[tuple[str, ...], ...]  # the PERSONs in each OPTION
type _Orders = tuple[tuple[int, ...], ...]  # the OPTIONs each PERSON does, in order
type _By = dict[tuple[int, int], reference.Route]  # the WAYs a PERSON takes after an OPTION
type _Choice = tuple[_Who, _Orders, _By | None]
type _Amount = cp_model.LinearExpr | int  # seconds: a plain number, or one the solver works out


def check(file: File) -> Report:
    """The answer for this TRIP, with its evidence. The same Report as the reference checker's."""
    return answers.check(file, shown=shown, works=works, stuck=stuck)


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
    search = _Search(file, world, switched=True, unsaid=remaining.unsaid)
    records = [record.id for record in (*file.facts, *file.wants, *file.locks)]
    choice, needed = search.clash(records)
    if choice is not None:
        does = search.turned_out
        chosen = replace(world, satisfies=does, might_satisfy=does)
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
    least as quick. A WAY SATISFIES no WANT, so nothing else about a route can matter. The
    reference checker still names the WAYs of the ITINERARY shown.
    """

    def time(route: reference.Route) -> int:
        return sum(
            world.unlisted_takes if way is None else world.takes[way][0] for way, _, _ in route
        )

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

    def __init__(
        self,
        file: File,
        world: World,
        switched: bool = False,
        unsaid: frozenset[tuple[str, str]] = frozenset(),
    ) -> None:
        """Build the model. With ``switched``, each FACT and DECISION applies only if switched on.

        A FACT that is switched off is unknown, and turns out as in the best case. So the world
        must be the best case when ``switched`` is set. ``unsaid`` holds each OPTION and WANT
        about which a FACT was taken out before: nobody knows about those either, even where
        the WANT's set is COMPLETE.
        """
        self.file, self.world, self.unsaid = file, world, unsaid
        # Whether each OPTION SATISFIES each WANT, where the solver chooses the world too, and
        # how that turned out in the last answer it gave.
        self.does: dict[tuple[str, str], cp_model.IntVar] = {}
        self.turned_out: frozenset[tuple[str, str]] = frozenset()
        self.model = cp_model.CpModel()
        self.switch: dict[str, cp_model.IntVar] = {}
        if switched:
            for record in (*file.facts, *file.wants, *file.locks):
                self.switch[record.id] = self.model.new_bool_var(f"given {record.id}")
        self._read_the_world()
        self._count_time()
        self._choose_who_takes_part()
        self.follows: list[dict[tuple[int, int], cp_model.IntVar]] = []
        self.nothing: list[cp_model.IntVar] = []
        # For each PERSON, the routes between two OPTIONs in different PLACEs, each with the
        # choice that takes it.
        self.routes: list[dict[tuple[int, int], list[tuple[cp_model.IntVar, reference.Route]]]] = []
        self.legs: list[tuple[cp_model.IntVar, int]] = []  # a route taken, and how many WAYs it has
        self.known = reference.Routes(file, world)
        self._worth_trying: dict[tuple[str, str], list[reference.Route]] = {}
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
        self.way_lasts: dict[str | None, _Amount] = {None: world.unlisted_takes}
        for way in file.ways:
            given = switch_of(file.duration(way.id))
            shortest = world.takes[way.id][0]
            self.way_lasts[way.id] = shortest if given is None else shortest * given
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
        self.zero = min([*fixed, *spans], default=0)
        room = sum(each.shortest for each in terms) + sum(each.margin or 0 for each in terms) + 1
        slowest = max([world.unlisted_takes, *(shortest for shortest, _ in world.takes.values())])
        room += len(options) * max(len(self.file.places), 1) * slowest
        self.room = room
        self.earliest, self.latest = -room, max([*fixed, *spans], default=0) - self.zero + room

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
                    model.add(takes == 0)
                elif not self.moves[index] and not wanted:
                    switches = [each for each in asking if each is not None]
                    if len(switches) == len(asking):
                        model.add_bool_or([takes.negated(), *switches])

    def _hold_to_the_wants(self) -> list[set[int]]:
        """Every must is met and every must-not is kept. Returns what could meet a must.

        That is, for each PERSON, the OPTIONs that could meet a must of theirs.
        """
        if self.switch:
            return self._hold_to_the_wants_with_switches()
        model, file, world = self.model, self.file, self.world
        meets: list[set[int]] = [set() for _ in file.persons]
        for want in file.wants:
            for index, option in enumerate(file.options):
                if (option.id, want.id) in world.might_satisfy:
                    for number, person in enumerate(file.persons):
                        if person.id in want.must_nots:
                            model.add(self.takes[number][index] == 0)
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
        for want in file.wants:
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
        """One PERSON's path: a circuit through a starting point and the OPTIONs they do.

        ``moved`` says whether the PERSON has moved by the end of an OPTION, and ``arrived``
        when they last arrived. These are only ever pushed one way: towards "has moved" and
        "arrived later". That way is the one that forbids more, so the solver gains nothing by
        going further than the truth.
        """
        model, options = self.model, self.file.options
        person, takes = self.file.persons[number], self.takes[number]
        home = len(options)  # the starting point of the circuit
        nothing = model.new_bool_var(f"{person.id} takes part in nothing")
        arcs: list[tuple[int, int, cp_model.LiteralT]] = [(home, home, nothing)]
        follows: dict[tuple[int, int], cp_model.IntVar] = {}
        between: dict[tuple[int, int], list[tuple[cp_model.IntVar, reference.Route]]] = {}
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
            follows[home, index], follows[index, home] = first, last
            arcs += [(home, index, first), (index, home, last)]
            if self.moves[index]:
                _when(model.add(moved[index] == 1), takes[index])
                if not self.endless[index]:
                    done = self.start[index] + self.lasts[index]
                    _when(model.add(arrived[index] >= done), takes[index])

        for before, earlier in enumerate(options):
            for after, later in enumerate(options):
                if before == after or self.endless[before]:
                    continue
                if not (self.usable[before] and self.usable[after]):
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
    ) -> tuple[cp_model.IntVar, list[tuple[cp_model.IntVar, reference.Route]]] | None:
        """The choice that a PERSON goes from one OPTION to the next by WAYs, and by which route.

        None when no route leads there, or when no PERSON who travels could be in time.
        """
        model, options, margin = self.model, self.file.options, self.margins[after]
        possible = self._routes(options[before].destination, options[after].origin)
        if not possible or margin is None:
            return None
        next_ = model.new_bool_var(name)
        if not self.moves[after]:
            _when(model.add(moved[after] == 1), next_)
        via = [next_]
        if len(possible) > 1:
            via = [model.new_bool_var(f"{name} by route {place}") for place in range(len(possible))]
            model.add(sum(via) == next_)
        for route, chosen in zip(possible, via, strict=True):
            free: _Amount = self.start[before] + self.lasts[before]
            for place, (way, origin, destination) in enumerate(route):
                moment = model.new_int_var(self.earliest, self.latest, f"{chosen.name} leg {place}")
                _when(model.add(moment >= free), chosen)
                if way is None:
                    self._outside_every_span(moment, origin, destination, chosen)
                free = moment + self.way_lasts[way]
            _when(model.add(self.start[after] >= free + margin), chosen)
            if not self.moves[after]:
                _when(model.add(arrived[after] >= free), chosen)
            self.legs.append((chosen, len(route)))
        return next_, list(zip(via, possible, strict=True))

    def _routes(self, here: str, there: str) -> list[reference.Route]:
        """The routes from one PLACE to another worth choosing between, worked out once.

        Where no COMPLETE FACT can rule a WAY out and no FACT can be switched off, only the time
        and the number of WAYs of a route matter, so the quickest of each length is enough.
        """
        if (here, there) not in self._worth_trying:
            possible = self.known.between(here, there)
            if not self.facts and not self.switch:
                possible = _quickest(self.world, possible)
            self._worth_trying[here, there] = possible
        return self._worth_trying[here, there]

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
        solver = _solver()
        status = solver.solve(self.model)
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
        solver = _solver()
        status = solver.solve(self.model)
        if status == cp_model.INFEASIBLE:
            return None
        return self._found(solver, status)

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
        home = count
        orders: list[tuple[int, ...]] = []
        for number in range(len(file.persons)):
            follows = self.follows[number]
            order: list[int] = []
            here = home
            while True:
                stop = self.nothing[number] if here == home else follows[here, home]
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
        solver = _solver()
        status = solver.solve(self.model)
        self.model.clear_objective()
        if status == cp_model.INFEASIBLE:
            return None
        if status != cp_model.OPTIMAL:
            raise AssertionError(f"the solver stopped early: {solver.status_name(status)}")
        return solver.value(amount)
