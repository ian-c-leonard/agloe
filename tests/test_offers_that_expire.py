"""An OFFER can state when it expires. From then on nobody can take a place of it."""

from dataclasses import replace
from random import Random
from typing import Any

import pytest

from agloe import answers, compiler, report
from agloe.answers import Answer, Report, as_seen
from agloe.file import File, FileError, Now, Offer, instant
from agloe.reference import any_works, best_case, first_shown, with_these_at_best, worst_case
from tests.stories import (
    at,
    booking,
    cap,
    every_right,
    lock,
    needs_right,
    now,
    offer,
    stays,
    trip,
)
from tests.test_cross_check import random_trip
from tests.test_offers import EVERYONE, a_boat_tour, at_ten, two_tours_with_offers

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


# Many generated trips.

EXPIRIES = (instant(at(17, day=11)), instant(at(17, day=12)), instant(at(17, day=13)))


def dated(rng: Random, file: File, with_now: bool) -> File:
    """The same FILE with a time of expiry on most of its OFFERs, and maybe a time now."""
    facts = [
        replace(fact, expires=rng.choice(EXPIRIES))
        if isinstance(fact, Offer) and rng.random() < 0.7
        else fact
        for fact in file.facts
    ]
    if with_now:
        moments = [EXPIRIES[0] - 1, EXPIRIES[0], EXPIRIES[1] - 1, EXPIRIES[1], EXPIRIES[2]]
        facts.append(Now("today", rng.choice(moments)))
    return replace(file, facts=tuple(facts))


def generated(count: int, with_now: bool, seed: int) -> list[File]:
    """Trips with OFFERs that expire: half with two tours, half of any kind."""
    rng = Random(seed)
    files: list[File] = []
    while len(files) < count:
        if len(files) % 2:
            plain = two_tours_with_offers(rng)
        else:
            plain = random_trip(rng, 0.1, contingent=0.3, with_wants=0.3, with_rights=0.6)
        file = dated(rng, plain, with_now)
        if file.dated_offers():
            files.append(file)
    return files


def test_both_checkers_agree_on_trips_with_offers_that_expire() -> None:
    seen: set[Answer] = set()
    for with_now in (True, False):
        for file in generated(120, with_now, seed=7):
            found = answers.check(file)
            assert compiler.check(file) == found
            seen.add(found.answer)
    assert seen == set(Answer)


def test_the_worst_case_with_no_time_now_is_the_file_after_every_expiry() -> None:
    """Two ways to close the OFFERs that might have expired give one answer and one plan."""
    plans = 0
    for file in generated(150, with_now=False, seed=11):
        late = as_seen(file, None)
        assert late.expired == worst_case(file).closed
        assert any_works(file, worst_case(file)) == any_works(late, worst_case(late))
        shown = first_shown(file, worst_case(file))
        assert shown == first_shown(late, worst_case(late))
        plans += shown is not None
    assert plans > 10


def test_with_no_time_now_the_answer_is_what_holds_at_every_time() -> None:
    """FEASIBLE where the trip works after every expiry, INFEASIBLE where it never works."""
    order = [Answer.FEASIBLE, Answer.UNDETERMINED, Answer.INFEASIBLE]
    seen: set[tuple[Answer, ...]] = set()
    for file in generated(150, with_now=False, seed=13):
        ends = sorted({offer.expires for offer in file.dated_offers() if offer.expires is not None})
        stretches = [as_seen(file, until) for until in (*ends, None)]
        at_each = [answers.check(seen_at).answer for seen_at in stretches]
        # A trip never gets better as time passes.
        assert [order.index(each) for each in at_each] == sorted(order.index(e) for e in at_each)
        found = answers.check(file).answer
        if at_each[-1] is Answer.FEASIBLE:
            assert found is Answer.FEASIBLE
        elif at_each[0] is Answer.INFEASIBLE:
            assert found is Answer.INFEASIBLE
        else:
            assert found is Answer.UNDETERMINED
        seen.add(tuple(at_each))
    # Some trips change their answer with the time, and some change it twice.
    assert any(len(set(each)) == 2 for each in seen)
    assert any(len(set(each)) == 3 for each in seen)


def test_each_case_holds_just_before_its_time_and_no_longer_at_it() -> None:
    timed = untimed = 0
    for file in generated(200, with_now=False, seed=17):
        found = answers.check(file)
        if found.answer is not Answer.UNDETERMINED:
            continue
        assert len(found.before) == len(found.missing)
        for enough, until in zip(found.missing, found.before, strict=True):
            asked = [needed.unknown for needed in enough]
            seen_at = as_seen(file, until)
            assert any_works(seen_at, with_these_at_best(seen_at, asked))
            if until is None:
                untimed += 1
                continue
            timed += 1
            # At that time the OFFERs that expire then are closed, and the case is not enough.
            later = file.as_of(until)
            assert not any_works(later, with_these_at_best(later, asked))
        # A case with no unknown FACT is the last one: no earlier stretch adds to it.
        assert all(enough for enough in found.missing[:-1])
    assert timed > 10 and untimed > 10


# The FILEs of the review of the words.

WEDNESDAY = at(17, day=12)


def test_two_offers_with_no_price_each_have_their_own_time() -> None:
    """Sam can pay the first price before Wednesday, or the second before Thursday."""
    file = a_boat_tour(
        booking("tour", "alex"),
        offer("tour", 1, id="early", price=None, expires=WEDNESDAY),
        offer("tour", 1, id="late", price=None, expires=THURSDAY),
        every_right("tour", "early", "late"),
    )
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    cases = [
        ([(needed.unknown.what, needed.unknown.about) for needed in enough], until)
        for enough, until in zip(found.missing, found.before, strict=True)
    ]
    assert cases == [
        ([("price", "late")], instant(THURSDAY)),
        ([("price", "early")], instant(WEDNESDAY)),
    ]
    said = report.as_text(file, found)
    assert "and it is before 5:00 pm on Thursday 13 May 2027" in said
    assert "and it is before 5:00 pm on Wednesday 12 May 2027" in said


def test_a_case_shows_the_purchase_and_the_cap_of_its_own_stretch() -> None:
    """A place for 3 dollars until Wednesday and one for 30 until Thursday, under a cap of 35."""
    facts = [
        *at_ten("tour"),
        needs_right("tour"),
        booking("tour", "alex", paid="2.00 USD", budget="money"),
        offer("tour", 1, id="cheap", price="3.00 USD", expires=WEDNESDAY),
        offer("tour", 1, id="dear", price="30.00 USD", expires=THURSDAY),
        every_right("tour", "cheap", "dear"),
    ]
    decisions = [lock("tour", "alex", "sam"), cap("money", "35.00 USD")]
    file = trip(EVERYONE, ["dock"], [stays("tour", "dock")], facts, decisions, rights=True)
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    assert found.before == (instant(THURSDAY),)
    assert found.missing == ((),)
    (plan,) = found.plans
    assert [(cover.person, cover.by) for cover in plan.buys] == [("sam", "dear")]
    said = report.as_text(file, found)
    assert "The trip works if it is before 5:00 pm on Thursday 13 May 2027." in said
    assert "dear" in said and "from cheap" not in said


def test_an_expired_free_place_does_not_hide_the_price_that_the_answer_turns_on() -> None:
    """The free seat expired on Wednesday. The other OFFER states no price."""
    file = a_boat_tour(
        booking("tour", "alex"),
        offer("tour", 1, id="free", price="0.00 USD", expires=WEDNESDAY),
        offer("tour", 1, id="other", price=None, expires=at(17, day=14)),
        every_right("tour", "free", "other"),
        now(9, day=13),
    )
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    assert [[(n.unknown.what, n.unknown.about) for n in enough] for enough in found.missing] == [
        [("price", "other")]
    ]
