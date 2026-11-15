"""The command: ``agloe check FILE`` prints the report for one FILE, in words or as JSON."""

import json
from pathlib import Path

import pytest

from agloe import compiler, report
from agloe.cli import main
from agloe.file import load
from agloe.reference import Answer
from tests.stories import (
    EXAMPLES,
    any_time,
    at,
    complete,
    cutoff,
    flight_home,
    lasts,
    lock,
    moves,
    starts_at,
    stays,
    trip,
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
        document["facts"].append(complete("art-institute", "ohare"))
    file = load(document)
    return report.as_text(file, compiler.check(file))


def test_several_ways_to_make_a_trip_work_are_numbered() -> None:
    assert with_a_cab(any_time("cab")).splitlines()[2:] == [
        "The trip works in any of these cases:",
        "  1. Cab to O'Hare takes 45 min or less.",
        "  2. There are other ways from the Art Institute to O'Hare that take 45 min or less.",
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


def test_a_trip_with_nothing_to_do_says_so() -> None:
    file = trip([], [], [], [], [])
    assert report.as_text(file, compiler.check(file)) == (
        "FEASIBLE: this trip works.\n\nNobody has to do anything.\n\n"
        "This plan holds however long the uncertain parts take.\n"
    )
