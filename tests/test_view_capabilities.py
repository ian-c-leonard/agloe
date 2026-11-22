"""What the page shows of the CAPABILITIES of a FILE.

The view sends the CAPABILITIES with each report: who has each or does not, and each OPTION
that a FACT says requires it or does not. ``src/agloe/view/static/capabilities.js`` puts them
in words, says who takes part in each of those OPTIONs and who meets what it requires in the
plan of the report, and marks what the report names. It has no page in it, so Node runs it
here, through ``view_part.mjs``.

Nothing in it judges a TRIP. Whether the PERSONs in an OPTION meet what it requires is for
the COMPILER to say: the page names who meets a requirement only where the report does.
"""

import json
from typing import Any

from agloe.answers import Answer, Report
from agloe.file import read
from tests.stories import EXAMPLES, can, cannot, every_requirement, requires, stays, trip
from tests.test_view_calendar import drawn, in_words, parts, sent_for, with_its_report

STORY = EXAMPLES / "a-driver"
FILES = sorted(
    path for path in EXAMPLES.rglob("*.json") if not path.name.endswith(".expected.json")
)
SAYS = (
    "The CAPABILITIES of the FILE, each with who has it and the OPTIONs that the FILE says"
    " require it or do not."
)
RED = " A red edge marks what the report names among what rules out every plan."
YELLOW = " A yellow edge marks what the report names in what the FILE does not say."
ALL = "The FILE states every one of its OPTIONs that requires it."
NOT_ALL = "Other OPTIONs of the FILE may require it too: the FILE does not say that these are all."
OF_ONE = "requires it of one PERSON who takes part"

type Trip = dict[str, Any]
type Capabilities = dict[str, Any]


def all_capabilities(
    trips: list[Trip | None],
    reports: list[dict[str, Any] | None] | None = None,
    texts: list[str | None] | None = None,
) -> list[Capabilities]:
    """What the page shows of the CAPABILITIES of each TRIP, by the page's own code."""
    return parts("capabilities", trips, reports, texts)


def capabilities_of(name: str) -> Capabilities:
    """What the page shows of the CAPABILITIES of an example, with the report on it."""
    sent, found, text = in_words(EXAMPLES / f"{name}.json")
    return all_capabilities([sent], [found], [text])[0]


def people(capability: Capabilities) -> list[tuple[str, str]]:
    """Each PERSON under a CAPABILITY, with what the FILE says of them."""
    return [(person["name"], person["says"]) for person in capability["people"]]


def test_a_capability_says_who_has_it_and_what_requires_it() -> None:
    """Two drives require driving a manual car of one PERSON. Only Sam has it."""
    shown = capabilities_of("a-driver/every-drive-is-stated")
    assert shown["says"] == SAYS
    assert (shown["clash"], shown["asked"]) == (False, False)
    (driving,) = shown["capabilities"]
    assert (driving["id"], driving["name"]) == ("drive-manual", "driving a manual car")
    # Every PERSON of the FILE, in its order, with what the FILE says of them.
    assert people(driving) == [
        ("Alex", "does not have it"),
        ("Sam", "has it"),
        ("Jo", "does not have it"),
    ]
    assert [person["has"] for person in driving["people"]] == [False, True, False]
    assert [person["records"] for person in driving["people"]] == [
        ["alex-does-not-drive-manual"],
        ["sam-drives-manual"],
        ["jo-does-not-drive-manual"],
    ]
    out, back = driving["options"]
    assert out == {
        "option": "drive-out",
        "name": "Drive to the dunes",
        "of": "one",
        "says": OF_ONE,
        "takes": "In the plan: Alex and Sam take part.",
        # The report says who meets what the drive requires, and the page says the same.
        "meets": "Sam meets that requirement.",
        "step": 0,
        "records": ["drive-out-needs-a-driver"],
        "clash": [],
        "finds": None,
        "cases": [],
        "asks": [],
    }
    assert (back["name"], back["meets"], back["step"]) == (
        "Drive back to the hotel",
        "Sam meets that requirement.",
        2,
    )
    # A FACT says that the FILE states every one of its OPTIONs that requires it.
    assert (driving["whole"], driving["records"]) == (ALL, ["every-drive-that-needs-a-driver"])


def test_a_capability_says_what_the_file_does_not_say_of_a_person() -> None:
    """The trip works if Alex can drive a manual car, or if Sam can. Jo cannot."""
    shown = capabilities_of("a-driver/depends-on-who-can-drive")
    assert shown["says"] == SAYS + YELLOW
    assert (shown["clash"], shown["asked"]) == (False, True)
    (driving,) = shown["capabilities"]
    assert people(driving) == [
        ("Alex", "the FILE does not say"),
        ("Sam", "the FILE does not say"),
        ("Jo", "does not have it"),
    ]
    alex, sam, jo = driving["people"]
    assert (alex["has"], alex["records"], alex["cases"]) == (None, [], [0])
    assert alex["asks"] == [
        "The trip works in any of these cases:",
        "1. Alex has the CAPABILITY driving a manual car.",
    ]
    assert (sam["cases"], sam["asks"][1]) == (
        [1],
        "2. Sam has the CAPABILITY driving a manual car.",
    )
    assert (jo["cases"], jo["asks"]) == ([], [])
    # Both cases are about this CAPABILITY, and neither is about what an OPTION requires.
    assert driving["cases"] == [0, 1]
    assert all(option["cases"] == [] for option in driving["options"])
    # With no plan, an OPTION says whom a LOCK names, and nobody is said to meet anything.
    assert [(option["takes"], option["meets"]) for option in driving["options"]] == [
        ("Alex and Sam are each named by a LOCK.", None)
    ] * 2
    # Each OPTION of this FILE has a FACT about driving: there is no other to speak of.
    assert driving["whole"] is None


def test_a_capability_is_marked_where_a_case_is_about_an_option_with_no_fact() -> None:
    """The trip works if brunch does not require driving. No FACT says what brunch requires."""
    shown = capabilities_of("a-driver/depends-on-brunch")
    (driving,) = shown["capabilities"]
    assert "Brunch at the hotel" not in [option["name"] for option in driving["options"]]
    assert driving["cases"] == [0]
    assert driving["asks"] == [
        "The trip works if Brunch at the hotel does not require driving a manual car."
    ]
    assert all(person["cases"] == [] for person in driving["people"])
    assert all(option["cases"] == [] for option in driving["options"])
    # No FACT says what either drive requires, and one case asks about both.
    (driving,) = capabilities_of("a-driver/depends-on-the-car")["capabilities"]
    assert (driving["options"], driving["cases"]) == ([], [0])
    assert driving["whole"] == "The FILE says of no OPTION whether it requires this CAPABILITY."
    # The page reads what a report names, whatever it is: a case that names an OPTION under
    # the CAPABILITY marks that OPTION there.
    sent, found = with_its_report(STORY / "depends-on-who-can-drive.json")
    about_a_drive = {"what": "requirement", "option": "drive-back", "capability": "drive-manual"}
    (shown,) = all_capabilities([sent], [{**found, "missing": [[about_a_drive]]}])
    (driving,) = shown["capabilities"]
    assert [(option["name"], option["cases"]) for option in driving["options"]] == [
        ("Drive to the dunes", []),
        ("Drive back to the hotel", [0]),
    ]
    assert driving["options"][1]["asks"] == [
        "The report names this OPTION and this CAPABILITY in what the FILE does not say."
    ]
    assert all(person["cases"] == [] for person in driving["people"])


def test_the_capabilities_mark_what_the_report_names_as_ruling_out_every_plan() -> None:
    """The drive back requires a driver, and nobody of the FILE can drive a manual car."""
    sent, found = with_its_report(STORY / "cannot-work.json")
    (shown,) = all_capabilities([sent], [found])
    assert shown["says"] == SAYS + RED
    assert shown["clash"] is True
    (driving,) = shown["capabilities"]
    assert [person["clash"] for person in driving["people"]] == [
        ["alex-does-not-drive-manual"],
        ["sam-does-not-drive-manual"],
        ["jo-does-not-drive-manual"],
    ]
    assert driving["people"][0]["finds"] == (
        "The report names alex-does-not-drive-manual among what rules out every plan."
    )
    # The report names what the drive back requires, and not what the drive out requires.
    assert [(option["name"], option["clash"]) for option in driving["options"]] == [
        ("Drive to the dunes", []),
        ("Drive back to the hotel", ["drive-back-needs-a-driver"]),
    ]
    assert driving["clash"] == []
    # Only what a report names is marked.
    odd: list[Any] = [None, {}, {**found, "answer": "FEASIBLE"}, {**found, "conflict": "x"}]
    for other in all_capabilities([sent] * len(odd), odd):
        assert other["says"] == SAYS
        (driving,) = other["capabilities"]
        assert all(each["clash"] == [] for each in (*driving["people"], *driving["options"]))


def test_who_meets_a_requirement_is_said_only_where_the_report_names_them() -> None:
    sent, found = with_its_report(STORY / "works.json")
    met = found["requirements"]
    assert [each["persons"] for each in met] == [["sam"], ["sam"]]
    odd: list[Any] = [
        None,
        {**found, "answer": "UNDETERMINED"},
        {**found, "requirements": "sam"},
        {**found, "requirements": [{**met[0], "persons": "sam"}]},
        {**found, "requirements": [{**met[0], "capability": "swimming"}]},
        {**found, "requirements": [{**met[0], "persons": []}]},
    ]
    for other in all_capabilities([sent] * len(odd), odd):
        (driving,) = other["capabilities"]
        assert [option["meets"] for option in driving["options"]] == [None, None]
    # Several PERSONs meet a requirement of each PERSON who takes part.
    both = {**found, "requirements": [{**met[0], "of": "each", "persons": ["alex", "sam"]}]}
    (shown,) = all_capabilities([sent], [both])
    assert shown["capabilities"][0]["options"][0]["meets"] == "Alex and Sam meet that requirement."


def test_a_capability_says_whether_its_options_are_all_that_require_it() -> None:
    def whole(facts: list[dict[str, Any]], options: tuple[str, ...] = ("swim", "picnic")) -> Any:
        file = trip(
            ["alex"],
            ["pier"],
            [stays(each, "pier") for each in options],
            facts,
            [],
            capabilities=["swimming"],
        )
        sent = sent_for(file, Report(Answer.UNDETERMINED))
        (shown,) = all_capabilities([sent])
        return shown["capabilities"][0]["whole"]

    each = requires("swim", "swimming", "each")
    none = requires("picnic", "swimming", "none")
    assert whole([each, every_requirement("swimming")]) == ALL
    assert whole([none, every_requirement("swimming")]) == (
        "The FILE states every one of its OPTIONs that requires it, and it names none."
    )
    assert whole([each]) == NOT_ALL
    assert whole([none]) == (
        "The FILE leaves open whether another of its OPTIONs requires this CAPABILITY."
    )
    assert whole([can("alex", "swimming")]) == (
        "The FILE says of no OPTION whether it requires this CAPABILITY."
    )
    # Every OPTION of the FILE has a FACT about it: there is no other to speak of.
    assert whole([each, none]) is None
    assert whole([cannot("alex", "swimming")], options=()) is None


def test_an_option_says_what_it_requires_of_a_capability() -> None:
    file = trip(
        ["alex", "sam"],
        ["pier"],
        [stays(each, "pier") for each in ("swim", "tour", "picnic")],
        [
            requires("swim", "swimming", "each"),
            requires("tour", "swimming"),
            requires("picnic", "swimming", "none"),
        ],
        [],
        capabilities=["swimming"],
    )
    (shown,) = all_capabilities([sent_for(file, Report(Answer.UNDETERMINED))])
    assert [(option["name"], option["says"]) for option in shown["capabilities"][0]["options"]] == [
        ("swim", "requires it of each PERSON who takes part"),
        ("tour", OF_ONE),
        ("picnic", "does not require it"),
    ]


def test_a_file_with_no_capability_shows_none() -> None:
    sent = drawn(EXAMPLES / "flight-home" / "works.json")
    assert sent["capabilities"] == []
    assert (
        all_capabilities([sent, None])
        == [{"says": "", "clash": False, "asked": False, "capabilities": []}] * 2
    )


def test_every_example_shows_its_capabilities_in_the_words_of_the_report() -> None:
    """Each CAPABILITY of each FILE is shown, and what the page says is what the report says."""
    asked = [in_words(path) for path in FILES]
    shown = all_capabilities(
        [sent for sent, _, _ in asked],
        [found for _, found, _ in asked],
        [words for _, _, words in asked],
    )
    has = requirements = meets = 0
    for path, (sent, found, words), each in zip(FILES, asked, shown, strict=True):
        file = read(path)
        name = f"{path.parent.name}/{path.stem}"
        assert [capability["id"] for capability in each["capabilities"]] == [
            capability.id for capability in file.capabilities
        ], name
        in_the_file = json.loads(path.read_text())
        for capability in each["capabilities"]:
            called = capability["name"]
            assert [person["person"] for person in capability["people"]] == [
                person["id"] for person in in_the_file["persons"]
            ], name
            for person in capability["people"]:
                # Where the report has a line about this PERSON and this CAPABILITY, the page
                # says the same of them.
                for record in person["records"]:
                    if f"  {record}: " in words:
                        has += 1
                        said = "has" if person["says"] == "has it" else "does not have"
                        assert (
                            f"  {record}: {person['name']} {said} the CAPABILITY {called}" in words
                        )
            for option in capability["options"]:
                if option["step"] is not None:
                    assert sent["steps"][option["step"]]["option"] == option["option"], name
                (record,) = option["records"]
                if f"  {record}: " in words:
                    requirements += 1
                    said = option["says"].replace(" it", f" {called}", 1)
                    assert f"  {record}: {option['name']} {said}" in words, name
                if option["meets"] is not None:
                    meets += 1
                    whom = "one PERSON" if option["of"] == "one" else "each PERSON"
                    stated = f"  {option['name']} requires {called} of {whom}. {option['meets']}"
                    assert stated in words, name
        # Each requirement that the report says somebody meets, for an OPTION with a FACT about
        # what it requires, is said on the page.
        with_a_fact = [met for met in found.get("requirements", []) if met["of"] is not None]
        said_to_meet = [
            option
            for capability in each["capabilities"]
            for option in capability["options"]
            if option["meets"] is not None
        ]
        assert len(said_to_meet) == len(with_a_fact), name
    assert min(has, requirements, meets) > 5
