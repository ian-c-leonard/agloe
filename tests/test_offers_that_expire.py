"""An OFFER can state when it expires. From then on nobody can take a place of it."""

from dataclasses import replace
from random import Random
from typing import Any

import pytest

from agloe import answers, compiler, report
from agloe.answers import Answer, Report, as_seen, expiries
from agloe.file import File, FileError, Now, Offer, instant
from agloe.reference import (
    Broken,
    Constraint,
    any_works,
    best_case,
    broken_as_listed,
    first_shown,
    with_these_at_best,
    worst_case,
)
from tests.stories import (
    at,
    booking,
    budget,
    cap,
    every_right,
    lock,
    needs_right,
    no_other_right_for,
    now,
    offer,
    stays,
    trip,
)
from tests.test_cross_check import random_trip
from tests.test_offers import EVERYONE, a_boat_tour, at_ten, two_tours_with_offers
from tests.test_offers_for_objects import BOTH, a_crossing

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


# OFFERs for OBJECTs.


def test_a_place_for_an_object_cannot_be_taken_once_its_offer_has_expired() -> None:
    """The car needs a place on the ferry. The car deck is on OFFER until Thursday."""
    deck = offer("ferry", 3, "car-deck", "90.00 USD", objects=["car"], expires=THURSDAY)
    pays = [budget("money", "alex", "sam", objects=["car"])]
    whole = no_other_right_for("ferry", "car", "car-deck")
    early = checked(a_crossing(deck, whole, MONDAY, budgets=pays))
    assert early.answer is Answer.FEASIBLE
    assert "today" in early.relies_on
    late = checked(a_crossing(deck, whole, FRIDAY, budgets=pays))
    assert late.answer is Answer.INFEASIBLE
    assert {"car-deck", "today"} <= set(late.conflict)
    # With no time now nobody knows, and the one case is that it is before Thursday.
    untimed = checked(a_crossing(deck, whole, budgets=pays))
    assert untimed.answer is Answer.UNDETERMINED
    assert (untimed.missing, untimed.before) == (((),), (instant(THURSDAY),))
    # Without the FACT that these are all the rights, another right might be found.
    open_to_more = checked(a_crossing(deck, FRIDAY, budgets=pays))
    assert open_to_more.answer is Answer.UNDETERMINED
    assert [[n.unknown.what for n in enough] for enough in open_to_more.missing] == [
        ["another right for"]
    ]


def test_an_expired_place_is_not_put_back_when_objects_are_matched_to_places() -> None:
    """Two OBJECTs need a place and one OFFER has one for either. A second place has expired.

    More money cannot put two OBJECTs on one place: the one without a place has no right.
    """
    either = offer("ferry", 1, "deck", "10.00 USD", objects=["car", "bike"])
    gone = offer("ferry", 1, "rack", "10.00 USD", objects=["bike"], expires=WEDNESDAY)
    pays = [budget("money", "alex", "sam", objects=["car", "bike"])]
    for moment in ([FRIDAY], []):
        file = a_crossing(either, gone, *moment, budgets=pays, bike=True)
        found = broken_as_listed(file, worst_case(file), BOTH)
        assert found == [Broken(Constraint.COVERED, "ferry", ("sam",), object="bike")]
    # While the rack is open, each has a place and both are paid for.
    early = a_crossing(either, gone, MONDAY, budgets=pays, bike=True)
    assert broken_as_listed(early, worst_case(early), BOTH) == []


# The report.


def said(file: File) -> str:
    return report.as_text(file, answers.check(file))


def as_json(file: File) -> dict[str, Any]:
    return report.as_json(file, answers.check(file))


def test_a_purchase_says_before_when_and_the_plan_relies_on_the_time_now() -> None:
    words = said(tour(MONDAY))
    assert (
        "    ! sam still has to buy a right to this, from tour-offer, for 10.00 USD from money,"
        " before 5:00 pm on Thursday 13 May 2027.\n"
    ) in words
    assert "  today: the time now is 9:00 am on Monday 10 May 2027\n" in words
    assert (
        "  tour-offer: an OFFER has 2 places for tour that can still be bought until 5:00 pm on"
        " Thursday 13 May 2027, for 10.00 USD each\n"
    ) in words
    # A plan that takes no place of a dated OFFER does not rely on the time now.
    booked = a_boat_tour(booking("tour", "alex", "sam"), offer("tour", 2, expires=THURSDAY), MONDAY)
    assert "today" not in answers.check(booked).relies_on
    # A purchase from an OFFER that states no expiry says no time.
    plain = said(a_boat_tour(booking("tour", "alex"), offer("tour", 2), MONDAY))
    assert "from tour-offer, for 10.00 USD from money.\n" in plain


def test_an_expired_offer_is_worded_as_one_that_had_its_places() -> None:
    words = said(tour(FRIDAY, every_right("tour", "tour-offer")))
    assert (
        "  tour-offer: an OFFER had 2 places for tour that could be bought until 5:00 pm on"
        " Thursday 13 May 2027, for 10.00 USD each\n"
    ) in words


@pytest.mark.parametrize(
    ("places", "price", "ends"),
    [
        (2, "10.00 USD", "The chance to buy up to 2 places at 10.00 USD each ends."),
        (1, "10.00 USD", "The chance to buy 1 place at 10.00 USD ends."),
        (2, "0.00 USD", "The chance to buy up to 2 places at no cost ends."),
        (
            2,
            None,
            "The chance to buy up to 2 places ends. The FILE does not state their price.",
        ),
        (1, None, "The chance to buy 1 place ends. The FILE does not state its price."),
    ],
)
def test_the_expiry_of_an_offer_is_a_deadline(places: int, price: str | None, ends: str) -> None:
    dated = offer("tour", places, price=price, expires=THURSDAY)
    words = said(a_boat_tour(booking("tour", "alex", "sam"), dated, MONDAY))
    assert (
        "DEADLINEs after that time, earliest first:\n"
        f"  5:00 pm on Thursday 13 May 2027: tour-offer, the OFFER for tour, expires. {ends}\n"
    ) in words


def test_an_expiry_that_has_passed_is_not_listed_and_the_report_says_that_none_is_left() -> None:
    words = said(tour(FRIDAY))
    assert "expires." not in words
    assert "\nNo DEADLINE comes after that time.\n" in words
    assert as_json(tour(FRIDAY))["deadlines"] == []


def test_with_no_time_now_every_expiry_is_listed() -> None:
    words = said(tour())
    assert (
        "This FILE does not state the time now. So nobody knows which of its DEADLINEs have"
        " passed. All of them, earliest first (times in America/Chicago):\n"
        "  5:00 pm on Thursday 13 May 2027: tour-offer, the OFFER for tour, expires."
    ) in words


def test_deadlines_at_one_instant_come_in_the_files_order_of_facts() -> None:
    """An OFFER expires when a term for cancelling starts. Whichever FACT comes first is first."""
    held = booking("tour", "alex", "sam")
    held["booking"]["cancelling"] = [
        {"costs": [{"amount": "0.00", "currency": "USD"}]},
        {"from": THURSDAY, "costs": [{"amount": "10.00", "currency": "USD"}]},
    ]
    dated = offer("tour", 2, expires=THURSDAY)
    first = as_json(a_boat_tour(held, dated, MONDAY))["deadlines"]
    assert [each["kind"] for each in first] == ["cancelling", "expiry"]
    second = as_json(a_boat_tour(dated, held, MONDAY))["deadlines"]
    assert [each["kind"] for each in second] == ["expiry", "cancelling"]
    # An earlier time comes first, whatever the order of the FACTs.
    sooner = offer("tour", 2, expires=WEDNESDAY)
    assert [each["kind"] for each in as_json(a_boat_tour(held, sooner, MONDAY))["deadlines"]] == [
        "expiry",
        "cancelling",
    ]


def test_an_offer_with_no_time_of_expiry_is_named() -> None:
    file = a_boat_tour(
        booking("tour", "alex"), offer("tour", 2, expires=THURSDAY), offer("tour", 1, id="spare")
    )
    assert said(file).endswith("\nNo time of expiry is stated for spare.\n")
    assert as_json(file)["no_expiry_stated"] == ["spare"]
    assert "no_expiry_stated" not in as_json(tour(MONDAY))
    # A FILE that states no time now, no terms and no expiry has no such part.
    plain = a_boat_tour(booking("tour", "alex"), offer("tour", 2))
    assert "No time of expiry" not in said(plain)
    assert "no_expiry_stated" not in as_json(plain)


def test_the_report_as_json_has_the_expiry_and_the_time_of_a_case() -> None:
    assert as_json(tour(MONDAY))["deadlines"] == [
        {
            "at": THURSDAY,
            "kind": "expiry",
            "offer": "tour-offer",
            "option": "tour",
            "places": 2,
            "price": {"amount": "10.00", "currency": "USD"},
        }
    ]
    unpriced = a_boat_tour(
        booking("tour", "alex", "sam"), offer("tour", 2, price=None, expires=THURSDAY)
    )
    assert as_json(unpriced)["deadlines"][0]["price"] is None
    untimed = as_json(tour())
    assert [[each["what"] for each in case] for case in untimed["missing"]] == [
        ["another right"],
        ["time"],
    ]
    assert untimed["missing"][1] == [{"what": "time", "before": THURSDAY}]
    # A case that asks for something else too has the time as its last condition.
    two = a_boat_tour(
        booking("tour", "alex"),
        offer("tour", 1, price=None, expires=THURSDAY),
        every_right("tour", "tour-offer"),
    )
    (case,) = as_json(two)["missing"]
    assert [each["what"] for each in case] == ["price", "time"]
    assert "and it is before 5:00 pm on Thursday 13 May 2027." in said(two)


def test_the_times_of_expiry_count_for_the_offsets() -> None:
    """The clocks change on Sunday 7 November 2027, after the OFFER expires."""
    early = "2027-11-05T17:00:00-05:00[America/Chicago]"
    start = "2027-11-10T10:00:00-06:00[America/Chicago]"

    def moved(*more: Any) -> File:
        file = a_boat_tour(booking("tour", "alex"), offer("tour", 2, expires=early), *more)
        facts = tuple(
            replace(fact, at=instant(start)) if type(fact).__name__ == "Start" else fact
            for fact in file.facts
        )
        return replace(file, facts=facts)

    # In a conflict the expired OFFER names the time, the only one before the change.
    late = {"id": "today", "now": "2027-11-09T09:00:00-06:00[America/Chicago]"}
    words = said(moved(late, every_right("tour", "tour-offer")))
    assert "could be bought until 5:00 pm (UTC-5) on Friday 5 November 2027" in words


# What each lookup and each world says of an OFFER that has expired.


def test_no_lookup_of_a_file_gives_an_offer_that_has_expired() -> None:
    deck = offer("ferry", 3, "car-deck", "90.00 USD", objects=["car"], expires=THURSDAY)
    pays = [budget("money", "alex", "sam", objects=["car"])]
    early = a_crossing(deck, MONDAY, budgets=pays)
    late = a_crossing(deck, FRIDAY, budgets=pays)
    assert [each.id for each in early.offers_for("ferry", "car")] == ["car-deck"]
    assert [each.id for each in early.offers_for_objects("ferry")] == ["car-deck"]
    assert [each.id for each in early.every_offer("ferry")] == ["car-deck"]
    assert late.offers_for("ferry", "car") == ()
    assert late.offers_for_objects("ferry") == ()
    assert late.every_offer("ferry") == ()
    assert late.offers_open_to("ferry", "car") == ()
    assert [each.id for each in late.offers_stated("ferry")] == ["car-deck"]
    assert tour(FRIDAY).every_offer("tour") == ()
    assert tour(FRIDAY).offers_open_to("tour", "sam") == ()


def test_the_file_as_of_a_moment_has_that_moment_as_its_only_time_now() -> None:
    later = tour(MONDAY).as_of(instant(THURSDAY))
    assert [fact.at for fact in later.facts if isinstance(fact, Now)] == [instant(THURSDAY)]
    assert later.expired == {"tour-offer"}
    assert tour(FRIDAY).as_of(instant(THURSDAY) - 1).expired == frozenset()


def test_nobody_can_pay_for_a_place_of_an_offer_that_is_closed_or_has_expired() -> None:
    assert ("tour-offer", "sam") in worst_case(tour(MONDAY)).payable
    assert worst_case(tour(FRIDAY)).payable == frozenset()
    assert worst_case(tour()).payable == frozenset()
    assert ("tour-offer", "sam") in best_case(tour()).payable


def test_an_object_whose_only_offer_is_closed_has_nothing_to_cover_it() -> None:
    """With no time now the car deck might have expired: at worst the car has no right."""
    deck = offer("ferry", 3, "car-deck", "90.00 USD", objects=["car"], expires=THURSDAY)
    pays = [budget("money", "alex", "sam", objects=["car"])]
    uncovered = [Broken(Constraint.COVERED, "ferry", ("alex",), object="car")]
    for file in (a_crossing(deck, budgets=pays), a_crossing(deck, FRIDAY, budgets=pays)):
        world = worst_case(file)
        assert ("ferry", "car") in world.uncovered
        assert ("ferry", "car") not in world.offered
        assert broken_as_listed(file, world, BOTH) == uncovered
    open_still = a_crossing(deck, MONDAY, budgets=pays)
    assert ("ferry", "car") in worst_case(open_still).offered
    assert broken_as_listed(open_still, worst_case(open_still), BOTH) == []


def test_the_expiries_are_in_the_order_of_time() -> None:
    file = a_boat_tour(
        booking("tour", "alex", "sam"),
        offer("tour", 1, id="late", expires=THURSDAY),
        offer("tour", 1, id="early", expires=WEDNESDAY),
        offer("tour", 1, id="also-late", expires=THURSDAY),
    )
    assert [each.offer for each in expiries(file)] == ["early", "late", "also-late"]
    assert [each.at for each in expiries(file)] == [
        instant(WEDNESDAY),
        instant(THURSDAY),
        instant(THURSDAY),
    ]
