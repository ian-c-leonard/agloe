"""OFFERs: a right that can still be bought counts, and a plan that takes one gets a WARNING."""

import json
from collections.abc import Sequence
from decimal import Decimal
from itertools import combinations
from pathlib import Path
from random import Random
from typing import cast

import pytest

from agloe import answers, compiler, report
from agloe.answers import Answer, Cover
from agloe.file import CompleteRights, File, FileError, Money, Offer, load, read
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
    first_shown,
    longest_case,
    with_no_offer,
    with_these_at_best,
    worst_case,
)
from tests.stories import (
    Document,
    booking,
    budget,
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
    trip_ends,
)
from tests.test_cross_check import random_trip, works_on_the_grid
from tests.test_rights import every_world_of_rights
from tests.test_where_a_path_ends import (
    checked,
    has_no_record_to_spare,
    ruled_out,
    the_solver_rules_out,
)

EVERYONE = ["alex", "sam", "jo"]
TIMES = ("tour-time", "tour-length", "tour-cutoff")


def at_ten(option: str) -> list[Document]:
    """An OPTION that starts at 10:00 am, with nothing left unknown about its time."""
    return [starts_at(option, 10), lasts(option, "PT1H"), cutoff(option, "PT0S")]


def a_boat_tour(*more: Document, locked: Sequence[str] = ("alex", "sam")) -> File:
    """A boat tour at 10:00 am that needs a right. A LOCK names Alex and Sam."""
    decisions = [lock("tour", *locked)] if locked else []
    facts = [*at_ten("tour"), needs_right("tour"), *more]
    return trip(EVERYONE, ["dock"], [stays("tour", "dock")], facts, decisions, rights=True)


TEN = Money(Decimal("10.00"), "USD")


def bought(option: str, person: str, offer: str) -> Cover:
    """A place of an OFFER that a PERSON takes, at ten dollars from the BUDGET called money."""
    return Cover(option, person, offer, True, TEN, "money")


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
    assert file.offers("tour") == (
        Offer("tour-offer", "tour", 2, TEN),
        Offer("more", "tour", 1, TEN),
    )
    assert file.places_on_offer("tour") == 3
    assert a_boat_tour().places_on_offer("tour") == 0


def test_an_offer_is_checked_like_every_other_fact() -> None:
    assert problems(offer("cruise", 1)) == "/facts/4: cruise is not an OPTION in this FILE"
    assert problems(offer("tour", 0)).endswith("0 is less than the minimum of 1")
    half = offer("tour", 1)
    half["offer"]["places"] = 1.5
    assert problems(half).endswith("1.5 is not of type 'integer'")
    only_offers = {"id": "all", "complete": {"offers": ["tour-offer"]}}
    assert problems(offer("tour", 1), only_offers).endswith("'rights_to' is a required property")


def test_the_places_of_an_offer_read_the_same_however_the_number_is_written(tmp_path: Path) -> None:
    """A hundred million places can be written three ways. A thousand million is too many."""
    document = json.dumps(
        {
            "persons": [],
            "places": [{"id": "dock", "name": "dock"}],
            "options": [{"id": "tour", "name": "tour", "place": "dock"}],
            "ways": [],
            "wants": [],
            "facts": [{"id": "tour-offer", "offer": {"option": "tour", "places": 12345}}],
            "decisions": [],
        }
    )
    path = tmp_path / "trip.json"
    for written in ("100000000", "1e8", "100000000.0"):
        path.write_text(document.replace("12345", written))
        assert read(path).places_on_offer("tour") == 100_000_000
    for written in ("1000000000", "1e9", "1000000000.0"):
        path.write_text(document.replace("12345", written))
        with pytest.raises(FileError, match="1000000000 is greater than the maximum of 999999999"):
            read(path)


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
        trip(["alex"], ["dock"], options, facts, [], rights=True)


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
    file = trip(["alex"], ["dock"], options, facts, [], rights=True)
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
        bought("tour", "sam", "tour-offer"),
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
    paid = "for 10.00 USD from money"
    assert words[4] == f"    ! sam still has to buy a right to this, from tour-offer, {paid}."
    assert words[6] == (
        'WARNING: not everything is booked yet. A line marked "!" that names an OFFER says who'
        " still has to buy a right. Only a BOOKING secures one."
    )
    offered = "an OFFER has 2 places for tour that can still be bought, for 10.00 USD each"
    assert f"  tour-offer: {offered}" in words
    as_json = report.as_json(file, found)
    assert as_json["to_buy"] == [
        {
            "option": "tour",
            "offer": "tour-offer",
            "persons": ["sam"],
            "only_if_needed": False,
            "price": {"amount": "10.00", "currency": "USD"},
            "budget": "money",
        }
    ]
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
        bought("tour", "sam", "first"),
        bought("tour", "jo", "second"),
    )
    words = in_words(file)
    assert words[4:6] == [
        "    ! sam still has to buy a right to this, from first, for 10.00 USD from money.",
        "    ! jo still has to buy a right to this, from second, for 10.00 USD from money.",
    ]
    one = a_boat_tour(offer("tour", 2), locked=("sam", "jo"))
    assert (
        in_words(one)[4]
        == "    ! sam and jo still have to buy a right to this, from tour-offer, for 10.00 USD each"
        " from money."
    )


def test_a_right_has_to_be_bought_only_if_the_option_needs_one() -> None:
    """Nobody knows whether the tour needs a right. The plan holds either way."""
    facts = [*at_ten("tour"), offer("tour", 2)]
    locks = [lock("tour", "alex", "sam")]
    file = trip(EVERYONE, ["dock"], [stays("tour", "dock")], facts, locks, rights=True)
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert found.relies_on == (*TIMES, "tour-offer", "lock-tour")
    mark = (
        "    ! alex and sam still have to buy a right to this if it needs one, from tour-offer, for"
        " 10.00 USD each from money."
    )
    assert in_words(file)[4] == mark
    to_buy = cast("list[dict[str, object]]", report.as_json(file, found)["to_buy"])
    assert [each["only_if_needed"] for each in to_buy] == [True]


def test_an_option_that_needs_no_right_takes_no_place() -> None:
    facts = [*at_ten("tour"), needs_no_right("tour"), offer("tour", 2)]
    locks = [lock("tour", "alex", "sam")]
    file = trip(EVERYONE, ["dock"], [stays("tour", "dock")], facts, locks, rights=True)
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
        ["alex"], ["loop"], options, facts, [lock("lunch", "alex")], wants=wants, rights=True
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
    assert found.rights == (bought("deck", "alex", "deck-offer"),)
    words = in_words(file)
    assert (
        words[0] == "FEASIBLE, with a WARNING: this trip works, but not everything is booked yet."
    )
    assert words[4] == (
        "    ! alex still has to buy a right to this, from deck-offer, for 10.00 USD from money."
    )


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
    file = trip(["alex"], ["dock"], options, facts, locks, rights=True)
    found = checked(file)
    assert found.robust is False
    assert found.rights == (bought("tour", "alex", "tour-offer"),)
    words = in_words(file)
    assert words[0].startswith("FEASIBLE, with a WARNING: this trip can work")
    assert words[5:7] == [
        "    ! alex still has to buy a right to this, from tour-offer, for 10.00 USD from money.",
        "    ! alex would still be busy for 1 h when this starts.",
    ]
    assert [line for line in words if line.startswith("WARNING:")] == [
        "WARNING: no plan is sure to hold if the uncertain parts take their longest. Each line"
        ' marked "!" that names no OFFER says what would go wrong at the step above it.',
        'WARNING: not everything is booked yet. A line marked "!" that names an OFFER says who'
        " still has to buy a right. Only a BOOKING secures one.",
    ]


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
    assert (
        in_words(file)[-3]
        == "  tour-offer: an OFFER has 1 place for tour that can still be bought, for 10.00 USD"
    )
    whole = "nobody on the trip holds another or can get one, except from tour-offer"
    assert (
        in_words(file)[-2] == f"  every-right-to-tour: the FILE lists every right to tour: {whole}"
    )


def test_each_case_says_everything_its_set_holds() -> None:
    """Alex and Sam are LOCKed into a tour at 10:00 am, and the TRIP ends at 11:00 am.

    Nobody knows how long the tour takes, and one place is on OFFER. Each set holds the length
    of the tour and a right for one of the two. The length has to fit, so stating it is not
    enough, and the words of each case say so.
    """
    facts = [starts_at("tour", 10), cutoff("tour", "PT0S"), needs_right("tour"), offer("tour", 1)]
    decisions = [lock("tour", "alex", "sam"), trip_ends(11)]
    file = trip(EVERYONE, ["dock"], [stays("tour", "dock")], facts, decisions, rights=True)
    length = Unknown("duration", "tour")
    assert asked(checked(file)) == [[length, right("tour", "alex")], [length, right("tour", "sam")]]
    more = "in addition to the 1 place on OFFER"
    assert in_words(file)[-3:] == [
        "The trip works in any of these cases:",
        f"  1. tour is quick enough and a right to tour is found for alex, {more}.",
        f"  2. tour is quick enough and a right to tour is found for sam, {more}.",
    ]


def test_a_shortage_among_many_locked_persons_takes_few_searches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ten PERSONs are LOCKed in and one place is on OFFER. Nine of them need another right.

    A set with fewer rights cannot be enough, so the search is not asked about one. Fourteen
    more PERSONs have nothing to do, and nothing is known about the swim, which nobody has to
    take. Their unknown FACTs make up no set either, and no set with them is even made.
    """
    people = [f"person-{number}" for number in range(10)]
    idle = [f"idle-{number}" for number in range(14)]
    facts = [*at_ten("tour"), needs_right("tour"), offer("tour", 1)]
    options = [stays("tour", "dock"), stays("swim", "dock")]
    file = trip([*people, *idle], ["dock"], options, facts, [lock("tour", *people)], rights=True)
    calls = 0
    solver = compiler.works

    def counted(file: File, world: World, asked: object = None) -> bool:
        nonlocal calls
        calls += 1
        return solver(file, world, asked)  # pyright: ignore[reportArgumentType]

    monkeypatch.setattr(compiler, "works", counted)
    found = compiler.check(file)
    assert len(found.missing) == 10
    assert all(len(enough) == 9 for enough in found.missing)
    assert calls < 20


def test_only_the_sets_with_enough_of_each_group_are_made() -> None:
    """The picks are those a search of every pick would keep, each made once."""
    facts = [right("tour", f"person-{number}") for number in range(6)]
    facts += [Unknown("start", "tour"), Unknown("cutoff", "tour")]
    groups = [(frozenset(facts[:3]), 2), (frozenset(facts[3:5]), 1)]
    for size in range(8):
        made = list(answers._with_enough_of_each(facts, groups, size))  # pyright: ignore[reportPrivateUsage]
        kept = [
            pick
            for pick in combinations(facts, size)
            if all(len(group.intersection(pick)) >= number for group, number in groups)
        ]
        assert len(made) == len(kept)
        assert {frozenset(pick) for pick in made} == {frozenset(pick) for pick in kept}
    assert list(answers._with_enough_of_each(facts, [], 2)) == list(combinations(facts, 2))  # pyright: ignore[reportPrivateUsage]


def test_a_thousand_groups_are_picked_from_without_going_deeper_each_time() -> None:
    """A thousand LOCKed visits that each need one more right give one pick of a thousand FACTs."""
    rights = [right(f"visit-{number}", "alex") for number in range(1200)]
    groups = [(frozenset({each}), 1) for each in rights]
    picks = list(answers._with_enough_of_each(rights, groups, len(rights)))  # pyright: ignore[reportPrivateUsage]
    assert [set(pick) for pick in picks] == [set(rights)]


def named(*names: str) -> list[Document]:
    return [{"id": f"person-{number}", "name": name} for number, name in enumerate(names)]


def test_a_name_that_a_list_could_split_in_two_is_shown_in_quotes() -> None:
    """Two FILEs have the same four names in a row, split in different places.

    A LOCK names three of the four in each, and they still have to buy a right. The words
    tell the two apart.
    """

    def words(*names: str) -> str:
        document: Document = {
            "persons": named(*names),
            "places": [{"id": "dock", "name": "dock"}],
            "budgets": [budget("money", *(f"person-{number}" for number in range(len(names))))],
            "options": [stays("tour", "dock")],
            "ways": [],
            "wants": [],
            "facts": [*at_ten("tour"), needs_right("tour"), offer("tour", 3)],
            "decisions": [lock("tour", "person-0", "person-1", "person-2")],
        }
        file = load(document)
        return report.as_text(file, checked(file)).splitlines()[4]

    buy = "still have to buy a right to this, from tour-offer, for 10.00 USD each from money."
    one = words("Lee, Gray", "Lee", "Sam", "Jo")
    other = words("Lee", "Gray, Lee", "Sam", "Jo")
    assert one == f'    ! "Lee, Gray", Lee and Sam {buy}'
    assert other == f'    ! Lee, "Gray, Lee" and Sam {buy}'
    capital = words("Sam And Jo", "Lee", "Kim", "Pat")
    assert capital.startswith('    ! "Sam And Jo", Lee and Kim')
    with_an_id = words("Lee (person-1)", "Lee", "Kim", "Pat")
    assert with_an_id.startswith('    ! "Lee (person-1)", Lee and Kim still have to buy')
    assert words("Lee", "Lee", "Kim", "Pat").startswith(
        "    ! Lee (person-0), Lee (person-1) and Kim"
    )
    # The quotes go on before the id: the first two share a name, and the third mimics one.
    alike = words("Lee and Jo", "Lee and Jo", "Lee and Jo (person-0)", "Sam")
    assert alike.startswith(
        '    ! "Lee and Jo" (person-0), "Lee and Jo" (person-1) and "Lee and Jo (person-0)" still'
    )
    pair = words("Sam and Jo", 'the "Duke"', "Lee", "Kim")
    assert pair.startswith('    ! "Sam and Jo", "the \\"Duke\\"" and Lee still have to buy')


def test_a_list_joined_with_and_shows_a_name_that_holds_and_in_quotes() -> None:
    """One OPTION called River and Walk, or two called River and Walk: the words differ.

    Calm is a must for Jo, the FILE states every OPTION that gives it, and Jo has a right to
    none of them. So the conflict names the COMPLETE set, with its OPTIONs.
    """

    def record(*names: str) -> str:
        ids = [f"option-{number}" for number in range(len(names))]
        facts = [fact for id in ids for fact in at_ten(id)]
        facts += [fact for id in ids for fact in (needs_right(id), every_right(id))]
        facts += [satisfies(id, "calm") for id in ids]
        document: Document = {
            "persons": named("Jo"),
            "places": [{"id": "dock", "name": "dock"}],
            "options": [
                {"id": id, "name": name, "place": "dock"}
                for id, name in zip(ids, names, strict=True)
            ],
            "ways": [],
            "wants": [must("calm", "person-0")],
            "facts": [*facts, {"id": "every-calm", "complete": {"satisfies": "calm"}}],
            "decisions": [],
        }
        file = load(document)
        found = checked(file)
        assert found.answer is Answer.INFEASIBLE
        lines = report.as_text(file, found).splitlines()
        return next(line for line in lines if line.startswith("  every-calm: "))

    one = "  every-calm: the FILE states every OPTION that SATISFIES calm: "
    assert record("River and Walk") == one + '"River and Walk"'
    assert record("River", "Walk") == one + "River and Walk"


def test_a_booking_that_covers_more_persons_than_the_plan_needs_says_whom_it_is_used_for() -> None:
    first = booking("tour", "alex", id="first")
    second = booking("tour", "alex", "sam", "jo", id="second")
    file = a_boat_tour(first, second)
    words = in_words(file)
    assert "  first: a BOOKING for tour covers alex" in words
    assert (
        "  second: a BOOKING for tour covers alex, sam and jo; this plan uses it for sam" in words
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
    assert found.rights[1] == bought("tour", "sam", "tour-offer")


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
    assert the_solver_rules_out(Remaining(file)) and not the_solver_rules_out(left)


def test_another_right_is_asked_for_as_far_as_the_places_run_out() -> None:
    """One place and two PERSONs with no right: either can take it, so there are two sets."""
    file = a_boat_tour(booking("tour", "alex"), offer("tour", 1), locked=EVERYONE)
    found = checked(file)
    assert asked(found) == [[right("tour", "sam")], [right("tour", "jo")]]
    assert in_words(file)[-2:] == [
        "  1. A right to tour is found for sam, in addition to the 1 place on OFFER.",
        "  2. A right to tour is found for jo, in addition to the 1 place on OFFER.",
    ]
    assert len(cast("list[object]", report.as_json(file, found)["missing"])) == 2


def test_each_way_to_pick_the_persons_who_need_a_right_is_a_case() -> None:
    people = ["alex", "sam", "jo", "pat"]
    facts = [*at_ten("tour"), needs_right("tour"), offer("tour", 2)]
    file = trip(
        people, ["dock"], [stays("tour", "dock")], facts, [lock("tour", *people)], rights=True
    )
    pairs = [[right("tour", one), right("tour", other)] for one, other in combinations(people, 2)]
    assert asked(checked(file)) == pairs
    words = in_words(file)
    assert len(words) == 3 + len(pairs)
    assert words[3] == (
        "  1. A right to tour is found for each of alex and sam, in addition to the 2 places on"
        " OFFER."
    )


def test_a_lock_asks_that_its_option_needs_no_right_only_where_the_places_run_out() -> None:
    def tour_with(places: int) -> File:
        facts = [*at_ten("tour"), offer("tour", places)]
        locks = [lock("tour", "alex", "sam"), {"id": "lock-jo", "lock": "tour", "persons": ["jo"]}]
        return trip(EVERYONE, ["dock"], [stays("tour", "dock")], facts, locks, rights=True)

    free = Unknown("needs no right", "tour")
    assert answers._asked_by_a_lock(tour_with(3)) == (frozenset(), [])  # pyright: ignore[reportPrivateUsage]
    assert checked(tour_with(3)).answer is Answer.FEASIBLE
    assert answers._asked_by_a_lock(tour_with(2)) == ({free}, [])  # pyright: ignore[reportPrivateUsage]
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
    return trip(persons, ["dock"], options, facts, decisions, rights=True)


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
