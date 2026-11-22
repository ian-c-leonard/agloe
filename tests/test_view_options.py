"""What the page shows of every OPTION of a FILE.

The view sends each OPTION with what the FILE says of it. ``src/agloe/view/static/options.js``
puts that in words, as the report words it, and says plainly what the FILE does not say. It
says who takes part in an OPTION in the plan of the report, and marks what the report names.
It has no page in it, so Node runs it here, through ``view_options.mjs``.

Nothing in it judges a TRIP. An OPTION that no LOCK names and no plan uses is shown like any
other: it is in the FILE.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from agloe.file import read
from tests.stories import EXAMPLES
from tests.test_view_calendar import drawn, in_words, with_its_report

STORY = EXAMPLES / "flight-home"
FILES = sorted(
    path for path in EXAMPLES.rglob("*.json") if not path.name.endswith(".expected.json")
)
SAYS = "Every OPTION of the FILE, with what the FILE says of it."
CHICAGO = " Times are on the clocks of America/Chicago."
UNSAID = "The FILE does not say how early people must be there."
RED = " A red edge marks what the report names among what rules out every plan."
YELLOW = " A yellow edge marks what the report names in what the FILE does not say."

type Trip = dict[str, Any]
type Options = dict[str, Any]


def all_options(
    trips: list[Trip | None],
    reports: list[dict[str, Any] | None] | None = None,
    texts: list[str | None] | None = None,
) -> list[Options]:
    """What the page shows of the OPTIONs of each TRIP, by the page's own code."""
    with_them = reports if reports is not None else [None] * len(trips)
    in_their_words = texts if texts is not None else [None] * len(trips)
    asked = [
        {"trip": sent, "report": found, "text": words}
        for sent, found, words in zip(trips, with_them, in_their_words, strict=True)
    ]
    node = shutil.which("node")
    if node is None:
        if os.environ.get("CI"):
            pytest.fail("the tests of the view need Node")
        pytest.skip("needs Node")
    done = subprocess.run(
        [node, str(Path(__file__).parent / "view_options.mjs")],
        input=json.dumps(asked),
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    shown: list[Options] = json.loads(done.stdout)
    return shown


def options_of(path: Path) -> Options:
    """What the page shows of the OPTIONs of an example, with the report on it."""
    sent, found, text = in_words(path)
    return all_options([sent], [found], [text])[0]


def test_an_option_says_what_the_file_says_of_it() -> None:
    """A visit, a train, a flight and a cab. The trip depends on how long the cab takes."""
    shown = options_of(STORY / "depends-on-the-cab.json")
    # A row shows a time, so the part says whose clocks show it.
    assert shown["says"] == SAYS + CHICAGO + YELLOW
    assert (shown["clash"], shown["asked"]) == (False, True)
    visit, train, flight, cab = shown["options"]
    assert visit == {
        "id": "museum-visit",
        "name": "Museum visit",
        "where": "the Art Institute",
        "when": "Starts at 2:30 pm on Saturday 15 May 2027.",
        "takes": "Takes 1 h.",
        # The FILE does not say how early to be at the museum, and the page says that.
        "arrive": UNSAID,
        "lock": "Alex and Sam are each named by a LOCK.",
        # The report shows no plan, so the page says nothing of one.
        "plan": None,
        "step": 0,
        "records": [
            "visit-time",
            "visit-length",
            "visit-needs-a-ticket",
            "museum-tickets",
            "lock-visit",
        ],
        "clash": [],
        "finds": None,
        "cases": [],
        "asks": [],
    }
    # The train goes from one PLACE to another, and no LOCK names it: the calendar has no step.
    assert (train["where"], train["when"], train["lock"], train["step"]) == (
        "the Art Institute to O'Hare",
        "Can start at any time.",
        "No LOCK names it.",
        None,
    )
    assert (flight["takes"], flight["arrive"]) == (
        "Takes 2 h 30 min.",
        "People must be there 45 min before it starts.",
    )
    # The FILE does not say how long the cab takes, and the report names the cab.
    assert (cab["name"], cab["when"], cab["takes"], cab["arrive"]) == (
        "Cab to O'Hare",
        "Can start at any time.",
        "The FILE does not say how long it takes.",
        UNSAID,
    )
    assert cab["cases"] == [0]
    assert cab["asks"] == ["The trip works if Cab to O'Hare takes 45 min or less."]
    assert all(option["cases"] == [] for option in (visit, train, flight))


def test_an_option_says_who_takes_part_in_it_in_the_plan() -> None:
    """Alex and Sam take the train to the flight, and no LOCK names the train."""
    shown = options_of(STORY / "works.json")
    assert shown["says"] == SAYS + CHICAGO
    said = {option["name"]: option for option in shown["options"]}
    assert said["Museum visit"]["plan"] == "In the plan: Alex and Sam take part."
    train = said["Blue Line to O'Hare"]
    assert (train["plan"], train["lock"]) == (
        "In the plan: Alex and Sam take part.",
        "No LOCK names it.",
    )
    assert train["step"] is not None
    # Alex must have deep-dish pizza, and the plan has no use for dinner at the tavern.
    shown = options_of(EXAMPLES / "a-must" / "works.json")
    said = {option["name"]: option for option in shown["options"]}
    tavern = said["Dinner at the tavern"]
    assert (tavern["plan"], tavern["step"]) == ("Not in the plan.", None)
    assert said["Dinner at the deep-dish place"]["plan"] == "In the plan: Alex takes part."


def test_an_option_has_the_words_for_each_kind_of_start_and_length() -> None:
    sent = drawn(STORY / "works.json")
    first = sent["options"][0]
    kinds: list[tuple[dict[str, Any], str, str, str]] = [
        (
            {"length": {"shortest": 1200, "longest": 2700, "contingent": True}, "margin": 0},
            first["start"] and "Starts at 2:00 pm on Saturday 15 May 2027.",
            "Takes between 20 min and 45 min.",
            "Nobody has to be there before it starts.",
        ),
        (
            {"start": None, "any_time": False, "length": None, "margin": None},
            "The FILE does not say when it starts.",
            "The FILE does not say how long it takes.",
            UNSAID,
        ),
        (
            {"length": {"shortest": 0, "longest": 0, "contingent": False}, "margin": 3661},
            "Starts at 2:00 pm on Saturday 15 May 2027.",
            "Takes no time.",
            "People must be there 1 h 1 min 1 s before it starts.",
        ),
        (
            # A range that the world decides in, whose two ends are the same.
            {"length": {"shortest": 3600, "longest": 3600, "contingent": True}},
            "Starts at 2:00 pm on Saturday 15 May 2027.",
            "Takes between 1 h and 1 h.",
            UNSAID,
        ),
        (
            # A time that Chicago's clocks show twice comes with its offset from UTC.
            {"start": {"at": "2027-11-07T01:30:00", "offset": "UTC-5"}},
            "Starts at 1:30 am (UTC-5) on Sunday 7 November 2027.",
            "Takes 1 h.",
            UNSAID,
        ),
    ]
    trips: list[Trip | None] = []
    for change, _, _, _ in kinds:
        other = json.loads(json.dumps(sent))
        other["options"][0].update(change)
        trips.append(other)
    for (_, when, takes, arrive), shown in zip(kinds, all_options(trips), strict=True):
        option = shown["options"][0]
        assert (option["when"], option["takes"], option["arrive"]) == (when, takes, arrive)


def test_a_range_with_two_ends_that_are_the_same_is_worded_as_the_report_words_it(
    tmp_path: Path,
) -> None:
    """The FILE says that the world decides how long the visit takes: between 1 h and 1 h."""
    content = json.loads((STORY / "cannot-work.json").read_text())
    (length,) = [fact for fact in content["facts"] if fact["id"] == "visit-length"]
    del length["duration"]
    length["contingent_duration"] = {"shortest": "PT1H", "longest": "PT1H"}
    path = tmp_path / "trip.json"
    path.write_text(json.dumps(content))
    sent, found, words = in_words(path)
    assert "visit-length" in found["conflict"]
    assert "visit-length: Museum visit takes between 1 h and 1 h" in words
    (shown,) = all_options([sent], [found], [words])
    assert shown["options"][0]["takes"] == "Takes between 1 h and 1 h."


def test_the_options_name_the_time_zone_only_where_a_row_shows_a_time() -> None:
    sent = drawn(STORY / "works.json")
    assert any(option["start"] for option in sent["options"])
    for option in sent["options"]:
        option["start"] = None
    (shown,) = all_options([sent])
    assert shown["says"] == SAYS


def test_the_options_mark_what_the_report_names_as_ruling_out_every_plan() -> None:
    sent, found = with_its_report(STORY / "cannot-work.json")
    (shown,) = all_options([sent], [found])
    assert shown["says"] == SAYS + CHICAGO + RED
    assert shown["clash"] is True
    named = set(found["conflict"])
    for option in shown["options"]:
        assert option["clash"] == [each for each in option["records"] if each in named]
        assert (option["finds"] is None) is (option["clash"] == [])
    assert any(option["clash"] for option in shown["options"])
    # Only what a report names is marked.
    odd: list[Any] = [None, {}, {**found, "answer": "FEASIBLE"}, {**found, "conflict": "x"}]
    for other in all_options([sent] * len(odd), odd):
        assert other["says"] == SAYS + CHICAGO
        assert all(option["clash"] == [] for option in other["options"])


def test_a_trip_with_no_option_shows_none() -> None:
    sent = drawn(STORY / "works.json")
    sent["options"], sent["steps"] = [], []
    assert (
        all_options([sent, None])
        == [{"says": "", "clash": False, "asked": False, "options": []}] * 2
    )


def test_every_example_shows_its_options_in_the_words_of_the_report() -> None:
    """Each OPTION of each FILE is shown, and a start or a length is worded as the report does."""
    asked = [in_words(path) for path in FILES]
    shown = all_options(
        [sent for sent, _, _ in asked],
        [found for _, found, _ in asked],
        [words for _, _, words in asked],
    )
    starts = lengths = margins = 0
    for path, (sent, _, words), each in zip(FILES, asked, shown, strict=True):
        file = read(path)
        name = f"{path.parent.name}/{path.stem}"
        assert [option["id"] for option in each["options"]] == [
            option.id for option in file.options
        ], name
        for option in each["options"]:
            if option["step"] is not None:
                assert sent["steps"][option["step"]]["option"] == option["id"], name
            # Where the report has a line about this OPTION's start, its length or how early
            # to be there, the page says the same of it.
            called = option["name"]
            if f": {called} starts at " in words:
                starts += 1
                assert f": {called} s{option['when'][1:-1]}" in words, name
            if f": {called} takes " in words and option["takes"].startswith("Takes"):
                lengths += 1
                assert f": {called} t{option['takes'][1:-1]}" in words, name
            early = option["arrive"]
            if early != UNSAID and f" before {called} starts" in words:
                margins += 1
                if early.startswith("People must be there "):
                    span = early[len("People must be there ") : -len(" before it starts.")]
                    assert f" {span} before {called} starts" in words, name
                else:
                    assert ": nobody has to be at " in words, name
    assert min(starts, lengths, margins) > 20
