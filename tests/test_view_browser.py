"""The page of the view in a real browser.

The other tests of the view run its code without a page: what the command sends, and what the
page's own code lays out. These drive the page itself, in Chromium through Playwright: what the
pointer lights up, where a click goes, whether the pointer can reach each mark, and what stays
on the page when a part of it cannot load.

They need a browser that Playwright has installed: ``uv run playwright install chromium``.
Without one they are skipped, but for the checks on Linux, where they fail.

No test waits for a length of time. Each waits for what it needs to be on the page. The page
loads its calendar, the ties of its lines and its strip beside the answer, and draws again as
each arrives. So a test also waits for what it expects to be lit, and never reads it at once.
"""

import contextlib
import http.client
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import threading
from collections.abc import Generator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Browser, Page, Route, sync_playwright
from playwright.sync_api import Error as BrowserError

from agloe.view import View
from agloe.view.check import checked
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
from tests.test_view import port_of, put, serving, stand_in

CHICAGO = "[America/Chicago]"
# The page shows the report on the FILE, and has said what its calendar holds.
ANSWERED = """() => {
  const part = document.getElementById("report-part");
  const line = document.getElementById("line").textContent;
  const answered = /^(FEASIBLE|INFEASIBLE|UNDETERMINED)/.test(line);
  const shown = !part.hidden && !part.classList.contains("old");
  return answered && shown && document.getElementById("calendar-says").textContent !== "";
}"""
# The strip is laid out in the room that the page has for its rows now.
FITTED = """() => {
  const box = document.getElementById("strip");
  const rows = box.querySelector(".strip-rows");
  const names = box.querySelector(".strip-people");
  if (box.hidden || rows === null || names === null) return false;
  const style = getComputedStyle(box);
  const sides = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
  const room = box.clientWidth - sides - names.getBoundingClientRect().width;
  return Math.abs(rows.getBoundingClientRect().width - room) < 1;
}"""
# What is lit on the page: the steps of the calendar, the steps with no time beside it, the
# marks of the strip, the names of the PERSONs over their columns of the calendar and beside
# their rows of the strip, the lines of the report, the PERSONs, the PLACEs with the OPTIONs and
# the WAYs under them, the WANTs with the OPTIONs under
# them, the OPTIONs of the FILE, the rights to them with their BOOKINGs and OFFERs, the
# BUDGETs with their caps and payments, its WAYs, the travel that it lists in full, the
# CAPABILITIES with the PERSONs and the OPTIONs under them, and the OBJECTs with the OPTIONs
# under them.
LIT = """() => {
  const first = (each) => each.title.split("\\n")[0];
  const all = (which) => [...document.querySelectorAll(which)];
  return {
    marks: [...new Set(all("#calendar .mark.lit").map(first))],
    untimed: all("#calendar-untimed .lit").map((each) => each.textContent),
    bars: [...new Set(all("#strip .bar.lit").map(first))],
    heads: [...new Set(all("#calendar .person.lit").map((each) => each.textContent))],
    beside: all("#strip .strip-people .lit").map((each) => each.textContent),
    rows: all("#report .row.lit").map((row) => row.textContent),
    wants: all("#wants .lit").map((each) => each.querySelector("h3, b").textContent),
    options: all("#options .item.lit").map((each) => each.querySelector("h3").textContent),
    persons: all("#persons .item.lit").map((each) => each.querySelector("h3").textContent),
    places: all("#places .lit").map((each) => each.querySelector("h3, b").textContent),
    rights: all("#rights .lit").map((each) => each.querySelector("h3, b").textContent),
    budgets: all("#budgets .lit").map((each) => each.querySelector("h3, b").textContent),
    objects: all("#objects .lit").map((each) => each.querySelector("h3, b").textContent),
    ways: all("#ways .item.lit").map((each) => each.querySelector("h3").textContent),
    travel: all("#travel .in-full.lit").map((each) => each.textContent),
    capabilities: all("#capabilities .lit").map((each) => each.querySelector("h3, b").textContent),
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
# Each step of the calendar in the column of each of its PERSONs, and those of them that no
# mark of the strip stands for in that PERSON's row. For a calendar with no lanes.
STANDS_FOR = """() => {
  const all = (which, inside = document) => [...inside.querySelectorAll(which)];
  const people = all("#strip .strip-people span").length;
  const hue = (each) => [...each.classList].find((name) => /^p[0-9]$/.test(name));
  const rowOf = (each) => Number(hue(each).slice(1));
  const wanted = new Set();
  for (const mark of all("#calendar .mark")) {
    for (const stripe of all(".stripe", mark)) wanted.add(`${mark.dataset.of}:${rowOf(stripe)}`);
  }
  const there = new Set();
  for (const bar of all("#strip .bar")) {
    const lines = all(".bar-line, .bar-tick, .bar-several", bar);
    const first = Math.round((parseFloat(bar.style.top) * people) / 100);
    const count = Math.max(Math.round((parseFloat(bar.style.height) * people) / 100), 1);
    const block = Array.from({ length: count }, (_, n) => first + n);
    const rows = lines.length ? lines.map(rowOf) : block;
    for (const step of bar.dataset.of.split(" ")) {
      for (const row of rows) there.add(`${step}:${row}`);
    }
  }
  const missing = [...wanted].filter((each) => !there.has(each));
  return { wanted: [...wanted].sort(), missing: missing.sort() };
}"""
# Whether the mark of a step is inside the box of the calendar, and inside the window.
INSIDE = """(name) => {
  const grid = document.getElementById("calendar").getBoundingClientRect();
  const marks = [...document.querySelectorAll("#calendar .mark")];
  const mark = marks.find((each) => each.title.startsWith(name)).getBoundingClientRect();
  return {
    across: mark.left >= grid.left - 1 && mark.right <= grid.right + 1,
    down: mark.top >= -1 && mark.bottom <= innerHeight + 1,
  };
}"""
# Where the report and the drawings are in the window, and which lines of the report that are
# lit are wholly inside the box of the report.
PLACED = """() => {
  const box = (id) => document.getElementById(id).getBoundingClientRect();
  const sides = ({ left, right, top, bottom }) => ({ left, right, top, bottom });
  const report = box("report");
  const lit = [...document.querySelectorAll("#report .row.lit")];
  // A line is shown where it is inside the box of the report and inside the window.
  const inside = (row) => {
    const at = row.getBoundingClientRect();
    return at.top >= Math.max(report.top, 0) && at.bottom <= Math.min(report.bottom, innerHeight);
  };
  const text = document.getElementById("report");
  return {
    report: sides(box("report-part")),
    drawings: sides(box("drawings")),
    lit: lit.length,
    shown: lit.filter(inside).length,
    tall: innerHeight,
    scrolls: text.scrollHeight > text.clientHeight,
    page: scrollY,
    at: text.scrollTop,
  };
}"""
# Whether what is lit on the page is what a test expects of it.
IS_LIT = f"""(expected) => {{
  const lit = ({LIT})();
  const same = ([part, value]) => JSON.stringify(lit[part]) === JSON.stringify(value);
  return Object.entries(expected).every(same);
}}"""

type Document = dict[str, Any]


@pytest.fixture(scope="session")
def chromium() -> Generator[Browser]:
    """One browser for all these tests.

    Only a machine with no browser installed skips them. Any other failure to start one is a
    failure, as is a missing browser in the checks on Linux.
    """
    with sync_playwright() as driver:
        try:
            browser = driver.chromium.launch()
        except BrowserError as problem:
            missing = "Executable doesn't exist" in str(problem)
            if not missing or (os.environ.get("CI") and sys.platform == "linux"):
                raise
            pytest.skip("needs a browser: uv run playwright install chromium")
        yield browser
        browser.close()


@contextmanager
def opened(
    chromium: Browser,
    path: Path,
    wide: int = 1280,
    tall: int = 1000,
    without: tuple[str, ...] = (),
    held: tuple[str, list[Route]] | None = None,
    faulty: tuple[str, str, list[str]] | None = None,
    python: str = sys.executable,
    once: str = ANSWERED,
    views: list[View] | None = None,
) -> Generator[Page]:
    """The page of the view of one FILE, once it shows the report on it.

    ``without`` names files of the page that the browser cannot load. ``held`` names one that
    the browser gets only when the test lets it: the test finds its request in the list.
    ``faulty`` names one that the browser gets with other code in it, and the list that takes
    the faults of the page, which are then no failure of the test. ``python`` is the program
    that checks the FILE, where a test stands another one in, and ``once`` says what the page
    shows when such a test wants it. ``views`` takes the view itself, for a test that cuts the
    page off from it.
    """
    with serving(path, python=python) as view:
        if views is not None:
            views.append(view)
        context = chromium.new_context(viewport={"width": wide, "height": tall})
        try:
            page = context.new_page()
            problems: list[str] = [] if faulty is None else faulty[2]
            page.on("pageerror", lambda problem: problems.append(str(problem)))
            for name in without:
                page.route(f"**/{name}", lambda route: route.abort())
            # The page counts its own faults, so that a test can wait for one.
            page.add_init_script(
                "window.faults = 0; addEventListener('error', () => { window.faults += 1; });"
            )
            if faulty is not None:
                code = faulty[1]
                page.route(
                    f"**/{faulty[0]}",
                    lambda route: route.fulfill(body=code, content_type="text/javascript"),
                )
            if held is not None:
                requests = held[1]
                page.route(f"**/{held[0]}", lambda route: requests.append(route))
            page.goto(view.address)
            page.wait_for_function(once, timeout=60_000)
            yield page
            assert faulty is not None or problems == []
        finally:
            context.close()


def cut_off(view: View) -> None:
    """End every connection that a page has to the view, as a network that fails does."""
    with view.changed:
        pages = list(view.pages)
    for page in pages:
        with contextlib.suppress(OSError):
            page.shutdown(socket.SHUT_RDWR)


def lit(page: Page, **expected: list[str]) -> dict[str, list[str]]:
    """What is lit on the page, once these parts of it are lit as expected."""
    page.wait_for_function(IS_LIT, arg=expected)
    found: dict[str, list[str]] = page.evaluate(LIT)
    return found


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


def test_the_page_draws_the_file_before_the_report_comes(chromium: Browser, tmp_path: Path) -> None:
    """A report can take minutes. What the FILE holds is on the page once the view has read it."""
    path = tmp_path / "trip.json"
    path.write_bytes((EXAMPLES / "ending-in-denver" / "works.json").read_bytes())
    first, answer, report = (json.dumps(event) for event in checked(path.read_bytes()))
    # In the place of the check: it says what it read and the answer at once, and gives the
    # report when the test lets it.
    (tmp_path / "python.first").write_text(f"{first}\n{answer}\n")
    (tmp_path / "python.report").write_text(f"{report}\n")
    go = tmp_path / "python.go"
    waits = 'cat "$0.first"\nwhile [ ! -e "$0.go" ]; do sleep 0.05; done\ncat "$0.report"'
    # The page shows the answer, and has said what its calendar holds.
    answered = """() => {
      const said = (id) => document.getElementById(id).textContent;
      return said("line").startsWith("FEASIBLE") && said("calendar-says") !== "";
    }"""
    # Nothing on the page is marked as old, and the report is on its way.
    waiting_again = """() => {
      const line = document.getElementById("line").textContent;
      return document.querySelectorAll(".old").length === 0 && line.endsWith("on its way.");
    }"""
    views: list[View] = []
    held = stand_in(tmp_path, waits)
    with opened(chromium, path, python=held, once=answered, views=views) as page:
        # The answer is on the page, and the report is not.
        assert (page.text_content("#line") or "").endswith("The report is on its way.")
        assert page.locator("#report-part").is_hidden()
        # The page draws the FILE all the same.
        page.locator("#persons .item").first.wait_for()
        page.locator("#options .item").first.wait_for()
        assert page.locator("#persons .item-name").all_text_contents() == ["Alex", "Sam"]
        assert page.locator("#places .card-name").all_text_contents() == [
            "the hotel",
            "the Art Institute",
            "O'Hare",
            "Denver",
        ]
        assert page.locator("#options .item").count() == 3
        assert page.locator("#wants .card").count() == 1
        assert page.locator("#ways .item").count() == 1
        # The calendar holds what a LOCK names, and says that there is no report yet. Nothing
        # on the page speaks of a plan, and nothing is marked.
        page.locator("#calendar .mark").first.wait_for()
        assert (page.text_content("#calendar-says") or "").startswith(
            "The page has no report on this FILE yet."
        )
        assert page.locator("#calendar .mark").count() == 1
        assert "In the plan" not in (page.text_content("#drawings") or "")
        marked = "#drawings :is(.clash, .asked, .warned):not(.key-box)"
        assert page.locator(marked).count() == 0
        assert page.locator(".old").count() == 0
        # Pointing ties the drawings of one step, with no line of a report to tie them to.
        page.locator("#options .item", has_text="Museum visit").hover()
        found = lit(page, options=["Museum visit"], marks=["Museum visit"])
        assert found["rows"] == []
        # The FILE is taken away, and the page has no report to fall back on. What it draws
        # stays, marked as on the FILE as it was, and the page says so.
        content = path.read_bytes()
        path.unlink()
        page.locator("#calendar-part.old").wait_for()
        assert (page.text_content("#line") or "").startswith("The FILE cannot be read")
        assert page.locator("#persons-part.old, #places-part.old, #options-part.old").count() == 3
        assert page.locator("#persons .item").count() == 2
        assert page.locator("#calendar .mark").count() == 1
        assert (page.text_content("#note") or "").endswith(
            "What the page shows below is on the FILE as it was before."
        )
        # The FILE is back: the page draws it as it is now.
        put(path, content)
        page.wait_for_function(waiting_again)
        assert page.locator("#persons .item").count() == 2
        # The page loses the view. What it draws is the last that it saw of the FILE, and it
        # is marked so. It finds the view again: nothing is marked, and the answer stands.
        cut_off(views[0])
        page.locator("#calendar-part.old").wait_for()
        assert page.text_content("#line") == "The view is not answering."
        assert page.locator("#persons-part.old").count() == 1
        # The page says what it said last, and that what it shows is the last it was sent.
        note = page.text_content("#note") or ""
        assert "When the page last heard the view, it said: FEASIBLE. The report is on" in note
        assert note.endswith("The FILE may have changed since then.")
        page.wait_for_function(waiting_again, timeout=20_000)
        # The keyboard is on a link of the row. It stays there when the page says more.
        page.locator("#contents .to", has_text="OPTIONs").focus()
        # The report comes: the page draws the plan, and ties the report to it.
        go.write_text("")
        page.locator("#report .row").first.wait_for()
        page.wait_for_function("() => document.querySelectorAll('#calendar .mark').length > 1")
        assert (page.text_content("#calendar-says") or "").startswith(
            "The ITINERARY of the report."
        )
        assert "In the plan: Alex and Sam take part." in (page.text_content("#options") or "")
        assert page.locator(".old").count() == 0
        assert page.evaluate("() => document.activeElement.getAttribute('href')") == "#options-part"
        # The page loses the view and finds it again, with the report on the page. It marks
        # what it shows while it hears nothing. Then all of it stands as it was: the page
        # never says that a report which it shows is on its way.
        line = page.text_content("#line")
        cut_off(views[0])
        page.locator("#report-part.old").wait_for()
        assert page.locator("#calendar-part.old").count() == 1
        # Each link of the row is pale where its part is, and says why. The page knows of no
        # change to the FILE, so the link speaks of none.
        links = page.locator("#contents .to")
        assert page.locator("#contents .to.old").count() == links.count() > 5
        assert links.first.get_attribute("title") == (
            "What this part shows is the last that the view sent."
        )
        page.wait_for_function(
            """(line) => document.querySelectorAll(".old").length === 0
              && document.getElementById("line").textContent === line""",
            arg=line,
            timeout=20_000,
        )
        assert page.locator("#report .row").count() > 5
        # The FILE changes. As soon as the view has read it, the page draws the FILE as it is
        # now, with no report. The report in words is still on the FILE as it was: it is
        # marked so, the page says which is which, and its lines are tied to nothing.
        go.unlink()
        changed = json.loads(path.read_text())
        changed["persons"][0]["name"] = "Alexandra"
        (tmp_path / "python.first").write_text(
            "".join(
                f"{json.dumps(event)}\n"
                for event in list(checked(json.dumps(changed).encode()))[:2]
            )
        )
        path.write_text(json.dumps(changed))
        page.locator("#persons .item-name", has_text="Alexandra").wait_for()
        # The link to the report is pale with it, and says that the FILE has changed.
        assert page.locator("#contents .to.old").all_text_contents() == ["The COMPILER's report"]
        assert page.locator("#contents .to.old").get_attribute("title") == (
            "What this part shows is on the FILE as it was before."
        )
        assert (page.text_content("#note") or "").endswith(
            "The report below is on the FILE as it was before."
        )
        assert page.locator("#report-part.old").count() == 1
        assert page.locator("#drawings .old").count() == 0
        assert page.locator("#report .row").count() == 0
        assert "Alex and Sam" in (page.text_content("#report") or "")
        assert "In the plan" not in (page.text_content("#drawings") or "")


def test_a_row_of_links_leads_to_each_part_of_the_page(chromium: Browser, tmp_path: Path) -> None:
    """One link for each part that the page shows, marked where the report names something."""
    # The heading of each part that the page shows, and the words of each link.
    shown = """() => {
      const parts = [...document.querySelectorAll("#drawings > section, #report-part")];
      const links = [...document.querySelectorAll("#contents .to")];
      const heading = (each) => each.querySelector("h2").textContent;
      return {
        parts: parts.filter((each) => !each.hidden).map(heading),
        links: links.map((each) => each.firstChild.textContent),
        counts: links.map((each) => each.querySelector(".count").textContent || null),
      };
    }"""
    # For each link: whether it has an edge of this kind, and whether something in its part has.
    edges = """(kind) => [...document.querySelectorAll("#contents .to")].map((link) => {
      const part = document.querySelector(link.getAttribute("href"));
      return [link.classList.contains(kind), part.querySelector(`.${kind}:not(.key-box)`) !== null];
    })"""
    story = EXAMPLES / "the-bags"
    with opened(chromium, story / "nobody-collects-them.json", wide=1100, tall=800) as page:
        page.locator("#objects .card").first.wait_for()
        page.wait_for_function("() => document.querySelectorAll('#contents .to').length === 9")
        found = page.evaluate(shown)
        # In the order of the page, each with the heading of its part. This FILE has no WANT,
        # no BUDGET of its own to show and no CAPABILITY, so the row has no link for them.
        assert found["links"] == found["parts"]
        assert found["links"] == [
            "To do and to decide",
            "Calendar",
            "PERSONs",
            "PLACEs",
            "OPTIONs",
            "BOOKINGs and OFFERs",
            "WAYs",
            "OBJECTs",
            "The COMPILER's report",
        ]
        # A part that holds things says how many.
        # What is open is counted too: four records rule out every plan.
        assert found["counts"] == ["4", None, "2", "4", "2", "2", "2", "1", None]
        # A link has the red edge where something in its part has it, and only there.
        red = page.evaluate(edges, "clash")
        assert all(link is part for link, part in red)
        on = [True, True, False, True, True, False, False, True, False]
        assert [link for link, _ in red] == on
        assert page.locator("#contents .to.asked").count() == 0
        # A click brings the part into view under the row, and the row stays at the top.
        page.locator("#contents .to", has_text="OPTIONs").click()
        page.wait_for_function(
            """() => {
              const row = document.getElementById("contents").getBoundingClientRect();
              const part = document.getElementById("options-part").getBoundingClientRect();
              return scrollY > 0 && row.top === 0 && part.top >= row.bottom - 1 && part.top < 100;
            }"""
        )
        # The last part is as far up as the page goes, and in view.
        page.locator("#contents .to", has_text="OBJECTs").click()
        page.wait_for_function(
            """() => {
              const row = document.getElementById("contents").getBoundingClientRect();
              const part = document.getElementById("objects-part").getBoundingClientRect();
              return row.top === 0 && part.top >= row.bottom - 1 && part.top < innerHeight / 2;
            }"""
        )
        # The keyboard reaches each link.
        page.locator("#contents .to").nth(1).focus()
        page.keyboard.press("Tab")
        assert page.evaluate("() => document.activeElement.textContent") == "PERSONs2"
    # In a narrower window the row takes two lines. The part still comes to rest under it.
    under_the_row = """(id) => {
      const row = document.getElementById("contents").getBoundingClientRect();
      const part = document.getElementById(id).getBoundingClientRect();
      return { row: [row.top, row.bottom], part: part.top, at: scrollY };
    }"""
    # How the row lies: how many lines its links take, from where to where it reaches, how
    # many links it cuts off, and how wide the page is beside the window.
    lies = """() => {
      const row = document.getElementById("contents");
      const at = row.getBoundingClientRect();
      const links = [...row.querySelectorAll(".to")].map((each) => each.getBoundingClientRect());
      return {
        lines: new Set(links.map((each) => Math.round(each.top))).size,
        sides: [at.left, at.right],
        cut: links.filter((each) => each.left < at.left || each.right > at.right).length,
        page: [document.documentElement.scrollWidth, document.documentElement.clientWidth],
      };
    }"""
    with opened(chromium, story / "they-collect-them.json", wide=700, tall=800) as page:
        page.locator("#objects .card").first.wait_for()
        page.wait_for_function("() => document.querySelectorAll('#contents .to').length === 9")
        found = page.evaluate(lies)
        assert (found["lines"], found["cut"], found["sides"]) == (2, 0, [28, 672])
        page.locator("#contents .to", has_text="OPTIONs").click()
        page.wait_for_function("() => scrollY > 0")
        page.wait_for_timeout(200)
        found = page.evaluate(under_the_row, "options-part")
        assert found["row"][0] == 0
        assert found["row"][1] <= found["part"] < found["row"][1] + 30
    # Whether what the keyboard is on is in the window, whole.
    in_the_window = """() => {
      const at = document.activeElement.getBoundingClientRect();
      return at.left >= 0 && at.right <= innerWidth && at.top >= 0 && at.bottom <= innerHeight;
    }"""
    # In a narrow window, such as the browser beside an agent, the row takes more lines
    # still. It does not stay at the top there, where it would take a good part of the
    # window: it goes with the page. The page has less room at its sides.
    for wide, lines in [(360, 4), (640, 2)]:
        with opened(chromium, story / "they-collect-them.json", wide=wide, tall=700) as page:
            page.locator("#objects .card").first.wait_for()
            page.wait_for_function("() => document.querySelectorAll('#contents .to').length === 9")
            found = page.evaluate(lies)
            # Every link is in the row whole, and the page is as wide as the window.
            assert (found["lines"], found["cut"]) == (lines, 0)
            assert (found["sides"], found["page"]) == ([14, wide - 14], [wide, wide])
            # Tab goes through the links from the first one, and each is in the window,
            # whole, when the keyboard is on it.
            reached: list[str] = []
            for _ in range(9):
                page.keyboard.press("Tab")
                assert page.evaluate(in_the_window)
                reached.append(page.evaluate("() => document.activeElement.firstChild.textContent"))
            assert reached[0] == "To do and to decide" and reached[-1] == "The COMPILER's report"
            # A click brings the part to the top of the window, and the row has gone up
            # with the page.
            page.locator("#contents .to", has_text="OPTIONs").click()
            page.wait_for_function("() => scrollY > 0 && location.hash === '#options-part'")
            page.wait_for_timeout(200)
            found = page.evaluate(under_the_row, "options-part")
            assert found["row"][1] < 0
            assert 0 <= found["part"] < 30
    # One pixel wider, and the row stays at the top as in any window of one column.
    with opened(chromium, story / "they-collect-them.json", wide=641, tall=700) as page:
        page.locator("#objects .card").first.wait_for()
        page.wait_for_function("() => document.querySelectorAll('#contents .to').length === 9")
        assert page.evaluate(lies)["sides"] == [28, 613]
        page.locator("#contents .to", has_text="OPTIONs").click()
        page.wait_for_function("() => scrollY > 0")
        page.wait_for_timeout(200)
        found = page.evaluate(under_the_row, "options-part")
        assert found["row"][0] == 0
        assert found["row"][1] <= found["part"] < found["row"][1] + 30
    # A link has the yellow edge where the report names something in what the FILE does not say.
    with opened(chromium, EXAMPLES / "flight-home" / "depends-on-the-cab.json") as page:
        page.locator("#options .item.asked").first.wait_for()
        page.wait_for_function("() => document.querySelectorAll('#contents .to.asked').length > 1")
        yellow = page.evaluate(edges, "asked")
        assert all(link is part for link, part in yellow)
        # The case in which the trip works is open, and it is about the cab among the OPTIONs.
        assert page.locator("#contents .to.asked").all_text_contents() == [
            "To do and to decide1",
            "OPTIONs4",
        ]
        assert page.locator("#contents .to.clash").count() == 0
    # On a wide window the row is above the two panes. A click moves the pane of the drawings,
    # and the page stays where it is.
    with opened(chromium, story / "they-collect-them.json", wide=1500, tall=700) as page:
        page.locator("#objects .card").first.wait_for()
        page.wait_for_function("() => document.querySelectorAll('#contents .to').length === 9")
        page.locator("#contents .to", has_text="OBJECTs").click()
        page.wait_for_function(
            """() => {
              const pane = document.getElementById("drawings");
              const part = document.getElementById("objects-part").getBoundingClientRect();
              const box = pane.getBoundingClientRect();
              const inside = part.top >= box.top - 1 && part.top < box.bottom;
              return scrollY === 0 && pane.scrollTop > 0 && inside;
            }"""
        )
        assert page.locator("#contents .to.clash, #contents .to.asked").count() == 0
    # A wide window that is too short for its panes scrolls as a whole. The row goes with
    # it, and covers no part that a link leads to.
    with opened(chromium, story / "they-collect-them.json", wide=1400, tall=420) as page:
        page.locator("#objects .card").first.wait_for()
        page.wait_for_function("() => document.querySelectorAll('#contents .to').length === 9")
        page.locator("#contents .to", has_text="The COMPILER's report").click()
        page.wait_for_function("() => document.querySelector('main').scrollTop > 0")
        page.wait_for_timeout(200)
        found = page.evaluate(under_the_row, "report-part")
        assert 0 <= found["part"] < 420
        assert found["row"][1] <= found["part"]
    # A link that is opened in a tab of its own leads to its part too: the page goes to the
    # part that its address names, once that part is drawn.
    with serving(story / "they-collect-them.json") as view:
        context = chromium.new_context(viewport={"width": 700, "height": 780})
        try:
            page = context.new_page()
            page.goto(f"{view.address}#objects-part")
            page.locator("#objects .card").first.wait_for()
            page.wait_for_function(
                """() => {
                  const row = document.getElementById("contents").getBoundingClientRect();
                  const part = document.getElementById("objects-part").getBoundingClientRect();
                  return scrollY > 0 && part.top >= row.bottom - 1 && part.top < innerHeight / 2;
                }"""
            )
            # Once the report is there, the page stays where the reader puts it.
            page.locator("#report .row").first.wait_for()
            page.evaluate("() => scrollTo(0, 0)")
            page.wait_for_timeout(300)
            assert page.evaluate("() => scrollY") == 0
        finally:
            context.close()
    # The keyboard is on the link of a part, and the FILE changes so that the part goes. The
    # page puts the keyboard on no other link. The next Tab goes on from where the link was.
    path = tmp_path / "things.json"
    content = json.loads((story / "they-collect-them.json").read_text())
    path.write_text(json.dumps(content))
    with opened(chromium, path) as page:
        page.locator("#objects .card").first.wait_for()
        page.wait_for_function("() => document.querySelectorAll('#contents .to').length === 9")
        page.locator("#contents .to", has_text="OBJECTs").focus()
        content["objects"] = []
        content["facts"] = [fact for fact in content["facts"] if "bags" not in json.dumps(fact)]
        put(path, json.dumps(content).encode())
        page.wait_for_function("() => document.querySelectorAll('#contents .to').length === 8")
        assert page.evaluate("() => document.activeElement === document.body")
        page.keyboard.press("Tab")
        focused = page.evaluate("() => document.activeElement.getAttribute('href')")
        assert focused == "#report-part"
    # A calendar that the page could not load has its place on the page, and its link, with
    # no edge: nothing in it is marked.
    with opened(chromium, story / "nobody-collects-them.json", without=("calendar.js",)) as page:
        page.locator("#objects .card.clash").first.wait_for()
        page.wait_for_function("() => document.querySelectorAll('#contents .to.clash').length > 0")
        assert page.locator("#contents .to").nth(1).text_content() == "Calendar"
        red = page.evaluate(edges, "clash")
        assert all(link is part for link, part in red)
        assert red[1] == [False, False]
    # A FILE that the format refuses has nothing to draw, and so no row.
    path = tmp_path / "trip.json"
    path.write_text("{}")
    refused = "() => document.getElementById('line').textContent.startsWith('This FILE does not')"
    with opened(chromium, path, once=refused) as page:
        assert page.locator("#contents").is_hidden()
        assert page.locator("#contents .to").count() == 0


def test_the_keyboard_lights_up_what_the_pointer_does(chromium: Browser, tmp_path: Path) -> None:
    """Tab reaches one drawing in each part, and the arrow keys move from it to the others."""
    # The part that the keyboard is in, and the name of the drawing that it is on.
    on = """() => {
      const at = document.activeElement;
      const name = at.querySelector("h3, b")?.textContent ?? at.textContent.trim();
      return [at.closest("section")?.id ?? null, name];
    }"""
    walk = "the walk between the hotel and the Art Institute"
    path = tmp_path / "trip.json"
    path.write_bytes((EXAMPLES / "ending-in-denver" / "works.json").read_bytes())
    with opened(chromium, path) as page:
        page.locator("#options .item").first.wait_for()
        page.locator("#report .row").first.wait_for()
        page.locator("#calendar .mark").first.wait_for()
        # From the link to a part, Tab goes to the first drawing of the part. It lights up
        # what the pointer lights up there: the step, and its line of the report.
        page.locator("#contents .to", has_text="OPTIONs").press("Enter")
        page.keyboard.press("Tab")
        assert page.evaluate(on) == ["options-part", "Museum visit"]
        found = lit(page, options=["Museum visit"], marks=["Museum visit"])
        assert any("2:00 pm to 3:00 pm: Museum visit" in row for row in found["rows"])
        # The arrow keys move through the drawings of the part, and stop at its two ends.
        page.keyboard.press("ArrowDown")
        assert page.evaluate(on) == ["options-part", "Blue Line to O'Hare"]
        lit(page, options=["Blue Line to O'Hare"], marks=["Blue Line to O'Hare"])
        page.keyboard.press("End")
        page.keyboard.press("ArrowDown")
        assert page.evaluate(on) == ["options-part", "Flight home"]
        lit(page, options=["Flight home"], marks=["Flight home"])
        page.keyboard.press("Home")
        page.keyboard.press("ArrowUp")
        assert page.evaluate(on) == ["options-part", "Museum visit"]
        page.keyboard.press("ArrowRight")
        assert page.evaluate(on) == ["options-part", "Blue Line to O'Hare"]
        # A part is one stop for Tab. The next Tab leaves it for the next part, and Tab the
        # other way comes back to the drawing that the keyboard was on.
        page.keyboard.press("Tab")
        assert page.evaluate(on) == ["rights-part", "Museum visit"]
        lit(page, rights=["Museum visit"], options=[])
        page.keyboard.press("ArrowDown")
        page.keyboard.press("ArrowDown")
        assert page.evaluate(on) == ["rights-part", "Flight home"]
        page.keyboard.press("Shift+Tab")
        assert page.evaluate(on) == ["options-part", "Blue Line to O'Hare"]
        page.keyboard.press("Tab")
        assert page.evaluate(on) == ["rights-part", "Flight home"]
        page.keyboard.press("Shift+Tab")
        lit(page, options=["Blue Line to O'Hare"], marks=["Blue Line to O'Hare"])
        # What the reader used last says what is lit. The pointer moves onto a PERSON: that
        # PERSON is lit. A key is pressed: what the keyboard is on is lit, with the pointer
        # at rest where it was.
        alex = page.locator("#persons .item").first
        alex.hover()
        lit(page, persons=["Alex"], options=[])
        page.keyboard.press("ArrowUp")
        assert page.evaluate(on) == ["options-part", "Museum visit"]
        lit(page, persons=[], options=["Museum visit"])
        # A key that moves the keyboard nowhere is a use of the keyboard too: Home on the
        # first drawing of a part, and a key that the page has no use for.
        for key in ["Home", "Escape"]:
            page.mouse.move(2, 2)
            alex.hover()
            lit(page, persons=["Alex"], options=[])
            page.keyboard.press(key)
            assert page.evaluate(on) == ["options-part", "Museum visit"]
            lit(page, persons=[], options=["Museum visit"])
        # A key that only changes what other keys do is no use of the keyboard.
        page.mouse.move(2, 2)
        alex.hover()
        for key in ["Shift", "Meta", "Control", "Alt", "CapsLock", "NumLock", "ScrollLock"]:
            page.keyboard.press(key)
        page.wait_for_timeout(100)
        lit(page, persons=["Alex"], options=[])
        page.keyboard.press("Escape")
        lit(page, persons=[], options=["Museum visit"])
        # A drawing that comes under a pointer at rest, as when the page scrolls, is not
        # pointed at.
        alex.evaluate("(row) => row.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }))")
        page.wait_for_timeout(100)
        lit(page, persons=[], options=["Museum visit"])
        # The pointer moves: what it is on is lit again. On something that is no drawing, and
        # off the page, it leaves what the keyboard is on lit.
        alex.scroll_into_view_if_needed()
        box = alex.bounding_box()
        assert box is not None
        page.mouse.move(box["x"] + 30, box["y"] + 12)
        page.mouse.move(box["x"] + 40, box["y"] + 14)
        lit(page, persons=["Alex"], options=[])
        page.locator("#options-part h2").hover()
        lit(page, persons=[], options=["Museum visit"], marks=["Museum visit"])
        page.mouse.move(2, 2)
        lit(page, persons=[], options=["Museum visit"])
        # A finger on the screen points with a tap, and a swipe points at nothing. The finger
        # goes down on a PERSON and moves the page: what the keyboard is on stays lit.
        page.keyboard.press("Escape")
        lit(page, persons=[], options=["Museum visit"])
        touch: Any = page.context.new_cdp_session(page)

        def finger(kind: str, *at: tuple[float, float]) -> None:
            points = [{"x": round(x), "y": round(y)} for x, y in at]
            touch.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": points})

        alex.scroll_into_view_if_needed()
        box = alex.bounding_box()
        assert box is not None
        before = page.evaluate("() => scrollY")
        finger("touchStart", (box["x"] + 30, box["y"] + 12))
        for moved in range(1, 7):
            finger("touchMove", (box["x"] + 30, box["y"] + 12 - 20 * moved))
        # The finger rests before it lifts, so that the page does not go on moving by itself.
        page.wait_for_timeout(200)
        finger("touchEnd")
        page.wait_for_function("(before) => scrollY > before", arg=before)
        page.wait_for_function(
            """() => new Promise((say) => setTimeout(say, 200, scrollY))
              .then((was) => was === scrollY)"""
        )
        lit(page, persons=[], options=["Museum visit"])
        # The pointer is at rest on one PERSON, and the finger taps another: the one that is
        # tapped is lit once the finger has lifted, and the keyboard is on it.
        sam = page.locator("#persons .item").nth(1)
        sam.hover()
        lit(page, persons=["Sam"], options=[])
        box = alex.bounding_box()
        assert box is not None
        finger("touchStart", (box["x"] + 30, box["y"] + 12))
        finger("touchEnd")
        lit(page, persons=["Alex"], options=[])
        assert page.evaluate(on)[0] == "persons-part"
        # The pointer moves again where it was: what it is on is lit.
        box = sam.bounding_box()
        assert box is not None
        page.mouse.move(box["x"] + box["width"] / 2 + 6, box["y"] + box["height"] / 2 + 3)
        lit(page, persons=["Sam"], options=[])
        touch.detach()
        page.locator("#options .item").first.focus()
        page.keyboard.press("Escape")
        lit(page, persons=[], options=["Museum visit"])
        # The page draws a FILE that has changed, and its drawings are new ones. The page does
        # not guess which of them is the one that the keyboard was on: the keyboard is on
        # nothing, and nothing is lit. The next Tab goes on from where the keyboard was.
        changed = json.loads(path.read_text())
        changed["persons"][0]["name"] = "Alexandra"
        put(path, json.dumps(changed).encode())
        page.locator("#persons .item-name", has_text="Alexandra").wait_for()
        page.locator("#report .row", has_text="Alexandra").first.wait_for()
        assert page.evaluate("() => document.activeElement === document.body")
        lit(page, options=[], marks=[], rows=[])
        page.keyboard.press("Tab")
        assert page.evaluate(on) == ["options-part", "Museum visit"]
        lit(page, options=["Museum visit"], marks=["Museum visit"])
        # In the report, one line takes the keyboard, and the arrow keys go from line to line
        # of those that are about something on the page.
        page.locator("#report").focus()
        page.keyboard.press("Tab")
        assert page.evaluate(on)[1].startswith(f"1:45 pm to 2:00 pm: {walk}")
        lit(page, marks=[walk], ways=[walk])
        page.keyboard.press("ArrowDown")
        assert page.evaluate(on)[1].startswith("2:00 pm to 3:00 pm: Museum visit")
        lit(page, marks=["Museum visit"], options=["Museum visit"])
        # With Shift, an arrow key is the browser's. It makes a selection of text longer, and
        # the keyboard stays on its line.
        page.locator("#report .row", has_text="2:00 pm to 3:00 pm: Museum visit").dblclick()
        chosen = "() => getSelection().toString()"
        before = page.evaluate(chosen)
        assert before
        page.keyboard.press("Shift+ArrowRight")
        after = page.evaluate(chosen)
        assert after.startswith(before) and len(after) == len(before) + 1
        assert page.evaluate(on)[1].startswith("2:00 pm to 3:00 pm: Museum visit")
        # The calendar is a part too: Tab reaches one of its drawings, and the arrows the rest.
        page.locator("#calendar").focus()
        page.keyboard.press("Tab")
        assert page.evaluate("() => document.activeElement.closest('#calendar') !== null")
        first = page.evaluate("() => document.activeElement.dataset.of")
        page.keyboard.press("End")
        last = page.evaluate(
            "() => document.activeElement.dataset.of ?? document.activeElement.dataset.record"
        )
        assert first != last
        # With the keyboard on something that is no drawing, nothing is lit.
        page.locator("#contents .to").first.focus()
        page.keyboard.press("Shift+Tab")
        lit(page, marks=[], options=[], rows=[], persons=[])
        # Each part has one drawing that Tab stops at, however many it holds.
        stops = page.evaluate(
            """() => [...document.querySelectorAll("#calendar-steps, #drawings > .part")]
              .filter((part) => !part.hidden)
              .map((part) => [...part.querySelectorAll("[data-of], [data-record]")])
              .map((drawings) => drawings.filter((each) => each.tabIndex === 0).length)"""
        )
        # The calendar, the PERSONs, the PLACEs, the WANTs, the OPTIONs, the rights and the WAYs.
        # What is open is a part too: the train to the flight, which no LOCK decides.
        assert stops == [1] * 8
    # The pointer is on a drawing before the report comes. When the report is there, its
    # line about that drawing is brought into view.
    first, answer, report = (json.dumps(event) for event in checked(path.read_bytes()))
    (tmp_path / "python.first").write_text(f"{first}\n{answer}\n")
    (tmp_path / "python.report").write_text(f"{report}\n")
    go = tmp_path / "python.go"
    waits = 'cat "$0.first"\nwhile [ ! -e "$0.go" ]; do sleep 0.05; done\ncat "$0.report"'
    drawn = "() => document.querySelectorAll('#wants .card').length > 0"
    held = stand_in(tmp_path, waits)
    with opened(chromium, path, wide=1500, tall=700, python=held, once=drawn) as page:
        page.locator("#wants .card .card-name").hover()
        lit(page, wants=["ending the trip in Denver"])
        go.write_text("")
        page.locator("#report .row").first.wait_for()
        found = lit(page, wants=["ending the trip in Denver"])
        assert ids_of(found["rows"]) == ["ending-in-denver"]
        page.wait_for_function(f"() => ({PLACED})().shown === 1")
    # A TRIP of two days has a strip above its calendar. The strip is a part for the keyboard,
    # and so is the calendar, after its own box: Tab goes from one to the next.
    with opened(chromium, EXAMPLES / "several-days" / "works-but-risky.json") as page:
        page.locator("#strip .bar").first.wait_for()
        page.locator("#calendar .mark").first.wait_for()
        page.locator("#persons .item").first.wait_for()
        where = """() => {
          const at = document.activeElement;
          const part = at.closest("#strip, #calendar, #drawings > .part");
          return [part === null ? null : part.id, at.matches("[data-of], [data-record]")];
        }"""
        page.locator("#drawings").focus()
        seen: list[list[Any]] = []
        for _ in range(5):
            page.keyboard.press("Tab")
            seen.append(page.evaluate(where))
        assert seen == [
            ["open-part", True],
            ["strip", True],
            ["calendar", False],
            ["calendar", True],
            ["persons-part", True],
        ]
    # A step of a minute is a tick on the strip. The ring of the keyboard goes around the tick.
    with opened(chromium, written(tmp_path, crowded())) as page:
        page.locator("#strip .bar").first.wait_for()
        page.locator("#drawings").focus()
        page.keyboard.press("Tab")
        ringed = None
        for _ in range(40):
            ringed = page.evaluate(
                """() => {
                  const tick = document.activeElement.querySelector(".bar-tick, .bar-several");
                  if (tick === null) return null;
                  const style = getComputedStyle(tick);
                  return [style.outlineStyle, parseFloat(style.outlineWidth)];
                }"""
            )
            if ringed is not None:
                break
            page.keyboard.press("ArrowRight")
        assert ringed == ["solid", 3]
    # A part keeps its stop for Tab while the page says more and draws nothing again: here
    # the page says that it has lost the view.
    views: list[View] = []
    story = EXAMPLES / "ending-in-denver" / "works.json"
    with opened(chromium, story, views=views) as page:
        page.locator("#options .item").first.wait_for()
        page.locator("#report .row").first.wait_for()
        page.locator("#calendar .mark").first.wait_for()
        page.locator("#contents .to", has_text="OPTIONs").press("Enter")
        page.keyboard.press("Tab")
        page.keyboard.press("ArrowDown")
        page.keyboard.press("Tab")
        assert page.evaluate(on) == ["rights-part", "Museum visit"]
        cut_off(views[0])
        page.locator("#answer.lost").wait_for()
        assert page.evaluate(on) == ["rights-part", "Museum visit"]
        page.keyboard.press("Shift+Tab")
        assert page.evaluate(on) == ["options-part", "Blue Line to O'Hare"]
    # The steps that the FILE gives no time for are under the calendar. They are of the
    # calendar's part: one stop for Tab, and the arrow keys go from the calendar to them.
    untimed = json.loads((EXAMPLES / "a-driver" / "depends-on-the-car.json").read_text())
    untimed["facts"] = [each for each in untimed["facts"] if each["id"] != "drive-back-time"]
    with opened(chromium, written(tmp_path, untimed)) as page:
        page.locator("#calendar .mark").first.wait_for()
        page.locator("#calendar-untimed span").first.wait_for()
        page.locator("#persons .item").first.wait_for()
        page.locator("#report .row").first.wait_for()
        inside = "(box) => document.activeElement.closest(box) !== null"
        page.locator("#calendar").focus()
        page.keyboard.press("Tab")
        assert page.evaluate(inside, "#calendar")
        page.keyboard.press("End")
        assert page.evaluate(inside, "#calendar-untimed")
        back = page.evaluate("() => document.activeElement.textContent")
        lit(page, untimed=[back])
        page.keyboard.press("ArrowUp")
        assert page.evaluate(inside, "#calendar")
        page.keyboard.press("Tab")
        assert page.evaluate(inside, "#persons-part")
        page.keyboard.press("Shift+Tab")
        assert page.evaluate(inside, "#calendar")
        stops = page.evaluate(
            """() => [...document.querySelectorAll("#calendar-steps [data-of]")]
              .filter((each) => each.tabIndex === 0).length"""
        )
        assert stops == 1
    # On a wide window the drawings are in a pane that cuts off what is outside it. The ring
    # of the keyboard is inside the pane: at its left, at its right, and at its end.
    ring = """() => {
      const at = document.activeElement;
      const style = getComputedStyle(at);
      const around = parseFloat(style.outlineWidth) + parseFloat(style.outlineOffset);
      const pane = document.getElementById("drawings");
      pane.scrollTop = pane.scrollHeight;
      const box = at.getBoundingClientRect();
      const room = pane.getBoundingClientRect();
      return {
        ring: style.outlineStyle === "solid" && around >= 4,
        left: box.left - around >= room.left,
        right: box.right + around <= room.left + pane.clientWidth,
        end: box.bottom + around <= room.top + pane.clientHeight,
      };
    }"""
    with opened(chromium, story, wide=1500, tall=700) as page:
        page.locator("#report .row").first.wait_for()
        page.locator("#calendar .mark").first.wait_for()
        page.locator("#ways .item").first.wait_for()
        page.locator("#contents .to", has_text="PERSONs").press("Enter")
        page.keyboard.press("Tab")
        assert page.evaluate(on)[0] == "persons-part"
        found = page.evaluate(ring)
        assert found["ring"] and found["left"] and found["right"], found
        last = page.locator("#drawings > .part:not([hidden])").last
        last.locator("[data-of], [data-record], [data-records]").first.focus()
        page.keyboard.press("End")
        found = page.evaluate(ring)
        assert all(found.values()), found
    # The row of links stays at the top of a window of one column. A line of the report that
    # the keyboard goes up to comes to rest under the row, and not behind it.
    with opened(chromium, EXAMPLES / "several-days" / "works-but-risky.json", 700, 600) as page:
        page.locator("#report .row").first.wait_for()
        page.locator("#report").focus()
        page.keyboard.press("Tab")
        page.keyboard.press("End")
        for _ in range(40):
            page.keyboard.press("ArrowUp")
            covered = page.evaluate(
                """() => {
                  const row = document.getElementById("contents").getBoundingClientRect();
                  const line = document.activeElement.getBoundingClientRect();
                  return line.top < row.bottom - 1;
                }"""
            )
            assert not covered


def test_the_report_on_the_page_is_the_report_in_words(chromium: Browser) -> None:
    """Character for character, before its lines are tied and after."""
    for name in [
        "flight-home/works-but-risky",
        "flight-home/cannot-work",
        "a-ticket/depends-on-the-price",
        "several-days/works",
    ]:
        path = EXAMPLES / f"{name}.json"
        expected = path.with_name(f"{path.stem}.expected.txt").read_text()
        requests: list[Route] = []
        with opened(chromium, path, held=("lines.js", requests)) as page:
            # The page has not got what ties its lines: the report is on it as it is.
            assert page.locator("#report .row").count() == 0, name
            assert page.text_content("#report") == expected, name
            (request,) = requests
            request.continue_()
            page.locator("#report .row").first.wait_for()
            assert page.locator("#report .row").count() == len(expected.split("\n")), name
            assert page.text_content("#report") == expected, name


def test_pointing_at_a_step_lights_up_what_the_report_says_of_it(chromium: Browser) -> None:
    """Alex and Sam would be too late for the flight if the train took its longest."""
    with opened(chromium, EXAMPLES / "flight-home" / "works-but-risky.json") as page:
        page.locator("#calendar .mark.warned").first.hover()
        found = lit(page, marks=["Flight home"])
        assert found["rows"][:2] == [
            "  5:00 pm to 7:30 pm: Flight home, Alex and Sam",
            "    ! Alex and Sam would be 5 min too late for this.",
        ]
        # The other lines are those of the records about the flight, and of no other step.
        records = ids_of(found["rows"][2:])
        assert {"flight-time", "lock-flight"} <= set(records)
        assert not {"visit-time", "lock-visit"} & set(records)
        # Pointing at the line of a record lights up what the record is about, and that line.
        page.locator("#report .row[data-record='lock-visit']").hover()
        found = lit(page, marks=["Museum visit"])
        assert ids_of(found["rows"]) == ["lock-visit"]
        # With the pointer off the parts of the page, nothing is lit.
        page.mouse.move(2, 2)
        lit(page, marks=[], rows=[], bars=[], untimed=[], wants=[], options=[])
        assert page.locator(".lit").count() == 0


def test_pointing_ties_the_strip_the_calendar_and_the_report(chromium: Browser) -> None:
    """On a TRIP of two days, a step is on the strip, on the calendar and in the report."""
    walk = "the walk between the hotel and Willis Tower"
    with opened(chromium, EXAMPLES / "several-days" / "works-but-risky.json") as page:
        page.locator("#strip .bar.warned").first.hover()
        found = lit(page, bars=[walk], marks=[walk])
        assert any(row.startswith("    ! ") for row in found["rows"])
        # And the other way: from the calendar to the strip.
        page.locator("#calendar .mark.locked").first.hover()
        found = lit(page, bars=["Dinner"], marks=["Dinner"])
        assert found["rows"][0].endswith(": Dinner, Alex")


def test_pointing_ties_a_want_to_the_calendar_and_the_report(chromium: Browser) -> None:
    """Alex must have a view from high up, and Jo must not. Only Alex goes up the tower."""
    with opened(chromium, EXAMPLES / "a-must-not" / "works.json") as page:
        page.locator("#wants .card").wait_for()
        page.locator("#report .row").first.wait_for()
        assert page.text_content("#wants .card-name") == "a view from high up"
        assert page.text_content("#wants .card-holds") == "A must for Alex. A must-not for Jo."
        # Pointing at an OPTION under the WANT lights up its step on the calendar, its line in
        # the plan, and the line of the FACT that it SATISFIES the WANT.
        page.locator("#wants .entry").first.hover()
        found = lit(page, marks=["Skydeck visit"], wants=["Skydeck visit"])
        assert found["rows"][0] == "  10:00 am to 11:30 am: Skydeck visit, Alex"
        assert ids_of(found["rows"][1:]) == ["skydeck-is-high-up"]
        # Pointing at the step on the calendar lights up the OPTION under the WANT.
        page.locator("#calendar .mark.planned").first.hover()
        lit(page, marks=["Skydeck visit"], wants=["Skydeck visit"])
        # Pointing at the WANT lights up its line in the report, and the other way round.
        page.locator("#wants .card-name").hover()
        found = lit(page, marks=[], wants=["a view from high up"])
        assert ids_of(found["rows"]) == ["view"]
        page.locator("#report .row[data-record='view']").hover()
        lit(page, marks=[], wants=["a view from high up"])
        # The line of a LOCK is about its OPTION: it lights up every drawing of that OPTION,
        # the one under the WANT too, and no other line of the report.
        page.locator("#report .row[data-record='lock-lunch']").hover()
        found = lit(page, marks=["Lunch in the park"], wants=["Lunch in the park"])
        assert found["options"] == ["Lunch in the park"]
        assert ids_of(found["rows"]) == ["lock-lunch"]


def test_an_option_under_a_want_that_is_lit_is_not_lit_itself(chromium: Browser) -> None:
    """The trip works if lunch on the rooftop does not SATISFY a view from high up.

    The case names the WANT and the lunch, and says nothing of the Skydeck visit, which is the
    one OPTION under the WANT. So the WANT and the lunch are lit, and the visit looks as it did.
    """
    grounds = """() => {
      const ground = (each) => getComputedStyle(each).backgroundColor;
      const entries = [...document.querySelectorAll("#wants .entry")];
      return {
        want: ground(document.querySelector("#wants .card.lit")),
        unlit: entries.filter((each) => !each.classList.contains("lit")).map(ground),
      };
    }"""
    with opened(chromium, EXAMPLES / "a-must-not" / "depends-on-the-lunch.json") as page:
        case = page.locator("#report .row[data-record='case:0']")
        case.wait_for()
        page.locator("#wants .entry").first.wait_for()
        assert page.locator("#wants .entry-name").all_text_contents() == ["Skydeck visit"]
        case.hover()
        lit(page, wants=["a view from high up"], options=["Lunch on the rooftop"])
        found = page.evaluate(grounds)
        # The visit has a ground of its own, which is not the ground of what is lit.
        (visit,) = found["unlit"]
        assert visit.startswith("rgb(") and visit != found["want"]


def test_a_want_has_the_red_edge_of_what_the_report_names(chromium: Browser) -> None:
    """Alex must have deep-dish pizza, and a LOCK names the blues show at the dinner's time."""
    with opened(chromium, EXAMPLES / "a-must" / "cannot-work.json") as page:
        want = page.locator("#wants .card.clash")
        want.wait_for()
        assert want.get_attribute("title") == (
            "The report names deep-dish and every-deep-dish-place among what rules out every plan."
        )
        assert (page.text_content("#wants-says") or "").endswith(
            " A red edge marks what the report names among what rules out every plan."
        )
        # The OPTION under it has no red edge: the report does not name its FACT.
        assert page.locator("#wants .entry").count() == 1
        assert page.locator("#wants .entry.clash").count() == 0
        assert page.text_content("#wants .entry-takes") == "No LOCK names it."
    # A FILE with no WANT has no such part on its page.
    with opened(chromium, EXAMPLES / "flight-home" / "works.json") as page:
        page.locator("#report .row").first.wait_for()
        page.locator("#calendar .mark").first.wait_for()
        assert page.locator("#wants-part").is_hidden()


def test_pointing_ties_an_option_to_the_calendar_and_the_report(chromium: Browser) -> None:
    """The trip depends on how long the cab takes. No LOCK names the cab.

    So the calendar has no step for the cab, and the page still shows it: it is in the FILE.
    """
    with opened(chromium, EXAMPLES / "flight-home" / "depends-on-the-cab.json") as page:
        case = page.locator("#report .row[data-record='case:0']")
        case.wait_for()
        said = case.text_content()
        assert said == "The trip works if Cab to O'Hare takes 45 min or less."
        rows = page.locator("#options .item")
        rows.first.wait_for()
        assert rows.count() == 4
        cab = page.locator("#options .item.asked")
        assert cab.count() == 1
        assert cab.locator(".item-name").text_content() == "Cab to O'Hare"
        assert cab.locator(".item-said p").all_text_contents() == [
            "Can start at any time.",
            "The FILE does not say how long it takes.",
            "The FILE does not say how early people must be there.",
            "Nobody needs a right to take part.",
            "No LOCK names it.",
        ]
        # A row shows a time, so the part says whose clocks show it.
        assert " Times are on the clocks of America/Chicago." in (
            page.text_content("#options-says") or ""
        )
        assert page.locator("#calendar .mark").count() == 2
        # Pointing at the cab lights up the line of the case that names it, and the other way.
        cab.hover()
        lit(page, options=["Cab to O'Hare"], marks=[], rows=[said])
        case.hover()
        lit(page, options=["Cab to O'Hare"], marks=[], rows=[said])
        # An OPTION that the calendar holds is its step: pointing at either lights up both.
        rows.first.hover()
        lit(page, options=["Museum visit"], marks=["Museum visit"])
        page.locator("#calendar .mark").first.hover()
        lit(page, options=["Museum visit"], marks=["Museum visit"])
    # In a plan, an OPTION is its step: pointing at it lights up its line in the plan too.
    with opened(chromium, EXAMPLES / "flight-home" / "works.json") as page:
        page.locator("#report .row").first.wait_for()
        train = page.locator("#options .item").nth(1)
        assert train.locator(".item-name").text_content() == "Blue Line to O'Hare"
        train.hover()
        found = lit(page, options=["Blue Line to O'Hare"], marks=["Blue Line to O'Hare"])
        assert found["rows"][0].endswith(": Blue Line to O'Hare, Alex and Sam")


def test_pointing_at_an_option_lights_up_no_other_that_its_case_names(
    chromium: Browser, tmp_path: Path
) -> None:
    """Nobody has a BOOKING for the flight, and the FILE does not say how long the cab takes.

    One case of the report names both the flight and the cab. A LOCK names the flight, so the
    calendar holds it. No LOCK names the cab.
    """
    content = json.loads((EXAMPLES / "flight-home" / "depends-on-the-cab.json").read_text())
    content["facts"] = [fact for fact in content["facts"] if fact["id"] != "flight-tickets"]
    with opened(chromium, written(tmp_path, content)) as page:
        case = page.locator("#report .row[data-record='case:0']")
        case.wait_for()
        said = case.text_content() or ""
        assert "Flight home" in said and "Cab to O'Hare" in said
        page.locator("#calendar .mark").first.wait_for()
        asked = page.locator("#options .item.asked")
        asked.first.wait_for()
        assert asked.locator(".item-name").all_text_contents() == ["Flight home", "Cab to O'Hare"]
        # The cab is no step of the calendar. Pointing at it lights up the case, and not the
        # flight: not its row, and not its step.
        asked.nth(1).hover()
        lit(page, options=["Cab to O'Hare"], marks=[], rows=[said])
        # Pointing at the flight lights up its step and the case, and not the cab.
        asked.first.hover()
        lit(page, options=["Flight home"], marks=["Flight home"], rows=[said])
        page.locator("#calendar .mark.asked").hover()
        lit(page, options=["Flight home"], marks=["Flight home"], rows=[said])
        # Pointing at the line of the case lights up both: the case is about both.
        case.hover()
        lit(page, options=["Flight home", "Cab to O'Hare"], marks=["Flight home"], rows=[said])


def test_pointing_ties_a_person_to_the_report(chromium: Browser) -> None:
    """Alex and Sam start from the hotel, and must end the TRIP in Denver."""
    # The colour of the bar in each row, and of the line under each PERSON's name in the calendar.
    colours = """() => {
      const all = (which) => [...document.querySelectorAll(which)];
      return {
        rows: all("#persons .item").map((row) => getComputedStyle(row, "::before").backgroundColor),
        columns: [...document.querySelector("#calendar .day").querySelectorAll(".person")].map(
          (head) => getComputedStyle(head).borderBottomColor,
        ),
      };
    }"""
    with opened(chromium, EXAMPLES / "ending-in-denver" / "works.json") as page:
        rows = page.locator("#persons .item")
        rows.first.wait_for()
        page.locator("#report .row").first.wait_for()
        page.locator("#calendar .mark").first.wait_for()
        assert rows.locator(".item-name").all_text_contents() == ["Alex", "Sam"]
        assert rows.locator(".item-where").all_text_contents() == ["Starts from the hotel."] * 2
        assert rows.first.locator(".item-said p").all_text_contents() == [
            "Must end the TRIP at Denver."
        ]
        # Each row has the colour of its PERSON's column in the calendar.
        found = page.evaluate(colours)
        assert found["rows"] == found["columns"]
        assert len(set(found["rows"])) == 2
        # Pointing at a PERSON lights up the line of the FACT about where they start from, and
        # the other way round. It lights up no step.
        rows.first.hover()
        found = lit(page, persons=["Alex"], marks=[])
        assert ids_of(found["rows"]) == ["alex-start"]
        page.locator("#report .row[data-record='sam-start']").hover()
        lit(page, persons=["Sam"], marks=[])
        # The name over a PERSON's column of the calendar is a drawing of the PERSON: it
        # lights up with the row, and the row with it.
        rows.first.hover()
        lit(page, persons=["Alex"], heads=["Alex"])
        page.locator("#calendar .person", has_text="Sam").first.hover()
        lit(page, persons=["Sam"], heads=["Sam"], marks=[])
        page.locator("#report .row[data-record='sam-start']").hover()
        lit(page, persons=["Sam"], heads=["Sam"])
        # Pointing at a step lights up the name of no PERSON.
        page.locator("#calendar .mark", has_text="Museum visit").first.hover()
        lit(page, marks=["Museum visit"], persons=[], heads=[])
    # On a TRIP of two days the strip has a row for each PERSON. The name beside it is a
    # drawing of the PERSON too, and so is the name over their column on each day.
    with opened(chromium, EXAMPLES / "several-days" / "works-but-risky.json") as page:
        page.locator("#persons .item").first.wait_for()
        beside = page.locator("#strip .strip-people span")
        beside.first.wait_for()
        names = page.locator("#persons .item-name").all_text_contents()
        assert beside.all_text_contents() == names == ["Alex"]
        beside.first.hover()
        lit(page, persons=names, heads=names, beside=names, marks=[], bars=[])
        days = page.locator("#calendar .day").count()
        assert days > 1
        assert page.locator("#calendar .person.lit").count() == days
        # Away from the names, none is lit. From the row of the PERSON, each is again.
        page.locator("#strip .bar").first.hover()
        lit(page, persons=[], heads=[], beside=[])
        page.locator("#persons .item").first.hover()
        lit(page, persons=names, heads=names, beside=names)
    # The trip works if Alex can drive a manual car, or if Sam can.
    with opened(chromium, EXAMPLES / "a-driver" / "depends-on-who-can-drive.json") as page:
        asked = page.locator("#persons .item.asked")
        asked.first.wait_for()
        assert asked.locator(".item-name").all_text_contents() == ["Alex", "Sam"]
        assert page.locator("#persons .item-where").first.text_content() == (
            "The FILE does not say where this PERSON starts from."
        )
        case = page.locator("#report .row[data-record='case:0']")
        case.wait_for()
        case.hover()
        lit(page, persons=["Alex"], capabilities=["driving a manual car", "Alex:"])


def test_pointing_ties_a_booking_and_an_offer_to_the_report(chromium: Browser) -> None:
    """Alex has a BOOKING for the Skydeck, and Sam still has to buy one of two places."""
    with opened(chromium, EXAMPLES / "a-ticket" / "not-bought-yet.json") as page:
        card = page.locator("#rights .card")
        card.wait_for()
        page.locator("#report .row").first.wait_for()
        page.locator("#calendar .mark").first.wait_for()
        assert card.locator(".card-name").text_content() == "Skydeck visit"
        assert card.locator(".card-holds").text_content() == "People need a right to take part."
        entries = card.locator(".entry")
        assert entries.locator(".entry-name").all_text_contents() == [
            "alex-skydeck-ticket",
            "skydeck-tickets",
        ]
        assert entries.first.locator("span").all_text_contents() == [
            "a BOOKING that covers Alex; its payment: 32.00 USD, paid by Alex, from the trip money",
            "In the plan: Alex uses it.",
        ]
        assert entries.nth(1).locator("span").all_text_contents() == [
            "an OFFER with 2 places that can still be bought, for 32.00 USD each",
            "In the plan: Sam takes a place of it.",
        ]
        # The row of the OPTION says whether people need a right to it.
        visit = page.locator("#options .item").first
        assert (
            "People need a right to take part." in visit.locator(".item-said p").all_text_contents()
        )
        # A BOOKING is a thing of its own: pointing at it lights up its lines in the report,
        # and no step.
        entries.first.hover()
        found = lit(page, rights=["alex-skydeck-ticket"], marks=[], options=[])
        assert set(ids_of(found["rows"])) == {"alex-skydeck-ticket"}
        # The line of the BOOKING is about its OPTION too: it lights up every drawing of it.
        page.locator("#report .row[data-record='alex-skydeck-ticket']").first.hover()
        lit(
            page,
            rights=["alex-skydeck-ticket"],
            marks=["Skydeck visit"],
            options=["Skydeck visit"],
        )
        page.locator("#report .row[data-record='skydeck-tickets']").first.hover()
        lit(page, rights=["skydeck-tickets"], marks=["Skydeck visit"])
        # The FACT that people need a right is about the OPTION and about the rights to it.
        page.locator("#report .row[data-record='skydeck-needs-a-ticket']").hover()
        lit(page, rights=["Skydeck visit"], marks=["Skydeck visit"], options=["Skydeck visit"])
        # The warning that Sam still has to buy a right is about the step and about the OFFER.
        warning = page.locator("#report .row.warns")
        said = warning.text_content() or ""
        assert said.startswith("    ! Sam still has to buy a right to this, from skydeck-tickets")
        warning.hover()
        lit(page, rights=["skydeck-tickets"], marks=["Skydeck visit"], options=["Skydeck visit"])
        entries.nth(1).hover()
        found = lit(page, rights=["skydeck-tickets"], marks=[])
        assert said in found["rows"]


def test_the_rights_have_the_edges_of_what_the_report_names(chromium: Browser) -> None:
    """Only Alex has a BOOKING, and a FACT says that the FILE lists every right to the visit."""
    with opened(chromium, EXAMPLES / "a-ticket" / "cannot-work.json") as page:
        page.locator("#rights .card.clash").wait_for()
        clash = page.locator("#rights .entry.clash")
        assert clash.locator(".entry-name").all_text_contents() == ["alex-skydeck-ticket"]
        assert page.text_content("#rights .card-whole") == (
            "The FILE lists every right for a PERSON to take part in it:"
            " nobody on the trip holds another or can get one."
        )
        # The report shows no plan, so the page says nothing of who uses the BOOKING.
        assert clash.locator("span").all_text_contents() == ["a BOOKING that covers Alex"]
    # The trip works if a right is found for Sam, or if a place has a price that Sam can pay.
    with opened(chromium, EXAMPLES / "a-ticket" / "depends-on-the-price.json") as page:
        page.locator("#rights .card.asked").wait_for()
        asked = page.locator("#rights .entry.asked")
        assert asked.locator(".entry-name").all_text_contents() == ["skydeck-tickets"]
        case = page.locator("#report .row[data-record='case:1']")
        case.wait_for()
        case.hover()
        lit(page, rights=["Skydeck visit", "skydeck-tickets"])
    # The trip works if the FILE states what a BOOKING paid. In the one plan that the report
    # gives for that case, Sam buys a place of the OFFER.
    with opened(chromium, EXAMPLES / "a-ticket" / "depends-on-the-receipt.json") as page:
        page.locator("#rights .entry.asked").wait_for()
        plan = page.locator("#report .row", has_text="One plan that works then:")
        plan.wait_for()
        plan.hover()
        lit(page, rights=["skydeck-tickets"])
        # The FILE says all there is to say of the OFFER: it has no yellow edge.
        asked = page.locator("#rights .entry.asked")
        assert asked.locator(".entry-name").all_text_contents() == ["alex-skydeck-ticket"]
    # A FILE that says only that nobody needs a right has no such part on its page.
    with opened(chromium, EXAMPLES / "a-driver" / "works.json") as page:
        page.locator("#report .row").first.wait_for()
        page.locator("#options .item").first.wait_for()
        assert page.locator("#rights-part").is_hidden()


def test_pointing_ties_a_budget_its_caps_and_its_payments_to_the_report(chromium: Browser) -> None:
    """The trip money is for Alex and Sam, and the TRIP spends at most 200.00 USD from it."""
    with opened(chromium, EXAMPLES / "a-ticket" / "within-the-cap.json") as page:
        card = page.locator("#budgets .card")
        card.wait_for()
        page.locator("#report .row").first.wait_for()
        page.locator("#rights .entry").first.wait_for()
        assert card.locator(".card-name").text_content() == "the trip money"
        assert card.locator(".card-holds").text_content() == "For Alex and Sam. It holds USD."
        entries = card.locator(".entry")
        assert entries.locator(".entry-name").all_text_contents() == [
            "trip-cap",
            "alex-skydeck-ticket",
        ]
        assert entries.locator(".entry-says").all_text_contents() == [
            "the TRIP spends at most 200.00 USD from it",
            "32.00 USD, paid by Alex",
        ]
        # The cap says what the report says its plan charges to it, in the report's words.
        assert entries.first.locator(".entry-takes").text_content() == (
            "In the plan: 32.00 paid; 32.00 still to buy; 136.00 left."
        )
        # The sum in USD of what the plan pays is about the OFFER that it still buys from.
        page.locator("#report .row", has_text="USD: 32.00 paid; 32.00 still to buy").hover()
        lit(page, rights=["skydeck-tickets"], marks=[], budgets=[])
        # The row of a PERSON names the BUDGETs that list them.
        assert page.locator("#persons .item-said p").all_text_contents() == [
            "May draw on the trip money.",
            "May draw on the trip money.",
            "No BUDGET of the FILE lists this PERSON.",
        ]
        # A cap is a thing of its own. The report states it twice on a plan: among what the
        # plan relies on, and with what is charged to it. Both lines are its lines.
        entries.first.hover()
        found = lit(page, budgets=["trip-cap"], marks=[], rights=[])
        assert [row.strip()[:25] for row in found["rows"]] == [
            "trip-cap: the TRIP spends",
            "trip-cap: at most 200.00 ",
        ]
        page.locator("#report .row[data-record='trip-cap']").nth(1).hover()
        lit(page, budgets=["trip-cap"], marks=[])
        # A payment is a drawing of its BOOKING: pointing at it lights up the BOOKING among
        # the rights, and its lines in the report.
        entries.nth(1).hover()
        found = lit(page, budgets=["alex-skydeck-ticket"], rights=["alex-skydeck-ticket"], marks=[])
        assert set(ids_of(found["rows"])) == {"alex-skydeck-ticket"}
    # Two BOOKINGs paid more from the trip money than its cap allows.
    with opened(chromium, EXAMPLES / "a-ticket" / "already-overspent.json") as page:
        page.locator("#budgets .entry.clash").first.wait_for()
        clash = page.locator("#budgets .entry.clash")
        assert clash.locator(".entry-name").all_text_contents() == [
            "trip-cap",
            "alex-skydeck-ticket",
            "jo-talk-ticket",
        ]
        # The report states the BUDGETs of the FILE. The line of each lights up its card.
        line = page.locator("#report .row", has_text="the trip money: for Alex and Sam")
        line.wait_for()
        line.hover()
        lit(page, budgets=["the trip money"], marks=[])
        page.locator("#budgets .card-name").hover()
        found = lit(page, budgets=["the trip money"], marks=[])
        assert found["rows"] == ["  the trip money: for Alex and Sam; it holds USD"]
    # Under the one plan for a case, the report states the cap with what that plan charges
    # to it. That line is about the cap.
    with opened(chromium, EXAMPLES / "a-ticket" / "depends-on-the-receipt.json") as page:
        page.locator("#budgets .entry").first.wait_for()
        line = page.locator("#report .row", has_text="trip-cap, on the trip money:")
        line.wait_for()
        said = line.text_content()
        line.hover()
        lit(page, budgets=["trip-cap"], marks=[])
        page.locator("#budgets .entry").first.hover()
        found = lit(page, budgets=["trip-cap"], marks=[])
        assert said in found["rows"]
    # A FILE with no BUDGET has no such part on its page.
    with opened(chromium, EXAMPLES / "flight-home" / "works.json") as page:
        page.locator("#report .row").first.wait_for()
        page.locator("#options .item").first.wait_for()
        assert page.locator("#budgets-part").is_hidden()
        assert page.locator("#persons .item-said p").count() == 0


def test_pointing_ties_an_object_to_the_calendar_and_the_report(
    chromium: Browser, tmp_path: Path
) -> None:
    """The bags are at the hotel. Alex collects them, and has them when the flight leaves."""
    with opened(chromium, EXAMPLES / "the-bags" / "they-collect-them.json") as page:
        card = page.locator("#objects .card")
        card.wait_for()
        page.locator("#report .row").first.wait_for()
        page.locator("#calendar .mark").first.wait_for()
        assert card.locator(".card-name").text_content() == "the bags"
        assert card.locator(".card-holds").text_content() == "The TRIP starts with it at the hotel."
        entries = card.locator(".entry")
        assert entries.locator(".entry-name").all_text_contents() == [
            "Flight home",
            "Collect the bags",
        ]
        assert entries.locator(".entry-says").all_text_contents() == [
            "requires it",
            "it can be handed over here",
        ]
        assert card.locator(".card-whole").all_text_contents() == [
            "The FILE states every one of its OPTIONs that requires it or refuses it.",
            "The FILE states every OPTION that hands it over, keeps it or carries it.",
            "The FILE states every one of its OPTIONs that needs a right for it, and it names"
            " none.",
        ]
        # The card says where the report says the bags are in its plan, worded as the report
        # words it: throughout, and just before the OPTION that requires them starts.
        assert card.locator(".card-plan").text_content() == (
            "In the plan: at the hotel when the TRIP starts; with Alex from 2:45 pm (handed over"
            " in Collect the bags)."
        )
        assert entries.locator(".entry-takes").all_text_contents() == [
            "In the plan: Alex and Sam take part.",
            "Just before it starts: with Alex.",
            "In the plan: Alex takes part.",
        ]
        # The card gives a time, so the part says whose clocks show it.
        assert " Times are on the clocks of America/Chicago." in (
            page.text_content("#objects-says") or ""
        )
        # Pointing at the OBJECT lights up the lines of its own FACTs, and the lines that say
        # where it is in the plan. It lights up no step.
        card.locator(".card-name").hover()
        found = lit(page, objects=["the bags"], marks=[])
        said = [row.strip() for row in found["rows"]]
        # They come in the order of the report: under the step, among what the plan relies
        # on, and under "Where each OBJECT is:".
        assert said[0] == "Alex takes the bags here."
        assert ids_of(said[1:5]) == [
            "where-the-bags-start",
            "every-use-of-the-bags",
            "everything-that-moves-the-bags",
            "every-ticket-for-the-bags",
        ]
        assert said[5:] == [
            "the bags: at the hotel when the TRIP starts; with Alex from 2:45 pm (handed over in"
            " Collect the bags)",
            "Flight home requires the bags. Just before it starts: with Alex.",
        ]
        # The line that says who takes the bags is about the step and about the OBJECT.
        page.locator("#report .row", has_text="Alex takes the bags here.").hover()
        lit(page, objects=["the bags", "Collect the bags"], marks=["Collect the bags"])
        # An OPTION under the OBJECT is its step: pointing at it lights up that step, its line
        # in the plan, the line of the FACT, and the line that says where the bags are then.
        entries.first.hover()
        found = lit(page, objects=["Flight home"], marks=["Flight home"])
        assert (
            "    Flight home requires the bags. Just before it starts: with Alex." in found["rows"]
        )
        assert "flight-needs-the-bags" in ids_of(found["rows"])
    # Nobody said where the bags are when the TRIP starts.
    with opened(chromium, EXAMPLES / "the-bags" / "nobody-said-where-they-are.json") as page:
        page.locator("#objects .card.asked").wait_for()
        assert page.text_content("#objects .card-holds") == (
            "The FILE does not say where it is when the TRIP starts."
        )
        case = page.locator("#report .row[data-record='case:0']")
        case.wait_for()
        case.hover()
        lit(page, objects=["the bags"], persons=["Alex"])
    # The trip might work if another transfer puts the bags at hand for the flight: the report
    # names the flight, and its step and its row have the yellow edge.
    with opened(chromium, EXAMPLES / "the-bags" / "somebody-might.json") as page:
        page.locator("#objects .card.asked").wait_for()
        asked = page.locator("#options .item.asked")
        asked.wait_for()
        assert asked.locator(".item-name").all_text_contents() == ["Flight home"]
        assert page.locator("#calendar .mark.asked").count() == 1
    # Nobody collects the bags, and the flight requires them. The report shows no plan, so
    # the card says nothing of one.
    with opened(chromium, EXAMPLES / "the-bags" / "nobody-collects-them.json") as page:
        page.locator("#objects .card.clash").wait_for()
        assert page.locator("#objects .entry.clash").count() >= 1
        assert page.locator("#objects .card-plan").count() == 0
        assert page.locator("#objects .entry-takes", has_text="Just before").count() == 0
    # The FILE does not say that the flight is all that requires the bags, and Alex carries
    # them. The report says of the museum visit that the FILE does not say whether it requires
    # them, and so does the card: that OPTION is under the OBJECT, and it is its step.
    content = json.loads((EXAMPLES / "the-bags" / "they-carry-them.json").read_text())
    content["facts"] = [fact for fact in content["facts"] if fact["id"] != "every-use-of-the-bags"]
    # FACTs say that neither OPTION refuses the bags, so the plan holds with Alex carrying them.
    content["facts"] += [
        {
            "id": f"{option}-lets-them-in",
            "option": option,
            "refuses": {"object": "bags", "refused": False},
        }
        for option in ("museum-visit", "flight")
    ]
    with opened(chromium, written(tmp_path, content)) as page:
        card = page.locator("#objects .card")
        card.wait_for()
        page.locator("#calendar .mark").first.wait_for()
        assert card.locator(".card-plan").text_content() == (
            "In the plan: with Alex when the TRIP starts."
        )
        # No card gives a time, and the part names no clocks.
        assert "clocks" not in (page.text_content("#objects-says") or "")
        # The entries that say that an OPTION does not refuse the bags are apart from it.
        assert card.locator(".entry.not .entry-says").all_text_contents() == [
            "does not refuse it",
            "does not refuse it",
            "the FILE does not say whether this requires it",
        ]
        might = card.locator(".entry.not", has_text="the FILE does not say")
        assert might.locator(".entry-name").all_text_contents() == ["Museum visit"]
        assert might.locator(".entry-says").all_text_contents() == [
            "the FILE does not say whether this requires it"
        ]
        assert might.locator(".entry-takes").all_text_contents() == [
            "In the plan: Alex and Sam take part.",
            "Just before it starts: with Alex, so the plan holds if it does.",
        ]
        assert "asked" not in (might.get_attribute("class") or "")
        line = (
            "    The FILE does not say whether Museum visit requires the bags. Just before it"
            " starts: with Alex, so the plan holds if it does."
        )
        # The visit is under the bags twice, and both entries are its step.
        might.hover()
        found = lit(page, objects=["Museum visit", "Museum visit"], marks=["Museum visit"])
        assert line in found["rows"]
        # That line of the report is about the step and about the OBJECT.
        page.locator("#report .row", has_text="The FILE does not say whether Museum").hover()
        lit(page, objects=["the bags", "Museum visit", "Museum visit"], marks=["Museum visit"])
    # A FILE with no OBJECT has no such part on its page.
    with opened(chromium, EXAMPLES / "flight-home" / "works.json") as page:
        page.locator("#report .row").first.wait_for()
        page.locator("#options .item").first.wait_for()
        assert page.locator("#objects-part").is_hidden()


def test_pointing_ties_a_place_to_the_calendar_and_the_report(chromium: Browser) -> None:
    """Alex and Sam start from the hotel, walk to the museum, and fly from O'Hare to Denver."""
    walk = "the walk between the hotel and the Art Institute"
    with opened(chromium, EXAMPLES / "ending-in-denver" / "works.json") as page:
        cards = page.locator("#places .card")
        cards.first.wait_for()
        page.locator("#report .row").first.wait_for()
        page.locator("#calendar .mark").first.wait_for()
        assert cards.locator(".card-name").all_text_contents() == [
            "the hotel",
            "the Art Institute",
            "O'Hare",
            "Denver",
        ]
        hotel, museum, ohare, denver = (cards.nth(n) for n in range(4))
        assert hotel.locator(".card-holds").all_text_contents() == ["Alex and Sam start from here."]
        assert hotel.locator(".entry-name").all_text_contents() == [walk]
        assert hotel.locator(".entry-says").all_text_contents() == [
            "between here and the Art Institute, in both directions"
        ]
        assert hotel.locator(".entry-takes").all_text_contents() == ["Takes 15 min."]
        assert museum.locator(".entry-name").all_text_contents() == [
            "Museum visit",
            "Blue Line to O'Hare",
            walk,
        ]
        assert museum.locator(".entry-says").all_text_contents() == [
            "happens here",
            "goes from here to O'Hare",
            "between here and the hotel, in both directions",
        ]
        assert ohare.locator(".entry-says").all_text_contents() == [
            "comes here from the Art Institute",
            "goes from here to Denver",
        ]
        assert denver.locator(".card-holds").all_text_contents() == [
            "Alex and Sam must end the TRIP here."
        ]
        # Pointing at a PLACE lights up the lines of its own records: here the FACTs about
        # who starts from it. It lights up no step and no PERSON.
        hotel.locator(".card-name").hover()
        found = lit(page, places=["the hotel"], marks=[], persons=[])
        assert ids_of(found["rows"]) == ["alex-start", "sam-start"]
        # The line of such a FACT is about the PERSON and about the PLACE.
        page.locator("#report .row[data-record='alex-start']").hover()
        lit(page, places=["the hotel"], persons=["Alex"])
        # A WANT about where the TRIP ends is about its PLACE too.
        denver.locator(".card-name").hover()
        found = lit(page, places=["Denver"], wants=[])
        assert ids_of(found["rows"]) == ["ending-in-denver"]
        page.locator("#report .row[data-record='ending-in-denver']").hover()
        lit(page, places=["Denver"], wants=["ending the trip in Denver"])
        # An OPTION under a PLACE is its step: pointing at it lights up that step, and the
        # OPTION under each PLACE that it is at.
        museum.locator(".entry").nth(1).hover()
        lit(page, places=["Blue Line to O'Hare"] * 2, marks=["Blue Line to O'Hare"])
        # A WAY under a PLACE is each step in which somebody takes it.
        hotel.locator(".entry").hover()
        lit(page, places=[walk, walk], marks=[walk], ways=[walk])
        # Pointing at a step lights up what is under the PLACEs, and no PLACE.
        page.locator("#calendar .mark", has_text="Museum visit").first.hover()
        lit(page, places=["Museum visit"], marks=["Museum visit"])
    # A WAY that nobody takes is a drawing of the WAY: here the report shows no plan. So
    # pointing at it under a PLACE lights up its row among the WAYs, and it under each of its
    # two PLACEs, and no other WAY. The other way round too.
    line = "the Blue Line to O'Hare"
    with opened(chromium, EXAMPLES / "the-bags" / "nobody-collects-them.json") as page:
        cards = page.locator("#places .card")
        cards.first.wait_for()
        page.locator("#ways .item").first.wait_for()
        cards.first.locator(".entry", has_text=walk).hover()
        lit(page, places=[walk, walk], ways=[walk], marks=[])
        page.locator("#ways .item", has_text=line).hover()
        lit(page, places=[line, line], ways=[line], marks=[])
    # The trip works if there are other WAYs from the Art Institute to O'Hare: the report
    # names the two PLACEs, and each has the yellow edge.
    with opened(chromium, EXAMPLES / "flight-home" / "depends-on-another-way.json") as page:
        asked = page.locator("#places .card.asked")
        asked.first.wait_for()
        assert asked.locator(".card-name").all_text_contents() == ["the Art Institute", "O'Hare"]
        assert "A yellow edge marks" in (page.text_content("#places-says") or "")
        case = page.locator("#report .row[data-record='case:0']")
        case.wait_for()
        case.hover()
        lit(page, places=["the Art Institute", "O'Hare"])
        asked.first.locator(".card-name").hover()
        found = lit(page, places=["the Art Institute"])
        assert [row.strip()[:40] for row in found["rows"]] == [
            "The trip works if there are other WAYs f"
        ]
    # Alex and Sam cannot end the TRIP in Denver: the report names the WANT, and its PLACE
    # has the red edge.
    with opened(chromium, EXAMPLES / "ending-in-denver" / "cannot-work.json") as page:
        clash = page.locator("#places .card.clash")
        clash.first.wait_for()
        assert clash.locator(".card-name").all_text_contents() == ["Denver"]
        assert page.locator("#places .entry.clash").count() == 0


def test_on_a_wide_window_the_report_stays_beside_the_drawings(chromium: Browser) -> None:
    """The page fills the window, and the drawings and the report each scroll by themselves."""
    path = EXAMPLES / "the-bags" / "they-collect-them.json"
    to_its_end = (
        "() => { const r = document.getElementById('report'); r.scrollTop = r.scrollHeight; }"
    )
    with opened(chromium, path, wide=1728, tall=700) as page:
        page.locator("#objects .card").wait_for()
        page.locator("#report .row").first.wait_for()
        page.locator("#calendar .mark").first.wait_for()
        placed = page.evaluate(PLACED)
        # The report is to the right of the drawings, and both are in the window from top to
        # bottom. The page itself does not scroll.
        assert placed["report"]["left"] >= placed["drawings"]["right"]
        assert abs(placed["report"]["top"] - placed["drawings"]["top"]) < 2
        for pane in (placed["report"], placed["drawings"]):
            assert pane["top"] >= 0 and pane["bottom"] <= placed["tall"]
        assert page.evaluate("() => document.documentElement.scrollHeight <= innerHeight")
        # The drawings scroll by themselves: the last of them comes into view, and the report
        # and the answer stay where they are.
        page.locator("#objects .card-name").scroll_into_view_if_needed()
        assert page.locator("#objects .card-name").is_visible()
        assert page.evaluate("() => document.getElementById('drawings').scrollTop") > 0
        assert page.evaluate(PLACED)["report"] == placed["report"]
        assert page.locator("#line").bounding_box() is not None
        # The report is scrolled to its end, where no line about where Alex starts from is.
        # Pointing at Alex brings that line into view there.
        page.evaluate(to_its_end)
        page.locator("#persons .item").first.hover()
        found = lit(page, persons=["Alex"])
        assert ids_of(found["rows"]) == ["alex-start"]
        page.wait_for_function(f"() => ({PLACED})().shown === 1")
        # Pointing at the OBJECT lights up seven lines. One is in view already, so nothing moves.
        before = page.evaluate(PLACED)["at"]
        page.locator("#objects .card-name").hover()
        lit(page, objects=["the bags"])
        placed = page.evaluate(PLACED)
        assert (placed["lit"], placed["shown"] > 0, placed["at"]) == (7, True, before)
        # A line of the report that is pointed at stays where it is.
        row = page.locator("#report .row[data-record='flight-needs-the-bags']")
        row.scroll_into_view_if_needed()
        before = row.bounding_box()
        row.hover()
        lit(page, objects=["Flight home"], marks=["Flight home"])
        assert row.bounding_box() == before
    # On a shorter and narrower window that is still wide, pointing at where the TRIP starts
    # brings its line into view. Only the report moves, so what is under the pointer is still
    # what was pointed at.
    with opened(chromium, path, wide=1400, tall=700) as page:
        page.locator("#report .row").first.wait_for()
        starts = page.locator("#calendar .bound-says").first
        starts.wait_for()
        starts.hover()
        page.wait_for_function(f"() => ({PLACED})().shown === 1")
        placed = page.evaluate(PLACED)
        assert (placed["lit"], placed["page"]) == (1, 0)
        assert page.evaluate("() => [...document.querySelectorAll(':hover')].pop().className") == (
            "bound-says lit"
        )
        # The reader scrolls the report to its end. Moving on within the same drawing leaves
        # the report where the reader put it.
        alex = page.locator("#persons .item").first
        alex.locator(".item-name").hover()
        lit(page, persons=["Alex"])
        page.wait_for_function(f"() => ({PLACED})().shown === 1")
        page.evaluate(to_its_end)
        end = page.evaluate(PLACED)["at"]
        assert end > 0
        alex.locator(".item-where").hover()
        lit(page, persons=["Alex"])
        assert page.evaluate(PLACED)["at"] == end
        # The keyboard reaches both panes, and End takes the report to its last line.
        for pane in ("#drawings", "#report", "#calendar"):
            assert page.locator(pane).get_attribute("tabindex") == "0"
        page.evaluate("() => { document.getElementById('report').scrollTop = 0; }")
        page.locator("#drawings").focus()
        # Tab stops once in each part on its way to the report.
        for _ in range(16):
            page.keyboard.press("Tab")
            if page.evaluate("() => document.activeElement.id") == "report":
                break
        assert page.evaluate("() => document.activeElement.id") == "report"
        page.keyboard.press("End")
        page.wait_for_function(
            "() => { const r = document.getElementById('report');"
            " return r.scrollTop + r.clientHeight >= r.scrollHeight - 1; }"
        )
    # The line of a WAY and its name beside it are one drawing. On a short window no line
    # about the WAY is in view at the end of the report. The reader's scrolling stands while
    # the pointer moves from the name to the line.
    with opened(chromium, path, wide=1400, tall=500) as page:
        page.locator("#report .row").first.wait_for()
        name = page.locator("#calendar .way-name").first
        name.hover()
        page.wait_for_function("() => document.querySelector('#calendar .way-name.lit') !== null")
        page.evaluate(to_its_end)
        placed = page.evaluate(PLACED)
        assert (placed["shown"], placed["at"] > 0) == (0, True)
        line = page.locator(f"#calendar .mark.way[data-of='{name.get_attribute('data-of')}']")
        line.locator(".stripe").first.hover()
        page.wait_for_function("() => document.querySelector('#calendar .stripe:hover') !== null")
        assert page.locator("#calendar .way-name.lit").count() == 1
        assert page.evaluate(PLACED)["at"] == placed["at"]
    # A window too short for its panes shows the upper part of the report. A line that is
    # lit under the window is brought into the part that the window shows.
    with opened(chromium, path, wide=1400, tall=460) as page:
        page.locator("#report .row").first.wait_for()
        page.locator("#persons .item").first.scroll_into_view_if_needed()
        below = page.evaluate(
            """() => {
              const report = document.getElementById("report");
              const row = report.querySelector(".row[data-record='alex-start']");
              report.scrollTop += row.getBoundingClientRect().top - innerHeight - 1;
              const at = row.getBoundingClientRect();
              const box = report.getBoundingClientRect();
              return at.top >= innerHeight && at.bottom <= box.bottom;
            }"""
        )
        assert below, "the line is not under the window and inside its pane"
        page.locator("#persons .item").first.hover()
        lit(page, persons=["Alex"])
        page.wait_for_function(f"() => ({PLACED})().shown === 1")
    # A shallow window keeps panes that a reader can use: the whole of it scrolls instead.
    with opened(chromium, path, wide=1400, tall=260) as page:
        page.locator("#report .row").first.wait_for()
        page.locator("#calendar .mark").first.wait_for()
        placed = page.evaluate(PLACED)
        assert placed["drawings"]["bottom"] - placed["drawings"]["top"] >= 300
        page.locator("#calendar .mark").first.hover()
        lit(page, marks=["Museum visit"])
    # A short report, at the top of the page: the one line about where the TRIP starts is
    # shown in the window once it is pointed at.
    with opened(chromium, EXAMPLES / "the-times-of-the-trip" / "works.json", 1400, 700) as page:
        page.locator("#report .row").first.wait_for()
        starts = page.locator("#calendar .bound-says").first
        starts.wait_for()
        starts.hover()
        page.wait_for_function(f"() => ({PLACED})().shown === 1")
        assert page.evaluate(PLACED)["page"] == 0
    # On a narrower window the page scrolls as a whole: the report is below the drawings, and
    # has no scrolling of its own.
    with opened(chromium, path, wide=1280, tall=700) as page:
        page.locator("#objects .card").wait_for()
        page.locator("#report .row").first.wait_for()
        placed = page.evaluate(PLACED)
        assert placed["report"]["top"] >= placed["drawings"]["bottom"]
        assert placed["scrolls"] is False
        assert page.evaluate("() => document.documentElement.scrollHeight > innerHeight")


def test_the_keyboard_moves_a_calendar_that_is_wider_than_its_room(
    chromium: Browser, tmp_path: Path
) -> None:
    """A train just after midnight, and brunch two weeks later: more days than fit side by side."""
    with opened(chromium, written(tmp_path, crowded()), wide=1400, tall=700) as page:
        calendar = page.locator("#calendar")
        page.locator("#calendar .mark").first.wait_for()
        assert calendar.get_attribute("aria-label") == "The calendar"
        box = "document.getElementById('calendar')"
        assert page.evaluate(f"() => {box}.scrollWidth > {box}.clientWidth")
        calendar.focus()
        page.keyboard.press("ArrowRight")
        page.wait_for_function(f"() => {box}.scrollLeft > 0")


def test_pointing_ties_a_way_to_the_calendar_and_the_report(chromium: Browser) -> None:
    """Alex walks from the tower to the park, between the Skydeck visit and lunch."""
    walk = "the walk between Willis Tower and Millennium Park"
    with opened(chromium, EXAMPLES / "a-must-not" / "works.json") as page:
        row = page.locator("#ways .item")
        row.wait_for()
        page.locator("#report .row").first.wait_for()
        page.locator("#calendar .mark").first.wait_for()
        assert row.locator(".item-name").text_content() == walk
        assert row.locator(".item-where").text_content() == (
            "Between Willis Tower and Millennium Park, in both directions."
        )
        assert row.locator(".item-said p").all_text_contents() == [
            "Takes 20 min.",
            "In the plan: Alex takes it at 11:30 am on Saturday 15 May 2027.",
        ]
        assert page.locator("#travel").is_hidden()
        # Pointing at the WAY lights up the step in which Alex takes it, its line in the plan,
        # and the line of the FACT about how long it takes.
        row.hover()
        found = lit(page, ways=[walk], marks=[walk])
        assert found["rows"] == [
            f"  11:30 am to 11:50 am: {walk}, Alex",
            f"  walk-from-tower-length: {walk} takes 20 min",
        ]
        # Pointing at the step, or at the line of the FACT, lights up the WAY.
        page.locator("#calendar .mark.way").first.hover()
        lit(page, ways=[walk], marks=[walk])
        page.locator("#report .row[data-record='walk-from-tower-length']").hover()
        lit(page, ways=[walk], marks=[walk])
        # Pointing at an OPTION lights up no WAY.
        page.locator("#options .item").first.hover()
        lit(page, ways=[], marks=["Skydeck visit"])


def test_a_way_that_somebody_takes_twice_is_tied_to_both_steps(
    chromium: Browser, tmp_path: Path
) -> None:
    """Alex walks to the pier for a swim, and back to the hotel for dinner."""
    content = {
        "persons": named("alex"),
        "places": named("hotel", "pier"),
        "budgets": [budget("money", "alex")],
        "options": [stays("swim", "pier"), stays("dinner", "hotel")],
        "ways": [way_between("walk", "hotel", "pier")],
        "wants": [],
        "facts": [
            *at("swim", "2027-05-15T10:00:00", "PT1H"),
            *at("dinner", "2027-05-15T18:00:00", "PT1H"),
            takes("walk", "PT10M"),
            starts("alex", "hotel"),
        ],
        "decisions": [lock("swim", "alex"), lock("dinner", "alex")],
    }
    with opened(chromium, written(tmp_path, content)) as page:
        row = page.locator("#ways .item")
        row.wait_for()
        page.locator("#report .row").first.wait_for()
        walks = page.locator("#calendar .mark.way")
        walks.first.wait_for()
        assert walks.count() == 2
        assert len(row.locator(".item-said").nth(1).locator("p").all_text_contents()) == 2
        # Pointing at the WAY lights up both steps, and the line of each in the plan.
        row.hover()
        page.wait_for_function(
            "() => document.querySelectorAll('#calendar .mark.way.lit').length === 2"
        )
        found = lit(page, ways=["walk"])
        assert [line.strip().split(": ")[1] for line in found["rows"][:2]] == ["walk, alex"] * 2
        # Pointing at one of the steps lights up the WAY, and not the other step.
        walks.first.hover()
        page.wait_for_function(
            "() => document.querySelectorAll('#calendar .mark.way.lit').length === 1"
        )
        lit(page, ways=["walk"])
        # The line of the FACT about its length is about the WAY: both steps light up.
        page.locator("#report .row[data-record='walk-length']").hover()
        page.wait_for_function(
            "() => document.querySelectorAll('#calendar .mark.way.lit').length === 2"
        )
        lit(page, ways=["walk"])


def test_a_way_and_travel_listed_in_full_have_the_edges_of_what_the_report_names(
    chromium: Browser,
) -> None:
    """The walk to the dock takes too long, and the FILE lists every way of that day."""
    dock = "the walk between Millennium Park and the Riverwalk dock"
    with opened(chromium, EXAMPLES / "a-day" / "cannot-work.json") as page:
        clash = page.locator("#ways .item.clash")
        clash.wait_for()
        assert clash.locator(".item-name").all_text_contents() == [dock]
        assert clash.get_attribute("title") == (
            "The report names walk-to-dock-length among what rules out every plan."
        )
        in_full = page.locator("#travel .in-full")
        said = (
            "Every way from one PLACE straight to another that leaves between 12:00 am on"
            " Friday 14 May 2027 and 11:59 pm is listed."
        )
        assert in_full.all_text_contents() == [said]
        assert page.locator("#travel .in-full.clash").count() == 1
        # Pointing at the line of that FACT lights up what the page says of it, and no WAY.
        line = page.locator("#report .row[data-record='all-ways']")
        line.wait_for()
        line.hover()
        lit(page, travel=[said], ways=[], marks=[])
        in_full.hover()
        found = lit(page, travel=[said], ways=[], marks=[])
        assert ids_of(found["rows"]) == ["all-ways"]
    # The trip depends on how long the walk to the dock takes.
    with opened(chromium, EXAMPLES / "a-day" / "depends-on-the-walk.json") as page:
        asked = page.locator("#ways .item.asked")
        asked.wait_for()
        assert asked.locator(".item-name").all_text_contents() == [dock]
        assert asked.locator(".item-said p").all_text_contents() == [
            "The FILE does not say how long it takes."
        ]
        case = page.locator("#report .row[data-record='case:0']")
        case.wait_for()
        assert asked.get_attribute("title") == case.text_content()
        case.hover()
        lit(page, ways=[dock])
    # A FILE with no WAY, and no travel that it lists in full, has no such part on its page.
    with opened(chromium, EXAMPLES / "flight-home" / "works.json") as page:
        page.locator("#report .row").first.wait_for()
        page.locator("#options .item").first.wait_for()
        assert page.locator("#ways-part").is_hidden()


def test_pointing_ties_a_capability_to_the_calendar_and_the_report(chromium: Browser) -> None:
    """Two drives require driving a manual car of one PERSON. Sam has it, and takes both."""
    with opened(chromium, EXAMPLES / "a-driver" / "every-drive-is-stated.json") as page:
        page.locator("#capabilities .card").wait_for()
        page.locator("#report .row").first.wait_for()
        page.locator("#calendar .mark").first.wait_for()
        assert page.text_content("#capabilities .card-name") == "driving a manual car"
        assert page.locator("#capabilities .has").all_text_contents() == [
            "Alex:does not have it",
            "Sam:has it",
            "Jo:does not have it",
        ]
        drive = page.locator("#capabilities .entry").first
        assert drive.locator("span").all_text_contents() == [
            "requires it of one PERSON who takes part",
            "In the plan: Alex and Sam take part. Sam meets that requirement.",
        ]
        # Pointing at an OPTION under the CAPABILITY lights up its step, its row, its line in
        # the plan, the line that says who meets what it requires, and the line of the FACT.
        drive.hover()
        found = lit(
            page,
            marks=["Drive to the dunes"],
            options=["Drive to the dunes"],
            capabilities=["Drive to the dunes"],
        )
        assert found["rows"] == [
            "  8:00 am to 9:00 am: Drive to the dunes, Alex and Sam",
            "  drive-out-needs-a-driver: Drive to the dunes requires driving a manual car"
            " of one PERSON who takes part",
            "  Drive to the dunes requires driving a manual car of one PERSON."
            " Sam meets that requirement.",
        ]
        # Pointing at the line that says who meets it lights up every drawing of the drive.
        page.locator("#report .row", has_text="Sam meets that requirement.").first.hover()
        lit(
            page,
            marks=["Drive to the dunes"],
            options=["Drive to the dunes"],
            capabilities=["Drive to the dunes"],
        )
        # The FACT that these are all the OPTIONs that require it is about the CAPABILITY.
        page.locator("#report .row[data-record='every-drive-that-needs-a-driver']").hover()
        lit(page, marks=[], options=[], capabilities=["driving a manual car"])
        page.locator("#capabilities .card-name").hover()
        found = lit(page, marks=[], options=[], capabilities=["driving a manual car"])
        assert ids_of(found["rows"]) == ["every-drive-that-needs-a-driver"]
        # What the FILE says of Sam and driving is a thing of its own.
        page.locator("#capabilities .has").nth(1).hover()
        found = lit(page, marks=[], options=[], capabilities=["Sam:"])
        assert ids_of(found["rows"]) == ["sam-drives-manual"]
        page.locator("#report .row[data-record='sam-drives-manual']").hover()
        lit(page, marks=[], options=[], capabilities=["Sam:"])


def test_a_capability_has_the_edges_of_what_the_report_names(chromium: Browser) -> None:
    """The trip works if Alex can drive a manual car, or if Sam can."""
    with opened(chromium, EXAMPLES / "a-driver" / "depends-on-who-can-drive.json") as page:
        asked = page.locator("#capabilities .has.asked")
        asked.first.wait_for()
        assert asked.all_text_contents() == [
            "Alex:the FILE does not say",
            "Sam:the FILE does not say",
        ]
        assert asked.first.get_attribute("title") == (
            "Alex: the FILE does not say\n"
            "The trip works in any of these cases:\n"
            "1. Alex has the CAPABILITY driving a manual car."
        )
        assert page.locator("#capabilities .card.asked").count() == 1
        assert (page.text_content("#capabilities-says") or "").endswith(
            " A yellow edge marks what the report names in what the FILE does not say."
        )
        # Pointing at the line of a case lights up the PERSON it is about, and the CAPABILITY.
        case = page.locator("#report .row[data-record='case:1']")
        case.wait_for()
        case.hover()
        lit(page, marks=[], capabilities=["driving a manual car", "Sam:"])
    # Nobody of the FILE can drive a manual car, and the drive back requires it.
    with opened(chromium, EXAMPLES / "a-driver" / "cannot-work.json") as page:
        page.locator("#capabilities .has.clash").first.wait_for()
        assert page.locator("#capabilities .has.clash").count() == 3
        clash = page.locator("#capabilities .entry.clash")
        assert clash.locator(".entry-name").all_text_contents() == ["Drive back to the hotel"]
        assert page.locator("#capabilities .card.clash").count() == 0
    # A FILE with no CAPABILITY has no such part on its page.
    with opened(chromium, EXAMPLES / "flight-home" / "works.json") as page:
        page.locator("#report .row").first.wait_for()
        page.locator("#options .item").first.wait_for()
        assert page.locator("#capabilities-part").is_hidden()


def test_a_long_name_under_a_want_lies_on_nothing(chromium: Browser, tmp_path: Path) -> None:
    """What the FILE says of an OPTION goes below its name where the two do not fit on a line."""
    content = json.loads((EXAMPLES / "a-must-not" / "works.json").read_text())
    # A name with a long word in it, which cannot break at a space.
    content["options"][0]["name"] = "Neuschwanstein Castle"
    content["options"][1]["name"] = "Lunch at the Hohenschwangau village restaurant"
    # Where the words of each are on the page, whatever box holds them.
    apart = """() => [...document.querySelectorAll("#wants .entry")].map((item) => {
      const words = (which) => {
        const range = document.createRange();
        range.selectNodeContents(item.querySelector(which));
        return range.getBoundingClientRect();
      };
      const [name, says] = [words(".entry-name"), words(".entry-says")];
      const box = item.getBoundingClientRect();
      const across = name.right <= says.left + 0.5 || says.right <= name.left + 0.5;
      const down = name.bottom <= says.top + 0.5 || says.bottom <= name.top + 0.5;
      const inside = name.right <= box.right + 0.5 && says.right <= box.right + 0.5;
      return (across || down) && inside;
    })"""
    with opened(chromium, written(tmp_path, content)) as page:
        page.locator("#wants .entry").first.wait_for()
        for wide in [1280, 980, 700]:
            page.set_viewport_size({"width": wide, "height": 1000})
            assert page.evaluate(apart) == [True, True], wide


def test_a_long_word_in_the_name_of_a_want_stays_on_its_card(
    chromium: Browser, tmp_path: Path
) -> None:
    """Two WANTs side by side, and the first is named with a word longer than its card."""
    content = json.loads((EXAMPLES / "a-must-not" / "works.json").read_text())
    (view,) = content["wants"]
    long = "Llanfairpwllgwyngyllgogerychwyrndrobwllllantysiliogogogoch"
    content["wants"] = [
        {**view, "name": f"Visit {long}"},
        {**view, "id": "air", "name": "Eat outdoors"},
    ]
    inside = """() => [...document.querySelectorAll("#wants .card")].map((card) => {
      const range = document.createRange();
      range.selectNodeContents(card.querySelector(".card-name"));
      return range.getBoundingClientRect().right <= card.getBoundingClientRect().right + 0.5;
    })"""
    with opened(chromium, written(tmp_path, content)) as page:
        page.locator("#wants .card").first.wait_for()
        assert page.locator("#wants .card").count() == 2
        for wide in [1280, 700, 420]:
            page.set_viewport_size({"width": wide, "height": 1000})
            assert page.evaluate(inside) == [True, True], wide
            # The page is no wider than its window.
            assert page.evaluate("() => document.documentElement.scrollWidth <= innerWidth"), wide


def test_a_step_with_no_time_lights_up_alone(chromium: Browser, tmp_path: Path) -> None:
    """Two drives are in one case of the report, and the FILE gives the second no time."""
    content = json.loads((EXAMPLES / "a-driver" / "depends-on-the-car.json").read_text())
    content["facts"] = [each for each in content["facts"] if each["id"] != "drive-back-time"]
    with opened(chromium, written(tmp_path, content)) as page:
        case = page.locator("#report .row[data-record='case:0']")
        case.wait_for()
        said = case.text_content()
        assert said is not None and said.startswith("The trip works if ")
        untimed = page.locator("#calendar-untimed span")
        assert untimed.count() == 1
        back = untimed.first.text_content()
        assert back is not None and back.startswith("Drive back to the hotel")
        # Pointing at the drive on the calendar lights up that drive, and the line of its case.
        page.locator("#calendar .mark.asked").first.hover()
        lit(page, marks=["Drive to the dunes"], untimed=[], rows=[said])
        # Pointing at the drive with no time lights up that one, and the line of its case.
        untimed.first.hover()
        lit(page, marks=[], untimed=[back], rows=[said])
        # Pointing at the line of the case lights up both.
        case.hover()
        lit(page, marks=["Drive to the dunes"], untimed=[back], rows=[said])


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
    says = "\n".join(
        [
            "2 steps too close together to show apart at this width:",
            "first-stop, 8:00 am to an unknown time",
            "    The trip works if first-stop takes 2 min or less.",
            "second-stop, 8:02 am to 8:03 am",
        ]
    )
    with opened(chromium, written(tmp_path, content), wide=700) as page:
        page.locator("#report .row[data-record='case:0']").wait_for()
        several = page.locator("#strip .bar.several.asked")
        several.wait_for()
        assert page.locator("#strip .bar.several").count() == 1
        # The pointer rests on the two ticks inside the mark: those are what says so.
        ticks = several.locator(".bar-several")
        assert ticks.get_attribute("title") == says
        assert several.get_attribute("title") == says
        # Pointing at it lights up both steps on the calendar, and the line of the case.
        ticks.hover()
        lit(
            page,
            marks=["first-stop", "second-stop"],
            rows=["The trip works if first-stop takes 2 min or less."],
        )


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
        title = several.first.locator(".bar-several").get_attribute("title") or ""
        assert title.startswith("3 steps too close together to show apart at this width:")
        assert [line.split(",")[0] for line in title.split("\n")[1:]] == ["door", "stairs", "gate"]
        for wide in [1280, 700, 420]:
            page.set_viewport_size({"width": wide, "height": 1000})
            # The strip is laid out again in the room that the window has.
            page.wait_for_function(FITTED)
            # Each step of the calendar is on the strip, in the row of each of its PERSONs:
            # three WAYs and the train for both, and brunch for Alex.
            stands = page.evaluate(STANDS_FOR)
            assert len(stands["wanted"]) == 9, wide
            assert stands["missing"] == [], wide
            reached = page.evaluate(REACHED)
            assert [each for each in reached if not each["hits"]] == [], wide
            rows = page.locator("#strip .strip-rows").bounding_box()
            box = page.locator("#strip").bounding_box()
            assert rows is not None and box is not None
            assert rows["x"] + rows["width"] <= box["x"] + box["width"], wide


def test_a_click_on_the_strip_brings_the_step_into_view(chromium: Browser, tmp_path: Path) -> None:
    """Four PERSONs and three days, in a window too small for the calendar either way."""
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
    with opened(chromium, written(tmp_path, content), wide=620, tall=500) as page:
        page.wait_for_function(FITTED)
        grid = page.locator("#calendar")
        assert grid.evaluate("(grid) => grid.scrollWidth > grid.clientWidth + 100")
        dinner = page.locator("#strip .bar").first
        brunch = page.locator("#strip .bar").last
        assert (dinner.get_attribute("title") or "").startswith("dinner")
        assert (brunch.get_attribute("title") or "").startswith("brunch")
        # Dinner is on the first day, below what the window shows. A click brings it up.
        assert page.evaluate(INSIDE, "dinner") == {"across": True, "down": False}
        dinner.click()
        assert page.evaluate(INSIDE, "dinner") == {"across": True, "down": True}
        assert grid.evaluate("(grid) => grid.scrollLeft") == 0
        # Brunch is on the third day, to the right of what the calendar shows.
        assert page.evaluate(INSIDE, "brunch")["across"] is False
        brunch.click()
        assert page.evaluate(INSIDE, "brunch") == {"across": True, "down": True}
        assert grid.evaluate("(grid) => grid.scrollLeft") > 0
        # And back to the left, to dinner.
        assert page.evaluate(INSIDE, "dinner")["across"] is False
        dinner.click()
        assert page.evaluate(INSIDE, "dinner") == {"across": True, "down": True}
        assert grid.evaluate("(grid) => grid.scrollLeft") == 0
        # The keyboard does what the click does. End takes it to the last mark of the strip,
        # and Enter brings that step into view.
        dinner.focus()
        page.keyboard.press("End")
        assert (page.evaluate("() => document.activeElement.title") or "").startswith("brunch")
        assert page.evaluate(INSIDE, "brunch")["across"] is False
        page.keyboard.press("Enter")
        assert page.evaluate(INSIDE, "brunch") == {"across": True, "down": True}
        assert grid.evaluate("(grid) => grid.scrollLeft") > 0
        # Space does the same, and the keyboard stays on the mark. The names of the PERSONs
        # come before the marks of the strip, so the arrow keys go back to dinner.
        page.keyboard.press("ArrowLeft")
        page.keyboard.press("ArrowLeft")
        assert (page.evaluate("() => document.activeElement.title") or "").startswith("dinner")
        assert page.evaluate(INSIDE, "dinner")["across"] is False
        page.keyboard.press("Space")
        assert page.evaluate(INSIDE, "dinner") == {"across": True, "down": True}
        assert grid.evaluate("(grid) => grid.scrollLeft") == 0
        assert (page.evaluate("() => document.activeElement.title") or "").startswith("dinner")
        # With Shift, Control, Alt or Meta, the key is the browser's.
        page.keyboard.press("End")
        for held in ["Shift", "Control", "Alt", "Meta"]:
            page.keyboard.press(f"{held}+Enter")
            assert page.evaluate(INSIDE, "brunch")["across"] is False, held
        # A mark of the strip says to a reader who cannot see it that it can be pressed.
        assert brunch.get_attribute("role") == "button"
        # A mark of the calendar does nothing when it is pressed, and does not say so.
        assert page.locator("#calendar .mark").first.get_attribute("role") is None


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
    # Without the WANTs: the calendar and the report.
    path = EXAMPLES / "a-must-not" / "works.json"
    expected = path.with_name(f"{path.stem}.expected.txt").read_text()
    with opened(chromium, path, without=("wants.js",)) as page:
        page.locator("#report .row").first.wait_for()
        page.locator("#calendar .mark").first.wait_for()
        assert page.locator("#wants-part").is_hidden()
        assert page.text_content("#report") == expected
    # Without the OPTIONs: the same, and the WANTs are there.
    with opened(chromium, path, without=("options.js",)) as page:
        page.locator("#report .row").first.wait_for()
        page.locator("#wants .card").first.wait_for()
        assert page.locator("#options-part").is_hidden()
        assert page.text_content("#report") == expected
    # With a fault in the WANTs: the same, and the fault is not swallowed.
    faults: list[str] = []
    code = 'export function wants() { throw new Error("a fault in the WANTs"); }'
    with opened(chromium, path, faulty=("wants.js", code, faults)) as page:
        page.locator("#report .row").first.wait_for()
        page.locator("#calendar .mark").first.wait_for()
        page.wait_for_function("() => window.faults > 0")
        assert page.locator("#wants-part").is_hidden()
        assert page.locator("#calendar .mark").count() == 3
        assert page.locator("#options .item").count() == 2
        assert page.text_content("#report") == expected
    assert faults and all("a fault in the WANTs" in fault for fault in faults)
    path = EXAMPLES / "several-days" / "works-but-risky.json"
    expected = path.with_name(f"{path.stem}.expected.txt").read_text()
    # Without the ties of the lines: the report as it is, and a calendar with no yellow edge.
    # The page asks for its strip last, so with the strip on the page nothing is still to come.
    with opened(chromium, path, without=("lines.js",)) as page:
        page.locator("#strip .bar").first.wait_for()
        assert page.text_content("#report") == expected
        assert page.locator("#report .row").count() == 0
        assert page.locator("#calendar .mark").count() > 3
        assert page.locator("#calendar .mark.warned").count() == 0


class Gateway:
    """A gateway in front of a view, as its owner would run one, for a browser of a test.

    It speaks to the browser over a secured line, with a certificate that it makes for the
    test and that nobody trusts. It passes each request on to the view under the name that
    the browser asked for, with what the browser said of itself, and passes what the view
    answers back as it comes. ``port`` is where it listens. ``to`` is the view, once there is
    one: the view needs the port of the gateway for its name.
    """

    def __init__(self, folder: Path) -> None:
        self.to: View | None = None
        gateway = self

        class Passed(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                """Nothing is logged."""

            def do_GET(self) -> None:
                view = gateway.to
                assert view is not None
                between = {"connection", "transfer-encoding"}
                said = {
                    name: value
                    for name, value in self.headers.items()
                    if name.lower() not in between
                }
                onward = http.client.HTTPConnection("127.0.0.1", port_of(view), timeout=120)
                try:
                    onward.request("GET", self.path, headers=said)
                    reply = onward.getresponse()
                    self.send_response(reply.status)
                    for name, value in reply.getheaders():
                        if name.lower() not in between:
                            self.send_header(name, value)
                    self.end_headers()
                    while chunk := reply.read1(65536):
                        self.wfile.write(chunk)
                        self.wfile.flush()
                except OSError:
                    return  # the browser or the view has gone
                finally:
                    onward.close()

        key, certificate = folder / "gateway.key", folder / "gateway.pem"
        made = ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1"]
        made += ["-subj", "/CN=view.example.org", "-keyout", str(key), "-out", str(certificate)]
        subprocess.run(made, check=True, capture_output=True)
        secured = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        secured.load_cert_chain(certificate, key)
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Passed)
        self._server.daemon_threads = True
        self._server.socket = secured.wrap_socket(self._server.socket, server_side=True)
        self.port = int(self._server.server_address[1])
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=20)


def test_the_page_works_through_a_gateway_under_the_name_of_the_gateway(
    chromium: Browser, tmp_path: Path
) -> None:
    """The owner of the view gives it the name of a gateway. A browser on another machine asks
    the gateway for that name over a secured line, and gets the whole page: the answer, the
    report, the calendar, and each change to the FILE. A sign-in on another site can send the
    reader back to the page. Under another name the view refuses the browser."""
    if shutil.which("openssl") is None:
        if os.environ.get("CI"):
            pytest.fail(
                "the checks need openssl, to make a certificate for the gateway of this test"
            )
        pytest.skip(
            "no openssl on this machine, to make a certificate for the gateway of this test"
        )
    path = tmp_path / "trip.json"
    path.write_bytes((EXAMPLES / "ending-in-denver" / "works.json").read_bytes())
    gateway = Gateway(tmp_path)
    # A browser of its own: every name under example.org is this machine, and the certificate
    # of the gateway is taken as it is.
    browser = chromium.browser_type.launch(
        args=["--host-resolver-rules=MAP *.example.org 127.0.0.1", "--ignore-certificate-errors"]
    )
    name = f"view.example.org:{gateway.port}"
    address = f"https://{name}/"
    try:
        with serving(path, allowed_host=name) as view:
            gateway.to = view
            page = browser.new_page()
            problems: list[str] = []
            page.on("pageerror", lambda problem: problems.append(str(problem)))
            got = page.goto(address)
            assert got is not None and got.status == 200
            page.wait_for_function(ANSWERED, timeout=60_000)
            assert (page.text_content("#line") or "").startswith("FEASIBLE")
            page.locator("#calendar .mark").first.wait_for()
            page.locator("#report .row").first.wait_for()
            page.locator("#ways .item").first.wait_for()
            assert page.evaluate("() => [location.protocol, location.host]") == ["https:", name]
            # The page follows the FILE through the gateway.
            changed = json.loads(path.read_text())
            changed["persons"][0]["name"] = "Alexandra"
            put(path, json.dumps(changed).encode())
            page.locator("#persons .item-name", has_text="Alexandra").wait_for()
            page.locator("#report .row", has_text="Alexandra").first.wait_for()
            assert problems == []
            # Under a name that the owner did not give, the view refuses the same browser.
            refused = browser.new_page().goto(f"https://other.example.org:{gateway.port}/")
            assert refused is not None and refused.status == 403
            # A sign-in on another site sends its reader back with a link. The page opens.
            # The page of that site reads nothing of the view, and when it opens the view in
            # a window, it keeps no hold on that window.
            elsewhere = f"""<!doctype html><title>a sign-in</title>
              <a id="back" href="{address}">back to the view</a>
              <script>
                window.read = null;
                fetch("{address}events").then(
                  () => {{ window.read = "read"; }},
                  () => {{ window.read = "refused"; }},
                );
                window.opened = window.open("{address}");
              </script>"""
            signin = browser.new_page()
            signin.route(
                "https://signin.example.net/**",
                lambda route: route.fulfill(body=elsewhere, content_type="text/html"),
            )
            with signin.context.expect_page() as popup:
                signin.goto("https://signin.example.net/")
            popup.value.wait_for_function(ANSWERED, timeout=60_000)
            signin.wait_for_function("() => window.read !== null")
            assert signin.evaluate("() => window.read") == "refused"
            signin.wait_for_function("() => window.opened.closed")
            signin.click("#back")
            signin.wait_for_function(ANSWERED, timeout=60_000)
            assert signin.url == address
    finally:
        browser.close()
        gateway.close()
    # A view with no such name refuses the gateway's name too.
    gateway = Gateway(tmp_path)
    browser = chromium.browser_type.launch(
        args=["--host-resolver-rules=MAP *.example.org 127.0.0.1", "--ignore-certificate-errors"]
    )
    try:
        with serving(path) as view:
            gateway.to = view
            refused = browser.new_page().goto(f"https://view.example.org:{gateway.port}/")
            assert refused is not None and refused.status == 403
    finally:
        browser.close()
        gateway.close()


def test_a_link_on_another_site_opens_the_page_and_its_page_reads_nothing(
    chromium: Browser, tmp_path: Path
) -> None:
    """A sign-in on another site sends its reader back to the view with a link. So a link on
    another site opens the page. A page of that site can still read nothing of the view, and
    cannot show the view inside itself."""
    path = tmp_path / "trip.json"
    path.write_bytes((EXAMPLES / "ending-in-denver" / "works.json").read_bytes())
    with serving(path) as view:
        elsewhere = f"""<!doctype html><title>elsewhere</title>
          <a id="go" href="{view.address}">to the view</a>
          <iframe id="inside" src="{view.address}"></iframe>
          <script>
            window.read = null;
            fetch("{view.address}events").then(
              () => {{ window.read = "read"; }},
              () => {{ window.read = "refused"; }},
            );
          </script>"""
        context = chromium.new_context()
        try:
            page = context.new_page()
            page.route(
                "http://elsewhere.example/**",
                lambda route: route.fulfill(body=elsewhere, content_type="text/html"),
            )
            page.goto("http://elsewhere.example/")
            # Its page cannot read what the view sends, and the view is not shown inside it.
            page.wait_for_function("() => window.read !== null")
            assert page.evaluate("() => window.read") == "refused"
            page.wait_for_timeout(500)
            inside = page.frame_locator("#inside")
            assert inside.locator("#line").count() == 0
            assert inside.locator("#report").count() == 0
            # Its link opens the view's page, with the answer and the report.
            page.click("#go")
            page.wait_for_function(ANSWERED, timeout=60_000)
            assert page.url == view.address
            assert (page.text_content("#line") or "").startswith("FEASIBLE")
            page.locator("#report .row").first.wait_for()
        finally:
            context.close()


def test_a_step_with_nobody_in_it_has_a_column_and_a_row_of_its_own(
    chromium: Browser, tmp_path: Path
) -> None:
    """A luggage service carries the bags to O'Hare while Alex and Sam are at the museum."""
    story = EXAMPLES / "the-bags" / "the-service-takes-them.json"
    in_the_last_third = """(mark) => {
      const day = mark.closest(".day-body").getBoundingClientRect();
      const box = mark.getBoundingClientRect();
      return box.left >= day.left + (day.width * 2) / 3 - 1 && box.right <= day.right + 1;
    }"""
    with opened(chromium, story) as page:
        page.locator("#calendar .mark").first.wait_for()
        page.locator("#report .row").first.wait_for()
        page.locator("#options .item").first.wait_for()
        # The day has a column for each PERSON, and one after them for nobody.
        heads = page.locator("#calendar .day .people span")
        assert heads.all_text_contents() == ["Alex", "Sam", "nobody"]
        # That column is no drawing of a PERSON, and it has no colour of one.
        nobody = page.locator("#calendar .people .nobody")
        assert nobody.get_attribute("data-of") is None
        hues = heads.evaluate_all(
            "(all) => all.map((each) => getComputedStyle(each).borderBottomColor)"
        )
        assert len(set(hues)) == 3
        # The service is in that column, and the visit is not.
        service = page.locator("#calendar .mark", has_text="Luggage service")
        assert service.count() == 1
        assert service.evaluate(in_the_last_third)
        assert not page.locator("#calendar .mark", has_text="Museum visit").first.evaluate(
            in_the_last_third
        )
        stripes = service.locator(".stripe").evaluate_all(
            "(all) => all.map((each) => each.className)"
        )
        assert stripes == ["stripe nobody"]
        # The key under the calendar says what an outlined mark in that column is.
        key = page.locator("#calendar-key .for-nobody")
        assert key.is_visible()
        assert key.text_content() == 'under "nobody": in the plan, with nobody of the TRIP in it'
        # The calendar says nothing more of it in words: the mark says it.
        assert "obody" not in (page.text_content("#calendar-says") or "")
        assert "nobody of the TRIP" in (service.get_attribute("title") or "")
        # Pointing at the service lights up its line of the report and its row among the OPTIONs.
        service.hover()
        found = lit(page, marks=["Luggage service"], options=["Luggage service"])
        assert any(
            row.strip().startswith("2:00 pm to 3:30 pm: Luggage service") for row in found["rows"]
        )
        # The keyboard reaches it like any other mark of the calendar.
        page.locator("#calendar").focus()
        page.keyboard.press("Tab")
        names: list[str] = []
        for _ in range(6):
            names.append(page.evaluate("() => document.activeElement.textContent"))
            page.keyboard.press("ArrowDown")
        assert any("Luggage service" in name for name in names)
    # With breakfast in Denver the next morning, the plan has two days, and so a strip. The
    # strip has a row for each PERSON and one for nobody, and the service is in that row.
    content = json.loads(story.read_text())
    content["options"].append({"id": "breakfast", "name": "Breakfast", "place": "denver"})
    content["facts"] += [
        {
            "id": "breakfast-time",
            "option": "breakfast",
            "starts_at": "2027-05-16T09:00:00-05:00[America/Chicago]",
        },
        {"id": "breakfast-length", "option": "breakfast", "duration": "PT1H"},
        {"id": "breakfast-arrival", "option": "breakfast", "arrive_before_start": "PT0S"},
        {"id": "breakfast-needs-no-ticket", "option": "breakfast", "needs_right": False},
    ]
    content["decisions"].append(
        {"id": "lock-breakfast", "lock": "breakfast", "persons": ["alex", "sam"]}
    )
    # A plan with somebody in every step has no such column, and its key has no such line.
    with opened(chromium, EXAMPLES / "flight-home" / "works.json") as page:
        page.locator("#calendar .mark").first.wait_for()
        assert page.locator("#calendar .people .nobody").count() == 0
        assert page.locator("#calendar-key .for-nobody").is_hidden()
    with opened(chromium, written(tmp_path, content)) as page:
        page.locator("#strip .bar").first.wait_for()
        assert (page.text_content("#line") or "").startswith("FEASIBLE")
        rows = page.locator("#strip .strip-people span")
        assert rows.all_text_contents() == ["Alex", "Sam", "nobody"]
        assert "one for the steps with nobody of the TRIP in them" in (
            page.text_content("#strip-says") or ""
        )
        in_the_last_row = """(bar) => {
          const rows = bar.closest(".strip-rows").getBoundingClientRect();
          const box = bar.getBoundingClientRect();
          return box.top >= rows.top + (rows.height * 2) / 3 - 1 && box.bottom <= rows.bottom + 1;
        }"""
        bar = page.locator("#strip .bar", has_text="Luggage service")
        assert bar.count() == 1
        assert bar.evaluate(in_the_last_row)
        # Pointing at it on the strip lights up the same step in the calendar.
        bar.hover()
        lit(page, marks=["Luggage service"], bars=["Luggage service"])


def test_the_page_lists_what_is_open_above_everything_that_it_draws(
    chromium: Browser, tmp_path: Path
) -> None:
    """A person who watches an agent plan a trip sees first what has to be done or decided."""
    first_part = "() => document.querySelector('#drawings > section:not([hidden])').id"
    rows = """() => [...document.querySelectorAll("#open .entry")].map((row) => ({
      mark: row.className.replace("entry", "").replace("lit", "").trim(),
      says: [...row.children].map((each) => each.textContent),
    }))"""
    # A plan that works: the train to the flight is the COMPILER's choice, and nobody has
    # decided it. The item is its step, so pointing at it lights up the step and its line.
    with opened(chromium, EXAMPLES / "flight-home" / "works.json") as page:
        page.locator("#report .row").first.wait_for()
        page.locator("#calendar .mark").first.wait_for()
        page.locator("#open .entry").first.wait_for()
        assert page.evaluate(first_part) == "open-part"
        assert page.text_content("#open-part h2") == "To do and to decide"
        assert page.text_content("#open-says") == (
            "1 thing is open. Times are on the clocks of America/Chicago."
        )
        assert page.evaluate(rows) == [
            {
                "mark": "not",
                "says": [
                    "Blue Line to O'Hare",
                    "Alex and Sam",
                    "Saturday 15 May 2027, 3:00 pm to 4:00 pm",
                ],
            }
        ]
        link = page.locator("#contents .to").first
        assert link.text_content() == "To do and to decide1"
        assert link.get_attribute("class") == "to"
        page.locator("#open .entry").hover()
        found = lit(page, marks=["Blue Line to O'Hare"], options=["Blue Line to O'Hare"])
        assert any("3:00 pm to 4:00 pm: Blue Line to O'Hare" in row for row in found["rows"])
        # The other way round: pointing at the step in the calendar lights up the item.
        page.locator("#calendar .mark", has_text="Blue Line").hover()
        page.wait_for_function("() => document.querySelectorAll('#open .entry.lit').length === 1")
    # A trip that cannot work: each record that the report names, with a red edge, and tied
    # to its line of the report and to what the record is about.
    with opened(chromium, EXAMPLES / "flight-home" / "cannot-work.json") as page:
        page.locator("#report .row").first.wait_for()
        page.locator("#calendar .mark").first.wait_for()
        page.locator("#open .entry").first.wait_for()
        assert page.text_content("#open-says") == "No plan works."
        # Over the records is the report's own line: which kinds they are, and what taking
        # one away means.
        assert page.text_content("#open .open-kind") == (
            "These FACTs and DECISIONs rule out every plan by themselves. Take any one away and"
            " they no longer do. A FACT that is taken away leaves what it said unknown. Times"
            " are in America/Chicago."
        )
        listed = page.evaluate(rows)
        assert len(listed) == 8 and all(row["mark"] == "clash" for row in listed)
        assert listed[-1]["says"] == ["lock-flight", "Alex and Sam take part in Flight home"]
        assert page.locator("#contents .to").first.get_attribute("class") == "to clash"
        page.locator("#open .entry", has_text="lock-flight").hover()
        found = lit(page, marks=["Flight home"])
        assert ids_of(found["rows"]) == ["lock-flight"]
    # A trip that depends on what the FILE does not say: each case, with a yellow edge.
    with opened(chromium, EXAMPLES / "a-ticket" / "depends-on-the-price.json") as page:
        page.locator("#report .row").first.wait_for()
        page.locator("#open .entry").first.wait_for()
        assert [row["mark"] for row in page.evaluate(rows)] == ["asked", "asked"]
        assert page.locator("#contents .to").first.get_attribute("class") == "to asked"
        page.locator("#open .entry").nth(1).hover()
        page.wait_for_function(
            "() => [...document.querySelectorAll('#report .row.lit')]"
            ".some((row) => row.dataset.record === 'case:1')"
        )
        # What the report says after its cases is under them, a line of the list for each
        # line of the report. The line of a BUDGET is a drawing of that BUDGET.
        also = page.locator("#open .open-also span")
        assert also.nth(0).text_content() == (
            "Who buys which place is from one plan that works in that case. A place with a"
            " price above nothing is paid from a BUDGET that lists the PERSON who takes it and"
            " holds the currency of the price. The BUDGETs of this FILE:"
        )
        assert also.nth(1).text_content() == "the trip money: for Alex and Sam; it holds USD"
        also.nth(1).hover()
        found = lit(page, budgets=["the trip money"], marks=[])
        assert found["rows"] == ["  the trip money: for Alex and Sam; it holds USD"]
        page.wait_for_function("() => document.querySelector('#open .open-under.lit') !== null")
    # A case can hold only under a condition that the report states on another line. The
    # plan and the cap that the report sets under the case are under its item.
    under = (
        "() => [...document.querySelectorAll('#open .open-more span')].map((e) => e.textContent)"
    )
    nothing_lit = "() => document.querySelectorAll('.lit').length === 0"
    with opened(chromium, EXAMPLES / "a-ticket" / "depends-on-the-receipt.json") as page:
        page.locator("#report .row").first.wait_for()
        page.locator("#open .entry").first.wait_for()
        (case,) = page.evaluate(rows)
        assert case["says"] == [
            "The trip works if the FILE states what alex-skydeck-ticket paid and from which BUDGET."
        ]
        plan, cap = page.evaluate(under)
        assert plan.startswith("One plan that works then: Sam buys a place from skydeck-tickets")
        assert cap.startswith("trip-cap, on the trip money: 32.00 still to buy")
        assert cap.endswith("That leaves 18.00 USD for whatever else is charged to it.")
        assert page.text_content("#contents .to") == "To do and to decide1"
        # The line of the plan is a drawing of the OFFER that Sam buys a place of, as in the
        # report. It is no drawing of the case: what the case is about stays dark.
        page.locator("#open .open-more span").first.hover()
        found = lit(page, rights=["skydeck-tickets"], budgets=[], marks=[])
        assert [row.strip().split(":")[0] for row in found["rows"]] == ["One plan that works then"]
        assert page.locator("#open .entry.lit").count() == 0
        # The keyboard goes through the case and the lines under it, and on to what the
        # report says after them.
        page.locator("#open-part").evaluate(
            "(part) => part.querySelector('[tabindex=\"0\"]').focus()"
        )
        stops: list[str] = []
        for _ in range(5):
            # What the keyboard is on: the case, or the thing that a line is a drawing of.
            stops.append(
                page.evaluate(
                    "() => (({ records, of }) => records ?? of)(document.activeElement.dataset)"
                )
            )
            page.keyboard.press("ArrowDown")
        assert stops == [
            "case:0",
            "offer:skydeck-tickets",
            "cap:trip-cap",
            "budget:trip-money",
            "budget:trip-money",
        ]
        lit(page, budgets=["the trip money"])
        # The list holds one thing for the one case, however many lines are under it.
        assert page.locator("#open li").count() == 1
    # A line under a case that is about nothing lights up nothing, as in the report. With a
    # cap on the trip money, the report gives a plan for each case, and in the first one
    # nobody buys a place.
    content = json.loads((EXAMPLES / "a-ticket" / "depends-on-the-price.json").read_text())
    limit = {"amount": "200.00", "currency": "USD"}
    content["decisions"].append({"id": "trip-cap", "budget": "trip-money", "spend_at_most": limit})
    with opened(chromium, written(tmp_path, content)) as page:
        page.locator("#report .row").first.wait_for()
        page.locator("#open .entry").first.wait_for()
        first = page.locator("#open .open-more span").first
        assert first.text_content() == (
            "One plan that works then: nobody buys a place from an OFFER of this FILE."
        )
        # Two cases, and two things in the list: the lines under a case are part of its one.
        # The list says that it is a list, also to a browser that takes one without bullets
        # for none.
        assert page.locator("#open li").count() == 2
        assert page.locator("#open ul[role='list'] > li").count() == 2
        assert page.text_content("#contents .to") == "To do and to decide2"
        page.locator("#open .entry").first.hover()
        page.wait_for_function("() => document.querySelectorAll('.lit').length > 1")
        first.hover()
        page.wait_for_function(nothing_lit)
    # What the report warns of at a step is on the list with that step.
    with opened(chromium, EXAMPLES / "a-ticket" / "not-bought-yet.json") as page:
        page.locator("#report .row").first.wait_for()
        page.locator("#calendar .mark").first.wait_for()
        page.locator("#open .entry").first.wait_for()
        (ticket,) = page.evaluate(rows)
        assert ticket["mark"] == "warned"
        assert ticket["says"][0] == "Skydeck visit"
        # The warning has the mark that the report gives it, and is under the name of its
        # step: the report speaks of a line marked "!" and of the step above it.
        assert ticket["says"][1].startswith("! Sam still has to buy a right to this, from ")
        below = """() => {
          const name = document.querySelector("#open .entry-name").getBoundingClientRect();
          const says = document.querySelector("#open .entry-says").getBoundingClientRect();
          return says.top >= name.bottom - 1;
        }"""
        assert page.evaluate(below)
        # Over the warnings is what the report says of them, in its own words.
        assert page.text_content("#open .open-kind") == (
            'WARNING: not everything is booked yet. A line marked "!" that names an OFFER says'
            " who still has to buy a right. Only a BOOKING secures one."
        )
        # The item is of what its line of the report is about: the step, and the OFFER that
        # Sam still has to buy a place of.
        page.locator("#open .entry").hover()
        found = lit(page, marks=["Skydeck visit"], rights=["skydeck-tickets"])
        assert any(row.startswith("    ! Sam still has to buy") for row in found["rows"])
        # The other way round: pointing at the OFFER lights up the item.
        page.locator("#rights .entry", has_text="skydeck-tickets").hover()
        page.wait_for_function("() => document.querySelectorAll('#open .entry.lit').length === 1")
        # With the keyboard on the item, the same is lit.
        page.locator("#report").hover()
        page.locator("#open .entry").focus()
        lit(page, marks=["Skydeck visit"], rights=["skydeck-tickets"])
    # Before the report comes, nothing says what is open, and the page has no such list.
    path = tmp_path / "trip.json"
    path.write_bytes((EXAMPLES / "flight-home" / "works.json").read_bytes())
    first, answer, report = (json.dumps(event) for event in checked(path.read_bytes()))
    (tmp_path / "python.first").write_text(f"{first}\n{answer}\n")
    (tmp_path / "python.report").write_text(f"{report}\n")
    go = tmp_path / "python.go"
    waits = 'cat "$0.first"\nwhile [ ! -e "$0.go" ]; do sleep 0.05; done\ncat "$0.report"'
    drawn = "() => document.querySelectorAll('#options .item').length > 0"
    with opened(chromium, path, python=stand_in(tmp_path, waits), once=drawn) as page:
        assert page.locator("#open-part").is_hidden()
        assert page.evaluate(first_part) == "calendar-part"
        go.write_text("")
        page.locator("#open .entry").first.wait_for()
        assert page.evaluate(first_part) == "open-part"
