"""The COMPILER: the answers of spec/rules.md, found with a solver.

The reference checker tries every choice of PERSONs and orders. This module asks CP-SAT for the
choice instead. It then hands that choice to the reference checker's own functions, which time it
and check it against the CONSTRAINTs. So whenever this module says that something works, the
rules as the reference checker applies them have agreed.

Only the search is different. The three answers, ROBUST and the evidence are worked out by
``reference.check``, with this module's search in place of its own.

The evidence for INFEASIBLE comes from removing FACTs and DECISIONs one at a time. Each step asks
the solver to prove again that nothing works, and those proofs are slow for a TRIP of ten OPTIONs
or more.
"""

from collections.abc import Sequence

from ortools.sat.python import cp_model

from agloe import reference
from agloe.file import Complete, File
from agloe.reference import Itinerary, Report, World

_MOST_AT_ONCE = 60  # yes-or-no choices ranked in one solve: their weights must fit in 64 bits

type _Choice = tuple[tuple[tuple[str, ...], ...], tuple[tuple[int, ...], ...]]  # who, and orders
type _Flag = cp_model.IntVar | bool  # something true or false: decided by the solver, or known
type _Journey = Sequence[tuple[_Flag, _Flag]]  # for each COMPLETE FACT: on its way, by unlisted


def check(file: File) -> Report:
    """The answer for this TRIP, with its evidence. The same Report as ``reference.check``."""
    return reference.check(file, shown=shown, works=works)


def shown(file: File, world: World) -> Itinerary | None:
    """The ITINERARY that "Which ITINERARY is shown" puts first in this world, or None."""
    choice = _Search(file, world).first_in_file_order()
    return None if choice is None else _checked(file, world, choice)


def works(file: File, world: World) -> bool:
    """Whether any ITINERARY works in this world."""
    choice = _Search(file, world).any()
    if choice is not None:
        _checked(file, world, choice)
    return choice is not None


def _checked(file: File, world: World, choice: _Choice) -> Itinerary:
    """The solver's choice, timed and checked by the reference checker."""
    itinerary = reference.scheduled(file, world, *choice)
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


def _when(constraint: cp_model.Constraint, *conditions: cp_model.LiteralT) -> None:
    """Make a constraint apply only when every condition holds."""
    constraint.only_enforce_if(list(conditions))  # pyright: ignore[reportUnknownMemberType]


class _Search:
    """One world as a CP-SAT model: who takes part in which OPTION, and in what order.

    Each PERSON's OPTIONs form a path. The path is a circuit through a starting point that stands
    for "before the first OPTION and after the last". Where the next OPTION starts somewhere
    else, unlisted OPTIONs take the PERSON there, by one of the routes the world has. Start times
    exist in the model only to prove that some timing fits; the times shown come from the
    reference checker.
    """

    def __init__(self, file: File, world: World) -> None:
        self.file = file
        self.model = cp_model.CpModel()
        model = self.model
        options, persons = file.options, file.persons
        count = len(options)
        terms = [world.terms[option.id] for option in options]
        usable = [each.fixed_start is not None or each.free_start for each in terms]
        lasts = [each.shortest for each in terms]
        endless = [each.longest is None for each in terms]
        moves = [option.origin != option.destination for option in options]
        unlisted = world.ways is None or bool(world.ways)
        self.facts = [fact for fact in file.facts if isinstance(fact, Complete)] if unlisted else []
        facts = self.facts

        # The model counts time from the earliest fixed time, to keep its numbers small. Every
        # start that matters lies within ``room`` of a fixed start or of the end of a span.
        fixed = [each.fixed_start for each in terms if each.fixed_start is not None]
        spans = [moment for fact in facts for moment in (fact.earliest - 1, fact.latest + 1)]
        self.zero = min([*fixed, *spans], default=0)
        room = sum(lasts) + sum(each.margin or 0 for each in terms) + 1
        room += count * max(len(file.places), 1) * world.way_takes
        earliest, latest = -room, max([*fixed, *spans], default=0) - self.zero + room

        self.takes = [
            [model.new_bool_var(f"takes {person.id} {option.id}") for option in options]
            for person in persons
        ]
        self.used = [model.new_bool_var(f"used {option.id}") for option in options]
        self.legs: list[tuple[cp_model.IntVar, int]] = []  # a route taken, and its unlisted OPTIONs
        start = [
            model.new_int_var(earliest, latest, f"start {option.id}")
            if each.fixed_start is None
            else model.new_constant(each.fixed_start - self.zero)
            for option, each in zip(options, terms, strict=True)
        ]
        turn = [model.new_int_var(0, max(count - 1, 0), f"turn {option.id}") for option in options]
        # Whether each OPTION leaves the first PLACE of each COMPLETE FACT within its span.
        leaves: list[list[_Flag]] = [
            [
                option.origin == fact.origin
                and option.destination != fact.origin
                and self._inside(
                    start[index] if each.fixed_start is None else each.fixed_start, fact, option.id
                )
                for fact in facts
            ]
            for index, (option, each) in enumerate(zip(options, terms, strict=True))
        ]

        for index, option in enumerate(options):
            model.add_max_equality(self.used[index], [0, *(row[index] for row in self.takes)])
            locked = {
                name for lock in file.locks if lock.option == option.id for name in lock.persons
            }
            for number, person in enumerate(persons):
                # Staying somewhere changes nothing for a PERSON whom no LOCK asks to stay.
                idle = not moves[index] and person.id not in locked
                if not usable[index] or idle:
                    model.add(self.takes[number][index] == 0)
                if person.id in locked:
                    model.add(self.takes[number][index] == 1)

        home = count  # the starting point of every PERSON's circuit
        self.follows: list[dict[tuple[int, int], cp_model.IntVar]] = []
        self.nothing: list[cp_model.IntVar] = []
        for number, person in enumerate(persons):
            takes = self.takes[number]
            nothing = model.new_bool_var(f"{person.id} takes part in nothing")
            self.nothing.append(nothing)
            arcs: list[tuple[int, int, cp_model.LiteralT]] = [(home, home, nothing)]
            follows: dict[tuple[int, int], cp_model.IntVar] = {}
            # Whether this PERSON has moved by the end of an OPTION, and when they last arrived.
            # These, and the journeys below, are only ever pushed one way: towards "has moved",
            # "arrived later" and "is on the way". That way is the one that forbids more, so the
            # solver gains nothing by going further than the truth.
            moved = [model.new_bool_var(f"{person.id} moved by {o.id}") for o in options]
            arrived = [
                model.new_int_var(earliest, latest + room, f"{person.id} arrived by {o.id}")
                for o in options
            ]
            # Where this PERSON stands with each COMPLETE FACT at the end of an OPTION.
            journey = [
                [
                    (
                        model.new_bool_var(f"{person.id} on the way of {fact.id} after {o.id}"),
                        model.new_bool_var(f"{person.id} by unlisted on {fact.id} after {o.id}"),
                    )
                    for fact in facts
                ]
                for o in options
            ]

            def after_option(
                before: _Journey,
                index: int,
                when: cp_model.IntVar,
                journey: list[list[tuple[cp_model.IntVar, cp_model.IntVar]]] = journey,
            ) -> None:
                """What each COMPLETE FACT makes of a listed OPTION done under ``when``."""
                for place, fact in enumerate(facts):
                    on_the_way, by_unlisted = before[place]
                    on_the_way = self._either(on_the_way, leaves[index][place], when)
                    if options[index].destination == fact.destination:
                        self._never(by_unlisted, when)
                        on_the_way, by_unlisted = False, False
                    _when(model.add(journey[index][place][0] >= on_the_way), when)
                    _when(model.add(journey[index][place][1] >= by_unlisted), when)

            for index, option in enumerate(options):
                model.add_implication(takes[index], nothing.negated())
                arcs.append((index, index, takes[index].negated()))
                first = model.new_bool_var(f"{person.id} starts with {option.id}")
                last = model.new_bool_var(f"{person.id} ends with {option.id}")
                follows[home, index], follows[index, home] = first, last
                arcs += [(home, index, first), (index, home, last)]
                after_option([(False, False)] * len(facts), index, first)
                if moves[index]:
                    _when(model.add(moved[index] == 1), takes[index])
                    if not endless[index]:
                        _when(
                            model.add(arrived[index] >= start[index] + lasts[index]), takes[index]
                        )

            for before, earlier in enumerate(options):
                for after, later in enumerate(options):
                    if before == after or endless[before]:
                        continue
                    if not (usable[before] and usable[after]):
                        continue
                    margin = terms[after].margin
                    ready = start[before] + lasts[before]
                    if earlier.destination == later.origin:
                        next_ = model.new_bool_var(f"{person.id}: {later.id} after {earlier.id}")
                        _when(model.add(start[after] >= ready), next_)
                        if not moves[after]:
                            _when(model.add(moved[after] >= moved[before]), next_)
                            _when(model.add(arrived[after] >= arrived[before]), next_)
                        if margin is None:
                            model.add_implication(next_, moved[before].negated())
                        elif margin:
                            _when(
                                model.add(start[after] >= arrived[before] + margin),
                                next_,
                                moved[before],
                            )
                        after_option(journey[before], after, next_)
                    else:
                        possible = reference.routes(file, world, earlier.destination, later.origin)
                        if not possible or margin is None:
                            continue  # no way there, or no way to be in time after travelling
                        next_ = model.new_bool_var(f"{person.id}: {later.id} after {earlier.id}")
                        if not moves[after]:
                            _when(model.add(moved[after] == 1), next_)
                        via = [next_]
                        if len(possible) > 1:
                            via = [
                                model.new_bool_var(f"{next_.name} by route {place}")
                                for place in range(len(possible))
                            ]
                            model.add(sum(via) == next_)
                        for route, chosen in zip(possible, via, strict=True):
                            there: _Journey = journey[before]
                            free: cp_model.LinearExprT = ready
                            for place, (origin, destination) in enumerate(route):
                                name = f"{chosen.name} leg {place}"
                                moment = model.new_int_var(earliest, latest, name)
                                _when(model.add(moment >= free), chosen)
                                there = self._after_unlisted(
                                    there, origin, destination, moment, chosen
                                )
                                free = moment + world.way_takes
                            _when(model.add(start[after] >= free + margin), chosen)
                            if not moves[after]:
                                _when(model.add(arrived[after] >= free), chosen)
                            after_option(there, after, chosen)
                            self.legs.append((chosen, len(route)))
                    follows[before, after] = next_
                    arcs.append((before, after, next_))
                    _when(model.add(turn[after] >= turn[before] + 1), next_)
            model.add_circuit(arcs)
            self.follows.append(follows)

    def any(self) -> _Choice | None:
        """Some choice of PERSONs and orders that works, or None when none does."""
        solver = _solver()
        status = solver.solve(self.model)
        if status == cp_model.INFEASIBLE:
            return None
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            raise AssertionError(f"the solver stopped early: {solver.status_name(status)}")
        count = len(self.file.options)
        orders: list[tuple[int, ...]] = []
        for follows in self.follows:
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
                order.append(ahead[0])
                here = ahead[0]
            orders.append(tuple(order))
        return self._who(orders), tuple(orders)

    def first_in_file_order(self) -> _Choice | None:
        """The choice of PERSONs and orders that "Which ITINERARY is shown" puts first."""
        model, file = self.model, self.file
        count = len(file.options)
        unlisted = sum(route * length for route, length in self.legs)
        taking_part = sum(each for row in self.takes for each in row) + unlisted
        steps = sum(self.used) + unlisted
        most_steps = count + sum(length for _, length in self.legs) + 1
        fewest = self._least(taking_part * most_steps + steps)
        if fewest is None:
            return None
        model.add(taking_part * most_steps + steps == fewest)
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
        return self._who(orders), tuple(orders)

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

    def _inside(self, moment: cp_model.IntVar | int, fact: Complete, name: str) -> _Flag:
        """Whether a start falls within the span of a COMPLETE FACT, both ends included."""
        if isinstance(moment, int):
            return fact.earliest <= moment <= fact.latest
        model = self.model
        inside = model.new_bool_var(f"{name} leaves within the span of {fact.id}")
        sooner = model.new_bool_var(f"{name} leaves before the span of {fact.id}")
        _when(model.add(moment <= fact.earliest - 1 - self.zero), inside.negated(), sooner)
        _when(model.add(moment >= fact.latest + 1 - self.zero), inside.negated(), sooner.negated())
        return inside

    def _after_unlisted(
        self,
        before: _Journey,
        origin: str,
        destination: str,
        moment: cp_model.IntVar,
        when: cp_model.IntVar,
    ) -> _Journey:
        """What each COMPLETE FACT makes of one unlisted OPTION taken under ``when``.

        A PERSON on the way from the first PLACE of a FACT, who left within its span, cannot
        reach the second PLACE by an unlisted OPTION, or after one.
        """
        after: list[tuple[_Flag, _Flag]] = []
        for (on_the_way, _), fact in zip(before, self.facts, strict=True):
            if origin == fact.origin:
                on_the_way = self._either(on_the_way, self._inside(moment, fact, when.name), when)
            if destination == fact.destination:
                self._never(on_the_way, when)
                after.append((False, False))
            else:
                after.append((on_the_way, on_the_way))
        return after

    def _either(self, first: _Flag, second: _Flag, when: cp_model.IntVar) -> _Flag:
        """Something true exactly when one of two things is, wherever ``when`` holds."""
        if first is True or second is True:
            return True
        if first is False:
            return second
        if second is False:
            return first
        either = self.model.new_bool_var(f"{first.name} or {second.name}")
        _when(self.model.add(either >= first), when)
        _when(self.model.add(either >= second), when)
        return either

    def _never(self, flag: _Flag, when: cp_model.IntVar) -> None:
        """Rule out ``when`` together with something being true."""
        if flag is True:
            self.model.add(when == 0)
        elif flag is not False:
            self.model.add_implication(when, flag.negated())

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
        return round(solver.objective_value)
