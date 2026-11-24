"""What the page lists as still open about a TRIP, above its drawings.

The list is for a person who watches an agent plan a trip. It holds what has to be done or
decided: what the COMPILER's report says rules out every plan, what it says the FILE does not
say, what it warns of, and the steps of a plan that no LOCK decides.
``src/agloe/view/static/open.js`` makes it from the TRIP as the view sends it and from the
report. It has no page in it, so Node runs it here, through ``view_part.mjs``.

Nothing in it judges a TRIP. Each item is the report's own line, or says what the FILE holds.
"""

import json
from typing import Any, cast

from agloe import report as reports
from agloe.answers import Answer, Report
from agloe.file import File, read
from agloe.reference import Step
from agloe.view.trip import shown
from tests.stories import EXAMPLES, lock, moves, seconds, starts_at, stays, trip
from tests.test_view_calendar import in_words, parts, sent_for

FILES = sorted(
    path for path in EXAMPLES.rglob("*.json") if not path.name.endswith(".expected.json")
)

type Trip = dict[str, Any]
type Open = dict[str, Any]


def all_open(
    trips: list[Trip | None],
    reports: list[dict[str, Any] | None] | None = None,
    texts: list[str | None] | None = None,
) -> list[Open]:
    """What the page lists as open about each TRIP, by the page's own code."""
    return parts("open", trips, reports, texts)


def open_of(name: str) -> Open:
    """What the page lists as open about an example, with the report on it."""
    sent, found, text = in_words(EXAMPLES / f"{name}.json")
    return all_open([sent], [found], [text])[0]


def open_in(file: File, found: Report) -> Open:
    """What the page lists as open about a FILE, with a report that a test gives for it."""
    sent = sent_for(file, found)
    (listed,) = all_open([sent], [reports.as_json(file, found)], [reports.as_text(file, found)])
    return listed


def said(listed: Open) -> list[tuple[str, list[tuple[str, str]]]]:
    """Each group of the list with its heading, and each of its items by name and words."""
    return [
        (group["says"], [(item["name"], item["says"]) for item in group["items"]])
        for group in listed["groups"]
    ]


def test_a_plan_lists_the_steps_that_no_lock_decides() -> None:
    """Alex and Sam visit the museum, take the Blue Line and fly home. LOCKs name them for
    the visit and for the flight. The train is the COMPILER's choice: nobody has decided it."""
    listed = open_of("flight-home/works")
    assert listed["says"] == "1 thing is open. Times are on the clocks of America/Chicago."
    assert said(listed) == [
        (
            "In the plan, and not decided. No LOCK names these PERSONs for these OPTIONs:",
            [("Blue Line to O'Hare", "Alex and Sam")],
        )
    ]
    (group,) = listed["groups"]
    (train,) = group["items"]
    assert train["when"] == "Saturday 15 May 2027, 3:00 pm to 4:00 pm"
    # The item is a drawing of its step: pointing at it lights up the step in the calendar.
    assert (group["kind"], train["of"], train["records"], train["mark"]) == ("choices", 1, [], "")
    assert (listed["count"], listed["clash"], listed["asked"]) == (1, False, False)


def test_a_plan_with_every_step_decided_has_nothing_open() -> None:
    """A LOCK names Alex for the visit, and the plan holds nothing else."""
    file = trip(
        ["alex"],
        ["hall"],
        [stays("visit", "hall")],
        [starts_at("visit", 10)],
        [lock("visit", "alex")],
    )
    plan = (Step("visit", "hall", "hall", ("alex",), seconds(10), seconds(11)),)
    assert open_in(file, Report(Answer.FEASIBLE, itinerary=plan)) == {
        "says": (
            "Nothing is open: the report warns of nothing, and a LOCK decides every OPTION of"
            " the plan."
        ),
        "count": 0,
        "clash": False,
        "asked": False,
        "groups": [],
    }


def test_a_plan_lists_what_the_report_warns_of() -> None:
    """Sam still has to buy a ticket for the Skydeck. LOCKs decide every OPTION of the plan."""
    listed = open_of("a-ticket/not-bought-yet")
    assert listed["says"] == "1 thing is open. Times are on the clocks of America/Chicago."
    (warnings,) = listed["groups"]
    assert (warnings["kind"], warnings["says"]) == ("warnings", "The report warns:")
    (ticket,) = warnings["items"]
    assert (ticket["name"], ticket["of"], ticket["mark"], ticket["records"]) == (
        "Skydeck visit",
        0,
        "warned",
        [],
    )
    assert ticket["says"] == (
        "Sam still has to buy a right to this, from skydeck-tickets, for 32.00 USD from the"
        " trip money."
    )
    assert ticket["when"] == "Saturday 15 May 2027, 10:00 am to 11:30 am"
    assert (listed["count"], listed["clash"], listed["asked"]) == (1, False, True)
    # A step that could start too late is warned of too, also where it is a WAY.
    listed = open_of("several-days/works-but-risky")
    (walk,) = listed["groups"][0]["items"]
    assert (walk["name"], walk["says"], walk["of"]) == (
        "the walk between the hotel and Willis Tower",
        "Alex would still be busy for 1 h 15 min when this starts.",
        4,
    )
    assert walk["when"] == "Saturday 15 May 2027, 8:45 am to 9:00 am"


def test_a_trip_that_depends_on_something_lists_each_case() -> None:
    """Sam has no ticket for the Skydeck, and the OFFER states no price."""
    listed = open_of("a-ticket/depends-on-the-price")
    assert listed["says"] == "The FILE does not say enough to tell whether this trip works."
    assert said(listed) == [
        (
            "The trip works in any of these cases:",
            [
                (
                    "",
                    "1. A right to Skydeck visit is found for Sam, in addition to the 2 places"
                    " on OFFER.",
                ),
                ("", "2. A place from skydeck-tickets has a price that Sam can pay."),
            ],
        )
    ]
    (group,) = listed["groups"]
    # Each case is tied like its line of the report, under a name that no record can have.
    assert group["kind"] == "cases"
    assert [(item["records"], item["of"], item["mark"]) for item in group["items"]] == [
        (["case:0"], None, "asked"),
        (["case:1"], None, "asked"),
    ]
    assert (listed["count"], listed["clash"], listed["asked"]) == (2, False, True)
    # One case has no heading over it in the report, and none here.
    listed = open_of("flight-home/depends-on-the-cab")
    assert said(listed) == [("", [("", "The trip works if Cab to O'Hare takes 45 min or less.")])]


def test_a_trip_that_cannot_work_lists_what_rules_out_every_plan() -> None:
    """The visit ends too late for the train to the flight."""
    listed = open_of("flight-home/cannot-work")
    assert listed["says"] == "No plan works. Times are on the clocks of America/Chicago."
    (group,) = listed["groups"]
    assert (group["kind"], group["says"]) == (
        "conflict",
        "These 8 FACTs, WANTs and DECISIONs rule out every plan together. Take any one away, and"
        " they no longer do:",
    )
    assert [(item["name"], item["says"]) for item in group["items"]][:2] == [
        ("visit-time", "Museum visit starts at 2:30 pm on Saturday 15 May 2027"),
        ("visit-length", "Museum visit takes 1 h"),
    ]
    assert [item["records"] for item in group["items"]] == [
        ["visit-time"],
        ["visit-length"],
        ["train-length"],
        ["flight-time"],
        ["bag-drop"],
        ["ways-to-ohare"],
        ["lock-visit"],
        ["lock-flight"],
    ]
    assert all((item["mark"], item["of"]) == ("clash", None) for item in group["items"])
    assert (listed["count"], listed["clash"], listed["asked"]) == (8, True, False)


def test_a_trip_with_no_report_lists_nothing() -> None:
    """Before the COMPILER has reported, nothing says what is open."""
    sent = shown(read(EXAMPLES / "flight-home" / "works.json"))
    assert sent is not None
    nothing: Open = {"says": "", "count": 0, "clash": False, "asked": False, "groups": []}
    assert all_open([cast("Trip", sent), None]) == [nothing, nothing]
    # A report that the page cannot read lists nothing either.
    assert all_open([cast("Trip", sent)], [{"answer": "MAYBE"}]) == [nothing]


def test_a_step_with_nobody_in_it_is_no_decision_of_a_person() -> None:
    """A van runs with nobody of the TRIP in it. A LOCK names PERSONs, so none can decide it."""
    file = trip(
        ["nobody", "alex"],
        ["hall", "port"],
        [stays("visit", "hall"), stays("lunch", "hall"), moves("van", "hall", "port")],
        [starts_at("visit", 10)],
        [lock("visit", "nobody")],
    )
    plan = (
        Step("visit", "hall", "hall", ("nobody",), seconds(10), seconds(11)),
        Step("lunch", "hall", "hall", ("nobody", "alex"), seconds(12), seconds(13)),
        Step("van", "hall", "port", (), seconds(14), seconds(15, 30)),
    )
    listed = open_in(file, Report(Answer.FEASIBLE, itinerary=plan))
    # Lunch is not decided for either of the two. A PERSON called nobody is told from nobody.
    assert said(listed) == [
        (
            "In the plan, and not decided. No LOCK names these PERSONs for these OPTIONs:",
            [("lunch", '"nobody" and alex')],
        )
    ]


def test_every_example_lists_what_its_report_says() -> None:
    """For every example: the list holds each record that rules out every plan, each case in
    which the trip works, and each line that the report marks with "!", and no other."""
    asked = [in_words(path) for path in FILES]
    listed = all_open(
        [sent for sent, _, _ in asked],
        [found for _, found, _ in asked],
        [text for _, _, text in asked],
    )
    kinds: set[str] = set()
    for path, (sent, found, text), listed_of in zip(FILES, asked, listed, strict=True):
        name = f"{path.parent.name}/{path.stem}"
        groups = {group["kind"]: group["items"] for group in listed_of["groups"]}
        kinds |= set(groups)
        assert listed_of["count"] == sum(len(items) for items in groups.values()), name
        assert [item["records"] for item in groups.get("conflict", [])] == [
            [record] for record in found.get("conflict", [])
        ], name
        assert [item["records"] for item in groups.get("cases", [])] == [
            [f"case:{n}"] for n in range(len(found.get("missing", [])))
        ], name
        warned = [
            line.removeprefix("    ! ") for line in text.split("\n") if line.startswith("    ! ")
        ]
        assert [item["says"] for item in groups.get("warnings", [])] == warned, name
        # A step is listed as not decided where somebody is in it whom no LOCK names for it.
        steps: list[dict[str, Any]] = sent["steps"] if found["answer"] == "FEASIBLE" else []
        open_steps = [
            n
            for n, step in enumerate(steps)
            if step["option"] is not None and set[str](step["persons"]) - set[str](step["locked"])
        ]
        assert [item["of"] for item in groups.get("choices", [])] == open_steps, name
        # Every word of an item is the report's, or is of the TRIP as the view sends it.
        assert json.dumps(listed_of)  # the list holds nothing that cannot be sent
    assert kinds == {"conflict", "cases", "warnings", "choices"}
