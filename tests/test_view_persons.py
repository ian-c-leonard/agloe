"""What the page shows of the PERSONs of a FILE.

The view sends the PERSONs, each FACT about where a PERSON starts from, and the WANTs.
``src/agloe/view/static/persons.js`` says of each PERSON where the FILE says they start from,
or that it does not say, and where a WANT has them end the TRIP. It marks what the report
names. It has no page in it, so Node runs it here, through ``view_part.mjs``.

Nothing in it judges a TRIP. Where a PERSON's path begins and ends in a plan is for the
COMPILER to say.
"""

from typing import Any

from agloe.file import read
from tests.stories import EXAMPLES
from tests.test_view_calendar import drawn, in_words, parts, with_its_report

FILES = sorted(
    path for path in EXAMPLES.rglob("*.json") if not path.name.endswith(".expected.json")
)
SAYS = "Every PERSON of the FILE, with where the FILE says they start from."
# In a FILE that has a BUDGET.
PAYS = (
    "Every PERSON of the FILE, with where the FILE says they start from and which BUDGETs they"
    " may draw on."
)
ENDS = " Where a WANT has a PERSON end the TRIP at a PLACE, the row says so."
RED = " A red edge marks what the report names among what rules out every plan."
YELLOW = " A yellow edge marks what the report names in what the FILE does not say."
UNSAID = "The FILE does not say where this PERSON starts from."

type Trip = dict[str, Any]
type Persons = dict[str, Any]


def all_persons(
    trips: list[Trip | None],
    reports: list[dict[str, Any] | None] | None = None,
    texts: list[str | None] | None = None,
) -> list[Persons]:
    """What the page shows of the PERSONs of each TRIP, by the page's own code."""
    return parts("persons", trips, reports, texts)


def persons_of(name: str) -> Persons:
    """What the page shows of the PERSONs of an example, with the report on it."""
    sent, found, text = in_words(EXAMPLES / f"{name}.json")
    return all_persons([sent], [found], [text])[0]


def test_a_person_says_where_they_start_from_and_where_a_want_has_them_end() -> None:
    """Alex and Sam start from the hotel, and must end the TRIP in Denver."""
    shown = persons_of("ending-in-denver/works")
    assert shown["says"] == SAYS + ENDS
    assert (shown["clash"], shown["asked"]) == (False, False)
    alex, sam = shown["persons"]
    assert alex == {
        "id": "alex",
        "name": "Alex",
        "where": "Starts from the hotel.",
        "ends": ["Must end the TRIP at Denver."],
        # This FILE has no BUDGET, so the page says nothing of who pays.
        "pays": [],
        # The FACT about where Alex starts from.
        "records": ["alex-start"],
        "clash": [],
        "finds": None,
        "cases": [],
        "asks": [],
    }
    assert (sam["name"], sam["where"], sam["records"]) == (
        "Sam",
        "Starts from the hotel.",
        ["sam-start"],
    )


def test_a_person_of_whom_the_file_says_nothing_says_so() -> None:
    shown = persons_of("flight-home/works")
    assert shown["says"] == SAYS
    assert [(person["name"], person["where"], person["ends"]) for person in shown["persons"]] == [
        ("Alex", UNSAID, []),
        ("Sam", UNSAID, []),
    ]
    assert all(person["records"] == [] for person in shown["persons"])


def test_a_person_says_which_budgets_they_may_draw_on() -> None:
    """The trip money is for Alex and Sam. No BUDGET lists Jo."""
    shown = persons_of("a-ticket/not-bought-yet")
    assert shown["says"] == PAYS
    assert [(person["name"], person["pays"]) for person in shown["persons"]] == [
        ("Alex", ["May draw on the trip money."]),
        ("Sam", ["May draw on the trip money."]),
        ("Jo", ["No BUDGET of the FILE lists this PERSON."]),
    ]
    # Each BUDGET has a sentence of its own. So one BUDGET named "Meals and tickets" never
    # reads like two BUDGETs named "Meals" and "tickets".
    sent = drawn(EXAMPLES / "a-ticket" / "not-bought-yet.json")
    (money,) = sent["budgets"]
    money["name"], money["persons"] = "Meals and tickets", ["alex"]
    sent["budgets"] += [
        {**money, "id": "meals", "name": "Meals", "persons": ["sam"]},
        {**money, "id": "tickets", "name": "tickets", "persons": ["sam"]},
    ]
    (shown,) = all_persons([sent])
    alex, sam, _ = shown["persons"]
    assert alex["pays"] == ["May draw on Meals and tickets."]
    assert sam["pays"] == ["May draw on Meals.", "May draw on tickets."]


def test_only_a_person_who_holds_the_want_must_end_the_trip_at_its_place() -> None:
    sent = drawn(EXAMPLES / "ending-in-denver" / "works.json")
    (want,) = [want for want in sent["wants"] if want["ends_at"] is not None]
    want["musts"] = ["alex"]
    (shown,) = all_persons([sent])
    assert [person["ends"] for person in shown["persons"]] == [
        ["Must end the TRIP at Denver."],
        [],
    ]
    # A WANT that an OPTION can deliver says nothing of where a PERSON ends the TRIP.
    want["ends_at"] = None
    (shown,) = all_persons([sent])
    assert shown["says"] == SAYS
    assert all(person["ends"] == [] for person in shown["persons"])


def test_the_persons_mark_what_the_report_says_the_file_does_not_say() -> None:
    """The trip works if Alex can drive a manual car, or if Sam can. Jo cannot."""
    shown = persons_of("a-driver/depends-on-who-can-drive")
    assert shown["says"] == SAYS + YELLOW
    alex, sam, jo = shown["persons"]
    assert (alex["cases"], sam["cases"], jo["cases"]) == ([0], [1], [])
    assert alex["asks"] == [
        "The trip works in any of these cases:",
        "1. Alex has the CAPABILITY driving a manual car.",
    ]
    assert jo["asks"] == []


def test_the_persons_mark_what_the_report_names_as_ruling_out_every_plan() -> None:
    sent, found = with_its_report(EXAMPLES / "ending-in-denver" / "works.json")
    # A report that names where Alex starts from among what rules out every plan.
    ruled = {"answer": "INFEASIBLE", "conflict": ["alex-start", "trip-end"]}
    (shown,) = all_persons([sent], [ruled])
    assert shown["says"] == SAYS + ENDS + RED
    alex, sam = shown["persons"]
    assert (alex["clash"], sam["clash"]) == (["alex-start"], [])
    assert alex["finds"] == "The report names alex-start among what rules out every plan."
    # Only what a report names is marked.
    odd: list[Any] = [None, {}, found, {**ruled, "answer": "FEASIBLE"}, {**ruled, "conflict": "x"}]
    for other in all_persons([sent] * len(odd), odd):
        assert other["clash"] is False
        assert all(person["clash"] == [] for person in other["persons"])


def test_a_trip_with_no_person_shows_none() -> None:
    sent = drawn(EXAMPLES / "flight-home" / "works.json")
    sent["persons"], sent["steps"], sent["wants"] = [], [], []
    empty: Persons = {"says": "", "clash": False, "asked": False, "persons": []}
    assert all_persons([sent, None]) == [empty] * 2


def test_every_example_shows_its_persons_in_the_words_of_the_report() -> None:
    """Each PERSON of each FILE is shown, and where they start from is worded as the report does."""
    asked = [in_words(path) for path in FILES]
    shown = all_persons(
        [sent for sent, _, _ in asked],
        [found for _, found, _ in asked],
        [words for _, _, words in asked],
    )
    starts = 0
    for path, (_, _, words), each in zip(FILES, asked, shown, strict=True):
        file = read(path)
        name = f"{path.parent.name}/{path.stem}"
        assert [person["id"] for person in each["persons"]] == [
            person.id for person in file.persons
        ], name
        for person in each["persons"]:
            stated = file.starts_from(person["id"])
            assert (person["where"] == UNSAID) is (stated is None), name
            assert person["records"] == ([] if stated is None else [stated.id]), name
            # Where the report has a line about where this PERSON starts from, the page says
            # the same.
            if stated is not None and f"  {stated.id}: " in words:
                starts += 1
                said = person["where"]
                assert f"  {stated.id}: {person['name']} s{said[1:-1]}" in words, name
    # Few examples say where a PERSON starts from.
    assert starts > 1
