"""The strip that the page draws above the calendar: all its days, with a row for each PERSON.

``src/agloe/view/static/strip.js`` takes the calendar as ``calendar.js`` lays it out, and puts
its days one after another in the pixels that the page has, so that time runs from left to
right. It has no page in it, so Node runs it here, through ``view_strip.mjs``.

The strip holds the marks of the calendar and no others. Marks that are too close together to
show apart at its width are one mark, which says so. So nothing in it judges a TRIP, and
nothing on it hides a step.
"""

import itertools
import json
import os
import random
import shutil
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest

from agloe.answers import Answer, Report
from agloe.file import File
from agloe.reference import Step
from agloe.view.trip import holds
from tests.stories import (
    EXAMPLES,
    lasts,
    lock,
    moves,
    seconds,
    starts_at,
    stays,
    trip,
    way_between,
)
from tests.test_view_calendar import (
    RECORDS,
    alone,
    drawn,
    framed,
    in_words,
    sent_for,
    some_trip,
    with_its_report,
)

STORY = EXAMPLES / "flight-home"
DAYS = EXAMPLES / "several-days"
CHICAGO = "[America/Chicago]"
SAYS = "All the days of the calendar on one strip, a row for each PERSON."
NOBODY = (
    "All the days of the calendar on one strip, a row for each PERSON and one for the steps"
    " with nobody of the TRIP in them."
)
CUT = " It leaves out the hours that the calendar does not show."
CLICK = " Click a step to see it in the calendar."
WIDE = 844  # pixels: the room of the strip in a window of the usual width
TICK = 5  # pixels: the width of the tick of a WAY that is too short for a line
LEAST = 3  # pixels: the least width of the block of an OPTION, and of the line of a WAY
STUB = 24  # pixels: the room of a day that shows no hours and holds a time of the TRIP
A_DAY_AT_LEAST = 6  # pixels: the least room of a day that holds something
ROW = 20  # pixels: the height of the row of one PERSON
LANE = 6  # pixels: the least height of a lane in which a mark can be drawn
A_DAY = 24 * 3600

type Trip = dict[str, Any]
type Calendar = dict[str, Any]
type Strip = dict[str, Any]


def strips(
    trips: list[Trip | None],
    reports: list[dict[str, Any] | None] | None = None,
    texts: list[str | None] | None = None,
    wide: list[float] | None = None,
) -> list[tuple[Calendar, Strip | None]]:
    """The calendar of each TRIP and the strip of that calendar, by the page's own code."""
    with_them = reports if reports is not None else [None] * len(trips)
    in_their_words = texts if texts is not None else [None] * len(trips)
    pixels = wide if wide is not None else [WIDE] * len(trips)
    asked = [
        {"trip": sent, "report": found, "text": words, "wide": room}
        for sent, found, words, room in zip(trips, with_them, in_their_words, pixels, strict=True)
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


def strip(sent: Trip | None, wide: float = WIDE) -> Strip | None:
    return strips([sent], wide=[wide])[0][1]


def a_strip(sent: Trip, wide: float = WIDE) -> Strip:
    """The strip of a TRIP that has one. With a pixel for each minute, its numbers are minutes."""
    band = strip(sent, wide)
    assert band is not None
    return band


def days(band: Strip) -> list[tuple[Any, ...]]:
    """Each day of the strip: its short name, where it starts and how wide it is."""
    return [(day["short"], day["x"], day["w"]) for day in band["days"]]


def places(band: Strip) -> list[tuple[Any, ...]]:
    """Where each mark is on the strip: the steps it stands for, its day, its start, its width."""
    return [
        (
            [each["step"] for each in mark["of"]],
            mark["of"][0]["day"],
            mark["x"],
            mark["w"],
        )
        for mark in band["marks"]
    ]


def gaps(band: Strip) -> list[bool]:
    """For each day of the strip, whether the strip leaves hours out before it."""
    return [day["gap"] for day in band["days"]]


def test_a_trip_on_one_day_has_no_strip() -> None:
    """The calendar of one day shows all of it already."""
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


def covered(laid: Calendar, band: Strip) -> None:
    """Each mark of the calendar is on the strip once in the row of each of its PERSONs.

    It is there with all that the calendar says of it: alone, or among the marks that one mark
    of the strip stands for.
    """
    there: dict[tuple[int, int, int], int] = {}
    for mark in band["marks"]:
        assert mark["of"], mark
        for each in mark["of"]:
            was = dict(laid["days"][each["day"]]["marks"][each["index"]])
            was.pop("top")
            was.pop("height")
            assert {key: each[key] for key in was} == was
            for row in range(mark["first"], mark["last"] + 1):
                assert each["first"] <= row <= each["last"], mark
                at = (each["day"], each["index"], row)
                there[at] = there.get(at, 0) + 1
    wanted = {
        (n, index, row)
        for n, day in enumerate(laid["days"])
        for index, mark in enumerate(day["marks"])
        for row in range(mark["first"], mark["last"] + 1)
    }
    assert set(there) == wanted
    assert set(there.values()) <= {1}


def test_the_strip_holds_the_marks_of_the_calendar() -> None:
    for name in ["works", "works-but-risky", "cannot-work", "depends-on-the-night"]:
        sent, found, words = in_words(DAYS / f"{name}.json")
        ((laid, band),) = strips([sent], [found], [words])
        assert band is not None, name
        assert band["marks"]
        covered(laid, band)
        assert band["persons"] == laid["persons"]
        assert [day["name"] for day in band["days"]] == [day["name"] for day in laid["days"]]


def test_the_strip_marks_what_the_calendar_marks() -> None:
    """A red edge and a yellow edge are on the strip where they are on the calendar."""
    sent, found = with_its_report(DAYS / "cannot-work.json")
    ((_, band),) = strips([sent], [found])
    assert band is not None
    assert any(each["clash"] for mark in band["marks"] for each in mark["of"])
    sent, found, words = in_words(DAYS / "works-but-risky.json")
    ((_, band),) = strips([sent], [found], [words])
    assert band is not None
    assert any(each["warns"] for mark in band["marks"] for each in mark["of"])


def test_time_runs_on_from_one_day_to_the_next() -> None:
    """A stay from 10:00 pm to 2:00 am, and one from midnight: the calendar shows whole days."""
    band = a_strip(
        alone(
            (f"2027-05-15T22:00:00-05:00{CHICAGO}", 4 * 3600),
            (f"2027-05-16T00:00:00-05:00{CHICAGO}", 3600),
        ),
        wide=280,
    )
    # The strip starts 20 minutes before the first stay, and ends 20 minutes after the last.
    assert days(band) == [("Sat 15", 0, 140), ("Sun 16", 140, 140)]
    assert band["wide"] == 280
    assert [day["per"] for day in band["days"]] == [1, 1]
    # The first stay is in two parts, and the second starts where the first ends.
    assert places(band) == [([0], 0, 20, 120), ([0], 1, 140, 120), ([1], 1, 140, 60)]
    first, second, _ = (mark["of"][0] for mark in band["marks"])
    assert (first["begins"], first["ends"]) == (True, False)
    assert (second["begins"], second["ends"]) == (False, True)
    # The two stays on Sunday are at one time, so each has a lane, as on the calendar.
    assert [(mark["lane"], mark["lanes"]) for mark in band["marks"]] == [(0, 1), (0, 2), (1, 2)]
    # No hour is left out between the two days, and the strip says nothing of the kind.
    assert gaps(band) == [False, False]
    assert band["cut"] is False
    assert band["says"] == SAYS + CLICK
    # In twice the pixels, everything is twice as far along and twice as wide.
    twice = a_strip(
        alone(
            (f"2027-05-15T22:00:00-05:00{CHICAGO}", 4 * 3600),
            (f"2027-05-16T00:00:00-05:00{CHICAGO}", 3600),
        ),
        wide=560,
    )
    assert places(twice) == [([0], 0, 40, 240), ([0], 1, 280, 240), ([1], 1, 280, 120)]


def test_days_that_show_some_hours_only_stand_one_after_another() -> None:
    """Two visits at 2:00 pm, a day apart. The calendar shows each day from 1:00 pm to 4:00 pm."""
    sent = alone(
        (f"2027-05-15T14:00:00-05:00{CHICAGO}", 3600),
        (f"2027-05-16T14:00:00-05:00{CHICAGO}", 3600),
    )
    ((laid, band),) = strips([sent], wide=[280])
    assert laid["hours"] == {"from": 13 * 60, "to": 16 * 60}
    assert band is not None
    assert days(band) == [("Sat 15", 0, 140), ("Sun 16", 140, 140)]
    assert places(band) == [([0], 0, 20, 60), ([1], 1, 200, 60)]
    # The strip leaves the night out, and says so.
    assert gaps(band) == [False, True]
    assert band["cut"] is True
    assert band["says"] == SAYS + CUT + CLICK


def test_the_strip_shows_when_the_trip_starts_and_ends() -> None:
    """From Friday at 6:00 pm to Sunday at noon, with a visit on Saturday at 2:00 pm."""
    band = a_strip(
        framed(f"2027-05-14T18:00:00-05:00{CHICAGO}", f"2027-05-16T12:00:00-05:00{CHICAGO}"),
        wide=220,
    )
    # The calendar shows each day from 1:00 pm to 4:00 pm, and a time of the TRIP outside
    # those hours at their edge. So Friday and Sunday take the least room on the strip.
    assert days(band) == [("Fri 14", 0, 20), ("Sat 15", 20, 180), ("Sun 16", 200, 20)]
    assert places(band) == [([0], 1, 80, 60)]
    # The line of each is on its own day: the start two pixels before the end of Friday.
    assert [
        (bound["edge"], bound["day"], bound["x"], bound["record"]) for bound in band["bounds"]
    ] == [("starts", 0, 18, "trip-start"), ("ends", 2, 200, "trip-end")]
    assert band["bounds"][0]["says"] == "The TRIP starts at 6:00 pm"
    assert gaps(band) == [False, True, True]


def test_a_day_that_shows_no_hours_has_a_place_where_it_holds_a_time_of_the_trip() -> None:
    """In Chicago the clocks go forward at 2:00 am on Sunday 14 March 2027.

    A TRIP from Friday evening to Sunday at 1:00 am, with lunch on Saturday. The calendar shows
    each day from noon to 3:00 pm, and Sunday's column before the change has none of those
    hours. The strip still gives it a place, with its name, for the end of the TRIP.
    """

    def with_lunch(starts: str) -> Trip:
        file = trip(
            ["alex"],
            ["cafe"],
            [stays("lunch", "cafe")],
            [
                {
                    "id": "lunch-time",
                    "option": "lunch",
                    "starts_at": f"2027-03-13T13:00:00-06:00{CHICAGO}",
                },
                lasts("lunch", "PT1H"),
            ],
            [
                lock("lunch", "alex"),
                {"id": "trip-start", "trip_starts_at": f"{starts}-06:00{CHICAGO}"},
                {"id": "trip-end", "trip_ends_at": f"2027-03-14T01:00:00-06:00{CHICAGO}"},
            ],
        )
        return sent_for(file, Report(Answer.UNDETERMINED))

    ((laid, band),) = strips([with_lunch("2027-03-12T18:00:00")], wide=[160 + STUB])
    assert laid["hours"] == {"from": 12 * 60, "to": 15 * 60}
    assert [day["name"] for day in laid["days"]] == [
        "Friday 12 March 2027",
        "Saturday 13 March 2027",
        "Sunday 14 March 2027 (UTC-6)",
    ]
    assert band is not None
    # Saturday is the last day with hours to show, so it ends 20 minutes after lunch.
    assert days(band) == [
        ("Fri 12", 0, 20),
        ("Sat 13", 20, 140),
        ("Sun 14 (UTC-6)", 160, STUB),
    ]
    assert places(band) == [([0], 1, 80, 60)]
    # The end of the TRIP is in the middle of Sunday's place, and not under Saturday.
    assert [(bound["edge"], bound["day"], bound["x"]) for bound in band["bounds"]] == [
        ("starts", 0, 18),
        ("ends", 2, 160 + STUB / 2),
    ]
    # Hours are left out before Saturday and before Sunday.
    assert gaps(band) == [False, True, True]
    # A TRIP that starts on Saturday has two days on its strip, and so it has a strip.
    band = a_strip(with_lunch("2027-03-13T12:30:00"), wide=140 + STUB)
    assert [day["short"] for day in band["days"]] == ["Sat 13", "Sun 14 (UTC-6)"]
    assert [bound["day"] for bound in band["bounds"]] == [0, 1]


def test_a_day_on_which_the_clocks_change_takes_the_room_of_its_hours() -> None:
    """In Chicago the clocks go back from 2:00 am to 1:00 am on 7 November 2027.

    A stay of 70 minutes from the first 1:05 am has 55 minutes before the change and 15 after.
    """
    band = a_strip(alone((f"2027-11-07T01:05:00-05:00{CHICAGO}", 70 * 60)), wide=110)
    assert days(band) == [("Sun 7 (UTC-5)", 0, 75), ("Sun 7 (UTC-6)", 75, 35)]
    # The second part starts where the first ends: the hour that the clocks show twice is
    # on the strip twice.
    assert places(band) == [([0], 0, 20, 55), ([0], 1, 75, 15)]
    # The calendar shows two hours of each column only. Still no time is left out between
    # these two: the first is shown to its last moment, and the second from its first.
    assert gaps(band) == [False, False]
    assert band["cut"] is False
    assert band["says"] == SAYS + CLICK
    # So it is where the clocks go forward, from 2:00 am to 3:00 am on 14 March 2027.
    band = a_strip(alone((f"2027-03-14T01:55:00-06:00{CHICAGO}", 70 * 60)), wide=110)
    assert days(band) == [("Sun 14 (UTC-6)", 0, 25), ("Sun 14 (UTC-5)", 25, 85)]
    assert places(band) == [([0], 0, 20, 5), ([0], 1, 25, 65)]
    assert gaps(band) == [False, False]


def test_each_mark_of_the_strip_says_which_mark_of_the_calendar_it_is() -> None:
    """Alex and Jo are at a concert, and Sam's row is between theirs."""
    file = trip(
        ["alex", "sam", "jo"],
        ["hall"],
        [stays("concert", "hall")],
        [starts_at("concert", 20), lasts("concert", "PT2H")],
        [
            lock("concert", "alex", "jo"),
            {"id": "trip-end", "trip_ends_at": f"2027-05-16T12:00:00-05:00{CHICAGO}"},
        ],
    )
    ((laid, band),) = strips([sent_for(file, Report(Answer.UNDETERMINED))])
    assert band is not None
    on_the_day = laid["days"][0]["marks"]
    assert [(mark["first"], mark["last"]) for mark in on_the_day] == [(0, 0), (2, 2)]
    # The concert is one step and two marks. A click on Jo's goes to Jo's on the calendar.
    assert [
        (mark["of"][0]["step"], mark["of"][0]["day"], mark["of"][0]["index"], mark["first"])
        for mark in band["marks"]
    ] == [(0, 0, 0, 0), (0, 0, 1, 2)]


def two_doors() -> File:
    """Alex and Sam, a hotel, a foyer and a museum, with a door and stairs between them."""
    return trip(
        ["alex", "sam"],
        ["hotel", "foyer", "museum"],
        [stays("visit", "museum")],
        [starts_at("visit", 12), lasts("visit", "PT1H")],
        [],
        ways=[way_between("door", "hotel", "foyer"), way_between("stairs", "foyer", "museum")],
    )


def test_a_way_too_short_to_draw_is_a_tick_across_its_time() -> None:
    """Alex and Sam go through a door, which takes a minute. The next day Alex visits a museum.

    With a pixel for each minute, the door is one pixel long. Its tick is five pixels wide, with
    the door's minute in the middle, in the row of each PERSON who goes through it.
    """
    plan = (
        Step(None, "hotel", "foyer", ("alex", "sam"), seconds(12), seconds(12, 1), way="door"),
        Step("visit", "museum", "museum", ("alex",), seconds(12) + A_DAY, seconds(13) + A_DAY),
    )
    # The calendar shows each day from 11:00 am to 2:00 pm. The strip starts at 11:40 am.
    band = a_strip(sent_for(two_doors(), Report(Answer.FEASIBLE, itinerary=plan)), wide=280)
    assert days(band) == [("Sat 15", 0, 140), ("Sun 16", 140, 140)]
    assert [
        (mark["of"][0]["name"], mark["small"], mark["first"], mark["last"], mark["x"], mark["w"])
        for mark in band["marks"]
    ] == [
        ("visit", False, 0, 0, 200, 60),
        ("door", True, 0, 0, 18, TICK),
        ("door", True, 1, 1, 18, TICK),
    ]
    # A WAY that is three pixels long or more is a line from its start to its end.
    band = a_strip(sent_for(two_doors(), Report(Answer.FEASIBLE, itinerary=plan)), wide=840)
    door = band["marks"][0]
    assert (door["small"], door["first"], door["last"], door["x"], door["w"]) == (
        False,
        0,
        1,
        60,
        3,
    )


def test_marks_too_close_together_to_show_apart_are_one_mark() -> None:
    """Alex goes through a door and up the stairs, a minute each. Sam goes through the door only.

    With a pixel for each minute, the two ticks in Alex's row would lie on each other. So they
    are one mark, which stands for both steps. In Sam's row the door has its own tick.
    """
    plan = (
        Step(None, "hotel", "foyer", ("alex", "sam"), seconds(12), seconds(12, 1), way="door"),
        Step(None, "foyer", "museum", ("alex",), seconds(12, 1), seconds(12, 2), way="stairs"),
        Step(None, "museum", "foyer", ("alex",), seconds(18), seconds(18, 1), way="stairs"),
        Step("visit", "museum", "museum", ("alex",), seconds(12) + A_DAY, seconds(13) + A_DAY),
    )
    sent = sent_for(two_doors(), Report(Answer.FEASIBLE, itinerary=plan))
    ((laid, band),) = strips([sent], wide=[580])
    assert band is not None
    assert [day["per"] for day in band["days"]] == [1, 1]
    assert [
        ([each["name"] for each in mark["of"]], mark["first"], mark["last"], mark["x"], mark["w"])
        for mark in band["marks"]
    ] == [
        (["visit"], 0, 0, 500, 60),
        # The door from 12:00 and the stairs from 12:01, in Alex's row.
        (["door", "stairs"], 0, 0, 18, 6),
        # The stairs at 6:00 pm are far from both.
        (["stairs"], 0, 0, 378, TICK),
        (["door"], 1, 1, 18, TICK),
    ]
    covered(laid, band)
    # With six pixels for each minute, the two ticks are apart, and each is a mark.
    ((laid, band),) = strips([sent], wide=[6 * 580])
    assert band is not None
    assert [[each["name"] for each in mark["of"]] for mark in band["marks"]] == [
        ["door"],
        ["stairs"],
        ["stairs"],
        ["visit"],
    ]
    covered(laid, band)


def test_a_mark_at_the_very_end_of_the_strip_stays_on_it() -> None:
    """A visit at noon, and a look of one minute that ends at midnight the day after."""
    sent = alone(
        (f"2027-05-15T12:00:00-05:00{CHICAGO}", 3600),
        (f"2027-05-16T23:59:00-05:00{CHICAGO}", 60),
    )
    band = a_strip(sent, wide=300)
    last = band["marks"][-1]
    day = band["days"][-1]
    # The look is too short to draw, so its block is three pixels wide. It ends where the
    # strip ends, and not after it.
    assert (last["small"], last["w"]) == (True, LEAST)
    assert last["x"] + last["w"] == pytest.approx(day["x"] + day["w"])
    assert day["x"] + day["w"] == pytest.approx(300)
    assert band["wide"] == pytest.approx(300)


def test_a_mark_that_small_marks_would_cover_joins_them() -> None:
    """At a hotel just before midnight: show a card, check in, take the key. Brunch is at noon.

    Showing the card and taking the key take half a minute each, and checking in takes three
    minutes. With a pixel for each minute, the two small marks would lie on each other and
    cover the check-in between them. So the three are one mark, and the check-in can be reached.
    """
    sent = alone(
        (f"2027-05-15T23:56:00-05:00{CHICAGO}", 30),
        (f"2027-05-15T23:56:30-05:00{CHICAGO}", 180),
        (f"2027-05-15T23:59:30-05:00{CHICAGO}", 30),
        (f"2027-05-16T12:00:00-05:00{CHICAGO}", 7200),
    )
    ((laid, band),) = strips([sent], wide=[224])
    assert band is not None
    assert days(band) == [("Sat 15", 0, 24), ("Sun 16", 24, 200)]
    # The names in a mark for several are in the order of the plan.
    assert [([each["step"] for each in mark["of"]], mark["small"]) for mark in band["marks"]] == [
        ([3], False),
        ([0, 1, 2], True),
    ]
    covered(laid, band)
    # With ten pixels for each minute, the check-in has room of its own.
    ((laid, band),) = strips([sent], wide=[2240])
    assert band is not None
    assert [[each["step"] for each in mark["of"]] for mark in band["marks"]] == [[0], [1], [2], [3]]


def test_a_mark_in_a_lane_too_thin_to_draw_is_small() -> None:
    """Eight stops of half a minute each, one after another, and one more the day after.

    The calendar puts the eight side by side, in eight lanes: none of them is tall enough to
    read there. On the strip a lane would be under three pixels high. So each of the eight is
    small: it takes the whole height of the row, from its start to its end, and none lies on
    another.
    """
    stops = [
        (f"2027-05-15T23:5{5 + n // 2}:{30 * (n % 2):02d}-05:00{CHICAGO}", 30) for n in range(8)
    ]
    sent = alone(*stops, (f"2027-05-16T00:05:00-05:00{CHICAGO}", 30))
    ((laid, band),) = strips([sent], wide=[505])
    assert band is not None
    assert {mark["lanes"] for mark in laid["days"][0]["marks"]} == {8}
    assert [day["per"] for day in band["days"]] == [10, 10]
    assert [
        ([each["step"] for each in mark["of"]], mark["small"], mark["x"], mark["w"], mark["lanes"])
        for mark in band["marks"]
    ] == [
        ([8], False, 300, 5, 1),
        *[([n], True, 200 + 5 * n, 5, 1) for n in range(8)],
    ]
    covered(laid, band)
    assert band["row"] == ROW


def test_a_day_that_holds_something_has_room_for_it() -> None:
    """A check-in of one minute on Saturday at 11:59 pm, and a TRIP that ends on Friday at 12:05 am.

    In 224 pixels, Saturday and Friday would each be less than a pixel wide. Each is six
    pixels wide, so the check-in is on Saturday and the end of the TRIP is on Friday.
    """
    file = trip(
        ["alex"],
        ["hotel"],
        [stays("check-in", "hotel"), stays("night", "hotel")],
        [
            {
                "id": "check-in-time",
                "option": "check-in",
                "starts_at": f"2027-05-15T23:59:00-05:00{CHICAGO}",
            },
            lasts("check-in", "PT1M"),
            {
                "id": "night-time",
                "option": "night",
                "starts_at": f"2027-05-16T00:00:00-05:00{CHICAGO}",
            },
            lasts("night", "PT8H"),
        ],
        [
            lock("check-in", "alex"),
            lock("night", "alex"),
            {"id": "trip-end", "trip_ends_at": f"2027-05-21T00:05:00-05:00{CHICAGO}"},
        ],
    )
    ((laid, band),) = strips([sent_for(file, Report(Answer.UNDETERMINED))], wide=[224])
    assert band is not None
    assert laid["hours"] == {"from": 0, "to": 24 * 60}
    saturday, sunday, friday = band["days"][0], band["days"][1], band["days"][-1]
    assert (saturday["short"], saturday["x"], saturday["w"]) == ("Sat 15", 0, A_DAY_AT_LEAST)
    assert (friday["short"], friday["w"]) == ("Fri 21", A_DAY_AT_LEAST)
    assert band["wide"] == pytest.approx(224)
    check_in, night = band["marks"][1], band["marks"][0]
    assert [each["name"] for each in check_in["of"]] == ["check-in"]
    # The check-in is three pixels wide, and ends where Saturday ends.
    assert (check_in["x"], check_in["w"]) == (pytest.approx(3), LEAST)
    assert night["x"] == pytest.approx(sunday["x"]) == pytest.approx(6)
    # The end of the TRIP is on Friday, with room for its line.
    (end,) = band["bounds"]
    assert friday["x"] <= end["x"] <= friday["x"] + friday["w"] - 2


def clear(mark: dict[str, Any], small: list[dict[str, Any]]) -> float:
    """The widest stretch of a mark that none of these small marks covers."""
    at, widest = mark["x"], 0.0
    for other in sorted(small, key=lambda each: each["x"]):
        if other["x"] + other["w"] <= mark["x"] or other["x"] >= mark["x"] + mark["w"]:
            continue
        widest = max(widest, other["x"] - at)
        at = max(at, other["x"] + other["w"])
    return max(widest, mark["x"] + mark["w"] - at)


def test_whatever_calendar_the_page_draws_has_a_strip_or_needs_none() -> None:
    """Every mark of the calendar is on the strip, inside its day, whatever the times are."""
    chosen = random.Random(11)
    trips = [some_trip(chosen) for _ in range(600)]
    for sent in trips:
        assert holds(sent), sent
    named = [chosen.sample([*RECORDS, "trip-end"], chosen.randrange(0, 4)) for _ in trips]
    reports: list[dict[str, Any] | None] = [
        {"answer": "INFEASIBLE", "conflict": conflict} if conflict else None for conflict in named
    ]
    pixels = [chosen.choice([120, 200, 300, 844, 4000]) for _ in trips]
    made = strips(cast("list[Trip | None]", trips), reports, wide=cast("list[float]", pixels))
    with_a_strip = merged = 0
    for sent, wide, (laid, band) in zip(trips, pixels, made, strict=True):
        with_room = [day for day in laid["days"] if day["open"]["bottom"] > day["open"]["top"]]
        shown = [
            day
            for day in laid["days"]
            if day["open"]["bottom"] > day["open"]["top"] or day["bounds"]
        ]
        on_the_calendar = [mark for day in laid["days"] for mark in day["marks"]]
        if len(shown) < 2 or not on_the_calendar:
            assert band is None, sent
            continue
        assert band is not None, sent
        with_a_strip += 1
        # The days stand one after another, and together they are the strip. These TRIPs
        # have whole days, so each day that is shown has hours to show.
        assert len(shown) == len(with_room)
        assert len(band["days"]) == len(laid["days"])
        at = 0.0
        for day, on_it in zip(band["days"], laid["days"], strict=True):
            assert day["x"] == pytest.approx(at)
            assert day["w"] >= 0
            # A day that holds something has room for it.
            if on_it["marks"] or on_it["bounds"]:
                assert day["w"] >= A_DAY_AT_LEAST - 1e-6, (sent, day)
            at += day["w"]
        assert band["wide"] == pytest.approx(at)
        assert band["wide"] == pytest.approx(wide)
        # The strip leaves hours out between all its days, or between none.
        whole = laid["hours"] == {"from": 0, "to": 24 * 60}
        assert gaps(band) == [False] + [not whole] * (len(band["days"]) - 1)
        assert band["cut"] is not whole
        # Each mark of the calendar is on the strip, in each row of its PERSONs.
        covered(laid, band)
        small: dict[int, list[tuple[float, float]]] = {}
        for mark in band["marks"]:
            on = {each["day"] for each in mark["of"]}
            assert len(on) == 1, (sent, mark)
            day = band["days"][on.pop()]
            assert 0 <= mark["first"] <= mark["last"] < len(band["persons"])
            # No mark is outside its day, however short it is.
            assert mark["w"] >= 0
            assert day["x"] - 1e-6 <= mark["x"], (sent, mark)
            assert mark["x"] + mark["w"] <= day["x"] + day["w"] + 1e-6, (sent, mark)
            if not mark["small"]:
                # A mark that can be drawn is as long as its time, and stands for itself.
                (one,) = mark["of"]
                was = laid["days"][one["day"]]["marks"][one["index"]]
                assert mark["w"] == pytest.approx(was["height"] * day["per"])
                assert mark["w"] >= LEAST - 1e-6
                assert (mark["first"], mark["last"]) == (one["first"], one["last"])
                # Its lane is high enough to draw it in.
                assert ROW / mark["lanes"] >= LANE
                continue
            assert mark["first"] == mark["last"]
            assert (mark["lane"], mark["lanes"]) == (0, 1)
            merged += len(mark["of"]) > 1
            small.setdefault(mark["first"], []).append((mark["x"], mark["x"] + mark["w"]))
        # In one row, no two marks that are too short to draw lie on each other.
        for spans in small.values():
            spans.sort()
            for (_, end), (start, _) in itertools.pairwise(spans):
                assert end <= start + 1e-6, (sent, spans)
        # A mark that can be drawn has three pixels that no small mark covers, in the row
        # of one of its PERSONs at least.
        for mark in band["marks"]:
            if mark["small"]:
                continue
            rows = range(mark["first"], mark["last"] + 1)
            in_the_way = [
                [each for each in band["marks"] if each["small"] and each["first"] == row]
                for row in rows
            ]
            assert any(clear(mark, others) >= LEAST - 1e-6 for others in in_the_way), (sent, mark)
        # Each time of the TRIP is inside its day too.
        bounds = [bound for day in laid["days"] for bound in day["bounds"]]
        assert len(band["bounds"]) == len(bounds)
        for bound in band["bounds"]:
            day = band["days"][bound["day"]]
            assert day["x"] - 1e-6 <= bound["x"] <= day["x"] + day["w"] - 2 + 1e-6
    assert with_a_strip > 100
    assert merged > 10


def test_the_strip_has_a_row_for_the_steps_with_nobody_in_them() -> None:
    """Alex visits the hall on Saturday and on Sunday. A van runs on each day with nobody of
    the TRIP in it. The strip has a row after Alex's, and each van is in that row."""
    file = trip(
        ["alex"],
        ["hall", "port"],
        [
            stays("visit", "hall"),
            stays("again", "hall"),
            moves("van", "hall", "port"),
            moves("other-van", "hall", "port"),
        ],
        [starts_at("visit", 10)],
        [],
    )
    day = 86400
    plan = (
        Step("visit", "hall", "hall", ("alex",), seconds(10), seconds(11)),
        Step("van", "hall", "port", (), seconds(14), seconds(15, 30)),
        Step("again", "hall", "hall", ("alex",), seconds(10) + day, seconds(11) + day),
        Step("other-van", "hall", "port", (), seconds(14) + day, seconds(15, 30) + day),
    )
    sent = sent_for(file, Report(Answer.FEASIBLE, itinerary=plan))
    band = a_strip(sent)
    assert band["nobody"] is True
    assert band["persons"] == [{"id": "alex", "name": "alex"}]
    assert band["says"] == NOBODY + CUT + CLICK
    rows = sorted(
        (mark["of"][0]["day"], mark["of"][0]["name"], mark["first"], mark["last"], mark["small"])
        for mark in band["marks"]
    )
    assert rows == [
        (0, "van", 1, 1, False),
        (0, "visit", 0, 0, False),
        (1, "again", 0, 0, False),
        (1, "other-van", 1, 1, False),
    ]
    assert all(
        each["nobody"] is (each["name"] != "visit" and each["name"] != "again")
        for mark in band["marks"]
        for each in mark["of"]
    )
    # On a strip too narrow to draw a van, it is a small mark in the row of the vans, and it
    # joins nothing in Alex's row.
    narrow = a_strip(sent, wide=16)
    small = [
        ([each["name"] for each in mark["of"]], mark["first"], mark["last"])
        for mark in narrow["marks"]
        if mark["small"]
    ]
    assert any(row == 1 for _, row, _ in small)
    # Every step is on the strip once, wide or narrow, and each in its own row: a van in
    # the row after Alex's, and a visit in Alex's.
    for band_of in (band, narrow):
        on_it = [
            (each["name"], mark["first"], mark["last"])
            for mark in band_of["marks"]
            for each in mark["of"]
        ]
        assert sorted(on_it) == [
            ("again", 0, 0),
            ("other-van", 1, 1),
            ("van", 1, 1),
            ("visit", 0, 0),
        ]
    # A plan with somebody in every step has no such row, and the strip says so.
    everybody = sent_for(file, Report(Answer.FEASIBLE, itinerary=(plan[0], plan[2])))
    plain = a_strip(everybody)
    assert (plain["nobody"], plain["says"]) == (False, SAYS + CUT + CLICK)
