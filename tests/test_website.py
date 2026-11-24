"""The pages of agloe.ai, under ``pages/``, agree with the documents and the examples.

A page marks what it takes from elsewhere with the path of its source:

- ``data-from``: a passage from a document must be in that document, word for word, and an
  example must be shown whole.
- ``data-lines-from``: the words are whole lines of that file, one after another.

The pages share one style sheet, ``pages/site.css``. Every link of a page and of the style sheet
must lead somewhere.

The home page also draws the first story as a day that a reader can change. It draws the day from a
FILE, and it carries each version of the story whole: its FILE, and the report the example
expects, in words and as data. When a reader changes the trip, the page runs the reference
checker in the reader's browser, through ``pages/checker.py``. That program must give the
examples their expected reports where the solver is missing, as it is in a browser.

``pages/trip-file.js`` is the page's own code for reading and changing a FILE. Node runs it here,
through ``website_gestures.mjs``: each change a reader can make must write a FILE that the format
accepts, and the page must be able to read the report on it.

The page on how a rule is built has two figures. One shows eight small plans, each marked with
the CONSTRAINTs it breaks: the reference checker must mark them the same. The other shows
variables of the COMPILER and statements about them: Node runs its code through
``website_statements.mjs``, and what it shows must agree with the expected report of each example.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import replace
from functools import cache
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest

from agloe import answers, reference
from agloe import report as reports_in
from agloe.file import load, read
from agloe.reference import Constraint, worst_case

ROOT = Path(__file__).parent.parent
PAGES = ROOT / "pages"
SITE = "https://agloe.ai/"
REPOSITORY = "https://github.com/ian-c-leonard/agloe"
STORY = "examples/flight-home"

# Elements that have no end tag.
VOID = {"br", "hr", "img", "input", "link", "meta"}
MARKS = {"data-from": "passage", "data-lines-from": "lines"}


class Page(HTMLParser):
    """Reads a page into its marked passages, its links, its ids and its style sheets."""

    def __init__(self) -> None:
        super().__init__()
        self.passages: list[tuple[str, str, str]] = []
        self.links: list[str] = []
        self.ids: set[str] = set()
        self.text: list[str] = []
        self.sheets: list[str] = []
        self.open: list[tuple[str, str | None, str | None, list[str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        named = dict(attrs)
        self.links += [value for name in ("href", "src") if (value := named.get(name))]
        if tag == "link" and named.get("rel") == "stylesheet" and (sheet := named.get("href")):
            self.sheets.append(sheet)
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
            self.links += re.findall(r'url\("([^"]+)"\)', data)
            return
        if inside == "script":
            return
        self.text.append(data)
        for _, kind, _, parts in self.open:
            if kind is not None:
                parts.append(data)


def read_page(path: Path) -> Page:
    page = Page()
    page.feed(path.read_text())
    page.close()
    assert page.open == [], f"{path.name} ends with an element still open"
    return page


# Every page of the site, by its path under pages/. What the site needs from elsewhere is not one.
SITE_PAGES = {
    path.relative_to(PAGES).as_posix(): read_page(path)
    for path in sorted(PAGES.rglob("*.html"))
    if "vendor" not in path.parts
}
# The home page.
PAGE = SITE_PAGES["index.html"]
PASSAGES = [
    (name, kind, source, text)
    for name, page in SITE_PAGES.items()
    for kind, source, text in page.passages
]


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
    ("name", "kind", "source", "text"), PASSAGES, ids=lambda value: words(str(value))[:50]
)
def test_a_page_says_what_its_source_says(name: str, kind: str, source: str, text: str) -> None:
    assert (ROOT / source).is_file(), f"{name} names {source}"
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
    reports = [
        (name, source)
        for name, kind, source, _ in PASSAGES
        if kind == "passage" and source.endswith(".expected.txt")
    ]
    assert reports
    for name, report in reports:
        file = report.replace(".expected.txt", ".json")
        assert f"uv run agloe check {file}" in words("".join(SITE_PAGES[name].text)), name


def test_every_example_a_page_names_exists() -> None:
    for name, page in SITE_PAGES.items():
        named = set(re.findall(r"examples/[\w/-]+\.json", "".join(page.text)))
        for file in named:
            assert (ROOT / file).is_file(), f"{name} names {file}"
    assert re.findall(r"examples/[\w/-]+\.json", "".join(PAGE.text))


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


def page_code(
    mode: str, given: object, script: str = "website_gestures.mjs"
) -> list[dict[str, Any]]:
    """What a page's own code makes of this. Node runs it, through a script beside this file."""
    node = shutil.which("node")
    if node is None:
        if os.environ.get("CI"):
            pytest.fail("the tests of the home page need Node")
        pytest.skip("needs Node")
    ran = subprocess.run(
        [node, str(Path(__file__).parent / script), mode],
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
    # Lunch ends at 1:30 pm as coffee starts at O'Hare, and coffee ends at 2:00 pm as the visit
    # starts. Each other way is drawn in the gap that it has to fill.
    tight = shown["works: lunch, and coffee at 1:30 pm"]["ways"]
    assert {(way["from"], way["to"]): way["leaves"] for way in tight} == {
        ("art-institute", "ohare"): 13 * 60 + 30,
        ("ohare", "art-institute"): 14 * 60,
    }


RULE_PAGE = (PAGES / "how-a-rule-is-built" / "index.html").read_text()


def test_the_small_plans_are_marked_as_the_reference_checker_marks_them() -> None:
    """The figure of eight plans says, for each, which CONSTRAINTs it breaks.

    Each plan has some of the three PERSONs in both drives of the example, at the times of the
    plan that the report shows. The reference checker says what each one breaks.
    """
    file = read(ROOT / "examples" / "a-driver" / "the-driver-comes-along.json")
    shown = answers.check(file).itinerary
    words = {Constraint.LOCK: "lock", Constraint.REQUIRED: "required"}
    cards = re.findall(
        r'<li class="plan( works)?" data-in="([^"]*)" data-breaks="([^"]*)">', RULE_PAGE
    )
    people = [person.id for person in file.persons]
    assert len({who for _, who, _ in cards}) == len(cards) == 2 ** len(people)
    for works, who, breaks in cards:
        persons = tuple(person for person in people if person in who.split())
        assert len(persons) == len(who.split()), who
        plan = tuple(replace(step, persons=persons) for step in shown) if persons else ()
        found = {each.constraint for each in reference.broken(file, worst_case(file), plan)}
        assert {words[constraint] for constraint in found} == set(breaks.split()), who
        assert bool(works) == (not found), who
    # The plan that the report shows is one of those that work.
    in_the_report = {" ".join(step.persons) for step in shown}
    assert in_the_report <= {who for works, who, _ in cards if works}


def test_the_page_gives_the_constraint_its_number_on_the_rules_page() -> None:
    rules = (ROOT / "spec" / "rules.md").read_text()
    number = re.search(r"^(\d+)\. \*\*Each requirement of an OPTION is met\.\*\*", rules, re.M)
    assert number is not None
    named = set(re.findall(r"(?:CONSTRAINT|[Rr]ule) (\d+)", RULE_PAGE))
    assert named == {number.group(1)}


def boards() -> list[dict[str, Any]]:
    """Each board of the figure of variables and statements, as the page states it."""
    found: list[dict[str, Any]] = []
    for part in RULE_PAGE.split('<div class="board" ')[1:]:
        file, solver = re.match(r'data-file="([^"]+)" data-solver="([^"]*)"', part).groups()  # type: ignore[union-attr]
        found.append(
            {
                "file": file,
                "solver": set(solver.split()),
                "statements": re.findall(r'<li(?: class="false")? data-says="([^"]+)">', part),
                "false": [
                    bool(marked) for marked in re.findall(r'<li( class="false")? data-says=', part)
                ],
                "lamps": re.findall(r'<span class="lamp">(\w+)</span>', part),
                "variables": re.findall(r'data-switch="(\w+)"', part),
                "yes": re.findall(r'aria-checked="true" data-switch="(\w+)"', part),
            }
        )
    return found


def test_the_variables_and_statements_agree_with_the_reports_of_the_examples() -> None:
    """A setting that makes every statement of a board true is a plan.

    Where the example is FEASIBLE, the setting that the board calls the solver's is such a
    setting, and it has in the drive the PERSONs that the expected report has there. Where the
    example is INFEASIBLE, there is no such setting. Before a reader sets anything, each
    statement is marked true or false as it is with the variables as the board shows them.
    """
    shown = boards()
    assert {board["file"] for board in shown} == set(
        re.findall(r'name="file" value="([^"]+)"', RULE_PAGE)
    )
    worked = page_code("", shown_as_given(shown), "website_statements.mjs")
    answers_seen: set[str] = set()
    for board, found in zip(shown, worked, strict=True):
        expected = json.loads((ROOT / "examples" / f"{board['file']}.expected.json").read_text())
        settings = [set(setting) for setting in found["settings"]]
        answers_seen.add(expected["answer"])
        if expected["answer"] == "FEASIBLE":
            drive = next(step for step in expected["itinerary"] if step["option"] == "drive-out")
            assert board["solver"] == {"used", *drive["persons"]}, board["file"]
            assert board["solver"] in settings, board["file"]
            assert set(board["yes"]) == board["solver"], board["file"]
        else:
            assert expected["answer"] == "INFEASIBLE", board["file"]
            assert settings == [] and not board["solver"], board["file"]
        assert found["holds"] == [not false for false in board["false"]], board["file"]
        assert board["lamps"] == ["true" if true else "false" for true in found["holds"]]
    assert answers_seen == {"FEASIBLE", "INFEASIBLE"}


def shown_as_given(shown: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What the Node script needs of each board."""
    return [
        {"statements": board["statements"], "variables": board["variables"], "yes": board["yes"]}
        for board in shown
    ]


def test_the_pages_have_the_same_header_and_footer() -> None:
    """The header and the footer are written out in each page, and they must stay the same."""

    def part(name: str, start: str, end: str) -> str:
        page = (PAGES / name).read_text()
        up = "../" * name.count("/")
        found = page[page.rindex(start) : page.rindex(end) + len(end)]
        return found.replace(f'href="{up}"', 'href="./"').replace(f'src="{up}', 'src="')

    for start, end in (('<header class="top">', "</header>"), ("<footer>", "</footer>")):
        assert len({part(name, start, end) for name in SITE_PAGES}) == 1, start


def links_of(name: str) -> list[tuple[Path, str]]:
    """Each link of a page and of its style sheets, with the folder it is read from."""
    folder = (PAGES / name).parent
    found = [(folder, link) for link in SITE_PAGES[name].links]
    for sheet in SITE_PAGES[name].sheets:
        styles = folder / sheet
        found += [
            (styles.parent, link) for link in re.findall(r'url\("([^"]+)"\)', styles.read_text())
        ]
    return found


@pytest.mark.parametrize("name", SITE_PAGES)
def test_every_link_leads_somewhere(name: str) -> None:
    page = SITE_PAGES[name]
    for folder, link in links_of(name):
        if link.startswith("#"):
            assert link[1:] in page.ids, link
            continue
        if link.startswith("data:"):
            continue
        for start in (f"{REPOSITORY}/blob/main/", f"{REPOSITORY}/tree/main/"):
            if link.startswith(start):
                assert (ROOT / link.removeprefix(start)).exists(), link
                break
        else:
            if "://" in link and not link.startswith(SITE):
                continue
            # A link inside the site: to a file, or to a folder that holds a page.
            path, _, mark = link.partition("#")
            target = PAGES / path.removeprefix(SITE) if path.startswith(SITE) else folder / path
            target = target.resolve()
            assert PAGES.resolve() in (target, *target.parents), f"{link} leaves the site"
            if target.is_dir():
                target = target / "index.html"
            assert target.is_file(), link
            if mark:
                there = SITE_PAGES[target.relative_to(PAGES.resolve()).as_posix()]
                assert mark in there.ids, link


def test_the_pages_share_one_style_sheet() -> None:
    for name, page in SITE_PAGES.items():
        sheets = {((PAGES / name).parent / sheet).resolve() for sheet in page.sheets}
        assert sheets == {(PAGES / "site.css").resolve()}, name
