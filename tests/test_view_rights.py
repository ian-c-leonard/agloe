"""What the page shows of the rights to the OPTIONs of a FILE.

The view sends what the FILE says of the rights to each OPTION: whether people need one, each
BOOKING and each OFFER, and the FACT that the FILE lists every right.
``src/agloe/view/static/rights.js`` puts them in words, as the report words them, says who
uses each right in the plan of the report, and marks what the report names. It has no page in
it, so Node runs it here, through ``view_part.mjs``.

Nothing in it judges a TRIP. Whether everybody who takes part has a right is for the COMPILER
to say: the page names who uses a right only where the report does.
"""

import json
import re
from pathlib import Path
from typing import Any

from agloe.file import Offer, read
from agloe.view.trip import holds
from tests.stories import EXAMPLES
from tests.test_view_calendar import drawn, in_words, parts, with_its_report

STORY = EXAMPLES / "a-ticket"
FILES = sorted(
    path for path in EXAMPLES.rglob("*.json") if not path.name.endswith(".expected.json")
)
SAYS = "The BOOKINGs and the OFFERs of the FILE, each under the OPTION that it is for."
RED = " A red edge marks what the report names among what rules out every plan."
YELLOW = " A yellow edge marks what the report names in what the FILE does not say."
NEEDED = "People need a right to take part."
NOT_ALL = (
    "Another right for a PERSON to take part in it may exist:"
    " the FILE does not say that these are all."
)
ALL = (
    "The FILE lists every right for a PERSON to take part in it:"
    " nobody on the trip holds another or can get one"
)
ON_OFFER = "an OFFER with 2 places that can still be bought, for 32.00 USD each"

type Trip = dict[str, Any]
type Rights = dict[str, Any]


def all_rights(
    trips: list[Trip | None],
    reports: list[dict[str, Any] | None] | None = None,
    texts: list[str | None] | None = None,
) -> list[Rights]:
    """What the page shows of the rights to the OPTIONs of each TRIP, by the page's own code."""
    return parts("rights", trips, reports, texts)


def rights_of(name: str) -> Rights:
    """What the page shows of the rights in an example, with the report on it."""
    sent, found, text = in_words(EXAMPLES / f"{name}.json")
    return all_rights([sent], [found], [text])[0]


def test_the_rights_to_an_option_say_who_has_one_and_what_is_on_offer() -> None:
    """Alex has a BOOKING for the Skydeck, and Sam still has to buy one of two places."""
    shown = rights_of("a-ticket/not-bought-yet")
    assert shown["says"] == SAYS
    assert (shown["clash"], shown["asked"]) == (False, False)
    # Nobody needs a right to the talk or to lunch, and the FILE says no more of them.
    (skydeck,) = shown["rights"]
    assert (skydeck["option"], skydeck["name"], skydeck["needs"]) == (
        "skydeck",
        "Skydeck visit",
        NEEDED,
    )
    assert skydeck["bookings"] == [
        {
            "id": "alex-skydeck-ticket",
            "name": "alex-skydeck-ticket",
            # What the BOOKING paid, who paid, and the BUDGET that the money came from.
            "says": (
                "a BOOKING that covers Alex; its payment: 32.00 USD, paid by Alex,"
                " from the trip money"
            ),
            # It states no terms for cancelling or for changing.
            "terms": [],
            # So the report says nothing of what holds now.
            "now": [],
            # The report says which right each PERSON uses, and the page says the same.
            "uses": "In the plan: Alex uses it.",
            "records": ["alex-skydeck-ticket"],
            "clash": [],
            "finds": None,
            "cases": [],
            "asks": [],
        }
    ]
    (offer,) = skydeck["offers"]
    assert (offer["id"], offer["says"], offer["uses"], offer["records"]) == (
        "skydeck-tickets",
        ON_OFFER,
        "In the plan: Sam takes a place of it.",
        ["skydeck-tickets"],
    )
    # The FILE does not say that these are all the rights to the visit.
    assert (skydeck["whole"], skydeck["records"]) == (NOT_ALL, ["skydeck-needs-a-ticket"])


def test_the_rights_mark_what_the_report_names_as_ruling_out_every_plan() -> None:
    """Only Alex has a BOOKING, and a FACT says that the FILE lists every right to the visit."""
    sent, found = with_its_report(STORY / "cannot-work.json")
    (shown,) = all_rights([sent], [found])
    assert shown["says"] == SAYS + RED
    (skydeck,) = shown["rights"]
    assert skydeck["whole"] == f"{ALL}."
    assert skydeck["clash"] == ["skydeck-needs-a-ticket", "skydeck-sold-out"]
    (booking,) = skydeck["bookings"]
    assert booking["clash"] == ["alex-skydeck-ticket"]
    assert booking["finds"] == (
        "The report names alex-skydeck-ticket among what rules out every plan."
    )
    # The report shows no plan, so the page says nothing of who uses the BOOKING.
    assert booking["uses"] is None
    # Only what a report names is marked.
    odd: list[Any] = [None, {}, {**found, "answer": "FEASIBLE"}, {**found, "conflict": "x"}]
    for other in all_rights([sent] * len(odd), odd):
        assert other["clash"] is False
        (skydeck,) = other["rights"]
        assert [each["clash"] for each in (skydeck, *skydeck["bookings"])] == [[], []]


def test_the_rights_mark_what_the_report_says_the_file_does_not_say() -> None:
    """The trip works if a right is found for Sam, or if a place has a price that Sam can pay."""
    shown = rights_of("a-ticket/depends-on-the-price")
    assert shown["says"] == SAYS + YELLOW
    (skydeck,) = shown["rights"]
    # Both cases are about the rights to the visit. The second names the OFFER.
    assert skydeck["cases"] == [0, 1]
    (offer,) = skydeck["offers"]
    assert (
        offer["says"] == "an OFFER with 2 places that can still be bought; nobody knows the price"
    )
    assert offer["cases"] == [1]
    assert offer["asks"] == [
        "The trip works in any of these cases:",
        "2. A place from skydeck-tickets has a price that Sam can pay.",
    ]
    assert all(booking["cases"] == [] for booking in skydeck["bookings"])
    # A case about what a BOOKING paid names that BOOKING.
    (skydeck,) = rights_of("a-ticket/depends-on-the-receipt")["rights"]
    (booking,) = skydeck["bookings"]
    assert (booking["cases"], skydeck["cases"]) == ([0], [0])
    assert booking["asks"] == [
        "The trip works if the FILE states what alex-skydeck-ticket paid and from which BUDGET."
    ]
    # The report gives one plan for that case, in which Sam buys a place of the OFFER. The
    # FILE says all there is to say of the OFFER, so it has no yellow edge.
    assert all(offer["cases"] == [] for offer in skydeck["offers"])


def test_each_kind_of_offer_and_of_set_of_rights_has_its_words() -> None:
    sent = drawn(STORY / "not-bought-yet.json")
    (skydeck, *_) = sent["rights"]
    for_persons: dict[str, Any] = {"objects": [], "names": {}}
    skydeck["offers"] = [
        {"id": "last-ticket", "places": 1, "price": {"amount": "0.50", "currency": "EUR"}}
        | for_persons,
        {"id": "desk", "places": 3, "price": None} | for_persons,
    ]
    skydeck["complete"] = {"record": "every-ticket", "offers": ["last-ticket", "desk"]}
    (shown,) = all_rights([sent])
    (rights,) = shown["rights"]
    assert [offer["says"] for offer in rights["offers"]] == [
        "an OFFER with 1 place that can still be bought, for 0.50 EUR",
        "an OFFER with 3 places that can still be bought; nobody knows the price",
    ]
    assert rights["whole"] == f"{ALL}, except from last-ticket and desk."
    assert rights["records"] == ["skydeck-needs-a-ticket", "every-ticket"]


def test_an_offer_for_objects_says_what_a_place_covers() -> None:
    """Three places on the car deck are on OFFER for the car. The plan takes one of them."""
    (ferry,) = rights_of("a-car-ferry/a-place-on-the-car-deck")["rights"]
    (deck,) = ferry["offers"]
    assert deck["says"] == (
        "an OFFER with 3 places that can still be bought to cover the car, for 90.00 USD each"
    )
    assert deck["uses"] == "In the plan: a place of it covers the car."
    assert ferry["closed"] == []
    # A FACT says that the FILE lists every right for the car, and it names the OFFER. The
    # report shows no plan, so the page says nothing of who takes a place.
    (ferry,) = rights_of("a-car-ferry/the-trip-money-is-three-dollars-short")["rights"]
    assert ferry["closed"] == [
        "The FILE lists every right to it that covers the car: nobody on the trip holds another"
        " or can get one, except from car-deck."
    ]
    (deck,) = ferry["offers"]
    assert deck["uses"] is None and deck["clash"] == ["car-deck"]
    # One place for either car: the OFFER names both, as a list that "or" joins.
    (ferry,) = rights_of("a-car-ferry/one-place-and-two-cars")["rights"]
    (deck,) = ferry["offers"]
    assert deck["says"] == (
        "an OFFER with 1 place that can still be bought to cover the car or Jo's car, for 90.00 USD"
    )
    # A place that is taken only if the OPTION turns out to need the right, and one that the
    # plan does not take.
    sent, found = with_its_report(EXAMPLES / "a-car-ferry" / "a-place-on-the-car-deck.json")
    (buy,) = found["to_buy"]
    (shown,) = all_rights([sent], [{**found, "to_buy": [{**buy, "only_if_needed": True}]}])
    assert shown["rights"][0]["offers"][0]["uses"] == (
        "In the plan: a place of it covers the car, if a right is needed there."
    )
    (shown,) = all_rights([sent], [{**found, "to_buy": []}])
    assert shown["rights"][0]["offers"][0]["uses"] == "In the plan: no place of it is taken."


def test_who_uses_a_right_is_said_only_where_the_report_names_them() -> None:
    sent, found = with_its_report(STORY / "works.json")
    (first, *rest) = found["itinerary"]
    assert first["rights"] == {"alex": "alex-skydeck-ticket", "sam": "sam-skydeck-ticket"}
    (shown,) = all_rights([sent], [found])
    (skydeck,) = shown["rights"]
    assert [booking["uses"] for booking in skydeck["bookings"]] == [
        "In the plan: Alex uses it.",
        "In the plan: Sam uses it.",
    ]
    # Two PERSONs who use one BOOKING, and two who each take a place of one OFFER.
    one = {**first, "rights": {"alex": "alex-skydeck-ticket", "sam": "alex-skydeck-ticket"}}
    (shown,) = all_rights([sent], [{**found, "itinerary": [one, *rest]}])
    (skydeck,) = shown["rights"]
    assert [booking["uses"] for booking in skydeck["bookings"]] == [
        "In the plan: Alex and Sam use it.",
        "In the plan: nobody uses it.",
    ]
    bought, report = with_its_report(STORY / "not-bought-yet.json")
    (visit, *others) = report["itinerary"]
    both = {**visit, "rights": {"alex": "skydeck-tickets", "sam": "skydeck-tickets"}}
    (shown,) = all_rights([bought], [{**report, "itinerary": [both, *others]}])
    (skydeck,) = shown["rights"]
    assert skydeck["offers"][0]["uses"] == "In the plan: Alex and Sam each take a place of it."
    # A report that states no right in a shape the page can read names nobody.
    odd: list[Any] = [
        {**found, "itinerary": "x"},
        {**found, "itinerary": [{**first, "rights": ["alex-skydeck-ticket"]}, *rest]},
        {**found, "itinerary": [{**first, "rights": {"alex": 1}}, *rest]},
        {**found, "itinerary": [None, *rest]},
    ]
    for other in all_rights([sent] * len(odd), odd):
        (skydeck,) = other["rights"]
        assert [booking["uses"] for booking in skydeck["bookings"]] == [
            "In the plan: nobody uses it."
        ] * 2


def test_a_booking_names_the_objects_that_it_covers(tmp_path: Path) -> None:
    """One BOOKING for the car ferry covers Alex, Sam and the car, and the plan uses it for
    all three. A second BOOKING that covers the car alone is drawn too, and nobody uses it:
    the report names the first one for the car."""
    shown = rights_of("a-car-ferry/booked")
    (ferry,) = shown["rights"]
    (tickets,) = ferry["bookings"]
    assert tickets["says"] == "a BOOKING that covers Alex, Sam and the car"
    assert tickets["uses"] == "In the plan: Alex, Sam and the car use it."
    content = json.loads((EXAMPLES / "a-car-ferry" / "booked.json").read_text())
    alone = {"id": "car-ticket", "booking": {"option": "ferry", "covers": ["car"]}}
    content["facts"].append(alone)
    path = tmp_path / "trip.json"
    path.write_text(json.dumps(content))
    sent, found, text = in_words(path)
    assert holds(sent)
    (ferry,) = all_rights([sent], [found], [text])[0]["rights"]
    assert [(booking["says"], booking["uses"]) for booking in ferry["bookings"]] == [
        (
            "a BOOKING that covers Alex, Sam and the car",
            "In the plan: Alex, Sam and the car use it.",
        ),
        ("a BOOKING that covers the car", "In the plan: nobody uses it."),
    ]


def test_the_rights_card_says_what_it_does_not_cover_for_an_object(tmp_path: Path) -> None:
    """The ferry needs a right for the car, and no BOOKING covers the car. A FACT says that
    the FILE lists every right for a PERSON to take part in the ferry, and the card says
    it in those words: the report still asks for a right for the car. An OPTION that only
    needs a right for an OBJECT has a card too."""
    content = json.loads((EXAMPLES / "a-car-ferry" / "the-car-has-no-ticket.json").read_text())
    content["facts"].append({"id": "sold-out", "complete": {"rights_to": "ferry"}})
    path = tmp_path / "trip.json"
    path.write_text(json.dumps(content))
    sent, found, text = in_words(path)
    assert "works if a right to Car ferry to Muskegon is found that covers the car." in text
    whole = all_rights([sent], [found], [text])[0]
    (ferry,) = whole["rights"]
    assert ferry["things"] == "It needs a right for the car."
    assert (ferry["whole"], ferry["closed"]) == (f"{ALL}.", [])
    assert "ferry-needs-a-car-ticket" in ferry["records"]
    # The right for the car is the one case of the report, and the card is marked with it.
    assert (ferry["cases"], whole["asked"]) == ([0], True)
    # A FACT says that the FILE lists every right to the ferry that covers the car. The
    # card says so, beside what it says of the PERSONs, and it is marked where the report
    # names that FACT among what rules out every plan.
    content["facts"].append(
        {"id": "the-car-deck-is-full", "complete": {"rights_to": "ferry", "for_object": "car"}}
    )
    path.write_text(json.dumps(content))
    sent, found, text = in_words(path)
    assert found["answer"] == "INFEASIBLE"
    (ferry,) = all_rights([sent], [found], [text])[0]["rights"]
    for_the_car = "The FILE lists every right to it that covers the car"
    assert ferry["closed"] == [f"{for_the_car}: nobody on the trip holds another or can get one."]
    assert (
        f"  the-car-deck-is-full: t{ferry['closed'][0][1:-1]}".replace(
            "to it that", "to Car ferry to Muskegon that"
        )
        in text
    )
    assert (ferry["whole"], "the-car-deck-is-full" in ferry["clash"]) == (f"{ALL}.", True)
    # Where the car is called Alex too, the card names it as the report does, with its id.
    content["objects"][0]["name"] = "Alex"
    path.write_text(json.dumps(content))
    sent, found, text = in_words(path)
    (ferry,) = all_rights([sent], [found], [text])[0]["rights"]
    assert ferry["closed"] == [
        "The FILE lists every right to it that covers Alex (car):"
        " nobody on the trip holds another or can get one."
    ]
    assert "that covers Alex (car): nobody on the trip" in text
    content["objects"][0]["name"] = "car and trailer"
    path.write_text(json.dumps(content))
    sent, found, text = in_words(path)
    (ferry,) = all_rights([sent], [found], [text])[0]["rights"]
    assert ferry["closed"][0].startswith('The FILE lists every right to it that covers "car and')
    assert 'that covers "car and trailer": nobody on the trip' in text
    content["objects"][0]["name"] = "the car"
    content["facts"] = [fact for fact in content["facts"] if fact["id"] != "the-car-deck-is-full"]
    # Nobody needs a right to take part in the ferry, and it has no BOOKING: it still needs
    # a right for the car, so it has a card.
    for fact in content["facts"]:
        if fact["id"] == "ferry-needs-a-ticket":
            fact["needs_right"] = False
    content["facts"] = [
        fact for fact in content["facts"] if fact["id"] not in ("sold-out", "ferry-tickets")
    ]
    path.write_text(json.dumps(content))
    sent, found, text = in_words(path)
    (ferry,) = all_rights([sent], [found], [text])[0]["rights"]
    assert (ferry["things"], ferry["bookings"]) == ("It needs a right for the car.", [])
    # A PERSON and an OBJECT that show one name show their ids, as in the report.
    content = json.loads((EXAMPLES / "a-car-ferry" / "booked.json").read_text())
    content["persons"][0]["name"] = "Scout"
    content["objects"][0]["name"] = "Scout"
    path.write_text(json.dumps(content))
    sent, found, text = in_words(path)
    (ferry,) = all_rights([sent], [found], [text])[0]["rights"]
    (tickets,) = ferry["bookings"]
    assert tickets["says"] == "a BOOKING that covers Scout (alex), Sam and Scout (car)"
    assert "covers Scout (alex), Sam and Scout (car)" in text
    assert tickets["uses"] == "In the plan: Scout (alex), Sam and Scout (car) use it."
    # With a BOOKING of its own for the car, each of the two still shows its id.
    for fact in content["facts"]:
        if fact["id"] == "ferry-tickets":
            fact["booking"]["covers"] = ["alex", "sam"]
    content["facts"].append({"id": "car-ticket", "booking": {"option": "ferry", "covers": ["car"]}})
    path.write_text(json.dumps(content))
    sent, found, text = in_words(path)
    (ferry,) = all_rights([sent], [found], [text])[0]["rights"]
    assert [(booking["says"], booking["uses"]) for booking in ferry["bookings"]] == [
        ("a BOOKING that covers Scout (alex) and Sam", "In the plan: Scout (alex) and Sam use it."),
        ("a BOOKING that covers Scout (car)", "In the plan: Scout (car) uses it."),
    ]
    assert "covers Scout (alex) and Sam" in text and "covers Scout (car)" in text
    # Sam is called Scout too. Two PERSONs show their ids wherever they are named, and the
    # car still shows its own on its receipt.
    content["persons"][1]["name"] = "Scout"
    path.write_text(json.dumps(content))
    sent, found, text = in_words(path)
    (ferry,) = all_rights([sent], [found], [text])[0]["rights"]
    assert [(booking["says"], booking["uses"]) for booking in ferry["bookings"]] == [
        (
            "a BOOKING that covers Scout (alex) and Scout (sam)",
            "In the plan: Scout (alex) and Scout (sam) use it.",
        ),
        ("a BOOKING that covers Scout (car)", "In the plan: Scout (car) uses it."),
    ]
    assert "  car-ticket: a BOOKING for Car ferry to Muskegon covers Scout (car)\n" in text
    # Two spellings that a page shows alike count as one name.
    content["persons"][0]["name"], content["persons"][1]["name"] = "Zoe\u0308", "Sam"
    content["objects"][0]["name"] = "Zo\u00eb"
    path.write_text(json.dumps(content))
    sent, found, text = in_words(path)
    (ferry,) = all_rights([sent], [found], [text])[0]["rights"]
    assert [booking["says"] for booking in ferry["bookings"]] == [
        "a BOOKING that covers Zoe\u0308 (alex) and Sam",
        "a BOOKING that covers Zo\u00eb (car)",
    ]


def test_a_booking_says_what_it_paid_as_far_as_the_file_says() -> None:
    def said(name: str) -> list[str]:
        (skydeck,) = rights_of(f"a-ticket/{name}")["rights"]
        return [booking["says"] for booking in skydeck["bookings"]]

    # A payment that names who paid, and no BUDGET.
    assert said("works") == [
        "a BOOKING that covers Alex; its payment: 32.00 USD, paid by Alex",
        "a BOOKING that covers Sam; its payment: 32.00 USD, paid by Sam",
    ]
    # The FILE has a cap, and the BOOKING states no payment: no cap can be shown to hold.
    assert said("depends-on-the-receipt") == ["a BOOKING that covers Alex; it states no payment"]
    # A FILE with no cap says nothing of a payment that a BOOKING does not state.
    sent = drawn(STORY / "depends-on-the-receipt.json")
    for budget in sent["budgets"]:
        budget["caps"] = []
    (shown,) = all_rights([sent])
    assert [booking["says"] for booking in shown["rights"][0]["bookings"]] == [
        "a BOOKING that covers Alex"
    ]
    # A payment of nothing says so.
    sent = drawn(STORY / "works.json")
    sent["rights"][0]["bookings"][0]["paid"] = {
        "amount": "0.00",
        "currency": "USD",
        "budget": None,
        "by": None,
    }
    (shown,) = all_rights([sent])
    assert shown["rights"][0]["bookings"][0]["says"] == (
        "a BOOKING that covers Alex; its payment: nothing"
    )


def test_a_place_bought_only_if_the_option_needs_a_right_says_so(tmp_path: Path) -> None:
    """The FILE does not say whether the Skydeck needs a right. Sam has none."""
    content = json.loads((STORY / "not-bought-yet.json").read_text())
    content["facts"] = [fact for fact in content["facts"] if fact["id"] != "skydeck-needs-a-ticket"]
    path = tmp_path / "trip.json"
    path.write_text(json.dumps(content))
    sent, found, words = in_words(path)
    assert "Sam still has to buy a right to this if it needs one, from skydeck-tickets" in words
    assert [buy["only_if_needed"] for buy in found["to_buy"]] == [True]
    (shown,) = all_rights([sent], [found], [words])
    (skydeck,) = shown["rights"]
    assert skydeck["needs"] == "The FILE does not say whether people need a right to take part."
    (offer,) = skydeck["offers"]
    assert offer["uses"] == ("In the plan: Sam takes a place of it, if the OPTION needs a right.")
    # Alex is covered by a BOOKING either way.
    assert [booking["uses"] for booking in skydeck["bookings"]] == ["In the plan: Alex uses it."]


def test_an_option_that_needs_a_right_is_shown_though_the_file_has_none_for_it() -> None:
    sent = drawn(STORY / "works.json")
    (skydeck, *_) = sent["rights"]
    skydeck["bookings"] = []
    (shown,) = all_rights([sent])
    (rights,) = shown["rights"]
    assert (rights["needs"], rights["bookings"], rights["offers"]) == (NEEDED, [], [])
    assert rights["whole"] == NOT_ALL
    # A FILE that says only that nobody needs a right, or nothing of rights, shows none.
    empty: Rights = {"says": "", "clash": False, "asked": False, "rights": []}
    sent["rights"] = sent["rights"][1:]
    assert all(each["needs"]["needed"] is False for each in sent["rights"])
    nothing = drawn(STORY / "works.json")
    nothing["rights"] = []
    assert all_rights([sent, nothing, None]) == [empty] * 3


def a_ferry_with(tmp_path: Path, name: str, change: Any) -> Path:
    """The booked car ferry with a change made to its content, as a FILE of its own."""
    content = json.loads((EXAMPLES / "a-car-ferry" / "booked.json").read_text())
    change(content)
    path = tmp_path / name / "trip.json"
    path.parent.mkdir()
    path.write_text(json.dumps(content))
    return path


def test_an_offer_that_expires_says_until_when_and_whether_it_has_expired() -> None:
    until = "until 5:00 pm (UTC-5) on Thursday 13 May 2027, for 32.00 USD each"
    for name, says in (
        ("the-offer-ends-on-thursday", f"an OFFER with 2 places that can still be bought {until}"),
        ("the-offer-has-expired", f"an OFFER that had 2 places that could be bought {until}"),
        # With no time now, nobody knows whether a place can still be bought.
        (
            "nobody-said-whether-the-offer-has-expired",
            f"an OFFER with 2 places that can be bought {until}",
        ),
    ):
        (skydeck,) = [
            each for each in rights_of(f"a-ticket/{name}")["rights"] if each["option"] == "skydeck"
        ]
        (tickets,) = skydeck["offers"]
        assert tickets["says"] == says, name
    # A COMPLETE set names an OFFER as long as the FILE holds it, and marks an expired one.
    (skydeck,) = [
        each
        for each in rights_of("a-ticket/expired-and-sold-out")["rights"]
        if each["option"] == "skydeck"
    ]
    assert skydeck["whole"].endswith("or can get one, except from skydeck-tickets (expired).")


def bookings_of(name: str) -> dict[str, Rights]:
    """The BOOKINGs that the page shows for an example about the room, by their ids."""
    shown = rights_of(f"the-room/{name}")
    return {booking["id"]: booking for each in shown["rights"] for booking in each["bookings"]}


WEDNESDAY = "6:00 pm (UTC-5) on Wednesday 12 May 2027"
CHANGE = "The fee for a change, apart from any difference in price"


def test_a_booking_says_what_cancelling_and_changing_cost_as_far_as_the_file_says() -> None:
    """The room can be cancelled at no cost until Wednesday at six. The ticket cannot."""
    bookings = bookings_of("on-monday")
    # Each kind of terms is one sentence, with its terms in the order of time.
    assert bookings["room"]["terms"] == [
        f"What cancelling costs: at first, nothing; from {WEDNESDAY}, 189.00 USD."
    ]
    # One term that holds from when the BOOKING was made holds at any time.
    assert bookings["skydeck-ticket"]["terms"] == ["What cancelling costs at any time: 32.00 USD."]
    # The card still says what the BOOKING covers, and who uses it in the plan.
    assert bookings["room"]["says"] == "a BOOKING that covers Alex"
    assert bookings["room"]["uses"] == "In the plan: Alex uses it."
    # A term that states no cost says that the FILE does not say.
    assert bookings_of("free-until-wednesday")["room"]["terms"] == [
        f"What cancelling costs: at first, nothing; from {WEDNESDAY}, the FILE does not say."
    ]
    # A cost in two currencies names both, and adds nothing up.
    assert bookings_of("points-and-dollars")["room"]["terms"] == [
        f"What cancelling costs: at first, nothing; from {WEDNESDAY}, 30000 hotel-points and"
        " 25.00 USD."
    ]
    # A term can say that the seller accepts none.
    assert bookings_of("the-ticket-cannot-be-cancelled")["skydeck-ticket"]["terms"] == [
        "What cancelling costs at any time: the seller accepts no cancellation."
    ]
    # Terms for changing state a fee, apart from what the changed BOOKING costs more or less.
    assert bookings_of("a-change")["room"]["terms"] == [
        f"What cancelling costs: at first, nothing; from {WEDNESDAY}, 189.00 USD.",
        f"{CHANGE}: at first, nothing; from 12:00 pm (UTC-5) on Tuesday 11 May 2027, 25.00 USD.",
    ]
    assert bookings_of("no-change-on-thursday")["room"]["terms"][1].endswith(
        ", the seller accepts no change."
    )
    # A BOOKING that states one kind of terms says nothing of the other.
    assert bookings_of("a-change")["skydeck-ticket"]["terms"] == [
        "What cancelling costs at any time: 32.00 USD."
    ]


def test_a_term_that_starts_at_a_time_says_nothing_of_the_time_before(tmp_path: Path) -> None:
    """The only term of the room starts on Wednesday at six. What cancelling costs before
    that, the FILE does not say, and neither does the page: such a term holds at no other
    time."""
    content = json.loads((EXAMPLES / "the-room" / "on-monday.json").read_text())
    room = next(fact for fact in content["facts"] if fact["id"] == "room")
    room["booking"]["cancelling"] = room["booking"]["cancelling"][1:]
    path = tmp_path / "trip.json"
    path.write_text(json.dumps(content))
    sent, found, text = in_words(path)
    (shown,) = all_rights([sent], [found], [text])
    bookings = {booking["id"]: booking for each in shown["rights"] for booking in each["bookings"]}
    assert bookings["room"]["terms"] == [f"What cancelling costs: from {WEDNESDAY}, 189.00 USD."]
    tickets = rights_of("a-ticket/works")["rights"][0]["bookings"]
    assert [ticket["terms"] for ticket in tickets] == [[], []]


def test_a_booking_with_dated_terms_says_what_the_report_says_holds_now(tmp_path: Path) -> None:
    """Which term holds at the time now is for the COMPILER to say. The card says it where
    the report does, in the report's words for the cost."""
    # It is Monday, and the room can be cancelled at no cost until Wednesday at six.
    bookings = bookings_of("on-monday")
    assert bookings["room"]["now"] == ["The report says that cancelling costs nothing now."]
    # One term that holds at any time says its cost already.
    assert bookings["skydeck-ticket"]["now"] == []
    # It is Wednesday at six: the later term holds.
    assert bookings_of("at-six-on-wednesday")["room"]["now"] == [
        "The report says that cancelling costs 189.00 USD now."
    ]
    # Both kinds of terms, each with what holds now.
    assert bookings_of("a-change")["room"]["now"] == [
        "The report says that cancelling costs nothing now.",
        "The report says that the fee for a change is nothing now, apart from any difference in"
        " price.",
    ]
    # On Thursday the seller accepts no change.
    assert bookings_of("no-change-on-thursday")["room"]["now"] == [
        "The report says that cancelling costs 189.00 USD now.",
        "The report says that the seller accepts no change now.",
    ]
    # A FILE that states no time now has no report of what holds now.
    assert bookings_of("nobody-said-what-time-it-is")["room"]["now"] == []
    # The term that holds states no cost: the report says that the FILE does not say.
    content = json.loads((EXAMPLES / "the-room" / "free-until-wednesday.json").read_text())
    today = next(fact for fact in content["facts"] if "now" in fact)
    today["now"] = "2027-05-13T09:00:00-05:00[America/Chicago]"
    path = tmp_path / "trip.json"
    path.write_text(json.dumps(content))
    sent, found, words = in_words(path)
    (shown,) = all_rights([sent], [found], [words])
    (room,) = [b for each in shown["rights"] for b in each["bookings"] if b["id"] == "room"]
    assert room["now"] == ["The report says that the FILE does not say what cancelling costs now."]
    # Before the report comes, the card says the terms and nothing of what holds now.
    (early,) = all_rights([sent])
    (room,) = [b for each in early["rights"] for b in each["bookings"] if b["id"] == "room"]
    assert (len(room["terms"]), room["now"]) == (1, [])


def room_with(tmp_path: Path, change: Any) -> tuple[dict[str, Rights], dict[str, Any]]:
    """The BOOKINGs that the page shows for the room on Monday, after a change to the FILE,
    by their ids, and the report on that FILE as JSON."""
    content = json.loads((EXAMPLES / "the-room" / "on-monday.json").read_text())
    change(content)
    path = tmp_path / "trip.json"
    path.write_text(json.dumps(content))
    sent, found, words = in_words(path)
    (shown,) = all_rights([sent], [found], [words])
    cards = {booking["id"]: booking for each in shown["rights"] for booking in each["bookings"]}
    return cards, found


def test_each_booking_says_what_holds_now_for_itself(tmp_path: Path) -> None:
    """Two BOOKINGs have dated terms, and other costs hold for each on Monday."""
    thursday = "2027-05-13T18:00:00-05:00[America/Chicago]"

    def dated_ticket(content: Any) -> None:
        ticket = next(fact for fact in content["facts"] if fact["id"] == "skydeck-ticket")
        ticket["booking"]["cancelling"] = [
            {"costs": [{"amount": "32.00", "currency": "USD"}]},
            {"from": thursday, "costs": [{"amount": "50.00", "currency": "USD"}]},
        ]

    cards, _ = room_with(tmp_path, dated_ticket)
    assert cards["room"]["now"] == ["The report says that cancelling costs nothing now."]
    assert cards["skydeck-ticket"]["now"] == [
        "The report says that cancelling costs 32.00 USD now."
    ]


def test_a_cost_that_holds_at_any_time_is_not_said_as_the_cost_now(tmp_path: Path) -> None:
    """The room has two terms with one cost, and nobody has said what time it is. The report
    states that cost for any time. The card says the two terms, and nothing of the time now."""

    def one_cost_and_no_time_now(content: Any) -> None:
        content["facts"] = [fact for fact in content["facts"] if "now" not in fact]
        room = next(fact for fact in content["facts"] if fact["id"] == "room")
        for term in room["booking"]["cancelling"]:
            term["costs"] = [{"amount": "189.00", "currency": "USD"}]

    cards, found = room_with(tmp_path, one_cost_and_no_time_now)
    assert "room" in [row["booking"] for row in found["cancelling_at_any_time"]]
    assert "cancelling_now" not in found
    assert cards["room"]["terms"] == [
        f"What cancelling costs: at first, 189.00 USD; from {WEDNESDAY}, 189.00 USD."
    ]
    assert cards["room"]["now"] == []


def test_every_example_says_what_holds_now_in_the_words_of_its_report() -> None:
    """For every BOOKING whose terms of a kind are dated, the card says what the report says
    holds now, and nothing where the report has no row for it. The cost is in the words of
    the report's row for that BOOKING, under its heading for the time now."""
    heads = {
        "cancelling": "What cancelling costs now:",
        "changing": "The fee for a change now, apart from any difference in price:",
    }

    def sentence(kind: str, value: str) -> str:
        """What the card says for one row of the report, from the words of that row."""
        if value.startswith("the seller accepts no "):
            return f"The report says that {value} now."
        if value == "the FILE does not say" and kind == "cancelling":
            return "The report says that the FILE does not say what cancelling costs now."
        if value == "the FILE does not say":
            return "The report says that the FILE does not state the fee for a change now."
        if kind == "cancelling":
            return f"The report says that cancelling costs {value} now."
        apart = ", apart from any difference in price"
        return f"The report says that the fee for a change is {value} now{apart}."

    asked = [in_words(path) for path in FILES]
    shown = all_rights(
        [sent for sent, _, _ in asked],
        [found for _, found, _ in asked],
        [words for _, _, words in asked],
    )
    held: list[str] = []
    for path, (sent, _, words), each in zip(FILES, asked, shown, strict=True):
        name = f"{path.parent.name}/{path.stem}"
        rows: dict[tuple[str, str], str] = {}
        over = ""
        for line in words.split("\n"):
            if not line.startswith("  "):
                over = line
            elif ", the BOOKING for " in line and ": " in line:
                rows[over, line.strip().split(",")[0]] = line.rsplit(": ", 1)[1]
        terms = {
            booking["id"]: booking["terms"]
            for rights in sent["rights"]
            for booking in rights["bookings"]
        }
        for booking in (booking for rights in each["rights"] for booking in rights["bookings"]):
            expected: list[str] = []
            for kind, heading in heads.items():
                stated = terms[booking["id"]][kind]
                dated = bool(stated) and not (len(stated) == 1 and stated[0]["since"] is None)
                if dated and (heading, booking["id"]) in rows:
                    expected.append(sentence(kind, rows[heading, booking["id"]]))
                    held.append(rows[heading, booking["id"]])
            assert booking["now"] == expected, (name, booking["id"])
    assert {"nothing", "189.00 USD", "the seller accepts no change"} <= set(held), set(held)


def test_the_part_says_the_time_now_that_the_file_states() -> None:
    """Which term holds, and whether an OFFER has expired, turns on the time now."""
    now = " The FILE states the time now: 9:00 am (UTC-5) on Monday 10 May 2027."
    assert rights_of("the-room/on-monday")["says"] == SAYS + now
    assert rights_of("a-ticket/the-offer-ends-on-thursday")["says"] == SAYS + now
    # A FILE with terms or with an OFFER that expires, and no time now, says that it has none.
    unsaid = " The FILE does not state the time now."
    assert rights_of("the-room/nobody-said-what-time-it-is")["says"] == SAYS + unsaid
    assert rights_of("a-ticket/nobody-said-whether-the-offer-has-expired")["says"].startswith(
        SAYS + unsaid
    )
    # A FILE with neither says nothing of the time now.
    assert rights_of("a-ticket/works")["says"] == SAYS


def test_every_example_words_a_cost_as_its_report_does() -> None:
    """Where a BOOKING has one term that holds at any time, the report states that cost in
    its last part: for the time now, or for any time. The page says the same words."""
    heads = {
        "What cancelling costs": (
            "What cancelling costs now:",
            "What cancelling costs at any time:",
        ),
        f"{CHANGE.removesuffix(', apart from any difference in price')}": (
            "The fee for a change now, apart from any difference in price:",
            "The fee for a change at any time, apart from any difference in price:",
        ),
    }
    asked = [in_words(path) for path in FILES]
    shown = all_rights(
        [sent for sent, _, _ in asked],
        [found for _, found, _ in asked],
        [words for _, _, words in asked],
    )
    held: list[str] = []
    for path, (_, _, words), each in zip(FILES, asked, shown, strict=True):
        name = f"{path.parent.name}/{path.stem}"
        lines = words.split("\n")
        # What the report says of each BOOKING under each of its headings about a cost.
        rows: dict[tuple[str, str], str] = {}
        over = ""
        for line in lines:
            if not line.startswith("  "):
                over = line
            elif ", the BOOKING for " in line and ": " in line:
                rows[over, line.strip().split(",")[0]] = line.rsplit(": ", 1)[1]
        for booking in (booking for rights in each["rights"] for booking in rights["bookings"]):
            for sentence in booking["terms"]:
                start, _, value = sentence.partition(": ")
                for head, (now, always) in heads.items():
                    if not start.startswith(f"{head} at any time"):
                        continue
                    # The report states the cost under one of its two headings: for the
                    # time now where the FILE states it, and for any time where it does not.
                    under = [each for each in (now, always) if (each, booking["id"]) in rows]
                    assert len(under) == 1, (name, sentence)
                    assert value == f"{rows[under[0], booking['id']]}.", (name, sentence)
                    held.append(value)
    # A cost in dollars, and a seller who accepts none.
    assert len(held) >= 10
    assert {"32.00 USD.", "the seller accepts no cancellation."} <= set(held), set(held)


def test_every_example_shows_its_rights_in_the_words_of_the_report(tmp_path: Path) -> None:
    """Each BOOKING and each OFFER of each FILE is shown, worded as the report words it.

    Two more FILEs come with the examples. On one car ferry nobody needs a right to take
    part, and the ferry needs a right for the car that no BOOKING covers. On the other the
    car has a BOOKING of its own."""

    def free_entry(content: Any) -> None:
        for fact in content["facts"]:
            if fact["id"] == "ferry-needs-a-ticket":
                fact["needs_right"] = False
        content["facts"] = [fact for fact in content["facts"] if fact["id"] != "ferry-tickets"]

    def two_receipts(content: Any) -> None:
        for fact in content["facts"]:
            if fact["id"] == "ferry-tickets":
                fact["booking"]["covers"] = ["alex", "sam"]
        receipt = {"id": "car-ticket", "booking": {"option": "ferry", "covers": ["car"]}}
        content["facts"].append(receipt)

    def a_name_with_nobody_in_it(content: Any) -> None:
        content["objects"][0]["name"] = "the car nobody washed"

    more = [
        a_ferry_with(tmp_path, "free-entry", free_entry),
        a_ferry_with(tmp_path, "two-receipts", two_receipts),
        a_ferry_with(tmp_path, "a-name", a_name_with_nobody_in_it),
    ]
    files = [*FILES, *more]
    asked = [in_words(path) for path in files]
    shown = all_rights(
        [sent for sent, _, _ in asked],
        [found for _, found, _ in asked],
        [words for _, _, words in asked],
    )
    bookings = offers = sets = uses = payments = 0
    cards: dict[str, list[str]] = {}
    for path, (sent, found, words), each in zip(files, asked, shown, strict=True):
        file = read(path)
        name = f"{path.parent.name}/{path.stem}"
        by_option = {rights["option"]: rights for rights in each["rights"]}
        cards[path.parent.name] = sorted(by_option)
        # A right is used by a PERSON who takes part, or it covers an OBJECT there.
        used = {
            (step["option"], by)
            for step in found.get("itinerary", [])
            for by in step.get("rights", {}).values()
        } | {
            (use["option"], use["booking"] or use.get("offer"))
            for thing in found.get("objects", [])
            for use in thing.get("covered_in", [])
        }
        for option in file.options:
            # Each OFFER for the OPTION: for PERSONs, or for the OBJECTs it names.
            on_offer = [
                fact for fact in file.facts if isinstance(fact, Offer) and fact.option == option.id
            ]
            listed = [*file.bookings(option.id), *on_offer]
            if (
                not listed
                and not file.needs_right(option.id)
                and not file.rights_complete(option.id)
                and not any(file.needs_right_for(option.id, thing.id) for thing in file.objects)
            ):
                assert option.id not in by_option, name
                continue
            rights = by_option[option.id]
            called = rights["name"]
            assert [booking["id"] for booking in rights["bookings"]] == [
                fact.id for fact in file.bookings(option.id)
            ], name
            assert [offer["id"] for offer in rights["offers"]] == [fact.id for fact in on_offer], (
                name
            )
            for booking in rights["bookings"]:
                # Where the report has a line about this BOOKING, the page says the same.
                if f"  {booking['id']}: a BOOKING" in words:
                    bookings += 1
                    said = booking["says"][len("a BOOKING that covers ") :]
                    covered, _, payment = said.partition("; ")
                    stated = f"  {booking['id']}: a BOOKING for {called} covers {covered}"
                    # The list of who is covered ends there: the line ends, or says more.
                    assert f"{stated}\n" in words or f"{stated}; " in words, name
                    # A report on a FILE with a cap says what the BOOKING paid on that line.
                    if file.caps:
                        assert f"{stated}; {payment}" in words, name
                # Where the report lists what the BOOKINGs paid, the page says the same.
                paid = booking["says"].partition("; its payment: ")[2]
                if paid and "What the BOOKINGs state that they paid:" in words:
                    payments += 1
                    assert f"  {booking['id']}: {paid}" in words, name
            for offer in rights["offers"]:
                if f"  {offer['id']}: an OFFER" in words:
                    offers += 1
                    # The card gives the time of expiry with its offset from UTC, and the
                    # report only where its times have more than one offset.
                    said = re.sub(r" \(UTC[^)]*\)", "", offer["says"])
                    said = said.replace("an OFFER with ", "an OFFER has ", 1)
                    said = said.replace(" that can ", f" for {called} that can ", 1)
                    # An OFFER that has expired had its places.
                    said = said.replace("an OFFER that had ", "an OFFER had ", 1)
                    said = said.replace(" that could be", f" for {called} that could be", 1)
                    assert f"  {offer['id']}: {said}" in words, name
            for right in (*rights["bookings"], *rights["offers"]):
                # Somebody uses it in the plan exactly where the report says so.
                if sent["itinerary"]:
                    uses += (option.id, right["id"]) in used
                    unused = (
                        "In the plan: nobody uses it.",
                        "In the plan: nobody takes a place of it.",
                        "In the plan: no place of it is taken.",
                    )
                    assert (right["uses"] in unused) is ((option.id, right["id"]) not in used), name
                else:
                    assert right["uses"] is None, name
            complete = file.rights_complete(option.id)
            if complete is not None and f"  {complete.id}: " in words:
                sets += 1
                said = rights["whole"].replace("part in it:", f"part in {called}:", 1)
                assert f"  {complete.id}: t{said[1:-1]}" in words, name
        assert set(by_option) <= {option.id for option in file.options}, name
    assert min(bookings, uses) > 5
    assert payments > 2
    assert (cards["free-entry"], cards["two-receipts"]) == (["ferry"], ["ferry"])
    # Few examples have an OFFER, or a FACT that the FILE lists every right.
    assert min(offers, sets) > 1
