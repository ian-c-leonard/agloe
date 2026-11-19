"""The search for a conflict: yes-or-no questions, one record or a block of records at a time."""

from random import Random

from agloe import answers, compiler, reference
from agloe.answers import Answer, check
from agloe.file import File
from agloe.reference import Remaining
from tests.stories import (
    Document,
    cap,
    ends_at,
    every,
    lasts,
    lock,
    must,
    satisfies,
    starts_at,
    stays,
    trip,
    trip_ends,
    trip_starts,
)
from tests.test_cross_check import random_trip


def records_of(file: File) -> int:
    return len(file.facts) + len(file.wants) + len(file.decisions)


def a_random_trip(seed: int) -> File:
    rng = Random(seed)
    kind = seed % 5
    if kind == 0:
        return random_trip(rng, 0.3, contingent=0.3, with_complete=0.4, with_ways=0.9)
    if kind == 1:
        both = ["alex", "sam"]
        return random_trip(rng, 0.3, both, with_wants=0.8, must_nots=0.4, whole_sets=0.5)
    if kind == 2:
        return random_trip(rng, 0.4, with_ways=0.9, with_ends=0.6, with_times=0.5)
    if kind == 3:
        return random_trip(rng, 0.5, ["alex", "sam"], count=3, with_wants=0.6, with_ways=0.5)
    return random_trip(rng, 0.2, ["alex", "sam"], with_rights=0.9, with_wants=0.5, whole_sets=0.5)


def test_a_block_at_a_time_gives_the_report_that_one_record_at_a_time_gives() -> None:
    """On random trips that cannot work, the two ways to take records out leave the same set."""
    seen = 0
    for seed in range(500):
        file = a_random_trip(seed)
        found = check(file)
        if found.answer is Answer.INFEASIBLE:
            seen += 1
            assert check(file, in_blocks=True) == found, seed
    assert seen > 40


def test_where_three_wants_clash_two_by_two_the_first_one_goes() -> None:
    """Sam must end the TRIP at three PLACEs. Any two of those WANTs conflict.

    The first can go, because the other two still conflict. Then neither of those can.
    """
    wants = [ends_at(place, "sam", id=f"end-at-{place}") for place in ("a", "b", "c")]
    file = trip(["sam"], ["a", "b", "c"], [], [], [], wants=wants)
    for in_blocks in (False, True):
        found = check(file, in_blocks=in_blocks)
        assert found.answer is Answer.INFEASIBLE
        assert found.conflict == ("end-at-b", "end-at-c")
    assert compiler.check(file) == check(file)


def counting(can_work: answers.CanWork) -> tuple[answers.CanWork, list[Remaining]]:
    """The same question, with a list of what it was asked about."""
    asked: list[Remaining] = []

    def counted(remaining: Remaining) -> bool:
        asked.append(remaining)
        return can_work(remaining)

    return counted, asked


def test_a_few_records_that_conflict_among_many_take_few_questions() -> None:
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
    found = check(file, compiler.shown, compiler.works, counted, in_blocks=True)
    assert found.conflict == ("call-time", "call-length", "nap-time", "lock-call", "lock-nap")
    assert len(asked) < 98 / 2
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


def test_the_solver_answers_one_question_with_one_model_however_many_pairs_are_open() -> None:
    """Eleven FACTs about the WANT can go at once, which leaves 2,048 best cases.

    The reference checker tries each of them. The solver chooses the best case with the plan.
    """
    small = a_want_held_both_ways(4)
    assert compiler.check(small) == check(small)
    assert check(small).conflict == ("end-at-a", "end-at-b")

    file = a_want_held_both_ways(11)
    counted, asked = counting(compiler.can_work)
    found = check(file, compiler.shown, compiler.works, counted, in_blocks=True)
    assert found.conflict == ("end-at-a", "end-at-b")
    assert max(len(reference.best_case_left(left)[1]) for left in asked) == 11
    assert len(asked) < 20


def test_the_reference_checker_takes_one_record_at_a_time() -> None:
    """Sam is LOCKed into seven stays that do not fit the TRIP, and a cap is on his BUDGET.

    Without the times of the stays, each order of the seven is a plan to try. The reference
    checker asks about one record at a time, so it never asks with all the times gone.
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
    gone = [records_of(file) - records_of(left.file) for left in asked]
    assert max(gone) <= records_of(file) - len(found.conflict) + 1
    assert compiler.check(file) == found
