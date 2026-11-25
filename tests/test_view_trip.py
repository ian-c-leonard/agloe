"""What a page is sent of a TRIP, so that it can draw it.

The command reads the FILE with the reader that the COMPILER uses. With each report it sends
the names, the days, who takes part in each step, and each time on the clocks that the report
shows times on. For a FEASIBLE TRIP the steps are the ITINERARY of the report. For any other
TRIP the report shows no ITINERARY, and the steps are the OPTIONs that a LOCK names, at the
times the FILE states.

It also sends the WANTs of the FILE: for whom each is a must or a must-not, and each OPTION
that a FACT says SATISFIES it or does not. And it sends every OPTION of the FILE with what the
FILE says of it: where it is, when it starts, how long it takes, how early people must be
there, and whom a LOCK names for it.

A day is sent as the stretch of it in which the clocks run on without a change, and each step
says which part of it lies in which stretch. So the page works out no time for itself, on any
night and in any time zone.
"""

import copy
import functools
import json
import os
import re
import shutil
import subprocess
import unicodedata
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from agloe import compiler
from agloe import report as reports
from agloe.answers import Answer, Report
from agloe.file import Complete, File, Offer, instant, parse, read
from agloe.names import seen_as
from agloe.reference import Step
from agloe.view.trip import MOST_DAYS, holds, shown
from tests.stories import (
    EXAMPLES,
    any_time,
    at,
    can,
    lasts,
    lasts_between,
    lock,
    moves,
    requires,
    seconds,
    starts_at,
    stays,
    takes,
    takes_between,
    trip,
    way_between,
)

STORY = EXAMPLES / "flight-home"
FILES = sorted(
    path for path in EXAMPLES.rglob("*.json") if not path.name.endswith(".expected.json")
)
# In the report in words: the line that names a day, and a line that shows one step of the plan.
DAY = re.compile(r"^(\w+) (\d+) (\w+) (\d+) \(times in .+\)$")
LINE = re.compile(r"^  \d{1,2}:\d\d(:\d\d)? [ap]m.* to .+: .+$")
# How the last part of a report starts. Its DEADLINEs have lines that start with a time too.
LAST_PART = re.compile(r"^This (report uses .+ as the time now|FILE does not state the time now)")
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
HOUR = 3600
CHICAGO = "[America/Chicago]"

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


def time(written: str, offset: str | None = None) -> dict[str, Any]:
    """A time as a page is sent it: as the clocks show it, with its offset where one is sent."""
    return {"at": written, "offset": offset}


def clock(sent: dict[str, Any] | None) -> str | None:
    """What the clocks show at a time that a page is sent."""
    return None if sent is None else sent["at"]


def day(date: str, opens: int = 0, closes: int = 24 * HOUR, offset: str | None = None) -> Trip:
    """A stretch of a day as a page is sent it: its date, and from when to when by the clock."""
    return {"date": date, "offset": offset, "opens": opens, "closes": closes}


def dates(sent: Trip) -> list[str]:
    return [each["date"] for each in sent["days"]]


def part(day: int, start: int, end: int, begins: bool = True, ends: bool = True) -> dict[str, Any]:
    """A part of a step: its stretch of a day, and from when to when by the clock, in seconds."""
    return {"day": day, "from": start, "to": end, "begins": begins, "ends": ends}


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
    assert sent["until"] is None
    in_the_file = json.loads(path.read_text()).get("wants", [])
    assert [want["id"] for want in sent["wants"]] == [want["id"] for want in in_the_file]
    # Every OPTION of the FILE is sent, in the FILE's order, with what the FILE says of it.
    assert [option["id"] for option in sent["options"]] == [each.id for each in file.options]
    for option, each in zip(sent["options"], file.options, strict=True):
        assert (option["from"], option["to"]) == (each.origin, each.destination)
        stated, length, margin = file.start(each.id), file.duration(each.id), file.cutoff(each.id)
        assert (option["start"] is not None) is (stated is not None and stated.at is not None)
        assert option["any_time"] is (stated is not None and stated.at is None)
        assert option["length"] == (
            None
            if length is None
            else {
                "shortest": length.shortest,
                "longest": length.longest,
                "contingent": length.contingent,
            }
        )
        assert option["margin"] == (None if margin is None else margin.margin)
        named = {person for lock in file.locks if lock.option == each.id for person in lock.persons}
        assert option["locked"] == [person.id for person in file.persons if person.id in named]
    # Each FACT about where a PERSON starts from is sent, in the FILE's order of PERSONs.
    started = [file.starts_from(person.id) for person in file.persons]
    assert sent["starts_from"] == [
        {"person": fact.person, "place": fact.place, "record": fact.id}
        for fact in started
        if fact is not None
    ]
    # Every WAY of the FILE is sent, in the FILE's order, with what the FILE says of it.
    assert [way["id"] for way in sent["ways"]] == [each.id for each in file.ways]
    for way, listed in zip(sent["ways"], file.ways, strict=True):
        assert (way["from"], way["to"], way["both_ways"]) == (
            listed.origin,
            listed.destination,
            listed.both_ways,
        )
        length = file.duration(listed.id)
        assert (way["length"] is None) is (length is None)
        assert way["records"] == ([] if length is None else [length.id])
    # So is each FACT that the FILE lists every way of some travel.
    in_full = [fact for fact in file.facts if isinstance(fact, Complete)]
    assert [(each["record"], each["from"], each["to"]) for each in sent["complete_travel"]] == [
        (fact.id, fact.origin, fact.destination) for fact in in_full
    ]
    # What the FILE says of the rights to an OPTION is sent, in the FILE's order of OPTIONs.
    said_of = {each["option"]: each for each in sent["rights"]}
    assert list(said_of) == [each.id for each in file.options if each.id in said_of]
    for each in file.options:
        needed, complete = file.needs_right(each.id), file.rights_complete(each.id)
        # Each OFFER for the OPTION: for PERSONs, or for the OBJECTs it names.
        bookings = file.bookings(each.id)
        offers = [fact for fact in file.facts if isinstance(fact, Offer) and fact.option == each.id]
        if needed is None and complete is None and not bookings and not offers:
            assert each.id not in said_of
            continue
        rights = said_of[each.id]
        assert (None if rights["needs"] is None else rights["needs"]["needed"]) is needed
        assert [booking["id"] for booking in rights["bookings"]] == [fact.id for fact in bookings]
        for booking, fact in zip(rights["bookings"], bookings, strict=True):
            assert booking["paid"] == (
                None
                if fact.paid is None
                else {
                    "amount": str(fact.paid.money.amount),
                    "currency": fact.paid.money.currency,
                    "budget": fact.paid.budget,
                    "by": fact.paid.by,
                }
            )
        assert [(offer["id"], offer["places"]) for offer in rights["offers"]] == [
            (fact.id, fact.places) for fact in offers
        ]
        for offer, fact in zip(rights["offers"], offers, strict=True):
            named = [thing.id for thing in file.objects if thing.id in fact.objects]
            assert offer["objects"] == named and sorted(offer["names"]) == sorted(named)
        assert (rights["complete"] is None) is (complete is None)
    # Every BUDGET of the FILE is sent, in the FILE's order, with each cap on it.
    assert [budget["id"] for budget in sent["budgets"]] == [each.id for each in file.budgets]
    for budget, pot in zip(sent["budgets"], file.budgets, strict=True):
        assert budget["persons"] == [each.id for each in file.persons if each.id in pot.persons]
        assert budget["objects"] == [each.id for each in file.objects if each.id in pot.objects]
        assert sorted(budget["names"]) == sorted([*pot.persons, *pot.objects])
        assert budget["currencies"] == list(pot.currencies)
        assert [(cap["id"], cap["limit"]["currency"]) for cap in budget["caps"]] == [
            (cap.id, currency) for (id, currency), cap in file.caps.items() if id == pot.id
        ]
    # Every CAPABILITY of the FILE is sent, in the FILE's order, with each FACT about it.
    assert [each["id"] for each in sent["capabilities"]] == [each.id for each in file.capabilities]
    for capability in sent["capabilities"]:
        able = [(person.id, file.ability(person.id, capability["id"])) for person in file.persons]
        assert capability["has"] == [
            {"person": person, "has": fact.has, "record": fact.id}
            for person, fact in able
            if fact is not None
        ]
        asked = [(each.id, file.requirement(each.id, capability["id"])) for each in file.options]
        assert [(each["option"], each["of"], each["record"]) for each in capability["options"]] == [
            (option, fact.of, fact.id) for option, fact in asked if fact is not None
        ]
        complete = file.requires_complete(capability["id"])
        assert capability["complete"] == (None if complete is None else complete.id)
    # Every OBJECT of the FILE is sent, in the FILE's order, with each FACT about it.
    assert [thing["id"] for thing in sent["objects"]] == [each.id for each in file.objects]
    for thing in sent["objects"]:
        starts = file.object_starts(thing["id"])
        assert thing["starts"] == (
            None
            if starts is None
            else {"person": starts.person, "place": starts.place, "record": starts.id}
        )
        needs = [(each.id, file.object_requirement(each.id, thing["id"])) for each in file.options]
        assert [(each["option"], each["needed"], each["record"]) for each in thing["requires"]] == [
            (option, fact.needed, fact.id) for option, fact in needs if fact is not None
        ]
        bars = [(each.id, file.object_refusal(each.id, thing["id"])) for each in file.options]
        assert [(each["option"], each["refused"], each["record"]) for each in thing["refuses"]] == [
            (option, fact.refused, fact.id) for option, fact in bars if fact is not None
        ]
        does = [(each.id, file.action(each.id, thing["id"])) for each in file.options]
        assert [(each["option"], each["does"], each["record"]) for each in thing["transfers"]] == [
            (option, fact.does, fact.id) for option, fact in does if fact is not None
        ]
        required = file.object_requirements_complete(thing["id"])
        moved = file.transfers_complete(thing["id"])
        assert thing["requires_complete"] == (None if required is None else required.id)
        assert thing["transfers_complete"] == (None if moved is None else moved.id)
    # Each step that is an OPTION is one of them.
    ids = {option["id"] for option in sent["options"]}
    assert {step["option"] for step in sent["steps"]} - {None} <= ids
    # In the examples the clocks do not change: every day is whole, and no time needs its offset.
    for each in sent["days"]:
        assert (each["offset"], each["opens"], each["closes"]) == (None, 0, 24 * HOUR)
    assert len(set(dates(sent))) == len(sent["days"])
    for step in sent["steps"]:
        assert bool(step["parts"]) is (step["start"] is not None)
        if step["parts"]:
            assert dates(sent)[step["parts"][0]["day"]] == step["start"]["at"][:10]
            assert step["start"]["offset"] is None


@pytest.mark.parametrize("path", FEASIBLE, ids=name_of)
def test_a_feasible_trip_is_sent_with_the_itinerary_of_its_report(path: Path) -> None:
    """Each PERSON takes the same steps, at the same times, as in the report."""
    sent = drawn(path)

    def on_the_clock(written: str | None) -> str | None:
        # The report writes a time with its offset and its time zone after the clock time.
        return None if written is None else written[:19]

    in_report = Counter(
        (
            step.get("option"),
            step.get("way"),
            person,
            on_the_clock(step["start"]),
            on_the_clock(step["end"]),
        )
        for step in expected(path)["itinerary"]
        for person in step["persons"]
    )
    in_trip = Counter(
        (step["option"], step["way"], person, clock(step["start"]), clock(step["end"]))
        for step in sent["steps"]
        for person in step["persons"]
    )
    assert in_trip == in_report
    # The report in words names PERSONs who take a WAY together on one line. So does the page.
    words = beside(path, ".expected.txt").read_text().split("\n")
    ends = next((at for at, line in enumerate(words) if LAST_PART.match(line)), len(words))
    lines = [line for line in words[:ends] if LINE.match(line)]
    assert len(sent["steps"]) == len(lines)
    for step, line in zip(sent["steps"], lines, strict=True):
        name = step["name"] or "another WAY"
        # A step with nobody of the TRIP in it names nobody after the OPTION.
        assert f": {name}, " in line if step["persons"] else line.endswith(f": {name}")
    # Every day that the report names is a day that the page is sent.
    for line in words:
        named = DAY.match(line)
        if named:
            month = MONTHS.index(named[3]) + 1
            assert f"{int(named[4]):04d}-{month:02d}-{int(named[2]):02d}" in dates(sent)


def test_each_step_says_which_of_its_persons_a_lock_names() -> None:
    sent = drawn(STORY / "works.json")
    assert [(step["option"], step["locked"]) for step in sent["steps"]] == [
        ("museum-visit", ["alex", "sam"]),
        ("blue-line", []),
        ("flight", ["alex", "sam"]),
    ]
    assert sent["days"] == [day("2027-05-15")]
    assert (sent["starts"], sent["ends"]) == (None, None)


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
            "locked": ["sam"],
            "start": time("2027-05-15T14:00:00"),
            "end": time("2027-05-15T15:00:00"),
            "latest": None,
            # The visit is on the first day, from 14 hours into it to 15.
            "parts": [part(0, 14 * HOUR, 15 * HOUR)],
            # The FACTs about the visit and the LOCK of it, in the FILE's order.
            "records": ["visit-time", "visit-length", "visit-open", "lock-visit"],
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
            "locked": [],
            "start": time("2027-05-15T15:00:00"),
            "end": time("2027-05-15T15:20:00"),
            "latest": None,
            "parts": [part(0, 15 * HOUR, 15 * HOUR + 1200)],
            # The FILE says nothing of the walk but that it is there.
            "records": [],
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
    told = [
        (step["persons"], step["from"], clock(step["start"]), clock(step["end"]))
        for step in sent["steps"]
    ]
    assert told == [
        (["alex"], "museum", "2027-05-15T15:00:00", "2027-05-15T15:20:00"),
        (["sam"], "museum", "2027-05-15T16:00:00", "2027-05-15T16:20:00"),
        (["alex"], "hotel", "2027-05-15T17:00:00", "2027-05-15T17:20:00"),
        # Nobody knows how long this one takes, so it has no end.
        (["sam"], "hotel", "2027-05-15T17:00:00", None),
    ]
    # A step with no known end has one part with no length, where it starts. It does not end.
    assert sent["steps"][-1]["parts"] == [part(0, 17 * HOUR, 17 * HOUR, ends=False)]
    assert holds(sent)


def test_a_way_that_the_file_does_not_list_has_no_name() -> None:
    """The report calls it another WAY. The page is told that the FILE gives it no name."""
    file = walking()
    other = Step(None, "museum", "hotel", ("alex",), seconds(15), None)
    sent = sent_for(file, Report(Answer.FEASIBLE, itinerary=(other,)))
    (step,) = sent["steps"]
    assert (step["option"], step["way"], step["name"]) == (None, None, None)
    assert holds(sent)


def test_each_step_names_the_records_of_the_file_that_are_about_it() -> None:
    """The FACTs about its OPTION or its WAY, and the LOCKs of its OPTION, in the FILE's order."""
    file = trip(
        ["alex", "sam"],
        ["museum", "hotel"],
        [stays("visit", "museum"), stays("lunch", "hotel")],
        [starts_at("visit", 14), lasts("visit", "PT1H"), takes("walk", "PT20M")],
        [
            {"id": "sam-visits", "lock": "visit", "persons": ["sam"]},
            {"id": "alex-visits", "lock": "visit", "persons": ["alex"]},
        ],
        ways=[way_between("walk", "museum", "hotel")],
    )
    plan = (
        Step("visit", "museum", "museum", ("alex", "sam"), seconds(14), seconds(15)),
        Step(None, "museum", "hotel", ("alex",), seconds(15), seconds(15, 20), way="walk"),
        Step(None, "hotel", "museum", ("alex",), seconds(16), None),
    )
    sent = sent_for(file, Report(Answer.FEASIBLE, itinerary=plan))
    assert [step["records"] for step in sent["steps"]] == [
        ["visit-time", "visit-length", "visit-open", "sam-visits", "alex-visits"],
        ["walk-length"],
        # A WAY that the FILE does not list has no record.
        [],
    ]
    assert holds(sent)
    # With no ITINERARY, the OPTIONs that a LOCK names say the same of themselves.
    (visit,) = sent_for(file, Report(Answer.INFEASIBLE))["steps"]
    assert visit["records"] == sent["steps"][0]["records"]


def test_a_step_that_can_take_longer_says_how_late_it_can_end() -> None:
    """The FILE gives the duration as a range. A plan ends the step after the least or the most."""

    def file_with(*about_the_walk: dict[str, Any]) -> File:
        return trip(
            ["alex"],
            ["museum", "hotel"],
            [stays("visit", "museum")],
            [starts_at("visit", 14), lasts_between("visit", "PT1H", "PT2H"), *about_the_walk],
            [],
            ways=[way_between("walk", "museum", "hotel")],
        )

    plan = (
        Step("visit", "museum", "museum", ("alex",), seconds(14), seconds(15)),
        Step(None, "museum", "hotel", ("alex",), seconds(15), seconds(15, 20), way="walk"),
    )
    both = file_with(takes_between("walk", "PT20M", "PT45M"))
    sent = sent_for(both, Report(Answer.FEASIBLE, itinerary=plan))
    assert [(clock(step["end"]), clock(step["latest"])) for step in sent["steps"]] == [
        ("2027-05-15T15:00:00", "2027-05-15T16:00:00"),
        ("2027-05-15T15:20:00", "2027-05-15T15:45:00"),
    ]
    assert holds(sent)
    # A plan that is sure to hold ends each step after the most it can take: none can end later.
    sure = (
        Step("visit", "museum", "museum", ("alex",), seconds(14), seconds(16)),
        Step(None, "museum", "hotel", ("alex",), seconds(16), seconds(16, 45), way="walk"),
    )
    sent = sent_for(both, Report(Answer.FEASIBLE, itinerary=sure))
    assert [step["latest"] for step in sent["steps"]] == [None, None]
    # A WAY that takes one length of time, or of which the FILE says nothing, can end no later.
    for file in (file_with(takes("walk", "PT20M")), file_with()):
        sent = sent_for(file, Report(Answer.FEASIBLE, itinerary=plan))
        assert [clock(step["latest"]) for step in sent["steps"]] == ["2027-05-15T16:00:00", None]
        assert holds(sent)


def wants_of(path: Path) -> list[dict[str, Any]]:
    wants: list[dict[str, Any]] = drawn(path)["wants"]
    return wants


def test_the_wants_of_the_file_are_sent_with_the_options_that_satisfy_each() -> None:
    """Alex must have deep-dish pizza. One dinner serves it, and two other OPTIONs do not."""
    path = EXAMPLES / "a-must" / "works.json"
    names = {each["id"]: each["name"] for each in json.loads(path.read_text())["options"]}
    said = {
        "dinner-pizzeria": (9, "pizzeria-serves-it"),
        "dinner-tavern": (0, "tavern-does-not-serve-it"),
        "blues-show": (0, "show-does-not-serve-it"),
    }
    assert wants_of(path) == [
        {
            "id": "deep-dish",
            "name": "deep-dish pizza",
            "musts": ["alex"],
            "must_nots": [],
            "ends_at": None,
            # The FILE does not say that these are all the OPTIONs that SATISFY it.
            "complete": None,
            # Each OPTION that a FACT says SATISFIES the WANT or does not, in the FILE's order
            # of OPTIONs, with its DEGREE OF SATISFACTION and the FACT that states it.
            "options": [
                {"option": id, "name": names[id], "degree": said[id][0], "record": said[id][1]}
                for id in names
                if id in said
            ],
        }
    ]
    assert len(wants_of(path)[0]["options"]) == 3


def test_a_want_says_for_whom_it_is_a_must_not_and_whether_its_options_are_all_stated() -> None:
    # Alex must have a view from high up, and Jo must not.
    (view,) = wants_of(EXAMPLES / "a-must-not" / "works.json")
    assert (view["musts"], view["must_nots"]) == (["alex"], ["jo"])
    assert [(each["option"], each["degree"]) for each in view["options"]] == [
        ("skydeck", 9),
        ("lunch", 0),
    ]
    # A FACT says that the FILE states every OPTION that SATISFIES the WANT.
    (pizza,) = wants_of(EXAMPLES / "a-must" / "cannot-work.json")
    assert pizza["complete"] == "every-deep-dish-place"
    assert [each["option"] for each in pizza["options"]] == ["dinner-pizzeria"]


def test_where_each_person_starts_from_is_sent_as_far_as_the_file_says() -> None:
    """Alex and Sam start from the hotel."""
    sent = drawn(EXAMPLES / "ending-in-denver" / "works.json")
    assert sent["starts_from"] == [
        {"person": "alex", "place": "hotel", "record": "alex-start"},
        {"person": "sam", "place": "hotel", "record": "sam-start"},
    ]
    # A FILE that does not say where anybody starts from has no such FACT to send.
    assert drawn(EXAMPLES / "flight-home" / "works.json")["starts_from"] == []
    # The FACTs come in the FILE's order of PERSONs, whatever their order among the FACTs.
    file = trip(
        ["alex", "sam", "jo"],
        ["hotel", "pier"],
        [],
        [
            {"id": "jo-start", "person": "jo", "starts_from": "pier"},
            {"id": "alex-start", "person": "alex", "starts_from": "hotel"},
        ],
        [],
    )
    sent = sent_for(file, Report(Answer.UNDETERMINED))
    assert [(fact["person"], fact["place"]) for fact in sent["starts_from"]] == [
        ("alex", "hotel"),
        ("jo", "pier"),
    ]


def test_every_way_of_the_file_is_sent_with_what_the_file_says_of_it() -> None:
    """A walk between the tower and the park, in both directions, that takes 20 minutes."""
    sent = drawn(EXAMPLES / "a-must-not" / "works.json")
    assert sent["ways"] == [
        {
            "id": "walk-from-tower",
            "name": "the walk between Willis Tower and Millennium Park",
            "from": "willis-tower",
            "to": "park",
            "both_ways": True,
            "length": {"shortest": 20 * 60, "longest": 20 * 60, "contingent": False},
            # The FACTs of the FILE that are about it.
            "records": ["walk-from-tower-length"],
        }
    ]
    assert sent["complete_travel"] == []
    # A WAY in one direction only, one whose length the world decides, and one with no FACT.
    file = trip(
        ["alex"],
        ["hotel", "pier", "park"],
        [],
        [takes_between("ferry", "PT20M", "PT40M")],
        [],
        ways=[
            {"id": "ferry", "name": "ferry", "from": "hotel", "to": "pier"},
            way_between("path", "pier", "park"),
        ],
    )
    ferry, path = sent_for(file, Report(Answer.UNDETERMINED))["ways"]
    assert (ferry["from"], ferry["to"], ferry["both_ways"]) == ("hotel", "pier", False)
    assert ferry["length"] == {"shortest": 20 * 60, "longest": 40 * 60, "contingent": True}
    assert (path["both_ways"], path["length"], path["records"]) == (True, None, [])


def test_each_fact_that_the_file_lists_every_way_of_some_travel_is_sent() -> None:
    """The FILE lists every way straight to Denver that leaves on the afternoon of the TRIP."""
    sent = drawn(EXAMPLES / "ending-in-denver" / "cannot-work.json")
    assert sent["complete_travel"] == [
        {
            "record": "every-way-to-denver",
            # The FACT leaves the first PLACE out: it stands for every PLACE.
            "from": None,
            "to": "denver",
            "earliest": time("2027-05-15T12:00:00"),
            "latest": time("2027-05-15T19:30:00"),
        }
    ]
    # A FACT that leaves both PLACEs out is about travel between any two.
    (in_full,) = drawn(EXAMPLES / "a-day" / "cannot-work.json")["complete_travel"]
    assert (in_full["record"], in_full["from"], in_full["to"]) == ("all-ways", None, None)
    assert (in_full["earliest"], in_full["latest"]) == (
        time("2027-05-14T00:00:00"),
        time("2027-05-14T23:59:00"),
    )


def test_the_rights_to_each_option_are_sent_as_far_as_the_file_says() -> None:
    """Alex has a BOOKING for the Skydeck, and two places are still on OFFER at 32.00 USD."""
    skydeck, talk, lunch = drawn(EXAMPLES / "a-ticket" / "not-bought-yet.json")["rights"]
    assert skydeck == {
        "option": "skydeck",
        "name": "Skydeck visit",
        "needs": {"needed": True, "record": "skydeck-needs-a-ticket"},
        "bookings": [
            {
                "id": "alex-skydeck-ticket",
                "covers": ["alex"],
                # The OBJECTs it covers: none.
                "objects": [],
                # The name to show for each PERSON and OBJECT that it covers.
                "names": {"alex": "Alex"},
                # What the BOOKING paid, from which BUDGET, and who paid.
                "paid": {
                    "amount": "32.00",
                    "currency": "USD",
                    "budget": "trip-money",
                    "by": "alex",
                },
                # Its terms for cancelling and for changing: it states none.
                "terms": {"cancelling": [], "changing": []},
            }
        ],
        "offers": [
            {
                "id": "skydeck-tickets",
                "places": 2,
                "price": {"amount": "32.00", "currency": "USD"},
                # The OBJECTs that its places are for: none, so they are for PERSONs.
                "objects": [],
                "names": {},
                # It states no time of expiry, and has not expired.
                "until": None,
                "expired": False,
            }
        ],
        # The FILE does not say that these are all the rights to the visit.
        "complete": None,
    }
    # Nobody needs a right to the talk or to lunch, and the FILE says no more of rights to them.
    for walk_up in (talk, lunch):
        assert walk_up["needs"]["needed"] is False
        assert (walk_up["bookings"], walk_up["offers"], walk_up["complete"]) == ([], [], None)
    # The visit is sold out: a FACT says that the FILE lists every right to it.
    (skydeck, *_) = drawn(EXAMPLES / "a-ticket" / "cannot-work.json")["rights"]
    assert skydeck["complete"] == {"record": "skydeck-sold-out", "offers": []}
    # An OFFER whose price nobody knows has none.
    (skydeck, *_) = drawn(EXAMPLES / "a-ticket" / "depends-on-the-price.json")["rights"]
    assert [offer["price"] for offer in skydeck["offers"]] == [None]
    # An OPTION of which the FILE says nothing about rights is not among them.
    file = trip(["alex"], ["pier"], [stays("swim", "pier")], [], [], rights=True)
    assert sent_for(file, Report(Answer.UNDETERMINED))["rights"] == []


def test_the_budgets_of_the_file_are_sent_with_their_caps() -> None:
    """The trip money is for Alex and Sam, and the TRIP spends at most 200.00 USD from it."""
    sent = drawn(EXAMPLES / "a-ticket" / "within-the-cap.json")
    assert sent["budgets"] == [
        {
            "id": "trip-money",
            "name": "the trip money",
            "persons": ["alex", "sam"],
            # The OBJECTs whose places it may pay for: none.
            "objects": [],
            # The name to show for each PERSON and OBJECT that it lists.
            "names": {"alex": "Alex", "sam": "Sam"},
            "currencies": ["USD"],
            "caps": [{"id": "trip-cap", "limit": {"amount": "200.00", "currency": "USD"}}],
        }
    ]
    # A BUDGET with no cap has none, and a FILE with no BUDGET is sent none.
    (money,) = drawn(EXAMPLES / "a-ticket" / "not-bought-yet.json")["budgets"]
    assert money["caps"] == []
    assert drawn(EXAMPLES / "flight-home" / "works.json")["budgets"] == []
    # A BOOKING that states no payment has none, and one can leave out the BUDGET and who paid.
    (skydeck, *_) = drawn(EXAMPLES / "a-ticket" / "depends-on-the-receipt.json")["rights"]
    assert [booking["paid"] for booking in skydeck["bookings"]] == [None]
    (skydeck, *_) = drawn(EXAMPLES / "a-ticket" / "works.json")["rights"]
    assert skydeck["bookings"][0]["paid"] == {
        "amount": "32.00",
        "currency": "USD",
        "budget": None,
        "by": "alex",
    }


def test_the_objects_of_the_file_are_sent_with_what_the_file_says_of_each() -> None:
    """The bags are at the hotel. The flight requires them, and the hotel hands them over."""
    sent = drawn(EXAMPLES / "the-bags" / "they-collect-them.json")
    assert sent["objects"] == [
        {
            "id": "bags",
            "name": "the bags",
            # Where the OBJECT is when the TRIP starts: at a PLACE, and with no PERSON.
            "starts": {"person": None, "place": "hotel", "record": "where-the-bags-start"},
            "requires": [
                {
                    "option": "flight",
                    "name": "Flight home",
                    "needed": True,
                    "record": "flight-needs-the-bags",
                }
            ],
            "refuses": [],
            "requires_complete": "every-use-of-the-bags",
            "transfers": [
                {
                    "option": "collect-bags",
                    "name": "Collect the bags",
                    "does": "hands_over",
                    "record": "hotel-releases-the-bags",
                }
            ],
            "transfers_complete": "everything-that-moves-the-bags",
            # No FACT says of an OPTION whether it needs a right for the bags, and one FACT
            # says that the FILE states every OPTION that does.
            "rights": [],
            "rights_complete": "every-ticket-for-the-bags",
            # No FACT says that the FILE lists every right to an OPTION that covers the bags.
            "rights_closed": [],
        }
    ]
    # The car ferry needs a right for the car, and the BOOKING covers Alex, Sam and the car.
    ferry = drawn(EXAMPLES / "a-car-ferry" / "booked.json")
    (car,) = ferry["objects"]
    assert car["rights"] == [
        {
            "option": "ferry",
            "name": "Car ferry to Muskegon",
            "needed": True,
            "record": "ferry-needs-a-car-ticket",
        }
    ]
    assert car["rights_complete"] == "every-ticket-for-the-car"
    assert car["rights_closed"] == []
    # A FACT says that the FILE lists every right to the ferry that covers the car.
    sold_out = drawn(EXAMPLES / "a-car-ferry" / "the-car-deck-is-sold-out.json")
    assert sold_out["objects"][0]["rights_closed"] == [
        {
            "option": "ferry",
            "name": "Car ferry to Muskegon",
            "record": "the-car-deck-is-full",
            "called": "the car",
            # The OFFERs that the FACT names: none.
            "offers": [],
        }
    ]
    # Three places on the car deck are on OFFER for the car, and the trip money pays for it.
    on_offer = drawn(EXAMPLES / "a-car-ferry" / "the-trip-money-is-three-dollars-short.json")
    (to_the_ferry, _) = on_offer["rights"]
    assert to_the_ferry["offers"] == [
        {
            "id": "car-deck",
            "places": 3,
            "price": {"amount": "90.00", "currency": "USD"},
            "objects": ["car"],
            "names": {"car": "the car"},
            "until": None,
            "expired": False,
        }
    ]
    assert on_offer["objects"][0]["rights_closed"][0]["offers"] == ["car-deck"]
    (money,) = on_offer["budgets"]
    assert (money["persons"], money["objects"]) == (["alex", "sam"], ["car"])
    assert money["names"] == {"alex": "Alex", "sam": "Sam", "car": "the car"}
    # A luggage service with no BOOKING has rights to show: it has no place for the bags.
    service = drawn(EXAMPLES / "the-bags" / "the-service-has-no-place-for-the-bags.json")
    assert "luggage-service" in [each["option"] for each in service["rights"]]
    (tickets,) = ferry["rights"][0]["bookings"]
    assert (tickets["covers"], tickets["objects"]) == (["alex", "sam"], ["car"])
    assert tickets["names"] == {"alex": "Alex", "sam": "Sam", "car": "the car"}
    # Alex has the bags when the TRIP starts, and the museum keeps them.
    (bags,) = drawn(EXAMPLES / "the-bags" / "the-museum-keeps-them.json")["objects"]
    assert bags["starts"] == {"person": "alex", "place": None, "record": "where-the-bags-start"}
    assert ("museum-visit", "keeps") in [
        (each["option"], each["does"]) for each in bags["transfers"]
    ]
    # The FILE does not say where the bags are when the TRIP starts.
    (bags,) = drawn(EXAMPLES / "the-bags" / "nobody-said-where-they-are.json")["objects"]
    assert bags["starts"] is None
    # A FILE with no OBJECT is sent none.
    assert drawn(EXAMPLES / "flight-home" / "works.json")["objects"] == []


def test_the_capabilities_of_the_file_are_sent_with_who_has_each_and_what_requires_it() -> None:
    """Two drives require driving a manual car of one PERSON. Sam has it, and the others do not."""
    sent = drawn(EXAMPLES / "a-driver" / "every-drive-is-stated.json")
    assert sent["capabilities"] == [
        {
            "id": "drive-manual",
            "name": "driving a manual car",
            # Each PERSON of whom a FACT says so, in the FILE's order of PERSONs.
            "has": [
                {"person": "alex", "has": False, "record": "alex-does-not-drive-manual"},
                {"person": "sam", "has": True, "record": "sam-drives-manual"},
                {"person": "jo", "has": False, "record": "jo-does-not-drive-manual"},
            ],
            # A FACT says that the FILE states every one of its OPTIONs that requires it.
            "complete": "every-drive-that-needs-a-driver",
            # Each OPTION of which a FACT says what it requires, in the FILE's order of OPTIONs.
            "options": [
                {
                    "option": "drive-out",
                    "name": "Drive to the dunes",
                    "of": "one",
                    "record": "drive-out-needs-a-driver",
                },
                {
                    "option": "drive-back",
                    "name": "Drive back to the hotel",
                    "of": "one",
                    "record": "drive-back-needs-a-driver",
                },
            ],
        }
    ]
    # The FILE says only of Jo whether they drive, and not that these are all the drives.
    (driving,) = drawn(EXAMPLES / "a-driver" / "depends-on-who-can-drive.json")["capabilities"]
    assert (driving["has"], driving["complete"]) == (
        [{"person": "jo", "has": False, "record": "jo-does-not-drive-manual"}],
        None,
    )
    # A FILE with no CAPABILITY is sent none.
    assert drawn(EXAMPLES / "flight-home" / "works.json")["capabilities"] == []


def test_a_capability_says_what_each_option_requires_of_it() -> None:
    """Of each PERSON who takes part, of one of them, or of none."""
    file = trip(
        ["alex", "sam"],
        ["pier"],
        [stays(each, "pier") for each in ("swim", "tour", "picnic", "walk")],
        [
            requires("picnic", "swimming", "none"),
            requires("tour", "swimming"),
            requires("swim", "swimming", "each"),
            can("sam", "swimming"),
        ],
        [],
        capabilities=["swimming", "rowing"],
    )
    swimming, rowing = sent_for(file, Report(Answer.UNDETERMINED))["capabilities"]
    assert [(each["option"], each["of"]) for each in swimming["options"]] == [
        ("swim", "each"),
        ("tour", "one"),
        ("picnic", "none"),
    ]
    assert swimming["has"] == [{"person": "sam", "has": True, "record": "sam-swimming"}]
    assert rowing == {"id": "rowing", "name": "rowing", "has": [], "complete": None, "options": []}


def test_a_want_about_where_the_trip_ends_names_the_place() -> None:
    """Alex and Sam must end the TRIP in Denver. No OPTION delivers such a WANT."""
    (ending,) = wants_of(EXAMPLES / "ending-in-denver" / "works.json")
    assert ending == {
        "id": "ending-in-denver",
        "name": "ending the trip in Denver",
        "musts": ["alex", "sam"],
        "must_nots": [],
        "ends_at": "denver",
        "complete": None,
        "options": [],
    }


def test_names_are_sent_as_the_report_shows_them() -> None:
    """Two PERSONs are called Alex, and two OPTIONs are called Skydeck visit.

    The report shows the id with a name that another record of its kind has, so that a reader
    can tell them apart. It puts a name in quotes where it could be taken for something else.
    The page is sent each name as the report shows it.
    """
    content = json.loads((EXAMPLES / "a-must-not" / "works.json").read_text())
    by_id = {each["id"]: each for kind in ("persons", "options", "wants") for each in content[kind]}
    by_id["jo"]["name"] = "Alex"
    by_id["lunch"]["name"] = "Skydeck visit"
    by_id["sam"]["name"] = "Tom and Jerry"
    by_id["view"]["name"] = "a view, from high up"
    file = parse(json.dumps(content))
    found = compiler.check(file)
    assert found.answer is Answer.FEASIBLE
    sent = sent_for(file, found)
    assert [each["name"] for each in sent["persons"]] == [
        "Alex (alex)",
        '"Tom and Jerry"',
        "Alex (jo)",
    ]
    assert [step["name"] for step in sent["steps"] if step["option"]] == [
        "Skydeck visit (skydeck)",
        "Skydeck visit (lunch)",
    ]
    (view,) = sent["wants"]
    assert view["name"] == '"a view, from high up"'
    assert [each["name"] for each in view["options"]] == [
        "Skydeck visit (skydeck)",
        "Skydeck visit (lunch)",
    ]
    # These are the report's own names: each is in the report in words.
    words = reports.as_text(file, found)
    shown = [each["name"] for each in sent["persons"]] + [view["name"]]
    shown += [each["name"] for each in view["options"]]
    for name in shown:
        assert name in words, name
    assert holds(sent)
    # A name that ends like a name with its id is in quotes, so it is not taken for one.
    by_id["sam"]["name"] = "Alex (jo)"
    file = parse(json.dumps(content))
    found = compiler.check(file)
    sent = sent_for(file, found)
    assert [each["name"] for each in sent["persons"]] == [
        "Alex (alex)",
        '"Alex (jo)"',
        "Alex (jo)",
    ]
    words = reports.as_text(file, found)
    for each in sent["persons"]:
        assert each["name"] in words, each["name"]
    # A name that the report uses for no name is in quotes too: a PERSON called nobody.
    by_id["sam"]["name"] = "nobody"
    file = parse(json.dumps(content))
    found = compiler.check(file)
    sent = sent_for(file, found)
    assert [each["name"] for each in sent["persons"]] == ["Alex (alex)", '"nobody"', "Alex (jo)"]
    words = reports.as_text(file, found)
    for each in sent["persons"]:
        assert each["name"] in words, each["name"]
    # The page has such a word of its own, for a step with nobody in it. And a name counts
    # as the page shows it: a soft hyphen in it changes nothing.
    for name in ("nobody of the TRIP", "no\u00adbody"):
        by_id["sam"]["name"] = name
        sent = sent_for(parse(json.dumps(content)), found)
        assert sent["persons"][1]["name"] == f'"{name}"'


def test_a_file_with_no_report_is_sent_as_the_file_alone_gives_it() -> None:
    """Before the COMPILER has reported, a page can draw what the FILE holds."""
    no_plan = Report(Answer.INFEASIBLE)
    for name in ("works", "works-but-risky", "cannot-work", "depends-on-the-cab"):
        file = read(STORY / f"{name}.json")
        found = compiler.check(file)
        first, with_it = shown(file), shown(file, found)
        assert first is not None and with_it is not None
        # It says that it has no report, and it is a TRIP that a page can draw.
        assert first["itinerary"] is None, name
        assert holds(first), name
        # Its steps are the OPTIONs that a LOCK names, as for a report that shows no ITINERARY.
        assert first == {**cast("Trip", shown(file, no_plan)), "itinerary": None}, name
        # What the FILE holds is the same with the report and without it.
        for part in (
            "zone",
            "persons",
            "places",
            "starts_from",
            "wants",
            "options",
            "ways",
            "complete_travel",
            "rights",
            "budgets",
            "capabilities",
            "objects",
        ):
            assert first[part] == with_it[part], (name, part)
        if found.answer is not Answer.FEASIBLE:
            assert first == {**with_it, "itinerary": None}, name


def test_names_that_look_the_same_on_a_page_come_with_their_ids() -> None:
    """Two PERSONs are called Joséphine, spelled with two different sets of characters.

    One has the letter with its accent as one character, the other has the letter and then
    the accent. A page shows the two alike. So it does two names that differ only in how many
    spaces they hold: a page shows a run of spaces as one. Each of these comes with its id,
    in the spelling of the FILE.
    """
    content = json.loads((EXAMPLES / "a-must-not" / "works.json").read_text())
    by_id = {each["id"]: each for kind in ("persons", "options") for each in content[kind]}
    one, other = "Jos\u00e9phine", "Jose\u0301phine"
    assert one != other
    by_id["alex"]["name"], by_id["jo"]["name"] = one, other
    by_id["skydeck"]["name"], by_id["lunch"]["name"] = "Anne Marie", "Anne  Marie"
    file = parse(json.dumps(content))
    sent = sent_for(file, compiler.check(file))
    assert [each["name"] for each in sent["persons"]] == [f"{one} (alex)", "Sam", f"{other} (jo)"]
    assert [step["name"] for step in sent["steps"] if step["option"]] == [
        "Anne Marie (skydeck)",
        "Anne  Marie (lunch)",
    ]
    assert holds(sent)
    # So do two names that differ only in a character that a page shows nothing for: a soft
    # hyphen, or a space of no width.
    by_id["alex"]["name"], by_id["jo"]["name"] = "Member\u00adship", "Membership"
    by_id["skydeck"]["name"], by_id["lunch"]["name"] = "Anne\u200bMarie", "AnneMarie"
    file = parse(json.dumps(content))
    sent = sent_for(file, compiler.check(file))
    assert [each["name"] for each in sent["persons"]] == [
        "Member\u00adship (alex)",
        "Sam",
        "Membership (jo)",
    ]
    assert [step["name"] for step in sent["steps"] if step["option"]] == [
        "Anne\u200bMarie (skydeck)",
        "AnneMarie (lunch)",
    ]
    # Or in a character that only says how the sign before it is drawn, or that joins two
    # others: a page shows nothing for it.
    by_id["alex"]["name"], by_id["jo"]["name"] = (
        "Central Caf\u00e9 \u2615",
        "Central Caf\u00e9 \u2615\ufe0f",
    )
    by_id["skydeck"]["name"], by_id["lunch"]["name"] = "Anne\u034fMarie", "AnneMarie"
    file = parse(json.dumps(content))
    sent = sent_for(file, compiler.check(file))
    assert [each["name"] for each in sent["persons"]] == [
        "Central Caf\u00e9 \u2615 (alex)",
        "Sam",
        "Central Caf\u00e9 \u2615\ufe0f (jo)",
    ]
    assert [step["name"] for step in sent["steps"] if step["option"]] == [
        "Anne\u034fMarie (skydeck)",
        "AnneMarie (lunch)",
    ]
    # Or in how a character is set: a hyphen that does not break, two letters drawn as one
    # sign, a space that does not break.
    by_id["alex"]["name"], by_id["jo"]["name"] = "Saint-Malo", "Saint\u2011Malo"
    by_id["skydeck"]["name"], by_id["lunch"]["name"] = "Sheffield tour", "Shef\ufb01eld\u00a0tour"
    file = parse(json.dumps(content))
    sent = sent_for(file, compiler.check(file))
    assert [each["name"] for each in sent["persons"]] == [
        "Saint-Malo (alex)",
        "Sam",
        "Saint\u2011Malo (jo)",
    ]
    assert [step["name"] for step in sent["steps"] if step["option"]] == [
        "Sheffield tour (skydeck)",
        "Shef\ufb01eld\u00a0tour (lunch)",
    ]
    # A name that only differs in its capitals looks different, and comes as it is.
    by_id["skydeck"]["name"], by_id["lunch"]["name"] = "Skydeck visit", "Lunch in the park"
    by_id["alex"]["name"], by_id["jo"]["name"] = "Alex", "alex"
    file = parse(json.dumps(content))
    sent = sent_for(file, compiler.check(file))
    assert [each["name"] for each in sent["persons"]] == ["Alex", "Sam", "alex"]


def test_what_a_page_shows_nothing_for_is_what_unicode_calls_default_ignorable() -> None:
    """The view and the page tell the same characters, and a browser knows which they are."""
    node = shutil.which("node")
    if node is None:
        if os.environ.get("CI"):
            pytest.fail("the tests of the view need Node")
        pytest.skip("needs Node")
    listing = """
    const found = [];
    for (let point = 0; point <= 0x10ffff; point += 1) {
      if (point >= 0xd800 && point <= 0xdfff) continue;
      if (/\\p{Default_Ignorable_Code_Point}/u.test(String.fromCodePoint(point))) found.push(point);
    }
    process.stdout.write(JSON.stringify(found));
    """
    done = subprocess.run([node, "--eval", listing], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    ignorable = set(json.loads(done.stdout))
    assert len(ignorable) > 4000
    # Between two letters, exactly these characters and the format characters leave no trace.
    unseen = {point for point in range(0x110000) if seen_as(f"a{chr(point)}b") == "ab"}
    formats = {point for point in range(0x110000) if unicodedata.category(chr(point)) == "Cf"}
    assert unseen == ignorable | formats
    # A sign that a page shows stays: a letter, an accent, a hyphen, a coffee cup.
    for sign in ("a", "\u00e9", "-", "\u2615", "\u0301", "'"):
        assert seen_as(f"a{sign}b") == unicodedata.normalize("NFC", f"a{sign}b"), sign
    # Each accent is joined to its letter, and each run of spaces is one space.
    assert seen_as("  Jose\u0301   Luis ") == "Jos\u00e9 Luis"
    # A character that is another one set in another way is that one: two letters drawn as
    # one sign, a wide letter, a hyphen that does not break.
    assert seen_as("Shef\ufb01eld") == "Sheffield"
    assert seen_as("\uff21irport") == "Airport"
    assert seen_as("Saint\u2011Malo") == seen_as("Saint\u2010Malo") == "Saint-Malo"
    # A dash is no hyphen, and a letter of another alphabet is another letter.
    assert seen_as("Saint\u2013Malo") != "Saint-Malo"
    assert seen_as("P\u0430ris") != "Paris"


def test_every_option_of_the_file_is_sent_with_what_the_file_says_of_it() -> None:
    """A visit, a train, a flight and a cab. No LOCK names the train or the cab."""
    sent = drawn(STORY / "depends-on-the-cab.json")
    visit, train, flight, cab = sent["options"]
    assert visit == {
        "id": "museum-visit",
        "name": "Museum visit",
        "from": "art-institute",
        "to": "art-institute",
        "start": time("2027-05-15T14:30:00"),
        "any_time": False,
        "length": {"shortest": HOUR, "longest": HOUR, "contingent": False},
        "margin": None,
        "locked": ["alex", "sam"],
        # The FACTs and DECISIONs of the FILE that are about it, in the FILE's order.
        "records": [
            "visit-time",
            "visit-length",
            "visit-needs-a-ticket",
            "museum-tickets",
            "lock-visit",
        ],
    }
    # The train can start at any time. The FILE says so, and that is not a time.
    assert (train["start"], train["any_time"], train["locked"]) == (None, True, [])
    assert (train["from"], train["to"]) == ("art-institute", "ohare")
    # People must be at the airport 45 minutes before the flight.
    assert (flight["margin"], flight["length"]) == (
        45 * 60,
        {"shortest": 9000, "longest": 9000, "contingent": False},
    )
    # The FILE does not say how long the cab takes.
    assert (cab["name"], cab["any_time"], cab["length"], cab["locked"]) == (
        "Cab to O'Hare",
        True,
        None,
        [],
    )
    assert cab["records"] == ["cab-time", "cab-is-walk-up"]


def test_an_option_with_no_word_about_its_start_has_none() -> None:
    sent = sent_for(locked_only(), Report(Answer.UNDETERMINED))
    by_id = {option["id"]: option for option in sent["options"]}
    assert len(by_id) == 7
    # The FILE says nothing of when this one starts, and of this one that it can start any time.
    assert (by_id["no-word"]["start"], by_id["no-word"]["any_time"]) == (None, False)
    assert (by_id["some-time"]["start"], by_id["some-time"]["any_time"]) == (None, True)
    # A length that the FILE gives as a range: the world decides in it.
    assert by_id["ride"]["length"] == {
        "shortest": 20 * 60,
        "longest": 50 * 60,
        "contingent": True,
    }
    # Several LOCKs name the visit. Each PERSON they name is there once, in the FILE's order.
    assert by_id["visit"]["locked"] == ["alex", "jo"]
    assert by_id["open"]["locked"] == []


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
            "locked": both,
            "start": time("2027-05-15T14:30:00"),
            "end": time("2027-05-15T15:30:00"),
            "latest": None,
            "parts": [part(0, 14 * HOUR + 1800, 15 * HOUR + 1800)],
            "records": [
                "visit-time",
                "visit-length",
                "visit-needs-a-ticket",
                "museum-tickets",
                "lock-visit",
            ],
        },
        {
            "option": "flight",
            "way": None,
            "name": "Flight home",
            "from": "ohare",
            "to": "home",
            "persons": both,
            "locked": both,
            "start": time("2027-05-15T17:00:00"),
            "end": time("2027-05-15T19:30:00"),
            "latest": None,
            "parts": [part(0, 17 * HOUR, 19 * HOUR + 1800)],
            "records": [
                "flight-time",
                "flight-length",
                "bag-drop",
                "flight-needs-a-ticket",
                "flight-tickets",
                "lock-flight",
            ],
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
    told = [
        (
            step["option"],
            step["persons"],
            clock(step["start"]),
            clock(step["end"]),
            clock(step["latest"]),
        )
        for step in sent["steps"]
    ]
    assert told == [
        ("lunch", ["alex", "sam"], "2027-05-15T12:00:00", "2027-05-15T13:00:00", None),
        # Several LOCKs name the visit. Each PERSON they name takes part once, in the FILE's order.
        ("visit", ["alex", "jo"], "2027-05-15T14:00:00", "2027-05-15T15:00:00", None),
        # The ride takes between 20 and 50 minutes. As in an ITINERARY, it ends after the least,
        # and it says how late it can end.
        ("ride", ["sam"], "2027-05-15T14:00:00", "2027-05-15T14:20:00", "2027-05-15T14:50:00"),
        # The FILE does not say how long dinner takes.
        ("dinner", ["alex", "sam", "jo"], "2027-05-15T19:00:00", None, None),
        # No time: one can start at any time, and the FILE says nothing of the other.
        ("some-time", ["alex"], None, None, None),
        ("no-word", ["jo"], None, None, None),
    ]
    for step in sent["steps"]:
        assert step["locked"] == step["persons"]
        assert step["way"] is None
    # A step with no time is on no day.
    assert [step["parts"] for step in sent["steps"][-2:]] == [[], []]
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
    # Chicago's clocks are at one offset from UTC all that day, so no time needs its offset.
    assert (step["start"], step["end"]) == (
        time("2027-05-15T20:00:00"),
        time("2027-05-15T20:30:00"),
    )
    assert step["parts"] == [part(0, 20 * HOUR, 20 * HOUR + 1800)]


def around_a_change(*locked: str) -> File:
    """A dinner before Chicago's clocks go back, and a brunch after. LOCKs name some of them."""

    def when(option: str, written: str) -> dict[str, Any]:
        return {"id": f"{option}-time", "option": option, "starts_at": written}

    return trip(
        ["alex"],
        ["hotel"],
        [stays("dinner", "hotel"), stays("brunch", "hotel")],
        [
            when("dinner", "2027-11-06T19:00:00-05:00[America/Chicago]"),
            lasts("dinner", "PT1H"),
            when("brunch", "2027-11-07T10:00:00-06:00[America/Chicago]"),
            lasts("brunch", "PT1H"),
        ],
        [lock(option, "alex") for option in locked],
    )


def test_a_time_gives_its_offset_where_the_report_gives_offsets() -> None:
    """A dinner before Chicago's clocks go back, and a FACT about WAYs that covers the day after.

    The times of the dinner are at one offset from UTC, and the FACT has a time at another. A
    report that names the FACT gives each time with its offset, and the view does the same.
    """
    span = {
        "earliest": f"2027-11-06T12:00:00-05:00{CHICAGO}",
        "latest": f"2027-11-07T12:00:00-06:00{CHICAGO}",
    }
    dinner: list[dict[str, Any]] = [
        {
            "id": "dinner-time",
            "option": "dinner",
            "starts_at": f"2027-11-06T19:00:00-05:00{CHICAGO}",
        },
        lasts("dinner", "PT1H"),
    ]
    every_way = {"id": "every-way", "complete": {"to": "pier", "leaving": span}}

    def with_these(facts: list[dict[str, Any]]) -> File:
        return trip(
            ["alex"], ["hotel", "pier"], [stays("dinner", "hotel")], facts, [lock("dinner", "alex")]
        )

    file = with_these([*dinner, every_way])
    found = Report(Answer.INFEASIBLE, conflict=("every-way",))
    assert reports.clock_for(file, found).offsets
    assert "(UTC-6)" in reports.as_text(file, found)
    (step,) = sent_for(file, found)["steps"]
    assert (step["start"], step["end"]) == (
        time("2027-11-06T19:00:00", "UTC-5"),
        time("2027-11-06T20:00:00", "UTC-5"),
    )
    # The view sends the span of the FACT whatever the report names. So the times that it sends
    # are not all at one offset, and each gives its own.
    quiet = Report(Answer.UNDETERMINED)
    assert not reports.clock_for(file, quiet).offsets
    sent = sent_for(file, quiet)
    (in_full,) = sent["complete_travel"]
    assert (in_full["earliest"], in_full["latest"]) == (
        time("2027-11-06T12:00:00", "UTC-5"),
        time("2027-11-07T12:00:00", "UTC-6"),
    )
    assert sent["steps"][0]["start"] == time("2027-11-06T19:00:00", "UTC-5")
    # Without the FACT, the times sent are all at one offset. A report that names no time
    # gives no offset, and then none of them has one.
    sent = sent_for(with_these(dinner), quiet)
    (step,) = sent["steps"]
    assert (step["start"], step["end"]) == (
        time("2027-11-06T19:00:00"),
        time("2027-11-06T20:00:00"),
    )
    assert sent["options"][0]["start"] == time("2027-11-06T19:00:00")


def test_times_at_two_offsets_each_give_theirs_whatever_the_report_names() -> None:
    """The time of an OPTION that no LOCK names is sent too, and counts."""
    sent = sent_for(around_a_change("dinner"), Report(Answer.UNDETERMINED))
    (dinner,) = sent["steps"]
    assert dinner["start"] == time("2027-11-06T19:00:00", "UTC-5")
    assert [option["start"] for option in sent["options"]] == [
        time("2027-11-06T19:00:00", "UTC-5"),
        time("2027-11-07T10:00:00", "UTC-6"),
    ]
    file = around_a_change("dinner", "brunch")
    quiet = Report(Answer.UNDETERMINED)
    assert not reports.clock_for(file, quiet).offsets
    dinner, brunch = sent_for(file, quiet)["steps"]
    assert (dinner["start"], brunch["start"]) == (
        time("2027-11-06T19:00:00", "UTC-5"),
        time("2027-11-07T10:00:00", "UTC-6"),
    )


def test_a_time_that_the_clocks_show_twice_gives_its_offset() -> None:
    """Chicago's clocks show 1:30 am twice on 7 November 2027, an hour apart.

    Only the offset says which of the two a departure is. So the view sends it, though this is
    the one time it sends and the report names none.
    """

    def leaving_at(offset: str) -> Trip:
        when = {
            "id": "bus-time",
            "option": "bus",
            "starts_at": f"2027-11-07T01:30:00{offset}{CHICAGO}",
        }
        file = trip(["alex"], ["hotel"], [stays("bus", "hotel")], [when], [])
        quiet = Report(Answer.UNDETERMINED)
        assert not reports.clock_for(file, quiet).offsets
        sent = sent_for(file, quiet)
        assert holds(sent)
        return sent["options"][0]["start"]

    assert leaving_at("-05:00") == time("2027-11-07T01:30:00", "UTC-5")
    assert leaving_at("-06:00") == time("2027-11-07T01:30:00", "UTC-6")
    # An hour later the clocks show each time once, and one time alone gives no offset.
    when = {"id": "bus-time", "option": "bus", "starts_at": f"2027-11-07T02:30:00-06:00{CHICAGO}"}
    file = trip(["alex"], ["hotel"], [stays("bus", "hotel")], [when], [])
    sent = sent_for(file, Report(Answer.UNDETERMINED))
    assert sent["options"][0]["start"] == time("2027-11-07T02:30:00")


def test_an_offset_is_written_as_the_report_writes_it() -> None:
    """India's clocks are five and a half hours ahead of UTC, and Nepal's change in 1986."""
    when = {
        "id": "stay-time",
        "option": "stay",
        "starts_at": "1985-12-31T23:00:00+05:30[Asia/Kathmandu]",
    }
    file = trip(["alex"], ["hotel"], [stays("stay", "hotel")], [when, lasts("stay", "PT2H")], [])
    start = instant(when["starts_at"])
    plan = (Step("stay", "hotel", "hotel", ("alex",), start, start + 2 * HOUR),)
    found = Report(Answer.FEASIBLE, itinerary=plan)
    (step,) = sent_for(file, found)["steps"]
    written = reports.as_text(file, found)
    for sent in (step["start"], step["end"]):
        assert f"({sent['offset']})" in written
    assert (step["start"]["offset"], step["end"]["offset"]) == ("UTC+5:30", "UTC+5:45")


def alone(*stays_of_alex: tuple[str, int | None]) -> Trip:
    """What is sent of Alex's stays, in a plan: each from a time, for so many seconds.

    The first stay's time is the first in the FILE, so its time zone is the one of the report.
    """
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


def test_a_step_that_runs_past_midnight_has_a_part_on_each_day() -> None:
    sent = alone((at(23, 30, day=14), 8 * HOUR))
    assert sent["days"] == [day("2027-05-14"), day("2027-05-15")]
    (night,) = sent["steps"]
    assert (night["start"], night["end"]) == (
        time("2027-05-14T23:30:00"),
        time("2027-05-15T07:30:00"),
    )
    # The first part runs to the end of its day: 24 hours. The second starts as its day does.
    assert night["parts"] == [
        part(0, 23 * HOUR + 1800, 24 * HOUR, ends=False),
        part(1, 0, 7 * HOUR + 1800, begins=False),
    ]
    assert holds(sent)


def test_a_step_that_ends_as_a_day_starts_does_not_reach_that_day() -> None:
    sent = alone((at(22, day=14), 2 * HOUR))
    assert dates(sent) == ["2027-05-14"]
    assert clock(sent["steps"][0]["end"]) == "2027-05-15T00:00:00"
    assert sent["steps"][0]["parts"] == [part(0, 22 * HOUR, 24 * HOUR)]


def test_a_step_with_no_known_end_is_on_the_day_it_starts_on() -> None:
    """Whatever the page draws for it, the step itself reaches no later day."""
    sent = alone((at(23, 55), None))
    assert dates(sent) == ["2027-05-15"]
    assert sent["steps"][0]["parts"] == [part(0, 23 * HOUR + 3300, 23 * HOUR + 3300, ends=False)]


def test_a_step_with_no_length_is_on_one_day_only() -> None:
    """Its day is the one that holds its moment, however many days the TRIP has after it."""
    file = trip(
        ["alex"],
        ["pier"],
        [stays("signal", "pier"), stays("wait", "pier"), stays("stay", "pier")],
        [starts_at("signal", 9)],
        [],
    )
    whole = 24 * HOUR
    plan = (
        Step("signal", "pier", "pier", ("alex",), seconds(9), seconds(9)),
        Step("wait", "pier", "pier", ("alex",), seconds(10), None),
        # A stay that starts as a day starts, and one with no length at that same moment.
        Step("stay", "pier", "pier", ("alex",), seconds(0) + whole, seconds(1) + 3 * whole),
        Step("signal", "pier", "pier", ("alex",), seconds(0) + 2 * whole, seconds(0) + 2 * whole),
    )
    sent = sent_for(file, Report(Answer.FEASIBLE, itinerary=plan))
    assert len(sent["days"]) == 4
    assert [step["parts"] for step in sent["steps"]] == [
        [part(0, 9 * HOUR, 9 * HOUR)],
        [part(0, 10 * HOUR, 10 * HOUR, ends=False)],
        [
            part(1, 0, whole, ends=False),
            part(2, 0, whole, False, False),
            part(3, 0, HOUR, begins=False),
        ],
        [part(2, 0, 0)],
    ]
    assert holds(sent)


def test_a_day_on_which_the_clocks_go_forward_is_two_stretches() -> None:
    """In Chicago the clocks go from 2:00 am to 3:00 am on 14 March 2027."""
    sent = alone(("2027-03-13T23:00:00-06:00[America/Chicago]", 7 * HOUR))
    # The Sunday is sent as the two hours before the change, and the 21 hours after it.
    assert sent["days"] == [
        day("2027-03-13"),
        day("2027-03-14", 0, 2 * HOUR, "UTC-6"),
        day("2027-03-14", 3 * HOUR, 24 * HOUR, "UTC-5"),
    ]
    (night,) = sent["steps"]
    # Seven hours after 11:00 pm, the clocks show 7:00 am. The times of this TRIP are not all at
    # one offset from UTC, so each comes with its own, as in the report.
    assert (night["start"], night["end"]) == (
        time("2027-03-13T23:00:00", "UTC-6"),
        time("2027-03-14T07:00:00", "UTC-5"),
    )
    assert night["parts"] == [
        part(0, 23 * HOUR, 24 * HOUR, ends=False),
        part(1, 0, 2 * HOUR, False, False),
        part(2, 3 * HOUR, 7 * HOUR, begins=False),
    ]
    # Every part is as long as it takes: one hour, two hours and four make seven.
    assert sum(each["to"] - each["from"] for each in night["parts"]) == 7 * HOUR
    assert holds(sent)


def test_two_moments_that_the_clocks_show_as_one_time_are_in_two_stretches() -> None:
    """In Chicago the clocks go back from 2:00 am to 1:00 am on 7 November 2027.

    So they show 1:10 am twice that night, an hour apart. A stay at the first is in the stretch
    before the change, and a stay at the second in the stretch after it.
    """
    first, second = "2027-11-07T01:10:00-05:00", "2027-11-07T01:10:00-06:00"
    sent = alone((f"{first}[America/Chicago]", 300), (f"{second}[America/Chicago]", 300))
    assert sent["days"] == [
        day("2027-11-07", 0, 2 * HOUR, "UTC-5"),
        day("2027-11-07", HOUR, 24 * HOUR, "UTC-6"),
    ]
    earlier, later = sent["steps"]
    assert (earlier["start"], later["start"]) == (
        time("2027-11-07T01:10:00", "UTC-5"),
        time("2027-11-07T01:10:00", "UTC-6"),
    )
    assert earlier["parts"] == [part(0, HOUR + 600, HOUR + 900)]
    assert later["parts"] == [part(1, HOUR + 600, HOUR + 900)]
    assert holds(sent)
    # A stay of 70 minutes from the first 1:05 am ends at the second 1:15 am. It has 55 minutes
    # before the change and 15 after it.
    (long,) = alone(("2027-11-07T01:05:00-05:00[America/Chicago]", 70 * 60))["steps"]
    assert (long["start"], long["end"]) == (
        time("2027-11-07T01:05:00", "UTC-5"),
        time("2027-11-07T01:15:00", "UTC-6"),
    )
    assert long["parts"] == [
        part(0, HOUR + 300, 2 * HOUR, ends=False),
        part(1, HOUR, HOUR + 900, begins=False),
    ]
    # A stay through the whole of that night ends at its time of day, as on any other night.
    night = alone(("2027-11-06T23:00:00-05:00[America/Chicago]", 9 * HOUR))
    assert dates(night) == ["2027-11-06", "2027-11-07", "2027-11-07"]
    assert clock(night["steps"][0]["end"]) == "2027-11-07T07:00:00"
    assert night["steps"][0]["parts"] == [
        part(0, 23 * HOUR, 24 * HOUR, ends=False),
        part(1, 0, 2 * HOUR, False, False),
        part(2, HOUR, 7 * HOUR, begins=False),
    ]
    assert holds(night)


def test_a_date_that_a_time_zone_left_out_is_no_day() -> None:
    """Samoa went from 29 December 2011 to 31 December: its clocks never showed the 30th."""
    sent = alone(("2011-12-29T23:00:00-10:00[Pacific/Apia]", 2 * HOUR))
    assert sent["zone"] == "Pacific/Apia"
    # The clocks change as the one day ends and the other starts, so each says its offset.
    assert sent["days"] == [
        day("2011-12-29", offset="UTC-10"),
        day("2011-12-31", offset="UTC+14"),
    ]
    (stay,) = sent["steps"]
    assert (stay["start"], stay["end"]) == (
        time("2011-12-29T23:00:00", "UTC-10"),
        time("2011-12-31T01:00:00", "UTC+14"),
    )
    assert stay["parts"] == [
        part(0, 23 * HOUR, 24 * HOUR, ends=False),
        part(1, 0, HOUR, begins=False),
    ]
    assert holds(sent)


def test_a_day_that_starts_late_starts_where_its_clocks_do() -> None:
    """In Beirut the clocks go from midnight to 1:00 am on 28 March 2027.

    That day has no first hour. A stay through that night is on it from 1:00 am.
    """
    sent = alone(("2027-03-27T23:00:00+02:00[Asia/Beirut]", 3 * HOUR))
    # The clocks change between the two days, so each says its offset from UTC.
    assert sent["days"] == [
        day("2027-03-27", offset="UTC+2"),
        day("2027-03-28", HOUR, 24 * HOUR, "UTC+3"),
    ]
    (stay,) = sent["steps"]
    assert (clock(stay["start"]), clock(stay["end"])) == (
        "2027-03-27T23:00:00",
        "2027-03-28T03:00:00",
    )
    assert stay["parts"] == [
        part(0, 23 * HOUR, 24 * HOUR, ends=False),
        part(1, HOUR, 3 * HOUR, begins=False),
    ]
    assert holds(sent)


def test_a_day_that_ends_late_has_its_last_hour_in_a_stretch_of_its_own() -> None:
    """In Beirut the clocks go back from midnight to 11:00 pm on 30 October 2027.

    That day has its last hour twice. A stay through that night is in both, and then on the
    next day.
    """
    sent = alone(("2027-10-30T22:00:00+03:00[Asia/Beirut]", 4 * HOUR))
    assert sent["days"] == [
        day("2027-10-30", 0, 24 * HOUR, "UTC+3"),
        day("2027-10-30", 23 * HOUR, 24 * HOUR, "UTC+2"),
        day("2027-10-31"),
    ]
    (stay,) = sent["steps"]
    assert (clock(stay["start"]), clock(stay["end"])) == (
        "2027-10-30T22:00:00",
        "2027-10-31T01:00:00",
    )
    assert stay["parts"] == [
        part(0, 22 * HOUR, 24 * HOUR, ends=False),
        part(1, 23 * HOUR, 24 * HOUR, False, False),
        part(2, 0, HOUR, begins=False),
    ]
    assert holds(sent)
    # A stretch says its offset because the clocks change at its end, whatever else is sent.
    # The clocks show 11:10 pm twice that night, so the time says which of the two it is.
    lone = alone(("2027-10-30T23:10:00+03:00[Asia/Beirut]", 300))
    assert lone["days"] == [day("2027-10-30", 0, 24 * HOUR, "UTC+3")]
    assert lone["steps"][0]["start"] == time("2027-10-30T23:10:00", "UTC+3")
    # Two hours before, the clocks show each time once: the stretch says its offset alone.
    early = alone(("2027-10-30T21:10:00+03:00[Asia/Beirut]", 300))
    assert early["days"] == [day("2027-10-30", 0, 24 * HOUR, "UTC+3")]
    assert early["steps"][0]["start"] == time("2027-10-30T21:10:00")
    # A stay of an hour from the first 11:10 pm ends, by the clock, where it started.
    (short,) = alone(("2027-10-30T23:10:00+03:00[Asia/Beirut]", HOUR))["steps"]
    assert (short["start"], short["end"]) == (
        time("2027-10-30T23:10:00", "UTC+3"),
        time("2027-10-30T23:10:00", "UTC+2"),
    )
    assert short["parts"] == [
        part(0, 23 * HOUR + 600, 24 * HOUR, ends=False),
        part(1, 23 * HOUR, 23 * HOUR + 600, begins=False),
    ]


def test_clocks_that_go_back_over_midnight_show_a_date_again() -> None:
    """In St. John's the clocks went back from 12:01 am on 1 November 2009 to 11:01 pm.

    So they showed the first minute of 1 November, then the last hour of 31 October again, and
    then 1 November. Each stay is on the date that the clocks showed when it happened.
    """
    sent = alone(
        ("2009-11-01T00:00:00-02:30[America/St_Johns]", 30),
        ("2009-10-31T23:05:00-03:30[America/St_Johns]", 60),
    )
    assert sent["days"] == [
        day("2009-11-01", 0, 60, "UTC-2:30"),
        day("2009-10-31", 23 * HOUR + 60, 24 * HOUR, "UTC-3:30"),
    ]
    first, then = sent["steps"]
    assert (first["start"], then["start"]) == (
        time("2009-11-01T00:00:00", "UTC-2:30"),
        time("2009-10-31T23:05:00", "UTC-3:30"),
    )
    assert first["parts"] == [part(0, 0, 30)]
    assert then["parts"] == [part(1, 23 * HOUR + 300, 23 * HOUR + 360)]
    assert holds(sent)
    # A stay from the evening before to the morning after is in all four stretches.
    night = alone(("2009-10-31T22:00:00-02:30[America/St_Johns]", 4 * HOUR))
    # The two stretches with the change between them say their offsets from UTC.
    assert night["days"] == [
        day("2009-10-31"),
        day("2009-11-01", 0, 60, "UTC-2:30"),
        day("2009-10-31", 23 * HOUR + 60, 24 * HOUR, "UTC-3:30"),
        day("2009-11-01"),
    ]
    assert [(each["from"], each["to"]) for each in night["steps"][0]["parts"]] == [
        (22 * HOUR, 24 * HOUR),
        (0, 60),
        (23 * HOUR + 60, 24 * HOUR),
        # Two hours, one minute and 59 minutes are gone: the last hour is left.
        (0, HOUR),
    ]
    assert holds(night)


def framed(starts: str | None, ends: str | None) -> Trip:
    """What is sent of a visit on Saturday at 2:00 pm, in a TRIP with these times for itself."""
    decisions = [lock("visit", "alex")]
    if starts is not None:
        decisions.append({"id": "trip-start", "trip_starts_at": starts})
    if ends is not None:
        decisions.append({"id": "trip-end", "trip_ends_at": ends})
    file = trip(
        ["alex"],
        ["museum"],
        [stays("visit", "museum")],
        [starts_at("visit", 14), lasts("visit", "PT1H")],
        decisions,
    )
    return sent_for(file, Report(Answer.UNDETERMINED))


def bound(written: str, on: int | None, second: int | None, record: str) -> Trip:
    """When a TRIP starts or ends, as a page is sent it, with the id of its DECISION."""
    return {"at": written, "offset": None, "day": on, "second": second, "record": record}


def test_the_days_run_from_when_the_trip_starts_to_when_it_ends() -> None:
    """The TRIP starts on Friday and ends on Monday, says the FILE. Its one step is on Saturday."""
    sent = framed(at(17, day=14), at(20, 30, day=17))
    assert dates(sent) == ["2027-05-14", "2027-05-15", "2027-05-16", "2027-05-17"]
    assert sent["starts"] == bound("2027-05-14T17:00:00", 0, 17 * HOUR, "trip-start")
    assert sent["ends"] == bound("2027-05-17T20:30:00", 3, 20 * HOUR + 1800, "trip-end")
    assert sent["steps"][0]["parts"] == [part(1, 14 * HOUR, 15 * HOUR)]
    assert holds(sent)
    # A TRIP that says only when it ends starts with its first step.
    sent = framed(None, at(9, day=16))
    assert dates(sent) == ["2027-05-15", "2027-05-16"]
    assert sent["starts"] is None


def test_a_trip_that_ends_as_a_day_starts_ends_on_the_day_before() -> None:
    sent = framed(at(0, day=15), at(0, day=17))
    assert dates(sent) == ["2027-05-15", "2027-05-16"]
    assert sent["starts"] == bound("2027-05-15T00:00:00", 0, 0, "trip-start")
    assert sent["ends"] == bound("2027-05-17T00:00:00", 1, 24 * HOUR, "trip-end")
    assert holds(sent)


def test_a_trip_that_takes_no_time_starts_and_ends_on_one_day() -> None:
    """It starts and ends at midnight. Both are at the start of that day, not the end of another."""
    file = trip(
        ["alex"],
        ["museum"],
        [],
        [],
        [
            {"id": "trip-start", "trip_starts_at": at(0, day=15)},
            {"id": "trip-end", "trip_ends_at": at(0, day=15)},
        ],
    )
    sent = sent_for(file, Report(Answer.FEASIBLE))
    assert dates(sent) == ["2027-05-15"]
    assert sent["starts"] == bound("2027-05-15T00:00:00", 0, 0, "trip-start")
    assert sent["ends"] == bound("2027-05-15T00:00:00", 0, 0, "trip-end")
    assert holds(sent)
    # So it is in the first second that can be written.
    first = {"id": "trip-end", "trip_ends_at": "0001-01-01T00:00:00+00:00[UTC]"}
    sent = sent_for(trip(["alex"], ["museum"], [], [], [first]), Report(Answer.FEASIBLE))
    assert dates(sent) == ["0001-01-01"]
    assert sent["ends"] == bound("0001-01-01T00:00:00", 0, 0, "trip-end")
    assert holds(sent)


def test_a_trip_that_takes_no_time_is_on_one_day_whatever_is_before_it() -> None:
    """The FILE says that the TRIP starts and ends at midnight, and LOCKs a visit the day before."""
    file = trip(
        ["alex"],
        ["museum"],
        [stays("visit", "museum")],
        [starts_at("visit", 14), lasts("visit", "PT1H")],
        [
            lock("visit", "alex"),
            {"id": "trip-start", "trip_starts_at": at(0, day=16)},
            {"id": "trip-end", "trip_ends_at": at(0, day=16)},
        ],
    )
    sent = sent_for(file, Report(Answer.INFEASIBLE))
    assert dates(sent) == ["2027-05-15", "2027-05-16"]
    assert sent["starts"] == bound("2027-05-16T00:00:00", 1, 0, "trip-start")
    assert sent["ends"] == bound("2027-05-16T00:00:00", 1, 0, "trip-end")
    assert holds(sent)


def test_the_first_day_that_can_be_written_is_a_whole_day() -> None:
    """In a zone five hours ahead of UTC, the first time that can be written is 5:00 am.

    No clock changes there. So that day is a day like any other, and says no offset.
    """
    first = {"id": "trip-start", "trip_starts_at": "0001-01-01T05:00:00+05:00[Etc/GMT-5]"}
    sent = sent_for(trip(["alex"], ["museum"], [], [], [first]), Report(Answer.FEASIBLE))
    assert sent["days"] == [day("0001-01-01")]
    assert sent["starts"] == bound("0001-01-01T05:00:00", 0, 5 * HOUR, "trip-start")
    assert holds(sent)
    last = {"id": "trip-end", "trip_ends_at": "9999-12-31T18:59:59-05:00[Etc/GMT+5]"}
    sent = sent_for(trip(["alex"], ["museum"], [], [], [last]), Report(Answer.FEASIBLE))
    assert sent["days"] == [day("9999-12-31")]
    assert sent["ends"] == bound("9999-12-31T18:59:59", 0, 19 * HOUR - 1, "trip-end")
    assert holds(sent)


def test_a_page_is_sent_two_months_at_most_and_is_told_where_the_trip_ends() -> None:
    assert MOST_DAYS == 62
    sent = framed(None, at(18, day=15).replace("2027-05", "2027-09"))
    assert len(sent["days"]) == 62
    assert (dates(sent)[0], dates(sent)[-1]) == ("2027-05-15", "2027-07-15")
    assert sent["until"] == "2027-09-15"
    assert sent["ends"] == bound("2027-09-15T18:00:00", None, None, "trip-end")
    assert holds(sent)
    # A step that goes on past the last day is sent as far as that day.
    sent = alone((at(10), 100 * 24 * HOUR))
    assert len(sent["days"]) == 62
    assert sent["until"] == "2027-08-23"
    parts = sent["steps"][0]["parts"]
    assert len(parts) == 62
    assert parts[0] == part(0, 10 * HOUR, 24 * HOUR, ends=False)
    assert parts[-1] == part(61, 0, 24 * HOUR, begins=False, ends=False)
    assert holds(sent)
    # A step that starts after the last day is sent with no part.
    late = alone((at(10), HOUR), (at(10).replace("2027-05", "2027-12"), HOUR))
    assert [len(step["parts"]) for step in late["steps"]] == [1, 0]
    assert holds(late)


def test_a_trip_with_a_time_that_cannot_be_written_cannot_be_drawn() -> None:
    """The page is told that there is nothing to draw, never a time that is not the TRIP's."""
    last = "9999-12-31T23:59:59+00:00[UTC]"
    when = {"id": "fireworks-time", "option": "fireworks", "starts_at": last}
    file = trip(
        ["alex"],
        ["pier"],
        [stays("fireworks", "pier")],
        [when, lasts("fireworks", "PT1S")],
        [lock("fireworks", "alex")],
    )
    assert shown(file, Report(Answer.INFEASIBLE)) is None
    assert shown(file, Report(Answer.UNDETERMINED)) is None
    # So it is before the COMPILER has reported.
    assert shown(file) is None
    begins = instant(last)
    step = Step("fireworks", "pier", "pier", ("alex",), begins, begins + 1)
    assert shown(file, Report(Answer.FEASIBLE, itinerary=(step,))) is None


def test_the_first_and_the_last_day_that_can_be_written_can_be_drawn() -> None:
    """The fireworks end in the last second of the year 9999."""
    sent = alone(("9999-12-31T22:00:00+00:00[UTC]", 2 * HOUR - 1))
    assert sent["days"] == [day("9999-12-31")]
    (fireworks,) = sent["steps"]
    assert clock(fireworks["end"]) == "9999-12-31T23:59:59"
    assert fireworks["parts"] == [part(0, 22 * HOUR, 24 * HOUR - 1)]
    assert holds(sent)
    first = alone(("0001-01-01T00:00:00+00:00[UTC]", HOUR))
    assert first["days"] == [day("0001-01-01")]
    assert holds(first)


def good() -> Trip:
    """A TRIP as a page is sent it: a WAY, an OPTION overnight, and the times of the TRIP."""
    file = trip(
        ["alex", "sam"],
        ["museum", "hotel"],
        [stays("night", "hotel")],
        [starts_at("night", 23), lasts_between("night", "PT8H", "PT9H")],
        [
            {"id": "trip-start", "trip_starts_at": at(9)},
            {"id": "trip-end", "trip_ends_at": at(12, day=16)},
        ],
        ways=[way_between("walk", "museum", "hotel")],
    )
    steps = (
        Step(None, "museum", "hotel", ("alex",), seconds(22), seconds(22, 20), way="walk"),
        Step("night", "hotel", "hotel", ("alex", "sam"), seconds(23), seconds(23) + 8 * HOUR),
    )
    sent = sent_for(file, Report(Answer.FEASIBLE, itinerary=steps))
    assert [len(step["parts"]) for step in sent["steps"]] == [1, 2]
    assert sent["steps"][1]["latest"] == time("2027-05-16T08:00:00")
    return sent


def _set(*path: str | int, to: object) -> Callable[[Trip], None]:
    """A change to a TRIP: the value at this path becomes another."""

    def change(sent: Trip) -> None:
        held: Any = sent
        for key in path[:-1]:
            held = held[key]
        held[path[-1]] = to

    return change


def _drop(*path: str | int) -> Callable[[Trip], None]:
    def change(sent: Trip) -> None:
        held: Any = sent
        for key in path[:-1]:
            held = held[key]
        del held[path[-1]]

    return change


def _no_time(sent: Trip) -> None:
    sent["steps"][0].update(start=None, end=None, parts=[])


def _no_end(sent: Trip) -> None:
    """The night has no known end, and still the two parts of a night that ends."""
    sent["steps"][1].update(end=None, latest=None)


WANT: dict[str, Any] = {
    "id": "a-bed",
    "name": "a bed",
    "musts": ["alex"],
    "must_nots": ["sam"],
    "ends_at": None,
    "complete": "every-bed",
    "options": [{"option": "night", "name": "night", "degree": 8, "record": "night-is-a-bed"}],
}


OPTION: dict[str, Any] = {
    "id": "dinner",
    "name": "dinner",
    "from": "hotel",
    "to": "hotel",
    "start": {"at": "2027-05-15T19:00:00", "offset": None},
    "any_time": False,
    "length": {"shortest": 3600, "longest": 5400, "contingent": True},
    "margin": 600,
    "locked": ["alex"],
    "records": ["dinner-time", "lock-dinner"],
}


START: dict[str, Any] = {"person": "alex", "place": "museum", "record": "alex-start"}


def _start(**other: object) -> Callable[[Trip], None]:
    """The TRIP gets one FACT about where a PERSON starts from, good but for these parts."""
    return _set("starts_from", to=[{**START, **other}])


def test_a_trip_that_says_where_a_person_starts_from_is_a_trip() -> None:
    sent = good()
    assert sent["starts_from"] == []
    _start()(sent)
    assert holds(sent)
    _set("starts_from", to=[START, {**START, "person": "sam", "record": "sam-start"}])(sent)
    assert holds(sent)


WAY: dict[str, Any] = {
    "id": "ferry",
    "name": "ferry",
    "from": "museum",
    "to": "hotel",
    "both_ways": False,
    "length": {"shortest": 1200, "longest": 2400, "contingent": True},
    "records": ["ferry-length"],
}
TRAVEL: dict[str, Any] = {
    "record": "every-way",
    "from": None,
    "to": "hotel",
    "earliest": {"at": "2027-05-15T09:00:00", "offset": None},
    "latest": {"at": "2027-05-15T21:00:00", "offset": None},
}


def _way(**other: object) -> Callable[[Trip], None]:
    """The TRIP gets one more WAY, which is good but for these parts."""

    def change(sent: Trip) -> None:
        sent["ways"] = [*sent["ways"], {**WAY, **other}]

    return change


def _travel(**other: object) -> Callable[[Trip], None]:
    """The TRIP gets one FACT that the FILE lists every way of some travel, good but for these."""
    return _set("complete_travel", to=[{**TRAVEL, **other}])


def test_a_trip_with_one_more_way_is_a_trip() -> None:
    sent = good()
    assert [way["id"] for way in sent["ways"]] == ["walk"]
    _way()(sent)
    assert holds(sent)
    # A WAY of which the FILE says no more than where it goes.
    sent = good()
    _way(both_ways=True, length=None, records=[])(sent)
    assert holds(sent)


def test_a_trip_with_travel_that_the_file_lists_in_full_is_a_trip() -> None:
    sent = good()
    assert sent["complete_travel"] == []
    _travel()(sent)
    assert holds(sent)
    # Between any two PLACEs, and from one PLACE to another.
    _travel(to=None)(sent)
    assert holds(sent)
    _travel(**{"from": "museum"})(sent)
    assert holds(sent)


RIGHTS: dict[str, Any] = {
    "option": "night",
    "name": "night",
    "needs": {"needed": True, "record": "night-needs-a-room"},
    "bookings": [
        {
            "id": "room",
            "covers": ["alex"],
            "objects": [],
            "names": {"alex": "alex"},
            "paid": None,
            "terms": {"cancelling": [], "changing": []},
        }
    ],
    "offers": [
        {
            "id": "rooms",
            "places": 2,
            "price": {"amount": "120.00", "currency": "USD"},
            "objects": [],
            "names": {},
            "until": None,
            "expired": False,
        }
    ],
    "complete": {"record": "every-room", "offers": ["rooms"]},
}


# The same OPTION once more, with no BOOKING and no OFFER.
NO_MORE_RIGHTS: dict[str, Any] = {**RIGHTS, "bookings": [], "offers": [], "complete": None}


BUDGET: dict[str, Any] = {
    "id": "pot",
    "name": "the pot",
    "persons": ["alex", "sam"],
    "objects": [],
    "names": {"alex": "alex", "sam": "sam"},
    "currencies": ["USD", "EUR"],
    "caps": [{"id": "pot-cap", "limit": {"amount": "500.00", "currency": "USD"}}],
}
BUDGET_WITH_NO_CAP: dict[str, Any] = {**BUDGET, "caps": []}
PAID: dict[str, Any] = {"amount": "120.00", "currency": "USD", "budget": "pot", "by": "alex"}


def _budget(**other: object) -> Callable[[Trip], None]:
    """The TRIP gets one BUDGET, which is good but for these parts."""
    return _set("budgets", to=[{**BUDGET, **other}])


def _paid(**other: object) -> Callable[[Trip], None]:
    """The TRIP gets one BUDGET, and a BOOKING whose payment is good but for these parts."""

    def change(sent: Trip) -> None:
        _budget()(sent)
        _booking(paid={**PAID, **other})(sent)

    return change


def _paid_is(other: object) -> Callable[[Trip], None]:
    """The TRIP gets one BUDGET, and a BOOKING with this in the place of what it paid."""

    def change(sent: Trip) -> None:
        _budget()(sent)
        _booking(paid=other)(sent)

    return change


def test_a_trip_with_a_budget_and_a_payment_is_a_trip() -> None:
    sent = good()
    # The FILE has one BUDGET, for Alex and Sam, with no cap.
    (money,) = sent["budgets"]
    assert (money["id"], money["persons"], money["caps"]) == ("money", ["alex", "sam"], [])
    _budget()(sent)
    assert holds(sent)
    # A BUDGET that lists nobody, and has no cap.
    _budget(persons=[], names={}, caps=[])(sent)
    assert holds(sent)
    # A cap in each currency that the BUDGET holds.
    euros = {"id": "pot-cap-eur", "limit": {"amount": "300", "currency": "EUR"}}
    _budget(caps=[BUDGET["caps"][0], euros])(sent)
    assert holds(sent)
    # A payment from the BUDGET, and one that names no BUDGET and nobody who paid.
    _paid()(sent)
    assert holds(sent)
    _paid(budget=None, by=None)(sent)
    assert holds(sent)


def _rights(**other: object) -> Callable[[Trip], None]:
    """The TRIP says this of the rights to one OPTION, which is good but for these parts."""
    return _set("rights", to=[{**RIGHTS, **other}])


def _booking(**other: object) -> Callable[[Trip], None]:
    return _rights(bookings=[{**RIGHTS["bookings"][0], **other}])


def _offer(**other: object) -> Callable[[Trip], None]:
    return _rights(offers=[{**RIGHTS["offers"][0], **other}])


def _term(**other: object) -> Trip:
    """A term of a BOOKING as it is sent: from when the BOOKING was made, at no cost."""
    return {"since": None, "costs": [], "refused": False, **other}


def rooms_of(name: str) -> tuple[Trip, dict[str, Trip]]:
    """What is sent of an example about the room, and its BOOKINGs by their ids."""
    sent = drawn(EXAMPLES / "the-room" / f"{name}.json")
    bookings = {
        booking["id"]: booking for rights in sent["rights"] for booking in rights["bookings"]
    }
    return sent, bookings


def test_a_booking_is_sent_with_its_terms_and_the_trip_with_the_time_now() -> None:
    """The room can be cancelled at no cost until Wednesday at six, and it is Monday."""
    sent, bookings = rooms_of("on-monday")
    # The time now, with the FACT that states it, as a report words a time.
    assert sent["now"] == {"record": "today", "at": "9:00 am (UTC-5) on Monday 10 May 2027"}
    free: Trip = {"since": None, "costs": [], "refused": False}
    wednesday = "6:00 pm (UTC-5) on Wednesday 12 May 2027"
    assert bookings["room"]["terms"] == {
        "cancelling": [
            # From when the BOOKING was made: cancelling costs nothing.
            free,
            {
                "since": wednesday,
                "costs": [{"amount": "189.00", "currency": "USD"}],
                "refused": False,
            },
        ],
        # It states no terms for changing.
        "changing": [],
    }
    assert bookings["skydeck-ticket"]["terms"]["cancelling"] == [
        {"since": None, "costs": [{"amount": "32.00", "currency": "USD"}], "refused": False}
    ]
    # A term that states no cost: nobody knows what cancelling costs while it holds.
    _, bookings = rooms_of("free-until-wednesday")
    assert bookings["room"]["terms"]["cancelling"] == [
        free,
        {"since": wednesday, "costs": None, "refused": False},
    ]
    # A cost in two currencies has both amounts, in the FILE's order.
    _, bookings = rooms_of("points-and-dollars")
    assert bookings["room"]["terms"]["cancelling"][1]["costs"] == [
        {"amount": "30000", "currency": "hotel-points"},
        {"amount": "25.00", "currency": "USD"},
    ]
    # A term can say that the seller accepts no cancellation. It states no cost.
    _, bookings = rooms_of("the-ticket-cannot-be-cancelled")
    assert bookings["skydeck-ticket"]["terms"]["cancelling"] == [
        {"since": None, "costs": None, "refused": True}
    ]
    # Terms for changing are sent in the same way.
    _, bookings = rooms_of("a-change")
    assert bookings["room"]["terms"]["changing"] == [
        free,
        {
            "since": "12:00 pm (UTC-5) on Tuesday 11 May 2027",
            "costs": [{"amount": "25.00", "currency": "USD"}],
            "refused": False,
        },
    ]
    # A FILE that states no time now sends none.
    sent, _ = rooms_of("nobody-said-what-time-it-is")
    assert sent["now"] is None
    assert drawn(EXAMPLES / "flight-home" / "works.json")["now"] is None


def test_a_trip_that_says_something_of_the_rights_to_an_option_is_a_trip() -> None:
    sent = good()
    # The FILE says that nobody needs a right to the night, and no more.
    (night,) = sent["rights"]
    assert (night["option"], night["needs"]["needed"], night["bookings"]) == ("night", False, [])
    _rights()(sent)
    assert holds(sent)
    # Nobody needs a right, and the FILE says no more.
    walk_up = {"needed": False, "record": "night-is-open"}
    _rights(needs=walk_up, bookings=[], offers=[], complete=None)(sent)
    assert holds(sent)
    # A BOOKING and nothing else, and an OFFER whose price nobody knows.
    _rights(needs=None, offers=[], complete=None)(sent)
    assert holds(sent)
    _offer(price=None)(sent)
    assert holds(sent)
    # A price of nothing, and one below one.
    for amount in ("0", "0.50"):
        _offer(price={"amount": amount, "currency": "USD"})(sent)
        assert holds(sent)


OBJECT: dict[str, Any] = {
    "id": "key",
    "name": "the key",
    "starts": {"person": "alex", "place": None, "record": "alex-has-the-key"},
    "requires": [{"option": "night", "name": "night", "needed": True, "record": "night-needs-it"}],
    "refuses": [{"option": "night", "name": "night", "refused": False, "record": "night-lets-it"}],
    "requires_complete": "every-use-of-the-key",
    "transfers": [
        {"option": "night", "name": "night", "does": "keeps", "record": "night-keeps-it"}
    ],
    "transfers_complete": "everything-that-moves-the-key",
    "rights": [{"option": "night", "name": "night", "needed": True, "record": "night-needs-key"}],
    "rights_complete": "every-ticket-for-the-key",
    "rights_closed": [
        {
            "option": "night",
            "name": "night",
            "record": "no-other-key-right",
            "called": "the key",
            "offers": [],
        }
    ],
}


def _object(**other: object) -> Callable[[Trip], None]:
    """The TRIP gets one OBJECT, which is good but for these parts."""
    return _set("objects", to=[{**OBJECT, **other}])


def _object_starts(**other: object) -> Callable[[Trip], None]:
    return _object(starts={**OBJECT["starts"], **other})


def _object_need(**other: object) -> Callable[[Trip], None]:
    return _object(requires=[{**OBJECT["requires"][0], **other}])


def _object_refusal(**other: object) -> Callable[[Trip], None]:
    return _object(refuses=[{**OBJECT["refuses"][0], **other}])


def _transfer(**other: object) -> Callable[[Trip], None]:
    return _object(transfers=[{**OBJECT["transfers"][0], **other}])


def test_a_trip_with_an_object_is_a_trip() -> None:
    sent = good()
    assert sent["objects"] == []
    _object()(sent)
    assert holds(sent)
    # A BOOKING can cover an OBJECT of the TRIP beside a PERSON, or an OBJECT alone.
    _booking(objects=["key"], names={"alex": "alex", "key": "the key"})(sent)
    assert holds(sent)
    _booking(covers=[], objects=["key"], names={"key": "the key"})(sent)
    assert holds(sent)
    # An OFFER can name an OBJECT of the TRIP, and a BUDGET can list one. A FACT that the
    # FILE lists every right for the OBJECT can name that OFFER.
    for_the_key = {**RIGHTS["offers"][0], "objects": ["key"], "names": {"key": "the key"}}
    _rights(offers=[for_the_key], complete=None)(sent)
    assert holds(sent)
    _object(rights_closed=[{**OBJECT["rights_closed"][0], "offers": ["rooms"]}])(sent)
    assert holds(sent)
    _budget(objects=["key"], names={"alex": "alex", "sam": "sam", "key": "the key"})(sent)
    assert holds(sent)
    _budget()(sent)
    _object()(sent)
    _rights()(sent)
    # An OBJECT of which the FILE says nothing.
    _object(
        starts=None,
        requires=[],
        refuses=[],
        requires_complete=None,
        transfers=[],
        transfers_complete=None,
    )(sent)
    assert holds(sent)
    # One that lies at a PLACE when the TRIP starts.
    _object_starts(person=None, place="hotel")(sent)
    assert holds(sent)
    # An OPTION hands it over, keeps it, or leaves it alone, and requires it or does not, and
    # refuses it or does not.
    for does in ("hands_over", "keeps", "nothing"):
        _transfer(does=does)(sent)
        assert holds(sent)
    _object_need(needed=False)(sent)
    assert holds(sent)
    _object_refusal(refused=True)(sent)
    assert holds(sent)


CAPABILITY: dict[str, Any] = {
    "id": "driving",
    "name": "driving",
    "has": [
        {"person": "alex", "has": True, "record": "alex-drives"},
        {"person": "sam", "has": False, "record": "sam-does-not-drive"},
    ],
    "complete": "every-drive",
    "options": [{"option": "night", "name": "night", "of": "one", "record": "night-needs-it"}],
}


def _capability(**other: object) -> Callable[[Trip], None]:
    """The TRIP gets one CAPABILITY, which is good but for these parts."""
    return _set("capabilities", to=[{**CAPABILITY, **other}])


def _ability(**other: object) -> Callable[[Trip], None]:
    """The TRIP gets one CAPABILITY, whose first PERSON is good but for these parts."""
    return _capability(has=[{**CAPABILITY["has"][0], **other}])


def _requirement(**other: object) -> Callable[[Trip], None]:
    """The TRIP gets one CAPABILITY, whose one OPTION is good but for these parts."""
    return _capability(options=[{**CAPABILITY["options"][0], **other}])


def test_a_trip_with_a_capability_is_a_trip() -> None:
    sent = good()
    assert sent["capabilities"] == []
    _capability()(sent)
    assert holds(sent)
    # A CAPABILITY of which the FILE says nothing.
    _capability(has=[], complete=None, options=[])(sent)
    assert holds(sent)
    # An OPTION requires it of one PERSON who takes part, of each, or of none.
    for of in ("one", "each", "none"):
        _requirement(of=of)(sent)
        assert holds(sent)


def _option(**other: object) -> Callable[[Trip], None]:
    """The TRIP gets one more OPTION, which is good but for these parts."""

    def change(sent: Trip) -> None:
        sent["options"] = [*sent["options"], {**OPTION, **other}]

    return change


def _option_is(other: object) -> Callable[[Trip], None]:
    """The TRIP gets this in the place of one more OPTION."""

    def change(sent: Trip) -> None:
        sent["options"] = [*sent["options"], other]

    return change


def test_a_trip_with_one_more_option_is_a_trip() -> None:
    sent = good()
    assert [option["id"] for option in sent["options"]] == ["night"]
    _option()(sent)
    assert holds(sent)
    # An OPTION of which the FILE says next to nothing.
    sent = good()
    _option(start=None, length=None, margin=None, locked=[], records=[])(sent)
    assert holds(sent)
    # One that can start at any time, and takes no time.
    sent = good()
    still = {"shortest": 0, "longest": 0, "contingent": False}
    _option(start=None, any_time=True, length=still, margin=0)(sent)
    assert holds(sent)
    # A range that the world decides in can have two ends that are the same.
    sent = good()
    _option(length={"shortest": 3600, "longest": 3600, "contingent": True})(sent)
    assert holds(sent)


def _want(**other: object) -> Callable[[Trip], None]:
    """The TRIP gets one WANT, which is good but for these parts."""
    return _set("wants", to=[{**WANT, **other}])


def _delivery(**other: object) -> Callable[[Trip], None]:
    """The TRIP gets one WANT, whose one OPTION is good but for these parts."""
    return _want(options=[{**WANT["options"][0], **other}])


def test_a_trip_with_a_want_is_a_trip() -> None:
    sent = good()
    assert sent["wants"] == []
    _want()(sent)
    assert holds(sent)
    # A WANT with nobody for whom it is a must-not, and no OPTION.
    _want(must_nots=[], complete=None, options=[])(sent)
    assert holds(sent)
    # A WANT about where the TRIP ends names a PLACE. No OPTION delivers such a WANT, and
    # it is a must for each PERSON who holds it.
    _want(ends_at="hotel", must_nots=[], complete=None, options=[])(sent)
    assert holds(sent)
    # A DEGREE OF SATISFACTION is from 0 to 10, both ends included.
    for degree in (0, 10):
        _delivery(degree=degree)(sent)
        assert holds(sent)


BROKEN: dict[str, Callable[[Trip], None]] = {
    "no options": _drop("options"),
    "options that are no list": _set("options", to={}),
    "a step that is none of the options": _set("options", to=[]),
    "an option that is no record": _option_is("dinner"),
    "an option with one thing more": _option(more=1),
    "an option with a blank name": _option(name=" "),
    "two options with one id": _option(id="night"),
    "an option at a place the trip does not have": _option(to="denver"),
    "an option with a start that is no time": _option(start="19:00"),
    "an option with a time that can start at any time": _option(any_time=True),
    "an option whose any time is no yes or no": _option(start=None, any_time=1),
    "an option with a length that is a number": _option(length=3600),
    "an option that takes less than no time": _option(
        length={"shortest": -1, "longest": 60, "contingent": True}
    ),
    "an option whose longest is under its shortest": _option(
        length={"shortest": 90, "longest": 60, "contingent": True}
    ),
    "an option with a length in words": _option(
        length={"shortest": "1 h", "longest": "1 h", "contingent": False}
    ),
    "an option with a range that the world does not decide": _option(
        length={"shortest": 60, "longest": 90, "contingent": False}
    ),
    "an option with a length that does not say whether the world decides": _option(
        length={"shortest": 60, "longest": 60}
    ),
    "an option with a length that the world decides as a number": _option(
        length={"shortest": 60, "longest": 60, "contingent": 1}
    ),
    "an option with a margin below nothing": _option(margin=-1),
    "an option with a margin that is a yes": _option(margin=True),
    "an option that a lock names for a person the trip does not have": _option(locked=["jo"]),
    "an option that names a person twice": _option(locked=["alex", "alex"]),
    "an option that names a record twice": _option(records=["dinner-time", "dinner-time"]),
    "no wants": _drop("wants"),
    "wants that are no list": _set("wants", to={}),
    "a want that is no record": _set("wants", to=["a-bed"]),
    "a want with one thing more": _want(more=1),
    "a want with a blank name": _want(name=" "),
    "a want with an id that is no text": _want(id=7),
    "two wants with one id": _set("wants", to=[WANT, WANT]),
    "a want that is a must for a person the trip does not have": _want(musts=["jo"]),
    "a want about where the trip ends that is a must-not for somebody": _want(
        ends_at="hotel", complete=None, options=[]
    ),
    "a want that names a person twice": _want(musts=["alex", "alex"]),
    "a want that is a must and a must-not for one person": _want(must_nots=["alex"]),
    "a want that is a must or a must-not for nobody": _want(musts=[], must_nots=[]),
    "a want whose musts are no list": _want(musts="alex"),
    "a want that ends at a place the trip does not have": _want(ends_at="denver", options=[]),
    "a want about where the trip ends that an option delivers": _want(ends_at="hotel"),
    "a want whose complete set is no id": _want(complete=7),
    "a want whose options are no list": _want(options={}),
    "an option of a want that is no record": _want(options=["night"]),
    "an option of a want with a degree above ten": _delivery(degree=11),
    "an option of a want with a degree below nothing": _delivery(degree=-1),
    "an option of a want with a degree in words": _delivery(degree="8"),
    "an option of a want with a degree that is a yes": _delivery(degree=True),
    "an option of a want with a blank name": _delivery(name=""),
    "an option of a want with no fact": _delivery(record=None),
    "a want that names an option twice": _want(options=[WANT["options"][0]] * 2),
    "an option of a want that the trip does not have": _delivery(option="dinner"),
    "no word on where persons start from": _drop("starts_from"),
    "where persons start from that is no list": _set("starts_from", to={}),
    "where a person starts from that is no record": _set("starts_from", to=["alex-start"]),
    "where a person starts from with one thing more": _start(more=1),
    "where a person the trip does not have starts from": _start(person="jo"),
    "a person who starts from a place the trip does not have": _start(place="denver"),
    "where a person starts from with no fact": _start(record=""),
    "a person who starts from two places": _set(
        "starts_from", to=[START, {**START, "place": "hotel", "record": "alex-start-2"}]
    ),
    "two persons whose starts are one fact": _set(
        "starts_from", to=[START, {**START, "person": "sam"}]
    ),
    "no ways": _drop("ways"),
    "ways that are no list": _set("ways", to={}),
    "a step that is none of the ways": _set("ways", to=[]),
    "a way that is no record": _set("ways", to=["walk"]),
    "a way with one thing more": _way(more=1),
    "a way with a blank name": _way(name=" "),
    "two ways with one id": _way(id="walk"),
    "a way with the id of an option": _way(id="night"),
    "a way from a place the trip does not have": _way(**{"from": "denver"}),
    "a way to a place the trip does not have": _way(to="denver"),
    "a way whose both ways is a number": _way(both_ways=1),
    "a way with a length that is a number": _way(length=1200),
    "a way whose longest is under its shortest": _way(
        length={"shortest": 90, "longest": 60, "contingent": True}
    ),
    "a way with a range that the world does not decide": _way(
        length={"shortest": 60, "longest": 90, "contingent": False}
    ),
    "a way that names a record twice": _way(records=["ferry-length", "ferry-length"]),
    "no travel listed in full": _drop("complete_travel"),
    "travel listed in full that is no list": _set("complete_travel", to={}),
    "travel listed in full that is no record": _set("complete_travel", to=["every-way"]),
    "travel listed in full with one thing more": _travel(more=1),
    "travel listed in full with no fact": _travel(record=""),
    "travel listed in full from a place the trip does not have": _travel(**{"from": "denver"}),
    "travel listed in full to a place the trip does not have": _travel(to="denver"),
    "travel listed in full with an end that is no time": _travel(latest="21:00"),
    "travel listed in full with no start": _travel(earliest=None),
    "two facts with one id that travel is listed in full": _set(
        "complete_travel", to=[TRAVEL, TRAVEL]
    ),
    "no rights": _drop("rights"),
    "rights that are no list": _set("rights", to={}),
    "rights that are no record": _set("rights", to=["night"]),
    "rights with one thing more": _rights(more=1),
    "rights to an option the trip does not have": _rights(option="dinner"),
    "rights to one option twice": _set("rights", to=[RIGHTS, NO_MORE_RIGHTS]),
    "rights to an option with a blank name": _rights(name=" "),
    "a need for a right that is a yes": _rights(needs=True),
    "a need for a right with no fact": _rights(needs={"needed": True, "record": ""}),
    "a need for a right that is a number": _rights(needs={"needed": 1, "record": "r"}),
    "bookings that are no list": _rights(bookings={}),
    "a booking that is no record": _rights(bookings=["room"]),
    "a booking with no id": _booking(id=""),
    "a booking that covers nobody": _booking(covers=[]),
    "a booking that covers an object twice": _booking(objects=["key", "key"]),
    "a booking that covers an object the trip does not have": _booking(objects=["key"]),
    "a booking whose objects are no list": _booking(objects="key"),
    "a booking that covers a person twice": _booking(covers=["alex", "alex"]),
    "a booking that covers a person the trip does not have": _booking(covers=["jo"]),
    "a booking with no name for a person it covers": _booking(names={}),
    "a booking with a name for a person it does not cover": _booking(
        names={"alex": "alex", "sam": "sam"}
    ),
    "a booking with a blank name": _booking(names={"alex": " "}),
    "a booking with a name that is a number": _booking(names={"alex": 1}),
    "a booking whose names are a list": _booking(names=["alex"]),
    "two bookings with one id": _rights(bookings=[RIGHTS["bookings"][0]] * 2),
    "a booking with the id of an offer": _booking(id="rooms"),
    "a booking whose terms are a list": _booking(terms=[]),
    "a booking with terms of one kind only": _booking(terms={"cancelling": []}),
    "a booking with terms of a third kind": _booking(
        terms={"cancelling": [], "changing": [], "moving": []}
    ),
    "a term that is a cost and no more": _booking(
        terms={"cancelling": [{"amount": "5.00", "currency": "USD"}], "changing": []}
    ),
    "a term with no word on whether the seller accepts": _booking(
        terms={"cancelling": [{"since": None, "costs": None}], "changing": []}
    ),
    "a later term that holds from when the booking was made": _booking(
        terms={"cancelling": [_term(), _term()], "changing": []}
    ),
    "a term that holds from no time": _booking(
        terms={"cancelling": [_term(since=" ")], "changing": []}
    ),
    "a term whose cost is an amount and no list": _booking(
        terms={"cancelling": [], "changing": [_term(costs={"amount": "5.00", "currency": "USD"})]}
    ),
    "a term whose cost has no currency": _booking(
        terms={"cancelling": [_term(costs=[{"amount": "5.00"}])], "changing": []}
    ),
    "a term whose cost is no amount": _booking(
        terms={"cancelling": [_term(costs=[{"amount": "five", "currency": "USD"}])], "changing": []}
    ),
    "a term whose cost holds nothing where an amount is": _booking(
        terms={"cancelling": [_term(costs=[None])], "changing": []}
    ),
    "a term with two amounts in one currency": _booking(
        terms={
            "cancelling": [
                _term(
                    costs=[
                        {"amount": "5.00", "currency": "USD"},
                        {"amount": "6.00", "currency": "USD"},
                    ]
                )
            ],
            "changing": [],
        }
    ),
    "a term that accepts none and states a cost": _booking(
        terms={"cancelling": [_term(refused=True)], "changing": []}
    ),
    "an offer that is no record": _rights(offers=["rooms"], complete=None),
    "an offer with no place": _offer(places=0),
    "an offer with places in words": _offer(places="2"),
    "an offer with a price that is a number": _offer(price=120),
    "an offer with a price in no currency": _offer(price={"amount": "120.00", "currency": " "}),
    "an offer with a price that is no amount": _offer(price={"amount": "-1", "currency": "USD"}),
    "an offer with no list of objects": _offer(objects=None),
    "an offer for an object the trip does not have": _offer(
        objects=["boat"], names={"boat": "the boat"}
    ),
    "an offer with a name for an object that it does not name": _offer(names={"boat": "the boat"}),
    "an offer whose names are a list": _offer(names=[]),
    "a fact that the rights are all listed with no id": _rights(
        complete={"record": "", "offers": []}
    ),
    "a fact that the rights are all listed that names another offer": _rights(
        complete={"record": "every-room", "offers": ["beds"]}
    ),
    "a fact that the rights are all listed that names an offer twice": _rights(
        complete={"record": "every-room", "offers": ["rooms", "rooms"]}
    ),
    "no budgets": _drop("budgets"),
    "budgets that are no list": _set("budgets", to={}),
    "a budget that is no record": _set("budgets", to=["pot"]),
    "a budget with one thing more": _budget(more=1),
    "a budget with a blank name": _budget(name=" "),
    "two budgets with one id": _set("budgets", to=[BUDGET, BUDGET_WITH_NO_CAP]),
    "a budget for a person the trip does not have": _budget(persons=["jo"]),
    "a budget that lists a person twice": _budget(persons=["alex", "alex"]),
    "a budget with no list of objects": _budget(objects=None),
    "a budget for an object the trip does not have": _budget(
        objects=["boat"], names={"alex": "alex", "sam": "sam", "boat": "the boat"}
    ),
    "a budget with no name for a person that it lists": _budget(names={"alex": "alex"}),
    "a budget with a blank name for a person": _budget(names={"alex": "alex", "sam": " "}),
    "a budget whose names are a list": _budget(names=["alex", "sam"]),
    "a budget that holds no currency": _budget(currencies=[]),
    "a budget that holds a currency twice": _budget(currencies=["USD", "USD"]),
    "a budget that holds a blank currency": _budget(currencies=[" "]),
    "caps that are no list": _budget(caps={}),
    "a cap that is no record": _budget(caps=["pot-cap"]),
    "a cap with no id": _budget(caps=[{**BUDGET["caps"][0], "id": ""}]),
    "a cap with no limit": _budget(caps=[{"id": "pot-cap", "limit": None}]),
    "a cap with a limit that is no amount": _budget(
        caps=[{"id": "pot-cap", "limit": {"amount": "lots", "currency": "USD"}}]
    ),
    "two caps in one currency": _budget(
        caps=[BUDGET["caps"][0], {**BUDGET["caps"][0], "id": "pot-cap-2"}]
    ),
    "a payment that is a number": _paid_is(120),
    "a payment with one thing more": _paid(more=1),
    "a payment that is no amount": _paid(amount="-1"),
    "a payment from a budget the trip does not have": _paid(budget="purse"),
    "a payment by a person the trip does not have": _paid(by="jo"),
    "no objects": _drop("objects"),
    "objects that are no list": _set("objects", to={}),
    "an object that is no record": _set("objects", to=["key"]),
    "an object with one thing more": _object(more=1),
    "an object with a blank name": _object(name=" "),
    "two objects with one id": _set("objects", to=[OBJECT, OBJECT]),
    "an object that starts with a person and at a place": _object_starts(place="hotel"),
    "an object that starts nowhere": _object_starts(person=None),
    "an object that starts with a person the trip does not have": _object_starts(person="jo"),
    "an object that starts at a place the trip does not have": _object_starts(
        person=None, place="denver"
    ),
    "an object whose start has no fact": _object_starts(record=""),
    "an object whose start is a place name": _object(starts="hotel"),
    "an object whose requirements are no list": _object(requires={}),
    "an option that requires an object and is no record": _object(requires=["night"]),
    "an option of an object that the trip does not have": _object_need(option="dinner"),
    "an option of an object with a blank name": _object_need(name=""),
    "an option that requires an object as a number": _object_need(needed=1),
    "an option of an object with no fact": _object_need(record=""),
    "an object that names an option twice among what requires it": _object(
        requires=[OBJECT["requires"][0]] * 2
    ),
    "an object whose refusals are no list": _object(refuses={}),
    "an option that refuses an object and is no record": _object(refuses=["night"]),
    "an option that refuses an object and that the trip does not have": _object_refusal(
        option="dinner"
    ),
    "an option that refuses an object with a blank name": _object_refusal(name=""),
    "an option that refuses an object as a number": _object_refusal(refused=1),
    "an option that refuses an object with no fact": _object_refusal(record=""),
    "an object that names an option twice among what refuses it": _object(
        refuses=[OBJECT["refuses"][0]] * 2
    ),
    "an option that does something else with an object": _transfer(does="loses"),
    "an option that moves an object and that the trip does not have": _transfer(option="dinner"),
    "an object that names an option twice among what moves it": _object(
        transfers=[OBJECT["transfers"][0]] * 2
    ),
    "an object whose complete set is no id": _object(requires_complete=7),
    "an object whose rights are all listed with no list of offers": _object(
        rights_closed=[{**OBJECT["rights_closed"][0], "offers": None}]
    ),
    "an object whose rights are all listed with an offer twice": _object(
        rights_closed=[{**OBJECT["rights_closed"][0], "offers": ["rooms", "rooms"]}]
    ),
    "an object whose rights are all listed with an offer that has no id": _object(
        rights_closed=[{**OBJECT["rights_closed"][0], "offers": [""]}]
    ),
    "no capabilities": _drop("capabilities"),
    "capabilities that are no list": _set("capabilities", to={}),
    "a capability that is no record": _set("capabilities", to=["driving"]),
    "a capability with one thing more": _capability(more=1),
    "a capability with a blank name": _capability(name=" "),
    "a capability with an id that is no text": _capability(id=7),
    "two capabilities with one id": _set("capabilities", to=[CAPABILITY, CAPABILITY]),
    "a capability whose complete set is no id": _capability(complete=7),
    "a capability whose persons are no list": _capability(has={}),
    "a capability of a person the trip does not have": _ability(person="jo"),
    "a capability that names a person twice": _capability(has=[CAPABILITY["has"][0]] * 2),
    "a person of a capability who is no record": _capability(has=["alex"]),
    "a person of a capability with a has that is a number": _ability(has=1),
    "a person of a capability with no fact": _ability(record=None),
    "a capability whose options are no list": _capability(options={}),
    "an option of a capability that is no record": _capability(options=["night"]),
    "an option of a capability that the trip does not have": _requirement(option="dinner"),
    "an option of a capability with a blank name": _requirement(name=""),
    "an option of a capability that requires it of two": _requirement(of="two"),
    "an option of a capability that requires it of a number": _requirement(of=1),
    "an option of a capability with no fact": _requirement(record=None),
    "a capability that names an option twice": _capability(options=[CAPABILITY["options"][0]] * 2),
    "no zone": _drop("zone"),
    "one thing more": _set("more", to=1),
    "a zone that is no text": _set("zone", to=5),
    "an itinerary that is no yes or no": _set("itinerary", to=1),
    "persons that are no list": _set("persons", to={}),
    "a person with no name": _drop("persons", 0, "name"),
    "a person with one thing more": _set("persons", 0, "more", to=1),
    "a person whose id is no text": _set("persons", 0, "id", to=1),
    "a person whose name is no text": _set("persons", 0, "name", to=None),
    "a person whose name is blank": _set("persons", 0, "name", to="  "),
    "a person who is no record": _set("persons", 0, to="alex"),
    "two persons with one id": _set("persons", 1, "id", to="alex"),
    "places that are no list": _set("places", to="museum"),
    "a place with no id": _drop("places", 0, "id"),
    "a place whose name is empty": _set("places", 0, "name", to=""),
    "two places with one id": _set("places", 1, "id", to="museum"),
    "days that are no list": _set("days", to="2027-05-15"),
    "a day that is a date and no more": _set("days", 0, to="2027-05-15"),
    "a day with no date": _drop("days", 0, "date"),
    "a day with one thing more": _set("days", 0, "more", to=1),
    "a day whose date is no date": _set("days", 0, "date", to="15 May 2027"),
    "a day whose date is no day": _set("days", 0, "date", to="2027-02-30"),
    "a day whose date is a time": _set("days", 0, "date", to="2027-05-15T00:00:00"),
    "a day whose date is a number": _set("days", 0, "date", to=20270515),
    "a day that opens before it starts": _set("days", 1, "opens", to=-1),
    "a day that closes after 24 hours": _set("days", 1, "closes", to=86401),
    "a day that closes before it opens": _set("days", 1, "closes", to=-1),
    "a day that opens at half a second": _set("days", 1, "opens", to=0.5),
    "a day with an offset that is none": _set("days", 0, "offset", to="-5"),
    "a day with an offset in words": _set("days", 0, "offset", to="UTC minus five"),
    "too many days": _set(
        "days", to=[{"date": "2027-05-15", "offset": None, "opens": 0, "closes": 86400}] * 63
    ),
    "a time now that is a time and no more": _set("now", to="9:00 am"),
    "a time now with no FACT": _set("now", to={"at": "9:00 am on Monday 10 May 2027"}),
    "a time now whose FACT has no id": _set(
        "now", to={"record": "", "at": "9:00 am on Monday 10 May 2027"}
    ),
    "a time now at no time": _set("now", to={"record": "today", "at": " "}),
    "a time now with one thing more": _set(
        "now", to={"record": "today", "at": "9:00 am on Monday 10 May 2027", "more": 1}
    ),
    "a last date that is no date": _set("until", to="soon"),
    "a last date that is a number": _set("until", to=20270916),
    "a start of the trip that is a time": _set("starts", to="2027-05-15T09:00:00"),
    "a start of the trip with no time": _drop("starts", "at"),
    "a start of the trip at no time": _set("starts", "at", to="9 am"),
    "a start of the trip with an offset that is none": _set("starts", "offset", to="UTC"),
    "a start of the trip on a day that is not sent": _set("starts", "day", to=2),
    "a start of the trip on a day before the first": _set("starts", "day", to=-1),
    "a start of the trip on a day and at no second": _set("starts", "second", to=None),
    "a start of the trip on no day and at a second": _set("starts", "day", to=None),
    "an end of the trip after the end of its day": _set("ends", "second", to=86401),
    "an end of the trip before its day": _set("ends", "second", to=-1),
    "an end of the trip at half a second": _set("ends", "second", to=0.5),
    "an end of the trip with one thing more": _set("ends", "more", to=1),
    "an end of the trip with no record": _drop("ends", "record"),
    "an end of the trip whose record is no text": _set("ends", "record", to=7),
    "an end of the trip whose record has no id": _set("ends", "record", to=""),
    "steps that are no list": _set("steps", to=None),
    "a step that is no record": _set("steps", 0, to=[]),
    "a step with no start": _drop("steps", 0, "start"),
    "a step with one thing more": _set("steps", 0, "more", to=1),
    "an option that is no text": _set("steps", 1, "option", to=7),
    "an option and a way at once": _set("steps", 1, "way", to="walk"),
    "a name that is no text": _set("steps", 0, "name", to=["walk"]),
    "an option with no name": _set("steps", 1, "name", to=None),
    "an option whose name is blank": _set("steps", 1, "name", to=" "),
    "a way of the file with no name": _set("steps", 0, "name", to=None),
    "a way with a name that the file does not list": _set("steps", 0, "way", to=None),
    "a step from no place of the trip": _set("steps", 0, "from", to="pier"),
    "a step to no place of the trip": _set("steps", 0, "to", to=None),
    "a step for nobody": _set("steps", 0, "persons", to=[]),
    "a step for somebody else": _set("steps", 0, "persons", to=["alex", "jo"]),
    "a step for one person twice": _set("steps", 0, "persons", to=["alex", "alex"]),
    "persons of a step that are no list": _set("steps", 0, "persons", to="alex"),
    "a person of a step who is no text": _set("steps", 1, "persons", to=[["alex"]]),
    "a lock for somebody who takes no part": _set("steps", 0, "locked", to=["sam"]),
    "locks that are no list": _set("steps", 0, "locked", to=True),
    "a start that is text and no more": _set("steps", 0, "start", to="2027-05-15T22:00:00"),
    "a start that is a number": _set("steps", 0, "start", "at", to=1810000000),
    "a start with one thing more": _set("steps", 0, "start", "more", to=1),
    "a start with no seconds": _set("steps", 0, "start", "at", to="2027-05-15T22:00"),
    "a start with its offset in it": _set(
        "steps", 0, "start", "at", to="2027-05-15T22:00:00-05:00"
    ),
    "a start on no day": _set("steps", 0, "start", "at", to="2027-02-30T22:00:00"),
    "a start at no time": _set("steps", 0, "start", "at", to="2027-05-15T24:00:00"),
    "a start in the year nought": _set("steps", 0, "start", "at", to="0000-05-15T22:00:00"),
    "a start in other digits": _set("steps", 0, "start", "at", to="٢٠٢٧-05-15T22:00:00"),
    "a start with an offset that is none": _set("steps", 0, "start", "offset", to="-05:00"),
    "a start on another day than its part": _set(
        "steps", 0, "start", "at", to="2027-05-16T22:00:00"
    ),
    "a start at another time than its part": _set(
        "steps", 0, "start", "at", to="2027-05-15T22:00:01"
    ),
    "an end with no start": _set("steps", 0, "start", to=None),
    "an end that is no time": _set("steps", 0, "end", "at", to="22:20"),
    "an end with a line after it": _set("steps", 0, "end", "at", to="2027-05-15T22:20:00\n"),
    "a latest end that is no time": _set("steps", 1, "latest", "at", to="8 am"),
    "a latest end with no end": _set("steps", 1, "end", to=None),
    "a step of an itinerary with no time": _no_time,
    "a way and a person whom no lock names, with no itinerary": _set("itinerary", to=False),
    "a way and a person whom no lock names, with no report": _set("itinerary", to=None),
    "parts that are no list": _set("steps", 0, "parts", to={}),
    "a part that is no record": _set("steps", 0, "parts", 0, to=[0, 79200, 80400]),
    "a part with no day": _drop("steps", 0, "parts", 0, "day"),
    "a part with one thing more": _set("steps", 0, "parts", 0, "more", to=1),
    "a part on a day that is not sent": _set("steps", 0, "parts", 0, "day", to=2),
    "a part on a day before the first": _set("steps", 0, "parts", 0, "day", to=-1),
    "a part on half a day": _set("steps", 0, "parts", 0, "day", to=0.5),
    "a part on another day than its step starts on": _set("steps", 0, "parts", 0, "day", to=1),
    "a part that ends before it starts": _set("steps", 0, "parts", 0, "to", to=79199),
    "a part that starts before its day": _set("steps", 1, "parts", 1, "from", to=-1),
    "a part that ends after its day": _set("steps", 1, "parts", 0, "to", to=86401),
    "a part that starts at a yes": _set("steps", 1, "parts", 1, "from", to=True),
    "a part whose beginning is a number": _set("steps", 0, "parts", 0, "begins", to=1),
    "a first part that does not begin the step": _set("steps", 0, "parts", 0, "begins", to=False),
    "two parts on one day": _set("steps", 1, "parts", 1, "day", to=0),
    "a later part that begins the step": _set("steps", 1, "parts", 1, "begins", to=True),
    "an earlier part that ends the step": _set("steps", 1, "parts", 0, "ends", to=True),
    "parts of a step with no time": lambda sent: sent["steps"][0].update(start=None, end=None),
    "no part of a step with a time": _set("steps", 0, "parts", to=[]),
    "no records of a step": _drop("steps", 0, "records"),
    "records that are no list": _set("steps", 1, "records", to="night-time"),
    "a record that is no text": _set("steps", 1, "records", to=[1]),
    "one record twice": _set("steps", 1, "records", to=["night-time", "night-time"]),
    "two parts of a step with no known end": _no_end,
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
