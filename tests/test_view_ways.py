"""What the page shows of the WAYs of a FILE, and of the travel that the FILE lists in full.

The view sends each WAY with what the FILE says of it, and each FACT that the FILE lists every
way of some travel. ``src/agloe/view/static/ways.js`` puts them in words, as the report words
them, says who takes each WAY in the plan of the report, and marks what the report names. It
has no page in it, so Node runs it here, through ``view_part.mjs``.

Nothing in it judges a TRIP. A WAY that no plan uses is shown like any other: it is in the
FILE.
"""

from typing import Any

from agloe.answers import Answer, Report
from agloe.file import Complete, read
from agloe.reference import Step
from tests.stories import EXAMPLES, seconds, starts_at, stays, takes, trip, way_between
from tests.test_view_calendar import drawn, in_words, parts, sent_for, with_its_report

FILES = sorted(
    path for path in EXAMPLES.rglob("*.json") if not path.name.endswith(".expected.json")
)
EVERY = "Every WAY of the FILE, with what the FILE says of it"
IN_FULL = ", and the travel that the FILE says it lists in full"
CHICAGO = " Times are on the clocks of America/Chicago."
RED = " A red edge marks what the report names among what rules out every plan."
YELLOW = " A yellow edge marks what the report names in what the FILE does not say."
UNSAID = "The FILE does not say how long it takes."

type Trip = dict[str, Any]
type Ways = dict[str, Any]


def all_ways(
    trips: list[Trip | None],
    reports: list[dict[str, Any] | None] | None = None,
    texts: list[str | None] | None = None,
) -> list[Ways]:
    """What the page shows of the WAYs of each TRIP, by the page's own code."""
    return parts("ways", trips, reports, texts)


def ways_of(name: str) -> Ways:
    """What the page shows of the WAYs of an example, with the report on it."""
    sent, found, text = in_words(EXAMPLES / f"{name}.json")
    return all_ways([sent], [found], [text])[0]


def test_a_way_says_where_it_goes_how_long_it_takes_and_who_takes_it() -> None:
    """Alex walks from the tower to the park, between the Skydeck visit and lunch."""
    shown = ways_of("a-must-not/works")
    # A row shows a time, so the part says whose clocks show it.
    assert shown["says"] == f"{EVERY}.{CHICAGO}"
    assert (shown["clash"], shown["asked"], shown["travel"]) == (False, False, [])
    assert shown["ways"] == [
        {
            "id": "walk-from-tower",
            "name": "the walk between Willis Tower and Millennium Park",
            "where": "Between Willis Tower and Millennium Park, in both directions.",
            "takes": "Takes 20 min.",
            "plan": ["In the plan: Alex takes it at 11:30 am on Saturday 15 May 2027."],
            # The step of the TRIP in which somebody takes it.
            "steps": [1],
            "records": ["walk-from-tower-length"],
            "clash": [],
            "finds": None,
            "cases": [],
            "asks": [],
        }
    ]


def test_a_way_says_what_the_file_does_not_say_of_it() -> None:
    """The trip depends on how long the walk to the dock takes."""
    shown = ways_of("a-day/depends-on-the-walk")
    assert (shown["clash"], shown["asked"]) == (False, True)
    assert shown["says"].endswith(YELLOW)
    walks = {way["id"]: way for way in shown["ways"]}
    walk = walks["walk-to-dock"]
    assert (walk["takes"], walk["cases"]) == (UNSAID, [0])
    assert walk["asks"] == [
        "The trip works if the walk between Millennium Park and the Riverwalk dock"
        " takes 15 min or less."
    ]
    # The report shows no plan, so the page says nothing of one.
    assert all((way["plan"], way["steps"]) == ([], []) for way in shown["ways"])
    assert all(way["cases"] == [] for id, way in walks.items() if id != "walk-to-dock")


def test_the_travel_that_the_file_lists_in_full_is_said_as_the_report_says_it() -> None:
    """The FILE lists every way straight to Denver that leaves on the afternoon of the TRIP."""
    sent, found, words = in_words(EXAMPLES / "ending-in-denver" / "cannot-work.json")
    (shown,) = all_ways([sent], [found], [words])
    (in_full,) = shown["travel"]
    assert in_full == {
        "record": "every-way-to-denver",
        "says": (
            "Every way straight to Denver that leaves between 12:00 pm on Saturday 15 May 2027"
            " and 7:30 pm is listed."
        ),
        "records": ["every-way-to-denver"],
        # The report names this FACT among what rules out every plan.
        "clash": ["every-way-to-denver"],
        "finds": "The report names every-way-to-denver among what rules out every plan.",
    }
    assert "  every-way-to-denver: every way straight to Denver that leaves between" in words
    assert shown["clash"] is True
    assert shown["says"].endswith(f"{IN_FULL}.{CHICAGO}{RED}")
    # A FACT that leaves both PLACEs out is about travel between any two.
    (in_full,) = ways_of("a-day/cannot-work")["travel"]
    assert in_full["says"] == (
        "Every way from one PLACE straight to another that leaves between 12:00 am on"
        " Friday 14 May 2027 and 11:59 pm is listed."
    )


def test_a_way_is_marked_where_the_report_names_how_long_it_takes() -> None:
    sent, found = with_its_report(EXAMPLES / "a-day" / "cannot-work.json")
    (shown,) = all_ways([sent], [found])
    assert "walk-to-dock-length" in found["conflict"]
    clashes = {way["id"]: way["clash"] for way in shown["ways"]}
    assert clashes["walk-to-dock"] == ["walk-to-dock-length"]
    assert all(clash == [] for id, clash in clashes.items() if id != "walk-to-dock")
    # Only what a report names is marked.
    odd: list[Any] = [None, {}, {**found, "answer": "FEASIBLE"}, {**found, "conflict": "x"}]
    for other in all_ways([sent] * len(odd), odd):
        assert other["clash"] is False
        assert all(each["clash"] == [] for each in (*other["ways"], *other["travel"]))


def span(earliest: str, latest: str) -> dict[str, str]:
    zone = "[America/Chicago]"
    return {"earliest": f"{earliest}-05:00{zone}", "latest": f"{latest}-05:00{zone}"}


def test_each_kind_of_way_and_of_travel_has_its_words() -> None:
    file = trip(
        ["alex"],
        ["hotel", "pier", "park"],
        [],
        [
            takes("ferry", "PT25M"),
            {
                "id": "from-the-hotel",
                "complete": {
                    "from": "hotel",
                    "leaving": span("2027-05-15T09:00:00", "2027-05-16T18:00:00"),
                },
            },
            {
                "id": "hotel-to-pier",
                "complete": {
                    "from": "hotel",
                    "to": "pier",
                    "leaving": span("2027-05-15T09:00:00", "2027-05-15T09:00:30"),
                },
            },
        ],
        [],
        ways=[
            {"id": "ferry", "name": "ferry", "from": "hotel", "to": "pier"},
            way_between("path", "pier", "park"),
        ],
    )
    (shown,) = all_ways([sent_for(file, Report(Answer.UNDETERMINED))])
    ferry, path = shown["ways"]
    assert (ferry["where"], ferry["takes"]) == (
        "From hotel to pier, in that direction only.",
        "Takes 25 min.",
    )
    assert (path["where"], path["takes"]) == ("Between pier and park, in both directions.", UNSAID)
    # A span that ends on another day says which, and a time with seconds shows them.
    assert [each["says"] for each in shown["travel"]] == [
        "Every way straight from hotel that leaves between 9:00 am on Saturday 15 May 2027"
        " and 6:00 pm on 16 May is listed.",
        "Every way straight from hotel to pier that leaves between 9:00 am on"
        " Saturday 15 May 2027 and 9:00:30 am is listed.",
    ]
    assert shown["says"] == f"{EVERY}{IN_FULL}.{CHICAGO}"


def test_a_way_says_each_time_that_somebody_takes_it_in_the_plan() -> None:
    """Alex walks to the pier at 9:00 am, and Alex and Sam walk back at noon."""
    file = trip(
        ["alex", "sam"],
        ["hotel", "pier"],
        [stays("swim", "pier")],
        # The time of the swim gives the FILE its time zone.
        [starts_at("swim", 10), takes("walk", "PT10M")],
        [],
        ways=[way_between("walk", "hotel", "pier"), way_between("tunnel", "hotel", "pier")],
    )
    plan = (
        Step(None, "hotel", "pier", ("alex",), seconds(9), seconds(9, 10), way="walk"),
        Step(None, "pier", "hotel", ("alex", "sam"), seconds(12), seconds(12, 10), way="walk"),
    )
    (shown,) = all_ways([sent_for(file, Report(Answer.FEASIBLE, itinerary=plan))])
    walk, tunnel = shown["ways"]
    assert (walk["steps"], walk["plan"]) == (
        [0, 1],
        [
            "In the plan: alex takes it at 9:00 am on Saturday 15 May 2027.",
            "In the plan: alex and sam take it at 12:00 pm on Saturday 15 May 2027.",
        ],
    )
    assert (tunnel["steps"], tunnel["plan"]) == ([], ["Not in the plan."])


def test_a_file_with_no_way_shows_none() -> None:
    sent = drawn(EXAMPLES / "flight-home" / "works.json")
    assert (sent["ways"], sent["complete_travel"]) == ([], [])
    empty: Ways = {"says": "", "clash": False, "asked": False, "ways": [], "travel": []}
    assert all_ways([sent, None]) == [empty] * 2
    # A FILE with no WAY that lists some travel in full shows that, and says that it has no WAY.
    sent = drawn(EXAMPLES / "ending-in-denver" / "cannot-work.json")
    sent["ways"] = []
    sent["steps"] = [step for step in sent["steps"] if step["way"] is None]
    (shown,) = all_ways([sent])
    assert shown["says"] == f"The FILE has no WAY. It says which travel it lists in full.{CHICAGO}"
    assert len(shown["travel"]) == 1


def test_every_example_shows_its_ways_in_the_words_of_the_report() -> None:
    """Each WAY of each FILE is shown, and a length or a span is worded as the report does."""
    asked = [in_words(path) for path in FILES]
    shown = all_ways(
        [sent for sent, _, _ in asked],
        [found for _, found, _ in asked],
        [words for _, _, words in asked],
    )
    lengths = spans = uses = 0
    for path, (sent, _, words), each in zip(FILES, asked, shown, strict=True):
        file = read(path)
        name = f"{path.parent.name}/{path.stem}"
        assert [way["id"] for way in each["ways"]] == [way.id for way in file.ways], name
        in_full = [fact.id for fact in file.facts if isinstance(fact, Complete)]
        assert [fact["record"] for fact in each["travel"]] == in_full, name
        for way in each["ways"]:
            for step in way["steps"]:
                uses += 1
                assert sent["steps"][step]["way"] == way["id"], name
            assert len(way["plan"]) == (max(len(way["steps"]), 1) if sent["itinerary"] else 0), name
            # Where the report has a line about how long this WAY takes, the page says the same.
            for record in way["records"]:
                if f"  {record}: " in words:
                    lengths += 1
                    assert f"  {record}: {way['name']} t{way['takes'][1:-1]}" in words, name
        for fact in each["travel"]:
            # Where the report names this FACT, the page says it in the same words.
            if f"  {fact['record']}: " in words:
                spans += 1
                said = fact["says"]
                assert f"  {fact['record']}: {said[0].lower()}{said[1:-1]}" in words, name
    assert min(lengths, uses) > 5
    assert spans > 2
