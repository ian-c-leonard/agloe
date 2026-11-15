"""The three answers, ROBUST, the ITINERARY shown and the evidence, on small TRIPs."""

from agloe.file import load
from agloe.reference import Answer, Missing, Unknown, check
from tests.stories import (
    any_time,
    at,
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
    without,
)

MORNING = [
    stays("breakfast", "hotel"),
    moves("walk", "hotel", "office"),
    stays("meeting", "office"),
]
MORNING_FACTS = [
    starts_at("breakfast", 8),
    lasts("breakfast", "PT1H"),
    any_time("walk"),
    starts_at("meeting", 10),
    lasts("meeting", "PT30M"),
]
MORNING_LOCKS = [lock("breakfast", "alex"), lock("meeting", "alex")]


def test_an_unrecorded_duration_is_not_a_choice() -> None:
    """Nobody recorded how long the walk takes, so the COMPILER does not pick a length."""
    facts = [*MORNING_FACTS, cutoff("meeting", "PT0S")]
    report = check(trip(["alex"], ["hotel", "office"], MORNING, facts, MORNING_LOCKS))
    assert report.answer is Answer.UNDETERMINED
    assert report.missing == (Missing(Unknown("duration", "walk"), at_most=3600),)


def test_two_unknown_facts_can_both_matter() -> None:
    report = check(trip(["alex"], ["hotel", "office"], MORNING, MORNING_FACTS, MORNING_LOCKS))
    assert report.answer is Answer.UNDETERMINED
    assert report.missing == (
        Missing(Unknown("duration", "walk"), at_most=None),
        Missing(Unknown("cutoff", "meeting"), at_most=None),
    )


def test_an_unrecorded_start_is_not_a_choice() -> None:
    file = trip(
        ["alex"],
        ["hotel"],
        [stays("dinner", "hotel")],
        [lasts("dinner", "PT1H")],
        [lock("dinner", "alex")],
    )
    report = check(file)
    assert report.answer is Answer.UNDETERMINED
    assert report.missing == (Missing(Unknown("start", "dinner"), at_most=None),)


def test_an_unrecorded_cutoff_matters_to_someone_who_travels() -> None:
    """With no FACT about bag drop, it works only if bag drop closes at most an hour before."""
    report = check(load(without(flight_home(), "bag-drop")))
    assert report.answer is Answer.UNDETERMINED
    assert report.missing == (Missing(Unknown("cutoff", "flight"), at_most=3600),)


def test_an_unrecorded_duration_does_not_matter_when_nothing_follows() -> None:
    report = check(load(without(flight_home(), "flight-length")))
    assert report.answer is Answer.FEASIBLE
    assert report.itinerary[-1].option == "flight"
    assert report.itinerary[-1].end is None
    assert "flight-length" not in report.relies_on


def test_being_in_two_places_at_once_needs_no_complete_fact() -> None:
    file = trip(
        ["alex"],
        ["museum", "theater"],
        [stays("visit", "museum"), stays("show", "theater")],
        [
            starts_at("visit", 14),
            lasts("visit", "PT1H"),
            starts_at("show", 14, 30),
            lasts("show", "PT1H"),
        ],
        [lock("visit", "alex"), lock("show", "alex")],
    )
    report = check(file)
    assert report.answer is Answer.INFEASIBLE
    assert report.conflict == ("visit-time", "visit-length", "show-time", "lock-visit", "lock-show")


def test_listed_options_join_up() -> None:
    file = trip(
        ["alex"],
        ["a", "b", "c"],
        [
            stays("pack", "a"),
            moves("first-leg", "a", "b"),
            moves("second-leg", "b", "c"),
            stays("meeting", "c"),
        ],
        [
            starts_at("pack", 9),
            lasts("pack", "PT0S"),
            any_time("first-leg"),
            lasts("first-leg", "PT1M"),
            any_time("second-leg"),
            lasts("second-leg", "PT1M"),
            cutoff("second-leg", "PT0S"),
            starts_at("meeting", 9, 3),
            lasts("meeting", "PT10M"),
            cutoff("meeting", "PT0S"),
        ],
        [lock("pack", "alex"), lock("meeting", "alex")],
    )
    report = check(file)
    assert report.answer is Answer.FEASIBLE
    assert [(step.option, step.start) for step in report.itinerary] == [
        ("pack", seconds(9)),
        ("first-leg", seconds(9)),
        ("second-leg", seconds(9, 1)),
        ("meeting", seconds(9, 3)),
    ]


def test_an_option_nobody_needs_changes_nothing() -> None:
    document = flight_home()
    document["options"].append(stays("night-tour", "home"))
    document["facts"] += [starts_at("night-tour", 3), lasts("night-tour", "PT9H")]
    assert check(load(document)) == check(load(flight_home()))


def test_only_those_who_need_an_option_take_part() -> None:
    document = flight_home()
    document["decisions"][1]["persons"] = ["alex"]
    report = check(load(document))
    assert report.answer is Answer.FEASIBLE
    assert [(step.option, step.persons) for step in report.itinerary] == [
        ("museum-visit", ("alex", "sam")),
        ("blue-line", ("alex",)),
        ("flight", ("alex",)),
    ]


def with_a_cab_listed_first(length: dict[str, object]) -> dict[str, object]:
    document = flight_home()
    document["options"].insert(0, moves("cab", "art-institute", "ohare"))
    document["facts"] += [any_time("cab"), length]
    return document


def test_the_itinerary_shown_uses_the_options_listed_first() -> None:
    report = check(load(with_a_cab_listed_first(lasts("cab", "PT30M"))))
    assert [step.option for step in report.itinerary] == ["museum-visit", "cab", "flight"]
    assert report.robust is True


def test_a_robust_itinerary_is_shown_before_any_other() -> None:
    """The cab is listed first but can take 90 minutes. The train always makes it."""
    report = check(load(with_a_cab_listed_first(lasts_between("cab", "PT30M", "PT1H30M"))))
    assert report.answer is Answer.FEASIBLE
    assert [step.option for step in report.itinerary] == ["museum-visit", "blue-line", "flight"]
    assert report.robust is True
    assert report.at_worst == ()


def test_a_robust_itinerary_allows_for_the_longest_durations() -> None:
    document = flight_home()
    document["facts"][3] = lasts_between("blue-line", "PT50M", "PT1H10M")
    document["facts"][3]["id"] = "train-length"
    report = check(load(document))
    assert report.robust is True
    train = report.itinerary[1]
    assert (train.start, train.end) == (seconds(15), seconds(16, 10))


def test_a_trip_with_no_fixed_time_still_has_an_order() -> None:
    file = trip(
        ["alex"],
        ["a", "b"],
        [stays("pack", "a"), moves("ride", "a", "b")],
        [any_time("pack"), lasts("pack", "PT30M"), any_time("ride"), lasts("ride", "PT1H")],
        [lock("pack", "alex"), lock("ride", "alex")],
    )
    report = check(file)
    assert report.answer is Answer.FEASIBLE
    assert [(step.option, step.start, step.end) for step in report.itinerary] == [
        ("pack", 0, 1800),
        ("ride", 1800, 5400),
    ]


def test_an_option_before_a_fixed_time_starts_as_late_as_it_can() -> None:
    file = trip(
        ["alex"],
        ["hotel", "office"],
        [moves("walk", "hotel", "office"), stays("meeting", "office")],
        [
            any_time("walk"),
            lasts("walk", "PT20M"),
            starts_at("meeting", 10),
            lasts("meeting", "PT30M"),
            cutoff("meeting", "PT10M"),
        ],
        [lock("meeting", "alex"), lock("walk", "alex")],
    )
    report = check(file)
    assert [(step.option, step.start) for step in report.itinerary] == [
        ("walk", seconds(9, 30)),
        ("meeting", seconds(10)),
    ]


def test_a_complete_set_says_nothing_after_its_span() -> None:
    """The listed train is far too slow. An unlisted way that leaves after the span might exist."""
    document = flight_home()
    document["facts"][3] = lasts("blue-line", "PT5H")
    document["facts"][4] = starts_at("flight", 19)
    ways = {
        "from": "art-institute",
        "to": "ohare",
        "leaving": {"earliest": at(12), "latest": at(16)},
    }
    document["facts"].append({"id": "ways-to-ohare", "complete": ways})
    report = check(load(document))
    assert report.answer is Answer.UNDETERMINED
    another = Unknown("another way", origin="art-institute", destination="ohare")
    assert report.missing == (Missing(another, at_most=2 * 3600 + 14 * 60 + 59),)


def test_a_complete_set_says_nothing_before_its_span() -> None:
    """Packing can be done at any time, so Alex could leave before the span begins."""
    ways = {"from": "a", "to": "b", "leaving": {"earliest": at(9), "latest": at(10, 30)}}
    file = trip(
        ["alex"],
        ["a", "b"],
        [stays("pack", "a"), stays("meeting", "b")],
        [
            any_time("pack"),
            lasts("pack", "PT30M"),
            starts_at("meeting", 10),
            lasts("meeting", "PT1H"),
            cutoff("meeting", "PT0S"),
            {"id": "ways", "complete": ways},
        ],
        [lock("pack", "alex"), lock("meeting", "alex")],
    )
    report = check(file)
    assert report.answer is Answer.UNDETERMINED
    assert report.missing == (Missing(Unknown("another way", origin="a", destination="b"), None),)


def test_a_complete_set_that_covers_every_leaving_time_makes_it_infeasible() -> None:
    ways = {"from": "a", "to": "b", "leaving": {"earliest": at(0), "latest": at(23, 59)}}
    file = trip(
        ["alex"],
        ["a", "b"],
        [stays("breakfast", "a"), stays("meeting", "b")],
        [
            starts_at("breakfast", 8),
            lasts("breakfast", "PT30M"),
            starts_at("meeting", 10),
            lasts("meeting", "PT1H"),
            cutoff("meeting", "PT0S"),
            {"id": "ways", "complete": ways},
        ],
        [lock("breakfast", "alex"), lock("meeting", "alex")],
    )
    report = check(file)
    assert report.answer is Answer.INFEASIBLE
    assert report.conflict == (
        "breakfast-time",
        "meeting-time",
        "ways",
        "lock-breakfast",
        "lock-meeting",
    )


def test_a_step_after_a_shared_step_takes_its_time_from_it() -> None:
    """Alex's meeting fixes when both finish packing. Sam's tram and nap follow from that."""
    file = trip(
        ["alex", "sam"],
        ["hotel", "office", "beach"],
        [
            stays("pack", "hotel"),
            moves("walk", "hotel", "office"),
            stays("meeting", "office"),
            moves("tram", "hotel", "beach"),
            stays("nap", "beach"),
        ],
        [
            any_time("pack"),
            lasts("pack", "PT30M"),
            any_time("walk"),
            lasts("walk", "PT15M"),
            starts_at("meeting", 10),
            lasts("meeting", "PT1H"),
            cutoff("meeting", "PT0S"),
            any_time("tram"),
            lasts("tram", "PT20M"),
            any_time("nap"),
            lasts("nap", "PT1H"),
            cutoff("nap", "PT0S"),
        ],
        [lock("pack", "alex", "sam"), lock("meeting", "alex"), lock("nap", "sam")],
    )
    report = check(file)
    assert report.answer is Answer.FEASIBLE
    assert [(step.option, step.persons, step.start) for step in report.itinerary] == [
        ("pack", ("alex", "sam"), seconds(9, 15)),
        ("walk", ("alex",), seconds(9, 45)),
        ("tram", ("sam",), seconds(9, 45)),
        ("meeting", ("alex",), seconds(10)),
        ("nap", ("sam",), seconds(10, 5)),
    ]


def test_an_empty_file_is_feasible() -> None:
    report = check(load({"persons": [], "places": [], "options": [], "facts": [], "decisions": []}))
    assert report.answer is Answer.FEASIBLE
    assert report.itinerary == ()
