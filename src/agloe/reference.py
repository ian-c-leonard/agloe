"""The reference checker: the rules of spec/rules.md applied directly, with no solver.

It is slow on purpose and meant for small TRIPs. It defines the right answer, and anything faster
must agree with it. It refuses an ITINERARY too large for it to try everything.

Read it beside spec/rules.md. ``broken`` is the section "The CONSTRAINTs". ``itineraries`` is
the section "Which ITINERARY is shown". ``check`` is the sections "The three answers", "ROBUST"
and "Evidence".
"""

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, replace
from enum import Enum
from itertools import combinations, groupby, pairwise, permutations, product

from agloe.file import Complete, File

_MOST_TO_TAKE_OUT = 12  # ``needless`` tries every combination of things to take out


class Constraint(Enum):
    """The CONSTRAINTs, named by their headings in spec/rules.md."""

    LOCK = "LOCKs are honored"
    START = "Each OPTION starts when it can"
    DURATION = "Each OPTION takes as long as it takes"
    PLACE = "Each PERSON is in one place at a time"
    ARRIVAL = "Each PERSON arrives in time"
    LISTED = "A COMPLETE set is the whole set"


class Answer(Enum):
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    UNDETERMINED = "UNDETERMINED"


@dataclass(frozen=True)
class Step:
    """One OPTION in an ITINERARY: who takes part and when it starts.

    ``option`` is None for an OPTION the FILE does not list. ``end`` follows from the duration, and
    is None when nobody knows how long the OPTION takes.
    """

    option: str | None
    origin: str
    destination: str
    persons: tuple[str, ...]
    start: int
    end: int | None


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
    """What a world says about one OPTION.

    With no ``fixed_start``, ``free_start`` says whether it can start at any time; if not, nobody
    knows when it starts. ``longest`` is None when there is no limit to how long it can take.
    ``margin`` is the access cutoff, and None when there is no limit to how early a PERSON must
    arrive.
    """

    fixed_start: int | None
    free_start: bool
    shortest: int
    longest: int | None
    margin: int | None


@dataclass(frozen=True)
class World:
    """One way the unknown FACTs turn out, or the worst of all the ways at once.

    ``ways`` holds the pairs of PLACEs that unlisted OPTIONs join directly, and None means every
    pair. A pair has as many unlisted OPTIONs as the PERSONs need. Each takes ``way_takes``
    seconds, starts at any time and has no access cutoff.
    """

    terms: Mapping[str, Terms]
    ways: frozenset[tuple[str, str]] | None
    way_takes: int = 0


@dataclass(frozen=True)
class Unknown:
    """A FACT the FILE does not state.

    ``what`` is "start", "duration" or "cutoff" for an OPTION, or "other ways" from one PLACE to
    another: unlisted OPTIONs that go straight there, as many as the PERSONs need.
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
    """The answer and its evidence.

    FEASIBLE: the ITINERARY shown, the FACTs and DECISIONs it relies on, whether it is ROBUST, and
    what it breaks when every CONTINGENT duration runs longest. INFEASIBLE: FACTs and DECISIONs
    that conflict. UNDETERMINED: each smallest set of unknown FACTs that would be enough.
    """

    answer: Answer
    itinerary: Itinerary = ()
    relies_on: tuple[str, ...] = ()
    robust: bool | None = None
    at_worst: tuple[Broken, ...] = ()
    conflict: tuple[str, ...] = ()
    missing: tuple[tuple[Missing, ...], ...] = ()


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
                out.append(Unknown("other ways", origin=origin.id, destination=destination.id))
    return tuple(out)


def best_case(file: File) -> World:
    """The possible world in which every unknown FACT turns out as well as it can."""
    return _world(file, None)


def worst_case(file: File) -> World:
    """Every unknown FACT at its worst. What works here works in every possible world."""
    return _world(file, frozenset())


def longest_case(file: File) -> World:
    """The worst case, with every CONTINGENT duration at its longest value."""
    return _world(file, frozenset(), longest=True)


def with_these_at_best(file: File, unknown: Iterable[Unknown]) -> World:
    """These unknown FACTs as in the best case, and every other unknown FACT as in the worst."""
    return _world(file, frozenset(unknown))


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
        start = file.start(option.id)
        duration = file.duration(option.id)
        cutoff = file.cutoff(option.id)
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
            if u.what == "other ways" and u.origin is not None and u.destination is not None
        )
    takes = pinned[1] if pinned is not None and pinned[0].what == "other ways" else 0
    return World(terms, ways, takes)


# ------------------------------- The CONSTRAINTs -------------------------------


def in_world(world: World, itinerary: Itinerary) -> Itinerary:
    """The same OPTIONs, PERSONs and start times, with each end as this world makes it.

    An end is None when the world sets no limit to how long the OPTION takes.
    """

    def end(step: Step) -> int | None:
        if step.option is None:
            return step.start + world.way_takes
        terms = world.terms[step.option]
        return None if terms.longest is None else step.start + terms.shortest

    return tuple(replace(step, end=end(step)) for step in itinerary)


def broken(file: File, world: World, itinerary: Itinerary) -> list[Broken]:
    """The CONSTRAINTs this ITINERARY does not meet in this world. An empty list means it works."""
    _well_formed(file, itinerary)
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
        named_once = len(set(step.persons)) == len(step.persons)
        if not step.persons or not named_once or not persons.issuperset(step.persons):
            raise ValueError("each step needs PERSONs from the FILE, each named once")
        if step.option is None:
            if not {step.origin, step.destination} <= places:
                raise ValueError("an unlisted OPTION still joins PLACEs from the FILE")
        elif step.option not in options:
            raise ValueError(f"{step.option} is not an OPTION in the FILE")
        else:
            option = options[step.option]
            if (step.origin, step.destination) != (option.origin, option.destination):
                raise ValueError(f"{step.option} does not happen where the FILE says")
        if step.end is not None and step.end < step.start:
            raise ValueError("a step ends before it starts")


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
    """The three CONSTRAINTs about what each PERSON does in order.

    The ITINERARY meets them if one of the orders its times allow works for every PERSON.
    """
    fewest: list[tuple[Constraint, str | None, int | None, str]] | None = None
    for order in _in_each_order(itinerary):
        found = [
            (constraint, option, late, person.id)
            for person in file.persons
            for path in [[step for step in order if person.id in step.persons]]
            for constraint, option, late in (
                *_places(path),
                *_arrivals(world, path),
                *_listed(file, world, path),
            )
        ]
        if fewest is None or len(found) < len(fewest):
            fewest = found
        if not found:
            break
    return [
        broken
        for kind in (Constraint.PLACE, Constraint.ARRIVAL, Constraint.LISTED)
        for broken in _gathered(
            file,
            kind,
            [
                (option, late, person)
                for which, option, late, person in fewest or []
                if which is kind
            ],
        )
    ]


def _in_each_order(itinerary: Itinerary) -> Iterator[list[Step]]:
    """The steps of an ITINERARY, in each order that their times allow.

    Steps that take no time and share an instant can happen in any order. The order is one order
    for the whole ITINERARY, so every PERSON sees those steps happen in the same order. Only the
    order among steps that share a PERSON, directly or through other steps, can matter, so only
    those are tried in every order. The orders are made one at a time.
    """

    def moment(step: Step) -> tuple[int, bool, int]:
        return (step.start, step.end is None, step.end or 0)

    groups: list[list[Step]] = []
    for _, steps in groupby(sorted(itinerary, key=moment), key=moment):
        same = list(steps)
        instant = same[0].end == same[0].start
        groups += _sharing_persons(same) if instant else [[step] for step in same]

    chosen = [tuple(group) for group in groups]
    choices = [number for number, group in enumerate(groups) if len(group) > 1]
    orders = [permutations(groups[number]) for number in choices]
    for place, number in enumerate(choices):
        chosen[number] = next(orders[place])
    while True:
        yield [step for steps in chosen for step in steps]
        # Move on like a mileage counter: the last group that has another order takes it, and
        # every group after it starts again from its first order.
        place = len(choices) - 1
        while place >= 0:
            following = next(orders[place], None)
            if following is not None:
                chosen[choices[place]] = following
                break
            orders[place] = permutations(groups[choices[place]])
            chosen[choices[place]] = next(orders[place])
            place -= 1
        else:
            return


def _sharing_persons(steps: list[Step]) -> list[list[Step]]:
    """These steps in groups: two steps are in one group when PERSONs link them."""
    groups: list[list[Step]] = []
    for step in steps:
        linked = [
            group for group in groups if any(set(step.persons) & set(o.persons) for o in group)
        ]
        for group in linked:
            groups.remove(group)
        groups.append([member for group in linked for member in group] + [step])
    return groups


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
    """A COMPLETE set is the whole set: an unlisted OPTION needs a world that has it.

    No world has one on a way between the PLACEs of a COMPLETE FACT that leaves within its span.
    The span includes both of its ends, and a way counts only if it reaches the second PLACE.
    """
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


# ------------------------------- Which ITINERARY is shown -------------------------------


def needless(file: File, world: World, itinerary: Itinerary) -> list[tuple[str | None, str]]:
    """What could be taken out of an ITINERARY that works: each an OPTION and a PERSON in it.

    It tries every combination of PERSONs in OPTIONs that no LOCK requires, with all the times
    left as they are. An empty list means the ITINERARY works without none of them.
    """
    locked = {(lock.option, person) for lock in file.locks for person in lock.persons}
    free = [
        (index, person)
        for index, step in enumerate(itinerary)
        for person in step.persons
        if (step.option, person) not in locked
    ]
    if len(free) > _MOST_TO_TAKE_OUT:
        raise ValueError("this ITINERARY is too large for the reference checker")
    for size in range(1, len(free) + 1):
        for out in combinations(free, size):
            smaller: list[Step] = []
            for index, step in enumerate(itinerary):
                staying = tuple(person for person in step.persons if (index, person) not in out)
                if staying:
                    smaller.append(replace(step, persons=staying))
            if not broken(file, world, tuple(smaller)):
                return [(itinerary[index].option, person) for index, person in out]
    return []


def itineraries(file: File, world: World) -> list[Itinerary]:
    """The ITINERARIES that work in this world with PERSONs taking part the fewest times.

    It tries every choice of who takes part in which OPTION and in what order. Where a PERSON's
    next OPTION starts somewhere else, unlisted OPTIONs take them there. The start times follow
    the rule of "Which ITINERARY is shown". Where a COMPLETE FACT covers a span of leaving times,
    leaving before the span and leaving after it are tried too. A choice works when the orders
    it names work: no other order is tried in their place.

    Nothing can be taken out of an ITINERARY in which PERSONs take part the fewest times, so
    ``needless`` finds nothing in any ITINERARY returned. They come in the order of "Which
    ITINERARY is shown".
    """
    best: list[tuple[_Shown, Itinerary]] = []
    fewest: int | None = None
    for who in _who_takes_part(file, world):
        if fewest is not None and sum(len(persons) for persons in who) > fewest:
            break
        mine = [
            [i for i, persons in enumerate(who) if person.id in persons] for person in file.persons
        ]
        for orders in product(*(list(_orders(file, world, indexes)) for indexes in mine)):
            found = scheduled(file, world, who, orders)
            if found is None:
                continue
            taking_part = sum(len(step.persons) for step in found)
            if fewest is None or taking_part < fewest:
                best, fewest = [], taking_part
            if taking_part == fewest:
                best.append((_in_file_order(file, found, orders), found))
    shown: list[Itinerary] = []
    for _, found in sorted(best, key=lambda each: each[0]):
        if found not in shown:
            shown.append(found)
    return shown


def scheduled(
    file: File,
    world: World,
    who: tuple[tuple[str, ...], ...],
    orders: tuple[tuple[int, ...], ...],
) -> Itinerary | None:
    """The ITINERARY for one choice of PERSONs and orders, or None when that choice does not work.

    ``who`` names the PERSONs in each OPTION, in the FILE's order of OPTIONs. ``orders`` gives,
    for each PERSON in the FILE's order, the OPTIONs they do, by position in the FILE, in the
    order they do them. The start times are those of "Which ITINERARY is shown".
    """
    return next(_schedules(file, world, who, orders), None)


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
        if before.destination == after.origin:
            return True
        return bool(_routes(file, world, before.destination, after.origin))

    for order in permutations(indexes):
        if all(can_follow(first, then) for first, then in pairwise(order)):
            yield order


type _Route = tuple[tuple[str, str], ...]  # unlisted OPTIONs one after another: from, to


def _routes(file: File, world: World, here: str, there: str) -> list[_Route]:
    """The ways to get from one PLACE to another by unlisted OPTIONs alone, shortest first.

    A direct unlisted OPTION is never worse than a way through other PLACEs, so where the world
    has one, it is the only route. Otherwise every route that visits no PLACE twice is given.
    """
    if world.ways is None or (here, there) in world.ways:
        return [((here, there),)]
    places = [place.id for place in file.places]
    found: list[tuple[str, ...]] = []

    def extend(visited: tuple[str, ...]) -> None:
        for place in places:
            if place in visited or (visited[-1], place) not in (world.ways or ()):
                continue
            if place == there:
                found.append((*visited, place))
            else:
                extend((*visited, place))

    extend((here,))
    found.sort(key=lambda visited: (len(visited), [places.index(place) for place in visited]))
    return [tuple(pairwise(visited)) for visited in found]


def _schedules(
    file: File,
    world: World,
    who: tuple[tuple[str, ...], ...],
    orders: tuple[tuple[int, ...], ...],
) -> Iterator[Itinerary]:
    """The ITINERARIES for one choice of PERSONs and orders.

    Where a PERSON's next OPTION starts somewhere else, unlisted OPTIONs must take them there.
    Each route is tried, fewest unlisted OPTIONs first, and then each way the timing can fall.
    """
    needed: list[tuple[int, int, list[_Route]]] = []  # which PERSON, after which step, the routes
    for number, order in enumerate(orders):
        for position, (before, after) in enumerate(pairwise(order)):
            here, there = file.options[before].destination, file.options[after].origin
            if here != there:
                routes = _routes(file, world, here, there)
                if not routes:
                    return
                needed.append((number, position, routes))
    every = product(*(routes for _, _, routes in needed))
    for chosen in sorted(every, key=lambda chosen: sum(len(route) for route in chosen)):
        hops = {
            (number, position): route
            for (number, position, _), route in zip(needed, chosen, strict=True)
        }
        yield from _timings(file, world, who, orders, hops)


def _timings(
    file: File,
    world: World,
    who: tuple[tuple[str, ...], ...],
    orders: tuple[tuple[int, ...], ...],
    hops: Mapping[tuple[int, int], _Route],
) -> Iterator[Itinerary]:
    """The ITINERARIES for one choice of PERSONs, orders and routes, one for each timing.

    Start times are as early as the CONSTRAINTs allow. A COMPLETE FACT covers a span of leaving
    times, and leaving outside that span can let an unlisted OPTION in. So each departure from the
    PLACE of such a FACT is tried as it falls, then before the span, then after it.
    """
    listed = len(file.options)
    ways: list[tuple[str, str, str]] = []  # the unlisted OPTIONs: who, from where, to where
    lines: list[list[int]] = []  # what each PERSON does in order, unlisted OPTIONs included
    for number, (person, order) in enumerate(zip(file.persons, orders, strict=True)):
        line: list[int] = []
        for position, index in enumerate(order):
            line.append(index)
            for start_place, end_place in hops.get((number, position), ()):
                ways.append((person.id, start_place, end_place))
                line.append(listed + len(ways) - 1)
        lines.append(line)

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
    for line in lines:
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
    if _goes_round(count, gaps):
        return  # two PERSONs would do the same OPTIONs at one instant in opposite orders
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
        steps: dict[int, Step] = {}
        for index, option in enumerate(file.options):
            if who[index]:
                lasts = takes(index)
                start = starts[index]
                end = None if lasts is None else start + lasts
                steps[index] = Step(
                    option.id, option.origin, option.destination, who[index], start, end
                )
        for number, (person_id, start_place, end_place) in enumerate(ways):
            start = starts[listed + number]
            steps[listed + number] = Step(
                None, start_place, end_place, (person_id,), start, start + world.way_takes
            )
        paths = [[steps[node] for node in line] for line in lines]
        if any(
            [*_places(path), *_arrivals(world, path), *_listed(file, world, path)] for path in paths
        ):
            continue
        yield tuple(sorted(steps.values(), key=lambda step: _step_in_file_order(file, step)))


def _goes_round(count: int, gaps: list[tuple[int, int, int]]) -> bool:
    """Whether the order these gaps give goes round in a circle."""
    waiting = [0] * count
    for _, after, _ in gaps:
        waiting[after] += 1
    ready = [node for node in range(count) if not waiting[node]]
    done = 0
    while ready:
        node = ready.pop()
        done += 1
        for before, after, _ in gaps:
            if before == node:
                waiting[after] -= 1
                if not waiting[after]:
                    ready.append(after)
    return done < count


def _times(
    count: int, gaps: list[tuple[int, int, int]], fixed: Mapping[int, int]
) -> list[int] | None:
    """Start times that keep every gap and every fixed start, or None when there are none.

    A start that comes after one already timed is as early as the gaps allow. Then a start that
    comes before one already timed is as late as they allow. Those two steps repeat until they
    time nothing more. What is left is tied to no fixed start, and counts from zero.
    """
    times: list[int | None] = [fixed.get(node) for node in range(count)]
    for _ in range(count + 1):
        moved = False
        for before, after, gap in gaps:
            base, current = times[before], times[after]
            if base is not None and (current is None or base + gap > current):
                if after in fixed:
                    return None  # something before a fixed start runs past it
                times[after] = base + gap
                moved = True
        if not moved:
            break
    else:
        return None  # the order goes round in a circle

    while True:
        untimed = {node for node in range(count) if times[node] is None}
        if not untimed:
            break
        if not _settle(gaps, times, untimed, late=True):
            return None
        still = {node for node in untimed if times[node] is None}
        if not _settle(gaps, times, still, late=False):
            return None
        if len(still) == len(untimed) and all(times[node] is None for node in still):
            for node in still:
                times[node] = 0
            if not _settle(gaps, times, still, late=False):
                return None
    return [moment for moment in times if moment is not None]


def _settle(
    gaps: list[tuple[int, int, int]], times: list[int | None], free: set[int], *, late: bool
) -> bool:
    """Time the starts in ``free`` from those already timed. False if the gaps go round in a circle.

    With ``late``, a start takes the latest time that the timed starts after it allow. Otherwise
    it takes the earliest time that the timed starts before it allow.
    """
    for _ in range(len(times) + 1):
        moved = False
        for before, after, gap in gaps:
            if late:
                limit, current = times[after], times[before]
                sooner = limit is not None and (current is None or limit - gap < current)
                if before in free and limit is not None and sooner:
                    times[before] = limit - gap
                    moved = True
            else:
                base, current = times[before], times[after]
                later = base is not None and (current is None or base + gap > current)
                if after in free and base is not None and later:
                    times[after] = base + gap
                    moved = True
        if not moved:
            return True
    return False


type _StepOrder = tuple[int, int, tuple[int, ...], int, int, int]


def _step_in_file_order(file: File, step: Step) -> _StepOrder:
    """Earlier steps first, then the FILE's order of OPTIONs, PERSONs and PLACEs."""
    options = [option.id for option in file.options]
    people = [person.id for person in file.persons]
    places = [place.id for place in file.places]
    index = len(options) if step.option is None else options.index(step.option)
    persons = tuple(people.index(person) for person in step.persons)
    origin, destination = places.index(step.origin), places.index(step.destination)
    end = -1 if step.end is None else step.end
    return (step.start, index, persons, origin, destination, end)


type _Shown = tuple[int, list[int], tuple[tuple[int, ...], ...], list[_StepOrder]]


def _in_file_order(file: File, itinerary: Itinerary, orders: tuple[tuple[int, ...], ...]) -> _Shown:
    """The order of "Which ITINERARY is shown" among ITINERARIES that tie on its first two rules.

    Fewest OPTIONs; then the OPTIONs listed first in the FILE; then, PERSON by PERSON, the
    OPTIONs each one does, in the order they do them, with the OPTIONs listed first coming first.
    """
    options = [option.id for option in file.options]
    used = sorted(
        len(options) if step.option is None else options.index(step.option) for step in itinerary
    )
    steps = [_step_in_file_order(file, step) for step in itinerary]
    return (len(itinerary), used, orders, steps)


# ------------------------------- The three answers -------------------------------


def check(file: File) -> Report:
    """The answer for this TRIP, with its evidence."""
    works = itineraries(file, worst_case(file))
    if works:
        longest = longest_case(file)
        robust = itineraries(file, longest)
        shown = robust[0] if robust else works[0]
        used = {step.option for step in shown}
        relies_on = [
            fact.id for fact in file.facts if not isinstance(fact, Complete) and fact.option in used
        ]
        relies_on += [lock.id for lock in file.locks]
        at_worst = () if robust else tuple(broken(file, longest, in_world(longest, shown)))
        return Report(Answer.FEASIBLE, shown, tuple(relies_on), bool(robust), at_worst)
    if not itineraries(file, best_case(file)):
        return Report(Answer.INFEASIBLE, conflict=_conflict(file))
    return Report(Answer.UNDETERMINED, missing=_missing(file))


def _conflict(file: File) -> tuple[str, ...]:
    """FACTs and DECISIONs that make the TRIP INFEASIBLE by themselves; none can be removed."""
    kept = file
    for record in [fact.id for fact in file.facts] + [lock.id for lock in file.locks]:
        without = kept.without(record)
        if not itineraries(without, best_case(without)):
            kept = without
    return tuple([fact.id for fact in kept.facts] + [lock.id for lock in kept.locks])


def _missing(file: File) -> tuple[tuple[Missing, ...], ...]:
    """Every smallest set of unknown FACTs that would be enough if they turned out well.

    Each set makes the TRIP FEASIBLE with every other unknown FACT at its worst. A set of one
    length of time comes with its limit.
    """
    every = unknowns(file)
    for size in range(1, len(every) + 1):
        enough = [
            some
            for some in combinations(every, size)
            if itineraries(file, _world(file, frozenset(some)))
        ]
        if enough:
            return tuple(
                tuple(Missing(u, _limit(file, u) if size == 1 else None) for u in some)
                for some in enough
            )
    raise AssertionError("the best case works, so some unknown FACTs make it work")


def _limit(file: File, unknown: Unknown) -> int | None:
    """The most seconds this one unknown can be for the TRIP to work.

    None for an unknown start, and None when any length of time would do.
    """
    if unknown.what == "start":
        return None
    kind = frozenset({unknown}) if unknown.what == "other ways" else frozenset[Unknown]()

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
