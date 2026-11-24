"""An OFFER for an OBJECT: a place that a right for an OBJECT can still be bought from.

An OFFER can name the OBJECTs it is for. Then each of its places is one right that covers any
one of those OBJECTs, and no PERSON takes it. A BUDGET lists the OBJECTs whose places it may
pay for. A car ferry still sells three places on the car deck, and the trip money pays for
the hire car.
"""

from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal
from itertools import product
from random import Random
from typing import Any, cast

import pytest

from agloe import answers, compiler, reference, report
from agloe.answers import Answer, Cover
from agloe.file import (
    Booking,
    Budget,
    Cap,
    CompleteNeedsRightFor,
    CompleteRightsFor,
    Fact,
    File,
    FileError,
    Money,
    NeedsRight,
    NeedsRightFor,
    Offer,
    Payment,
)
from agloe.reference import (
    Broken,
    Constraint,
    Itinerary,
    Remaining,
    Step,
    Unknown,
    Where,
    best_case,
    best_case_left,
    broken_as_listed,
    goes_along,
    itineraries,
    taken_together,
    taking_a_place,
    unknowns,
    way_to_pay,
    with_no_offer,
    with_these_at_best,
    worst_case,
)
from tests.stories import (
    Document,
    booking,
    budget,
    cap,
    carries,
    cutoff,
    does_with,
    every_right,
    every_right_for,
    every_transfer,
    every_use,
    hands_over,
    has_object,
    keeps,
    lasts,
    lasts_between,
    lies_at,
    lock,
    moves,
    needs_no_right,
    needs_right,
    needs_right_for,
    no_other_right_for,
    offer,
    requires_object,
    seconds,
    starts_at,
    starts_from,
    stays,
    trip,
)
from tests.test_object_rights import checked, without
from tests.test_objects import (
    NEW,
    EveryOrder,
    a_trip_with_objects,
    a_trip_with_services,
    as_visits,
    asked,
    at,
    every_chain,
    smallest_sets,
    worlds_to_try,
)
from tests.test_where_a_path_ends import has_no_record_to_spare

NINETY = Money(Decimal("90.00"), "USD")


def a_crossing(
    *facts: Document,
    budgets: Sequence[Document] | None = None,
    rights: bool = False,
    bike: bool = False,
    caps: Sequence[Document] = (),
    bag: bool = False,
) -> File:
    """Alex and Sam take the car ferry from Milwaukee to Muskegon at 6:00 am, and a LOCK says so.

    Alex has the hire car and Sam has the bike when the TRIP starts. The ferry needs a right
    for the car. With ``bike``, it needs one for the bike too, and otherwise it needs none.
    With ``bag``, Sam has a bag too, and the ferry needs a right for it.
    The FILE says nothing else about rights for the OBJECTs but what ``facts`` says. Nobody
    needs a right to take part, unless ``rights`` leaves that to ``facts`` too. Without
    ``budgets``, one BUDGET called money pays for Alex and Sam, in USD, and it lists no
    OBJECT. ``caps`` are the caps on the BUDGETs.
    """
    stated = [
        *at("ferry", 6, 0, "PT2H30M"),
        starts_from("alex", "milwaukee"),
        starts_from("sam", "milwaukee"),
        has_object("alex", "car"),
        has_object("sam", "bike"),
        *(each(thing) for thing in ("car", "bike") for each in (every_use, every_transfer)),
        needs_right_for("ferry", "car"),
        needs_right_for("ferry", "bike", bike),
        *facts,
    ]
    if bag:
        stated += [has_object("sam", "bag"), every_use("bag"), every_transfer("bag")]
        stated.append(needs_right_for("ferry", "bag"))
    return trip(
        ["alex", "sam"],
        ["milwaukee", "muskegon"],
        [moves("ferry", "milwaukee", "muskegon")],
        stated,
        [lock("ferry", "alex", "sam"), *caps],
        rights=rights,
        budgets=budgets,
        objects=["car", "bike", *(["bag"] if bag else [])],
        object_rights=True,
    )


def car_deck(places: int = 3, price: str | None = "90.00 USD") -> Document:
    """An OFFER of places on the car deck of the ferry, for the hire car."""
    return offer("ferry", places, "car-deck", price, objects=["car"])


def problems(*facts: Document, budgets: Sequence[Document] | None = None) -> str:
    with pytest.raises(FileError) as refused:
        a_crossing(*facts, budgets=budgets, rights=True, bike=True)
    return str(refused.value)


# ------------------------------- What a FILE holds -------------------------------


def test_an_offer_names_the_objects_it_is_for() -> None:
    rack = offer("ferry", 2, "rack", "5.00 USD", objects=["bike", "car"])
    file = a_crossing(car_deck(), rack, offer("ferry", 20, "seats"), rights=True)
    deck = Offer("car-deck", "ferry", 3, NINETY, ("car",))
    racks = Offer("rack", "ferry", 2, Money(Decimal("5.00"), "USD"), ("bike", "car"))
    assert file.offers_for("ferry", "car") == (deck, racks)
    assert file.offers_for("ferry", "bike") == (racks,)
    assert file.offers_for_objects("ferry") == (deck, racks)
    assert file.offers_for("drive", "car") == ()


def test_an_offer_for_objects_has_no_place_for_a_person() -> None:
    """The OFFERs of an OPTION are those for a PERSON to take part: a place on the car deck is
    none. An OFFER that names no OBJECT has no place for an OBJECT."""
    file = a_crossing(car_deck(), offer("ferry", 20, "seats"), rights=True)
    assert [each.id for each in file.offers("ferry")] == ["seats"]
    assert file.places_on_offer("ferry") == 20
    only_the_deck = a_crossing(car_deck())
    assert only_the_deck.offers("ferry") == ()
    assert only_the_deck.places_on_offer("ferry") == 0
    assert file.offers_for("ferry", "bike") == ()


def test_a_budget_lists_the_objects_whose_places_it_may_pay_for() -> None:
    trip_money = budget("trip-money", "alex", "sam", objects=["car"])
    file = a_crossing(budgets=[trip_money])
    assert file.budgets == (
        Budget("trip-money", "trip-money", ("alex", "sam"), ("USD",), ("car",)),
    )
    assert file.listed("car") and not file.listed("bike")
    assert file.pays("car", NINETY) == file.budgets[0]
    assert file.pays("bike", NINETY) is None
    assert file.pays("car", Money(Decimal(90), "EUR")) is None
    assert file.pays("car", Money(Decimal("0.00"), "USD")) is None
    assert file.payers("car", "USD") == file.budgets
    assert file.payers("bike", "USD") == ()
    # Left out, a BUDGET pays for no OBJECT.
    assert a_crossing().budgets[0].objects == ()


def test_a_budget_can_list_objects_and_no_person() -> None:
    """A fund for the bikes pays for the bike whoever has it, and nobody draws on it."""
    pots = [budget("money", "alex", "sam"), budget("bike-fund", objects=["bike"], holds=["EUR"])]
    file = a_crossing(budgets=pots)
    assert file.budgets[1] == Budget("bike-fund", "bike-fund", (), ("EUR",), ("bike",))
    assert file.listed("bike")
    assert [each.id for each in file.payers("bike", "EUR")] == ["bike-fund"]
    assert file.payers("bike", "USD") == ()


def test_the_first_budget_listed_that_can_pay_for_an_object_is_the_one_that_pays() -> None:
    pots = [
        budget("euros", objects=["car"], holds=["EUR"]),
        budget("first", "alex", objects=["car"]),
        budget("second", "sam", objects=["car", "bike"]),
    ]
    file = a_crossing(budgets=pots)
    payer = file.pays("car", NINETY)
    assert payer is not None and payer.id == "first"
    assert [each.id for each in file.payers("car", "USD")] == ["first", "second"]


def test_a_complete_set_for_an_object_names_the_offers_that_name_it() -> None:
    whole = no_other_right_for("ferry", "car", "car-deck")
    file = a_crossing(car_deck(), whole)
    assert file.rights_complete_for("ferry", "car") == CompleteRightsFor(
        "every-right-to-ferry-for-car", "ferry", "car", ("car-deck",)
    )
    # A set that names no OFFER says that no OFFER names the OBJECT, written either way.
    for none in (no_other_right_for("ferry", "bike"), no_other_right_for("ferry", "bike", *())):
        assert a_crossing(car_deck(), none).rights_complete_for("ferry", "bike") is not None
    empty: Document = {
        "id": "full",
        "complete": {"rights_to": "ferry", "for_object": "bike", "offers": []},
    }
    closed = a_crossing(car_deck(), empty).rights_complete_for("ferry", "bike")
    assert closed == CompleteRightsFor("full", "ferry", "bike", ())


def test_two_complete_sets_can_name_one_offer() -> None:
    """One rack takes the bike or the car. The set for each of them names it."""
    rack = offer("ferry", 1, "rack", objects=["bike", "car"])
    sets = [no_other_right_for("ferry", thing, "rack") for thing in ("car", "bike")]
    file = a_crossing(rack, *sets)
    assert [file.rights_complete_for("ferry", thing) for thing in ("car", "bike")] == [
        CompleteRightsFor("every-right-to-ferry-for-car", "ferry", "car", ("rack",)),
        CompleteRightsFor("every-right-to-ferry-for-bike", "ferry", "bike", ("rack",)),
    ]


def test_a_complete_set_for_the_persons_says_nothing_of_an_offer_for_objects() -> None:
    """The set for the PERSONs names the OFFERs for PERSONs. A FILE can have an OFFER for an
    OBJECT beside it, and the set for an OBJECT can stand beside an OFFER for PERSONs."""
    people = [needs_right("ferry"), every_right("ferry", "seats"), offer("ferry", 20, "seats")]
    file = a_crossing(*people, car_deck(), no_other_right_for("ferry", "bike"), rights=True)
    found = file.rights_complete("ferry")
    assert found is not None and found.offers == ("seats",)
    assert [each.id for each in file.offers_for("ferry", "car")] == ["car-deck"]


NO_OBJECT: Document = {"id": "deck", "offer": {"option": "ferry", "places": 1, "for_objects": []}}
TWICE: Document = {
    "id": "deck",
    "offer": {"option": "ferry", "places": 1, "for_objects": ["car", "car"]},
}
NAMED_TWICE: Document = {
    "id": "full",
    "complete": {"rights_to": "ferry", "for_object": "car", "offers": ["car-deck", "car-deck"]},
}
RACK = offer("ferry", 1, "rack", objects=["bike"])
SEATS = offer("ferry", 20, "seats")


@pytest.mark.parametrize(
    ("facts", "problem"),
    [
        ([NO_OBJECT], "/facts/13: fits no known shape; the closest miss: [] should be non-empty"),
        ([TWICE], "['car', 'car'] has non-unique elements"),
        ([offer("ferry", 1, objects=["boat"])], "/facts/13: boat is not an OBJECT in this FILE"),
        ([offer("ferry", 1, objects=["alex"])], "/facts/13: alex is not an OBJECT in this FILE"),
        ([offer("tram", 1, objects=["car"])], "/facts/13: tram is not an OPTION in this FILE"),
        # A set for an OBJECT names exactly the OFFERs for its OPTION that name the OBJECT.
        (
            [car_deck(), no_other_right_for("ferry", "car")],
            "/facts/13: the rights to ferry for car are COMPLETE, and that FACT does not name"
            " this OFFER",
        ),
        (
            [no_other_right_for("ferry", "car", "car-deck")],
            "/facts/13: car-deck is not an OFFER for ferry",
        ),
        (
            [RACK, no_other_right_for("ferry", "car", "rack")],
            "/facts/14: rack is not an OFFER for car",
        ),
        (
            [SEATS, no_other_right_for("ferry", "car", "seats")],
            "/facts/14: seats is not an OFFER for car",
        ),
        ([car_deck(), NAMED_TWICE], "['car-deck', 'car-deck'] has non-unique elements"),
        # A set for the PERSONs names no OFFER for OBJECTs.
        (
            [car_deck(), every_right("ferry", "car-deck")],
            "/facts/14: car-deck is an OFFER for OBJECTs",
        ),
    ],
)
def test_the_format_refuses_an_offer_for_objects_that_cannot_be_meant(
    facts: list[Document], problem: str
) -> None:
    assert problem in problems(*facts)


def test_a_complete_set_names_only_offers_for_its_own_option() -> None:
    """A place in a car park is no place on the ferry, though both are for the car."""

    def a_stop(*facts: Document) -> File:
        stated = [*at("ferry", 6, 0, "PT2H30M"), *at("park", 9), *facts]
        options = [moves("ferry", "milwaukee", "muskegon"), moves("park", "muskegon", "holland")]
        places = ["milwaukee", "muskegon", "holland"]
        return trip(["alex"], places, options, stated, [], objects=["car"], object_rights=True)

    elsewhere = offer("park", 1, "car-park", objects=["car"])
    assert a_stop(elsewhere, no_other_right_for("ferry", "car")).offers_for("park", "car")
    with pytest.raises(FileError) as refused:
        a_stop(elsewhere, no_other_right_for("ferry", "car", "car-park"))
    assert "car-park is not an OFFER for ferry" in str(refused.value)


@pytest.mark.parametrize(
    ("pot", "problem"),
    [
        (budget("pot", "alex", objects=["boat"]), "/budgets/0: boat is not an OBJECT in this FILE"),
        (budget("pot", objects=["alex"]), "/budgets/0: alex is not an OBJECT in this FILE"),
        (budget("pot", "car"), "/budgets/0: car is not a PERSON in this FILE"),
        (budget("pot", "alex", objects=["car", "car"]), "['car', 'car'] has non-unique elements"),
    ],
)
def test_the_format_refuses_a_budget_whose_objects_cannot_be_meant(
    pot: Document, problem: str
) -> None:
    assert problem in problems(budgets=[pot])


# ------------------------------- The two cases -------------------------------

WHOLE = no_other_right_for("ferry", "car", "car-deck")
TRIP_MONEY = budget("trip-money", "alex", "sam", objects=["car"])
ON_THE_FERRY = ("ferry", "car")


def test_only_a_place_of_an_offer_covers_the_object() -> None:
    """The ferry needs a right for the car, no BOOKING covers the car, and the FILE lists
    every right for it: three places on the car deck. Then the car takes one of them where
    it needs the right, at worst and at best."""
    file = a_crossing(car_deck(), WHOLE, budgets=[TRIP_MONEY])
    for world in (worst_case(file), best_case(file)):
        assert world.offered == {ON_THE_FERRY} and not world.uncovered
        assert world.payable == {("car-deck", "car")}
    # Where the FILE does not say that it lists every right, another right can be found.
    open_set = a_crossing(car_deck(), budgets=[TRIP_MONEY])
    assert worst_case(open_set).offered == {ON_THE_FERRY}
    assert not best_case(open_set).offered and not best_case(open_set).uncovered
    # A BOOKING that covers the car leaves nothing to buy.
    booked = a_crossing(car_deck(), WHOLE, booking("ferry", "car"), budgets=[TRIP_MONEY])
    assert not worst_case(booked).offered and not worst_case(booked).uncovered
    # A rack for the bike gives the car nothing.
    rack = offer("ferry", 1, "rack", objects=["bike"])
    sold_out = a_crossing(rack, no_other_right_for("ferry", "car"))
    assert worst_case(sold_out).uncovered == {ON_THE_FERRY} and not worst_case(sold_out).offered
    # With every OFFER left out, nothing covers the car.
    bare = with_no_offer(worst_case(file))
    assert bare.uncovered == {ON_THE_FERRY} and not bare.offered and not bare.payable


def test_who_can_pay_for_a_place_that_covers_an_object() -> None:
    """A BUDGET that lists the car and holds the currency of the price can pay. Once a
    BUDGET lists the car, no other BUDGET pays for it. Where none lists it, nobody knows
    who pays: at best a BUDGET does, and at worst none."""

    def at_worst(file: File) -> bool:
        return ("car-deck", "car") in worst_case(file).payable

    def at_best(file: File) -> bool:
        return ("car-deck", "car") in best_case(file).payable

    funding = Unknown("funding", about="car")
    listed = a_crossing(car_deck(), budgets=[TRIP_MONEY])
    assert at_worst(listed) and at_best(listed) and funding not in unknowns(listed)
    # The BUDGET that lists the car holds no dollars. The money of Alex and Sam does not
    # pay for it then.
    euros = [budget("money", "alex", "sam"), budget("car-fund", objects=["car"], holds=["EUR"])]
    wrong = a_crossing(car_deck(), budgets=euros)
    assert not at_worst(wrong) and not at_best(wrong) and funding not in unknowns(wrong)
    unlisted = a_crossing(car_deck())
    assert not at_worst(unlisted) and at_best(unlisted) and funding in unknowns(unlisted)
    assert ("car-deck", "car") in with_these_at_best(unlisted, [funding]).payable
    # A place that costs nothing needs nobody to pay, and nothing is asked about money.
    free = a_crossing(car_deck(price="0.00 USD"))
    assert at_worst(free)
    assert not [each for each in unknowns(free) if each.what in ("price", "funding")]
    # A price that nobody knows: at worst no BUDGET of the car is sure to hold its currency.
    unpriced = a_crossing(car_deck(price=None), budgets=[TRIP_MONEY])
    price = Unknown("price", "ferry", about="car-deck")
    assert not at_worst(unpriced) and at_best(unpriced) and price in unknowns(unpriced)
    assert ("car-deck", "car") in with_these_at_best(unpriced, [price]).payable


def test_a_place_for_an_object_is_none_for_a_person() -> None:
    people = [needs_right("ferry"), offer("ferry", 20, "seats")]
    file = a_crossing(car_deck(), *people, budgets=[TRIP_MONEY], rights=True)
    pairs = {("car-deck", "car"), ("seats", "alex"), ("seats", "sam")}
    assert worst_case(file).payable == pairs
    assert worst_case(file).places == {"ferry": 20}


def test_nothing_about_money_is_asked_where_a_booking_covers_the_object() -> None:
    booked = a_crossing(car_deck(price=None), booking("ferry", "car"))
    assert not [each for each in unknowns(booked) if each.what in ("price", "funding")]
    # And nothing where a FACT says that the ferry needs no right for the bike.
    rack = offer("ferry", 1, "rack", None, objects=["bike"])
    assert not [each for each in unknowns(a_crossing(rack)) if each.what in ("price", "funding")]


# ------------------------------- The check of a plan -------------------------------


def a_train(
    *facts: Document,
    places: int = 1,
    budgets: Sequence[Document] | None = None,
    caps: Sequence[Document] = (),
    rights: bool = False,
) -> File:
    """A train from A to B at 9:00 am needs a right for the bike. A rack still has a place
    for the bike, for 10 dollars, and the money of Alex and Jo pays for the bike. Jo and
    Alex can take the train. Each story says where the bike starts. Nobody needs a right to
    take part, unless ``rights`` leaves that to the story too."""
    stated = [*at("train", 9), starts_from("alex", "a"), starts_from("jo", "a")]
    stated += [needs_right_for("train", "bike"), every_use("bike"), every_transfer("bike")]
    stated += [offer("train", places, "rack", objects=["bike"]), *facts]
    pots = [budget("money", "alex", "jo", objects=["bike"])] if budgets is None else budgets
    return trip(
        ["alex", "jo"],
        ["a", "b"],
        [moves("train", "a", "b")],
        stated,
        list(caps),
        rights=rights,
        budgets=pots,
        objects=["bike"],
        object_rights=True,
    )


def ride(
    *persons: str, handed: tuple[tuple[str, str], ...] = (), carried: tuple[str, ...] = ()
) -> Step:
    return Step(
        "train", "a", "b", persons, seconds(9), seconds(9, 30), handed=handed, carried=carried
    )


def on_the_train(file: File, *steps: Step) -> list[str]:
    """The OBJECTs that take a place on the train in a plan that works, at worst."""
    assert broken_as_listed(file, worst_case(file), steps) == []
    return list(taking_a_place(file, worst_case(file), steps).get("train", {}))


def test_the_object_takes_a_place_where_a_person_who_takes_part_has_it() -> None:
    file = a_train(has_object("alex", "bike"))
    assert on_the_train(file, ride("alex")) == ["bike"]
    assert on_the_train(file, ride("alex", "jo")) == ["bike"]
    # Jo does not have the bike, and Alex stays behind with it.
    assert on_the_train(file, ride("jo")) == []


def test_the_object_takes_a_place_where_it_is_handed_over() -> None:
    file = a_train(lies_at("bike", "a"), hands_over("train", "bike"))
    assert on_the_train(file, ride("alex", handed=(("bike", "alex"),))) == ["bike"]
    # A hand-over that nobody makes takes no place: the bike stays on the platform.
    assert on_the_train(file, ride("alex")) == []


def test_the_object_takes_a_place_where_it_is_carried() -> None:
    file = a_train(lies_at("bike", "a"), carries("train", "bike"))
    assert on_the_train(file, ride("alex", carried=("bike",))) == ["bike"]
    assert on_the_train(file, ride("alex")) == []
    # A train with nobody in it carries the bike on the same terms.
    assert on_the_train(file, ride(carried=("bike",))) == ["bike"]


def test_the_object_takes_a_place_where_it_goes_along_with_no_choice() -> None:
    facts = [lies_at("bike", "a"), carries("train", "bike"), requires_object("train", "bike")]
    assert on_the_train(a_train(*facts), ride("alex")) == ["bike"]


def test_the_grounds_for_a_right_take_one_place() -> None:
    """Jo has the bike and hands it to Alex in the train. A PERSON who takes part has it, and
    it is handed over: that is one requirement, and one place."""
    file = a_train(has_object("jo", "bike"), hands_over("train", "bike"))
    handed = ride("alex", "jo", handed=(("bike", "alex"),))
    assert on_the_train(file, handed) == ["bike"]
    paying = way_to_pay(file, worst_case(file), {"train": ("alex", "jo")}, {"train": ["bike"]})
    assert paying == {("train", "bike"): ("rack", "money")}


def crossing(*persons: str) -> Step:
    return Step("ferry", "milwaukee", "muskegon", persons, seconds(6), seconds(8, 30))


BOTH = (crossing("alex", "sam"),)
FOR_BOTH = budget("money", "alex", "sam", objects=["car", "bike"])


def test_an_object_with_no_place_left_has_no_right() -> None:
    """One rack takes the car or the bike, and both cross. The car is listed first, so it
    has the place, and the bike has no right: the sixteenth CONSTRAINT."""
    rack = offer("ferry", 1, "rack", objects=["car", "bike"])
    file = a_crossing(rack, budgets=[FOR_BOTH], bike=True)
    found = broken_as_listed(file, worst_case(file), BOTH)
    assert found == [Broken(Constraint.COVERED, "ferry", ("sam",), object="bike")]
    two = a_crossing(
        offer("ferry", 2, "rack", objects=["car", "bike"]), budgets=[FOR_BOTH], bike=True
    )
    assert broken_as_listed(two, worst_case(two), BOTH) == []
    assert taking_a_place(two, worst_case(two), BOTH) == {"ferry": {"car": True, "bike": True}}


def test_a_place_that_nobody_can_pay_for_is_not_paid_for() -> None:
    """No BUDGET lists the car. The car deck has a place, and at worst nobody pays for it:
    the eleventh CONSTRAINT. Where another OBJECT has the last place, the car has no right."""
    file = a_crossing(car_deck())
    found = broken_as_listed(file, worst_case(file), BOTH)
    assert found == [Broken(Constraint.PAID, "ferry", ("alex",), object="car")]
    # The bike can be paid for, and takes the one place. The car is left with none.
    rack = offer("ferry", 1, "rack", objects=["car", "bike"])
    for_the_bike = budget("money", "alex", "sam", objects=["bike"])
    full = a_crossing(rack, budgets=[for_the_bike], bike=True)
    found = broken_as_listed(full, worst_case(full), BOTH)
    assert found == [Broken(Constraint.COVERED, "ferry", ("alex",), object="car")]


def test_a_place_for_each_object_comes_before_who_pays() -> None:
    """A free rack takes the car or the bike, and a car deck at 10 dollars takes only the
    car. No BUDGET lists either. Each has a place, the bike on the rack and the car on the
    deck, and only the car's place is not paid for. A bag, and a free shelf for the bike or
    the bag, change nothing. Once a BUDGET lists the car, nothing is broken."""
    rack = offer("ferry", 1, "rack", "0.00 USD", objects=["car", "bike"])
    deck = car_deck(1, "10.00 USD")
    unpaid = [Broken(Constraint.PAID, "ferry", ("alex",), object="car")]
    file = a_crossing(rack, deck, bike=True)
    assert broken_as_listed(file, worst_case(file), BOTH) == unpaid
    shelf = offer("ferry", 1, "shelf", "0.00 USD", objects=["bike", "bag"])
    with_a_bag = a_crossing(rack, deck, shelf, bike=True, bag=True)
    assert broken_as_listed(with_a_bag, worst_case(with_a_bag), BOTH) == unpaid
    for_the_car = budget("money", "alex", "sam", objects=["car"])
    funded = a_crossing(rack, deck, budgets=[for_the_car], bike=True)
    world = worst_case(funded)
    assert broken_as_listed(funded, world, BOTH) == []
    paying = way_to_pay(funded, world, {"ferry": ("alex", "sam")}, {"ferry": ["car", "bike"]})
    assert paying == {("ferry", "car"): ("car-deck", "money"), ("ferry", "bike"): ("rack", None)}


def test_the_first_object_in_the_files_order_is_paid_for_first() -> None:
    """Three places take two OBJECTs each, and each has its own currency. The dollars pay
    for the car or the bike on the first, the euros pay for the bag on the second, and
    nobody holds pounds for the third. All three OBJECTs have a place only if each is on
    another one. The car comes first in the FILE, so it has the first place, and it is paid
    for. That leaves the second for the bike and the third for the bag, both unpaid."""
    places = [
        offer("ferry", 1, "first", "5.00 USD", objects=["car", "bike"]),
        offer("ferry", 1, "second", "5.00 EUR", objects=["bike", "bag"]),
        offer("ferry", 1, "third", "5.00 GBP", objects=["car", "bag"]),
    ]
    pots = [
        budget("dollars", "alex", "sam", objects=["car", "bike"]),
        budget("euros", objects=["bag"], holds=["EUR"]),
    ]
    file = a_crossing(*places, budgets=pots, bike=True, bag=True)
    assert broken_as_listed(file, worst_case(file), BOTH) == [
        Broken(Constraint.PAID, "ferry", ("sam",), object="bike"),
        Broken(Constraint.PAID, "ferry", ("sam",), object="bag"),
    ]


def test_a_cap_counts_what_the_persons_and_the_objects_buy_together() -> None:
    """Alex and Sam each buy a seat for 10 dollars, and the car takes a place for 90. The
    trip money pays for all three, and its cap counts them together."""
    people = [needs_right("ferry"), offer("ferry", 20, "seats")]

    def capped(most: str) -> File:
        limit = [cap("trip-money", f"{most} USD")]
        return a_crossing(car_deck(), *people, budgets=[TRIP_MONEY], rights=True, caps=limit)

    enough = capped("110.00")
    world = worst_case(enough)
    assert broken_as_listed(enough, world, BOTH) == []
    paying = way_to_pay(enough, world, {"ferry": ("alex", "sam")}, {"ferry": ["car"]})
    assert paying == {
        ("ferry", "alex"): ("seats", "trip-money"),
        ("ferry", "sam"): ("seats", "trip-money"),
        ("ferry", "car"): ("car-deck", "trip-money"),
    }
    short = capped("109.99")
    assert broken_as_listed(short, worst_case(short), BOTH) == [Broken(Constraint.CAP, None, ())]


@pytest.mark.parametrize("limit", [[], [cap("money", "500.00 USD")]])
def test_each_object_takes_the_first_offer_that_leaves_a_place_for_the_rest(
    limit: list[Document],
) -> None:
    """The first rack takes the car or the bike, and the second only the car. The car is
    listed first. It takes the second rack, so that the bike has the first: the fixed rule,
    with a cap in the FILE and with none."""
    racks = [
        offer("ferry", 1, "rack-a", objects=["car", "bike"]),
        offer("ferry", 1, "rack-b", objects=["car"]),
    ]
    file = a_crossing(*racks, budgets=[FOR_BOTH], bike=True, caps=limit)
    world = worst_case(file)
    assert broken_as_listed(file, world, BOTH) == []
    paying = way_to_pay(file, world, {"ferry": ("alex", "sam")}, {"ferry": ["car", "bike"]})
    assert paying == {
        ("ferry", "car"): ("rack-b", "money"),
        ("ferry", "bike"): ("rack-a", "money"),
    }


# ------------------------------- The search -------------------------------


def a_meeting(*facts: Document, caps: Sequence[Document] = ()) -> File:
    """Alex has the bike, and nothing requires it. Alex meets Jo at 8:00 am, where the bike
    can be handed over, and takes the train at 9:00 am. The train needs a right for the
    bike, and a rack has a place for it, for 10 dollars."""
    options = [stays("meet", "a"), moves("train", "a", "b")]
    stated = [*at("meet", 8), *at("train", 9), starts_from("alex", "a"), starts_from("jo", "a")]
    stated += [has_object("alex", "bike"), hands_over("meet", "bike"), every_use("bike")]
    stated += [every_transfer("bike"), needs_right_for("train", "bike"), every_right_for("bike")]
    stated += [offer("train", 1, "rack", objects=["bike"]), *facts]
    return trip(
        ["alex", "jo"],
        ["a", "b"],
        options,
        stated,
        [lock("meet", "alex", "jo"), lock("train", "alex"), *caps],
        budgets=[budget("money", "alex", "jo", objects=["bike"])],
        objects=["bike"],
        object_rights=True,
    )


def test_the_search_keeps_a_choice_that_takes_fewer_places() -> None:
    """The search keeps one choice of hand-overs for each place it can leave the OBJECT in,
    and at the end the choices that can still be the one shown. A hand-over more comes
    later by the rules. It is kept where it takes a place of an OFFER in fewer OPTIONs:
    whether the places can be paid for is not known there."""
    file = a_meeting()
    world = worst_case(file)
    with_alex, with_jo = frozenset({Where(person="alex")}), frozenset({Where(person="jo")})
    visits = as_visits([("meet", ("alex", "jo"), "a"), ("train", ("alex",), "a")])

    def rank(option: str, person: str | None) -> tuple[int, int]:
        return (["meet", "train"].index(option), ["alex", "jo"].index(person or "alex"))

    def reached(of: File) -> reference._Reached:  # pyright: ignore[reportPrivateUsage]
        return reference._first_hand_overs(  # pyright: ignore[reportPrivateUsage]
            worst_case(of), "bike", visits, [with_alex], rank, {}
        )

    def taken(where: str, *options: str) -> frozenset[tuple[Where, frozenset[frozenset[str]]]]:
        """The bike is with this PERSON, and has taken a place in these OPTIONs."""
        return frozenset({(Where(person=where), frozenset({frozenset(options)}))})

    assert world.offered == {("train", "bike")}
    assert reached(file) == {
        (with_alex, (), taken("alex", "train")): (),
        (with_jo, (), taken("jo")): ((0, 1),),
    }
    kept = reference._first_of(reached(file))  # pyright: ignore[reportPrivateUsage]
    assert kept == [((), ()), (((0, 1),), ())]
    # With a BOOKING that covers the bike, no place is taken. The hand-over comes later
    # and counts on no less, so it cannot be the choice shown.
    booked = a_meeting(booking("train", "bike"))
    nothing_kept = frozenset[object]()
    assert reached(booked) == {
        (with_alex, (), nothing_kept): (),
        (with_jo, (), nothing_kept): ((0, 1),),
    }
    assert reference._first_of(reached(booked)) == [((), ())]  # pyright: ignore[reportPrivateUsage]


def shown(file: File) -> list[tuple[str | None, tuple[str, ...], tuple[tuple[str, str], ...]]]:
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    return [(step.option, step.persons, step.handed) for step in found.itinerary]


def test_a_plan_takes_no_place_where_it_works_without_one() -> None:
    """Alex can hand the bike to Jo before the train. That plan takes no place of an OFFER,
    so it comes first, though it has a hand-over more."""
    file = a_meeting()
    assert shown(file) == [("meet", ("alex", "jo"), (("bike", "jo"),)), ("train", ("alex",), ())]
    assert not checked(file).rights


def a_morning(most: str) -> File:
    """Sam has the bike and Alex the hire car. Sam has breakfast with Jo at 5:00 am, where
    the bike can be handed over. Alex and Sam take the ferry at 6:00 am. The ferry needs a
    right for the car and for the bike: the car deck has a place for 90 dollars and the
    rack one for 10. The trip money pays, up to its cap."""
    options = [stays("breakfast", "milwaukee"), moves("ferry", "milwaukee", "muskegon")]
    people = ["alex", "sam", "jo"]
    stated = [*at("breakfast", 5), *at("ferry", 6, 0, "PT2H30M")]
    stated += [starts_from(person, "milwaukee") for person in people]
    stated += [has_object("alex", "car"), has_object("sam", "bike")]
    stated += [each(thing) for thing in ("car", "bike") for each in (every_use, every_transfer)]
    stated += [hands_over("breakfast", "bike")]
    stated += [needs_right_for("ferry", thing) for thing in ("car", "bike")]
    stated += [every_right_for("car"), every_right_for("bike")]
    stated += [car_deck(1), offer("ferry", 1, "rack", objects=["bike"])]
    decisions = [lock("breakfast", "sam", "jo"), lock("ferry", "alex", "sam")]
    decisions += [cap("trip-money", f"{most} USD")]
    return trip(
        people,
        ["milwaukee", "muskegon"],
        options,
        stated,
        decisions,
        budgets=[budget("trip-money", *people, objects=["car", "bike"])],
        objects=["car", "bike"],
        object_rights=True,
    )


def test_a_hand_over_saves_a_place_that_the_cap_does_not_allow() -> None:
    """The car has to cross, and its place costs 90 dollars. With 100 dollars, the bike
    crosses too. With 95, the plan with the fewest hand-overs cannot be paid for. Sam hands
    the bike to Jo at breakfast: one hand-over more, and the only plan that the cap allows."""
    both_cross = [("breakfast", ("sam", "jo"), ()), ("ferry", ("alex", "sam"), ())]
    assert shown(a_morning("100.00")) == both_cross
    bought = [(cover.object, cover.by) for cover in checked(a_morning("100.00")).rights]
    assert bought == [("car", "car-deck"), ("bike", "rack")]
    the_bike_stays = [
        ("breakfast", ("sam", "jo"), (("bike", "jo"),)),
        ("ferry", ("alex", "sam"), ()),
    ]
    assert shown(a_morning("95.00")) == the_bike_stays
    bought = [(cover.object, cover.by) for cover in checked(a_morning("95.00")).rights]
    assert bought == [("car", "car-deck")]
    # With 89 dollars the car cannot cross, and Alex is LOCKed into the ferry with it.
    assert checked(a_morning("89.00")).answer is Answer.UNDETERMINED


def test_the_best_case_starts_the_object_where_its_place_can_be_paid_for() -> None:
    """Nobody says where the bike starts. Alex takes the train, and the cap leaves 5 dollars
    for a place that costs 10. In a world where the bike starts with Alex, it takes that
    place, and the plan cannot be paid for. In a world where it starts with Jo, it takes
    none. The best case picks the start, and it picks one that works."""
    whole = no_other_right_for("train", "bike", "rack")
    file = a_train(whole, caps=[cap("money", "5.00 USD"), lock("train", "alex")])
    best = best_case(file)
    assert "bike" in best.starts_anywhere and best.offered == {("train", "bike")}
    visits = as_visits([("train", ("alex",), "a")])
    begins = reference._begins(file, best, "bike")  # pyright: ignore[reportPrivateUsage]
    runs = reference._least_broken(best, "bike", visits, begins, {}, set(), {})  # pyright: ignore[reportPrivateUsage]
    # Two ways that break nothing: the first start takes a place, and the next takes none.
    assert [(run[1][0], run[3]) for run in runs] == [
        (frozenset({Where(person="alex")}), ((0, None, True),)),
        (frozenset({Where(person="jo")}), ()),
    ]
    assert broken_as_listed(file, best, (ride("alex"),)) == []
    assert taking_a_place(file, best, (ride("alex"),)) == {}
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    # With no cap, the first way is taken: the place can be paid for.
    free = a_train(whole, caps=[lock("train", "alex")])
    assert taking_a_place(free, best_case(free), (ride("alex"),)) == {"train": {"bike": True}}


def test_another_transfer_does_not_save_the_place_of_an_object_that_goes_along() -> None:
    """The train requires the bike and carries it, so the bike goes along whenever the
    train runs. Another transfer might bring the bike, and it does not cover it: the bike
    takes its place, and the cap has to allow it."""
    facts = [lies_at("bike", "a"), carries("train", "bike"), requires_object("train", "bike")]
    facts += [no_other_right_for("train", "bike", "rack")]

    def capped(most: str) -> File:
        limits = [cap("money", f"{most} USD"), lock("train", "alex")]
        return without(a_train(*facts, caps=limits), "every-transfer-of-bike")

    short = capped("5.00")
    assert "bike" in best_case(short).brought
    assert broken_as_listed(short, best_case(short), (ride("alex"),)) == [
        Broken(Constraint.CAP, None, ())
    ]
    found = checked(short)
    assert found.answer is Answer.INFEASIBLE
    assert {"rack", "money-cap", "every-right-to-train-for-bike"} <= set(found.conflict)
    assert has_no_record_to_spare(short, found.conflict)
    assert checked(capped("10.00")).answer is Answer.FEASIBLE


# ------------------------------- The conflict -------------------------------


def test_an_offer_for_objects_that_is_taken_out_might_have_a_place_for_each_object_it_names() -> (
    None
):
    """Taking a FACT out makes what it stated unknown: the places of the OFFER and its
    price. So it might have a place for each OBJECT it names, at no cost. It still has
    none for a PERSON or for another OBJECT."""
    rack = offer("ferry", 1, "rack", objects=["bike"])
    sets = [
        no_other_right_for("ferry", "car", "car-deck"),
        no_other_right_for("ferry", "bike", "rack"),
    ]
    people = [needs_right("ferry"), every_right("ferry", "seats"), offer("ferry", 1, "seats")]
    file = a_crossing(car_deck(), rack, *sets, *people, bike=True, rights=True)
    whole, _ = best_case_left(Remaining(file))
    assert whole.offered == {ON_THE_FERRY, ("ferry", "bike")}
    left, _ = best_case_left(Remaining(file).without("rack"))
    assert left.offered == {ON_THE_FERRY} and not left.uncovered
    assert left.rights == whole.rights
    # A seat that is taken out might be there for every PERSON, and for no OBJECT.
    left, _ = best_case_left(Remaining(file).without("seats"))
    assert left.offered == whole.offered and not left.uncovered
    assert left.rights == {("ferry", "alex"), ("ferry", "sam")}


def test_a_rack_for_the_bike_is_no_part_of_why_the_car_cannot_cross() -> None:
    rack = offer("ferry", 1, "rack", objects=["bike"])
    file = a_crossing(rack, no_other_right_for("ferry", "car"), budgets=[FOR_BOTH], bike=True)
    found = checked(file)
    assert found.answer is Answer.INFEASIBLE
    assert "rack" not in found.conflict and "every-right-to-ferry-for-car" in found.conflict
    assert has_no_record_to_spare(file, found.conflict)


def test_one_place_cannot_cover_two_objects() -> None:
    """One rack takes the car or the bike, and both have to cross. The conflict holds the
    OFFER and the two COMPLETE sets: without any of them, another place might be there."""
    rack = offer("ferry", 1, "rack", objects=["car", "bike"])
    sets = [no_other_right_for("ferry", thing, "rack") for thing in ("car", "bike")]
    file = a_crossing(rack, *sets, budgets=[FOR_BOTH], bike=True)
    found = checked(file)
    assert found.answer is Answer.INFEASIBLE
    assert found.conflict == (
        "car-start",
        "bike-start",
        "every-transfer-of-car",
        "every-transfer-of-bike",
        "ferry-right-for-car",
        "ferry-right-for-bike",
        "rack",
        "every-right-to-ferry-for-car",
        "every-right-to-ferry-for-bike",
        "lock-ferry",
    )
    assert not found.given_budgets
    assert has_no_record_to_spare(file, found.conflict)


# ------------------------------- The report -------------------------------


def in_words(file: File) -> list[str]:
    return report.as_text(file, checked(file)).splitlines()


def test_the_report_names_the_offer_the_price_and_the_budget_for_an_object() -> None:
    file = a_crossing(car_deck(), WHOLE, budgets=[TRIP_MONEY])
    found = checked(file)
    assert found.answer is Answer.FEASIBLE and found.robust
    ninety = Money(Decimal("90.00"), "USD")
    assert found.rights == (Cover("ferry", None, "car-deck", True, ninety, "trip-money", "car"),)
    assert "car-deck" in found.relies_on and "every-right-to-ferry-for-car" not in found.relies_on
    lines = in_words(file)
    assert (
        lines[0] == "FEASIBLE, with a WARNING: this trip works, but not everything is booked yet."
    )
    assert (
        "    ! A right to this still has to be bought for car, from car-deck, for 90.00 USD"
        " from trip-money." in lines
    )
    assert (
        'WARNING: not everything is booked yet. A line marked "!" that names an OFFER says'
        " which OBJECT still needs a right. Only a BOOKING secures one." in lines
    )
    assert (
        "  car-deck: an OFFER has 3 places for ferry that can still be bought to cover car,"
        " for 90.00 USD each" in lines
    )
    assert (
        "    ferry needs a right for car. Just before it starts: with alex. A place from"
        " car-deck covers car, once it is bought." in lines
    )
    assert "  USD: 90.00 still to buy (car-deck)" in lines
    said = report.as_json(file, found)
    assert said["to_buy"] == [
        {
            "option": "ferry",
            "offer": "car-deck",
            "persons": [],
            "objects": ["car"],
            "only_if_needed": False,
            "price": {"amount": "90.00", "currency": "USD"},
            "budget": "trip-money",
        }
    ]
    (step,) = cast("list[dict[str, object]]", said["itinerary"])
    assert "rights" not in step
    (thing,) = cast("list[dict[str, object]]", said["objects"])
    assert thing["covered_in"] == [
        {
            "option": "ferry",
            "stated": True,
            "where": [{"person": "alex"}],
            "booking": None,
            "offer": "car-deck",
        }
    ]


def test_persons_and_objects_that_still_need_a_right_are_named_apart() -> None:
    """Alex and Sam each buy a seat, and the car and the bike each take a place on the rack."""
    people = [needs_right("ferry"), offer("ferry", 20, "seats")]
    rack = offer("ferry", 2, "rack", "5.00 USD", objects=["car", "bike"])
    file = a_crossing(rack, *people, budgets=[FOR_BOTH], bike=True, rights=True)
    lines = in_words(file)
    start = lines.index("  6:00 am to 8:30 am: ferry, alex and sam")
    assert lines[start + 1 : start + 3] == [
        "    ! alex and sam still have to buy a right to this, from seats, for 10.00 USD each"
        " from money.",
        "    ! A right to this still has to be bought for each of car and bike, from rack, for"
        " 5.00 USD each from money.",
    ]
    assert (
        'WARNING: not everything is booked yet. A line marked "!" that names an OFFER says'
        " who still has to buy a right and which OBJECT still needs one. Only a BOOKING"
        " secures one." in lines
    )
    assert "  USD: 30.00 still to buy (seats and rack)" in lines


def test_a_place_that_is_needed_only_if_the_option_needs_a_right() -> None:
    """Nobody says whether the ferry needs a right for the bike. The plan holds either way:
    the bike takes a place if it does."""
    rack = offer("ferry", 2, "rack", "5.00 USD", objects=["car", "bike"])
    file = without(a_crossing(rack, budgets=[FOR_BOTH]), "ferry-right-for-bike")
    lines = in_words(file)
    assert (
        "    ! A right to this still has to be bought for car, from rack, for 5.00 USD from"
        " money." in lines
    )
    assert (
        "    ! A right to this might still have to be bought for bike, from rack, for 5.00 USD"
        " from money." in lines
    )
    assert (
        "    The FILE does not say whether ferry needs a right for bike. Just before it starts:"
        " with sam. A place from rack covers bike, so the plan holds if it does." in lines
    )
    assert (
        "  USD: 5.00 still to buy (rack); up to 5.00 more, depending on which OPTIONs need a"
        " right (rack)" in lines
    )


def test_the_report_asks_who_pays_for_an_object_that_no_budget_lists() -> None:
    file = a_crossing(car_deck(), WHOLE)
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    ((needed,),) = found.missing
    assert needed.unknown == Unknown("funding", about="car")
    ninety = Money(Decimal("90.00"), "USD")
    assert needed.buys == (Cover("ferry", None, "car-deck", True, ninety, None, "car"),)
    lines = in_words(file)
    assert (
        "The trip works if each place that covers car can be paid from a BUDGET that lists car"
        " (one from car-deck for 90.00 USD)." in lines
    )
    assert "  money: for alex and sam; it holds USD" in lines
    said = report.as_json(file, found)
    assert said["missing"] == [
        [
            {
                "what": "funding",
                "object": "car",
                "buys": [
                    {
                        "person": None,
                        "object": "car",
                        "option": "ferry",
                        "offer": "car-deck",
                        "price": {"amount": "90.00", "currency": "USD"},
                    }
                ],
                "at_most": None,
            }
        ]
    ]


def test_the_report_asks_for_a_price_that_can_be_paid_for_the_object() -> None:
    file = a_crossing(car_deck(price=None), WHOLE, budgets=[TRIP_MONEY])
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    ((needed,),) = found.missing
    assert needed.unknown == Unknown("price", "ferry", about="car-deck")
    lines = in_words(file)
    assert "The trip works if a place from car-deck has a price that can be paid for car." in lines
    assert "  trip-money: for alex, sam and car; it holds USD" in lines


def test_a_cap_that_is_a_dollar_short_rules_the_trip_out() -> None:
    """The car deck is the only way to cover the car, a place costs 90 dollars, and the trip
    money may spend 89. The conflict holds the cap, the OFFER and the COMPLETE set."""
    file = a_crossing(
        car_deck(), WHOLE, budgets=[TRIP_MONEY], caps=[cap("trip-money", "89.00 USD")]
    )
    found = checked(file)
    assert found.answer is Answer.INFEASIBLE and found.given_budgets
    assert {"car-deck", "every-right-to-ferry-for-car", "trip-money-cap"} <= set(found.conflict)
    assert has_no_record_to_spare(file, found.conflict)
    lines = in_words(file)
    assert (
        "  every-right-to-ferry-for-car: the FILE lists every right to ferry that covers car:"
        " nobody on the trip holds another or can get one, except from car-deck" in lines
    )
    assert "  trip-money: for alex, sam and car; it holds USD" in lines
    enough = a_crossing(
        car_deck(), WHOLE, budgets=[TRIP_MONEY], caps=[cap("trip-money", "90.00 USD")]
    )
    assert (
        "  trip-money-cap: at most 90.00 USD from trip-money: 0.00 paid; 90.00 still to buy;"
        " 0.00 left" in in_words(enough)
    )


# ------------------------------- Random trips -------------------------------

NOTHING = Payment(Money(Decimal("0.00"), "USD"))
PRICES = [None, "0.00 USD", "10.00 USD", "10.00 USD", "25.00 EUR"]


def with_offers(rng: Random, file: File, tight: bool = False) -> File:
    """The same FILE with FACTs about rights for its OBJECTs, and with money: OFFERs for
    OBJECTs, BUDGETs that list OBJECTs, and in some FILEs a cap.

    Most OPTIONs need a right for an OBJECT, some need none, and of some nobody says. A
    few BOOKINGs cover an OBJECT, and for some OPTIONs the FILE lists every right for an
    OBJECT. Three OPTIONs in four have an OFFER for some of the OBJECTs, with one place or
    two, at no cost, for 10 dollars, for 25 euros or at a price that nobody knows. A FACT
    that the FILE lists every right for an OBJECT names the OFFERs that name the OBJECT.
    In some FILEs an OPTION also needs a right for the PERSONs, with seats on OFFER, so
    that PERSONs and OBJECTs draw on the same money. The BUDGETs list all the OBJECTs,
    some of them or none, and one FILE in five has a fund that lists only OBJECTs. Each
    BOOKING states that it paid nothing, so that a cap can be shown to hold.

    With ``tight``, the FILE lists every right for most OPTIONs and OBJECTs, each OFFER has
    one place, and most FILEs have a cap: a place is often the only way, and often short.
    """
    things = [thing.id for thing in file.objects]
    offers: list[Offer] = []
    facts: list[Fact] = []
    for fact in file.facts:
        if isinstance(fact, CompleteNeedsRightFor):
            continue
        if isinstance(fact, NeedsRight) and not fact.needed and rng.random() < 0.15:
            facts.append(replace(fact, needed=True))
            ten = Money(Decimal("10.00"), "USD")
            offers.append(Offer(f"{fact.option}-seats", fact.option, 2, ten))
        elif isinstance(fact, Booking):
            facts.append(replace(fact, paid=NOTHING))
        else:
            facts.append(fact)
    for option in file.options:
        if rng.random() < 0.75:
            named = tuple(thing for thing in things if rng.random() < 0.8)
            quoted = rng.choice(PRICES)
            price = None
            if quoted is not None:
                amount, currency = quoted.split()
                price = Money(Decimal(amount), currency)
            places = 1 if tight else rng.choice([1, 1, 2])
            offers.append(
                Offer(f"{option.id}-places", option.id, places, price, named or (things[0],))
            )
    for thing in things:
        if rng.random() < 0.4:
            facts.append(CompleteNeedsRightFor(f"every-right-for-{thing}", thing))
        for option in file.options:
            roll = rng.random()
            name = f"{option.id}-right-for-{thing}"
            if roll < 0.55:
                facts.append(NeedsRightFor(name, option.id, thing, True))
            elif roll < 0.65:
                facts.append(NeedsRightFor(name, option.id, thing, False))
            if rng.random() < 0.1:
                facts.append(
                    Booking(f"{option.id}-covers-{thing}", option.id, (), NOTHING, (thing,))
                )
            if rng.random() < (0.8 if tight else 0.35):
                # The set names exactly the OFFERs for its OPTION that name its OBJECT.
                names = tuple(
                    each.id for each in offers if each.option == option.id and thing in each.objects
                )
                full = f"{option.id}-full-for-{thing}"
                facts.append(CompleteRightsFor(full, option.id, thing, names))
    persons = tuple(person.id for person in file.persons)
    roll = rng.random()
    if roll < 0.5:
        budgets = (Budget("money", "money", persons, ("USD",), tuple(things)),)
    elif roll < 0.65:
        budgets = (Budget("money", "money", persons, ("USD",)),)
    elif roll < 0.85:
        budgets = (
            Budget("money", "money", persons, ("USD",), tuple(things[:1])),
            Budget("fund", "fund", (), ("USD", "EUR"), tuple(things)),
        )
    else:
        some = tuple(thing for thing in things if rng.random() < 0.5)
        budgets = (Budget("money", "money", persons, ("USD", "EUR"), some),)
    decisions = list(file.decisions)
    if rng.random() < (0.7 if tight else 0.4):
        most = Money(Decimal(rng.choice(["5.00", "10.00", "20.00"])), "USD")
        decisions.append(Cap("money-cap", "money", most))
    return replace(file, facts=(*facts, *offers), budgets=budgets, decisions=tuple(decisions))


def a_trip_with_offers(rng: Random, number: int) -> File:
    """Some trips have vans that run with nobody in them. The others have OBJECTs to fetch,
    to ship across and to use, with hand-overs and OPTIONs that keep them. Half of each
    kind are tight, as ``with_offers`` says."""
    tight = number % 4 > 1
    if number % 2:
        return with_offers(rng, a_trip_with_services(rng), tight)
    return with_offers(rng, a_trip_with_objects(rng, most=2, leave_out=0.08), tight)


def test_both_checkers_agree_on_trips_with_offers_for_objects() -> None:
    """On random trips with OFFERs for OBJECTs, BUDGETs that list OBJECTs and caps, the
    solver's search and the COMPILER give the report that the reference checker gives. A
    plan that is shown works as listed in the worst case, and it relies on each OFFER that
    it takes a place of. A conflict that holds an OFFER for OBJECTs is enough, with no
    record to spare."""
    rng = Random(24)
    seen: dict[Answer, int] = {}
    placed = with_persons = short = about_money = 0
    for number in range(240):
        file = a_trip_with_offers(rng, number)
        found = checked(file)
        seen[found.answer] = seen.get(found.answer, 0) + 1
        for_objects = {fact.id for fact in file.facts if isinstance(fact, Offer) and fact.objects}
        if found.answer is Answer.FEASIBLE:
            assert reference.works_as_listed(file, worst_case(file), found.itinerary)
            taken = [cover for cover in found.rights if cover.object is not None]
            assert {cover.by for cover in taken} <= for_objects & set(found.relies_on)
            placed += bool(taken)
            with_persons += bool(taken) and any(
                cover.to_buy and cover.person for cover in found.rights
            )
        if found.answer is Answer.INFEASIBLE and for_objects & set(found.conflict):
            assert has_no_record_to_spare(file, found.conflict)
            short += 1
        asked_for = [each.unknown for group in found.missing for each in group]
        about_money += any(
            (each.what == "funding" and each.person is None)
            or (each.what == "price" and each.about in for_objects)
            for each in asked_for
        )
    assert seen[Answer.FEASIBLE] > 70 and seen[Answer.UNDETERMINED] > 70
    assert seen[Answer.INFEASIBLE] > 40
    assert placed > 20 and with_persons > 3 and short > 1 and about_money > 15


def test_the_sets_named_about_money_for_objects_are_all_the_smallest_that_are_enough() -> None:
    """Checked by trying every set of that size and of each smaller one, on random trips with
    OFFERs for OBJECTs. Each set that a report names is enough, and it is not enough with
    one FACT less."""
    rng = Random(5)
    compared = several = about_money = 0
    for number in range(200):
        tight = number % 4 > 1
        if number % 2:
            file = with_offers(rng, a_trip_with_services(rng), tight)
        else:
            file = with_offers(rng, a_trip_with_objects(rng, most=1, leave_out=0.08), tight)
        named_sets = asked(answers.check(file))
        for named in named_sets:
            assert itineraries(file, with_these_at_best(file, named))
            for left_out in named:
                fewer = [unknown for unknown in named if unknown != left_out]
                assert not itineraries(file, with_these_at_best(file, fewer))
        plain = [unknown for unknown in unknowns(file) if unknown.what not in NEW]
        if named_sets and len(named_sets[0]) <= 3 and len(plain) <= 13:
            assert named_sets == smallest_sets(file)
            compared += 1
            several += len(named_sets) > 1
            money = ("price", "funding")
            about_money += any(u.what in money for named in named_sets for u in named)
    assert compared > 30 and several > 8 and about_money > 8


def those_that_a_right_orders(
    file: File,
    world: reference.World,
    who: tuple[tuple[str, ...], ...],
    orders: tuple[tuple[int, ...], ...],
    *hints: object,
    empty: frozenset[int] = frozenset(),
    whether_any: bool = False,
) -> object:
    """Every order of the OPTIONs that matter to each OBJECT, with every choice of hand-overs
    and carries, also for an OBJECT that only a right asks about."""
    asking = world.uncovered | world.offered
    return every_chain(file, world, who, orders, everything=False, empty=empty, asking=asking)


def every_option_in_every_order(
    file: File,
    world: reference.World,
    who: tuple[tuple[str, ...], ...],
    orders: tuple[tuple[int, ...], ...],
    *hints: object,
    empty: frozenset[int] = frozenset(),
    whether_any: bool = False,
) -> object:
    """Every order of every OPTION that happens, with every OBJECT handed about in every way."""
    asking = world.uncovered | world.offered
    return every_chain(file, world, who, orders, everything=True, empty=empty, asking=asking)


def test_the_search_shows_the_plan_that_trying_every_choice_shows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The search keeps one choice of hand-overs and carries for each place it can leave an
    OBJECT in, each set of arrivals and each set of places taken. Here every order of the
    OPTIONs that matter to an OBJECT is tried with every choice, each is timed and checked,
    and the rule picks among all of them. The ITINERARIES are the same, in the same order."""
    rng = Random(7)
    search = EveryOrder(monkeypatch)
    compared = placed = handed = 0
    for number in range(90):
        file = a_trip_with_offers(rng, number)
        for world in worlds_to_try(rng, file):
            search.as_built()
            found = itineraries(file, world)
            search.skipping_nothing(those_that_a_right_orders)
            assert itineraries(file, world) == found
            compared += bool(found)
            takes = [bool(taking_a_place(file, world, plan)) for plan in found]
            placed += any(takes)
            handed += any(
                any(step.handed or step.carried for step in plan)
                for plan, taking in zip(found, takes, strict=True)
                if taking
            )
    assert compared > 200 and placed > 25 and handed > 15


def test_ordering_only_the_options_that_matter_to_an_object_misses_no_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Here every OPTION that happens is put in every order, and every OBJECT is handed about
    in every way. Something works there exactly where the search finds something."""
    rng = Random(8)
    search = EveryOrder(monkeypatch)
    works = fails = 0
    for number in range(60):
        file = a_trip_with_offers(rng, number)
        for world in worlds_to_try(rng, file):
            search.as_built()
            found = bool(itineraries(file, world))
            search.skipping_nothing(every_option_in_every_order)
            assert bool(itineraries(file, world)) == found
            works += found
            fails += not found
    assert works > 120 and fails > 100


def test_the_plan_for_a_case_says_which_place_covers_the_object() -> None:
    """In a FILE with a cap, the report gives one plan for each case. A place that covers an
    OBJECT is named with the OBJECT, its price and the BUDGET that pays."""
    limit = [cap("trip-money", "100.00 USD")]
    file = a_crossing(car_deck(price=None), WHOLE, budgets=[TRIP_MONEY], caps=limit)
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    (plan,) = found.plans
    assert plan.buys == (Cover("ferry", None, "car-deck", True, None, None, "car"),)
    lines = in_words(file)
    assert (
        "  One plan that works then: a place from car-deck covers car, at a price that the FILE"
        " has yet to state." in lines
    )
    said = report.as_json(file, found)
    (shown,) = cast("list[dict[str, object]]", said["plans"])
    assert shown["buys"] == [
        {
            "person": None,
            "object": "car",
            "option": "ferry",
            "offer": "car-deck",
            "price": None,
            "budget": None,
            "only_if_needed": False,
        }
    ]
    # The FILE does not say who pays for the car: the plan names the place and its price.
    unlisted = a_crossing(car_deck(), WHOLE, caps=[cap("money", "100.00 USD")])
    assert (
        "  One plan that works then: a place from car-deck covers car, for 90.00 USD."
        in in_words(unlisted)
    )


def test_a_place_that_an_object_only_might_need_reads_as_one_that_might_be_bought() -> None:
    """Nobody says where the bike starts. Alex takes the train, and the bike might be with
    Alex: then it takes the place on the rack. The plan holds wherever the bike is, so the
    trip works. The place is counted, and the report says that it might have to be bought."""
    locked = [lock("train", "alex")]
    file = a_train(caps=locked)
    worst = worst_case(file)
    assert "bike" not in worst.starts and "bike" not in worst.starts_anywhere
    assert taking_a_place(file, worst, (ride("alex"),)) == {"train": {"bike": False}}
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    ten = Money(Decimal("10.00"), "USD")
    assert found.rights == (Cover("train", None, "rack", True, ten, "money", "bike", True),)
    lines = in_words(file)
    assert (
        "    ! A right to this might still have to be bought for bike, from rack, for 10.00 USD"
        " from money." in lines
    )
    assert (
        "  USD: up to 10.00 more, depending on which OPTIONs need a right and on where each"
        " OBJECT is (rack)" in lines
    )
    (buy,) = cast("list[dict[str, object]]", report.as_json(file, found)["to_buy"])
    assert (buy["objects"], buy["only_if_needed"]) == (["bike"], True)
    # With a cap, the row of the cap says the same.
    capped = a_train(caps=[*locked, cap("money", "30.00 USD")])
    assert (
        "  money-cap: at most 30.00 USD from money: 0.00 paid; 0.00 still to buy; up to 10.00"
        " more to buy, depending on which OPTIONs need a right and on where each OBJECT is;"
        " 20.00 left" in in_words(capped)
    )
    # Where Alex has the bike, the place is sure.
    sure = a_train(has_object("alex", "bike"), caps=locked)
    assert taking_a_place(sure, worst_case(sure), (ride("alex"),)) == {"train": {"bike": True}}
    assert "  USD: 10.00 still to buy (rack)" in in_words(sure)


def test_an_object_that_only_might_go_along_might_take_a_place() -> None:
    """The train carries the bike, and nobody knows whether it requires it. If it does, the
    bike goes along with no choice and takes a place. Another transfer brings the bike in
    the best case, and the place is counted there too, as one that it might take."""
    facts = [lies_at("bike", "a"), carries("train", "bike")]
    file = without(a_train(*facts), "every-use-of-bike")
    worst = worst_case(file)
    assert reference.goes_along(worst, "train", "bike") == "might"
    assert taking_a_place(file, worst, (ride("alex"),)) == {"train": {"bike": False}}
    # The plan's own carry is sure.
    assert taking_a_place(file, worst, (ride("alex", carried=("bike",)),)) == {
        "train": {"bike": True}
    }


def test_a_plan_for_a_case_counts_the_place_of_an_object_that_another_transfer_brings() -> None:
    """The train requires the bike and carries it, and the bike lies at the other end. The
    trip works if another transfer brings the bike. Then the bike goes along and takes its
    place, and the plan that the report gives for that case counts it."""
    facts = [lies_at("bike", "b"), carries("train", "bike"), requires_object("train", "bike")]
    limits = [lock("train", "alex"), cap("money", "30.00 USD")]
    file = without(a_train(*facts, caps=limits), "every-transfer-of-bike")
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    ((needed,),) = found.missing
    assert needed.unknown == Unknown("another transfer", about="bike")
    # The transfer has to put the bike at hand. The plan takes a place for it on the
    # train, so the transfer need not keep it out.
    assert needed.at_hand_for == (("train", "requires", True, False),)
    ten = Money(Decimal("10.00"), "USD")
    (plan,) = found.plans
    assert plan.buys == (Cover("train", None, "rack", True, ten, "money", "bike"),)
    (row,) = plan.caps
    assert (row.to_buy, row.left) == (ten.units, 2 * ten.units)
    assert (
        "  One plan that works then: a place from rack covers bike, for 10.00 USD from money."
        in in_words(file)
    )


def test_a_hand_over_that_cannot_happen_takes_no_place() -> None:
    """The plan hands the bike to Alex in the train, and the bike lies at the other end. The
    hand-over cannot happen, so the fourteenth CONSTRAINT is broken. The bike is never in the
    train, and it takes no place there."""
    file = a_train(lies_at("bike", "b"), hands_over("train", "bike"))
    worst = worst_case(file)
    plan = (ride("alex", handed=(("bike", "alex"),)),)
    assert broken_as_listed(file, worst, plan) == [
        Broken(Constraint.AT_HAND, "train", ("alex",), object="bike")
    ]
    assert taking_a_place(file, worst, plan) == {}


def test_an_object_that_another_transfer_brings_might_take_a_place() -> None:
    """The train carries the bike, and nobody knows whether it requires it. Another transfer
    brings the bike, so nothing follows it through the plan. If the train requires the bike,
    it goes along and takes a place: the place is counted, as one that it might take. Where
    a FACT says that the train requires the bike, the place is sure."""
    facts = [lies_at("bike", "a"), carries("train", "bike")]
    open_set = ("every-use-of-bike", "every-transfer-of-bike")
    file = a_train(*facts)
    for record in open_set:
        file = without(file, record)
    world = with_these_at_best(file, [Unknown("another transfer", about="bike")])
    assert "bike" in world.brought and world.offered == {("train", "bike")}
    assert reference.goes_along(world, "train", "bike") == "might"
    assert taking_a_place(file, world, (ride("alex"),)) == {"train": {"bike": False}}
    required = without(a_train(*facts, requires_object("train", "bike")), "every-transfer-of-bike")
    world = with_these_at_best(required, [Unknown("another transfer", about="bike")])
    assert reference.goes_along(world, "train", "bike") == "sure"
    assert taking_a_place(required, world, (ride("alex"),)) == {"train": {"bike": True}}


# A ride: the train, who takes it, the hour it leaves, and from where to where.
type Ride = tuple[str, str, int, str, str]
ALEX_NORTH: Ride = ("north", "alex", 9, "a", "b")
JO_SOUTH: Ride = ("south", "jo", 9, "a", "c")
ALEX_SOUTH: Ride = ("south", "alex", 10, "b", "d")
ALEX_EAST: Ride = ("east", "alex", 10, "b", "d")


def trains(
    most: str,
    rides: Sequence[Ride],
    *facts: Document,
    rights: bool = False,
    options: Sequence[Document] = (),
    transfers: bool = True,
) -> File:
    """Each of these trains needs a right for the bike, and a rack on each has a place for
    it, for 10 dollars. The FILE lists every right for the bike, and the money may spend
    this much. A LOCK names the rider of each train. Nobody says where the bike starts,
    unless ``facts`` does.

    Nobody needs a right to take part, unless ``rights`` leaves that to ``facts``.
    ``options`` are OPTIONs besides the trains. Without ``transfers``, no FACT says that
    the FILE states every transfer of the bike, and a FACT says of each train that it does
    nothing with the bike.
    """
    stated = [starts_from("alex", "a"), starts_from("jo", "a")]
    stated += [every_use("bike"), every_right_for("bike")]
    stated += [every_transfer("bike")] if transfers else []
    for train, _, hour, _, _ in rides:
        stated += at(train, hour)
        stated += [
            needs_right_for(train, "bike"),
            offer(train, 1, f"{train}-rack", objects=["bike"]),
        ]
        stated.append(no_other_right_for(train, "bike", f"{train}-rack"))
        stated += [] if transfers else [does_with(train, "bike", "nothing")]
    decisions = [lock(train, rider) for train, rider, _, _, _ in rides]
    return trip(
        ["alex", "jo"],
        ["a", "b", "c", "d"],
        [*(moves(train, origin, to) for train, _, _, origin, to in rides), *options],
        [*stated, *facts],
        [*decisions, cap("money", f"{most} USD")],
        rights=rights,
        budgets=[budget("money", "alex", "jo", objects=["bike"])],
        objects=["bike"],
        object_rights=True,
    )


def two_trains(most: str, *facts: Document, one_rider: bool = False, rights: bool = False) -> File:
    """Alex takes the north train from A at 9:00 am, and Jo takes the south train from A at
    the same time. With ``one_rider``, the south train leaves at 10:00 am from where the
    north train ends, and Alex takes it too. The rest is as ``trains`` says."""
    rides = [ALEX_NORTH, ALEX_SOUTH if one_rider else JO_SOUTH]
    return trains(most, rides, *facts, rights=rights)


def riding(*rides: Ride) -> tuple[Step, ...]:
    """A plan with each of these rides, in the order given."""
    return tuple(
        Step(train, origin, to, (rider,), seconds(hour), seconds(hour, 30))
        for train, rider, hour, origin, to in rides
    )


def test_a_bike_that_one_of_two_travelers_has_takes_a_place_on_one_train() -> None:
    """Alex and Jo take different trains, and nobody knows where the bike starts. It has a
    place on each rack, and it is on one train at most. So a cap counts one place: 10
    dollars are enough, and one cent less is not."""
    enough = two_trains("10.00")
    world, plan = worst_case(enough), riding(ALEX_NORTH, JO_SOUTH)
    assert broken_as_listed(enough, world, plan) == []
    assert taking_a_place(enough, world, plan) == {
        "north": {"bike": False},
        "south": {"bike": False},
    }
    one_or_the_other = frozenset({frozenset({"north"}), frozenset({"south"})})
    assert taken_together(enough, world, plan) == {"bike": one_or_the_other}
    found = checked(enough)
    assert found.answer is Answer.FEASIBLE and found.robust
    sets = (("north",), ("south",))
    assert [(cover.option, cover.by, cover.might, cover.together) for cover in found.rights] == [
        ("north", "north-rack", True, sets),
        ("south", "south-rack", True, sets),
    ]
    lines = in_words(enough)
    for line in (
        "    Of the places for bike, at most one has to be bought: for north or south.",
        "  USD: up to 10.00 more, depending on which OPTIONs need a right and on where each"
        " OBJECT is (north-rack and south-rack)",
        "  money-cap: at most 10.00 USD from money: 0.00 paid; 0.00 still to buy; up to 10.00"
        " more to buy, depending on which OPTIONs need a right and on where each OBJECT is;"
        " 0.00 left",
        'WARNING: not everything is booked yet. A line marked "!" that names an OFFER says'
        " which OBJECT might still need a right. Only a BOOKING secures one.",
    ):
        assert line in lines
    said = report.as_json(enough, found)
    assert said["places_together"] == [{"object": "bike", "options": [["north"], ["south"]]}]
    (totals,) = cast("dict[str, list[dict[str, str]]]", said["money"])["totals"]
    assert (totals["to_buy"], totals["to_buy_at_most_if_needed"]) == ("0", "10.00")
    short = two_trains("9.99")
    assert broken_as_listed(short, worst_case(short), plan) == [Broken(Constraint.CAP, None, ())]
    found = checked(short)
    assert found.answer is Answer.UNDETERMINED
    asked_for = [[needed.unknown for needed in some] for some in found.missing]
    assert [Unknown("starts at", about="bike", place="a")] in asked_for


def test_a_bike_that_one_traveler_might_have_on_two_trains_takes_both_places() -> None:
    """Alex takes one train and then the other, and nobody knows where the bike starts. If
    Alex has it, it takes a place on both. So a cap counts both: 20 dollars are enough, and
    one cent less is not."""
    enough = two_trains("20.00", one_rider=True)
    world, plan = worst_case(enough), riding(ALEX_NORTH, ALEX_SOUTH)
    assert broken_as_listed(enough, world, plan) == []
    assert taken_together(enough, world, plan) == {"bike": {frozenset({"north", "south"})}}
    found = checked(enough)
    assert found.answer is Answer.FEASIBLE
    assert all(cover.might and not cover.together for cover in found.rights)
    lines = in_words(enough)
    assert (
        "  USD: up to 20.00 more, depending on which OPTIONs need a right and on where each"
        " OBJECT is (north-rack and south-rack)" in lines
    )
    assert not any(line.startswith("    Of the places for") for line in lines)
    assert "places_together" not in report.as_json(enough, found)
    short = two_trains("19.99", one_rider=True)
    assert broken_as_listed(short, worst_case(short), plan) == [Broken(Constraint.CAP, None, ())]
    assert checked(short).answer is Answer.UNDETERMINED


def test_the_solver_asks_again_where_the_rules_count_more_than_its_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Alex takes one train and then the other, nobody knows where the bike starts, and the
    money may spend 15 dollars. The model counts the dearer of two places that the bike
    only might take: 10 dollars. The rules count both. So the rules refuse the solver's
    choice, the next model leaves that choice out, and so on until the solver has none."""
    file = two_trains("15.00", one_rider=True)
    world = worst_case(file)
    refusals = refusals_of_the_rules(monkeypatch)
    assert compiler.shown(file, world) is None
    assert refusals and all(refusals)
    refusals.clear()
    assert not compiler.works(file, world)
    assert refusals and all(refusals)
    # Where the bike is in one place, the model counts what the rules count, and the rules
    # refuse nothing.
    refusals.clear()
    known = two_trains("15.00", has_object("alex", "bike"), one_rider=True)
    assert compiler.shown(known, worst_case(known)) is None
    assert not compiler.works(known, worst_case(known))
    assert refusals == []


def test_a_plan_for_a_case_says_which_places_are_never_both_bought() -> None:
    """Nobody knows the price of a seat on the north train. In the case that Alex can pay
    it, the plan has a place for the bike on each rack, and says that one of them is bought
    at most. The cap counts one."""
    seats = [needs_right("north"), offer("north", 5, "seats", None), needs_no_right("south")]
    file = two_trains("30.00", *seats, rights=True)
    lines = in_words(file)
    start = lines.index("  2. A place from seats has a price that alex can pay.")
    assert lines[start + 2 : start + 4] == [
        "     Of the places for bike, at most one has to be bought: for north or south.",
        "     money-cap, on money: up to 10.00 more if OPTIONs need a right or an OBJECT is"
        " there, of at most 30.00 USD. That leaves 20.00 USD for whatever else is charged to it.",
    ]
    plans = cast("list[dict[str, object]]", report.as_json(file, checked(file))["plans"])
    together = [{"object": "bike", "options": [["north"], ["south"]]}]
    assert all(plan["places_together"] == together for plan in plans)


def test_places_that_are_bought_together_are_named_set_by_set() -> None:
    """Alex takes the north train and then the east train, and Jo takes the south train.
    Nobody knows where the bike starts. With Alex it takes a place on two trains, and with
    Jo on one. So a cap counts two places, and the report names both sets."""
    rides = [ALEX_NORTH, JO_SOUTH, ALEX_EAST]
    enough = trains("20.00", rides)
    sets = {frozenset({"north", "east"}), frozenset({"south"})}
    assert taken_together(enough, worst_case(enough), riding(*rides)) == {"bike": sets}
    found = checked(enough)
    assert found.answer is Answer.FEASIBLE
    assert {cover.together for cover in found.rights} == {(("north", "east"), ("south",))}
    lines = in_words(enough)
    assert (
        "    Of the places for bike, at most these have to be bought together: for north, for"
        " east; or for south." in lines
    )
    assert (
        "  USD: up to 20.00 more, depending on which OPTIONs need a right and on where each"
        " OBJECT is (north-rack, south-rack and east-rack)" in lines
    )
    said = report.as_json(enough, found)
    options = [["north", "east"], ["south"]]
    assert said["places_together"] == [{"object": "bike", "options": options}]
    assert checked(trains("19.99", rides)).answer is Answer.UNDETERMINED


def test_the_plan_shown_has_no_step_that_only_a_wrong_count_asks_for() -> None:
    """Alex and Jo take different trains, and the money may spend 10 dollars. A luggage
    check before the trains keeps the bike, and takes between 5 and 30 minutes. A count of
    both racks would send the travelers there to be rid of the bike, with a plan that can
    run late. One rack is counted, so they skip it, and the plan is sure to hold."""
    check = [starts_at("check", 8, 45), lasts_between("check", "PT5M", "PT30M")]
    check += [cutoff("check", "PT0S"), keeps("check", "bike")]
    file = trains("10.00", [ALEX_NORTH, JO_SOUTH], *check, options=[stays("check", "a")])
    found = checked(file)
    assert found.answer is Answer.FEASIBLE and found.robust
    assert [step.option for step in found.itinerary] == ["north", "south"]


def refusals_of_the_rules(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """A list that gains an entry each time the rules time and check a choice of the solver:
    whether they refused it."""
    scheduled = reference.scheduled
    refusals: list[bool] = []

    def counted(*given: Any, **named: Any) -> Itinerary | None:
        found = scheduled(*given, **named)
        refusals.append(found is None)
        return found

    monkeypatch.setattr(reference, "scheduled", counted)
    return refusals


def test_the_model_counts_the_dearest_place_that_an_object_only_might_take(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Alex and Jo take different trains, nobody knows where the bike starts, and the money
    is one cent short of a rack. The model counts the dearer of the two places, as the
    rules do. So the solver finds nothing, and the rules have nothing to refuse."""
    file = two_trains("9.99")
    refusals = refusals_of_the_rules(monkeypatch)
    assert compiler.shown(file, worst_case(file)) is None
    assert not compiler.works(file, worst_case(file))
    assert refusals == []


def test_the_model_counts_each_place_that_an_object_is_sure_to_take(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Alex has the bike and takes one train and then the other. A locker in another town
    might keep the bike, so the world does not say where the bike is all through a plan.
    Nobody can get to the locker. So the bike is sure to take a place on both trains, the
    model counts both, and 15 dollars are not enough for it."""
    locker = [starts_at("locker", 8, 45), lasts("locker", "PT5M"), cutoff("locker", "PT0S")]
    known = has_object("alex", "bike")
    rides = [ALEX_NORTH, ALEX_SOUTH]
    file = trains("15.00", rides, known, *locker, options=[stays("locker", "c")], transfers=False)
    world = worst_case(file)
    assert world.does[("locker", "bike")] == "might_keep"
    refusals = refusals_of_the_rules(monkeypatch)
    assert compiler.shown(file, world) is None
    assert refusals == []
    enough = trains("20.00", rides, known, *locker, options=[stays("locker", "c")], transfers=False)
    assert compiler.shown(enough, worst_case(enough)) is not None
    assert refusals == [False]


PLACES = [
    Where(person="alex"),
    Where(person="jo"),
    Where(place="a"),
    Where(place="b"),
    Where(),
    Where(option="ferry"),
]


def test_what_an_option_does_with_an_object_moves_each_place_by_itself() -> None:
    """Which places an OBJECT takes together is worked out one place at a time. That gives
    the right sets only where each place is moved by itself: where the OBJECT might be
    after an OPTION, from several places, is where it might be from each of them."""
    after = reference._after  # pyright: ignore[reportPrivateUsage]
    visit = as_visits([("train", ("alex",), "a")])[0]
    actions = ["nothing", "keeps", "might_keep", "might_take", "might_carry", "hands_over"]
    actions += ["carries", "carries_unless_refused"]
    some = [
        frozenset(place for place, held in zip(PLACES, bits, strict=True) if held)
        for bits in product((False, True), repeat=len(PLACES))
        if any(bits)
    ]
    how = product(actions, (False, True), (None, "alex"), (False, True), (None, "sure", "might"))
    for does, refused, taker, loaded, along in how:
        alone = {
            place: after(does, frozenset({place}), visit, refused, taker, loaded, along)
            for place in PLACES
        }
        for places in some:
            together = after(does, places, visit, refused, taker, loaded, along)
            assert together == frozenset().union(*(alone[place] for place in places))


def test_a_cap_counts_the_places_that_cost_the_most_together() -> None:
    """The bike takes a place on the first train and on the second, or else on the third.
    The racks cost 10, 20 and 15 dollars. So a cap counts 30: the first two places."""
    trains = {"first": "10.00 USD", "second": "20.00 USD", "third": "15.00 USD"}
    riders = {"first": ("alex",), "second": ("alex",), "third": ("jo",)}
    sets = {"bike": [frozenset({"first", "second"}), frozenset({"third"})]}
    on_each = {train: ["bike"] for train in trains}

    def with_at_most(most: str) -> File:
        stated = [fact for train in trains for fact in at(train, 9)]
        stated += [starts_from("alex", "a"), starts_from("jo", "a")]
        stated += [every_use("bike"), every_transfer("bike"), every_right_for("bike")]
        for train, price in trains.items():
            stated += [needs_right_for(train, "bike")]
            stated.append(offer(train, 1, f"{train}-rack", price, objects=["bike"]))
        return trip(
            ["alex", "jo"],
            ["a", "b"],
            [moves(train, "a", "b") for train in trains],
            stated,
            [cap("money", f"{most} USD")],
            budgets=[budget("money", "alex", "jo", objects=["bike"])],
            objects=["bike"],
            object_rights=True,
        )

    enough = with_at_most("30.00")
    paying = way_to_pay(enough, worst_case(enough), riders, on_each, sets)
    assert paying == {(train, "bike"): (f"{train}-rack", "money") for train in trains}
    short = with_at_most("29.99")
    assert way_to_pay(short, worst_case(short), riders, on_each, sets) is None
    # An OBJECT that is in one place pays for every place it takes.
    assert way_to_pay(enough, worst_case(enough), riders, on_each) is None
    all_three = with_at_most("45.00")
    assert way_to_pay(all_three, worst_case(all_three), riders, on_each) is not None


def test_a_purchase_draws_on_a_cap_what_it_adds_to_the_most_an_object_pays() -> None:
    """The same three racks, bought one after another. The first draws its 10 dollars. The
    third is never bought with it, and costs 15: it draws 5 more. The second is bought
    with the first, and the two cost 30: it draws 15 more. Undoing them gives it all back."""
    key = ("money", "USD")
    room: dict[tuple[str, str], int] = {key: 100}
    buyers = [("first", "bike"), ("third", "bike"), ("second", "bike"), ("first", "alex")]
    sets = {"bike": [frozenset({"first", "second"}), frozenset({"third"})]}
    caps = reference._Caps(room, buyers, sets)  # pyright: ignore[reportPrivateUsage]
    drew = [caps.take(purchase, key, units) for purchase, units in enumerate((10, 15, 20))]
    assert drew == [10, 5, 15] and room[key] == 70
    # A PERSON pays the whole price, and so does an OBJECT with no such sets.
    assert caps.draws(3, key, 40) == 40
    assert caps.counted_by_sets(3) is None and caps.counted_by_sets(0) == "bike"
    for purchase, units in reversed(list(enumerate((10, 15, 20)))):
        caps.give_back(purchase, key, units, drew[purchase])
    assert room[key] == 100 and caps.draws(1, key, 15) == 15


def test_a_missing_payer_is_not_a_missing_place() -> None:
    """One rack takes the car or the bike, and another takes only the car. Both cross, and
    only the car has a BUDGET. The car fits the rack that takes only cars, so the bike has
    a place, and nobody pays for it: the eleventh CONSTRAINT, and not the sixteenth. A
    BUDGET for the bike alone is enough."""
    racks = [
        offer("ferry", 1, "rack-a", objects=["car", "bike"]),
        offer("ferry", 1, "rack-b", objects=["car"]),
    ]
    sets = [
        no_other_right_for("ferry", "car", "rack-a", "rack-b"),
        no_other_right_for("ferry", "bike", "rack-a"),
    ]
    for_the_car = budget("money", "alex", "sam", objects=["car"])
    file = a_crossing(*racks, *sets, budgets=[for_the_car], bike=True)
    found = broken_as_listed(file, worst_case(file), BOTH)
    assert found == [Broken(Constraint.PAID, "ferry", ("sam",), object="bike")]
    asked_for = [[needed.unknown for needed in some] for some in checked(file).missing]
    assert asked_for == [[Unknown("funding", about="bike")]]


def test_the_prices_of_an_option_are_asked_in_the_files_order() -> None:
    """The car deck is listed before the seats, and neither states a price. Alex, Sam and
    the car all need a place, so the trip works only if both prices can be paid. The report
    asks for them in the FILE's order. Who pays for a PERSON comes before who pays for an
    OBJECT."""
    people = [
        needs_right("ferry"),
        offer("ferry", 20, "seats", None),
        every_right("ferry", "seats"),
    ]
    file = a_crossing(car_deck(price=None), *people, WHOLE, budgets=[TRIP_MONEY], rights=True)
    asked_for = [[needed.unknown for needed in some] for some in checked(file).missing]
    assert asked_for == [
        [Unknown("price", "ferry", about="car-deck"), Unknown("price", "ferry", about="seats")]
    ]
    nobody_pays = a_crossing(
        car_deck(), *people, WHOLE, budgets=[budget("money", "alex")], rights=True
    )
    about_money = [each for each in unknowns(nobody_pays) if each.what in ("price", "funding")]
    assert about_money == [
        Unknown("price", "ferry", about="seats"),
        Unknown("funding", person="sam"),
        Unknown("funding", about="car"),
    ]


def test_another_transfer_has_to_keep_the_object_out_where_its_place_cannot_be_paid_for() -> None:
    """Alex has the bike and takes the train. The rack costs dollars, and the only BUDGET
    that lists the bike holds euros. The FILE lists every right for the bike, and it does
    not list every transfer. So the trip might work if another transfer takes the bike
    from Alex before the train, and the report says so."""
    euros = [budget("money", "alex", "jo"), budget("bike-fund", objects=["bike"], holds=["EUR"])]
    facts = [has_object("alex", "bike"), does_with("train", "bike", "nothing")]
    facts += [no_other_right_for("train", "bike", "rack")]
    file = a_train(*facts, budgets=euros, caps=[lock("train", "alex")])
    file = without(file, "every-transfer-of-bike")
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    ((needed,),) = found.missing
    assert needed.unknown == Unknown("another transfer", about="bike")
    assert needed.at_hand_for == (("train", "needs a right for", True, False),)
    assert (
        "The trip might work if another transfer keeps bike away from whoever is in train."
        in in_words(file)
    )


def three_trains(price: str, most: str, bike: bool = False) -> tuple[File, tuple[Step, ...]]:
    """Three travelers take three trains, and nobody knows where eight bags start. The van
    of each train takes a bag at this price, and the money may spend this much. With
    ``bike``, Alex has a bike, which the FILE lists after the bags, and the rack of the
    first train takes it for 10 dollars. With the FILE comes the plan: each traveler takes
    their own train."""
    people, trains = ["alex", "sam", "jo"], ["first", "second", "third"]
    bags = [f"bag-{number}" for number in range(8)]
    things = [*bags, "bike"] if bike else bags
    stated = [fact for train in trains for fact in at(train, 9)]
    stated += [starts_from(person, "a") for person in people]
    stated += [each(thing) for thing in things for each in (every_use, every_transfer)]
    stated += [every_right_for(thing) for thing in things]
    for train in trains:
        stated.append(offer(train, 8, f"{train}-van", price, objects=bags))
        stated += [needs_right_for(train, bag) for bag in bags]
        stated += [no_other_right_for(train, bag, f"{train}-van") for bag in bags]
    if bike:
        stated += [has_object("alex", "bike"), needs_right_for("first", "bike")]
        stated.append(offer("first", 1, "rack", "10.00 USD", objects=["bike"]))
        stated.append(no_other_right_for("first", "bike", "rack"))
    decisions = [lock(train, person) for train, person in zip(trains, people, strict=True)]
    file = trip(
        people,
        ["a", "b"],
        [moves(train, "a", "b") for train in trains],
        stated,
        [*decisions, cap("money", most)],
        budgets=[budget("money", *people, objects=things)],
        objects=things,
        object_rights=True,
    )
    plan = tuple(
        Step(train, "a", "b", (person,), seconds(9), seconds(9, 30))
        for train, person in zip(trains, people, strict=True)
    )
    return file, plan


def counting_the_checks_of_rights(monkeypatch: pytest.MonkeyPatch, most: int) -> None:
    """Fails as soon as a check asks more than this many times whether rights can be had."""
    its_own = reference._rights  # pyright: ignore[reportPrivateUsage]
    calls = 0

    def counted(*given: Any, **named: Any) -> list[Broken]:
        nonlocal calls
        calls += 1
        assert calls < most
        return its_own(*given, **named)

    monkeypatch.setattr(reference, "_rights", counted)


def test_the_ways_of_many_objects_are_picked_without_trying_every_pick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each train charges 10 dollars for a bag, and the money may spend 5. In the best case
    the bags stay behind. Each bag has four ways to go, so there are 65,536 picks. A way
    that cannot be paid for is given up at once, with every pick that starts with it."""
    file, plan = three_trains("10.00 USD", "5.00 USD")
    best = best_case(file)
    counting_the_checks_of_rights(monkeypatch, 200)  # one for the PERSONs, three for each bag
    assert broken_as_listed(file, best, plan) == []
    assert taking_a_place(file, best, plan) == {}


def test_a_place_that_an_object_is_sure_to_take_is_counted_before_any_pick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each train charges 1 dollar for a bag, and the money may spend 10. Alex has a bike,
    and its place on the first train costs all 10. The bike has one way to go, and the FILE
    lists it after the bags. Its place is counted from the start, so no bag is tried on a
    train with every pick for the bags after it."""
    file, plan = three_trains("1.00 USD", "10.00 USD", bike=True)
    best = best_case(file)
    counting_the_checks_of_rights(monkeypatch, 200)
    assert broken_as_listed(file, best, plan) == []
    assert taking_a_place(file, best, plan) == {"first": {"bike": True}}


def test_a_cap_turns_on_where_an_object_is_only_in_the_currency_of_its_place() -> None:
    """A seat on the train costs 2 euros, if the train needs a right. The rack costs 10
    dollars, if the bike is with Alex. One BUDGET holds both currencies, with a cap on
    each. Only the cap in dollars turns on where the bike is."""
    both = budget("money", "alex", "jo", holds=["USD", "EUR"], objects=["bike"])
    limits = [cap("money", "50.00 USD", "dollars"), cap("money", "50.00 EUR", "euros")]
    seats = offer("train", 5, "seats", "2.00 EUR")
    file = a_train(seats, rights=True, budgets=[both], caps=[lock("train", "alex"), *limits])
    lines = in_words(file)
    (dollars,) = [line for line in lines if line.startswith("  dollars: at most ")]
    assert "depending on which OPTIONs need a right and on where each OBJECT is" in dollars
    assert (
        "  euros: at most 50.00 EUR from money: 0.00 paid; 0.00 still to buy; up to 2.00 more"
        " to buy, depending on which OPTIONs need a right; 48.00 left" in lines
    )


def every_way_to_pay(
    file: File,
    world: reference.World,
    taking_part: dict[str, tuple[str, ...]],
    taking: dict[str, list[str]],
    together: dict[str, set[frozenset[str]]],
) -> dict[tuple[str, str], tuple[str, str | None]] | None:
    """The way to pay, found by trying every pair of an OFFER and a BUDGET for every
    purchase: the first that leaves no place taken twice and passes no cap. A cap adds up
    what the PERSONs buy, and for each OBJECT the set of its places that costs the most."""
    buyers: list[tuple[str, str]] = []
    places: dict[str, int] = {}
    for option, persons in taking_part.items():
        if option in world.needs_right:
            buyers += [
                (option, person.id)
                for person in file.persons
                if person.id in persons and (option, person.id) not in world.rights
            ]
            places |= {each.id: each.places for each in file.offers(option)}
        buyers += [(option, thing) for thing in taking.get(option, [])]
        places |= {each.id: each.places for each in file.offers_for_objects(option)}
    pairs = [reference.pairs_to_pay(file, world, option, buyer) for option, buyer in buyers]
    room = {key: each.limit.units - (world.spent.get(key) or 0) for key, each in file.caps.items()}
    for picks in product(*(range(len(able)) for able in pairs)):
        picked = [able[number] for able, number in zip(pairs, picks, strict=True)]
        taken = [offer for offer, _, _, _ in picked]
        if any(taken.count(offer) > places[offer] for offer in taken):
            continue
        for key, most in room.items():
            drawn = [
                (option, buyer, units)
                for (option, buyer), (_, _, on, units) in zip(buyers, picked, strict=True)
                if on == key
            ]
            total = sum(units for _, buyer, units in drawn if buyer not in together)
            for thing, sets in together.items():
                total += max(
                    sum(
                        units for option, buyer, units in drawn if buyer == thing and option in some
                    )
                    for some in sets
                )
            if total > most:
                break
        else:
            return {
                buyer: (offer, pot)
                for buyer, (offer, pot, _, _) in zip(buyers, picked, strict=True)
            }
    return None


def some_trains_to_pay_for(rng: Random) -> tuple[File, list[str], list[str]]:
    """Two to four trains, a bike and sometimes a bag. Each train has one or two OFFERs for
    OBJECTs, some have seats on OFFER, the prices are in two currencies, and one or two
    BUDGETs have caps. With the FILE come its trains and its OBJECTs."""
    prices = ["0.00 USD", "5.00 USD", "10.00 USD", "20.00 USD", "10.00 EUR", "15.00 EUR"]
    names = [f"t{number}" for number in range(rng.choice([2, 3, 3, 4]))]
    things = ["bike", "bag"][: rng.choice([1, 2, 2])]
    stated = [fact for train in names for fact in at(train, 9)]
    stated += [starts_from("alex", "a"), starts_from("jo", "a")]
    stated += [each(thing) for thing in things for each in (every_use, every_transfer)]
    stated += [every_right_for(thing) for thing in things]
    for train in names:
        if rng.random() < 0.3:
            seats = offer(train, rng.choice([1, 2]), f"{train}-seats", rng.choice(prices))
            stated += [needs_right(train), seats]
        elif rng.random() < 0.9:
            stated.append(needs_no_right(train))
        for number in range(rng.choice([1, 1, 2])):
            named = [thing for thing in things if rng.random() < 0.8] or things[:1]
            rack = f"{train}-rack-{number}"
            stated.append(
                offer(train, rng.choice([1, 1, 2]), rack, rng.choice(prices), objects=named)
            )
        stated += [needs_right_for(train, thing) for thing in things]
    both = ["USD", "EUR"] if rng.random() < 0.8 else ["USD"]
    listed = [thing for thing in things if rng.random() < 0.9]
    pots = [budget("money", "alex", "jo", holds=both, objects=listed)]
    if rng.random() < 0.6:
        pots.append(budget("fund", holds=["USD", "EUR"], objects=things))
    caps = [
        cap(
            pot["id"],
            f"{rng.choice([10, 15, 20, 30, 40, 60])}.00 {held}",
            f"{pot['id']}-{held.lower()}",
        )
        for pot in pots
        for held in pot["currencies"]
        if rng.random() < 0.7
    ]
    file = trip(
        ["alex", "jo"],
        ["a", "b"],
        [moves(train, "a", "b") for train in names],
        stated,
        caps or [cap("money", "20.00 USD")],
        rights=True,
        budgets=pots,
        objects=things,
        object_rights=True,
    )
    return file, names, things


def test_the_way_to_pay_is_the_first_that_trying_every_way_finds() -> None:
    """On random trains, with random PERSONs and OBJECTs to pay for and random sets of
    places that an OBJECT takes together. The search for a way to pay looks ahead,
    remembers where it has been and counts a purchase by what it adds. It finds the way
    that trying every way finds, and none where there is none."""
    rng = Random(142)
    ways = none = several = 0
    for _ in range(700):
        file, names, things = some_trains_to_pay_for(rng)
        world = worst_case(file)
        taking_part = {
            train: tuple(person for person in ("alex", "jo") if rng.random() < 0.4)
            for train in names
        }
        on_each = {train: [thing for thing in things if rng.random() < 0.55] for train in names}
        taking = {train: some for train, some in on_each.items() if some}
        together: dict[str, set[frozenset[str]]] = {}
        for thing in things:
            on = [train for train in names if thing in taking.get(train, [])]
            if on and rng.random() < 0.75:
                count = rng.choice([1, 2, 2, 3])
                sets = [frozenset(t for t in on if rng.random() < 0.5) for _ in range(count)]
                sets.append(frozenset(t for t in on if not any(t in some for some in sets)))
                together[thing] = {
                    one for one in sets if one and not any(one < other for other in sets)
                }
        found = way_to_pay(file, world, taking_part, taking, together)
        assert found == every_way_to_pay(file, world, taking_part, taking, together)
        ways += found is not None
        none += found is None
        several += found is not None and any(len(sets) > 1 for sets in together.values())
    assert ways > 200 and none > 200 and several > 40


def a_plan_on_some_trains(rng: Random) -> tuple[File, tuple[Step, ...]]:
    """Two to four trains among three PLACES, one after another, and a bike and sometimes a
    bag. Most trains need a right for an OBJECT, with a rack on OFFER. Of some trains a
    FACT says what they do with an OBJECT, and in half the FILEs no FACT says that those
    are all the transfers. Few FILEs say where an OBJECT starts. With the FILE comes a
    plan: most of the trains, each with some of the travelers, and some of the hand-overs
    and carries that the FILE allows."""
    people, towns = ["alex", "jo", "sam"], ["a", "b", "c"]
    names = [f"t{number}" for number in range(rng.choice([2, 3, 3, 4]))]
    things = ["bike", "bag"][: rng.choice([1, 1, 2])]
    ends = {train: tuple(rng.sample(towns, 2)) for train in names}
    stated = [fact for hour, train in enumerate(names, 9) for fact in at(train, hour)]
    stated += [starts_from(person, "a") for person in people]
    does: dict[tuple[str, str], str] = {}
    for thing in things:
        stated += [every_use(thing), every_right_for(thing)]
        stated += [every_transfer(thing)] if rng.random() < 0.5 else []
        roll = rng.random()
        if roll < 0.15:
            stated.append(has_object(rng.choice(people), thing))
        elif roll < 0.25:
            stated.append(lies_at(thing, rng.choice(towns)))
        for train in names:
            stated += [needs_right_for(train, thing)] if rng.random() < 0.8 else []
            if rng.random() < 0.45:
                does[train, thing] = rng.choice(["hands_over", "keeps", "carries", "nothing"])
                stated.append(does_with(train, thing, does[train, thing]))
    stated += [offer(train, 3, f"{train}-rack", objects=things) for train in names]
    file = trip(
        people,
        towns,
        [moves(train, *ends[train]) for train in names],
        stated,
        [],
        budgets=[budget("money", *people, objects=things)],
        objects=things,
        object_rights=True,
    )
    plan: list[Step] = []
    for hour, train in enumerate(names, 9):
        if rng.random() < 0.15:
            continue
        riders = tuple(person for person in people if rng.random() < 0.5) or (rng.choice(people),)
        handed = tuple(
            (thing, rng.choice(riders))
            for thing in things
            if does.get((train, thing)) == "hands_over" and rng.random() < 0.6
        )
        carried = tuple(
            thing
            for thing in things
            if does.get((train, thing)) == "carries" and rng.random() < 0.6
        )
        origin, to = ends[train]
        times = (seconds(hour), seconds(hour, 30))
        plan.append(Step(train, origin, to, riders, *times, handed=handed, carried=carried))
    return file, tuple(plan)


def test_the_places_taken_together_are_those_of_each_way_things_can_turn_out() -> None:
    """Checked on random plans by following one way at a time: one place where the OBJECT
    starts, and for each train that might keep it, that it does or that it does not. Each
    way gives the trains where the OBJECT takes a place. The sets that no other set holds
    are the sets that the walk through all the places at once gives."""
    rng = Random(144)
    compared = several = kept = 0
    everywhere = [Where(person=each) for each in ("alex", "jo", "sam")]
    everywhere += [*(Where(place=each) for each in "abc"), Where()]
    for _ in range(1200):
        file, plan = a_plan_on_some_trains(rng)
        world = worst_case(file)
        together = taken_together(file, world, plan)
        for thing in (each.id for each in file.objects):
            actions = {pair: does for pair, does in world.does.items() if pair[1] == thing}
            assert not any(goes_along(world, train, thing) for train, _ in actions)
            might_keep = [pair for pair, does in actions.items() if does == "might_keep"]
            assert set(actions.values()) <= {"might_keep", "hands_over", "keeps", "carries"}
            begins = [world.starts[thing]] if thing in world.starts else everywhere
            alone: set[frozenset[str]] = set()
            for where, each in product(
                begins, product(("keeps", "nothing"), repeat=len(might_keep))
            ):
                does = {**world.does, **dict(zip(might_keep, each, strict=True))}
                known = replace(world, starts={**world.starts, thing: where}, does=does)
                taking = taking_a_place(file, known, plan)
                alone.add(frozenset(train for train, things in taking.items() if thing in things))
            largest = {one for one in alone if not any(one < other for other in alone)}
            assert together.get(thing) == (largest if any(largest) else None)
            compared += 1
            several += len(largest) > 1
            kept += len(largest) > 1 and bool(might_keep)
    assert compared > 1200 and several > 300 and kept > 100
