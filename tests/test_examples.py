"""Every example FILE gives the result written beside it."""

import json
from pathlib import Path
from typing import Any, cast

import pytest

from agloe.file import instant, length, read
from agloe.reference import Report, broken, check, worst_case
from tests.stories import EXAMPLES

FILES = sorted(
    path for path in EXAMPLES.rglob("*.json") if not path.name.endswith(".expected.json")
)


def in_seconds(expected: Any) -> Any:
    """The expected result with its times and lengths of time as whole seconds."""
    if isinstance(expected, list):
        return [in_seconds(item) for item in cast("list[Any]", expected)]
    if isinstance(expected, dict):
        out: dict[str, Any] = {}
        for key, value in cast("dict[str, Any]", expected).items():
            if key in ("start", "end"):
                out[key] = instant(value)
            elif key in ("late", "at_most"):
                out[key] = length(value)
            else:
                out[key] = in_seconds(value)
        return out
    return expected


def as_written(report: Report) -> dict[str, Any]:
    """A report in the shape of an expected result."""
    out: dict[str, Any] = {"answer": report.answer.value}
    if report.itinerary:
        out["itinerary"] = [
            {
                "option": step.option,
                "persons": list(step.persons),
                "start": step.start,
                "end": step.end,
            }
            for step in report.itinerary
        ]
        out["relies_on"] = list(report.relies_on)
        out["robust"] = report.robust
    if report.at_worst:
        out["at_worst"] = [
            {
                "constraint": found.constraint.value,
                "option": found.option,
                "persons": list(found.persons),
                "late": found.late,
            }
            for found in report.at_worst
        ]
    if report.conflict:
        out["conflict"] = list(report.conflict)
    if report.missing:
        missing: list[dict[str, Any]] = []
        for needed in report.missing:
            unknown = needed.unknown
            entry: dict[str, Any] = {"what": unknown.what}
            if unknown.option is not None:
                entry["option"] = unknown.option
            else:
                entry["from"], entry["to"] = unknown.origin, unknown.destination
            entry["at_most"] = needed.at_most
            missing.append(entry)
        out["missing"] = missing
    return out


def expected_beside(path: Path) -> Path:
    return path.with_name(path.stem + ".expected.json")


def test_there_are_examples() -> None:
    assert len(FILES) >= 5


@pytest.mark.parametrize("path", FILES, ids=lambda path: f"{path.parent.name}/{path.stem}")
def test_example_gives_its_expected_result(path: Path) -> None:
    expected = in_seconds(json.loads(expected_beside(path).read_text()))
    assert as_written(check(read(path))) == expected


@pytest.mark.parametrize("path", FILES, ids=lambda path: f"{path.parent.name}/{path.stem}")
def test_example_gives_the_same_result_every_time(path: Path) -> None:
    assert check(read(path)) == check(read(path))


@pytest.mark.parametrize("path", FILES, ids=lambda path: f"{path.parent.name}/{path.stem}")
def test_the_itinerary_shown_meets_every_constraint(path: Path) -> None:
    file = read(path)
    report = check(file)
    if report.itinerary:
        assert broken(file, worst_case(file), report.itinerary) == []


def test_every_expected_result_has_its_file() -> None:
    for result in EXAMPLES.rglob("*.expected.json"):
        assert result.with_name(result.name.replace(".expected.json", ".json")) in FILES
