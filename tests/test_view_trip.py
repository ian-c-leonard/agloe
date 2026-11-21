"""What a page is sent of a TRIP, so that it can draw it.

The command reads the FILE with the reader that the COMPILER uses. With each report it sends
the names, who takes part in each step, and each time on the clocks that the report shows times
on. For a FEASIBLE TRIP the steps are the ITINERARY of the report. For any other TRIP the report
shows no ITINERARY, and the steps are the OPTIONs that a LOCK names, at the times the FILE
states.
"""

import copy
import functools
import json
import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from agloe import compiler
from agloe.answers import Answer, Report
from agloe.file import File, read
from agloe.reference import Step
from agloe.view.trip import holds, shown
from tests.stories import (
    EXAMPLES,
    any_time,
    lasts,
    lasts_between,
    lock,
    moves,
    seconds,
    starts_at,
    stays,
    trip,
    way_between,
)

STORY = EXAMPLES / "flight-home"
FILES = sorted(
    path for path in EXAMPLES.rglob("*.json") if not path.name.endswith(".expected.json")
)
# A line of the report in words that shows one step of the ITINERARY.
LINE = re.compile(r"^  \d{1,2}:\d\d(:\d\d)? [ap]m.* to .+: .+, .+$")

type Trip = dict[str, Any]


def beside(path: Path, ending: str) -> Path:
    return path.with_name(path.stem + ending)


def name_of(path: Path) -> str:
    return f"{path.parent.name}/{path.stem}"


def expected(path: Path) -> dict[str, Any]:
    found: dict[str, Any] = json.loads(beside(path, ".expected.json").read_text())
    return found


FEASIBLE = [path for path in FILES if expected(path)["answer"] == "FEASIBLE"]


def sent_for(file: File, report: Report) -> Trip:
    """What a page is sent of the TRIP in a FILE, with this report on it."""
    sent = shown(file, report)
    assert sent is not None
    return cast("Trip", sent)


@functools.cache
def _drawn(path: Path) -> Trip:
    file = read(path)
    return sent_for(file, compiler.check(file))


def drawn(path: Path) -> Trip:
    """What a page is sent of the TRIP in this FILE, with the report on it."""
    return copy.deepcopy(_drawn(path))


@pytest.mark.parametrize("path", FILES, ids=name_of)
def test_every_example_is_sent_as_a_trip_that_a_page_can_draw(path: Path) -> None:
    sent = drawn(path)
    file = read(path)
    assert holds(sent)
    # Nothing in it is lost on the way to the page.
    assert json.loads(json.dumps(sent)) == sent
    assert sent["zone"] == file.zone
    assert sent["persons"] == [{"id": each.id, "name": each.name} for each in file.persons]
    assert sent["places"] == [{"id": each.id, "name": each.name} for each in file.places]
    assert sent["itinerary"] is (expected(path)["answer"] == "FEASIBLE")


@pytest.mark.parametrize("path", FEASIBLE, ids=name_of)
def test_a_feasible_trip_is_sent_with_the_itinerary_of_its_report(path: Path) -> None:
    """Each PERSON takes the same steps, at the same times, as in the report."""
    sent = drawn(path)

    def clock(written: str | None) -> str | None:
        # The report writes a time with its offset and its time zone after the clock time.
        return None if written is None else written[:19]

    in_report = Counter(
        (step.get("option"), step.get("way"), person, clock(step["start"]), clock(step["end"]))
        for step in expected(path)["itinerary"]
        for person in step["persons"]
    )
    in_trip = Counter(
        (step["option"], step["way"], person, step["start"], step["end"])
        for step in sent["steps"]
        for person in step["persons"]
    )
    assert in_trip == in_report
    # The report in words names PERSONs who take a WAY together on one line. So does the page.
    lines = [
        line for line in beside(path, ".expected.txt").read_text().split("\n") if LINE.match(line)
    ]
    assert len(sent["steps"]) == len(lines)
    for step, line in zip(sent["steps"], lines, strict=True):
        assert f": {step['name'] or 'another WAY'}, " in line


def test_each_step_says_which_of_its_persons_a_lock_names() -> None:
    sent = drawn(STORY / "works.json")
    assert [(step["option"], step["locked"]) for step in sent["steps"]] == [
        ("museum-visit", ["alex", "sam"]),
        ("blue-line", []),
        ("flight", ["alex", "sam"]),
    ]


def test_a_lock_that_names_one_of_the_persons_marks_that_person_only() -> None:
    file = trip(
        ["alex", "sam"],
        ["museum"],
        [stays("visit", "museum")],
        [starts_at("visit", 14), lasts("visit", "PT1H")],
        [lock("visit", "sam")],
    )
    visit = Step("visit", "museum", "museum", ("sam", "alex"), seconds(14), seconds(15))
    sent = sent_for(file, Report(Answer.FEASIBLE, itinerary=(visit,)))
    assert sent["steps"] == [
        {
            "option": "visit",
            "way": None,
            "name": "visit",
            "from": "museum",
            "to": "museum",
            # The PERSONs come in the order of the FILE, as they do in the report.
            "persons": ["alex", "sam"],
            "start": "2027-05-15T14:00:00",
            "end": "2027-05-15T15:00:00",
            "locked": ["sam"],
        }
    ]
    assert holds(sent)


def walking() -> File:
    """Alex and Sam, a museum and a hotel, and a walk between the two."""
    return trip(
        ["alex", "sam"],
        ["museum", "hotel"],
        [stays("visit", "museum")],
        [starts_at("visit", 14), lasts("visit", "PT1H")],
        [],
        ways=[way_between("walk", "museum", "hotel")],
    )


def test_persons_who_take_a_way_together_are_one_step() -> None:
    """The report in words names them on one line, and the page draws them as one."""
    file = walking()
    there = [
        Step(None, "museum", "hotel", (person,), seconds(15), seconds(15, 20), way="walk")
        for person in ("alex", "sam")
    ]
    sent = sent_for(file, Report(Answer.FEASIBLE, itinerary=tuple(there)))
    assert sent["steps"] == [
        {
            "option": None,
            "way": "walk",
            "name": "walk",
            "from": "museum",
            "to": "hotel",
            "persons": ["alex", "sam"],
            "start": "2027-05-15T15:00:00",
            "end": "2027-05-15T15:20:00",
            "locked": [],
        }
    ]
    assert holds(sent)


def test_persons_who_take_a_way_apart_are_a_step_each() -> None:
    file = walking()
    apart = (
        Step(None, "museum", "hotel", ("alex",), seconds(15), seconds(15, 20), way="walk"),
        Step(None, "museum", "hotel", ("sam",), seconds(16), seconds(16, 20), way="walk"),
        Step(None, "hotel", "museum", ("alex",), seconds(17), seconds(17, 20), way="walk"),
        Step(None, "hotel", "museum", ("sam",), seconds(17), None, way="walk"),
    )
    sent = sent_for(file, Report(Answer.FEASIBLE, itinerary=apart))
    assert [
        (step["persons"], step["from"], step["start"], step["end"]) for step in sent["steps"]
    ] == [
        (["alex"], "museum", "2027-05-15T15:00:00", "2027-05-15T15:20:00"),
        (["sam"], "museum", "2027-05-15T16:00:00", "2027-05-15T16:20:00"),
        (["alex"], "hotel", "2027-05-15T17:00:00", "2027-05-15T17:20:00"),
        # Nobody knows how long this one takes, so it has no end.
        (["sam"], "hotel", "2027-05-15T17:00:00", None),
    ]
    assert holds(sent)


def test_a_way_that_the_file_does_not_list_has_no_name() -> None:
    """The report calls it another WAY. The page is told that the FILE gives it no name."""
    file = walking()
    other = Step(None, "museum", "hotel", ("alex",), seconds(15), None)
    sent = sent_for(file, Report(Answer.FEASIBLE, itinerary=(other,)))
    (step,) = sent["steps"]
    assert (step["option"], step["way"], step["name"]) == (None, None, None)
    assert holds(sent)


def test_a_trip_with_no_itinerary_is_sent_with_the_options_that_a_lock_names() -> None:
    sent = drawn(STORY / "cannot-work.json")
    assert sent["itinerary"] is False
    both = ["alex", "sam"]
    assert sent["steps"] == [
        {
            "option": "museum-visit",
            "way": None,
            "name": "Museum visit",
            "from": "art-institute",
            "to": "art-institute",
            "persons": both,
            "start": "2027-05-15T14:30:00",
            "end": "2027-05-15T15:30:00",
            "locked": both,
        },
        {
            "option": "flight",
            "way": None,
            "name": "Flight home",
            "from": "ohare",
            "to": "home",
            "persons": both,
            "start": "2027-05-15T17:00:00",
            "end": "2027-05-15T19:30:00",
            "locked": both,
        },
    ]


def locked_only() -> File:
    """A FILE whose LOCKs name OPTIONs with every kind of time, and one OPTION that none names."""
    return trip(
        ["alex", "sam", "jo"],
        ["museum", "hotel", "pier"],
        [
            stays("some-time", "pier"),
            stays("dinner", "hotel"),
            stays("visit", "museum"),
            moves("ride", "museum", "hotel"),
            stays("no-word", "pier"),
            stays("open", "pier"),
            stays("lunch", "museum"),
        ],
        [
            any_time("some-time"),
            lasts("some-time", "PT1H"),
            starts_at("dinner", 19),
            starts_at("visit", 14),
            lasts("visit", "PT1H"),
            starts_at("ride", 14),
            lasts_between("ride", "PT20M", "PT50M"),
            starts_at("open", 9),
            lasts("open", "PT1H"),
            starts_at("lunch", 12),
            lasts("lunch", "PT1H"),
        ],
        [
            lock("some-time", "alex"),
            lock("dinner", "alex", "sam", "jo"),
            {"id": "jo-visits", "lock": "visit", "persons": ["jo"]},
            {"id": "alex-visits", "lock": "visit", "persons": ["alex"]},
            {"id": "alex-visits-again", "lock": "visit", "persons": ["alex"]},
            lock("ride", "sam"),
            lock("no-word", "jo"),
            lock("lunch", "sam", "alex"),
        ],
    )


def test_a_locked_option_is_sent_at_the_time_that_the_file_states() -> None:
    sent = sent_for(locked_only(), Report(Answer.INFEASIBLE))
    assert holds(sent)
    assert sent["itinerary"] is False
    told = [(step["option"], step["persons"], step["start"], step["end"]) for step in sent["steps"]]
    assert told == [
        ("lunch", ["alex", "sam"], "2027-05-15T12:00:00", "2027-05-15T13:00:00"),
        # Several LOCKs name the visit. Each PERSON they name takes part once, in the FILE's order.
        ("visit", ["alex", "jo"], "2027-05-15T14:00:00", "2027-05-15T15:00:00"),
        # The ride takes between 20 and 50 minutes. As in an ITINERARY, it ends after the least.
        ("ride", ["sam"], "2027-05-15T14:00:00", "2027-05-15T14:20:00"),
        # The FILE does not say how long dinner takes.
        ("dinner", ["alex", "sam", "jo"], "2027-05-15T19:00:00", None),
        # No time: one can start at any time, and the FILE says nothing of the other.
        ("some-time", ["alex"], None, None),
        ("no-word", ["jo"], None, None),
    ]
    for step in sent["steps"]:
        assert step["locked"] == step["persons"]
        assert step["way"] is None
    # No LOCK names the OPTION called open, so it is not sent, whatever the FILE says of it.
    assert "open" not in {step["option"] for step in sent["steps"]}


def test_a_trip_that_depends_on_what_nobody_knows_is_sent_like_one_that_cannot_work() -> None:
    assert shown(locked_only(), Report(Answer.UNDETERMINED)) == shown(
        locked_only(), Report(Answer.INFEASIBLE)
    )


def test_every_time_is_on_the_clocks_that_the_report_shows_times_on() -> None:
    """The first time in the FILE names Chicago. A time that names Denver is shown on Chicago's."""
    in_denver = {
        "id": "landing-time",
        "option": "landing",
        "starts_at": "2027-05-15T19:00:00-06:00[America/Denver]",
    }
    file = trip(
        ["alex"],
        ["museum", "denver"],
        [stays("visit", "museum"), stays("landing", "denver")],
        [starts_at("visit", 14), in_denver, lasts("landing", "PT30M")],
        [lock("landing", "alex")],
    )
    assert file.zone == "America/Chicago"
    sent = sent_for(file, Report(Answer.UNDETERMINED))
    assert sent["zone"] == "America/Chicago"
    (step,) = sent["steps"]
    assert (step["start"], step["end"]) == ("2027-05-15T20:00:00", "2027-05-15T20:30:00")


def at_the_end_of_time() -> File:
    """The fireworks start in the last second of the year 9999 and end one second later."""
    last = {
        "id": "fireworks-time",
        "option": "fireworks",
        "starts_at": "9999-12-31T23:59:59+00:00[UTC]",
    }
    return trip(
        ["alex"],
        ["pier"],
        [stays("fireworks", "pier")],
        [last, lasts("fireworks", "PT1S")],
        [lock("fireworks", "alex")],
    )


def test_a_trip_with_a_time_that_cannot_be_written_cannot_be_drawn() -> None:
    """The page is told that there is nothing to draw, never a time that is not the TRIP's."""
    file = at_the_end_of_time()
    assert shown(file, Report(Answer.INFEASIBLE)) is None
    start = file.start("fireworks")
    assert start is not None
    assert start.at is not None
    step = Step("fireworks", "pier", "pier", ("alex",), start.at, start.at + 1)
    assert shown(file, Report(Answer.FEASIBLE, itinerary=(step,))) is None
    # One second earlier, every time can be written.
    whole = Step("fireworks", "pier", "pier", ("alex",), start.at - 1, start.at)
    sent = sent_for(file, Report(Answer.FEASIBLE, itinerary=(whole,)))
    assert sent["steps"][0]["end"] == "9999-12-31T23:59:59"


def good() -> Trip:
    """A TRIP as a page is sent it, with two steps: an OPTION and a WAY."""
    file = walking()
    steps = (
        Step("visit", "museum", "museum", ("alex", "sam"), seconds(14), seconds(15)),
        Step(None, "museum", "hotel", ("alex",), seconds(15), seconds(15, 20), way="walk"),
    )
    sent = sent_for(file, Report(Answer.FEASIBLE, itinerary=steps))
    return sent


def _set(*path: str | int, to: object) -> Callable[[Trip], None]:
    """A change to a TRIP: the value at this path becomes another."""

    def change(sent: Trip) -> None:
        part: Any = sent
        for key in path[:-1]:
            part = part[key]
        part[path[-1]] = to

    return change


def _drop(*path: str | int) -> Callable[[Trip], None]:
    def change(sent: Trip) -> None:
        part: Any = sent
        for key in path[:-1]:
            part = part[key]
        del part[path[-1]]

    return change


BROKEN: dict[str, Callable[[Trip], None]] = {
    "no zone": _drop("zone"),
    "one thing more": _set("more", to=1),
    "a zone that is no text": _set("zone", to=5),
    "an itinerary that is no yes or no": _set("itinerary", to=1),
    "persons that are no list": _set("persons", to={}),
    "a person with no name": _drop("persons", 0, "name"),
    "a person with one thing more": _set("persons", 0, "more", to=1),
    "a person whose id is no text": _set("persons", 0, "id", to=1),
    "a person whose name is no text": _set("persons", 0, "name", to=None),
    "a person who is no record": _set("persons", 0, to="alex"),
    "two persons with one id": _set("persons", 1, "id", to="alex"),
    "places that are no list": _set("places", to="museum"),
    "a place with no id": _drop("places", 0, "id"),
    "two places with one id": _set("places", 1, "id", to="museum"),
    "steps that are no list": _set("steps", to=None),
    "a step that is no record": _set("steps", 0, to=[]),
    "a step with no start": _drop("steps", 0, "start"),
    "a step with one thing more": _set("steps", 0, "more", to=1),
    "an option that is no text": _set("steps", 0, "option", to=7),
    "an option and a way at once": _set("steps", 0, "way", to="walk"),
    "a name that is no text": _set("steps", 0, "name", to=["visit"]),
    "a step from no place of the trip": _set("steps", 0, "from", to="pier"),
    "a step to no place of the trip": _set("steps", 0, "to", to=None),
    "a step for nobody": _set("steps", 0, "persons", to=[]),
    "a step for somebody else": _set("steps", 0, "persons", to=["alex", "jo"]),
    "a step for one person twice": _set("steps", 0, "persons", to=["alex", "alex"]),
    "persons of a step that are no list": _set("steps", 0, "persons", to="alex"),
    "a person of a step who is no text": _set("steps", 1, "persons", to=[["alex"]]),
    "a lock for somebody who takes no part": _set("steps", 1, "locked", to=["sam"]),
    "locks that are no list": _set("steps", 0, "locked", to=True),
    "a start that is a number": _set("steps", 0, "start", to=1810000000),
    "a start with no seconds": _set("steps", 0, "start", to="2027-05-15T14:00"),
    "a start with an offset": _set("steps", 0, "start", to="2027-05-15T14:00:00-05:00"),
    "a start on no day": _set("steps", 0, "start", to="2027-02-30T14:00:00"),
    "a start at no time": _set("steps", 0, "start", to="2027-05-15T24:00:00"),
    "a start in the year nought": _set("steps", 0, "start", to="0000-05-15T14:00:00"),
    "an end with no start": _set("steps", 0, "start", to=None),
    "a step of an itinerary with no time": lambda sent: sent["steps"][1].update(
        start=None, end=None
    ),
    "a way and a person whom no lock names, with no itinerary": _set("itinerary", to=False),
    "an end that is no time": _set("steps", 0, "end", to="15:00"),
    "an end with a line after it": _set("steps", 0, "end", to="2027-05-15T15:00:00\n"),
}


def test_the_trips_that_break_are_good_before_they_are_broken() -> None:
    assert holds(good())
    assert holds(json.loads(json.dumps(good())))


@pytest.mark.parametrize("change", BROKEN.values(), ids=BROKEN.keys())
def test_what_a_page_cannot_draw_is_no_trip(change: Callable[[Trip], None]) -> None:
    """The view passes a TRIP on only where it holds all that the page reads, and no more."""
    sent = good()
    change(sent)
    assert not holds(sent)


@pytest.mark.parametrize("other", [None, [], "trip", 3, True, {}])
def test_what_is_no_record_is_no_trip(other: object) -> None:
    assert not holds(other)
