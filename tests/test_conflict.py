"""The search for a conflict: one yes-or-no question for each record, in the FILE's order."""

from random import Random
from typing import Any

import pytest
from ortools.sat.python import cp_model

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
    starts_from,
    stays,
    takes,
    trip,
    trip_ends,
    trip_starts,
    way,
    way_between,
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


def solves_counted(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, bool]]:
    """A list that gains an entry each time the solver is given a model.

    The entry says how hard the solver had to search, as the conflicts it met, and whether
    the model had something to make as small as possible.
    """
    solves: list[tuple[int, bool]] = []
    solve = cp_model.CpSolver.solve

    def counted(self: cp_model.CpSolver, model: cp_model.CpModel) -> object:
        status = solve(self, model)
        solves.append((self.num_conflicts, model.has_objective()))
        return status

    monkeypatch.setattr(cp_model.CpSolver, "solve", counted)
    return solves


def searched(solves: list[tuple[int, bool]]) -> int:
    return sum(conflicts for conflicts, _ in solves)


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


def test_two_talks_at_the_same_hour_are_seen_to_clash_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sam is LOCKed into twelve talks at one PLACE, and the last two both start at noon.

    The other times go one by one, and each time the two talks at noon still clash. The
    model of a plain question says outright that no two OPTIONs of a PERSON overlap, so the
    solver sees that with next to no search, however many talks could come between the two.
    """
    names = [f"talk-{number}" for number in range(12)]
    facts: list[Document] = []
    for number, name in enumerate(names[:10]):
        facts += [starts_at(name, 7 + number // 2, 30 * (number % 2)), lasts(name, "PT25M")]
    for name in names[10:]:
        facts += [starts_at(name, 12), lasts(name, "PT25M")]
    locks = [lock(name, "sam") for name in names]
    file = trip(["sam"], ["center"], [stays(name, "center") for name in names], facts, locks)
    solves = solves_counted(monkeypatch)
    found = compiler.check(file)
    late = ("talk-10", "talk-11")
    assert found.conflict == (
        *(f"{name}-{what}" for name in late for what in ("time", "length")),
        *(f"lock-{name}" for name in late),
    )
    assert searched(solves) < 10_000


def test_a_talk_of_no_length_cannot_start_inside_another(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sam is LOCKed into nine talks in one hall. The last starts ten minutes into the eighth.

    With the FACT about its length taken out, the last talk takes no time in the best case.
    It still cannot start inside the eighth, and the solver sees that with little search.
    """
    names = [f"talk-{number}" for number in range(9)]
    facts: list[Document] = []
    for number, name in enumerate(names[:8]):
        minutes = 40 * number
        facts += [starts_at(name, 9 + minutes // 60, minutes % 60), lasts(name, "PT25M")]
    facts += [starts_at("talk-8", 13, 50), lasts("talk-8", "PT25M")]
    locks = [lock(name, "sam") for name in names]
    file = trip(["sam"], ["hall"], [stays(name, "hall") for name in names], facts, locks)
    solves = solves_counted(monkeypatch)
    found = compiler.check(file)
    assert found.conflict == (
        "talk-7-time",
        "talk-7-length",
        "talk-8-time",
        "lock-talk-7",
        "lock-talk-8",
    )
    assert searched(solves) < 10_000
    left = Remaining(file).without("talk-8-length")
    assert not compiler.can_work(left) and not reference.can_work(left)


def test_the_plan_for_workshops_that_overlap_is_chosen_with_little_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Six colleagues each need three topics, and each topic has two workshops that overlap.

    The model that looks for the plan to show does not say outright that no two OPTIONs of a
    PERSON overlap. With that in it, the solver met eighty times as many conflicts here.
    """
    people = [f"colleague-{number}" for number in range(6)]
    options: list[Document] = []
    facts: list[Document] = []
    wants: list[Document] = []
    for topic in range(3):
        wants.append(must(f"topic-{topic}", *people))
        facts.append(every(f"topic-{topic}"))
        for which in range(2):
            name = f"workshop-{topic}-{which}"
            options.append(stays(name, "venue"))
            facts += [starts_at(name, 9 + 3 * topic, 30 * which), lasts(name, "PT1H30M")]
            facts.append(satisfies(name, f"topic-{topic}"))
    file = trip(people, ["venue"], options, facts, [], wants=wants)
    solves = solves_counted(monkeypatch)
    found = compiler.check(file)
    assert found.answer is Answer.FEASIBLE
    assert searched(solves) < 30_000


def test_one_check_asks_the_solver_once_about_one_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sam is LOCKed into one stay, and nobody knows whether it needs a right.

    The search for a conflict and the search for missing FACTs both ask whether anything
    works in the best case. The solver answers that once.
    """
    facts = [starts_at("stay", 9), lasts("stay", "PT25M")]
    file = trip(["sam"], ["a"], [stays("stay", "a")], facts, [lock("stay", "sam")], tickets=True)
    solves = solves_counted(monkeypatch)
    found = compiler.check(file)
    assert found.answer is Answer.UNDETERMINED
    assert [aims for _, aims in solves if not aims] == [False]


def test_an_answer_kept_for_one_model_is_read_with_the_routes_of_each_question() -> None:
    """Sam starts at the depot and must end the TRIP at two PLACEs. A bus goes to one, a ferry
    to the other.

    Without either WANT the model has the same text: one WAY to where Sam has to end. So
    the solver is asked once, and the plan for each question names its own WAY.
    """
    ways = [way("bus", "depot", "a"), way("ferry", "depot", "b")]
    facts = [starts_from("sam", "depot"), takes("bus", "PT10M"), takes("ferry", "PT10M")]
    facts += [starts_at("wait", 9), lasts("wait", "PT5M")]
    wants = [ends_at("a", "sam", id="end-at-a"), ends_at("b", "sam", id="end-at-b")]
    options = [stays("wait", "depot")]
    file = trip(["sam"], ["depot", "a", "b"], options, facts, [lock("wait", "sam")], ways, wants)
    found = compiler.check(file)
    assert found.conflict == ("end-at-a", "end-at-b")
    assert found == check(file)
    plans = [
        compiler.shown(left.file, reference.best_case_left(left)[0])
        for left in (Remaining(file).without(want) for want in found.conflict)
    ]
    assert [[step.way for step in plan or () if step.way] for plan in plans] == [["ferry"], ["bus"]]


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


# ------------------------------- Two LOCKed OPTIONs at once ------------------------------------


def a_busy_day(rng: Random) -> File:
    """One or two PERSONs, and stays at one or two PLACEs on a half-hour grid, mostly LOCKed.

    A stay lasts no time, half an hour or an hour, or nobody knows how long. Some stays have
    no stated start.
    """
    people = ["alex", "sam"][: rng.choice([1, 2])]
    places = ["a", "b"][: rng.choice([1, 2])]
    names = [f"stay-{number}" for number in range(rng.choice([2, 3, 4]))]
    options = [stays(name, rng.choice(places)) for name in names]
    facts: list[Document] = []
    for name in names:
        if rng.random() < 0.85:
            facts.append(starts_at(name, 9 + rng.randrange(3), rng.choice([0, 30])))
        if rng.random() < 0.85:
            facts.append(lasts(name, rng.choice(["PT0S", "PT30M", "PT1H"])))
    ways = [way_between("walk", "a", "b")] if len(places) == 2 else []
    facts += [takes("walk", "PT10M")] if ways and rng.random() < 0.8 else []
    locks = [
        lock(name, *[person for person in people if rng.random() < 0.8] or people[:1])
        for name in names
        if rng.random() < 0.8
    ]
    # A second LOCK for an OPTION that has one already, perhaps for the same PERSON.
    again = [
        {**lock(each["lock"], rng.choice(people)), "id": f"{each['id']}-again"}
        for each in locks
        if rng.random() < 0.3
    ]
    return trip(people, places, options, facts, [*locks, *again], ways=ways)


def test_two_locked_options_at_once_rule_out_every_plan() -> None:
    """Where the solver sees a PERSON LOCKed twice at once, the reference checker finds no plan."""
    rng = Random(9090)
    seen = 0
    twice = compiler._locked_twice_at_once  # pyright: ignore[reportPrivateUsage]
    for _ in range(400):
        file = a_busy_day(rng)
        for world in (reference.worst_case(file), reference.best_case(file)):
            if twice(file, world):
                seen += 1
                assert not reference.any_works(file, world)
    assert seen > 100


def test_two_talks_at_noon_are_ruled_out_with_no_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sam is LOCKed into two talks of half an hour that both start at noon."""
    facts: list[Document] = []
    for name in ("first", "second"):
        facts += [starts_at(name, 12), lasts(name, "PT30M")]
    options = [stays("first", "hall"), stays("second", "hall")]
    locks = [lock("first", "sam"), lock("second", "sam")]
    file = trip(["sam"], ["hall"], options, facts, locks)
    built = 0
    search = compiler._Search  # pyright: ignore[reportPrivateUsage]
    build = search.__init__

    def counted(self: object, *given: Any, **named: Any) -> None:
        nonlocal built
        built += 1
        build(self, *given, **named)  # pyright: ignore[reportArgumentType]

    monkeypatch.setattr(search, "__init__", counted)
    world = reference.worst_case(file)
    assert compiler.shown(file, world) is None
    assert not compiler.works(file, world)
    assert not compiler.can_work(Remaining(file))
    assert built == 0


def test_two_locks_for_one_option_are_one_option() -> None:
    """Sam is LOCKed into lunch twice, once alone and once with Alex. One lunch honors both."""
    facts = [starts_at("lunch", 12), lasts("lunch", "PT30M")]
    locks = [lock("lunch", "sam"), {**lock("lunch", "sam", "alex"), "id": "lock-lunch-for-both"}]
    file = trip(["sam", "alex"], ["cafe"], [stays("lunch", "cafe")], facts, locks)
    twice = compiler._locked_twice_at_once  # pyright: ignore[reportPrivateUsage]
    assert not twice(file, reference.worst_case(file))
    found = compiler.check(file)
    assert (found.answer, found.robust) == (Answer.FEASIBLE, True)
    assert found == check(file)


def test_seeing_a_person_locked_twice_at_once_changes_no_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The solver's search gives the same report without that look, and so does the reference."""
    rng = Random(9191)
    files = [a_busy_day(rng) for _ in range(300)]
    found = [compiler.check(file) for file in files]

    def never(*_: object) -> bool:
        return False

    monkeypatch.setattr(compiler, "_locked_twice_at_once", never)
    seen: set[Answer] = set()
    for file, with_the_look in zip(files, found, strict=True):
        assert compiler.check(file) == with_the_look
        assert check(file) == with_the_look
        seen.add(with_the_look.answer)
    assert seen == set(Answer)


def test_a_double_booking_among_many_sailings_needs_few_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Six travelers have breakfast until 08:45 and are LOCKed onto the sailing at 08:30.

    The FILE lists 24 sailings. While both LOCKs and their times are there, no model is
    built: the two cannot both be done. The solver is asked only once one of them is gone.
    """
    people = [f"traveler-{number}" for number in range(6)]
    options = [stays("breakfast", "port")]
    facts: list[Document] = [starts_at("breakfast", 8), lasts("breakfast", "PT45M")]
    for number in range(24):
        name = f"sailing-{number}"
        options.append(moves(name, "port", "island"))
        minutes = min(8 * 60 + 30 * number, 23 * 60 + 59)
        facts += [starts_at(name, minutes // 60, minutes % 60), lasts(name, "PT20M")]
    decisions = [lock("breakfast", *people), lock("sailing-1", *people)]
    file = trip(people, ["port", "island"], options, facts, decisions)
    built = 0
    search = compiler._Search  # pyright: ignore[reportPrivateUsage]
    build = search.__init__

    def counted(self: object, *given: Any, **named: Any) -> None:
        nonlocal built
        built += 1
        build(self, *given, **named)  # pyright: ignore[reportArgumentType]

    monkeypatch.setattr(search, "__init__", counted)
    found = compiler.check(file)
    assert found.conflict == (
        "breakfast-time",
        "breakfast-length",
        "sailing-1-time",
        "lock-breakfast",
        "lock-sailing-1",
    )
    assert built <= len(found.conflict)
