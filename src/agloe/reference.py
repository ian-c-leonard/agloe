"""The reference checker: the rules of spec/rules.md applied directly, with no solver.

It is slow on purpose and meant for small TRIPs. It defines the right answer, and anything faster
must agree with it. It refuses an ITINERARY too large for it to try everything.

Read it beside spec/rules.md. The worlds are the section "What is unknown". ``broken`` is the
section "The CONSTRAINTs": it checks a finished ITINERARY against all six, and nothing here or in
the solver counts as working unless it passes. ``itineraries`` is the section "Which ITINERARY
is shown". The sections "The three answers", "ROBUST" and "Evidence" are in ``answers``, which
works them out from this module's search or from a faster one.
"""

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from enum import Enum
from itertools import combinations, groupby, pairwise, permutations, product

from agloe.file import Complete, File

_MOST_TO_TAKE_OUT = 12  # ``needless`` tries every combination of things to take out


class Constraint(Enum):
    """The CONSTRAINTs, named by their headings in spec/rules.md."""

    LOCK = "LOCKs are honored"
    START = "Each OPTION starts when it can"
    DURATION = "Each OPTION and WAY takes as long as it takes"
    PLACE = "Each PERSON is in one place at a time"
    ARRIVAL = "Each PERSON arrives in time"
    LISTED = "A COMPLETE set is the whole set"


@dataclass(frozen=True)
class Step:
    """One thing in an ITINERARY: an OPTION that happens, or a WAY that PERSONs take.

    ``option`` names an OPTION. Otherwise the step is a WAY: ``way`` names a listed one, and both
    are None for a WAY the FILE does not list. ``end`` follows from the duration, and is None when
    nobody knows how long the step takes.
    """

    option: str | None
    origin: str
    destination: str
    persons: tuple[str, ...]
    start: int
    end: int | None
    way: str | None = None


type Itinerary = tuple[Step, ...]
type Leg = tuple[str | None, str, str]  # a WAY, or None for an unlisted one; from; to


@dataclass(frozen=True)
class Broken:
    """A CONSTRAINT an ITINERARY does not meet: at which step, for whom, by how many seconds.

    ``option`` names the OPTION where it happens. Where it happens at a WAY, ``option`` is None
    and ``taken`` says which WAY and which time it is taken: the WAY with its two PLACEs, and
    its start.
    """

    constraint: Constraint
    option: str | None
    persons: tuple[str, ...]
    late: int | None = None
    taken: tuple[Leg, int] | None = None


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

    ``unlisted`` holds the pairs of PLACEs that an unlisted WAY joins directly, and None means
    every pair. Each unlisted WAY takes ``unlisted_takes`` seconds. ``takes`` gives the shortest
    and the longest time of each listed WAY, and the longest is None when there is no limit.
    """

    terms: Mapping[str, Terms]
    unlisted: frozenset[tuple[str, str]] | None
    unlisted_takes: int = 0
    takes: Mapping[str, tuple[int, int | None]] = field(
        default_factory=dict[str, tuple[int, int | None]]
    )


@dataclass(frozen=True)
class Unknown:
    """A FACT the FILE does not state.

    ``what`` is "start", "duration" or "cutoff" for an OPTION, "duration" for a WAY, or "other
    ways" from one PLACE to another: unlisted WAYs that go straight there.
    """

    what: str
    option: str | None = None
    origin: str | None = None
    destination: str | None = None
    way: str | None = None


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
    for way in file.ways:
        if file.duration(way.id) is None:
            out.append(Unknown("duration", way=way.id))
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


def with_this_long(file: File, unknown: Unknown, seconds: int) -> World:
    """The worst case, except that one unknown length of time is exactly this many seconds.

    For other WAYs between two PLACEs, those WAYs exist and each takes this long.
    """
    kind = frozenset({unknown}) if unknown.what == "other ways" else frozenset[Unknown]()
    return _world(file, kind, pinned=(unknown, seconds))


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
    takes: dict[str, tuple[int, int | None]] = {}
    for way in file.ways:
        duration = file.duration(way.id)
        if duration is not None:
            takes[way.id] = (duration.longest if longest else duration.shortest, duration.longest)
        else:
            most = value(Unknown("duration", way=way.id))
            takes[way.id] = (most or 0, most)
    unlisted = None
    if kind is not None:
        unlisted = frozenset(
            (u.origin, u.destination)
            for u in kind
            if u.what == "other ways" and u.origin is not None and u.destination is not None
        )
    unlisted_takes = pinned[1] if pinned is not None and pinned[0].what == "other ways" else 0
    return World(terms, unlisted, unlisted_takes, takes)


# ------------------------------- The CONSTRAINTs -------------------------------


def in_world(world: World, itinerary: Itinerary) -> Itinerary:
    """The same OPTIONs, PERSONs, WAYs and start times, with each end as this world makes it.

    An end is None when the world sets no limit to how long the step takes.
    """

    def end(step: Step) -> int | None:
        if step.option is not None:
            terms = world.terms[step.option]
            return None if terms.longest is None else step.start + terms.shortest
        if step.way is None:
            return step.start + world.unlisted_takes
        shortest, longest = world.takes[step.way]
        return None if longest is None else step.start + shortest

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
    """An ITINERARY names PERSONs, PLACEs, OPTIONs and WAYs from the FILE, each OPTION once."""
    persons = {person.id for person in file.persons}
    places = {place.id for place in file.places}
    options = {option.id: option for option in file.options}
    ways = {way.id: way for way in file.ways}
    listed = [step.option for step in itinerary if step.option is not None]
    if len(listed) != len(set(listed)):
        raise ValueError("an OPTION happens at most once")
    for step in itinerary:
        named_once = len(set(step.persons)) == len(step.persons)
        if not step.persons or not named_once or not persons.issuperset(step.persons):
            raise ValueError("each step needs PERSONs from the FILE, each named once")
        ends = (step.origin, step.destination)
        if step.option is not None:
            if step.way is not None or step.option not in options:
                raise ValueError(f"{step.option} is not an OPTION in the FILE")
            if ends != (options[step.option].origin, options[step.option].destination):
                raise ValueError(f"{step.option} does not happen where the FILE says")
        elif step.way is not None:
            if step.way not in ways:
                raise ValueError(f"{step.way} is not a WAY in the FILE")
            way = ways[step.way]
            there = ends == (way.origin, way.destination)
            back = way.both_ways and ends == (way.destination, way.origin)
            if not (there or back):
                raise ValueError(f"{step.way} does not go where the FILE says")
        elif not set(ends) <= places or step.origin == step.destination:
            raise ValueError("an unlisted WAY still joins two PLACEs from the FILE")
        if step.end is not None and step.end < step.start:
            raise ValueError("a step ends before it starts")


def _where(step: Step) -> tuple[str | None, tuple[Leg, int] | None]:
    """How a Broken names a step: an OPTION by its id, a WAY by what it is and when it starts."""
    if step.option is not None:
        return step.option, None
    return None, ((step.way, step.origin, step.destination), step.start)


def _in_file_order_of_persons(file: File, persons: Iterable[str]) -> tuple[str, ...]:
    order = [person.id for person in file.persons]
    return tuple(sorted(set(persons), key=order.index))


def _gathered(
    file: File, constraint: Constraint, found: list[tuple[Step, int | None, str]]
) -> list[Broken]:
    """One Broken for each step and amount, naming every PERSON it affects in the FILE's order."""
    groups: dict[tuple[str | None, tuple[Leg, int] | None, int | None], list[str]] = {}
    for step, late, person in found:
        groups.setdefault((*_where(step), late), []).append(person)
    return [
        Broken(constraint, option, _in_file_order_of_persons(file, people), late, taken)
        for (option, taken, late), people in groups.items()
    ]


def _locks(file: File, itinerary: Itinerary) -> list[Broken]:
    """LOCKs are honored: every LOCKed OPTION happens, and the PERSONs its LOCK names take part."""
    taking_part = {step.option: step.persons for step in itinerary if step.option is not None}
    left_out: dict[str, list[str]] = {}
    for lock in file.locks:
        for person in lock.persons:
            if person not in taking_part.get(lock.option, ()):
                left_out.setdefault(lock.option, []).append(person)
    return [
        Broken(Constraint.LOCK, option, _in_file_order_of_persons(file, people))
        for option, people in left_out.items()
    ]


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
    """Each OPTION and WAY takes as long as it takes: it ends after a duration the FACTs allow."""
    out: list[Broken] = []
    for step in itinerary:
        if step.option is not None:
            terms = world.terms[step.option]
            shortest, longest = terms.shortest, terms.longest
        elif step.way is not None:
            shortest, longest = world.takes[step.way]
        else:
            shortest = longest = world.unlisted_takes
        if longest is None or step.end is None:
            fits = longest is None and step.end is None
        else:
            fits = shortest <= step.end - step.start <= longest
        if not fits:
            option, taken = _where(step)
            out.append(Broken(Constraint.DURATION, option, step.persons, None, taken))
    return out


type _Found = list[tuple[Constraint, Step, int | None]]  # which, at which step, how late


def _along_each_path(file: File, world: World, itinerary: Itinerary) -> list[Broken]:
    """The three CONSTRAINTs about what each PERSON does in order.

    The ITINERARY meets them if one of the orders its times allow works for every PERSON.
    """
    fewest: list[tuple[Constraint, Step, int | None, str]] | None = None
    for order in _in_each_order(itinerary):
        found = [
            (constraint, step, late, person.id)
            for person in file.persons
            for path in [[step for step in order if person.id in step.persons]]
            for constraint, step, late in (
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
            [(step, late, person) for which, step, late, person in fewest or [] if which is kind],
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
    """Each PERSON is in one place at a time: no overlap, and each step starts where they are."""
    found: _Found = []
    for before, after in pairwise(path):
        if before.end is None:
            found.append((Constraint.PLACE, after, None))
        elif before.end > after.start:
            found.append((Constraint.PLACE, after, before.end - after.start))
        elif before.destination != after.origin:
            found.append((Constraint.PLACE, after, None))
    return found


def _arrivals(world: World, path: list[Step]) -> _Found:
    """Each PERSON arrives in time: whoever travels to an OPTION gets there before its cutoff."""
    found: _Found = []
    arrived: Step | None = None  # the step that last brought this PERSON to a new PLACE
    for step in path:
        margin = 0 if step.option is None else world.terms[step.option].margin
        if arrived is not None and margin != 0:
            if arrived.end is None or margin is None:
                found.append((Constraint.ARRIVAL, step, None))
            elif arrived.end + margin > step.start:
                found.append((Constraint.ARRIVAL, step, arrived.end + margin - step.start))
        if step.origin != step.destination:
            arrived = step
    return found


def _listed(file: File, world: World, path: list[Step]) -> _Found:
    """A COMPLETE set is the whole set: an unlisted WAY needs a world that has it.

    No world has one that goes straight between the PLACEs of a COMPLETE FACT and starts within
    its span. The span includes both of its ends.
    """
    found: _Found = []
    for step in path:
        if step.option is not None or step.way is not None:
            continue
        here = (step.origin, step.destination)
        if world.unlisted is not None and here not in world.unlisted:
            found.append((Constraint.LISTED, step, None))
        for fact in file.facts:
            if isinstance(fact, Complete) and fact.rules_out(*here, step.start):
                found.append((Constraint.LISTED, step, None))
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
    next OPTION starts somewhere else, WAYs take them there, listed or not. The start times follow
    the rule of "Which ITINERARY is shown". Where a COMPLETE FACT rules out an unlisted WAY for a
    span of time, taking it before the span and after it are tried too. A choice works when the
    orders it names work: no other order is tried in their place.

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
    by: Mapping[tuple[int, int], Route] | None = None,
) -> Itinerary | None:
    """The ITINERARY for one choice of PERSONs and orders, or None when it breaks a CONSTRAINT.

    ``who`` names the PERSONs in each OPTION, in the FILE's order of OPTIONs. ``orders`` gives,
    for each PERSON in the FILE's order, the OPTIONs they do, by position in the FILE, in the
    order they do them. The start times are those of "Which ITINERARY is shown", and so are the
    WAYs the PERSONs take.

    With ``by``, only one choice of WAYs is tried: for a PERSON, by position in the FILE, and
    the position of an OPTION in their order, the route they take after that OPTION.
    """
    if by is not None:
        return next(_timings(file, world, who, orders, by), None)
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
        return bool(routes(file, world, before.destination, after.origin))

    for order in permutations(indexes):
        if all(can_follow(first, then) for first, then in pairwise(order)):
            yield order


type Route = tuple[Leg, ...]


def routes(file: File, world: World, here: str, there: str) -> list[Route]:
    """Every route from one PLACE to another by WAYs alone that is worth trying, shortest first.

    A route passes through no PLACE twice. A PERSON who came back to a PLACE could have waited
    there instead: every WAY they take after that starts at the same time either way, and no
    CONSTRAINT asks how they spent the wait. A listed WAY with no limit to how long it takes is
    left out, because nothing could follow it. Two unlisted WAYs in a row are left out where one
    unlisted WAY joins the same two PLACEs at any time: the one is never worse than the two.
    """
    places = [place.id for place in file.places]
    complete = [fact for fact in file.facts if isinstance(fact, Complete)]

    def joined(origin: str, destination: str) -> bool:
        return world.unlisted is None or (origin, destination) in world.unlisted

    def always_joined(origin: str, destination: str) -> bool:
        limited = any(fact.covers(origin, destination) for fact in complete)
        return joined(origin, destination) and not limited

    def onward(place: str) -> Iterator[tuple[str | None, str]]:
        for way in file.ways:
            if world.takes[way.id][1] is None:
                continue
            if way.origin == place:
                yield way.id, way.destination
            elif way.both_ways and way.destination == place:
                yield way.id, way.origin
        for other in places:
            if other != place and joined(place, other):
                yield None, other

    found: list[Route] = []

    def extend(passed: tuple[str, ...], legs: Route) -> None:
        for way, place in onward(passed[-1]):
            if place in passed:
                continue
            if way is None and legs and legs[-1][0] is None and always_joined(legs[-1][1], place):
                continue
            longer = (*legs, (way, passed[-1], place))
            if place == there:
                found.append(longer)
            else:
                extend((*passed, place), longer)

    extend((here,), ())
    return sorted(found, key=lambda route: (len(route), _legs_in_file_order(file, route)))


def _legs_in_file_order(file: File, route: Route) -> list[tuple[int, int, int]]:
    """The WAYs listed first come first, then the PLACEs listed first. Unlisted WAYs come last."""
    ways = [way.id for way in file.ways]
    places = [place.id for place in file.places]
    return [
        (len(ways) if way is None else ways.index(way), places.index(origin), places.index(to))
        for way, origin, to in route
    ]


def _schedules(
    file: File,
    world: World,
    who: tuple[tuple[str, ...], ...],
    orders: tuple[tuple[int, ...], ...],
) -> Iterator[Itinerary]:
    """The ITINERARIES for one choice of PERSONs and orders.

    Where a PERSON's next OPTION starts somewhere else, WAYs must take them there. The routes
    are tried with the fewest WAYs first, then in the order of "Which ITINERARY is shown": PERSON
    by PERSON, the WAYs listed first. Then each way the timing can fall is tried.
    """
    needed: list[tuple[int, int, list[Route]]] = []  # which PERSON, after which step, the routes
    for number, order in enumerate(orders):
        for position, (before, after) in enumerate(pairwise(order)):
            here, there = file.options[before].destination, file.options[after].origin
            if here != there:
                possible = routes(file, world, here, there)
                if not possible:
                    return
                needed.append((number, position, possible))

    def taken(chosen: tuple[Route, ...]) -> list[list[tuple[int, int, int]]]:
        """For each PERSON in turn, every WAY they take, in the order they take them."""
        each: list[list[tuple[int, int, int]]] = [[] for _ in orders]
        for (number, _, _), route in zip(needed, chosen, strict=True):
            each[number] += _legs_in_file_order(file, route)
        return each

    # The fewest and the most WAYs that the routes from each point on can take in all.
    least = [0] * (len(needed) + 1)
    greatest = [0] * (len(needed) + 1)
    for rest in reversed(range(len(needed))):
        lengths = [len(route) for route in needed[rest][2]]
        least[rest] = least[rest + 1] + min(lengths)
        greatest[rest] = greatest[rest + 1] + max(lengths)

    def with_this_many(total: int, rest: int = 0) -> Iterator[tuple[Route, ...]]:
        """Every choice of routes that takes this many WAYs in all."""
        if rest == len(needed):
            yield ()
            return
        for route in needed[rest][2]:
            left = total - len(route)
            if least[rest + 1] <= left <= greatest[rest + 1]:
                for others in with_this_many(left, rest + 1):
                    yield (route, *others)

    fewest, most = least[0], greatest[0]
    for total in range(fewest, most + 1):
        for chosen in sorted(with_this_many(total), key=taken):
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
    hops: Mapping[tuple[int, int], Route],
) -> Iterator[Itinerary]:
    """The ITINERARIES for one choice of PERSONs, orders and routes, one for each timing.

    Start times are as early as the CONSTRAINTs allow. A COMPLETE FACT rules out an unlisted WAY
    only within its span. So each unlisted WAY between the PLACEs of such a FACT is tried as it
    falls, then before the span, then after it.
    """
    listed = len(file.options)
    legs: list[tuple[str, Leg]] = []  # each WAY taken: who takes it, and which one
    lines: list[list[int]] = []  # what each PERSON does in order, the WAYs they take included
    for number, (person, order) in enumerate(zip(file.persons, orders, strict=True)):
        line: list[int] = []
        for position, index in enumerate(order):
            line.append(index)
            for leg in hops.get((number, position), ()):
                legs.append((person.id, leg))
                line.append(listed + len(legs) - 1)
        lines.append(line)

    def takes(node: int) -> int | None:
        if node < listed:
            terms = world.terms[file.options[node].id]
            return None if terms.longest is None else terms.shortest
        way = legs[node - listed][1][0]
        return world.unlisted_takes if way is None else world.takes[way][0]

    def origin(node: int) -> str:
        return legs[node - listed][1][1] if node >= listed else file.options[node].origin

    def destination(node: int) -> str:
        return legs[node - listed][1][2] if node >= listed else file.options[node].destination

    def moves(node: int) -> bool:
        return origin(node) != destination(node)

    def unlisted(node: int) -> bool:
        return node >= listed and legs[node - listed][1][0] is None

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

    count = listed + len(legs)
    if _goes_round(count, gaps):
        return  # two PERSONs would do the same OPTIONs at one instant in opposite orders
    zero = count  # one more start, pinned at time zero, to measure the spans from
    fixed: dict[int, int] = {zero: 0}
    for index, option in enumerate(file.options):
        at = world.terms[option.id].fixed_start
        if who[index] and at is not None:
            fixed[index] = at

    leaving = [
        (node, fact)
        for fact in file.facts
        if isinstance(fact, Complete)
        for node in range(listed, count)
        if unlisted(node) and fact.covers(origin(node), destination(node))
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
        for number, (person_id, (way, start_place, end_place)) in enumerate(legs):
            start = starts[listed + number]
            lasts = takes(listed + number)
            end = None if lasts is None else start + lasts
            steps[listed + number] = Step(
                None, start_place, end_place, (person_id,), start, end, way
            )
        paths = [[steps[node] for node in line] for line in lines]
        if any(
            [*_places(path), *_arrivals(world, path), *_listed(file, world, path)] for path in paths
        ):
            continue
        itinerary = tuple(
            sorted(
                _together(file, steps.values()), key=lambda step: _step_in_file_order(file, step)
            )
        )
        if _locks(file, itinerary) or _starts(world, itinerary) or _durations(world, itinerary):
            continue
        yield itinerary


def _together(file: File, steps: Iterable[Step]) -> list[Step]:
    """The steps, with PERSONs who take the same WAY at the same time shown as one step.

    A PERSON who takes the same WAY twice in one instant still has two steps.
    """
    order = [person.id for person in file.persons]
    merged: list[Step] = []
    for step in steps:
        for place, other in enumerate(merged):
            same = replace(other, persons=step.persons) == step
            if same and not set(step.persons) & set(other.persons):
                persons = tuple(sorted((*other.persons, *step.persons), key=order.index))
                merged[place] = replace(other, persons=persons)
                break
        else:
            merged.append(step)
    return merged


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
    """Earlier steps first, then the FILE's order of OPTIONs, WAYs, PERSONs and PLACEs."""
    options = [option.id for option in file.options]
    ways = [way.id for way in file.ways]
    people = [person.id for person in file.persons]
    places = [place.id for place in file.places]
    if step.option is not None:
        index = options.index(step.option)
    else:
        index = len(options) + (len(ways) if step.way is None else ways.index(step.way))
    persons = tuple(people.index(person) for person in step.persons)
    origin, destination = places.index(step.origin), places.index(step.destination)
    end = -1 if step.end is None else step.end
    return (step.start, index, persons, origin, destination, end)


type _Shown = tuple[int, list[int], tuple[tuple[int, ...], ...], list[_StepOrder]]


def _in_file_order(file: File, itinerary: Itinerary, orders: tuple[tuple[int, ...], ...]) -> _Shown:
    """The order of "Which ITINERARY is shown" among ITINERARIES that tie on its first two rules.

    Fewest OPTIONs; then the OPTIONs listed first in the FILE; then, PERSON by PERSON, the
    OPTIONs each one does, in the order they do them, with the OPTIONs listed first coming first.
    The WAYs are already those listed first: ``scheduled`` gives one ITINERARY for each order.
    """
    options = [option.id for option in file.options]
    used = sorted(options.index(step.option) for step in itinerary if step.option is not None)
    steps = [_step_in_file_order(file, step) for step in itinerary]
    return (len(used), used, orders, steps)


def first_shown(file: File, world: World) -> Itinerary | None:
    """The ITINERARY that "Which ITINERARY is shown" puts first in this world, if any works."""
    found = itineraries(file, world)
    return found[0] if found else None


def any_works(file: File, world: World) -> bool:
    """Whether any ITINERARY works in this world."""
    return bool(itineraries(file, world))
