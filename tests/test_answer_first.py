"""The answer can come first: a check gives its answer as soon as it is proved, then its report."""

import io
import json
import sys
from collections.abc import Callable
from pathlib import Path
from random import Random

import pytest

from agloe import answers, compiler, reference, report
from agloe.answers import Answer, CanWork, Report, Shown, Works
from agloe.cli import main
from agloe.file import File, read
from agloe.reference import Itinerary, Remaining, World, worst_case
from tests.stories import (
    EXAMPLES,
    cutoff,
    lasts,
    lock,
    must,
    needs_no_right,
    satisfies,
    starts_at,
    stays,
    takes,
    trip,
    way,
)
from tests.test_cross_check import random_trip

FILES = sorted(
    path for path in EXAMPLES.rglob("*.json") if not path.name.endswith(".expected.json")
)
WORKS = EXAMPLES / "flight-home" / "works.json"
CANNOT_WORK = EXAMPLES / "flight-home" / "cannot-work.json"
DEPENDS = EXAMPLES / "flight-home" / "depends-on-the-cab.json"

type Program = tuple[Shown, Works, CanWork]

PROGRAMS: dict[str, Program] = {
    "the reference checker": (reference.first_shown, reference.any_works, reference.can_work),
    "the solver": (compiler.shown, compiler.works, compiler.can_work),
}
SERIES: dict[str, Callable[[File], list[Report]]] = {
    "the reference checker": lambda file: list(answers.reports(file)),
    "the solver": lambda file: list(compiler.reports(file)),
}


class Asked:
    """The searches of one program, with a note of each question as it is asked."""

    def __init__(self, program: Program) -> None:
        self._shown, self._works, self._can_work = program
        self.questions: list[str] = []
        self.left: list[Remaining] = []

    def shown(self, file: File, world: World) -> Itinerary | None:
        self.questions.append("which plan is shown")
        return self._shown(file, world)

    def works(self, file: File, world: World) -> bool:
        self.questions.append("does anything work")
        return self._works(file, world)

    def can_work(self, remaining: Remaining) -> bool:
        self.questions.append("can anything work")
        self.left.append(remaining)
        return self._can_work(remaining)

    def reports(self, file: File) -> list[Report]:
        return list(answers.reports(file, self.shown, self.works, self.can_work))

    def check(self, file: File) -> Report:
        return answers.check(file, self.shown, self.works, self.can_work)


def two_shows() -> File:
    """Sam must see a show. The matinee and the evening show would both do."""
    shows = {"matinee": 14, "evening": 19}
    facts = [
        fact
        for show, hour in shows.items()
        for fact in (
            starts_at(show, hour),
            lasts(show, "PT2H"),
            cutoff(show, "PT0S"),
            satisfies(show, "a-show"),
        )
    ]
    return trip(
        ["sam"],
        ["theater"],
        [stays(show, "theater") for show in shows],
        facts,
        [],
        wants=[must("a-show", "sam")],
    )


@pytest.mark.parametrize("program", PROGRAMS)
def test_feasible_is_given_before_the_plan_to_show_is_looked_for(program: str) -> None:
    file = two_shows()
    asked = Asked(PROGRAMS[program])
    series = answers.reports(file, asked.shown, asked.works, asked.can_work)
    assert next(series) == Report(Answer.FEASIBLE, unfinished=True)
    assert asked.questions == ["does anything work"]
    full = next(series)
    assert asked.questions[1:] == ["which plan is shown"] * 2
    assert [step.option for step in full.itinerary] == ["matinee"]
    assert not full.unfinished
    assert list(series) == []


@pytest.mark.parametrize("program", PROGRAMS)
def test_the_first_plan_found_is_not_the_plan_shown(
    program: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """So the answer ahead holds no plan. The question stops at the first plan that works."""
    file = two_shows()
    worst = worst_case(file)
    found: list[Itinerary] = []
    scheduled = reference.scheduled

    def noted(*given: object, **named: object) -> Itinerary | None:
        result = scheduled(*given, **named)  # type: ignore[arg-type]
        if result is not None:
            found.append(result)
        return result

    monkeypatch.setattr(reference, "scheduled", noted)
    assert PROGRAMS[program][1](file, worst)
    monkeypatch.undo()
    assert [[step.option for step in each] for each in found] == [["evening"]]
    shown = reference.first_shown(file, worst)
    assert shown is not None
    assert [step.option for step in shown] == ["matinee"]


@pytest.mark.parametrize("program", PROGRAMS)
def test_infeasible_is_given_before_any_record_is_taken_out(program: str) -> None:
    file = read(CANNOT_WORK)
    asked = Asked(PROGRAMS[program])
    series = answers.reports(file, asked.shown, asked.works, asked.can_work)
    assert next(series) == Report(Answer.INFEASIBLE, unfinished=True)
    assert asked.questions == ["does anything work", "can anything work"]
    assert asked.left == [Remaining(file)]
    full = next(series)
    assert full.answer is Answer.INFEASIBLE
    assert full.conflict
    assert len(asked.left) > 1
    assert list(series) == []


@pytest.mark.parametrize("program", PROGRAMS)
def test_undetermined_is_given_before_any_missing_fact_is_tried(program: str) -> None:
    file = read(DEPENDS)
    asked = Asked(PROGRAMS[program])
    series = answers.reports(file, asked.shown, asked.works, asked.can_work)
    assert next(series) == Report(Answer.UNDETERMINED, unfinished=True)
    assert asked.questions == ["does anything work", "can anything work"]
    full = next(series)
    assert full.answer is Answer.UNDETERMINED
    assert full.missing
    assert len(asked.questions) > 2
    assert list(series) == []


def test_two_locks_at_once_are_asked_about_in_both_cases() -> None:
    """Sam is LOCKed into a talk at 9 and a talk at 10, and nobody knows how long the first is.

    Nothing works in the worst case: the first talk might never end. The answer is not
    INFEASIBLE for that. In the best case the first talk is over by 10.
    """
    file = trip(
        ["sam"],
        ["hall"],
        [stays("first", "hall"), stays("second", "hall")],
        [
            starts_at("first", 9),
            cutoff("first", "PT0S"),
            starts_at("second", 10),
            lasts("second", "PT1H"),
            cutoff("second", "PT0S"),
        ],
        [lock("first", "sam"), lock("second", "sam")],
    )
    for series in SERIES.values():
        ahead, full = series(file)
        assert ahead == Report(Answer.UNDETERMINED, unfinished=True)
        assert full.answer is Answer.UNDETERMINED


def test_an_empty_file_has_no_plan_ahead_and_an_empty_plan_in_its_report() -> None:
    file = trip([], [], [], [], [])
    for series in SERIES.values():
        ahead, full = series(file)
        assert report.as_json(file, ahead) == {"answer": "FEASIBLE", "unfinished": True}
        shape = report.as_json(file, full)
        assert shape["itinerary"] == []
        assert "unfinished" not in shape


@pytest.mark.parametrize("path", [WORKS, CANNOT_WORK, DEPENDS], ids=lambda path: path.stem)
@pytest.mark.parametrize("program", PROGRAMS)
def test_a_plain_check_asks_what_it_asked_before(program: str, path: Path) -> None:
    """The question that gives FEASIBLE ahead is asked only where the answer is wanted ahead."""
    file = read(path)
    ahead, plain = Asked(PROGRAMS[program]), Asked(PROGRAMS[program])
    *_, full = ahead.reports(file)
    assert plain.check(file) == full
    assert plain.questions[0] == "which plan is shown"
    assert ahead.questions[0] == "does anything work"
    if full.answer is Answer.FEASIBLE:
        assert ahead.questions[1:] == plain.questions
    else:
        # Nothing works in the worst case, so no plan to show is looked for there.
        assert ahead.questions[1:] == plain.questions[1:]


@pytest.mark.parametrize("path", FILES, ids=lambda path: f"{path.parent.name}/{path.stem}")
@pytest.mark.parametrize("program", SERIES)
def test_the_answer_ahead_is_the_answer_of_the_expected_result(program: str, path: Path) -> None:
    file = read(path)
    expected = json.loads(path.with_name(path.stem + ".expected.json").read_text())
    ahead, full = SERIES[program](file)
    assert ahead == Report(Answer(expected["answer"]), unfinished=True)
    assert report.as_json(file, full) == expected


def test_the_two_programs_give_the_same_series_on_random_trips() -> None:
    rng = Random(74)
    trips = [random_trip(rng, leave_out=0) for _ in range(40)]
    trips += [random_trip(rng, 0.25, contingent=0.3, with_complete=0.4) for _ in range(60)]
    trips += [
        random_trip(rng, 0.2, contingent=0.3, with_complete=0.4, with_ways=0.9) for _ in range(60)
    ]
    trips += [
        random_trip(rng, 0.2, with_wants=0.8, must_nots=0.3, whole_sets=0.5) for _ in range(60)
    ]
    trips += [random_trip(rng, 0.2, with_wants=0.5, with_rights=0.8) for _ in range(60)]
    seen: set[Answer] = set()
    for file in trips:
        series = list(answers.reports(file))
        assert list(compiler.reports(file)) == series
        ahead, full = series
        assert ahead == Report(full.answer, unfinished=True)
        assert full == answers.check(file)
        seen.add(full.answer)
    assert seen == set(Answer)


def does_not_fit(*given: object, **named: object) -> None:
    raise compiler.DoesNotFit


@pytest.mark.parametrize("search", ["works", "shown", "can_work"])
@pytest.mark.parametrize("path", [WORKS, CANNOT_WORK, DEPENDS], ids=lambda path: path.stem)
def test_the_reference_checker_takes_over_without_saying_anything_twice(
    path: Path, search: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The numbers stop fitting the solver before the answer is given, or after."""
    file = read(path)
    expected = list(answers.reports(file))
    monkeypatch.setattr(compiler, search, does_not_fit)
    assert list(compiler.reports(file)) == expected
    assert compiler.check(file) == expected[-1]


def test_the_numbers_stop_fitting_after_infeasible_was_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first question about a record of the conflict does not fit the solver."""
    file = read(CANNOT_WORK)
    expected = list(answers.reports(file))
    can_work = compiler.can_work
    questions: list[Remaining] = []

    def fits_once(remaining: Remaining, asked: object = None) -> bool:
        questions.append(remaining)
        if len(questions) > 1:
            raise compiler.DoesNotFit
        return can_work(remaining)

    monkeypatch.setattr(compiler, "can_work", fits_once)
    series = compiler.reports(file)
    assert next(series) == expected[0]
    assert len(questions) == 1
    assert list(series) == expected[1:]
    assert len(questions) == 2


def test_times_too_far_apart_for_the_solver_still_get_the_answer_once() -> None:
    """One WAY takes over 100,000 years, among 1,122 PLACEs: a path could pass 64 bits."""
    places = [f"p{number}" for number in range(1122)]
    visits = [stays(f"visit-{number}", "p0") for number in range(1122)]
    far = [takes("far", "PT999999999H999999999M999999999S")]
    file = trip(["sam"], places, visits, far, [], ways=[way("far", "p0", "p1")])
    with pytest.raises(compiler.DoesNotFit):
        compiler.works(file, worst_case(file))
    ahead, full = compiler.reports(file)
    assert ahead == Report(Answer.FEASIBLE, unfinished=True)
    assert (full.answer, full.itinerary, full.unfinished) == (Answer.FEASIBLE, (), False)


def test_an_answer_ahead_in_words() -> None:
    file = two_shows()
    assert report.as_text(file, Report(Answer.FEASIBLE, unfinished=True)).splitlines() == [
        "FEASIBLE: this trip can work.",
        "",
        "The check is still choosing the plan to show. The report will say whether that plan is"
        " sure to hold, and what is still to buy.",
    ]
    assert report.as_text(file, Report(Answer.INFEASIBLE, unfinished=True)).splitlines() == [
        "INFEASIBLE: this trip cannot work.",
        "",
        "The check is still working out which FACTs, WANTs and DECISIONs rule out every plan.",
    ]
    assert report.as_text(file, Report(Answer.UNDETERMINED, unfinished=True)).splitlines() == [
        "UNDETERMINED: the FILE does not say enough to tell.",
        "",
        "The check is still working out which missing FACTs would be enough.",
    ]


@pytest.mark.parametrize("path", FILES, ids=lambda path: f"{path.parent.name}/{path.stem}")
def test_the_command_prints_the_answer_and_then_the_expected_result(
    path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """As JSON, each of the two is one line. The second holds the expected result."""
    code = main(["check", str(path), "--json", "--answer-first"])
    ahead, full = capsys.readouterr().out.splitlines()
    expected = json.loads(path.with_name(path.stem + ".expected.json").read_text())
    assert json.loads(ahead) == {"answer": expected["answer"], "unfinished": True}
    assert json.loads(full) == expected
    assert code == (0 if expected["answer"] == "FEASIBLE" else 1)


@pytest.mark.parametrize("path", [WORKS, CANNOT_WORK, DEPENDS], ids=lambda path: path.stem)
def test_the_command_prints_the_answer_and_then_the_expected_words(
    path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file = read(path)
    answer = Answer(json.loads(path.with_name(path.stem + ".expected.json").read_text())["answer"])
    main(["check", str(path), "--answer-first"])
    ahead = report.as_text(file, Report(answer, unfinished=True))
    expected = path.with_name(path.stem + ".expected.txt").read_text()
    assert capsys.readouterr().out == f"{ahead}\n{expected}"


class Written(io.StringIO):
    """What a command printed, and how much of it has been written out."""

    out = 0

    def flush(self) -> None:
        self.out = len(self.getvalue())
        super().flush()


@pytest.mark.parametrize(
    ("path", "search", "answer"),
    [(WORKS, "shown", "FEASIBLE"), (CANNOT_WORK, "can_work", "INFEASIBLE")],
    ids=["works", "cannot-work"],
)
def test_the_answer_is_written_out_before_the_search_goes_on(
    path: Path, search: str, answer: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whoever reads the first line has it while the evidence is still being worked out."""
    printed = Written()
    monkeypatch.setattr(sys, "stdout", printed)
    real = getattr(compiler, search)
    seen: list[str] = []

    def noted(*given: object, **named: object) -> object:
        seen.append(printed.getvalue()[: printed.out])
        return real(*given, **named)

    monkeypatch.setattr(compiler, search, noted)
    main(["check", str(path), "--json", "--answer-first"])
    line = json.dumps({"answer": answer, "unfinished": True}) + "\n"
    # The question that proves INFEASIBLE is asked before anything is printed.
    assert seen[-1] == line
    assert set(seen) <= {"", line}
    assert printed.getvalue().startswith(line)


def test_an_answer_can_be_printed_before_a_report_that_cannot_be_written(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """The stay starts in the last second of the year 9999 and ends one second later.

    The answer holds no time, so it is printed. The command still ends with 2.
    """
    document = {
        "persons": [{"id": "alex", "name": "Alex"}],
        "places": [{"id": "pier", "name": "Navy Pier"}],
        "options": [stays("fireworks", "pier")],
        "ways": [],
        "wants": [],
        "facts": [
            {
                "id": "fireworks-time",
                "option": "fireworks",
                "starts_at": "9999-12-31T23:59:59+00:00[UTC]",
            },
            lasts("fireworks", "PT1S"),
            needs_no_right("fireworks"),
        ],
        "decisions": [lock("fireworks", "alex")],
    }
    path = tmp_path / "trip.json"
    path.write_text(json.dumps(document))
    assert main(["check", str(path), "--json", "--answer-first"]) == 2
    printed = capsys.readouterr()
    assert printed.out == '{"answer": "FEASIBLE", "unfinished": true}\n'
    assert printed.err == (
        f"{path}: the report holds a time outside the years 0001 to 9999, so it cannot be written\n"
    )
