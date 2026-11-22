"""What the page shows of the PLACEs of a FILE.

The view sends the PLACEs, and with the other things of the FILE where each of them is.
``src/agloe/view/static/places.js`` says of each PLACE what the FILE puts there: who starts
from it, which OBJECTs are there when the TRIP starts, who must end the TRIP there, and the
OPTIONs and the WAYs that are at it or go from it or to it. It marks what the report names. It
has no page in it, so Node runs it here, through ``view_part.mjs``.

Nothing in it judges a TRIP. Who is at a PLACE at a time of a plan is for the COMPILER to say.
"""

import json
from pathlib import Path
from typing import Any

from agloe.file import read
from tests.stories import EXAMPLES
from tests.test_view_calendar import drawn, in_words, parts, with_its_report

FILES = sorted(
    path for path in EXAMPLES.rglob("*.json") if not path.name.endswith(".expected.json")
)
SAYS = (
    "Every PLACE of the FILE, with what the FILE puts there: the PERSONs and the OBJECTs that"
    " start there, the PERSONs who must end the TRIP there, and the OPTIONs and the WAYs that"
    " are at it or go from it or to it."
)
RED = " A red edge marks what the report names among what rules out every plan."
YELLOW = " A yellow edge marks what the report names in what the FILE does not say."
EMPTY = "Nothing in the FILE is at this PLACE."
UNMARKED: dict[str, Any] = {"records": [], "clash": [], "finds": None, "cases": [], "asks": []}

type Trip = dict[str, Any]
type Places = dict[str, Any]


def all_places(
    trips: list[Trip | None],
    reports: list[dict[str, Any] | None] | None = None,
    texts: list[str | None] | None = None,
) -> list[Places]:
    """What the page shows of the PLACEs of each TRIP, by the page's own code."""
    return parts("places", trips, reports, texts)


def places_of(name: str) -> Places:
    """What the page shows of the PLACEs of an example, with the report on it."""
    sent, found, text = in_words(EXAMPLES / f"{name}.json")
    return all_places([sent], [found], [text])[0]


def test_a_place_says_who_starts_from_it_and_what_is_at_it() -> None:
    """Alex and Sam start from the hotel, walk to the museum, and fly from O'Hare to Denver."""
    shown = places_of("ending-in-denver/works")
    assert shown["says"] == SAYS
    assert (shown["clash"], shown["asked"]) == (False, False)
    hotel, museum, ohare, denver = shown["places"]
    assert hotel == {
        "id": "hotel",
        "name": "the hotel",
        "holds": ["Alex and Sam start from here."],
        "options": [],
        "ways": [
            {
                "way": "walk",
                "name": "the walk between the hotel and the Art Institute",
                "says": "between here and the Art Institute, in both directions",
                "takes": "Takes 15 min.",
                # The step of the plan in which Alex and Sam take it.
                "steps": [0],
                **UNMARKED,
            }
        ],
        # The FACTs about who starts from it.
        "records": ["alex-start", "sam-start"],
        "clash": [],
        "finds": None,
        "cases": [],
        "asks": [],
    }
    assert (museum["name"], museum["holds"], museum["records"]) == ("the Art Institute", [], [])
    assert museum["options"] == [
        {
            "option": "museum-visit",
            "name": "Museum visit",
            "says": "happens here",
            "takes": "In the plan: Alex and Sam take part.",
            "step": 1,
            **UNMARKED,
        },
        {
            "option": "blue-line",
            "name": "Blue Line to O'Hare",
            "says": "goes from here to O'Hare",
            "takes": "In the plan: Alex and Sam take part.",
            "step": 2,
            **UNMARKED,
        },
    ]
    assert [(way["name"][:8], way["says"]) for way in museum["ways"]] == [
        ("the walk", "between here and the hotel, in both directions")
    ]
    # An OPTION that goes from one PLACE to another is under both.
    assert [(option["name"], option["says"]) for option in ohare["options"]] == [
        ("Blue Line to O'Hare", "comes here from the Art Institute"),
        ("Flight home", "goes from here to Denver"),
    ]
    assert [(option["name"], option["says"]) for option in denver["options"]] == [
        ("Flight home", "comes here from O'Hare")
    ]
    # A WANT about where the TRIP ends is about its PLACE.
    assert denver["holds"] == ["Alex and Sam must end the TRIP here."]
    assert denver["records"] == ["ending-in-denver"]


def test_a_place_where_an_object_is_when_the_trip_starts_says_so() -> None:
    """The bags are at the hotel. The Blue Line goes to O'Hare, and not back."""
    shown = places_of("the-bags/they-collect-them")
    by_name = {place["name"]: place for place in shown["places"]}
    hotel = by_name["the hotel"]
    assert hotel["holds"] == ["The TRIP starts with the bags here."]
    assert hotel["records"] == ["where-the-bags-start"]
    assert [(option["name"], option["says"]) for option in hotel["options"]] == [
        ("Collect the bags", "happens here")
    ]
    # A WAY that a PERSON can take in one direction says so at both of its PLACEs.
    (line,) = [way for way in by_name["the Art Institute"]["ways"] if way["way"] == "blue-line"]
    assert line["says"] == "from here to O'Hare, in that direction only"
    (line,) = [way for way in by_name["O'Hare"]["ways"] if way["way"] == "blue-line"]
    assert line["says"] == "from the Art Institute to here, in that direction only"
    # Alex and Sam start from the museum, and each takes the Blue Line by themselves.
    assert by_name["the Art Institute"]["holds"] == ["Alex and Sam start from here."]
    assert len(line["steps"]) == 2


def test_a_place_that_nothing_is_at_says_so() -> None:
    sent = drawn(EXAMPLES / "ending-in-denver" / "works.json")
    sent["places"].append({"id": "pier", "name": "Navy Pier"})
    (shown,) = all_places([sent])
    pier = shown["places"][-1]
    assert (pier["holds"], pier["options"], pier["ways"], pier["records"]) == ([EMPTY], [], [], [])
    # One PERSON starts from a PLACE.
    sent["starts_from"][1]["place"] = "pier"
    (shown,) = all_places([sent])
    assert [place["holds"] for place in shown["places"]] == [
        ["Alex starts from here."],
        [],
        [],
        ["Alex and Sam must end the TRIP here."],
        ["Sam starts from here."],
    ]


def test_a_want_that_an_option_can_deliver_is_about_no_place() -> None:
    sent = drawn(EXAMPLES / "ending-in-denver" / "works.json")
    (want,) = [want for want in sent["wants"] if want["ends_at"] is not None]
    # One PERSON of the two holds the WANT about where the TRIP ends.
    want["musts"] = ["sam"]
    (shown,) = all_places([sent])
    assert shown["places"][-1]["holds"] == ["Sam must end the TRIP here."]
    want["ends_at"] = None
    (shown,) = all_places([sent])
    assert (shown["places"][-1]["holds"], shown["places"][-1]["records"]) == ([], [])


def test_a_place_whose_name_is_the_word_for_the_place_of_the_card_is_in_quotation_marks() -> None:
    """A card says "here" for its own PLACE. Another PLACE can have that word as its name."""
    sent = drawn(EXAMPLES / "ending-in-denver" / "works.json")
    (museum,) = [place for place in sent["places"] if place["id"] == "art-institute"]
    museum["name"] = "Here"
    (shown,) = all_places([sent])
    hotel, here, ohare, _ = shown["places"]
    assert here["name"] == "Here"
    assert [way["says"] for way in hotel["ways"]] == ['between here and "Here", in both directions']
    assert [option["says"] for option in ohare["options"]] == [
        'comes here from "Here"',
        "goes from here to Denver",
    ]
    assert [option["says"] for option in here["options"]] == [
        "happens here",
        "goes from here to O'Hare",
    ]
    # Where the page shows the id of such a name, the quotation marks go on before the id.
    # A name that only holds the word is as it is.
    museum["name"] = "here (art-institute)"
    sent["places"][0]["name"] = "Here and there"
    (shown,) = all_places([sent])
    hotel, here, ohare, _ = shown["places"]
    assert [way["says"] for way in hotel["ways"]] == [
        'between here and "here" (art-institute), in both directions'
    ]
    assert [way["says"] for way in here["ways"]] == [
        "between here and Here and there, in both directions"
    ]


def test_two_places_whose_names_look_alike_have_their_ids(tmp_path: Path) -> None:
    """One name has a hyphen, and the other a hyphen that does not break."""
    content = json.loads((EXAMPLES / "ending-in-denver" / "works.json").read_text())
    by_id = {place["id"]: place for place in content["places"]}
    by_id["hotel"]["name"], by_id["art-institute"]["name"] = "Saint-Malo", "Saint\u2011Malo"
    path = tmp_path / "trip.json"
    path.write_text(json.dumps(content))
    sent, found, words = in_words(path)
    assert found["answer"] == "FEASIBLE"
    (shown,) = all_places([sent], [found], [words])
    hotel, museum, ohare, _ = shown["places"]
    # Each card has the id, and so has each sentence of another card that names the PLACE.
    assert (hotel["name"], museum["name"]) == (
        "Saint-Malo (hotel)",
        "Saint\u2011Malo (art-institute)",
    )
    assert [way["says"] for way in hotel["ways"]] == [
        "between here and Saint\u2011Malo (art-institute), in both directions"
    ]
    assert [way["says"] for way in museum["ways"]] == [
        "between here and Saint-Malo (hotel), in both directions"
    ]
    assert ohare["options"][0]["says"] == "comes here from Saint\u2011Malo (art-institute)"


def test_the_places_mark_what_the_report_says_the_file_does_not_say() -> None:
    """The trip works if there are other WAYs from the Art Institute to O'Hare."""
    shown = places_of("flight-home/depends-on-another-way")
    assert shown["says"] == SAYS + YELLOW
    assert shown["asked"] is True
    asked = {place["name"]: place["cases"] for place in shown["places"]}
    assert asked["the Art Institute"] == [0]
    assert asked["O'Hare"] == [0]
    assert sum(len(cases) for cases in asked.values()) == 2
    (museum,) = [place for place in shown["places"] if place["id"] == "art-institute"]
    assert museum["asks"] == [
        "The trip works if there are other WAYs from the Art Institute to O'Hare that take 45 min"
        " or less."
    ]
    # Each case names its own two PLACEs.
    shown = places_of("ending-in-denver/depends-on-another-flight")
    asked = {place["id"]: place["cases"] for place in shown["places"]}
    assert asked == {"hotel": [0], "art-institute": [1], "ohare": [2], "denver": [0, 1, 2]}
    # Nobody said where the bags are when the TRIP starts: they may be at the hotel.
    shown = places_of("the-bags/nobody-said-where-they-are")
    asked = {place["id"]: place["cases"] for place in shown["places"]}
    assert (asked["hotel"], asked["ohare"]) == ([2], [3])
    (hotel,) = [place for place in shown["places"] if place["id"] == "hotel"]
    assert hotel["asks"][0] == "The trip works in any of these cases:"
    assert len(hotel["asks"]) == 2
    # With no report in words, the PLACE says that the report names it.
    sent, found = with_its_report(EXAMPLES / "flight-home" / "depends-on-another-way.json")
    (shown,) = all_places([sent], [found])
    (museum,) = [place for place in shown["places"] if place["id"] == "art-institute"]
    assert museum["asks"] == ["The report names this PLACE in what the FILE does not say."]


def test_the_places_mark_what_the_report_names_as_ruling_out_every_plan() -> None:
    sent, found = with_its_report(EXAMPLES / "ending-in-denver" / "works.json")
    # A report that names where Alex starts from, and the WANT about where the TRIP ends.
    ruled = {"answer": "INFEASIBLE", "conflict": ["alex-start", "ending-in-denver", "trip-end"]}
    (shown,) = all_places([sent], [ruled])
    assert shown["says"] == SAYS + RED
    hotel, museum, ohare, denver = shown["places"]
    assert (hotel["clash"], museum["clash"], ohare["clash"]) == (["alex-start"], [], [])
    assert denver["clash"] == ["ending-in-denver"]
    assert hotel["finds"] == "The report names alex-start among what rules out every plan."
    # An OPTION or a WAY under a PLACE has no record, and so no edge.
    under = [each for place in shown["places"] for each in (*place["options"], *place["ways"])]
    assert all(each["records"] == [] and each["clash"] == [] for each in under)
    # Only what a report names is marked.
    odd: list[Any] = [None, {}, found, {**ruled, "answer": "FEASIBLE"}, {**ruled, "conflict": "x"}]
    for other in all_places([sent] * len(odd), odd):
        assert other["clash"] is False
        assert all(place["clash"] == [] for place in other["places"])


def test_an_option_that_is_no_step_and_a_way_that_nobody_takes_say_so() -> None:
    """A report that shows no plan: the page has the LOCKs, and no step for a WAY."""
    shown = places_of("ending-in-denver/cannot-work")
    museum = shown["places"][1]
    (visit,) = [option for option in museum["options"] if option["option"] == "museum-visit"]
    assert visit["takes"] == "Alex and Sam are each named by a LOCK."
    assert all(way["steps"] == [] for place in shown["places"] for way in place["ways"])


def test_a_trip_with_no_place_shows_none() -> None:
    sent = drawn(EXAMPLES / "flight-home" / "works.json")
    empty: Places = {"says": "", "clash": False, "asked": False, "places": []}
    bare: Trip = {**sent, "places": []}
    assert all_places([bare, None]) == [empty] * 2


def test_every_example_shows_each_place_with_what_the_file_puts_there() -> None:
    """Each PLACE of each FILE is shown, with every OPTION and WAY of the FILE that is at it."""
    asked = [in_words(path) for path in FILES]
    shown = all_places(
        [sent for sent, _, _ in asked],
        [found for _, found, _ in asked],
        [words for _, _, words in asked],
    )
    starts = moves = 0
    for path, (_, _, words), each in zip(FILES, asked, shown, strict=True):
        file = read(path)
        name = f"{path.parent.name}/{path.stem}"
        assert [place["id"] for place in each["places"]] == [place.id for place in file.places], (
            name
        )
        for place in each["places"]:
            # Each OPTION of the FILE is under the PLACE where it starts and the one where it
            # ends, and under no other.
            there = [
                option.id
                for option in file.options
                if place["id"] in (option.origin, option.destination)
            ]
            assert [option["option"] for option in place["options"]] == there, name
            moves += sum(option["says"] != "happens here" for option in place["options"])
            # Where the report has a line about a PERSON who starts from this PLACE, the page
            # names that PERSON here.
            for person in file.persons:
                stated = file.starts_from(person.id)
                if stated is None or stated.place != place["id"]:
                    continue
                assert stated.id in place["records"], name
                if f"  {stated.id}: " in words:
                    starts += 1
                    (line,) = [
                        row for row in words.splitlines() if row.startswith(f"  {stated.id}: ")
                    ]
                    who = line[len(f"  {stated.id}: ") :].split(" starts from ")[0]
                    assert who in place["holds"][0], name
                    assert line.endswith(f" starts from {place['name']}"), name
    assert min(starts, moves) > 3
