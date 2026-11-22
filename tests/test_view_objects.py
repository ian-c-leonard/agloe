"""What the page shows of the OBJECTs of a FILE.

The view sends the OBJECTs with each report: where each is when the TRIP starts, the OPTIONs
that a FACT says require it or do not, and those that a FACT says hand it over, keep it or
leave it alone. ``src/agloe/view/static/objects.js`` puts them in words, as the report words
them, says who takes part in each of those OPTIONs, and marks what the report names. It has no
page in it, so Node runs it here, through ``view_part.mjs``.

Nothing in it judges a TRIP. Where an OBJECT is in a plan is for the COMPILER to say.
"""

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
    " FILE says require it, and those that it says hand it over or keep it."
)
RED = " A red edge marks what the report names among what rules out every plan."
YELLOW = " A yellow edge marks what the report names in what the FILE does not say."
ALL_REQUIRE = "The FILE states every one of its OPTIONs that requires it."
ALL_MOVE = "The FILE states every OPTION that hands it over or keeps it."
MAY_MOVE = "Another OPTION may hand it over or keep it: the FILE does not say that these are all."
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


def objects_of(name: str) -> Objects:
    """What the page shows of the OBJECTs of an example, with the report on it."""
    sent, found, text = in_words(EXAMPLES / f"{name}.json")
    return all_objects([sent], [found], [text])[0]


def test_an_object_says_where_it_starts_what_requires_it_and_what_moves_it() -> None:
    """The bags are at the hotel. The flight requires them, and the hotel hands them over."""
    shown = objects_of("the-bags/they-collect-them")
    assert shown["says"] == SAYS
    assert (shown["clash"], shown["asked"]) == (False, False)
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
    assert bags["whole"] == [ALL_REQUIRE, ALL_MOVE]
    # Its own records: where it starts, and the two FACTs that the FILE states every OPTION.
    assert bags["records"] == [
        "where-the-bags-start",
        "every-use-of-the-bags",
        "everything-that-moves-the-bags",
    ]


def test_an_object_that_a_person_has_and_an_option_that_keeps_it() -> None:
    """Alex has the bags when the TRIP starts, and the museum keeps them during the visit."""
    (bags,) = objects_of("the-bags/the-museum-keeps-them")["objects"]
    assert bags["starts"] == "Alex has it when the TRIP starts."
    said = {each["name"]: each["says"] for each in bags["transfers"]}
    assert said["Museum visit"] == "keeps it"
    assert said["Pick up at the cloakroom"] == "it can be handed over here"


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
    assert whole(requires_complete=None, transfers_complete=None) == [
        "Other OPTIONs of the FILE may require it too: the FILE does not say that these are all.",
        MAY_MOVE,
    ]
    assert whole(
        requires=[{**needs, "needed": False}], transfers=[{**moves, "does": "nothing"}]
    ) == [
        "The FILE states every one of its OPTIONs that requires it, and it names none.",
        "The FILE states every OPTION that hands it over or keeps it, and it names none.",
    ]
    assert whole(requires=[], requires_complete=None) == [
        "The FILE says of no OPTION whether it requires this OBJECT.",
        ALL_MOVE,
    ]
    assert whole(requires=[{**needs, "needed": False}], requires_complete=None)[0] == (
        "The FILE leaves open whether another of its OPTIONs requires this OBJECT."
    )
    # Every OPTION of the FILE has a FACT about whether it requires the OBJECT.
    every = [
        {**needs, "option": option["id"], "name": option["name"]} for option in sent["options"]
    ]
    assert whole(requires=every, requires_complete=None)[0] == (
        "The FILE says of each of its OPTIONs whether it requires this OBJECT."
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
    starts = needs = moves = 0
    for path, (sent, _, words), each in zip(FILES, asked, shown, strict=True):
        file = read(path)
        name = f"{path.parent.name}/{path.stem}"
        assert [thing["id"] for thing in each["objects"]] == [thing.id for thing in file.objects], (
            name
        )
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
            for option in thing["requires"]:
                if option["step"] is not None:
                    assert sent["steps"][option["step"]]["option"] == option["option"], name
                (record,) = option["records"]
                if f"  {record}: " in words:
                    needs += 1
                    said = option["says"].replace(" it", f" {called}", 1)
                    assert f"  {record}: {option['name']} {said}" in words, name
            for option in thing["transfers"]:
                (record,) = option["records"]
                if f"  {record}: " in words:
                    moves += 1
                    if option["says"] == "it can be handed over here":
                        said = f"{called} can be handed over in {option['name']}"
                    else:
                        said = f"{option['name']} {option['says'].replace(' it', f' {called}', 1)}"
                    assert f"  {record}: {said}" in words, name
    assert min(starts, needs, moves) > 3
