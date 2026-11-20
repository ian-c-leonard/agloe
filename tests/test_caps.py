"""Caps: a DECISION can cap what the TRIP spends from a BUDGET in one currency."""

from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal
from itertools import product
from random import Random

import pytest

from agloe import answers, compiler, reference, report
from agloe.answers import Answer, CapRow, Cover, Plan, Report
from agloe.file import Booking, Cap, File, FileError, Money, Offer
from agloe.reference import (
    Broken,
    Constraint,
    Remaining,
    Step,
    Unknown,
    broken,
    unknowns,
    way_to_pay,
    worst_case,
)
from tests.stories import (
    Document,
    any_time,
    booking,
    budget,
    cap,
    cutoff,
    ends_at,
    every,
    every_right,
    lasts,
    lock,
    moves,
    must,
    needs_no_right,
    needs_right,
    offer,
    satisfies,
    seconds,
    starts_at,
    starts_from,
    stays,
    takes,
    trip,
    way_between,
)
from tests.test_where_a_path_ends import checked, has_no_record_to_spare, ruled_out

EVERYONE = ["alex", "sam", "jo"]
LEAVES = "for whatever else is charged to it."
NOTHING = "nobody buys a place from an OFFER of this FILE"


def at(option: str, hour: int) -> list[Document]:
    """An OPTION that starts at this hour, with nothing left unknown about its time."""
    return [starts_at(option, hour), lasts(option, "PT1H"), cutoff(option, "PT0S")]


def a_tour(
    *more: Document,
    locked: Sequence[str] = ("sam",),
    budgets: Sequence[Document] | None = None,
    caps: Sequence[Document] = (),
    persons: Sequence[str] = EVERYONE,
) -> File:
    """A boat tour at 10:00 am that needs a right. A LOCK names Sam, unless told otherwise.

    One BUDGET, the trip money, pays in USD for everybody, unless the test names others.
    """
    if budgets is None:
        budgets = [budget("trip-money", *persons)]
    decisions = [*([lock("tour", *locked)] if locked else []), *caps]
    facts = [*at("tour", 10), needs_right("tour"), *more]
    options = [stays("tour", "dock")]
    return trip(list(persons), ["dock"], options, facts, decisions, tickets=True, budgets=budgets)


def charged(ticket: str, option: str = "tour") -> Unknown:
    """What a BOOKING charged to the BUDGETs of the FILE, where the FILE leaves that open."""
    return Unknown("charged", option, about=ticket)


def asked(file: File) -> list[list[Unknown]]:
    return [[needed.unknown for needed in enough] for enough in checked(file).missing]


def in_words(file: File) -> list[str]:
    return report.as_text(file, checked(file)).splitlines()


def problems(*caps: Document, budgets: Sequence[Document] | None = None) -> str:
    with pytest.raises(FileError) as refused:
        a_tour(caps=caps, budgets=budgets)
    return str(refused.value)


# ------------------------------- What a FILE holds -------------------------------


def test_a_cap_names_a_budget_and_an_amount_in_a_currency_it_holds() -> None:
    both = [budget("pot", "sam", holds=["USD", "EUR"])]
    file = a_tour(caps=[cap("pot", "50.00 USD"), cap("pot", "0 EUR", id="no-euros")], budgets=both)
    assert file.caps == {
        ("pot", "USD"): Cap("pot-cap", "pot", Money(Decimal("50.00"), "USD")),
        ("pot", "EUR"): Cap("no-euros", "pot", Money(Decimal(0), "EUR")),
    }
    assert problems(cap("savings", "1 USD")) == "/decisions/1: savings is not a BUDGET in this FILE"
    assert problems(cap("trip-money", "1 EUR")) == "/decisions/1: trip-money holds no EUR"
    twice = [cap("trip-money", "1 USD"), cap("trip-money", "2 USD", id="again")]
    assert problems(*twice) == "/decisions/2: another DECISION already caps trip-money in USD"
    malformed = cap("trip-money", "1 USD")
    malformed["spend_at_most"]["amount"] = "1,000"
    assert "fits no known shape" in problems(malformed)


def test_a_file_with_no_cap_has_nothing_unknown_about_a_charge() -> None:
    file = a_tour(booking("tour", "sam"))
    assert not any(unknown.what == "charged" for unknown in unknowns(file))


# ------------------------------- What the BOOKINGs charged -------------------------------


def test_two_bookings_that_nobody_uses_can_pass_a_cap_together() -> None:
    """A cap of 50 USD, and BOOKINGs for Alex and Jo that paid 30 and 25 USD from it."""
    first = booking("tour", "alex", id="first", paid="30 USD", budget="trip-money")
    second = booking("tour", "jo", id="second", paid="25 USD", budget="trip-money")
    file = a_tour(first, second, locked=(), caps=[cap("trip-money", "50 USD")])
    found = checked(file)
    assert found.answer is Answer.INFEASIBLE
    assert found.conflict == ("first", "second", "trip-money-cap")
    assert has_no_record_to_spare(file, found.conflict)
    nothing = (Step("tour", "dock", "dock", ("alex",), seconds(10), seconds(11)),)
    assert Broken(Constraint.CAP, None, (), cap="trip-money-cap") in broken(
        file, worst_case(file), nothing
    )
    as_json = report.as_json(file, found)
    assert as_json["caps"] == [
        {"cap": "trip-money-cap", "budget": "trip-money", "currency": "USD", "limit": "50"}
    ]
    assert as_json["payments"] == [
        {"booking": "first", "amount": "30", "currency": "USD", "budget": "trip-money", "by": None},
        {
            "booking": "second",
            "amount": "25",
            "currency": "USD",
            "budget": "trip-money",
            "by": None,
        },
    ]
    assert in_words(file)[3:6] == [
        "  first: a BOOKING for tour covers alex; its payment: 30 USD, from trip-money",
        "  second: a BOOKING for tour covers jo; its payment: 25 USD, from trip-money",
        "  trip-money-cap: the TRIP spends at most 50 USD from trip-money",
    ]


def test_a_plan_says_which_of_two_bookings_gives_a_person_their_right() -> None:
    """Two BOOKINGs cover Sam, and each paid nothing. The trip money may spend nothing."""
    tickets = [
        booking("tour", "sam", id="first", paid="0 USD"),
        booking("tour", "sam", id="second", paid="0 USD"),
    ]
    file = a_tour(*tickets, caps=[cap("trip-money", "0 USD")])
    found = checked(file)
    assert [cover.by for cover in found.rights] == ["first"]
    words = in_words(file)
    assert "  first: a BOOKING for tour covers sam; its payment: nothing" in words
    assert (
        "  second: a BOOKING for tour covers sam; its payment: nothing; this plan counts what it"
        " paid, and nobody uses its right"
    ) in words


def test_a_booking_counts_once_however_many_it_covers() -> None:
    for_three = booking("tour", *EVERYONE, paid="50 USD", budget="trip-money")
    file = a_tour(for_three, locked=EVERYONE, caps=[cap("trip-money", "50 USD")])
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert found.caps == (CapRow("trip-money-cap", 500000, (), (), 0, 0, 0),)


@pytest.mark.parametrize(
    ("paid", "parts", "answer"),
    [
        ("0 USD", {"budget": "trip-money"}, Answer.FEASIBLE),
        ("1 USD", {"budget": "trip-money"}, Answer.INFEASIBLE),
        ("1 USD", {"budget": "savings"}, Answer.FEASIBLE),
        ("1 EUR", {"budget": "trip-money"}, Answer.FEASIBLE),
        ("1 USD", {}, Answer.UNDETERMINED),
        ("1 EUR", {}, Answer.FEASIBLE),
        (None, {}, Answer.UNDETERMINED),
    ],
)
def test_a_charge_counts_only_against_the_cap_of_its_budget_and_currency(
    paid: str | None, parts: dict[str, str], answer: Answer
) -> None:
    """The trip money may spend no USD. Jo has a BOOKING, and nobody has to do anything."""
    pots = [budget("trip-money", *EVERYONE, holds=["USD", "EUR"]), budget("savings", "jo")]
    ticket = booking("tour", "jo", paid=paid, **parts)
    file = a_tour(ticket, locked=(), budgets=pots, caps=[cap("trip-money", "0 USD")])
    found = checked(file)
    assert found.answer is answer
    if answer is Answer.UNDETERMINED:
        assert asked(file) == [[charged("tour-booking")]]
    if answer is Answer.FEASIBLE:
        # Nobody does anything, and the plan still relies on the cap and on what Jo's
        # BOOKING says it charged.
        assert found.relies_on == ("tour-booking", "trip-money-cap")
        assert (
            sum(
                "; this plan counts what it paid, and nobody uses its right" in line
                for line in in_words(file)
            )
            == 1
        )


def test_only_a_charge_that_a_cap_could_turn_on_is_an_unknown_fact() -> None:
    """The trip money holds dollars and euros, and only its dollars have a cap."""
    pots = [budget("trip-money", *EVERYONE, holds=["USD", "EUR"])]
    tickets = [
        booking("tour", "alex", id="unstated"),
        booking("tour", "alex", id="dollars", paid="1 USD"),
        booking("tour", "alex", id="nothing", paid="0 USD"),
        booking("tour", "alex", id="euros", paid="1 EUR"),
        booking("tour", "alex", id="named", paid="1 USD", budget="trip-money"),
    ]
    file = a_tour(*tickets, locked=(), budgets=pots, caps=[cap("trip-money", "9 USD")])
    assert unknowns(file) == (
        Unknown("another right", "tour", person="sam"),
        Unknown("another right", "tour", person="jo"),
        charged("unstated"),
        charged("dollars"),
    )


def test_an_amount_in_a_row_is_never_rounded_to_the_decimal_places_of_the_cap() -> None:
    half = booking("tour", "jo", paid="0.5 USD", budget="trip-money")
    file = a_tour(half, locked=(), caps=[cap("trip-money", "1 USD")])
    assert in_words(file)[-1] == (
        "  trip-money-cap: at most 1 USD from trip-money: 0.5 paid; 0 still to buy; 0.5 left"
    )


def test_a_payment_nobody_stated_has_no_upper_bound() -> None:
    most = "999999999999.9999 USD"
    file = a_tour(booking("tour", "jo"), locked=(), caps=[cap("trip-money", most)])
    assert checked(file).answer is Answer.UNDETERMINED
    stated = a_tour(booking("tour", "jo", paid=most), locked=(), caps=[cap("trip-money", most)])
    assert checked(stated).answer is Answer.FEASIBLE


def test_a_payment_from_an_unknown_budget_is_shown_as_one_that_might_count() -> None:
    """The trip money may spend 5 USD. A BOOKING paid 1 USD, and nobody knows from where."""
    loose = booking("tour", "jo", id="loose", paid="1 USD")
    file = a_tour(loose, locked=(), caps=[cap("trip-money", "5 USD")])
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert found.caps == (CapRow("trip-money-cap", 0, (("loose", 10000),), (), 0, 0, 40000),)
    assert in_words(file)[-1] == (
        "  trip-money-cap: at most 5 USD from trip-money: 0 paid; up to 1 more that loose might"
        " have paid from it; 0 still to buy; at least 4 left"
    )
    caps = report.as_json(file, found)["caps"]
    assert isinstance(caps, list)
    assert caps[0]["might_be_paid"] == [{"booking": "loose", "amount": "1"}]


def test_a_cap_is_kept_to_the_ten_thousandth() -> None:
    tickets = [
        booking("tour", "alex", id="first", paid="0.0001 USD", budget="trip-money"),
        booking("tour", "jo", id="second", paid="0.0002 USD", budget="trip-money"),
    ]
    exact = a_tour(*tickets, locked=(), caps=[cap("trip-money", "0.0003 USD")])
    assert checked(exact).answer is Answer.FEASIBLE
    assert in_words(exact)[-1] == (
        "  trip-money-cap: at most 0.0003 USD from trip-money: 0.0003 paid; 0.0000 still to buy;"
        " 0.0000 left"
    )
    short = a_tour(*tickets, locked=(), caps=[cap("trip-money", "0.00029 USD".replace("9", ""))])
    assert checked(short).answer is Answer.INFEASIBLE


# ------------------------------- The way to pay -------------------------------


def two_visits(*more: Document, budgets: Sequence[Document], caps: Sequence[Document]) -> File:
    """Sam takes the tour at 10:00 am and Jo the talk at noon. Each has one place at 10 USD."""
    options = [stays("tour", "dock"), stays("talk", "dock")]
    facts = [*at("tour", 10), *at("talk", 12), needs_right("tour"), needs_right("talk")]
    facts += [offer("tour", 1, price="10 USD"), offer("talk", 1, price="10 USD"), *more]
    decisions = [lock("tour", "sam"), lock("talk", "jo"), *caps]
    return trip(["sam", "jo"], ["dock"], options, facts, decisions, tickets=True, budgets=budgets)


def test_an_earlier_purchase_leaves_the_only_budget_a_later_one_can_use() -> None:
    """Sam can draw on A and on B, and Jo only on A. Each BUDGET may spend 10 USD."""
    pots = [budget("a", "sam", "jo"), budget("b", "sam")]
    file = two_visits(budgets=pots, caps=[cap("a", "10 USD"), cap("b", "10 USD")])
    found = checked(file)
    assert found.answer is Answer.FEASIBLE and found.robust
    ten = Money(Decimal(10), "USD")
    assert found.rights == (
        Cover("tour", "sam", "tour-offer", True, ten, "b"),
        Cover("talk", "jo", "talk-offer", True, ten, "a"),
    )
    assert found.caps == (
        CapRow("a-cap", 0, (), (), 100000, 0, 0),
        CapRow("b-cap", 0, (), (), 100000, 0, 0),
    )
    assert in_words(file)[-3:] == [
        "The caps:",
        "  a-cap: at most 10 USD from a: 0 paid; 10 still to buy; 0 left",
        "  b-cap: at most 10 USD from b: 0 paid; 10 still to buy; 0 left",
    ]
    roomy = two_visits(budgets=pots, caps=[cap("a", "20 USD"), cap("b", "10 USD")])
    assert [cover.budget for cover in checked(roomy).rights] == ["a", "a"]
    tight = two_visits(budgets=pots, caps=[cap("a", "10 USD"), cap("b", "9 USD")])
    assert asked(tight) == [
        [Unknown("another right", "tour", person="sam")],
        [Unknown("another right", "talk", person="jo")],
    ]


def test_one_way_to_pay_has_to_work_wherever_an_old_payment_came_from() -> None:
    """A and B may spend 1 USD each. An old BOOKING paid 1 USD from one of them, or neither."""
    pots = [budget("a", "sam"), budget("b", "sam")]
    old = booking("tour", "alex", id="old", paid="1 USD")
    facts = [old, offer("tour", 1, price="1 USD"), every_right("tour", "tour-offer")]
    file = a_tour(*facts, budgets=pots, caps=[cap("a", "1 USD"), cap("b", "1 USD")])
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    assert asked(file) == [[charged("old")]]
    one = Money(Decimal(1), "USD")
    assert found.plans == (
        Plan(
            (Cover("tour", "sam", "tour-offer", True, one, "a"),),
            (
                CapRow("a-cap", 0, (("old", 10000),), ("old",), 10000, 0, 0),
                CapRow("b-cap", 0, (("old", 10000),), ("old",), 0, 0, 10000),
            ),
        ),
    )
    assert in_words(file)[2:6] == [
        "The trip works if the FILE states which BUDGET the 1 USD of old came from.",
        "  One plan that works then: sam buys a place from tour-offer for 1 USD from a.",
        f"  a-cap, on a: 1 still to buy, of at most 1 USD. That leaves 0 USD {LEAVES}",
        f"  b-cap, on b: nothing so far, of at most 1 USD. That leaves 1 USD {LEAVES}",
    ]
    for source, answer in (("a", Answer.FEASIBLE), ("b", Answer.FEASIBLE)):
        named = booking("tour", "alex", id="old", paid="1 USD", budget=source)
        told = a_tour(named, *facts[1:], budgets=pots, caps=[cap("a", "1 USD"), cap("b", "1 USD")])
        assert checked(told).answer is answer
        assert checked(told).rights[-1].budget == ("b" if source == "a" else "a")


def test_a_free_place_goes_to_the_person_who_can_pay_for_no_other() -> None:
    """Sam comes first and can pay from B. Jo draws only on A, which may spend nothing."""
    pots = [budget("a", "jo"), budget("b", "sam")]
    offers = [
        offer("tour", 1, id="free", price="0 USD"),
        offer("tour", 1, id="priced", price="1 USD"),
    ]
    file = a_tour(
        *offers,
        every_right("tour", "free", "priced"),
        locked=("sam", "jo"),
        budgets=pots,
        caps=[cap("a", "0 USD")],
    )
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert [(cover.person, cover.by, cover.budget) for cover in found.rights] == [
        ("sam", "priced", "b"),
        ("jo", "free", None),
    ]
    worst = worst_case(file)
    assert way_to_pay(file, worst, {"tour": ("sam", "jo")}) == {
        ("tour", "sam"): ("priced", "b"),
        ("tour", "jo"): ("free", None),
    }


def test_budgets_that_no_cap_limits_are_alike_to_the_search() -> None:
    """Fourteen buyers and six BUDGETs with no cap. The last buyer can only take the free place."""
    persons = [f"p{number}" for number in range(14)]
    pots = [budget(f"b{number}", *persons) for number in range(6)]
    pots.append(budget("capped", "p0"))
    places = [
        offer("tour", 1, id="free", price="0 USD"),
        offer("tour", 14, id="paid", price="1 USD"),
    ]
    file = a_tour(
        *places, locked=persons, budgets=pots, caps=[cap("capped", "0 USD")], persons=persons
    )
    worst = worst_case(file)
    only_free = replace(worst, payable=worst.payable - {("paid", "p13")})
    way = way_to_pay(file, only_free, {"tour": tuple(persons)})
    assert way is not None
    assert way["tour", "p13"] == ("free", None)
    assert {way["tour", person] for person in persons[:-1]} == {("paid", "b0")}


def test_what_a_report_asks_for_says_that_it_has_to_fit_the_caps() -> None:
    """Sam is in a tour that might need a right. The trip money may spend nothing."""
    options = [stays("tour", "dock")]
    decisions = [lock("tour", "sam"), cap("money", "0 USD")]
    might = trip(["sam"], ["dock"], options, at("tour", 10), decisions, tickets=True)
    assert (
        "If tour does need a right, a BOOKING for each PERSON who takes part in it is enough"
        " instead, if what those BOOKINGs paid fits the caps."
    ) in in_words(might)
    needs = trip(
        ["sam"], ["dock"], options, [*at("tour", 10), needs_right("tour")], decisions, tickets=True
    )
    assert in_words(needs)[2] == (
        "The trip works if a right to tour is found for sam, at a cost that fits the caps."
    )
    found = checked(a_tour(booking("tour", "alex"), locked=(), caps=[cap("trip-money", "1 USD")]))
    as_json = report.as_json(
        a_tour(booking("tour", "alex"), locked=(), caps=[cap("trip-money", "1 USD")]), found
    )
    missing = as_json["missing"]
    assert isinstance(missing, list)
    assert missing[0] == [
        {"what": "charged", "option": "tour", "booking": "tour-booking", "at_most": None}
    ]


def test_a_purchase_can_pass_a_cap_only_where_nothing_else_gives_the_right() -> None:
    paid = booking("tour", "alex", paid="32.00 USD", budget="trip-money", by="alex")
    places = offer("tour", 2, price="32.00 USD")
    low = [cap("trip-money", "50.00 USD")]
    file = a_tour(paid, places, every_right("tour", "tour-offer"), caps=low)
    found = checked(file)
    assert found.answer is Answer.INFEASIBLE
    assert found.conflict == (
        "tour-needs-right",
        "tour-booking",
        "tour-offer",
        "every-right-to-tour",
        "lock-tour",
        "trip-money-cap",
    )
    assert found.given_budgets
    assert has_no_record_to_spare(file, found.conflict)
    still_open = a_tour(paid, places, caps=low)
    assert asked(still_open) == [[Unknown("another right", "tour", person="sam")]]
    enough = a_tour(
        paid, places, every_right("tour", "tour-offer"), caps=[cap("trip-money", "64.00 USD")]
    )
    assert checked(enough).answer is Answer.FEASIBLE


def test_a_place_bought_only_if_needed_is_counted_as_if_it_were() -> None:
    """Nobody knows whether the tour needs a right. A place costs 1 USD, and the cap is 1 USD."""
    options = [stays("tour", "dock")]
    facts = [*at("tour", 10), offer("tour", 1, price="1 USD")]
    pots = [budget("trip-money", "sam", "jo")]

    def with_tickets(*tickets: Document) -> File:
        decisions = [lock("tour", "sam"), cap("trip-money", "1 USD")]
        return trip(
            ["sam", "jo"],
            ["dock"],
            options,
            [*facts, *tickets],
            decisions,
            tickets=True,
            budgets=pots,
        )

    file = with_tickets()
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert found.caps == (CapRow("trip-money-cap", 0, (), (), 0, 10000, 0),)
    assert in_words(file)[-1] == (
        "  trip-money-cap: at most 1 USD from trip-money: 0 paid; 0 still to buy;"
        " up to 1 more to buy, depending on which OPTIONs need a right; 0 left"
    )
    spent = with_tickets(booking("tour", "jo", paid="1 USD", budget="trip-money"))
    assert asked(spent) == [[Unknown("needs no right", "tour")]]


# ------------------------------- What a report asks, with caps -------------------------------


def test_two_receipts_that_might_charge_one_cap_are_in_one_sum() -> None:
    tickets = [booking("tour", "alex", id="first"), booking("tour", "jo", id="second")]
    file = a_tour(*tickets, locked=(), caps=[cap("trip-money", "1 USD")])
    found = checked(file)
    assert asked(file) == [[charged("first"), charged("second")]]
    both = (("first", None), ("second", None))
    row = CapRow("trip-money-cap", 0, both, ("first", "second"), 0, 0, 10000)
    assert found.plans == (Plan((), (row,)),)
    assert in_words(file)[2:5] == [
        "The trip works if the FILE states what first paid and from which BUDGET and the FILE"
        " states what second paid and from which BUDGET.",
        f"  One plan that works then: {NOTHING}.",
        "  trip-money-cap, on trip-money: nothing so far, of at most 1 USD. That leaves 1 USD"
        f" {LEAVES}",
    ]


def test_a_receipt_that_no_set_asks_about_is_still_in_the_sum() -> None:
    """A cap of 10 USD. One BOOKING states no payment, and one paid 3 USD from somewhere."""
    tickets = [
        booking("tour", "alex", id="unstated"),
        booking("tour", "jo", id="loose", paid="3 USD"),
    ]
    file = a_tour(*tickets, locked=(), caps=[cap("trip-money", "10 USD")])
    found = checked(file)
    assert asked(file) == [[charged("unstated")]]
    might = (("unstated", None), ("loose", 30000))
    row = CapRow("trip-money-cap", 0, might, ("unstated",), 0, 0, 70000)
    assert found.plans == (Plan((), (row,)),)
    assert in_words(file)[4] == (
        "  trip-money-cap, on trip-money: up to 3 that loose might have charged it, of at most"
        " 10 USD. That leaves 7 USD for whatever else is charged to it, and more once the FILE"
        " says that loose charged it less."
    )
    plans = report.as_json(file, found)["plans"]
    assert plans == [
        {
            "buys": [],
            "caps": [
                {
                    "cap": "trip-money-cap",
                    "budget": "trip-money",
                    "currency": "USD",
                    "limit": "10",
                    "paid": "0",
                    "might_be_paid": [
                        {"booking": "unstated", "amount": None},
                        {"booking": "loose", "amount": "3"},
                    ],
                    "to_buy": "0",
                    "to_buy_at_most_if_needed": "0",
                    "asked": ["unstated"],
                    "left": "7",
                }
            ],
        }
    ]


def test_two_files_that_ask_for_the_same_price_show_what_the_cap_has_left() -> None:
    """One place with no stated price for Sam. An unused BOOKING paid 0 or 1 USD from A."""
    pots = [budget("a", "sam")]
    place = [offer("tour", 1, price=None), every_right("tour", "tour-offer")]
    reports: list[list[str]] = []
    for paid, answer in (("0 USD", Answer.FEASIBLE), ("1 USD", Answer.INFEASIBLE)):
        ticket = booking("tour", "alex", paid=paid, budget="a")
        file = a_tour(ticket, *place, budgets=pots, caps=[cap("a", "1 USD")])
        assert asked(file) == [[Unknown("price", "tour", about="tour-offer")]]
        reports.append(in_words(file))
        quoted = [offer("tour", 1, price="1 USD"), place[1]]
        told = a_tour(ticket, *quoted, budgets=pots, caps=[cap("a", "1 USD")])
        assert checked(told).answer is answer
    assert (
        reports[0][4]
        == f"  a-cap, on a: nothing so far, of at most 1 USD. That leaves 1 USD {LEAVES}"
    )
    assert reports[1][4] == f"  a-cap, on a: 1 paid, of at most 1 USD. That leaves 0 USD {LEAVES}"


def test_a_price_for_two_buyers_is_in_the_sum_twice() -> None:
    """Sam and Jo draw on A, which may spend 1 USD. Two places have no stated price."""
    pots = [budget("a", "sam", "jo")]
    places = [offer("tour", 2, id="first", price=None), offer("tour", 1, id="spare", price="1 USD")]
    whole = every_right("tour", "first", "spare")
    file = a_tour(*places, whole, locked=("sam", "jo"), budgets=pots, caps=[cap("a", "1 USD")])
    found = checked(file)
    assert asked(file) == [[Unknown("price", "tour", about="first")]]
    assert found.plans[0].caps == (CapRow("a-cap", 0, (), (), 0, 0, 10000),)
    assert in_words(file)[3:5] == [
        "  One plan that works then: sam buys a place from first at a price that the FILE has yet"
        " to state; jo buys a place from first at a price that the FILE has yet to state.",
        f"  a-cap, on a: nothing so far, of at most 1 USD. That leaves 1 USD {LEAVES}",
    ]
    for quote, answer in (("0.50 USD", Answer.FEASIBLE), ("0.51 USD", Answer.INFEASIBLE)):
        stated = [offer("tour", 2, id="first", price=quote), places[1]]
        told = a_tour(*stated, whole, locked=("sam", "jo"), budgets=pots, caps=[cap("a", "1 USD")])
        assert checked(told).answer is answer


def test_the_plan_for_a_length_of_time_works_at_the_limit_the_report_gives() -> None:
    """Sam's visit starts at 9:00 am and nobody knows how long it takes. A show is a must.

    One show is at 10:00 am and one at 11:00 am. A ticket costs 1 USD, and the cap is 1 USD.
    The visit may take two hours, and then only the later show can be reached.
    """
    options = [stays("visit", "hall"), stays("early", "hall"), stays("late", "hall")]
    facts = [starts_at("visit", 9), cutoff("visit", "PT0S"), needs_no_right("visit")]
    facts += [*at("early", 10), *at("late", 11), needs_right("early"), needs_right("late")]
    facts += [offer("early", 1, price="1 USD"), offer("late", 1, price="1 USD")]
    facts += [every_right("early", "early-offer"), every_right("late", "late-offer")]
    facts += [satisfies("early", "show"), satisfies("late", "show"), every("show")]
    decisions = [lock("visit", "sam"), cap("money", "1 USD")]
    file = trip(
        ["sam"], ["hall"], options, facts, decisions, wants=[must("show", "sam")], tickets=True
    )
    found = checked(file)
    assert [needed.at_most for needed in found.missing[0]] == [seconds(2) - seconds(0)]
    assert [cover.by for cover in found.plans[0].buys] == ["late-offer"]
    assert in_words(file)[2:4] == [
        "The trip works if visit takes 2 h or less.",
        "  One plan that works then: sam buys a place from late-offer for 1 USD from money.",
    ]


def test_a_price_nobody_knows_has_to_fit_in_what_each_budget_has_left() -> None:
    """A lists Sam and Jo, and B lists Jo. Each may spend 1 USD. Two places have no price."""
    pots = [budget("a", "sam", "jo"), budget("b", "jo")]
    places = [offer("tour", 2, id="first", price=None), every_right("tour", "first")]
    caps = [cap("a", "1 USD"), cap("b", "1 USD")]
    file = a_tour(*places, locked=("sam", "jo"), budgets=pots, caps=caps)
    assert [row.left for row in checked(file).plans[0].caps] == [10000, 10000]
    # At 1 USD a place, A pays for Sam and B for Jo: each fits in what its cap has left.
    stated = [offer("tour", 2, id="first", price="1 USD"), places[1]]
    told = checked(a_tour(*stated, locked=("sam", "jo"), budgets=pots, caps=caps))
    assert [cover.budget for cover in told.rights] == ["a", "b"]
    dearer = [offer("tour", 2, id="first", price="1.01 USD"), places[1]]
    assert checked(a_tour(*dearer, locked=("sam", "jo"), budgets=pots, caps=caps)).answer is (
        Answer.INFEASIBLE
    )


def test_what_the_writer_finds_has_to_fit_in_what_a_cap_has_left() -> None:
    """A right that is found and a new payer can cost money. The report says what is left."""
    low = [cap("trip-money", "1 USD")]
    file = a_tour(caps=low, persons=["sam"])
    assert in_words(file)[2:7] == [
        "The trip works if a right to tour is found for sam, at a cost that fits the caps.",
        f"  One plan that works then: {NOTHING}.",
        "  trip-money-cap, on trip-money: nothing so far, of at most 1 USD. That leaves 1 USD"
        f" {LEAVES}",
        "",
        "Whatever the FILE comes to state counts against a cap like everything else: what a"
        " BOOKING paid from its BUDGET in its currency, and each place that its BUDGET pays for."
        " All of it has to fit in what the cap has left.",
    ]
    # A BOOKING that is found counts where it was paid from, whoever that BUDGET lists.
    pots = [budget("a", "sam"), budget("b")]
    for paid, answer in (("1 USD", Answer.FEASIBLE), ("1.01 USD", Answer.INFEASIBLE)):
        ticket = booking("tour", "sam", paid=paid, budget="b")
        told = a_tour(ticket, budgets=pots, caps=[cap("b", "1 USD")], persons=["sam"])
        assert checked(told).answer is answer
    # Two places at 1 USD for Sam and Jo, whom no BUDGET lists. A may spend 1 USD.
    places = [offer("tour", 2, price="1 USD"), every_right("tour", "tour-offer")]
    one_cap = [cap("a", "1 USD")]
    nobody = a_tour(*places, locked=("sam", "jo"), budgets=[budget("a")], caps=one_cap)
    assert [row.left for row in checked(nobody).plans[0].caps] == [10000]
    both_on_a = [budget("a", "sam", "jo")]
    apart = [budget("a", "sam"), budget("b", "jo")]
    for pots, answer in ((both_on_a, Answer.INFEASIBLE), (apart, Answer.FEASIBLE)):
        told = a_tour(*places, locked=("sam", "jo"), budgets=pots, caps=one_cap)
        assert checked(told).answer is answer


def test_the_plan_for_any_length_of_time_works_however_long_it_is() -> None:
    """Sam takes a bus at 9:00 am, and nobody knows how long it takes. A show is a must.

    One show is at 10:00 am, and one can start at any time. The plan buys the second.
    """
    options = [moves("bus", "home", "hall"), stays("fixed", "hall"), stays("flexible", "hall")]
    facts = [starts_at("bus", 9), cutoff("bus", "PT0S"), needs_no_right("bus"), *at("fixed", 10)]
    facts += [any_time("flexible"), lasts("flexible", "PT1H"), cutoff("flexible", "PT0S")]
    facts += [needs_right("fixed"), needs_right("flexible")]
    facts += [offer("fixed", 1, price="1 USD"), offer("flexible", 1, price="1 USD")]
    facts += [every_right("fixed", "fixed-offer"), every_right("flexible", "flexible-offer")]
    facts += [satisfies("fixed", "show"), satisfies("flexible", "show"), every("show")]
    decisions = [lock("bus", "sam"), cap("money", "1 USD")]
    places = ["home", "hall"]
    file = trip(
        ["sam"], places, options, facts, decisions, wants=[must("show", "sam")], tickets=True
    )
    found = checked(file)
    assert [needed.unknown.what for needed in found.missing[0]] == ["duration"]
    assert found.missing[0][0].at_most is None
    assert [cover.by for cover in found.plans[0].buys] == ["flexible-offer"]


def test_a_price_and_a_payer_can_both_be_needed_beside_a_cap() -> None:
    """Jo draws on A, which may spend nothing. No BUDGET lists Sam. Two OFFERs of one place."""
    pots = [budget("a", "jo")]
    offers = [
        offer("tour", 1, id="unpriced", price=None),
        offer("tour", 1, id="priced", price="1 USD"),
    ]
    file = a_tour(
        *offers,
        every_right("tour", "unpriced", "priced"),
        locked=("sam", "jo"),
        budgets=pots,
        caps=[cap("a", "0 USD")],
    )
    assert asked(file) == [
        [Unknown("price", "tour", about="unpriced"), Unknown("funding", person="sam")]
    ]
    plan = checked(file).plans[0]
    assert [(cover.person, cover.by, cover.budget) for cover in plan.buys] == [
        ("sam", "priced", None),
        ("jo", "unpriced", None),
    ]


# ------------------------------- A conflict -------------------------------


def test_removing_a_booking_forgets_whom_it_covers_and_what_it_charged() -> None:
    """A may spend nothing. Alex's BOOKING charged it 1 USD, and Sam's place costs 1 USD."""
    pots = [budget("a", "alex", "sam")]
    file = a_tour(
        booking("tour", "alex", paid="1 USD", budget="a"),
        offer("tour", 1, price="1 USD"),
        every_right("tour", "tour-offer"),
        budgets=pots,
        caps=[cap("a", "0 USD")],
    )
    found = checked(file)
    assert found.answer is Answer.INFEASIBLE
    assert found.conflict == ("tour-booking", "a-cap")
    assert has_no_record_to_spare(file, found.conflict)
    # Taken out of the whole FILE, the BOOKING might cover Sam and have charged nothing.
    whole = Remaining(file)
    assert ruled_out(whole) and not ruled_out(whole.without("tour-booking"))
    # Forgetting only one of the two is not enough.
    assert ruled_out(replace(whole, open_to_all=frozenset({"tour"})))
    no_charge = replace(file, facts=tuple(f for f in file.facts if f.id != "tour-booking"))
    assert ruled_out(Remaining(no_charge))


def test_a_conflict_names_a_booking_that_states_no_payment_as_that() -> None:
    """A may spend nothing. Alex has a BOOKING, and Sam's place costs 1 USD."""
    pots = [budget("a", "alex", "sam")]
    file = a_tour(
        booking("tour", "alex"),
        offer("tour", 1, price="1 USD"),
        every_right("tour", "tour-offer"),
        budgets=pots,
        caps=[cap("a", "0 USD")],
    )
    found = checked(file)
    assert found.answer is Answer.INFEASIBLE and "tour-booking" in found.conflict
    as_json = report.as_json(file, found)
    assert as_json["payments"] == [] and as_json["not_stated"] == ["tour-booking"]
    assert "  tour-booking: a BOOKING for tour covers alex; it states no payment" in in_words(file)


def test_removing_a_cap_lifts_that_limit_only() -> None:
    """A holds dollars and euros, and each has a cap. Only the dollars are overspent."""
    pots = [budget("a", "alex", holds=["USD", "EUR"])]
    tickets = [
        booking("tour", "alex", id="dollars", paid="2 USD", budget="a"),
        booking("tour", "jo", id="euros", paid="1 EUR", budget="a"),
    ]
    caps = [cap("a", "1 USD", id="usd-cap"), cap("a", "1 EUR", id="eur-cap")]
    file = a_tour(*tickets, locked=(), budgets=pots, caps=caps)
    found = checked(file)
    assert found.conflict == ("dollars", "usd-cap")
    assert has_no_record_to_spare(file, found.conflict)
    without_the_cap = replace(file, decisions=tuple(d for d in file.decisions if d.id != "usd-cap"))
    assert checked(without_the_cap).answer is Answer.FEASIBLE


# ------------------------------- Against every possible world -------------------------------


def a_capped_tour(rng: Random) -> File:
    """One tour with every time stated, some BOOKINGs, some OFFERs, two BUDGETs and their caps."""
    persons = ["alex", "sam", "jo"]
    buyers = rng.sample(persons, rng.randrange(0, 3))
    pots = [
        budget("a", *rng.sample(persons, rng.randrange(1, 4))),
        budget("b", *rng.sample(persons, 2)),
    ]
    facts: list[Document] = []
    for number in range(rng.randrange(0, 3)):
        holder = rng.choice([person for person in persons if person not in buyers])
        paid = rng.choice([None, "0 USD", "1 USD", "2 USD"])
        source = rng.choice([None, "a", "b"]) if paid else None
        facts.append(booking("tour", holder, id=f"ticket-{number}", paid=paid, budget=source))
    offers = [f"offer-{number}" for number in range(rng.randrange(1, 3))]
    prices = ["0 USD", "1 USD", "2 USD"]
    facts += [
        offer("tour", rng.choice([1, 2]), id=name, price=rng.choice(prices)) for name in offers
    ]
    facts.append(every_right("tour", *offers))
    caps = [cap(pot, f"{rng.randrange(0, 4)} USD") for pot in ("a", "b") if rng.random() < 0.8]
    return a_tour(*facts, locked=buyers, budgets=pots, caps=caps, persons=persons)


def every_way_the_charges_could_be(file: File) -> list[dict[tuple[str, str], int]]:
    """For each possible world, what the BOOKINGs charged to each cap, in ten-thousandths.

    A payment that names no BUDGET came from A, from B or from outside. A BOOKING with no
    stated payment paid nothing, or more than any cap, from A or from B.
    """
    fixed = dict.fromkeys(file.caps, 0)
    open_ended: list[list[dict[tuple[str, str], int]]] = []
    for fact in file.facts:
        if not isinstance(fact, Booking):
            continue
        if fact.paid is None:
            open_ended.append([{}, {("a", "USD"): 10**9}, {("b", "USD"): 10**9}])
        elif fact.paid.budget is None and fact.paid.money.amount:
            units = fact.paid.money.units
            open_ended.append([{}, {("a", "USD"): units}, {("b", "USD"): units}])
        elif fact.paid.budget is not None and (fact.paid.budget, "USD") in fixed:
            fixed[fact.paid.budget, "USD"] += fact.paid.money.units
    worlds: list[dict[tuple[str, str], int]] = []
    for each in product(*open_ended):
        charged_so_far = dict(fixed)
        for charge in each:
            for key, units in charge.items():
                if key in charged_so_far:
                    charged_so_far[key] += units
        worlds.append(charged_so_far)
    return worlds


def every_way_to_pay(
    file: File, buyers: Sequence[str], funded: bool
) -> list[tuple[tuple[str, str | None], ...]]:
    """Every way to give each buyer a place of an OFFER and a BUDGET that may pay for it.

    Nobody knows who pays for a PERSON whom no BUDGET lists. With ``funded``, money from
    outside the FILE pays for them, and no cap counts it. Without, nothing does.
    """
    choices: list[list[tuple[str, str | None]]] = []
    for person in buyers:
        able: list[tuple[str, str | None]] = []
        for each in file.offers("tour"):
            assert each.price is not None
            if not each.price.amount or (funded and not file.listed(person)):
                able.append((each.id, None))
            able += [(each.id, pot.id) for pot in file.payers(person, "USD") if each.price.amount]
        choices.append(able)
    ways = product(*choices)
    places = {each.id: each.places for each in file.offers("tour")}
    return [
        way for way in ways if all([o for o, _ in way].count(i) <= n for i, n in places.items())
    ]


def keeps_every_cap(
    file: File, way: Sequence[tuple[str, str | None]], charged_so_far: dict[tuple[str, str], int]
) -> bool:
    prices = {fact.id: fact.price for fact in file.facts if isinstance(fact, Offer)}
    total = dict(charged_so_far)
    for each, pot in way:
        price = prices[each]
        if pot is not None and price is not None and (pot, "USD") in total:
            total[pot, "USD"] += price.units
    return all(total[key] <= limit.limit.units for key, limit in file.caps.items())


def test_the_answers_hold_for_one_way_to_pay_in_every_possible_world() -> None:
    """FEASIBLE: one way to pay keeps every cap in every world. INFEASIBLE: none does in any."""
    rng = Random(4747)
    seen: set[Answer] = set()
    split = 0
    for _ in range(2500):
        file = a_capped_tour(rng)
        buyers = (
            [person.id for person in file.persons if person.id in file.locks[0].persons]
            if file.locks
            else []
        )
        buyers = [person for person in buyers if file.booking("tour", person) is None]
        worlds = every_way_the_charges_could_be(file)
        ways = every_way_to_pay(file, buyers, funded=False)
        at_best = every_way_to_pay(file, buyers, funded=True)
        everywhere = any(all(keeps_every_cap(file, way, world) for world in worlds) for way in ways)
        somewhere = any(keeps_every_cap(file, way, world) for way in at_best for world in worlds)
        found = checked(file)
        seen.add(found.answer)
        assert (found.answer is Answer.FEASIBLE) == everywhere
        assert (found.answer is Answer.INFEASIBLE) == (not somewhere)
        each_world = all(any(keeps_every_cap(file, way, world) for way in ways) for world in worlds)
        split += each_world and not everywhere
        if found.answer is Answer.INFEASIBLE:
            assert has_no_record_to_spare(file, found.conflict)
        if found.answer is Answer.FEASIBLE:
            way = tuple((cover.by, cover.budget) for cover in found.rights if cover.to_buy)
            assert all(keeps_every_cap(file, way, world) for world in worlds)
    assert seen == set(Answer)
    assert split > 0


# ------------------------------------- With the solver --------------------------------------


def two_capped_visits(rng: Random) -> File:
    """Two visits at one PLACE with BOOKINGs, OFFERs, two BUDGETs and their caps.

    Nothing about time is unknown. Rights, prices, payers and charges can be.
    """
    persons = ["alex", "sam", "jo"]
    options = [stays("tour", "dock"), stays("talk", "dock")]
    pots = [
        budget("a", *rng.sample(persons, rng.randrange(1, 4))),
        budget("b", *rng.sample(persons, 2)),
    ]
    facts: list[Document] = []
    decisions: list[Document] = []
    for number, option in enumerate(("tour", "talk")):
        facts += at(option, 10 + 2 * number)
        if rng.random() < 0.8:
            facts.append(needs_right(option))
        for count in range(rng.randrange(0, 3)):
            paid = rng.choice([None, "0 USD", "1 USD", "2 USD"])
            source = rng.choice([None, "a", "b"]) if paid else None
            covered = rng.sample(persons, rng.randrange(1, 3))
            ticket = f"{option}-ticket-{count}"
            facts.append(booking(option, *covered, id=ticket, paid=paid, budget=source))
        offers = [f"{option}-offer-{count}" for count in range(rng.randrange(0, 3))]
        prices = ["0 USD", "1 USD", "2 USD", None]
        facts += [
            offer(option, rng.choice([1, 2]), id=name, price=rng.choice(prices)) for name in offers
        ]
        if rng.random() < 0.6:
            facts.append(every_right(option, *offers))
        if rng.random() < 0.8:
            decisions.append(lock(option, *rng.sample(persons, rng.randrange(1, 4))))
    decisions += [
        cap(pot, f"{rng.randrange(0, 5)} USD") for pot in ("a", "b") if rng.random() < 0.8
    ]
    return trip(persons, ["dock"], options, facts, decisions, tickets=True, budgets=pots)


def test_the_solver_gives_the_reference_checkers_report_for_trips_with_caps() -> None:
    """The answer ahead and the Report, on random trips with one visit and with two."""
    rng = Random(4848)
    seen: set[Answer] = set()
    capped = with_plans = 0
    trips = [two_capped_visits(rng) for _ in range(250)]
    trips += [a_capped_tour(rng) for _ in range(150)]
    for file in trips:
        series = list(answers.reports(file))
        assert list(compiler.reports(file)) == series
        found = series[-1]
        assert isinstance(found, Report)
        assert compiler.check(file) == found
        seen.add(found.answer)
        capped += bool(file.caps)
        with_plans += bool(found.plans)
    assert seen == set(Answer)
    assert capped > 250
    assert with_plans > 30


def test_the_solver_builds_a_model_for_a_trip_with_a_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reference checker's own search is not asked: the solver shares out the BUDGETs."""
    paid = booking("tour", "alex", paid="32.00 USD", budget="trip-money")
    file = a_tour(paid, offer("tour", 2, price="32.00 USD"), caps=[cap("trip-money", "200.00 USD")])
    expected = checked(file)

    def not_asked(*given: object, **named: object) -> None:
        raise AssertionError("the reference checker's search was asked")

    monkeypatch.setattr(reference, "itineraries", not_asked)
    assert compiler.check(file) == expected
    (row,) = expected.caps
    assert (row.paid, row.to_buy, row.left) == (320_000, 320_000, 1_360_000)


def test_a_place_that_costs_more_than_a_cap_has_left_is_paid_from_another_budget() -> None:
    """Sam's place costs 2 USD. The first BUDGET has 1 USD left, and the second has room."""
    pots = [budget("a", "sam"), budget("b", "sam")]
    paid = booking("tour", "alex", paid="1 USD", budget="a")
    caps = [cap("a", "2 USD"), cap("b", "2 USD")]
    file = a_tour(paid, offer("tour", 1, price="2 USD"), budgets=pots, caps=caps)
    found = compiler.check(file)
    assert found == checked(file)
    assert [(cover.person, cover.budget) for cover in found.rights if cover.to_buy] == [
        ("sam", "b")
    ]


def test_amounts_too_large_for_the_solver_go_to_the_reference_checker() -> None:
    """A cap, and six hundred places at the largest price a FILE can state."""
    most = "999999999999.9999 USD"
    persons = [f"p{number}" for number in range(3)]
    places = [offer("tour", 1, id=f"offer-{number}", price=most) for number in range(600)]
    file = a_tour(*places, locked=["p0"], caps=[cap("trip-money", most)], persons=persons)
    with pytest.raises(compiler.DoesNotFit):
        compiler.works(file, worst_case(file))
    found = compiler.check(file)
    assert found == checked(file)
    assert found.answer is Answer.FEASIBLE


def test_bookings_that_pass_a_cap_are_seen_before_a_model_is_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One BOOKING paid 2 USD from a BUDGET with a cap of 1 USD. No plan can change that.

    So the two questions that give the answer need no model. The search for the conflict
    builds one only where the BOOKING or the cap is taken out.
    """
    facts = [starts_from("sam", "home"), needs_right("ride")]
    facts.append(booking("ride", "sam", paid="2 USD", budget="money"))
    options = [moves("ride", "stop", "home")]
    file = trip(["sam"], ["home", "stop"], options, facts, [cap("money", "1 USD")], tickets=True)
    found = compiler.check(file)
    assert found == checked(file)
    assert found.answer is Answer.INFEASIBLE
    assert found.conflict == ("ride-booking", "money-cap")

    def not_built(*given: object, **named: object) -> None:
        raise AssertionError("a model was built")

    monkeypatch.setattr(compiler._Search, "__init__", not_built)  # pyright: ignore[reportPrivateUsage]
    assert compiler.shown(file, worst_case(file)) is None
    assert not compiler.works(file, worst_case(file))
    assert not compiler.can_work(Remaining(file))
    assert not compiler.can_work(Remaining(file).without("ride-right"))


def a_weekend(limit: str, sold: bool = False) -> File:
    """Four PERSONs start from the hotel and must end there, with a cap on the trip money.

    Each of three sights is a WANT that all four must have, and it has two times to choose
    from. Every visit needs a ticket at 10 USD. Alex has paid for the first one. With
    ``sold``, FACTs say that the OFFER listed for each visit is every right to it.
    """
    people = ["alex", "sam", "jo", "max"]
    sights = ["skydeck", "museum", "pier"]
    ways = [way_between(f"hotel-{sight}", "hotel", sight) for sight in sights]
    ways += [way_between("skydeck-museum", "skydeck", "museum")]
    ways += [way_between("museum-pier", "museum", "pier")]
    facts = [starts_from(person, "hotel") for person in people]
    facts += [takes(each["id"], "PT10M") for each in ways]
    options: list[Document] = []
    wants = [ends_at("hotel", *people)]
    for number, sight in enumerate(sights):
        wants.append(must(f"see-{sight}", *people))
        facts.append(every(f"see-{sight}"))
        for turn in ("early", "late"):
            name = f"{sight}-{turn}"
            options.append(stays(name, sight))
            facts += [*at(name, 9 + 2 * number + (turn == "late")), satisfies(name, f"see-{sight}")]
            facts += [needs_right(name), offer(name, 4, price="10.00 USD")]
            facts += [every_right(name, f"{name}-offer")] if sold else []
    facts.append(booking("skydeck-early", "alex", paid="10.00 USD", budget="money"))
    return trip(
        people, ["hotel", *sights], options, facts, [cap("money", limit)], ways, wants, True
    )


def test_the_solver_answers_a_weekend_with_a_cap() -> None:
    """The reference checker tries every way to share out the visits.

    Nine minutes are not enough for it, so no test compares the two on this FILE.
    """
    found = compiler.check(a_weekend("200.00 USD"))
    assert found.answer is Answer.FEASIBLE
    visits = [step.option for step in found.itinerary if step.option is not None]
    assert visits == ["skydeck-early", "museum-early", "pier-early"]
    (row,) = found.caps
    assert (row.paid, row.to_buy, row.left) == (100_000, 1_100_000, 800_000)


def test_a_weekend_over_its_cap_cannot_work_where_the_tickets_listed_are_all_there_are() -> None:
    """Eleven tickets at 10 USD are still to buy, and Alex's ticket took 10 USD of the cap."""
    found = compiler.check(a_weekend("110.00 USD", sold=True))
    assert found.answer is Answer.INFEASIBLE
    assert "money-cap" in found.conflict
    assert compiler.check(a_weekend("120.00 USD", sold=True)).answer is Answer.FEASIBLE


def test_a_weekend_over_its_cap_depends_on_what_the_file_does_not_say() -> None:
    """Nothing says that the tickets listed are all there are, so another right might be found."""
    ahead, *_ = compiler.reports(a_weekend("110.00 USD"))
    assert ahead is Answer.UNDETERMINED
