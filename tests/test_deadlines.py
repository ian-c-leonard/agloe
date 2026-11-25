"""A FILE states the time now and what cancelling a BOOKING costs. A report lists the DEADLINEs."""

import json
from decimal import Decimal, Inexact, localcontext
from pathlib import Path
from typing import Any

import pytest

from agloe import compiler, report
from agloe.answers import (
    Answer,
    Deadline,
    check,
    costs_at_any_time,
    costs_now,
    deadlines,
    with_no_terms,
)
from agloe.file import Booking, FileError, Money, Now, Term, instant, load, written
from tests.stories import EXAMPLES, Document, lasts, lock, named, starts_at, stays

type Costs = list[tuple[str, str]]

# A BOOKING of these stories that states terms for cancelling states none for changing.
NO_CHANGING = "\nNo terms for changing are stated for room.\n"

MONDAY = "2027-05-10T09:00:00-05:00[America/Chicago]"
TUESDAY = "2027-05-11T12:00:00-05:00[America/Chicago]"
WEDNESDAY = "2027-05-12T18:00:00-05:00[America/Chicago]"
THURSDAY = "2027-05-13T09:00:00-05:00[America/Chicago]"
FREE: Costs = [("0.00", "USD")]
ALL: Costs = [("189.00", "USD")]


def term(costs: Costs | None = None, since: str | None = None) -> Document:
    """One term for cancelling: what it costs, from when. None: the term leaves it out."""
    stated: Document = {} if since is None else {"from": since}
    if costs is not None:
        stated["costs"] = [{"amount": amount, "currency": currency} for amount, currency in costs]
    return stated


def a_night(
    *terms: Document, now: str | None = None, others: tuple[Document, ...] = ()
) -> Document:
    """Alex has a room for Friday night. The BOOKING states these terms for cancelling.

    ``others`` are more FACTs: they come after the BOOKING for the room.
    """
    room: Document = {"option": "night", "covers": ["alex"]}
    if terms:
        room["cancelling"] = list(terms)
    facts = [
        starts_at("night", 23, 30),
        lasts("night", "PT8H"),
        {"id": "night-needs-a-room", "option": "night", "needs_right": True},
        {"id": "room", "booking": room},
        *others,
    ]
    if now is not None:
        facts.append({"id": "today", "now": now})
    return {
        "persons": named("alex"),
        "places": named("hotel"),
        "options": [stays("night", "hotel")],
        "ways": [],
        "wants": [],
        "facts": facts,
        "decisions": [lock("night", "alex")],
    }


def a_ticket(id: str, *terms: Document) -> Document:
    """One more BOOKING for the night, with its own terms."""
    held: Document = {"option": "night", "covers": ["alex"]}
    if terms:
        held["cancelling"] = list(terms)
    return {"id": id, "booking": held}


def money(*amounts: tuple[str, str]) -> tuple[Money, ...]:
    return tuple(Money(Decimal(amount), currency) for amount, currency in amounts)


def problems(document: Document) -> str:
    with pytest.raises(FileError) as refused:
        load(document)
    return str(refused.value)


def words(document: Document) -> str:
    file = load(document)
    return report.as_text(file, check(file))


def as_json(document: Document) -> dict[str, Any]:
    file = load(document)
    return report.as_json(file, check(file))


# The format.


def test_a_file_can_state_the_time_now() -> None:
    file = load(a_night(now=MONDAY))
    assert file.now() == Now("today", instant(MONDAY))
    assert load(a_night()).now() is None


def test_a_file_states_the_time_now_once() -> None:
    document = a_night(now=MONDAY)
    document["facts"].append({"id": "later", "now": THURSDAY})
    assert problems(document) == "/facts/5: another FACT already states this"


def test_the_time_now_is_a_real_time_in_its_zone() -> None:
    assert "is not a real date and time" in problems(
        a_night(now="2027-02-30T09:00:00-06:00[America/Chicago]")
    )
    assert "does not agree with its time zone" in problems(
        a_night(now="2027-05-10T09:00:00-06:00[America/Chicago]")
    )


def test_a_booking_states_what_cancelling_costs() -> None:
    file = load(a_night(term(FREE), term(ALL, WEDNESDAY)))
    room = next(fact for fact in file.facts if isinstance(fact, Booking))
    assert room.cancelling == (Term(None, ()), Term(instant(WEDNESDAY), money(("189.00", "USD"))))
    assert (
        next(fact for fact in load(a_night()).facts if isinstance(fact, Booking)).cancelling == ()
    )


def test_a_term_can_leave_out_its_cost_and_the_first_can_state_its_time() -> None:
    file = load(a_night(term(FREE, TUESDAY), term(None, WEDNESDAY)))
    room = next(fact for fact in file.facts if isinstance(fact, Booking))
    assert room.cancelling == (Term(instant(TUESDAY), ()), Term(instant(WEDNESDAY), None))


def test_a_cost_has_one_amount_for_each_currency_and_none_of_nothing() -> None:
    both = [("30000", "AA-points"), ("0", "EUR"), ("50.00", "USD")]
    file = load(a_night(term(both)))
    room = next(fact for fact in file.facts if isinstance(fact, Booking))
    assert room.cancelling == (Term(None, money(("30000", "AA-points"), ("50.00", "USD"))),)


def test_the_terms_come_in_the_order_of_time() -> None:
    late_first = a_night(term(FREE, WEDNESDAY), term(ALL, TUESDAY))
    second = "/facts/3/booking/cancelling/1: it does not start after the term before it"
    third = "/facts/3/booking/cancelling/2: it does not start after the term before it"
    assert problems(late_first) == second
    at_once = a_night(term(FREE), term(ALL, WEDNESDAY), term(None, WEDNESDAY))
    assert problems(at_once) == third
    # The same instant on the clocks of another zone is the same instant.
    elsewhere = "2027-05-12T19:00:00-04:00[America/New_York]"
    same = a_night(term(FREE), term(ALL, WEDNESDAY), term(None, elsewhere))
    assert problems(same) == third


def test_only_the_first_term_leaves_out_its_time() -> None:
    document = a_night(term(FREE), term(ALL))
    assert problems(document) == (
        "/facts/3/booking/cancelling/1: only the first term can leave out when it starts"
    )


def test_a_term_states_a_time_or_a_cost() -> None:
    nothing = "{} should be non-empty"
    start = "/facts/3: fits no known shape; the closest miss: at /facts/3/booking/cancelling/"
    assert problems(a_night({})) == f"{start}0, {nothing}"
    assert problems(a_night(term(FREE), {})) == f"{start}1, {nothing}"


def test_a_term_with_no_cost_is_taken_wherever_it_comes() -> None:
    """The seller's terms change at a time, and nobody has said what cancelling costs."""
    only_a_time = load(a_night(term(None, WEDNESDAY)))
    room = next(fact for fact in only_a_time.facts if isinstance(fact, Booking))
    assert room.cancelling == (Term(instant(WEDNESDAY), None),)
    assert load(a_night(term(FREE), term(None, TUESDAY), term(None, WEDNESDAY)))


def test_a_term_names_a_currency_once() -> None:
    document = a_night(term(FREE), term([("10.00", "USD"), ("5.00", "USD")], WEDNESDAY))
    assert problems(document) == "/facts/3/booking/cancelling/1: it states USD more than once"


def test_a_list_of_terms_is_not_empty_and_a_cost_is_not_either() -> None:
    start = "/facts/3: fits no known shape; the closest miss: at /facts/3/booking/cancelling"
    document = a_night()
    document["facts"][3]["booking"]["cancelling"] = []
    assert problems(document) == f"{start}, [] should be non-empty"
    document["facts"][3]["booking"]["cancelling"] = [{"costs": []}]
    assert problems(document) == f"{start}/0/costs, [] should be non-empty"


def test_a_time_of_a_term_is_a_real_time() -> None:
    wrong = "2027-02-30T18:00:00-06:00[America/Chicago]"
    document = a_night(term(FREE), term(ALL, wrong))
    assert problems(document) == (
        f"/facts/3/booking/cancelling/1: {wrong} is not a real date and time"
    )


def test_cancelling_can_cost_more_than_the_booking_paid_and_in_another_currency() -> None:
    document = a_night(term([("250.00", "EUR")]))
    document["facts"][3]["booking"]["paid"] = {"amount": "189.00", "currency": "USD"}
    assert load(document)


# What a DEADLINE is, and its STAKE.


def found(document: Document) -> list[tuple[str, str, str, tuple[Money, ...] | None]]:
    """Each DEADLINE of a FILE: its BOOKING, its time as written, how it changes, its STAKE."""
    file = load(document)
    return [
        (each.booking, written(each.at, file.zone), each.change, each.stake)
        for each in deadlines(file)
    ]


def test_a_cost_that_rises_from_nothing_has_all_of_it_at_stake() -> None:
    file = load(a_night(term(FREE), term(ALL, WEDNESDAY)))
    assert deadlines(file) == (Deadline(instant(WEDNESDAY), "room", (), money(("189.00", "USD"))),)
    assert found(a_night(term(FREE), term(ALL, WEDNESDAY))) == [
        ("room", WEDNESDAY, "rises", money(("189.00", "USD")))
    ]


def test_the_stake_of_a_rise_is_the_difference() -> None:
    steps = a_night(term(FREE), term([("50.00", "USD")], TUESDAY), term(ALL, WEDNESDAY))
    assert found(steps) == [
        ("room", TUESDAY, "rises", money(("50.00", "USD"))),
        ("room", WEDNESDAY, "rises", money(("139.00", "USD"))),
    ]
    # A cost on both sides: no stretch with no cost has an end to name.
    assert deadlines(load(steps)) == (
        Deadline(instant(TUESDAY), "room", (), money(("50.00", "USD"))),
        Deadline(instant(WEDNESDAY), "room", money(("50.00", "USD")), money(("189.00", "USD"))),
    )


def test_a_cost_that_falls_is_listed_with_nothing_at_stake() -> None:
    falls = a_night(term(ALL), term([("50.00", "USD")], WEDNESDAY))
    assert found(falls) == [("room", WEDNESDAY, "falls", ())]
    to_nothing = a_night(term(ALL), term(FREE, WEDNESDAY))
    assert found(to_nothing) == [("room", WEDNESDAY, "falls", ())]


def test_the_same_cost_on_both_sides_is_no_deadline() -> None:
    assert found(a_night(term(ALL), term(ALL, WEDNESDAY))) == []
    # Two ways to write one amount are the same amount, and nothing is nothing in any currency.
    assert found(a_night(term(ALL), term([("189.0", "USD")], WEDNESDAY))) == []
    assert found(a_night(term(FREE), term([("0", "EUR")], WEDNESDAY))) == []
    # The order of the currencies says nothing.
    one = [("30000", "AA-points"), ("50.00", "USD")]
    other = [("50.00", "USD"), ("30000", "AA-points")]
    assert found(a_night(term(one), term(other, WEDNESDAY))) == []


def test_a_gap_between_two_costs_has_a_deadline_at_each_end() -> None:
    document = a_night(term(FREE), term(None, TUESDAY), term(ALL, WEDNESDAY))
    assert deadlines(load(document)) == (
        Deadline(instant(TUESDAY), "room", (), None),
        Deadline(instant(WEDNESDAY), "room", None, money(("189.00", "USD"))),
    )
    said = words(document)
    assert (
        "  12:00 pm on Tuesday 11 May 2027: a term for cancelling room, the BOOKING for night,"
        " starts. The FILE does not say what cancelling costs in it. It costs nothing in the"
        " term before it. The STAKE is unknown.\n"
    ) in said
    assert (
        "  6:00 pm on Wednesday 12 May 2027: a term for cancelling room, the BOOKING for night,"
        " starts. Cancelling costs 189.00 USD in it. The FILE does not say what it costs in"
        " the term before it. The STAKE is unknown.\n"
    ) in said


def test_a_cost_is_said_of_its_own_term_and_of_no_other() -> None:
    """Free, then a gap, then 50 dollars, then a gap, then 189 dollars."""
    friday = "2027-05-14T12:00:00-05:00[America/Chicago]"
    fifty = [("50.00", "USD")]
    document = a_night(
        term(FREE),
        term(None, TUESDAY),
        term(fifty, WEDNESDAY),
        term(None, THURSDAY),
        term(ALL, friday),
    )
    start = "a term for cancelling room, the BOOKING for night, starts."
    unknown = "The STAKE is unknown.\n"
    unsaid = "The FILE does not say what cancelling costs in it."
    assert words(document).endswith(
        f"  12:00 pm on Tuesday 11 May 2027: {start} {unsaid} It costs nothing in the term"
        f" before it. {unknown}"
        f"  6:00 pm on Wednesday 12 May 2027: {start} Cancelling costs 50.00 USD in it. The"
        f" FILE does not say what it costs in the term before it. {unknown}"
        f"  9:00 am on Thursday 13 May 2027: {start} {unsaid} It costs 50.00 USD in the term"
        f" before it. {unknown}"
        f"  12:00 pm on Friday 14 May 2027: {start} Cancelling costs 189.00 USD in it. The"
        f" FILE does not say what it costs in the term before it. {unknown}"
        f"{NO_CHANGING}"
    )


def test_a_term_with_no_cost_is_a_deadline_also_after_a_time_with_no_cost() -> None:
    """ "The penalty increases at 6:00 pm on Wednesday. Ask the hotel for the charges." """
    only_a_time = a_night(term(None, WEDNESDAY))
    assert deadlines(load(only_a_time)) == (
        Deadline(instant(WEDNESDAY), "room", None, None, first=True),
    )
    assert found(only_a_time) == [("room", WEDNESDAY, "not stated before or from then", None)]
    assert words(only_a_time).endswith(
        "  6:00 pm on Wednesday 12 May 2027: a term for cancelling room, the BOOKING for night,"
        " starts. The FILE does not say what cancelling costs in it, or before it. The STAKE is"
        " unknown.\n" + NO_CHANGING
    )
    twice = a_night(term(FREE), term(None, TUESDAY), term(None, WEDNESDAY))
    assert found(twice) == [
        ("room", TUESDAY, "not stated from then", None),
        ("room", WEDNESDAY, "not stated before or from then", None),
    ]
    assert words(twice).endswith(
        "  6:00 pm on Wednesday 12 May 2027: a term for cancelling room, the BOOKING for night,"
        " starts. The FILE does not say what cancelling costs in it, or in the term before it."
        " The STAKE is unknown.\n" + NO_CHANGING
    )
    assert as_json(twice)["deadlines"][1] == {
        "at": WEDNESDAY,
        "kind": "cancelling",
        "booking": "room",
        "option": "night",
        "before": None,
        "from_then": None,
        "change": "not stated before or from then",
        "stake": None,
        "first_term": False,
    }


def test_the_stake_does_not_turn_on_the_decimal_settings_of_the_caller() -> None:
    document = a_night(term([("50.00", "USD")]), term([("189.04", "USD")], WEDNESDAY), now=MONDAY)
    usual = words(document)
    assert "At STAKE: 139.04 USD." in usual
    with localcontext() as settings:
        settings.prec = 4
        assert words(document) == usual
        settings.traps[Inexact] = True
        assert words(document) == usual
        assert as_json(document)["deadlines"][0]["stake"] == [
            {"amount": "139.04", "currency": "USD"}
        ]


def test_a_difference_has_the_decimal_places_of_the_amount_that_states_more() -> None:
    def less(amount: str, by: str) -> str:
        return str(Money(Decimal(amount), "USD").less(Money(Decimal(by), "USD")).amount)

    assert less("189.04", "50.00") == "139.04"
    assert less("189", "50") == "139"
    assert less("189.00", "50") == "139.00"
    assert less("189.5", "50.25") == "139.25"
    assert less("1", "0.9999") == "0.0001"
    assert less("999999999999.9999", "0.0001") == "999999999999.9998"
    assert less("10.50", "0.5") == "10.00"


def test_a_stated_cost_that_ends_is_a_deadline_with_an_unknown_stake() -> None:
    document = a_night(term(FREE), term(None, WEDNESDAY))
    assert found(document) == [("room", WEDNESDAY, "not stated from then", None)]
    file = load(document)
    assert deadlines(file) == (Deadline(instant(WEDNESDAY), "room", (), None),)


def test_a_first_term_with_a_time_has_no_cost_before_it() -> None:
    document = a_night(term(ALL, WEDNESDAY))
    assert found(document) == [("room", WEDNESDAY, "not stated before", None)]
    assert deadlines(load(document)) == (
        Deadline(instant(WEDNESDAY), "room", None, money(("189.00", "USD")), first=True),
    )


def test_nothing_is_at_stake_where_cancelling_costs_nothing_from_then_on() -> None:
    assert found(a_night(term(FREE, WEDNESDAY))) == [("room", WEDNESDAY, "not stated before", ())]
    after_a_gap = a_night(term(ALL), term(None, TUESDAY), term(FREE, WEDNESDAY))
    assert found(after_a_gap) == [
        ("room", TUESDAY, "not stated from then", None),
        ("room", WEDNESDAY, "not stated before", ()),
    ]
    assert (
        "Cancelling costs nothing in it. The FILE does not say what it costs in the term before"
        " it. Nothing is at STAKE.\n"
    ) in words(after_a_gap)


def test_more_in_one_currency_and_less_in_another_is_not_added_up() -> None:
    document = a_night(term([("5000", "AA-points")]), term([("100.00", "USD")], WEDNESDAY))
    assert found(document) == [("room", WEDNESDAY, "differs", None)]
    partly = a_night(
        term([("5000", "AA-points"), ("20.00", "USD")]), term([("100.00", "USD")], WEDNESDAY)
    )
    assert found(partly) == [("room", WEDNESDAY, "differs", None)]


def test_a_rise_in_two_currencies_has_each_difference_at_stake() -> None:
    before = [("10000", "AA-points"), ("50.00", "USD")]
    after = [("30000", "AA-points"), ("50.00", "USD"), ("5.00", "EUR")]
    assert found(a_night(term(before), term(after, WEDNESDAY))) == [
        ("room", WEDNESDAY, "rises", money(("20000", "AA-points"), ("5.00", "EUR")))
    ]
    # A currency that is gone from then on is less of it.
    assert found(a_night(term(after), term(before, WEDNESDAY))) == [
        ("room", WEDNESDAY, "falls", ())
    ]


# Which DEADLINEs are listed.


def test_with_no_time_now_every_deadline_is_listed() -> None:
    steps = a_night(term(FREE), term([("50.00", "USD")], TUESDAY), term(ALL, WEDNESDAY))
    assert [when for _, when, _, _ in found(steps)] == [TUESDAY, WEDNESDAY]


def test_with_a_time_now_only_the_deadlines_after_it_are_listed() -> None:
    def steps(now: str) -> Document:
        return a_night(term(FREE), term([("50.00", "USD")], TUESDAY), term(ALL, WEDNESDAY), now=now)

    assert [when for _, when, _, _ in found(steps(MONDAY))] == [TUESDAY, WEDNESDAY]
    assert [when for _, when, _, _ in found(steps(THURSDAY))] == []
    # At its own instant a term holds already, so its DEADLINE has passed. A second earlier
    # it has not.
    assert [when for _, when, _, _ in found(steps(TUESDAY))] == [WEDNESDAY]
    just_before = "2027-05-11T11:59:59-05:00[America/Chicago]"
    assert [when for _, when, _, _ in found(steps(just_before))] == [TUESDAY, WEDNESDAY]
    just_after = "2027-05-11T12:00:01-05:00[America/Chicago]"
    assert [when for _, when, _, _ in found(steps(just_after))] == [WEDNESDAY]


def test_the_earliest_deadline_comes_first_and_the_files_order_breaks_a_tie() -> None:
    document = a_night(
        term(FREE),
        term(ALL, WEDNESDAY),
        others=(
            a_ticket("late", term(FREE), term(ALL, THURSDAY)),
            a_ticket("early", term(FREE), term(ALL, TUESDAY)),
            a_ticket("also", term(FREE), term(ALL, WEDNESDAY)),
        ),
    )
    assert [(booking, when) for booking, when, _, _ in found(document)] == [
        ("early", TUESDAY),
        ("room", WEDNESDAY),
        ("also", WEDNESDAY),
        ("late", THURSDAY),
    ]


def test_a_deadline_is_listed_after_its_option_has_started_and_after_the_trip_ends() -> None:
    later = "2027-06-01T12:00:00-05:00[America/Chicago]"
    document = a_night(term(FREE), term(ALL, later), now=MONDAY)
    document["decisions"].append(
        {"id": "the-end", "trip_ends_at": "2027-05-16T12:00:00-05:00[America/Chicago]"}
    )
    assert [when for _, when, _, _ in found(document)] == [later]


# What cancelling costs now, and the BOOKINGs with no terms.


def test_what_cancelling_costs_now_is_the_cost_of_the_term_that_holds() -> None:
    def steps(now: str | None) -> Document:
        return a_night(term(FREE), term([("50.00", "USD")], TUESDAY), term(ALL, WEDNESDAY), now=now)

    assert costs_now(load(steps(MONDAY)), "cancelling") == (("room", ()),)
    assert costs_now(load(steps(TUESDAY)), "cancelling") == (("room", money(("50.00", "USD"))),)
    assert costs_now(load(steps(THURSDAY)), "cancelling") == (("room", money(("189.00", "USD"))),)
    assert costs_now(load(steps(None)), "cancelling") == ()


def test_no_cost_is_known_now_before_the_first_term_or_in_a_term_with_none() -> None:
    assert costs_now(load(a_night(term(ALL, WEDNESDAY), now=MONDAY)), "cancelling") == (
        ("room", None),
    )
    assert costs_now(load(a_night(term(ALL, WEDNESDAY), now=WEDNESDAY)), "cancelling") == (
        ("room", money(("189.00", "USD"))),
    )
    ends = a_night(term(FREE), term(None, WEDNESDAY), now=THURSDAY)
    assert costs_now(load(ends), "cancelling") == (("room", None),)


def test_a_booking_with_no_terms_is_named() -> None:
    document = a_night(term(FREE), others=(a_ticket("spare"), a_ticket("other")))
    file = load(document)
    assert with_no_terms(file, "cancelling") == ("spare", "other")
    assert costs_now(
        load(a_night(now=MONDAY, others=(a_ticket("spare", term(ALL)),))), "cancelling"
    ) == (("spare", money(("189.00", "USD"))),)


def test_a_cost_that_holds_at_any_time_is_known_with_no_time_now() -> None:
    def at_any_time(*terms: Document) -> tuple[tuple[str, tuple[Money, ...]], ...]:
        return costs_at_any_time(load(a_night(*terms)), "cancelling")

    all_of_it = (("room", money(("189.00", "USD"))),)
    assert at_any_time(term(ALL)) == all_of_it
    assert at_any_time(term(FREE)) == (("room", ()),)
    # Two terms that state one cost, also written in two ways.
    assert at_any_time(term(ALL), term([("189.0", "USD")], WEDNESDAY)) == all_of_it
    # A cost that changes, one that ends, and one that starts at a stated time.
    assert at_any_time(term(FREE), term(ALL, WEDNESDAY)) == ()
    assert at_any_time(term(ALL), term(None, WEDNESDAY)) == ()
    assert at_any_time(term(ALL, WEDNESDAY)) == ()
    assert at_any_time() == ()


def test_three_kinds_of_terms_with_no_time_now_have_three_reports() -> None:
    """Free at any time, 189 dollars at any time, and a cost that only starts on Wednesday."""
    free, kept, late = a_night(term(FREE)), a_night(term(ALL)), a_night(term(ALL, WEDNESDAY))
    assert len({words(free), words(kept), words(late)}) == 3
    assert as_json(free)["cancelling_at_any_time"] == [
        {"booking": "room", "option": "night", "costs": []}
    ]
    assert as_json(kept)["cancelling_at_any_time"] == [
        {"booking": "room", "option": "night", "costs": [{"amount": "189.00", "currency": "USD"}]}
    ]
    assert "cancelling_at_any_time" not in as_json(late)
    # With a time now, the costs now say it.
    timed = as_json(a_night(term(ALL), now=MONDAY))
    assert "cancelling_at_any_time" not in timed
    assert timed["cancelling_now"] == as_json(kept)["cancelling_at_any_time"]


# The report.


def test_a_file_with_no_time_now_and_no_terms_has_the_report_it_had() -> None:
    document = a_night()
    assert "DEADLINE" not in words(document)
    assert "time now" not in words(document)
    assert "cancelling" not in words(document)
    assert set(as_json(document)) == {"answer", "itinerary", "relies_on", "robust"}


def test_the_time_now_and_the_terms_change_no_answer_and_no_evidence() -> None:
    plain = load(a_night(others=(a_ticket("spare"),)))
    stated = load(
        a_night(
            term(FREE),
            term(ALL, WEDNESDAY),
            now=THURSDAY,
            others=(a_ticket("spare", term(ALL)),),
        )
    )
    assert check(stated) == check(plain)
    assert compiler.check(stated) == check(stated)
    assert check(stated).answer is Answer.FEASIBLE
    assert "today" not in check(stated).relies_on


def test_the_report_says_which_time_it_uses_and_lists_the_deadline() -> None:
    said = words(a_night(term(FREE), term(ALL, WEDNESDAY), now=MONDAY))
    assert said.endswith(
        "\n"
        "This report uses 9:00 am on Monday 10 May 2027 as the time now (times in"
        " America/Chicago). The FACT today states it.\n"
        "\n"
        "DEADLINEs after that time, earliest first:\n"
        "  6:00 pm on Wednesday 12 May 2027: a term for cancelling room, the BOOKING for night,"
        " starts. Cancelling costs 189.00 USD in it, and nothing in the term before it. At"
        " STAKE: 189.00 USD.\n"
        "\n"
        "What cancelling costs now:\n"
        "  room, the BOOKING for night: nothing\n" + NO_CHANGING
    )


def test_the_report_says_that_no_deadline_is_left() -> None:
    said = words(a_night(term(FREE), term(ALL, WEDNESDAY), now=THURSDAY))
    assert said.endswith(
        "\n"
        "This report uses 9:00 am on Thursday 13 May 2027 as the time now (times in"
        " America/Chicago). The FACT today states it.\n"
        "\n"
        "No DEADLINE comes after that time.\n"
        "\n"
        "What cancelling costs now:\n"
        "  room, the BOOKING for night: 189.00 USD\n" + NO_CHANGING
    )


def test_with_no_time_now_the_report_says_that_nobody_knows_what_has_passed() -> None:
    said = words(a_night(term(FREE), term(ALL, WEDNESDAY)))
    assert said.endswith(
        "\n"
        "This FILE does not state the time now. So nobody knows which of its DEADLINEs have"
        " passed. All of them, earliest first (times in America/Chicago):\n"
        "  6:00 pm on Wednesday 12 May 2027: a term for cancelling room, the BOOKING for night,"
        " starts. Cancelling costs 189.00 USD in it, and nothing in the term before it. At"
        " STAKE: 189.00 USD.\n" + NO_CHANGING
    )
    assert "costs now" not in said


def test_terms_that_never_change_have_no_deadline_with_or_without_a_time() -> None:
    assert words(a_night(term(ALL))).endswith(
        "\n"
        "This FILE does not state the time now. Its terms have no DEADLINE.\n"
        "\n"
        "What cancelling costs at any time:\n"
        "  room, the BOOKING for night: 189.00 USD\n" + NO_CHANGING
    )
    assert words(a_night(term(ALL), now=MONDAY)).endswith(
        "\n"
        "No DEADLINE comes after that time.\n"
        "\n"
        "What cancelling costs now:\n"
        "  room, the BOOKING for night: 189.00 USD\n" + NO_CHANGING
    )


def test_a_time_now_with_no_terms_names_each_booking() -> None:
    said = words(a_night(now=MONDAY, others=(a_ticket("spare"),)))
    assert said.endswith(
        "\n"
        "This report uses 9:00 am on Monday 10 May 2027 as the time now (times in"
        " America/Chicago). The FACT today states it.\n"
        "\n"
        "No terms for cancelling or for changing are stated for room and spare.\n"
    )


def test_the_bookings_with_no_terms_come_after_the_others() -> None:
    said = words(a_night(term(ALL), now=MONDAY, others=(a_ticket("spare"),)))
    assert said.endswith(
        "What cancelling costs now:\n"
        "  room, the BOOKING for night: 189.00 USD\n"
        "\n"
        "No terms for cancelling or for changing are stated for spare.\n" + NO_CHANGING
    )
    untimed = words(a_night(term(ALL), others=(a_ticket("spare"),)))
    assert untimed.endswith(
        "Its terms have no DEADLINE.\n"
        "\n"
        "What cancelling costs at any time:\n"
        "  room, the BOOKING for night: 189.00 USD\n"
        "\n"
        "No terms for cancelling or for changing are stated for spare.\n" + NO_CHANGING
    )


@pytest.mark.parametrize(
    ("terms", "line"),
    [
        (
            (term([("50.00", "USD")]), term(ALL, WEDNESDAY)),
            "Cancelling costs 189.00 USD in it, and 50.00 USD in the term before it. At STAKE:"
            " 139.00 USD.",
        ),
        (
            (term(ALL), term([("50.00", "USD")], WEDNESDAY)),
            "Cancelling costs 50.00 USD in it, and 189.00 USD in the term before it. Nothing is"
            " at STAKE.",
        ),
        (
            (term(ALL), term(FREE, WEDNESDAY)),
            "Cancelling costs nothing in it, and 189.00 USD in the term before it. Nothing is at"
            " STAKE.",
        ),
        (
            (term([("5000", "AA-points")]), term([("100.00", "USD")], WEDNESDAY)),
            "Cancelling costs 100.00 USD in it, and 5000 AA-points in the term before it. At"
            " STAKE: 100.00 USD, in place of 5000 AA-points.",
        ),
        (
            (
                term([("10000", "AA-points"), ("50.00", "USD")]),
                term([("30000", "AA-points"), ("50.00", "USD")], WEDNESDAY),
            ),
            "Cancelling costs 30000 AA-points and 50.00 USD in it, and 10000 AA-points and 50.00"
            " USD in the term before it. At STAKE: 20000 AA-points.",
        ),
        (
            (term(FREE), term(None, WEDNESDAY)),
            "The FILE does not say what cancelling costs in it. It costs nothing in the term"
            " before it. The STAKE is unknown.",
        ),
        (
            (term(ALL, WEDNESDAY),),
            "Cancelling costs 189.00 USD in it. The FILE does not say what it costs before it."
            " The STAKE is unknown.",
        ),
        (
            (term(FREE, WEDNESDAY),),
            "Cancelling costs nothing in it. The FILE does not say what it costs before it."
            " Nothing is at STAKE.",
        ),
    ],
)
def test_each_kind_of_deadline_has_its_line(terms: tuple[Document, ...], line: str) -> None:
    said = words(a_night(*terms))
    start = (
        "  6:00 pm on Wednesday 12 May 2027: a term for cancelling room, the BOOKING for night,"
        " starts. "
    )
    assert start + line + "\n" in said


def test_a_term_that_starts_with_the_same_cost_is_no_deadline_and_the_report_does_not_deny_it() -> (
    None
):
    """25 dollars at any time, written as two terms: a term starts on Wednesday all the same."""
    same = (term([("25", "USD")]), term([("25.00", "USD")], WEDNESDAY))
    timed, untimed = words(a_night(*same, now=MONDAY)), words(a_night(*same))
    assert "\nNo DEADLINE comes after that time.\n" in timed
    assert "Its terms have no DEADLINE.\n" in untimed
    assert "change" not in timed + untimed
    assert as_json(a_night(*same))["deadlines"] == []


def test_a_first_term_and_a_term_after_one_with_no_cost_differ_in_the_report_as_json() -> None:
    """Wednesday's term with no cost, alone, and after Monday's term with no cost."""
    monday = "2027-05-10T12:00:00-05:00[America/Chicago]"
    sunday = "2027-05-09T09:00:00-05:00[America/Chicago]"
    alone = as_json(a_night(term(None, WEDNESDAY), now=TUESDAY))
    after = as_json(a_night(term(None, monday), term(None, WEDNESDAY), now=TUESDAY))
    assert alone != after
    assert [each["first_term"] for each in alone["deadlines"]] == [True]
    assert [each["first_term"] for each in after["deadlines"]] == [False]
    assert as_json(a_night(term(None, monday), now=sunday))["deadlines"][0]["first_term"] is True


def test_a_cost_now_that_the_file_does_not_state_is_said() -> None:
    said = words(a_night(term(ALL, WEDNESDAY), now=MONDAY))
    assert "  room, the BOOKING for night: the FILE does not say\n" in said


def test_every_kind_of_report_has_the_deadlines() -> None:
    # A night that nobody has said the start of, and a night that needs a room nobody has.
    unknown = a_night(term(FREE), term(ALL, WEDNESDAY), now=MONDAY)
    del unknown["facts"][0]
    assert as_json(unknown)["answer"] == "UNDETERMINED"
    ruled_out = a_night(term(FREE), term(ALL, WEDNESDAY), now=MONDAY)
    ruled_out["facts"][3]["booking"]["covers"] = ["sam"]
    ruled_out["persons"] += named("sam")
    ruled_out["facts"].append({"id": "no-more-rooms", "complete": {"rights_to": "night"}})
    assert as_json(ruled_out)["answer"] == "INFEASIBLE"
    for document in (unknown, ruled_out):
        assert "DEADLINEs after that time, earliest first:\n" in words(document)
        assert "At STAKE: 189.00 USD.\n" in words(document)
        assert [each["booking"] for each in as_json(document)["deadlines"]] == ["room"]


def test_a_time_on_another_clock_shows_offsets() -> None:
    """The clocks change on Sunday 7 November 2027, between the time now and the DEADLINE."""
    before = "2027-11-05T09:00:00-05:00[America/Chicago]"
    after = "2027-11-08T18:00:00-06:00[America/Chicago]"
    document = a_night(term(FREE), term(ALL, after), now=before)
    for fact in document["facts"]:
        if "starts_at" in fact:
            fact["starts_at"] = "2027-11-05T23:30:00-05:00[America/Chicago]"
    said = words(document)
    assert "This report uses 9:00 am (UTC-5) on Friday 5 November 2027 as the time now" in said
    assert "  6:00 pm (UTC-6) on Monday 8 November 2027: a term for cancelling room" in said
    file = load(document)
    assert report.clock_for(file, check(file)).offsets
    # The time now counts by itself: here it is the only time before the clocks change.
    early = a_night(term(FREE), term(ALL, after), now=before)
    for fact in early["facts"]:
        if "starts_at" in fact:
            fact["starts_at"] = "2027-11-09T23:30:00-06:00[America/Chicago]"
    assert "uses 9:00 am (UTC-5) on Friday 5 November 2027 as the time now" in words(early)
    assert "  11:30 pm (UTC-6) to 7:30 am (UTC-6) on 10 November: night, alex" in words(early)
    # So does a DEADLINE: here it is the only time after they change.
    late = a_night(term(FREE), term(ALL, after), now="2027-11-05T12:00:00-05:00[America/Chicago]")
    for fact in late["facts"]:
        if "starts_at" in fact:
            fact["starts_at"] = "2027-11-05T13:00:00-05:00[America/Chicago]"
    assert "  6:00 pm (UTC-6) on Monday 8 November 2027: a term for cancelling room" in words(late)
    assert "uses 12:00 pm (UTC-5) on Friday 5 November 2027 as the time now" in words(late)
    # A DEADLINE that has passed is not shown, so its time does not count.
    passed = a_night(
        term(FREE),
        term(ALL, "2027-11-05T18:00:00-05:00[America/Chicago]"),
        now="2027-11-09T09:00:00-06:00[America/Chicago]",
    )
    for fact in passed["facts"]:
        if "starts_at" in fact:
            fact["starts_at"] = "2027-11-09T23:30:00-06:00[America/Chicago]"
    assert "(UTC" not in words(passed)
    assert "No DEADLINE comes after that time." in words(passed)


def test_a_time_that_the_clocks_show_twice_has_its_offset() -> None:
    """On Sunday 7 November 2027 the clocks of Chicago show 1:30 am twice, an hour apart."""
    first = "2027-11-07T01:30:00-05:00[America/Chicago]"
    second = "2027-11-07T01:30:00-06:00[America/Chicago]"

    def said(cutoff: str, night: str) -> str:
        document = a_night(term(FREE), term(ALL, cutoff))
        for fact in document["facts"]:
            if "starts_at" in fact:
                fact["starts_at"] = night
        return words(document)

    # The night is before the clocks change in one FILE, and after it in the other. So the
    # times that each report shows have one offset, and only the time that comes twice has
    # its offset beside it.
    before = said(first, "2027-11-05T23:30:00-05:00[America/Chicago]")
    after = said(second, "2027-11-10T23:30:00-06:00[America/Chicago]")
    assert "  1:30 am (UTC-5) on Sunday 7 November 2027: a term for cancelling room" in before
    assert "  1:30 am (UTC-6) on Sunday 7 November 2027: a term for cancelling room" in after
    assert before.count("(UTC") == after.count("(UTC") == 1
    # A step at such a time has its offset too.
    early = a_night()
    early["facts"][0]["starts_at"] = first
    early["facts"][1]["duration"] = "PT10M"
    assert "  1:30 am (UTC-5) to 1:40 am (UTC-5): night, alex" in words(early)


def test_the_time_now_does_not_decide_the_zone_of_a_report() -> None:
    """An agent in Tokyo checks a trip to Chicago: the report is on the clocks of Chicago."""
    tokyo = "2027-05-10T23:00:00+09:00[Asia/Tokyo]"
    document = a_night(term(FREE), term(ALL, WEDNESDAY))
    document["facts"].insert(0, {"id": "today", "now": tokyo})
    assert load(document).zone == "America/Chicago"
    assert "This report uses 9:00 am on Monday 10 May 2027 as the time now" in words(document)
    # A FILE that states no other time has the zone of the time now.
    alone = a_night(now=tokyo)
    alone["facts"] = [fact for fact in alone["facts"] if "starts_at" not in fact]
    assert load(alone).zone == "Asia/Tokyo"
    assert "This report uses 11:00 pm on Monday 10 May 2027 as the time now" in words(alone)


def test_the_report_as_json_has_the_time_now_and_the_deadlines() -> None:
    document = a_night(
        term(FREE),
        term([("50.00", "USD")], TUESDAY),
        term(ALL, WEDNESDAY),
        now=MONDAY,
        others=(a_ticket("spare"),),
    )
    out = as_json(document)
    assert out["now"] == {"fact": "today", "at": MONDAY}
    assert out["deadlines"] == [
        {
            "at": TUESDAY,
            "kind": "cancelling",
            "booking": "room",
            "option": "night",
            "before": [],
            "from_then": [{"amount": "50.00", "currency": "USD"}],
            "change": "rises",
            "stake": [{"amount": "50.00", "currency": "USD"}],
            "first_term": False,
        },
        {
            "at": WEDNESDAY,
            "kind": "cancelling",
            "booking": "room",
            "option": "night",
            "before": [{"amount": "50.00", "currency": "USD"}],
            "from_then": [{"amount": "189.00", "currency": "USD"}],
            "change": "rises",
            "stake": [{"amount": "139.00", "currency": "USD"}],
            "first_term": False,
        },
    ]
    assert out["cancelling_now"] == [{"booking": "room", "option": "night", "costs": []}]
    assert out["no_terms_for_cancelling"] == ["spare"]


def test_the_report_as_json_says_what_is_not_stated() -> None:
    out = as_json(a_night(term(FREE), term(None, WEDNESDAY)))
    assert "now" not in out
    assert "cancelling_now" not in out
    assert "no_terms_for_cancelling" not in out
    assert out["deadlines"] == [
        {
            "at": WEDNESDAY,
            "kind": "cancelling",
            "booking": "room",
            "option": "night",
            "before": [],
            "from_then": None,
            "change": "not stated from then",
            "stake": None,
            "first_term": False,
        }
    ]
    late = as_json(a_night(term(ALL, WEDNESDAY), now=MONDAY))
    assert late["deadlines"][0]["before"] is None
    assert late["deadlines"][0]["first_term"] is True
    assert late["deadlines"][0]["change"] == "not stated before"
    assert late["cancelling_now"] == [{"booking": "room", "option": "night", "costs": None}]
    mixed = as_json(a_night(term([("5000", "AA-points")]), term([("100.00", "USD")], WEDNESDAY)))
    assert mixed["deadlines"][0]["change"] == "differs"
    assert mixed["deadlines"][0]["stake"] is None
    assert as_json(a_night(now=MONDAY))["deadlines"] == []
    assert as_json(a_night(now=MONDAY))["no_terms_for_cancelling"] == ["room"]


def test_the_time_now_has_its_words_as_a_record() -> None:
    file = load(a_night(now=MONDAY))
    clock = report.clock_for(file, check(file))
    said = report._record(file, clock, "today")  # pyright: ignore[reportPrivateUsage]
    assert said == "the time now is 9:00 am on Monday 10 May 2027"


def test_a_booking_is_named_by_its_option_as_the_rest_of_the_report_names_it() -> None:
    """Two OPTIONs that a page shows alike have their ids beside their names."""
    document = a_night(term(FREE), term(ALL, WEDNESDAY))
    document["options"] = [
        {"id": "night", "name": "Night at the hotel", "place": "hotel"},
        {"id": "second-night", "name": "Night at the hotel", "place": "hotel"},
    ]
    assert (
        "a term for cancelling room, the BOOKING for Night at the hotel (night), starts."
    ) in words(document)


# The story on the rules page.


def test_the_story_of_the_room_has_its_three_days() -> None:
    folder: Path = EXAMPLES / "the-room"
    said = {path.stem: path.read_text() for path in folder.glob("*.expected.txt")}
    assert "At STAKE: 189.00 USD." in said["on-monday.expected"]
    assert "No DEADLINE comes after that time." in said["on-thursday.expected"]
    assert (
        "nobody knows which of its DEADLINEs have passed"
        in (said["nobody-said-what-time-it-is.expected"])
    )
    for path in folder.glob("*.expected.json"):
        assert json.loads(path.read_text())["answer"] in {"FEASIBLE", "INFEASIBLE", "UNDETERMINED"}
