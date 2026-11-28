"""The pages of agloe.ai, under ``pages/``, agree with the documents and the examples.

A page marks what it takes from elsewhere with the path of its source:

- ``data-from``: a passage from a document must be in that document, word for word, and an
  example must be shown whole.
- ``data-lines-from``: the words are whole lines of that file, one after another.

The pages share one style sheet, ``pages/site.css``. Every link of a page and of the style sheet
must lead somewhere.

One page is not in the repository: ``tools/build_site_examples.py`` writes the page of examples
from the examples section of ``spec/rules.md`` when the site is published. The tests run that
script and read what it writes as one more page of the site. It must show every example FILE
with its report.

The home page also draws the first story as a day that a reader can change. It draws the day from a
FILE, and it carries each version of the story whole: its FILE, and the report the example
expects, in words and as data. When a reader changes the trip, the page runs the reference
checker in the reader's browser, through ``pages/checker.py``. That program must give the
examples their expected reports where the solver is missing, as it is in a browser.

``pages/trip-file.js`` is the page's own code for reading and changing a FILE. Node runs it here,
through ``website_gestures.mjs``: each change a reader can make must write a FILE that the format
accepts, and the page must be able to read the report on it.

The page on how an answer is decided shows four FILEs in the worst case and in the best case.
Both checkers must find a plan where the page says one works, and none where it says none does.

The page on how a rule is built has two figures. One shows the eight choices of who is in a
drive, with those the reference checker tries and what each breaks: the reference checker must
say the same. The other shows variables of the COMPILER and statements about them: Node runs its
code through ``website_statements.mjs``, and what it shows must agree with the expected report of
each example.
"""

import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import replace
from functools import cache
from html.parser import HTMLParser
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any, cast

import pytest

from agloe import answers, compiler, reference
from agloe import report as reports_in
from agloe.file import load, read
from agloe.reference import Constraint, best_case, worst_case

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


def read_page(name: str, written: str) -> Page:
    page = Page()
    page.feed(written)
    page.close()
    assert page.open == [], f"{name} ends with an element still open"
    return page


EXAMPLES_TOOL = ROOT / "tools" / "build_site_examples.py"


def built_examples() -> str:
    """The page of examples as the script writes it now."""
    with tempfile.TemporaryDirectory() as folder:
        out = Path(folder) / "index.html"
        subprocess.run(
            [sys.executable, str(EXAMPLES_TOOL), "--out", str(out)], check=True, capture_output=True
        )
        return out.read_text()


# The words of every page of the site, by its path under pages/. What the site needs from
# elsewhere is no page. The page of examples is written when the site is published, so a copy
# that may lie in pages/ is left out, and the page is written afresh here.
SITE_TEXT = {
    path.relative_to(PAGES).as_posix(): path.read_text()
    for path in sorted(PAGES.rglob("*.html"))
    if not {"vendor", "examples"} & set(path.parts)
} | {"examples/index.html": built_examples()}
SITE_PAGES = {name: read_page(name, written) for name, written in SITE_TEXT.items()}
# The page with the trip that a reader can change.
TRIP = "check-a-trip/index.html"
PAGE = SITE_PAGES[TRIP]
# The home page.
HOME = SITE_TEXT["index.html"]
# The FILE that the figures of the home page are drawn from.
THREE = "pages/files/three-travelers.json"
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
    return re.findall(r'name="version" value="([\w-]+)"', (PAGES / TRIP).read_text())


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
    buttons = set(re.findall(r'data-add="([\w-]+)"', (PAGES / TRIP).read_text()))
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


def test_the_choices_are_marked_as_the_reference_checker_marks_them() -> None:
    """The figure of eight choices says which the reference checker tries, and what each breaks.

    A choice has some of the three PERSONs in both drives of the example, at the times of the
    plan that the report shows. The reference checker tries only the choices that honor the
    LOCKs, so the figure marks the others as not tried. For each one that is tried, the
    reference checker says whether it breaks the CONSTRAINT that the page is about.
    """
    file = read(ROOT / "examples" / "a-driver" / "the-driver-comes-along.json")
    shown = answers.check(file).itinerary
    locked = {person for lock in file.locks for person in lock.persons}
    cards = re.findall(
        r'<li class="plan( skipped| works)?" data-in="([^"]*)" data-breaks="([^"]*)">', RULE_PAGE
    )
    people = [person.id for person in file.persons]
    assert len({who for _, who, _ in cards}) == len(cards) == 2 ** len(people)
    for kind, who, breaks in cards:
        persons = tuple(person for person in people if person in who.split())
        assert len(persons) == len(who.split()), who
        plan = tuple(replace(step, persons=persons) for step in shown) if persons else ()
        found = {each.constraint for each in reference.broken(file, worst_case(file), plan)}
        words = {Constraint.LOCK: "lock", Constraint.REQUIRED: "required"}
        assert {words[constraint] for constraint in found} == set(breaks.split()), who
        tried = locked <= set(persons)
        assert tried == (Constraint.LOCK not in found), who
        assert kind.strip() == ("skipped" if not tried else "" if found else "works"), who
    # The plan that the report shows is the first of the choices that work.
    working = [who for kind, who, _ in cards if kind.strip() == "works"]
    assert [" ".join(step.persons) for step in shown] == [working[0]] * len(shown)


def test_the_two_cases_of_each_file_are_what_both_checkers_find() -> None:
    """The page on how an answer is decided says, for four FILEs, whether a plan works in each case.

    Both checkers are asked about the worst case and the best case of each FILE. The answer that
    the two cases give, by the small table on the page, is the answer of the expected report.
    """
    page = SITE_TEXT["how-an-answer-is-decided/index.html"]
    boards = re.findall(
        r'<div class="worlds" data-file="([^"]+)" data-worst="(\w+)" data-best="(\w+)">', page
    )
    assert {name for name, _, _ in boards} == set(re.findall(r'name="case" value="([^"]+)"', page))
    rows = re.findall(
        r"<tr><td>([a-z ]+)</td><td>([a-z ]+)</td><td class=\"\w+\">(\w+)</td></tr>", page
    )
    said = {"a plan works": "plan", "no plan works": "none"}
    table = {(said[worst], said[best]): answer for worst, best, answer in rows}
    assert len(table) == 3
    seen: set[str] = set()
    for name, worst, best in boards:
        file = read(ROOT / "examples" / f"{name}.json")
        for case, plan in ((worst_case(file), worst), (best_case(file), best)):
            works = bool(reference.itineraries(file, case))
            assert compiler.works(file, case) == works, name
            assert plan == ("plan" if works else "none"), name
        expected = json.loads((ROOT / "examples" / f"{name}.expected.json").read_text())["answer"]
        assert table[worst, best] == expected, name
        seen.add(expected)
    assert seen == {"FEASIBLE", "INFEASIBLE", "UNDETERMINED"}


def says_at_least(later: Any, earlier: Any) -> bool:
    """Whether a record says everything an earlier form of it said, and maybe more."""
    if isinstance(earlier, dict) and isinstance(later, dict):
        before, after = cast("dict[str, Any]", earlier), cast("dict[str, Any]", later)
        return all(key in after and says_at_least(after[key], said) for key, said in before.items())
    return later == earlier


def test_the_file_that_grows_is_one_file_with_records_added() -> None:
    """The home page shows one FILE at three moments, with the COMPILER's answer to each.

    The first two are FILEs of the examples. The second holds every record of the first, and
    each still says what it said. In the third a PERSON has bought a place of an OFFER: the
    FILE has their BOOKING, and the OFFER has one place fewer, as the rules page asks of
    whoever writes a FILE. Both checkers are asked, and the first line of each report on it
    is the line the page gives.
    """
    figure = re.search(r'<figure class="grows" id="file-grows">(.*?)</figure>', HOME, re.S)
    assert figure is not None
    steps = re.findall(r"<li ([^>]+)>(.*?)</li>", figure.group(1), re.S)
    named = [dict(re.findall(r'data-([a-z-]+)="([^"]+)"', given)) for given, _ in steps]
    assert [sorted(each) for each in named] == [["file"], ["file"], ["buyer", "buys-from", "offer"]]
    first, second, last = named
    assert last["buys-from"] == second["file"]
    before = json.loads((ROOT / "examples" / f"{first['file']}.json").read_text())
    after = json.loads((ROOT / "examples" / f"{second['file']}.json").read_text())
    for kind, records in before.items():
        later = {record["id"]: record for record in after[kind]}
        for record in records:
            assert says_at_least(later[record["id"]], record), record["id"]
    offer = next(fact["offer"] for fact in after["facts"] if fact["id"] == last["offer"])
    budget = next(each["id"] for each in after["budgets"] if last["buyer"] in each["persons"])
    price = offer["prices"][0]
    after["facts"].append(
        {
            "id": f"a-right-for-{last['buyer']}",
            "booking": {
                "option": offer["option"],
                "covers": [last["buyer"]],
                "paid": {**price, "budget": budget, "by": last["buyer"]},
            },
        }
    )
    offer["places"] -= 1
    assert offer["places"] == 1 and "lowers the OFFER to one place" in steps[2][1]
    said = re.search(r'<p class="answer-line">(.*?)</p>', steps[2][1], re.S)
    assert said is not None
    file = load(after)
    for found in (answers.check(file), compiler.check(file)):
        assert reports_in.as_text(file, found).splitlines()[0] == html.unescape(said.group(1))


def three_travelers() -> dict[str, Any]:
    """The FILE for three travelers, as JSON."""
    return json.loads((ROOT / THREE).read_text())


def named(records: list[dict[str, Any]]) -> dict[str, str]:
    """The name of each record, by its id."""
    return {record["id"]: record["name"] for record in records}


def test_the_table_of_wants_is_what_the_file_holds() -> None:
    """The home page shows who wants what in the FILE for three travelers, and what delivers it.

    Each WANT has a column. Each PERSON has a row that says must or must not under the WANTs
    they hold. Each OPTION has a row with its DEGREE OF SATISFACTION under each WANT. The FILE
    has a FACT for every pair of an OPTION and a WANT, so no cell is left to a guess.
    """
    figure = re.search(
        r'<figure class="holds" id="who-wants-what" data-file="([^"]+)">(.*?)</figure>', HOME, re.S
    )
    assert figure is not None and figure.group(1) == THREE
    document, body = three_travelers(), figure.group(2)
    columns = re.findall(r'<th scope="col" data-want="([\w-]+)">(.*?)</th>', body)
    assert [(each["id"], each["name"]) for each in document["wants"]] == columns
    said = {10: '<td class="must">must</td>', -10: '<td class="must-not">must not</td>'}
    persons = re.findall(r'<tr data-person="([\w-]+)"><th scope="row">(.*?)</th>(.*?)</tr>', body)
    assert [(person, name) for person, name, _ in persons] == list(
        named(document["persons"]).items()
    )
    for person, _, cells in persons:
        held = [
            {holder["person"]: holder["degree"] for holder in want["holders"]}.get(person)
            for want in document["wants"]
        ]
        assert cells == "".join(said[degree] if degree else "<td></td>" for degree in held), person
    options = re.findall(r'<tr data-option="([\w-]+)"><th scope="row">(.*?)</th>(.*?)</tr>', body)
    assert [(option, name) for option, name, _ in options] == list(
        named(document["options"]).items()
    )
    delivered = {
        (fact["option"], fact["satisfies"]["want"]): fact["satisfies"]["degree"]
        for fact in document["facts"]
        if "satisfies" in fact
    }
    assert len(delivered) == len(document["options"]) * len(document["wants"])
    assert not [fact for fact in document["facts"] if "complete" in fact]
    for option, _, cells in options:
        row = [delivered[option, want["id"]] for want in document["wants"]]
        assert cells == "".join(
            f"<td>{degree}</td>" if degree else '<td class="none">0</td>' for degree in row
        ), option
    assert document["decisions"] == [] and "five OPTIONs and no DECISION" in HOME


def test_the_plan_for_three_travelers_is_what_both_checkers_show() -> None:
    """The home page shows the first lines of the report on the FILE for three travelers."""
    shown = re.search(
        r'<div class="terminal" id="plan-for-three">.*?'
        r"uv run agloe check ([\w/.-]+)</p>\s*<pre>(.*?)</pre>",
        HOME,
        re.S,
    )
    assert shown is not None and shown.group(1) == THREE
    wanted = html.unescape(shown.group(2)).rstrip("\n").split("\n")
    file = read(ROOT / THREE)
    for found in (answers.check(file), compiler.check(file)):
        report = reports_in.as_text(file, found).split("\n")
        assert report[: len(wanted)] == wanted
        # The lines shown are the whole plan: the next line of the report is empty.
        assert report[len(wanted)] == ""


def test_the_choices_are_counted_as_the_page_says() -> None:
    """Each PERSON is in an OPTION or out of it: two choices for each pair of the two."""
    figure = re.search(r'<figure class="counts" id="choices">(.*?)</figure>', HOME, re.S)
    assert figure is not None
    rows = re.findall(
        r'<tr data-travelers="(\d+)" data-options="(\d+)"(?: class="this")?>'
        r"<td>(\d+)</td><td>(\d+)</td><td>([\d,]+)</td></tr>",
        figure.group(1),
    )
    assert len(rows) == 4
    for travelers, options, first, second, choices in rows:
        assert (travelers, options) == (first, second)
        assert f"{2 ** (int(travelers) * int(options)):,}" == choices
    marked = re.search(
        r'data-travelers="(\d+)" data-options="(\d+)" class="this">'
        r"<td>\d+</td><td>\d+</td><td>([\d,]+)",
        figure.group(1),
    )
    document = three_travelers()
    assert marked is not None and figure.group(1).count('class="this"') == 1
    assert (int(marked.group(1)), int(marked.group(2))) == (
        len(document["persons"]),
        len(document["options"]),
    )
    pairs = int(marked.group(1)) * int(marked.group(2))
    assert (
        f"That makes {pairs} yes-or-no choices, and {marked.group(3)} ways to answer them." in HOME
    )


def score(document: dict[str, Any], plan: dict[str, list[str]]) -> dict[str, int]:
    """Each PERSON's SCORE for a plan, as the vocabulary defines SCORE, and the total.

    A plan says who takes part in each OPTION. For every PERSON and every WANT they hold, the
    DEGREE OF WANT times the DEGREE OF SATISFACTION that the plan delivers to them.
    """
    delivered = {
        (fact["option"], fact["satisfies"]["want"]): fact["satisfies"]["degree"]
        for fact in document["facts"]
        if "satisfies" in fact
    }
    scores = dict.fromkeys((person["id"] for person in document["persons"]), 0)
    for want in document["wants"]:
        for holder in want["holders"]:
            got = [
                delivered.get((option, want["id"]), 0)
                for option, persons in plan.items()
                if holder["person"] in persons
            ]
            # In each plan of the page, a holder is in at most one OPTION that delivers the WANT.
            assert sum(1 for degree in got if degree) <= 1
            scores[holder["person"]] += holder["degree"] * max(got, default=0)
    return scores | {"total": sum(scores.values())}


def plan_of(file: Any, found: Any) -> dict[str, list[str]]:
    """Who takes part in each OPTION of the plan that a report shows."""
    steps = cast("list[dict[str, Any]]", reports_in.as_json(file, found)["itinerary"])
    return {step["option"]: step["persons"] for step in steps if "option" in step}


def test_the_two_plans_work_and_score_as_the_page_says() -> None:
    """The home page gives each PERSON's SCORE for two plans of the FILE for three travelers.

    The first is the plan that the COMPILER shows. The second is named on the page. With a
    LOCK for each of its OPTIONs, both checkers say that the TRIP works and show that plan.
    The SCOREs are worked out here from the FILE, by the vocabulary's definition.
    """
    figure = re.search(
        r'<figure class="scores" id="two-plans" data-file="([^"]+)">(.*?)</figure>', HOME, re.S
    )
    assert figure is not None and figure.group(1) == THREE
    document, body = three_travelers(), figure.group(2)
    file = read(ROOT / THREE)
    first = plan_of(file, compiler.check(file))
    assert first == plan_of(file, answers.check(file))
    other = re.search(r"data-plan='([^']+)'", body)
    assert other is not None
    second: dict[str, list[str]] = json.loads(other.group(1))
    locked = json.loads(json.dumps(document))
    locked["decisions"] = [
        {"id": f"lock-{option}", "lock": option, "persons": persons}
        for option, persons in second.items()
    ]
    with_locks = load(locked)
    for found in (answers.check(with_locks), compiler.check(with_locks)):
        assert reports_in.as_text(with_locks, found).startswith("FEASIBLE: this trip works.")
        assert plan_of(with_locks, found) == second
    rows = {
        name: (first_plan, second_plan)
        for name, first_plan, second_plan in re.findall(
            r'<th scope="row">(\w+)</th><td>(\d+)</td><td>(\d+)</td>', body
        )
    }
    names = named(document["persons"]) | {"total": "Total"}
    for plan, column in ((first, 0), (second, 1)):
        for person, points in score(document, plan).items():
            assert int(rows[names[person]][column]) == points, (person, column)
    # What the page says of Jo: no view in either plan, and blues at the tavern or at the club.
    delivered = {
        (fact["option"], fact["satisfies"]["want"]): fact["satisfies"]["degree"]
        for fact in document["facts"]
        if "satisfies" in fact
    }
    for plan, place, option in ((first, "tavern", "dinner-tavern"), (second, "club", "blues-show")):
        taken = [each for each, persons in plan.items() if "jo" in persons]
        assert taken == [option]
        assert delivered[option, "view"] == 0
        assert f"at the {place}, {delivered[option, 'blues']} out of 10" in HOME
    assert "Jo keeps away from heights in both." in HOME


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
    """The header and the footer are written out in each page, and they must stay the same.

    They name their targets from the root of the site, so the text is the same on every page.
    """

    def part(name: str, start: str, end: str) -> str:
        page = SITE_TEXT[name]
        return page[page.rindex(start) : page.rindex(end) + len(end)]

    for start, end in (('<header class="top">', "</header>"), ("<footer>", "</footer>")):
        assert len({part(name, start, end) for name in SITE_PAGES}) == 1, start


def test_the_sitemap_lists_every_page_under_its_own_address() -> None:
    """The page for a wrong address is no page of the site, and it asks not to be listed."""
    listed = re.findall(r"<loc>([^<]+)</loc>", (PAGES / "sitemap.xml").read_text())
    pages = {name: SITE + name.removesuffix("index.html") for name in SITE_PAGES}
    assert '<meta name="robots" content="noindex">' in SITE_TEXT["404.html"]
    del pages["404.html"]
    assert sorted(listed) == sorted(pages.values())
    assert f"Sitemap: {SITE}sitemap.xml" in (PAGES / "robots.txt").read_text()
    for name, address in pages.items():
        assert f'<link rel="canonical" href="{address}">' in SITE_TEXT[name], name


def test_the_page_of_examples_shows_every_example_as_the_rules_page_tells_it() -> None:
    """Each FILE has one row: its name, what it says and the answer, in the words of the rules page.

    Under the row are the command, the whole expected report, and links to the FILE and to the
    report as JSON. The row has the class of the answer in the expected result, and the numbers
    beside the answers to pick out are the numbers of FILEs with each answer.
    """
    page = SITE_TEXT["examples/index.html"]
    rules = (ROOT / "spec" / "rules.md").read_text().split("\n## Examples\n")[1]
    told = {
        file: (name, says, answer)
        for name, file, says, answer in re.findall(
            r"^\| \[([^\]]+)\]\(\.\./(examples/[\w/-]+\.json)\) \| (.+?) \| (.+?) \|$", rules, re.M
        )
    }
    files = sorted(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "examples").rglob("*.json")
        if not path.name.endswith(".expected.json")
    )
    assert files and sorted(told) == files
    assert page.count('<li class="case ') == len(files)
    kinds = {"FEASIBLE": "feasible", "INFEASIBLE": "infeasible", "UNDETERMINED": "undetermined"}
    shown: dict[str, int] = dict.fromkeys(kinds, 0)

    def read(part: str) -> str:
        """The words of a piece of the page, without its marks."""
        return words(html.unescape(re.sub(r"<[^>]+>", "", part)))

    for name in files:
        stem = name.removesuffix(".json")
        report = (ROOT / f"{stem}.expected.txt").read_text()
        answer = json.loads((ROOT / f"{stem}.expected.json").read_text())["answer"]
        mark = stem.removeprefix("examples/").replace("/", "-")
        assert page.count(f'id="{mark}">') == 1, name
        opened = re.search(rf'<li class="case {kinds[answer]}( warned)?" id="{mark}">', page)
        assert opened is not None, name
        row = page[opened.start() : page.index("</li>", opened.start())]
        title, says, said = told[name]
        assert f"<h4>{html.escape(title)}</h4>" in row, name
        cells = re.findall(r'<p class="case-(?:says|answer)">(.*?)</p>', row, re.S)
        assert [read(cell) for cell in cells] == [plain(says), plain(said)], name
        assert plain(said).startswith(answer), name
        assert f"uv run agloe check {name}</p>" in row, name
        assert f'<pre tabindex="0">{html.escape(report, quote=False)}</pre>' in row, name
        assert f'<a href="{REPOSITORY}/blob/main/{name}">FILE</a>' in row, name
        assert f'<a href="{REPOSITORY}/blob/main/{stem}.expected.json">JSON report</a>' in row, name
        shown[answer] += 1
    for answer, count in shown.items():
        assert f'value="{kinds[answer]}"><span>{answer} <b>{count}</b></span>' in page, answer
    assert f'value="all" checked><span>All <b>{len(files)}</b></span>' in page


def test_the_script_for_the_page_of_examples_refuses_a_section_it_cannot_read() -> None:
    spec = spec_from_file_location("build_site_examples", EXAMPLES_TOOL)
    assert spec is not None and spec.loader is not None
    tool = module_from_spec(spec)
    sys.modules[spec.name] = tool
    spec.loader.exec_module(tool)
    rules = (ROOT / "spec" / "rules.md").read_text()
    assert tool.stories(rules)
    row = "| [works](../examples/flight-home/works.json) | They leave the museum at 3:00 pm. |"
    assert rules.count(row) == 1
    for broken in (
        # No section, a row with no FILE, a table with other columns, a FILE that is not there.
        rules.replace("\n## Examples\n", "\n## Stories\n"),
        rules.replace(row, "| works | They leave the museum at 3:00 pm. |"),
        rules.replace("| FILE | What it says | Answer |", "| FILE | Answer |", 1),
        rules.replace(row, row.replace("works.json", "missing.json")),
        # A fourth cell, an answer that is not the expected one, and a FILE listed twice.
        rules.replace(row, row + " One more cell. |"),
        rules.replace(row + " FEASIBLE.", row + " INFEASIBLE."),
        rules.replace(row, row + " FEASIBLE. |\n" + row),
    ):
        assert broken != rules
        with pytest.raises(SystemExit, match="cannot be read"):
            tool.stories(broken)
    # A pipe inside a cell is written with a backslash, and the page shows the pipe alone.
    piped = tool.stories(rules.replace(row, row.replace("3:00 pm.", "3:00 pm \\| sharp.")))
    assert piped["flight-home"][0].cases[0].says == "They leave the museum at 3:00 pm | sharp."


def test_the_page_for_a_wrong_address_names_everything_from_the_root() -> None:
    """A wrong address can be any number of folders deep, so nothing on its page is relative."""
    page = SITE_PAGES["404.html"]
    assert page.links
    for link in [*page.links, *page.sheets]:
        assert link.startswith(("/", "#", "https://")), link


def target_of(folder: Path, link: str) -> Path:
    """The file or folder of the site that a link leads to, read from this folder."""
    if link.startswith(SITE):
        return (PAGES / link.removeprefix(SITE)).resolve()
    if link.startswith("/"):
        return (PAGES / link.lstrip("/")).resolve()
    return (folder / link).resolve()


def links_of(name: str) -> list[tuple[Path, str]]:
    """Each link of a page and of its style sheets, with the folder it is read from."""
    folder = (PAGES / name).parent
    found = [(folder, link) for link in SITE_PAGES[name].links]
    for sheet in SITE_PAGES[name].sheets:
        styles = target_of(folder, sheet)
        found += [
            (styles.parent, link) for link in re.findall(r'url\("([^"]+)"\)', styles.read_text())
        ]
    return found


def headings_of(document: Path) -> set[str]:
    """The headings of a document, each as GitHub names it in a link."""
    return {
        re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        for heading in re.findall(r"^#+ (.+)$", document.read_text(), flags=re.MULTILINE)
    }


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
                path, _, mark = link.removeprefix(start).partition("#")
                assert (ROOT / path).exists(), link
                if mark:
                    assert mark in headings_of(ROOT / path), link
                break
        else:
            if "://" in link and not link.startswith(SITE):
                continue
            # A link inside the site: to a file, or to a folder that holds a page.
            path, _, mark = link.partition("#")
            target = target_of(folder, path)
            assert PAGES.resolve() in (target, *target.parents), f"{link} leaves the site"
            # A page of the site, by its own name or by the folder it is the page of.
            there = target.relative_to(PAGES.resolve()).as_posix()
            pages = [
                each
                for each in (there, f"{there}/index.html".removeprefix("./"))
                if each in SITE_PAGES
            ]
            assert pages or target.is_file(), link
            if mark:
                assert mark in SITE_PAGES[pages[0]].ids, link


def test_the_pages_share_one_style_sheet() -> None:
    for name, page in SITE_PAGES.items():
        sheets = {target_of((PAGES / name).parent, sheet) for sheet in page.sheets}
        assert sheets == {(PAGES / "site.css").resolve()}, name
