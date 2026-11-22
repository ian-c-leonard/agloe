"""What the page shows of the BUDGETs of a FILE.

The view sends the BUDGETs with each report: who may draw on each, the currencies it holds,
and each cap on what the TRIP spends from it. It sends what each BOOKING paid.
``src/agloe/view/static/budgets.js`` puts them in words, as the report words them, and marks
what the report names. It has no page in it, so Node runs it here, through ``view_part.mjs``.

Nothing in it judges a TRIP, and nothing in it adds up money. Whether a cap holds is for the
COMPILER to say.
"""

from typing import Any

from agloe.file import Booking, read
from tests.stories import EXAMPLES
from tests.test_view_calendar import drawn, in_words, parts, with_its_report

STORY = EXAMPLES / "a-ticket"
FILES = sorted(
    path for path in EXAMPLES.rglob("*.json") if not path.name.endswith(".expected.json")
)
SAYS = (
    "The BUDGETs of the FILE, each with who may draw on it, the caps on it, and what the"
    " BOOKINGs state that they paid from it."
)
RED = " A red edge marks what the report names among what rules out every plan."
NO_CAP = "The FILE sets no cap on what the TRIP spends from it."

type Trip = dict[str, Any]
type Budgets = dict[str, Any]


def all_budgets(
    trips: list[Trip | None],
    reports: list[dict[str, Any] | None] | None = None,
    texts: list[str | None] | None = None,
) -> list[Budgets]:
    """What the page shows of the BUDGETs of each TRIP, by the page's own code."""
    return parts("budgets", trips, reports, texts)


def budgets_of(name: str) -> Budgets:
    """What the page shows of the BUDGETs of an example, with the report on it."""
    sent, found, text = in_words(EXAMPLES / f"{name}.json")
    return all_budgets([sent], [found], [text])[0]


def test_a_budget_says_who_may_draw_on_it_its_caps_and_what_was_paid_from_it() -> None:
    """The trip money is for Alex and Sam. The TRIP spends at most 200.00 USD from it."""
    shown = budgets_of("a-ticket/within-the-cap")
    assert shown["says"] == SAYS
    assert (shown["clash"], shown["asked"], shown["unnamed"]) == (False, False, [])
    (money,) = shown["budgets"]
    assert (money["id"], money["name"], money["holds"]) == (
        "trip-money",
        "the trip money",
        "For Alex and Sam. It holds USD.",
    )
    assert money["caps"] == [
        {
            "id": "trip-cap",
            "name": "trip-cap",
            "says": "the TRIP spends at most 200.00 USD from it",
            # What the report says its plan charges to the cap, in the report's own words.
            "plan": "In the plan: 32.00 paid; 32.00 still to buy; 136.00 left.",
            "records": ["trip-cap"],
            "clash": [],
            "finds": None,
            "cases": [],
            "asks": [],
        }
    ]
    # Alex's BOOKING states that it paid 32.00 USD from this BUDGET.
    (paid,) = money["payments"]
    assert (paid["id"], paid["says"], paid["records"]) == (
        "alex-skydeck-ticket",
        "32.00 USD, paid by Alex",
        ["alex-skydeck-ticket"],
    )
    assert money["whole"] is None


def test_a_cap_says_what_a_plan_charges_to_it_only_where_the_report_says_so() -> None:
    sent, found, words = in_words(STORY / "within-the-cap.json")
    assert "\nThe caps:\n  trip-cap: at most 200.00 USD from the trip money: 32.00 paid;" in words
    # With no report in words, the page has nothing to say of the plan.
    (shown,) = all_budgets([sent], [found])
    assert shown["budgets"][0]["caps"][0]["plan"] is None
    # A report on a TRIP that cannot work states no plan, and so nothing is charged in one.
    (money,) = budgets_of("a-ticket/already-overspent")["budgets"]
    assert [cap["plan"] for cap in money["caps"]] == [None]
    (money,) = budgets_of("a-ticket/depends-on-the-receipt")["budgets"]
    assert [cap["plan"] for cap in money["caps"]] == [None]


def test_a_budget_with_no_cap_says_so() -> None:
    (money,) = budgets_of("a-ticket/not-bought-yet")["budgets"]
    assert (money["caps"], money["whole"]) == ([], NO_CAP)


def test_a_payment_that_names_no_budget_is_under_none() -> None:
    """Alex's BOOKING states what it paid, and not which BUDGET the money came from."""
    sent = drawn(STORY / "within-the-cap.json")
    sent["rights"][0]["bookings"][0]["paid"]["budget"] = None
    (shown,) = all_budgets([sent])
    assert [budget["payments"] for budget in shown["budgets"]] == [[]]
    assert [(paid["id"], paid["says"]) for paid in shown["unnamed"]] == [
        ("alex-skydeck-ticket", "32.00 USD, paid by Alex")
    ]
    # A FILE with no BUDGET has no such part: its BOOKINGs say what they paid where they are.
    assert drawn(STORY / "works.json")["budgets"] == []
    assert budgets_of("a-ticket/works")["unnamed"] == []


def test_the_budgets_mark_what_the_report_names_as_ruling_out_every_plan() -> None:
    """Two BOOKINGs paid 57.00 USD from the trip money, and its cap is 50.00 USD."""
    sent, found = with_its_report(STORY / "already-overspent.json")
    (shown,) = all_budgets([sent], [found])
    assert shown["says"] == SAYS + RED
    (money,) = shown["budgets"]
    (cap,) = money["caps"]
    assert (cap["says"], cap["clash"]) == (
        "the TRIP spends at most 50.00 USD from it",
        ["trip-cap"],
    )
    assert cap["finds"] == "The report names trip-cap among what rules out every plan."
    assert [(paid["says"], paid["clash"]) for paid in money["payments"]] == [
        ("32.00 USD, paid by Alex", ["alex-skydeck-ticket"]),
        ("25.00 USD, paid by Jo", ["jo-talk-ticket"]),
    ]
    # Only what a report names is marked.
    odd: list[Any] = [None, {}, {**found, "answer": "FEASIBLE"}, {**found, "conflict": "x"}]
    for other in all_budgets([sent] * len(odd), odd):
        assert other["clash"] is False


def test_each_kind_of_budget_has_its_words() -> None:
    sent = drawn(STORY / "within-the-cap.json")
    (money,) = sent["budgets"]
    money["persons"], money["currencies"] = [], ["USD", "EUR"]
    money["caps"].append({"id": "euro-cap", "limit": {"amount": "0.50", "currency": "EUR"}})
    (shown,) = all_budgets([sent])
    (budget,) = shown["budgets"]
    assert budget["holds"] == "It lists no PERSON. It holds USD and EUR."
    assert [cap["says"] for cap in budget["caps"]] == [
        "the TRIP spends at most 200.00 USD from it",
        "the TRIP spends at most 0.50 EUR from it",
    ]


def test_a_file_with_no_budget_shows_none() -> None:
    sent = drawn(EXAMPLES / "flight-home" / "works.json")
    assert sent["budgets"] == []
    empty: Budgets = {"says": "", "clash": False, "asked": False, "budgets": [], "unnamed": []}
    assert all_budgets([sent, None]) == [empty] * 2


def test_every_example_shows_its_budgets_in_the_words_of_the_report() -> None:
    """Each BUDGET, each cap and each payment is shown, worded as the report words it."""
    asked = [in_words(path) for path in FILES]
    shown = all_budgets(
        [sent for sent, _, _ in asked],
        [found for _, found, _ in asked],
        [words for _, _, words in asked],
    )
    pots = caps = payments = charged = 0
    for path, (_, _, words), each in zip(FILES, asked, shown, strict=True):
        file = read(path)
        name = f"{path.parent.name}/{path.stem}"
        assert [budget["id"] for budget in each["budgets"]] == [pot.id for pot in file.budgets], (
            name
        )
        # What each BOOKING that states a payment says of the BUDGET that the money came from.
        paid = {
            fact.id: fact.paid.budget
            for fact in file.facts
            if isinstance(fact, Booking) and fact.paid is not None
        }
        from_one = [payment["id"] for budget in each["budgets"] for payment in budget["payments"]]
        from_none = [payment["id"] for payment in each["unnamed"]]
        if file.budgets:
            assert sorted([*from_one, *from_none]) == sorted(paid), name
            assert from_none == [id for id, budget in paid.items() if budget is None], name
        for budget in each["budgets"]:
            # Where the report states the BUDGETs of the FILE, the page says the same of each.
            if " The BUDGETs of this FILE:" in words:
                pots += 1
                held = budget["holds"]
                said = f"{held[0].lower()}{held[1:-1]}".replace(". It holds ", "; it holds ")
                assert f"  {budget['name']}: {said}" in words, name
            for cap in budget["caps"]:
                # Where the report says what a plan charges to the cap, the page says the same.
                assert (cap["plan"] is not None) is ("\nThe caps:\n" in words), name
                if cap["plan"] is not None:
                    charged += 1
                    said = cap["plan"][len("In the plan: ") : -1]
                    assert f"  {cap['id']}: at most " in words, name
                    assert f": {said}\n" in f"{words}\n", name
                # Where the report names a cap, the page says the same of it.
                if f"  {cap['id']}: the TRIP spends" in words:
                    caps += 1
                    said = cap["says"].replace(" from it", f" from {budget['name']}")
                    assert f"  {cap['id']}: {said}" in words, name
            for payment in budget["payments"]:
                if "What the BOOKINGs state that they paid:" in words:
                    payments += 1
                    stated = f"  {payment['id']}: {payment['says']}, from {budget['name']}"
                    assert stated in words, name
    assert min(pots, caps, payments) > 1
    assert charged > 0
