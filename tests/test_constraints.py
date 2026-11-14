"""Each CONSTRAINT, shown by one ITINERARY that meets it and one that does not."""

import pytest

from agloe.file import File, load
from agloe.reference import Broken, Constraint, Itinerary, Step, best_case, broken, worst_case
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
    trip,
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


def test_nothing_happens_without_need() -> None:
    document = flight_home()
    document["options"].append(stays("coffee", "art-institute"))
    document["facts"] += [any_time("coffee"), lasts("coffee", "PT10M")]
    file = load(document)
    coffee = step(file, "coffee", seconds(13), seconds(13, 10), "alex")
    assert found(coffee, visit(), train(), flight(), file=file) == [
        Broken(Constraint.NEED, "coffee", ("alex",))
    ]


def test_an_itinerary_names_things_from_the_file() -> None:
    with pytest.raises(ValueError, match="at most once"):
        found(visit(), visit())
    with pytest.raises(ValueError, match="PERSONs from the FILE"):
        found(step(STORY, "flight", seconds(17), seconds(19, 30), "jo"))
    with pytest.raises(ValueError, match="where the FILE says"):
        found(Step("flight", "home", "ohare", BOTH, seconds(17), seconds(19, 30)))
