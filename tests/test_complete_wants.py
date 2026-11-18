"""A COMPLETE set for a WANT: the FILE states every OPTION that SATISFIES the WANT."""

from itertools import combinations
from random import Random

import pytest

from agloe import answers, compiler, report
from agloe.answers import Answer, Missing, Report
from agloe.file import CompleteFor, File, FileError, load
from agloe.reference import (
    Broken,
    Constraint,
    Itinerary,
    Remaining,
    Step,
    Unknown,
    best_case,
    best_cases,
    broken,
    in_world,
    itineraries,
    needless,
    one_way_each,
    unknowns,
    with_these_at_best,
    worst_case,
)
from tests.stories import (
    Document,
    cutoff,
    every,
    flight_home,
    lasts,
    lock,
    must,
    must_not,
    satisfies,
    seconds,
    starts_at,
    stays,
    trip,
)
from tests.test_cross_check import any_choice, possible_world, random_trip, works_on_the_grid


def at_seven(option: str, minutes: int = 60) -> list[Document]:
    return [starts_at(option, 19), lasts(option, f"PT{minutes}M"), cutoff(option, "PT0S")]


def an_evening(*more: Document, wants: list[Document], locks: list[Document]) -> File:
    """Three OPTIONs in one PLACE at 7:00 pm: a pizzeria, a tavern and a show.

    A FACT says the pizzeria SATISFIES deep-dish pizza. The FILE says nothing about the tavern
    and the show.
    """
    options = [stays(id, "river-north") for id in ("pizzeria", "tavern", "show")]
    facts = [*at_seven("pizzeria"), *at_seven("tavern"), *at_seven("show")]
    facts += [satisfies("pizzeria", "deep-dish", 8), *more]
    return trip(["alex", "sam"], ["river-north"], options, facts, locks, wants=wants)


def dinner(option: str, *persons: str) -> Step:
    return Step(option, "river-north", "river-north", persons, seconds(19), seconds(20))


def checked(file: File) -> Report:
    """The reference checker's Report, once the COMPILER has given the same one."""
    found = answers.check(file)
    assert compiler.check(file) == found
    return found


def cannot_work(left: Remaining) -> bool:
    """Whether nothing works in any best case of what is left of a FILE, by trying everything."""
    return not any(itineraries(left.file, world) for world in best_cases(left))


def test_the_file_can_say_that_a_wants_set_is_complete() -> None:
    document = flight_home()
    document["wants"] = [must("window-seat", "alex")]
    document["facts"] += [satisfies("flight", "window-seat", 7), every("window-seat")]
    file = load(document)
    assert file.complete_for("window-seat") == CompleteFor("every-window-seat", "window-seat")
    assert file.says("flight", "window-seat") is True
    assert file.says("blue-line", "window-seat") is False


def test_without_that_fact_nobody_knows_about_an_option_with_no_fact() -> None:
    document = flight_home()
    document["wants"] = [must("window-seat", "alex")]
    document["facts"].append(satisfies("flight", "window-seat", 0))
    file = load(document)
    assert file.complete_for("window-seat") is None
    assert file.says("flight", "window-seat") is False
    assert file.says("blue-line", "window-seat") is None


def problems(document: Document) -> str:
    with pytest.raises(FileError) as refused:
        load(document)
    return str(refused.value)


def test_a_complete_set_names_a_want_of_the_file() -> None:
    document = flight_home()
    document["facts"].append(every("window-seat"))
    last = len(document["facts"]) - 1
    assert problems(document) == f"/facts/{last}: window-seat is not a WANT in this FILE"


def test_a_want_has_one_fact_that_its_set_is_complete() -> None:
    document = flight_home()
    document["wants"] = [must("window-seat", "alex")]
    again = every("window-seat")
    again["id"] = "every-window-seat-again"
    document["facts"] += [every("window-seat"), again]
    last = len(document["facts"]) - 1
    assert (
        problems(document) == f"/facts/{last}: another FACT already states this about window-seat"
    )


def test_nothing_about_a_complete_want_is_unknown() -> None:
    wants = [must("deep-dish", "alex", never=["sam"])]
    open_set = an_evening(wants=wants, locks=[])
    assert {unknown.what for unknown in unknowns(open_set)} == {
        "satisfies",
        "does not satisfy",
        "another option",
    }
    whole = an_evening(every("deep-dish"), wants=wants, locks=[])
    assert unknowns(whole) == ()
    assert best_case(whole).another_option == frozenset()
    assert list(best_cases(Remaining(whole))) == [best_case(whole)]


def test_an_option_with_no_fact_about_a_complete_want_breaks_no_must_not() -> None:
    wants = [must_not("deep-dish", "sam")]
    at_the_tavern: Itinerary = (dinner("tavern", "sam"),)
    open_set = an_evening(wants=wants, locks=[])
    assert broken(open_set, worst_case(open_set), at_the_tavern) == [
        Broken(Constraint.MUST_NOT, "tavern", ("sam",), want="deep-dish")
    ]
    whole = an_evening(every("deep-dish"), wants=wants, locks=[])
    assert broken(whole, worst_case(whole), at_the_tavern) == []


def test_an_option_with_no_fact_about_a_complete_want_meets_no_must_in_any_case() -> None:
    whole = an_evening(every("deep-dish"), wants=[must("deep-dish", "alex")], locks=[])
    unmet = Broken(Constraint.MUST, None, ("alex",), want="deep-dish")
    for world in (worst_case(whole), best_case(whole)):
        assert broken(whole, world, (dinner("tavern", "alex"),)) == [unmet]
        assert broken(whole, world, ()) == [unmet]
        assert broken(whole, world, (dinner("pizzeria", "alex"),)) == []


def test_a_must_can_make_a_trip_infeasible_where_the_set_is_complete() -> None:
    """Alex is LOCKed for the show while the pizzeria serves. Nothing else SATISFIES the WANT."""
    wants = [must("deep-dish", "alex")]
    locks = [lock("show", "alex")]
    open_set = checked(an_evening(wants=wants, locks=locks))
    assert open_set.answer is Answer.UNDETERMINED
    whole = checked(an_evening(every("deep-dish"), wants=wants, locks=locks))
    assert whole.answer is Answer.INFEASIBLE
    assert whole.conflict == (
        "pizzeria-time",
        "pizzeria-length",
        "show-time",
        "show-length",
        "every-deep-dish",
        "deep-dish",
        "lock-show",
    )


def test_a_must_with_nothing_listed_for_it_is_infeasible_where_the_set_is_complete() -> None:
    file = trip(["alex"], [], [], [every("deep-dish")], [], wants=[must("deep-dish", "alex")])
    found = checked(file)
    assert found.answer is Answer.INFEASIBLE
    assert found.conflict == ("every-deep-dish", "deep-dish")


def test_a_complete_set_ends_the_questions_about_options_with_no_fact() -> None:
    """Sam must not have deep-dish pizza and is LOCKed for the tavern."""
    wants = [must_not("deep-dish", "sam")]
    locks = [lock("tavern", "sam")]
    open_set = checked(an_evening(wants=wants, locks=locks))
    assert open_set.missing == (
        (Missing(Unknown("does not satisfy", "tavern", want="deep-dish"), None),),
    )
    file = an_evening(every("deep-dish"), wants=wants, locks=locks)
    whole = checked(file)
    assert whole.answer is Answer.FEASIBLE
    assert whole.relies_on == (
        "tavern-time",
        "tavern-length",
        "tavern-cutoff",
        "every-deep-dish",
        "tavern-open",
        "deep-dish",
        "lock-tavern",
    )
    assert needless(file, worst_case(file), whole.itinerary) == []


def test_a_fact_that_is_taken_out_is_unknown_even_where_the_set_is_complete() -> None:
    """Leaving a FACT out of a FILE and taking it out to look for a conflict are different."""
    wants = [must("deep-dish", "alex")]
    file = an_evening(
        satisfies("tavern", "deep-dish", 0), every("deep-dish"), wants=wants, locks=[]
    )
    assert file.says("tavern", "deep-dish") is False
    assert file.without("tavern-gives-deep-dish").says("tavern", "deep-dish") is False
    left = Remaining(file).without("tavern-gives-deep-dish")
    assert left.unsaid == {("tavern", "deep-dish")}
    assert left.reopened() == [("tavern", "deep-dish")]
    (best,) = best_cases(left)
    assert ("tavern", "deep-dish") in best.satisfies
    assert ("show", "deep-dish") not in best.might_satisfy
    assert left.without("every-deep-dish").reopened() == []
    assert Remaining(file).without("pizzeria-time").reopened() == []


def test_what_is_reopened_turns_out_the_way_that_helps() -> None:
    """A must wants it to SATISFY the WANT, a must-not wants it not to, and both get both."""
    more = [satisfies("tavern", "deep-dish", 0), every("deep-dish")]
    tavern = ("tavern", "deep-dish")
    for wants, expected in (
        ([must("deep-dish", "alex")], [True]),
        ([must_not("deep-dish", "alex")], [False]),
        ([must("deep-dish", "alex", never=["sam"])], [False, True]),
    ):
        left = Remaining(an_evening(*more, wants=wants, locks=[])).without("tavern-gives-deep-dish")
        assert [tavern in world.satisfies for world in best_cases(left)] == expected
        assert all(world.satisfies == world.might_satisfy for world in best_cases(left))


def test_a_conflict_keeps_a_fact_that_rules_an_option_out() -> None:
    """Alex is LOCKed for the show. A FACT says that the tavern does not SATISFY the WANT.

    Taking that FACT out would leave the tavern unknown, so it is part of the conflict, though
    the COMPLETE set rules out the same thing. The FACT that the pizzeria SATISFIES the WANT is
    no part of it: the pizzeria clashes with the show whether it does or not.
    """
    file = an_early_tavern()
    found = checked(file)
    assert found.answer is Answer.INFEASIBLE
    assert "tavern-gives-deep-dish" in found.conflict
    assert "pizzeria-gives-deep-dish" not in found.conflict
    assert "every-deep-dish" in found.conflict


def an_early_tavern() -> File:
    """The tavern at 5:00 pm, then the pizzeria and the show at 7:00 pm. The show is LOCKed.

    Deep-dish pizza is a must for Alex. The pizzeria SATISFIES it, the tavern does not, and the
    FILE says that the WANT's set is COMPLETE.
    """
    options = [stays(id, "river-north") for id in ("pizzeria", "tavern", "show")]
    facts = [
        *at_seven("pizzeria"),
        starts_at("tavern", 17),
        lasts("tavern", "PT1H"),
        cutoff("tavern", "PT0S"),
        *at_seven("show"),
        satisfies("pizzeria", "deep-dish", 8),
        satisfies("tavern", "deep-dish", 0),
        every("deep-dish"),
    ]
    wants = [must("deep-dish", "alex")]
    return trip(["alex"], ["river-north"], options, facts, [lock("show", "alex")], wants=wants)


def both_at_the_show(*more: Document) -> File:
    """Only the show is listed. Its set is COMPLETE for a WANT that Alex must have and Sam must not.

    Both are LOCKed for the show.
    """
    wants = [must("deep-dish", "alex", never=["sam"])]
    facts = [*at_seven("show"), *more, every("deep-dish")]
    options = [stays("show", "river-north")]
    locks = [lock("show", "alex", "sam")]
    return trip(["alex", "sam"], ["river-north"], options, facts, locks, wants=wants)


def test_a_conflict_is_exact_where_a_fact_about_a_want_held_both_ways_is_taken_out() -> None:
    """If the show SATISFIES the WANT, Sam breaks a must-not. If it does not, Alex's must is unmet.

    So the FACT about the show is no part of the conflict: the trip cannot work either way.
    """
    for degree in (6, 0):
        file = both_at_the_show(satisfies("show", "deep-dish", degree))
        found = checked(file)
        assert found.answer is Answer.INFEASIBLE
        assert found.conflict == ("every-deep-dish", "deep-dish", "lock-show")
        forgotten = Remaining(file).without("show-gives-deep-dish")
        assert len(list(best_cases(forgotten))) == 2
        assert cannot_work(forgotten)
        assert compiler.stuck(forgotten) is not None


def test_every_conflict_is_enough_and_has_no_record_to_spare() -> None:
    """Checked by trying everything, in every best case of the FILE with records taken out."""
    rng = Random(9090)
    with_a_whole_set = 0
    for _ in range(140):
        file = random_trip(
            rng, 0.15, ["alex", "sam"], count=2, with_wants=1, must_nots=0.4, whole_sets=0.7
        )
        found = checked(file)
        if found.answer is not Answer.INFEASIBLE:
            continue
        records = [*(fact.id for fact in file.facts), *(want.id for want in file.wants)]
        records += [each.id for each in file.locks]
        alone = Remaining(file)
        for record in records:
            if record not in found.conflict:
                alone = alone.without(record)
        assert cannot_work(alone)
        for record in found.conflict:
            assert not cannot_work(alone.without(record)), record
        with_a_whole_set += any(isinstance(fact, CompleteFor) for fact in file.facts)
    assert with_a_whole_set > 20


def test_the_report_puts_a_complete_set_for_a_want_in_words() -> None:
    file = trip(["alex"], [], [], [every("deep-dish")], [], wants=[must("deep-dish", "alex")])
    assert report.as_text(file, checked(file)).splitlines()[2:] == [
        "These FACTs and WANTs rule out every plan by themselves. Take any one away"
        " and they no longer do. A FACT that is taken away leaves what it said unknown."
        " Times are in UTC.",
        "  every-deep-dish: the FILE states every OPTION that SATISFIES deep-dish: there is none",
        "  deep-dish: deep-dish is a must for alex",
    ]


def test_a_conflict_is_one_of_perhaps_several() -> None:
    """Two musts, each with a COMPLETE set and nothing that SATISFIES it. Either rules the trip out.

    The report names one conflict. Its words claim only that these records rule out every plan
    by themselves, and that they no longer do with one taken away. The trip still cannot work.
    """
    facts = [every("pizza"), every("a-view")]
    wants = [must("pizza", "alex"), must("a-view", "alex")]
    file = trip(["alex"], [], [], facts, [], wants=wants)
    found = checked(file)
    assert found.conflict == ("every-a-view", "a-view")
    assert "rule out every plan by themselves" in report.as_text(file, found)
    still = Remaining(file).without("every-a-view")
    assert cannot_work(still)
    alone = Remaining(file).without("every-pizza").without("pizza")
    assert cannot_work(alone)
    assert not cannot_work(alone.without("every-a-view"))
    assert not cannot_work(alone.without("a-view"))


def test_a_complete_set_in_words_names_the_options_that_satisfy_the_want() -> None:
    """Alex is LOCKed for the show while both dinners that SATISFY the WANT are served."""
    wants = [must("deep-dish", "alex")]
    more = [satisfies("tavern", "deep-dish", 3), satisfies("show", "deep-dish", 0)]
    file = an_evening(*more, every("deep-dish"), wants=wants, locks=[lock("show", "alex")])
    found = checked(file)
    assert found.answer is Answer.INFEASIBLE
    assert (
        "  every-deep-dish: the FILE states every OPTION that SATISFIES deep-dish:"
        " pizzeria and tavern\n"
    ) in report.as_text(file, found)


def test_a_plan_relies_on_a_complete_set_only_where_it_needs_it() -> None:
    """Sam must not have deep-dish pizza. Nothing asks Sam to do anything.

    The empty plan works with or without the COMPLETE set, so it does not rely on it. Once Sam
    is LOCKed for the tavern, which has no FACT about the WANT, it does.
    """
    wants = [must_not("deep-dish", "sam")]
    idle = an_evening(every("deep-dish"), wants=wants, locks=[])
    assert checked(idle).relies_on == ("deep-dish",)
    at_the_pizzeria = an_evening(every("deep-dish"), wants=wants, locks=[lock("pizzeria", "alex")])
    assert "every-deep-dish" not in checked(at_the_pizzeria).relies_on
    at_the_tavern = an_evening(every("deep-dish"), wants=wants, locks=[lock("tavern", "sam")])
    assert "every-deep-dish" in checked(at_the_tavern).relies_on
    stated = an_evening(
        satisfies("tavern", "deep-dish", 0),
        every("deep-dish"),
        wants=wants,
        locks=[lock("tavern", "sam")],
    )
    assert "every-deep-dish" not in checked(stated).relies_on


def test_many_musts_with_complete_sets_do_not_slow_the_search_for_a_conflict() -> None:
    """One OPTION SATISFIES twenty WANTs, and nothing SATISFIES one more. All sets are COMPLETE.

    Only the last WANT and its COMPLETE set clash. Taking the other FACTs out reopens twenty
    questions, and none of them has to be tried both ways.
    """
    wants = [must(f"want-{number}", "alex") for number in range(21)]
    facts = [*at_seven("supper")]
    facts += [satisfies("supper", f"want-{number}", 5) for number in range(20)]
    facts += [every(f"want-{number}") for number in range(21)]
    file = trip(["alex"], ["loop"], [stays("supper", "loop")], facts, [], wants=wants)
    assert compiler.check(file).conflict == ("every-want-20", "want-20")
    left = Remaining(file)
    for number in range(20):
        left = left.without(f"supper-gives-want-{number}")
    assert len(left.reopened()) == 20
    assert len(list(best_cases(left))) == 1


def test_a_wrong_key_in_a_complete_set_is_named_alone() -> None:
    document = flight_home()
    document["wants"] = [must("window-seat", "alex")]
    odd = every("window-seat")
    odd["complete"]["note"] = 1
    document["facts"].append(odd)
    last = len(document["facts"]) - 1
    assert problems(document) == (
        f"/facts/{last}: fits no known shape; the closest miss:"
        " Additional properties are not allowed ('note' was unexpected)"
    )


def test_only_a_fact_is_told_to_choose_a_kind_of_complete_set() -> None:
    """An OPTION has no `complete` at all, so the reader says only that."""
    document = flight_home()
    document["options"][0]["complete"] = {"satisfies": "x", "from": "art-institute"}
    said = problems(document)
    assert said.startswith("/options/0: fits no known shape")
    assert "of one kind" not in said


def test_a_report_names_only_the_kinds_of_record_it_lists() -> None:
    file = trip(["alex"], [], [], [every("deep-dish")], [], wants=[must("deep-dish", "alex")])
    words = report.as_text(file, checked(file))
    assert "These FACTs and WANTs rule out every plan by themselves." in words
    assert "DECISION" not in words


def test_a_complete_set_of_two_kinds_is_refused_as_that() -> None:
    document = flight_home()
    document["wants"] = [must("window-seat", "alex")]
    both = every("window-seat")
    both["complete"]["from"] = "art-institute"
    document["facts"].append(both)
    last = len(document["facts"]) - 1
    one_kind = "travel, the OPTIONs that SATISFY a WANT, or the rights to an OPTION"
    assert problems(document) == f"/facts/{last}: a COMPLETE set is of one kind: {one_kind}"
    both["complete"] = {"satisfies": "window-seat", "rights_to": "flight"}
    assert problems(document) == f"/facts/{last}: a COMPLETE set is of one kind: {one_kind}"


def test_the_search_finds_a_plan_whenever_trying_everything_does() -> None:
    """Every choice of PERSONs and every start on the grid is tried, and each WANT is checked."""
    rng = Random(1212)
    seen: set[bool] = set()
    whole = 0
    for _ in range(150):
        file = random_trip(rng, leave_out=0, with_wants=1, must_nots=0.4, whole_sets=0.6)
        found = checked(file)
        feasible = found.answer is Answer.FEASIBLE
        assert feasible == works_on_the_grid(file, [worst_case(file)])
        if feasible:
            assert broken(file, worst_case(file), found.itinerary) == []
            assert needless(file, worst_case(file), found.itinerary) == []
        whole += any(isinstance(fact, CompleteFor) for fact in file.facts)
        seen.add(feasible)
    assert seen == {True, False}
    assert whole > 50


def a_trip(rng: Random, leave_out: float, persons: list[str] | None, with_ways: float) -> File:
    """A random trip with WANTs, some held as must-nots, and some with COMPLETE sets."""
    return random_trip(
        rng,
        leave_out,
        persons,
        contingent=0.3 if leave_out else 0,
        with_complete=0.4 if leave_out else 0,
        with_ways=with_ways,
        with_wants=1,
        must_nots=0.4,
        whole_sets=0.6,
    )


def test_the_two_checkers_agree_on_random_trips_with_complete_sets_for_wants() -> None:
    rng = Random(1313)
    trips = [a_trip(rng, 0.25, None, 0) for _ in range(80)]
    trips += [a_trip(rng, 0.2, None, 0.9) for _ in range(80)]
    trips += [a_trip(rng, 0, ["alex", "sam"], 0.5) for _ in range(80)]
    seen: set[Answer] = set()
    named = 0
    for file in trips:
        found = checked(file)
        seen.add(found.answer)
        whole = {fact.id for fact in file.facts if isinstance(fact, CompleteFor)}
        named += bool(whole & set(found.conflict))
    assert seen == set(Answer)
    assert named > 20


def test_the_best_and_worst_cases_settle_the_answer_with_complete_sets_for_wants() -> None:
    """Three claims of the rules page, each checked in possible worlds chosen at random.

    In a possible world an OPTION with no FACT about a WANT whose set is COMPLETE does not
    SATISFY it, and there is no other OPTION for that WANT. What works in the worst case works
    in every possible world. What works in a possible world works in the best case. An
    INFEASIBLE TRIP has nothing that works in any of them. And each set of unknown FACTs a
    report names is enough, while no part of it is.
    """
    rng = Random(1414)
    seen: set[Answer] = set()
    by_chance_with_a_whole_set = 0
    for number in range(200):
        with_ways = 0.8 if number % 2 else 0
        file = random_trip(
            rng,
            0.3,
            with_complete=0.3,
            with_ways=with_ways,
            with_wants=1,
            must_nots=0.4,
            whole_sets=0.6,
        )
        found = answers.check(file)
        seen.add(found.answer)
        best, worst = best_case(file), worst_case(file)
        always = itineraries(file, worst)
        assert bool(always) == (found.answer is Answer.FEASIBLE)
        for enough in found.missing:
            named = [needed.unknown for needed in enough]
            assert itineraries(file, with_these_at_best(file, named))
            for left_out in named:
                fewer = [unknown for unknown in named if unknown != left_out]
                assert not itineraries(file, with_these_at_best(file, fewer))
        whole = any(isinstance(fact, CompleteFor) for fact in file.facts)
        for _ in range(6):
            world = possible_world(rng, file)
            for choice in always:
                assert broken(file, world, in_world(world, choice)) == []
            by_chance = [any_choice(rng, file, world) for _ in range(12)]
            by_chance = [
                each for each in by_chance if not broken(file, world, in_world(world, each))
            ]
            by_chance_with_a_whole_set += bool(by_chance and whole)
            if by_chance:
                assert itineraries(file, world)
            for choice in (*itineraries(file, world), *by_chance):
                assert broken(file, best, in_world(best, choice)) == []
            if found.answer is Answer.INFEASIBLE:
                assert not by_chance
                assert not itineraries(file, world)
    assert seen == set(Answer)
    assert by_chance_with_a_whole_set > 50


def test_a_slow_search_of_every_set_finds_the_sets_the_report_names() -> None:
    rng = Random(1515)
    compared = 0
    for _ in range(80):
        file = random_trip(
            rng, 0.2, ["alex", "sam"], count=2, with_wants=1, must_nots=0.4, whole_sets=0.5
        )
        found = answers.check(file)
        every_unknown = unknowns(file)
        if found.answer is not Answer.UNDETERMINED or len(every_unknown) > 12:
            continue
        enough = [
            some
            for size in range(1, len(every_unknown) + 1)
            for some in combinations(every_unknown, size)
            if one_way_each(some) and itineraries(file, with_these_at_best(file, some))
        ]

        def cost(some: tuple[Unknown, ...]) -> tuple[int, int]:
            to_find = sum(each.what == "another option" for each in some)
            return (to_find, len(some) - to_find)

        least = min(cost(some) for some in enough)
        expected = [some for some in enough if cost(some) == least]
        assert [tuple(needed.unknown for needed in some) for some in found.missing] == expected
        compared += 1
    assert compared > 15
