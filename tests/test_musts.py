"""Musts: a PERSON for whom a WANT is a must takes part in an OPTION that SATISFIES it."""

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
    complete,
    cutoff,
    lasts,
    lasts_between,
    lock,
    must,
    satisfies,
    seconds,
    starts_at,
    stays,
    takes,
    trip,
    way_between,
)
from tests.test_cross_check import any_choice, possible_world, random_trip, works_on_the_grid


def another(person: str, want: str = "deep-dish") -> Unknown:
    """Another OPTION for a WANT, outside the FILE, that this PERSON can take part in."""
    return Unknown("another option", want=want, person=person)


def whether(option: str, want: str = "deep-dish") -> Unknown:
    """Whether a listed OPTION SATISFIES a WANT, where no FACT says."""
    return Unknown("satisfies", option, want=want)


def at_seven(option: str, minutes: int = 60) -> list[Document]:
    """An OPTION that starts at 7:00 pm, with nothing left unknown about its time."""
    return [starts_at(option, 19), lasts(option, f"PT{minutes}M"), cutoff(option, "PT0S")]


def at_noon(option: str) -> list[Document]:
    return [starts_at(option, 12), lasts(option, "PT1H"), cutoff(option, "PT0S")]


def an_evening(
    *more: Document, holders: Sequence[str] = ("alex",), locks: Sequence[Document] = ()
) -> File:
    """Three dinners in one PLACE at 7:00 pm. Deep-dish pizza is a must for the holders.

    A FACT says the pizzeria SATISFIES it, and a FACT says the tavern does not. The FILE says
    nothing about the bar.
    """
    options = [stays(id, "river-north") for id in ("pizzeria", "tavern", "bar")]
    facts = [*at_seven("pizzeria"), *at_seven("tavern"), *at_seven("bar")]
    facts += [satisfies("pizzeria", "deep-dish", 8), satisfies("tavern", "deep-dish", 0), *more]
    wants = [must("deep-dish", *holders)]
    return trip(["alex", "sam"], ["river-north"], options, facts, list(locks), wants=wants)


def dinner(option: str, *persons: str) -> Step:
    return Step(option, "river-north", "river-north", persons, seconds(19), seconds(20))


def unmet(*persons: str) -> Broken:
    return Broken(Constraint.MUST, None, persons, want="deep-dish")


def checked(file: File) -> Report:
    """The reference checker's Report, once the COMPILER has given the same one."""
    found = answers.check(file)
    assert compiler.check(file) == found
    return found


def what_happens(found: Report) -> list[str | None]:
    return [step.option or step.way for step in found.itinerary]


def test_a_must_is_met_by_taking_part_in_an_option_that_satisfies_it() -> None:
    file = an_evening()
    assert broken(file, worst_case(file), (dinner("pizzeria", "alex"),)) == []
    assert broken(file, worst_case(file), ()) == [unmet("alex")]


def test_a_must_is_about_the_person_who_holds_it() -> None:
    file = an_evening()
    assert broken(file, worst_case(file), (dinner("pizzeria", "sam"),)) == [unmet("alex")]


def test_a_degree_of_zero_meets_no_must_in_any_world() -> None:
    file = an_evening()
    at_the_tavern: Itinerary = (dinner("tavern", "alex"),)
    assert broken(file, worst_case(file), at_the_tavern) == [unmet("alex")]
    every_fact_at_its_best = with_these_at_best(file, [whether("bar")])
    assert broken(file, every_fact_at_its_best, at_the_tavern) == [unmet("alex")]


def test_any_degree_above_zero_meets_a_must() -> None:
    file = an_evening(satisfies("bar", "deep-dish", 1))
    assert broken(file, worst_case(file), (dinner("bar", "alex"),)) == []


def test_an_option_with_no_fact_meets_a_must_only_where_it_turns_out_to_satisfy_it() -> None:
    file = an_evening()
    at_the_bar: Itinerary = (dinner("bar", "alex"),)
    assert broken(file, worst_case(file), at_the_bar) == [unmet("alex")]
    it_does = with_these_at_best(file, [whether("bar")])
    assert broken(file, it_does, at_the_bar) == []
    assert broken(file, it_does, ()) == [unmet("alex")]


def test_another_option_meets_the_must_of_the_person_it_is_for() -> None:
    file = an_evening(holders=["alex", "sam"])
    assert broken(file, with_these_at_best(file, [another("alex")]), ()) == [unmet("sam")]
    for_both = with_these_at_best(file, [another("alex"), another("sam")])
    assert broken(file, for_both, ()) == []
    assert broken(file, best_case(file), ()) == []


def test_one_finding_names_everyone_whose_must_is_unmet() -> None:
    file = an_evening(holders=["sam", "alex"])
    assert broken(file, worst_case(file), ()) == [unmet("alex", "sam")]
    assert broken(file, worst_case(file), (dinner("pizzeria", "sam"),)) == [unmet("alex")]


def test_a_must_puts_an_option_in_the_plan_that_no_lock_names() -> None:
    file = an_evening()
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert found.itinerary == (dinner("pizzeria", "alex"),)
    assert found.relies_on == (
        "pizzeria-time",
        "pizzeria-length",
        "pizzeria-cutoff",
        "pizzeria-gives-deep-dish",
        "deep-dish",
    )
    assert needless(file, worst_case(file), found.itinerary) == []


def test_each_holder_meets_a_must_themselves() -> None:
    file = an_evening(holders=["alex", "sam"])
    assert checked(file).itinerary == (dinner("pizzeria", "alex", "sam"),)


def test_the_plan_takes_the_option_listed_first_that_meets_a_must() -> None:
    file = an_evening(satisfies("bar", "deep-dish", 10))
    assert checked(file).itinerary == (dinner("pizzeria", "alex"),)


def a_show_after_dinner(*more: Document, pizzeria_takes: int | tuple[int, int] = 75) -> File:
    """Alex is LOCKed for a show at a club at 8:30 pm, a 15 minute walk from River North.

    Deep-dish pizza is a must for Alex. A FACT says dinner at the pizzeria in River North
    SATISFIES it. The counter at the club is listed after the pizzeria. Dinner at the pizzeria
    takes a number of minutes, or a CONTINGENT range of them.
    """
    options = [stays("pizzeria", "river-north"), stays("counter", "club"), stays("show", "club")]
    if isinstance(pizzeria_takes, int):
        length = lasts("pizzeria", f"PT{pizzeria_takes}M")
    else:
        shortest, longest = pizzeria_takes
        length = lasts_between("pizzeria", f"PT{shortest}M", f"PT{longest}M")
    facts = [
        starts_at("pizzeria", 19),
        length,
        cutoff("pizzeria", "PT0S"),
        *at_seven("counter"),
        starts_at("show", 20, 30),
        lasts("show", "PT2H"),
        cutoff("show", "PT0S"),
        takes("walk", "PT15M"),
        satisfies("pizzeria", "deep-dish", 9),
        satisfies("show", "deep-dish", 0),
        complete(None, None),
        *more,
    ]
    return trip(
        ["alex"],
        ["river-north", "club"],
        options,
        facts,
        [lock("show", "alex")],
        ways=[way_between("walk", "river-north", "club")],
        wants=[must("deep-dish", "alex")],
    )


def test_a_must_can_send_a_person_somewhere_else_first() -> None:
    found = checked(a_show_after_dinner(satisfies("counter", "deep-dish", 0)))
    assert what_happens(found) == ["pizzeria", "walk", "show"]
    assert found.robust


def test_the_plan_meets_a_must_with_the_fewest_steps() -> None:
    """The counter is listed after the pizzeria, but it needs no walk."""
    found = checked(a_show_after_dinner(satisfies("counter", "deep-dish", 2)))
    assert what_happens(found) == ["counter", "show"]


def test_two_holders_can_meet_a_must_in_different_options() -> None:
    """Alex is busy at noon and Sam at 7:00 pm, so each has pizza at the other meal."""
    options = [stays(id, "loop") for id in ("pizza-lunch", "pizza-dinner", "meeting", "call")]
    facts = [
        *(fact for id in ("pizza-lunch", "meeting") for fact in at_noon(id)),
        *(fact for id in ("pizza-dinner", "call") for fact in at_seven(id)),
        satisfies("pizza-lunch", "deep-dish"),
        satisfies("pizza-dinner", "deep-dish"),
        satisfies("meeting", "deep-dish", 0),
        satisfies("call", "deep-dish", 0),
    ]
    locks = [lock("meeting", "alex"), lock("call", "sam")]
    wants = [must("deep-dish", "alex", "sam")]
    found = checked(trip(["alex", "sam"], ["loop"], options, facts, locks, wants=wants))
    assert found.answer is Answer.FEASIBLE
    assert {step.option: step.persons for step in found.itinerary} == {
        "pizza-lunch": ("sam",),
        "meeting": ("alex",),
        "pizza-dinner": ("alex",),
        "call": ("sam",),
    }


def test_a_must_that_no_known_option_meets_in_time_is_undetermined() -> None:
    """Dinner at the pizzeria runs past the show, and the FILE says nothing about the counter."""
    found = checked(a_show_after_dinner(pizzeria_takes=100))
    assert found.answer is Answer.UNDETERMINED
    assert found.missing == ((Missing(whether("counter"), None),),)


def test_another_option_is_named_only_when_nothing_listed_could_be_enough() -> None:
    """With a FACT that the counter does not SATISFY the WANT, only another OPTION is left."""
    file = a_show_after_dinner(satisfies("counter", "deep-dish", 0), pizzeria_takes=100)
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    assert found.missing == ((Missing(another("alex"), None),),)


def test_facts_about_a_listed_option_come_before_another_option() -> None:
    """Nobody knows how long the pizzeria takes, or how early Alex must be at the show.

    Those two FACTs would be enough. Another OPTION at the club would be enough by itself. But
    it stands in for a listed OPTION and every FACT about it, so the report names the two FACTs.
    """
    file = a_show_after_dinner(satisfies("counter", "deep-dish", 0))
    file = file.without("pizzeria-length").without("show-cutoff")
    found = checked(file)
    assert found.missing == (
        (Missing(Unknown("duration", "pizzeria"), None), Missing(Unknown("cutoff", "show"), None)),
    )
    by_itself = with_these_at_best(file, [another("alex")])
    assert answers.any_works(file, by_itself)
    assert compiler.works(file, by_itself)


def test_a_report_counts_conditions_and_names_listed_options_first() -> None:
    """Pizza and a view are both musts for Alex. One listed OPTION might SATISFY pizza.

    The report asks for one FACT about that OPTION and for another OPTION for the view. One
    OPTION outside the FILE could deliver both, but that would be two conditions.
    """
    facts = [*at_seven("supper"), satisfies("supper", "a-view", 0)]
    wants = [must("deep-dish", "alex"), must("a-view", "alex")]
    file = trip(["alex"], ["loop"], [stays("supper", "loop")], facts, [], wants=wants)
    found = checked(file)
    assert found.missing == (
        (Missing(whether("supper"), None), Missing(another("alex", "a-view"), None)),
    )
    assert report.as_text(file, found).splitlines()[2] == (
        "The trip works if supper SATISFIES deep-dish and another OPTION that SATISFIES a-view"
        " is found for alex."
    )
    both_found = with_these_at_best(file, [another("alex"), another("alex", "a-view")])
    assert answers.any_works(file, both_found)


def test_a_must_alone_never_makes_a_trip_infeasible() -> None:
    """Nothing is listed at all. Another OPTION might still be found."""
    file = trip(["alex"], [], [], [], [], wants=[must("deep-dish", "alex")])
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    assert found.missing == ((Missing(another("alex"), None),),)


def test_each_person_who_needs_another_option_is_named() -> None:
    """Sam can have pizza at the pizzeria, but Alex is LOCKed at the tavern at that time."""
    file = an_evening(
        satisfies("bar", "deep-dish", 0), holders=["alex", "sam"], locks=[lock("tavern", "alex")]
    )
    found = checked(file)
    assert found.missing == ((Missing(another("alex"), None),),)
    nobody_can = an_evening(
        satisfies("bar", "deep-dish", 0),
        holders=["alex", "sam"],
        locks=[lock("tavern", "alex", "sam")],
    )
    both = (Missing(another("alex"), None), Missing(another("sam"), None))
    assert checked(nobody_can).missing == (both,)


def test_a_trip_that_cannot_work_for_another_reason_stays_infeasible() -> None:
    """Alex is LOCKed for two OPTIONs at the same time. The must is no part of the conflict."""
    file = an_evening(locks=[lock("tavern", "alex"), lock("bar", "alex")])
    found = checked(file)
    assert found.answer is Answer.INFEASIBLE
    assert found.conflict == (
        "tavern-time",
        "tavern-length",
        "bar-time",
        "bar-length",
        "lock-tavern",
        "lock-bar",
    )


def test_unknown_facts_about_wants_come_in_the_order_of_the_rules_page() -> None:
    options = [stays("pizzeria", "river-north"), stays("bar", "river-north")]
    facts = [*at_seven("pizzeria"), *at_seven("bar"), satisfies("bar", "a-view", 0)]
    wants = [must("deep-dish", "sam", "alex"), must("a-view", "sam")]
    file = trip(["alex", "sam"], ["river-north"], options, facts, [], wants=wants)
    assert unknowns(file) == (
        whether("pizzeria"),
        whether("pizzeria", "a-view"),
        whether("bar"),
        another("alex"),
        another("sam"),
        another("sam", "a-view"),
    )


def test_a_plan_that_a_must_shapes_can_get_a_warning() -> None:
    """Dinner at the pizzeria can run to 100 minutes, and then Alex would still be at the table."""
    file = a_show_after_dinner(satisfies("counter", "deep-dish", 0), pizzeria_takes=(75, 100))
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert found.robust is False
    assert what_happens(found) == ["pizzeria", "walk", "show"]
    assert found.at_worst == (
        Broken(Constraint.PLACE, None, ("alex",), 25 * 60, step=1),
        Broken(Constraint.PLACE, "show", ("alex",), 10 * 60),
    )
    words = report.as_text(file, found)
    assert "    ! alex would still be busy for 25 min when this starts.\n" in words


def test_the_report_names_the_want_and_what_satisfies_it() -> None:
    file = an_evening()
    words = report.as_text(file, checked(file)).splitlines()
    assert words[-6:] == [
        "The plan relies on these FACTs and WANTs:",
        "  pizzeria-time: pizzeria starts at 7:00 pm on Saturday 15 May 2027",
        "  pizzeria-length: pizzeria takes 1 h",
        "  pizzeria-cutoff: nobody has to be at river-north before pizzeria starts",
        "  pizzeria-gives-deep-dish: pizzeria SATISFIES deep-dish, 8 out of 10",
        "  deep-dish: deep-dish is a must for alex",
    ]


def test_the_report_says_which_option_would_have_to_satisfy_the_want() -> None:
    file = a_show_after_dinner(pizzeria_takes=100)
    found = checked(file)
    assert report.as_text(file, found).splitlines()[2:] == [
        "The trip works if counter SATISFIES deep-dish."
    ]
    assert report.as_json(file, found)["missing"] == [
        [{"what": "satisfies", "option": "counter", "want": "deep-dish", "at_most": None}]
    ]


def test_the_report_says_for_whom_another_option_would_have_to_be_found() -> None:
    file = an_evening(
        satisfies("bar", "deep-dish", 0),
        holders=["alex", "sam"],
        locks=[lock("tavern", "alex", "sam")],
    )
    found = checked(file)
    assert report.as_text(file, found).splitlines()[2:] == [
        "The trip works if another OPTION that SATISFIES deep-dish is found for each of alex"
        " and sam.",
        "",
        "Another OPTION helps only if the PERSON it is for can take part in it and still do"
        " everything else the trip asks of them. One OPTION can be found for several PERSONs"
        " and several WANTs.",
    ]
    assert report.as_json(file, found)["missing"] == [
        [
            {"what": "another option", "want": "deep-dish", "person": "alex", "at_most": None},
            {"what": "another option", "want": "deep-dish", "person": "sam", "at_most": None},
        ]
    ]


def test_a_fact_that_an_option_does_not_satisfy_a_want_is_put_in_words() -> None:
    file = an_evening(locks=[lock("tavern", "sam")])
    words = report.as_text(file, checked(file))
    assert "  tavern-gives-deep-dish: tavern does not SATISFY deep-dish\n" in words


def test_the_search_finds_a_plan_with_musts_whenever_trying_everything_does() -> None:
    """Every choice of PERSONs and every start on the grid is tried, and each must is checked."""
    rng = Random(1010)
    seen: set[bool] = set()
    shaped = 0
    for _ in range(150):
        file = random_trip(rng, leave_out=0, with_wants=1)
        found = checked(file)
        feasible = found.answer is Answer.FEASIBLE
        assert feasible == works_on_the_grid(file, [worst_case(file)])
        if feasible:
            assert broken(file, worst_case(file), found.itinerary) == []
            assert needless(file, worst_case(file), found.itinerary) == []
            locked = {each.option for each in file.locks}
            shaped += any(step.option not in locked for step in found.itinerary)
        seen.add(feasible)
    assert seen == {True, False}
    assert shaped > 15


def test_the_two_checkers_agree_on_random_trips_with_musts() -> None:
    rng = Random(2020)
    trips = [
        random_trip(rng, 0.25, contingent=0.3, with_complete=0.4, with_wants=1) for _ in range(80)
    ]
    trips += [
        random_trip(rng, 0.2, contingent=0.3, with_complete=0.4, with_ways=0.9, with_wants=1)
        for _ in range(80)
    ]
    trips += [random_trip(rng, leave_out=0, with_ways=0.5, with_wants=1) for _ in range(80)]
    seen: set[Answer] = set()
    another_option = satisfying = 0
    for file in trips:
        found = checked(file)
        seen.add(found.answer)
        kinds = {needed.unknown.what for enough in found.missing for needed in enough}
        another_option += "another option" in kinds
        satisfying += "satisfies" in kinds
    assert seen == set(Answer)
    assert another_option > 10
    assert satisfying > 50


def test_the_best_and_worst_cases_settle_the_answer_with_musts() -> None:
    """Three claims of the rules page, each checked in possible worlds chosen at random.

    A possible world says whether each OPTION SATISFIES each WANT, and for whom there is another
    OPTION. What works in the worst case works in every possible world. What works in a possible
    world works in the best case. And each set of unknown FACTs a report names is enough, while
    no part of it is.
    """
    rng = Random(3030)
    seen: set[Answer] = set()
    by_chance_with_a_must = 0
    for number in range(200):
        with_ways = 0.8 if number % 2 else 0
        file = random_trip(rng, 0.3, with_complete=0.3, with_ways=with_ways, with_wants=1)
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
            by_chance_with_a_must += bool(by_chance and file.wants)
            if by_chance:
                assert itineraries(file, world)
            for choice in (*itineraries(file, world), *by_chance):
                assert broken(file, best, in_world(best, choice)) == []
            if found.answer is Answer.INFEASIBLE:
                assert not by_chance
                assert not itineraries(file, world)
    assert seen == set(Answer)
    assert by_chance_with_a_must > 100
