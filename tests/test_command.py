"""The command: ``agloe check FILE`` prints the report for one FILE, in words or as JSON."""

import json
from pathlib import Path

import pytest

from agloe import compiler, report
from agloe.answers import Answer
from agloe.cli import main
from agloe.file import File, load
from tests.stories import (
    EXAMPLES,
    any_time,
    at,
    complete,
    cutoff,
    flight_home,
    lasts,
    lasts_between,
    lock,
    moves,
    starts_at,
    stays,
    takes,
    takes_between,
    trip,
    way,
    way_between,
)

FILES = sorted(
    path for path in EXAMPLES.rglob("*.json") if not path.name.endswith(".expected.json")
)


def beside(path: Path, ending: str) -> Path:
    return path.with_name(path.stem + ending)


@pytest.mark.parametrize("path", FILES, ids=lambda path: f"{path.parent.name}/{path.stem}")
def test_the_command_prints_the_expected_result(
    path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """As JSON, the command prints exactly the expected result beside the example."""
    code = main(["check", str(path), "--json"])
    printed = json.loads(capsys.readouterr().out)
    expected = json.loads(beside(path, ".expected.json").read_text())
    assert printed == expected
    assert code == (0 if expected["answer"] == "FEASIBLE" else 1)


@pytest.mark.parametrize("path", FILES, ids=lambda path: f"{path.parent.name}/{path.stem}")
def test_the_command_prints_the_expected_words(
    path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["check", str(path)])
    assert capsys.readouterr().out == beside(path, ".expected.txt").read_text()


def test_a_file_that_breaks_the_format_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    document = flight_home()
    document["facts"][0]["starts_at"] = "2027-01-15T14:00:00-05:00[America/Chicago]"
    del document["places"][0]["name"]
    path = tmp_path / "trip.json"
    path.write_text(json.dumps(document))
    assert main(["check", str(path)]) == 2
    printed = capsys.readouterr()
    assert printed.out == ""
    assert printed.err.splitlines() == [
        f"{path} does not follow the format:",
        "  /places/0: 'name' is a required property",
    ]


def test_a_file_that_is_not_there_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "nowhere.json"
    assert main(["check", str(path)]) == 2
    assert capsys.readouterr().err == f"{path}: No such file or directory\n"


def with_a_cab(*facts: dict[str, object], only_listed_ways: bool = False) -> str:
    """The story in which they leave the museum too late, with a cab added, in words."""
    document = json.loads((EXAMPLES / "flight-home" / "depends-on-another-way.json").read_text())
    document["options"].append(moves("cab", "art-institute", "ohare"))
    document["options"][-1]["name"] = "Cab to O'Hare"
    document["facts"] += facts
    if only_listed_ways:
        document["facts"].append(complete(None, "ohare"))
    file = load(document)
    return report.as_text(file, compiler.check(file))


def test_several_ways_to_make_a_trip_work_are_numbered() -> None:
    assert with_a_cab(any_time("cab")).splitlines()[2:] == [
        "The trip works in any of these cases:",
        "  1. Cab to O'Hare takes 45 min or less.",
        "  2. There are other WAYs from the Art Institute to O'Hare that take 45 min or less.",
    ]


def test_two_unknown_facts_that_are_both_needed_are_joined() -> None:
    assert with_a_cab(only_listed_ways=True).splitlines()[2:] == [
        "The trip works if Cab to O'Hare can start at any time and Cab to O'Hare is quick enough."
    ]


def test_an_unknown_cutoff_is_named_with_its_place() -> None:
    document = flight_home()
    document["facts"] = [fact for fact in document["facts"] if fact["id"] != "bag-drop"]
    file = load(document)
    assert report.as_text(file, compiler.check(file)).splitlines()[2] == (
        "The trip works if people must be at O'Hare 1 h or less before Flight home starts."
    )


def test_a_plan_shows_its_days_and_an_unknown_end() -> None:
    """Dinner is late on the 15th. The night train leaves the next day, and nobody timed it."""
    file = trip(
        ["alex"],
        ["hotel", "station"],
        [stays("dinner", "hotel"), moves("night-train", "hotel", "station")],
        [
            starts_at("dinner", 23, 30),
            lasts("dinner", "PT45M"),
            any_time("night-train"),
            cutoff("night-train", "PT0S"),
        ],
        [lock("dinner", "alex"), lock("night-train", "alex")],
    )
    found = compiler.check(file)
    assert found.answer is Answer.FEASIBLE
    assert report.as_text(file, found).splitlines()[:7] == [
        "FEASIBLE: this trip works.",
        "",
        "Saturday 15 May 2027 (times in America/Chicago)",
        "  11:30 pm to 12:15 am on 16 May: dinner, alex",
        "",
        "Sunday 16 May 2027 (times in America/Chicago)",
        "  12:15 am to an unknown time: night-train, alex",
    ]
    assert report.as_json(file, found)["itinerary"] == [
        {"option": "dinner", "persons": ["alex"], "start": at(23, 30), "end": at(0, 15, day=16)},
        {"option": "night-train", "persons": ["alex"], "start": at(0, 15, day=16), "end": None},
    ]


def a_walk_to_dinner(*facts: dict[str, object]) -> File:
    """Alex and Sam have a drink at the hotel at 6:00 pm and dinner at a restaurant at 7:00 pm."""
    return trip(
        ["alex", "sam"],
        ["hotel", "restaurant"],
        [stays("drink", "hotel"), stays("dinner", "restaurant")],
        [
            starts_at("drink", 18),
            lasts("drink", "PT30M"),
            starts_at("dinner", 19),
            lasts("dinner", "PT2H"),
            cutoff("dinner", "PT0S"),
            *facts,
        ],
        [lock("drink", "alex", "sam"), lock("dinner", "alex", "sam")],
        [way_between("walk", "hotel", "restaurant")],
    )


def test_a_plan_shows_the_ways_people_take() -> None:
    """In words, Alex and Sam share a line for the walk. As JSON, each one's walk is a step."""
    file = a_walk_to_dinner(takes_between("walk", "PT10M", "PT20M"))
    found = compiler.check(file)
    words = report.as_text(file, found).splitlines()
    assert words[2:6] == [
        "Saturday 15 May 2027 (times in America/Chicago)",
        "  6:00 pm to 6:30 pm: drink, alex and sam",
        "  6:30 pm to 6:50 pm: walk, alex and sam",
        "  7:00 pm to 9:00 pm: dinner, alex and sam",
    ]
    assert "  walk-length: walk takes between 10 min and 20 min" in words
    assert report.as_json(file, found)["itinerary"] == [
        {"option": "drink", "persons": ["alex", "sam"], "start": at(18), "end": at(18, 30)},
        {"way": "walk", "persons": ["alex"], "start": at(18, 30), "end": at(18, 50)},
        {"way": "walk", "persons": ["sam"], "start": at(18, 30), "end": at(18, 50)},
        {"option": "dinner", "persons": ["alex", "sam"], "start": at(19), "end": at(21)},
    ]


def test_a_way_nobody_timed_is_named_in_what_is_missing() -> None:
    file = a_walk_to_dinner()
    found = compiler.check(file)
    assert report.as_text(file, found).splitlines()[2:] == [
        "The trip works in any of these cases:",
        "  1. Walk takes 30 min or less.",
        "  2. There are other WAYs from hotel to restaurant that take 30 min or less.",
    ]
    assert report.as_json(file, found)["missing"] == [
        [{"what": "duration", "way": "walk", "at_most": "PT30M"}],
        [{"what": "other ways", "from": "hotel", "to": "restaurant", "at_most": "PT30M"}],
    ]


def test_a_trip_with_nothing_to_do_says_so() -> None:
    file = trip([], [], [], [], [])
    assert report.as_text(file, compiler.check(file)) == (
        "FEASIBLE: this trip works.\n\nNobody has to do anything.\n"
    )


def test_a_report_with_a_time_past_the_year_9999_is_not_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The stay starts in the last second of the year 9999 and ends one second later."""
    document = {
        "persons": [{"id": "alex", "name": "Alex"}],
        "places": [{"id": "pier", "name": "Navy Pier"}],
        "options": [stays("fireworks", "pier")],
        "ways": [],
        "facts": [
            {
                "id": "fireworks-time",
                "option": "fireworks",
                "starts_at": "9999-12-31T23:59:59+00:00[UTC]",
            },
            lasts("fireworks", "PT1S"),
        ],
        "decisions": [lock("fireworks", "alex")],
    }
    assert compiler.check(load(document)).answer is Answer.FEASIBLE
    path = tmp_path / "trip.json"
    path.write_text(json.dumps(document))
    for arguments in (["check", str(path)], ["check", str(path), "--json"]):
        assert main(arguments) == 2
        printed = capsys.readouterr()
        assert printed.out == ""
        assert printed.err == (
            f"{path}: the report holds a time outside the years 0001 to 9999, "
            "so it cannot be written\n"
        )


def test_a_complete_fact_is_put_in_words_for_the_places_it_names() -> None:
    """Alex is at the hotel at 9:00 and at the pier at 10:00, and the FILE lists no way there."""
    words = {
        ("hotel", "pier"): "ways-hotel-pier: every way straight from hotel to pier",
        (None, "pier"): "ways-to-pier: every way straight to pier",
        ("hotel", None): "ways-from-hotel: every way straight from hotel",
        (None, None): "ways: every way from one PLACE straight to another",
    }
    for (origin, destination), expected in words.items():
        file = trip(
            ["alex"],
            ["hotel", "pier"],
            [stays("breakfast", "hotel"), stays("fireworks", "pier")],
            [
                starts_at("breakfast", 9),
                lasts("breakfast", "PT0S"),
                starts_at("fireworks", 10),
                complete(origin, destination),
            ],
            [lock("breakfast", "alex"), lock("fireworks", "alex")],
        )
        printed = report.as_text(file, compiler.check(file)).splitlines()
        assert printed[0] == "INFEASIBLE: this trip cannot work."
        span = "that leaves between 12:00 am on Saturday 15 May 2027 and 11:59 pm is listed"
        assert f"  {expected} {span}" in printed


def test_a_warning_names_the_way_and_the_time_it_is_taken() -> None:
    """The visit can run an hour late. Then Alex is still there when the walk should start."""
    file = trip(
        ["alex"],
        ["gallery", "pier"],
        [stays("visit", "gallery"), stays("dinner", "pier")],
        [
            starts_at("visit", 9),
            lasts_between("visit", "PT30M", "PT1H30M"),
            starts_at("dinner", 10, 30),
            lasts("dinner", "PT1H"),
            cutoff("dinner", "PT0S"),
            takes("walk", "PT30M"),
        ],
        [lock("visit", "alex"), lock("dinner", "alex")],
        [way("walk", "gallery", "pier")],
    )
    found = compiler.check(file)
    assert report.as_json(file, found)["at_worst"] == [
        {
            "constraint": "Each PERSON is in one place at a time",
            "step": 1,
            "way": "walk",
            "from": "gallery",
            "to": "pier",
            "start": at(9, 30),
            "persons": ["alex"],
            "late": "PT1H",
        }
    ]
    assert report.as_text(file, found).splitlines()[6:9] == [
        "",
        "WARNING: no plan is sure to hold if the uncertain parts take their longest. In this plan:",
        "  alex would still be busy for 1 h at 9:30 am, the time to take walk.",
    ]


def test_a_plan_that_holds_with_uncertain_parts_says_so() -> None:
    document = json.loads((EXAMPLES / "flight-home" / "works-but-risky.json").read_text())
    for fact in document["facts"]:
        if fact["id"] == "train-length":
            fact["contingent_duration"]["longest"] = "PT1H15M"
    file = load(document)
    lines = report.as_text(file, compiler.check(file)).splitlines()
    assert lines[0] == "FEASIBLE: this trip works."
    assert lines[7] == (
        "This plan holds however long the uncertain parts take, within the ranges the FILE states."
    )


def test_times_show_their_offset_when_the_clocks_change() -> None:
    """Chicago's clocks go back at 2:00 am on 7 November 2027, so 1:15 am comes twice."""
    document = {
        "persons": [{"id": "alex", "name": "Alex"}],
        "places": [{"id": "hotel", "name": "Hotel"}],
        "options": [stays("night-shift", "hotel")],
        "ways": [],
        "facts": [
            {
                "id": "night-shift-time",
                "option": "night-shift",
                "starts_at": "2027-11-07T01:45:00-05:00[America/Chicago]",
            },
            lasts("night-shift", "PT30M"),
        ],
        "decisions": [lock("night-shift", "alex")],
    }
    file = load(document)
    lines = report.as_text(file, compiler.check(file)).splitlines()
    assert lines[2:4] == [
        "Sunday 7 November 2027 (times in America/Chicago)",
        "  1:45 am (UTC-5) to 1:15 am (UTC-6): night-shift, Alex",
    ]
    assert lines[6] == (
        "  night-shift-time: night-shift starts at 1:45 am (UTC-5) on Sunday 7 November 2027"
    )


def test_the_same_way_taken_twice_has_a_line_each_time() -> None:
    """Alex and Sam walk to dinner and walk back for a nightcap at the hotel."""
    file = trip(
        ["alex", "sam"],
        ["hotel", "restaurant"],
        [stays("dinner", "restaurant"), stays("nightcap", "hotel")],
        [
            starts_at("dinner", 19),
            lasts("dinner", "PT2H"),
            starts_at("nightcap", 21, 30),
            lasts("nightcap", "PT30M"),
            cutoff("nightcap", "PT0S"),
            takes("walk", "PT20M"),
        ],
        [lock("dinner", "alex", "sam"), lock("nightcap", "alex", "sam")],
        [way_between("walk", "hotel", "restaurant")],
    )
    assert report.as_text(file, compiler.check(file)).splitlines()[3:6] == [
        "  7:00 pm to 9:00 pm: dinner, alex and sam",
        "  9:00 pm to 9:20 pm: walk, alex and sam",
        "  9:30 pm to 10:00 pm: nightcap, alex and sam",
    ]
    earlier = [starts_at("nightcap", 18), lasts("nightcap", "PT30M"), starts_at("dinner", 19)]
    there_and_back = trip(
        ["alex", "sam"],
        ["hotel", "restaurant"],
        [stays("nightcap", "hotel"), stays("dinner", "restaurant"), stays("bed", "hotel")],
        [
            *earlier,
            lasts("dinner", "PT2H"),
            cutoff("dinner", "PT0S"),
            starts_at("bed", 22),
            cutoff("bed", "PT0S"),
            takes("walk", "PT20M"),
        ],
        [lock(name, "alex", "sam") for name in ("nightcap", "dinner", "bed")],
        [way_between("walk", "hotel", "restaurant")],
    )
    lines = report.as_text(there_and_back, compiler.check(there_and_back)).splitlines()
    assert [line for line in lines if ": walk, " in line] == [
        "  6:30 pm to 6:50 pm: walk, alex and sam",
        "  9:00 pm to 9:20 pm: walk, alex and sam",
    ]


def test_a_way_that_must_take_no_time_is_put_plainly() -> None:
    """Alex is at the hotel and at the restaurant at the same instant."""
    file = trip(
        ["alex"],
        ["hotel", "restaurant"],
        [stays("call", "hotel"), stays("toast", "restaurant")],
        [
            starts_at("call", 19),
            lasts("call", "PT0S"),
            starts_at("toast", 19),
            lasts("toast", "PT0S"),
            cutoff("toast", "PT0S"),
            cutoff("call", "PT0S"),
        ],
        [lock("call", "alex"), lock("toast", "alex")],
    )
    assert report.as_text(file, compiler.check(file)).splitlines()[2:] == [
        "The trip works in any of these cases:",
        "  1. There are other WAYs from hotel to restaurant that take no time.",
        "  2. There are other WAYs from restaurant to hotel that take no time.",
    ]
