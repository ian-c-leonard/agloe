"""The reference checker's shortcuts, checked the slow way on many small random TRIPs.

The rules page makes two claims that save the checker from trying everything. Starting each OPTION
as early as possible is enough to find an ITINERARY if one exists. The best case and the worst
case are enough to settle the answer for every possible world. These tests try the things the
shortcuts skip.
"""

from itertools import combinations, product
from random import Random

from agloe.file import File
from agloe.reference import Answer, Step, Terms, World, broken, check, itineraries, worst_case
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


def random_trip(rng: Random, leave_out: float) -> File:
    """Two or three OPTIONs on a quarter-hour grid. ``leave_out``: how often a FACT is unstated."""
    count = rng.choice([2, 3])
    persons = ["alex", "sam"] if count == 2 and rng.random() < 0.4 else ["alex"]
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
    return trip(persons, PLACES, options, facts, decisions)


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


def test_starting_as_early_as_possible_finds_an_itinerary_whenever_one_exists() -> None:
    rng = Random(2027)
    answers: set[bool] = set()
    for _ in range(150):
        file = random_trip(rng, leave_out=0)
        feasible = check(file).answer is Answer.FEASIBLE
        assert feasible == works_on_the_grid(file)
        answers.add(feasible)
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
