"""The reference checker: the CONSTRAINTs of spec/rules.md applied directly, with no solver.

It is slow on purpose and meant for small TRIPs. It defines the right answer, and anything faster
must agree with it.

Read it beside spec/rules.md. ``broken`` is the section "The CONSTRAINTs". ``check`` is the
sections "The three answers", "ROBUST", "Which ITINERARY is shown" and "Evidence".
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from enum import Enum
from itertools import combinations, groupby, pairwise, permutations, product

from agloe.file import Complete, File, Option

_MOST_TO_DROP = 12  # "Nothing happens without need" tries every way to take things out


class Constraint(Enum):
    """The CONSTRAINTs, named by their headings in spec/rules.md."""

    LOCK = "LOCKs are honored"
    START = "Each OPTION starts when it can"
    DURATION = "Each OPTION takes as long as it takes"
    PLACE = "Each PERSON is in one place at a time"
    ARRIVAL = "Each PERSON arrives in time"
    LISTED = "A COMPLETE set is the whole set"
    NEED = "Nothing happens without need"


class Answer(Enum):
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    UNDETERMINED = "UNDETERMINED"


@dataclass(frozen=True)
class Step:
    """One OPTION as it happens in an ITINERARY."""

    option: str | None  # None: an OPTION the FILE does not list
    origin: str
    destination: str
    persons: tuple[str, ...]
    start: int
    end: int | None  # None: nobody knows how long it takes


type Itinerary = tuple[Step, ...]


@dataclass(frozen=True)
class Broken:
    """A CONSTRAINT an ITINERARY does not meet: at which OPTION, for whom, by how many seconds."""

    constraint: Constraint
    option: str | None
    persons: tuple[str, ...]
    late: int | None = None


@dataclass(frozen=True)
class Terms:
    """What a world says about one OPTION."""

    fixed_start: int | None  # it can start only then
    free_start: bool  # it can start at any time; false with no fixed start means nobody knows when
    shortest: int
    longest: int | None  # None: there is no limit to how long it can take
    margin: (
        int | None
    )  # the access cutoff; None: there is no limit to how early a PERSON must arrive


@dataclass(frozen=True)
class World:
    """One way the unknown FACTs turn out, or the worst of all the ways at once."""

    terms: Mapping[str, Terms]
    ways: (
        frozenset[tuple[str, str]] | None
    )  # pairs of PLACEs an unlisted OPTION joins; None: every pair
    way_takes: int = 0  # how long an unlisted OPTION takes


@dataclass(frozen=True)
class Unknown:
    """A FACT the FILE does not state.

    ``what`` is "start", "duration" or "cutoff" for an OPTION, or "another way" between two PLACEs.
    """

    what: str
    option: str | None = None
    origin: str | None = None
    destination: str | None = None


@dataclass(frozen=True)
class Missing:
    """An unknown FACT the answer depends on, and the most seconds it can be for a FEASIBLE TRIP."""

    unknown: Unknown
    at_most: int | None


@dataclass(frozen=True)
class Report:
    answer: Answer
    itinerary: Itinerary = ()  # FEASIBLE: the ITINERARY shown
    relies_on: tuple[str, ...] = ()  # FEASIBLE: the FACTs and DECISIONs it relies on
    robust: bool | None = None  # FEASIBLE: whether the ITINERARY shown is ROBUST
    at_worst: tuple[
        Broken, ...
    ] = ()  # FEASIBLE: what breaks when every CONTINGENT duration runs longest
    conflict: tuple[str, ...] = ()  # INFEASIBLE: FACTs and DECISIONs that conflict
    missing: tuple[Missing, ...] = ()  # UNDETERMINED: the unknown FACTs it depends on


# ------------------------------- What is unknown -------------------------------


def unknowns(file: File) -> tuple[Unknown, ...]:
    """Every FACT the FILE leaves out, in the FILE's order."""
    out: list[Unknown] = []
    for option in file.options:
        if file.start(option.id) is None:
            out.append(Unknown("start", option.id))
        if file.duration(option.id) is None:
            out.append(Unknown("duration", option.id))
        if file.cutoff(option.id) is None:
            out.append(Unknown("cutoff", option.id))
    for origin in file.places:
        for destination in file.places:
            if origin != destination:
                out.append(Unknown("another way", origin=origin.id, destination=destination.id))
    return tuple(out)


def best_case(file: File) -> World:
    """The possible world in which every unknown FACT turns out as well as it can."""
    return _world(file, None)


def worst_case(file: File) -> World:
    """Every unknown FACT at its worst. What works here works in every possible world."""
    return _world(file, frozenset())


def _world(
    file: File,
    kind: frozenset[Unknown] | None,
    *,
    longest: bool = False,
    pinned: tuple[Unknown, int] | None = None,
) -> World:
    """A world in which the unknowns in ``kind`` turn out well and the rest badly.

    With ``kind`` None, every unknown turns out well. ``longest`` gives every CONTINGENT duration
    its longest value. ``pinned`` gives one unknown an exact value.
    """

    def well(unknown: Unknown) -> bool:
        return kind is None or unknown in kind

    def value(unknown: Unknown) -> int | None:
        if pinned is not None and pinned[0] == unknown:
            return pinned[1]
        return 0 if well(unknown) else None

    terms: dict[str, Terms] = {}
    for option in file.options:
        start, duration, cutoff = (
            file.start(option.id),
            file.duration(option.id),
            file.cutoff(option.id),
        )
        if start is not None:
            fixed, free = start.at, start.at is None
        else:
            fixed, free = None, well(Unknown("start", option.id))
        if duration is not None:
            most: int | None = duration.longest
            least = duration.longest if longest else duration.shortest
        else:
            most = value(Unknown("duration", option.id))
            least = most or 0
        margin = cutoff.margin if cutoff is not None else value(Unknown("cutoff", option.id))
        terms[option.id] = Terms(fixed, free, least, most, margin)
    ways = None
    if kind is not None:
        ways = frozenset(
            (u.origin, u.destination)
            for u in kind
            if u.what == "another way" and u.origin is not None and u.destination is not None
        )
    takes = pinned[1] if pinned is not None and pinned[0].what == "another way" else 0
    return World(terms, ways, takes)


# ------------------------------- The CONSTRAINTs -------------------------------


def broken(file: File, world: World, itinerary: Itinerary) -> list[Broken]:
    """The CONSTRAINTs this ITINERARY does not meet in this world. An empty list means it works."""
    _well_formed(file, itinerary)
    return _broken_before_need(file, world, itinerary) or _needless(file, world, itinerary)


def _broken_before_need(file: File, world: World, itinerary: Itinerary) -> list[Broken]:
    return [
        *_locks(file, itinerary),
        *_starts(world, itinerary),
        *_durations(world, itinerary),
        *_along_each_path(file, world, itinerary),
    ]


def _well_formed(file: File, itinerary: Itinerary) -> None:
    """An ITINERARY names PERSONs, PLACEs and OPTIONs from the FILE, each OPTION at most once."""
    persons = {person.id for person in file.persons}
    places = {place.id for place in file.places}
    options = {option.id: option for option in file.options}
    listed = [step.option for step in itinerary if step.option is not None]
    if len(listed) != len(set(listed)):
        raise ValueError("an OPTION happens at most once")
    for step in itinerary:
        if (
            not step.persons
            or len(set(step.persons)) != len(step.persons)
            or not persons.issuperset(step.persons)
        ):
            raise ValueError("each step needs PERSONs from the FILE, each named once")
        if step.option is None:
            if not {step.origin, step.destination} <= places:
                raise ValueError("an unlisted OPTION still joins PLACEs from the FILE")
        elif step.option not in options:
            raise ValueError(f"{step.option} is not an OPTION in the FILE")
        elif (step.origin, step.destination) != (
            options[step.option].origin,
            options[step.option].destination,
        ):
            raise ValueError(f"{step.option} does not happen where the FILE says")
        if step.end is not None and step.end < step.start:
            raise ValueError("a step ends before it starts")


def _paths(itinerary: Itinerary, person: str) -> Iterator[list[Step]]:
    """What one PERSON does, in each order that their times allow.

    Steps that take no time and share an instant can happen in any order.
    """

    def moment(step: Step) -> tuple[int, bool, int]:
        return (step.start, step.end is None, step.end or 0)

    mine = sorted((step for step in itinerary if person in step.persons), key=moment)
    together = [list(steps) for _, steps in groupby(mine, key=moment)]
    orders = [
        list(permutations(steps)) if steps[0].end == steps[0].start else [tuple(steps)]
        for steps in together
    ]
    for order in product(*orders):
        yield [step for steps in order for step in steps]


def _gathered(
    file: File, constraint: Constraint, found: list[tuple[str | None, int | None, str]]
) -> list[Broken]:
    """One Broken for each OPTION and amount, naming every PERSON it affects in the FILE's order."""
    groups: dict[tuple[str | None, int | None], list[str]] = {}
    for option, late, person in found:
        groups.setdefault((option, late), []).append(person)
    order = [person.id for person in file.persons]
    return [
        Broken(constraint, option, tuple(sorted(set(people), key=order.index)), late)
        for (option, late), people in groups.items()
    ]


def _locks(file: File, itinerary: Itinerary) -> list[Broken]:
    """LOCKs are honored: every LOCKed OPTION happens, and the PERSONs its LOCK names take part."""
    taking_part = {step.option: step.persons for step in itinerary if step.option is not None}
    found: list[tuple[str | None, int | None, str]] = [
        (lock.option, None, person)
        for lock in file.locks
        for person in lock.persons
        if person not in taking_part.get(lock.option, ())
    ]
    return _gathered(file, Constraint.LOCK, found)


def _starts(world: World, itinerary: Itinerary) -> list[Broken]:
    """Each OPTION starts when it can: at its fixed start, or at any time if a FACT says so."""
    out: list[Broken] = []
    for step in itinerary:
        if step.option is None:
            continue
        terms = world.terms[step.option]
        fits = terms.free_start if terms.fixed_start is None else step.start == terms.fixed_start
        if not fits:
            out.append(Broken(Constraint.START, step.option, step.persons))
    return out


def _durations(world: World, itinerary: Itinerary) -> list[Broken]:
    """Each OPTION takes as long as it takes: it ends after a duration the FACTs allow."""
    out: list[Broken] = []
    for step in itinerary:
        if step.option is None:
            fits = step.end == step.start + world.way_takes
        else:
            terms = world.terms[step.option]
            if terms.longest is None or step.end is None:
                fits = terms.longest is None and step.end is None
            else:
                fits = terms.shortest <= step.end - step.start <= terms.longest
        if not fits:
            out.append(Broken(Constraint.DURATION, step.option, step.persons))
    return out


type _Found = list[tuple[Constraint, str | None, int | None]]  # which, at which OPTION, how late


def _along_each_path(file: File, world: World, itinerary: Itinerary) -> list[Broken]:
    """The three CONSTRAINTs about what one PERSON does in order.

    A PERSON's path works if one of the orders their times allow meets all three.
    """
    by_constraint: dict[Constraint, list[tuple[str | None, int | None, str]]] = {
        Constraint.PLACE: [],
        Constraint.ARRIVAL: [],
        Constraint.LISTED: [],
    }
    for person in file.persons:
        fewest: _Found | None = None
        for path in _paths(itinerary, person.id):
            found = [*_places(path), *_arrivals(world, path), *_listed(file, world, path)]
            if fewest is None or len(found) < len(fewest):
                fewest = found
            if not found:
                break
        for constraint, option, late in fewest or []:
            by_constraint[constraint].append((option, late, person.id))
    return [
        broken
        for constraint, found in by_constraint.items()
        for broken in _gathered(file, constraint, found)
    ]


def _places(path: list[Step]) -> _Found:
    """Each PERSON is in one place at a time: no overlap, and each OPTION starts where they are."""
    found: _Found = []
    for before, after in pairwise(path):
        if before.end is None:
            found.append((Constraint.PLACE, after.option, None))
        elif before.end > after.start:
            found.append((Constraint.PLACE, after.option, before.end - after.start))
        elif before.destination != after.origin:
            found.append((Constraint.PLACE, after.option, None))
    return found


def _arrivals(world: World, path: list[Step]) -> _Found:
    """Each PERSON arrives in time: whoever travels to an OPTION gets there before its cutoff."""
    found: _Found = []
    arrived: Step | None = None  # the step that last brought this PERSON to a new PLACE
    for step in path:
        margin = 0 if step.option is None else world.terms[step.option].margin
        if arrived is not None and margin != 0:
            if arrived.end is None or margin is None:
                found.append((Constraint.ARRIVAL, step.option, None))
            elif arrived.end + margin > step.start:
                found.append((Constraint.ARRIVAL, step.option, arrived.end + margin - step.start))
        if step.origin != step.destination:
            arrived = step
    return found


def _listed(file: File, world: World, path: list[Step]) -> _Found:
    """A COMPLETE set is the whole set: an unlisted OPTION needs a world that has it."""
    found: _Found = []
    for step in path:
        here = (step.origin, step.destination)
        if step.option is None and world.ways is not None and here not in world.ways:
            found.append((Constraint.LISTED, None, None))
    for fact in file.facts:
        if not isinstance(fact, Complete):
            continue
        for first, step in enumerate(path):
            leaves = step.origin == fact.origin and step.destination != fact.origin
            if not (leaves and fact.earliest <= step.start <= fact.latest):
                continue
            for last in range(first, len(path)):
                if path[last].destination == fact.destination:
                    if any(part.option is None for part in path[first : last + 1]):
                        found.append((Constraint.LISTED, None, None))
                    break
    return found


def _needless(file: File, world: World, itinerary: Itinerary) -> list[Broken]:
    """Nothing happens without need: taking out what no LOCK requires breaks another CONSTRAINT."""
    locked = {(lock.option, person) for lock in file.locks for person in lock.persons}
    free = [
        (index, person)
        for index, step in enumerate(itinerary)
        for person in step.persons
        if (step.option, person) not in locked
    ]
    if len(free) > _MOST_TO_DROP:
        raise ValueError("this ITINERARY is too large for the reference checker")
    for size in range(1, len(free) + 1):
        for dropped in combinations(free, size):
            smaller: list[Step] = []
            for index, step in enumerate(itinerary):
                staying = tuple(person for person in step.persons if (index, person) not in dropped)
                if staying:
                    smaller.append(replace(step, persons=staying))
            if not _broken_before_need(file, world, tuple(smaller)):
                index, person = dropped[0]
                return [Broken(Constraint.NEED, itinerary[index].option, (person,))]
    return []


# ------------------------------- Finding ITINERARIES -------------------------------


def itineraries(file: File, world: World) -> list[Itinerary]:
    """The ITINERARIES that work in this world with the fewest PERSONs taking part in OPTIONs.

    It tries every choice of who takes part in which OPTION and in what order. An unlisted OPTION
    is used only to join two listed ones. Each OPTION starts as early as the CONSTRAINTs allow, and
    one with nothing before it starts as late as they allow. Where a COMPLETE FACT covers a span of
    leaving times, leaving before the span and leaving after it are tried too. An ITINERARY with
    the fewest PERSONs taking part cannot have anything taken out, so every ITINERARY returned
    also meets "Nothing happens without need".
    """
    best: list[Itinerary] = []
    fewest: int | None = None
    for who in _who_takes_part(file, world):
        if fewest is not None and sum(len(persons) for persons in who) > fewest:
            break
        mine = [
            [i for i, persons in enumerate(who) if person.id in persons] for person in file.persons
        ]
        for orders in product(*(list(_orders(file, world, indexes)) for indexes in mine)):
            for found in _schedules(file, world, who, orders):
                if _broken_before_need(file, world, found):
                    continue
                taking_part = sum(len(step.persons) for step in found)
                if fewest is None or taking_part < fewest:
                    best, fewest = [found], taking_part
                elif taking_part == fewest and found not in best:
                    best.append(found)
                break
    return sorted(best, key=lambda itinerary: _in_file_order(file, itinerary))


def _who_takes_part(file: File, world: World) -> list[tuple[tuple[str, ...], ...]]:
    """Every choice of PERSONs for every OPTION that honors the LOCKs, fewest PERSONs first."""
    people = [person.id for person in file.persons]
    choices: list[list[tuple[str, ...]]] = []
    for option in file.options:
        must = {
            person for lock in file.locks if lock.option == option.id for person in lock.persons
        }
        terms = world.terms[option.id]
        can_happen = terms.fixed_start is not None or terms.free_start
        groups = [group for size in range(len(people) + 1) for group in combinations(people, size)]
        choices.append(
            [group for group in groups if must.issubset(group) and (can_happen or not group)]
        )
    return sorted(product(*choices), key=lambda who: sum(len(persons) for persons in who))


def _orders(file: File, world: World, indexes: list[int]) -> Iterator[tuple[int, ...]]:
    """Every order in which one PERSON could do their OPTIONs."""

    def can_follow(first: int, then: int) -> bool:
        before, after = file.options[first], file.options[then]
        early, late = world.terms[before.id].fixed_start, world.terms[after.id].fixed_start
        if early is not None and late is not None and early > late:
            return False
        joined = world.ways is None or (before.destination, after.origin) in world.ways
        return before.destination == after.origin or joined

    for order in permutations(indexes):
        if all(can_follow(first, then) for first, then in pairwise(order)):
            yield order


def _schedules(
    file: File,
    world: World,
    who: tuple[tuple[str, ...], ...],
    orders: tuple[tuple[int, ...], ...],
) -> Iterator[Itinerary]:
    """The ITINERARIES for one choice of PERSONs and orders, one for each way the timing can fall.

    Start times are as early as the CONSTRAINTs allow. A COMPLETE FACT covers a span of leaving
    times, and leaving outside that span can let an unlisted OPTION in. So each departure from the
    PLACE of such a FACT is tried as it falls, then before the span, then after it.
    """
    listed = len(file.options)
    ways: list[tuple[str, str, str]] = []  # the unlisted OPTIONs: who, from where, to where

    def takes(node: int) -> int | None:
        if node >= listed:
            return world.way_takes
        terms = world.terms[file.options[node].id]
        return None if terms.longest is None else terms.shortest

    def origin(node: int) -> str:
        return ways[node - listed][1] if node >= listed else file.options[node].origin

    def moves(node: int) -> bool:
        if node >= listed:
            return True
        return file.options[node].origin != file.options[node].destination

    gaps: list[tuple[int, int, int]] = []  # (before, after, least seconds between their starts)
    for person, order in zip(file.persons, orders, strict=True):
        line: list[int] = []
        here: str | None = None
        for index in order:
            option: Option = file.options[index]
            if here is not None and here != option.origin:
                ways.append((person.id, here, option.origin))
                line.append(listed + len(ways) - 1)
            line.append(index)
            here = option.destination
        arrived: int | None = None  # the step that last brought this PERSON to a new PLACE
        for position, node in enumerate(line):
            if position:
                lasts = takes(line[position - 1])
                if lasts is None:
                    return
                gaps.append((line[position - 1], node, lasts))
            margin = 0 if node >= listed else world.terms[file.options[node].id].margin
            if arrived is not None and margin != 0:
                lasts = takes(arrived)
                if lasts is None or margin is None:
                    return
                gaps.append((arrived, node, lasts + margin))
            if moves(node):
                arrived = node

    count = listed + len(ways)
    zero = count  # one more start, pinned at time zero, to measure the spans from
    fixed: dict[int, int] = {zero: 0}
    for index, option in enumerate(file.options):
        at = world.terms[option.id].fixed_start
        if who[index] and at is not None:
            fixed[index] = at

    happening = [node for node in range(count) if node >= listed or who[node]]
    leaving = [
        (node, fact)
        for fact in file.facts
        if isinstance(fact, Complete) and ways
        for node in happening
        if moves(node) and origin(node) == fact.origin
    ]
    for choice in product(("as it falls", "before", "after"), repeat=len(leaving)):
        outside: list[tuple[int, int, int]] = []
        for (node, fact), when in zip(leaving, choice, strict=True):
            if when == "after":
                outside.append((zero, node, fact.latest + 1))
            elif when == "before":
                outside.append((node, zero, 1 - fact.earliest))
        starts = _times(count + 1, [*gaps, *outside], fixed)
        if starts is None:
            continue
        steps: list[Step] = []
        for index, option in enumerate(file.options):
            if who[index]:
                lasts = takes(index)
                end = None if lasts is None else starts[index] + lasts
                steps.append(
                    Step(
                        option.id, option.origin, option.destination, who[index], starts[index], end
                    )
                )
        for number, (person_id, start_place, end_place) in enumerate(ways):
            start = starts[listed + number]
            steps.append(
                Step(None, start_place, end_place, (person_id,), start, start + world.way_takes)
            )
        yield tuple(sorted(steps, key=lambda step: _step_in_file_order(file, step)))


def _times(
    count: int, gaps: list[tuple[int, int, int]], fixed: Mapping[int, int]
) -> list[int] | None:
    """Start times that keep every gap and every fixed start, or None when there are none.

    Each start is as early as the gaps allow. A start with nothing before it is as late as they
    allow.
    """
    early: list[int | None] = [fixed.get(node) for node in range(count)]
    for _ in range(count + 1):
        moved = False
        for before, after, gap in gaps:
            base, current = early[before], early[after]
            if base is not None and (current is None or base + gap > current):
                if after in fixed:
                    return None  # something before a fixed start runs past it
                early[after] = base + gap
                moved = True
        if not moved:
            break
    else:
        return None  # the order goes round in a circle

    late = list(early)
    for _ in range(count + 1):
        moved = False
        for before, after, gap in gaps:
            limit, current = late[after], late[before]
            if (
                early[before] is None
                and limit is not None
                and (current is None or limit - gap < current)
            ):
                late[before] = limit - gap
                moved = True
        if not moved:
            break
    else:
        return None

    # What is left has nothing to hurry it. It follows whatever comes before it, and counts from
    # zero if nothing does.
    starts = [0 if moment is None else moment for moment in late]
    for _ in range(count + 1):
        moved = False
        for before, after, gap in gaps:
            if late[after] is None and starts[before] + gap > starts[after]:
                starts[after] = starts[before] + gap
                moved = True
        if not moved:
            return starts
    return None


def _step_in_file_order(file: File, step: Step) -> tuple[int, int, str, str, tuple[int, ...], int]:
    options = [option.id for option in file.options]
    people = [person.id for person in file.persons]
    index = len(options) if step.option is None else options.index(step.option)
    persons = tuple(people.index(person) for person in step.persons)
    return (
        step.start,
        index,
        step.origin,
        step.destination,
        persons,
        -1 if step.end is None else step.end,
    )


def _in_file_order(
    file: File, itinerary: Itinerary
) -> tuple[int, list[int], list[tuple[int, int, str, str, tuple[int, ...], int]]]:
    """Fewest OPTIONs first, then the ITINERARIES that use the OPTIONs listed first in the FILE."""
    options = [option.id for option in file.options]
    used = sorted(
        len(options) if step.option is None else options.index(step.option) for step in itinerary
    )
    return (len(itinerary), used, [_step_in_file_order(file, step) for step in itinerary])


# ------------------------------- The three answers -------------------------------


def check(file: File) -> Report:
    """The answer for this TRIP, with its evidence."""
    works = itineraries(file, worst_case(file))
    if works:
        longest = _world(file, frozenset(), longest=True)
        robust = itineraries(file, longest)
        shown = robust[0] if robust else works[0]
        used = {step.option for step in shown}
        relies_on = [
            fact.id for fact in file.facts if not isinstance(fact, Complete) and fact.option in used
        ]
        relies_on += [lock.id for lock in file.locks]
        at_worst = () if robust else tuple(broken(file, longest, _running_longest(longest, shown)))
        return Report(Answer.FEASIBLE, shown, tuple(relies_on), bool(robust), at_worst)
    if not itineraries(file, best_case(file)):
        return Report(Answer.INFEASIBLE, conflict=_conflict(file))
    return Report(Answer.UNDETERMINED, missing=_missing(file))


def _running_longest(longest: World, itinerary: Itinerary) -> Itinerary:
    """The same OPTIONs at the same start times, with every CONTINGENT duration at its longest."""
    return tuple(
        step
        if step.option is None
        else replace(step, end=step.start + longest.terms[step.option].shortest)
        for step in itinerary
    )


def _conflict(file: File) -> tuple[str, ...]:
    """FACTs and DECISIONs that make the TRIP INFEASIBLE by themselves; none can be removed."""
    kept = file
    for record in [fact.id for fact in file.facts] + [lock.id for lock in file.locks]:
        without = kept.without(record)
        if not itineraries(without, best_case(without)):
            kept = without
    return tuple([fact.id for fact in kept.facts] + [lock.id for lock in kept.locks])


def _missing(file: File) -> tuple[Missing, ...]:
    """The fewest unknown FACTs that would have to turn out well for the TRIP to be FEASIBLE."""
    every = unknowns(file)
    for size in range(1, len(every) + 1):
        for some in combinations(every, size):
            if itineraries(file, _world(file, frozenset(some))):
                return tuple(
                    Missing(unknown, _limit(file, unknown) if size == 1 else None)
                    for unknown in some
                )
    raise AssertionError("the best case works, so some unknown FACTs make it work")


def _limit(file: File, unknown: Unknown) -> int | None:
    """The most seconds this one unknown can be for the TRIP to work. None for an unknown start."""
    if unknown.what == "start":
        return None
    kind = frozenset({unknown}) if unknown.what == "another way" else frozenset[Unknown]()

    def works(seconds: int) -> bool:
        return bool(itineraries(file, _world(file, kind, pinned=(unknown, seconds))))

    over = 1
    while works(over):
        over *= 2
        if over > 2**40:
            return None  # it works however long this takes
    under = over // 2
    while over - under > 1:
        middle = (under + over) // 2
        under, over = (middle, over) if works(middle) else (under, middle)
    return under
