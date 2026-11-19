"""The agloe.ai home page, ``pages/index.html``, agrees with the documents and the examples.

The page marks each passage it takes from elsewhere with ``data-from`` and the path of its
source. A passage from a document must be in that document, word for word. An example must be
shown whole.
"""

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
PAGES = ROOT / "pages"
SITE = "https://agloe.ai/"
REPOSITORY = "https://github.com/ian-c-leonard/agloe"

# Elements that have no end tag.
VOID = {"br", "hr", "img", "input", "link", "meta"}


class Page(HTMLParser):
    """Reads the page into its marked passages, its links and the ids that links can point at."""

    def __init__(self) -> None:
        super().__init__()
        self.passages: list[tuple[str, str]] = []
        self.links: list[str] = []
        self.ids: set[str] = set()
        self.text: list[str] = []
        self.open: list[tuple[str, str | None, list[str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        named = dict(attrs)
        self.links += [value for name in ("href", "src") if (value := named.get(name))]
        if (content := named.get("content")) and content.startswith(SITE):
            self.links.append(content)
        if identity := named.get("id"):
            self.ids.add(identity)
        if tag not in VOID:
            self.open.append((tag, named.get("data-from"), []))

    def handle_endtag(self, tag: str) -> None:
        opened, source, parts = self.open.pop()
        assert opened == tag, f"<{opened}> is closed by </{tag}>"
        if source is not None:
            self.passages.append((source, "".join(parts)))

    def handle_data(self, data: str) -> None:
        if self.open and self.open[-1][0] == "style":
            self.links += re.findall(r'url\("([^"]+)"\)', data)
            return
        self.text.append(data)
        for _, source, parts in self.open:
            if source is not None:
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


def test_the_page_takes_passages_from_documents_and_shows_examples() -> None:
    sources = {Path(source).suffix for source, _ in PAGE.passages}
    assert {".md", ".json", ".txt"} <= sources


@pytest.mark.parametrize(
    ("source", "text"), PAGE.passages, ids=lambda value: words(str(value))[:50]
)
def test_the_page_says_what_its_source_says(source: str, text: str) -> None:
    there = (ROOT / source).read_text()
    if source.endswith(".md"):
        assert words(text) in plain(there)
    else:
        assert text.strip("\n") == there.strip("\n")


def test_each_report_stands_under_the_command_that_gives_it() -> None:
    shown = words("".join(PAGE.text))
    reports = [source for source, _ in PAGE.passages if source.endswith(".expected.txt")]
    for report in reports:
        file = report.replace(".expected.txt", ".json")
        assert f"uv run agloe check {file}" in shown


def test_every_example_the_page_names_exists() -> None:
    named = set(re.findall(r"examples/[\w/-]+\.json", "".join(PAGE.text)))
    assert named
    for file in named:
        assert (ROOT / file).is_file(), file


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
