"""The command: ``agloe check FILE`` prints the report for one FILE, in words or as JSON."""

import json
from pathlib import Path

import pytest

from agloe import compiler, report
from agloe.answers import Answer
from agloe.cli import main
from agloe.file import File, load
from agloe.reference import Step, works_as_listed, worst_case
from tests.stories import (
    EXAMPLES,
    any_time,
    at,
    complete,
    cutoff,
    flight_home,
    lasts,
    lasts_between,
    lock,
    moves,
    needs_no_right,
    starts_at,
    stays,
    takes,
    takes_between,
    trip,
    way,
    way_between,
)
from tests.test_answers import two_who_swap_places

FILES = sorted(
    path for path in EXAMPLES.rglob("*.json") if not path.name.endswith(".expected.json")
)


def beside(path: Path, ending: str) -> Path:
    return path.with_name(path.stem + ending)


@pytest.mark.parametrize("path", FILES, ids=lambda path: f"{path.parent.name}/{path.stem}")
def test_the_command_prints_the_expected_result(
    path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """As JSON, the command prints exactly the expected result beside the example."""
    code = main(["check", str(path), "--json"])
    printed = json.loads(capsys.readouterr().out)
    expected = json.loads(beside(path, ".expected.json").read_text())
    assert printed == expected
    assert code == (0 if expected["answer"] == "FEASIBLE" else 1)


@pytest.mark.parametrize("path", FILES, ids=lambda path: f"{path.parent.name}/{path.stem}")
def test_the_command_prints_the_expected_words(
    path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["check", str(path)])
    assert capsys.readouterr().out == beside(path, ".expected.txt").read_text()


def test_a_file_that_breaks_the_format_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    document = flight_home()
    document["facts"][0]["starts_at"] = "2027-01-15T14:00:00-05:00[America/Chicago]"
    del document["places"][0]["name"]
    path = tmp_path / "trip.json"
    path.write_text(json.dumps(document))
    assert main(["check", str(path)]) == 2
    printed = capsys.readouterr()
    assert printed.out == ""
    assert printed.err.splitlines() == [
        f"{path} does not follow the format:",
        "  /places/0: 'name' is a required property",
    ]


def test_a_file_that_is_not_there_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "nowhere.json"
    assert main(["check", str(path)]) == 2
    assert capsys.readouterr().err == f"{path}: No such file or directory\n"


def with_a_cab(*facts: dict[str, object], only_listed_ways: bool = False) -> str:
    """The story in which they leave the museum too late, with a cab added, in words."""
    document = json.loads((EXAMPLES / "flight-home" / "depends-on-another-way.json").read_text())
    document["options"].append(moves("cab", "art-institute", "ohare"))
    document["options"][-1]["name"] = "Cab to O'Hare"
    document["facts"] += [*facts, needs_no_right("cab")]
    if only_listed_ways:
        document["facts"].append(complete(None, "ohare"))
    file = load(document)
    return report.as_text(file, compiler.check(file))


def test_several_ways_to_make_a_trip_work_are_numbered() -> None:
    assert with_a_cab(any_time("cab")).splitlines()[2:] == [
        "The trip works in any of these cases:",
        "  1. Cab to O'Hare takes 45 min or less.",
        "  2. There are other WAYs from the Art Institute to O'Hare that take 45 min or less.",
        "",
        "Other WAYs help only if they can be taken when the plan needs them, with a right where"
        " they need one.",
    ]


def test_two_unknown_facts_that_are_both_needed_are_joined() -> None:
    assert with_a_cab(only_listed_ways=True).splitlines()[2:] == [
        "The trip works if Cab to O'Hare can start at any time and Cab to O'Hare is quick enough."
    ]


def test_an_unknown_cutoff_is_named_with_its_place() -> None:
    document = flight_home()
    document["facts"] = [fact for fact in document["facts"] if fact["id"] != "bag-drop"]
    file = load(document)
    assert report.as_text(file, compiler.check(file)).splitlines()[2] == (
        "The trip works if people must be at O'Hare 1 h or less before Flight home starts."
    )


def test_a_plan_shows_its_days_and_an_unknown_end() -> None:
    """Dinner is late on the 15th. The night train leaves the next day, and nobody timed it."""
    file = trip(
        ["alex"],
        ["hotel", "station"],
        [stays("dinner", "hotel"), moves("night-train", "hotel", "station")],
        [
            starts_at("dinner", 23, 30),
            lasts("dinner", "PT45M"),
            any_time("night-train"),
            cutoff("night-train", "PT0S"),
        ],
        [lock("dinner", "alex"), lock("night-train", "alex")],
    )
    found = compiler.check(file)
    assert found.answer is Answer.FEASIBLE
    assert report.as_text(file, found).splitlines()[:7] == [
        "FEASIBLE: this trip works.",
        "",
        "Saturday 15 May 2027 (times in America/Chicago)",
        "  11:30 pm to 12:15 am on 16 May: dinner, alex",
        "",
        "Sunday 16 May 2027 (times in America/Chicago)",
        "  12:15 am to an unknown time: night-train, alex",
    ]
    assert report.as_json(file, found)["itinerary"] == [
        {"option": "dinner", "persons": ["alex"], "start": at(23, 30), "end": at(0, 15, day=16)},
        {"option": "night-train", "persons": ["alex"], "start": at(0, 15, day=16), "end": None},
    ]


def a_walk_to_dinner(*facts: dict[str, object]) -> File:
    """Alex and Sam have a drink at the hotel at 6:00 pm and dinner at a restaurant at 7:00 pm."""
    return trip(
        ["alex", "sam"],
        ["hotel", "restaurant"],
        [stays("drink", "hotel"), stays("dinner", "restaurant")],
        [
            starts_at("drink", 18),
            lasts("drink", "PT30M"),
            starts_at("dinner", 19),
            lasts("dinner", "PT2H"),
            cutoff("dinner", "PT0S"),
            *facts,
        ],
        [lock("drink", "alex", "sam"), lock("dinner", "alex", "sam")],
        [way_between("walk", "hotel", "restaurant")],
    )


def test_a_plan_shows_the_ways_people_take() -> None:
    """In words, Alex and Sam share a line for the walk. As JSON, each one's walk is a step."""
    file = a_walk_to_dinner(takes_between("walk", "PT10M", "PT20M"))
    found = compiler.check(file)
    words = report.as_text(file, found).splitlines()
    assert words[2:6] == [
        "Saturday 15 May 2027 (times in America/Chicago)",
        "  6:00 pm to 6:30 pm: drink, alex and sam",
        "  6:30 pm to 6:50 pm: walk, alex and sam",
        "  7:00 pm to 9:00 pm: dinner, alex and sam",
    ]
    assert "  walk-length: walk takes between 10 min and 20 min" in words
    assert report.as_json(file, found)["itinerary"] == [
        {"option": "drink", "persons": ["alex", "sam"], "start": at(18), "end": at(18, 30)},
        {"way": "walk", "persons": ["alex"], "start": at(18, 30), "end": at(18, 50)},
        {"way": "walk", "persons": ["sam"], "start": at(18, 30), "end": at(18, 50)},
        {"option": "dinner", "persons": ["alex", "sam"], "start": at(19), "end": at(21)},
    ]


def test_a_way_nobody_timed_is_named_in_what_is_missing() -> None:
    file = a_walk_to_dinner()
    found = compiler.check(file)
    assert report.as_text(file, found).splitlines()[2:] == [
        "The trip works in any of these cases:",
        "  1. walk takes 30 min or less.",
        "  2. There are other WAYs from hotel to restaurant that take 30 min or less.",
        "",
        "Other WAYs help only if they can be taken when the plan needs them, with a right where"
        " they need one.",
    ]
    assert report.as_json(file, found)["missing"] == [
        [{"what": "duration", "way": "walk", "at_most": "PT30M"}],
        [{"what": "other ways", "from": "hotel", "to": "restaurant", "at_most": "PT30M"}],
    ]


def test_a_trip_with_nothing_to_do_says_so() -> None:
    file = trip([], [], [], [], [])
    assert report.as_text(file, compiler.check(file)) == (
        "FEASIBLE: this trip works.\n\nNobody has to do anything.\n"
    )


def test_a_report_with_a_time_past_the_year_9999_is_not_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The stay starts in the last second of the year 9999 and ends one second later."""
    document = {
        "persons": [{"id": "alex", "name": "Alex"}],
        "places": [{"id": "pier", "name": "Navy Pier"}],
        "options": [stays("fireworks", "pier")],
        "ways": [],
        "wants": [],
        "facts": [
            {
                "id": "fireworks-time",
                "option": "fireworks",
                "starts_at": "9999-12-31T23:59:59+00:00[UTC]",
            },
            lasts("fireworks", "PT1S"),
            needs_no_right("fireworks"),
        ],
        "decisions": [lock("fireworks", "alex")],
    }
    assert compiler.check(load(document)).answer is Answer.FEASIBLE
    path = tmp_path / "trip.json"
    path.write_text(json.dumps(document))
    for arguments in (["check", str(path)], ["check", str(path), "--json"]):
        assert main(arguments) == 2
        printed = capsys.readouterr()
        assert printed.out == ""
        assert printed.err == (
            f"{path}: the report holds a time outside the years 0001 to 9999, "
            "so it cannot be written\n"
        )


def test_a_complete_fact_is_put_in_words_for_the_places_it_names() -> None:
    """Alex is at the hotel at 9:00 and at the pier at 10:00, and the FILE lists no way there."""
    words = {
        ("hotel", "pier"): "ways-hotel-pier: every way straight from hotel to pier",
        (None, "pier"): "ways-to-pier: every way straight to pier",
        ("hotel", None): "ways-from-hotel: every way straight from hotel",
        (None, None): "ways: every way from one PLACE straight to another",
    }
    for (origin, destination), expected in words.items():
        file = trip(
            ["alex"],
            ["hotel", "pier"],
            [stays("breakfast", "hotel"), stays("fireworks", "pier")],
            [
                starts_at("breakfast", 9),
                lasts("breakfast", "PT0S"),
                starts_at("fireworks", 10),
                complete(origin, destination),
            ],
            [lock("breakfast", "alex"), lock("fireworks", "alex")],
        )
        printed = report.as_text(file, compiler.check(file)).splitlines()
        assert printed[0] == "INFEASIBLE: this trip cannot work."
        span = "that leaves between 12:00 am on Saturday 15 May 2027 and 11:59 pm is listed"
        assert f"  {expected} {span}" in printed


def test_a_warning_is_printed_under_the_step_it_is_about() -> None:
    """The visit can run an hour late. Then Alex is still there when the walk should start."""
    file = trip(
        ["alex"],
        ["gallery", "pier"],
        [stays("visit", "gallery"), stays("dinner", "pier")],
        [
            starts_at("visit", 9),
            lasts_between("visit", "PT30M", "PT1H30M"),
            starts_at("dinner", 10, 30),
            lasts("dinner", "PT1H"),
            cutoff("dinner", "PT0S"),
            takes("walk", "PT30M"),
        ],
        [lock("visit", "alex"), lock("dinner", "alex")],
        [way("walk", "gallery", "pier")],
    )
    found = compiler.check(file)
    assert report.as_json(file, found)["at_worst"] == [
        {
            "constraint": "Each PERSON is in one place at a time",
            "step": 1,
            "way": "walk",
            "from": "gallery",
            "to": "pier",
            "start": at(9, 30),
            "persons": ["alex"],
            "late": "PT1H",
        }
    ]
    assert report.as_text(file, found).splitlines()[3:9] == [
        "  9:00 am to 9:30 am: visit, alex",
        "  9:30 am to 10:00 am: walk, alex",
        "    ! alex would still be busy for 1 h when this starts.",
        "  10:30 am to 11:30 am: dinner, alex",
        "",
        "WARNING: no plan is sure to hold if the uncertain parts take their longest."
        ' Each line marked "!" says what would go wrong at the step above it.',
    ]


def test_a_plan_that_holds_with_uncertain_parts_says_so() -> None:
    document = json.loads((EXAMPLES / "flight-home" / "works-but-risky.json").read_text())
    for fact in document["facts"]:
        if fact["id"] == "train-length":
            fact["contingent_duration"]["longest"] = "PT1H15M"
    file = load(document)
    lines = report.as_text(file, compiler.check(file)).splitlines()
    assert lines[0] == "FEASIBLE: this trip works."
    assert lines[7] == (
        "This plan holds however long the uncertain parts take, within the ranges the FILE states."
    )


def test_times_show_their_offset_when_the_clocks_change() -> None:
    """Chicago's clocks go back at 2:00 am on 7 November 2027, so 1:15 am comes twice."""
    document = {
        "persons": [{"id": "alex", "name": "Alex"}],
        "places": [{"id": "hotel", "name": "Hotel"}],
        "options": [stays("night-shift", "hotel")],
        "ways": [],
        "wants": [],
        "facts": [
            {
                "id": "night-shift-time",
                "option": "night-shift",
                "starts_at": "2027-11-07T01:45:00-05:00[America/Chicago]",
            },
            lasts("night-shift", "PT30M"),
            needs_no_right("night-shift"),
        ],
        "decisions": [lock("night-shift", "alex")],
    }
    file = load(document)
    lines = report.as_text(file, compiler.check(file)).splitlines()
    assert lines[2:4] == [
        "Sunday 7 November 2027 (times in America/Chicago)",
        "  1:45 am (UTC-5) to 1:15 am (UTC-6): night-shift, Alex",
    ]
    assert lines[6] == (
        "  night-shift-time: night-shift starts at 1:45 am (UTC-5) on Sunday 7 November 2027"
    )


def test_the_same_way_taken_twice_has_a_line_each_time() -> None:
    """Alex and Sam walk to dinner and walk back for a nightcap at the hotel."""
    file = trip(
        ["alex", "sam"],
        ["hotel", "restaurant"],
        [stays("dinner", "restaurant"), stays("nightcap", "hotel")],
        [
            starts_at("dinner", 19),
            lasts("dinner", "PT2H"),
            starts_at("nightcap", 21, 30),
            lasts("nightcap", "PT30M"),
            cutoff("nightcap", "PT0S"),
            takes("walk", "PT20M"),
        ],
        [lock("dinner", "alex", "sam"), lock("nightcap", "alex", "sam")],
        [way_between("walk", "hotel", "restaurant")],
    )
    assert report.as_text(file, compiler.check(file)).splitlines()[3:6] == [
        "  7:00 pm to 9:00 pm: dinner, alex and sam",
        "  9:00 pm to 9:20 pm: walk, alex and sam",
        "  9:30 pm to 10:00 pm: nightcap, alex and sam",
    ]
    earlier = [starts_at("nightcap", 18), lasts("nightcap", "PT30M"), starts_at("dinner", 19)]
    there_and_back = trip(
        ["alex", "sam"],
        ["hotel", "restaurant"],
        [stays("nightcap", "hotel"), stays("dinner", "restaurant"), stays("bed", "hotel")],
        [
            *earlier,
            lasts("dinner", "PT2H"),
            cutoff("dinner", "PT0S"),
            starts_at("bed", 22),
            cutoff("bed", "PT0S"),
            takes("walk", "PT20M"),
        ],
        [lock(name, "alex", "sam") for name in ("nightcap", "dinner", "bed")],
        [way_between("walk", "hotel", "restaurant")],
    )
    lines = report.as_text(there_and_back, compiler.check(there_and_back)).splitlines()
    assert [line for line in lines if ": walk, " in line] == [
        "  6:30 pm to 6:50 pm: walk, alex and sam",
        "  9:00 pm to 9:20 pm: walk, alex and sam",
    ]


def test_a_way_that_must_take_no_time_is_put_plainly() -> None:
    """Alex is at the hotel and at the restaurant at the same instant."""
    file = trip(
        ["alex"],
        ["hotel", "restaurant"],
        [stays("call", "hotel"), stays("toast", "restaurant")],
        [
            starts_at("call", 19),
            lasts("call", "PT0S"),
            starts_at("toast", 19),
            lasts("toast", "PT0S"),
            cutoff("toast", "PT0S"),
            cutoff("call", "PT0S"),
        ],
        [lock("call", "alex"), lock("toast", "alex")],
    )
    assert report.as_text(file, compiler.check(file)).splitlines()[2:] == [
        "The trip works in any of these cases:",
        "  1. There are other WAYs from hotel to restaurant that take no time.",
        "  2. There are other WAYs from restaurant to hotel that take no time.",
        "",
        "Other WAYs help only if they can be taken when the plan needs them, with a right where"
        " they need one.",
    ]


def test_the_plan_in_words_keeps_every_step_in_its_order() -> None:
    """Alex takes the same WAY twice at 9:00, before and after a ride that takes no time.

    Both times are printed. Read back as an ITINERARY, the printed plan still works.
    """
    file = trip(
        ["alex"],
        ["a", "b"],
        [stays("first", "a"), moves("ride", "b", "a"), stays("last", "b")],
        [
            starts_at("first", 8),
            lasts("first", "PT1H"),
            starts_at("ride", 9),
            lasts("ride", "PT0S"),
            cutoff("ride", "PT0S"),
            starts_at("last", 9),
            lasts("last", "PT1H"),
            cutoff("last", "PT0S"),
            takes("ab", "PT0S"),
        ],
        [lock("first", "alex"), lock("ride", "alex"), lock("last", "alex")],
        [way("ab", "a", "b")],
    )
    found = compiler.check(file)
    assert report.as_text(file, found).splitlines()[3:8] == [
        "  8:00 am to 9:00 am: first, alex",
        "  9:00 am to 9:00 am: ab, alex",
        "  9:00 am to 9:00 am: ride, alex",
        "  9:00 am to 9:00 am: ab, alex",
        "  9:00 am to 10:00 am: last, alex",
    ]
    assert works_as_listed(file, worst_case(file), tuple(report.together(found.itinerary)))


def test_persons_share_a_line_only_where_their_steps_are_next_to_each_other() -> None:
    """Alex goes to b and back at 9:00 while Sam goes to a and back, by the same WAY.

    Alex's way back and Sam's way there are the same WAY at the same time, but other steps come
    between them, so they stay on two lines.
    """
    file = two_who_swap_places()
    found = compiler.check(file)
    shown = report.together(found.itinerary)
    assert [(step.origin, step.persons) for step in shown if step.way] == [
        ("a", ("alex",)),
        ("b", ("alex",)),
        ("b", ("sam",)),
        ("a", ("sam",)),
    ]
    assert works_as_listed(file, worst_case(file), tuple(shown))


def test_a_warning_names_together_the_persons_who_share_a_line() -> None:
    """The drink can run twenty minutes over, into the time Alex and Sam should start walking."""
    file = trip(
        ["alex", "sam"],
        ["hotel", "restaurant"],
        [stays("drink", "hotel"), stays("dinner", "restaurant")],
        [
            starts_at("drink", 18),
            lasts_between("drink", "PT30M", "PT50M"),
            starts_at("dinner", 19),
            lasts("dinner", "PT2H"),
            cutoff("dinner", "PT0S"),
            takes("walk", "PT20M"),
        ],
        [lock("drink", "alex", "sam"), lock("dinner", "alex", "sam")],
        [way_between("walk", "hotel", "restaurant")],
    )
    found = compiler.check(file)
    assert [(broken.step, broken.persons) for broken in found.at_worst] == [
        (1, ("alex",)),
        (2, ("sam",)),
    ]
    assert report.as_text(file, found).splitlines()[4:6] == [
        "  6:30 pm to 6:50 pm: walk, alex and sam",
        "    ! alex and sam would still be busy for 20 min when this starts.",
    ]


def test_warnings_on_two_lines_of_the_plan_stay_apart() -> None:
    """Alex has a drink at the hotel and Sam at a bar. Each drink can run twenty minutes over.

    Both then walk twenty minutes to dinner, by different WAYs. Each walk has its own line in
    the plan, so each has its own warning.
    """
    file = trip(
        ["alex", "sam"],
        ["hotel", "bar", "restaurant"],
        [stays("drink", "hotel"), stays("beer", "bar"), stays("dinner", "restaurant")],
        [
            starts_at("drink", 18),
            lasts_between("drink", "PT30M", "PT50M"),
            starts_at("beer", 18),
            lasts_between("beer", "PT30M", "PT50M"),
            starts_at("dinner", 19),
            lasts("dinner", "PT2H"),
            cutoff("dinner", "PT0S"),
            takes("walk", "PT20M"),
            takes("stroll", "PT20M"),
        ],
        [lock("drink", "alex"), lock("beer", "sam"), lock("dinner", "alex", "sam")],
        [way("walk", "hotel", "restaurant"), way("stroll", "bar", "restaurant")],
    )
    words = report.as_text(file, compiler.check(file)).splitlines()
    marked = [
        (words[number - 1].strip(), line.strip())
        for number, line in enumerate(words)
        if line.startswith("    ! ")
    ]
    assert marked == [
        (
            "6:30 pm to 6:50 pm: walk, alex",
            "! alex would still be busy for 20 min when this starts.",
        ),
        (
            "6:30 pm to 6:50 pm: stroll, sam",
            "! sam would still be busy for 20 min when this starts.",
        ),
    ]


def test_a_person_never_shares_a_line_with_themselves() -> None:
    walk = Step(None, "hotel", "restaurant", ("alex",), 0, 600, "walk")
    assert report.together((walk, walk)) == [walk, walk]
    with_sam = Step(None, "hotel", "restaurant", ("sam",), 0, 600, "walk")
    assert report.together((walk, with_sam)) == [
        Step(None, "hotel", "restaurant", ("alex", "sam"), 0, 600, "walk")
    ]


def test_a_warning_sits_under_the_right_one_of_two_lines_that_read_the_same() -> None:
    """Alex takes the same WAY twice at 9:00, before and after a ride that can take a minute.

    If the ride takes that minute, Alex is not back for the second time. Both lines of the plan
    read the same, and the warning is printed under the second one.
    """
    file = trip(
        ["alex"],
        ["a", "b"],
        [stays("first", "a"), moves("ride", "b", "a"), stays("last", "b")],
        [
            starts_at("first", 8),
            lasts("first", "PT1H"),
            starts_at("ride", 9),
            lasts_between("ride", "PT0S", "PT1M"),
            cutoff("ride", "PT0S"),
            starts_at("last", 9),
            lasts("last", "PT1H"),
            cutoff("last", "PT0S"),
            takes("ab", "PT0S"),
        ],
        [lock("first", "alex"), lock("ride", "alex"), lock("last", "alex")],
        [way("ab", "a", "b")],
    )
    words = report.as_text(file, compiler.check(file)).splitlines()
    assert words[4] == words[6] == "  9:00 am to 9:00 am: ab, alex"
    assert not words[5].startswith("    ! ")
    assert words[7] == "    ! alex would still be busy for 1 min when this starts."


def test_records_with_the_same_name_show_their_ids() -> None:
    """Two travelers are both called Alex, and only one of them is LOCKed onto the late stop."""
    document = {
        "persons": [{"id": "alex-a", "name": "Alex"}, {"id": "alex-b", "name": "Alex"}],
        "places": [{"id": "hotel", "name": "the hotel"}],
        "options": [stays("call", "hotel"), stays("nap", "hotel")],
        "ways": [],
        "wants": [],
        "facts": [
            starts_at("call", 9),
            lasts_between("call", "PT30M", "PT1H"),
            starts_at("nap", 9, 30),
            lasts("nap", "PT1H"),
            needs_no_right("call"),
            needs_no_right("nap"),
        ],
        "decisions": [lock("call", "alex-a", "alex-b"), lock("nap", "alex-b")],
    }
    file = load(document)
    words = report.as_text(file, compiler.check(file)).splitlines()
    assert "  9:00 am to 9:30 am: call, Alex (alex-a) and Alex (alex-b)" in words
    assert "    ! Alex (alex-b) would still be busy for 30 min when this starts." in words
    assert "  lock-nap: Alex (alex-b) takes part in nap" in words


def test_a_warning_names_only_the_persons_in_trouble_on_a_shared_line() -> None:
    """Alex has a drink and Sam takes a call, both at the hotel. Only the call can run long.

    They walk to dinner together, on one line of the plan. The warning under that line names
    Sam alone.
    """
    file = trip(
        ["alex", "sam"],
        ["hotel", "restaurant"],
        [stays("drink", "hotel"), stays("call", "hotel"), stays("dinner", "restaurant")],
        [
            starts_at("drink", 18),
            lasts("drink", "PT30M"),
            starts_at("call", 18),
            lasts_between("call", "PT30M", "PT50M"),
            starts_at("dinner", 19),
            lasts("dinner", "PT2H"),
            cutoff("dinner", "PT0S"),
            takes("walk", "PT20M"),
        ],
        [lock("drink", "alex"), lock("call", "sam"), lock("dinner", "alex", "sam")],
        [way_between("walk", "hotel", "restaurant")],
    )
    assert report.as_text(file, compiler.check(file)).splitlines()[5:8] == [
        "  6:30 pm to 6:50 pm: walk, alex and sam",
        "    ! sam would still be busy for 20 min when this starts.",
        "  7:00 pm to 9:00 pm: dinner, alex and sam",
    ]


def test_a_warning_follows_the_order_the_plan_shows() -> None:
    """Sam rides back to a one second before midnight, takes a WAY to b, and is there at midnight.

    The ride can take a minute. In the plan shown, the WAY comes after the ride, so the warning
    is worked out in that order too: Sam is still riding when the WAY should start.
    """
    document = {
        "persons": [{"id": "sam", "name": "Sam"}],
        "places": [{"id": "a", "name": "a"}, {"id": "b", "name": "b"}],
        "options": [moves("back", "b", "a"), stays("last", "b")],
        "ways": [way("ab", "a", "b")],
        "wants": [],
        "facts": [
            {
                "id": "back-time",
                "option": "back",
                "starts_at": "2027-12-31T23:59:59-06:00[America/Chicago]",
            },
            lasts_between("back", "PT0S", "PT1M"),
            cutoff("back", "PT0S"),
            {
                "id": "last-time",
                "option": "last",
                "starts_at": "2028-01-01T00:00:00-06:00[America/Chicago]",
            },
            lasts("last", "PT1H"),
            cutoff("last", "PT0S"),
            needs_no_right("back"),
            needs_no_right("last"),
            takes("ab", "PT0S"),
        ],
        "decisions": [lock("back", "sam"), lock("last", "sam")],
    }
    file = load(document)
    assert report.as_text(file, compiler.check(file)).splitlines()[2:10] == [
        "Friday 31 December 2027 (times in America/Chicago)",
        "  11:59:59 pm to 11:59:59 pm: back, Sam",
        "  11:59:59 pm to 11:59:59 pm: ab, Sam",
        "    ! Sam would still be busy for 1 min when this starts.",
        "",
        "Saturday 1 January 2028 (times in America/Chicago)",
        "  12:00 am to 1:00 am: last, Sam",
        "    ! Sam would still be busy for 59 s when this starts.",
    ]


def test_an_offset_is_shown_to_the_second() -> None:
    """Until 11 March 1911, clocks in Paris ran 9 minutes and 21 seconds ahead of UTC."""
    document = {
        "persons": [{"id": "alex", "name": "Alex"}],
        "places": [{"id": "cafe", "name": "the cafe"}],
        "options": [stays("coffee", "cafe"), stays("paper", "cafe")],
        "ways": [],
        "wants": [],
        "facts": [
            any_time("coffee"),
            lasts("coffee", "PT1H"),
            {
                "id": "paper-time",
                "option": "paper",
                "starts_at": "1911-03-11T00:00:00+00:00[Europe/Paris]",
            },
            lasts("paper", "PT1M"),
            needs_no_right("coffee"),
            needs_no_right("paper"),
        ],
        "decisions": [lock("coffee", "alex"), lock("paper", "alex")],
    }
    file = load(document)
    words = report.as_text(file, compiler.check(file)).splitlines()
    assert words[3] == "  11:09:21 pm (UTC+0:09:21) to 12:00 am (UTC+0) on 11 March: coffee, Alex"


def test_an_end_in_another_year_shows_its_year() -> None:
    document = {
        "persons": [{"id": "alex", "name": "Alex"}],
        "places": [{"id": "cabin", "name": "the cabin"}],
        "options": [stays("stay", "cabin")],
        "ways": [],
        "wants": [],
        "facts": [
            {"id": "stay-time", "option": "stay", "starts_at": "2027-05-14T23:30:00+00:00[UTC]"},
            lasts("stay", "PT8784H"),
            needs_no_right("stay"),
        ],
        "decisions": [lock("stay", "alex")],
    }
    file = load(document)
    words = report.as_text(file, compiler.check(file)).splitlines()
    assert words[2:4] == [
        "Friday 14 May 2027 (times in UTC)",
        "  11:30 pm to 11:30 pm on 14 May 2028: stay, Alex",
    ]


def test_no_two_records_are_shown_by_the_same_name() -> None:
    """Two travelers are called Alex. A third is called "Alex (b)", as the second is shown.

    A name that ends like a name with its id is put in quotes, so the three stay apart.
    """
    document = {
        "persons": [
            {"id": "a", "name": "Alex"},
            {"id": "b", "name": "Alex"},
            {"id": "c", "name": "Alex (b)"},
        ],
        "places": [{"id": "hotel", "name": "the hotel"}],
        "options": [stays("call", "hotel")],
        "ways": [],
        "wants": [],
        "facts": [starts_at("call", 9), lasts("call", "PT30M"), needs_no_right("call")],
        "decisions": [lock("call", "a", "b", "c")],
    }
    file = load(document)
    words = report.as_text(file, compiler.check(file)).splitlines()
    assert words[3] == '  9:00 am to 9:30 am: call, Alex (a), Alex (b) and "Alex (b)"'


def test_a_name_that_the_report_uses_for_no_name_is_in_quotes() -> None:
    """A traveler is called Nobody, and another is called people. "call, Nobody" would read
    as a call with nobody in it, so each of those names is in quotes wherever it is shown."""
    document = {
        "persons": [{"id": "a", "name": "Nobody"}, {"id": "b", "name": "people"}],
        "places": [{"id": "hotel", "name": "the hotel"}],
        "options": [stays("call", "hotel")],
        "ways": [],
        "wants": [],
        "facts": [starts_at("call", 9), lasts("call", "PT30M"), needs_no_right("call")],
        "decisions": [lock("call", "a", "b")],
    }
    file = load(document)
    words = report.as_text(file, compiler.check(file)).splitlines()
    assert words[3] == '  9:00 am to 9:30 am: call, "Nobody" and "people"'
    assert '  lock-call: "Nobody" and "people" take part in call' in words
    # A name that only holds such a word is no such word.
    document["persons"] = [{"id": "a", "name": "Nobody Owens"}, {"id": "b", "name": "Sam"}]
    file = load(document)
    words = report.as_text(file, compiler.check(file)).splitlines()
    assert words[3] == "  9:00 am to 9:30 am: call, Nobody Owens and Sam"


def test_a_warning_falls_under_the_day_it_is_about() -> None:
    """Alex takes the same walk at 9:00 am on Saturday and on Sunday. Only Sunday's is at risk."""

    def on(day: int, hour: int, minute: int = 0) -> str:
        return f"2027-05-{day:02d}T{hour:02d}:{minute:02d}:00-05:00[America/Chicago]"

    document = {
        "persons": [{"id": "alex", "name": "Alex"}],
        "places": [{"id": "hotel", "name": "the hotel"}, {"id": "pier", "name": "the pier"}],
        "options": [
            stays("coffee", "hotel"),
            stays("swim", "pier"),
            moves("shuttle", "pier", "hotel"),
            stays("sail", "pier"),
        ],
        "ways": [way("walk", "hotel", "pier")],
        "wants": [],
        "facts": [
            {"id": "coffee-time", "option": "coffee", "starts_at": on(15, 8)},
            lasts("coffee", "PT1H"),
            {"id": "swim-time", "option": "swim", "starts_at": on(15, 10)},
            lasts("swim", "PT0S"),
            cutoff("swim", "PT0S"),
            {"id": "shuttle-time", "option": "shuttle", "starts_at": on(16, 8)},
            lasts_between("shuttle", "PT1H", "PT1H1M"),
            cutoff("shuttle", "PT0S"),
            {"id": "sail-time", "option": "sail", "starts_at": on(16, 9, 20)},
            lasts("sail", "PT1H"),
            cutoff("sail", "PT0S"),
            *(needs_no_right(name) for name in ("coffee", "swim", "shuttle", "sail")),
            takes("walk", "PT20M"),
        ],
        "decisions": [lock(name, "alex") for name in ("coffee", "swim", "shuttle", "sail")],
    }
    file = load(document)
    words = report.as_text(file, compiler.check(file)).splitlines()
    saturday, sunday = (
        words.index("Saturday 15 May 2027 (times in America/Chicago)"),
        words.index("Sunday 16 May 2027 (times in America/Chicago)"),
    )
    marks = [number for number, line in enumerate(words) if line.startswith("    ! ")]
    assert len(marks) == 1
    assert saturday < sunday < marks[0]
    assert words[marks[0] - 1] == "  9:00 am to 9:20 am: walk, Alex"
