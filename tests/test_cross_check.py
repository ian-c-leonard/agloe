"""The reference checker's shortcuts, checked the slow way on many small random TRIPs.

The rules page makes four claims that save the checker from trying everything. Starting each
OPTION as early as possible is enough to find an ITINERARY if one exists. The longest value of
each CONTINGENT duration is enough to decide ROBUST. The best case and the worst case are enough
to settle the answer for every possible world. A PERSON who goes round in a circle by WAYs alone
could have waited instead. These tests try the things the shortcuts skip.
"""

from dataclasses import replace
from itertools import combinations, pairwise, permutations, product
from random import Random

from agloe.answers import Answer, check
from agloe.file import Complete, Duration, File
from agloe.reference import (
    Itinerary,
    Step,
    Terms,
    World,
    best_case,
    broken,
    has_to_end_at,
    in_world,
    itineraries,
    needless,
    with_these_at_best,
    worst_case,
)
from tests.stories import (
    Document,
    any_time,
    booking,
    complete,
    cutoff,
    ends_at,
    every,
    every_right,
    lasts,
    lasts_between,
    lock,
    moves,
    must,
    needs_no_right,
    needs_right,
    offer,
    satisfies,
    seconds,
    starts_at,
    starts_from,
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
    with_wants: float = 0,
    must_nots: float = 0,
    whole_sets: float = 0,
    with_times: float = 0,
    with_ends: float = 0,
    with_rights: float = 0,
) -> File:
    """Two or three OPTIONs on a quarter-hour grid.

    ``leave_out`` is how often a FACT is unstated. ``with_complete`` is how often a COMPLETE FACT
    is added. Its span starts one second after a grid time and ends one second before another, so
    the times just outside it are on the grid. ``contingent`` is how often a duration is a range.
    ``with_ways`` is how often the FILE lists one or two WAYs. ``with_wants`` is how often it
    has one or two WANTs, each a must for some PERSONs. ``must_nots`` is how often a holder
    has the WANT as a must-not instead. For each OPTION and WANT, a FACT says that the OPTION
    SATISFIES the WANT, or that it does not, or the FILE says nothing. ``whole_sets`` is how
    often a FACT says that a WANT's set is COMPLETE. ``with_times`` is how often a DECISION says
    when the TRIP starts, and how often one says when it ends, both on the grid. ``with_ends``
    is how often a FACT says where a PERSON starts from, and how often a PERSON has to end the
    TRIP at some PLACE. ``with_rights`` is how often a FACT says that the FILE holds every right
    to an OPTION. When it is set, a FACT says that an OPTION needs a right, or that it needs
    none, or the FILE says nothing, and an OPTION has up to two BOOKINGs and up to two OFFERs.
    When it is not, a FACT says that each OPTION needs none.
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
        whole: Document = {"from": origin, "to": destination, "leaving": leaving}
        left_out = rng.choice(["from", "to", None, None])
        if left_out is not None:
            del whole[left_out]
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
    wants: list[Document] = []
    if with_wants and rng.random() < with_wants:
        for number in range(rng.choice([1, 1, 2])):
            id = f"want-{number}"
            holders = rng.sample(persons, rng.randrange(1, len(persons) + 1))
            never = [person for person in holders if must_nots and rng.random() < must_nots]
            wants.append(must(id, *(p for p in holders if p not in never), never=never))
            for option in options:
                degree = rng.choice([None, None, 0, 0, 3, 10, 10])
                if degree is not None:
                    facts.append(satisfies(option["id"], id, degree))
            if whole_sets and rng.random() < whole_sets:
                facts.append(every(id))
    if with_ends:
        for person in persons:
            if rng.random() < with_ends:
                facts.append(starts_from(person, rng.choice(PLACES)))
        for person in persons:
            if rng.random() < with_ends:
                wants.append(ends_at(rng.choice(PLACES), person, id=f"{person}-ending"))
        if wants and rng.random() < 0.15:
            wants.append(ends_at(rng.choice(PLACES), *persons, id="ending"))
    if with_times and rng.random() < with_times:
        decisions.append(at_the_start(rng))
    if with_times and rng.random() < with_times:
        decisions.append(at_the_end(rng))
    if with_rights:
        for option in options:
            id = option["id"]
            stated = rng.choice([needs_right(id), needs_right(id), needs_no_right(id), None])
            if stated is not None:
                facts.append(stated)
            for number in range(rng.choice([0, 1, 1, 2])):
                covered = rng.sample(persons, rng.randrange(1, len(persons) + 1))
                facts.append(booking(id, *covered, id=f"{id}-booking-{number}"))
            offers = [f"{id}-offer-{number}" for number in range(rng.choice([0, 0, 0, 1, 1, 2]))]
            facts += [offer(id, rng.choice([1, 1, 2]), id=name) for name in offers]
            if rng.random() < with_rights:
                facts.append(every_right(id, *offers))
    return trip(persons, PLACES, options, facts, decisions, ways, wants, tickets=bool(with_rights))


def at_the_start(rng: Random) -> Document:
    """A DECISION that the TRIP starts at 8:30 am, 8:45 am, 9:00 am or 9:15 am."""
    quarter = rng.randrange(-2, 2)
    return {"id": "trip-start", "trip_starts_at": at_second(seconds(9) + QUARTER * quarter)}


def at_the_end(rng: Random) -> Document:
    """A DECISION that the TRIP ends at a quarter hour from 9:30 am to 10:30 am."""
    quarter = rng.randrange(2, 7)
    return {"id": "trip-end", "trip_ends_at": at_second(seconds(9) + QUARTER * quarter)}


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

    For one PERSON. It also tries one unlisted WAY between any two PLACES, and two in a row
    through the third PLACE.
    """
    world = best_case(file)
    person = file.persons[0].id
    grid = [seconds(9) + QUARTER * quarter for quarter in range(-4, 11)]

    def hop(origin: str, destination: str, moment: int) -> Step:
        return Step(None, origin, destination, (person,), moment, moment)

    hops: list[tuple[Step, ...]] = [()]
    hops += [(hop(*pair, moment),) for pair in permutations(PLACES, 2) for moment in grid]
    hops += [
        (hop(first, between, moment), hop(between, last, later))
        for first, between, last in permutations(PLACES, 3)
        for moment in grid
        for later in grid
        if later >= moment
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
            for taken in hops if len(options) >= 2 else [()]:
                if not broken(file, world, (*steps, *taken)):
                    return True
    return False


def two_places_with_no_listed_way(rng: Random) -> File:
    """Alex is LOCKed on two OPTIONs in different PLACES, and the FILE lists no way between them.

    One or two COMPLETE FACTs usually cover the ways from the first PLACE for some spans: to the
    second PLACE, or to every PLACE. Whether an unlisted WAY can still join the two depends on
    when Alex can leave, and on whether the way through the third PLACE is open.

    Half the time Alex must also be at the second PLACE late in the morning, and a FACT covers
    every way back to the first PLACE for the whole day.
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
        ways: Document = {"from": "a", "leaving": leaving}
        if rng.random() < 0.3:
            ways["to"] = "b"
        facts.append({"id": f"ways-{number}", "complete": ways})
    options = [stays("first", "a"), stays("second", "b")]
    decisions = [lock("first", "alex"), lock("second", "alex")]
    if stay_there:
        options.append(stays("third", "b"))
        facts += [
            starts_at("third", 11, 15),
            lasts("third", "PT0S"),
            cutoff("third", "PT0S"),
            complete(None, "a"),
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
    slow = QUARTER * rng.choice([0, 1, 2])
    delivered = [want for want in file.wants if want.ends_at is None]
    delivers: set[tuple[str, str]] = set()
    for option in file.options:
        for want in delivered:
            said = file.says(option.id, want.id)
            guessed = rng.random() < 0.5
            if guessed if said is None else said:
                delivers.add((option.id, want.id))
    elsewhere = frozenset(
        (want.id, person)
        for want in delivered
        for person in want.musts
        if file.complete_for(want.id) is None and rng.random() < 0.3
    )
    # Whether an OPTION needs a right is a guess where no FACT says. So is another right, for
    # a PERSON whom no BOOKING covers, unless a FACT says that the FILE holds every right.
    needs = frozenset(
        option.id
        for option in file.options
        if (
            rng.random() < 0.5
            if file.needs_right(option.id) is None
            else file.needs_right(option.id)
        )
    )
    rights = frozenset(
        (option.id, person.id)
        for option in file.options
        for person in file.persons
        if file.needs_right(option.id) is not False
        and (
            file.booking(option.id, person.id) is not None
            or (file.rights_complete(option.id) is None and rng.random() < 0.4)
        )
    )
    # One possible world: what SATISFIES a WANT is the same for a must and for a must-not.
    delivered_by = frozenset(delivers)
    places = {option.id: file.places_on_offer(option.id) for option in file.options}
    return World(
        terms, unlisted, slow, takes, delivered_by, delivered_by, elsewhere, needs, rights, places
    )


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
        # A WAY from where the PERSON starts from, and a WAY to where they have to end the
        # TRIP, where one goes straight there.
        begins, asked = file.starts_from(person), has_to_end_at(file, person)
        end = asked[0].ends_at if asked else None
        first = mine[0].origin if mine else end
        if begins is not None and first is not None and begins.place != first:
            direct = [leg for leg in legs if leg[1:] == (begins.place, first)]
            if direct and rng.random() < 0.8:
                name, origin, destination = rng.choice(direct)
                early = (mine[0].start if mine else seconds(9)) - QUARTER * rng.randrange(3)
                steps.append(Step(None, origin, destination, (person,), early, None, name))
        if mine and end is not None and mine[-1].destination != end:
            direct = [leg for leg in legs if leg[1:] == (mine[-1].destination, end)]
            if direct and rng.random() < 0.8:
                name, origin, destination = rng.choice(direct)
                late = mine[-1].start + QUARTER * rng.randrange(4)
                steps.append(Step(None, origin, destination, (person,), late, None, name))
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


def a_walk(rng: Random, passed: list[str]) -> tuple[File, World, Itinerary]:
    """Two stops with WAYs between them through these PLACEs, some listed and some not.

    Returns the FILE, a world and the ITINERARY: the first stop, the WAYs and the last stop.
    The FILE has up to two COMPLETE FACTs. Every step starts later than the one before, so the
    steps can happen in one order only.
    """
    listed: list[Document] = []
    facts: list[Document] = []
    lengths: dict[tuple[str, str], tuple[str, int]] = {}  # the WAY from one PLACE to another
    for number, (origin, destination) in enumerate(rng.sample(list(permutations(PLACES, 2)), 3)):
        id, minutes = f"way-{number}", 5 * rng.randrange(3)
        both = rng.random() < 0.5
        listed.append(
            way_between(id, origin, destination) if both else way(id, origin, destination)
        )
        facts.append(takes(id, f"PT{minutes}M"))
        lengths[origin, destination] = (id, 60 * minutes)
        if both:
            lengths.setdefault((destination, origin), (id, 60 * minutes))

    unlisted_takes = 300 * rng.randrange(3)
    legs: list[Step] = []
    free = seconds(9)
    for origin, destination in pairwise(passed):
        name, lasts_for = None, unlisted_takes
        if (origin, destination) in lengths and rng.random() < 0.6:
            name, lasts_for = lengths[origin, destination]
        start = max(free + 300 * rng.randrange(3), seconds(9) + 300 * (len(legs) + 1))
        if legs:
            start = max(start, legs[-1].start + 300)
        legs.append(Step(None, origin, destination, ("alex",), start, start + lasts_for, name))
        free = start + lasts_for
    arrive = (free - seconds(9)) // 60 + 5 * rng.randrange(1, 4)  # minutes after 9:00

    facts += [
        starts_at("first", 9),
        lasts("first", "PT0S"),
        starts_at("last", 9 + arrive // 60, arrive % 60),
        lasts("last", "PT0S"),
        cutoff("last", f"PT{5 * rng.randrange(3)}M"),
    ]
    for number in range(rng.randrange(3)):
        origin, destination = rng.choice([*permutations(PLACES, 2)])
        whole: Document = {"from": origin, "to": destination}
        left_out = rng.choice(["from", "to", None, None])
        if left_out is not None:
            del whole[left_out]
        first = 5 * rng.randrange(20)
        last = first + 5 * rng.randrange(1, 12)
        whole["leaving"] = {
            "earliest": at_second(seconds(9) + 60 * first),
            "latest": at_second(seconds(9) + 60 * last),
        }
        if all(whole != fact.get("complete") for fact in facts):
            facts.append({"id": f"ways-{number}", "complete": whole})
    file = trip(
        ["alex"],
        PLACES,
        [stays("first", passed[0]), stays("last", passed[-1])],
        facts,
        [lock("first", "alex"), lock("last", "alex")],
        listed,
    )
    world = best_case(file) if rng.random() < 0.5 else possible_world(rng, file)
    world = replace(world, unlisted_takes=unlisted_takes)
    first_stop = Step("first", passed[0], passed[0], ("alex",), seconds(9), seconds(9))
    at_last = seconds(9) + 60 * arrive
    last_stop = Step("last", passed[-1], passed[-1], ("alex",), at_last, at_last)
    return file, world, (first_stop, *legs, last_stop)


def test_going_round_in_a_circle_never_helps() -> None:
    """A PERSON who comes back to a PLACE by WAYs alone could have waited there instead.

    So the searches only try routes that pass through no PLACE twice. Whenever an ITINERARY with
    such a circle works, it still works without the WAYs between the two visits.
    """
    rng = Random(11)
    worked = 0
    for _ in range(1500):
        passed = [rng.choice(PLACES)]
        for _ in range(rng.randrange(2, 6)):
            passed.append(rng.choice([place for place in PLACES if place != passed[-1]]))
        again = next((n for n in range(len(passed)) if passed[n] in passed[:n]), None)
        if again is None:
            continue
        before = passed.index(passed[again])
        file, world, (first, *legs, last) = a_walk(rng, passed)
        if not broken(file, world, (first, *legs, last)):
            worked += 1
            assert broken(file, world, (first, *legs[:before], *legs[again:], last)) == []
    assert worked > 500


def test_one_unlisted_way_stands_in_for_a_route_that_takes_one() -> None:
    """Alex goes from one PLACE through a second to a third, and one of the two WAYs is unlisted.

    Say an unlisted WAY also goes straight from the first PLACE to the third, and every COMPLETE
    FACT about those two PLACEs is also about the two PLACEs of the unlisted WAY taken. Then the
    ITINERARY still works with the straight WAY, taken when the other would have been. So the
    searches leave the longer route out.
    """
    rng = Random(12)
    worked = 0
    for _ in range(4000):
        passed = rng.sample(PLACES, 3)
        file, world, (first, there, on, last) = a_walk(rng, passed)
        ends = (passed[0], passed[2])
        if world.unlisted is not None and ends not in world.unlisted:
            continue
        about_the_ends = {fact.id for fact in file.facts if covers(fact, *ends)}
        for taken in (there, on):
            about_this = {
                fact.id for fact in file.facts if covers(fact, taken.origin, taken.destination)
            }
            if taken.way is not None or not about_the_ends <= about_this:
                continue
            if not broken(file, world, (first, there, on, last)):
                worked += 1
                arrives = taken.start + world.unlisted_takes
                straight = Step(None, *ends, ("alex",), taken.start, arrives)
                assert broken(file, world, (first, straight, last)) == []
    assert worked > 300


def covers(fact: object, origin: str, destination: str) -> bool:
    """Whether a FACT is a COMPLETE FACT about travel straight from one PLACE to another."""
    return isinstance(fact, Complete) and fact.covers(origin, destination)


def a_group_that_meets(rng: Random) -> File:
    """Three PERSONs do two things apart, in two PLACEs, and then one thing together in a third.

    A WAY leads from each of the first two PLACEs to the third. One of them may be untimed. Half
    the time a FACT says the FILE lists every way.
    """
    people = ["alex", "sam", "jo"]
    first = rng.sample(people, rng.choice([1, 2]))
    second = [person for person in people if person not in first]
    facts: list[Document] = []
    for id in ("one", "two"):
        facts += [starts_at(id, 9, 15 * rng.randrange(4)), lasts(id, f"PT{15 * rng.randrange(4)}M")]
    facts += [
        starts_at("meet", 10, 15 * rng.randrange(3)),
        lasts("meet", "PT0S"),
        cutoff("meet", f"PT{15 * rng.randrange(2)}M"),
    ]
    for id in ("from-a", "from-b"):
        if rng.random() < 0.8:
            facts.append(takes(id, f"PT{15 * rng.randrange(3)}M"))
    if rng.random() < 0.5:
        facts.append(complete(None, None))
    return trip(
        people,
        PLACES,
        [stays("one", "a"), stays("two", "b"), stays("meet", "c")],
        facts,
        [lock("one", *first), lock("two", *second), lock("meet", *people)],
        [way_between("from-a", "a", "c"), way_between("from-b", "b", "c")],
    )
