"""What the page lists as still open about a TRIP, above its drawings.

The list is for a person who watches an agent plan a trip. It holds what has to be done or
decided: what the COMPILER's report says rules out every plan, what it says the FILE does not
say, what it warns of, and the steps of a plan that no LOCK decides.
``src/agloe/view/static/open.js`` makes it from the TRIP as the view sends it and from the
report. It has no page in it, so Node runs it here, through ``view_part.mjs``.

Nothing in it judges a TRIP. Each item is the report's own line, or says what the FILE holds.
"""

import json
from pathlib import Path
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


def further(lines: list[dict[str, Any]]) -> list[tuple[str, list[str]]]:
    """Lines that the list takes from the report as they are: the words, and what each is of."""
    return [(line["says"], line["of"]) for line in lines]


CHOICES = "No LOCK names these PERSONs for these OPTIONs of the plan:"
NOTHING = (
    "Nothing is open. The report gives no warnings, and a LOCK names each PERSON for every"
    " OPTION they take part in."
)
BUDGETS = (
    "A place with a price above nothing is paid from a BUDGET that lists the PERSON who takes"
    " it and holds the currency of the price. The BUDGETs of this FILE:"
)


def test_a_plan_lists_the_steps_that_no_lock_decides() -> None:
    """Alex and Sam visit the museum, take the Blue Line and fly home. LOCKs name them for
    the visit and for the flight. The train is the COMPILER's choice: nobody has decided it."""
    listed = open_of("flight-home/works")
    assert listed["says"] == "1 thing is open. Times are on the clocks of America/Chicago."
    assert said(listed) == [(CHOICES, [("Blue Line to O'Hare", "Alex and Sam")])]
    (group,) = listed["groups"]
    (train,) = group["items"]
    assert train["when"] == "Saturday 15 May 2027, 3:00 pm to 4:00 pm"
    # The item is a drawing of its step: pointing at it lights up the step in the calendar.
    assert (group["kind"], train["of"], train["records"], train["mark"]) == (
        "choices",
        ["1"],
        [],
        "",
    )
    assert (train["who"], train["more"], group["also"]) == ("", [], [])
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
    nothing: Open = {"says": NOTHING, "count": 0, "clash": False, "asked": False, "groups": []}
    assert open_in(file, Report(Answer.FEASIBLE, itinerary=plan)) == nothing
    # A service takes the bags with nobody of the TRIP in it. No LOCK can name anybody for
    # it, and the list does not say that one does.
    assert open_of("the-bags/the-service-takes-them") == nothing


def test_a_plan_lists_what_the_report_warns_of() -> None:
    """Sam still has to buy a ticket for the Skydeck. LOCKs decide every OPTION of the plan."""
    listed = open_of("a-ticket/not-bought-yet")
    assert listed["says"] == "1 thing is open. Times are on the clocks of America/Chicago."
    (warnings,) = listed["groups"]
    assert (warnings["kind"], warnings["says"]) == ("warnings", "The report warns:")
    (ticket,) = warnings["items"]
    # The item is of everything that the line of the report is about: the step and the OFFER.
    assert (ticket["name"], ticket["of"], ticket["mark"], ticket["records"]) == (
        "Skydeck visit",
        ["0", "offer:skydeck-tickets"],
        "warned",
        [],
    )
    # The report names Sam as the page does, so the item says nothing more of who it is.
    assert ticket["who"] == ""
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
        ["4"],
    )
    assert walk["when"] == "Saturday 15 May 2027, 8:45 am to 9:00 am"


def renamed(tmp_path: Path, example: str, names: dict[str, str]) -> Open:
    """What the page lists as open about an example in which PERSONs have other names."""
    document = json.loads((EXAMPLES / f"{example}.json").read_text())
    for person in document["persons"]:
        person["name"] = names.get(person["id"], person["name"])
    path = tmp_path / "trip.json"
    path.write_text(json.dumps(document))
    sent, found, text = in_words(path)
    return all_open([sent], [found], [text])[0]


def test_a_purchase_names_who_buys_as_the_page_names_them(tmp_path: Path) -> None:
    """Two PERSONs have names that a page shows alike: one has two spaces in it. The report
    in words tells them apart by the spaces. A page cannot, so it shows the id of each."""
    listed = renamed(tmp_path, "a-ticket/not-bought-yet", {"alex": "Mary Ann", "sam": "Mary  Ann"})
    (ticket,) = listed["groups"][0]["items"]
    assert ticket["says"].startswith("Mary  Ann still has to buy a right to this, from ")
    assert ticket["who"] == "On this page, that is Mary  Ann (sam)."
    # Where the report names the PERSON as the page does, the item adds nothing.
    listed = renamed(tmp_path, "a-ticket/not-bought-yet", {"sam": "Samantha"})
    (ticket,) = listed["groups"][0]["items"]
    assert ticket["says"].startswith("Samantha still has to buy a right to this, from ")
    assert ticket["who"] == ""


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
        (["case:0"], [], "asked"),
        (["case:1"], [], "asked"),
    ]
    assert (listed["count"], listed["clash"], listed["asked"]) == (2, False, True)
    # What the report says after its cases is under the list, in its own lines. The line of
    # a BUDGET is of that BUDGET.
    assert [further(lines) for lines in group["also"]] == [
        [
            (f"Who buys which place is from one plan that works in that case. {BUDGETS}", []),
            ("the trip money: for Alex and Sam; it holds USD", ["budget:trip-money"]),
        ]
    ]
    # One case has no heading over it in the report, and none here.
    listed = open_of("flight-home/depends-on-the-cab")
    assert said(listed) == [("", [("", "The trip works if Cab to O'Hare takes 45 min or less.")])]
    assert listed["groups"][0]["also"] == []


def test_a_case_keeps_what_the_report_says_under_it_and_after_it() -> None:
    """A BOOKING for Alex states no payment, and a cap holds the trip to 50.00 USD. The trip
    works only if what the BOOKING paid leaves room for Sam's place: the report says how much
    that is, under the case."""
    listed = open_of("a-ticket/depends-on-the-receipt")
    (group,) = listed["groups"]
    (case,) = group["items"]
    assert (case["says"], listed["count"]) == (
        "The trip works if the FILE states what alex-skydeck-ticket paid and from which BUDGET.",
        1,
    )
    assert further(case["more"]) == [
        (
            "One plan that works then: Sam buys a place from skydeck-tickets for 32.00 USD from"
            " the trip money.",
            ["offer:skydeck-tickets"],
        ),
        (
            "trip-cap, on the trip money: 32.00 still to buy, of at most 50.00 USD. That leaves"
            " 18.00 USD for whatever else is charged to it.",
            ["cap:trip-cap"],
        ),
    ]
    assert [further(lines) for lines in group["also"]] == [
        [
            (
                "Whatever the FILE comes to state counts against a cap like everything else:"
                " what a BOOKING paid from its BUDGET in its currency, and each place that its"
                " BUDGET pays for. All of it has to fit in what the cap has left.",
                [],
            )
        ],
        [
            (f"Who buys which place is from one plan that works in that case. {BUDGETS}", []),
            ("the trip money: for Alex and Sam; it holds USD", ["budget:trip-money"]),
        ],
    ]
    # Another way to make the trip work, which the report states after the case.
    listed = open_of("a-ticket/depends-on-the-talk")
    (group,) = listed["groups"]
    assert said(listed) == [
        ("", [("", "The trip works if nobody needs a right to take part in Gallery talk.")])
    ]
    assert [further(lines) for lines in group["also"]] == [
        [
            (
                "If Gallery talk does need a right, a BOOKING for each PERSON who takes part in"
                " it is enough instead.",
                [],
            )
        ]
    ]


def test_a_trip_that_cannot_work_lists_what_rules_out_every_plan() -> None:
    """The visit ends too late for the train to the flight."""
    listed = open_of("flight-home/cannot-work")
    assert listed["says"] == "No plan works."
    (group,) = listed["groups"]
    # The heading is the report's own line: it says which kinds of record these are, and
    # what taking one away means.
    assert (group["kind"], group["says"], group["also"]) == (
        "conflict",
        "These FACTs and DECISIONs rule out every plan by themselves. Take any one away and they"
        " no longer do. A FACT that is taken away leaves what it said unknown. Times are in"
        " America/Chicago.",
        [],
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
    assert all((item["mark"], item["of"]) == ("clash", []) for item in group["items"])
    assert (listed["count"], listed["clash"], listed["asked"]) == (8, True, False)
    # Where the BUDGETs of the FILE are part of why no plan works, the report says so and
    # states them. The list keeps both.
    listed = open_of("a-ticket/over-the-cap")
    (group,) = listed["groups"]
    assert group["says"] == (
        "These FACTs and DECISIONs rule out every plan, given the BUDGETs of this FILE. Take any"
        " one away and they no longer do. A FACT that is taken away leaves what it said unknown."
        " Times are in America/Chicago."
    )
    assert [further(lines) for lines in group["also"]] == [
        [(BUDGETS, []), ("the trip money: for Alex and Sam; it holds USD", ["budget:trip-money"])]
    ]
    assert listed["count"] == 6


def test_a_trip_with_no_report_lists_nothing() -> None:
    """Before the COMPILER has reported, nothing says what is open."""
    sent = shown(read(EXAMPLES / "flight-home" / "works.json"))
    assert sent is not None
    nothing: Open = {"says": "", "count": 0, "clash": False, "asked": False, "groups": []}
    assert all_open([cast("Trip", sent), None]) == [nothing, nothing]
    # A report that the page cannot read lists nothing either.
    assert all_open([cast("Trip", sent)], [{"answer": "MAYBE"}]) == [nothing]


def test_a_report_whose_words_and_json_disagree_lists_nothing() -> None:
    """The list says what the report in words says of what the report as JSON names. Where
    the two do not fit together, it says nothing: half a list would read as the whole."""
    nothing: Open = {"says": "", "count": 0, "clash": False, "asked": False, "groups": []}
    for name, old, new in [
        # The words name one record fewer than the JSON.
        ("flight-home/cannot-work", "  lock-flight: ", "  another: "),
        # The words have no line over the records.
        ("flight-home/cannot-work", "These FACTs and DECISIONs rule out", "These rule out"),
        # The words state one case fewer than the JSON.
        ("a-ticket/depends-on-the-price", "  2. A place from", "  A place from"),
        # A line that the report marks with "!" is under no step.
        ("a-ticket/not-bought-yet", "    ! Sam still", "\n    ! Sam still"),
    ]:
        sent, found, text = in_words(EXAMPLES / f"{name}.json")
        assert old in text, name
        assert all_open([sent], [found], [text.replace(old, new)]) == [nothing], (name, old)
        assert all_open([sent], [found], [text]) != [nothing], name


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
    assert said(listed) == [(CHOICES, [("lunch", '"nobody" and alex')])]


def test_every_example_lists_what_its_report_says() -> None:
    """For every example: the list holds each record that rules out every plan, each case in
    which the trip works, and each line that the report marks with "!", and no other. Of a
    report that shows no plan, it holds every line after the answer, once and in order."""
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
        assert [item["of"] for item in groups.get("choices", [])] == [
            [str(n)] for n in open_steps
        ], name
        # A warning is of the step that its line of the report is under.
        # The plan comes first in a report, one step to a line, set in by two spaces.
        under: list[str] = []
        step = -1
        for line in text.split("\n"):
            if line.startswith("  ") and line[2] != " ":
                step += 1
            elif line.startswith("    ! "):
                under.append(str(step))
        assert [item["of"][0] for item in groups.get("warnings", [])] == under, name
        # A step that is not decided names the PERSONs whom no LOCK names for it.
        names = {person["id"]: person["name"] for person in sent["persons"]}
        for item in groups.get("choices", []):
            step_of = steps[int(item["of"][0])]
            free = [names[id] for id in step_of["persons"] if id not in step_of["locked"]]
            assert all(name_of in item["says"] for name_of in free), name
        if found["answer"] == "FEASIBLE":
            continue
        # A report that shows no plan is about what is open and nothing else. The list holds
        # each of its lines after the answer: none is left out, and none is there twice.
        held = [
            line
            for group in listed_of["groups"]
            for line in [
                group["says"],
                *(
                    words
                    for item in group["items"]
                    for words in [
                        f"{item['name']}: {item['says']}" if item["name"] else item["says"],
                        *(more["says"] for more in item["more"]),
                    ]
                ),
                *(line["says"] for lines in group["also"] for line in lines),
            ]
            if line
        ]
        assert held == [line.strip() for line in text.split("\n")[1:] if line.strip()], name
    assert kinds == {"conflict", "cases", "warnings", "choices"}
