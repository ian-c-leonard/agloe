"""OFFERs: a right that can still be bought counts, and a plan that takes one gets a WARNING."""

from collections.abc import Sequence
from itertools import combinations
from random import Random
from typing import cast

import pytest

from agloe import answers, compiler, report
from agloe.answers import Answer, Cover
from agloe.file import CompleteRights, File, FileError, Offer
from agloe.reference import (
    Broken,
    Constraint,
    Itinerary,
    Remaining,
    Step,
    Unknown,
    best_case,
    broken,
    first_shown,
    longest_case,
    with_no_offer,
    with_these_at_best,
    worst_case,
)
from tests.stories import (
    Document,
    booking,
    cutoff,
    every_right,
    lasts,
    lasts_between,
    lock,
    must,
    needs_no_right,
    needs_right,
    offer,
    satisfies,
    seconds,
    starts_at,
    stays,
    trip,
)
from tests.test_cross_check import random_trip, works_on_the_grid
from tests.test_rights import every_world_of_rights
from tests.test_where_a_path_ends import checked, has_no_record_to_spare, ruled_out

EVERYONE = ["alex", "sam", "jo"]
TIMES = ("tour-time", "tour-length", "tour-cutoff")


def at_ten(option: str) -> list[Document]:
    """An OPTION that starts at 10:00 am, with nothing left unknown about its time."""
    return [starts_at(option, 10), lasts(option, "PT1H"), cutoff(option, "PT0S")]


def a_boat_tour(*more: Document, locked: Sequence[str] = ("alex", "sam")) -> File:
    """A boat tour at 10:00 am that needs a right. A LOCK names Alex and Sam."""
    decisions = [lock("tour", *locked)] if locked else []
    facts = [*at_ten("tour"), needs_right("tour"), *more]
    return trip(EVERYONE, ["dock"], [stays("tour", "dock")], facts, decisions, tickets=True)


def on_the_tour(*persons: str) -> Itinerary:
    return (Step("tour", "dock", "dock", persons, seconds(10), seconds(11)),)


def right(option: str, person: str) -> Unknown:
    return Unknown("another right", option, person=person)


def asked(found: answers.Report) -> list[list[Unknown]]:
    return [[needed.unknown for needed in enough] for enough in found.missing]


def in_words(file: File) -> list[str]:
    return report.as_text(file, checked(file)).splitlines()


def problems(*facts: Document) -> str:
    with pytest.raises(FileError) as refused:
        a_boat_tour(*facts)
    return str(refused.value)


# ------------------------------- What a FILE holds -------------------------------


def test_an_offer_has_places_for_one_option() -> None:
    file = a_boat_tour(offer("tour", 2), offer("tour", 1, id="more"))
    assert file.offers("tour") == (Offer("tour-offer", "tour", 2), Offer("more", "tour", 1))
    assert file.places_on_offer("tour") == 3
    assert a_boat_tour().places_on_offer("tour") == 0


def test_an_offer_is_checked_like_every_other_fact() -> None:
    assert problems(offer("cruise", 1)) == "/facts/4: cruise is not an OPTION in this FILE"
    assert problems(offer("tour", 0)).endswith("0 is less than the minimum of 1")
    half = offer("tour", 1)
    half["offer"]["places"] = 1.5
    assert problems(half).endswith("1.5 is not of type 'integer'")


def test_a_complete_set_of_rights_names_the_offers_that_are_still_open() -> None:
    file = a_boat_tour(offer("tour", 1), every_right("tour", "tour-offer"))
    assert file.rights_complete("tour") == CompleteRights(
        "every-right-to-tour", "tour", ("tour-offer",)
    )
    unnamed = "/facts/4: the rights to tour are COMPLETE, and that FACT does not name this OFFER"
    assert problems(offer("tour", 1), every_right("tour")) == unnamed
    assert problems(every_right("tour"), offer("tour", 1)) == unnamed.replace("/4", "/5")
    assert problems(every_right("tour", "nothing")) == "/facts/4: nothing is not an OFFER for tour"
    not_one = "/facts/5: tour-booking is not an OFFER for tour"
    assert problems(booking("tour", "alex"), every_right("tour", "tour-booking")) == not_one
    twice = [offer("tour", 1), every_right("tour", "tour-offer", "tour-offer")]
    assert problems(*twice).endswith("has non-unique elements")


def test_an_offer_for_another_option_is_not_one_for_this_option() -> None:
    options = [stays("tour", "dock"), stays("cruise", "dock")]
    facts = [offer("cruise", 1), every_right("tour", "cruise-offer")]
    with pytest.raises(FileError, match="/facts/1: cruise-offer is not an OFFER for tour"):
        trip(["alex"], ["dock"], options, facts, [], tickets=True)


# ------------------------------- The CONSTRAINT -------------------------------


def test_a_place_serves_one_person() -> None:
    file = a_boat_tour(booking("tour", "alex"), offer("tour", 1), locked=())
    worst = worst_case(file)
    assert broken(file, worst, on_the_tour("alex", "sam")) == []
    assert broken(file, worst, on_the_tour("jo")) == []
    left_out = [Broken(Constraint.RIGHT, "tour", ("jo",))]
    assert broken(file, worst, on_the_tour("jo", "alex", "sam")) == left_out
    assert broken(file, best_case(file), on_the_tour("jo", "alex", "sam")) == []


def test_the_places_of_two_offers_add_up() -> None:
    file = a_boat_tour(offer("tour", 1), offer("tour", 1, id="more"), locked=())
    assert broken(file, worst_case(file), on_the_tour("alex", "sam")) == []
    left_out = [Broken(Constraint.RIGHT, "tour", ("jo",))]
    assert broken(file, worst_case(file), on_the_tour(*EVERYONE)) == left_out


def test_a_place_is_for_its_own_option_only() -> None:
    options = [stays("tour", "dock"), stays("cruise", "dock")]
    facts = [*at_ten("tour"), needs_right("tour"), needs_right("cruise"), offer("cruise", 3)]
    file = trip(["alex"], ["dock"], options, facts, [], tickets=True)
    left_out = [Broken(Constraint.RIGHT, "tour", ("alex",))]
    assert broken(file, worst_case(file), on_the_tour("alex")) == left_out


def test_a_world_with_no_offer_has_no_place_to_take() -> None:
    file = a_boat_tour(offer("tour", 2), locked=())
    worst = worst_case(file)
    assert worst.places == {"tour": 2}
    assert with_no_offer(worst).places == {}
    assert broken(file, with_no_offer(worst), on_the_tour("alex")) == [
        Broken(Constraint.RIGHT, "tour", ("alex",))
    ]


# ------------------------------- The answers and the WARNING -------------------------------


def test_a_plan_that_takes_a_place_works_and_gets_a_warning() -> None:
    file = a_boat_tour(booking("tour", "alex"), offer("tour", 2))
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert found.robust is True
    assert found.rights == (
        Cover("tour", "alex", "tour-booking", False),
        Cover("tour", "sam", "tour-offer", True),
    )
    assert found.relies_on == (
        *TIMES,
        "tour-needs-right",
        "tour-booking",
        "tour-offer",
        "lock-tour",
    )
    words = in_words(file)
    assert (
        words[0] == "FEASIBLE, with a WARNING: this trip works, but not everything is booked yet."
    )
    assert words[4] == "    ! sam still has to buy a right to this, from tour-offer."
    assert words[6] == (
        'WARNING: not everything is booked yet. A line marked "!" that names an OFFER says who'
        " still has to buy a right. Only a BOOKING secures one."
    )
    assert "  tour-offer: an OFFER has 2 places for tour that can still be bought" in words
    as_json = report.as_json(file, found)
    assert as_json["to_buy"] == [{"option": "tour", "offer": "tour-offer", "persons": ["sam"]}]
    steps = cast("list[dict[str, object]]", as_json["itinerary"])
    assert steps[0]["rights"] == {"alex": "tour-booking", "sam": "tour-offer"}


def test_a_plan_with_a_booking_for_everybody_gets_no_warning() -> None:
    file = a_boat_tour(booking("tour", "alex", "sam"), offer("tour", 2))
    found = checked(file)
    assert [cover.to_buy for cover in found.rights] == [False, False]
    assert found.relies_on == (*TIMES, "tour-needs-right", "tour-booking", "lock-tour")
    assert in_words(file)[0] == "FEASIBLE: this trip works."
    assert "to_buy" not in report.as_json(file, found)


def test_the_persons_who_take_part_take_the_places_in_the_files_order() -> None:
    """Alex comes first in the FILE and stays ashore. The places go to those who take part."""
    offers = [offer("tour", 1, id="first"), offer("tour", 1, id="second")]
    file = a_boat_tour(*offers, locked=("sam", "jo"))
    found = checked(file)
    assert found.rights == (
        Cover("tour", "sam", "first", True),
        Cover("tour", "jo", "second", True),
    )
    words = in_words(file)
    assert words[4:6] == [
        "    ! sam still has to buy a right to this, from first.",
        "    ! jo still has to buy a right to this, from second.",
    ]
    one = a_boat_tour(offer("tour", 2), locked=("sam", "jo"))
    assert (
        in_words(one)[4] == "    ! sam and jo still have to buy a right to this, from tour-offer."
    )


def test_a_right_has_to_be_bought_only_if_the_option_needs_one() -> None:
    """Nobody knows whether the tour needs a right. The plan holds either way."""
    facts = [*at_ten("tour"), offer("tour", 2)]
    locks = [lock("tour", "alex", "sam")]
    file = trip(EVERYONE, ["dock"], [stays("tour", "dock")], facts, locks, tickets=True)
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert found.relies_on == (*TIMES, "tour-offer", "lock-tour")
    mark = "    ! alex and sam still have to buy a right to this if it needs one, from tour-offer."
    assert in_words(file)[4] == mark


def test_an_option_that_needs_no_right_takes_no_place() -> None:
    facts = [*at_ten("tour"), needs_no_right("tour"), offer("tour", 2)]
    locks = [lock("tour", "alex", "sam")]
    file = trip(EVERYONE, ["dock"], [stays("tour", "dock")], facts, locks, tickets=True)
    found = checked(file)
    assert found.rights == ()
    assert found.relies_on == (*TIMES, "tour-open", "lock-tour")
    assert in_words(file)[0] == "FEASIBLE: this trip works."


def two_views(deck: Document | None = None, tower: Document | None = None) -> File:
    """A view is a must for Alex. The deck is listed first and has a place on OFFER.

    Alex has a BOOKING for the tower. Both start at 10:00 am and take half an hour, unless
    told otherwise. Lunch at 11:00 am is LOCKed.
    """
    options = [stays("deck", "loop"), stays("tower", "loop"), stays("lunch", "loop")]
    facts = [starts_at("deck", 10), deck or lasts("deck", "PT30M"), cutoff("deck", "PT0S")]
    facts += [starts_at("tower", 10), tower or lasts("tower", "PT30M"), cutoff("tower", "PT0S")]
    facts += [starts_at("lunch", 11), lasts("lunch", "PT1H"), cutoff("lunch", "PT0S")]
    facts += [satisfies("deck", "view"), satisfies("tower", "view")]
    facts += [needs_right("deck"), needs_right("tower"), needs_no_right("lunch")]
    facts += [offer("deck", 1), booking("tower", "alex")]
    wants = [must("view", "alex")]
    return trip(
        ["alex"], ["loop"], options, facts, [lock("lunch", "alex")], wants=wants, tickets=True
    )


def test_a_plan_that_is_fully_booked_comes_before_one_that_takes_a_place() -> None:
    """The deck is listed first, but only the tower is booked."""
    file = two_views()
    found = checked(file)
    assert [step.option for step in found.itinerary] == ["tower", "lunch"]
    assert [cover.to_buy for cover in found.rights] == [False]
    assert "deck-offer" not in found.relies_on
    assert in_words(file)[0] == "FEASIBLE: this trip works."


def test_a_robust_plan_that_takes_a_place_comes_before_a_booked_one_that_may_run_late() -> None:
    """The tower can take until 11:15 am, when lunch has started. The deck is over at 10:30 am."""
    file = two_views(tower=lasts_between("tower", "PT45M", "PT1H15M"))
    found = checked(file)
    assert [step.option for step in found.itinerary] == ["deck", "lunch"]
    assert found.robust is True
    assert found.rights == (Cover("deck", "alex", "deck-offer", True),)
    words = in_words(file)
    assert (
        words[0] == "FEASIBLE, with a WARNING: this trip works, but not everything is booked yet."
    )
    assert words[4] == "    ! alex still has to buy a right to this, from deck-offer."


def test_a_booked_plan_comes_before_one_that_takes_a_place_where_neither_is_robust() -> None:
    """Both can take until 11:15 am. The tower is booked, so it is the one shown."""
    until_late = "PT1H15M"
    file = two_views(
        deck=lasts_between("deck", "PT30M", until_late),
        tower=lasts_between("tower", "PT45M", until_late),
    )
    found = checked(file)
    assert found.robust is False
    assert [step.option for step in found.itinerary] == ["tower", "lunch"]
    assert [cover.to_buy for cover in found.rights] == [False]
    assert in_words(file)[0].startswith("FEASIBLE, with a WARNING: this trip can work")


def test_a_report_can_give_both_warnings() -> None:
    options = [stays("swim", "dock"), stays("tour", "dock")]
    facts = [starts_at("swim", 9), lasts_between("swim", "PT30M", "PT2H"), cutoff("swim", "PT0S")]
    facts += [*at_ten("tour"), needs_no_right("swim"), needs_right("tour"), offer("tour", 1)]
    locks = [lock("swim", "alex"), lock("tour", "alex")]
    file = trip(["alex"], ["dock"], options, facts, locks, tickets=True)
    found = checked(file)
    assert found.robust is False
    assert found.rights == (Cover("tour", "alex", "tour-offer", True),)
    words = in_words(file)
    assert words[0].startswith("FEASIBLE, with a WARNING: this trip can work")
    assert words[5:7] == [
        "    ! alex still has to buy a right to this, from tour-offer.",
        "    ! alex would still be busy for 1 h when this starts.",
    ]
    assert sum(line.startswith("WARNING:") for line in words) == 2


def test_too_few_places_make_a_trip_infeasible_where_the_rights_are_complete() -> None:
    file = a_boat_tour(
        booking("tour", "alex"),
        offer("tour", 1),
        every_right("tour", "tour-offer"),
        locked=EVERYONE,
    )
    found = checked(file)
    assert found.answer is Answer.INFEASIBLE
    conflict = (
        "tour-needs-right",
        "tour-booking",
        "tour-offer",
        "every-right-to-tour",
        "lock-tour",
    )
    assert found.conflict == conflict
    assert has_no_record_to_spare(file, conflict)
    whole = "nobody on the trip holds another or can get one, except from tour-offer"
    assert (
        in_words(file)[-2] == f"  every-right-to-tour: the FILE lists every right to tour: {whole}"
    )


def test_a_conflict_holds_every_offer_for_the_option() -> None:
    offers = [offer("tour", 1, id="first"), offer("tour", 1, id="second")]
    file = a_boat_tour(*offers, every_right("tour", "first", "second"), locked=EVERYONE)
    found = checked(file)
    conflict = ("tour-needs-right", "first", "second", "every-right-to-tour", "lock-tour")
    assert found.conflict == conflict
    assert has_no_record_to_spare(file, conflict)


def test_enough_places_work_though_the_rights_are_complete() -> None:
    file = a_boat_tour(booking("tour", "alex"), offer("tour", 1), every_right("tour", "tour-offer"))
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert found.rights[1] == Cover("tour", "sam", "tour-offer", True)


def test_an_offer_that_is_taken_out_might_have_a_place_for_everybody() -> None:
    file = a_boat_tour(
        booking("tour", "alex"),
        offer("tour", 1),
        every_right("tour", "tour-offer"),
        locked=EVERYONE,
    )
    left = Remaining(file).without("tour-offer")
    assert left.open_to_all == {"tour"}
    assert ruled_out(Remaining(file)) and not ruled_out(left)
    assert compiler.stuck(left) is None


def test_another_right_is_asked_for_as_far_as_the_places_run_out() -> None:
    """One place and two PERSONs with no right: either can take it, so there are two sets."""
    file = a_boat_tour(booking("tour", "alex"), offer("tour", 1), locked=EVERYONE)
    found = checked(file)
    assert asked(found) == [[right("tour", "sam")], [right("tour", "jo")]]
    assert in_words(file)[-1] == "The trip works if a right to tour is found for one of sam and jo."
    assert len(cast("list[object]", report.as_json(file, found)["missing"])) == 2


def test_the_words_say_how_many_of_a_group_need_a_right() -> None:
    people = ["alex", "sam", "jo", "pat", "kim"]
    facts = [starts_at("tour", 10), lasts("tour", "PT1H"), needs_right("tour"), offer("tour", 2)]
    file = trip(
        people, ["dock"], [stays("tour", "dock")], facts, [lock("tour", *people)], tickets=True
    )
    sets = asked(checked(file))
    assert len(sets) == 10
    assert all(len(some) == 3 for some in sets)
    assert in_words(file)[-1] == (
        "The trip works if a right to tour is found for 3 of alex, sam, jo, pat and kim."
    )


def test_a_lock_asks_that_its_option_needs_no_right_only_where_the_places_run_out() -> None:
    def tour_with(places: int) -> File:
        facts = [*at_ten("tour"), offer("tour", places)]
        locks = [lock("tour", "alex", "sam"), {"id": "lock-jo", "lock": "tour", "persons": ["jo"]}]
        return trip(EVERYONE, ["dock"], [stays("tour", "dock")], facts, locks, tickets=True)

    free = Unknown("needs no right", "tour")
    assert answers._asked_by_a_lock(tour_with(3)) == frozenset()  # pyright: ignore[reportPrivateUsage]
    assert checked(tour_with(3)).answer is Answer.FEASIBLE
    assert answers._asked_by_a_lock(tour_with(2)) == {free}  # pyright: ignore[reportPrivateUsage]
    assert asked(checked(tour_with(2))) == [[free]]


# ------------------------------- Against every possible world -------------------------------


def two_tours_with_offers(rng: Random) -> File:
    """Two OPTIONs at one PLACE with every time stated. Only rights are unknown.

    Some take a quarter of an hour or half an hour, as the world decides.
    """
    persons = ["alex", "sam", "jo"] if rng.random() < 0.6 else ["alex", "sam"]
    options = [stays("tour", "dock"), stays("cruise", "dock")]
    facts: list[Document] = []
    decisions: list[Document] = []
    for option in ("tour", "cruise"):
        length = lasts(option, "PT15M")
        if rng.random() < 0.4:
            length = lasts_between(option, "PT15M", "PT30M")
        facts += [starts_at(option, 9, 15 * rng.randrange(3)), length, cutoff(option, "PT0S")]
        stated = rng.choice([needs_right(option), needs_right(option), needs_right(option), None])
        if stated is not None:
            facts.append(stated)
        if rng.random() < 0.5:
            covered = rng.sample(persons, rng.randrange(1, len(persons)))
            facts.append(booking(option, *covered))
        offers = [f"{option}-offer-{number}" for number in range(rng.choice([0, 1, 1, 2]))]
        facts += [offer(option, rng.choice([1, 1, 2]), id=name) for name in offers]
        if rng.random() < 0.5:
            facts.append(every_right(option, *offers))
        if rng.random() < 0.8:
            decisions.append(lock(option, *rng.sample(persons, rng.randrange(1, len(persons) + 1))))
    return trip(persons, ["dock"], options, facts, decisions, tickets=True)


def test_the_three_answers_hold_for_every_way_rights_could_turn_out_with_offers() -> None:
    """FEASIBLE: one choice works in every world. INFEASIBLE: no choice works in any."""
    rng = Random(6060)
    seen: set[Answer] = set()
    took_a_place = 0
    for _ in range(150):
        file = two_tours_with_offers(rng)
        worlds = every_world_of_rights(file)
        found = checked(file)
        seen.add(found.answer)
        took_a_place += any(cover.to_buy for cover in found.rights)
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
    assert took_a_place > 10


def test_the_plan_shown_and_what_covers_whom_follow_the_rules_on_random_trips() -> None:
    """The first of the four steps with a plan decides, and no place is taken twice."""
    rng = Random(7070)
    steps_seen: set[int] = set()
    for number in range(700):
        if number % 2:
            file = two_tours_with_offers(rng)
        else:
            file = random_trip(rng, 0.1, contingent=0.5, with_wants=0.5, with_rights=0.4)
        found = compiler.check(file)
        if found.answer is not Answer.FEASIBLE:
            continue
        worst, longest = worst_case(file), longest_case(file)
        worlds = [with_no_offer(longest), longest, with_no_offer(worst), worst]
        plans = [first_shown(file, world) for world in worlds]
        step = next(number for number, plan in enumerate(plans) if plan is not None)
        steps_seen.add(step)
        assert found.itinerary == plans[step]
        assert found.robust is (step < 2)
        assert any(cover.to_buy for cover in found.rights) is (step in (1, 3))
        for each in found.itinerary:
            if each.option is None or file.needs_right(each.option) is False:
                continue
            covers = [cover for cover in found.rights if cover.option == each.option]
            assert [cover.person for cover in covers] == [
                person.id for person in file.persons if person.id in each.persons
            ]
            for cover in covers:
                booked = file.booking(each.option, cover.person)
                assert cover.to_buy is (booked is None)
                assert booked is None or cover.by == booked.id
            for listed in file.offers(each.option):
                assert sum(cover.by == listed.id for cover in covers) <= listed.places
    assert steps_seen == {0, 1, 2, 3}


def test_several_sets_that_differ_only_in_who_gets_a_right_are_every_way_to_pick_them() -> None:
    """The one sentence a report prints for them says no more and no less than the sets."""
    people = ["alex", "sam", "jo", "pat"]
    facts = [*at_ten("tour"), needs_right("tour"), offer("tour", 1)]
    file = trip(
        people, ["dock"], [stays("tour", "dock")], facts, [lock("tour", *people)], tickets=True
    )
    found = checked(file)
    expected = [[right("tour", person) for person in three] for three in combinations(people, 3)]
    assert asked(found) == expected
    assert in_words(file)[-1] == (
        "The trip works if a right to tour is found for 3 of alex, sam, jo and pat."
    )
