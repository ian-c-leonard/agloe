"""A BOOKING can state what the seller charges for a change to it."""

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
    every_deadline,
    with_no_terms,
)
from agloe.file import Booking, Term, instant, load
from tests.stories import Document
from tests.test_deadlines import (
    ALL,
    FREE,
    MONDAY,
    THURSDAY,
    TUESDAY,
    WEDNESDAY,
    Costs,
    a_night,
    a_ticket,
    as_json,
    money,
    problems,
    term,
    words,
)

FEE: Costs = [("25.00", "USD")]
START = "a term for changes to room, the BOOKING for night, starts."
NOW = "The fee for a change now, apart from any difference in price:"
AT_ANY_TIME = "The fee for a change at any time, apart from any difference in price:"


def changed(document: Document, *terms: Document, of: str = "room") -> Document:
    """The same FILE, where one BOOKING states these terms for changing."""
    for fact in document["facts"]:
        if fact["id"] == of:
            fact["booking"]["changing"] = list(terms)
    return document


def a_room(*terms: Document, now: str | None = None, cancelling: tuple[Document, ...] = ()) -> Any:
    """Alex's room for the night, with these terms for changing it."""
    return changed(a_night(*cancelling, now=now), *terms)


def room_of(document: Document) -> Booking:
    return next(fact for fact in load(document).facts if isinstance(fact, Booking))


# The format.


def test_a_booking_states_what_the_seller_charges_for_a_change() -> None:
    room = room_of(a_room(term(FREE), term(FEE, TUESDAY)))
    assert room.changing == (Term(None, ()), Term(instant(TUESDAY), money(("25.00", "USD"))))
    assert room.cancelling == ()
    assert room.terms("changing") == room.changing
    assert room.terms("cancelling") == ()
    assert room_of(a_night(term(FREE))).changing == ()


def test_the_two_lists_of_terms_are_apart() -> None:
    room = room_of(a_room(term(FEE), cancelling=(term(FREE), term(ALL, WEDNESDAY))))
    assert room.changing == (Term(None, money(("25.00", "USD"))),)
    assert room.cancelling == (Term(None, ()), Term(instant(WEDNESDAY), money(("189.00", "USD"))))
    assert room.terms("cancelling") == room.cancelling


def test_the_terms_for_changing_follow_the_rules_of_a_list_of_terms() -> None:
    late = a_room(term(FREE), term(FEE))
    assert problems(late) == (
        "/facts/3/booking/changing/1: only the first term can leave out when it starts"
    )
    backwards = a_room(term(FREE, WEDNESDAY), term(FEE, TUESDAY))
    assert problems(backwards) == (
        "/facts/3/booking/changing/1: it does not start after the term before it"
    )
    twice = a_room(term([("5.00", "USD"), ("7.00", "USD")]))
    assert problems(twice) == "/facts/3/booking/changing/0: it states USD more than once"
    unreal = a_room(term(FEE, "2027-02-30T09:00:00-06:00[America/Chicago]"))
    assert "/facts/3/booking/changing/0: " in problems(unreal)
    assert "is not a real date and time" in problems(unreal)


def test_a_list_of_terms_for_changing_holds_a_term_and_a_term_states_something() -> None:
    assert "/facts/3/booking/changing" in problems(a_room())
    assert "/facts/3/booking/changing/0" in problems(a_room({}))
    assert "/facts/3/booking/changing/0/costs" in problems(a_room({"costs": []}))


def test_a_problem_in_one_list_is_not_said_of_the_other() -> None:
    wrong = a_room(term(FREE), cancelling=(term(FREE), term(ALL)))
    assert problems(wrong) == (
        "/facts/3/booking/cancelling/1: only the first term can leave out when it starts"
    )


# The DEADLINEs.


def test_a_term_for_changing_starts_at_a_deadline() -> None:
    file = load(a_room(term(FREE), term(FEE, TUESDAY)))
    fee = money(("25.00", "USD"))
    assert deadlines(file) == (Deadline(instant(TUESDAY), "room", (), fee, kind="changing"),)
    assert deadlines(file)[0].stake == fee
    assert deadlines(file)[0].change == "rises"


def test_a_term_for_cancelling_is_a_deadline_of_its_own_kind() -> None:
    (found,) = deadlines(load(a_night(term(FREE), term(ALL, WEDNESDAY))))
    assert found.kind == "cancelling"


def test_each_list_is_compared_within_itself() -> None:
    """Cancelling costs nothing until Wednesday. A change costs 25 dollars at any time."""
    file = load(a_room(term(FEE), cancelling=(term(FREE), term(ALL, WEDNESDAY))))
    assert deadlines(file) == (
        Deadline(instant(WEDNESDAY), "room", (), money(("189.00", "USD")), kind="cancelling"),
    )
    # The same fee again is no DEADLINE, whatever cancelling costs at that time.
    same = load(a_room(term(FEE), term(FEE, WEDNESDAY), cancelling=(term(FREE),)))
    assert deadlines(same) == ()


def test_a_first_term_for_changing_that_states_its_time_is_a_deadline() -> None:
    (found,) = deadlines(load(a_room(term(FEE, TUESDAY))))
    assert (found.before, found.first, found.kind) == (None, True, "changing")
    assert found.stake is None
    (free,) = deadlines(load(a_room(term(FREE, TUESDAY))))
    assert free.stake == ()


def test_deadlines_at_one_instant_come_in_the_order_of_facts_and_then_cancelling_first() -> None:
    document = a_night(
        term(FREE),
        term(ALL, WEDNESDAY),
        others=(a_ticket("spare", term(FREE), term(ALL, WEDNESDAY)),),
    )
    changed(document, term(FREE), term(FEE, WEDNESDAY))
    changed(document, term(FREE), term(FEE, WEDNESDAY), of="spare")
    assert [(each.booking, each.kind) for each in deadlines(load(document))] == [
        ("room", "cancelling"),
        ("room", "changing"),
        ("spare", "cancelling"),
        ("spare", "changing"),
    ]
    assert every_deadline(load(document)) == deadlines(load(document))
    # The earlier time comes first, whichever kind it is.
    early = a_room(term(FREE), term(FEE, TUESDAY), cancelling=(term(FREE), term(ALL, WEDNESDAY)))
    assert [(each.kind, each.at) for each in deadlines(load(early))] == [
        ("changing", instant(TUESDAY)),
        ("cancelling", instant(WEDNESDAY)),
    ]


def test_with_a_time_now_only_the_deadlines_after_it_are_listed() -> None:
    def kinds(now: str) -> list[str]:
        terms = (term(FREE), term(FEE, TUESDAY))
        file = load(a_room(*terms, now=now, cancelling=(term(FREE), term(ALL, WEDNESDAY))))
        return [each.kind for each in deadlines(file)]

    assert kinds(MONDAY) == ["changing", "cancelling"]
    assert kinds(TUESDAY) == ["cancelling"]
    assert kinds(THURSDAY) == []


def test_what_a_change_costs_now_is_the_fee_of_the_term_that_holds() -> None:
    def fee(now: str | None) -> object:
        return costs_now(load(a_room(term(FREE), term(FEE, TUESDAY), now=now)), "changing")

    assert fee(MONDAY) == (("room", ()),)
    assert fee(TUESDAY) == (("room", money(("25.00", "USD"))),)
    assert fee(None) == ()
    # What cancelling costs is read from the other list.
    file = load(a_room(term(FEE), now=MONDAY, cancelling=(term(ALL),)))
    assert costs_now(file, "changing") == (("room", money(("25.00", "USD"))),)
    assert costs_now(file, "cancelling") == (("room", money(("189.00", "USD"))),)
    assert costs_now(load(a_night(term(ALL), now=MONDAY)), "changing") == ()


def test_a_fee_that_never_changes_is_known_at_any_time() -> None:
    flat = load(a_room(term(FEE), cancelling=(term(FREE), term(ALL, WEDNESDAY))))
    assert costs_at_any_time(flat, "changing") == (("room", money(("25.00", "USD"))),)
    assert costs_at_any_time(flat, "cancelling") == ()
    # A BOOKING that states no terms for cancelling has its fee all the same.
    alone = load(a_room(term(FEE)))
    assert costs_at_any_time(alone, "changing") == (("room", money(("25.00", "USD"))),)
    assert costs_at_any_time(alone, "cancelling") == ()
    rising = load(a_room(term(FREE), term(FEE, TUESDAY), cancelling=(term(ALL),)))
    assert costs_at_any_time(rising, "changing") == ()
    assert costs_at_any_time(rising, "cancelling") == (("room", money(("189.00", "USD"))),)


def test_a_booking_with_no_terms_of_one_kind_is_named_for_that_kind() -> None:
    document = a_night(term(ALL), others=(a_ticket("spare"), a_ticket("other")))
    changed(document, term(FEE), of="other")
    file = load(document)
    assert with_no_terms(file, "cancelling") == ("spare", "other")
    assert with_no_terms(file, "changing") == ("room", "spare")


def test_the_terms_for_changing_change_no_answer_and_no_plan() -> None:
    plain = load(a_night(term(ALL), now=MONDAY))
    stated = load(a_room(term(FREE), term(FEE, TUESDAY), now=MONDAY, cancelling=(term(ALL),)))
    assert check(stated) == check(plain)
    assert compiler.check(stated) == check(stated)
    assert check(stated).answer is Answer.FEASIBLE


# The words.


def test_the_report_lists_both_kinds_of_deadline_and_both_costs_now() -> None:
    terms = (term(FREE), term(FEE, TUESDAY))
    said = words(a_room(*terms, now=MONDAY, cancelling=(term(FREE), term(ALL, WEDNESDAY))))
    assert said.endswith(
        "\n"
        "DEADLINEs after that time, earliest first:\n"
        f"  12:00 pm on Tuesday 11 May 2027: {START} The fee for a change is 25.00 USD in it,"
        " and nothing in the term before it. At STAKE in the fee: 25.00 USD.\n"
        "  6:00 pm on Wednesday 12 May 2027: a term for cancelling room, the BOOKING for night,"
        " starts. Cancelling costs 189.00 USD in it, and nothing in the term before it. At"
        " STAKE: 189.00 USD.\n"
        "\n"
        "What cancelling costs now:\n"
        "  room, the BOOKING for night: nothing\n"
        "\n"
        f"{NOW}\n"
        "  room, the BOOKING for night: nothing\n"
    )


@pytest.mark.parametrize(
    ("terms", "line"),
    [
        (
            (term(FEE), term([("40.00", "USD")], TUESDAY)),
            "The fee for a change is 40.00 USD in it, and 25.00 USD in the term before it. At"
            " STAKE in the fee: 15.00 USD.",
        ),
        (
            (term(FEE), term(FREE, TUESDAY)),
            "The fee for a change is nothing in it, and 25.00 USD in the term before it. Nothing"
            " is at STAKE in the fee.",
        ),
        (
            (term([("25.00", "USD"), ("100", "points")]), term([("40.00", "USD")], TUESDAY)),
            "The fee for a change is 40.00 USD in it, and 25.00 USD and 100 points in the term"
            " before it. At STAKE in the fee: 40.00 USD, in place of 25.00 USD and 100 points.",
        ),
        (
            (term(FEE), term(None, TUESDAY)),
            "The FILE does not state the fee for a change in it. The fee is 25.00 USD in the term"
            " before it. The STAKE in the fee is unknown.",
        ),
        (
            (term(None, TUESDAY),),
            "The FILE does not state the fee for a change in it, or before it. The STAKE in the"
            " fee is unknown.",
        ),
        (
            (term(FEE, TUESDAY),),
            "The fee for a change is 25.00 USD in it. The FILE does not state the fee before it."
            " The STAKE in the fee is unknown.",
        ),
        (
            (term(FREE, TUESDAY),),
            "The fee for a change is nothing in it. The FILE does not state the fee before it."
            " Nothing is at STAKE in the fee.",
        ),
        (
            (term(None, MONDAY), term(FEE, TUESDAY)),
            "The fee for a change is 25.00 USD in it. The FILE does not state the fee in the term"
            " before it. The STAKE in the fee is unknown.",
        ),
        (
            (term(None, MONDAY), term(None, TUESDAY)),
            "The FILE does not state the fee for a change in it, or in the term before it. The"
            " STAKE in the fee is unknown.",
        ),
    ],
)
def test_each_way_a_fee_can_change_in_words(terms: tuple[Document, ...], line: str) -> None:
    said = words(a_room(*terms, cancelling=(term(ALL),)))
    assert f"  12:00 pm on Tuesday 11 May 2027: {START} {line}\n" in said
    # The same terms for cancelling have the words for cancelling, with no word of a fee.
    plain = words(a_night(*terms))
    assert "a term for cancelling room, the BOOKING for night, starts." in plain
    assert "fee" not in plain


def test_a_fee_that_the_file_does_not_state_for_the_time_now() -> None:
    said = words(a_room(term(FEE, WEDNESDAY), now=MONDAY, cancelling=(term(ALL),)))
    assert f"\n{NOW}\n  room, the BOOKING for night: the FILE does not say\n" in said


def test_a_file_with_terms_for_changing_alone_has_the_last_part() -> None:
    said = words(a_room(term(FREE), term(FEE, TUESDAY)))
    assert said.endswith(
        "\n"
        "This FILE does not state the time now. So nobody knows which of its DEADLINEs have"
        " passed. All of them, earliest first (times in America/Chicago):\n"
        f"  12:00 pm on Tuesday 11 May 2027: {START} The fee for a change is 25.00 USD in it,"
        " and nothing in the term before it. At STAKE in the fee: 25.00 USD.\n"
        "\n"
        "No terms for cancelling are stated for room.\n"
    )
    assert as_json(a_room(term(FREE), term(FEE, TUESDAY)))["deadlines"][0]["kind"] == "changing"
    # A FILE that states neither kind of terms, no time now and no expiry has no such part.
    assert "DEADLINE" not in words(a_night())
    assert "No terms" not in words(a_night())


def test_once_the_last_term_for_changing_has_started_no_deadline_is_left() -> None:
    said = words(a_room(term(FREE), term(FEE, TUESDAY), now=THURSDAY))
    assert said.endswith(
        "\n"
        "No DEADLINE comes after that time.\n"
        "\n"
        f"{NOW}\n"
        "  room, the BOOKING for night: 25.00 USD\n"
        "\n"
        "No terms for cancelling are stated for room.\n"
    )


def test_with_no_time_now_a_fee_that_never_changes_is_said_for_any_time() -> None:
    said = words(a_room(term(FEE), cancelling=(term(ALL),)))
    assert said.endswith(
        "\n"
        "This FILE does not state the time now. Its terms have no DEADLINE.\n"
        "\n"
        "What cancelling costs at any time:\n"
        "  room, the BOOKING for night: 189.00 USD\n"
        "\n"
        f"{AT_ANY_TIME}\n"
        "  room, the BOOKING for night: 25.00 USD\n"
    )
    timed = words(a_room(term(FEE), now=MONDAY, cancelling=(term(ALL),)))
    assert AT_ANY_TIME not in timed
    assert f"\n{NOW}\n  room, the BOOKING for night: 25.00 USD\n" in timed


def test_a_booking_with_no_terms_is_named_once_for_each_kind_it_lacks() -> None:
    """The room states both kinds. One BOOKING states neither, one each kind alone."""
    others = (a_ticket("neither"), a_ticket("cancelled", term(ALL)), a_ticket("moved"))
    document = a_room(term(FEE), cancelling=(term(ALL),))
    document["facts"][4:4] = list(others)
    changed(document, term(FEE), of="moved")
    assert words(document).endswith(
        "\n"
        "No terms for cancelling or for changing are stated for neither.\n"
        "\n"
        "No terms for cancelling are stated for moved.\n"
        "\n"
        "No terms for changing are stated for cancelled.\n"
    )
    shown = as_json(document)
    assert shown["no_terms_for_cancelling"] == ["neither", "moved"]
    assert shown["no_terms_for_changing"] == ["neither", "cancelled"]


def test_a_fee_that_rises_has_the_rise_at_stake() -> None:
    """From 25 dollars to 40: 15 dollars are at STAKE in the fee, in words and as JSON."""
    document = a_room(term(FEE), term([("40.00", "USD")], TUESDAY), now=MONDAY)
    (found,) = deadlines(load(document))
    assert found.stake == money(("15.00", "USD"))
    (shown,) = as_json(document)["deadlines"]
    assert shown["stake"] == [{"amount": "15.00", "currency": "USD"}]
    assert shown["before"] == [{"amount": "25.00", "currency": "USD"}]
    assert shown["from_then"] == [{"amount": "40.00", "currency": "USD"}]
    assert "At STAKE in the fee: 15.00 USD.\n" in words(document)


def test_a_report_that_cannot_tell_has_the_terms_for_changing() -> None:
    """Nobody has said when the night starts, and a LOCK asks for it."""
    document = a_room(term(FREE), term(FEE, TUESDAY), now=MONDAY)
    document["facts"] = [fact for fact in document["facts"] if fact["id"] != "night-time"]
    file = load(document)
    assert check(file).answer is Answer.UNDETERMINED
    said = report.as_text(file, check(file))
    assert f"  12:00 pm on Tuesday 11 May 2027: {START}" in said
    assert f"\n{NOW}\n  room, the BOOKING for night: nothing\n" in said


def test_every_kind_of_report_has_the_terms_for_changing() -> None:
    """A room that Alex cannot use: the LOCK names somebody the BOOKING does not cover."""
    document = a_room(term(FREE), term(FEE, TUESDAY), now=MONDAY)
    document["persons"].append({"id": "sam", "name": "sam"})
    document["decisions"][0]["persons"] = ["sam"]
    document["facts"].append(
        {"id": "no-other-room", "complete": {"rights_to": "night"}},
    )
    file = load(document)
    assert check(file).answer is Answer.INFEASIBLE
    assert f"  12:00 pm on Tuesday 11 May 2027: {START}" in report.as_text(file, check(file))


# The report as JSON.


def test_the_report_as_json_names_the_kind_of_each_term() -> None:
    terms = (term(FREE), term(FEE, TUESDAY))
    shown = as_json(a_room(*terms, now=MONDAY, cancelling=(term(FREE), term(ALL, WEDNESDAY))))
    assert shown["deadlines"] == [
        {
            "at": TUESDAY,
            "kind": "changing",
            "booking": "room",
            "option": "night",
            "before": [],
            "from_then": [{"amount": "25.00", "currency": "USD"}],
            "change": "rises",
            "stake": [{"amount": "25.00", "currency": "USD"}],
            "first_term": False,
        },
        {
            "at": WEDNESDAY,
            "kind": "cancelling",
            "booking": "room",
            "option": "night",
            "before": [],
            "from_then": [{"amount": "189.00", "currency": "USD"}],
            "change": "rises",
            "stake": [{"amount": "189.00", "currency": "USD"}],
            "first_term": False,
        },
    ]
    assert shown["cancelling_now"] == [{"booking": "room", "option": "night", "costs": []}]
    assert shown["changing_now"] == [{"booking": "room", "option": "night", "costs": []}]
    assert "changing_at_any_time" not in shown
    assert "no_terms_for_changing" not in shown
    assert "no_terms_for_cancelling" not in shown


def test_the_report_as_json_has_the_fee_at_any_time_only_with_no_time_now() -> None:
    untimed = as_json(a_room(term(FEE), cancelling=(term(ALL),)))
    fee = [
        {"booking": "room", "option": "night", "costs": [{"amount": "25.00", "currency": "USD"}]}
    ]
    assert untimed["changing_at_any_time"] == fee
    assert "changing_now" not in untimed
    timed = as_json(a_room(term(FEE), now=MONDAY, cancelling=(term(ALL),)))
    assert timed["changing_now"] == fee
    assert "changing_at_any_time" not in timed


def test_the_first_term_of_each_list_is_marked_in_its_own_list() -> None:
    shown = as_json(a_room(term(FEE, TUESDAY), cancelling=(term(FREE), term(ALL, WEDNESDAY))))
    assert [(each["kind"], each["first_term"]) for each in shown["deadlines"]] == [
        ("changing", True),
        ("cancelling", False),
    ]
