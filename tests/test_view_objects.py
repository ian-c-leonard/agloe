"""What the page shows of the OBJECTs of a FILE.

The view sends the OBJECTs with each report: where each is when the TRIP starts, the OPTIONs
that a FACT says require it or do not, those that a FACT says refuse it or do not, and those
that a FACT says hand it over, keep it or leave it alone. ``src/agloe/view/static/objects.js``
puts them in words, as the report words them, says who takes part in each of those OPTIONs,
and marks what the report names. It has no page in it, so Node runs it here, through
``view_part.mjs``.

Nothing in it judges a TRIP. Where an OBJECT is in a plan is for the COMPILER to say.
"""

import json
from pathlib import Path
from typing import Any

from agloe.file import read
from tests.stories import EXAMPLES
from tests.test_view_calendar import drawn, in_words, parts, with_its_report

STORY = EXAMPLES / "the-bags"
FILES = sorted(
    path for path in EXAMPLES.rglob("*.json") if not path.name.endswith(".expected.json")
)
SAYS = (
    "The OBJECTs of the FILE, each with where it is when the TRIP starts, the OPTIONs that the"
    " FILE says require it or refuse it, and those that it says hand it over, keep it or carry it."
)
# Where a card gives a time of the plan.
CLOCKS = " Times are on the clocks of America/Chicago."
RED = " A red edge marks what the report names among what rules out every plan."
YELLOW = " A yellow edge marks what the report names in what the FILE does not say."
ALL_REQUIRE = "The FILE states every one of its OPTIONs that requires it or refuses it."
ALL_MOVE = "The FILE states every OPTION that hands it over, keeps it or carries it."
NO_TICKET = "The FILE states every one of its OPTIONs that needs a right for it, and it names none."
NONE = ", and it names none."
MAY_MOVE = (
    "Another OPTION may hand it over, keep it or carry it: "
    "the FILE does not say that these are all."
)
UNSAID = "The FILE does not say where it is when the TRIP starts."

type Trip = dict[str, Any]
type Objects = dict[str, Any]


def all_objects(
    trips: list[Trip | None],
    reports: list[dict[str, Any] | None] | None = None,
    texts: list[str | None] | None = None,
) -> list[Objects]:
    """What the page shows of the OBJECTs of each TRIP, by the page's own code."""
    return parts("objects", trips, reports, texts)


def refusing_nothing(content: dict[str, Any], *things: str) -> list[dict[str, Any]]:
    """A FACT for each OPTION of a FILE and each of these OBJECTs: the OPTION does not refuse it."""
    return [
        {
            "id": f"{option['id']}-lets-in-{thing}",
            "option": option["id"],
            "refuses": {"object": thing, "refused": False},
        }
        for option in content["options"]
        for thing in things
    ]


def objects_of(name: str) -> Objects:
    """What the page shows of the OBJECTs of an example, with the report on it."""
    sent, found, text = in_words(EXAMPLES / f"{name}.json")
    return all_objects([sent], [found], [text])[0]


def test_an_object_says_where_it_starts_what_requires_it_and_what_moves_it() -> None:
    """The bags are at the hotel. The flight requires them, and the hotel hands them over."""
    shown = objects_of("the-bags/they-collect-them")
    # The card says when Alex takes the bags, so the part says whose clocks that time is on.
    assert shown["says"] == SAYS + CLOCKS
    assert (shown["clash"], shown["asked"]) == (False, False)
    # Alex carries the bags throughout: the card gives no time, and the part names no clocks.
    assert objects_of("the-bags/they-carry-them")["says"] == SAYS
    (bags,) = shown["objects"]
    assert (bags["id"], bags["name"], bags["starts"]) == (
        "bags",
        "the bags",
        "The TRIP starts with it at the hotel.",
    )
    assert bags["requires"] == [
        {
            "option": "flight",
            "name": "Flight home",
            "does": True,
            "says": "requires it",
            "takes": "In the plan: Alex and Sam take part.",
            "step": 6,
            "plan": "Just before it starts: with Alex.",
            "records": ["flight-needs-the-bags"],
            "clash": [],
            "finds": None,
            "cases": [],
            "asks": [],
        }
    ]
    (collect,) = bags["transfers"]
    assert (collect["name"], collect["says"], collect["takes"], collect["does"]) == (
        "Collect the bags",
        "it can be handed over here",
        "In the plan: Alex takes part.",
        True,
    )
    assert collect["plan"] is None
    assert bags["whole"] == [ALL_REQUIRE, ALL_MOVE, NO_TICKET]
    # Where the report says the OBJECT is in its plan, worded as the report words it.
    assert bags["plan"] == (
        "In the plan: at the hotel when the TRIP starts; with Alex from 2:45 pm (handed over in"
        " Collect the bags)."
    )
    assert bags["might"] == []
    # Its own records: where it starts, and the three FACTs that the FILE states every OPTION.
    assert bags["records"] == [
        "where-the-bags-start",
        "every-use-of-the-bags",
        "everything-that-moves-the-bags",
        "every-ticket-for-the-bags",
    ]
    assert bags["rights"] == []


def test_an_object_says_where_it_is_in_a_plan_only_where_the_report_says_so() -> None:
    sent, found, words = in_words(STORY / "they-collect-them.json")
    assert "\nWhere each OBJECT is:\n  the bags: at the hotel when the TRIP starts; with" in words
    # The page words it from the report as JSON, so it needs no report in words.
    (shown,) = all_objects([sent], [found])
    (bags,) = shown["objects"]
    assert bags["plan"] == (
        "In the plan: at the hotel when the TRIP starts; with Alex from 2:45 pm (handed over in"
        " Collect the bags)."
    )
    assert bags["requires"][0]["plan"] == "Just before it starts: with Alex."
    # With no report, the page has nothing to say of a plan.
    (shown,) = all_objects([sent])
    (bags,) = shown["objects"]
    assert (bags["plan"], bags["might"], bags["requires"][0]["plan"]) == (None, [], None)
    # A report that shows no plan says where no OBJECT is.
    for name in ("nobody-collects-them", "depends-on-the-museum", "somebody-might"):
        (bags,) = objects_of(f"the-bags/{name}")["objects"]
        assert (bags["plan"], bags["might"]) == (None, []), name
        assert [each["plan"] for each in bags["requires"]] == [None] * len(bags["requires"]), name
    # A report that names something that the TRIP does not hold says nothing of that OBJECT:
    # a PERSON, a PLACE or an OPTION that is not there, or a way of getting somewhere that
    # the page has no words for.
    (carried,) = found["objects"]
    first, second = carried["path"]
    paths: list[list[Any]] = [
        [{**first, "where": [{"place": "the-moon"}]}, second],
        [first, {**second, "where": [{"person": "nobody"}]}],
        [first, {**second, "since": "no-such-option"}],
        [first, {**second, "how": "thrown"}],
        [first, {**second, "where": []}],
        [],
    ]
    for path in paths:
        other: dict[str, Any] = {**found, "objects": [{**carried, "path": path}]}
        (shown,) = all_objects([sent], [other])
        (bags,) = shown["objects"]
        assert (bags["plan"], bags["might"], bags["requires"][0]["plan"]) == (None, [], None)


def test_where_an_object_is_in_a_plan_has_the_names_that_the_page_shows(tmp_path: Path) -> None:
    """Two OBJECTs, two OPTIONs or two PERSONs whose names look alike show their ids."""
    story = json.loads((STORY / "they-carry-them.json").read_text())
    about_the_bags = (
        "where-the-bags-start",
        "flight-needs-the-bags",
        "every-use-of-the-bags",
        "everything-that-moves-the-bags",
        "every-ticket-for-the-bags",
    )
    others = [fact for fact in story["facts"] if fact["id"] not in about_the_bags]
    path = tmp_path / "trip.json"

    def two(first: str, second: str) -> list[dict[str, Any]]:
        """Alex has one thing and Sam another, and the flight requires both."""
        return [
            {"id": "alex-has-one", "object": first, "starts_with": "alex"},
            {"id": "sam-has-one", "object": second, "starts_with": "sam"},
            {"id": "needs-one", "option": "flight", "requires": {"object": first, "needed": True}},
            {"id": "needs-two", "option": "flight", "requires": {"object": second, "needed": True}},
            {"id": "all-that-move-one", "complete": {"transfers": first}},
            {"id": "all-that-move-two", "complete": {"transfers": second}},
            {"id": "no-ticket-for-one", "complete": {"needs_right_for": first}},
            {"id": "no-ticket-for-two", "complete": {"needs_right_for": second}},
        ]

    # Alex and Sam have a bag each. The two names differ by a space, and a page shows them
    # alike, so each card has the id. The report gives no id, and each card still says where
    # its own bag is.
    lets_in = refusing_nothing(story, "alex-bag", "sam-bag")
    content = {**story, "facts": [*others, *two("alex-bag", "sam-bag"), *lets_in]}
    content["objects"] = [
        {"id": "alex-bag", "name": "the bags"},
        {"id": "sam-bag", "name": "the  bags"},
    ]
    path.write_text(json.dumps(content))
    sent, found, words = in_words(path)
    assert "\n  the bags: with Alex when the TRIP starts\n" in words
    assert "\n  the  bags: with Sam when the TRIP starts\n" in words
    (shown,) = all_objects([sent], [found], [words])
    said = [
        (each["name"], each["plan"], [option["plan"] for option in each["requires"]])
        for each in shown["objects"]
    ]
    assert said == [
        (
            "the bags (alex-bag)",
            "In the plan: with Alex when the TRIP starts.",
            ["Just before it starts: with Alex."],
        ),
        (
            "the  bags (sam-bag)",
            "In the plan: with Sam when the TRIP starts.",
            ["Just before it starts: with Sam."],
        ),
    ]
    # Two PERSONs have one name, once with the accent joined to its letter and once after
    # it. The page shows the id of each, also where it says who has an OBJECT.
    lets_in = refusing_nothing(story, "bags", "passport")
    content = {**story, "facts": [*others, *two("bags", "passport"), *lets_in]}
    content["objects"] = [
        {"id": "bags", "name": "the bags"},
        {"id": "passport", "name": "a passport"},
    ]
    content["persons"] = [{"id": "alex", "name": "Jos\u00e9"}, {"id": "sam", "name": "Jose\u0301"}]
    path.write_text(json.dumps(content))
    sent, found, words = in_words(path)
    (shown,) = all_objects([sent], [found], [words])
    said = [
        (each["plan"], [option["plan"] for option in each["requires"]]) for each in shown["objects"]
    ]
    assert said == [
        (
            "In the plan: with Jos\u00e9 (alex) when the TRIP starts.",
            ["Just before it starts: with Jos\u00e9 (alex)."],
        ),
        (
            "In the plan: with Jose\u0301 (sam) when the TRIP starts.",
            ["Just before it starts: with Jose\u0301 (sam)."],
        ),
    ]
    # Two OPTIONs have names that a page shows alike, and the FILE does not say that the
    # flight is all that requires the bags. The other OPTION is under the bags with its id.
    content = json.loads(json.dumps(story))
    content["facts"] = [fact for fact in story["facts"] if fact["id"] != "every-use-of-the-bags"]
    content["facts"] += refusing_nothing(story, "bags")
    (visit,) = [option for option in content["options"] if option["id"] == "museum-visit"]
    visit["name"] = "Flight  home"
    path.write_text(json.dumps(content))
    sent, found, words = in_words(path)
    (shown,) = all_objects([sent], [found], [words])
    (bags,) = shown["objects"]
    assert [(each["name"], each["plan"]) for each in (*bags["requires"], *bags["might"])] == [
        ("Flight home (flight)", "Just before it starts: with Alex."),
        (
            "Flight  home (museum-visit)",
            "Just before it starts: with Alex, so the plan holds if it does.",
        ),
    ]
    # A report cannot say of one OPTION both that a FACT has it require the OBJECT and that
    # the FILE does not say. Where one does, the OPTION is under the OBJECT once.
    (carried,) = found["objects"]
    uses = [{**use, "stated": False} for use in carried["required_by"]]
    other = {**found, "objects": [{**carried, "required_by": uses}]}
    (shown,) = all_objects([sent], [other], [words])
    (bags,) = shown["objects"]
    assert [each["option"] for each in bags["might"]] == ["museum-visit"]
    assert [each["plan"] for each in bags["requires"]] == [None]


def test_an_option_that_refuses_an_object_is_under_it(tmp_path: Path) -> None:
    """Alex leaves the bags at the cloakroom, and the galleries refuse them."""
    (bags,) = objects_of("the-bags/they-leave-them-at-the-cloakroom")["objects"]
    assert bags["refuses"] == [
        {
            "option": "museum-visit",
            "name": "Museum visit",
            "does": True,
            "says": "refuses it",
            "takes": "In the plan: Alex and Sam take part.",
            "step": 1,
            "plan": "Just before it starts: at the Art Institute.",
            "records": ["galleries-refuse-the-bags"],
            "clash": [],
            "finds": None,
            "cases": [],
            "asks": [],
        }
    ]
    assert [each["name"] for each in bags["requires"]] == ["Flight home"]
    assert bags["whole"] == [ALL_REQUIRE, ALL_MOVE, NO_TICKET]
    # An OPTION of which a FACT says that it does not refuse the OBJECT says so, and the plan
    # has no word on it.
    content = json.loads((STORY / "they-carry-them.json").read_text())
    content["facts"] += refusing_nothing(content, "bags")
    path = tmp_path / "trip.json"
    path.write_text(json.dumps(content))
    sent, found, words = in_words(path)
    (shown,) = all_objects([sent], [found], [words])
    (bags,) = shown["objects"]
    assert [
        (each["name"], each["says"], each["does"], each["plan"]) for each in bags["refuses"]
    ] == [
        ("Museum visit", "does not refuse it", False, None),
        ("Flight home", "does not refuse it", False, None),
    ]
    # The records that rule out every plan mark the OPTION that refuses the OBJECT.
    (bags,) = objects_of("the-bags/the-galleries-refuse-them")["objects"]
    assert [each["clash"] for each in bags["refuses"]] == [["galleries-refuse-the-bags"]]


def test_an_option_of_the_plan_that_might_refuse_an_object_is_under_it(tmp_path: Path) -> None:
    """Nobody said whether the galleries refuse the bags. Alex leaves them at the cloakroom."""
    content = json.loads((STORY / "they-leave-them-at-the-cloakroom.json").read_text())
    gone = ("every-use-of-the-bags", "galleries-refuse-the-bags")
    content["facts"] = [fact for fact in content["facts"] if fact["id"] not in gone]
    content["facts"] += [
        fact for fact in refusing_nothing(content, "bags") if fact["option"] != "museum-visit"
    ]
    path = tmp_path / "trip.json"
    path.write_text(json.dumps(content))
    sent, found, words = in_words(path)
    assert found["answer"] == "FEASIBLE"
    (shown,) = all_objects([sent], [found], [words])
    (bags,) = shown["objects"]
    assert [(each["name"], each["says"], each["plan"]) for each in bags["might"]][-1] == (
        "Museum visit",
        "the FILE does not say whether this refuses it",
        "Just before it starts: at the Art Institute, so the plan holds if it does.",
    )
    silent = "The FILE does not say whether Museum visit refuses the bags"
    assert f"\n    {silent}. {bags['might'][-1]['plan']}\n" in words
    # The visit is under the bags twice: the FILE does not say whether it requires them either.
    assert [each["says"][-11:] for each in bags["might"] if each["name"] == "Museum visit"] == [
        "requires it",
        " refuses it",
    ]


def test_a_case_marks_the_option_that_an_object_has_to_stay_out_of() -> None:
    """The trip might work if another transfer keeps the bags out of the visit."""
    shown = objects_of("the-bags/somebody-might-take-them")
    (bags,) = shown["objects"]
    assert bags["asks"] == [
        "The trip might work if another transfer leaves the bags at hand for Flight home, and"
        " keeps the bags out of Museum visit."
    ]
    # The case has the bags at hand for the flight, and out of the visit. Each is marked where
    # the card says that the OPTION requires the bags, or refuses them, and nowhere else.
    assert [(each["name"], each["cases"]) for each in bags["requires"]] == [("Flight home", [0])]
    assert [(each["name"], each["cases"]) for each in bags["refuses"]] == [("Museum visit", [0])]
    sent, found, words = in_words(STORY / "somebody-might-take-them.json")
    (need,) = found["missing"][0]
    swapped = [
        {**each, "check": "refuses" if each["check"] == "requires" else "requires"}
        for each in need["at_hand_for"]
    ]
    other = {**found, "missing": [[{**need, "at_hand_for": swapped}]]}
    (shown,) = all_objects([sent], [other], [words])
    (bags,) = shown["objects"]
    assert [each["cases"] for each in (*bags["requires"], *bags["refuses"])] == [[], []]
    # A case about whether an OPTION refuses the OBJECT marks the OBJECT.
    sent, found, words = in_words(STORY / "nobody-said-whether-they-refuse-them.json")
    assert found["missing"] == [
        [{"what": "does not refuse", "option": "museum-visit", "object": "bags"}]
    ]
    (shown,) = all_objects([sent], [found], [words])
    (bags,) = shown["objects"]
    assert (bags["cases"], shown["says"]) == ([0], SAYS + YELLOW)
    # It marks the OPTION where a FACT about the two is under the OBJECT.
    (thing,) = sent["objects"]
    thing["refuses"].append(
        {"option": "museum-visit", "name": "Museum visit", "refused": True, "record": "bars"}
    )
    (shown,) = all_objects([sent], [found], [words])
    (bags,) = shown["objects"]
    assert [(each["name"], each["cases"]) for each in bags["refuses"]] == [
        ("Flight home", []),
        ("Museum visit", [0]),
    ]
    assert all(each["cases"] == [] for each in (*bags["requires"], *bags["transfers"]))


def test_an_object_that_goes_along_with_no_choice_reads_as_the_report_reads(
    tmp_path: Path,
) -> None:
    """Each drive requires the car and carries it, so the car goes where the drive goes."""
    sent, found, words = in_words(EXAMPLES / "the-car" / "they-drive-it-there-and-back.json")
    (shown,) = all_objects([sent], [found], [words])
    (car,) = shown["objects"]
    assert car["plan"] == (
        "In the plan: at the hotel when the TRIP starts; in Drive to the dunes from 8:00 am"
        " (carried); at the Indiana Dunes from 9:00 am (where Drive to the dunes ends); in Drive"
        " back to the hotel from 11:00 am (carried); at the hotel from 12:00 pm (where Drive"
        " back to the hotel ends)."
    )
    assert f"\n  the car: {car['plan'][len('In the plan: ') : -1]}\n" in words
    # Only the drive there, and nobody says how long it takes. The car is at the dunes when
    # the drive ends, and the card gives no time for that.
    content = json.loads((EXAMPLES / "the-car" / "they-drive-it-there-and-back.json").read_text())
    content["options"] = [each for each in content["options"] if each["id"] == "drive-out"]
    content["decisions"] = [each for each in content["decisions"] if each["lock"] == "drive-out"]
    there = [fact for fact in content["facts"] if fact.get("option") != "drive-back"]
    path = tmp_path / "trip.json"
    content["facts"] = [fact for fact in there if fact["id"] != "drive-out-length"]
    path.write_text(json.dumps(content))
    sent, found, words = in_words(path)
    (shown,) = all_objects([sent], [found], [words])
    (car,) = shown["objects"]
    assert car["plan"] == (
        "In the plan: at the hotel when the TRIP starts; in Drive to the dunes from 8:00 am"
        " (carried); at the Indiana Dunes when Drive to the dunes ends."
    )
    assert f"\n  the car: {car['plan'][len('In the plan: ') : -1]}\n" in words
    # No FACT says whether the drive requires the car. If it does, the car goes along. So
    # the card names both places, from the start of the drive and again from its end.
    unsaid = ("drive-out-needs-the-car", "every-use-of-the-car")
    content["facts"] = [fact for fact in there if fact["id"] not in unsaid]
    content["facts"] += refusing_nothing(content, "car")
    path.write_text(json.dumps(content))
    sent, found, words = in_words(path)
    assert found["answer"] == "FEASIBLE"
    (shown,) = all_objects([sent], [found], [words])
    (car,) = shown["objects"]
    assert car["plan"] == (
        "In the plan: at the hotel when the TRIP starts; at the hotel or in Drive to the dunes"
        " from 8:00 am (the FILE does not say whether Drive to the dunes requires the car); at"
        " the hotel or at the Indiana Dunes from 9:00 am (where Drive to the dunes ends)."
    )
    assert f"\n  the car: {car['plan'][len('In the plan: ') : -1]}\n" in words


def test_an_object_that_might_be_anywhere_says_that_nobody_knows_where_it_is(
    tmp_path: Path,
) -> None:
    """Nobody said where the bags are. Alex and Sam both stop at the cloakroom, which keeps them."""
    content = json.loads((STORY / "they-leave-them-at-the-cloakroom.json").read_text())
    gone = ("where-the-bags-start", "flight-needs-the-bags")
    content["facts"] = [fact for fact in content["facts"] if fact["id"] not in gone]
    path = tmp_path / "trip.json"
    path.write_text(json.dumps(content))
    sent, found, words = in_words(path)
    assert found["answer"] == "FEASIBLE"
    (shown,) = all_objects([sent], [found], [words])
    (bags,) = shown["objects"]
    elsewhere = "at the hotel, at the Art Institute, at O'Hare, at Denver or somewhere the FILE"
    assert bags["plan"] == (
        f"In the plan: nobody knows where when the TRIP starts; {elsewhere} does not name from"
        " 12:55 pm (kept by Drop off at the cloakroom if anybody there has the bags)."
    )
    assert f"\n  the bags: {bags['plan'][len('In the plan: ') : -1]}\n" in words
    (visit,) = bags["refuses"]
    assert visit["plan"] == f"Just before it starts: {elsewhere} does not name."
    assert f"\n    Museum visit refuses the bags. {visit['plan']}\n" in f"{words}\n"
    # An OPTION that the bags might be in is not one of those places. A list that is as long
    # and has an OPTION in it names each place. With all of them, nobody knows where.
    anywhere = found["objects"][0]["path"][0]["where"]
    assert len(anywhere) == len(content["persons"]) + len(content["places"]) + 1
    named = "with Sam, at the hotel, at the Art Institute, at O'Hare, at Denver, somewhere"
    for where, said in (
        (
            [*anywhere[1:], {"option": "flight"}],
            f"{named} the FILE does not name or in Flight home",
        ),
        ([*anywhere, {"option": "flight"}], "nobody knows where"),
    ):
        other = json.loads(json.dumps(found))
        other["objects"][0]["path"][0]["where"] = where
        (shown,) = all_objects([sent], [other])
        plan = shown["objects"][0]["plan"]
        assert plan.startswith(f"In the plan: {said} when the TRIP starts; "), plan


def test_an_object_that_might_be_in_one_of_several_places_says_each(tmp_path: Path) -> None:
    """The FILE does not say what the museum does with the bags. The cloakroom returns them.

    The flight requires the bags, and the FILE does not say what it does with them. So they
    might also go along in it, and lie where it ends once it is over.
    """
    content = json.loads((STORY / "the-museum-keeps-them.json").read_text())
    gone = ("museum-checks-the-bags", "everything-that-moves-the-bags")
    content["facts"] = [fact for fact in content["facts"] if fact["id"] not in gone]
    path = tmp_path / "trip.json"
    path.write_text(json.dumps(content))
    sent, found, words = in_words(path)
    assert found["answer"] == "FEASIBLE"
    (shown,) = all_objects([sent], [found], [words])
    (bags,) = shown["objects"]
    assert bags["plan"] == (
        "In the plan: with Alex when the TRIP starts; with Alex or at the Art Institute from"
        " 1:00 pm (the FILE does not say what Museum visit does with the bags); with Alex from"
        " 2:30 pm (handed over in Pick up at the cloakroom); with Alex, at O'Hare or in Flight"
        " home from 5:00 pm (the FILE does not say what Flight home does with the bags); with"
        " Alex, at O'Hare or at Denver from 7:30 pm (where Flight home ends)."
    )
    assert f"\n  the bags: {bags['plan'][len('In the plan: ') : -1]}\n" in words
    assert shown["says"] == SAYS + CLOCKS
    # A name that holds the word "or" is in quotation marks in such a list, as in the report:
    # it is one name, and not two places where the OBJECT might be.
    (museum,) = [place for place in content["places"] if place["id"] == "art-institute"]
    museum["name"] = "Ripley's Believe It or Not!"
    content["persons"][0]["name"] = "Tom or Jerry"
    path.write_text(json.dumps(content))
    sent, found, words = in_words(path)
    (shown,) = all_objects([sent], [found], [words])
    (bags,) = shown["objects"]
    assert bags["plan"].startswith(
        'In the plan: with "Tom or Jerry" when the TRIP starts; with "Tom or Jerry" or at'
        ' "Ripley\'s Believe It or Not!" from 1:00 pm (the FILE does not say what Museum visit'
    )
    assert f"\n  the bags: {bags['plan'][len('In the plan: ') : -1]}\n" in words
    assert bags["requires"][0]["plan"] == 'Just before it starts: with "Tom or Jerry".'
    assert f"    Flight home requires the bags. {bags['requires'][0]['plan']}\n" in f"{words}\n"
    # Where the page shows the id of such a name, the quotation marks go on before the id.
    (hotel,) = [place for place in content["places"] if place["id"] == "hotel"]
    museum["name"], hotel["name"] = "Believe It or Not", "Believe It  or Not"
    path.write_text(json.dumps(content))
    sent, found, words = in_words(path)
    (shown,) = all_objects([sent], [found], [words])
    (bags,) = shown["objects"]
    assert ' or at "Believe It or Not" (art-institute) from 1:00 pm (' in bags["plan"]
    assert ' or at "Believe It or Not" from 1:00 pm (' in words
    # A name holds the word where a page shows it so. A mark of direction after the word
    # shows as nothing, so the name reads "Tom or Jerry", and it is in quotation marks. Each
    # name keeps the spelling of the FILE. The report tells the word by its spelling, so it
    # sets no quotation marks here: the page differs from it in them and in the id.
    content["persons"] = [
        {"id": "alex", "name": "Tom or\u200e Jerry"},
        {"id": "sam", "name": "Tom or Jerry"},
    ]
    path.write_text(json.dumps(content))
    sent, found, words = in_words(path)
    (shown,) = all_objects([sent], [found], [words])
    (bags,) = shown["objects"]
    assert bags["plan"].startswith('In the plan: with "Tom or\u200e Jerry" (alex) when the TRIP')
    assert bags["requires"][0]["plan"] == (
        'Just before it starts: with "Tom or\u200e Jerry" (alex).'
    )
    assert "\n  the bags: with Tom or\u200e Jerry when the TRIP starts; " in words
    # So is a name with a character after the word that joins two others and shows as nothing.
    content["persons"] = [
        {"id": "alex", "name": "Tom or\u034f Jerry"},
        {"id": "sam", "name": "Sam"},
    ]
    path.write_text(json.dumps(content))
    sent, found, words = in_words(path)
    (shown,) = all_objects([sent], [found], [words])
    (bags,) = shown["objects"]
    assert bags["requires"][0]["plan"] == 'Just before it starts: with "Tom or\u034f Jerry".'
    # A character that joins the word to the one before it leaves no such word to see.
    content["persons"] = [{"id": "alex", "name": "Tom\ufeffor Jerry"}, {"id": "sam", "name": "Sam"}]
    path.write_text(json.dumps(content))
    sent, found, words = in_words(path)
    (shown,) = all_objects([sent], [found], [words])
    (bags,) = shown["objects"]
    assert bags["requires"][0]["plan"] == "Just before it starts: with Tom\ufeffor Jerry."


def test_an_option_of_the_plan_that_might_require_an_object_is_under_it(tmp_path: Path) -> None:
    """The FILE does not say that the flight is all that requires the bags. Alex carries them."""
    content = json.loads((STORY / "they-carry-them.json").read_text())
    content["facts"] = [fact for fact in content["facts"] if fact["id"] != "every-use-of-the-bags"]
    content["facts"] += refusing_nothing(content, "bags")
    path = tmp_path / "trip.json"
    path.write_text(json.dumps(content))
    sent, found, words = in_words(path)
    assert found["answer"] == "FEASIBLE"
    (shown,) = all_objects([sent], [found], [words])
    assert (shown["clash"], shown["asked"]) == (False, False)
    (bags,) = shown["objects"]
    assert bags["plan"] == "In the plan: with Alex when the TRIP starts."
    assert [(each["name"], each["plan"]) for each in bags["requires"]] == [
        ("Flight home", "Just before it starts: with Alex.")
    ]
    assert bags["might"] == [
        {
            "option": "museum-visit",
            "name": "Museum visit",
            "does": False,
            "says": "the FILE does not say whether this requires it",
            "takes": "In the plan: Alex and Sam take part.",
            "step": 0,
            "plan": "Just before it starts: with Alex, so the plan holds if it does.",
            "records": [],
            "clash": [],
            "finds": None,
            "cases": [],
            "asks": [],
        }
    ]
    # An OBJECT whose name holds a colon, and an OPTION whose name does, keep their words.
    content["objects"][0]["name"] = "the bags: two"
    (visit,) = [option for option in content["options"] if option["id"] == "museum-visit"]
    visit["name"] = "Museum: the visit"
    path.write_text(json.dumps(content))
    sent, found, words = in_words(path)
    (shown,) = all_objects([sent], [found], [words])
    (bags,) = shown["objects"]
    # The report puts such a name in quotation marks, and so does the page.
    assert bags["name"] == '"the bags: two"'
    assert bags["plan"] == "In the plan: with Alex when the TRIP starts."
    assert [(each["name"], each["plan"]) for each in bags["might"]] == [
        ('"Museum: the visit"', "Just before it starts: with Alex, so the plan holds if it does.")
    ]


def test_an_object_that_a_person_has_and_an_option_that_keeps_it() -> None:
    """Alex has the bags when the TRIP starts, and the museum keeps them during the visit."""
    (bags,) = objects_of("the-bags/the-museum-keeps-them")["objects"]
    assert bags["starts"] == "Alex has it when the TRIP starts."
    said = {each["name"]: each["says"] for each in bags["transfers"]}
    assert said["Museum visit"] == "keeps it"
    assert said["Pick up at the cloakroom"] == "it can be handed over here"


def test_an_option_that_refuses_an_object_moves_it_for_nobody(tmp_path: Path) -> None:
    """One FACT says that an OPTION hands the bags over or keeps them, and another that it
    refuses them. The rules have it refuse them first, so the card says what that comes to."""

    def bags_of(story: str, *facts: dict[str, Any]) -> Objects:
        content = json.loads((STORY / f"{story}.json").read_text())
        content["facts"] += facts
        path = tmp_path / "trip.json"
        path.write_text(json.dumps(content))
        sent, found, words = in_words(path)
        (shown,) = all_objects([sent], [found], [words])
        (bags,) = shown["objects"]
        return bags

    def refusal(option: str, refused: bool = True) -> dict[str, Any]:
        return {
            "id": f"{option}-and-the-bags",
            "option": option,
            "refuses": {"object": "bags", "refused": refused},
        }

    # The hotel hands the bags over where they are collected, and collecting them refuses
    # them: nobody can take them there. The entry is drawn as one that does nothing with the
    # bags, and it is tied to both FACTs.
    bags = bags_of("they-collect-them", refusal("collect-bags"))
    (hands,) = bags["transfers"]
    assert (hands["name"], hands["says"], hands["does"]) == (
        "Collect the bags",
        "it can be handed over here, but nobody can take it: this refuses it",
        False,
    )
    assert hands["records"] == ["hotel-releases-the-bags", "collect-bags-and-the-bags"]
    assert [(each["says"], each["records"]) for each in bags["refuses"]] == [
        ("refuses it", ["collect-bags-and-the-bags"])
    ]
    # The report names the refusal among what rules out every plan, so both entries are marked.
    assert hands["clash"] == ["collect-bags-and-the-bags"]
    # The museum keeps the bags and refuses them: nobody who has them can take part.
    bags = bags_of("the-museum-keeps-them", refusal("museum-visit"))
    said = {each["name"]: (each["says"], each["does"]) for each in bags["transfers"]}
    assert said == {
        "Museum visit": ("keeps it, but nobody who has it can take part: this refuses it", False),
        "Pick up at the cloakroom": ("it can be handed over here", True),
    }
    # A FACT that the OPTION does not refuse the bags changes nothing.
    bags = bags_of("the-museum-keeps-them", refusal("museum-visit", refused=False))
    (keeps, _) = bags["transfers"]
    assert (keeps["says"], keeps["does"], keeps["records"]) == (
        "keeps it",
        True,
        ["museum-checks-the-bags"],
    )
    # An OPTION that leaves the bags alone and refuses them leaves them alone.
    alone = {
        "id": "flight-leaves-the-bags",
        "option": "flight",
        "with_object": {"object": "bags", "does": "nothing"},
    }
    bags = bags_of("the-museum-keeps-them", refusal("flight"), alone)
    said = {each["name"]: (each["says"], each["records"]) for each in bags["transfers"]}
    assert said["Flight home"] == ("leaves it alone", ["flight-leaves-the-bags"])


def test_the_objects_mark_what_the_report_says_the_file_does_not_say() -> None:
    """Nobody said where the bags are when the TRIP starts."""
    shown = objects_of("the-bags/nobody-said-where-they-are")
    assert shown["says"] == SAYS + YELLOW
    (bags,) = shown["objects"]
    assert (bags["starts"], bags["cases"]) == (UNSAID, [0, 1, 2, 3])
    assert bags["asks"][:2] == [
        "The trip works in any of these cases:",
        "1. Alex has the bags when the TRIP starts.",
    ]
    # A case that might not be enough is worded as the report words it.
    (bags,) = objects_of("the-bags/somebody-might")["objects"]
    assert bags["cases"] == [0]
    assert bags["asks"] == [
        "The trip might work if another transfer puts the bags at hand for Flight home."
    ]


def test_a_case_marks_the_option_under_an_object_that_shows_what_the_case_is_about() -> None:
    """The trip might work if another transfer puts the bags at hand for the flight."""
    (bags,) = objects_of("the-bags/somebody-might")["objects"]
    # The flight requires the bags, and the case has them at hand for it.
    assert [(each["name"], each["cases"]) for each in bags["requires"]] == [("Flight home", [0])]
    assert all(each["cases"] == [] for each in bags["transfers"])
    # A case about whether the museum requires the bags is not about what the museum does
    # with them. So it marks the OBJECT, and not the OPTION that leaves them alone.
    sent, found, words = in_words(STORY / "depends-on-the-museum.json")
    assert found["missing"] == [
        [{"what": "does not require", "option": "museum-visit", "object": "bags"}]
    ]
    (thing,) = sent["objects"]
    thing["transfers"].append(
        {
            "option": "museum-visit",
            "name": "Museum visit",
            "does": "nothing",
            "record": "museum-leaves-them",
        }
    )
    (shown,) = all_objects([sent], [found], [words])
    (bags,) = shown["objects"]
    assert bags["cases"] == [0]
    assert [each["cases"] for each in bags["transfers"] if each["name"] == "Museum visit"] == [[]]
    # A case about what an OPTION does with the OBJECT marks that OPTION there.
    for what in (
        "hands over",
        "keeps",
        "does not keep",
        "does not carry",
        "does not keep or carry",
        "carries",
    ):
        does = {"what": what, "option": "museum-visit", "object": "bags"}
        (shown,) = all_objects([sent], [{**found, "missing": [[does]]}])
        (bags,) = shown["objects"]
        marked = [each["cases"] for each in bags["transfers"] if each["name"] == "Museum visit"]
        assert marked == [[0]], what
        assert all(each["cases"] == [] for each in bags["requires"])


def test_the_objects_mark_what_the_report_names_as_ruling_out_every_plan() -> None:
    sent, found = with_its_report(STORY / "nobody-collects-them.json")
    (shown,) = all_objects([sent], [found])
    assert shown["says"] == SAYS + RED
    (bags,) = shown["objects"]
    named = set(found["conflict"])
    assert bags["clash"] == [record for record in bags["records"] if record in named]
    assert bags["clash"]
    for each in (*bags["requires"], *bags["transfers"]):
        assert each["clash"] == [record for record in each["records"] if record in named]
    # Only what a report names is marked.
    odd: list[Any] = [None, {}, {**found, "answer": "FEASIBLE"}, {**found, "conflict": "x"}]
    for other in all_objects([sent] * len(odd), odd):
        assert other["clash"] is False


def test_an_object_says_whether_its_options_are_all_there_are() -> None:
    sent = drawn(STORY / "they-collect-them.json")
    (bags,) = sent["objects"]

    def whole(**other: Any) -> list[str]:
        (shown,) = all_objects([{**sent, "objects": [{**bags, **other}]}])
        said: list[str] = shown["objects"][0]["whole"]
        return said

    needs, moves = bags["requires"][0], bags["transfers"][0]
    bars = {"option": needs["option"], "name": needs["name"], "refused": True, "record": "bars-it"}
    no_refusal = "The FILE says of no OPTION whether it refuses this OBJECT."
    # One FACT says that the FILE states every OPTION that requires the OBJECT or refuses it.
    # Without it, the card says of each of the two what the FILE leaves open.
    assert whole(requires_complete=None, transfers_complete=None) == [
        "Other OPTIONs of the FILE may require it too: the FILE does not say that these are all.",
        no_refusal,
        MAY_MOVE,
        NO_TICKET,
    ]
    assert whole(
        requires=[{**needs, "needed": False}], transfers=[{**moves, "does": "nothing"}]
    ) == [
        "The FILE states every one of its OPTIONs that requires it or refuses it, and it names"
        " none.",
        ALL_MOVE[:-1] + NONE,
        NO_TICKET,
    ]
    # An OPTION that refuses the OBJECT is one that the FILE names.
    assert whole(requires=[], refuses=[bars]) == [ALL_REQUIRE, ALL_MOVE, NO_TICKET]
    assert whole(requires=[], requires_complete=None) == [
        "The FILE says of no OPTION whether it requires this OBJECT.",
        no_refusal,
        ALL_MOVE,
        NO_TICKET,
    ]
    assert whole(requires=[{**needs, "needed": False}], requires_complete=None)[0] == (
        "The FILE leaves open whether another of its OPTIONs requires this OBJECT."
    )
    assert whole(refuses=[bars], requires_complete=None)[1] == (
        "Other OPTIONs of the FILE may refuse it too: the FILE does not say that these are all."
    )
    assert whole(refuses=[{**bars, "refused": False}], requires_complete=None)[1] == (
        "The FILE leaves open whether another of its OPTIONs refuses this OBJECT."
    )
    # Every OPTION of the FILE has a FACT about whether it requires the OBJECT, and one about
    # whether it refuses it.
    every = [
        {**needs, "option": option["id"], "name": option["name"]} for option in sent["options"]
    ]
    all_bar = [
        {**bars, "option": option["id"], "name": option["name"]} for option in sent["options"]
    ]
    assert whole(requires=every, refuses=all_bar, requires_complete=None)[:2] == [
        "The FILE says of each of its OPTIONs whether it requires this OBJECT.",
        "The FILE says of each of its OPTIONs whether it refuses this OBJECT.",
    ]
    # A FILE with no OPTION says so: nothing in it can require the OBJECT or refuse it.
    walk: Trip = {**sent, "options": [], "steps": [], "rights": [], "wants": [], "capabilities": []}
    lone: Trip = {**bags, "requires": [], "requires_complete": None, "transfers": []}
    (shown,) = all_objects([{**walk, "objects": [lone]}])
    assert shown["objects"][0]["whole"] == [
        "The FILE lists no OPTION.",
        ALL_MOVE[:-1] + NONE,
        NO_TICKET,
    ]
    # An OPTION that needs a right for the OBJECT is one that the FILE names. Without the
    # FACT that these are all, another OPTION of the FILE may need one too.
    ticket = {"option": needs["option"], "name": needs["name"], "needed": True, "record": "t"}
    assert whole(rights=[ticket])[-1] == NO_TICKET.removesuffix(", and it names none.") + "."
    assert whole(rights=[ticket], rights_complete=None)[-1] == (
        "Other OPTIONs of the FILE may need a right for it too: the FILE does not say that"
        " these are all."
    )
    assert whole(rights_complete=None)[-1] == (
        "The FILE says of no OPTION whether it needs a right for this OBJECT."
    )
    # A FACT for each OPTION of the FILE leaves nothing open.
    all_ticketed = [
        {**ticket, "option": option["id"], "name": option["name"], "needed": option["id"] == "x"}
        for option in sent["options"]
    ]
    assert whole(rights=all_ticketed, rights_complete=None)[-1] == (
        "The FILE says of each of its OPTIONs whether it needs a right for this OBJECT."
    )
    assert whole(rights=[{**ticket, "needed": False}], rights_complete=None)[-1] == (
        "The FILE leaves open whether another of its OPTIONs needs a right for this OBJECT."
    )


def test_an_option_that_leaves_an_object_alone_or_does_not_require_it_says_so() -> None:
    sent = drawn(STORY / "they-collect-them.json")
    (bags,) = sent["objects"]
    bags["requires"][0]["needed"] = False
    bags["transfers"][0]["does"] = "nothing"
    (shown,) = all_objects([sent])
    (thing,) = shown["objects"]
    assert [(each["says"], each["does"]) for each in (*thing["requires"], *thing["transfers"])] == [
        ("does not require it", False),
        ("leaves it alone", False),
    ]


def test_a_file_with_no_object_shows_none() -> None:
    sent = drawn(EXAMPLES / "flight-home" / "works.json")
    assert sent["objects"] == []
    empty: Objects = {"says": "", "clash": False, "asked": False, "objects": []}
    assert all_objects([sent, None]) == [empty] * 2


def test_every_example_shows_its_objects_in_the_words_of_the_report() -> None:
    """Each OBJECT of each FILE is shown, and each FACT about it is worded as the report does."""
    asked = [in_words(path) for path in FILES]
    shown = all_objects(
        [sent for sent, _, _ in asked],
        [found for _, found, _ in asked],
        [words for _, _, words in asked],
    )
    starts = needs = bars = moves = placed = 0
    for path, (sent, _, words), each in zip(FILES, asked, shown, strict=True):
        file = read(path)
        name = f"{path.parent.name}/{path.stem}"
        assert [thing["id"] for thing in each["objects"]] == [thing.id for thing in file.objects], (
            name
        )
        # Where the report says where each OBJECT is in its plan, the page says each of those
        # lines again, and nothing of a plan where the report says none.
        under = words.split("\nWhere each OBJECT is:\n")[1:]
        again: list[str] = []
        for thing in each["objects"]:
            if thing["plan"] is not None:
                again.append(f"  {thing['name']}: {thing['plan'][len('In the plan: ') : -1]}")
            for check, listed in (
                ("requires", "requires"),
                ("refuses", "refuses"),
                ("needs a right for", "rights"),
            ):
                for option in thing[listed]:
                    if option["plan"] is not None:
                        said = f"{option['name']} {check} {thing['name']}"
                        again.append(f"    {said}. {option['plan']}")
            for option in thing["might"]:
                check = "requires"
                for other in ("refuses", "needs a right for"):
                    if option["says"].endswith(f"{other} it"):
                        check = other
                silent = f"The FILE does not say whether {option['name']} {check} {thing['name']}"
                again.append(f"    {silent}. {option['plan']}")
        if under:
            placed += 1
            lines = under[0].split("\n\n")[0].splitlines()
            assert sorted(again) == sorted(lines), name
        else:
            assert again == [], name
        for thing in each["objects"]:
            called = thing["name"]
            stated = file.object_starts(thing["id"])
            assert (thing["starts"] == UNSAID) is (stated is None), name
            # Where the report has a line about where this OBJECT starts, the page says the same.
            if stated is not None and f"  {stated.id}: " in words:
                starts += 1
                said = thing["starts"][:-1].replace(" it ", f" {called} ", 1)
                said = said.replace("The TRIP starts", "the TRIP starts", 1)
                assert f"  {stated.id}: {said}" in words, name
            for option in (*thing["requires"], *thing["refuses"]):
                if option["step"] is not None:
                    assert sent["steps"][option["step"]]["option"] == option["option"], name
                (record,) = option["records"]
                if f"  {record}: " in words:
                    needs += option in thing["requires"]
                    bars += option in thing["refuses"]
                    said = option["says"].replace(" it", f" {called}", 1)
                    assert f"  {record}: {option['name']} {said}" in words, name
            for option in thing["transfers"]:
                # An OPTION that also refuses the OBJECT is tied to that FACT too, and says
                # after a comma what the two come to.
                record = option["records"][0]
                if f"  {record}: " in words:
                    moves += 1
                    does = option["says"].split(", but ")[0]
                    if does == "it can be handed over here":
                        said = f"{called} can be handed over in {option['name']}"
                    else:
                        said = f"{option['name']} {does.replace(' it', f' {called}', 1)}"
                    assert f"  {record}: {said}" in words, name
    assert min(starts, needs, moves, placed) > 3
    assert bars > 1
