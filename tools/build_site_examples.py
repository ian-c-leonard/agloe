"""Write the page of examples for agloe.ai: ``pages/examples/index.html``.

The rules page, ``spec/rules.md``, ends with the examples: a story in words, then a table with
one row for each FILE of that story, what the FILE says and the answer. This script reads that
section and writes it as a page of the site, with the report of each FILE beside it. So the page
says what the rules page says, and nobody has to keep the two in step.

The page is not committed. The pages workflow runs this before it publishes agloe.ai:

    python tools/build_site_examples.py

The frame of the page is ``tools/site_examples.html``. The header and the footer are those of the
home page. The script stops with an error where the section has a shape it does not know, or
where a row names a FILE that is missing its report. The tests run it, so that shows before a
merge.
"""

import argparse
import html
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from string import Template

ROOT = Path(__file__).resolve().parent.parent
PAGES = ROOT / "pages"
FRAME = Path(__file__).with_name("site_examples.html")
SOURCE = "https://github.com/ian-c-leonard/agloe/blob/main"
FOLDER = "https://github.com/ian-c-leonard/agloe/tree/main"
HEADING = "\n## Examples\n"
COLUMNS = "| FILE | What it says | Answer |"
# The first cell of a row: the name of a FILE, as a link to it.
FILE = re.compile(r"^\[(?P<name>[^\]]+)\]\(\.\./(?P<file>examples/[\w-]+/[\w-]+\.json)\)$")
# The class of an answer on the page, by the answer in the report as data.
KINDS = {"FEASIBLE": "feasible", "INFEASIBLE": "infeasible", "UNDETERMINED": "undetermined"}

CASE = Template("""\
          <li class="case $kind" id="$mark">
            <h4>$name</h4>
            <p class="case-says">$says</p>
            <p class="case-answer">$answer</p>
            <details>
              <summary>The report</summary>
              <div class="terminal">
                <p class="command"><span aria-hidden="true">$$ </span>uv run agloe check $file</p>
                <pre tabindex="0">$report</pre>
              </div>
              <p class="small"><a href="$source/$file">FILE</a>
                <a href="$source/$data">JSON report</a></p>
            </details>
          </li>""")
PART = Template("""\
        <div class="part">
$told
          <ul class="cases">
$cases
          </ul>
        </div>""")
STORY = Template("""\
      <section class="story" id="$folder" aria-labelledby="$folder-name">
        <h2 id="$folder-name"><a href="$at/examples/$folder">examples/<b>$folder</b></a></h2>
$parts
      </section>""")
SHOWN = Template(
    '        <label><input type="radio" name="show" value="$kind">'
    "<span>$answer <b>$count</b></span></label>"
)


@dataclass(frozen=True)
class Case:
    """One FILE of a story: its name on the rules page, what it says, and the answer."""

    name: str
    file: str
    says: str
    answer: str
    kind: str
    report: str


@dataclass(frozen=True)
class Part:
    """A story in words, and the FILEs that tell it."""

    told: tuple[str, ...]
    cases: tuple[Case, ...]


def wrong(why: str) -> SystemExit:
    return SystemExit(f"The examples of spec/rules.md cannot be read: {why}")


def blocks_of(rules: str) -> list[str]:
    """The paragraphs and tables of the examples section of the rules page."""
    if rules.count(HEADING) != 1:
        raise wrong('there is not exactly one heading "## Examples"')
    return rules.split(HEADING)[1].strip().split("\n\n")


def stories(rules: str) -> dict[str, list[Part]]:
    """Each folder of examples with its stories, in the order of the rules page."""
    blocks = blocks_of(rules)
    found: dict[str, list[Part]] = {}
    told: list[str] = []
    # The first paragraph is about all the stories, and the last is about the reports.
    for block in blocks[1:-1]:
        if not block.startswith("|"):
            told.append(block)
            continue
        head, rule, *rows = block.split("\n")
        if head != COLUMNS or not set(rule) <= set("|-") or not told or not rows:
            raise wrong(f"a table does not follow a story with the columns {COLUMNS}")
        cases = [case(row) for row in rows]
        folders = {each.file.split("/")[1] for each in cases}
        if len(folders) != 1:
            raise wrong(f"one table names FILEs of several folders: {sorted(folders)}")
        listed = [each.file for parts in found.values() for part in parts for each in part.cases]
        twice = sorted({each.file for each in cases} & set(listed)) or sorted(
            {each.file for each in cases if [other.file for other in cases].count(each.file) > 1}
        )
        if twice:
            raise wrong(f"a FILE is listed twice: {twice[0]}")
        found.setdefault(folders.pop(), []).append(Part(tuple(told), tuple(cases)))
        told = []
    if told or len(blocks) < 3 or blocks[-1].startswith("|"):
        raise wrong("the section does not end with a table and then one paragraph")
    return found


def case(row: str) -> Case:
    """One row of a table, with the report that stands beside its FILE.

    A row has three cells. A pipe inside a cell is written with a backslash before it.
    """
    cells = [cell.strip().replace("\\|", "|") for cell in re.split(r"(?<!\\)\|", row)]
    read = FILE.match(cells[1]) if len(cells) == 5 and not (cells[0] or cells[4]) else None
    if read is None or not cells[2] or not cells[3]:
        raise wrong(f"this row is not a FILE, what it says and an answer: {row[:80]}")
    says, answer = cells[2], cells[3]
    file = ROOT / read["file"]
    in_words = file.with_name(file.stem + ".expected.txt")
    as_data = file.with_name(file.stem + ".expected.json")
    if not (file.is_file() and in_words.is_file() and as_data.is_file()):
        raise wrong(f"{read['file']} or its expected report is missing")
    report = in_words.read_text()
    expected = json.loads(as_data.read_text())["answer"]
    if expected not in KINDS:
        raise wrong(f"{read['file']} expects the answer {expected}, which this page does not know")
    # The words of the row start with the answer of the expected result.
    if re.match(rf"{expected}\b", answer) is None:
        raise wrong(f"the row of {read['file']} does not start its answer with {expected}")
    kind = KINDS[expected]
    # A FEASIBLE answer with a WARNING says so in the first line of its report.
    if kind == "feasible" and "WARNING" in report.split("\n")[0]:
        kind = "feasible warned"
    return Case(read["name"], read["file"], says, answer, kind, report)


def words(markdown: str) -> str:
    """A line of the rules page as HTML: its links, its bold words and its code."""

    def link(found: re.Match[str]) -> str:
        # A link of the rules page is read from where that page is: spec/rules.md.
        target = found[2]
        if target.startswith("../"):
            target = f"{SOURCE}/{target.removeprefix('../')}"
        elif target.startswith("#"):
            target = f"{SOURCE}/spec/rules.md{target}"
        elif "://" not in target:
            target = f"{SOURCE}/spec/{target}"
        return f'<a href="{html.escape(target)}">{found[1]}</a>'

    text = html.escape(markdown, quote=False)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link, text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", text)


def in_page(each: Case) -> str:
    """One FILE as a row of the page: its name, what it says, the answer, and its report."""
    stem = each.file.removesuffix(".json")
    return CASE.substitute(
        kind=each.kind,
        mark=stem.removeprefix("examples/").replace("/", "-"),
        name=html.escape(each.name),
        says=words(each.says),
        answer=words(each.answer),
        file=each.file,
        data=f"{stem}.expected.json",
        report=html.escape(each.report, quote=False),
        source=SOURCE,
    )


def page(rules: str, home: str) -> str:
    """The page of examples, with the header and the footer of the home page."""
    found = stories(rules)
    cases = [each for parts in found.values() for part in parts for each in part.cases]
    counts = {kind: sum(each.kind.split()[0] == kind for each in cases) for kind in KINDS.values()}
    told = [
        STORY.substitute(
            folder=folder,
            at=FOLDER,
            parts="\n".join(
                PART.substitute(
                    told="\n".join(f'          <p class="told">{words(p)}</p>' for p in part.told),
                    cases="\n".join(in_page(each) for each in part.cases),
                )
                for part in parts
            ),
        )
        for folder, parts in found.items()
    ]
    return Template(FRAME.read_text()).substitute(
        header=home[home.index('<a class="skip" href="#main">') : home.index("</header>") + 9],
        footer=home[home.rindex("<footer>") : home.rindex("</footer>") + 9],
        count=len(cases),
        shown="\n".join(
            SHOWN.substitute(kind=kind, answer=answer, count=counts[kind])
            for answer, kind in KINDS.items()
        ),
        folders="\n".join(f'          <li><a href="#{each}">{each}</a></li>' for each in found),
        stories="\n".join(told),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Write the page of examples for agloe.ai.")
    parser.add_argument("--out", type=Path, default=PAGES / "examples" / "index.html")
    out: Path = parser.parse_args().out
    written = page((ROOT / "spec" / "rules.md").read_text(), (PAGES / "index.html").read_text())
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(written)
    print(f"wrote {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
