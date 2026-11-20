"""A FILE is read from its text exactly as it is read from disk.

``parse`` takes the text of a FILE and ``read`` takes its path. Both give the same File, and
both refuse the same text with the same problems.
"""

from pathlib import Path

import pytest

from agloe.file import FileError, parse, read
from tests.stories import EXAMPLES

FILES = sorted(
    path for path in EXAMPLES.rglob("*.json") if not path.name.endswith(".expected.json")
)
STORY = (EXAMPLES / "a-must" / "works.json").read_text(encoding="utf-8")

REFUSED = {
    "not JSON": "{ this is not JSON",
    "a key stated twice": STORY.replace('"persons":', '"persons": [], "persons":', 1),
    "nested too deeply": "[" * 100_000 + "]" * 100_000,
    "NaN": STORY.replace('"degree": 10', '"degree": NaN', 1),
    "a number with a fraction": STORY.replace('"degree": 10', '"degree": 7.5', 1),
}


@pytest.mark.parametrize("path", FILES, ids=lambda path: f"{path.parent.name}/{path.stem}")
def test_the_text_of_a_file_gives_the_same_file_as_its_path(path: Path) -> None:
    assert parse(path.read_text(encoding="utf-8")) == read(path)


@pytest.mark.parametrize("text", REFUSED.values(), ids=REFUSED.keys())
def test_the_text_of_a_file_is_refused_as_its_path_is(text: str, tmp_path: Path) -> None:
    path = tmp_path / "trip.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(FileError) as from_text:
        parse(text)
    with pytest.raises(FileError) as from_disk:
        read(path)
    assert from_text.value.problems
    assert from_text.value.problems == from_disk.value.problems


def test_a_path_that_holds_no_text_is_refused_as_before(tmp_path: Path) -> None:
    """Bytes that are no UTF-8 are no JSON. A path that cannot be opened is another failure."""
    path = tmp_path / "trip.json"
    path.write_bytes(b"\xff\xfe")
    with pytest.raises(FileError) as refused:
        read(path)
    assert refused.value.problems[0].startswith("not readable as JSON: 'utf-8' codec")
    with pytest.raises(OSError, match="No such file"):
        read(tmp_path / "nothing.json")
