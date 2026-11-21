"""The page of the view in a real browser.

The other tests of the view run its code without a page: what the command sends, and what the
page's own code lays out. These drive the page itself, in Chromium through Playwright: what the
pointer lights up, where a click goes, whether the pointer can reach each mark, and what stays
on the page when a part of it cannot load.

They need a browser that Playwright has installed: ``uv run playwright install chromium``.
Without one they are skipped, but for the checks on Linux, where they fail.

No test here waits for a length of time. Each waits for what it needs to be on the page.
"""

import json
import os
import sys
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Browser, Page, sync_playwright
from playwright.sync_api import Error as BrowserError

from tests.stories import (
    EXAMPLES,
    budget,
    lasts,
    lock,
    moves,
    named,
    needs_no_right,
    stays,
    takes,
    way_between,
)
from tests.test_view import serving

CHICAGO = "[America/Chicago]"
# The page shows the report on the FILE, and has said what its calendar holds.
ANSWERED = """() => {
  const part = document.getElementById("report-part");
  const line = document.getElementById("line").textContent;
  const answered = /^(FEASIBLE|INFEASIBLE|UNDETERMINED)/.test(line);
  const shown = !part.hidden && !part.classList.contains("old");
  return answered && shown && document.getElementById("calendar-says").textContent !== "";
}"""
# The strip is laid out in the room that the page has for it now.
FITTED = """() => {
  const rows = document.querySelector("#strip .strip-rows");
  const room = document.getElementById("calendar-part").clientWidth - 80;
  return rows !== null && Math.abs(rows.getBoundingClientRect().width - room) < 1;
}"""
# What is lit on the page: the steps of the calendar, the steps with no time beside it, the
# marks of the strip, and the lines of the report.
LIT = """() => {
  const first = (each) => each.title.split("\\n")[0];
  const all = (which) => [...document.querySelectorAll(which)];
  return {
    marks: [...new Set(all("#calendar .mark.lit").map(first))],
    untimed: all("#calendar-untimed .lit").map((each) => each.textContent),
    bars: [...new Set(all("#strip .bar.lit").map(first))],
    rows: all("#report .row.lit").map((row) => row.textContent),
  };
}"""
# For each mark of the strip, how many of 15 by 9 points of it answer the pointer for it.
REACHED = """() => [...document.querySelectorAll("#strip .bar")].map((bar) => {
  const at = (bar.querySelector(".bar-tick, .bar-several") ?? bar).getBoundingClientRect();
  let hits = 0;
  for (let i = 0; i < 15; i += 1) for (let j = 0; j < 9; j += 1) {
    const x = at.left + (at.width * (i + 0.5)) / 15;
    const y = at.top + (at.height * (j + 0.5)) / 9;
    const hit = document.elementFromPoint(x, y);
    if (hit !== null && hit.closest(".bar") === bar) hits += 1;
  }
  return { name: bar.title.split("\\n")[0], hits };
})"""
# Whether the mark of brunch is inside the box of the calendar, and inside the window.
INSIDE = """() => {
  const grid = document.getElementById("calendar").getBoundingClientRect();
  const marks = [...document.querySelectorAll("#calendar .mark")];
  const mark = marks.find((each) => each.title.startsWith("brunch")).getBoundingClientRect();
  return {
    across: mark.left >= grid.left - 1 && mark.right <= grid.right + 1,
    down: mark.top >= -1 && mark.bottom <= innerHeight + 1,
  };
}"""

type Document = dict[str, Any]


@pytest.fixture(scope="session")
def chromium() -> Generator[Browser]:
    """One browser for all these tests."""
    with sync_playwright() as driver:
        try:
            browser = driver.chromium.launch()
        except BrowserError as problem:
            if os.environ.get("CI") and sys.platform == "linux":
                pytest.fail(f"the checks on Linux need a browser: {problem}")
            pytest.skip("needs a browser: uv run playwright install chromium")
        yield browser
        browser.close()


@contextmanager
def opened(
    chromium: Browser, path: Path, wide: int = 1280, without: tuple[str, ...] = ()
) -> Generator[Page]:
    """The page of the view of one FILE, once it shows the report on it.

    ``without`` names files of the page that the browser cannot load. The page loads its
    calendar, the ties of its lines and its strip beside the answer: a test waits for the part
    that it is about.
    """
    with serving(path) as view:
        context = chromium.new_context(viewport={"width": wide, "height": 1000})
        try:
            page = context.new_page()
            problems: list[str] = []
            page.on("pageerror", lambda problem: problems.append(str(problem)))
            for name in without:
                page.route(f"**/{name}", lambda route: route.abort())
            page.goto(view.address)
            page.wait_for_function(ANSWERED, timeout=60_000)
            yield page
            assert problems == []
        finally:
            context.close()


def written(tmp_path: Path, content: Document) -> Path:
    path = tmp_path / "trip.json"
    path.write_text(json.dumps(content))
    return path


def at(option: str, when: str, length: str | None) -> list[Document]:
    """An OPTION that starts then, needs no right, and can be reached up to its start."""
    return [
        {"id": f"{option}-time", "option": option, "starts_at": f"{when}-05:00{CHICAGO}"},
        *([] if length is None else [lasts(option, length)]),
        needs_no_right(option),
        {"id": f"{option}-cutoff", "option": option, "arrive_before_start": "PT0S"},
    ]


def starts(person: str, place: str) -> Document:
    return {"id": f"{person}-starts", "person": person, "starts_from": place}


def ids_of(rows: list[str]) -> list[str]:
    """The ids that these lines of a report start with."""
    return [row.strip().split(":")[0] for row in rows]


def test_the_report_on_the_page_is_the_report_in_words(chromium: Browser) -> None:
    """Character for character, whatever the answer is and however its lines are tied."""
    for name in [
        "flight-home/works-but-risky",
        "flight-home/cannot-work",
        "a-ticket/depends-on-the-price",
        "several-days/works",
    ]:
        path = EXAMPLES / f"{name}.json"
        expected = path.with_name(f"{path.stem}.expected.txt").read_text()
        with opened(chromium, path) as page:
            assert page.text_content("#report") == expected, name
            # So it is once each line is tied to what it is about.
            page.locator("#report .row").first.wait_for()
            assert page.locator("#report .row").count() == len(expected.split("\n")), name
            assert page.text_content("#report") == expected, name


def test_pointing_at_a_step_lights_up_what_the_report_says_of_it(chromium: Browser) -> None:
    """Alex and Sam would be too late for the flight if the train took its longest."""
    with opened(chromium, EXAMPLES / "flight-home" / "works-but-risky.json") as page:
        page.locator("#calendar .mark.warned").first.hover(force=True)
        lit = page.evaluate(LIT)
        assert lit["marks"] == ["Flight home"]
        assert lit["rows"][:2] == [
            "  5:00 pm to 7:30 pm: Flight home, Alex and Sam",
            "    ! Alex and Sam would be 5 min too late for this.",
        ]
        # The other lines are those of the records about the flight, and of no other step.
        records = ids_of(lit["rows"][2:])
        assert {"flight-time", "lock-flight"} <= set(records)
        assert not {"visit-time", "lock-visit"} & set(records)
        # Pointing at the line of a record lights up what the record is about, and that line.
        page.locator("#report .row[data-record='lock-visit']").hover()
        lit = page.evaluate(LIT)
        assert lit["marks"] == ["Museum visit"]
        assert ids_of(lit["rows"]) == ["lock-visit"]
        # With the pointer off the parts of the page, nothing is lit.
        page.mouse.move(2, 2)
        assert page.locator(".lit").count() == 0


def test_pointing_ties_the_strip_the_calendar_and_the_report(chromium: Browser) -> None:
    """On a TRIP of two days, a step is on the strip, on the calendar and in the report."""
    with opened(chromium, EXAMPLES / "several-days" / "works-but-risky.json") as page:
        page.locator("#strip .bar.warned").first.hover(force=True)
        lit = page.evaluate(LIT)
        assert lit["bars"] == lit["marks"]
        assert len(lit["marks"]) == 1
        assert any(row.startswith("    ! ") for row in lit["rows"])
        # And the other way: from the calendar to the strip.
        page.locator("#calendar .mark.locked").first.hover(force=True)
        lit = page.evaluate(LIT)
        assert lit["bars"] == lit["marks"] == ["Dinner"]


def test_a_step_with_no_time_lights_up_alone(chromium: Browser, tmp_path: Path) -> None:
    """Two drives are in one case of the report, and the FILE gives the second no time."""
    content = json.loads((EXAMPLES / "a-driver" / "depends-on-the-car.json").read_text())
    content["facts"] = [each for each in content["facts"] if each["id"] != "drive-back-time"]
    with opened(chromium, written(tmp_path, content)) as page:
        case = page.locator("#report .row[data-record='case:0']")
        case.wait_for()
        untimed = page.locator("#calendar-untimed span")
        assert untimed.count() == 1
        back = untimed.first.text_content()
        assert back is not None and back.startswith("Drive back to the hotel")
        # Pointing at the drive on the calendar lights up that drive, and the line of its case.
        page.locator("#calendar .mark.asked").first.hover(force=True)
        lit = page.evaluate(LIT)
        assert (lit["marks"], lit["untimed"]) == (["Drive to the dunes"], [])
        assert len(lit["rows"]) == 1 and lit["rows"][0].startswith("The trip works if ")
        # Pointing at the drive with no time lights up that one.
        untimed.first.hover()
        lit = page.evaluate(LIT)
        assert (lit["marks"], lit["untimed"]) == ([], [back])
        # Pointing at the line of the case lights up both.
        case.hover()
        lit = page.evaluate(LIT)
        assert (lit["marks"], lit["untimed"]) == (["Drive to the dunes"], [back])


def test_a_mark_for_several_steps_says_what_the_report_says_of_each(
    chromium: Browser, tmp_path: Path
) -> None:
    """Two stops two minutes apart, and a third a month later. The first has no length."""
    stops = ["first-stop", "second-stop", "third-stop"]
    content = {
        "persons": named("alex"),
        "places": named("station"),
        "budgets": [budget("money", "alex")],
        "options": [stays(stop, "station") for stop in stops],
        "ways": [],
        "wants": [],
        "facts": [
            *at("first-stop", "2027-05-15T08:00:00", None),
            *at("second-stop", "2027-05-15T08:02:00", "PT1M"),
            *at("third-stop", "2027-06-14T19:00:00", "PT1M"),
            starts("alex", "station"),
        ],
        "decisions": [lock(stop, "alex") for stop in stops],
    }
    with opened(chromium, written(tmp_path, content), wide=700) as page:
        page.locator("#report .row[data-record='case:0']").wait_for()
        several = page.locator("#strip .bar.several.asked")
        several.wait_for()
        assert page.locator("#strip .bar.several").count() == 1
        assert several.get_attribute("title") == "\n".join(
            [
                "2 steps too close together to show apart at this width:",
                "first-stop, 8:00 am to an unknown time",
                "    The trip works if first-stop takes 2 min or less.",
                "second-stop, 8:02 am to 8:03 am",
            ]
        )
        # Pointing at it lights up both steps on the calendar, and the line of the case.
        several.locator(".bar-several").hover(force=True)
        lit = page.evaluate(LIT)
        assert lit["marks"] == ["first-stop", "second-stop"]
        assert lit["rows"] == ["The trip works if first-stop takes 2 min or less."]


def crowded() -> Document:
    """Three WAYs of a minute each to a train just after midnight, and brunch two weeks later."""
    ways = [("door", "room", "hall"), ("stairs", "hall", "street"), ("gate", "street", "station")]
    return {
        "persons": named("alex", "sam"),
        "places": named("room", "hall", "street", "station", "city"),
        "budgets": [budget("money", "alex", "sam")],
        "options": [moves("train", "station", "city"), stays("brunch", "city")],
        "ways": [way_between(way, first, second) for way, first, second in ways],
        "wants": [],
        "facts": [
            *at("train", "2027-05-15T00:04:00", "PT2H"),
            *at("brunch", "2027-05-29T10:00:00", "PT1H"),
            *[takes(way, "PT1M") for way, _, _ in ways],
            starts("alex", "room"),
            starts("sam", "room"),
        ],
        "decisions": [
            lock("train", "alex", "sam"),
            lock("brunch", "alex"),
            {"id": "trip-start", "trip_starts_at": f"2027-05-15T00:00:00-05:00{CHICAGO}"},
        ],
    }


def test_the_pointer_can_reach_every_mark_of_the_strip(chromium: Browser, tmp_path: Path) -> None:
    """However narrow the window is, and however close together the steps are."""
    with opened(chromium, written(tmp_path, crowded())) as page:
        assert (page.text_content("#line") or "").startswith("FEASIBLE")
        page.wait_for_function(FITTED)
        # The three WAYs of a minute are one mark in each PERSON's row, which names each.
        several = page.locator("#strip .bar.several")
        assert several.count() == 2
        title = several.first.get_attribute("title") or ""
        assert title.startswith("3 steps too close together to show apart at this width:")
        assert [line.split(",")[0] for line in title.split("\n")[1:]] == ["door", "stairs", "gate"]
        for wide in [1280, 700, 420]:
            page.set_viewport_size({"width": wide, "height": 1000})
            # The strip is laid out again in the room that the window has.
            page.wait_for_function(FITTED)
            reached = page.evaluate(REACHED)
            assert reached, wide
            assert [each for each in reached if not each["hits"]] == [], wide
            rows = page.locator("#strip .strip-rows").bounding_box()
            box = page.locator("#strip").bounding_box()
            assert rows is not None and box is not None
            assert rows["x"] + rows["width"] <= box["x"] + box["width"], wide


def test_a_click_on_the_strip_brings_the_step_into_view(chromium: Browser, tmp_path: Path) -> None:
    """Four PERSONs and three days: in a narrow window the calendar is wider than its box."""
    persons = ["alex", "sam", "jo", "max"]
    days = {"dinner": "2027-05-14T19:00:00", "lunch": "2027-05-15T12:00:00"}
    content = {
        "persons": named(*persons),
        "places": named("hotel"),
        "budgets": [budget("money", *persons)],
        "options": [stays(option, "hotel") for option in [*days, "brunch"]],
        "ways": [],
        "wants": [],
        "facts": [
            *[fact for option, when in days.items() for fact in at(option, when, "PT1H")],
            *at("brunch", "2027-05-16T10:00:00", "PT1H"),
            *[starts(person, "hotel") for person in persons],
        ],
        "decisions": [lock(option, *persons) for option in [*days, "brunch"]],
    }
    with opened(chromium, written(tmp_path, content), wide=620) as page:
        page.wait_for_function(FITTED)
        grid = page.locator("#calendar")
        assert grid.evaluate("(grid) => grid.scrollWidth > grid.clientWidth + 100")
        assert page.evaluate(INSIDE)["across"] is False
        page.locator("#strip .bar").last.click(force=True)
        assert page.evaluate(INSIDE) == {"across": True, "down": True}
        assert grid.evaluate("(grid) => grid.scrollLeft") > 0


def test_the_page_shows_what_it_can_without_a_part_that_cannot_load(chromium: Browser) -> None:
    path = EXAMPLES / "several-days" / "works-but-risky.json"
    expected = path.with_name(f"{path.stem}.expected.txt").read_text()
    # Without the strip: the calendar, with its marks and its yellow edge.
    with opened(chromium, path, without=("strip.js",)) as page:
        page.locator("#calendar .mark.warned").wait_for()
        assert page.locator("#calendar .mark.warned").count() == 1
        assert page.locator("#calendar .mark").count() > 3
        assert page.locator("#strip").is_hidden()
        assert page.text_content("#report") == expected
    # Without the calendar: the answer and the report, and the page says what is missing.
    with opened(chromium, path, without=("calendar.js",)) as page:
        page.locator("#report .row").first.wait_for()
        assert page.text_content("#calendar-says") == "The page could not load its calendar."
        assert page.locator("#calendar").is_hidden()
        assert page.locator("#strip").is_hidden()
        assert (page.text_content("#line") or "").startswith("FEASIBLE")
        assert page.text_content("#report") == expected
    # Without the ties of the lines: the report as it is, and a calendar with no yellow edge.
    # The page asks for its strip last, so with the strip on the page nothing is still to come.
    with opened(chromium, path, without=("lines.js",)) as page:
        page.locator("#strip .bar").first.wait_for()
        assert page.text_content("#report") == expected
        assert page.locator("#report .row").count() == 0
        assert page.locator("#calendar .mark").count() > 3
        assert page.locator("#calendar .mark.warned").count() == 0
