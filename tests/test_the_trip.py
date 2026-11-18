"""The times of the TRIP: nothing starts before the TRIP starts, and nothing ends after it ends."""

from random import Random

import pytest

from agloe import answers, compiler, report
from agloe.answers import Answer, Missing, Report
from agloe.file import File, FileError, TripEnd, TripStart, load
from agloe.reference import (
    Broken,
    Constraint,
    Step,
    Unknown,
    best_case,
    broken,
    in_world,
    itineraries,
    needless,
    with_these_at_best,
    worst_case,
)
from tests.stories import (
    Document,
    any_time,
    cutoff,
    flight_home,
    lasts,
    lasts_between,
    lock,
    moves,
    seconds,
    starts_at,
    stays,
    trip,
    trip_ends,
    trip_starts,
)
from tests.test_cross_check import any_choice, possible_world, random_trip, works_on_the_grid


def a_visit(*times: Document, at: Document | None = None, length: Document | None = None) -> File:
    """Alex is LOCKed for a visit at 10:00 am that takes an hour, and for nothing else.

    ``times`` are DECISIONs about when the TRIP starts and ends.
    """
    facts = [at or starts_at("visit", 10), length or lasts("visit", "PT1H")]
    decisions = [*times, lock("visit", "alex")]
    return trip(["alex"], ["museum"], [stays("visit", "museum")], facts, decisions)


def the_visit(start: int, end: int | None) -> Step:
    return Step("visit", "museum", "museum", ("alex",), start, end)


def outside(late: int | None) -> Broken:
    return Broken(Constraint.WITHIN, "visit", ("alex",), late)


def checked(file: File) -> Report:
    """The reference checker's Report, once the COMPILER has given the same one."""
    found = answers.check(file)
    assert compiler.check(file) == found
    return found


def problems(document: Document) -> str:
    with pytest.raises(FileError) as refused:
        load(document)
    return str(refused.value)


def test_a_file_can_say_when_the_trip_starts_and_ends() -> None:
    file = a_visit(trip_starts(9), trip_ends(12))
    assert file.trip_start() == TripStart("trip-start", seconds(9))
    assert file.trip_end() == TripEnd("trip-end", seconds(12))
    assert a_visit().trip_start() is None
    assert a_visit().trip_end() is None


def test_a_file_says_once_when_the_trip_starts_and_once_when_it_ends() -> None:
    document = flight_home()
    again = trip_starts(9)
    again["id"] = "trip-start-again"
    document["decisions"] += [trip_starts(8), again]
    last = len(document["decisions"]) - 1
    said = f"/decisions/{last}: another DECISION already states this about the TRIP"
    assert problems(document) == said


def test_the_trip_does_not_end_before_it_starts() -> None:
    document = flight_home()
    document["decisions"] += [trip_starts(12), trip_ends(9)]
    assert problems(document) == "/decisions: the TRIP ends before it starts"
    document["decisions"][-1] = trip_ends(12)
    assert load(document).trip_end() == TripEnd("trip-end", seconds(12))


def test_a_time_of_the_trip_is_a_real_time() -> None:
    document = flight_home()
    document["decisions"].append({"id": "trip-start", "trip_starts_at": "next week"})
    assert problems(document).startswith(f"/decisions/{len(document['decisions']) - 1}")


def test_a_time_of_the_trip_is_a_decision_and_no_fact() -> None:
    document = flight_home()
    document["facts"].append(trip_starts(9))
    assert problems(document).startswith(f"/facts/{len(document['facts']) - 1}")


def test_nothing_starts_before_the_trip_starts() -> None:
    file = a_visit(trip_starts(10, 30))
    plan = (the_visit(seconds(10), seconds(11)),)
    assert broken(file, worst_case(file), plan) == [outside(30 * 60)]
    on_time = a_visit(trip_starts(10))
    assert broken(on_time, worst_case(on_time), plan) == []


def test_nothing_ends_after_the_trip_ends() -> None:
    file = a_visit(trip_ends(10, 45))
    plan = (the_visit(seconds(10), seconds(11)),)
    assert broken(file, worst_case(file), plan) == [outside(15 * 60)]
    in_time = a_visit(trip_ends(11))
    assert broken(in_time, worst_case(in_time), plan) == []


def test_a_step_with_no_known_end_is_not_over_when_the_trip_ends() -> None:
    file = a_visit(trip_ends(18)).without("visit-length")
    plan = (the_visit(seconds(10), None),)
    assert broken(file, worst_case(file), plan) == [outside(None)]
    assert broken(file, best_case(file), (the_visit(seconds(10), seconds(10)),)) == []
    no_end = a_visit().without("visit-length")
    assert broken(no_end, worst_case(no_end), plan) == []


def test_a_locked_option_before_the_trip_starts_makes_it_infeasible() -> None:
    found = checked(a_visit(trip_starts(10, 30)))
    assert found.answer is Answer.INFEASIBLE
    assert found.conflict == ("visit-time", "trip-start", "lock-visit")


def test_a_locked_option_that_ends_after_the_trip_makes_it_infeasible() -> None:
    found = checked(a_visit(trip_ends(10, 45)))
    assert found.answer is Answer.INFEASIBLE
    assert found.conflict == ("visit-time", "visit-length", "trip-end", "lock-visit")


def test_an_unknown_duration_has_to_fit_before_the_trip_ends() -> None:
    file = a_visit(trip_ends(11, 30)).without("visit-length")
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    assert found.missing == ((Missing(Unknown("duration", "visit"), 90 * 60),),)
    assert report.as_text(file, found).splitlines()[2] == (
        "The trip works if visit takes 1 h 30 min or less."
    )
    no_end = a_visit().without("visit-length")
    assert checked(no_end).answer is Answer.FEASIBLE


def test_a_plan_can_run_past_the_end_of_the_trip_if_something_takes_its_longest() -> None:
    file = a_visit(trip_ends(11, 30), length=lasts_between("visit", "PT1H", "PT2H"))
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert found.robust is False
    assert found.at_worst == (outside(30 * 60),)
    assert "    ! This would end 30 min after the trip ends.\n" in report.as_text(file, found)


def test_a_plan_relies_on_the_times_of_the_trip_where_it_has_anything_in_it() -> None:
    file = a_visit(trip_starts(9), trip_ends(12))
    found = checked(file)
    assert found.relies_on == ("visit-time", "visit-length", "trip-start", "trip-end", "lock-visit")
    words = report.as_text(file, found)
    assert "  trip-start: the TRIP starts at 9:00 am on Saturday 15 May 2027\n" in words
    assert "  trip-end: the TRIP ends at 12:00 pm on Saturday 15 May 2027\n" in words
    idle = trip(["alex"], ["museum"], [stays("visit", "museum")], [], [trip_starts(9)])
    assert checked(idle).relies_on == ()


def test_what_is_tied_to_no_fixed_start_is_timed_from_the_start_of_the_trip() -> None:
    file = a_visit(trip_starts(9), trip_ends(12), at=any_time("visit"))
    assert checked(file).itinerary == (the_visit(seconds(9), seconds(10)),)
    unbounded = a_visit(at=any_time("visit"))
    assert checked(unbounded).itinerary == (the_visit(0, 3600),)


def two_before_a_fixed_one(*times: Document, alex_too: bool = False) -> File:
    """Alex and Sam ride to the museum, where a talk starts at 10:00 am. Sam then has a tour.

    The ride takes 15 minutes and can start at any time. The tour can start at any time, and
    whoever takes it must be at the museum 15 minutes before it. With ``alex_too``, Alex takes
    the tour as well, after the talk. ``times`` are DECISIONs about when the TRIP starts and ends.
    """
    options = [moves("ride", "hotel", "museum"), stays("talk", "museum"), stays("tour", "museum")]
    facts = [
        any_time("ride"),
        lasts("ride", "PT15M"),
        cutoff("ride", "PT0S"),
        starts_at("talk", 10),
        lasts("talk", "PT0S"),
        cutoff("talk", "PT0S"),
        any_time("tour"),
        lasts("tour", "PT0S"),
        cutoff("tour", "PT15M"),
    ]
    on_the_tour = ["sam", "alex"] if alex_too else ["sam"]
    locks = [lock("ride", "alex", "sam"), lock("talk", "alex"), lock("tour", *on_the_tour)]
    return trip(["alex", "sam"], ["hotel", "museum"], options, facts, [*times, *locks])


def test_as_late_as_it_can_leaves_room_for_what_comes_after_before_the_trip_ends() -> None:
    """The ride could leave at 9:45 am for the talk. Then Sam's tour would start at 10:15 am.

    The TRIP ends at 10:00 am. So the ride leaves at 9:30 am, and the tour starts at 10:00 am.
    """
    without_an_end = checked(two_before_a_fixed_one())
    assert {step.option: step.start for step in without_an_end.itinerary} == {
        "ride": seconds(9, 45),
        "talk": seconds(10),
        "tour": seconds(10, 15),
    }
    found = checked(two_before_a_fixed_one(trip_ends(10)))
    assert found.answer is Answer.FEASIBLE
    assert {step.option: step.start for step in found.itinerary} == {
        "ride": seconds(9, 30),
        "talk": seconds(10),
        "tour": seconds(10),
    }


def test_as_early_as_it_can_leaves_room_for_what_comes_before_after_the_trip_starts() -> None:
    """Sam's tour comes after the ride, and Alex's talk at 10:00 am comes after it too.

    Counting back from the talk, the ride leaves at 9:45 am. The TRIP starts then, so the ride
    cannot be earlier, and the tour starts when it can: at 10:15 am.
    """
    found = checked(two_before_a_fixed_one(trip_starts(9, 45)))
    assert found.answer is Answer.FEASIBLE
    assert {step.option: step.start for step in found.itinerary} == {
        "ride": seconds(9, 45),
        "talk": seconds(10),
        "tour": seconds(10, 15),
    }
    a_minute_later = checked(two_before_a_fixed_one(trip_starts(9, 46)))
    assert a_minute_later.answer is Answer.UNDETERMINED  # only an unlisted WAY back could help


def test_what_comes_after_a_fixed_start_waits_for_what_cannot_be_earlier() -> None:
    """Alex takes the tour too, after the talk at 10:00 am, and must be there 15 minutes before.

    With no start of the TRIP, the tour is at 10:00 am and the ride leaves at 9:30 am to be in
    time for it. Where the TRIP starts at 9:45 am, the ride cannot leave before then. So the
    tour waits: it starts at 10:15 am, though it comes after a fixed start.
    """
    free = checked(two_before_a_fixed_one(alex_too=True))
    assert {step.option: step.start for step in free.itinerary} == {
        "ride": seconds(9, 30),
        "talk": seconds(10),
        "tour": seconds(10),
    }
    found = checked(two_before_a_fixed_one(trip_starts(9, 45), alex_too=True))
    assert found.answer is Answer.FEASIBLE
    assert {step.option: step.start for step in found.itinerary} == {
        "ride": seconds(9, 45),
        "talk": seconds(10),
        "tour": seconds(10, 15),
    }


def test_the_search_finds_a_plan_within_the_trip_whenever_trying_everything_does() -> None:
    """Every choice of PERSONs and every start on the grid is tried, and each step is checked."""
    rng = Random(1616)
    seen: set[bool] = set()
    bounded = 0
    for _ in range(200):
        file = random_trip(rng, leave_out=0, with_times=0.8)
        found = checked(file)
        feasible = found.answer is Answer.FEASIBLE
        assert feasible == works_on_the_grid(file, [worst_case(file)])
        if feasible:
            assert broken(file, worst_case(file), found.itinerary) == []
            assert needless(file, worst_case(file), found.itinerary) == []
        bounded += file.trip_start() is not None or file.trip_end() is not None
        seen.add(feasible)
    assert seen == {True, False}
    assert bounded > 150


def test_the_two_checkers_agree_on_random_trips_with_the_times_of_the_trip() -> None:
    rng = Random(1717)
    trips = [
        random_trip(rng, 0.25, contingent=0.3, with_complete=0.4, with_times=0.8)
        for _ in range(100)
    ]
    trips += [
        random_trip(rng, 0.2, contingent=0.3, with_complete=0.4, with_ways=0.9, with_times=0.8)
        for _ in range(100)
    ]
    trips += [
        random_trip(rng, 0, ["alex", "sam"], contingent=0.5, with_ways=0.5, with_times=0.8)
        for _ in range(100)
    ]
    seen: set[Answer] = set()
    robust: set[bool | None] = set()
    named = 0
    for file in trips:
        found = checked(file)
        seen.add(found.answer)
        robust.add(found.robust)
        bounds = {each.id for each in (file.trip_start(), file.trip_end()) if each is not None}
        named += bool(bounds & set(found.conflict))
    assert seen == set(Answer)
    assert robust == {True, False, None}
    assert named > 15


def test_the_best_and_worst_cases_settle_the_answer_with_the_times_of_the_trip() -> None:
    """What works in the worst case works in every possible world, and so on, as before.

    The times of the TRIP are the same in every possible world: they are limits, and nothing
    about them is unknown.
    """
    rng = Random(1818)
    seen: set[Answer] = set()
    by_chance_within = 0
    for number in range(200):
        with_ways = 0.8 if number % 2 else 0
        file = random_trip(rng, 0.3, with_complete=0.3, with_ways=with_ways, with_times=0.8)
        found = answers.check(file)
        seen.add(found.answer)
        best, worst = best_case(file), worst_case(file)
        always = itineraries(file, worst)
        assert bool(always) == (found.answer is Answer.FEASIBLE)
        for enough in found.missing:
            named = [needed.unknown for needed in enough]
            assert itineraries(file, with_these_at_best(file, named))
            for left_out in named:
                fewer = [unknown for unknown in named if unknown != left_out]
                assert not itineraries(file, with_these_at_best(file, fewer))
        for _ in range(6):
            world = possible_world(rng, file)
            for choice in always:
                assert broken(file, world, in_world(world, choice)) == []
            by_chance = [any_choice(rng, file, world) for _ in range(12)]
            by_chance = [
                each for each in by_chance if not broken(file, world, in_world(world, each))
            ]
            by_chance_within += bool(by_chance)
            if by_chance:
                assert itineraries(file, world)
            for choice in (*itineraries(file, world), *by_chance):
                assert broken(file, best, in_world(best, choice)) == []
            if found.answer is Answer.INFEASIBLE:
                assert not by_chance
                assert not itineraries(file, world)
    assert seen == set(Answer)
    assert by_chance_within > 100
