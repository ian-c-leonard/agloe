"""What the page shows of the WANTs of a FILE.

The view sends the WANTs with each report: for whom each is a must or a must-not, and each
OPTION that a FACT says SATISFIES it or does not. ``src/agloe/view/static/wants.js`` puts them
in words, says who takes part in each of those OPTIONs, and marks what the report names. It
has no page in it, so Node runs it here, through ``view_part.mjs``.

Nothing in it judges a TRIP. Whether an ITINERARY SATISFIES a WANT is for the COMPILER to say.
"""

import json
from typing import Any

from agloe.file import read
from tests.stories import EXAMPLES
from tests.test_view_calendar import drawn, in_words, parts, with_its_report

FILES = sorted(
    path for path in EXAMPLES.rglob("*.json") if not path.name.endswith(".expected.json")
)
SAYS = "The WANTs of the FILE, each with the OPTIONs that the FILE says SATISFY it or do not."
RED = " A red edge marks what the report names among what rules out every plan."
YELLOW = " A yellow edge marks what the report names in what the FILE does not say."
NOT_ALL = "Other OPTIONs may SATISFY it too: the FILE does not say that these are all."
ALL = "The FILE states every OPTION that SATISFIES it."

type Trip = dict[str, Any]
type Wants = dict[str, Any]


def all_wants(
    trips: list[Trip | None],
    reports: list[dict[str, Any] | None] | None = None,
    texts: list[str | None] | None = None,
) -> list[Wants]:
    """What the page shows of the WANTs of each TRIP, by the page's own code."""
    return parts("wants", trips, reports, texts)


def wants_of(name: str, words: bool = True) -> Wants:
    """What the page shows of the WANTs of an example, with the report on it."""
    sent, found, text = in_words(EXAMPLES / f"{name}.json")
    return all_wants([sent], [found], [text if words else None])[0]


def said(option: Wants) -> tuple[Any, ...]:
    """An OPTION under a WANT: its name, what the FILE says of it, who takes part, its step."""
    return (option["name"], option["says"], option["takes"], option["step"])


def test_a_want_says_for_whom_it_is_a_must_and_what_satisfies_it() -> None:
    """Alex must have deep-dish pizza. The plan has dinner at the pizzeria, then a blues show."""
    shown = wants_of("a-must/works")
    assert shown["says"] == SAYS
    assert (shown["clash"], shown["asked"]) == (False, False)
    (pizza,) = shown["wants"]
    assert (pizza["id"], pizza["name"]) == ("deep-dish", "deep-dish pizza")
    assert pizza["holds"] == "A must for Alex."
    assert pizza["ends"] is None
    assert pizza["whole"] == NOT_ALL
    assert pizza["records"] == ["deep-dish"]
    assert [said(option) for option in pizza["options"]] == [
        (
            "Dinner at the deep-dish place",
            "SATISFIES it, 9 out of 10",
            "In the plan: Alex takes part.",
            0,
        ),
        ("Dinner at the tavern", "does not SATISFY it", "Not in the plan.", None),
        ("Blues show", "does not SATISFY it", "In the plan: Alex takes part.", 2),
    ]
    # Each OPTION names the FACT that says so.
    assert [option["records"] for option in pizza["options"]] == [
        ["pizzeria-serves-it"],
        ["tavern-does-not-serve-it"],
        ["show-does-not-serve-it"],
    ]
    # A report on a plan that works marks nothing.
    for each in [pizza, *pizza["options"]]:
        assert (each["clash"], each["finds"], each["cases"], each["asks"]) == ([], None, [], [])


def test_a_want_says_for_whom_it_is_a_must_not() -> None:
    """Alex must have a view from high up, and Jo must not. Only Alex goes up the tower."""
    (view,) = wants_of("a-must-not/works")["wants"]
    assert view["holds"] == "A must for Alex. A must-not for Jo."
    assert [said(option) for option in view["options"]] == [
        ("Skydeck visit", "SATISFIES it, 9 out of 10", "In the plan: Alex takes part.", 0),
        ("Lunch in the park", "does not SATISFY it", "In the plan: Alex, Sam and Jo take part.", 2),
    ]


def test_a_want_about_where_the_trip_ends_says_so() -> None:
    (ending,) = wants_of("ending-in-denver/works")["wants"]
    assert ending["name"] == "ending the trip in Denver"
    # It says what the WANT asks of its holders: another WANT can ask others to end elsewhere.
    assert ending["holds"] == "Alex and Sam must end the TRIP at Denver."
    assert ending["ends"] == "It is about the whole ITINERARY: no OPTION delivers it."
    assert (ending["whole"], ending["options"]) == (None, [])
    # A must-not about where the TRIP ends.
    sent = drawn(EXAMPLES / "ending-in-denver" / "works.json")
    sent["wants"][0].update(musts=["alex"], must_nots=["sam"])
    (shown,) = all_wants([sent])
    assert shown["wants"][0]["holds"] == (
        "Alex must end the TRIP at Denver. Sam must not end the TRIP at Denver."
    )


def test_a_want_says_whether_its_options_are_all_that_satisfy_it() -> None:
    """What stands under the OPTIONs of a WANT never says more than the FILE does."""
    sent = drawn(EXAMPLES / "a-must-not" / "works.json")
    skydeck, lunch = sent["wants"][0]["options"]
    assert (skydeck["degree"], lunch["degree"]) == (9, 0)
    cases: list[tuple[list[dict[str, Any]], str | None, str]] = [
        # An OPTION SATISFIES it: there may be others, unless the FILE states every one.
        ([skydeck, lunch], None, NOT_ALL),
        ([skydeck, lunch], "every-view", ALL),
        # The FILE names only an OPTION that does not SATISFY it.
        ([lunch], None, "The FILE leaves open whether another OPTION SATISFIES this WANT."),
        (
            [lunch],
            "every-view",
            "The FILE states every OPTION that SATISFIES it, and it names none.",
        ),
        # The FILE says nothing of any OPTION and this WANT.
        ([], None, "The FILE says of no OPTION whether it SATISFIES this WANT."),
        ([], "every-view", "The FILE states every OPTION that SATISFIES it, and it names none."),
    ]
    trips: list[Trip | None] = []
    for options, complete, _ in cases:
        other = json.loads(json.dumps(sent))
        other["wants"][0].update(options=options, complete=complete)
        trips.append(other)
    for (_, _, expected), shown in zip(cases, all_wants(trips), strict=True):
        assert shown["wants"][0]["whole"] == expected


def test_each_person_whom_a_lock_names_is_named_so() -> None:
    """Several LOCKs can name the PERSONs of one OPTION: the words fit one LOCK and several."""
    (view,) = wants_of("a-must-not/cannot-work")["wants"]
    assert view["options"][0]["takes"] == "Alex, Sam and Jo are each named by a LOCK."
    (pizza,) = wants_of("a-must/depends-on-the-menu")["wants"]
    assert [option["takes"] for option in pizza["options"]] == [
        "No LOCK names it.",
        "Alex is named by a LOCK.",
    ]


def test_the_wants_mark_what_the_report_names_as_ruling_out_every_plan() -> None:
    """Alex must have deep-dish pizza, and a LOCK names the blues show at the pizzeria's time."""
    shown = wants_of("a-must/cannot-work")
    assert shown["says"] == SAYS + RED
    assert shown["clash"] is True
    (pizza,) = shown["wants"]
    # The WANT's records are itself, and the FACT that the FILE states every OPTION for it.
    assert pizza["whole"] == ALL
    assert pizza["records"] == ["deep-dish", "every-deep-dish-place"]
    assert pizza["clash"] == ["deep-dish", "every-deep-dish-place"]
    assert pizza["finds"] == (
        "The report names deep-dish and every-deep-dish-place among what rules out every plan."
    )
    # The report shows no ITINERARY, so each OPTION says whom a LOCK names for it.
    assert [said(option) for option in pizza["options"]] == [
        ("Dinner at the deep-dish place", "SATISFIES it, 9 out of 10", "No LOCK names it.", None)
    ]
    assert pizza["options"][0]["clash"] == []
    # A FACT that an OPTION SATISFIES the WANT is marked where the report names it.
    (view,) = wants_of("a-must-not/cannot-work")["wants"]
    assert view["clash"] == ["view"]
    skydeck, lunch = view["options"]
    assert lunch["clash"] == []
    assert said(skydeck) == (
        "Skydeck visit",
        "SATISFIES it, 9 out of 10",
        "Alex, Sam and Jo are each named by a LOCK.",
        0,
    )
    assert skydeck["clash"] == ["skydeck-is-high-up"]
    assert skydeck["finds"] == (
        "The report names skydeck-is-high-up among what rules out every plan."
    )


def test_the_wants_mark_what_the_report_says_the_file_does_not_say() -> None:
    """The trip works if dinner at the tavern SATISFIES deep-dish pizza. The FILE does not say."""
    shown = wants_of("a-must/depends-on-the-menu")
    assert shown["says"] == SAYS + YELLOW
    assert shown["asked"] is True
    (pizza,) = shown["wants"]
    assert pizza["cases"] == [0]
    assert pizza["asks"] == ["The trip works if Dinner at the tavern SATISFIES deep-dish pizza."]
    # The FILE has no FACT about the tavern and this WANT, so the tavern is not under it.
    assert [option["name"] for option in pizza["options"]] == [
        "Dinner at the deep-dish place",
        "Blues show",
    ]
    assert all(option["cases"] == [] for option in pizza["options"])
    # A case can name the WANT alone: another OPTION that SATISFIES it is found.
    (pizza,) = wants_of("a-must/depends-on-another-place")["wants"]
    assert pizza["cases"] == [0]
    assert pizza["asks"] == [
        "The trip works if another OPTION that SATISFIES deep-dish pizza is found for Alex."
    ]
    # Without the report in words, the mark says that the report names the WANT.
    (pizza,) = wants_of("a-must/depends-on-another-place", words=False)["wants"]
    assert pizza["asks"] == ["The report names this WANT in what the FILE does not say."]


def test_an_option_under_a_want_is_marked_where_a_case_names_both() -> None:
    """A case that needs a FACT about an OPTION and a WANT marks that OPTION under that WANT."""
    sent, found = with_its_report(EXAMPLES / "a-must-not" / "works.json")
    (need,) = [
        {"what": "does not satisfy", "option": "lunch", "want": "view", "at_most": None},
    ]
    report = {"answer": "UNDETERMINED", "missing": [[need], [{"what": "has", "person": "jo"}]]}
    (shown,) = all_wants([sent], [report])
    (view,) = shown["wants"]
    assert view["cases"] == [0]
    assert [option["cases"] for option in view["options"]] == [[], [0]]
    assert found["answer"] == "FEASIBLE"


def test_only_what_a_report_names_is_marked() -> None:
    sent = drawn(EXAMPLES / "a-must" / "cannot-work.json")
    _, found = with_its_report(EXAMPLES / "a-must" / "cannot-work.json")
    odd: list[Any] = [
        None,
        {},
        # Another answer, and what is no list of ids or of cases.
        {**found, "answer": "FEASIBLE"},
        {**found, "conflict": "deep-dish"},
        {"answer": "INFEASIBLE", "conflict": [7, None, ["deep-dish"]]},
        {"answer": "UNDETERMINED", "missing": [[]]},
        {"answer": "UNDETERMINED", "missing": [["deep-dish"]]},
        {"answer": "UNDETERMINED", "missing": [[{"want": 7}]]},
    ]
    for shown in all_wants([sent] * len(odd), odd):
        assert shown["says"] == SAYS
        assert (shown["clash"], shown["asked"]) == (False, False)
        (pizza,) = shown["wants"]
        assert (pizza["clash"], pizza["cases"]) == ([], [])


def test_a_file_with_no_want_shows_none() -> None:
    (shown,) = all_wants([drawn(EXAMPLES / "flight-home" / "works.json")])
    assert shown == {"says": "", "clash": False, "asked": False, "wants": []}
    # Nor does a TRIP of which the view could make nothing.
    (shown,) = all_wants([None])
    assert shown == {"says": "", "clash": False, "asked": False, "wants": []}


def test_every_example_shows_its_wants() -> None:
    """Each WANT of each FILE is shown once, with each OPTION that the FILE says something of."""
    asked = [in_words(path) for path in FILES]
    shown = all_wants(
        [sent for sent, _, _ in asked],
        [found for _, found, _ in asked],
        [words for _, _, words in asked],
    )
    with_wants = 0
    for path, (sent, _, _), each in zip(FILES, asked, shown, strict=True):
        file = read(path)
        name = f"{path.parent.name}/{path.stem}"
        assert [want["id"] for want in each["wants"]] == [want.id for want in file.wants], name
        with_wants += bool(file.wants)
        for want in each["wants"]:
            stated = [
                option.id
                for option in file.options
                if file.satisfies(option.id, want["id"]) is not None
            ]
            assert [option["option"] for option in want["options"]] == stated, name
            for option in want["options"]:
                # The step that the page ties an OPTION to is that OPTION's step.
                if option["step"] is not None:
                    assert sent["steps"][option["step"]]["option"] == option["option"], name
                fact = file.satisfies(option["option"], want["id"])
                assert fact is not None
                assert option["says"].startswith("SATISFIES") is (fact.degree > 0), name
    assert with_wants == 10
