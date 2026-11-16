"""Must-nots: a PERSON for whom a WANT is a must-not takes part in no OPTION that SATISFIES it."""

from collections.abc import Sequence
from random import Random

from agloe import answers, compiler, report
from agloe.answers import Answer, Missing, Report
from agloe.file import File
from agloe.reference import (
    Broken,
    Constraint,
    Itinerary,
    Step,
    Unknown,
    best_case,
    broken,
    in_world,
    itineraries,
    needless,
    unknowns,
    with_these_at_best,
    worst_case,
)
from tests.stories import (
    Document,
    cutoff,
    lasts,
    lock,
    must,
    must_not,
    satisfies,
    seconds,
    starts_at,
    stays,
    takes,
    trip,
    way_between,
)
from tests.test_cross_check import any_choice, possible_world, random_trip, works_on_the_grid

EVERYONE = ("alex", "sam", "jo")


def at_ten(option: str) -> list[Document]:
    """An OPTION that starts at 10:00 am, with nothing left unknown about its time."""
    return [starts_at(option, 10), lasts(option, "PT1H"), cutoff(option, "PT0S")]


def a_morning_up_high(
    *more: Document, wants: Sequence[Document] | None = None, locks: Sequence[Document] = ()
) -> File:
    """Three OPTIONs in the Loop at 10:00 am. A view is a must for Alex and a must-not for Jo.

    A FACT says the tower SATISFIES it, and a FACT says the gallery does not. The FILE says
    nothing about the rooftop.
    """
    options = [stays(id, "loop") for id in ("tower", "gallery", "rooftop")]
    facts = [*at_ten("tower"), *at_ten("gallery"), *at_ten("rooftop")]
    facts += [satisfies("tower", "view", 9), satisfies("gallery", "view", 0), *more]
    if wants is None:
        wants = [must("view", "alex", never=["jo"])]
    return trip(list(EVERYONE), ["loop"], options, facts, list(locks), wants=list(wants))


def visit(option: str, *persons: str) -> Step:
    return Step(option, "loop", "loop", persons, seconds(10), seconds(11))


def broke(option: str, *persons: str) -> Broken:
    return Broken(Constraint.MUST_NOT, option, persons, want="view")


def is_not(option: str, want: str = "view") -> Unknown:
    """That a listed OPTION does not SATISFY a WANT, where no FACT says."""
    return Unknown("does not satisfy", option, want=want)


def checked(file: File) -> Report:
    """The reference checker's Report, once the COMPILER has given the same one."""
    found = answers.check(file)
    assert compiler.check(file) == found
    return found


def who_does_what(found: Report) -> dict[str | None, tuple[str, ...]]:
    return {step.option: step.persons for step in found.itinerary}


def test_a_must_not_is_kept_by_staying_out_of_an_option_that_satisfies_it() -> None:
    file = a_morning_up_high()
    up: Itinerary = (visit("tower", "alex", "jo"),)
    assert broken(file, worst_case(file), up) == [broke("tower", "jo")]
    assert broken(file, best_case(file), up) == [broke("tower", "jo")]
    assert broken(file, worst_case(file), (visit("tower", "alex"),)) == []


def test_a_must_not_is_about_the_person_who_holds_it() -> None:
    """Alex goes up and Sam comes along. Neither breaks what Jo must not have."""
    file = a_morning_up_high()
    assert broken(file, worst_case(file), (visit("tower", "alex", "sam"),)) == []


def test_a_degree_of_zero_breaks_no_must_not() -> None:
    file = a_morning_up_high()
    plan: Itinerary = (visit("tower", "alex"), visit("gallery", "jo"))
    assert broken(file, worst_case(file), plan) == []


def test_any_degree_above_zero_breaks_a_must_not() -> None:
    file = a_morning_up_high(satisfies("rooftop", "view", 1))
    plan: Itinerary = (visit("tower", "alex"), visit("rooftop", "jo"))
    assert broken(file, best_case(file), plan) == [broke("rooftop", "jo")]


def test_an_option_with_no_fact_breaks_a_must_not_unless_it_turns_out_not_to_satisfy_it() -> None:
    file = a_morning_up_high()
    plan: Itinerary = (visit("tower", "alex"), visit("rooftop", "jo"))
    assert broken(file, worst_case(file), plan) == [broke("rooftop", "jo")]
    assert broken(file, with_these_at_best(file, [is_not("rooftop")]), plan) == []
    assert broken(file, best_case(file), plan) == []


def test_nobody_can_count_on_an_unknown_either_way() -> None:
    """Alex needs the rooftop to SATISFY the WANT, and Jo needs it not to."""
    file = a_morning_up_high()
    both: Itinerary = (visit("rooftop", "alex", "jo"),)
    unmet = Broken(Constraint.MUST, None, ("alex",), want="view")
    assert broken(file, worst_case(file), both) == [unmet, broke("rooftop", "jo")]
    it_does = with_these_at_best(file, [Unknown("satisfies", "rooftop", want="view")])
    assert broken(file, it_does, both) == [broke("rooftop", "jo")]
    assert broken(file, with_these_at_best(file, [is_not("rooftop")]), both) == [unmet]


def test_one_finding_names_everyone_who_breaks_a_must_not_in_an_option() -> None:
    file = a_morning_up_high(wants=[must_not("view", "jo", "alex")])
    assert broken(file, worst_case(file), (visit("tower", *EVERYONE),)) == [
        broke("tower", "alex", "jo")
    ]


def test_a_must_not_keeps_a_person_out_of_an_option() -> None:
    """All three are LOCKed for lunch. Only Alex goes up the tower before it."""
    file = a_morning_later(satisfies("lunch", "view", 0))
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert who_does_what(found) == {"tower": ("alex",), "lunch": EVERYONE}
    assert "view" in found.relies_on
    assert needless(file, worst_case(file), found.itinerary) == []


def a_morning_later(*more: Document, locks: Sequence[Document] | None = None) -> File:
    """The tower at 10:00 am and lunch at noon, both in the Loop. All three are LOCKed for lunch.

    A view is a must for Alex and a must-not for Jo. A FACT says the tower SATISFIES it.
    """
    options = [stays("tower", "loop"), stays("lunch", "loop")]
    facts = [
        *at_ten("tower"),
        starts_at("lunch", 12),
        lasts("lunch", "PT1H"),
        cutoff("lunch", "PT0S"),
        satisfies("tower", "view", 9),
        *more,
    ]
    if locks is None:
        locks = [lock("lunch", *EVERYONE)]
    wants = [must("view", "alex", never=["jo"])]
    return trip(list(EVERYONE), ["loop"], options, facts, list(locks), wants=wants)


def test_a_must_not_with_no_fact_makes_the_trip_undetermined() -> None:
    """Nobody has recorded whether lunch SATISFIES the WANT, and Jo is LOCKed for it."""
    found = checked(a_morning_later())
    assert found.answer is Answer.UNDETERMINED
    assert found.missing == ((Missing(is_not("lunch"), None),),)


def test_a_lock_against_a_must_not_makes_the_trip_infeasible() -> None:
    file = a_morning_later(
        satisfies("lunch", "view", 0), locks=[lock("tower", *EVERYONE), lock("lunch", *EVERYONE)]
    )
    found = checked(file)
    assert found.answer is Answer.INFEASIBLE
    assert found.conflict == ("tower-gives-view", "view", "lock-tower")


def test_a_must_not_never_puts_anything_in_the_plan() -> None:
    file = a_morning_up_high(wants=[must_not("view", "jo")])
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert found.itinerary == ()
    assert found.relies_on == ("view",)


def test_one_want_held_both_ways_in_one_option() -> None:
    """Alex and Jo are both LOCKed for the rooftop, and nobody knows about its view.

    If it SATISFIES the WANT, Jo's must-not is broken. If it does not, Alex's must is unmet
    there. So the trip works only if it does not and another OPTION is found for Alex.
    """
    found = checked(both_on_the_rooftop())
    assert found.answer is Answer.UNDETERMINED
    another = Unknown("another option", want="view", person="alex")
    assert found.missing == ((Missing(is_not("rooftop"), None), Missing(another, None)),)


def both_on_the_rooftop(*more: Document) -> File:
    """Only the rooftop is listed. A view is a must for Alex and a must-not for Jo.

    Both are LOCKed for the rooftop.
    """
    wants = [must("view", "alex", never=["jo"])]
    locks = [lock("rooftop", "alex", "jo")]
    facts = [*at_ten("rooftop"), *more]
    return trip(list(EVERYONE), ["loop"], [stays("rooftop", "loop")], facts, locks, wants=wants)


def test_a_fact_settles_a_want_held_both_ways() -> None:
    it_does = checked(both_on_the_rooftop(satisfies("rooftop", "view", 4)))
    assert it_does.answer is Answer.INFEASIBLE
    assert it_does.conflict == ("rooftop-gives-view", "view", "lock-rooftop")
    it_does_not = checked(both_on_the_rooftop(satisfies("rooftop", "view", 0)))
    another = Unknown("another option", want="view", person="alex")
    assert it_does_not.missing == ((Missing(another, None),),)


def test_no_set_says_that_an_option_both_does_and_does_not_satisfy_a_want() -> None:
    rng = Random(4040)
    both_ways = 0
    for _ in range(120):
        file = random_trip(rng, 0.2, ["alex", "sam"], with_wants=1, must_nots=0.5)
        for enough in answers.check(file).missing:
            about = [
                (needed.unknown.option, needed.unknown.want)
                for needed in enough
                if needed.unknown.what in ("satisfies", "does not satisfy")
            ]
            assert len(about) == len(set(about))
        kinds = {unknown.what for unknown in unknowns(file)}
        both_ways += {"satisfies", "does not satisfy"} <= kinds
    assert both_ways > 20


def test_a_want_that_is_taken_out_asks_nothing_of_anyone() -> None:
    file = both_on_the_rooftop(satisfies("rooftop", "view", 4))
    without = file.without("view")
    assert [(want.id, want.musts, want.must_nots) for want in without.wants] == [("view", (), ())]
    assert checked(without).answer is Answer.FEASIBLE
    assert checked(without).relies_on[-1] == "lock-rooftop"
    assert "view" not in checked(without).relies_on


def test_a_conflict_names_only_the_want_that_is_part_of_it() -> None:
    wants = [must_not("noise", "sam"), must("view", "alex", never=["jo"])]
    options = [stays("rooftop", "loop")]
    facts = [*at_ten("rooftop"), satisfies("rooftop", "view", 4), satisfies("rooftop", "noise", 0)]
    locks = [lock("rooftop", "jo", "sam")]
    found = checked(trip(list(EVERYONE), ["loop"], options, facts, locks, wants=wants))
    assert found.conflict == ("rooftop-gives-view", "view", "lock-rooftop")


def test_unknown_facts_about_a_want_held_both_ways_come_in_the_order_of_the_rules_page() -> None:
    file = both_on_the_rooftop()
    assert unknowns(file) == (
        Unknown("satisfies", "rooftop", want="view"),
        is_not("rooftop"),
        Unknown("another option", want="view", person="alex"),
    )
    only_a_must_not = a_morning_up_high(wants=[must_not("view", "jo")])
    assert unknowns(only_a_must_not) == (is_not("rooftop"),)


def test_the_report_puts_a_must_not_in_words() -> None:
    file = both_on_the_rooftop(satisfies("rooftop", "view", 4))
    found = checked(file)
    assert report.as_text(file, found).splitlines()[2:] == [
        "These FACTs, WANTs and DECISIONs clash. Each one is needed for the clash."
        " Times are in America/Chicago.",
        "  rooftop-gives-view: rooftop SATISFIES view, 4 out of 10",
        "  view: view is a must for alex and a must-not for jo",
        "  lock-rooftop: alex and jo take part in rooftop",
    ]
    assert report.as_json(file, found)["conflict"] == ["rooftop-gives-view", "view", "lock-rooftop"]


def test_the_report_says_which_option_would_have_to_not_satisfy_the_want() -> None:
    file = a_morning_later()
    found = checked(file)
    assert report.as_text(file, found).splitlines()[2:] == [
        "The trip works if lunch does not SATISFY view."
    ]
    assert report.as_json(file, found)["missing"] == [
        [{"what": "does not satisfy", "option": "lunch", "want": "view", "at_most": None}]
    ]


def test_a_want_that_is_only_a_must_not_is_put_in_words() -> None:
    file = a_morning_up_high(wants=[must_not("view", "jo", "sam")])
    assert "  view: view is a must-not for sam and jo\n" in report.as_text(file, checked(file))


def test_other_ways_must_not_break_a_must_not_either() -> None:
    """Jo must get from the hotel to lunch, and no WAY is listed. A cable car would not do."""
    options = [stays("breakfast", "hotel"), stays("lunch", "loop")]
    facts = [
        starts_at("breakfast", 8),
        lasts("breakfast", "PT1H"),
        cutoff("breakfast", "PT0S"),
        starts_at("lunch", 12),
        lasts("lunch", "PT1H"),
        cutoff("lunch", "PT0S"),
        satisfies("breakfast", "view", 0),
        satisfies("lunch", "view", 0),
    ]
    locks = [lock("breakfast", "jo"), lock("lunch", "jo")]
    wants = [must_not("view", "jo")]
    file = trip(["jo"], ["hotel", "loop"], options, facts, locks, wants=wants)
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    assert report.as_text(file, found).splitlines()[2:] == [
        "The trip works if there are other WAYs from hotel to loop that take 3 h or less.",
        "",
        "Other WAYs help only if they can be taken when the plan needs them, and only if they"
        " SATISFY nothing that is a must-not for a PERSON who takes them.",
    ]


def test_a_listed_way_breaks_no_must_not() -> None:
    options = [stays("breakfast", "hotel"), stays("lunch", "loop")]
    facts = [
        starts_at("breakfast", 8),
        lasts("breakfast", "PT1H"),
        cutoff("breakfast", "PT0S"),
        starts_at("lunch", 12),
        lasts("lunch", "PT1H"),
        cutoff("lunch", "PT0S"),
        satisfies("breakfast", "view", 0),
        satisfies("lunch", "view", 0),
        takes("walk", "PT30M"),
    ]
    locks = [lock("breakfast", "jo"), lock("lunch", "jo")]
    ways = [way_between("walk", "hotel", "loop")]
    wants = [must_not("view", "jo")]
    file = trip(["jo"], ["hotel", "loop"], options, facts, locks, ways=ways, wants=wants)
    assert checked(file).answer is Answer.FEASIBLE


def test_the_search_finds_a_plan_with_must_nots_whenever_trying_everything_does() -> None:
    """Every choice of PERSONs and every start on the grid is tried, and each WANT is checked."""
    rng = Random(5050)
    seen: set[bool] = set()
    held_back = 0
    for _ in range(150):
        file = random_trip(rng, leave_out=0, with_wants=1, must_nots=0.5)
        found = checked(file)
        feasible = found.answer is Answer.FEASIBLE
        assert feasible == works_on_the_grid(file, [worst_case(file)])
        if feasible:
            assert broken(file, worst_case(file), found.itinerary) == []
            assert needless(file, worst_case(file), found.itinerary) == []
        held_back += any(want.must_nots for want in file.wants)
        seen.add(feasible)
    assert seen == {True, False}
    assert held_back > 50


def test_the_two_checkers_agree_on_random_trips_with_must_nots() -> None:
    rng = Random(6060)
    trips = [
        random_trip(rng, 0.25, contingent=0.3, with_complete=0.4, with_wants=1, must_nots=0.5)
        for _ in range(80)
    ]
    trips += [
        random_trip(
            rng, 0.2, contingent=0.3, with_complete=0.4, with_ways=0.9, with_wants=1, must_nots=0.5
        )
        for _ in range(80)
    ]
    trips += [
        random_trip(rng, leave_out=0, with_ways=0.5, with_wants=1, must_nots=0.5) for _ in range(80)
    ]
    seen: set[Answer] = set()
    does_not = wants_in_conflicts = 0
    for file in trips:
        found = checked(file)
        seen.add(found.answer)
        kinds = {needed.unknown.what for enough in found.missing for needed in enough}
        does_not += "does not satisfy" in kinds
        wants_in_conflicts += bool({want.id for want in file.wants} & set(found.conflict))
    assert seen == set(Answer)
    assert does_not > 20
    assert wants_in_conflicts > 20


def test_the_best_and_worst_cases_settle_the_answer_with_must_nots() -> None:
    """Three claims of the rules page, each checked in possible worlds chosen at random.

    In a possible world an OPTION SATISFIES a WANT or it does not, for a must and a must-not
    alike. What works in the worst case works in every possible world. What works in a possible
    world works in the best case. An INFEASIBLE TRIP has nothing that works in any of them. And
    each set of unknown FACTs a report names is enough, while no part of it is.
    """
    rng = Random(7070)
    seen: set[Answer] = set()
    by_chance_with_a_must_not = 0
    for number in range(200):
        with_ways = 0.8 if number % 2 else 0
        file = random_trip(
            rng, 0.3, with_complete=0.3, with_ways=with_ways, with_wants=1, must_nots=0.5
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
        for _ in range(6):
            world = possible_world(rng, file)
            for choice in always:
                assert broken(file, world, in_world(world, choice)) == []
            by_chance = [any_choice(rng, file, world) for _ in range(12)]
            by_chance = [
                each for each in by_chance if not broken(file, world, in_world(world, each))
            ]
            held = any(want.must_nots for want in file.wants)
            by_chance_with_a_must_not += bool(by_chance and held)
            if by_chance:
                assert itineraries(file, world)
            for choice in (*itineraries(file, world), *by_chance):
                assert broken(file, best, in_world(best, choice)) == []
            if found.answer is Answer.INFEASIBLE:
                assert not by_chance
                assert not itineraries(file, world)
    assert seen == set(Answer)
    assert by_chance_with_a_must_not > 50
