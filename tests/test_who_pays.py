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
    any_works,
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
PAID_FROM = (
    "A place with a price above nothing is paid from a BUDGET that lists the PERSON who takes it"
    " and holds the currency of the price."
)
ONE_WAY = f"Who buys which place is from one plan that works in that case. {PAID_FROM}"


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
    two = a_boat_tour(budgets=[budget("first", "alex"), budget("second", "jo", holds=["EUR"])])
    assert two.listed("jo") and not two.listed("sam")


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


def test_those_left_with_no_place_have_no_right_and_the_others_cannot_pay() -> None:
    """One place in euros, and Sam and Jo hold dollars. Sam has the place, and cannot pay."""
    file = a_boat_tour(offer("tour", 1, price="9.00 EUR"), locked=())
    assert broken(file, worst_case(file), on_the_tour("alex", "sam", "jo")) == [
        Broken(Constraint.RIGHT, "tour", ("jo",)),
        Broken(Constraint.PAID, "tour", ("sam",)),
    ]


def test_the_only_person_who_can_pay_for_the_only_place_is_not_the_one_left_out() -> None:
    """Alex comes first and holds euros. Sam holds dollars, and the one place is in dollars."""
    pots = [budget("euros", "alex", holds=["EUR"]), budget("dollars", "sam")]
    facts = [*at_ten("tour"), needs_right("tour"), offer("tour", 1)]
    options = [stays("tour", "dock")]
    locked = [lock("tour", "alex", "sam")]
    file = trip(["alex", "sam"], ["dock"], options, facts, locked, tickets=True, budgets=pots)
    worst = worst_case(file)
    assert placed(file, worst, "tour", ["alex", "sam"]) == {"sam": "tour-offer"}
    no_right = [Broken(Constraint.RIGHT, "tour", ("alex",))]
    assert broken(file, worst, on_the_tour("alex", "sam")) == no_right
    assert asked(checked(file)) == [[right("tour", "alex")]]


def some_places(*places: int) -> File:
    """A tour for four PERSONs with an OFFER of so many places for each number given.

    The OFFERs are called o0, o1 and so on. A test says who can pay for which.
    """
    offers = [offer("tour", count, id=f"o{number}") for number, count in enumerate(places)]
    facts = [*at_ten("tour"), needs_right("tour"), *offers]
    persons = ["p0", "p1", "p2", "p3"]
    return trip(persons, ["dock"], [stays("tour", "dock")], facts, [], tickets=True)


def by_trying_every_way(
    file: File, persons: Sequence[str], payable: frozenset[tuple[str, str]]
) -> dict[str, str]:
    """Who takes which place, by the rule in words and with no shortcut.

    Of every way to give places out, the one that leaves out nobody it could seat, going
    through the PERSONs in order. Among those, the one with the OFFERs listed first.
    """
    offers = file.offers("tour")
    order = {each.id: number for number, each in enumerate(offers)}
    choices = [
        [None, *(each.id for each in offers if (each.id, who) in payable)] for who in persons
    ]
    ways = [
        picks
        for picks in product(*choices)
        if all(picks.count(each.id) <= each.places for each in offers)
    ]

    def rank(picks: tuple[str | None, ...]) -> tuple[list[bool], list[int]]:
        return [each is None for each in picks], [order[each] for each in picks if each is not None]

    best = min(ways, key=rank)
    return {who: each for who, each in zip(persons, best, strict=True) if each is not None}


def test_places_are_shared_out_as_trying_every_way_would() -> None:
    rng = Random(3939)
    moved = 0
    for _ in range(600):
        file = some_places(*(rng.randrange(1, 3) for _ in range(rng.randrange(1, 4))))
        persons = [f"p{number}" for number in range(rng.randrange(1, 5))]
        often = rng.random()
        payable = frozenset(
            (each.id, who)
            for each in file.offers("tour")
            for who in persons
            if rng.random() < often
        )
        world = replace(worst_case(file), payable=payable)
        taken = placed(file, world, "tour", persons)
        assert taken == by_trying_every_way(file, persons, payable)
        assert list(taken) == [who for who in persons if who in taken]
        first = {
            who: next(each.id for each in file.offers("tour") if (each.id, who) in payable)
            for who in taken
        }
        moved += taken != first
    assert moved > 60


def test_a_person_who_has_settled_on_a_place_is_not_moved_for_a_later_one() -> None:
    """The first PERSON takes the first place. The second cannot have theirs as well."""
    file = some_places(1, 1, 1, 1)
    can_pay_for = {"p0": ["o0", "o1"], "p1": ["o2", "o3"], "p2": ["o0", "o2"]}
    payable = frozenset((each, who) for who, offers in can_pay_for.items() for each in offers)
    world = replace(worst_case(file), payable=payable)
    taken = placed(file, world, "tour", ["p0", "p1", "p2"])
    assert taken == {"p0": "o0", "p1": "o3", "p2": "o2"}


def a_chain(many: int) -> File:
    """Each PERSON can pay for their own place or the next one, and the last only for the first.

    So everybody has a place only when the last PERSON takes the first place, and everybody
    else moves along by one.
    """
    persons = [f"p{number}" for number in range(many)]
    offers = [offer("tour", 1, id=f"o{number}", price=f"1 C{number}") for number in range(many)]
    pots = [
        budget(f"b{number}", f"p{number}", holds=[f"C{number}", f"C{number + 1}"])
        for number in range(many - 1)
    ]
    pots.append(budget(f"b{many - 1}", f"p{many - 1}", holds=["C0"]))
    facts = [*at_ten("tour"), needs_right("tour"), *offers]
    options = [stays("tour", "dock")]
    locked = [lock("tour", *persons)]
    return trip(persons, ["dock"], options, facts, locked, tickets=True, budgets=pots)


def test_a_thousand_persons_who_each_have_to_move_along_all_get_a_place() -> None:
    file = a_chain(1000)
    persons = [person.id for person in file.persons]
    worst = worst_case(file)
    taken = placed(file, worst, "tour", persons)
    assert taken == {"p999": "o0", **{f"p{number}": f"o{number + 1}" for number in range(999)}}
    assert broken(file, worst, on_the_tour(*persons)) == []


def test_the_solver_seats_a_long_chain_as_the_reference_checker_does() -> None:
    file = a_chain(150)
    found = compiler.check(file)
    assert found.answer is Answer.FEASIBLE
    assert {cover.person: cover.by for cover in found.rights} == placed(
        file, worst_case(file), "tour", [person.id for person in file.persons]
    )


def test_a_place_that_none_of_them_can_pay_for_changes_nothing() -> None:
    """Forty places in dollars, and one in euros that nobody can pay for."""
    persons = [f"p{number}" for number in range(40)]
    facts = [*at_ten("tour"), needs_right("tour"), offer("tour", 40)]
    options = [stays("tour", "dock")]
    locked = [lock("tour", *persons)]
    plain = trip(persons, ["dock"], options, facts, locked, tickets=True)
    in_euros = offer("tour", 1, id="euro", price="1 EUR")
    more = trip(persons, ["dock"], options, [*facts, in_euros], locked, tickets=True)
    for file in (plain, more):
        taken = placed(file, worst_case(file), "tour", persons)
        assert taken == dict.fromkeys(persons, "tour-offer")
    assert compiler.check(more).rights == compiler.check(plain).rights
    too_few = [*facts[:-1], offer("tour", 39), in_euros]
    short = trip(persons, ["dock"], options, too_few, locked, tickets=True)
    assert len(placed(short, worst_case(short), "tour", persons)) == 39
    assert compiler.check(short).answer is Answer.UNDETERMINED


def test_a_person_who_can_pay_for_no_place_changes_nothing_for_the_others() -> None:
    """Forty buyers of forty places in dollars, and one more PERSON whom no BUDGET lists."""
    buyers = [f"p{number}" for number in range(40)]
    facts = [*at_ten("tour"), needs_right("tour"), offer("tour", 40)]
    options = [stays("tour", "dock")]
    locked = [lock("tour", *buyers)]
    pots = [budget("money", *buyers)]
    file = trip([*buyers, "idle"], ["dock"], options, facts, locked, tickets=True, budgets=pots)
    worst = worst_case(file)
    assert placed(file, worst, "tour", [*buyers, "idle"]) == dict.fromkeys(buyers, "tour-offer")
    found = compiler.check(file)
    assert found.answer is Answer.FEASIBLE and len(found.rights) == 40
    # The places are alike for the forty, so the solver counts them and chooses none.
    model = compiler._Search(file, worst).model  # pyright: ignore[reportPrivateUsage]
    assert "takes a place of" not in str(model.proto)
    chosen = compiler._Search(a_chain(3), worst_case(a_chain(3))).model  # pyright: ignore[reportPrivateUsage]
    assert "takes a place of" in str(chosen.proto)


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
    to_buy = "each place that sam has to buy can be paid from a BUDGET that lists sam"
    assert in_words(file)[-5:] == [
        "The trip works in any of these cases:",
        "  1. A right to tour is found for sam, in addition to the 2 places on OFFER.",
        f"  2. E{to_buy[1:]} (one from tour-offer for 10.00 USD).",
        "",
        f"{ONE_WAY} This FILE names no BUDGET.",
    ]
    as_json = report.as_json(file, found)
    ten_dollars = {"amount": "10.00", "currency": "USD"}
    place = {"person": "sam", "option": "tour", "offer": "tour-offer", "price": ten_dollars}
    assert as_json["missing"] == [
        [{"what": "another right", "option": "tour", "person": "sam", "at_most": None}],
        [{"what": "funding", "person": "sam", "buys": [place], "at_most": None}],
    ]
    assert as_json["budgets"] == []


def test_a_report_that_asks_who_pays_says_what_there_is_to_pay() -> None:
    """One place that Sam has to take, in euros or in pounds. The two reports differ."""
    for price in ("1 EUR", "1 GBP"):
        file = a_boat_tour(offer("tour", 1, price=price), every_right("tour", "tour-offer"))
        nobody_said = replace(file, budgets=())
        found = checked(nobody_said)
        assert asked(found) == [[can_pay("sam")]]
        assert in_words(nobody_said)[2].endswith(f"(one from tour-offer for {price}).")
        amount, currency = price.split()
        assert found.missing[0][0].buys == (
            Cover("tour", "sam", "tour-offer", True, Money(Decimal(amount), currency)),
        )
        in_euros = a_boat_tour(
            offer("tour", 1, price=price),
            every_right("tour", "tour-offer"),
            budgets=[budget("euros", "sam", holds=["EUR"])],
        )
        euros = price.endswith("EUR")
        assert checked(in_euros).answer is (Answer.FEASIBLE if euros else Answer.INFEASIBLE)


def test_a_missing_price_names_the_person_whose_budget_it_has_to_fit() -> None:
    """One place with no stated price. Alex holds euros and francs, Sam pounds and dollars."""
    pots = [
        budget("alexs", "alex", holds=["EUR", "CHF"]),
        budget("sams", "sam", holds=["GBP", "CAD"]),
    ]
    facts = [*at_ten("tour"), needs_right("tour"), offer("tour", 1, price=None)]
    facts.append(every_right("tour", "tour-offer"))
    options = [stays("tour", "dock")]
    for who in ("alex", "sam"):
        locked = [lock("tour", who)]
        file = trip(["alex", "sam"], ["dock"], options, facts, locked, tickets=True, budgets=pots)
        for found in (checked(file), compiler.check(file)):
            assert asked(found) == [[price_of("tour-offer")]]
            assert found.missing[0][0].buys == (Cover("tour", who, "tour-offer", True),)
        assert in_words(file)[2:] == [
            f"The trip works if a place from tour-offer has a price that {who} can pay.",
            "",
            f"{ONE_WAY} The BUDGETs of this FILE:",
            "  alexs: for alex; it holds EUR and CHF",
            "  sams: for sam; it holds GBP and CAD",
        ]
    both = [lock("tour", "alex", "sam")]
    two_places = [*facts[:-2], offer("tour", 2, price=None), facts[-1]]
    file = trip(["alex", "sam"], ["dock"], options, two_places, both, tickets=True, budgets=pots)
    assert in_words(file)[2] == (
        "The trip works if a place from tour-offer has a price that alex and sam can each pay."
    )


def test_a_price_is_about_the_persons_who_take_a_place_of_its_offer() -> None:
    """Sam and Jo both need a place. Who takes the one with no stated price depends."""
    one_place = a_boat_tour(offer("tour", 1, price=None), locked=EVERYONE)
    found = checked(one_place)
    assert asked(found) == [
        [right("tour", "sam"), right("tour", "jo")],
        [right("tour", "sam"), price_of("tour-offer")],
        [right("tour", "jo"), price_of("tour-offer")],
    ]
    # Whoever a right is found for buys no place, so the other one takes it.
    assert [enough[1].buys[0].person for enough in found.missing[1:]] == ["jo", "sam"]
    assert in_words(one_place)[4] == (
        "  2. A right to tour is found for sam, in addition to the 1 place on OFFER and a place"
        " from tour-offer has a price that jo can pay."
    )
    offers = [offer("tour", 1, id="priced"), offer("tour", 1, id="unpriced", price=None)]
    two_offers = a_boat_tour(*offers, every_right("tour", "priced", "unpriced"), locked=EVERYONE)
    found = checked(two_offers)
    assert asked(found) == [[price_of("unpriced")]]
    assert found.missing[0][0].buys == (Cover("tour", "jo", "unpriced", True),)


def test_a_missing_payer_is_told_only_what_is_left_to_buy() -> None:
    """Sam has to make two visits, one in dollars and one in euros. One of them is booked."""
    options = [stays("tour", "dock"), stays("cruise", "dock")]
    facts = [*at_ten("tour"), starts_at("cruise", 12), lasts("cruise", "PT1H")]
    facts += [cutoff("cruise", "PT0S"), needs_right("tour"), needs_right("cruise")]
    facts += [offer("tour", 1, price="1 USD"), offer("cruise", 1, price="1 EUR")]
    facts += [every_right("tour", "tour-offer"), every_right("cruise", "cruise-offer")]
    locked = [lock("tour", "sam"), lock("cruise", "sam")]
    left = {"tour": "one from cruise-offer for 1 EUR", "cruise": "one from tour-offer for 1 USD"}
    for booked, to_buy in left.items():
        stated = [*facts, booking(booked, "sam")]
        file = trip(["sam"], ["dock"], options, stated, locked, tickets=True, budgets=[])
        assert asked(checked(file)) == [[can_pay("sam")]]
        assert in_words(file)[2].endswith(f"a BUDGET that lists sam ({to_buy}).")
    neither = trip(["sam"], ["dock"], options, facts, locked, tickets=True, budgets=[])
    assert in_words(neither)[2].endswith(
        "(one from tour-offer for 1 USD, one from cruise-offer for 1 EUR)."
    )
    free = [
        offer("tour", 1, price="0 USD") if fact["id"] == "tour-offer" else fact for fact in facts
    ]
    one_free = trip(["sam"], ["dock"], options, free, locked, tickets=True, budgets=[])
    assert in_words(one_free)[2].endswith(
        "a BUDGET that lists sam (one from cruise-offer for 1 EUR)."
    )
    two_pots = [budget("dollars", "sam"), budget("euros", "sam", holds=["EUR"])]
    paid = trip(["sam"], ["dock"], options, facts, locked, tickets=True, budgets=two_pots)
    assert [cover.budget for cover in checked(paid).rights] == ["dollars", "euros"]


def test_who_buys_which_place_follows_the_places_that_are_left() -> None:
    """Alex holds euros, Jo holds pounds, and no BUDGET lists Sam. All three need a place."""
    pots = [budget("alexs", "alex", holds=["EUR"]), budget("jos", "jo", holds=["GBP"])]
    options = [stays("tour", "dock")]
    locked = [lock("tour", *EVERYONE)]
    for euros, pounds, sams in ((2, 1, "one from eur for 1 EUR"), (1, 2, "one from gbp for 1 GBP")):
        offers = [offer("tour", euros, id="eur", price="1 EUR")]
        offers.append(offer("tour", pounds, id="gbp", price="1 GBP"))
        facts = [*at_ten("tour"), needs_right("tour"), *offers, every_right("tour", "eur", "gbp")]
        file = trip(EVERYONE, ["dock"], options, facts, locked, tickets=True, budgets=pots)
        for found in (checked(file), compiler.check(file)):
            assert asked(found) == [[can_pay("sam")]]
        assert in_words(file)[2].endswith(f"a BUDGET that lists sam ({sams}).")


def test_a_budget_that_turns_out_to_pay_pays_for_a_place_with_no_stated_price() -> None:
    """Sam has to make two visits. Each has one place, and nobody knows either price."""
    options = [stays("tour", "dock"), stays("cruise", "dock")]
    facts = [*at_ten("tour"), starts_at("cruise", 12), lasts("cruise", "PT1H")]
    facts += [cutoff("cruise", "PT0S"), needs_right("tour"), needs_right("cruise")]
    facts += [offer("tour", 1, price=None), offer("cruise", 1, price=None)]
    facts += [every_right("tour", "tour-offer"), every_right("cruise", "cruise-offer")]
    locked = [lock("tour", "sam"), lock("cruise", "sam")]
    file = trip(["sam"], ["dock"], options, facts, locked, tickets=True, budgets=[])
    assert with_these_at_best(file, [can_pay("sam")]).payable == {
        ("tour-offer", "sam"),
        ("cruise-offer", "sam"),
    }
    for found in (checked(file), compiler.check(file)):
        assert asked(found) == [[can_pay("sam")]]
    unknown = "at a price nobody knows"
    assert in_words(file)[2].endswith(
        f"(one from tour-offer {unknown}, one from cruise-offer {unknown})."
    )
    one_visit = a_boat_tour(
        offer("tour", 1, price=None), every_right("tour", "tour-offer"), budgets=[]
    )
    assert asked(checked(one_visit)) == [[price_of("tour-offer")], [can_pay("sam")]]


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


def test_a_conflict_that_turns_on_who_can_pay_says_so_and_shows_the_budgets() -> None:
    """The four records rule out every plan only because Sam's BUDGET holds no euros."""
    facts = [*at_ten("tour"), needs_right("tour"), offer("tour", 1, price="1 EUR")]
    facts.append(every_right("tour", "tour-offer"))
    options = [stays("tour", "dock")]
    locked = [lock("tour", "sam")]

    def with_budgets(*pots: Document) -> File:
        return trip(["sam"], ["dock"], options, facts, locked, tickets=True, budgets=pots)

    file = with_budgets(budget("pot", "sam"))
    for found in (checked(file), compiler.check(file)):
        assert found.conflict == (
            "tour-needs-right",
            "tour-offer",
            "every-right-to-tour",
            "lock-tour",
        )
        assert found.given_budgets
    words = in_words(file)
    assert words[2].startswith(
        "These FACTs and DECISIONs rule out every plan, given the BUDGETs of this FILE. Take"
    )
    assert words[-3:] == [
        "",
        f"{PAID_FROM} The BUDGETs of this FILE:",
        "  pot: for sam; it holds USD",
    ]
    as_json = report.as_json(file, checked(file))
    assert as_json["budgets"] == [{"id": "pot", "persons": ["sam"], "currencies": ["USD"]}]
    assert checked(with_budgets(budget("pot", "sam", holds=["EUR"]))).answer is Answer.FEASIBLE
    assert asked(checked(with_budgets())) == [[can_pay("sam")]]


def test_a_conflict_that_no_budget_bears_on_shows_none() -> None:
    """One place in dollars for Sam and Jo. Both can pay, and there are too few places."""
    file = a_boat_tour(offer("tour", 1), every_right("tour", "tour-offer"), locked=EVERYONE)
    found = checked(file)
    assert found.answer is Answer.INFEASIBLE and "tour-offer" in found.conflict
    assert not found.given_budgets
    assert "budgets" not in report.as_json(file, found)
    words = in_words(file)
    assert words[2].startswith("These FACTs and DECISIONs rule out every plan by themselves.")
    assert not any("BUDGET" in line for line in words)
    # Somebody who takes no part and cannot pay changes nothing: there are still too few places.
    pots = [budget("dollars", "alex", "sam"), budget("jos", "jo", holds=["EUR"])]
    with_an_onlooker = a_boat_tour(
        offer("tour", 1),
        every_right("tour", "tour-offer"),
        booking("tour", "jo", id="jos-booking"),
        locked=("alex", "sam", "jo"),
        budgets=pots,
    )
    for found in (checked(with_an_onlooker), compiler.check(with_an_onlooker)):
        assert found.answer is Answer.FEASIBLE
    two_buyers = trip(
        EVERYONE,
        ["dock"],
        [stays("tour", "dock")],
        [*at_ten("tour"), needs_right("tour"), offer("tour", 1), every_right("tour", "tour-offer")],
        [lock("tour", "alex", "sam")],
        tickets=True,
        budgets=pots,
    )
    for found in (checked(two_buyers), compiler.check(two_buyers)):
        assert found.answer is Answer.INFEASIBLE and not found.given_budgets


def test_a_set_names_those_who_cannot_all_have_a_place_they_can_pay_for() -> None:
    """Alex and Sam hold euros, and Jo holds pounds. One place is in euros and one in pounds."""
    pots = [budget("euros", "alex", "sam", holds=["EUR"]), budget("pounds", "jo", holds=["GBP"])]
    offers = [offer("tour", 1, id="eur", price="1 EUR"), offer("tour", 1, id="gbp", price="1 GBP")]
    facts = [*at_ten("tour"), needs_right("tour"), *offers]
    options = [stays("tour", "dock")]
    locked = [lock("tour", *EVERYONE)]
    file = trip(EVERYONE, ["dock"], options, facts, locked, tickets=True, budgets=pots)
    for found in (checked(file), compiler.check(file)):
        assert asked(found) == [[right("tour", "alex")], [right("tour", "sam")]]
    assert "budgets" not in report.as_json(file, checked(file))


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
        "  2. A place from tour-offer has a price that sam can pay.",
        "",
        f"{ONE_WAY} The BUDGETs of this FILE:",
        "  money: for alex, sam and jo; it holds USD",
    ]
    as_json = report.as_json(file, found)
    missing = as_json["missing"]
    assert isinstance(missing, list)
    place = {"person": "sam", "option": "tour", "offer": "tour-offer", "price": None}
    assert missing[1] == [
        {"what": "price", "option": "tour", "offer": "tour-offer", "buys": [place], "at_most": None}
    ]
    everybody = {"id": "money", "persons": EVERYONE, "currencies": ["USD"]}
    assert as_json["budgets"] == [everybody]


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
    assert price_of("tour-offer") not in unknowns(a_boat_tour(offer("tour", 2)))


def test_nothing_about_money_is_unknown_where_nobody_has_to_pay() -> None:
    """A place of an OPTION that needs no right, a place that costs nothing, and a BOOKING."""
    options = [stays("tour", "dock")]
    timed = at_ten("tour")
    unpriced = offer("tour", 1, price=None)
    needs_none = trip(["sam"], ["dock"], options, [*timed, unpriced], [], budgets=[])
    assert unknowns(needs_none) == ()
    might = trip(["sam"], ["dock"], options, [*timed, unpriced], [], tickets=True, budgets=[])
    assert [unknown.what for unknown in unknowns(might)] == ["needs no right", "price", "funding"]
    free = [*timed, needs_right("tour"), offer("tour", 1, price="0 USD")]
    costs_nothing = trip(["sam"], ["dock"], options, free, [], tickets=True, budgets=[])
    assert [unknown.what for unknown in unknowns(costs_nothing)] == ["another right"]
    booked = [*timed, needs_right("tour"), unpriced, booking("tour", "sam")]
    has_a_right = trip(["sam"], ["dock"], options, booked, [], tickets=True, budgets=[])
    assert unknowns(has_a_right) == ()
    only_jo = trip(["sam", "jo"], ["dock"], options, booked, [], tickets=True, budgets=[])
    assert unknowns(only_jo) == (right("tour", "jo"), price_of("tour-offer"), can_pay("jo"))


@pytest.mark.parametrize("booked", [False, True])
def test_offers_that_nobody_can_need_cost_the_search_nothing(booked: bool) -> None:
    """Three visits with no stated length. One has sixteen OFFERs that nobody can need.

    The visits need no right, or they need one and Sam has a BOOKING for each. The last visit
    can take any length of time, so the report asks about the first two.
    """
    names = ["tour", "cruise", "walk"]
    options = [stays(name, "dock") for name in names]
    facts = [starts_at(name, 10 + 2 * number) for number, name in enumerate(names)]
    facts += [cutoff(name, "PT0S") for name in names]
    if booked:
        facts += [fact for name in names for fact in (needs_right(name), booking(name, "sam"))]
    locked = [lock(name, "sam") for name in names]
    unpriced = [offer("tour", 1, id=f"offer-{number}", price=None) for number in range(16)]
    calls: list[int] = []

    def counted(file: File, world: World) -> bool:
        calls.append(1)
        return any_works(file, world)

    counts: list[int] = []
    for more in ([], unpriced):
        calls.clear()
        file = trip(["sam"], ["dock"], options, [*facts, *more], locked, tickets=booked)
        found = answers.check(file, works=counted)
        assert [unknown.what for unknown in asked(found)[0]] == ["duration"] * 2
        counts.append(len(calls))
    assert counts[0] == counts[1]


def test_a_budget_holds_at_least_one_currency_and_can_list_nobody() -> None:
    assert "should be non-empty" in problems(budgets=[budget("pot", "sam", holds=[])])
    nobodys = a_boat_tour(offer("tour", 2), budgets=[budget("pot")])
    assert not nobodys.listed("sam")
    assert asked(checked(nobodys)) == [[right("tour", "sam")], [can_pay("sam")]]


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


def test_what_a_report_asks_about_money_is_enough_once_the_file_states_it() -> None:
    """A set of one FACT about money names who buys what. The FILE then states just that.

    For a missing payer, it gets a BUDGET that lists the PERSON and holds the currencies of
    the places named. For a missing price, the OFFER gets a price in a currency that every
    PERSON named can pay. Either way the TRIP becomes FEASIBLE.
    """
    rng = Random(4141)
    payers = prices = 0
    for _ in range(400):
        file = two_tours_with_money(rng)
        found = compiler.check(file)
        for enough in found.missing:
            needed = enough[0]
            if len(enough) > 1 or needed.unknown.what not in ("price", "funding"):
                continue
            assert needed.buys
            if needed.unknown.what == "funding":
                stated = [cover.price for cover in needed.buys if cover.price is not None]
                if len(stated) < len(needed.buys):
                    continue
                who = needed.unknown.person or ""
                held = tuple(dict.fromkeys(price.currency for price in stated))
                pots = (*file.budgets, Budget("found", "found", (who,), held))
                assert checked(replace(file, budgets=pots)).answer is Answer.FEASIBLE
                payers += 1
            else:
                buyers = [cover.person for cover in needed.buys]
                shared = [
                    currency
                    for currency in ("USD", "EUR")
                    if all(file.pays(who, Money(Decimal(1), currency)) for who in buyers)
                ]
                if not shared:
                    continue
                priced = tuple(
                    replace(fact, price=Money(Decimal(1), shared[0]))
                    if isinstance(fact, Offer) and fact.id == needed.unknown.about
                    else fact
                    for fact in file.facts
                )
                assert checked(replace(file, facts=priced)).answer is Answer.FEASIBLE
                prices += 1
    assert payers > 10
    assert prices > 10


def test_a_conflict_that_does_not_turn_on_the_budgets_holds_without_them() -> None:
    rng = Random(4242)
    either: set[bool] = set()
    for _ in range(300):
        file = two_tours_with_money(rng)
        found = compiler.check(file)
        if found.answer is not Answer.INFEASIBLE:
            continue
        assert found == checked(file)
        either.add(found.given_budgets)
        if not found.given_budgets:
            assert checked(replace(file, budgets=())).answer is Answer.INFEASIBLE
    assert either == {False, True}


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
