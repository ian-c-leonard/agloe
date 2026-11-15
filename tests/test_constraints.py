"""Each CONSTRAINT, shown by one ITINERARY that meets it and one that does not."""

import pytest

from agloe.file import File, load
from agloe.reference import (
    Broken,
    Constraint,
    Itinerary,
    Step,
    best_case,
    broken,
    needless,
    worst_case,
)
from tests.stories import (
    any_time,
    at,
    complete,
    cutoff,
    flight_home,
    lasts,
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

STORY = load(flight_home())
BOTH = ("alex", "sam")


def step(file: File, option: str, start: int, end: int | None, *persons: str) -> Step:
    found = file.option(option)
    return Step(option, found.origin, found.destination, persons or BOTH, start, end)


def unlisted(origin: str, destination: str, start: int, *persons: str) -> Step:
    return Step(None, origin, destination, persons or BOTH, start, start)


def visit(end: int = seconds(15)) -> Step:
    return step(STORY, "museum-visit", seconds(14), end)


def train(start: int = seconds(15)) -> Step:
    return step(STORY, "blue-line", start, start + 3600)


def flight(start: int = seconds(17)) -> Step:
    return step(STORY, "flight", start, start + 9000)


def found(*itinerary: Step, file: File = STORY) -> list[Broken]:
    return broken(file, worst_case(file), itinerary)


def test_the_story_meets_every_constraint() -> None:
    assert found(visit(), train(), flight()) == []


def test_locks_are_honored() -> None:
    assert found() == [
        Broken(Constraint.LOCK, "museum-visit", BOTH),
        Broken(Constraint.LOCK, "flight", BOTH),
    ]
    alone = step(STORY, "flight", seconds(17), seconds(19, 30), "alex")
    alex_only: Itinerary = (step(STORY, "museum-visit", seconds(14), seconds(15), "alex"), alone)
    assert Broken(Constraint.LOCK, "flight", ("sam",)) in broken(
        STORY, worst_case(STORY), alex_only
    )


def test_each_option_starts_when_it_can() -> None:
    assert found(visit(), train(), flight(seconds(17, 30))) == [
        Broken(Constraint.START, "flight", BOTH)
    ]


def test_each_option_takes_as_long_as_it_takes() -> None:
    short_visit = visit(end=seconds(14, 30))
    assert found(short_visit, train(), flight()) == [
        Broken(Constraint.DURATION, "museum-visit", BOTH)
    ]


def test_each_person_is_in_one_place_at_a_time() -> None:
    assert found(visit(), flight()) == [Broken(Constraint.PLACE, "flight", BOTH)]
    early_train = train(seconds(14, 30))
    assert found(visit(), early_train, flight()) == [
        Broken(Constraint.PLACE, "blue-line", BOTH, late=1800)
    ]


def test_each_person_arrives_in_time() -> None:
    assert found(visit(), train(seconds(15, 15)), flight()) == []
    assert found(visit(), train(seconds(15, 30)), flight()) == [
        Broken(Constraint.ARRIVAL, "flight", BOTH, late=900)
    ]


def test_a_person_who_was_there_all_along_is_in_time() -> None:
    file = trip(
        ["alex"],
        ["ohare", "home"],
        [stays("coffee", "ohare"), moves("flight", "ohare", "home")],
        [
            starts_at("coffee", 16, 30),
            lasts("coffee", "PT20M"),
            starts_at("flight", 17),
            lasts("flight", "PT2H30M"),
            cutoff("flight", "PT45M"),
        ],
        [lock("coffee", "alex"), lock("flight", "alex")],
    )
    coffee = step(file, "coffee", seconds(16, 30), seconds(16, 50), "alex")
    home = step(file, "flight", seconds(17), seconds(19, 30), "alex")
    assert found(coffee, home, file=file) == []


def test_an_unlisted_option_needs_a_world_that_has_it() -> None:
    shortcut = (visit(), unlisted("art-institute", "ohare", seconds(15)), flight())
    assert broken(STORY, worst_case(STORY), shortcut) == [Broken(Constraint.LISTED, None, BOTH)]
    assert broken(STORY, best_case(STORY), shortcut) == []


def with_complete_ways() -> File:
    document = flight_home()
    document["places"].append({"id": "midway", "name": "Midway"})
    document["facts"].append(complete("art-institute", "ohare"))
    return load(document)


def test_a_complete_set_is_the_whole_set() -> None:
    file = with_complete_ways()
    shortcut = (visit(), unlisted("art-institute", "ohare", seconds(15)), flight())
    assert broken(file, best_case(file), shortcut) == [Broken(Constraint.LISTED, None, BOTH)]


def test_a_complete_set_covers_ways_through_other_places() -> None:
    file = with_complete_ways()
    first = unlisted("art-institute", "midway", seconds(15))
    second = unlisted("midway", "ohare", seconds(15))
    assert broken(file, best_case(file), (visit(), first, second, flight())) == [
        Broken(Constraint.LISTED, None, BOTH)
    ]


def test_a_complete_set_says_nothing_outside_its_span() -> None:
    document = flight_home()
    ways = {
        "from": "art-institute",
        "to": "ohare",
        "leaving": {"earliest": at(16), "latest": at(18)},
    }
    document["facts"].append({"id": "ways-late", "complete": ways})
    file = load(document)
    shortcut = (visit(), unlisted("art-institute", "ohare", seconds(15)), flight())
    assert broken(file, best_case(file), shortcut) == []


def test_a_complete_span_includes_both_of_its_ends() -> None:
    document = flight_home()
    ways = {
        "from": "art-institute",
        "to": "ohare",
        "leaving": {"earliest": at(15), "latest": at(15, 10)},
    }
    document["facts"].append({"id": "ways-at-three", "complete": ways})
    file = load(document)

    def leaving_at(moment: int) -> list[Broken]:
        shortcut = (visit(), unlisted("art-institute", "ohare", moment), flight())
        return broken(file, best_case(file), shortcut)

    covered = [Broken(Constraint.LISTED, None, BOTH)]
    assert leaving_at(seconds(15)) == covered
    assert leaving_at(seconds(15, 10)) == covered
    assert leaving_at(seconds(15, 10) + 1) == []


def test_a_complete_set_covers_only_ways_that_reach_the_second_place() -> None:
    """Sam takes an unlisted way to Midway and stays there. Nothing says those ways are listed."""
    file = with_complete_ways()
    alex = ("alex",)
    alone = (
        step(file, "museum-visit", seconds(14), seconds(15)),
        unlisted("art-institute", "midway", seconds(15), "sam"),
        step(file, "blue-line", seconds(15), seconds(16), *alex),
        step(file, "flight", seconds(17), seconds(19, 30), *alex),
    )
    assert broken(file, best_case(file), alone) == [Broken(Constraint.LOCK, "flight", ("sam",))]


def test_many_options_at_one_instant_are_checked_at_once() -> None:
    """Ten PERSONs each do their own thing at 9:00, and none of it takes any time."""
    people = [f"person-{number}" for number in range(10)]
    file = trip(
        people,
        ["hall"],
        [stays(f"task-{number}", "hall") for number in range(10)],
        [
            fact
            for number in range(10)
            for fact in (starts_at(f"task-{number}", 9), lasts(f"task-{number}", "PT0S"))
        ],
        [lock(f"task-{number}", people[number]) for number in range(10)],
    )
    everyone = tuple(
        Step(f"task-{number}", "hall", "hall", (people[number],), seconds(9), seconds(9))
        for number in range(10)
    )
    assert broken(file, worst_case(file), everyone) == []


def test_every_order_is_tried_at_every_instant() -> None:
    """At 9:00 Alex must do a task at a before the ride to b, though the ride is listed first.

    At 10:00 two more things at b take no time. The order at 10:00 must not stop the checker from
    trying the other order at 9:00.
    """
    file = trip(
        ["alex"],
        ["a", "b"],
        [moves("ride", "a", "b"), stays("task", "a"), stays("lunch", "b"), stays("call", "b")],
        [
            fact
            for id, hour in (("ride", 9), ("task", 9), ("lunch", 10), ("call", 10))
            for fact in (starts_at(id, hour), lasts(id, "PT0S"), cutoff(id, "PT0S"))
        ],
        [lock(id, "alex") for id in ("ride", "task", "lunch", "call")],
    )
    alex = ("alex",)
    day = (
        Step("ride", "a", "b", alex, seconds(9), seconds(9)),
        Step("task", "a", "a", alex, seconds(9), seconds(9)),
        Step("lunch", "b", "b", alex, seconds(10), seconds(10)),
        Step("call", "b", "b", alex, seconds(10), seconds(10)),
    )
    assert broken(file, worst_case(file), day) == []


def test_a_long_day_is_checked_step_by_step() -> None:
    """Alex stays at one PLACE for 1,200 one-second OPTIONs in a row."""
    count = 1200
    ids = [f"stay-{number}" for number in range(count)]
    facts: list[dict[str, object]] = []
    for number, id in enumerate(ids):
        start = starts_at(id, 9)
        start["starts_at"] = (
            f"2027-05-15T09:{number // 60:02d}:{number % 60:02d}-05:00[America/Chicago]"
        )
        facts += [start, lasts(id, "PT1S")]
    file = trip(
        ["alex"], ["a"], [stays(id, "a") for id in ids], facts, [lock(id, "alex") for id in ids]
    )
    day = tuple(
        Step(id, "a", "a", ("alex",), seconds(9) + number, seconds(9) + number + 1)
        for number, id in enumerate(ids)
    )
    assert broken(file, worst_case(file), day) == []


def test_options_that_take_time_are_not_tried_in_every_order() -> None:
    """Nine PERSONs each stay an hour from 9:00. The first one is also booked at 9:30."""
    people = [f"person-{number}" for number in range(9)]
    stays_at_nine = [stays(f"task-{number}", "hall") for number in range(9)]
    facts = [
        fact
        for number in range(9)
        for fact in (starts_at(f"task-{number}", 9), lasts(f"task-{number}", "PT1H"))
    ]
    file = trip(
        people,
        ["hall"],
        [*stays_at_nine, stays("clash", "hall")],
        [*facts, starts_at("clash", 9, 30), lasts("clash", "PT1H")],
        [],
    )
    steps = [
        Step(f"task-{number}", "hall", "hall", (people[number],), seconds(9), seconds(10))
        for number in range(9)
    ]
    clash = Step("clash", "hall", "hall", (people[0],), seconds(9, 30), seconds(10, 30))
    assert broken(file, worst_case(file), (*steps, clash)) == [
        Broken(Constraint.PLACE, "clash", (people[0],), late=1800)
    ]


def test_a_complete_set_covers_a_journey_up_to_the_first_arrival() -> None:
    """Alex takes the listed train to O'Hare, then unlisted OPTIONs to Midway and back."""
    file = with_complete_ways()
    alex = ("alex",)
    journey = (
        step(file, "museum-visit", seconds(14), seconds(15), *alex),
        step(file, "blue-line", seconds(15), seconds(16), *alex),
        unlisted("ohare", "midway", seconds(16), *alex),
        unlisted("midway", "ohare", seconds(16, 30), *alex),
    )
    found = broken(file, best_case(file), journey)
    assert Constraint.LISTED not in {each.constraint for each in found}
    there_and_back = (*journey[:2], unlisted("ohare", "art-institute", seconds(16), *alex))
    again = unlisted("art-institute", "ohare", seconds(16, 30), *alex)
    found = broken(file, best_case(file), (*there_and_back, again))
    assert Broken(Constraint.LISTED, None, alex) in found


def with_walks() -> File:
    """Alex at three stops, with a walk between the hotel and the gallery and one to the cafe."""
    return trip(
        ["alex"],
        ["hotel", "gallery", "cafe"],
        [stays("breakfast", "hotel"), stays("museum", "gallery")],
        [
            starts_at("breakfast", 8),
            lasts("breakfast", "PT1H"),
            starts_at("museum", 10),
            lasts("museum", "PT2H"),
            cutoff("museum", "PT0S"),
            takes("walk", "PT15M"),
            takes_between("stroll", "PT10M", "PT20M"),
        ],
        [lock("breakfast", "alex"), lock("museum", "alex")],
        [way_between("walk", "hotel", "gallery"), way("stroll", "gallery", "cafe")],
    )


def walk(origin: str, destination: str, start: int, minutes: int = 15, name: str = "walk") -> Step:
    return Step(None, origin, destination, ("alex",), start, start + 60 * minutes, name)


def test_a_way_takes_as_long_as_it_takes_each_time() -> None:
    file = with_walks()
    world = worst_case(file)
    breakfast = step(file, "breakfast", seconds(8), seconds(9), "alex")
    museum = step(file, "museum", seconds(10), seconds(12), "alex")
    there = walk("hotel", "gallery", seconds(9, 30))
    assert broken(file, world, (breakfast, there, museum)) == []
    too_quick = walk("hotel", "gallery", seconds(9, 30), minutes=5)
    assert broken(file, world, (breakfast, too_quick, museum)) == [
        Broken(Constraint.DURATION, None, ("alex",))
    ]
    stroll = walk("gallery", "cafe", seconds(12), minutes=20, name="stroll")
    assert broken(file, world, (breakfast, there, museum, stroll)) == []
    too_long = walk("gallery", "cafe", seconds(12), minutes=25, name="stroll")
    assert broken(file, world, (breakfast, there, museum, too_long)) == [
        Broken(Constraint.DURATION, None, ("alex",))
    ]


def test_a_way_must_be_over_before_the_next_thing_starts() -> None:
    file = with_walks()
    breakfast = step(file, "breakfast", seconds(8), seconds(9), "alex")
    museum = step(file, "museum", seconds(10), seconds(12), "alex")
    late = walk("hotel", "gallery", seconds(9, 50))
    assert broken(file, worst_case(file), (breakfast, late, museum)) == [
        Broken(Constraint.PLACE, "museum", ("alex",), late=300)
    ]


def test_several_ways_in_a_row_pass_through_no_place_twice() -> None:
    file = with_walks()
    breakfast = step(file, "breakfast", seconds(8), seconds(9), "alex")
    museum = step(file, "museum", seconds(10), seconds(12), "alex")
    there = walk("hotel", "gallery", seconds(9))
    back = walk("gallery", "hotel", seconds(9, 15))
    again = walk("hotel", "gallery", seconds(9, 30))
    assert broken(file, worst_case(file), (breakfast, there, back, again, museum)) == [
        Broken(Constraint.PLACE, None, ("alex",))
    ]


def test_a_way_goes_only_where_the_file_says() -> None:
    file = with_walks()
    with pytest.raises(ValueError, match="does not go where the FILE says"):
        broken(file, worst_case(file), (walk("cafe", "gallery", seconds(9), name="stroll"),))
    with pytest.raises(ValueError, match="is not a WAY in the FILE"):
        broken(file, worst_case(file), (walk("hotel", "gallery", seconds(9), name="swim"),))


def test_what_nobody_needs_can_be_taken_out() -> None:
    document = flight_home()
    document["options"].append(stays("coffee", "art-institute"))
    document["facts"] += [any_time("coffee"), lasts("coffee", "PT10M")]
    file = load(document)
    world = worst_case(file)
    coffee = step(file, "coffee", seconds(13), seconds(13, 10), "alex")
    with_coffee = (coffee, visit(), train(), flight())
    assert broken(file, world, with_coffee) == []
    assert needless(file, world, with_coffee) == [("coffee", "alex")]
    assert needless(file, world, (visit(), train(), flight())) == []


def test_an_itinerary_names_things_from_the_file() -> None:
    with pytest.raises(ValueError, match="at most once"):
        found(visit(), visit())
    with pytest.raises(ValueError, match="PERSONs from the FILE"):
        found(step(STORY, "flight", seconds(17), seconds(19, 30), "jo"))
    with pytest.raises(ValueError, match="where the FILE says"):
        found(Step("flight", "home", "ohare", BOTH, seconds(17), seconds(19, 30)))
