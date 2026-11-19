"""Who pays: a place with a price is paid from a BUDGET of the PERSON who takes it."""

from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal
from itertools import product
from random import Random

import pytest

from agloe import answers, compiler, report
from agloe.answers import Answer, Cover
from agloe.file import Budget, File, FileError, Money, Offer
from agloe.reference import (
    Broken,
    Constraint,
    Itinerary,
    Step,
    Unknown,
    World,
    best_case,
    broken,
    placed,
    unknowns,
    with_these_at_best,
    worst_case,
)
from tests.stories import (
    Document,
    booking,
    budget,
    cutoff,
    every,
    every_right,
    lasts,
    lock,
    must,
    needs_right,
    offer,
    satisfies,
    seconds,
    starts_at,
    stays,
    trip,
)
from tests.test_cross_check import works_on_the_grid
from tests.test_rights import every_world_of_rights
from tests.test_where_a_path_ends import checked, has_no_record_to_spare

EVERYONE = ["alex", "sam", "jo"]


def at_ten(option: str) -> list[Document]:
    """An OPTION that starts at 10:00 am, with nothing left unknown about its time."""
    return [starts_at(option, 10), lasts(option, "PT1H"), cutoff(option, "PT0S")]


def a_boat_tour(
    *more: Document,
    locked: Sequence[str] = ("alex", "sam"),
    budgets: Sequence[Document] | None = None,
) -> File:
    """A boat tour at 10:00 am that needs a right. A LOCK names Alex and Sam.

    Alex has a BOOKING, so Sam is the one who has to buy. Unless told otherwise, one BUDGET
    called money pays in USD for everybody.
    """
    decisions = [lock("tour", *locked)] if locked else []
    facts = [*at_ten("tour"), needs_right("tour"), booking("tour", "alex"), *more]
    options = [stays("tour", "dock")]
    return trip(EVERYONE, ["dock"], options, facts, decisions, tickets=True, budgets=budgets)


def on_the_tour(*persons: str) -> Itinerary:
    return (Step("tour", "dock", "dock", persons, seconds(10), seconds(11)),)


def right(option: str, person: str) -> Unknown:
    return Unknown("another right", option, person=person)


def price_of(offer: str, option: str = "tour") -> Unknown:
    """What a place of an OFFER costs, where the FILE does not say."""
    return Unknown("price", option, about=offer)


def can_pay(person: str) -> Unknown:
    """That a BUDGET can pay for a PERSON whom no BUDGET lists."""
    return Unknown("funding", person=person)


def asked(found: answers.Report) -> list[list[Unknown]]:
    return [[needed.unknown for needed in enough] for enough in found.missing]


def in_words(file: File) -> list[str]:
    return report.as_text(file, checked(file)).splitlines()


def problems(*facts: Document, budgets: Sequence[Document] | None = None) -> str:
    with pytest.raises(FileError) as refused:
        a_boat_tour(*facts, budgets=budgets)
    return str(refused.value)


def costing(amount: str, currency: str = "USD") -> Document:
    """An OFFER of two places for the tour with a price written this way."""
    offered = offer("tour", 2)
    offered["offer"]["prices"] = [{"amount": amount, "currency": currency}]
    return offered


# ------------------------------- What a FILE holds -------------------------------


def test_a_budget_lists_who_may_draw_on_it_and_the_currencies_it_holds() -> None:
    both = budget("pot", "alex", "sam", holds=["USD", "EUR"])
    file = a_boat_tour(budgets=[both])
    assert file.budgets == (Budget("pot", "pot", ("alex", "sam"), ("USD", "EUR")),)
    assert file.listed("sam") and not file.listed("jo")
    five_euros = Money(Decimal(5), "EUR")
    assert file.pays("sam", five_euros) == file.budgets[0]
    assert file.pays("jo", five_euros) is None
    assert file.pays("sam", Money(Decimal(5), "GBP")) is None


def test_a_price_of_nothing_draws_on_no_budget() -> None:
    file = a_boat_tour()
    assert file.pays("sam", Money(Decimal("0.00"), "USD")) is None


def test_the_first_budget_listed_that_can_pay_is_the_one_that_pays() -> None:
    pots = [budget("euros", "sam", holds=["EUR"]), budget("first", "sam"), budget("second", "sam")]
    file = a_boat_tour(budgets=pots)
    payer = file.pays("sam", Money(Decimal(5), "USD"))
    assert payer is not None and payer.id == "first"


def test_an_offer_states_what_one_place_costs() -> None:
    file = a_boat_tour(offer("tour", 2, price="32.00 USD"), offer("tour", 1, id="more", price=None))
    assert file.offers("tour") == (
        Offer("tour-offer", "tour", 2, Money(Decimal("32.00"), "USD")),
        Offer("more", "tour", 1, None),
    )


def test_two_ways_to_write_one_amount_are_the_same_amount() -> None:
    written = [a_boat_tour(costing(amount)).offers("tour")[0].price for amount in ("32", "32.0")]
    assert written[0] == written[1] == Money(Decimal("32.00"), "USD")
    assert str(a_boat_tour(costing("32.50")).offers("tour")[0].price) == "32.50 USD"


@pytest.mark.parametrize("amount", ["032", "-1", "+1", "1e2", "1,000", "1.", ".5", "1.23456", ""])
def test_an_amount_is_digits_with_at_most_four_after_a_point(amount: str) -> None:
    assert "fits no known shape" in problems(costing(amount))


@pytest.mark.parametrize("amount", ["0", "0.5", "1.2345", "999999999999", "10.00"])
def test_an_amount_can_be_nothing_or_as_large_as_twelve_digits(amount: str) -> None:
    assert a_boat_tour(costing(amount)).offers("tour")[0].price == Money(Decimal(amount), "USD")


def test_money_is_checked_like_everything_else() -> None:
    assert "fits no known shape" in problems(costing("5", "US dollars"))
    unknown = [budget("pot", "pat")]
    assert problems(budgets=unknown) == "/budgets/0: pat is not a PERSON in this FILE"
    same_id = [budget("alex", "sam")]
    assert problems(budgets=same_id) == "/budgets/0: the id alex is used more than once"
    twice = offer("tour", 2)
    twice["offer"]["prices"] *= 2
    assert "is too long" in problems(twice)
    none = offer("tour", 2)
    none["offer"]["prices"] = []
    assert "should be non-empty" in problems(none)
    listed_twice = budget("pot", "sam", "sam")
    assert "non-unique" in problems(budgets=[listed_twice])


# ------------------------------- The CONSTRAINT -------------------------------


def test_a_place_is_paid_from_a_budget_that_lists_the_person_and_holds_the_currency() -> None:
    in_euros = offer("tour", 2, price="9.00 EUR")
    file = a_boat_tour(in_euros, locked=())
    unpaid = [Broken(Constraint.PAID, "tour", ("sam",))]
    assert broken(file, worst_case(file), on_the_tour("alex", "sam")) == unpaid
    for pots in (
        [budget("sams", "sam", holds=["EUR"])],
        [budget("alexs", "alex", "sam", holds=["EUR"])],
    ):
        paid = a_boat_tour(in_euros, locked=(), budgets=pots)
        assert broken(paid, worst_case(paid), on_the_tour("alex", "sam")) == []
    not_sams = a_boat_tour(in_euros, locked=(), budgets=[budget("alexs", "alex", holds=["EUR"])])
    assert broken(not_sams, worst_case(not_sams), on_the_tour("alex", "sam")) == unpaid


def test_a_place_that_costs_nothing_needs_nobody_to_pay() -> None:
    file = a_boat_tour(offer("tour", 2, price="0 EUR"), locked=(), budgets=[])
    assert broken(file, worst_case(file), on_the_tour("alex", "sam", "jo")) == []


def test_too_few_places_are_reported_before_who_can_pay() -> None:
    file = a_boat_tour(offer("tour", 1, price="9.00 EUR"), locked=())
    no_right = [Broken(Constraint.RIGHT, "tour", ("jo",))]
    assert broken(file, worst_case(file), on_the_tour("alex", "sam", "jo")) == no_right


def test_each_person_takes_the_first_place_that_leaves_a_way_for_the_rest() -> None:
    """Sam can pay only in dollars. Alex can pay either way, and comes first in the FILE."""
    offers = [offer("tour", 1, id="dollar"), offer("tour", 1, id="euro", price="9.00 EUR")]
    pots = [budget("sams", "sam"), budget("alexs", "alex", holds=["USD", "EUR"])]
    options = [stays("tour", "dock")]
    facts = [*at_ten("tour"), needs_right("tour"), *offers]
    file = trip(EVERYONE, ["dock"], options, facts, [], tickets=True, budgets=pots)
    worst = worst_case(file)
    assert placed(file, worst, "tour", ["alex", "sam"]) == {"alex": "euro", "sam": "dollar"}
    assert placed(file, worst, "tour", ["alex"]) == {"alex": "dollar"}
    assert placed(file, worst, "tour", ["alex", "sam", "jo"]) == {"alex": "euro", "sam": "dollar"}
    unpaid = [Broken(Constraint.PAID, "tour", ("jo",))]
    more = replace(worst, places={"tour": 3})
    assert broken(file, more, on_the_tour("alex", "sam", "jo")) == unpaid


def test_a_world_says_who_can_pay_for_a_place_of_each_offer() -> None:
    offers = [offer("tour", 1, id="priced"), offer("tour", 1, id="unpriced", price=None)]
    file = a_boat_tour(*offers, budgets=[budget("sams", "sam")])
    assert worst_case(file).payable == {("priced", "sam")}
    everybody = {(each, person) for each in ("priced", "unpriced") for person in EVERYONE}
    assert best_case(file).payable == everybody


# ------------------------------- The three answers -------------------------------


def test_a_report_says_what_a_place_costs_and_which_budget_pays() -> None:
    file = a_boat_tour(offer("tour", 2, price="32.00 USD"))
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert found.rights == (
        Cover("tour", "alex", "tour-booking", False),
        Cover("tour", "sam", "tour-offer", True, Money(Decimal("32.00"), "USD"), "money"),
    )
    words = in_words(file)
    assert words[4] == (
        "    ! sam still has to buy a right to this, from tour-offer, for 32.00 USD from money."
    )
    offered = "an OFFER has 2 places for tour that can still be bought, for 32.00 USD each"
    assert f"  tour-offer: {offered}" in words
    assert report.as_json(file, found)["to_buy"] == [
        {
            "option": "tour",
            "offer": "tour-offer",
            "persons": ["sam"],
            "only_if_needed": False,
            "price": {"amount": "32.00", "currency": "USD"},
            "budget": "money",
        }
    ]


def test_a_sponsor_is_a_budget_that_lists_the_person_it_pays_for() -> None:
    """Alex's own money pays for Sam, because the FILE lists Sam on it."""
    file = a_boat_tour(offer("tour", 2), budgets=[budget("alexs", "alex", "sam")])
    found = checked(file)
    assert found.rights[1].budget == "alexs"
    only_alex = a_boat_tour(offer("tour", 2), budgets=[budget("alexs", "alex")])
    assert checked(only_alex).answer is Answer.UNDETERMINED


def test_a_place_that_costs_nothing_is_taken_at_no_cost() -> None:
    file = a_boat_tour(offer("tour", 2, price="0 EUR"), budgets=[])
    found = checked(file)
    assert found.rights[1] == Cover("tour", "sam", "tour-offer", True, Money(Decimal(0), "EUR"))
    assert in_words(file)[4] == (
        "    ! sam still has to buy a right to this, from tour-offer, at no cost."
    )
    to_buy = report.as_json(file, found)["to_buy"]
    assert isinstance(to_buy, list) and to_buy[0]["budget"] is None


def test_where_no_budget_lists_a_person_nobody_knows_who_pays() -> None:
    file = a_boat_tour(offer("tour", 2), budgets=[])
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    assert asked(found) == [[right("tour", "sam")], [can_pay("sam")]]
    assert in_words(file)[-5:] == [
        "The trip works in any of these cases:",
        "  1. A right to tour is found for sam, in addition to the 2 places on OFFER.",
        "  2. A BUDGET can pay for what sam has to buy.",
        "",
        "This FILE names no BUDGET, so nobody has said who pays for a place.",
    ]
    assert report.as_json(file, found)["missing"] == [
        [{"what": "another right", "option": "tour", "person": "sam", "at_most": None}],
        [{"what": "funding", "person": "sam", "at_most": None}],
    ]


def test_a_person_whom_a_budget_lists_pays_from_no_other() -> None:
    """Sam's BUDGET holds dollars and the place is in euros. Nothing is unknown about that."""
    in_euros = offer("tour", 2, price="9.00 EUR")
    file = a_boat_tour(in_euros)
    assert can_pay("sam") not in unknowns(file)
    assert asked(checked(file)) == [[right("tour", "sam")]]
    closed = a_boat_tour(in_euros, every_right("tour", "tour-offer"))
    found = checked(closed)
    assert found.answer is Answer.INFEASIBLE
    conflict = (
        "tour-needs-right",
        "tour-booking",
        "tour-offer",
        "every-right-to-tour",
        "lock-tour",
    )
    assert found.conflict == conflict
    assert has_no_record_to_spare(closed, conflict)


def test_an_unknown_payer_does_not_make_a_trip_infeasible() -> None:
    file = a_boat_tour(offer("tour", 2), every_right("tour", "tour-offer"), budgets=[])
    assert asked(checked(file)) == [[can_pay("sam")]]


def test_nobody_can_count_on_a_place_with_no_stated_price() -> None:
    unpriced = offer("tour", 2, price=None)
    file = a_boat_tour(unpriced)
    found = checked(file)
    assert asked(found) == [[right("tour", "sam")], [price_of("tour-offer")]]
    assert in_words(file)[-5:] == [
        "  1. A right to tour is found for sam, in addition to the 2 places on OFFER.",
        "  2. A place from tour-offer has a price that each PERSON who takes one can pay.",
        "",
        "A place is paid from a BUDGET that lists the PERSON and holds the currency:",
        "  money: for alex, sam and jo; it holds USD",
    ]
    missing = report.as_json(file, found)["missing"]
    assert isinstance(missing, list)
    assert missing[1] == [
        {"what": "price", "option": "tour", "offer": "tour-offer", "at_most": None}
    ]
    nobody_pays = a_boat_tour(unpriced, every_right("tour", "tour-offer"), budgets=[])
    assert asked(checked(nobody_pays)) == [[price_of("tour-offer")]]


def test_a_conflict_names_an_offer_with_no_stated_price_as_that() -> None:
    """One place for Sam and Jo, and that is all there is. What it costs changes nothing."""
    one_place = offer("tour", 1, price=None)
    file = a_boat_tour(one_place, every_right("tour", "tour-offer"), locked=EVERYONE)
    assert checked(file).answer is Answer.INFEASIBLE
    offered = "an OFFER has 1 place for tour that can still be bought; nobody knows the price"
    assert f"  tour-offer: {offered}" in in_words(file)


def test_the_unknown_facts_about_money_have_their_place_in_the_order() -> None:
    offers = [offer("tour", 1, id="first", price=None), offer("tour", 1, id="second", price=None)]
    file = a_boat_tour(*offers, budgets=[budget("alexs", "alex")])
    assert list(unknowns(file)) == [
        right("tour", "sam"),
        right("tour", "jo"),
        price_of("first"),
        price_of("second"),
        can_pay("sam"),
        can_pay("jo"),
    ]
    assert can_pay("sam") not in unknowns(a_boat_tour(budgets=[]))


def two_views(first: str = "9.00 EUR") -> File:
    """A view is a must for Alex. Two visits give it, and each has one place on OFFER.

    The deck is listed first. Alex's BUDGET holds dollars.
    """
    options = [stays("deck", "loop"), stays("tower", "loop")]
    facts = [*at_ten("deck"), *at_ten("tower"), needs_right("deck"), needs_right("tower")]
    facts += [satisfies("deck", "view"), satisfies("tower", "view"), every("view")]
    facts += [offer("deck", 1, price=first), offer("tower", 1)]
    facts += [every_right("deck", "deck-offer"), every_right("tower", "tower-offer")]
    wants = [must("view", "alex")]
    return trip(["alex"], ["loop"], options, facts, [], wants=wants, tickets=True)


def test_a_visit_that_cannot_be_paid_for_is_not_the_plan_shown() -> None:
    """The deck is listed first, but its place is in euros. The tower can be paid for."""
    assert [step.option for step in checked(two_views("10.00 USD")).itinerary] == ["deck"]
    found = checked(two_views())
    assert [step.option for step in found.itinerary] == ["tower"]
    assert found.rights == (
        Cover("tower", "alex", "tower-offer", True, Money(Decimal("10.00"), "USD"), "money"),
    )
    assert "deck-offer" not in found.relies_on


# ------------------------------- Against every possible world -------------------------------


def two_tours_with_money(rng: Random) -> File:
    """Two OPTIONs at one PLACE with every time stated. Only rights and money are unknown."""
    persons = ["alex", "sam", "jo"] if rng.random() < 0.5 else ["alex", "sam"]
    options = [stays("tour", "dock"), stays("cruise", "dock")]
    facts: list[Document] = []
    decisions: list[Document] = []
    prices = ["10.00 USD", "10.00 USD", None, "5.00 EUR", "0 USD"]
    for option in ("tour", "cruise"):
        facts += [starts_at(option, 9, 15 * rng.randrange(3)), lasts(option, "PT15M")]
        facts += [cutoff(option, "PT0S"), needs_right(option)]
        if rng.random() < 0.4:
            facts.append(booking(option, *rng.sample(persons, rng.randrange(1, len(persons)))))
        offers = [f"{option}-offer-{number}" for number in range(rng.choice([1, 1, 2]))]
        facts += [
            offer(option, rng.choice([1, 2]), id=name, price=rng.choice(prices)) for name in offers
        ]
        if rng.random() < 0.6:
            facts.append(every_right(option, *offers))
        if rng.random() < 0.8:
            decisions.append(lock(option, *rng.sample(persons, rng.randrange(1, len(persons) + 1))))
    some = rng.sample(persons, rng.randrange(1, len(persons) + 1))
    pots = rng.choice(
        [
            [budget("money", *persons)],
            [budget("money", *some)],
            [],
            [budget("dollars", *some), budget("euros", *persons, holds=["EUR"])],
        ]
    )
    return trip(persons, ["dock"], options, facts, decisions, tickets=True, budgets=pots)


def every_world_of_money(file: File) -> list[World]:
    """Every way the unknown FACTs about rights and money could turn out.

    An OFFER with no stated price quotes one amount for all its places: nothing, or five in
    dollars, in euros, or in a currency that no BUDGET holds. A PERSON whom no BUDGET lists
    has one that can pay, or has none.
    """
    quotes = [Money(Decimal(0), "USD"), Money(Decimal(5), "USD"), Money(Decimal(5), "EUR")]
    quotes.append(Money(Decimal(5), "nowhere"))
    offers = [fact for fact in file.facts if isinstance(fact, Offer)]
    unpriced = [each for each in offers if each.price is None]
    unlisted = [person.id for person in file.persons if not file.listed(person.id)]
    worlds: list[World] = []
    for world in every_world_of_rights(file):
        for quoted in product(quotes, repeat=len(unpriced)):
            for funded in product([False, True], repeat=len(unlisted)):
                has_money = {person for person, yes in zip(unlisted, funded, strict=True) if yes}
                price = dict(zip((each.id for each in unpriced), quoted, strict=True))
                payable = {
                    (each.id, person.id)
                    for each in offers
                    for person in file.persons
                    if not (each.price or price[each.id]).amount
                    or file.pays(person.id, each.price or price[each.id]) is not None
                    or person.id in has_money
                }
                worlds.append(replace(world, payable=frozenset(payable)))
    return worlds


def test_the_three_answers_hold_for_every_way_money_could_turn_out() -> None:
    """FEASIBLE: one choice works in every world. INFEASIBLE: no choice works in any."""
    rng = Random(8080)
    seen: set[Answer] = set()
    kinds: set[str] = set()
    for _ in range(120):
        file = two_tours_with_money(rng)
        worlds = every_world_of_money(file)
        found = checked(file)
        seen.add(found.answer)
        assert (found.answer is Answer.FEASIBLE) == works_on_the_grid(file, worlds)
        somewhere = any(works_on_the_grid(file, [world]) for world in worlds)
        assert (found.answer is Answer.INFEASIBLE) == (not somewhere)
        if found.answer is Answer.INFEASIBLE:
            assert has_no_record_to_spare(file, found.conflict)
        for enough in asked(found):
            kinds.update(unknown.what for unknown in enough)
            assert works_on_the_grid(file, [with_these_at_best(file, enough)])
            for left_out in enough:
                fewer = [unknown for unknown in enough if unknown != left_out]
                assert not works_on_the_grid(file, [with_these_at_best(file, fewer)])
    assert seen == set(Answer)
    assert {"price", "funding", "another right"} <= kinds


def test_what_a_report_says_about_each_purchase_follows_the_rules_on_random_trips() -> None:
    """The place is one the PERSON can pay for, and the first BUDGET that can pay is named."""
    rng = Random(9090)
    bought = paid_from_a_budget = 0
    for _ in range(300):
        file = two_tours_with_money(rng)
        found = compiler.check(file)
        if found.answer is not Answer.FEASIBLE:
            continue
        offers = {fact.id: fact for fact in file.facts if isinstance(fact, Offer)}
        for cover in found.rights:
            if not cover.to_buy:
                continue
            bought += 1
            assert cover.price is not None and cover.price == offers[cover.by].price
            payer = file.pays(cover.person, cover.price)
            assert cover.budget == (None if payer is None else payer.id)
            assert payer is not None or not cover.price.amount
            paid_from_a_budget += payer is not None
        for each in offers.values():
            assert sum(cover.by == each.id for cover in found.rights) <= each.places
    assert bought > 40
    assert paid_from_a_budget > 20
