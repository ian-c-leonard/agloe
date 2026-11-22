"""The lines of a report in words, and what on the calendar each line is about.

A report in words shows the plan one step to a line, and under a step what it warns of. It shows
each FACT, WANT and DECISION that it names on a line that starts with its id. Where a trip
depends on what the FILE does not say, it shows each case in which the trip works on a line.
So the page can tie a line to the step it shows, to the record it names, or to the case it
states. ``src/agloe/view/static/lines.js`` does that. It has no page in it, so Node runs it
here, through ``view_lines.mjs``.

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
    plans = depends = requirements = purchases = 0
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
        shows = [
            line
            for line in found
            if line["step"] is not None and not line["warns"] and line["meets"] is None
        ]
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
        # Each requirement that the report says somebody meets has one line, in the order of
        # the report as JSON, and that line is about the step that its OPTION is.
        met = said.get("requirements", [])
        meets = [line for line in found if line["meets"] is not None]
        assert [line["meets"] for line in meets] == list(range(len(met))), name
        requirements += bool(met)
        for line in meets:
            step = trip["steps"][line["step"]]
            assert step["option"] == met[line["meets"]]["option"], name
            # Where the FILE does not say what the OPTION requires, the line says that first.
            assert f"{step['name']} requires " in line["text"], name
            assert line["record"] is None and line["case"] is None and not line["warns"], name
        # Each place that the plan still buys has a warning that is tied to its OFFER, and no
        # line is tied to an OFFER that the report as JSON does not have somebody buy from.
        to_buy = {buy["offer"] for buy in said.get("to_buy", [])}
        in_plans = {buy["offer"] for plan in said.get("plans", []) for buy in plan["buys"]}
        tied_to = {offer for line in found for offer in line["offers"]}
        assert tied_to <= to_buy | in_plans, name
        assert to_buy <= tied_to, name
        purchases += bool(tied_to)
        # Each case in which the trip works has one line, in the order of the report as JSON.
        missing = said.get("missing", [])
        states = [line for line in found if line["case"] is not None]
        assert [line["case"] for line in states] == list(range(len(missing))), name
        depends += bool(missing)
        for line in states:
            assert line["step"] is None and line["record"] is None, name
            # One case is a sentence. It says that the trip works, or that it might.
            one = ("The trip works if ", "The trip might work if ")
            starts = one if len(missing) == 1 else (f"  {line['case'] + 1}. ",)
            assert line["text"].startswith(starts), name
    assert plans > 10
    assert depends > 10
    assert requirements > 2
    assert purchases > 2


def test_a_line_about_a_requirement_is_tied_whatever_the_name_of_its_option_starts_with(
    tmp_path: Path,
) -> None:
    """The name of the first drive starts with a space. The report sets its line in further."""
    content = json.loads((EXAMPLES / "a-driver" / "works.json").read_text())
    content["options"][0]["name"] = " Drive to the dunes"
    path = tmp_path / "trip.json"
    path.write_text(json.dumps(content))
    asked = asked_of(path)
    assert "\n   Drive to the dunes requires driving a manual car of one PERSON." in asked["text"]
    (found,) = lines_of([asked])
    meets = [line for line in found if line["meets"] is not None]
    assert [(line["meets"], line["step"]) for line in meets] == [(0, 0), (1, 1)]
    assert meets[1]["text"].startswith("  Drive back to the hotel requires ")


def test_a_line_that_says_who_buys_a_place_is_tied_to_the_offer() -> None:
    """Sam still has to buy a right to the Skydeck visit, from the OFFER skydeck-tickets."""
    asked = asked_of(EXAMPLES / "a-ticket" / "not-bought-yet.json")
    (found,) = lines_of([asked])
    buys = [line for line in found if line["offers"]]
    assert [(line["offers"], line["step"], line["warns"]) for line in buys] == [
        (["skydeck-tickets"], 0, True)
    ]
    assert buys[0]["text"].startswith("    ! Sam still has to buy a right to this, from ")
    # A report that names another OFFER for that step, or none, leaves the line tied to none.
    odd: list[Any] = [
        [{**asked["report"]["to_buy"][0], "offer": "skydeck"}],
        [{**asked["report"]["to_buy"][0], "option": "lunch"}],
        "skydeck-tickets",
        [],
    ]
    for to_buy in odd:
        (other,) = lines_of([{**asked, "report": {**asked["report"], "to_buy": to_buy}}])
        assert all(line["offers"] == [] for line in other)
    # A warning about something else names no OFFER.
    (late,) = lines_of([asked_of(EXAMPLES / "flight-home" / "works-but-risky.json")])
    assert any(line["warns"] for line in late)
    assert all(line["offers"] == [] for line in late)


def test_the_plan_that_a_report_gives_for_a_case_is_tied_to_the_offers_it_buys_from() -> None:
    """The trip works if the FILE states what a BOOKING paid. Then Sam buys a place."""
    asked = asked_of(EXAMPLES / "a-ticket" / "depends-on-the-receipt.json")
    (found,) = lines_of([asked])
    buys = [line for line in found if line["offers"]]
    assert [(line["offers"], line["case"], line["step"]) for line in buys] == [
        (["skydeck-tickets"], None, None)
    ]
    assert buys[0]["text"].startswith("  One plan that works then: Sam buys a place from ")
    # The line of the case is above it, and is tied to the case alone.
    (case,) = [line for line in found if line["case"] is not None]
    assert (case["case"], case["offers"]) == (0, [])
    # A report with no plan for each of its cases ties no line to an OFFER.
    odd: list[Any] = [[], "x", [{"buys": [{"offer": 1}]}], [{}, {}]]
    for plans in odd:
        (other,) = lines_of([{**asked, "report": {**asked["report"], "plans": plans}}])
        assert all(line["offers"] == [] for line in other)


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


def test_a_case_in_which_the_trip_works_is_tied_to_its_line() -> None:
    """One case is a sentence. Several are a list, numbered in the order of the report as JSON."""
    one = asked_of(EXAMPLES / "several-days" / "depends-on-the-night.json")
    two = asked_of(EXAMPLES / "a-kayak-tour" / "two-things-left-open.json")
    assert (len(one["report"]["missing"]), len(two["report"]["missing"])) == (1, 2)
    first, second = lines_of([one, two])
    assert [(line["case"], line["text"]) for line in first if line["case"] is not None] == [
        (0, "The trip works if Night at the hotel takes 8 h 30 min or less.")
    ]
    assert [(line["case"], line["text"]) for line in second if line["case"] is not None] == [
        (
            0,
            "  1. Kayak tour requires swimming of one PERSON who takes part, or does not"
            " require it.",
        ),
        (1, "  2. Jo has the CAPABILITY swimming."),
    ]


def test_a_line_that_only_looks_like_a_case_is_tied_to_none() -> None:
    """A BUDGET is named like the first of a list, and the report lists the BUDGETs of the FILE."""
    written = (EXAMPLES / "a-ticket" / "depends-on-the-price.json").read_text()
    assert '"the trip money"' in written
    file = parse(written.replace('"the trip money"', '"1. the trip money"'))
    found = compiler.check(file)
    asked = {
        "text": report.as_text(file, found),
        "report": report.as_json(file, found),
        "trip": shown(file, found),
    }
    (tied,) = lines_of([asked])
    numbered = [line for line in tied if line["text"].startswith("  1. ")]
    assert [line["text"][:24] for line in numbered] == [
        "  1. A right to Skydeck ",
        "  1. the trip money: for",
    ]
    assert [line["case"] for line in numbered] == [0, None]
    assert [line["case"] for line in tied if line["case"] is not None] == [0, 1]


def test_what_a_report_says_under_a_case_is_between_the_lines_of_the_cases() -> None:
    """With a cap on what a BUDGET spends, the report shows a plan under each case."""
    written = json.loads((EXAMPLES / "a-ticket" / "depends-on-the-price.json").read_text())
    cap = {
        "id": "trip-cap",
        "budget": "trip-money",
        "spend_at_most": {"amount": "200.00", "currency": "USD"},
    }
    written["decisions"].append(cap)
    file = parse(json.dumps(written))
    found = compiler.check(file)
    in_words = report.as_text(file, found)
    as_json = report.as_json(file, found)
    assert len(cast("list[Any]", as_json["missing"])) == 2
    asked = {"text": in_words, "report": as_json, "trip": shown(file, found)}
    (tied,) = lines_of([asked])
    states = [line for line in tied if line["case"] is not None]
    assert [(line["case"], line["text"][:30]) for line in states] == [
        (0, "  1. A right to Skydeck visit "),
        (1, "  2. A place from skydeck-tick"),
    ]
    # Between the two is what the report says of the first case, further in.
    first, second = (tied.index(line) for line in states)
    between = tied[first + 1 : second]
    assert between
    assert all(line["text"].startswith("     ") and line["case"] is None for line in between)
    # With a line numbered out of turn under the heading, the words are not the cases of the
    # report as JSON, and nothing is tied.
    lines = in_words.split("\n")
    out_of_turn = "\n".join([*lines[: second + 1], "  4. Something else.", *lines[second + 1 :]])
    (tied,) = lines_of([{**asked, "text": out_of_turn}])
    assert all(line["case"] is None for line in tied)


def test_cases_are_tied_only_where_the_report_states_each_of_them() -> None:
    """With another report as JSON, the report in words is whole and no line states a case."""
    asked = asked_of(EXAMPLES / "a-kayak-tour" / "two-things-left-open.json")
    said = asked["report"]
    odd: list[Any] = [
        None,
        {},
        # Another answer, more cases or fewer than the words list, and what is no list of cases.
        {**said, "answer": "FEASIBLE"},
        {**said, "missing": [*said["missing"], said["missing"][0]]},
        {**said, "missing": said["missing"][:1]},
        {**said, "missing": "swimming"},
        {**said, "missing": [said["missing"][0], "swimming"]},
        {**said, "missing": [said["missing"][0], [None]]},
        {**said, "missing": []},
    ]
    for found in lines_of([{**asked, "report": other} for other in odd]):
        assert "\n".join(line["text"] for line in found) == asked["text"]
        assert all(line["case"] is None for line in found)


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
