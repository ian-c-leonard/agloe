"""The reference checker's shortcuts, checked the slow way on many small random TRIPs.

The rules page makes three claims that save the checker from trying everything. Starting each
OPTION as early as possible is enough to find an ITINERARY if one exists. The longest value of
each CONTINGENT duration is enough to decide ROBUST. The best case and the worst case are enough
to settle the answer for every possible world. These tests try the things the shortcuts skip.
"""

from dataclasses import replace
from itertools import combinations, pairwise, product
from random import Random

from agloe.file import Duration, File
from agloe.reference import (
    Answer,
    Itinerary,
    Step,
    Terms,
    World,
    best_case,
    broken,
    check,
    in_world,
    itineraries,
    needless,
    with_these_at_best,
    worst_case,
)
from tests.stories import (
    Document,
    any_time,
    complete,
    cutoff,
    lasts,
    lasts_between,
    lock,
    moves,
    seconds,
    starts_at,
    stays,
    takes,
    takes_between,
    trip,
    way,
    way_between,
)

QUARTER = 900
PLACES = ["a", "b", "c"]


def random_trip(
    rng: Random,
    leave_out: float,
    persons: list[str] | None = None,
    count: int | None = None,
    with_complete: float = 0,
    contingent: float = 0,
    with_ways: float = 0,
) -> File:
    """Two or three OPTIONs on a quarter-hour grid.

    ``leave_out`` is how often a FACT is unstated. ``with_complete`` is how often a COMPLETE FACT
    is added. Its span starts one second after a grid time and ends one second before another, so
    the times just outside it are on the grid. ``contingent`` is how often a duration is a range.
    ``with_ways`` is how often the FILE lists one or two WAYs.
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
        length = lasts(id, f"PT{15 * rng.randrange(2)}M")
        if contingent and rng.random() < contingent:
            shortest = rng.randrange(2)
            longest = rng.randrange(shortest + 1, 3)
            length = lasts_between(id, f"PT{15 * shortest}M", f"PT{15 * longest}M")
        stated = [start, length, cutoff(id, f"PT{15 * rng.randrange(2)}M")]
        facts += [fact for fact in stated if rng.random() >= leave_out]
        if rng.random() < 0.6:
            decisions.append(lock(id, *rng.sample(persons, rng.randrange(1, len(persons) + 1))))
    if rng.random() < with_complete:
        origin = rng.choice(PLACES)
        destination = rng.choice([place for place in PLACES if place != origin])
        first = rng.randrange(4)
        last = rng.randrange(first + 1, 9)
        leaving = {
            "earliest": at_second(seconds(9) + QUARTER * first + 1),
            "latest": at_second(seconds(9) + QUARTER * last - 1),
        }
        whole = {"from": origin, "to": destination, "leaving": leaving}
        facts.append({"id": "ways", "complete": whole})
    ways: list[Document] = []
    if rng.random() < with_ways:
        for number in range(rng.choice([1, 2])):
            id = f"way-{number}"
            origin, destination = rng.sample(PLACES, 2)
            both = rng.random() < 0.5
            ways.append(
                way_between(id, origin, destination) if both else way(id, origin, destination)
            )
            length = takes(id, f"PT{15 * rng.randrange(2)}M")
            if contingent and rng.random() < contingent:
                length = takes_between(id, "PT0M", f"PT{15 * rng.randrange(1, 3)}M")
            if rng.random() >= leave_out:
                facts.append(length)
    return trip(persons, PLACES, options, facts, decisions, ways)


def at_second(moment: int) -> str:
    """A time on the day of the stories, to the second."""
    into_day = moment - seconds(0)
    hour, rest = divmod(into_day, 3600)
    return f"2027-05-15T{hour:02d}:{rest // 60:02d}:{rest % 60:02d}-05:00[America/Chicago]"


def works_on_the_grid(file: File, worlds: list[World]) -> bool:
    """Whether one choice of PERSONs and start times works in all of these worlds.

    It tries every start on the grid. Every FACT about an OPTION must be stated.
    """
    world = worlds[0]
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
                steps.append(Step(option.id, option.origin, option.destination, group, start, None))
            if all(not broken(file, each, in_world(each, tuple(steps))) for each in worlds):
                return True
    return False


def every_length(file: File) -> list[World]:
    """Each CONTINGENT duration at its shortest or its longest, in every combination."""
    world = worst_case(file)
    ranges = [fact for fact in file.facts if isinstance(fact, Duration) and fact.contingent]
    worlds: list[World] = []
    for values in product(*(sorted({fact.shortest, fact.longest}) for fact in ranges)):
        terms = dict(world.terms)
        for fact, value in zip(ranges, values, strict=True):
            terms[fact.option] = replace(terms[fact.option], shortest=value, longest=value)
        worlds.append(replace(world, terms=terms))
    return worlds


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
        assert feasible == works_on_the_grid(file, [worst_case(file)])
        if feasible:
            assert broken(file, worst_case(file), report.itinerary) == []
            assert needless(file, worst_case(file), report.itinerary) == []
        answers.add(feasible)
    assert answers == {True, False}


def test_the_longest_durations_decide_robust() -> None:
    """ROBUST means one choice works for every value. Check that against trying the values."""
    rng = Random(80)
    answers: set[bool | None] = set()
    for _ in range(250):
        file = random_trip(rng, leave_out=0, contingent=0.6)
        report = check(file)
        feasible = report.answer is Answer.FEASIBLE
        assert feasible == works_on_the_grid(file, [worst_case(file)])
        if not feasible:
            continue
        lengths = every_length(file)
        assert report.robust == works_on_the_grid(file, lengths)
        assert bool(report.at_worst) != report.robust
        assert needless(file, worst_case(file), report.itinerary) == []
        if report.robust:
            for world in lengths:
                assert broken(file, world, in_world(world, report.itinerary)) == []
        answers.add(report.robust)
    assert answers == {True, False}


def works_in_the_best_case_on_the_grid(file: File) -> bool:
    """Whether any ITINERARY works in the best case, trying every start on the grid.

    For one PERSON. It also tries one unlisted OPTION between any two PLACES.
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
            for hop in hops if len(options) >= 2 else [None]:
                if not broken(file, world, (*steps, hop) if hop else tuple(steps)):
                    return True
    return False


def two_places_with_no_listed_way(rng: Random) -> File:
    """Alex is LOCKed on two OPTIONs in different PLACES, and the FILE lists no way between them.

    One or two COMPLETE FACTs usually cover the ways between those PLACES for some spans. Whether
    an unlisted OPTION can still join them depends on when Alex can leave.

    Half the time Alex must also be at the second PLACE late in the morning, and a FACT covers
    the ways back for the whole day.
    """
    stay_there = rng.random() < 0.5
    facts: list[Document] = []
    for id, quarters in (("first", range(4)), ("second", range(2, 9))):
        quarter = rng.choice(quarters)
        start = starts_at(id, 9 + quarter // 4, 15 * (quarter % 4))
        pinned = id == "second" and stay_there
        stated = [
            start if pinned or rng.random() < 0.7 else any_time(id),
            lasts(id, f"PT{15 * rng.randrange(2)}M"),
            cutoff(id, f"PT{15 * rng.randrange(2)}M"),
        ]
        facts += [fact for fact in stated if (pinned and fact is start) or rng.random() >= 0.15]
    spans: set[tuple[int, int]] = set()
    for chance in (0.85, 0.4):
        if rng.random() < chance:
            first = rng.randrange(5)
            spans.add((first, rng.randrange(first + 1, 10)))
    for number, (first, last) in enumerate(sorted(spans)):
        leaving = {
            "earliest": at_second(seconds(9) + QUARTER * first + 1),
            "latest": at_second(seconds(9) + QUARTER * last - 1),
        }
        ways = {"from": "a", "to": "b", "leaving": leaving}
        facts.append({"id": f"ways-{number}", "complete": ways})
    options = [stays("first", "a"), stays("second", "b")]
    decisions = [lock("first", "alex"), lock("second", "alex")]
    if stay_there:
        options.append(stays("third", "b"))
        facts += [
            starts_at("third", 11, 15),
            lasts("third", "PT0S"),
            cutoff("third", "PT0S"),
            complete("b", "a"),
        ]
        decisions.append(lock("third", "alex"))
    return trip(["alex"], PLACES, options, facts, decisions)


def test_the_best_case_search_misses_no_itinerary() -> None:
    """INFEASIBLE means nothing works in the best case. Check that against trying everything."""
    rng = Random(42)
    answers: set[bool] = set()
    trips = [random_trip(rng, 0.3, persons=["alex"], count=2, with_complete=0.7) for _ in range(80)]
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
    unlisted = frozenset(pair for pair in pairs if rng.random() < 0.3)
    takes: dict[str, tuple[int, int | None]] = {}
    for each in file.ways:
        duration = file.duration(each.id)
        guess = QUARTER * rng.choice([0, 1, 2, 40])
        takes[each.id] = (
            (guess, guess) if duration is None else (duration.shortest, duration.longest)
        )
    return World(terms, unlisted, QUARTER * rng.choice([0, 1, 2]), takes)


def any_choice(rng: Random, file: File, world: World) -> Itinerary:
    """Some OPTIONs, PERSONs, WAYs and start times on the grid.

    Nothing here comes from the checker's search. LOCKed PERSONs always take part, and a PERSON
    usually takes a WAY where two of their OPTIONs are in different PLACEs, so that the choice
    has a fair chance of working.
    """
    people = [person.id for person in file.persons]
    steps: list[Step] = []
    for option in file.options:
        must = {
            person for lock in file.locks if lock.option == option.id for person in lock.persons
        }
        persons = tuple(person for person in people if person in must or rng.random() < 0.25)
        fixed = world.terms[option.id].fixed_start
        start = seconds(9) + QUARTER * rng.randrange(-4, 8) if fixed is None else fixed
        if persons:
            steps.append(Step(option.id, option.origin, option.destination, persons, start, None))
    every = [(a, b) for a in PLACES for b in PLACES if a != b]
    legs: list[tuple[str | None, str, str]] = [
        (None, a, b) for a, b in sorted(every if world.unlisted is None else world.unlisted)
    ]
    for each in file.ways:
        legs.append((each.id, each.origin, each.destination))
        if each.both_ways:
            legs.append((each.id, each.destination, each.origin))
    for person in people:
        mine = sorted((step for step in steps if person in step.persons), key=lambda s: s.start)
        for before, after in pairwise(mine):
            direct = [leg for leg in legs if leg[1:] == (before.destination, after.origin)]
            if direct and rng.random() < 0.8:
                name, origin, destination = rng.choice(direct)
                quarters = max((after.start - before.start) // QUARTER, 0)
                start = before.start + QUARTER * rng.randrange(quarters + 1)
                steps.append(Step(None, origin, destination, (person,), start, None, name))
    if legs:
        for _ in range(rng.choice([0, 0, 0, 1])):
            name, origin, destination = rng.choice(legs)
            start = seconds(9) + QUARTER * rng.randrange(-4, 8)
            steps.append(Step(None, origin, destination, (rng.choice(people),), start, None, name))
    return tuple(steps)


def test_the_best_and_worst_cases_settle_the_answer_for_every_possible_world() -> None:
    """Three things, each checked in possible worlds chosen at random.

    What works in the worst case works in every possible world. What works in a possible world
    works in the best case with the same start times. And an INFEASIBLE TRIP has nothing that
    works in any possible world. Where a choice made by chance works, the search finds one too.

    For an UNDETERMINED TRIP, each set of unknown FACTs the report names is enough, and no
    part of it is.
    """
    rng = Random(1970)
    answers: set[Answer] = set()
    found_by_chance = by_listed_way = 0
    for number in range(300):
        with_ways = 0.8 if number % 2 else 0
        file = random_trip(rng, leave_out=0.3, with_complete=0.3, with_ways=with_ways)
        report = check(file)
        answers.add(report.answer)
        best, worst = best_case(file), worst_case(file)
        always = itineraries(file, worst)
        assert bool(always) == (report.answer is Answer.FEASIBLE)
        assert bool(report.missing) == (report.answer is Answer.UNDETERMINED)
        for enough in report.missing:
            named = [needed.unknown for needed in enough]
            assert itineraries(file, with_these_at_best(file, named))
            for left_out in named:
                fewer = [unknown for unknown in named if unknown != left_out]
                assert not itineraries(file, with_these_at_best(file, fewer))
        for _ in range(8):
            world = possible_world(rng, file)
            for choice in always:
                assert broken(file, world, in_world(world, choice)) == []
            by_chance = [any_choice(rng, file, world) for _ in range(12)]
            by_chance = [
                each for each in by_chance if not broken(file, world, in_world(world, each))
            ]
            found_by_chance += len(by_chance)
            by_listed_way += sum(any(step.way for step in each) for each in by_chance)
            if by_chance:
                assert itineraries(file, world)
            working_here = [*itineraries(file, world), *by_chance]
            for choice in working_here:
                assert broken(file, best, in_world(best, choice)) == []
            if report.answer is Answer.INFEASIBLE:
                assert working_here == []
    assert answers == set(Answer)
    assert found_by_chance > 500
    assert by_listed_way > 50
