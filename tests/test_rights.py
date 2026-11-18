"""Rights: a PERSON takes part in an OPTION that needs a right only with a right to it."""

from collections.abc import Sequence
from dataclasses import replace
from itertools import combinations, product
from random import Random

import pytest

from agloe import answers, compiler, report
from agloe.answers import Answer
from agloe.file import Booking, CompleteRights, File, FileError, NeedsRight
from agloe.reference import (
    Broken,
    Constraint,
    Itinerary,
    Remaining,
    Step,
    Unknown,
    World,
    best_case,
    broken,
    in_world,
    itineraries,
    one_way_each,
    unknowns,
    with_these_at_best,
    works_as_listed,
    worst_case,
)
from tests.stories import (
    Document,
    booking,
    cutoff,
    every,
    every_right,
    lasts,
    lock,
    must,
    must_not,
    needs_no_right,
    needs_right,
    satisfies,
    seconds,
    starts_at,
    stays,
    trip,
)
from tests.test_cross_check import (
    any_choice,
    possible_world,
    random_trip,
    works_on_the_grid,
)
from tests.test_where_a_path_ends import checked, has_no_record_to_spare, ruled_out

EVERYONE = ["alex", "sam", "jo"]
TIMES = ("tour-time", "tour-length", "tour-cutoff")


def at_ten(option: str) -> list[Document]:
    """An OPTION that starts at 10:00 am, with nothing left unknown about its time."""
    return [starts_at(option, 10), lasts(option, "PT1H"), cutoff(option, "PT0S")]


def a_boat_tour(
    *more: Document, locked: Sequence[str] = ("alex", "sam"), wants: Sequence[Document] = ()
) -> File:
    """A boat tour at 10:00 am, with nothing unknown about its time. A LOCK names Alex and Sam.

    The FILE says about rights only what ``more`` says.
    """
    decisions = [lock("tour", *locked)] if locked else []
    options = [stays("tour", "dock")]
    return trip(
        EVERYONE, ["dock"], options, [*at_ten("tour"), *more], decisions, wants=wants, tickets=True
    )


def on_the_tour(*persons: str) -> Itinerary:
    return (Step("tour", "dock", "dock", persons, seconds(10), seconds(11)),)


def free(option: str) -> Unknown:
    """That a listed OPTION needs no right, where no FACT says."""
    return Unknown("needs no right", option)


def right(option: str, person: str) -> Unknown:
    """Another right to a listed OPTION for a PERSON."""
    return Unknown("another right", option, person=person)


def asked(found: answers.Report) -> list[list[Unknown]]:
    """The sets of unknown FACTs a report names."""
    return [[needed.unknown for needed in enough] for enough in found.missing]


def in_words(file: File) -> list[str]:
    return report.as_text(file, checked(file)).splitlines()


def problems(*facts: Document) -> str:
    with pytest.raises(FileError) as refused:
        a_boat_tour(*facts)
    return str(refused.value)


# ------------------------------- What a FILE holds -------------------------------


def test_a_file_says_whether_an_option_needs_a_right() -> None:
    file = a_boat_tour(needs_right("tour"))
    assert file.facts[-1] == NeedsRight("tour-needs-right", "tour", True)
    assert file.needs_right("tour") is True
    assert a_boat_tour(needs_no_right("tour")).needs_right("tour") is False
    assert a_boat_tour().needs_right("tour") is None


def test_a_booking_covers_the_persons_it_names() -> None:
    file = a_boat_tour(booking("tour", "alex", "sam"))
    assert file.booking("tour", "alex") == Booking("tour-booking", "tour", ("alex", "sam"))
    assert file.booking("tour", "sam") == file.booking("tour", "alex")
    assert file.booking("tour", "jo") is None


def test_the_booking_listed_first_is_the_one_that_covers_a_person() -> None:
    file = a_boat_tour(
        booking("tour", "alex", id="first"), booking("tour", "sam", "alex", id="second")
    )
    for_alex, for_sam = file.booking("tour", "alex"), file.booking("tour", "sam")
    assert for_alex is not None and for_alex.id == "first"
    assert for_sam is not None and for_sam.id == "second"


def test_a_fact_can_say_that_the_file_holds_every_right_to_an_option() -> None:
    assert a_boat_tour().rights_complete("tour") is None
    whole = a_boat_tour(every_right("tour")).rights_complete("tour")
    assert whole == CompleteRights("every-right-to-tour", "tour")


def test_facts_about_rights_are_checked_like_every_other_fact() -> None:
    twice = "/facts/4: another FACT already states this about tour"
    assert problems(needs_right("tour"), needs_no_right("tour")) == twice
    again = every_right("tour")
    again["id"] = "again"
    assert problems(every_right("tour"), again) == twice
    assert problems(booking("cruise", "alex")) == "/facts/3: cruise is not an OPTION in this FILE"
    assert problems(every_right("cruise")) == "/facts/3: cruise is not an OPTION in this FILE"
    assert problems(booking("tour", "pat")) == "/facts/3: pat is not a PERSON in this FILE"
    assert problems(booking("tour", "alex", "alex")) == "/facts/3: alex is covered more than once"
    nobody = "/facts/3: fits no known shape; the closest miss: [] should be non-empty"
    assert problems(booking("tour")) == nobody
    maybe = {"id": "maybe", "option": "tour", "needs_right": "yes"}
    assert problems(maybe).endswith("'yes' is not of type 'boolean'")


def test_a_booking_says_nothing_but_its_option_and_whom_it_covers() -> None:
    priced = booking("tour", "alex")
    priced["booking"]["price"] = 30
    assert problems(priced).endswith("('price' was unexpected)")


# ------------------------------- The CONSTRAINT -------------------------------


def test_each_person_needs_a_right_of_their_own() -> None:
    file = a_boat_tour(needs_right("tour"), booking("tour", "alex"), locked=())
    worst = worst_case(file)
    assert broken(file, worst, on_the_tour("alex")) == []
    without = [Broken(Constraint.RIGHT, "tour", ("sam", "jo"))]
    assert broken(file, worst, on_the_tour("jo", "alex", "sam")) == without
    assert broken(file, best_case(file), on_the_tour("jo", "alex", "sam")) == []


def test_an_option_that_needs_no_right_is_open_to_everybody() -> None:
    file = a_boat_tour(needs_no_right("tour"))
    assert broken(file, worst_case(file), on_the_tour(*EVERYONE)) == []


def test_a_booking_is_for_its_own_option_only() -> None:
    options = [stays("tour", "dock"), stays("cruise", "dock")]
    facts = [*at_ten("tour"), needs_right("tour"), needs_right("cruise"), booking("cruise", "alex")]
    file = trip(["alex"], ["dock"], options, facts, [], tickets=True)
    without = [Broken(Constraint.RIGHT, "tour", ("alex",))]
    assert broken(file, worst_case(file), on_the_tour("alex")) == without


def test_a_booking_puts_nobody_into_an_option() -> None:
    file = a_boat_tour(needs_right("tour"), booking("tour", "jo"), locked=())
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert found.itinerary == ()
    assert found.relies_on == ()


# ------------------------------- The three answers -------------------------------


def test_a_booking_for_everyone_who_takes_part_makes_a_trip_feasible() -> None:
    file = a_boat_tour(needs_right("tour"), booking("tour", "alex", "sam"))
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert found.itinerary == on_the_tour("alex", "sam")
    assert found.relies_on == (*TIMES, "tour-needs-right", "tour-booking", "lock-tour")
    assert in_words(file)[-3:-1] == [
        "  tour-needs-right: people need a right to take part in tour",
        "  tour-booking: a BOOKING for tour covers alex and sam",
    ]


def test_a_missing_right_might_still_be_had() -> None:
    file = a_boat_tour(needs_right("tour"), booking("tour", "alex"))
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    assert asked(found) == [[right("tour", "sam")]]
    assert in_words(file)[-1] == "The trip works if a right to tour is found for sam."
    assert report.as_json(file, found)["missing"] == [
        [{"what": "another right", "option": "tour", "person": "sam", "at_most": None}]
    ]


def test_a_report_names_together_the_persons_who_need_a_right_to_one_option() -> None:
    file = a_boat_tour(needs_right("tour"))
    assert asked(checked(file)) == [[right("tour", "alex"), right("tour", "sam")]]
    assert (
        in_words(file)[-1] == "The trip works if a right to tour is found for each of alex and sam."
    )


def test_with_no_fact_nobody_knows_whether_an_option_needs_a_right() -> None:
    """The report asks that first. It asks for no right to an OPTION that might need none."""
    file = a_boat_tour()
    assert [unknown.what for unknown in unknowns(file)] == ["needs no right"]
    assert asked(checked(file)) == [[free("tour")]]
    assert in_words(file)[-3:] == [
        "The trip works if nobody needs a right to take part in tour.",
        "",
        "If tour does need a right, a BOOKING for each PERSON who takes part in it is enough"
        " instead.",
    ]
    covered = a_boat_tour(booking("tour", "alex"))
    assert asked(checked(covered)) == [[free("tour")]]


def test_a_right_is_unknown_only_where_one_might_be_had_and_would_help() -> None:
    """Nothing is unknown for a PERSON whom a BOOKING covers, or where the rights are COMPLETE."""
    file = a_boat_tour(needs_right("tour"), booking("tour", "alex"))
    assert list(unknowns(file)) == [right("tour", "sam"), right("tour", "jo")]
    assert unknowns(a_boat_tour(needs_right("tour"), every_right("tour"))) == ()
    assert unknowns(a_boat_tour(needs_no_right("tour"))) == ()


def test_the_unknown_facts_about_rights_come_before_those_about_wants() -> None:
    options = [stays("tour", "dock")]
    file = trip(["alex"], ["dock"], options, [], [], wants=[must("water", "alex")], tickets=True)
    assert [unknown.what for unknown in unknowns(file)] == [
        "start",
        "duration",
        "cutoff",
        "needs no right",
        "satisfies",
        "another option",
    ]
    wants = [must("water", "alex")]
    stated = trip(["alex"], ["dock"], options, [needs_right("tour")], [], wants=wants, tickets=True)
    assert [unknown.what for unknown in unknowns(stated)][3:5] == ["another right", "satisfies"]


def test_the_sets_a_report_names_come_in_the_order_of_their_facts() -> None:
    """The tower gives a view and the deck a breeze, at the same time. Alex must have both.

    So one of the two has to be found elsewhere. The set that asks about the tower comes
    first, though the search comes to the other OPTION for a view first.
    """
    options = [stays("tower", "loop"), stays("deck", "loop")]
    facts = [*at_ten("tower"), *at_ten("deck")]
    facts += [satisfies("tower", "view"), satisfies("tower", "breeze", 0)]
    facts += [satisfies("deck", "breeze"), satisfies("deck", "view", 0)]
    wants = [must("view", "alex"), must("breeze", "alex")]
    file = trip(["alex"], ["loop"], options, facts, [], wants=wants, tickets=True)
    a_view_elsewhere = Unknown("another option", want="view", person="alex")
    a_breeze_elsewhere = Unknown("another option", want="breeze", person="alex")
    assert asked(checked(file)) == [
        [free("tower"), a_breeze_elsewhere],
        [free("deck"), a_view_elsewhere],
    ]


def test_the_options_that_have_to_need_no_right_are_named_together() -> None:
    options = [stays(id, "dock") for id in ("tour", "cruise", "swim")]
    facts = [starts_at("tour", 10), starts_at("cruise", 12), starts_at("swim", 14)]
    facts += [fact for id in ("tour", "cruise", "swim") for fact in at_ten(id)[1:]]
    locks = [lock(id, "alex") for id in ("tour", "cruise", "swim")]
    file = trip(["alex"], ["dock"], options, facts, locks, tickets=True)
    assert asked(checked(file)) == [[free("tour"), free("cruise"), free("swim")]]
    words = "The trip works if nobody needs a right to take part in tour, cruise or swim."
    assert in_words(file)[2] == words


def test_the_words_keep_the_order_of_the_unknown_facts() -> None:
    """The cruise has no stated start, so the two OPTIONs are not named together."""
    options = [stays("tour", "dock"), stays("cruise", "dock")]
    facts = [*at_ten("tour"), *at_ten("cruise")[1:]]
    locks = [lock("tour", "alex"), lock("cruise", "alex")]
    file = trip(["alex"], ["dock"], options, facts, locks, tickets=True)
    assert asked(checked(file)) == [[free("tour"), Unknown("start", "cruise"), free("cruise")]]
    assert in_words(file)[2] == (
        "The trip works if nobody needs a right to take part in tour and cruise can start at any"
        " time and nobody needs a right to take part in cruise."
    )


def test_a_booking_for_everyone_settles_an_option_that_might_need_a_right() -> None:
    """Nobody knows whether the tour needs a right. The plan holds either way."""
    file = a_boat_tour(booking("tour", "alex", "sam"))
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert found.relies_on == (*TIMES, "tour-booking", "lock-tour")


def test_a_plan_relies_on_no_booking_for_an_option_that_needs_no_right() -> None:
    file = a_boat_tour(needs_no_right("tour"), booking("tour", "alex", "sam"))
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert found.relies_on == (*TIMES, "tour-open", "lock-tour")


def test_a_plan_relies_on_the_first_booking_that_covers_each_person_in_it() -> None:
    """Jo stays ashore, and Sam has two BOOKINGs. The FACT that closes the set is not needed."""
    file = a_boat_tour(
        needs_right("tour"),
        booking("tour", "jo", id="for-jo"),
        booking("tour", "alex", id="first"),
        booking("tour", "alex", "sam", id="second"),
        booking("tour", "sam", id="third"),
        every_right("tour"),
    )
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert found.relies_on == (*TIMES, "tour-needs-right", "first", "second", "lock-tour")


def test_a_missing_right_makes_a_trip_infeasible_where_the_rights_are_complete() -> None:
    file = a_boat_tour(needs_right("tour"), booking("tour", "alex"), every_right("tour"))
    found = checked(file)
    assert found.answer is Answer.INFEASIBLE
    conflict = ("tour-needs-right", "tour-booking", "every-right-to-tour", "lock-tour")
    assert found.conflict == conflict
    assert has_no_record_to_spare(file, conflict)
    whole = "nobody on the trip holds another or can get one"
    assert (
        in_words(file)[-2] == f"  every-right-to-tour: the FILE lists every right to tour: {whole}"
    )


def test_a_conflict_holds_every_booking_for_the_option() -> None:
    """Either BOOKING, once nobody knows whom it covers, might cover Sam."""
    file = a_boat_tour(
        needs_right("tour"),
        booking("tour", "alex", id="first"),
        booking("tour", "alex", "jo", id="second"),
        every_right("tour"),
    )
    found = checked(file)
    conflict = ("tour-needs-right", "first", "second", "every-right-to-tour", "lock-tour")
    assert found.conflict == conflict
    assert has_no_record_to_spare(file, conflict)


def test_a_complete_set_with_no_booking_leaves_nobody_a_right() -> None:
    file = a_boat_tour(needs_right("tour"), every_right("tour"), locked=("alex",))
    found = checked(file)
    assert found.conflict == ("tour-needs-right", "every-right-to-tour", "lock-tour")
    assert has_no_record_to_spare(file, found.conflict)


def test_a_booking_that_is_taken_out_might_cover_anybody() -> None:
    file = a_boat_tour(needs_right("tour"), booking("tour", "alex"), every_right("tour"))
    left = Remaining(file).without("tour-booking")
    assert left.open_to_all == {"tour"}
    assert left.might_cover() == {("tour", person) for person in EVERYONE}
    assert ruled_out(Remaining(file)) and not ruled_out(left)
    assert compiler.stuck(left) is None
    assert compiler.stuck(Remaining(file)) == {
        "tour-needs-right",
        "tour-booking",
        "every-right-to-tour",
        "lock-tour",
    }


def test_complete_rights_do_not_settle_an_option_that_might_need_none() -> None:
    """Alex is LOCKed in, nobody holds a right and none can be had. The tour might be free."""
    file = a_boat_tour(every_right("tour"), locked=("alex",))
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    assert asked(found) == [[free("tour")]]
    # No BOOKING can stand in: the FILE says that nobody can get a right.
    assert in_words(file)[-1] == "The trip works if nobody needs a right to take part in tour."


def test_a_right_that_might_be_had_does_not_undo_a_must_not() -> None:
    """The tour is on the water, which Alex must not have. A right would change nothing."""
    wants = [must_not("water", "alex")]
    file = a_boat_tour(needs_right("tour"), satisfies("tour", "water"), wants=wants)
    found = checked(file)
    assert found.answer is Answer.INFEASIBLE
    assert found.conflict == ("tour-gives-water", "water", "lock-tour")


def a_view(*more: Document) -> File:
    """A view is a must for Alex, and no LOCK names anything.

    The tower gives a view and needs a right. The FILE holds every right to it, and holds none.
    Anybody can go up to the rooftop.
    """
    options = [stays("tower", "loop"), stays("rooftop", "loop")]
    facts = [*at_ten("tower"), *at_ten("rooftop"), satisfies("tower", "view")]
    facts += [needs_right("tower"), every_right("tower"), needs_no_right("rooftop"), *more]
    wants = [must("view", "alex")]
    return trip(["alex"], ["loop"], options, facts, [], wants=wants, tickets=True)


def test_an_option_nobody_can_get_into_leaves_a_must_to_the_others() -> None:
    it_does = checked(a_view(satisfies("rooftop", "view")))
    assert it_does.answer is Answer.FEASIBLE
    assert [step.option for step in it_does.itinerary] == ["rooftop"]
    assert asked(checked(a_view())) == [[Unknown("satisfies", "rooftop", want="view")]]
    another = Unknown("another option", want="view", person="alex")
    assert asked(checked(a_view(satisfies("rooftop", "view", 0)))) == [[another]]
    file = a_view(satisfies("rooftop", "view", 0), every("view"))
    found = checked(file)
    assert found.answer is Answer.INFEASIBLE
    assert found.conflict == (
        "tower-needs-right",
        "every-right-to-tower",
        "rooftop-gives-view",
        "every-view",
        "view",
    )
    assert has_no_record_to_spare(file, found.conflict)


def test_the_rights_a_report_asks_for_work_together_in_one_plan() -> None:
    """Alex is LOCKed into the river tour and Sam into the tower. Jo must see the skyline.

    Only those two give it, both need a right, and nobody has one. Jo needs a right to one of
    them. A right for Alex and a right for Sam are not enough, though each OPTION then has one.
    """
    options = [stays("river", "dock"), stays("tower", "loop")]
    facts = [*at_ten("river"), *at_ten("tower"), needs_right("river"), needs_right("tower")]
    facts += [satisfies("river", "skyline"), satisfies("tower", "skyline"), every("skyline")]
    locks = [lock("river", "alex"), lock("tower", "sam")]
    wants = [must("skyline", "jo")]
    file = trip(EVERYONE, ["dock", "loop"], options, facts, locks, wants=wants, tickets=True)
    found = checked(file)
    assert asked(found) == [
        [right("river", "alex"), right("river", "jo"), right("tower", "sam")],
        [right("river", "alex"), right("tower", "sam"), right("tower", "jo")],
    ]
    assert in_words(file)[-2:] == [
        "  1. A right to river is found for each of alex and jo and a right to tower is found"
        " for sam.",
        "  2. A right to river is found for alex and a right to tower is found for each of sam"
        " and jo.",
    ]
    too_few = [right("river", "alex"), right("tower", "sam")]
    assert not itineraries(file, with_these_at_best(file, too_few))


# ------------------------------- Against every possible world -------------------------------


def two_tours(rng: Random) -> File:
    """Two OPTIONs at one PLACE with every time stated. Only rights are unknown."""
    persons = ["alex", "sam"] if rng.random() < 0.6 else ["alex"]
    options = [stays("tour", "dock"), stays("cruise", "dock")]
    facts: list[Document] = []
    decisions: list[Document] = []
    for option in ("tour", "cruise"):
        facts += [starts_at(option, 9, 15 * rng.randrange(3)), lasts(option, "PT15M")]
        facts.append(cutoff(option, "PT0S"))
        stated = rng.choice(
            [needs_right(option), needs_right(option), needs_no_right(option), None]
        )
        if stated is not None:
            facts.append(stated)
        for number in range(rng.choice([0, 1, 1, 2])):
            covered = rng.sample(persons, rng.randrange(1, len(persons) + 1))
            facts.append(booking(option, *covered, id=f"{option}-booking-{number}"))
        if rng.random() < 0.4:
            facts.append(every_right(option))
        if rng.random() < 0.7:
            decisions.append(lock(option, *rng.sample(persons, rng.randrange(1, len(persons) + 1))))
    return trip(persons, ["dock"], options, facts, decisions, tickets=True)


def every_world_of_rights(file: File) -> list[World]:
    """Every way the unknown FACTs about rights could turn out. Nothing else is unknown."""
    options, persons = file.options, file.persons
    known = {option.id for option in options if file.needs_right(option.id)}
    unsaid = [option.id for option in options if file.needs_right(option.id) is None]
    pairs = [(option.id, person.id) for option in options for person in persons]
    covered = {pair for pair in pairs if file.booking(*pair) is not None}
    may_be_had = [
        pair for pair in pairs if pair not in covered and file.rights_complete(pair[0]) is None
    ]
    worlds: list[World] = []
    for needed in product([False, True], repeat=len(unsaid)):
        needs = known | {option for option, yes in zip(unsaid, needed, strict=True) if yes}
        for had in product([False, True], repeat=len(may_be_had)):
            rights = covered | {pair for pair, yes in zip(may_be_had, had, strict=True) if yes}
            world = replace(worst_case(file), needs_right=frozenset(needs))
            worlds.append(replace(world, rights=frozenset(rights)))
    return worlds


def test_the_three_answers_hold_for_every_way_rights_could_turn_out() -> None:
    """FEASIBLE: one choice works in every world. INFEASIBLE: no choice works in any."""
    rng = Random(1010)
    seen: set[Answer] = set()
    for _ in range(150):
        file = two_tours(rng)
        worlds = every_world_of_rights(file)
        found = checked(file)
        seen.add(found.answer)
        assert (found.answer is Answer.FEASIBLE) == works_on_the_grid(file, worlds)
        somewhere = any(works_on_the_grid(file, [world]) for world in worlds)
        assert (found.answer is Answer.INFEASIBLE) == (not somewhere)
        if found.answer is Answer.INFEASIBLE:
            assert has_no_record_to_spare(file, found.conflict)
        for enough in asked(found):
            assert works_on_the_grid(file, [with_these_at_best(file, enough)])
            for left_out in enough:
                fewer = [unknown for unknown in enough if unknown != left_out]
                assert not works_on_the_grid(file, [with_these_at_best(file, fewer)])
    assert seen == set(Answer)


def test_the_best_and_worst_cases_settle_the_answer_with_rights_among_the_unknowns() -> None:
    """What works in the worst case works in every possible world, and so on, as before."""
    rng = Random(2020)
    seen: set[Answer] = set()
    by_chance_with_a_right = 0
    for _ in range(160):
        file = random_trip(rng, 0.2, with_ways=0.5, with_wants=0.4, must_nots=0.3, with_rights=0.4)
        found = answers.check(file)
        seen.add(found.answer)
        best, worst = best_case(file), worst_case(file)
        always = itineraries(file, worst)
        assert bool(always) == (found.answer is Answer.FEASIBLE)
        for enough in asked(found):
            assert itineraries(file, with_these_at_best(file, enough))
            for left_out in enough:
                fewer = [unknown for unknown in enough if unknown != left_out]
                assert not itineraries(file, with_these_at_best(file, fewer))
        for _ in range(6):
            world = possible_world(rng, file)
            for choice in always:
                assert works_as_listed(file, world, in_world(world, choice))
            by_chance = [any_choice(rng, file, world) for _ in range(12)]
            by_chance = [
                each for each in by_chance if not broken(file, world, in_world(world, each))
            ]
            by_chance_with_a_right += any(
                step.option in world.needs_right for each in by_chance for step in each
            )
            if by_chance:
                assert itineraries(file, world)
            for choice in (*itineraries(file, world), *by_chance):
                assert broken(file, best, in_world(best, choice)) == []
            if found.answer is Answer.INFEASIBLE:
                assert not by_chance
                assert not itineraries(file, world)
    assert seen == set(Answer)
    assert by_chance_with_a_right > 20


def test_the_compiler_and_the_reference_checker_agree_on_trips_with_rights() -> None:
    rng = Random(3030)
    trips = [two_tours(rng) for _ in range(100)]
    trips += [random_trip(rng, 0.2, with_ways=0.5, with_rights=0.4) for _ in range(120)]
    trips += [
        random_trip(rng, 0.2, with_wants=0.8, must_nots=0.3, whole_sets=0.4, with_rights=0.4)
        for _ in range(120)
    ]
    trips += [
        random_trip(rng, 0.1, with_ends=0.5, with_ways=0.8, with_rights=0.3) for _ in range(60)
    ]
    seen: set[Answer] = set()
    for file in trips:
        found = answers.check(file)
        assert compiler.check(file) == found
        seen.add(found.answer)
    assert seen == set(Answer)


# ------------------------------- The search for missing FACTs -------------------------------


def test_the_search_for_missing_facts_skips_no_set() -> None:
    """The sets a report names are those a slow search of all sets finds, in the same order."""
    rng = Random(4040)
    compared = several = held = 0
    for _ in range(140):
        persons = ["alex", "sam"] if rng.random() < 0.5 else ["alex"]
        file = random_trip(
            rng, 0.15, persons, count=2, with_wants=0.5, must_nots=0.4, with_rights=0.3
        )
        found = compiler.check(file)
        every = unknowns(file)
        if found.answer is not Answer.UNDETERMINED or len(every) > 13:
            continue
        enough = [
            some
            for size in range(1, len(every) + 1)
            for some in combinations(every, size)
            if one_way_each(some) and itineraries(file, with_these_at_best(file, some))
        ]

        def cost(some: tuple[Unknown, ...]) -> tuple[int, int]:
            to_find = sum(each.what == "another option" for each in some)
            return (to_find, len(some) - to_find)

        least = min(cost(some) for some in enough)
        assert asked(found) == [list(some) for some in enough if cost(some) == least]
        in_every_set = answers._asked_by_a_lock(file)  # pyright: ignore[reportPrivateUsage]
        assert all(in_every_set.issubset(some) for some in enough)
        held += bool(in_every_set)
        compared += 1
        several += len(found.missing[0]) > 2
    assert compared > 30
    assert several > 10
    assert held > 10


def test_a_file_that_says_nothing_about_rights_gets_its_report_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Six OPTIONs in a row, all LOCKed. The report asks one thing about each of them.

    Every set holds those six FACTs, so the search tries one set and no smaller one.
    """
    names = [f"stop-{number}" for number in range(6)]
    facts = [
        fact
        for number, name in enumerate(names)
        for fact in (starts_at(name, 9 + number), lasts(name, "PT30M"), cutoff(name, "PT0S"))
    ]
    options = [stays(name, "dock") for name in names]
    file = trip(
        ["alex"], ["dock"], options, facts, [lock(name, "alex") for name in names], tickets=True
    )
    calls = 0
    solver = compiler.works

    def counted(file: File, world: World) -> bool:
        nonlocal calls
        calls += 1
        return answers.any_works(file, world)

    def counted_solver(file: File, world: World) -> bool:
        nonlocal calls
        calls += 1
        return solver(file, world)

    found = answers.check(file, works=counted)
    assert asked(found) == [[free(name) for name in names]]
    assert calls < 6
    calls = 0
    monkeypatch.setattr(compiler, "works", counted_solver)
    assert compiler.check(file) == found
    assert calls < 6


def test_a_lock_says_which_unknown_facts_every_set_holds() -> None:
    """The start of a LOCKed OPTION, and that it needs no right where somebody is not covered."""
    nothing_said = trip(
        EVERYONE, ["dock"], [stays("tour", "dock")], [], [lock("tour", "alex", "sam")], tickets=True
    )
    assert answers._asked_by_a_lock(nothing_said) == {Unknown("start", "tour"), free("tour")}  # pyright: ignore[reportPrivateUsage]
    for_alex = [lasts("tour", "PT1H"), cutoff("tour", "PT0S"), booking("tour", "alex")]
    one_covered = trip(
        EVERYONE, ["dock"], [stays("tour", "dock")], for_alex, [lock("tour", "alex")], tickets=True
    )
    assert asked(checked(one_covered)) == [[Unknown("start", "tour")]]
    both_locked = trip(
        EVERYONE,
        ["dock"],
        [stays("tour", "dock")],
        for_alex,
        [lock("tour", "alex", "sam")],
        tickets=True,
    )
    assert asked(checked(both_locked)) == [[Unknown("start", "tour"), free("tour")]]
    assert answers._asked_by_a_lock(a_boat_tour(needs_right("tour"))) == frozenset()  # pyright: ignore[reportPrivateUsage]
    assert answers._asked_by_a_lock(a_boat_tour(locked=())) == frozenset()  # pyright: ignore[reportPrivateUsage]


def test_the_search_that_tries_every_choice_is_asked_about_no_world_it_is_slow_in() -> None:
    """Five optional stays with no stated start, and five PERSONs. Alex needs two of the stays.

    A world where four of the stays can start has a million choices of who takes part, and the
    search that tries every choice goes through them all to find that none works. So the
    search for missing FACTs asks only about the best case, the upper bound, and the sets it
    tries.
    """
    people = ["alex", "sam", "jo", "pat", "kim"]
    names = [f"stay-{number}" for number in range(5)]
    facts = [fact for name in names for fact in (lasts(name, "PT5M"), cutoff(name, "PT0S"))]
    facts += [satisfies("stay-0", "first"), every("first")]
    facts += [satisfies("stay-1", "second"), every("second")]
    wants = [must("first", "alex"), must("second", "alex")]
    file = trip(people, ["dock"], [stays(name, "dock") for name in names], facts, [], wants=wants)
    asked_about: list[World] = []

    def recorded(file: File, world: World) -> bool:
        asked_about.append(world)
        return answers.any_works(file, world)

    found = answers.check(file, works=recorded)
    assert asked(found) == [[Unknown("start", "stay-0"), Unknown("start", "stay-1")]]
    can_start = [sum(terms.free_start for terms in world.terms.values()) for world in asked_about]
    assert sorted(count for count in can_start if count > 2) == [5, 5]
    assert compiler.check(file) == found
