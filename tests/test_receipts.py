"""Receipts: a BOOKING can state what it paid, and a report adds up the money."""

from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal, Inexact, localcontext
from random import Random

import pytest

from agloe import compiler, report
from agloe.answers import Answer
from agloe.file import Booking, File, FileError, Money, Payment, load
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
RECEIPTS = "What the BOOKINGs state that they paid:"
SUMS = "The money of this plan, by currency:"


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


def test_a_report_gives_each_payment_once_with_who_paid_and_the_budget() -> None:
    cases = {
        "32.00 USD, paid by alex, from trip-money": {"budget": "trip-money", "by": "alex"},
        "32.00 USD, from trip-money": {"budget": "trip-money"},
        "32.00 USD, paid by sam": {"by": "sam"},
        "32.00 USD": {},
    }
    for said, parts in cases.items():
        file = a_tour_and_a_talk(booking("tour", "alex", paid="32.00 USD", **parts))
        words = in_words(file)
        assert words[words.index(RECEIPTS) + 1] == f"  tour-booking: {said}"
        # The record itself reads as before: no CONSTRAINT is about what it paid.
        assert "  tour-booking: a BOOKING for tour covers alex" in words
    free = a_tour_and_a_talk(booking("tour", "alex", paid="0 USD", by="alex"))
    assert "  tour-booking: nothing, paid by alex" in in_words(free)


def test_a_report_adds_up_what_is_paid_and_what_is_still_to_buy() -> None:
    """Alex has a ticket for the tour. Jo has one for the talk, and does not go."""
    file = a_tour_and_a_talk(
        booking("tour", "alex", paid="32.00 USD", budget="trip-money", by="alex"),
        booking("talk", "jo", id="jo-talk", paid="5 EUR"),
        booking("talk", "sam", id="sam-talk"),
    )
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert in_words(file)[-8:] == [
        RECEIPTS,
        "  tour-booking: 32.00 USD, paid by alex, from trip-money",
        "  jo-talk: 5 EUR",
        "  No payment is stated for sam-talk.",
        "",
        SUMS,
        "  USD: 32.00 paid; 64.00 still to buy (tour-offer); up to 8.50 more, depending on which"
        " OPTIONs need a right (talk-offer)",
        "  EUR: 5 paid",
    ]
    dollars = {"paid": "32.00", "to_buy": "64.00", "to_buy_at_most_if_needed": "8.50"}
    euros = {"paid": "5", "to_buy": "0", "to_buy_at_most_if_needed": "0"}
    first = {"booking": "tour-booking", "amount": "32.00", "currency": "USD"}
    second = {"booking": "jo-talk", "amount": "5", "currency": "EUR", "budget": None, "by": None}
    assert report.as_json(file, found)["money"] == {
        "paid": [{**first, "budget": "trip-money", "by": "alex"}, second],
        "not_stated": ["sam-talk"],
        "totals": [{"currency": "USD", **dollars}, {"currency": "EUR", **euros}],
    }
    assert report.as_json(file, compiler.check(file)) == report.as_json(file, found)


def test_what_is_bought_only_if_needed_is_the_most_it_can_come_to() -> None:
    """Two visits that might need a right, at 1 USD and at 2 USD. Each is needed or not."""
    options = [stays("tour", "dock"), stays("talk", "dock")]
    facts = [*at("tour", 10), *at("talk", 12)]
    facts += [offer("tour", 1, price="1 USD"), offer("talk", 1, price="2 USD")]
    locked = [lock("tour", "alex"), lock("talk", "alex")]
    file = trip(["alex"], ["dock"], options, facts, locked, tickets=True)
    assert in_words(file)[-1] == (
        "  USD: up to 3 more, depending on which OPTIONs need a right (tour-offer and talk-offer)"
    )
    money = report.as_json(file, checked(file))["money"]
    assert isinstance(money, dict)
    assert money["totals"] == [
        {"currency": "USD", "paid": "0", "to_buy": "0", "to_buy_at_most_if_needed": "3"}
    ]


def test_amounts_in_one_currency_are_added_exactly() -> None:
    file = a_tour_and_a_talk(
        booking("tour", "alex", paid="0.1 USD"),
        booking("tour", "sam", id="sams", paid="0.2 USD"),
        booking("tour", "jo", id="jos", paid="999999999999.9999 USD"),
    )
    assert in_words(file)[-1] == (
        "  USD: 1000000000000.2999 paid; up to 8.50 more, depending on which OPTIONs need a right"
        " (talk-offer)"
    )
    tenths = a_tour_and_a_talk(
        booking("tour", "alex", paid="0.1 USD"),
        booking("tour", "sam", id="sams", paid="0.20 USD"),
        booking("tour", "jo", id="jos", paid="7 USD"),
    )
    assert in_words(tenths)[-1].startswith("  USD: 7.30 paid;")


def test_the_sums_do_not_depend_on_the_decimal_settings_of_the_caller() -> None:
    """Two places at the largest amount a FILE can state, and nothing about a payment."""
    options = [stays("tour", "dock")]
    facts = [*at("tour", 10), needs_right("tour"), offer("tour", 2, price="999999999999.9999 USD")]
    file = trip(
        ["alex", "sam"], ["dock"], options, facts, [lock("tour", "alex", "sam")], tickets=True
    )
    usual = report.as_text(file, checked(file))
    assert usual.splitlines()[-1] == "  USD: 1999999999999.9998 still to buy (tour-offer)"
    with localcontext() as settings:
        settings.prec = 16
        assert report.as_text(file, checked(file)) == usual
        settings.traps[Inexact] = True
        assert report.as_text(file, checked(file)) == usual
        assert report.as_json(file, checked(file))["money"] == {
            "paid": [],
            "not_stated": [],
            "totals": [
                {
                    "currency": "USD",
                    "paid": "0",
                    "to_buy": "1999999999999.9998",
                    "to_buy_at_most_if_needed": "0",
                }
            ],
        }


def test_a_payment_of_nothing_is_stated_and_enters_no_sum() -> None:
    """Everybody has a BOOKING, and nothing is bought. One BOOKING states that it paid nothing."""
    tickets = [booking("tour", *EVERYONE, paid="0 USD"), booking("talk", "alex", id="talks")]
    file = a_tour_and_a_talk(*tickets)
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert in_words(file)[-3:] == [
        RECEIPTS,
        "  tour-booking: nothing",
        "  No payment is stated for talks.",
    ]
    nothing = {"booking": "tour-booking", "amount": "0", "currency": "USD"}
    assert report.as_json(file, found)["money"] == {
        "paid": [{**nothing, "budget": None, "by": None}],
        "not_stated": ["talks"],
        "totals": [],
    }


def test_a_payment_of_nothing_does_not_read_like_a_payment_nobody_stated() -> None:
    """One BOOKING that nobody uses. It states that it paid nothing, or it states no payment."""
    options = [stays("tour", "dock")]

    def with_ticket(ticket: Document) -> File:
        facts = [*at("tour", 10), needs_right("tour"), ticket]
        pots = [budget("trip-money", "alex")]
        return trip(["alex"], ["dock"], options, facts, [], tickets=True, budgets=pots)

    paid_nothing = with_ticket(booking("tour", "alex", paid="0 USD", budget="trip-money"))
    not_stated = with_ticket(booking("tour", "alex"))
    assert in_words(paid_nothing)[-2:] == [RECEIPTS, "  tour-booking: nothing, from trip-money"]
    assert RECEIPTS not in in_words(not_stated)
    assert "money" not in report.as_json(not_stated, checked(not_stated))


def test_two_payments_that_add_up_alike_are_still_told_apart() -> None:
    def with_payments(first: str, second: str) -> list[str]:
        tickets = [
            booking("tour", *EVERYONE, id="first", paid=first),
            booking("tour", "alex", id="second", paid=second),
            booking("talk", "alex", id="talks", paid="0 USD"),
        ]
        return in_words(a_tour_and_a_talk(*tickets))

    one_way, other_way = with_payments("1 USD", "3 USD"), with_payments("3 USD", "1 USD")
    assert one_way[-1] == other_way[-1] == "  USD: 4 paid"
    assert one_way[-7:-4] == [RECEIPTS, "  first: 1 USD", "  second: 3 USD"]
    assert other_way[-7:-4] == [RECEIPTS, "  first: 3 USD", "  second: 1 USD"]


def test_no_name_can_copy_the_words_of_a_payment() -> None:
    """A BUDGET or a PERSON whose name reads like part of the line."""

    def receipt(person: str, pot: str, source: bool) -> str:
        document = {
            "persons": [{"id": "a", "name": person}],
            "places": [{"id": "dock", "name": "dock"}],
            "budgets": [{"id": "b", "name": pot, "persons": [], "currencies": ["USD"]}],
            "options": [stays("tour", "dock")],
            "ways": [],
            "wants": [],
            "facts": [
                *at("tour", 10),
                needs_right("tour"),
                booking("tour", "a", paid="1 USD", by="a", budget="b" if source else None),
            ],
            "decisions": [lock("tour", "a")],
        }
        words = in_words(load(document))
        return words[words.index(RECEIPTS) + 1]

    assert receipt("A", "B", True) == "  tour-booking: 1 USD, paid by A, from B"
    assert receipt("A from B", "C", False) == "  tour-booking: 1 USD, paid by A from B"
    assert receipt("A, from B", "C", False) == '  tour-booking: 1 USD, paid by "A, from B"'
    assert (
        receipt("A", "B, paid by C", True)
        == '  tour-booking: 1 USD, paid by A, from "B, paid by C"'
    )


def test_a_report_says_nothing_about_money_where_none_is_stated() -> None:
    """Everybody has a BOOKING, no BOOKING states a payment, and nothing is bought."""
    file = a_tour_and_a_talk(booking("tour", *EVERYONE), booking("talk", "alex", id="talks"))
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert RECEIPTS not in in_words(file) and SUMS not in in_words(file)
    assert "money" not in report.as_json(file, found)


def test_only_a_plan_states_the_money() -> None:
    """A TRIP that depends on a FACT shows no payments and no sums."""
    paid = booking("tour", "alex", paid="32.00 USD")
    one_place = [paid, offer("tour", 1, id="one", price="1 USD")]
    options = [stays("tour", "dock")]
    locked = [lock("tour", *EVERYONE)]
    facts = [*at("tour", 10), needs_right("tour"), *one_place]
    file = trip(EVERYONE, ["dock"], options, facts, locked, tickets=True)
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    assert RECEIPTS not in in_words(file) and SUMS not in in_words(file)
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
