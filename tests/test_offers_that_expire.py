"""An OFFER can state when it expires. From then on nobody can take a place of it."""

from typing import Any

import pytest

from agloe import answers, compiler, report
from agloe.answers import Answer, Report
from agloe.file import File, FileError, Offer, instant
from agloe.reference import best_case, worst_case
from tests.stories import at, booking, every_right, now, offer
from tests.test_offers import a_boat_tour

THURSDAY = at(17, day=13)  # when the OFFER of these stories expires: 5:00 pm on 13 May
MONDAY = now(9, day=10)
FRIDAY = now(9, day=14)


def tour(*more: Any) -> File:
    """Alex has a ticket for the boat tour and Sam has none. Two places are on OFFER."""
    return a_boat_tour(booking("tour", "alex"), offer("tour", 2, expires=THURSDAY), *more)


def checked(file: File) -> Report:
    """The report, which both checkers give alike."""
    found = answers.check(file)
    assert compiler.check(file) == found
    return found


# The format.


def test_an_offer_states_when_it_expires() -> None:
    (dated,) = [fact for fact in tour().facts if isinstance(fact, Offer)]
    assert dated.expires == instant(THURSDAY)
    plain = a_boat_tour(offer("tour", 2))
    assert next(fact for fact in plain.facts if isinstance(fact, Offer)).expires is None
    assert tour().dated_offers() == (dated,)
    assert plain.dated_offers() == ()


def test_the_time_at_which_an_offer_expires_is_a_real_time() -> None:
    wrong = "2027-02-30T17:00:00-06:00[America/Chicago]"
    with pytest.raises(FileError) as refused:
        a_boat_tour(offer("tour", 2, expires=wrong))
    assert f"{wrong} is not a real date and time" in str(refused.value)


# With a time now.


def test_before_it_expires_an_offer_is_as_it_was() -> None:
    dated, plain = (
        checked(tour(MONDAY)),
        checked(a_boat_tour(booking("tour", "alex"), offer("tour", 2))),
    )
    assert dated.answer is Answer.FEASIBLE
    assert (dated.itinerary, dated.rights) == (plain.itinerary, plain.rights)
    assert tour(MONDAY).expired == frozenset()


def test_an_offer_has_expired_at_the_time_it_states_and_from_then_on() -> None:
    a_second_before = {"id": "today", "now": "2027-05-13T16:59:59-05:00[America/Chicago]"}
    at_that_time = {"id": "today", "now": THURSDAY}
    assert tour(a_second_before).expired == frozenset()
    assert tour(at_that_time).expired == {"tour-offer"}
    assert tour(FRIDAY).expired == {"tour-offer"}
    assert checked(tour(a_second_before)).answer is Answer.FEASIBLE
    assert checked(tour(at_that_time)).answer is Answer.UNDETERMINED


def test_nobody_takes_a_place_of_an_offer_that_has_expired() -> None:
    """Sam has no right. Another right might be found, unless the rights are COMPLETE."""
    late = tour(FRIDAY)
    assert late.offers("tour") == ()
    assert late.places_on_offer("tour") == 0
    found = checked(late)
    assert found.answer is Answer.UNDETERMINED
    assert [[each.unknown.what for each in enough] for enough in found.missing] == [
        ["another right"]
    ]
    ruled_out = checked(tour(FRIDAY, every_right("tour", "tour-offer")))
    assert ruled_out.answer is Answer.INFEASIBLE


def test_a_conflict_that_turns_on_an_expired_offer_holds_the_offer_and_the_time_now() -> None:
    ruled_out = checked(tour(FRIDAY, every_right("tour", "tour-offer")))
    assert {"today", "tour-offer", "every-right-to-tour"} <= set(ruled_out.conflict)
    # One place for two PERSONs rules the trip out at any time: the time is no part of that.
    one_place = a_boat_tour(
        offer("tour", 1, expires=THURSDAY), FRIDAY, every_right("tour", "tour-offer")
    )
    short = checked(one_place)
    assert short.answer is Answer.INFEASIBLE
    assert "today" not in short.conflict
    assert "tour-offer" in short.conflict


# With no time now.


def test_with_no_time_now_the_worst_case_has_every_dated_offer_closed_and_the_best_none() -> None:
    file = tour()
    assert file.expired == frozenset()
    assert worst_case(file).closed == {"tour-offer"}
    assert worst_case(file).places["tour"] == 0
    assert best_case(file).closed == frozenset()
    assert best_case(file).places["tour"] == 2
    # An OFFER that states no expiry is open in every case.
    undated = a_boat_tour(booking("tour", "alex"), offer("tour", 2))
    assert worst_case(undated).closed == frozenset()
    assert worst_case(undated).places["tour"] == 2


def test_with_no_time_now_a_trip_that_needs_a_dated_offer_is_undetermined() -> None:
    assert checked(tour()).answer is Answer.UNDETERMINED
    assert checked(tour(every_right("tour", "tour-offer"))).answer is Answer.UNDETERMINED


def test_with_no_time_now_a_plan_takes_a_place_of_an_offer_that_cannot_have_expired() -> None:
    both = tour(offer("tour", 1, id="standby"))
    found = checked(both)
    assert found.answer is Answer.FEASIBLE
    assert [cover.by for cover in found.rights if cover.person == "sam"] == ["standby"]


def test_with_no_time_now_a_trip_with_too_few_places_at_any_time_is_ruled_out() -> None:
    one_place = a_boat_tour(offer("tour", 1, expires=THURSDAY), every_right("tour", "tour-offer"))
    assert checked(one_place).answer is Answer.INFEASIBLE


def test_the_words_of_a_report_are_made() -> None:
    for file in (
        tour(MONDAY),
        tour(FRIDAY),
        tour(),
        tour(FRIDAY, every_right("tour", "tour-offer")),
    ):
        assert report.as_text(file, answers.check(file))
