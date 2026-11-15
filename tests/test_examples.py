"""Every example FILE gives the result written beside it."""

import json
from pathlib import Path

import pytest

from agloe import report
from agloe.answers import check
from agloe.file import read
from agloe.reference import broken, needless, worst_case
from tests.stories import EXAMPLES

FILES = sorted(
    path for path in EXAMPLES.rglob("*.json") if not path.name.endswith(".expected.json")
)


def expected_beside(path: Path) -> Path:
    return path.with_name(path.stem + ".expected.json")


def test_there_are_examples() -> None:
    assert len(FILES) >= 5


@pytest.mark.parametrize("path", FILES, ids=lambda path: f"{path.parent.name}/{path.stem}")
def test_example_gives_its_expected_result(path: Path) -> None:
    file = read(path)
    assert report.as_json(file, check(file)) == json.loads(expected_beside(path).read_text())


@pytest.mark.parametrize("path", FILES, ids=lambda path: f"{path.parent.name}/{path.stem}")
def test_example_gives_the_same_result_every_time(path: Path) -> None:
    assert check(read(path)) == check(read(path))


@pytest.mark.parametrize("path", FILES, ids=lambda path: f"{path.parent.name}/{path.stem}")
def test_the_itinerary_shown_works_and_has_nothing_needless(path: Path) -> None:
    file = read(path)
    itinerary = check(file).itinerary
    if itinerary:
        assert broken(file, worst_case(file), itinerary) == []
        assert needless(file, worst_case(file), itinerary) == []


def test_every_expected_result_has_its_file() -> None:
    for result in EXAMPLES.rglob("*.expected.json"):
        assert result.with_name(result.name.replace(".expected.json", ".json")) in FILES
