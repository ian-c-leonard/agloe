"""The strip that the page draws above the calendar: the whole TRIP, with a row for each PERSON.

``src/agloe/view/static/strip.js`` takes the calendar as ``calendar.js`` lays it out, and puts
its days one after another, so that time runs from left to right. It has no page in it, so Node
runs it here, through ``view_strip.mjs``.

The strip holds the marks of the calendar and no others. So nothing in it judges a TRIP.
"""

import json
import os
import random
import shutil
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest

from agloe.view.trip import holds
from tests.stories import EXAMPLES
from tests.test_view_calendar import (
    RECORDS,
    alone,
    drawn,
    framed,
    in_words,
    some_trip,
    with_its_report,
)

STORY = EXAMPLES / "flight-home"
DAYS = EXAMPLES / "several-days"
CHICAGO = "[America/Chicago]"
SAYS = "The whole TRIP, a row for each PERSON."
CUT = " It leaves out the hours that the calendar does not show."
CLICK = " Click a step to see it in the calendar."

type Trip = dict[str, Any]
type Calendar = dict[str, Any]
type Strip = dict[str, Any]


def strips(
    trips: list[Trip | None],
    reports: list[dict[str, Any] | None] | None = None,
    texts: list[str | None] | None = None,
) -> list[tuple[Calendar, Strip | None]]:
    """The calendar of each TRIP and the strip of that calendar, by the page's own code."""
    with_them = reports if reports is not None else [None] * len(trips)
    in_their_words = texts if texts is not None else [None] * len(trips)
    asked = [
        {"trip": sent, "report": found, "text": words}
        for sent, found, words in zip(trips, with_them, in_their_words, strict=True)
    ]
    node = shutil.which("node")
    if node is None:
        if os.environ.get("CI"):
            pytest.fail("the tests of the view need Node")
        pytest.skip("needs Node")
    done = subprocess.run(
        [node, str(Path(__file__).parent / "view_strip.mjs")],
        input=json.dumps(asked),
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    made: list[dict[str, Any]] = json.loads(done.stdout)
    return [(each["calendar"], each["strip"]) for each in made]


def strip(
    sent: Trip | None, found: dict[str, Any] | None = None, words: str | None = None
) -> Strip | None:
    return strips([sent], [found], [words])[0][1]


def a_strip(sent: Trip) -> Strip:
    band = strip(sent)
    assert band is not None
    return band


def places(band: Strip) -> list[tuple[Any, ...]]:
    """Where each mark is on the strip: its step, its day, its left and its width."""
    return [(mark["step"], mark["day"], mark["left"], mark["width"]) for mark in band["marks"]]


def test_a_trip_on_one_day_has_no_strip() -> None:
    """The calendar of one day is the whole TRIP already."""
    (laid, band) = strips([drawn(STORY / "works.json")])[0]
    assert len(laid["days"]) == 1
    assert band is None
    # Nor has a TRIP of which the view could make no calendar.
    assert strip(None) is None


def test_a_trip_with_no_step_on_its_days_has_no_strip() -> None:
    sent = framed(f"2027-05-14T18:00:00-05:00{CHICAGO}", f"2027-05-16T12:00:00-05:00{CHICAGO}")
    assert strip(sent) is not None
    empty = framed(
        f"2027-05-14T18:00:00-05:00{CHICAGO}", f"2027-05-16T12:00:00-05:00{CHICAGO}", visit=False
    )
    assert len(empty["days"]) == 3
    assert strip(empty) is None


def test_the_strip_holds_the_marks_of_the_calendar() -> None:
    """Each mark of the calendar is on the strip once, with all that the calendar says of it."""
    for name in ["works", "works-but-risky", "cannot-work", "depends-on-the-night"]:
        sent, found, words = in_words(DAYS / f"{name}.json")
        ((laid, band),) = strips([sent], [found], [words])
        assert band is not None, name
        on_the_calendar = [
            {**mark, "day": n} for n, day in enumerate(laid["days"]) for mark in day["marks"]
        ]
        assert len(band["marks"]) == len(on_the_calendar) > 0
        for mark, there in zip(band["marks"], on_the_calendar, strict=True):
            width = there.pop("height")
            there.pop("top")
            assert {key: mark[key] for key in there} == there
            assert mark["width"] == width
        assert band["persons"] == laid["persons"]
        assert [day["name"] for day in band["days"]] == [day["name"] for day in laid["days"]]


def test_the_strip_marks_what_the_calendar_marks() -> None:
    """A red edge and a yellow edge are on the strip where they are on the calendar."""
    sent, found = with_its_report(DAYS / "cannot-work.json")
    band = strip(sent, found)
    assert band is not None
    assert any(mark["clash"] for mark in band["marks"])
    sent, found, words = in_words(DAYS / "works-but-risky.json")
    band = strip(sent, found, words)
    assert band is not None
    assert any(mark["warns"] for mark in band["marks"])


def test_time_runs_on_from_one_day_to_the_next() -> None:
    """A stay from 10:00 pm to 2:00 am, and one from midnight: the calendar shows whole days."""
    band = a_strip(
        alone(
            (f"2027-05-15T22:00:00-05:00{CHICAGO}", 4 * 3600),
            (f"2027-05-16T00:00:00-05:00{CHICAGO}", 3600),
        )
    )
    # The strip starts 20 minutes before the first stay, and ends 20 minutes after the last.
    assert [(day["short"], day["left"], day["width"]) for day in band["days"]] == [
        ("Sat 15", 0, 140),
        ("Sun 16", 140, 140),
    ]
    assert band["length"] == 280
    # The first stay is in two parts, and the second starts where the first ends.
    assert places(band) == [(0, 0, 20, 120), (0, 1, 140, 120), (1, 1, 140, 60)]
    first, second, _ = band["marks"]
    assert (first["begins"], first["ends"]) == (True, False)
    assert (second["begins"], second["ends"]) == (False, True)
    assert band["cut"] is False
    assert band["says"] == SAYS + CLICK


def test_days_that_show_some_hours_only_stand_one_after_another() -> None:
    """Two visits at 2:00 pm, a day apart. The calendar shows each day from 1:00 pm to 4:00 pm."""
    sent = alone(
        (f"2027-05-15T14:00:00-05:00{CHICAGO}", 3600),
        (f"2027-05-16T14:00:00-05:00{CHICAGO}", 3600),
    )
    ((laid, band),) = strips([sent])
    assert laid["hours"] == {"from": 13 * 60, "to": 16 * 60}
    assert band is not None
    assert [(day["left"], day["width"]) for day in band["days"]] == [(0, 140), (140, 140)]
    assert places(band) == [(0, 0, 20, 60), (1, 1, 200, 60)]
    # The strip says that it leaves the nights out.
    assert band["cut"] is True
    assert band["says"] == SAYS + CUT + CLICK


def test_the_strip_shows_when_the_trip_starts_and_ends() -> None:
    """From Friday at 6:00 pm to Sunday at noon, with a visit on Saturday at 2:00 pm."""
    band = a_strip(
        framed(f"2027-05-14T18:00:00-05:00{CHICAGO}", f"2027-05-16T12:00:00-05:00{CHICAGO}")
    )
    # The calendar shows each day from 1:00 pm to 4:00 pm, and a time of the TRIP outside
    # those hours at their edge. So Friday and Sunday take the least room on the strip.
    assert [(day["short"], day["left"], day["width"]) for day in band["days"]] == [
        ("Fri 14", 0, 20),
        ("Sat 15", 20, 180),
        ("Sun 16", 200, 20),
    ]
    assert places(band) == [(0, 1, 80, 60)]
    assert [
        (bound["edge"], bound["day"], bound["left"], bound["record"]) for bound in band["bounds"]
    ] == [("starts", 0, 20, "trip-start"), ("ends", 2, 200, "trip-end")]
    assert band["bounds"][0]["says"] == "The TRIP starts at 6:00 pm"


def test_a_day_on_which_the_clocks_change_takes_the_room_of_its_hours() -> None:
    """In Chicago the clocks go back from 2:00 am to 1:00 am on 7 November 2027.

    A stay of 70 minutes from the first 1:05 am has 55 minutes before the change and 15 after.
    """
    band = a_strip(alone((f"2027-11-07T01:05:00-05:00{CHICAGO}", 70 * 60)))
    assert [(day["short"], day["left"], day["width"]) for day in band["days"]] == [
        ("Sun 7 (UTC-5)", 0, 75),
        ("Sun 7 (UTC-6)", 75, 35),
    ]
    # The second part starts where the first ends: the hour that the clocks show twice is
    # on the strip twice.
    assert places(band) == [(0, 0, 20, 55), (0, 1, 75, 15)]
    assert band["cut"] is True


def test_whatever_calendar_the_page_draws_has_a_strip_or_needs_none() -> None:
    """Every mark of the calendar is on the strip, inside its day, whatever the times are."""
    chosen = random.Random(11)
    trips = [some_trip(chosen) for _ in range(500)]
    for sent in trips:
        assert holds(sent), sent
    named = [chosen.sample([*RECORDS, "trip-end"], chosen.randrange(0, 4)) for _ in trips]
    reports: list[dict[str, Any] | None] = [
        {"answer": "INFEASIBLE", "conflict": conflict} if conflict else None for conflict in named
    ]
    made = strips(cast("list[Trip | None]", trips), reports)
    with_a_strip = 0
    for sent, (laid, band) in zip(trips, made, strict=True):
        with_room = [day for day in laid["days"] if day["open"]["bottom"] > day["open"]["top"]]
        on_the_calendar = [mark for day in laid["days"] for mark in day["marks"]]
        if len(with_room) < 2 or not on_the_calendar:
            assert band is None, sent
            continue
        assert band is not None, sent
        with_a_strip += 1
        # The days stand one after another, and together they are the strip.
        assert len(band["days"]) == len(laid["days"])
        at = 0
        for day in band["days"]:
            assert day["left"] == at
            assert day["width"] >= 0
            at += day["width"]
        assert band["length"] == at > 0
        # Each mark of the calendar is on the strip once, inside its day.
        assert len(band["marks"]) == len(on_the_calendar)
        before = -1
        for mark in band["marks"]:
            day = band["days"][mark["day"]]
            assert before <= mark["day"]
            before = mark["day"]
            assert mark["width"] >= 0
            assert day["left"] <= mark["left"], (sent, mark)
            end = day["left"] + day["width"]
            assert mark["left"] + mark["width"] <= end + 1e-6, (sent, mark)
            assert 0 <= mark["first"] <= mark["last"] < len(band["persons"])
        steps = sorted((mark["day"], mark["step"], mark["first"]) for mark in band["marks"])
        there = sorted(
            (n, mark["step"], mark["first"])
            for n, day in enumerate(laid["days"])
            for mark in day["marks"]
        )
        assert steps == there
        # A mark is as long on the strip as it is tall on the calendar.
        for mark, was in zip(band["marks"], on_the_calendar, strict=True):
            assert mark["width"] == was["height"], (sent, mark)
        # So is each time of the TRIP.
        bounds = [bound for day in laid["days"] for bound in day["bounds"]]
        assert len(band["bounds"]) == len(bounds)
        for bound in band["bounds"]:
            day = band["days"][bound["day"]]
            assert day["left"] <= bound["left"] <= day["left"] + day["width"]
    assert with_a_strip > 100
