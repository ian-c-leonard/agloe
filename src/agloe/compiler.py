"""The COMPILER: the answers of spec/rules.md, found with a solver.

The reference checker tries every choice of PERSONs and orders. This module asks CP-SAT for the
choice instead. It then hands that choice to the reference checker's own functions, which time it
and check it against the CONSTRAINTs. So every ITINERARY shown here has passed the rules as the
reference checker applies them.

The solver decides FEASIBLE and ROBUST and picks the ITINERARY shown. The other two answers and
their evidence still come from the reference checker.
"""

from collections.abc import Sequence

from ortools.sat.python import cp_model

from agloe import reference
from agloe.file import Complete, File
from agloe.reference import Answer, Itinerary, Report, World

_MOST_AT_ONCE = 60  # yes-or-no choices ranked in one solve: their weights must fit in 64 bits


def check(file: File) -> Report:
    """The answer for this TRIP, with its evidence. The same Report as ``reference.check``."""
    works = shown(file, reference.worst_case(file))
    if works is None:
        return reference.check(file)
    longest = reference.longest_case(file)
    robust = shown(file, longest)
    itinerary = works if robust is None else robust
    used = {step.option for step in itinerary}
    relies_on = [
        fact.id for fact in file.facts if not isinstance(fact, Complete) and fact.option in used
    ]
    relies_on += [lock.id for lock in file.locks]
    at_worst = (
        tuple(reference.broken(file, longest, reference.in_world(longest, itinerary)))
        if robust is None
        else ()
    )
    return Report(Answer.FEASIBLE, itinerary, tuple(relies_on), robust is not None, at_worst)


def shown(file: File, world: World) -> Itinerary | None:
    """The ITINERARY that "Which ITINERARY is shown" picks in this world, or None if none works.

    The world must hold no unlisted OPTIONs.
    """
    if world.ways is None or world.ways:
        raise ValueError("this search does not handle unlisted OPTIONs yet")
    choice = _Search(file, world).first_in_file_order()
    if choice is None:
        return None
    who, orders = choice
    itinerary = reference.scheduled(file, world, who, orders)
    if itinerary is None or reference.broken(file, world, itinerary):
        raise AssertionError("the solver chose PERSONs and orders that the rules refuse")
    return itinerary


def _when(constraint: cp_model.Constraint, *conditions: cp_model.LiteralT) -> None:
    """Make a constraint apply only when every condition holds."""
    constraint.only_enforce_if(list(conditions))  # pyright: ignore[reportUnknownMemberType]


class _Search:
    """One world as a CP-SAT model: who takes part in which OPTION, and in what order.

    Each PERSON's OPTIONs form a path. The path is a circuit through a starting point that stands
    for "before the first OPTION and after the last". Start times exist in the model only to
    prove that some timing fits; the times shown come from the reference checker.
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

        fixed = [each.fixed_start for each in terms if each.fixed_start is not None]
        room = sum(lasts) + sum(each.margin or 0 for each in terms) + 1
        earliest, latest = min([0, *fixed]) - room, max([0, *fixed]) + room

        self.takes = [
            [model.new_bool_var(f"takes {person.id} {option.id}") for option in options]
            for person in persons
        ]
        self.used = [model.new_bool_var(f"used {option.id}") for option in options]
        start = [
            model.new_int_var(earliest, latest, f"start {option.id}")
            if each.fixed_start is None
            else model.new_constant(each.fixed_start)
            for option, each in zip(options, terms, strict=True)
        ]
        turn = [model.new_int_var(0, max(count - 1, 0), f"turn {option.id}") for option in options]

        for index, option in enumerate(options):
            model.add_max_equality(self.used[index], [0, *(row[index] for row in self.takes)])
            locked = {
                name for lock in file.locks if lock.option == option.id for name in lock.persons
            }
            for number, person in enumerate(persons):
                if not usable[index]:
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
            moved = [model.new_bool_var(f"{person.id} moved by {o.id}") for o in options]
            arrived = [
                model.new_int_var(earliest, latest + room, f"{person.id} arrived by {o.id}")
                for o in options
            ]
            for index, option in enumerate(options):
                model.add_implication(takes[index], nothing.negated())
                arcs.append((index, index, takes[index].negated()))
                first = model.new_bool_var(f"{person.id} starts with {option.id}")
                last = model.new_bool_var(f"{person.id} ends with {option.id}")
                follows[home, index], follows[index, home] = first, last
                arcs += [(home, index, first), (index, home, last)]
                if moves[index]:
                    _when(model.add(moved[index] == 1), takes[index])
                    if not endless[index]:
                        _when(
                            model.add(arrived[index] == start[index] + lasts[index]), takes[index]
                        )
                else:
                    _when(model.add(moved[index] == 0), first)
            for before, earlier in enumerate(options):
                for after, later in enumerate(options):
                    joined = earlier.destination == later.origin
                    if before == after or not joined or endless[before]:
                        continue
                    if not (usable[before] and usable[after]):
                        continue
                    next_ = model.new_bool_var(f"{person.id}: {later.id} after {earlier.id}")
                    follows[before, after] = next_
                    arcs.append((before, after, next_))
                    _when(model.add(start[after] >= start[before] + lasts[before]), next_)
                    _when(model.add(turn[after] >= turn[before] + 1), next_)
                    if not moves[after]:
                        _when(model.add(moved[after] == moved[before]), next_)
                        _when(model.add(arrived[after] == arrived[before]), next_)
                    margin = terms[after].margin
                    if margin is None:
                        model.add_implication(next_, moved[before].negated())
                    elif margin:
                        _when(
                            model.add(start[after] >= arrived[before] + margin),
                            next_,
                            moved[before],
                        )
            model.add_circuit(arcs)
            self.follows.append(follows)

    def first_in_file_order(
        self,
    ) -> tuple[tuple[tuple[str, ...], ...], tuple[tuple[int, ...], ...]] | None:
        """The choice of PERSONs and orders that "Which ITINERARY is shown" puts first."""
        model, file = self.model, self.file
        count = len(file.options)
        taking_part = sum(each for row in self.takes for each in row)
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
        who = tuple(
            tuple(
                person.id for number, person in enumerate(file.persons) if index in orders[number]
            )
            for index in range(count)
        )
        return who, tuple(orders)

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
        solver = cp_model.CpSolver()
        solver.parameters.num_workers = 1
        status = solver.solve(self.model)
        self.model.clear_objective()
        if status == cp_model.INFEASIBLE:
            return None
        if status != cp_model.OPTIMAL:
            raise AssertionError(f"the solver stopped early: {solver.status_name(status)}")
        return round(solver.objective_value)

    def _solve(self) -> cp_model.CpSolver:
        solver = cp_model.CpSolver()
        solver.parameters.num_workers = 1
        status = solver.solve(self.model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            raise AssertionError(f"the solver found no answer: {solver.status_name(status)}")
        return solver
