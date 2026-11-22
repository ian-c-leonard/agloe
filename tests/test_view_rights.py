"""What the page shows of the rights to the OPTIONs of a FILE.

The view sends what the FILE says of the rights to each OPTION: whether people need one, each
BOOKING and each OFFER, and the FACT that the FILE lists every right.
``src/agloe/view/static/rights.js`` puts them in words, as the report words them, says who
uses each right in the plan of the report, and marks what the report names. It has no page in
it, so Node runs it here, through ``view_part.mjs``.

Nothing in it judges a TRIP. Whether everybody who takes part has a right is for the COMPILER
to say: the page names who uses a right only where the report does.
"""

from typing import Any

from agloe.file import read
from tests.stories import EXAMPLES
from tests.test_view_calendar import drawn, in_words, parts, with_its_report

STORY = EXAMPLES / "a-ticket"
FILES = sorted(
    path for path in EXAMPLES.rglob("*.json") if not path.name.endswith(".expected.json")
)
SAYS = "The BOOKINGs and the OFFERs of the FILE, each under the OPTION that it gives a right to."
RED = " A red edge marks what the report names among what rules out every plan."
YELLOW = " A yellow edge marks what the report names in what the FILE does not say."
NEEDED = "People need a right to take part."
NOT_ALL = "Another right to it may exist: the FILE does not say that these are all."
ALL = "The FILE lists every right to it: nobody on the trip holds another or can get one"
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
            "says": "a BOOKING that covers Alex",
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
    assert all(offer["cases"] == [] for offer in skydeck["offers"])


def test_each_kind_of_offer_and_of_set_of_rights_has_its_words() -> None:
    sent = drawn(STORY / "not-bought-yet.json")
    (skydeck, *_) = sent["rights"]
    skydeck["offers"] = [
        {"id": "last-ticket", "places": 1, "price": {"amount": "0.50", "currency": "EUR"}},
        {"id": "desk", "places": 3, "price": None},
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


def test_every_example_shows_its_rights_in_the_words_of_the_report() -> None:
    """Each BOOKING and each OFFER of each FILE is shown, worded as the report words it."""
    asked = [in_words(path) for path in FILES]
    shown = all_rights(
        [sent for sent, _, _ in asked],
        [found for _, found, _ in asked],
        [words for _, _, words in asked],
    )
    bookings = offers = sets = uses = 0
    for path, (sent, found, words), each in zip(FILES, asked, shown, strict=True):
        file = read(path)
        name = f"{path.parent.name}/{path.stem}"
        by_option = {rights["option"]: rights for rights in each["rights"]}
        used = {
            (step["option"], by)
            for step in found.get("itinerary", [])
            for by in step.get("rights", {}).values()
        }
        for option in file.options:
            listed = [*file.bookings(option.id), *file.offers(option.id)]
            if (
                not listed
                and not file.needs_right(option.id)
                and not file.rights_complete(option.id)
            ):
                assert option.id not in by_option, name
                continue
            rights = by_option[option.id]
            called = rights["name"]
            assert [booking["id"] for booking in rights["bookings"]] == [
                fact.id for fact in file.bookings(option.id)
            ], name
            assert [offer["id"] for offer in rights["offers"]] == [
                fact.id for fact in file.offers(option.id)
            ], name
            for booking in rights["bookings"]:
                # Where the report has a line about this BOOKING, the page says the same.
                if f"  {booking['id']}: a BOOKING" in words:
                    bookings += 1
                    covered = booking["says"][len("a BOOKING that covers ") :]
                    stated = f"  {booking['id']}: a BOOKING for {called} covers {covered}"
                    assert stated in words, name
            for offer in rights["offers"]:
                if f"  {offer['id']}: an OFFER" in words:
                    offers += 1
                    said = offer["says"].replace("an OFFER with ", "an OFFER has ", 1)
                    said = said.replace(" that can still", f" for {called} that can still", 1)
                    assert f"  {offer['id']}: {said}" in words, name
            for right in (*rights["bookings"], *rights["offers"]):
                # Somebody uses it in the plan exactly where the report says so.
                if sent["itinerary"]:
                    uses += (option.id, right["id"]) in used
                    assert ("nobody" in right["uses"]) is ((option.id, right["id"]) not in used), (
                        name
                    )
                else:
                    assert right["uses"] is None, name
            complete = file.rights_complete(option.id)
            if complete is not None and f"  {complete.id}: " in words:
                sets += 1
                said = rights["whole"].replace("to it:", f"to {called}:", 1)
                assert f"  {complete.id}: t{said[1:-1]}" in words, name
        assert set(by_option) <= {option.id for option in file.options}, name
    assert min(bookings, uses) > 5
    # Few examples have an OFFER, or a FACT that the FILE lists every right.
    assert min(offers, sets) > 1
