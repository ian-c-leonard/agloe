"""The search for a conflict: yes-or-no questions, a block of records at a time."""

from random import Random

from agloe import compiler
from agloe.answers import Answer, check
from agloe.file import File
from agloe.reference import Remaining, World
from tests.stories import Document, ends_at, lasts, lock, starts_at, stays, trip
from tests.test_cross_check import random_trip
from tests.test_where_a_path_ends import ruled_out


def one_record_at_a_time(file: File) -> tuple[str, ...]:
    """The records left once each one that the TRIP stays INFEASIBLE without is taken out."""
    kept = Remaining(file)
    stays: list[str] = []
    for record in (*file.facts, *file.wants, *file.decisions):
        smaller = kept.without(record.id)
        if ruled_out(smaller):
            kept = smaller
        else:
            stays.append(record.id)
    return tuple(stays)


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


def test_a_block_at_a_time_names_the_conflict_that_one_record_at_a_time_names() -> None:
    """On random trips that cannot work, the two ways to take records out leave the same set."""
    seen = 0
    for seed in range(500):
        file = a_random_trip(seed)
        found = check(file)
        if found.answer is Answer.INFEASIBLE:
            seen += 1
            assert found.conflict == one_record_at_a_time(file), seed
    assert seen > 40


def test_where_three_wants_clash_two_by_two_the_first_one_goes() -> None:
    """Sam must end the TRIP at three PLACEs. Any two of those WANTs conflict.

    The first can go, because the other two still conflict. Then neither of those can.
    """
    wants = [ends_at(place, "sam", id=f"end-at-{place}") for place in ("a", "b", "c")]
    file = trip(["sam"], ["a", "b", "c"], [], [], [], wants=wants)
    found = check(file)
    assert found.answer is Answer.INFEASIBLE
    assert found.conflict == ("end-at-b", "end-at-c")
    assert found.conflict == one_record_at_a_time(file)


def test_a_few_records_that_conflict_among_many_take_few_questions() -> None:
    """Sam is LOCKed into a call and a nap that overlap. Thirty other stays are in nobody's way.

    The FILE has 98 records, and five of them conflict. The solver answers the questions:
    the reference checker would try every choice of the thirty stays for each one.
    """
    names = ["call", "nap", *(f"stay-{number}" for number in range(30))]
    facts: list[Document] = [starts_at("call", 9), lasts("call", "PT1H")]
    facts += [starts_at("nap", 9, 30), lasts("nap", "PT1H")]
    for number in range(30):
        facts += [starts_at(f"stay-{number}", 12 + number % 8), lasts(f"stay-{number}", "PT30M")]
    locks = [lock("call", "sam"), lock("nap", "sam")]
    file = trip(["sam"], ["hotel"], [stays(name, "hotel") for name in names], facts, locks)
    records = len(file.facts) + len(file.wants) + len(file.decisions)
    assert records == 98
    asked = 0

    def counted(left: File, world: World) -> bool:
        nonlocal asked
        asked += 1
        return compiler.works(left, world)

    found = check(file, compiler.shown, counted)
    assert found.conflict == ("call-time", "call-length", "nap-time", "lock-call", "lock-nap")
    assert asked < records / 2
