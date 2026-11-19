"""The search for a conflict: one yes-or-no question for each record, in the FILE's order."""

import pytest

from agloe import answers, compiler, reference
from agloe.answers import Answer, check
from agloe.file import File
from agloe.reference import Remaining
from tests.stories import (
    Document,
    any_time,
    cap,
    ends_at,
    every,
    lasts,
    lock,
    moves,
    must,
    satisfies,
    starts_at,
    stays,
    trip,
    trip_ends,
    trip_starts,
)


def records_of(file: File) -> int:
    return len(file.facts) + len(file.wants) + len(file.decisions)


def counting(can_work: answers.CanWork) -> tuple[answers.CanWork, list[Remaining]]:
    """The same question, with a list of what it was asked about."""
    asked: list[Remaining] = []

    def counted(remaining: Remaining) -> bool:
        asked.append(remaining)
        return can_work(remaining)

    return counted, asked


def by_the_solver(file: File, can_work: answers.CanWork = compiler.can_work) -> answers.Report:
    """The Report with the solver's search for every part."""
    return check(file, compiler.shown, compiler.works, can_work)


def test_where_three_wants_clash_two_by_two_the_first_one_goes() -> None:
    """Sam must end the TRIP at three PLACEs. Any two of those WANTs conflict.

    The first can go, because the other two still conflict. Then neither of those can.
    """
    wants = [ends_at(place, "sam", id=f"end-at-{place}") for place in ("a", "b", "c")]
    file = trip(["sam"], ["a", "b", "c"], [], [], [], wants=wants)
    found = check(file)
    assert found.answer is Answer.INFEASIBLE
    assert found.conflict == ("end-at-b", "end-at-c")
    assert by_the_solver(file) == found


def test_each_record_takes_one_question() -> None:
    """Sam is LOCKed into a call and a nap that overlap. Thirty other stays are in nobody's way.

    The FILE has 98 records, and five of them conflict. The solver answers the questions.
    With the reference checker's search this test does not end in six minutes.
    """
    names = ["call", "nap", *(f"stay-{number}" for number in range(30))]
    facts: list[Document] = [starts_at("call", 9), lasts("call", "PT1H")]
    facts += [starts_at("nap", 9, 30), lasts("nap", "PT1H")]
    for number in range(30):
        facts += [starts_at(f"stay-{number}", 12 + number % 8), lasts(f"stay-{number}", "PT30M")]
    locks = [lock("call", "sam"), lock("nap", "sam")]
    file = trip(["sam"], ["hotel"], [stays(name, "hotel") for name in names], facts, locks)
    assert records_of(file) == 98
    counted, asked = counting(compiler.can_work)
    found = by_the_solver(file, counted)
    assert found.conflict == ("call-time", "call-length", "nap-time", "lock-call", "lock-nap")
    # One for the whole FILE, and one for each record. No OFFER has a price, so none for BUDGETs.
    assert len(asked) == 98 + 1
    assert found == compiler.check(file)


def a_want_held_both_ways(count: int) -> File:
    """Some stays SATISFY a WANT that Alex must have and Sam must not, and the set is COMPLETE.

    Sam must also end the TRIP at two PLACEs, and those two WANTs are the whole conflict. A
    FACT about a stay that is taken out leaves it open whether the stay SATISFIES the WANT.
    """
    names = [f"stay-{number}" for number in range(count)]
    facts = [satisfies(name, "spice") for name in names]
    facts.append(every("spice"))
    wants = [must("spice", "alex", never=["sam"])]
    wants += [ends_at("a", "sam", id="end-at-a"), ends_at("b", "sam", id="end-at-b")]
    options = [stays(name, "a") for name in names]
    return trip(["alex", "sam"], ["a", "b"], options, facts, [], wants=wants, tickets=True)


def solves_counted(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """A list that gains one entry each time the solver is asked."""
    solves: list[int] = []
    search = compiler._Search  # pyright: ignore[reportPrivateUsage]
    solve = search._solve  # pyright: ignore[reportPrivateUsage]

    def counted(self: object, relax: bool = True) -> object:
        solves.append(1)
        return solve(self, relax)  # pyright: ignore[reportArgumentType]

    monkeypatch.setattr(search, "_solve", counted)
    return solves


def test_the_solver_answers_one_question_with_one_solve_however_many_pairs_are_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Eleven FACTs about the WANT go one after another, which leaves 2,048 best cases.

    The reference checker tries each of them. The solver chooses the best case with the plan.
    """
    small = a_want_held_both_ways(4)
    assert by_the_solver(small) == check(small)
    assert check(small).conflict == ("end-at-a", "end-at-b")

    file = a_want_held_both_ways(11)
    solves = solves_counted(monkeypatch)
    each: list[int] = []
    open_pairs: list[int] = []

    def counted(left: Remaining) -> bool:
        before = len(solves)
        answer = compiler.can_work(left)
        each.append(len(solves) - before)
        open_pairs.append(len(reference.best_case_left(left)[1]))
        return answer

    found = by_the_solver(file, counted)
    assert found.conflict == ("end-at-a", "end-at-b")
    assert max(open_pairs) == 11
    assert set(each) == {1}


def test_a_fact_that_says_what_the_best_case_takes_anyway_costs_no_second_solve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sam is LOCKed into eight stays of a minute, and the TRIP lasts seven minutes.

    Six FACTs say that a stay can start at any time. The best case takes that anyway, so the
    model without each of them is the model with it, and the solver is not asked again.
    """
    names = [f"stay-{number}" for number in range(8)]
    facts = [any_time(name) for name in names[:6]] + [lasts(name, "PT1M") for name in names]
    decisions = [trip_starts(10), trip_ends(10, 7), *(lock(name, "sam") for name in names)]
    options = [stays(name, "a") for name in names]
    file = trip(["sam"], ["a"], options, facts, decisions, tickets=True)
    solves = solves_counted(monkeypatch)
    found = compiler.check(file)
    assert found.answer is Answer.INFEASIBLE
    assert not any(record.endswith("-time") for record in found.conflict)
    # One solve for the plan in the worst case and one for the whole FILE. Then at most one
    # for each record, less the six that leave the model as it was.
    assert len(solves) <= 2 + records_of(file) - 6


def test_the_reference_checker_never_asks_with_all_the_times_gone() -> None:
    """Sam is LOCKed into seven stays that do not fit the TRIP, and a cap is on his BUDGET.

    Without the times of the stays, each order of the seven is a plan to try. One record
    goes at a time, and a time that the conflict needs stays, so few are ever out at once.
    """
    names = [f"stay-{number}" for number in range(7)]
    facts: list[Document] = [
        starts_at(name, 10, 1 + 2 * number) for number, name in enumerate(names[:6])
    ]
    facts.append(lasts("stay-6", "PT3M"))
    decisions = [trip_starts(10), trip_ends(10, 12), *(lock(name, "sam") for name in names)]
    decisions.append(cap("money", "0 USD"))
    file = trip(["sam"], ["a"], [stays(name, "a") for name in names], facts, decisions)
    counted, asked = counting(reference.can_work)
    found = check(file, can_work=counted)
    assert found.answer is Answer.INFEASIBLE
    assert len(asked) == records_of(file) + 1
    times_gone = [sum(left.file.start(name) is None for name in names[:6]) for left in asked]
    assert max(times_gone) <= 1
    assert compiler.check(file) == found


def test_rides_that_two_persons_are_locked_into_are_asked_about_one_lock_at_a_time() -> None:
    """Alex and Sam are LOCKed into eighteen rides to and fro, and Sam must end at both PLACEs.

    The two WANTs are the conflict. With them there, nothing works whatever else is left, so
    no question about a LOCK has to find a plan for the rides.
    """
    rides = [moves(f"ride-{number}", *("ab" if number % 2 == 0 else "ba")) for number in range(18)]
    wants = [ends_at("a", "sam", id="end-at-a"), ends_at("b", "sam", id="end-at-b")]
    locks = [lock(ride["id"], "alex", "sam") for ride in reversed(rides)]
    file = trip(["alex", "sam"], ["a", "b"], rides, [], locks, wants=wants, tickets=True)
    counted, asked = counting(compiler.can_work)
    found = by_the_solver(file, counted)
    assert found.conflict == ("end-at-a", "end-at-b")
    could = [left for left in asked if compiler.can_work(left)]
    assert len(could) == 2
    assert all(len(left.file.locks) == 18 for left in could)
