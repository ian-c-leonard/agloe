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

import json
import os
import sys
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Browser, Page, Route, sync_playwright
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
# marks of the strip, the lines of the report, the WANTs with the OPTIONs under them, and
# the OPTIONs of the FILE.
LIT = """() => {
  const first = (each) => each.title.split("\\n")[0];
  const all = (which) => [...document.querySelectorAll(which)];
  return {
    marks: [...new Set(all("#calendar .mark.lit").map(first))],
    untimed: all("#calendar-untimed .lit").map((each) => each.textContent),
    bars: [...new Set(all("#strip .bar.lit").map(first))],
    rows: all("#report .row.lit").map((row) => row.textContent),
    wants: all("#wants .lit").map((each) => each.querySelector("h3, b").textContent),
    options: all("#options .option.lit").map((each) => each.querySelector("h3").textContent),
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
) -> Generator[Page]:
    """The page of the view of one FILE, once it shows the report on it.

    ``without`` names files of the page that the browser cannot load. ``held`` names one that
    the browser gets only when the test lets it: the test finds its request in the list.
    ``faulty`` names one that the browser gets with other code in it, and the list that takes
    the faults of the page, which are then no failure of the test.
    """
    with serving(path) as view:
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
            page.wait_for_function(ANSWERED, timeout=60_000)
            yield page
            assert faulty is not None or problems == []
        finally:
            context.close()


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
        page.locator("#wants .want").wait_for()
        page.locator("#report .row").first.wait_for()
        assert page.text_content("#wants .want-name") == "a view from high up"
        assert page.text_content("#wants .want-holds") == "A must for Alex. A must-not for Jo."
        # Pointing at an OPTION under the WANT lights up its step on the calendar, its line in
        # the plan, and the line of the FACT that it SATISFIES the WANT.
        page.locator("#wants .delivers").first.hover()
        found = lit(page, marks=["Skydeck visit"], wants=["Skydeck visit"])
        assert found["rows"][0] == "  10:00 am to 11:30 am: Skydeck visit, Alex"
        assert ids_of(found["rows"][1:]) == ["skydeck-is-high-up"]
        # Pointing at the step on the calendar lights up the OPTION under the WANT.
        page.locator("#calendar .mark.planned").first.hover()
        lit(page, marks=["Skydeck visit"], wants=["Skydeck visit"])
        # Pointing at the WANT lights up its line in the report, and the other way round.
        page.locator("#wants .want-name").hover()
        found = lit(page, marks=[], wants=["a view from high up"])
        assert ids_of(found["rows"]) == ["view"]
        page.locator("#report .row[data-record='view']").hover()
        lit(page, marks=[], wants=["a view from high up"])


def test_a_want_has_the_red_edge_of_what_the_report_names(chromium: Browser) -> None:
    """Alex must have deep-dish pizza, and a LOCK names the blues show at the dinner's time."""
    with opened(chromium, EXAMPLES / "a-must" / "cannot-work.json") as page:
        want = page.locator("#wants .want.clash")
        want.wait_for()
        assert want.get_attribute("title") == (
            "The report names deep-dish and every-deep-dish-place among what rules out every plan."
        )
        assert (page.text_content("#wants-says") or "").endswith(
            " A red edge marks what the report names among what rules out every plan."
        )
        # The OPTION under it has no red edge: the report does not name its FACT.
        assert page.locator("#wants .delivers").count() == 1
        assert page.locator("#wants .delivers.clash").count() == 0
        assert page.text_content("#wants .delivers-takes") == "No LOCK names it."
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
        rows = page.locator("#options .option")
        rows.first.wait_for()
        assert rows.count() == 4
        cab = page.locator("#options .option.asked")
        assert cab.count() == 1
        assert cab.locator(".option-name").text_content() == "Cab to O'Hare"
        assert cab.locator(".option-said p").all_text_contents() == [
            "Can start at any time.",
            "The FILE does not say how long it takes.",
            "The FILE does not say how early people must be there.",
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
        train = page.locator("#options .option").nth(1)
        assert train.locator(".option-name").text_content() == "Blue Line to O'Hare"
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
        asked = page.locator("#options .option.asked")
        asked.first.wait_for()
        assert asked.locator(".option-name").all_text_contents() == ["Flight home", "Cab to O'Hare"]
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


def test_a_long_name_under_a_want_lies_on_nothing(chromium: Browser, tmp_path: Path) -> None:
    """What the FILE says of an OPTION goes below its name where the two do not fit on a line."""
    content = json.loads((EXAMPLES / "a-must-not" / "works.json").read_text())
    # A name with a long word in it, which cannot break at a space.
    content["options"][0]["name"] = "Neuschwanstein Castle"
    content["options"][1]["name"] = "Lunch at the Hohenschwangau village restaurant"
    # Where the words of each are on the page, whatever box holds them.
    apart = """() => [...document.querySelectorAll("#wants .delivers")].map((item) => {
      const words = (which) => {
        const range = document.createRange();
        range.selectNodeContents(item.querySelector(which));
        return range.getBoundingClientRect();
      };
      const [name, says] = [words(".delivers-name"), words(".delivers-says")];
      const box = item.getBoundingClientRect();
      const across = name.right <= says.left + 0.5 || says.right <= name.left + 0.5;
      const down = name.bottom <= says.top + 0.5 || says.bottom <= name.top + 0.5;
      const inside = name.right <= box.right + 0.5 && says.right <= box.right + 0.5;
      return (across || down) && inside;
    })"""
    with opened(chromium, written(tmp_path, content)) as page:
        page.locator("#wants .delivers").first.wait_for()
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
    inside = """() => [...document.querySelectorAll("#wants .want")].map((card) => {
      const range = document.createRange();
      range.selectNodeContents(card.querySelector(".want-name"));
      return range.getBoundingClientRect().right <= card.getBoundingClientRect().right + 0.5;
    })"""
    with opened(chromium, written(tmp_path, content)) as page:
        page.locator("#wants .want").first.wait_for()
        assert page.locator("#wants .want").count() == 2
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
        page.locator("#wants .want").first.wait_for()
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
        assert page.locator("#options .option").count() == 2
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
