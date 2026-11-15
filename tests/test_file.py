"""A FILE that does not follow the format is refused, with the place and the reason."""

from pathlib import Path

import pytest

from agloe.file import FileError, instant, length, load, read
from tests.stories import Document, at, complete, flight_home


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
    assert problems(document).startswith("persons/0/id:")


def test_a_time_carries_its_offset_and_zone() -> None:
    document = flight_home()
    document["facts"][0]["starts_at"] = "2027-05-15T14:00:00"
    assert problems(document).startswith("facts/0:")


def test_a_time_is_a_real_date() -> None:
    document = flight_home()
    document["facts"][0]["starts_at"] = "2027-02-30T14:00:00-06:00[America/Chicago]"
    assert (
        "facts/0: 2027-02-30T14:00:00-06:00[America/Chicago] is not a real date and time"
        in problems(document)
    )


def test_a_time_zone_name_starts_each_part_with_a_letter() -> None:
    for name in ("0", "-", "America/0", "+00:00"):
        document = flight_home()
        document["facts"][0]["starts_at"] = f"2027-05-15T14:00:00-05:00[{name}]"
        assert problems(document).startswith("facts/0:")
    document = flight_home()
    document["facts"][0]["starts_at"] = "2027-05-15T14:00:00-05:00[America/Port-au-Prince]"
    assert load(document).start("museum-visit") is not None


def test_an_offset_from_utc_is_a_real_offset() -> None:
    document = flight_home()
    document["facts"][0]["starts_at"] = "2027-05-15T14:00:00+00:99[UTC]"
    assert problems(document).startswith("facts/0:")


def test_text_holds_no_line_break() -> None:
    document = flight_home()
    document["persons"][0]["id"] = "alex\n"
    document["facts"][0]["starts_at"] += "\n"
    document["facts"][1]["duration"] = "PT1H\n"
    found = problems(document)
    assert "persons/0/id: 'alex\\n' holds a control character" in found
    assert "facts/0/starts_at:" in found
    assert "facts/1/duration: 'PT1H\\n' holds a control character" in found


def test_a_time_of_day_runs_from_midnight_to_one_second_before_it() -> None:
    document = flight_home()
    document["facts"][0]["starts_at"] = "2027-05-15T24:00:00-05:00[America/Chicago]"
    assert problems(document).startswith("facts/0:")


def test_a_length_of_time_is_not_endless() -> None:
    document = flight_home()
    document["facts"][1]["duration"] = "PT" + "9" * 5000 + "H"
    assert problems(document).startswith("facts/1:")


def test_a_name_can_be_read_and_written() -> None:
    document = flight_home()
    document["persons"][0]["name"] = "   "
    document["persons"][1]["name"] = "Sam\u2028Lee"
    document["places"][1]["name"] = "O'Hare\u0085"
    document["places"][0]["name"] = "Art \ud800 Institute"
    found = problems(document)
    assert "persons/0/name:" in found
    assert "persons/1/name: 'Sam\\u2028Lee' holds a control character" in found
    assert "places/0/name: 'Art \\ud800 Institute' holds half of a character" in found
    assert 'places/1/name: "O\'Hare\\x85" holds a control character' in found


def test_a_fact_states_one_thing() -> None:
    document = flight_home()
    document["facts"][0]["duration"] = "PT1H"
    assert problems(document).startswith("facts/0: fits no known shape")


def test_every_reference_points_at_something_in_the_file() -> None:
    document = flight_home()
    document["options"][0]["place"] = "the-moon"
    document["facts"][1]["option"] = "a-nap"
    document["decisions"][0]["persons"] = ["alex", "jo"]
    found = problems(document)
    assert "options/0: the-moon is not a PLACE in this FILE" in found
    assert "facts/1: a-nap is not a OPTION in this FILE" in found
    assert "decisions/0: jo is not a PERSON in this FILE" in found


def test_an_id_is_used_once_in_the_whole_file() -> None:
    document = flight_home()
    document["places"][0]["id"] = "alex"
    document["options"][0]["place"] = "alex"
    document["options"][1]["from"] = "alex"
    assert "places/0: the id alex is used more than once" in problems(document)


def test_an_option_that_moves_goes_somewhere_else() -> None:
    document = flight_home()
    document["options"][1]["to"] = "art-institute"
    assert "options/1: an OPTION that moves needs two different PLACEs" in problems(document)


def test_each_fact_is_stated_once() -> None:
    document = flight_home()
    document["facts"].append(
        {"id": "visit-length-again", "option": "museum-visit", "duration": "PT2H"}
    )
    assert "facts/7: another FACT already states this about museum-visit" in problems(document)


def test_a_complete_fact_is_stated_once() -> None:
    document = flight_home()
    document["facts"] += [complete("art-institute", "ohare"), complete("art-institute", "ohare")]
    document["facts"][8]["id"] = "ways-again"
    assert "facts/8: another FACT already states this" in problems(document)


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
    assert "facts/3: the shortest duration is longer than the longest" in found
    assert "facts/7: the span ends before it starts" in found


def test_a_file_on_disk_must_be_json(tmp_path: Path) -> None:
    path = tmp_path / "trip.json"
    path.write_text("{ not json")
    with pytest.raises(FileError, match="not readable as JSON"):
        read(path)


def test_a_file_on_disk_states_each_key_once(tmp_path: Path) -> None:
    path = tmp_path / "trip.json"
    path.write_text(
        '{"persons": [], "persons": [], "places": [], "options": [], "facts": [], "decisions": []}'
    )
    with pytest.raises(FileError, match="the FILE: states persons more than once"):
        read(path)


def test_a_repeated_key_is_reported_where_it_is(tmp_path: Path) -> None:
    path = tmp_path / "trip.json"
    path.write_text(
        '{"persons": [{"id": "alex", "name": "Alex"}, {"id": "sam", "id": "sam", "name": "Sam"}],'
        ' "places": [], "options": [], "decisions": [], "facts": [{"id": "ways", "complete":'
        ' {"from": "a", "to": "b", "leaving": {"earliest": "x", "earliest": "y", "latest": "z"}}}]}'
    )
    with pytest.raises(FileError) as refused:
        read(path)
    assert refused.value.problems == (
        "persons/1: states id more than once",
        "facts/0/complete/leaving: states earliest more than once",
    )


def test_a_file_on_disk_is_not_nested_without_end(tmp_path: Path) -> None:
    path = tmp_path / "trip.json"
    path.write_text("[" * 200_000)
    with pytest.raises(FileError, match="nested too deeply"):
        read(path)


def test_an_empty_file_is_a_file() -> None:
    file = load({"persons": [], "places": [], "options": [], "facts": [], "decisions": []})
    assert file.options == ()
