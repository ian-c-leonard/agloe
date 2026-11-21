"""The lines of a report in words, and what on the calendar each line is about.

A report in words shows the plan one step to a line, and under a step what it warns of. It shows
each FACT, WANT and DECISION that it names on a line that starts with its id. So the page can
tie a line to the step it shows, or to the record it names. ``src/agloe/view/static/lines.js``
does that. It has no page in it, so Node runs it here, through ``view_lines.mjs``.

Nothing in it judges a TRIP. It finds what the report already says, line by line.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest

from agloe import compiler, report
from agloe.file import parse, read
from agloe.view.trip import shown
from tests.stories import EXAMPLES

FILES = sorted(
    path for path in EXAMPLES.rglob("*.json") if not path.name.endswith(".expected.json")
)

type Line = dict[str, Any]


def asked_of(path: Path) -> dict[str, Any]:
    """The report on this FILE in words and as JSON, and the TRIP that the view sends with it."""
    file = read(path)
    found = compiler.check(file)
    return {
        "text": report.as_text(file, found),
        "report": report.as_json(file, found),
        "trip": shown(file, found),
    }


def lines_of(asked: list[dict[str, Any]]) -> list[list[Line]]:
    """The lines of each report, by the page's own code."""
    node = shutil.which("node")
    if node is None:
        if os.environ.get("CI"):
            pytest.fail("the tests of the view need Node")
        pytest.skip("needs Node")
    done = subprocess.run(
        [node, str(Path(__file__).parent / "view_lines.mjs")],
        input=json.dumps(asked),
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    found: list[list[Line]] = json.loads(done.stdout)
    return found


def test_the_lines_are_the_report_and_each_is_tied_to_what_it_is_about() -> None:
    """For every example: nothing of the report is lost, and each tie is one the report makes."""
    asked = [asked_of(path) for path in FILES]
    plans = 0
    for path, each, found in zip(FILES, asked, lines_of(asked), strict=True):
        name = f"{path.parent.name}/{path.stem}"
        assert "\n".join(line["text"] for line in found) == each["text"], name
        said = each["report"]
        trip = cast("dict[str, Any]", each["trip"])
        # Each record that the report names has a line that starts with its id. A report can
        # say more of a record further down, such as what a BOOKING paid: that line is its too.
        ids = [*said.get("relies_on", []), *said.get("conflict", [])]
        records = [line["record"] for line in found if line["record"] is not None]
        assert set(records) == set(ids), name
        assert len(records) >= len(ids), name
        for line in found:
            if line["record"] is not None:
                assert line["text"].startswith(f"  {line['record']}: "), name
                assert line["step"] is None, name
        # Each step of a plan has one line, in the plan's order, and that line names the step.
        shows = [line for line in found if line["step"] is not None and not line["warns"]]
        if said["answer"] == "FEASIBLE":
            plans += 1
            assert [line["step"] for line in shows] == list(range(len(trip["steps"]))), name
            for line in shows:
                step = trip["steps"][line["step"]]
                assert f": {step['name'] or 'another WAY'}, " in line["text"], name
        else:
            assert shows == [], name
        # A warning is under the step that it is about.
        position = {id(line): at for at, line in enumerate(found)}
        for line in found:
            if line["warns"]:
                assert line["text"].startswith("    ! "), name
                above = [other for other in shows if position[id(other)] < position[id(line)]]
                assert above[-1]["step"] == line["step"], name
        warnings = sum(1 for line in each["text"].split("\n") if line.startswith("    ! "))
        assert sum(1 for line in found if line["warns"]) == warnings, name
    assert plans > 10


def test_a_warning_is_tied_to_the_step_above_it() -> None:
    """Alex and Sam would be too late for the flight if the train took its longest."""
    asked = asked_of(EXAMPLES / "flight-home" / "works-but-risky.json")
    (found,) = lines_of([asked])
    trip = cast("dict[str, Any]", asked["trip"])
    flight = [step["option"] for step in trip["steps"]].index("flight")
    (warning,) = [line for line in found if line["warns"]]
    assert warning["text"] == "    ! Alex and Sam would be 5 min too late for this."
    assert warning["step"] == flight
    shows = {
        line["step"]: line["text"]
        for line in found
        if not line["warns"] and line["step"] is not None
    }
    assert shows[flight] == "  5:00 pm to 7:30 pm: Flight home, Alex and Sam"


def test_lines_are_tied_to_steps_only_where_the_plan_is_the_one_that_the_view_sent() -> None:
    """With another plan, or with no TRIP, the report is whole and no line names a step."""
    asked = asked_of(EXAMPLES / "flight-home" / "works.json")
    trip = cast("dict[str, Any]", asked["trip"])
    fewer = {**trip, "steps": trip["steps"][:-1]}
    not_a_plan = {**trip, "itinerary": False}
    for other in (fewer, not_a_plan, None):
        (found,) = lines_of([{**asked, "trip": other}])
        assert "\n".join(line["text"] for line in found) == asked["text"]
        assert all(line["step"] is None and not line["warns"] for line in found)
        # The records are still tied: they do not depend on the plan.
        assert sum(1 for line in found if line["record"] is not None) == len(
            asked["report"]["relies_on"]
        )


def test_a_line_that_only_starts_like_a_record_is_tied_to_none() -> None:
    """The money is in a currency called miles, and a BOOKING has the id miles too.

    The report says what that BOOKING paid on a line that starts with its id, and it gives the
    total in the currency on a line that starts the same way. Only the first names the record.
    """
    written = (EXAMPLES / "a-ticket" / "within-the-cap.json").read_text()
    assert "alex-skydeck-ticket" in written
    file = parse(written.replace("USD", "miles").replace("alex-skydeck-ticket", "miles"))
    found = compiler.check(file)
    as_json = report.as_json(file, found)
    assert "miles" in cast("list[str]", as_json["relies_on"])
    asked = {"text": report.as_text(file, found), "report": as_json, "trip": shown(file, found)}
    (tied,) = lines_of([asked])
    starts_so = [line for line in tied if line["text"].startswith("  miles: ")]
    assert len(starts_so) >= 3
    total = [
        line for line in starts_so if "still to buy" in line["text"] or " paid; " in line["text"]
    ]
    assert total
    assert all(line["record"] is None for line in total)
    assert sum(1 for line in starts_so if line["record"] == "miles") == len(starts_so) - len(total)


def test_a_report_that_names_nothing_the_page_can_read_ties_no_record() -> None:
    asked = asked_of(EXAMPLES / "flight-home" / "cannot-work.json")
    odd: list[Any] = [
        None,
        {},
        {"conflict": "visit-time"},
        {"conflict": [1, None, ["visit-time"]], "relies_on": {"visit-time": True}},
    ]
    for found in lines_of([{**asked, "report": other} for other in odd]):
        assert "\n".join(line["text"] for line in found) == asked["text"]
        assert all(line["record"] is None for line in found)
    # A line that starts like a record, with an id that the report does not name, is tied to none.
    (found,) = lines_of([{**asked, "report": {"conflict": ["visit-time"]}}])
    assert [line["record"] for line in found if line["record"] is not None] == ["visit-time"]
