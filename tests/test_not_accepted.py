"""A term of a BOOKING can say that the seller accepts no cancellation, or no change."""

from typing import Any

import pytest

from agloe import compiler
from agloe.answers import (
    Deadline,
    check,
    costs_at_any_time,
    costs_now,
    deadlines,
    not_accepted_at_any_time,
    not_accepted_now,
)
from agloe.file import Booking, Term, instant, load
from tests.stories import Document
from tests.test_changing import a_room, changed
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
CANCEL = "a term for cancelling room, the BOOKING for night, starts."
CHANGE = "a term for changes to room, the BOOKING for night, starts."


def none(since: str | None = None) -> Document:
    """A term that says the seller accepts none, from this time on."""
    return {"accepted": False} if since is None else {"from": since, "accepted": False}


def room_of(document: Document) -> Booking:
    return next(fact for fact in load(document).facts if isinstance(fact, Booking))


# The format.


def test_a_term_can_say_that_the_seller_accepts_none() -> None:
    room = room_of(a_night(term(FREE), none(WEDNESDAY)))
    assert room.cancelling == (Term(None, ()), Term(instant(WEDNESDAY), None, refused=True))
    assert room_of(a_room(none())).changing == (Term(None, None, refused=True),)
    # No other term states it: one with a cost, or one that says nothing.
    plain = room_of(a_night(term(ALL), term(None, TUESDAY))).cancelling
    assert not any(each.refused for each in plain)


def test_a_term_states_a_cost_or_that_the_seller_accepts_none_and_not_both() -> None:
    both = {"from": WEDNESDAY, "accepted": False, "costs": [{"amount": "5.00", "currency": "USD"}]}
    assert "/facts/3/booking/cancelling/0" in problems(a_night(both))
    assert "/facts/3/booking/changing/0" in problems(a_room(both))
    # The only value is false: a term that states a cost says that the seller accepts it.
    assert "/facts/3/booking/cancelling/0/accepted" in problems(a_night({"accepted": True}))
    assert "/facts/3/booking/changing/0/accepted" in problems(a_room({"accepted": True}))


def test_such_a_term_follows_the_rules_of_a_list_of_terms() -> None:
    assert problems(a_night(term(FREE), none())) == (
        "/facts/3/booking/cancelling/1: only the first term can leave out when it starts"
    )
    assert problems(a_room(none(WEDNESDAY), none(TUESDAY))) == (
        "/facts/3/booking/changing/1: it does not start after the term before it"
    )


# The DEADLINEs.


def test_a_chance_ends_where_a_term_with_a_cost_comes_before() -> None:
    (found,) = deadlines(load(a_night(term(FREE), none(WEDNESDAY))))
    assert found == Deadline(instant(WEDNESDAY), "room", (), None, refused_after=True)
    assert (found.change, found.stake) == ("ends", None)
    (fee,) = deadlines(load(a_room(term(FEE), none(TUESDAY))))
    assert fee == Deadline(
        instant(TUESDAY),
        "room",
        money(("25.00", "USD")),
        None,
        kind="changing",
        refused_after=True,
    )
    assert (fee.change, fee.stake) == ("ends", None)


def test_nobody_knows_what_ends_where_nothing_is_stated_before() -> None:
    """A first term with a time, or a term after one with no stated cost."""
    (first,) = deadlines(load(a_night(none(TUESDAY))))
    assert (first.first, first.refused_before, first.refused_after) == (True, False, True)
    assert (first.change, first.stake) == ("not stated before", None)
    _, later = deadlines(load(a_night(term(None, TUESDAY), none(WEDNESDAY))))
    assert (later.first, later.before, later.refused_after) == (False, None, True)
    assert (later.change, later.stake) == ("not stated before", None)


def test_nothing_is_at_stake_after_a_term_in_which_the_seller_accepts_none() -> None:
    """There was nothing to do before the DEADLINE, so waiting loses nothing."""
    (cost,) = deadlines(load(a_night(none(), term(ALL, WEDNESDAY))))
    assert cost == Deadline(
        instant(WEDNESDAY), "room", None, money(("189.00", "USD")), refused_before=True
    )
    assert (cost.change, cost.stake) == ("starts", ())
    (unsaid,) = deadlines(load(a_night(none(), term(None, WEDNESDAY))))
    assert (unsaid.refused_before, unsaid.after) == (True, None)
    assert (unsaid.change, unsaid.stake) == ("not stated from then", ())


def test_two_terms_in_which_the_seller_accepts_none_state_the_same() -> None:
    assert deadlines(load(a_night(none(), none(WEDNESDAY)))) == ()
    (only,) = deadlines(load(a_night(term(FREE), none(TUESDAY), none(WEDNESDAY))))
    assert only.at == instant(TUESDAY)
    # A cost of nothing is not the same as accepting none, either way round.
    assert len(deadlines(load(a_night(term(FREE), none(TUESDAY), term(FREE, WEDNESDAY))))) == 2


def test_what_holds_now_and_at_any_time() -> None:
    def at(now: str | None) -> Any:
        return load(a_night(term(FREE), none(WEDNESDAY), now=now))

    assert not_accepted_now(at(MONDAY), "cancelling") == ()
    assert not_accepted_now(at(WEDNESDAY), "cancelling") == ("room",)
    assert not_accepted_now(at(THURSDAY), "cancelling") == ("room",)
    assert not_accepted_now(at(THURSDAY), "changing") == ()
    assert not_accepted_now(at(None), "cancelling") == ()
    assert costs_now(at(THURSDAY), "cancelling") == (("room", None),)
    # Before the first term starts, nothing holds: nobody has said.
    early = load(a_night(none(WEDNESDAY), now=MONDAY))
    assert costs_now(early, "cancelling") == (("room", None),)
    assert not_accepted_now(early, "cancelling") == ()
    # At any time: the first term has no time, and every term says the same.
    assert not_accepted_at_any_time(load(a_night(none())), "cancelling") == ("room",)
    assert not_accepted_at_any_time(load(a_night(none())), "changing") == ()
    assert not_accepted_at_any_time(load(a_room(none())), "changing") == ("room",)
    assert not_accepted_at_any_time(load(a_night(none(WEDNESDAY))), "cancelling") == ()
    assert not_accepted_at_any_time(load(a_night(none(), term(ALL, WEDNESDAY))), "cancelling") == ()
    assert not_accepted_at_any_time(load(a_night(term(ALL), none(WEDNESDAY))), "cancelling") == ()
    assert not_accepted_at_any_time(load(a_night()), "cancelling") == ()
    assert costs_at_any_time(load(a_night(none())), "cancelling") == ()
    assert costs_at_any_time(load(a_night(term(ALL), none(WEDNESDAY))), "cancelling") == ()


def test_the_seller_can_take_it_again_from_a_later_term() -> None:
    """No cancellation until Tuesday, and from then on for 189 dollars."""

    def at(now: str) -> Document:
        return a_night(none(), term(ALL, TUESDAY), now=now)

    cost = money(("189.00", "USD"))
    assert not_accepted_now(load(at(MONDAY)), "cancelling") == ("room",)
    for later in (TUESDAY, WEDNESDAY):
        assert not_accepted_now(load(at(later)), "cancelling") == ()
        assert costs_now(load(at(later)), "cancelling") == (("room", cost),)
        assert "  room, the BOOKING for night: 189.00 USD\n" in words(at(later))
        assert "accepts no" not in words(at(later))
        assert as_json(at(later))["cancelling_now"] == [
            {
                "booking": "room",
                "option": "night",
                "costs": [{"amount": "189.00", "currency": "USD"}],
            }
        ]


def test_a_term_that_says_it_again_changes_nothing_for_any_time() -> None:
    """The seller accepts no cancellation, and says so again from Wednesday."""
    document = a_night(none(), none(WEDNESDAY))
    assert not_accepted_at_any_time(load(document), "cancelling") == ("room",)
    assert "  room, the BOOKING for night: the seller accepts no cancellation\n" in words(document)
    assert as_json(document)["cancelling_at_any_time"] == [
        {"booking": "room", "option": "night", "costs": None, "accepted": False}
    ]


def test_such_a_term_changes_no_answer_and_no_plan() -> None:
    plain = load(a_night(term(ALL), now=MONDAY))
    stated = load(a_room(none(), now=MONDAY, cancelling=(term(FREE), none(WEDNESDAY))))
    assert check(stated) == check(plain)
    assert compiler.check(stated) == check(stated)


# The words.


@pytest.mark.parametrize(
    ("terms", "cancelling", "changing"),
    [
        (
            (term(FREE), none(TUESDAY)),
            "The seller accepts no cancellation in it. Cancelling costs nothing in the term"
            " before it. At STAKE: the chance to cancel it.",
            "The seller accepts no change in it. The fee for a change is nothing in the term"
            " before it. At STAKE: the chance to change it.",
        ),
        (
            (term(FEE), none(TUESDAY)),
            "The seller accepts no cancellation in it. Cancelling costs 25.00 USD in the term"
            " before it. At STAKE: the chance to cancel it.",
            "The seller accepts no change in it. The fee for a change is 25.00 USD in the term"
            " before it. At STAKE: the chance to change it.",
        ),
        (
            (none(TUESDAY),),
            "The seller accepts no cancellation in it. The FILE does not say whether the seller"
            " accepts a cancellation before it. The STAKE is unknown.",
            "The seller accepts no change in it. The FILE does not say whether the seller accepts"
            " a change before it. The STAKE is unknown.",
        ),
        (
            (term(None, MONDAY), none(TUESDAY)),
            "The seller accepts no cancellation in it. The FILE does not say whether the seller"
            " accepts a cancellation in the term before it. The STAKE is unknown.",
            "The seller accepts no change in it. The FILE does not say whether the seller accepts"
            " a change in the term before it. The STAKE is unknown.",
        ),
        (
            (none(), term(FEE, TUESDAY)),
            "Cancelling costs 25.00 USD in it. The seller accepts no cancellation in the term"
            " before it, so nothing is at STAKE.",
            "The fee for a change is 25.00 USD in it. The seller accepts no change in the term"
            " before it, so nothing is at STAKE.",
        ),
        (
            (none(), term(None, TUESDAY)),
            "The FILE does not say what cancelling costs in it. The seller accepts no"
            " cancellation in the term before it, so nothing is at STAKE.",
            "The FILE does not state the fee for a change in it. The seller accepts no change in"
            " the term before it, so nothing is at STAKE.",
        ),
    ],
)
def test_each_pair_of_terms_in_words(
    terms: tuple[Document, ...], cancelling: str, changing: str
) -> None:
    assert f"  12:00 pm on Tuesday 11 May 2027: {CANCEL} {cancelling}\n" in words(a_night(*terms))
    assert f"  12:00 pm on Tuesday 11 May 2027: {CHANGE} {changing}\n" in words(a_room(*terms))


def test_what_holds_now_in_words() -> None:
    document = a_room(
        term(FREE), none(TUESDAY), now=THURSDAY, cancelling=(term(FREE), none(WEDNESDAY))
    )
    assert words(document).endswith(
        "\n"
        "No DEADLINE comes after that time.\n"
        "\n"
        "What cancelling costs now:\n"
        "  room, the BOOKING for night: the seller accepts no cancellation\n"
        "\n"
        "The fee for a change now, apart from any difference in price:\n"
        "  room, the BOOKING for night: the seller accepts no change\n"
    )
    # A term that has not started yet says nothing of now.
    early = words(a_night(none(WEDNESDAY), now=MONDAY))
    assert "  room, the BOOKING for night: the FILE does not say\n" in early
    assert "accepts no cancellation\n" not in early


def test_what_holds_at_any_time_in_words() -> None:
    """The room cannot be cancelled, and a change to it costs 25 dollars. The ticket costs
    189 dollars to cancel, and nobody takes a change to it."""
    document = a_room(term(FEE), cancelling=(none(),))
    document["facts"].append(a_ticket("spare", term(ALL)))
    changed(document, none(), of="spare")
    assert words(document).endswith(
        "\n"
        "This FILE does not state the time now. Its terms have no DEADLINE.\n"
        "\n"
        "What cancelling costs at any time:\n"
        "  room, the BOOKING for night: the seller accepts no cancellation\n"
        "  spare, the BOOKING for night: 189.00 USD\n"
        "\n"
        "The fee for a change at any time, apart from any difference in price:\n"
        "  room, the BOOKING for night: 25.00 USD\n"
        "  spare, the BOOKING for night: the seller accepts no change\n"
    )


def test_a_term_with_a_time_says_nothing_of_any_time() -> None:
    said = words(a_night(none(WEDNESDAY)))
    assert "at any time" not in said
    assert (
        f"  6:00 pm on Wednesday 12 May 2027: {CANCEL} The seller accepts no cancellation" in said
    )


# The report as JSON.


def test_a_deadline_as_json_says_which_side_accepts_none() -> None:
    (ends,) = as_json(a_night(term(FREE), none(WEDNESDAY)))["deadlines"]
    assert ends == {
        "at": WEDNESDAY,
        "kind": "cancelling",
        "booking": "room",
        "option": "night",
        "before": [],
        "from_then": None,
        "change": "ends",
        "stake": None,
        "first_term": False,
        "accepted_from_then": False,
    }
    (starts,) = as_json(a_room(none(), term(FEE, TUESDAY)))["deadlines"]
    assert starts == {
        "at": TUESDAY,
        "kind": "changing",
        "booking": "room",
        "option": "night",
        "before": None,
        "from_then": [{"amount": "25.00", "currency": "USD"}],
        "change": "starts",
        "stake": [],
        "first_term": False,
        "accepted_before": False,
    }
    # A DEADLINE between two terms that the seller accepts has neither member.
    (plain,) = as_json(a_night(term(FREE), term(ALL, WEDNESDAY)))["deadlines"]
    assert "accepted_before" not in plain
    assert "accepted_from_then" not in plain


def test_what_holds_now_and_at_any_time_as_json() -> None:
    timed = as_json(a_room(none(), now=MONDAY, cancelling=(term(ALL),)))
    assert timed["changing_now"] == [
        {"booking": "room", "option": "night", "costs": None, "accepted": False}
    ]
    assert timed["cancelling_now"] == [
        {"booking": "room", "option": "night", "costs": [{"amount": "189.00", "currency": "USD"}]}
    ]
    untimed = as_json(a_room(none(), cancelling=(term(ALL),)))
    assert untimed["changing_at_any_time"] == [
        {"booking": "room", "option": "night", "costs": None, "accepted": False}
    ]
    assert untimed["cancelling_at_any_time"] == [
        {"booking": "room", "option": "night", "costs": [{"amount": "189.00", "currency": "USD"}]}
    ]
    # A cost that the FILE does not state for the time now is not a refusal.
    early = as_json(a_night(none(WEDNESDAY), now=MONDAY))
    assert early["cancelling_now"] == [{"booking": "room", "option": "night", "costs": None}]
