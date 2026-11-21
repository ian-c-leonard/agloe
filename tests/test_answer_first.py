"""The answer can come first: a check gives its answer as soon as it is proved, then its report."""

import io
import json
import os
import select
import subprocess
import sys
from collections.abc import Callable, Iterable
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
    Document,
    cutoff,
    lasts,
    lasts_between,
    lock,
    must,
    needs_no_right,
    needs_right,
    offer,
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


def the_two(series: Iterable[Answer | Report]) -> tuple[Answer, Report]:
    """A series is the answer and then the Report, and nothing more."""
    ahead, full = series
    assert isinstance(ahead, Answer)
    assert isinstance(full, Report)
    return ahead, full


SERIES: dict[str, Callable[[File], tuple[Answer, Report]]] = {
    "the reference checker": lambda file: the_two(answers.reports(file)),
    "the solver": lambda file: the_two(compiler.reports(file)),
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

    def reports(self, file: File) -> tuple[Answer, Report]:
        return the_two(answers.reports(file, self.shown, self.works, self.can_work))

    def check(self, file: File) -> Report:
        return answers.check(file, self.shown, self.works, self.can_work)


def two_shows(*lasting: Document) -> File:
    """Sam must see a show. The matinee and the evening show would both do.

    Each show lasts two hours, unless ``lasting`` says how long one of them lasts.
    """
    shows = {"matinee": 14, "evening": 19}
    stated = {fact["option"] for fact in lasting}
    facts = [
        fact
        for show, hour in shows.items()
        for fact in (
            starts_at(show, hour),
            *([] if show in stated else [lasts(show, "PT2H")]),
            cutoff(show, "PT0S"),
            satisfies(show, "a-show"),
        )
    ]
    facts += lasting
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
    assert next(series) is Answer.FEASIBLE
    assert asked.questions == ["does anything work"]
    full = next(series)
    assert isinstance(full, Report)
    assert asked.questions[1:] == ["which plan is shown"]
    assert [step.option for step in full.itinerary] == ["matinee"]
    assert list(series) == []


@pytest.mark.parametrize("program", PROGRAMS)
def test_the_plan_to_show_is_looked_for_once_in_the_same_world(program: str) -> None:
    """With no CONTINGENT duration, the longest case is the worst case.

    The plan found in the worst case is the plan for the longest case, so the report is ROBUST
    with no second search. A show that can run long makes the two cases differ, and then each
    is searched.
    """
    asked = Asked(PROGRAMS[program])
    assert asked.check(two_shows()).robust
    assert asked.questions == ["which plan is shown"]
    asked = Asked(PROGRAMS[program])
    report = asked.check(two_shows(lasts_between("evening", "PT2H", "PT3H")))
    assert report.robust
    assert asked.questions == ["which plan is shown"] * 2


@pytest.mark.parametrize("program", PROGRAMS)
def test_a_plan_that_buys_a_place_is_looked_for_once_in_each_world(program: str) -> None:
    """Sam still has to buy a place for the show, and no duration is CONTINGENT.

    First comes a search for a plan that takes no place of an OFFER, and there is none. The
    plan of the worst case then stands for the longest case: two searches, where each world
    has one.
    """
    file = trip(
        ["sam"],
        ["theater"],
        [stays("show", "theater")],
        [
            starts_at("show", 19),
            lasts("show", "PT2H"),
            cutoff("show", "PT0S"),
            needs_right("show"),
            offer("show", 1, price="20.00 USD"),
        ],
        [lock("show", "sam")],
        rights=True,
    )
    asked = Asked(PROGRAMS[program])
    report = asked.check(file)
    assert (report.answer, report.robust) == (Answer.FEASIBLE, True)
    assert [cover.to_buy for cover in report.rights] == [True]
    assert asked.questions == ["which plan is shown"] * 2


def found_by(works: Works, file: File, monkeypatch: pytest.MonkeyPatch) -> list[Itinerary]:
    """Each ITINERARY that passed the rules while this search looked for one in the worst case."""
    found: list[Itinerary] = []
    scheduled = reference.scheduled

    def noted(*given: object, **named: object) -> Itinerary | None:
        result = scheduled(*given, **named)  # type: ignore[arg-type]
        if result is not None:
            found.append(result)
        return result

    monkeypatch.setattr(reference, "scheduled", noted)
    assert works(file, worst_case(file))
    monkeypatch.undo()
    return found


@pytest.mark.parametrize("program", PROGRAMS)
def test_the_question_before_feasible_stops_at_the_first_plan_that_works(
    program: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Which plan that is can differ: the solver may find either show first."""
    found = found_by(PROGRAMS[program][1], two_shows(), monkeypatch)
    assert len(found) == 1
    assert [step.option for step in found[0]] in (["matinee"], ["evening"])


def test_the_first_plan_the_reference_checker_finds_is_not_the_plan_shown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """So no plan is given with the answer: the plan to show is still to be chosen."""
    file = two_shows()
    (first,) = found_by(reference.any_works, file, monkeypatch)
    shown = reference.first_shown(file, worst_case(file))
    assert shown is not None
    assert [step.option for step in first] == ["evening"]
    assert [step.option for step in shown] == ["matinee"]


@pytest.mark.parametrize("program", PROGRAMS)
def test_infeasible_is_given_before_any_record_is_taken_out(program: str) -> None:
    file = read(CANNOT_WORK)
    asked = Asked(PROGRAMS[program])
    series = answers.reports(file, asked.shown, asked.works, asked.can_work)
    assert next(series) is Answer.INFEASIBLE
    assert asked.questions == ["does anything work", "can anything work"]
    assert asked.left == [Remaining(file)]
    full = next(series)
    assert isinstance(full, Report)
    assert full.answer is Answer.INFEASIBLE
    assert full.conflict
    assert len(asked.left) > 1
    assert list(series) == []


@pytest.mark.parametrize("program", PROGRAMS)
def test_undetermined_is_given_before_any_missing_fact_is_tried(program: str) -> None:
    file = read(DEPENDS)
    asked = Asked(PROGRAMS[program])
    series = answers.reports(file, asked.shown, asked.works, asked.can_work)
    assert next(series) is Answer.UNDETERMINED
    assert asked.questions == ["does anything work", "can anything work"]
    full = next(series)
    assert isinstance(full, Report)
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
        assert ahead is Answer.UNDETERMINED
        assert full.answer is Answer.UNDETERMINED


def test_an_empty_file_has_no_plan_ahead_and_an_empty_plan_in_its_report() -> None:
    file = trip([], [], [], [], [])
    for series in SERIES.values():
        ahead, full = series(file)
        assert report.answer_as_json(ahead) == {"answer": "FEASIBLE", "unfinished": True}
        shape = report.as_json(file, full)
        assert shape["itinerary"] == []
        assert "unfinished" not in shape


@pytest.mark.parametrize("path", [WORKS, CANNOT_WORK, DEPENDS], ids=lambda path: path.stem)
@pytest.mark.parametrize("program", PROGRAMS)
def test_a_plain_check_asks_what_it_asked_before(program: str, path: Path) -> None:
    """The question that gives FEASIBLE ahead is asked only where the answer is wanted ahead."""
    file = read(path)
    ahead, plain = Asked(PROGRAMS[program]), Asked(PROGRAMS[program])
    _, full = ahead.reports(file)
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
    assert ahead is Answer(expected["answer"])
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
        ahead, full = the_two(answers.reports(file))
        assert the_two(compiler.reports(file)) == (ahead, full)
        assert ahead is full.answer
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


def test_an_answer_that_the_reference_checker_does_not_confirm_is_a_fault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The solver says that a trip works which cannot, and then its numbers stop fitting."""
    file = read(CANNOT_WORK)
    monkeypatch.setattr(compiler, "works", lambda *given, **named: True)  # type: ignore[misc]
    monkeypatch.setattr(compiler, "shown", does_not_fit)
    series = compiler.reports(file)
    assert next(series) is Answer.FEASIBLE
    with pytest.raises(AssertionError, match="the solver proved an answer that the rules refuse"):
        next(series)


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
    ahead, full = the_two(compiler.reports(file))
    assert ahead is Answer.FEASIBLE
    assert (full.answer, full.itinerary) == (Answer.FEASIBLE, ())


def test_an_answer_ahead_in_words() -> None:
    assert report.answer_as_text(Answer.FEASIBLE).splitlines() == [
        "FEASIBLE: this trip can work.",
        "",
        "The check is still choosing the plan to show. The report will say whether that plan is"
        " sure to hold, and what is still to buy.",
    ]
    assert report.answer_as_text(Answer.INFEASIBLE).splitlines() == [
        "INFEASIBLE: this trip cannot work.",
        "",
        "The check is still working out which FACTs, WANTs and DECISIONs rule out every plan, and"
        " whether they do so only with the BUDGETs of this FILE.",
    ]
    assert report.answer_as_text(Answer.UNDETERMINED).splitlines() == [
        "UNDETERMINED: the FILE does not say enough to tell.",
        "",
        "The check is still working out which missing FACTs would be enough.",
    ]


def test_an_answer_ahead_holds_no_plan_at_all() -> None:
    """Sam is LOCKed into a museum visit. An empty plan would say that nobody has to do anything."""
    file = trip(
        ["sam"],
        ["museum"],
        [stays("visit", "museum")],
        [starts_at("visit", 10), lasts("visit", "PT2H"), cutoff("visit", "PT0S")],
        [lock("visit", "sam")],
    )
    for series in SERIES.values():
        ahead, full = series(file)
        assert ahead is Answer.FEASIBLE
        assert not hasattr(ahead, "itinerary")
        assert report.answer_as_json(ahead) == {"answer": "FEASIBLE", "unfinished": True}
        assert [step.option for step in full.itinerary] == ["visit"]


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
    answer = Answer(json.loads(path.with_name(path.stem + ".expected.json").read_text())["answer"])
    main(["check", str(path), "--answer-first"])
    ahead = report.answer_as_text(answer)
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


PLAIN = "import sys; from agloe.cli import main; sys.exit(main(sys.argv[1:]))"

# The command, with a search for the plan to show that waits for a line on its input.
HELD = """
import sys

from agloe import compiler
from agloe.cli import main

shown = compiler.shown


def held(file, world):
    sys.stdin.readline()
    return shown(file, world)


compiler.shown = held
sys.exit(main(sys.argv[1:]))
"""


def started(program: str, *arguments: str, **environment: str) -> subprocess.Popen[str]:
    """The command as a process of its own, with pipes for what it reads and writes."""
    return subprocess.Popen(
        [sys.executable, "-c", program, *arguments],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, **environment},
    )


def first_line(command: subprocess.Popen[str]) -> str:
    """The first line the command writes out, while its search waits."""
    assert command.stdout is not None
    ready, _, _ = select.select([command.stdout], [], [], 60)
    assert ready, "nothing was written out before the search went on"
    return command.stdout.readline()


def test_the_answer_comes_through_a_pipe_while_the_search_waits() -> None:
    command = started(HELD, "check", str(WORKS), "--json", "--answer-first")
    assert first_line(command) == '{"answer": "FEASIBLE", "unfinished": true}\n'
    rest, problems = command.communicate(timeout=60)
    assert json.loads(rest) == json.loads(WORKS.with_name("works.expected.json").read_text())
    assert (command.returncode, problems) == (0, "")


def test_a_reader_that_leaves_after_the_answer_gets_no_report() -> None:
    """The command ends with 2, and with no complaint: nobody is there to read one."""
    command = started(HELD, "check", str(WORKS), "--json", "--answer-first")
    assert first_line(command) == '{"answer": "FEASIBLE", "unfinished": true}\n'
    assert command.stdout is not None
    assert command.stdin is not None
    assert command.stderr is not None
    command.stdout.close()
    command.stdin.close()
    assert command.wait(timeout=60) == 2
    assert command.stderr.read() == ""
    command.stderr.close()


def test_a_name_the_output_cannot_write_ends_the_command_with_2(tmp_path: Path) -> None:
    """Ren\u00e9 stays at the hotel, and the output takes ASCII only.

    The answer holds no name, so it is written. The report in words is not, and the command
    says so. As JSON the report holds ids only.
    """
    document = {
        "persons": [{"id": "rene", "name": "Ren\u00e9"}],
        "places": [{"id": "hotel", "name": "Hotel"}],
        "options": [stays("night", "hotel")],
        "ways": [],
        "wants": [],
        "facts": [starts_at("night", 22), lasts("night", "PT8H"), needs_no_right("night")],
        "decisions": [lock("night", "rene")],
    }
    path = tmp_path / "trip.json"
    path.write_text(json.dumps(document))
    for flags, written in (
        (["--answer-first"], report.answer_as_text(Answer.FEASIBLE) + "\n"),
        ([], ""),
    ):
        command = started(PLAIN, "check", str(path), *flags, PYTHONIOENCODING="ascii")
        out, problems = command.communicate(timeout=60)
        assert out == written
        assert command.returncode == 2
        assert problems.startswith(f"{path}: the output could not be written: ")
        assert "Traceback" not in problems
