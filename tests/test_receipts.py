"""Receipts: a BOOKING can state what it paid, and a report adds up the money."""

from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal
from random import Random

import pytest

from agloe import compiler, report
from agloe.answers import Answer
from agloe.file import Booking, File, FileError, Money, Payment
from tests.stories import (
    Document,
    booking,
    budget,
    cutoff,
    lasts,
    lock,
    needs_right,
    offer,
    starts_at,
    stays,
    trip,
)
from tests.test_cross_check import random_trip
from tests.test_where_a_path_ends import checked

EVERYONE = ["alex", "sam", "jo"]
ADDED_UP = "What is paid, and what this plan still has to pay:"


def at(option: str, hour: int) -> list[Document]:
    """An OPTION that starts at this hour, with nothing left unknown about its time."""
    return [starts_at(option, hour), lasts(option, "PT1H"), cutoff(option, "PT0S")]


def a_tour_and_a_talk(*more: Document, budgets: Sequence[Document] | None = None) -> File:
    """A boat tour at 10:00 am that needs a right, and a talk at noon that might.

    A LOCK names all three in the tour and Alex in the talk. An OFFER has two places for the
    tour at 32.00 USD, and one for the talk at 8.50 USD. One BUDGET, the trip money, pays in
    USD for everybody, unless the test names others.
    """
    if budgets is None:
        budgets = [budget("trip-money", *EVERYONE)]
    options = [stays("tour", "dock"), stays("talk", "dock")]
    facts = [*at("tour", 10), *at("talk", 12), needs_right("tour"), *more]
    facts += [offer("tour", 2, price="32.00 USD"), offer("talk", 1, price="8.50 USD")]
    locked = [lock("tour", *EVERYONE), lock("talk", "alex")]
    return trip(EVERYONE, ["dock"], options, facts, locked, tickets=True, budgets=budgets)


def in_words(file: File) -> list[str]:
    return report.as_text(file, checked(file)).splitlines()


def problems(*facts: Document) -> str:
    with pytest.raises(FileError) as refused:
        a_tour_and_a_talk(*facts)
    return str(refused.value)


# ------------------------------- What a FILE holds -------------------------------


def test_a_booking_can_state_what_it_paid_from_which_budget_and_who_paid() -> None:
    whole = booking("tour", "alex", paid="32.00 USD", budget="trip-money", by="sam")
    file = a_tour_and_a_talk(whole, booking("tour", "jo", id="jos", paid="5 EUR"))
    paid = [fact.paid for fact in file.facts if isinstance(fact, Booking)]
    assert paid == [
        Payment(Money(Decimal("32.00"), "USD"), "trip-money", "sam"),
        Payment(Money(Decimal(5), "EUR")),
    ]
    assert a_tour_and_a_talk(booking("tour", "alex")).booking("tour", "alex") == Booking(
        "tour-booking", "tour", ("alex",), None
    )


def test_a_payment_names_a_budget_of_the_file_that_holds_its_currency() -> None:
    unknown = booking("tour", "alex", paid="32.00 USD", budget="savings")
    assert problems(unknown) == "/facts/7: savings is not a BUDGET in this FILE"
    in_euros = booking("tour", "alex", paid="32.00 EUR", budget="trip-money")
    assert problems(in_euros) == "/facts/7: trip-money holds no EUR"
    stranger = booking("tour", "alex", paid="32.00 USD", by="pat")
    assert problems(stranger) == "/facts/7: pat is not a PERSON in this FILE"


def test_a_payment_can_come_from_a_budget_that_lists_neither_payer_nor_covered() -> None:
    """Jo paid for Alex from a BUDGET that lists only Sam. A payment that was made counts."""
    pots = [budget("sams", "sam")]
    paid = booking("tour", "alex", paid="32.00 USD", budget="sams", by="jo")
    file = a_tour_and_a_talk(paid, budgets=pots)
    assert file.booking("tour", "alex") == Booking(
        "tour-booking", "tour", ("alex",), Payment(Money(Decimal("32.00"), "USD"), "sams", "jo")
    )


@pytest.mark.parametrize("amount", ["032", "-1", "1e2", "1,000", "1.23456", ""])
def test_a_payment_is_written_like_any_amount(amount: str) -> None:
    paid = booking("tour", "alex", paid="1 USD")
    paid["booking"]["paid"]["amount"] = amount
    assert "fits no known shape" in problems(paid)


def test_a_payment_holds_nothing_but_its_four_parts() -> None:
    paid = booking("tour", "alex", paid="1 USD")
    paid["booking"]["paid"]["deposit"] = True
    assert "fits no known shape" in problems(paid)
    no_currency = booking("tour", "alex", paid="1 USD")
    del no_currency["booking"]["paid"]["currency"]
    assert "fits no known shape" in problems(no_currency)


# ------------------------------- What a report says -------------------------------


def test_a_booking_says_what_it_paid_in_words() -> None:
    cases = {
        "alex paid 32.00 USD for it from trip-money": {"budget": "trip-money", "by": "alex"},
        "32.00 USD was paid for it from trip-money": {"budget": "trip-money"},
        "sam paid 32.00 USD for it": {"by": "sam"},
        "32.00 USD was paid for it": {},
    }
    for said, parts in cases.items():
        file = a_tour_and_a_talk(booking("tour", "alex", paid="32.00 USD", **parts))
        assert f"  tour-booking: a BOOKING for tour covers alex; {said}" in in_words(file)
    free = a_tour_and_a_talk(booking("tour", "alex", paid="0 USD", by="alex"))
    assert "  tour-booking: a BOOKING for tour covers alex; alex paid nothing for it" in (
        in_words(free)
    )
    unstated = a_tour_and_a_talk(booking("tour", "alex"))
    assert "  tour-booking: a BOOKING for tour covers alex" in in_words(unstated)


def test_a_report_adds_up_what_is_paid_and_what_is_still_to_pay() -> None:
    """Alex has a ticket for the tour. Jo has one for the talk, and does not go."""
    file = a_tour_and_a_talk(
        booking("tour", "alex", paid="32.00 USD", budget="trip-money", by="alex"),
        booking("talk", "jo", id="jo-talk", paid="5 EUR"),
        booking("talk", "sam", id="sam-talk"),
    )
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert in_words(file)[-4:] == [
        ADDED_UP,
        "  32.00 USD paid (tour-booking); 64.00 USD still to pay (tour-offer);"
        " 8.50 USD to pay only if a right is needed (talk-offer)",
        "  5 EUR paid (jo-talk)",
        "  No payment is stated for sam-talk.",
    ]
    dollars = {"currency": "USD", "paid": "32.00", "to_pay": "64.00", "to_pay_if_needed": "8.50"}
    euros = {"currency": "EUR", "paid": "5", "to_pay": "0", "to_pay_if_needed": "0"}
    first = {"booking": "tour-booking", "amount": "32.00", "currency": "USD"}
    second = {"booking": "jo-talk", "amount": "5", "currency": "EUR", "budget": None, "by": None}
    assert report.as_json(file, found)["money"] == {
        "totals": [dollars, euros],
        "paid": [{**first, "budget": "trip-money", "by": "alex"}, second],
        "not_stated": ["sam-talk"],
    }
    assert report.as_json(file, compiler.check(file)) == report.as_json(file, found)


def test_amounts_in_one_currency_are_added_exactly() -> None:
    file = a_tour_and_a_talk(
        booking("tour", "alex", paid="0.1 USD"),
        booking("tour", "sam", id="sams", paid="0.2 USD"),
        booking("tour", "jo", id="jos", paid="999999999999.9999 USD"),
    )
    assert in_words(file)[-1] == (
        "  1000000000000.2999 USD paid (tour-booking, sams and jos);"
        " 8.50 USD to pay only if a right is needed (talk-offer)"
    )


def test_a_report_adds_up_nothing_where_there_is_nothing_to_add() -> None:
    """Everybody has a BOOKING. None states a payment above nothing, and nothing is bought."""
    tickets = [booking("tour", *EVERYONE, paid="0 USD"), booking("talk", "alex", id="talks")]
    file = a_tour_and_a_talk(*tickets)
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert ADDED_UP not in in_words(file)
    assert "money" not in report.as_json(file, found)


def test_a_payment_of_nothing_is_stated_and_counts_in_no_currency() -> None:
    tickets = [booking("tour", *EVERYONE, paid="0 USD"), booking("talk", "jo", id="jos")]
    file = a_tour_and_a_talk(*tickets)
    assert in_words(file)[-3:] == [
        ADDED_UP,
        "  8.50 USD to pay only if a right is needed (talk-offer)",
        "  No payment is stated for jos.",
    ]
    money = report.as_json(file, checked(file))["money"]
    assert isinstance(money, dict)
    assert money["not_stated"] == ["jos"]
    nothing = {"booking": "tour-booking", "amount": "0", "currency": "USD"}
    assert money["paid"] == [{**nothing, "budget": None, "by": None}]


def test_only_a_plan_adds_up_the_money() -> None:
    """A TRIP that cannot work and one that depends on a FACT show no sums."""
    paid = booking("tour", "alex", paid="32.00 USD")
    one_place = [paid, offer("tour", 1, id="one", price="1 USD")]
    options = [stays("tour", "dock")]
    locked = [lock("tour", *EVERYONE)]
    facts = [*at("tour", 10), needs_right("tour"), *one_place]
    file = trip(EVERYONE, ["dock"], options, facts, locked, tickets=True)
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    assert ADDED_UP not in in_words(file)
    assert "money" not in report.as_json(file, found)


# ------------------------------- No answer turns on a payment -------------------------------


def with_payments(file: File, rng: Random) -> File:
    """The same FILE, where most BOOKINGs state some payment."""
    facts: list[object] = []
    for fact in file.facts:
        if isinstance(fact, Booking) and rng.random() < 0.8:
            currency = rng.choice(["USD", "EUR", "points"])
            amount = Decimal(rng.choice(["0", "0.5", "10.00", "999999999999.9999"]))
            holders = [each.id for each in file.budgets if currency in each.currencies]
            source = rng.choice([None, *holders])
            payer = rng.choice([None, *(person.id for person in file.persons)])
            fact = replace(fact, paid=Payment(Money(amount, currency), source, payer))
        facts.append(fact)
    return replace(file, facts=tuple(facts))  # pyright: ignore[reportArgumentType]


def test_what_a_booking_paid_changes_no_answer_and_no_evidence() -> None:
    rng = Random(4545)
    seen: set[Answer] = set()
    paid = 0
    for _ in range(300):
        file = random_trip(rng, 0.15, with_wants=0.4, with_rights=0.5)
        told = with_payments(file, rng)
        found = compiler.check(file)
        assert compiler.check(told) == found
        if found.answer is Answer.FEASIBLE:
            assert checked(told) == found
        seen.add(found.answer)
        paid += any(isinstance(fact, Booking) and fact.paid for fact in told.facts)
    assert seen == set(Answer)
    assert paid > 100
