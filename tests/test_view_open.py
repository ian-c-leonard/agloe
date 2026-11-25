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


NOT_SURE = (
    "WARNING: no plan is sure to hold if the uncertain parts take their longest. Each line"
    ' marked "!" says what would go wrong at the step above it.'
)
NOT_BOOKED = (
    'WARNING: not everything is booked yet. A line marked "!" that names an OFFER says who'
    " still has to buy a right. Only a BOOKING secures one."
)


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
    assert (train["more"], group["also"]) == ([], [])
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
    assert open_in(file, Report(Answer.FEASIBLE, itinerary=plan, robust=True)) == nothing
    # A service takes the bags with nobody of the TRIP in it. No LOCK can name anybody for
    # it, and the list does not say that one does.
    assert open_of("the-bags/the-service-takes-them") == nothing


def test_a_plan_lists_what_the_report_warns_of() -> None:
    """Sam still has to buy a ticket for the Skydeck. LOCKs decide every OPTION of the plan."""
    listed = open_of("a-ticket/not-bought-yet")
    assert listed["says"] == "1 thing is open. Times are on the clocks of America/Chicago."
    (warnings,) = listed["groups"]
    # Over the warnings is what the report says of them: only a BOOKING secures a right.
    assert (warnings["kind"], warnings["says"]) == ("warnings", NOT_BOOKED)
    (ticket,) = warnings["items"]
    # The item is of everything that the line of the report is about: the step and the OFFER.
    assert (ticket["name"], ticket["of"], ticket["mark"], ticket["records"]) == (
        "Skydeck visit",
        ["0", "offer:skydeck-tickets"],
        "warned",
        [],
    )
    # The line keeps the mark that the report gives it: the report speaks of that mark.
    assert ticket["says"] == (
        "! Sam still has to buy a right to this, from skydeck-tickets, for 32.00 USD from the"
        " trip money."
    )
    assert ticket["when"] == "Saturday 15 May 2027, 10:00 am to 11:30 am"
    assert (listed["count"], listed["clash"], listed["asked"]) == (1, False, True)
    # A step that could start too late is warned of too, also where it is a WAY.
    # The report says under which condition that comes true. The list says it with it.
    listed = open_of("several-days/works-but-risky")
    assert listed["groups"][0]["says"] == NOT_SURE
    (walk,) = listed["groups"][0]["items"]
    assert (walk["name"], walk["says"], walk["of"]) == (
        "the walk between the hotel and Willis Tower",
        "! Alex would still be busy for 1 h 15 min when this starts.",
        ["4"],
    )
    assert walk["when"] == "Saturday 15 May 2027, 8:45 am to 9:00 am"


def test_each_purchase_is_an_item_of_its_own(tmp_path: Path) -> None:
    """Nobody has a ticket for the Skydeck yet, and Alex and Sam each pay from their own
    BUDGET. The report has a line for each of the two, and so has the list."""
    document = json.loads((EXAMPLES / "a-ticket" / "not-bought-yet.json").read_text())
    document["budgets"] = [
        {"id": "alex-money", "name": "Alex's money", "persons": ["alex"], "currencies": ["USD"]},
        {"id": "sam-money", "name": "Sam's money", "persons": ["sam"], "currencies": ["USD"]},
    ]
    document["facts"] = [fact for fact in document["facts"] if fact["id"] != "alex-skydeck-ticket"]
    path = tmp_path / "trip.json"
    path.write_text(json.dumps(document))
    sent, found, text = in_words(path)
    (listed,) = all_open([sent], [found], [text])
    (group,) = listed["groups"]
    assert [(item["name"], item["says"], item["of"]) for item in group["items"]] == [
        (
            "Skydeck visit",
            "! Alex still has to buy a right to this, from skydeck-tickets, for 32.00 USD from"
            " Alex's money.",
            ["0", "offer:skydeck-tickets"],
        ),
        (
            "Skydeck visit",
            "! Sam still has to buy a right to this, from skydeck-tickets, for 32.00 USD from"
            " Sam's money.",
            ["0", "offer:skydeck-tickets"],
        ),
    ]
    # Each item is its line of the report and nothing else.
    assert all(set(item) == set(group["items"][0]) for item in group["items"])
    assert set(group["items"][0]) == {"name", "says", "when", "of", "records", "mark", "more"}
    assert listed["says"] == "2 things are open. Times are on the clocks of America/Chicago."


def asked_of(tmp_path: Path, example: str, change: Any) -> tuple[Trip, dict[str, Any], str]:
    """An example that a test changes: what is sent of it, and the report as JSON and in words."""
    document = json.loads((EXAMPLES / f"{example}.json").read_text())
    change(document)
    path = tmp_path / "trip.json"
    path.write_text(json.dumps(document))
    return in_words(path)


def changed(tmp_path: Path, example: str, change: Any) -> tuple[Open, str]:
    """What the page lists as open about an example that a test changes, and the report."""
    sent, found, text = asked_of(tmp_path, example, change)
    (listed,) = all_open([sent], [found], [text])
    return listed, text


def no_tickets(document: dict[str, Any]) -> None:
    """Nobody has a ticket for the flight yet: an OFFER has two places, at a price."""
    money = {"id": "trip-money", "name": "the trip money", "persons": ["alex", "sam"]}
    document["budgets"] = [{**money, "currencies": ["USD"]}]
    seats = {
        "option": "flight",
        "places": 2,
        "prices": [{"amount": "120.00", "currency": "USD"}],
    }
    document["facts"] = [
        {"id": "flight-seats", "offer": seats} if fact["id"] == "flight-tickets" else fact
        for fact in document["facts"]
    ]


def test_a_plan_with_both_kinds_of_warning_says_what_each_means(tmp_path: Path) -> None:
    """The train to the flight can take 20 min longer, and nobody has a ticket for the flight
    yet. The report says of its lines marked "!" which are of which kind."""
    listed, text = changed(tmp_path, "flight-home/works-but-risky", no_tickets)
    warnings, choices = listed["groups"]
    # Both lines of the report are over the warnings, in the report's order.
    assert warnings["says"].split("\n") == [
        "WARNING: no plan is sure to hold if the uncertain parts take their longest. Each line"
        ' marked "!" that names no OFFER says what would go wrong at the step above it.',
        NOT_BOOKED,
    ]
    # Each warning is under the name of its step, with its mark, so that a reader can tell
    # which line names an OFFER.
    assert [(item["name"], item["says"], item["of"]) for item in warnings["items"]] == [
        (
            "Flight home",
            "! Alex and Sam still have to buy a right to this, from flight-seats, for 120.00"
            " USD each from the trip money.",
            ["2", "offer:flight-seats"],
        ),
        ("Flight home", "! Alex and Sam would be 5 min too late for this.", ["2"]),
    ]
    assert [line.strip() for line in text.split("\n") if line.startswith("    ! ")] == [
        item["says"] for item in warnings["items"]
    ]
    assert choices["kind"] == "choices"
    assert listed["says"] == "3 things are open. Times are on the clocks of America/Chicago."


def test_a_plan_that_holds_however_long_things_take_warns_of_nothing(tmp_path: Path) -> None:
    """The train can take 20 min longer, and the bags can be dropped 30 min before the
    flight. The report says that the plan holds, and warns of nothing."""

    def later_bag_drop(document: dict[str, Any]) -> None:
        for fact in document["facts"]:
            if fact["id"] == "bag-drop":
                fact["arrive_before_start"] = "PT30M"

    listed, text = changed(tmp_path, "flight-home/works-but-risky", later_bag_drop)
    assert "This plan holds however long the uncertain parts take" in text
    # Only the train is open: no LOCK names anybody for it.
    assert said(listed) == [(CHOICES, [("Blue Line to O'Hare", "Alex and Sam")])]
    assert (listed["count"], listed["asked"]) == (1, False)

    def decided(document: dict[str, Any]) -> None:
        later_bag_drop(document)
        document["decisions"].append(
            {"id": "lock-train", "lock": "blue-line", "persons": ["alex", "sam"]}
        )

    listed, _ = changed(tmp_path, "flight-home/works-but-risky", decided)
    assert (listed["says"], listed["groups"]) == (NOTHING, [])


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
    # A line is set in where the report sets it in.
    assert [line["inset"] for line in group["also"][0]] == [False, True]
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


def test_the_deadlines_of_a_report_are_no_part_of_what_rules_out_every_plan() -> None:
    """The night ends after breakfast starts. What cancelling the room costs is not why."""
    listed = open_of("the-room/cannot-work")
    (group,) = listed["groups"]
    assert group["kind"] == "conflict"
    assert group["also"] == []
    assert [item["name"] for item in group["items"]] == [
        "night-time",
        "night-length",
        "breakfast-time",
        "lock-night",
        "lock-breakfast",
    ]


def test_the_deadlines_of_a_report_are_no_part_of_a_case(tmp_path: Path) -> None:
    """Nobody has said how long the night lasts, and the room can still be cancelled."""

    def with_terms(document: dict[str, Any]) -> None:
        room = next(fact for fact in document["facts"] if fact["id"] == "room")
        room["booking"]["cancelling"] = [
            {"costs": [{"amount": "0.00", "currency": "USD"}]},
            {
                "from": "2027-05-12T18:00:00-05:00[America/Chicago]",
                "costs": [{"amount": "189.00", "currency": "USD"}],
            },
        ]

    listed, text = changed(tmp_path, "several-days/depends-on-the-night", with_terms)
    assert "At STAKE: 189.00 USD." in text
    (group,) = listed["groups"]
    assert group["kind"] == "cases"
    assert group["also"] == []
    assert listed["count"] == 1


def test_a_deadline_is_no_step_of_the_plan(tmp_path: Path) -> None:
    """A DEADLINE has a line that starts with a time and names the ferry "to Muskegon"."""

    def with_terms(document: dict[str, Any]) -> None:
        tickets = next(fact for fact in document["facts"] if fact["id"] == "ferry-tickets")
        tickets["booking"]["cancelling"] = [
            {"costs": [{"amount": "0.00", "currency": "USD"}]},
            {
                "from": "2027-07-14T18:00:00-05:00[America/Chicago]",
                "costs": [{"amount": "38.00", "currency": "USD"}],
            },
        ]

    before = open_of("a-car-ferry/a-place-on-the-car-deck")
    listed, text = changed(tmp_path, "a-car-ferry/a-place-on-the-car-deck", with_terms)
    assert "cancelling ferry-tickets, the BOOKING for Car ferry to Muskegon, starts." in text
    assert listed == before
    assert listed["says"].startswith("1 thing is open.")
    assert [item["says"] for group in listed["groups"] for item in group["items"]] == [
        "! A right to this still has to be bought for the car, from car-deck, for 90.00 USD from"
        " the trip money."
    ]


def test_a_case_that_holds_before_a_time_says_on_which_clocks() -> None:
    """The case names its clocks itself: a card says it again with no other line beside it."""
    listed = open_of("a-ticket/nobody-said-whether-the-offer-has-expired")
    assert [item["says"] for group in listed["groups"] for item in group["items"]] == [
        "1. A right to Skydeck visit is found for Sam, in addition to the places on OFFER.",
        "2. It is before 5:00 pm on Thursday 13 May 2027 (America/Chicago).",
    ]


def test_a_trip_with_no_report_lists_nothing() -> None:
    """Before the COMPILER has reported, nothing says what is open."""
    sent = shown(read(EXAMPLES / "flight-home" / "works.json"))
    assert sent is not None
    nothing: Open = {"says": "", "count": 0, "clash": False, "asked": False, "groups": []}
    assert all_open([cast("Trip", sent), None]) == [nothing, nothing]
    # A report that the page cannot read lists nothing either.
    assert all_open([cast("Trip", sent)], [{"answer": "MAYBE"}]) == [nothing]


def test_a_report_whose_words_and_json_disagree_lists_nothing(tmp_path: Path) -> None:
    """The list says what the report in words says of what the report as JSON names. Where
    the two do not fit together, it says nothing: half a list would read as the whole."""
    nothing: Open = {"says": "", "count": 0, "clash": False, "asked": False, "groups": []}
    # Of two lines that the report marks with "!", one is under no step. The other one
    # alone would be half a list.
    sent, found, text = asked_of(tmp_path, "flight-home/works-but-risky", no_tickets)
    late = "    ! Alex and Sam would be 5 min too late for this."
    assert late in text
    assert all_open([sent], [found], [text.replace(late, f"\n{late}")]) == [nothing]
    assert all_open([sent], [found], [text])[0]["count"] == 3
    for name, old, new in [
        # The words name one record fewer than the JSON.
        ("flight-home/cannot-work", "  lock-flight: ", "  another: "),
        # The words have no line over the records.
        ("flight-home/cannot-work", "These FACTs and DECISIONs rule out", "These rule out"),
        # The words state one case fewer than the JSON.
        ("a-ticket/depends-on-the-price", "  2. A place from", "  A place from"),
        # A line that the report marks with "!" is under no step.
        ("a-ticket/not-bought-yet", "    ! Sam still", "\n    ! Sam still"),
        # The words have no line for the right that the JSON says somebody has to buy.
        ("a-ticket/not-bought-yet", "    ! Sam still", "    Sam still"),
        # The words do not say what the lines marked "!" mean.
        ("a-ticket/not-bought-yet", "WARNING: not everything", "Not everything"),
        ("flight-home/works-but-risky", "WARNING: no plan is sure", "No plan is sure"),
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
    listed = open_in(file, Report(Answer.FEASIBLE, itinerary=plan, robust=True))
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
        warned = [line.strip() for line in text.split("\n") if line.startswith("    ! ")]
        assert [item["says"] for item in groups.get("warnings", [])] == warned, name
        # Over them is each line with which the report says what they mean.
        explained = "\n".join(line for line in text.split("\n") if line.startswith("WARNING: "))
        over = [group["says"] for group in listed_of["groups"] if group["kind"] == "warnings"]
        assert over == ([explained] if warned else []), name
        assert bool(explained) == bool(warned), name
        # A report that the page can read has a list, also where nothing is open.
        assert listed_of["says"], name
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
        # The last part of a report is about no plan: the time now and what cancelling costs.
        said_of_plans = text.split("\n")[1:]
        last_part = [
            at
            for at, line in enumerate(said_of_plans)
            if line.startswith(("This report uses ", "This FILE does not state the time now."))
        ]
        if last_part:
            said_of_plans = said_of_plans[: last_part[0]]
        assert held == [line.strip() for line in said_of_plans if line.strip()], name
    assert kinds == {"conflict", "cases", "warnings", "choices"}
