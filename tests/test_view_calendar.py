"""The calendar that the page draws of a TRIP: a column for each day, and in it one for each PERSON.

The view sends the TRIP with each report. ``src/agloe/view/static/calendar.js`` lays it out:
which day a step is on, how far down the day it starts, how tall it is, and whose columns it
spans. It has no page in it, so Node runs it here, through ``view_calendar.mjs``.

Nothing in it judges a TRIP. For a FEASIBLE TRIP the calendar holds the ITINERARY of the report,
in the report's own words. For any other TRIP it holds only the OPTIONs that a LOCK names.
"""

import json
import os
import random
import re
import shutil
import subprocess
from datetime import date, datetime, timedelta
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
    lock,
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
# In the report in words: the line that names a day, and a line that shows one step of the plan.
DAY = re.compile(r"^(\w+ \d+ \w+ \d+) \(times in (.+)\)$")
LINE = re.compile(r"^  \d{1,2}:\d\d(:\d\d)? [ap]m.* to .+: .+, .+$")
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]
CHICAGO = " Times are on the clocks of America/Chicago."
ONLY_LOCKS = (
    "The report shows no ITINERARY. The calendar holds only the OPTIONs that a LOCK names, at"
    " the times the FILE states."
)

type Trip = dict[str, Any]
type Calendar = dict[str, Any]


def beside(path: Path, ending: str) -> Path:
    return path.with_name(path.stem + ending)


def sent_for(file: File, report: Report) -> Trip:
    """What a page is sent of the TRIP in a FILE, with this report on it."""
    sent = shown(file, report)
    assert sent is not None
    return cast("Trip", sent)


def drawn(path: Path) -> Trip:
    file = read(path)
    return sent_for(file, compiler.check(file))


def calendars(trips: list[Trip | None]) -> list[Calendar]:
    """The calendar of each TRIP, by the page's own code."""
    node = shutil.which("node")
    if node is None:
        if os.environ.get("CI"):
            pytest.fail("the tests of the view need Node")
        pytest.skip("needs Node")
    done = subprocess.run(
        [node, str(Path(__file__).parent / "view_calendar.mjs")],
        input=json.dumps(trips),
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    laid: list[Calendar] = json.loads(done.stdout)
    return laid


def calendar(sent: Trip | None) -> Calendar:
    return calendars([sent])[0]


def marks(laid: Calendar, day: int = 0) -> list[tuple[Any, ...]]:
    """The marks of one day: step, state, first and last column, top, height, begins, ends."""
    return [
        tuple(
            mark[part]
            for part in ("step", "state", "first", "last", "top", "height", "begins", "ends")
        )
        for mark in laid["days"][day]["marks"]
    ]


def test_the_calendar_says_what_the_report_says() -> None:
    """For every FEASIBLE example: the same days and the same steps, in the report's own words."""
    feasible = [
        path
        for path in FILES
        if json.loads(beside(path, ".expected.json").read_text())["answer"] == "FEASIBLE"
    ]
    assert len(feasible) > 10
    laid = calendars([drawn(path) for path in feasible])
    for path, calendar_of in zip(feasible, laid, strict=True):
        name = f"{path.parent.name}/{path.stem}"
        in_report: list[tuple[str, str]] = []
        day = ""
        for line in beside(path, ".expected.txt").read_text().split("\n"):
            header = DAY.match(line)
            if header:
                day = header[1]
                assert calendar_of["zone"] == header[2], name
            elif LINE.match(line):
                in_report.append((day, line))
        in_calendar: list[tuple[str, str]] = []
        for each in calendar_of["days"]:
            seen: set[int] = set()
            for mark in each["marks"]:
                # A step is drawn once for each run of PERSONs, and once more on each later day.
                if mark["begins"] and mark["step"] not in seen:
                    seen.add(mark["step"])
                    words = f"  {mark['when']}: {mark['name']}, {mark['who']}"
                    in_calendar.append((each["name"], words))
        assert in_calendar == in_report, name
        assert calendar_of["untimed"] == [], name
        if in_report:
            assert calendar_of["says"] == f"The ITINERARY of the report.{CHICAGO}", name


def test_the_calendar_of_the_flight_home() -> None:
    """Alex and Sam visit the museum, take the Blue Line and fly home, all on one Saturday."""
    laid = calendar(drawn(STORY / "works.json"))
    assert laid["persons"] == [{"id": "alex", "name": "Alex"}, {"id": "sam", "name": "Sam"}]
    # The day shows whole hours, with room above the first step and below the last.
    assert laid["hours"] == {"from": 13 * 60, "to": 20 * 60}
    assert [day["name"] for day in laid["days"]] == ["Saturday 15 May 2027"]
    assert marks(laid) == [
        # Both columns, an hour down the day, an hour tall. A LOCK names the visit.
        (0, "locked", 0, 1, 60, 60, True, True),
        # The Blue Line is in the plan, and no LOCK names it.
        (1, "planned", 0, 1, 120, 60, True, True),
        (2, "locked", 0, 1, 240, 150, True, True),
    ]
    visit, train, flight = laid["days"][0]["marks"]
    assert (visit["kind"], visit["name"], visit["where"]) == (
        "option",
        "Museum visit",
        "the Art Institute",
    )
    assert (visit["when"], visit["who"]) == ("2:00 pm to 3:00 pm", "Alex and Sam")
    assert train["where"] == "the Art Institute to O'Hare"
    assert flight["where"] == "O'Hare to home"


def test_a_trip_with_no_itinerary_has_a_calendar_of_what_is_locked() -> None:
    """And the calendar says so, in words."""
    laid = calendar(drawn(STORY / "cannot-work.json"))
    assert laid["says"] == ONLY_LOCKS + CHICAGO
    assert laid["hours"] == {"from": 14 * 60, "to": 20 * 60}
    assert marks(laid) == [
        (0, "locked", 0, 1, 30, 60, True, True),
        (1, "locked", 0, 1, 180, 150, True, True),
    ]
    assert [mark["name"] for mark in laid["days"][0]["marks"]] == ["Museum visit", "Flight home"]


def group() -> File:
    """Alex, Sam and Jo, a museum and a hotel with a walk between, and a LOCK that names Sam."""
    return trip(
        ["alex", "sam", "jo"],
        ["museum", "hotel"],
        [stays("visit", "museum"), stays("lunch", "hotel")],
        [starts_at("visit", 14), lasts("visit", "PT1H")],
        [lock("visit", "sam")],
        ways=[way_between("walk", "museum", "hotel")],
    )


def test_a_step_spans_the_columns_of_the_persons_who_take_part() -> None:
    plan = (
        # Alex and Jo have Sam's column between theirs.
        Step("lunch", "hotel", "hotel", ("alex", "jo"), seconds(12), seconds(13)),
        # Everybody takes part, and the LOCK names Sam only.
        Step("visit", "museum", "museum", ("alex", "sam", "jo"), seconds(14), seconds(15)),
        Step(None, "museum", "hotel", ("sam", "jo"), seconds(15), seconds(15, 20), way="walk"),
        Step(None, "museum", "hotel", ("alex",), seconds(16), seconds(16, 19), way="walk"),
    )
    laid = calendar(sent_for(group(), Report(Answer.FEASIBLE, itinerary=plan)))
    assert laid["hours"] == {"from": 11 * 60, "to": 17 * 60}
    assert marks(laid) == [
        (0, "planned", 0, 0, 60, 60, True, True),
        (0, "planned", 2, 2, 60, 60, True, True),
        (1, "planned", 0, 0, 180, 60, True, True),
        (1, "locked", 1, 1, 180, 60, True, True),
        (1, "planned", 2, 2, 180, 60, True, True),
        (2, "way", 1, 2, 240, 20, True, True),
        (3, "way", 0, 0, 300, 19, True, True),
    ]
    by_step = {mark["step"]: mark for mark in laid["days"][0]["marks"]}
    # In the FILEs of the stories, each PERSON's name is their id.
    assert by_step[0]["who"] == "alex and jo"
    assert by_step[1]["who"] == "alex, sam and jo"
    assert (by_step[2]["kind"], by_step[2]["name"], by_step[2]["where"]) == (
        "way",
        "walk",
        "museum to hotel",
    )
    # A WAY has its name beside it where it takes 20 minutes or more.
    assert [by_step[step]["named"] for step in (0, 1, 2, 3)] == [True, True, True, False]


def test_a_way_that_the_file_does_not_list_is_named_as_the_report_names_it() -> None:
    other = Step(None, "museum", "hotel", ("alex",), seconds(15), seconds(15, 30))
    laid = calendar(sent_for(group(), Report(Answer.FEASIBLE, itinerary=(other,))))
    (mark,) = laid["days"][0]["marks"]
    assert (mark["kind"], mark["name"], mark["state"]) == ("way", "another WAY", "way")


def test_a_step_that_runs_past_midnight_is_on_both_days() -> None:
    """A night at the hotel, in the example of several days."""
    laid = calendar(drawn(EXAMPLES / "several-days" / "works.json"))
    assert [day["name"] for day in laid["days"]] == ["Friday 14 May 2027", "Saturday 15 May 2027"]
    # Breakfast at 8:00 am is the earliest step of a day. The night runs to midnight on its day.
    assert laid["hours"] == {"from": 7 * 60, "to": 24 * 60}
    friday = {mark["name"]: mark for mark in laid["days"][0]["marks"]}
    saturday = {mark["name"]: mark for mark in laid["days"][1]["marks"]}
    night = "Night at the hotel"
    assert (friday[night]["top"], friday[night]["height"]) == ((23.5 - 7) * 60, 30)
    assert (friday[night]["begins"], friday[night]["ends"]) == (True, False)
    # The day after shows the rest of the night, from the first hour that the calendar shows.
    assert (saturday[night]["top"], saturday[night]["height"]) == (0, 30)
    assert (saturday[night]["begins"], saturday[night]["ends"]) == (False, True)
    assert friday[night]["when"] == saturday[night]["when"] == "11:30 pm to 7:30 am on 15 May"
    assert (saturday["Breakfast"]["top"], saturday["Breakfast"]["height"]) == (60, 45)


def test_a_step_that_ends_before_the_hours_shown_has_no_part_on_the_next_day() -> None:
    """Its mark does not end on the day it starts, and its words say when it ends."""
    file = trip(
        ["alex"],
        ["hotel"],
        [stays("night", "hotel"), stays("lunch", "hotel")],
        [starts_at("night", 23)],
        [],
    )
    plan = (
        Step("night", "hotel", "hotel", ("alex",), seconds(23), seconds(23) + 6 * 3600),
        Step("lunch", "hotel", "hotel", ("alex",), seconds(12) + 86400, seconds(13) + 86400),
    )
    laid = calendar(sent_for(file, Report(Answer.FEASIBLE, itinerary=plan)))
    assert laid["hours"] == {"from": 11 * 60, "to": 24 * 60}
    assert marks(laid, 0) == [(0, "planned", 0, 0, 12 * 60, 60, True, False)]
    assert marks(laid, 1) == [(1, "planned", 0, 0, 60, 60, True, True)]
    assert laid["days"][0]["marks"][0]["when"] == "11:00 pm to 5:00 am on 16 May"


def test_a_step_with_no_known_end_is_drawn_half_an_hour_tall_and_does_not_end() -> None:
    walk = Step(None, "museum", "hotel", ("alex",), seconds(15), None, way="walk")
    laid = calendar(sent_for(group(), Report(Answer.FEASIBLE, itinerary=(walk,))))
    assert marks(laid) == [(0, "way", 0, 0, 60, 30, True, False)]
    assert laid["days"][0]["marks"][0]["when"] == "3:00 pm to an unknown time"


def test_a_step_with_no_time_is_named_beside_the_calendar() -> None:
    file = trip(
        ["alex", "sam"],
        ["museum", "pier"],
        [stays("visit", "museum"), stays("fireworks", "pier")],
        [starts_at("visit", 14), lasts("visit", "PT1H"), any_time("fireworks")],
        [lock("visit", "alex"), lock("fireworks", "alex", "sam")],
    )
    laid = calendar(sent_for(file, Report(Answer.UNDETERMINED)))
    assert laid["untimed"] == [{"name": "fireworks", "who": "alex and sam"}]
    assert marks(laid) == [(0, "locked", 0, 0, 60, 60, True, True)]
    assert laid["says"] == ONLY_LOCKS + CHICAGO


def test_a_calendar_with_nothing_on_it_says_why() -> None:
    nothing_locked = trip(["alex"], ["pier"], [stays("fireworks", "pier")], [], [])
    no_time = trip(
        ["alex"], ["pier"], [stays("fireworks", "pier")], [], [lock("fireworks", "alex")]
    )
    nobody = trip([], ["pier"], [], [], [])
    empty, untimed, idle, none = calendars(
        [
            sent_for(nothing_locked, Report(Answer.INFEASIBLE)),
            sent_for(no_time, Report(Answer.UNDETERMINED)),
            sent_for(nobody, Report(Answer.FEASIBLE)),
            None,
        ]
    )
    assert empty["says"] == (
        "The report shows no ITINERARY, and no LOCK names an OPTION. So the calendar is empty."
    )
    assert untimed["says"] == (
        "The report shows no ITINERARY, and the FILE gives no time to the OPTIONs that a LOCK"
        " names. So the calendar is empty."
    )
    assert untimed["untimed"] == [{"name": "fireworks", "who": "alex"}]
    assert idle["says"] == "The ITINERARY of the report is empty: nobody has to do anything."
    # The view sends no TRIP where one of its times cannot be written.
    assert none["says"] == (
        "This TRIP holds a time outside the years 0001 to 9999, so it has no calendar."
    )
    for laid in (empty, untimed, idle, none):
        assert laid["days"] == []


def test_the_calendar_shows_two_months_at_most_and_says_what_it_leaves_out() -> None:
    # The FILE's first time names Chicago, so the report shows every time on Chicago's clocks.
    file = trip(
        ["alex"],
        ["pier"],
        [stays("first", "pier"), stays("last", "pier")],
        [starts_at("first", 10)],
        [],
    )
    day = 86400
    plan = (
        Step("first", "pier", "pier", ("alex",), seconds(10), seconds(11)),
        Step("last", "pier", "pier", ("alex",), seconds(10) + 99 * day, seconds(11) + 99 * day),
    )
    laid = calendar(sent_for(file, Report(Answer.FEASIBLE, itinerary=plan)))
    assert len(laid["days"]) == 62
    assert laid["days"][0]["name"] == "Saturday 15 May 2027"
    assert laid["days"][-1]["name"] == "Thursday 15 July 2027"
    assert laid["says"] == (
        f"The ITINERARY of the report.{CHICAGO}"
        " The calendar shows the first 62 days. The steps go on for 38 more."
    )
    assert [len(each["marks"]) for each in laid["days"]] == [1, *([0] * 61)]


def made(steps: list[dict[str, Any]], persons: int = 1) -> Trip:
    """A TRIP as the view sends it, made by hand, for times that a FILE of the stories has not."""
    sent: Trip = {
        "zone": "UTC",
        "persons": [{"id": f"p{n}", "name": f"P{n}"} for n in range(persons)],
        "places": [{"id": "pier", "name": "the pier"}],
        "itinerary": True,
        "steps": [
            {
                "option": "stay",
                "way": None,
                "name": "Stay",
                "from": "pier",
                "to": "pier",
                "persons": ["p0"],
                "locked": [],
                **step,
            }
            for step in steps
        ],
    }
    assert holds(sent), sent
    return sent


def test_the_calendar_names_days_and_times_as_the_report_does() -> None:
    """On every kind of day, from the year 1 to the year 9999, and at every kind of time."""
    days = [
        date(1, 1, 1),
        date(9999, 12, 31),
        date(1900, 2, 28),
        date(2000, 2, 29),
        date(1970, 1, 1),
    ]
    chosen = random.Random(1)
    days += [date.fromordinal(chosen.randrange(1, date.max.toordinal())) for _ in range(300)]
    trips = [made([{"start": f"{day.isoformat()}T10:00:00", "end": None}]) for day in days]
    for day, laid in zip(days, calendars(cast("list[Trip | None]", trips)), strict=True):
        name = f"{DAYS[day.weekday()]} {day.day} {MONTHS[day.month - 1]} {day.year}"
        assert [each["name"] for each in laid["days"]] == [name]

    def when(start: str, end: str) -> str:
        (mark,) = calendar(made([{"start": start, "end": end}]))["days"][0]["marks"][:1]
        return str(mark["when"])

    assert when("2027-05-15T00:00:00", "2027-05-15T12:00:00") == "12:00 am to 12:00 pm"
    assert when("2027-05-15T00:00:05", "2027-05-15T23:59:59") == "12:00:05 am to 11:59:59 pm"
    assert when("2027-05-15T09:05:00", "2027-05-15T13:00:00") == "9:05 am to 1:00 pm"
    assert (
        when("2027-12-31T22:00:00", "2028-01-01T01:00:00")
        == "10:00 pm to 1:00 am on 1 January 2028"
    )


def test_a_step_that_ends_at_an_earlier_time_of_day_than_it_starts_has_no_height() -> None:
    """Where the clocks go back, a step can end at an earlier time of day than it starts at."""
    laid = calendar(made([{"start": "2027-11-07T01:30:00", "end": "2027-11-07T01:10:00"}]))
    # The day shows the hours from 1:00 am on, and the step is half an hour down it.
    assert laid["hours"]["from"] == 60
    assert marks(laid) == [(0, "planned", 0, 0, 30, 0, True, True)]


def some_trip(chosen: random.Random) -> Trip:
    """A TRIP of any kind that the view can send: odd times, no times, many or no PERSONs."""
    persons = [f"p{n}" for n in range(chosen.randrange(0, 6))]
    places = [f"q{n}" for n in range(chosen.randrange(1, 4))]
    first = datetime(chosen.choice([1, 1970, 2027, 9999]), chosen.randrange(1, 13), 1, 0, 0, 0)

    def time(most: int) -> str | None:
        try:
            moment = first + timedelta(seconds=chosen.randrange(-most, most))
        except OverflowError:
            return None
        return moment.isoformat(timespec="seconds")

    # With an ITINERARY, every step has a time, and some are WAYs. With none, every step is an
    # OPTION that a LOCK names for each PERSON who takes part, and it may have no time.
    planned = chosen.random() < 0.5
    steps: list[dict[str, Any]] = []
    for _ in range(chosen.randrange(0, 9) if persons else 0):
        takers = chosen.sample(persons, chosen.randrange(1, len(persons) + 1))
        start = time(chosen.choice([3600, 86400, 40 * 86400, 400 * 86400]))
        if start is None or (not planned and chosen.random() < 0.2):
            if planned:
                continue
            start = None
        end = None if start is None or chosen.random() < 0.2 else time(3 * 86400)
        is_way = planned and chosen.random() < 0.3
        steps.append(
            {
                "option": None if is_way else "o",
                "way": chosen.choice(["w", None]) if is_way else None,
                "name": chosen.choice(["A name", None]),
                "from": chosen.choice(places),
                "to": chosen.choice(places),
                "persons": takers,
                "start": start,
                "end": end,
                "locked": chosen.sample(takers, chosen.randrange(0, len(takers) + 1))
                if planned
                else takers,
            }
        )
    return {
        "zone": "UTC",
        "persons": [{"id": id, "name": id.upper()} for id in persons],
        "places": [{"id": id, "name": id.upper()} for id in places],
        "itinerary": planned,
        "steps": steps,
    }


def test_whatever_trip_the_view_sends_has_a_calendar() -> None:
    """Every mark is on its day and in its PERSONs' columns, whatever the times are."""
    chosen = random.Random(7)
    trips = [some_trip(chosen) for _ in range(400)]
    for sent in trips:
        assert holds(sent), sent
    assert sum(1 for sent in trips if sent["steps"]) > 200
    for sent, laid in zip(trips, calendars(cast("list[Trip | None]", trips)), strict=True):
        tall = laid["hours"]["to"] - laid["hours"]["from"]
        assert 0 <= laid["hours"]["from"] < laid["hours"]["to"] <= 24 * 60
        assert len(laid["days"]) <= 62
        assert laid["persons"] == sent["persons"]
        timed = [n for n, step in enumerate(sent["steps"]) if step["start"] is not None]
        assert len(laid["untimed"]) == len(sent["steps"]) - len(timed)
        begun: set[int] = set()
        for day in laid["days"]:
            for mark in day["marks"]:
                step = sent["steps"][mark["step"]]
                columns = [
                    n for n, person in enumerate(sent["persons"]) if person["id"] in step["persons"]
                ]
                assert 0 <= mark["top"] <= mark["top"] + mark["height"] <= tall, (sent, mark)
                assert set(range(mark["first"], mark["last"] + 1)) <= set(columns), (sent, mark)
                assert mark["kind"] == ("way" if step["option"] is None else "option")
                if mark["begins"]:
                    begun.add(mark["step"])
        # Unless the calendar leaves days out, every step with a time begins on one of its days.
        if "more" not in laid["says"]:
            assert begun == set(timed), sent
