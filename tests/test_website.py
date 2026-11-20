"""The agloe.ai home page, ``pages/index.html``, agrees with the documents and the examples.

The page marks what it takes from elsewhere with the path of its source:

- ``data-from``: a passage from a document must be in that document, word for word, and an
  example must be shown whole.
- ``data-lines-from``: the words are whole lines of that file, one after another.

The page also draws the first story as a day that a reader can change. It draws the day from a
FILE, and it carries each version of the story whole: its FILE, and the report the example
expects, in words and as data. When a reader changes the trip, the page runs the reference
checker in the reader's browser, through ``pages/checker.py``. That program must give the
examples their expected reports where the solver is missing, as it is in a browser.

``pages/trip-file.js`` is the page's own code for reading and changing a FILE. Node runs it here,
through ``website_gestures.mjs``: each change a reader can make must write a FILE that the format
accepts, and the page must be able to read the report on it.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from functools import cache
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest

from agloe import answers
from agloe import report as reports_in
from agloe.file import load
from agloe.reference import Constraint

ROOT = Path(__file__).parent.parent
PAGES = ROOT / "pages"
SITE = "https://agloe.ai/"
REPOSITORY = "https://github.com/ian-c-leonard/agloe"
STORY = "examples/flight-home"

# Elements that have no end tag.
VOID = {"br", "hr", "img", "input", "link", "meta"}
MARKS = {"data-from": "passage", "data-lines-from": "lines"}


class Page(HTMLParser):
    """Reads the page into its marked passages, its links, its ids and its style sheet."""

    def __init__(self) -> None:
        super().__init__()
        self.passages: list[tuple[str, str, str]] = []
        self.links: list[str] = []
        self.ids: set[str] = set()
        self.text: list[str] = []
        self.style: list[str] = []
        self.open: list[tuple[str, str | None, str | None, list[str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        named = dict(attrs)
        self.links += [value for name in ("href", "src") if (value := named.get(name))]
        if (content := named.get("content")) and content.startswith(SITE):
            self.links.append(content)
        if identity := named.get("id"):
            self.ids.add(identity)
        if tag in VOID:
            return
        marked = [(kind, named[name]) for name, kind in MARKS.items() if named.get(name)]
        assert len(marked) <= 1, f"<{tag}> names two sources"
        kind, source = marked[0] if marked else (None, None)
        self.open.append((tag, kind, source, []))

    def handle_endtag(self, tag: str) -> None:
        opened, kind, source, parts = self.open.pop()
        assert opened == tag, f"<{opened}> is closed by </{tag}>"
        if kind is not None and source is not None:
            self.passages.append((kind, source, "".join(parts)))

    def handle_data(self, data: str) -> None:
        inside = self.open[-1][0] if self.open else ""
        if inside == "style":
            self.style.append(data)
            self.links += re.findall(r'url\("([^"]+)"\)', data)
            return
        if inside == "script":
            return
        self.text.append(data)
        for _, kind, _, parts in self.open:
            if kind is not None:
                parts.append(data)


def read_page() -> Page:
    page = Page()
    page.feed((PAGES / "index.html").read_text())
    page.close()
    assert page.open == [], "the page ends with an element still open"
    return page


PAGE = read_page()


def words(text: str) -> str:
    """The text with every run of white space as one space."""
    return " ".join(text.split())


def plain(document: str) -> str:
    """The words of a Markdown document, without the marks that set them."""
    text = re.sub(r"^\s*(?:-|\d+\.|#+)\s+", "", document, flags=re.MULTILINE)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    return words(re.sub(r"[*`]", "", text))


def lines(text: str) -> list[str]:
    """The lines of a text, each without the white space around it."""
    return [line.strip() for line in text.strip("\n").split("\n")]


def test_the_page_takes_passages_from_documents_and_shows_examples() -> None:
    kinds = {(kind, Path(source).suffix) for kind, source, _ in PAGE.passages}
    assert {
        ("passage", ".md"),
        ("passage", ".json"),
        ("passage", ".txt"),
        ("lines", ".txt"),
    } <= kinds


@pytest.mark.parametrize(
    ("kind", "source", "text"), PAGE.passages, ids=lambda value: words(str(value))[:50]
)
def test_the_page_says_what_its_source_says(kind: str, source: str, text: str) -> None:
    there = (ROOT / source).read_text()
    if kind == "lines":
        wanted, all_lines = lines(text), lines(there)
        runs = [all_lines[at : at + len(wanted)] for at in range(len(all_lines))]
        assert wanted in runs
    elif source.endswith(".md"):
        assert words(text) in plain(there)
    else:
        assert text.strip("\n") == there.strip("\n")


def test_each_report_stands_under_the_command_that_gives_it() -> None:
    shown = words("".join(PAGE.text))
    reports = [
        source
        for kind, source, _ in PAGE.passages
        if kind == "passage" and source.endswith(".expected.txt")
    ]
    assert reports
    for report in reports:
        file = report.replace(".expected.txt", ".json")
        assert f"uv run agloe check {file}" in shown


def test_every_example_the_page_names_exists() -> None:
    named = set(re.findall(r"examples/[\w/-]+\.json", "".join(PAGE.text)))
    assert named
    for file in named:
        assert (ROOT / file).is_file(), file


def offered() -> list[str]:
    """The versions of the story that the page offers, in the order it offers them."""
    return re.findall(r'name="version" value="([\w-]+)"', (PAGES / "index.html").read_text())


def test_the_page_carries_each_version_of_the_story_whole() -> None:
    carried = {source for kind, source, _ in PAGE.passages if kind == "passage"}
    assert offered()
    for version in offered():
        for ending in (".json", ".expected.txt", ".expected.json"):
            assert f"{STORY}/{version}{ending}" in carried, f"{version}{ending}"


def checked_in_a_browser(files: list[str]) -> list[dict[str, Any]]:
    """What ``pages/checker.py`` says about each FILE where there is no solver, as in a browser."""
    program = (
        "import json, sys\n"
        "sys.modules['ortools'] = None\n"  # so that importing the solver fails
        f"exec(compile(open({str(PAGES / 'checker.py')!r}).read(), 'checker.py', 'exec'))\n"
        "print(json.dumps([json.loads(check(text)) for text in json.load(sys.stdin)]))\n"
    )
    ran = subprocess.run(
        [sys.executable, "-c", program],
        input=json.dumps(files),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(ran.stdout)


def test_the_page_checks_a_trip_as_the_examples_expect() -> None:
    versions = offered()
    found = checked_in_a_browser([(ROOT / STORY / f"{name}.json").read_text() for name in versions])
    for version, report in zip(versions, found, strict=True):
        words = (ROOT / STORY / f"{version}.expected.txt").read_text()
        data = json.loads((ROOT / STORY / f"{version}.expected.json").read_text())
        assert report["text"] == words, version
        assert report["json"] == data, version


def test_the_page_says_how_a_file_breaks_the_format() -> None:
    (report,) = checked_in_a_browser(['{"persons": 3}'])
    assert "/persons: 3 is not of type 'array'" in report["refused"]


def test_each_thing_a_reader_can_add_gives_a_report() -> None:
    """Each addition is records for a FILE: added to the first version, alone and together."""
    additions: dict[str, dict[str, Any]] = json.loads(
        (PAGES / "trip" / "additions.json").read_text()
    )
    first: dict[str, list[Any]] = json.loads((ROOT / STORY / "works.json").read_text())
    buttons = set(re.findall(r'data-add="([\w-]+)"', (PAGES / "index.html").read_text()))
    assert buttons | {"complete"} == set(additions)

    def with_these(names: list[str]) -> str:
        file = {kind: list(records) for kind, records in first.items()}
        for name in names:
            for kind, records in additions[name].items():
                if kind != "label":
                    file[kind] += records
        return json.dumps(file)

    tried = [[name] for name in additions] + [[name for name in additions if name != "coffee"]]
    reports = checked_in_a_browser([with_these(names) for names in tried])
    for names, report in zip(tried, reports, strict=True):
        assert "refused" not in report, (names, report)
        assert report["answer"] in {"FEASIBLE", "INFEASIBLE", "UNDETERMINED"}, names


def page_code(mode: str, given: object) -> list[dict[str, Any]]:
    """What the page's own code for changing a FILE makes of this, run by Node."""
    node = shutil.which("node")
    if node is None:
        if os.environ.get("CI"):
            pytest.fail("the tests of the home page need Node")
        pytest.skip("needs Node")
    ran = subprocess.run(
        [node, str(Path(__file__).parent / "website_gestures.mjs"), mode],
        input=json.dumps(given),
        capture_output=True,
        text=True,
        check=False,
    )
    assert ran.returncode == 0, ran.stderr
    return json.loads(ran.stdout)


@cache
def changed_trips() -> list[dict[str, Any]]:
    """Each version of the story after each change a reader can make to it: a name and a FILE."""
    stories = {name: json.loads((ROOT / STORY / f"{name}.json").read_text()) for name in offered()}
    additions = json.loads((PAGES / "trip" / "additions.json").read_text())
    return page_code("files", {"stories": stories, "additions": additions})


def test_each_change_a_reader_can_make_writes_a_file_in_the_format() -> None:
    changed = changed_trips()
    assert len(changed) > 100
    for trip in changed:
        load(trip["file"])


@cache
def reported_trips() -> list[dict[str, Any]]:
    """The trips with one change, each with the reference checker's report on it.

    Only these are checked, because the reference checker is slow on a busy day.
    """
    once = [trip for trip in changed_trips() if " with " not in trip["name"]]
    assert len(once) > 40
    for trip in once:
        file = load(trip["file"])
        found = answers.check(file)
        trip["report"] = {
            "text": reports_in.as_text(file, found),
            "json": reports_in.as_json(file, found),
        }
    return once


def test_the_page_can_read_the_report_on_a_changed_trip() -> None:
    """Each further change that the page would write from a report must be in the format too."""
    for further in page_code("draw", reported_trips()):
        load(further["file"])


def test_the_lines_under_the_day_leave_nothing_out() -> None:
    """Under the day the page puts the answer and every line that says what the answer turns on.

    An UNDETERMINED report says what the FILE would have to say: one condition, or several
    cases, and then what else has to be true for that to help. The page shows all of it. A report
    with a WARNING marks each step that may go wrong: the page shows each such step with what
    would go wrong at it.
    """
    trips = reported_trips()
    shown = page_code("said", [{"name": trip["name"], "report": trip["report"]} for trip in trips])
    several = 0
    for trip, under in zip(trips, shown, strict=True):
        name = trip["name"]
        lines = trip["report"]["text"].split("\n")
        said = [line["words"] for line in under["said"]]
        assert said[0] == lines[0], name
        answer = trip["report"]["json"]["answer"]
        if answer == "UNDETERMINED":
            assert said[1:] == [line.strip() for line in lines[1:] if line.strip()], name
            several += "The trip works in any of these cases:" in said
        elif trip["report"]["json"].get("robust") is False:
            for at, line in enumerate(lines):
                if line.strip().startswith("!"):
                    step = next(before for before in reversed(lines[:at]) if "!" not in before[:6])
                    assert said.index(step.strip()) < said.index(line.strip()), name
        else:
            assert len(said) == 1, name
    assert several, "no report offered several cases"


def test_the_day_shows_what_the_report_says() -> None:
    """The day draws each other way that a report asks about, and how late people would be.

    Too late to arrive is counted from the time to be there. Still busy when something starts is
    counted from its start. The page tells the two apart by the name of the rule in the report.
    """
    trips = reported_trips()
    shown = {each["name"]: each for each in page_code("scene", trips)}
    rules = {Constraint.ARRIVAL.value, Constraint.PLACE.value}
    for trip in trips:
        found = trip["report"]["json"]
        day = shown[trip["name"]]
        asked = {
            (need["from"], need["to"])
            for enough in found.get("missing", [])
            for need in enough
            if need["what"] == "other ways" and need.get("from") and need.get("to")
        }
        assert {(way["from"], way["to"]) for way in day["ways"]} == asked, trip["name"]
        late = [worst for worst in found.get("at_worst", []) if worst.get("late")]
        assert all(worst["constraint"] in rules for worst in late), trip["name"]
        assert len(day["late"]) == len(late), trip["name"]
    # The train may take three hours, so it may land at 6:00 pm. People must be there by 4:15 pm,
    # and the flight leaves at 5:00 pm.
    bars = sorted(
        (bar["from"], bar["minutes"]) for bar in shown["works: late blue-line by 400"]["late"]
    )
    assert bars == [(16 * 60 + 15, 105), (17 * 60, 60)]
    # Coffee at O'Hare comes before the visit, so the report asks about ways there and back.
    there_and_back = shown["cannot-work: the ways are not all listed, and coffee is at 1:30 pm"]
    assert len(there_and_back["ways"]) == 2
    # The flight lands at 3:45 pm. Another way back to the visit is drawn from then, to its start.
    back = shown["works: the flight leaves at 1:15 pm, and the visit starts at 4:00 pm"]["ways"]
    assert [(way["leaves"], way["shown"]) for way in back] == [(15 * 60 + 45, 15)]


def test_every_link_leads_somewhere() -> None:
    for link in PAGE.links:
        if link.startswith("#"):
            assert link[1:] in PAGE.ids, link
            continue
        for start in (f"{REPOSITORY}/blob/main/", f"{REPOSITORY}/tree/main/"):
            if link.startswith(start):
                assert (ROOT / link.removeprefix(start)).exists(), link
                break
        else:
            if "://" not in link or link.startswith(SITE):
                assert (PAGES / link.removeprefix(SITE)).exists(), link
