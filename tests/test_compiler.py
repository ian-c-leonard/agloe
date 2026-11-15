"""The COMPILER finds with a solver what the reference checker finds by trying everything."""

from pathlib import Path
from random import Random

import pytest

from agloe import compiler, reference
from agloe.file import File, read
from agloe.reference import Answer, longest_case, worst_case
from tests.stories import (
    EXAMPLES,
    any_time,
    cutoff,
    lasts,
    lasts_between,
    lock,
    moves,
    seconds,
    starts_at,
    stays,
    trip,
)
from tests.test_cross_check import a_shared_ride, random_trip

FILES = sorted(
    path for path in EXAMPLES.rglob("*.json") if not path.name.endswith(".expected.json")
)


@pytest.mark.parametrize("path", FILES, ids=lambda path: f"{path.parent.name}/{path.stem}")
def test_the_compiler_gives_the_reference_checkers_report(path: Path) -> None:
    file = read(path)
    assert compiler.check(file) == reference.check(file)


def test_the_compiler_and_the_reference_checker_agree_on_random_trips() -> None:
    """The same Report for every TRIP, and the same ITINERARY shown in both worlds it is chosen in.

    The second comparison matters because the COMPILER asks the reference checker when its own
    search finds nothing. A search that wrongly found nothing would otherwise go unnoticed.
    """
    rng = Random(404)
    trips = [random_trip(rng, leave_out=0) for _ in range(100)]
    trips += [a_shared_ride(rng) for _ in range(100)]
    trips += [random_trip(rng, leave_out=0, contingent=0.6) for _ in range(100)]
    trips += [random_trip(rng, 0.2, contingent=0.3, with_complete=0.3) for _ in range(100)]
    answers: set[Answer] = set()
    robust: set[bool | None] = set()
    for file in trips:
        report = reference.check(file)
        assert compiler.check(file) == report
        for world in (worst_case(file), longest_case(file)):
            every = reference.itineraries(file, world)
            assert compiler.shown(file, world) == (every[0] if every else None)
        answers.add(report.answer)
        robust.add(report.robust)
    assert answers == set(Answer)
    assert robust == {True, False, None}


def at_one_instant(rng: Random) -> File:
    """Three or four OPTIONs that take no time, all at 9:00, between two PLACEs."""
    options = [
        stays(f"option-{number}", rng.choice("ab"))
        if rng.random() < 0.4
        else moves(f"option-{number}", *rng.sample("ab", 2))
        for number in range(rng.choice([3, 4]))
    ]
    facts = [
        fact
        for option in options
        for fact in (
            starts_at(option["id"], 9),
            lasts(option["id"], "PT0S"),
            cutoff(option["id"], "PT0S"),
        )
    ]
    decisions = [
        lock(option["id"], *rng.sample(["alex", "sam"], rng.choice([1, 2])))
        for option in options
        if rng.random() < 0.7
    ]
    return trip(["alex", "sam"], ["a", "b"], options, facts, decisions)


def test_the_compiler_and_the_reference_checker_agree_at_one_instant() -> None:
    """OPTIONs that share an instant must happen in one order for everyone."""
    rng = Random(9)
    feasible: set[bool] = set()
    for _ in range(200):
        file = at_one_instant(rng)
        every = reference.itineraries(file, worst_case(file))
        assert compiler.shown(file, worst_case(file)) == (every[0] if every else None)
        feasible.add(bool(every))
    assert feasible == {True, False}


def test_two_persons_cannot_take_two_rides_in_opposite_orders() -> None:
    """Alex starts at a and Sam at b. Two rides that take no time leave at 9:30, one each way."""
    file = trip(
        ["alex", "sam"],
        ["a", "b"],
        [
            stays("first", "a"),
            stays("second", "b"),
            moves("out", "a", "b"),
            moves("back", "b", "a"),
        ],
        [
            starts_at("first", 9),
            lasts("first", "PT30M"),
            starts_at("second", 9),
            lasts("second", "PT30M"),
            starts_at("out", 9, 30),
            lasts("out", "PT0S"),
            cutoff("out", "PT0S"),
            starts_at("back", 9, 30),
            lasts("back", "PT0S"),
            cutoff("back", "PT0S"),
        ],
        [
            lock("first", "alex"),
            lock("second", "sam"),
            lock("out", "alex", "sam"),
            lock("back", "alex", "sam"),
        ],
    )
    assert compiler.shown(file, worst_case(file)) is None


def test_a_cutoff_counts_from_the_arrival_however_long_ago() -> None:
    """Alex rides to the airport, has a coffee there, and then finds bag drop closed."""

    def with_ride_at(hour: int, minute: int) -> File:
        return trip(
            ["alex"],
            ["hotel", "airport", "home"],
            [
                moves("ride", "hotel", "airport"),
                stays("coffee", "airport"),
                moves("flight", "airport", "home"),
            ],
            [
                starts_at("ride", hour, minute),
                lasts("ride", "PT30M"),
                cutoff("ride", "PT0S"),
                any_time("coffee"),
                lasts("coffee", "PT10M"),
                cutoff("coffee", "PT0S"),
                starts_at("flight", 10),
                lasts("flight", "PT2H"),
                cutoff("flight", "PT45M"),
            ],
            [lock("ride", "alex"), lock("coffee", "alex"), lock("flight", "alex")],
        )

    in_time, too_late = with_ride_at(8, 45), with_ride_at(9, 0)
    assert compiler.check(in_time).answer is Answer.FEASIBLE
    assert compiler.shown(too_late, worst_case(too_late)) is None
    assert compiler.check(too_late) == reference.check(too_late)


def two_ways_through(*ids: str) -> File:
    """Alex goes from a through b to c. An early pair of rides and a late pair both work."""
    rides = {
        "early-to-b": (moves("early-to-b", "a", "b"), 9, 0),
        "early-to-c": (moves("early-to-c", "b", "c"), 9, 30),
        "late-to-b": (moves("late-to-b", "a", "b"), 10, 0),
        "late-to-c": (moves("late-to-c", "b", "c"), 10, 30),
    }
    stops = {"start": (stays("start", "a"), 8, 30), "finish": (stays("finish", "c"), 11, 30)}
    every = {**rides, **stops}
    return trip(
        ["alex"],
        ["a", "b", "c"],
        [every[id][0] for id in ids],
        [
            fact
            for id in ids
            for fact in (
                starts_at(id, every[id][1], every[id][2]),
                lasts(id, "PT20M"),
                cutoff(id, "PT0S"),
            )
        ],
        [lock("start", "alex"), lock("finish", "alex")],
    )


def test_the_options_listed_first_matter_more_than_the_order_they_are_done_in() -> None:
    """The early pair holds the OPTION listed first, though Alex starts with one listed last."""
    file = two_ways_through("early-to-c", "late-to-b", "late-to-c", "start", "finish", "early-to-b")
    report = compiler.check(file)
    assert [step.option for step in report.itinerary] == [
        "start",
        "early-to-b",
        "early-to-c",
        "finish",
    ]
    assert report == reference.check(file)


def a_day_in_chicago(cab: dict[str, object]) -> File:
    """Three PERSONs, ten OPTIONs: far more choices than the reference checker can try."""
    everyone = ("alex", "sam", "jo")
    options = [
        stays("breakfast", "hotel"),
        moves("walk-to-museum", "hotel", "art-institute"),
        stays("museum-visit", "art-institute"),
        moves("cab-to-river", "hotel", "river"),
        stays("boat-tour", "river"),
        moves("walk-to-pier", "art-institute", "pier"),
        moves("water-taxi", "river", "pier"),
        stays("lunch", "pier"),
        moves("cab-to-ohare", "pier", "ohare"),
        moves("flight", "ohare", "home"),
    ]
    facts = [
        starts_at("breakfast", 8),
        lasts("breakfast", "PT1H"),
        any_time("walk-to-museum"),
        lasts("walk-to-museum", "PT20M"),
        starts_at("museum-visit", 10),
        lasts("museum-visit", "PT2H"),
        any_time("cab-to-river"),
        lasts("cab-to-river", "PT15M"),
        starts_at("boat-tour", 10, 30),
        lasts("boat-tour", "PT1H30M"),
        any_time("walk-to-pier"),
        lasts("walk-to-pier", "PT25M"),
        starts_at("water-taxi", 12, 15),
        lasts("water-taxi", "PT20M"),
        starts_at("lunch", 13),
        lasts("lunch", "PT1H"),
        any_time("cab-to-ohare"),
        cab,
        starts_at("flight", 17),
        lasts("flight", "PT2H30M"),
        cutoff("flight", "PT45M"),
    ]
    facts += [cutoff(option["id"], "PT0S") for option in options[1:9]]
    decisions = [
        lock("breakfast", *everyone),
        lock("museum-visit", "alex", "sam"),
        lock("boat-tour", "jo"),
        lock("lunch", *everyone),
        lock("flight", *everyone),
    ]
    places = ["hotel", "art-institute", "river", "pier", "ohare", "home"]
    return trip(list(everyone), places, options, facts, decisions)


def test_the_compiler_plans_a_day_the_reference_checker_cannot_try() -> None:
    file = a_day_in_chicago(lasts("cab-to-ohare", "PT50M"))
    report = compiler.check(file)
    assert report.answer is Answer.FEASIBLE
    assert report.robust is True
    assert [(step.option, step.persons, step.start) for step in report.itinerary] == [
        ("breakfast", ("alex", "sam", "jo"), seconds(8)),
        ("walk-to-museum", ("alex", "sam"), seconds(9)),
        ("cab-to-river", ("jo",), seconds(9)),
        ("museum-visit", ("alex", "sam"), seconds(10)),
        ("boat-tour", ("jo",), seconds(10, 30)),
        ("walk-to-pier", ("alex", "sam"), seconds(12)),
        ("water-taxi", ("jo",), seconds(12, 15)),
        ("lunch", ("alex", "sam", "jo"), seconds(13)),
        ("cab-to-ohare", ("alex", "sam", "jo"), seconds(14)),
        ("flight", ("alex", "sam", "jo"), seconds(17)),
    ]
    assert reference.broken(file, worst_case(file), report.itinerary) == []


def test_the_compiler_warns_when_the_day_is_not_robust() -> None:
    """The cab to O'Hare can take up to two and a half hours."""
    file = a_day_in_chicago(lasts_between("cab-to-ohare", "PT40M", "PT2H30M"))
    report = compiler.check(file)
    assert report.answer is Answer.FEASIBLE
    assert report.robust is False
    assert [(found.constraint, found.option, found.late) for found in report.at_worst] == [
        (reference.Constraint.ARRIVAL, "flight", 15 * 60)
    ]


def test_the_search_refuses_unlisted_options_for_now() -> None:
    file = a_day_in_chicago(lasts("cab-to-ohare", "PT50M"))
    with pytest.raises(ValueError, match="unlisted OPTIONs"):
        compiler.shown(file, reference.best_case(file))
