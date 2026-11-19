"""The agloe.ai home page, ``pages/index.html``, agrees with the documents and the examples.

The page marks what it takes from elsewhere with the path of its source:

- ``data-from``: a passage from a document must be in that document, word for word, and an
  example must be shown whole.
- ``data-lines-from``: the words are whole lines of that file, one after another.

The page also draws the first story as a day. Each bar is placed by numbers in the style
sheet, one set for each version of the trip, and each number must be a FACT of that FILE.
"""

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest

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


def minutes(length: str) -> int:
    """A length of time such as PT1H20M, in minutes."""
    found = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?", length)
    assert found, length
    return int(found.group(1) or 0) * 60 + int(found.group(2) or 0)


def fact_in_minutes(fact: dict[str, Any], longest: bool) -> int:
    """What a FACT states, as the page draws it: a time of day or a length, in minutes."""
    if "starts_at" in fact:
        hour, minute = fact["starts_at"][11:16].split(":")
        return int(hour) * 60 + int(minute)
    if "contingent_duration" in fact:
        return minutes(fact["contingent_duration"]["longest" if longest else "shortest"])
    for name in ("duration", "arrive_before_start"):
        if name in fact:
            return minutes(fact[name])
    raise AssertionError(f"the page cannot draw {fact}")


def drawn_days() -> list[tuple[str, str, int]]:
    """Each number the page draws a day from: the version, the name of the FACT, the number."""
    style = "".join(PAGE.style)
    days = re.findall(r'main:has\(input\[value="([\w-]+)"\]:checked\) \{([^}]*)\}', style)
    return [
        (version, name, int(number))
        for version, block in days
        for name, number in re.findall(r"--([\w-]+): (\d+);", block)
    ]


def test_the_page_draws_a_day_for_each_version_it_offers() -> None:
    offered = set(
        re.findall(r'name="version" value="([\w-]+)"', (PAGES / "index.html").read_text())
    )
    assert offered
    assert {version for version, _, _ in drawn_days()} == offered


@pytest.mark.parametrize(("version", "name", "number"), drawn_days())
def test_each_number_of_a_day_is_a_fact_of_its_file(version: str, name: str, number: int) -> None:
    file = json.loads((ROOT / STORY / f"{version}.json").read_text())
    facts = {fact["id"]: fact for fact in file["facts"]}
    longest = name.endswith("-longest")
    assert fact_in_minutes(facts[name.removesuffix("-longest")], longest) == number


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
