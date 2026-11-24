"""The calendar that the page draws of a TRIP: a column for each day, and in it one for each PERSON.

The view sends the TRIP with each report. ``src/agloe/view/static/calendar.js`` lays it out:
how far down its day a step starts, how tall it is, whose columns it spans, and what its words
are. It has no page in it, so Node runs it here, through ``view_calendar.mjs``.

Nothing in it judges a TRIP. For a FEASIBLE TRIP the calendar holds the ITINERARY of the report,
in the report's own words. For any other TRIP it holds only the OPTIONs that a LOCK names.
"""

import itertools
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

from agloe import compiler, report
from agloe.answers import Answer, Report
from agloe.file import File, instant, parse, read
from agloe.reference import Step
from agloe.view.trip import holds, shown
from tests.stories import (
    EXAMPLES,
    any_time,
    at,
    carries,
    cutoff,
    every_right,
    every_transfer,
    every_use,
    lasts,
    lasts_between,
    lies_at,
    lock,
    moves,
    needs_no_right,
    needs_right,
    requires_object,
    seconds,
    starts_at,
    starts_from,
    stays,
    takes,
    trip,
    way_between,
)

STORY = EXAMPLES / "flight-home"
FILES = sorted(
    path for path in EXAMPLES.rglob("*.json") if not path.name.endswith(".expected.json")
)
# In the report in words: the line that names a day, and a line that shows one step of the plan.
DAY = re.compile(r"^(\w+ \d+ \w+ \d+) \(times in (.+)\)$")
LINE = re.compile(r"^  \d{1,2}:\d\d(:\d\d)? [ap]m.* to .+: .+$")
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
CHANGES = " A column that names its offset from UTC starts or ends with a change of those clocks."
ONLY_LOCKS = (
    "The report shows no ITINERARY. The calendar holds only the OPTIONs that a LOCK names, at"
    " the times the FILE states."
)
# Before the COMPILER has reported on the FILE.
NO_REPORT = (
    "The page has no report on this FILE yet. The calendar holds only the OPTIONs that a LOCK"
    " names, at the times the FILE states."
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


def calendars(
    trips: list[Trip | None],
    reports: list[dict[str, Any] | None] | None = None,
    texts: list[str | None] | None = None,
) -> list[Calendar]:
    """The calendar of each TRIP, by the page's own code, with the report that it came with.

    The report is as JSON, and in words where the calendar is to mark what it warns of.
    """
    with_them = reports if reports is not None else [None] * len(trips)
    in_words = texts if texts is not None else [None] * len(trips)
    asked = [
        {"trip": sent, "report": found, "text": words}
        for sent, found, words in zip(trips, with_them, in_words, strict=True)
    ]
    node = shutil.which("node")
    if node is None:
        if os.environ.get("CI"):
            pytest.fail("the tests of the view need Node")
        pytest.skip("needs Node")
    done = subprocess.run(
        [node, str(Path(__file__).parent / "view_calendar.mjs")],
        input=json.dumps(asked),
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    laid: list[Calendar] = json.loads(done.stdout)
    return laid


def parts(
    name: str,
    trips: list[Trip | None],
    reports: list[dict[str, Any] | None] | None = None,
    texts: list[str | None] | None = None,
) -> list[dict[str, Any]]:
    """What one part of the page shows of each TRIP, by the page's own code.

    ``name`` is the part: wants, options or capabilities. The report is as JSON, and in words
    where the part is to say what the report says of a case.
    """
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
        [node, str(Path(__file__).parent / "view_part.mjs"), name],
        input=json.dumps(asked),
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    shown: list[dict[str, Any]] = json.loads(done.stdout)
    return shown


def calendar(
    sent: Trip | None, found: dict[str, Any] | None = None, words: str | None = None
) -> Calendar:
    return calendars([sent], [found], [words])[0]


def with_its_report(path: Path) -> tuple[Trip, dict[str, Any]]:
    """What is sent of the TRIP in this FILE, and the report on it as JSON."""
    file = read(path)
    found = compiler.check(file)
    return sent_for(file, found), report.as_json(file, found)


def marks(laid: Calendar, day: int = 0) -> list[tuple[Any, ...]]:
    """The marks of one day: step, state, first and last column, top, height, begins, ends."""
    parts = ("step", "state", "first", "last", "top", "height", "begins", "ends")
    return [tuple(mark[each] for each in parts) for mark in laid["days"][day]["marks"]]


def names(laid: Calendar) -> list[str]:
    return [day["name"] for day in laid["days"]]


def test_the_calendar_says_what_the_report_says() -> None:
    """For every FEASIBLE example: the same days and the same steps, in the report's own words."""
    feasible = [
        path
        for path in FILES
        if json.loads(beside(path, ".expected.json").read_text())["answer"] == "FEASIBLE"
    ]
    assert len(feasible) > 10
    with_nobody = ending_late = 0
    sent_of = {path: drawn(path) for path in feasible}
    laid = calendars([sent_of[path] for path in feasible])
    for path, calendar_of in zip(feasible, laid, strict=True):
        name = f"{path.parent.name}/{path.stem}"
        in_report: list[tuple[str, str]] = []
        sent = sent_of[path]
        nobody = {n for n, step in enumerate(sent["steps"]) if not step["persons"]}
        day = ""
        for line in beside(path, ".expected.txt").read_text().split("\n"):
            header = DAY.match(line)
            if header:
                day = header[1]
                assert calendar_of["zone"] == header[2], name
            elif LINE.match(line):
                in_report.append((day, line))
        in_calendar: list[tuple[str, str]] = []
        # A step with nobody of the TRIP in it is in the column after those of the PERSONs,
        # and the calendar has that column only where the plan has such a step.
        last = len(sent["persons"])
        assert calendar_of["nobody"] is bool(nobody), name
        for each in calendar_of["days"]:
            seen: set[int] = set()
            for mark in each["marks"]:
                alone = mark["step"] in nobody
                assert mark["nobody"] is alone, name
                assert ((mark["first"], mark["last"]) == (last, last)) is alone, name
                # A step is drawn once for each run of PERSONs, and once more on each later day.
                if mark["begins"] and mark["step"] not in seen:
                    seen.add(mark["step"])
                    # The report names the PERSONs of a step, and nobody where there are none.
                    who = "" if alone else f", {mark['who']}"
                    words = f"  {mark['when']}: {mark['name']}{who}"
                    in_calendar.append((each["name"], words))
        assert in_calendar == in_report, name
        assert calendar_of["untimed"] == [], name
        assert calendar_of["itinerary"] is True, name
        if in_report:
            assert calendar_of["says"] == f"The ITINERARY of the report.{CHICAGO}", name
            with_nobody += bool(nobody)
            # The report shows when a step ends at the earliest. The calendar adds how late
            # it can end, where the FILE gives a range.
            ending_late += any(sent["steps"][n]["latest"] is not None for n in nobody)
        for each in calendar_of["days"]:
            # In a plan nobody is in two places at once, so every mark has its column to itself.
            assert all((mark["lane"], mark["lanes"]) == (0, 1) for mark in each["marks"]), name
            # In the examples the clocks do not change, so every column shows all its hours.
            assert each["shut"] == [], name
    assert with_nobody > 1 and ending_late > 0


def test_the_calendar_says_how_late_a_step_with_nobody_in_it_can_end_on_the_next_day() -> None:
    """A van leaves A at 11:00 pm with the bag and takes between half an hour and two hours
    and one second. Jo collects the bag at B at 1:00 am the next day. Nobody rides the van.
    The mark of the van says that it can end as late as 1:00:01 am, and on which day that is."""
    late_night = starts_at("pickup", 1)
    late_night["starts_at"] = late_night["starts_at"].replace("2027-05-15", "2027-05-16")
    facts = [
        starts_at("van", 23),
        lasts_between("van", "PT30M", "PT2H1S"),
        cutoff("van", "PT0S"),
        needs_right("van"),
        every_right("van"),
        late_night,
        lasts("pickup", "PT30M"),
        cutoff("pickup", "PT0S"),
        needs_no_right("pickup"),
        starts_from("jo", "b"),
        lies_at("bag", "a"),
        carries("van", "bag"),
        requires_object("pickup", "bag"),
        every_use("bag"),
        every_transfer("bag"),
    ]
    options = [moves("van", "a", "b"), stays("pickup", "b")]
    file = trip(
        ["jo"], ["a", "b"], options, facts, [lock("pickup", "jo")], rights=True, objects=["bag"]
    )
    found = compiler.check(file)
    assert found.answer is Answer.FEASIBLE
    sent, words = sent_for(file, found), report.as_text(file, found)
    laid = calendar(sent, report.as_json(file, found), words)
    assert warnings_are_those_of_the_report(sent, words, laid, "the van at night")
    # The van is in the column after Jo's, on the day it starts on.
    assert laid["nobody"] is True
    (van,) = [mark for mark in laid["days"][0]["marks"] if mark["nobody"]]
    assert (van["name"], van["first"], van["last"]) == ("van", 1, 1)
    assert (van["when"], van["late"]) == (
        "11:00 pm to 11:30 pm",
        "or as late as 1:00:01 am on 16 May",
    )
    assert (van["who"], van["lock"]) == ("nobody of the TRIP", "No LOCK names anybody for it.")
    assert "Nobody" not in laid["says"]
    # The report warns at the pickup: the bag might be late.
    assert laid["warned"] is True


def test_the_calendar_has_a_column_for_the_steps_with_nobody_in_them() -> None:
    """Alex visits the hall on Saturday. Two vans run that day with nobody of the TRIP in them,
    at the same time, and a third on Sunday, when the report warns of something at it. Each
    has its mark in the column after Alex's, with its WARNING on it."""
    vans = ["first-van", "other-van", "last-van"]
    file = trip(
        ["alex"],
        ["hall", "port"],
        [stays("visit", "hall"), *(moves(van, "hall", "port") for van in vans)],
        [starts_at("visit", 10)],
        [],
    )
    day = 86400
    plan = (
        Step("visit", "hall", "hall", ("alex",), seconds(10), seconds(11)),
        Step("first-van", "hall", "port", (), seconds(14), seconds(15, 30)),
        Step("other-van", "hall", "port", (), seconds(15), seconds(16)),
        Step("last-van", "hall", "port", (), seconds(14) + day, seconds(15, 30) + day),
    )
    sent = sent_for(file, Report(Answer.FEASIBLE, itinerary=plan))

    def in_words(*under_the_visit: str) -> str:
        return "\n".join(
            [
                "FEASIBLE, with a WARNING: this trip works, but it is at risk.",
                "",
                "Saturday 15 May 2027 (times in America/Chicago)",
                "  10:00 am to 11:00 am: visit, alex",
                *under_the_visit,
                "  2:00 pm to 3:30 pm: first-van",
                "  3:00 pm to 4:00 pm: other-van",
                "",
                "Sunday 16 May 2027 (times in America/Chicago)",
                "  2:00 pm to 3:30 pm: last-van",
                "    ! the permit would arrive 1 h after this starts.",
                "",
            ]
        )

    laid = calendar(sent, {"answer": "FEASIBLE"}, in_words())
    assert laid["nobody"] is True
    assert laid["persons"] == [{"id": "alex", "name": "alex"}]
    shown = [
        [
            (mark["name"], mark["first"], mark["last"], mark["lane"], mark["lanes"])
            for mark in each["marks"]
        ]
        for each in laid["days"]
    ]
    assert shown == [
        # The visit is in Alex's column. The two vans are in the column after it, and they
        # stand beside each other there, because they run at the same time.
        [("visit", 0, 0, 0, 1), ("first-van", 1, 1, 0, 2), ("other-van", 1, 1, 1, 2)],
        [("last-van", 1, 1, 0, 1)],
    ]
    states = [[(mark["state"], mark["nobody"]) for mark in each["marks"]] for each in laid["days"]]
    assert states == [
        [("planned", False), ("planned", True), ("planned", True)],
        [("planned", True)],
    ]
    # The WARNING is on the mark of its van, so the calendar speaks of the yellow edge.
    assert [mark["warns"] for mark in laid["days"][1]["marks"]] == [
        ["the permit would arrive 1 h after this starts."]
    ]
    assert laid["warned"] is True
    assert laid["says"] == f"The ITINERARY of the report.{CHICAGO}{WARNS}"
    assert warnings_are_those_of_the_report(sent, in_words(), laid, "three vans")
    # Without the report in words, the calendar has the same marks and warns of nothing.
    bare = calendar(sent)
    assert (bare["warned"], bare["says"]) == (False, f"The ITINERARY of the report.{CHICAGO}")
    assert [[mark["name"] for mark in each["marks"]] for each in bare["days"]] == [
        ["visit", "first-van", "other-van"],
        ["last-van"],
    ]
    # A plan with somebody in every step has no such column.
    everybody = sent_for(file, Report(Answer.FEASIBLE, itinerary=plan[:1]))
    assert calendar(everybody)["nobody"] is False


def test_the_calendar_of_the_flight_home() -> None:
    """Alex and Sam visit the museum, take the Blue Line and fly home, all on one Saturday."""
    laid = calendar(drawn(STORY / "works.json"))
    assert laid["persons"] == [{"id": "alex", "name": "Alex"}, {"id": "sam", "name": "Sam"}]
    # The day shows whole hours, with room above the first step and below the last.
    assert laid["hours"] == {"from": 13 * 60, "to": 20 * 60}
    assert names(laid) == ["Saturday 15 May 2027"]
    assert marks(laid) == [
        # Both columns, an hour down the day, an hour tall. A LOCK names the visit.
        (0, "locked", 0, 1, 60, 60, True, True),
        # The Blue Line is in the plan, and no LOCK names it.
        (1, "planned", 0, 1, 120, 60, True, True),
        (2, "locked", 0, 1, 240, 150, True, True),
    ]
    visit, train, flight = laid["days"][0]["marks"]
    assert (visit["kind"], visit["name"]) == ("option", "Museum visit")
    assert (visit["when"], visit["where"]) == ("2:00 pm to 3:00 pm", "the Art Institute")
    assert (visit["who"], visit["lock"]) == (
        "Alex and Sam",
        "Alex and Sam are each named by a LOCK.",
    )
    assert (train["where"], train["lock"]) == (
        "the Art Institute to O'Hare",
        "No LOCK names Alex and Sam.",
    )
    assert flight["where"] == "O'Hare to home"
    assert laid["days"][0]["bounds"] == []


def test_a_trip_with_no_report_has_a_calendar_of_what_is_locked_and_says_so() -> None:
    """Before the COMPILER has reported, the calendar holds what the FILE alone gives it."""
    file = read(STORY / "works.json")
    sent = shown(file)
    assert sent is not None
    laid = calendar(cast("Trip", sent))
    assert laid["says"] == NO_REPORT + CHICAGO
    assert laid["itinerary"] is None
    assert (laid["clash"], laid["warned"], laid["asked"]) == (False, False, False)
    # The same steps, at the same places, as for a report that shows no ITINERARY.
    with_none = calendar(sent_for(file, Report(Answer.INFEASIBLE)))
    assert with_none["says"] == ONLY_LOCKS + CHICAGO
    assert laid["days"] == with_none["days"]


def test_a_calendar_with_no_day_says_that_it_marks_a_step_with_no_time(tmp_path: Path) -> None:
    """A LOCK names the Skydeck visit, the FILE gives it no time, and nobody has a ticket."""
    content = json.loads((EXAMPLES / "a-ticket" / "cannot-work.json").read_text())
    content["decisions"] = [each for each in content["decisions"] if each["id"] == "lock-skydeck"]
    content["facts"] = [fact for fact in content["facts"] if fact["id"] != "skydeck-time"]
    path = tmp_path / "trip.json"
    path.write_text(json.dumps(content))
    sent, found = with_its_report(path)
    assert (found["answer"], sent["days"]) == ("INFEASIBLE", [])
    laid = calendar(sent, found)
    (step,) = laid["untimed"]
    assert step["clash"]
    # The whole says so too: the row of links marks the calendar by it.
    assert laid["clash"] is True


def test_a_trip_with_no_itinerary_has_a_calendar_of_what_is_locked() -> None:
    """And the calendar says so, in words."""
    laid = calendar(drawn(STORY / "cannot-work.json"))
    assert laid["says"] == ONLY_LOCKS + CHICAGO
    assert laid["itinerary"] is False
    assert laid["hours"] == {"from": 14 * 60, "to": 20 * 60}
    assert marks(laid) == [
        (0, "locked", 0, 1, 30, 60, True, True),
        (1, "locked", 0, 1, 180, 150, True, True),
    ]
    assert [mark["name"] for mark in laid["days"][0]["marks"]] == ["Museum visit", "Flight home"]


RULES_OUT = (
    " The report names {} records that rule out every plan."
    " A red edge marks what {} of them are about."
)


def test_the_calendar_marks_what_the_report_names_as_ruling_out_every_plan() -> None:
    """The report says which FACTs and DECISIONs cannot all hold. The calendar judges nothing."""
    sent, found = with_its_report(STORY / "cannot-work.json")
    assert len(found["conflict"]) == 8
    laid = calendar(sent, found)
    visit, flight = laid["days"][0]["marks"]
    # Each mark names the records about its step that the report names, in the FILE's order.
    assert visit["clash"] == ["visit-time", "visit-length", "lock-visit"]
    assert flight["clash"] == ["flight-time", "bag-drop", "lock-flight"]
    assert visit["finds"] == (
        "The report names visit-time, visit-length and lock-visit among what rules out every plan."
    )
    # Two of the eight are about no step of the calendar: a FACT about the Blue Line, which no
    # LOCK names, and a FACT about the ways to the airport.
    assert laid["says"] == ONLY_LOCKS + CHICAGO + RULES_OUT.format(8, 6)
    assert laid["clash"] is True
    # Without the report, the calendar marks nothing.
    bare = calendar(sent)
    assert [mark["clash"] for mark in bare["days"][0]["marks"]] == [[], []]
    assert [mark["finds"] for mark in bare["days"][0]["marks"]] == [None, None]
    assert (bare["says"], bare["clash"]) == (ONLY_LOCKS + CHICAGO, False)


def test_the_calendar_marks_the_end_of_the_trip_that_the_report_names() -> None:
    """The TRIP ends before the flight lands. The report names both the flight and that end."""
    sent, found = with_its_report(EXAMPLES / "the-times-of-the-trip" / "ends-too-early.json")
    assert found["conflict"] == ["flight-time", "flight-length", "trip-end", "lock-flight"]
    laid = calendar(sent, found)
    by_name = {mark["name"]: mark for mark in laid["days"][0]["marks"]}
    assert by_name["Flight home"]["clash"] == ["flight-time", "flight-length", "lock-flight"]
    assert by_name["Museum visit"]["clash"] == []
    assert [(bound["edge"], bound["clash"]) for bound in laid["days"][0]["bounds"]] == [
        ("starts", False),
        ("ends", True),
    ]
    assert laid["says"].endswith(RULES_OUT.format(4, 4))


def test_the_calendar_marks_only_what_a_report_names() -> None:
    """For every example: each record that a mark names is one that the report names."""
    pairs = [with_its_report(path) for path in FILES]
    laid = calendars([sent for sent, _ in pairs], [found for _, found in pairs])
    seen = 0
    for path, (sent, found), calendar_of in zip(FILES, pairs, laid, strict=True):
        name = f"{path.parent.name}/{path.stem}"
        conflict = found.get("conflict", [])
        marked: set[str] = set()
        for day in calendar_of["days"]:
            for mark in day["marks"]:
                records = sent["steps"][mark["step"]]["records"]
                assert mark["clash"] == [each for each in records if each in conflict], name
                marked.update(mark["clash"])
            for bound in day["bounds"]:
                assert bound["clash"] in (True, False), name
        for which in ("starts", "ends"):
            if sent[which] is not None and sent[which]["record"] in conflict:
                marked.add(sent[which]["record"])
        for step in sent["steps"]:
            if step["start"] is None:
                marked.update(each for each in step["records"] if each in conflict)
        assert calendar_of["clash"] is bool(marked), name
        assert ("rule out every plan" in calendar_of["says"]) is bool(conflict), name
        if conflict:
            seen += 1
            assert f"names {len(conflict)} records" in calendar_of["says"], name
            ending = (
                f"what {len(marked)} of them {'is' if len(marked) == 1 else 'are'} about."
                if marked
                else "None of them is about what the calendar shows."
            )
            assert calendar_of["says"].endswith(ending), name
        else:
            assert found["answer"] != "INFEASIBLE", name
    assert seen > 5


def test_a_report_that_names_nothing_the_page_can_read_marks_nothing() -> None:
    """Whatever the report holds where it names what rules out every plan, the calendar is whole."""
    sent, _ = with_its_report(STORY / "cannot-work.json")
    odd: list[dict[str, Any] | None] = [
        {"answer": "INFEASIBLE"},
        {"answer": "INFEASIBLE", "conflict": "visit-time"},
        {"answer": "INFEASIBLE", "conflict": [1, None, ["visit-time"], {"id": "visit-time"}]},
        {"answer": "INFEASIBLE", "conflict": {"visit-time": True}},
        {},
        None,
    ]
    for laid in calendars([sent] * len(odd), odd):
        assert [mark["clash"] for mark in laid["days"][0]["marks"]] == [[], []]
        assert laid["says"] == ONLY_LOCKS + CHICAGO
    # One record, and none that the calendar shows.
    one = calendar(sent, {"answer": "INFEASIBLE", "conflict": ["lock-visit"]})
    assert one["says"].endswith(
        " The report names 1 record that rules out every plan. A red edge marks what it is about."
    )
    other = calendar(sent, {"answer": "INFEASIBLE", "conflict": ["ways-to-ohare", "train-length"]})
    assert other["says"].endswith(
        " The report names 2 records that rule out every plan."
        " None of them is about what the calendar shows."
    )
    assert other["clash"] is False


WARNS = " A yellow edge marks each step shown at which the report warns of something."


def in_words(path: Path) -> tuple[Trip, dict[str, Any], str]:
    """What is sent of the TRIP in this FILE, and the report on it as JSON and in words."""
    file = read(path)
    found = compiler.check(file)
    return sent_for(file, found), report.as_json(file, found), report.as_text(file, found)


def test_the_calendar_marks_the_steps_at_which_the_report_warns_of_something() -> None:
    """In the report's own words: the lines that the report puts under a step of the plan."""
    sent, found, words = in_words(STORY / "works-but-risky.json")
    laid = calendar(sent, found, words)
    by_name = {mark["name"]: mark for mark in laid["days"][0]["marks"]}
    assert by_name["Flight home"]["warns"] == ["Alex and Sam would be 5 min too late for this."]
    assert by_name["Museum visit"]["warns"] == []
    assert laid["says"] == f"The ITINERARY of the report.{CHICAGO}{WARNS}"
    assert laid["warned"] is True
    # A right that is not bought yet is a warning too.
    sent, found, words = in_words(EXAMPLES / "a-ticket" / "not-bought-yet.json")
    laid = calendar(sent, found, words)
    warned = {mark["name"]: mark["warns"] for mark in laid["days"][0]["marks"] if mark["warns"]}
    assert list(warned) == ["Skydeck visit"]
    assert warned["Skydeck visit"][0].startswith("Sam still has to buy a right to this")
    # Without the report in words, the calendar marks nothing of it.
    bare = calendar(sent, found)
    assert all(mark["warns"] == [] for mark in bare["days"][0]["marks"])
    assert (bare["warned"], WARNS in bare["says"]) == (False, False)


def test_the_calendar_says_what_the_report_warns_of_after_the_days_shown() -> None:
    """Two concerts three months apart, each with a ticket still to buy. Only the first is shown."""
    file = trip(
        ["alex"],
        ["hall"],
        [stays("first", "hall"), stays("last", "hall")],
        [starts_at("first", 10)],
        [],
    )
    day = 86400
    plan = (
        Step("first", "hall", "hall", ("alex",), seconds(10), seconds(11)),
        Step("last", "hall", "hall", ("alex",), seconds(10) + 99 * day, seconds(11) + 99 * day),
    )
    sent = sent_for(file, Report(Answer.FEASIBLE, itinerary=plan))
    assert [len(step["parts"]) for step in sent["steps"]] == [1, 0]
    words = "\n".join(
        [
            "FEASIBLE, with a WARNING: this trip works, but not everything is booked yet.",
            "",
            "Saturday 15 May 2027 (times in America/Chicago)",
            "  10:00 am to 11:00 am: first, alex",
            "    ! alex still has to buy a right to this.",
            "",
            "Sunday 22 August 2027 (times in America/Chicago)",
            "  10:00 am to 11:00 am: last, alex",
            "    ! alex still has to buy a right to this.",
            "",
        ]
    )
    laid = calendar(sent, {"answer": "FEASIBLE"}, words)
    assert [mark["warns"] for mark in laid["days"][0]["marks"]] == [
        ["alex still has to buy a right to this."]
    ]
    assert laid["says"].endswith(
        f"{WARNS} The report also warns of something at 1 step after the days shown."
    )
    assert warnings_are_those_of_the_report(sent, words, laid, "two concerts")
    # With the first concert bought, the only WARNING is at a step that has no mark.
    still_to_buy = "\n    ! alex still has to buy a right to this."
    bought = words.replace(f"first, alex{still_to_buy}", "first, alex", 1)
    assert bought.count(still_to_buy) == 1
    laid = calendar(sent, {"answer": "FEASIBLE"}, bought)
    assert laid["warned"] is False
    assert warnings_are_those_of_the_report(sent, bought, laid, "the last concert")


def test_the_calendar_warns_only_of_what_the_report_warns_of() -> None:
    """For every example: the words on each step are the lines that the report puts under it."""
    asked = [in_words(path) for path in FILES]
    laid = calendars(
        [sent for sent, _, _ in asked],
        [found for _, found, _ in asked],
        [words for _, _, words in asked],
    )
    seen = 0
    for path, (sent, _, words), calendar_of in zip(FILES, asked, laid, strict=True):
        name = f"{path.parent.name}/{path.stem}"
        seen += warnings_are_those_of_the_report(sent, words, calendar_of, name)
    assert seen > 3


def warnings_are_those_of_the_report(
    sent: Trip, words: str, calendar_of: Calendar, name: str
) -> bool:
    """Checks that the calendar warns of what the report warns of, step by step, and says
    whether the report warns of anything. A step that has a mark has its words on its marks,
    and the calendar speaks of a yellow edge where a mark has some. A step with nobody in
    it has its mark like any other. A step after the days shown is counted."""
    # The lines of the report that start with "!", each under the line of its step.
    under: dict[int, list[str]] = {}
    step = -1
    for line in words.split("\n"):
        if LINE.match(line):
            step += 1
        elif line.startswith("    ! ") and step >= 0:
            under.setdefault(step, []).append(line.removeprefix("    ! "))
    marked: set[int] = set()
    for day in calendar_of["days"]:
        for mark in day["marks"]:
            marked.add(mark["step"])
            assert mark["warns"] == under.get(mark["step"], []), name
            assert mark["records"] == sent["steps"][mark["step"]]["records"], name
        for bound in day["bounds"]:
            assert bound["record"] in {"trip-start", "trip-end"}, name
    drawn_with_one = any(number in marked for number in under)
    assert calendar_of["warned"] is drawn_with_one, name
    assert (WARNS in calendar_of["says"]) is drawn_with_one, name
    later = [n for n in under if n not in marked]
    count = "1 step" if len(later) == 1 else f"{len(later)} steps"
    if later:
        also = f" The report also warns of something at {count} after the days shown."
        assert also in calendar_of["says"], name
    else:
        assert "The report also warns of something" not in calendar_of["says"], name
    return bool(under)


def test_the_calendar_marks_a_warning_at_a_step_with_nobody_in_it_for_a_real_report() -> None:
    """A van takes a permit from C to A and takes between one hour and three. A second van
    requires the permit at A at 11:00 am and carries the bag to B, where Jo collects it.
    Nobody rides either van. The report warns at the second van that the permit would come
    an hour late. Both vans have their marks in the column after Jo's, and the second has
    the WARNING on it."""
    options = [moves("permit-van", "c", "a"), moves("bag-van", "a", "b"), stays("pickup", "b")]
    facts = [
        starts_at("permit-van", 9),
        lasts_between("permit-van", "PT1H", "PT3H"),
        starts_at("bag-van", 11),
        lasts("bag-van", "PT1H"),
        starts_at("pickup", 13),
        lasts("pickup", "PT30M"),
        *(cutoff(each, "PT0S") for each in ("permit-van", "bag-van", "pickup")),
        needs_no_right("pickup"),
        *(
            fact
            for van in ("permit-van", "bag-van")
            for fact in (needs_right(van), every_right(van))
        ),
        starts_from("jo", "b"),
        lies_at("permit", "c"),
        lies_at("bag", "a"),
        carries("permit-van", "permit"),
        carries("bag-van", "bag"),
        requires_object("bag-van", "permit"),
        requires_object("pickup", "bag"),
        *(
            fact
            for thing in ("permit", "bag")
            for fact in (every_use(thing), every_transfer(thing))
        ),
    ]
    file = trip(
        ["jo"],
        ["a", "b", "c"],
        options,
        facts,
        [lock("pickup", "jo")],
        rights=True,
        objects=["permit", "bag"],
    )
    found = compiler.check(file)
    assert found.answer is Answer.FEASIBLE
    sent, words = sent_for(file, found), report.as_text(file, found)
    assert [step["persons"] for step in sent["steps"]] == [[], [], ["jo"]]
    laid = calendar(sent, report.as_json(file, found), words)
    assert warnings_are_those_of_the_report(sent, words, laid, "the permit comes late")
    assert laid["warned"] is True
    assert laid["says"] == f"The ITINERARY of the report.{CHICAGO}{WARNS}"
    shown = [
        (mark["name"], mark["first"], mark["when"], mark["late"], mark["warns"])
        for mark in laid["days"][0]["marks"]
    ]
    assert shown == [
        ("permit-van", 1, "9:00 am to 10:00 am", "or as late as 12:00 pm", []),
        (
            "bag-van",
            1,
            "11:00 am to 12:00 pm",
            None,
            ["permit would arrive 1 h after this starts."],
        ),
        ("pickup", 0, "1:00 pm to 1:30 pm", None, []),
    ]


ASKS = " A yellow edge marks each step shown that the report names in what the FILE does not say."
NOT_SHOWN = " What the report says the FILE does not say is not about a step shown here."
NAMED_SO = "The report names this OPTION in what the FILE does not say."
ANY_OF = "The trip works in any of these cases:"


def asked_marks(laid: Calendar) -> dict[str, tuple[list[int], list[str]]]:
    """For each step on the calendar: the cases of the report that name it, and their words."""
    return {
        mark["name"]: (mark["cases"], mark["asks"]) for day in laid["days"] for mark in day["marks"]
    }


def test_the_calendar_marks_the_steps_that_the_file_does_not_say_enough_about() -> None:
    """The trip works if the night at the hotel takes 8 h 30 min or less. The FILE does not say."""
    sent, found, words = in_words(EXAMPLES / "several-days" / "depends-on-the-night.json")
    laid = calendar(sent, found, words)
    assert laid["says"] == f"{ONLY_LOCKS}{CHICAGO}{ASKS}"
    assert laid["asked"] is True
    said = "The trip works if Night at the hotel takes 8 h 30 min or less."
    assert asked_marks(laid) == {
        "Dinner": ([], []),
        "Night at the hotel": ([0], [said]),
        "Breakfast": ([], []),
        "Skydeck visit": ([], []),
    }


def test_a_case_marks_each_step_that_it_names_and_a_step_has_each_case_that_names_it() -> None:
    # One case that needs two things: each drive does not require driving a manual car.
    sent, found, words = in_words(EXAMPLES / "a-driver" / "depends-on-the-car.json")
    said = (
        "The trip works if Drive to the dunes does not require driving a manual car and Drive"
        " back to the hotel does not require driving a manual car."
    )
    assert asked_marks(calendar(sent, found, words)) == {
        "Drive to the dunes": ([0], [said]),
        "Drive back to the hotel": ([0], [said]),
    }
    # Two cases about one OPTION: a right is found, or a place has a price that can be paid.
    sent, found, words = in_words(EXAMPLES / "a-ticket" / "depends-on-the-price.json")
    laid = calendar(sent, found, words)
    # The words are the lines of the report: its heading, and the line of each case.
    assert ANY_OF in words.split("\n")
    assert asked_marks(laid) == {
        "Skydeck visit": (
            [0, 1],
            [
                ANY_OF,
                "1. A right to Skydeck visit is found for Sam, in addition to the 2 places on"
                " OFFER.",
                "2. A place from skydeck-tickets has a price that Sam can pay.",
            ],
        ),
        "Gallery talk": ([], []),
        "Lunch in the park": ([], []),
    }
    for line in asked_marks(laid)["Skydeck visit"][1][1:]:
        assert f"  {line}" in words.split("\n")
    # Two cases, and one of them is about a PERSON and no step.
    sent, found, words = in_words(EXAMPLES / "a-kayak-tour" / "two-things-left-open.json")
    assert asked_marks(calendar(sent, found, words)) == {
        "Kayak tour": (
            [0],
            [
                ANY_OF,
                "1. Kayak tour requires swimming of one PERSON who takes part, or does not"
                " require it.",
            ],
        )
    }
    # A case can name a step by the place that somebody has to buy for it.
    sent, found, words = in_words(EXAMPLES / "a-ticket" / "nobody-said-who-pays.json")
    assert [need.get("option") for need in found["missing"][1]] == [None]
    assert [buy["option"] for buy in found["missing"][1][0]["buys"]] == ["skydeck"]
    cases, said = asked_marks(calendar(sent, found, words))["Skydeck visit"]
    assert cases == [0, 1]
    assert [line[:40] for line in said] == [
        ANY_OF,
        "1. A right to Skydeck visit is found for",
        "2. Each place that Sam has to buy can be",
    ]


def test_the_calendar_says_where_what_is_missing_is_about_no_step_shown() -> None:
    """The trip works if the cab takes 45 min or less. No LOCK names the cab, so it is not shown."""
    sent, found, words = in_words(STORY / "depends-on-the-cab.json")
    laid = calendar(sent, found, words)
    assert laid["says"] == f"{ONLY_LOCKS}{CHICAGO}{NOT_SHOWN}"
    assert laid["asked"] is False
    assert asked_marks(laid) == {"Museum visit": ([], []), "Flight home": ([], [])}


def test_only_a_report_on_a_trip_that_depends_on_something_marks_what_is_missing() -> None:
    sent, found = with_its_report(EXAMPLES / "several-days" / "depends-on-the-night.json")
    # Without the report in words, the mark says that the report names its OPTION.
    laid = calendar(sent, found)
    assert asked_marks(laid)["Night at the hotel"] == ([0], [NAMED_SO])
    assert laid["says"] == f"{ONLY_LOCKS}{CHICAGO}{ASKS}"
    odd: list[Any] = [
        None,
        {},
        # Another answer, and what is no list of cases.
        {**found, "answer": "INFEASIBLE"},
        {**found, "missing": "night"},
        {**found, "missing": [["night"], [None], [{"option": 3}], 7]},
        {**found, "missing": []},
    ]
    for laid in calendars([sent] * len(odd), odd):
        assert laid["says"] == f"{ONLY_LOCKS}{CHICAGO}"
        assert laid["asked"] is False
        assert all(cases == [] and asks == [] for cases, asks in asked_marks(laid).values())


def test_a_step_with_no_time_is_marked_where_the_report_says_what_is_missing_about_it() -> None:
    """A LOCK names a dinner that has no time, and the report says the trip depends on it."""
    file = trip(
        ["alex"],
        ["hotel"],
        [stays("dinner", "hotel"), stays("visit", "hotel")],
        [starts_at("visit", 14), lasts("visit", "PT1H")],
        [lock("dinner", "alex"), lock("visit", "alex")],
    )
    sent = sent_for(file, Report(Answer.UNDETERMINED))
    found = {"answer": "UNDETERMINED", "missing": [[{"what": "duration", "option": "dinner"}]]}
    laid = calendar(sent, found)
    (dinner,) = laid["untimed"]
    assert (dinner["name"], dinner["cases"], dinner["asks"]) == ("dinner", [0], [NAMED_SO])
    # It says which step of the TRIP it is, so that pointing at it lights up that step alone.
    assert sent["steps"][dinner["step"]]["option"] == "dinner"
    assert laid["asked"] is True
    assert laid["says"].endswith(ASKS)


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
    day = laid["days"][0]["marks"]
    # In the FILEs of the stories, each PERSON's name is their id.
    assert [mark["who"] for mark in day[:2]] == ["alex and jo"] * 2
    # Everybody takes part in the visit. Each mark says whom the LOCK names, and whom it does not.
    assert [mark["who"] for mark in day[2:5]] == ["alex, sam and jo"] * 3
    assert [mark["lock"] for mark in day[2:5]] == [
        "No LOCK names alex.",
        "sam is named by a LOCK.",
        "No LOCK names jo.",
    ]
    walk = day[5]
    assert (walk["kind"], walk["name"], walk["where"]) == ("way", "walk", "museum to hotel")
    assert walk["lock"] is None
    # A WAY has its name beside it where it takes 20 minutes or more.
    assert [mark["named"] for mark in day[4:]] == [True, True, False]
    assert not any(mark["brief"] for mark in day)


def test_a_way_that_the_file_does_not_list_is_named_as_the_report_names_it() -> None:
    other = Step(None, "museum", "hotel", ("alex",), seconds(15), seconds(15, 30))
    laid = calendar(sent_for(group(), Report(Answer.FEASIBLE, itinerary=(other,))))
    (mark,) = laid["days"][0]["marks"]
    assert (mark["kind"], mark["name"], mark["state"]) == ("way", "another WAY", "way")


def test_a_way_that_takes_next_to_no_time_is_a_tick_that_nothing_covers() -> None:
    """Alex takes a WAY that takes no time, and at that moment a visit starts."""
    file = trip(
        ["alex"],
        ["hotel", "museum"],
        [stays("visit", "museum")],
        [starts_at("visit", 12), lasts("visit", "PT1H"), takes("door", "PT0S")],
        [],
        ways=[way_between("door", "hotel", "museum")],
    )
    plan = (
        Step(None, "hotel", "museum", ("alex",), seconds(12), seconds(12), way="door"),
        Step("visit", "museum", "museum", ("alex",), seconds(12), seconds(13)),
    )
    laid = calendar(sent_for(file, Report(Answer.FEASIBLE, itinerary=plan)))
    door, visit = laid["days"][0]["marks"]
    assert (door["kind"], door["top"], door["height"]) == ("way", visit["top"], 0)
    # The page draws a mark that is brief as a tick on top of what is beside it.
    assert (door["brief"], visit["brief"]) == (True, False)


def test_ways_that_take_no_time_at_one_moment_are_ticks_beside_each_other() -> None:
    """Alex goes from the hotel to the foyer and on to the museum. Neither WAY takes any time."""
    file = trip(
        ["alex"],
        ["hotel", "foyer", "museum"],
        [stays("visit", "museum")],
        [starts_at("visit", 12), lasts("visit", "PT1M")],
        [],
        ways=[way_between("door", "hotel", "foyer"), way_between("stairs", "foyer", "museum")],
    )
    plan = (
        Step(None, "hotel", "foyer", ("alex",), seconds(12), seconds(12), way="door"),
        Step(None, "foyer", "museum", ("alex",), seconds(12), seconds(12), way="stairs"),
        Step("visit", "museum", "museum", ("alex",), seconds(12), seconds(12, 1)),
    )
    laid = calendar(sent_for(file, Report(Answer.FEASIBLE, itinerary=plan)))
    door, stairs, visit = laid["days"][0]["marks"]
    # The page puts ticks that would lie on each other beside each other.
    assert (door["brief"], stairs["brief"], visit["brief"]) == (True, True, False)
    assert door["top"] == stairs["top"] == visit["top"]


def test_a_step_that_runs_past_midnight_is_on_both_days() -> None:
    """A night at the hotel, in the example of several days."""
    laid = calendar(drawn(EXAMPLES / "several-days" / "works.json"))
    assert names(laid) == ["Friday 14 May 2027", "Saturday 15 May 2027"]
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


def alone(*stays_of_alex: tuple[str, int | None]) -> Trip:
    """What is sent of Alex's stays, in a plan: each from a time, for so many seconds."""
    when = {"id": "stay-time", "option": "stay", "starts_at": stays_of_alex[0][0]}
    file = trip(["alex"], ["hotel"], [stays("stay", "hotel")], [when], [])
    plan = tuple(
        Step(
            "stay",
            "hotel",
            "hotel",
            ("alex",),
            instant(start),
            None if length is None else instant(start) + length,
        )
        for start, length in stays_of_alex
    )
    return sent_for(file, Report(Answer.FEASIBLE, itinerary=plan))


def test_a_step_with_no_known_end_is_drawn_half_an_hour_tall_and_does_not_end() -> None:
    walk = Step(None, "museum", "hotel", ("alex",), seconds(15), None, way="walk")
    laid = calendar(sent_for(group(), Report(Answer.FEASIBLE, itinerary=(walk,))))
    assert marks(laid) == [(0, "way", 0, 0, 60, 30, True, False)]
    assert laid["days"][0]["marks"][0]["when"] == "3:00 pm to an unknown time"


def test_a_step_with_no_known_end_stays_on_the_day_it_starts_on() -> None:
    """Five minutes before midnight, its mark is five minutes tall, and there is no next day."""
    laid = calendar(alone((at(23, 55), None)))
    assert names(laid) == ["Saturday 15 May 2027"]
    assert laid["hours"] == {"from": 23 * 60, "to": 24 * 60}
    assert marks(laid) == [(0, "planned", 0, 0, 55, 5, True, False)]
    # One second before midnight, it is one second tall, and ends where the day does.
    laid = calendar(alone((at(23, 59).replace(":59:00", ":59:59"), None)))
    (mark,) = laid["days"][0]["marks"]
    assert mark["top"] + mark["height"] == 60


def test_a_day_on_which_the_clocks_go_back_has_a_column_before_and_one_after() -> None:
    """In Chicago the clocks go back from 2:00 am to 1:00 am on 7 November 2027.

    They show 1:10 am twice that night. Two stays, one at each, are an hour apart. So they are
    in two columns, and never side by side in one.
    """
    first, second = "2027-11-07T01:10:00-05:00", "2027-11-07T01:10:00-06:00"
    laid = calendar(alone((f"{first}[America/Chicago]", 300), (f"{second}[America/Chicago]", 300)))
    assert names(laid) == ["Sunday 7 November 2027 (UTC-5)", "Sunday 7 November 2027 (UTC-6)"]
    assert laid["says"] == f"The ITINERARY of the report.{CHICAGO}{CHANGES}"
    assert laid["hours"] == {"from": 0, "to": 2 * 60}
    assert marks(laid, 0) == [(0, "planned", 0, 0, 70, 5, True, True)]
    assert marks(laid, 1) == [(1, "planned", 0, 0, 70, 5, True, True)]
    # The times of this TRIP are not all at one offset from UTC, so each says its own.
    assert [day["marks"][0]["when"] for day in laid["days"]] == [
        "1:10 am (UTC-5) to 1:15 am (UTC-5)",
        "1:10 am (UTC-6) to 1:15 am (UTC-6)",
    ]
    # The first column has every hour that is shown. The second starts at 1:00 am: the hour
    # before that is not on its clocks.
    assert laid["days"][0]["shut"] == []
    assert laid["days"][1]["shut"] == [{"top": 0, "height": 60}]
    # A stay of 70 minutes from the first 1:05 am: 55 minutes in one column, 15 in the other.
    laid = calendar(alone(("2027-11-07T01:05:00-05:00[America/Chicago]", 70 * 60)))
    assert marks(laid, 0) == [(0, "planned", 0, 0, 65, 55, True, False)]
    assert marks(laid, 1) == [(0, "planned", 0, 0, 60, 15, False, True)]
    assert laid["days"][0]["marks"][0]["when"] == "1:05 am (UTC-5) to 1:15 am (UTC-6)"


def test_a_step_that_goes_on_after_the_clocks_change_is_shown_to_its_end() -> None:
    """In Chicago the clocks go from 2:00 am to 3:00 am on 14 March 2027.

    A stay of 70 minutes from 1:55 am has five minutes before the change and 65 after it. The
    calendar shows the hours of both.
    """
    laid = calendar(alone(("2027-03-14T01:55:00-06:00[America/Chicago]", 70 * 60)))
    assert names(laid) == ["Sunday 14 March 2027 (UTC-6)", "Sunday 14 March 2027 (UTC-5)"]
    assert laid["hours"] == {"from": 60, "to": 5 * 60}
    assert marks(laid, 0) == [(0, "planned", 0, 0, 55, 5, True, False)]
    assert marks(laid, 1) == [(0, "planned", 0, 0, 120, 65, False, True)]
    # Each column says which of the hours shown its clocks run in, and whether those hold
    # its first moment and its last. Here no time is left out between the two columns.
    assert [day["open"] for day in laid["days"]] == [
        {"top": 0, "bottom": 60, "first": False, "last": True},
        {"top": 120, "bottom": 240, "first": True, "last": False},
    ]
    assert laid["days"][0]["shut"] == [{"top": 60, "height": 180}]
    assert laid["days"][1]["shut"] == [{"top": 0, "height": 120}]


def test_a_step_that_goes_on_at_an_earlier_time_of_day_is_shown_there() -> None:
    """In the Chatham Islands the clocks go back from 3:45 am to 2:45 am on 4 April 2027.

    A stay of ten minutes from 3:40 am has five minutes before the change and five after it,
    at 2:45 am. The calendar shows the hours of both.
    """
    laid = calendar(alone(("2027-04-04T03:40:00+13:45[Pacific/Chatham]", 600)))
    assert names(laid) == ["Sunday 4 April 2027 (UTC+13:45)", "Sunday 4 April 2027 (UTC+12:45)"]
    assert laid["hours"] == {"from": 2 * 60, "to": 5 * 60}
    assert marks(laid, 0) == [(0, "planned", 0, 0, 100, 5, True, False)]
    assert marks(laid, 1) == [(0, "planned", 0, 0, 45, 5, False, True)]
    assert laid["days"][0]["marks"][0]["when"] == "3:40 am (UTC+13:45) to 2:50 am (UTC+12:45)"


def test_a_date_that_a_time_zone_left_out_has_no_column() -> None:
    """Samoa went from 29 December 2011 to 31 December."""
    laid = calendar(alone(("2011-12-29T23:00:00-10:00[Pacific/Apia]", 2 * 3600)))
    assert names(laid) == [
        "Thursday 29 December 2011 (UTC-10)",
        "Saturday 31 December 2011 (UTC+14)",
    ]
    when = "11:00 pm (UTC-10) to 1:00 am (UTC+14) on 31 December"
    assert laid["days"][0]["marks"][0]["when"] == when


def test_a_step_that_can_take_longer_says_so_and_does_not_end() -> None:
    """The FILE gives a duration as a range. The mark ends after the least, with a dashed edge."""
    file = trip(
        ["alex"],
        ["museum"],
        [stays("visit", "museum")],
        [starts_at("visit", 14, 30), lasts_between("visit", "PT1H", "PT2H")],
        [lock("visit", "alex")],
    )
    least = Step("visit", "museum", "museum", ("alex",), seconds(14, 30), seconds(15, 30))
    for found in (Report(Answer.INFEASIBLE), Report(Answer.FEASIBLE, itinerary=(least,))):
        laid = calendar(sent_for(file, found))
        (mark,) = laid["days"][0]["marks"]
        assert (mark["when"], mark["late"]) == ("2:30 pm to 3:30 pm", "or as late as 4:30 pm")
        assert (mark["height"], mark["begins"], mark["ends"]) == (60, True, False)
    # The COMPILER's plan for this FILE is sure to hold: it ends the visit after the most.
    (mark,) = calendar(sent_for(file, compiler.check(file)))["days"][0]["marks"]
    assert (mark["when"], mark["late"]) == ("2:30 pm to 4:30 pm", None)
    assert (mark["height"], mark["ends"]) == (120, True)
    # A step that takes one length of time can end no later, and its mark ends.
    (visit,) = calendar(drawn(STORY / "cannot-work.json"))["days"][0]["marks"][:1]
    assert (visit["late"], visit["ends"]) == (None, True)


def test_options_that_one_person_is_in_at_the_same_time_stand_side_by_side() -> None:
    """Two LOCKs can name OPTIONs at the same time. Neither mark hides the other."""
    file = trip(
        ["alex", "sam", "jo"],
        ["museum", "pier", "hotel"],
        [stays("visit", "museum"), stays("fireworks", "pier"), stays("dinner", "hotel")],
        [
            starts_at("visit", 14),
            lasts("visit", "PT2H"),
            starts_at("fireworks", 15),
            lasts("fireworks", "PT2H"),
            starts_at("dinner", 16, 30),
            lasts("dinner", "PT1H"),
        ],
        [
            lock("visit", "alex", "sam", "jo"),
            lock("fireworks", "alex", "sam"),
            lock("dinner", "alex", "jo"),
        ],
    )
    laid = calendar(sent_for(file, Report(Answer.INFEASIBLE)))
    placed = [
        (mark["name"], mark["first"], mark["last"], mark["lane"], mark["lanes"])
        for mark in laid["days"][0]["marks"]
    ]
    assert placed == [
        # Alex and Sam are in the visit and in the fireworks at once: two lanes in each column.
        ("visit", 0, 0, 0, 2),
        ("visit", 1, 1, 0, 2),
        # Jo is in the visit, and in nothing else until dinner: one lane.
        ("visit", 2, 2, 0, 1),
        ("fireworks", 0, 0, 1, 2),
        ("fireworks", 1, 1, 1, 2),
        # Dinner starts when the visit is over, and takes the lane that the visit leaves to Alex.
        ("dinner", 0, 0, 0, 2),
        ("dinner", 2, 2, 0, 1),
    ]
    # Two OPTIONs at exactly the same time, both with no length: still a lane each.
    both = trip(
        ["alex"],
        ["pier"],
        [stays("one", "pier"), stays("other", "pier")],
        [starts_at("one", 9), lasts("one", "PT0S"), starts_at("other", 9), lasts("other", "PT0S")],
        [lock("one", "alex"), lock("other", "alex")],
    )
    laid = calendar(sent_for(both, Report(Answer.INFEASIBLE)))
    assert [(mark["lane"], mark["lanes"]) for mark in laid["days"][0]["marks"]] == [(0, 2), (1, 2)]


def framed(starts: str, ends: str, visit: bool = True) -> Trip:
    """What is sent of a TRIP with these times for itself, and a visit on Saturday at 2:00 pm."""
    times: list[dict[str, Any]] = [
        {"id": "trip-start", "trip_starts_at": starts},
        {"id": "trip-end", "trip_ends_at": ends},
    ]
    file = trip(
        ["alex"],
        ["museum"],
        [stays("visit", "museum")],
        [starts_at("visit", 14), lasts("visit", "PT1H")],
        [lock("visit", "alex"), *times] if visit else times,
    )
    return sent_for(file, Report(Answer.UNDETERMINED if visit else Answer.FEASIBLE))


def test_the_calendar_shows_when_the_trip_starts_and_ends() -> None:
    """On the days that the FILE gives the TRIP, whether or not a step is on them."""
    laid = calendar(framed(at(13, 30), at(16, 15)))
    assert laid["hours"] == {"from": 13 * 60, "to": 16 * 60}
    assert laid["days"][0]["bounds"] == [
        {
            "says": "The TRIP starts at 1:30 pm",
            "edge": "starts",
            "top": 30,
            "clash": False,
            "record": "trip-start",
        },
        # 4:15 pm is after the hours that the calendar shows, so the line is at their edge.
        {
            "says": "The TRIP ends at 4:15 pm",
            "edge": "ends",
            "top": 180,
            "clash": False,
            "record": "trip-end",
        },
    ]
    laid = calendar(framed(at(17, day=14), at(20, 30, day=17)))
    assert names(laid) == [
        "Friday 14 May 2027",
        "Saturday 15 May 2027",
        "Sunday 16 May 2027",
        "Monday 17 May 2027",
    ]
    assert [len(day["marks"]) for day in laid["days"]] == [0, 1, 0, 0]
    assert [[bound["says"] for bound in day["bounds"]] for day in laid["days"]] == [
        ["The TRIP starts at 5:00 pm"],
        [],
        [],
        ["The TRIP ends at 8:30 pm"],
    ]


def test_the_start_and_the_end_of_the_trip_each_have_their_line_and_their_words() -> None:
    """However close together they are. The page puts the words above the day and below it."""
    # Both are before the hours that the calendar shows, so both lines are at the top of the day.
    laid = calendar(framed(at(9), at(10)))
    assert laid["hours"] == {"from": 13 * 60, "to": 16 * 60}
    assert laid["days"][0]["bounds"] == [
        {
            "says": "The TRIP starts at 9:00 am",
            "edge": "starts",
            "top": 0,
            "clash": False,
            "record": "trip-start",
        },
        {
            "says": "The TRIP ends at 10:00 am",
            "edge": "ends",
            "top": 0,
            "clash": False,
            "record": "trip-end",
        },
    ]
    # A TRIP of one minute.
    laid = calendar(framed(at(0), at(0, 1), visit=False))
    assert laid["days"][0]["bounds"] == [
        {
            "says": "The TRIP starts at 12:00 am",
            "edge": "starts",
            "top": 0,
            "clash": False,
            "record": "trip-start",
        },
        {
            "says": "The TRIP ends at 12:01 am",
            "edge": "ends",
            "top": 1,
            "clash": False,
            "record": "trip-end",
        },
    ]


def test_only_the_time_of_the_trip_that_the_report_names_is_marked() -> None:
    """The TRIP is from 9:00 am to 9:30 am, and a LOCK names a tour that ends at 9:40 am."""
    file = trip(
        ["alex"],
        ["pier"],
        [stays("tour", "pier")],
        [starts_at("tour", 9, 20), lasts("tour", "PT20M")],
        [
            lock("tour", "alex"),
            {"id": "trip-start", "trip_starts_at": at(9)},
            {"id": "trip-end", "trip_ends_at": at(9, 30)},
        ],
    )
    found = compiler.check(file)
    assert found.answer is Answer.INFEASIBLE
    assert "trip-end" in found.conflict
    assert "trip-start" not in found.conflict
    laid = calendar(sent_for(file, found), report.as_json(file, found))
    assert [(bound["edge"], bound["clash"]) for bound in laid["days"][0]["bounds"]] == [
        ("starts", False),
        ("ends", True),
    ]


def test_a_step_with_no_time_is_marked_where_the_report_names_what_is_about_it() -> None:
    """A LOCK names the Skydeck visit, the FILE gives it no time, and no ticket covers it."""
    document = json.loads((EXAMPLES / "a-ticket" / "cannot-work.json").read_text())
    document["facts"] = [fact for fact in document["facts"] if fact["id"] != "skydeck-time"]
    file = parse(json.dumps(document))
    found = compiler.check(file)
    assert found.answer is Answer.INFEASIBLE
    sent = sent_for(file, found)
    (visit,) = [step for step in sent["steps"] if step["option"] == "skydeck"]
    assert visit["start"] is None
    assert set(found.conflict) <= set(visit["records"])
    laid = calendar(sent, report.as_json(file, found))
    (untimed,) = [step for step in laid["untimed"] if step["name"] == "Skydeck visit"]
    assert untimed["clash"] == [each for each in visit["records"] if each in found.conflict]
    assert untimed["finds"].startswith("The report names ")
    count = len(found.conflict)
    assert laid["says"].endswith(
        f" The report names {count} records that rule out every plan."
        f" A red edge marks what {count} of them are about."
    )
    assert laid["clash"] is True


def test_only_a_report_on_a_trip_that_cannot_work_marks_anything() -> None:
    """A report on a TRIP that works names nothing that rules out every plan."""
    sent, found = with_its_report(STORY / "works.json")
    odd = {**found, "conflict": ["visit-time", "lock-visit", "lock-flight"]}
    laid = calendar(sent, odd)
    assert all(mark["clash"] == [] for mark in laid["days"][0]["marks"])
    assert laid["says"] == f"The ITINERARY of the report.{CHICAGO}"


def test_a_time_of_the_trip_says_its_date_where_its_column_has_another() -> None:
    """In St. John's the clocks went back over midnight on 1 November 2009.

    A TRIP that ends at 11:01 pm on 31 October, as the clocks show that date again, ends as the
    one minute of 1 November before it does. That column says the date of the end.
    """
    stjohns = "[America/St_Johns]"
    file = trip(
        ["alex"],
        ["harbour"],
        [],
        [],
        [
            {"id": "trip-start", "trip_starts_at": f"2009-10-31T20:00:00-02:30{stjohns}"},
            {"id": "trip-end", "trip_ends_at": f"2009-10-31T23:01:00-03:30{stjohns}"},
        ],
    )
    laid = calendar(sent_for(file, Report(Answer.FEASIBLE)))
    assert names(laid) == ["Saturday 31 October 2009", "Sunday 1 November 2009 (UTC-2:30)"]
    assert [[bound["says"] for bound in day["bounds"]] for day in laid["days"]] == [
        ["The TRIP starts at 8:00 pm (UTC-2:30)"],
        ["The TRIP ends at 11:01 pm (UTC-3:30) on 31 October"],
    ]


def test_a_calendar_with_no_step_shows_the_hours_of_the_trip() -> None:
    """Nobody has to do anything, and the TRIP is from 1:00 am to 5:00 am."""
    laid = calendar(framed(at(1), at(5), visit=False))
    assert laid["says"] == (
        f"The ITINERARY of the report is empty: nobody has to do anything.{CHICAGO}"
    )
    assert laid["hours"] == {"from": 0, "to": 6 * 60}
    assert laid["days"][0]["marks"] == []
    assert laid["days"][0]["bounds"] == [
        {
            "says": "The TRIP starts at 1:00 am",
            "edge": "starts",
            "top": 60,
            "clash": False,
            "record": "trip-start",
        },
        {
            "says": "The TRIP ends at 5:00 am",
            "edge": "ends",
            "top": 300,
            "clash": False,
            "record": "trip-end",
        },
    ]
    # A TRIP from one afternoon to the next covers the night between: the days show all hours.
    laid = calendar(framed(at(14), at(14, day=16), visit=False))
    assert laid["hours"] == {"from": 0, "to": 24 * 60}
    assert [[bound["top"] for bound in day["bounds"]] for day in laid["days"]] == [[840], [840]]
    # So does a TRIP that ends after the last day that the calendar shows.
    laid = calendar(framed(at(14), at(14).replace("2027-05", "2027-08"), visit=False))
    assert len(laid["days"]) == 62
    assert laid["hours"] == {"from": 0, "to": 24 * 60}
    assert [len(day["bounds"]) for day in laid["days"]] == [1, *([0] * 61)]


def test_a_step_with_no_time_is_named_beside_the_calendar() -> None:
    file = trip(
        ["alex", "sam"],
        ["museum", "pier"],
        [stays("visit", "museum"), stays("fireworks", "pier")],
        [starts_at("visit", 14), lasts("visit", "PT1H"), any_time("fireworks")],
        [lock("visit", "alex"), lock("fireworks", "alex", "sam")],
    )
    laid = calendar(sent_for(file, Report(Answer.UNDETERMINED)))
    assert laid["untimed"] == [
        {
            "name": "fireworks",
            "who": "alex and sam",
            "records": ["fireworks-time", "fireworks-open", "lock-fireworks"],
            "clash": [],
            "finds": None,
            "cases": [],
            "asks": [],
            # The visit comes first, at its time. The fireworks have none.
            "step": 1,
        }
    ]
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
    # Before the COMPILER has reported, each says that instead.
    early = calendars([cast("Trip", shown(nothing_locked)), cast("Trip", shown(no_time))])
    assert [each["says"] for each in early] == [
        "The page has no report on this FILE yet, and no LOCK names an OPTION. So the calendar"
        " is empty.",
        "The page has no report on this FILE yet, and the FILE gives no time to the OPTIONs that"
        " a LOCK names. So the calendar is empty.",
    ]
    assert untimed["untimed"] == [
        {
            "name": "fireworks",
            "who": "alex",
            "records": ["fireworks-open", "lock-fireworks"],
            "clash": [],
            "finds": None,
            "cases": [],
            "asks": [],
            "step": 0,
        }
    ]
    assert idle["says"] == "The ITINERARY of the report is empty: nobody has to do anything."
    # Where the view sends no TRIP, the page says that there is no calendar.
    assert none["says"] == "There is no calendar of this TRIP: the view could not make one."
    for laid in (empty, untimed, idle, none):
        assert laid["days"] == []


def test_the_calendar_shows_two_months_at_most_and_says_where_the_trip_ends() -> None:
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
    assert (names(laid)[0], names(laid)[-1]) == ("Saturday 15 May 2027", "Thursday 15 July 2027")
    assert laid["says"] == (
        f"The ITINERARY of the report.{CHICAGO}"
        " The calendar shows the first 62 columns. It leaves out what comes after them, up to"
        " Sunday 22 August 2027."
    )
    assert [len(each["marks"]) for each in laid["days"]] == [1, *([0] * 61)]


def parts_of(start: datetime, end: datetime | None, days: list[date]) -> list[dict[str, Any]]:
    """The parts of a step on these days, where every day has 24 hours."""

    def seconds_of(moment: datetime) -> int:
        on_the_clock = moment.hour * 3600 + moment.minute * 60 + moment.second
        return moment.toordinal() * 86400 + on_the_clock

    begins = seconds_of(start)
    reach = begins if end is None else max(begins, seconds_of(end))
    parts: list[dict[str, Any]] = []
    for index, day in enumerate(days):
        opens = day.toordinal() * 86400
        first, last = max(begins, opens), min(reach, opens + 86400)
        if not (first < last if reach > begins else opens <= begins < opens + 86400):
            continue
        parts.append(
            {
                "day": index,
                "from": first - opens,
                "to": last - opens,
                "begins": first == begins,
                "ends": end is not None and last == reach,
            }
        )
    return parts


def an_option(id: str, name: str, place: str) -> dict[str, Any]:
    """An OPTION as the view sends it, of which the FILE says nothing but where it is."""
    return {
        "id": id,
        "name": name,
        "from": place,
        "to": place,
        "start": None,
        "any_time": False,
        "length": None,
        "margin": None,
        "locked": [],
        "records": [],
    }


def a_way(id: str, name: str, place: str) -> dict[str, Any]:
    """A WAY as the view sends it, of which the FILE says nothing but where it goes."""
    return {
        "id": id,
        "name": name,
        "from": place,
        "to": place,
        "both_ways": True,
        "length": None,
        "records": [],
    }


def written(moment: datetime | None) -> dict[str, Any] | None:
    """A time as the view sends it, with no offset."""
    return None if moment is None else {"at": moment.isoformat(timespec="seconds"), "offset": None}


def whole(day: date) -> dict[str, Any]:
    """A day of 24 hours as the view sends it."""
    return {"date": day.isoformat(), "offset": None, "opens": 0, "closes": 86400}


def made(times: list[tuple[str, str | None]]) -> Trip:
    """A TRIP as the view sends it, made by hand: one stay of one PERSON for each pair of times."""
    spans = [
        (datetime.fromisoformat(start), None if end is None else datetime.fromisoformat(end))
        for start, end in times
    ]
    first = min(start.date() for start, _ in spans)
    last = max(
        (end - timedelta(seconds=1) if end and end > start else start).date()
        for start, end in spans
    )
    days = [first + timedelta(days=n) for n in range((last - first).days + 1)]
    sent: Trip = {
        "zone": "UTC",
        "persons": [{"id": "p0", "name": "P0"}],
        "places": [{"id": "pier", "name": "the pier"}],
        "itinerary": True,
        "days": [whole(day) for day in days],
        "until": None,
        "starts": None,
        "ends": None,
        "wants": [],
        "options": [an_option("stay", "Stay", "pier")],
        "starts_from": [],
        "ways": [],
        "complete_travel": [],
        "rights": [],
        "budgets": [],
        "capabilities": [],
        "objects": [],
        "steps": [
            {
                "option": "stay",
                "way": None,
                "name": "Stay",
                "from": "pier",
                "to": "pier",
                "persons": ["p0"],
                "locked": [],
                "start": written(start),
                "end": written(end),
                "latest": None,
                "parts": parts_of(start, end, days),
                "records": [],
            }
            for start, end in spans
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
    trips = [made([(f"{day.isoformat()}T10:00:00", None)]) for day in days]
    for day, laid in zip(days, calendars(cast("list[Trip | None]", trips)), strict=True):
        name = f"{DAYS[day.weekday()]} {day.day} {MONTHS[day.month - 1]} {day.year}"
        assert names(laid) == [name]

    def when(start: str, end: str) -> str:
        return str(calendar(made([(start, end)]))["days"][0]["marks"][0]["when"])

    assert when("2027-05-15T00:00:00", "2027-05-15T12:00:00") == "12:00 am to 12:00 pm"
    assert when("2027-05-15T00:00:05", "2027-05-15T23:59:59") == "12:00:05 am to 11:59:59 pm"
    assert when("2027-05-15T09:05:00", "2027-05-15T13:00:00") == "9:05 am to 1:00 pm"
    late = "10:00 pm to 1:00 am on 1 January 2028"
    assert when("2027-12-31T22:00:00", "2028-01-01T01:00:00") == late


RECORDS = ["a-time", "a-length", "a-lock", "another"]


def some_trip(chosen: random.Random) -> Trip:
    """A TRIP of any kind that the view can send: odd times, no times, many or no PERSONs."""
    persons = [f"p{n}" for n in range(chosen.randrange(0, 6))]
    places = [f"q{n}" for n in range(chosen.randrange(1, 4))]
    year = chosen.choice([1, 1970, 2027, 9999])
    opens = datetime(year, chosen.randrange(1, 11), chosen.randrange(1, 28), 0, 0, 0)
    days = [opens.date() + timedelta(days=n) for n in range(chosen.randrange(0, 9))]
    closes = opens + timedelta(days=len(days))

    def moment(after: datetime | None = None) -> datetime:
        early = opens if after is None else after
        room = max(1, int((closes - early).total_seconds()))
        return early + timedelta(seconds=chosen.randrange(0, room))

    # With an ITINERARY, every step has a time, and some are WAYs. With none, every step is an
    # OPTION that a LOCK names for each PERSON who takes part, and it may have no time.
    planned = chosen.random() < 0.5
    steps: list[dict[str, Any]] = []
    for _ in range(chosen.randrange(0, 9) if persons else 0):
        takers = chosen.sample(persons, chosen.randrange(1, len(persons) + 1))
        untimed = not days or (not planned and chosen.random() < 0.2)
        if untimed and planned:
            continue
        start = None if untimed else moment()
        end = None if start is None or chosen.random() < 0.2 else moment(start)
        if end is not None and chosen.random() < 0.3:
            end = start  # a step with no length
        latest = None if end is None or chosen.random() < 0.7 else end + timedelta(minutes=45)
        is_way = planned and chosen.random() < 0.3
        way = chosen.choice(["w", None]) if is_way else None
        steps.append(
            {
                "option": None if is_way else "o",
                "way": way,
                "name": None if is_way and way is None else "A name",
                "from": chosen.choice(places),
                "to": chosen.choice(places),
                "persons": takers,
                "locked": chosen.sample(takers, chosen.randrange(0, len(takers) + 1))
                if planned
                else takers,
                "start": written(start),
                "end": written(end),
                "latest": written(latest),
                "parts": [] if start is None else parts_of(start, end, days),
                "records": chosen.sample(RECORDS, chosen.randrange(0, len(RECORDS) + 1)),
            }
        )

    def bound(record: str) -> dict[str, Any] | None:
        if not days or chosen.random() < 0.5:
            return None
        day = chosen.randrange(0, len(days))
        second = chosen.choice([0, 86400, chosen.randrange(0, 86401)])
        when = f"{days[day].isoformat()}T12:00:00"
        return {"at": when, "offset": None, "day": day, "second": second, "record": record}

    return {
        "zone": "UTC",
        "persons": [{"id": id, "name": id.upper()} for id in persons],
        "places": [{"id": id, "name": id.upper()} for id in places],
        "itinerary": planned,
        "days": [whole(day) for day in days],
        "until": chosen.choice([None, None, "2030-01-01"]),
        "wants": [],
        "options": [an_option("o", "A name", places[0])],
        "starts_from": [],
        "ways": [a_way("w", "A name", places[0])],
        "complete_travel": [],
        "rights": [],
        "budgets": [],
        "capabilities": [],
        "objects": [],
        "starts": bound("trip-start"),
        "ends": bound("trip-end"),
        "steps": steps,
    }


def test_whatever_trip_the_view_sends_has_a_calendar() -> None:
    """Every mark is on its day and in its PERSONs' columns, whatever the times are."""
    chosen = random.Random(7)
    trips = [some_trip(chosen) for _ in range(500)]
    for sent in trips:
        assert holds(sent), sent
    assert sum(1 for sent in trips if sent["steps"]) > 200
    # Each comes with a report that names some records, or with none.
    named = [chosen.sample([*RECORDS, "trip-end"], chosen.randrange(0, 4)) for _ in trips]
    reports: list[dict[str, Any] | None] = [
        {"answer": "INFEASIBLE", "conflict": conflict} if conflict else None for conflict in named
    ]
    laid_out = calendars(cast("list[Trip | None]", trips), reports)
    for sent, conflict, laid in zip(trips, named, laid_out, strict=True):
        tall = laid["hours"]["to"] - laid["hours"]["from"]
        assert 0 <= laid["hours"]["from"] < laid["hours"]["to"] <= 24 * 60
        assert len(laid["days"]) == len(sent["days"])
        assert laid["persons"] == sent["persons"]
        timed = [n for n, step in enumerate(sent["steps"]) if step["start"] is not None]
        assert len(laid["untimed"]) == len(sent["steps"]) - len(timed)
        begun: set[int] = set()
        for day in laid["days"]:
            taken: dict[tuple[int, int], list[tuple[float, float]]] = {}
            for mark in day["marks"]:
                step = sent["steps"][mark["step"]]
                columns = [
                    n for n, person in enumerate(sent["persons"]) if person["id"] in step["persons"]
                ]
                assert 0 <= mark["top"] <= mark["top"] + mark["height"] <= tall, (sent, mark)
                assert set(range(mark["first"], mark["last"] + 1)) <= set(columns), (sent, mark)
                assert mark["kind"] == ("way" if step["option"] is None else "option")
                assert 0 <= mark["lane"] < mark["lanes"], mark
                assert mark["clash"] == [each for each in step["records"] if each in conflict]
                if mark["begins"]:
                    begun.add(mark["step"])
                if mark["kind"] == "option":
                    for column in range(mark["first"], mark["last"] + 1):
                        span = (mark["top"], mark["top"] + mark["height"])
                        taken.setdefault((column, mark["lane"]), []).append(span)
            # No two OPTIONs are drawn over each other: in one lane of one column, one
            # follows another.
            for spans in taken.values():
                spans.sort()
                for (_, bottom), (top, _) in itertools.pairwise(spans):
                    assert bottom <= top, (sent, spans)
            for bound in day["bounds"]:
                assert 0 <= bound["top"] <= tall
            assert day["shut"] == []
        # Every step with a time begins on one of the days.
        assert begun == set(timed), sent
