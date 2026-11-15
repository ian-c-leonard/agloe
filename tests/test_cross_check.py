"""The reference checker's shortcuts, checked the slow way on many small random TRIPs.

The rules page makes two claims that save the checker from trying everything. Starting each OPTION
as early as possible is enough to find an ITINERARY if one exists. The best case and the worst
case are enough to settle the answer for every possible world. These tests try the things the
shortcuts skip.
"""

from itertools import combinations, product
from random import Random

from agloe.file import File
from agloe.reference import (
    Answer,
    Step,
    Terms,
    World,
    best_case,
    broken,
    check,
    itineraries,
    worst_case,
)
from tests.stories import (
    Document,
    any_time,
    cutoff,
    lasts,
    lock,
    moves,
    seconds,
    starts_at,
    stays,
    trip,
)

QUARTER = 900
PLACES = ["a", "b", "c"]


def random_trip(
    rng: Random,
    leave_out: float,
    persons: list[str] | None = None,
    count: int | None = None,
    complete: float = 0,
) -> File:
    """Two or three OPTIONs on a quarter-hour grid.

    ``leave_out`` is how often a FACT is unstated. ``complete`` is how often a COMPLETE FACT is
    added. Its span starts one second after a grid time and ends one second before another, so
    the times just outside it are on the grid.
    """
    count = count or rng.choice([2, 3])
    if persons is None:
        persons = ["alex", "sam"] if rng.random() < (0.4 if count == 2 else 0.25) else ["alex"]
    options: list[Document] = []
    facts: list[Document] = []
    decisions: list[Document] = []
    free = 0
    for number in range(count):
        id = f"option-{number}"
        origin = rng.choice(PLACES)
        elsewhere = rng.choice([place for place in PLACES if place != origin])
        options.append(stays(id, origin) if rng.random() < 0.35 else moves(id, origin, elsewhere))
        if rng.random() < 0.55 or free == 2:
            quarter = rng.randrange(4)
            start = starts_at(id, 9, 15 * quarter)
        else:
            start = any_time(id)
            free += 1
        stated = [
            start,
            lasts(id, f"PT{15 * rng.randrange(2)}M"),
            cutoff(id, f"PT{15 * rng.randrange(2)}M"),
        ]
        facts += [fact for fact in stated if rng.random() >= leave_out]
        if rng.random() < 0.6:
            decisions.append(lock(id, *rng.sample(persons, rng.randrange(1, len(persons) + 1))))
    if rng.random() < complete:
        origin = rng.choice(PLACES)
        destination = rng.choice([place for place in PLACES if place != origin])
        first = rng.randrange(4)
        last = rng.randrange(first + 1, 9)
        leaving = {
            "earliest": at_second(seconds(9) + QUARTER * first + 1),
            "latest": at_second(seconds(9) + QUARTER * last - 1),
        }
        ways = {"from": origin, "to": destination, "leaving": leaving}
        facts.append({"id": "ways", "complete": ways})
    return trip(persons, PLACES, options, facts, decisions)


def at_second(moment: int) -> str:
    """A time on the day of the stories, to the second."""
    into_day = moment - seconds(0)
    hour, rest = divmod(into_day, 3600)
    return f"2027-05-15T{hour:02d}:{rest // 60:02d}:{rest % 60:02d}-05:00[America/Chicago]"


def works_on_the_grid(file: File) -> bool:
    """Whether any ITINERARY works, trying every start on the grid. Every FACT must be stated."""
    world = worst_case(file)
    people = [person.id for person in file.persons]
    groups = [group for size in range(len(people) + 1) for group in combinations(people, size)]
    grid = [seconds(9) + QUARTER * quarter for quarter in range(-6, 10)]
    for who in product(groups, repeat=len(file.options)):
        if any(
            not set(found.persons) <= set(who[file.options.index(file.option(found.option))])
            for found in file.locks
        ):
            continue
        taking = [(option, group) for option, group in zip(file.options, who, strict=True) if group]
        fixed = {option.id: world.terms[option.id].fixed_start for option, _ in taking}
        free = [id for id, moment in fixed.items() if moment is None]
        for times in product(grid, repeat=len(free)):
            chosen = dict(zip(free, times, strict=True))
            steps: list[Step] = []
            for option, group in taking:
                start = fixed[option.id]
                if start is None:
                    start = chosen[option.id]
                end = start + world.terms[option.id].shortest
                steps.append(Step(option.id, option.origin, option.destination, group, start, end))
            if not broken(file, world, tuple(steps)):
                return True
    return False


def a_shared_ride(rng: Random) -> File:
    """Alex and Sam may share a ride from a to b, then each has their own plans at b.

    One PERSON's fixed time then decides when the ride leaves, and the other's plans follow.
    """
    options = [moves("ride", "a", "b"), stays("first", "b"), stays("second", "b")]
    facts: list[Document] = []
    decisions: list[Document] = []
    free = 0
    for option in options:
        id = option["id"]
        if rng.random() < 0.5 or free == 2:
            quarter = rng.randrange(6)
            facts.append(starts_at(id, 9 + quarter // 4, 15 * (quarter % 4)))
        else:
            facts.append(any_time(id))
            free += 1
        facts += [
            lasts(id, f"PT{15 * rng.randrange(2)}M"),
            cutoff(id, f"PT{15 * rng.randrange(2)}M"),
        ]
        who = rng.choice([["alex"], ["sam"], ["alex", "sam"]])
        if id == "ride" or rng.random() < 0.8:
            decisions.append(lock(id, *who))
    return trip(["alex", "sam"], PLACES, options, facts, decisions)


def test_starting_as_early_as_possible_finds_an_itinerary_whenever_one_exists() -> None:
    rng = Random(2027)
    answers: set[bool] = set()
    trips = [random_trip(rng, leave_out=0) for _ in range(150)]
    trips += [a_shared_ride(rng) for _ in range(150)]
    for file in trips:
        report = check(file)
        feasible = report.answer is Answer.FEASIBLE
        assert feasible == works_on_the_grid(file)
        if feasible:
            assert broken(file, worst_case(file), report.itinerary) == []
        answers.add(feasible)
    assert answers == {True, False}


def works_in_the_best_case_on_the_grid(file: File) -> bool:
    """Whether any ITINERARY works in the best case, trying every start on the grid.

    For one PERSON and two OPTIONs. It also tries one unlisted OPTION between any two PLACES.
    """
    world = best_case(file)
    person = file.persons[0].id
    grid = [seconds(9) + QUARTER * quarter for quarter in range(-4, 11)]
    hops: list[Step | None] = [None]
    hops += [
        Step(None, origin, destination, (person,), moment, moment)
        for origin in PLACES
        for destination in PLACES
        if origin != destination
        for moment in grid
    ]
    for taking in product([False, True], repeat=len(file.options)):
        options = [option for option, taken in zip(file.options, taking, strict=True) if taken]
        fixed = {option.id: world.terms[option.id].fixed_start for option in options}
        free = [id for id, moment in fixed.items() if moment is None]
        for times in product(grid, repeat=len(free)):
            chosen = dict(zip(free, times, strict=True))
            steps: list[Step] = []
            for option in options:
                start = fixed[option.id]
                if start is None:
                    start = chosen[option.id]
                end = start + world.terms[option.id].shortest
                steps.append(
                    Step(option.id, option.origin, option.destination, (person,), start, end)
                )
            for hop in hops if len(options) == 2 else [None]:
                if not broken(file, world, (*steps, hop) if hop else tuple(steps)):
                    return True
    return False


def two_places_with_no_listed_way(rng: Random) -> File:
    """Alex is LOCKed on two OPTIONs in different PLACES, and the FILE lists no way between them.

    A COMPLETE FACT usually covers the ways between those PLACES for some span. Whether an
    unlisted OPTION can still join them depends on when Alex can leave.
    """
    facts: list[Document] = []
    for id, quarters in (("first", range(4)), ("second", range(2, 9))):
        quarter = rng.choice(quarters)
        start = starts_at(id, 9 + quarter // 4, 15 * (quarter % 4))
        stated = [
            start if rng.random() < 0.7 else any_time(id),
            lasts(id, f"PT{15 * rng.randrange(2)}M"),
            cutoff(id, f"PT{15 * rng.randrange(2)}M"),
        ]
        facts += [fact for fact in stated if rng.random() >= 0.15]
    if rng.random() < 0.85:
        first = rng.randrange(5)
        leaving = {
            "earliest": at_second(seconds(9) + QUARTER * first + 1),
            "latest": at_second(seconds(9) + QUARTER * rng.randrange(first + 1, 10) - 1),
        }
        facts.append({"id": "ways", "complete": {"from": "a", "to": "b", "leaving": leaving}})
    options = [stays("first", "a"), stays("second", "b")]
    return trip(["alex"], PLACES, options, facts, [lock("first", "alex"), lock("second", "alex")])


def test_the_best_case_search_misses_no_itinerary() -> None:
    """INFEASIBLE means nothing works in the best case. Check that against trying everything."""
    rng = Random(42)
    answers: set[bool] = set()
    trips = [random_trip(rng, 0.3, persons=["alex"], count=2, complete=0.7) for _ in range(80)]
    trips += [two_places_with_no_listed_way(rng) for _ in range(200)]
    for file in trips:
        infeasible = check(file).answer is Answer.INFEASIBLE
        assert infeasible != works_in_the_best_case_on_the_grid(file)
        answers.add(infeasible)
    assert answers == {True, False}


def possible_world(rng: Random, file: File) -> World:
    """One way the unknown FACTs could turn out, chosen at random."""
    terms: dict[str, Terms] = {}
    for option in file.options:
        start, duration, margin = (
            file.start(option.id),
            file.duration(option.id),
            file.cutoff(option.id),
        )
        if start is not None:
            fixed, free = start.at, start.at is None
        elif rng.random() < 0.5:
            fixed, free = None, True
        else:
            fixed, free = seconds(9) + QUARTER * rng.randrange(4), False
        lasts_for = QUARTER * rng.choice([0, 1, 2, 40])
        least, most = (
            (duration.shortest, duration.longest)
            if duration is not None
            else (lasts_for, lasts_for)
        )
        needs = margin.margin if margin is not None else QUARTER * rng.choice([0, 1, 2, 40])
        terms[option.id] = Terms(fixed, free, least, most, needs)
    pairs = [(a, b) for a in PLACES for b in PLACES if a != b]
    ways = frozenset(pair for pair in pairs if rng.random() < 0.3)
    return World(terms, ways, QUARTER * rng.choice([0, 1, 2]))


def test_the_best_and_worst_cases_settle_the_answer_for_every_possible_world() -> None:
    rng = Random(1970)
    answers: set[Answer] = set()
    for _ in range(300):
        file = random_trip(rng, leave_out=0.3)
        report = check(file)
        answers.add(report.answer)
        for _ in range(8):
            world = possible_world(rng, file)
            if report.answer is Answer.FEASIBLE:
                as_it_happens = tuple(
                    step
                    if step.option is None or step.end is not None
                    else Step(
                        step.option,
                        step.origin,
                        step.destination,
                        step.persons,
                        step.start,
                        step.start + world.terms[step.option].shortest,
                    )
                    for step in report.itinerary
                )
                assert broken(file, world, as_it_happens) == []
            elif report.answer is Answer.INFEASIBLE:
                assert itineraries(file, world) == []
    assert answers == set(Answer)
