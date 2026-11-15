"""A FILE that does not follow the format is refused, with the place and the reason."""

import json
import re
from pathlib import Path

import pytest

from agloe.file import Complete, FileError, instant, length, load, read
from tests.stories import (
    Document,
    at,
    complete,
    flight_home,
    takes,
    takes_between,
    way,
    way_between,
)

ROOT = Path(__file__).parent.parent


def problems(document: Document) -> str:
    with pytest.raises(FileError) as refused:
        load(document)
    return str(refused.value)


def test_the_story_is_accepted() -> None:
    file = load(flight_home())
    assert [option.id for option in file.options] == ["museum-visit", "blue-line", "flight"]
    assert (
        file.option("museum-visit").origin
        == file.option("museum-visit").destination
        == "art-institute"
    )


def test_times_and_lengths_are_exact_whole_seconds() -> None:
    assert instant("1970-01-01T00:00:10+00:00[UTC]") == 10
    assert instant("2027-05-15T14:00:00-05:00[America/Chicago]") == instant(
        "2027-05-15T19:00:00+00:00[UTC]"
    )
    assert length("PT2H30M") == 9000
    assert length("PT45S") == 45
    assert length("PT1H1M1S") == 3661


def test_an_unknown_part_is_refused() -> None:
    document = flight_home()
    document["notes"] = []
    assert "notes" in problems(document)


def test_a_missing_part_is_refused() -> None:
    document = flight_home()
    del document["decisions"]
    assert "'decisions' is a required property" in problems(document)


def test_an_id_is_lower_case_words_joined_by_hyphens() -> None:
    document = flight_home()
    document["persons"][0]["id"] = "Alex"
    assert problems(document).startswith("/persons/0/id:")


def test_a_time_carries_its_offset_and_zone() -> None:
    document = flight_home()
    document["facts"][0]["starts_at"] = "2027-05-15T14:00:00"
    assert problems(document).startswith("/facts/0:")


def test_a_time_is_a_real_date() -> None:
    document = flight_home()
    document["facts"][0]["starts_at"] = "2027-02-30T14:00:00-06:00[America/Chicago]"
    assert (
        "/facts/0: 2027-02-30T14:00:00-06:00[America/Chicago] is not a real date and time"
        in problems(document)
    )


def test_a_time_zone_name_starts_each_part_with_a_letter() -> None:
    for name in ("0", "-", "America/0", "+00:00"):
        document = flight_home()
        document["facts"][0]["starts_at"] = f"2027-05-15T14:00:00-05:00[{name}]"
        assert problems(document).startswith("/facts/0:")
    document = flight_home()
    document["facts"][0]["starts_at"] = "2027-05-15T14:00:00-04:00[America/Port-au-Prince]"
    assert load(document).start("museum-visit") is not None


def test_a_time_agrees_with_its_time_zone() -> None:
    """Chicago is six hours behind UTC in January, and five in May."""
    document = flight_home()
    document["facts"][0]["starts_at"] = "2027-01-15T14:00:00-05:00[America/Chicago]"
    assert problems(document) == (
        "/facts/0: 2027-01-15T14:00:00-05:00[America/Chicago] does not agree with its time zone:"
        " America/Chicago is at -06:00 then"
    )
    document["facts"][0]["starts_at"] = "2027-01-15T14:00:00-06:00[America/Chicago]"
    assert load(document).start("museum-visit") is not None


def test_a_time_lies_in_the_years_the_format_can_write() -> None:
    """One hour ahead of UTC, the first hour of the year 0001 falls before it in UTC."""
    document = flight_home()
    document["facts"][0]["starts_at"] = "0001-01-01T00:00:00+01:00[Etc/GMT-1]"
    assert problems(document) == (
        "/facts/0: 0001-01-01T00:00:00+01:00[Etc/GMT-1] is outside the years 0001 to 9999 in UTC"
    )
    document["facts"][0]["starts_at"] = "0001-01-01T01:00:00+01:00[Etc/GMT-1]"
    assert load(document).start("museum-visit") is not None


def test_a_time_zone_is_one_the_database_knows() -> None:
    for name in ("Made/Up", "America", "..", "America/../UTC"):
        document = flight_home()
        document["facts"][0]["starts_at"] = f"2027-05-15T14:00:00-05:00[{name}]"
        assert problems(document) == (
            f"/facts/0: {name} is not a time zone in the time-zone database"
        )


def test_clocks_that_change_are_read_exactly() -> None:
    """Chicago skips 2:00 to 3:00 on 14 March 2027, and repeats 1:00 to 2:00 on 7 November."""
    document = flight_home()
    document["facts"][0]["starts_at"] = "2027-03-14T02:30:00-06:00[America/Chicago]"
    assert "does not agree with its time zone" in problems(document)
    earlier = "2027-11-07T01:30:00-05:00[America/Chicago]"
    later = "2027-11-07T01:30:00-06:00[America/Chicago]"
    document["facts"] = [{"id": "visit-time", "option": "museum-visit", "starts_at": earlier}]
    first = load(document).start("museum-visit")
    document["facts"][0]["starts_at"] = later
    second = load(document).start("museum-visit")
    assert first is not None and second is not None
    assert first.at is not None and second.at is not None
    assert second.at - first.at == 3600


def test_an_offset_from_utc_is_a_real_offset() -> None:
    document = flight_home()
    document["facts"][0]["starts_at"] = "2027-05-15T14:00:00+00:99[UTC]"
    assert problems(document).startswith("/facts/0:")


def test_text_holds_no_line_break() -> None:
    document = flight_home()
    document["persons"][0]["id"] = "alex\n"
    document["facts"][0]["starts_at"] += "\n"
    document["facts"][1]["duration"] = "PT1H\n"
    found = problems(document)
    assert "/persons/0/id: 'alex\\n' holds a control character" in found
    assert "/facts/0/starts_at:" in found
    assert "/facts/1/duration: 'PT1H\\n' holds a control character" in found


def test_a_time_of_day_runs_from_midnight_to_one_second_before_it() -> None:
    document = flight_home()
    document["facts"][0]["starts_at"] = "2027-05-15T24:00:00-05:00[America/Chicago]"
    assert problems(document).startswith("/facts/0:")


def test_a_length_of_time_is_not_endless() -> None:
    document = flight_home()
    document["facts"][1]["duration"] = "PT" + "9" * 5000 + "H"
    assert problems(document).startswith("/facts/1:")


def test_a_name_can_be_read_and_written() -> None:
    document = flight_home()
    document["persons"][0]["name"] = " \u00a0\ufeff "
    document["persons"][1]["name"] = "Sam\u2028Lee"
    document["places"][1]["name"] = "O'Hare\u0085"
    document["places"][0]["name"] = "Art \ud800 Institute"
    found = problems(document)
    assert "/persons/0/name:" in found
    assert "/persons/1/name: 'Sam\\u2028Lee' holds a control character" in found
    assert "/places/0/name: 'Art \\ud800 Institute' holds half of a character" in found
    assert '/places/1/name: "O\'Hare\\x85" holds a control character' in found


def test_the_schema_and_the_reader_agree_about_names() -> None:
    """The schema's pattern, read as every engine reads it, refuses what the reader refuses.

    Half of a surrogate pair is the one exception: the schema's description says so.
    """
    schema = json.loads((ROOT / "src" / "agloe" / "schema" / "file.schema.json").read_text())
    pattern = re.compile(schema["$defs"]["name"]["pattern"])
    names = {
        "Alex": True,
        "Art Institute of Chicago": True,
        "O'Hare ✈": True,
        "Zoë 😀": True,
        "": False,
        " ": False,
        "\u00a0\u3000": False,
        "\ufeff": False,
        "A\nB": False,
        "A\u0085B": False,
        "A\u2028B": False,
        "A\x7fB": False,
        "tab\there": False,
    }
    for name, accepted in names.items():
        document = flight_home()
        document["persons"][0]["name"] = name
        assert (pattern.fullmatch(name) is not None) == accepted, repr(name)
        if accepted:
            assert load(document).persons[0].name == name
        else:
            assert "/persons/0/name" in problems(document), repr(name)


def test_a_fact_states_one_thing() -> None:
    document = flight_home()
    document["facts"][0]["duration"] = "PT1H"
    assert problems(document).startswith("/facts/0: fits no known shape")


def test_every_reference_points_at_something_in_the_file() -> None:
    document = flight_home()
    document["options"][0]["place"] = "the-moon"
    document["facts"][1]["option"] = "a-nap"
    document["decisions"][0]["persons"] = ["alex", "jo"]
    found = problems(document)
    assert "/options/0: the-moon is not a PLACE in this FILE" in found
    assert "/facts/1: a-nap is not a OPTION in this FILE" in found
    assert "/decisions/0: jo is not a PERSON in this FILE" in found


def test_an_id_is_used_once_in_the_whole_file() -> None:
    document = flight_home()
    document["places"][0]["id"] = "alex"
    document["options"][0]["place"] = "alex"
    document["options"][1]["from"] = "alex"
    assert "/places/0: the id alex is used more than once" in problems(document)


def test_a_way_joins_two_places_and_a_fact_says_how_long_it_takes() -> None:
    document = flight_home()
    document["ways"] = [
        way("cab", "art-institute", "ohare"),
        way_between("walk", "art-institute", "home"),
    ]
    document["facts"] += [takes("cab", "PT40M"), takes_between("walk", "PT10M", "PT15M")]
    file = load(document)
    assert [(each.id, each.origin, each.destination, each.both_ways) for each in file.ways] == [
        ("cab", "art-institute", "ohare", False),
        ("walk", "art-institute", "home", True),
    ]
    cab, walk = file.duration("cab"), file.duration("walk")
    assert cab is not None and (cab.shortest, cab.longest, cab.contingent) == (2400, 2400, False)
    assert walk is not None and (walk.shortest, walk.longest, walk.contingent) == (600, 900, True)


def test_a_way_is_checked_like_everything_else() -> None:
    document = flight_home()
    document["ways"] = [
        way("cab", "art-institute", "the-moon"),
        way_between("alex", "ohare", "home"),
        way("stroll", "home", "home"),
    ]
    document["facts"] += [
        takes("cab", "PT40M"),
        {"id": "cab-again", "way": "cab", "duration": "PT30M"},
        takes("museum-visit", "PT5M"),
        takes_between("stroll", "PT20M", "PT10M"),
    ]
    found = problems(document)
    assert "/ways/0: the-moon is not a PLACE in this FILE" in found
    assert "/ways/1: the id alex is used more than once" in found
    assert "/ways/2: a WAY needs two different PLACEs" in found
    assert "/facts/8: another FACT already states this about cab" in found
    assert "/facts/9: museum-visit is not a WAY in this FILE" in found
    assert "/facts/10: the shortest duration is longer than the longest" in found
    document = flight_home()
    document["ways"] = [{"id": "loop", "name": "Loop", "between": ["home", "home"]}]
    assert problems(document).startswith("/ways/0: fits no known shape")


def test_an_option_that_moves_goes_somewhere_else() -> None:
    document = flight_home()
    document["options"][1]["to"] = "art-institute"
    assert "/options/1: an OPTION that moves needs two different PLACEs" in problems(document)


def test_each_fact_is_stated_once() -> None:
    document = flight_home()
    document["facts"].append(
        {"id": "visit-length-again", "option": "museum-visit", "duration": "PT2H"}
    )
    assert "/facts/7: another FACT already states this about museum-visit" in problems(document)


def test_a_complete_fact_names_two_different_places_or_leaves_some_out() -> None:
    document = flight_home()
    document["facts"] += [complete("ohare", "ohare"), complete(None, "the-moon")]
    found = problems(document)
    assert "/facts/7: a COMPLETE FACT needs two different PLACEs" in found
    assert "/facts/8: the-moon is not a PLACE in this FILE" in found
    document["facts"][7:] = [complete("art-institute", None), complete(None, None)]
    stated = [fact for fact in load(document).facts if isinstance(fact, Complete)]
    assert [(fact.origin, fact.destination) for fact in stated] == [
        ("art-institute", None),
        (None, None),
    ]


def test_a_complete_fact_is_stated_once() -> None:
    document = flight_home()
    document["facts"] += [complete("art-institute", "ohare"), complete("art-institute", "ohare")]
    document["facts"][8]["id"] = "ways-again"
    assert "/facts/8: another FACT already states this" in problems(document)


def test_a_range_and_a_span_run_forward() -> None:
    document = flight_home()
    backwards = {"shortest": "PT2H", "longest": "PT1H"}
    document["facts"][3] = {
        "id": "train-length",
        "option": "blue-line",
        "contingent_duration": backwards,
    }
    ways = {
        "from": "art-institute",
        "to": "ohare",
        "leaving": {"earliest": at(18), "latest": at(12)},
    }
    document["facts"].append({"id": "ways", "complete": ways})
    found = problems(document)
    assert "/facts/3: the shortest duration is longer than the longest" in found
    assert "/facts/7: the span ends before it starts" in found


def test_a_file_on_disk_must_be_json(tmp_path: Path) -> None:
    path = tmp_path / "trip.json"
    path.write_text("{ not json")
    with pytest.raises(FileError, match="not readable as JSON"):
        read(path)


def test_a_file_on_disk_states_each_key_once(tmp_path: Path) -> None:
    path = tmp_path / "trip.json"
    path.write_text(
        '{"persons": [], "persons": [], "places": [], "options": [], "ways": [],'
        ' "facts": [], "decisions": []}'
    )
    with pytest.raises(FileError, match="the FILE: states persons more than once"):
        read(path)


def test_a_repeated_key_is_reported_where_it_is(tmp_path: Path) -> None:
    path = tmp_path / "trip.json"
    path.write_text(
        '{"persons": [{"id": "alex", "name": "Alex"}, {"id": "sam", "id": "sam", "name": "Sam"}],'
        ' "places": [], "options": [], "ways": [], "decisions": [],'
        ' "facts": [{"id": "ways", "complete":'
        ' {"from": "a", "to": "b", "leaving": {"earliest": "x", "earliest": "y", "latest": "z"}}}]}'
    )
    with pytest.raises(FileError) as refused:
        read(path)
    assert refused.value.problems == (
        "/persons/1: states id more than once",
        "/facts/0/complete/leaving: states earliest more than once",
    )


def test_two_places_in_a_file_never_share_a_location(tmp_path: Path) -> None:
    path = tmp_path / "trip.json"
    found: list[str] = []
    for text in (
        '{"a/b": {"x": 1, "x": 2}}',
        '{"a": {"b": {"x": 1, "x": 2}}}',
        '{"": {"x": 1, "x": 2}}',
        '{"x": 1, "x": 2}',
        '{"a~b": {"x": 1, "x": 2}}',
    ):
        path.write_text(text)
        with pytest.raises(FileError) as refused:
            read(path)
        found.append(refused.value.problems[0])
    assert found == [
        "/a~1b: states x more than once",
        "/a/b: states x more than once",
        "/: states x more than once",
        "the FILE: states x more than once",
        "/a~0b: states x more than once",
    ]


def test_a_file_is_not_nested_deeply(tmp_path: Path) -> None:
    path = tmp_path / "trip.json"
    for depth in (20, 2_000, 200_000):
        path.write_text("[" * depth + "]" * depth)
        with pytest.raises(FileError, match="nested too deeply"):
            read(path)
    document = flight_home()
    nested: list[object] = []
    for _ in range(2_000):
        nested = [nested]
    document["notes"] = nested
    assert problems(document) == "the FILE: it is nested too deeply"


def test_every_problem_can_be_written_out(tmp_path: Path) -> None:
    path = tmp_path / "trip.json"
    for text in (
        '{"\\ud800": 1, "\\ud800": 2}',
        '{"\\ud800": {"x": 1, "x": 2}}',
        '{"\\n": 1, "\\n": 2}',
        '{"persons": [], "places": [], "options": [], "ways": [], "facts": [], "decisions": [],'
        ' "\\ud800": {"caf\\u00e9": "\\u0007"}}',
    ):
        path.write_text(text)
        with pytest.raises(FileError) as refused:
            read(path)
        for problem in refused.value.problems:
            assert problem.encode("utf-8")
            assert "\n" not in problem
    assert refused.value.problems[-1] == "/\\ud800/caf\\xe9: '\\x07' holds a control character"


def test_an_empty_file_is_a_file() -> None:
    file = load(
        {"persons": [], "places": [], "options": [], "ways": [], "facts": [], "decisions": []}
    )
    assert file.options == ()
