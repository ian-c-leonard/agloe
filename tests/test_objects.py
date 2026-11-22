"""OBJECTs: where a thing is, which OPTIONs require it, and which hand it over or keep it."""

import json
from collections.abc import Iterator, Sequence
from dataclasses import replace
from itertools import combinations, pairwise, permutations, product
from random import Random

import pytest

from agloe import answers, compiler, reference, report
from agloe.answers import Answer, Carried, Report, Stay, Use
from agloe.file import (
    CompleteRequiresObject,
    CompleteTransfers,
    File,
    FileError,
    Object,
    ObjectStarts,
    RequiresObject,
    WithObject,
    load,
)
from agloe.reference import (
    Broken,
    Constraint,
    Itinerary,
    Remaining,
    Step,
    Unknown,
    Where,
    World,
    best_case,
    best_cases,
    broken,
    broken_as_listed,
    first_shown,
    in_world,
    itineraries,
    longest_case,
    no_better_than,
    one_way_each,
    unknowns,
    whereabouts,
    with_these_at_best,
    works_as_listed,
    worst_case,
)
from tests.stories import (
    EXAMPLES,
    Document,
    any_time,
    booking,
    complete,
    cutoff,
    does_with,
    every,
    every_right,
    every_transfer,
    every_use,
    hands_over,
    has_object,
    keeps,
    lasts,
    lasts_between,
    lies_at,
    lock,
    must,
    needs_right,
    requires_object,
    satisfies,
    seconds,
    starts_at,
    stays,
    takes,
    trip,
    way_between,
)
from tests.test_cross_check import possible_world, random_trip


def at(option: str, hour: int, minute: int = 0, length: str = "PT30M") -> list[Document]:
    """An OPTION that starts at a fixed time, takes this long and has no access cutoff."""
    return [starts_at(option, hour, minute), lasts(option, length), cutoff(option, "PT0S")]


def whenever(option: str, length: str = "PT5M") -> list[Document]:
    """An OPTION that can start at any time, takes this long and has no access cutoff."""
    return [any_time(option), lasts(option, length), cutoff(option, "PT0S")]


def checked(file: File) -> Report:
    """The reference checker's Report, once the COMPILER has given the same one."""
    found = answers.check(file)
    assert compiler.check(file) == found
    return found


def problems(document: Document) -> str:
    with pytest.raises(FileError) as refused:
        load(document)
    return str(refused.value)


def a_document(*facts: Document) -> Document:
    """A check-in desk as the JSON an agent would write, with these FACTs about the passport."""
    return {
        "persons": [{"id": "alex", "name": "Alex"}],
        "places": [{"id": "desk", "name": "the desk"}],
        "objects": [{"id": "passport", "name": "the passport"}],
        "options": [stays("check-in", "desk")],
        "ways": [],
        "wants": [],
        "facts": list(facts),
        "decisions": [],
    }


def asked(found: Report) -> list[tuple[Unknown, ...]]:
    """The sets of unknown FACTs that a report names."""
    return [tuple(needed.unknown for needed in enough) for enough in found.missing]


# What a FILE holds.


def test_a_file_lists_objects_and_states_five_facts_about_them() -> None:
    file = load(
        a_document(
            has_object("alex", "passport"),
            requires_object("check-in", "passport"),
            keeps("check-in", "passport"),
            every_use("passport"),
            every_transfer("passport"),
        )
    )
    assert file.objects == (Object("passport", "the passport"),)
    assert file.facts == (
        ObjectStarts("passport-start", "passport", person="alex"),
        RequiresObject("check-in-requires-passport", "check-in", "passport", True),
        WithObject("check-in-with-passport", "check-in", "passport", "keeps"),
        CompleteRequiresObject("every-use-of-passport", "passport"),
        CompleteTransfers("every-transfer-of-passport", "passport"),
    )


def test_a_file_without_objects_lists_none() -> None:
    document = a_document()
    del document["objects"]
    assert load(document).objects == ()


def test_an_object_starts_with_a_person_or_at_a_place() -> None:
    assert load(a_document(lies_at("passport", "desk"))).facts == (
        ObjectStarts("passport-start", "passport", place="desk"),
    )
    both = {"id": "start", "object": "passport", "starts_with": "alex", "starts_at": "desk"}
    assert "fits no known shape" in problems(a_document(both))


def test_with_no_fact_nobody_knows_about_an_object() -> None:
    file = load(a_document())
    assert file.object_starts("passport") is None
    assert file.requires_object("check-in", "passport") is None
    assert file.does_with("check-in", "passport") is None


def test_a_fact_states_whether_an_option_requires_an_object() -> None:
    for needed in (True, False):
        file = load(a_document(requires_object("check-in", "passport", needed)))
        assert file.requires_object("check-in", "passport") is needed


@pytest.mark.parametrize("does", ["hands_over", "keeps", "nothing"])
def test_a_fact_states_what_an_option_does_with_an_object(does: str) -> None:
    file = load(a_document(does_with("check-in", "passport", does)))
    assert file.does_with("check-in", "passport") == does


def test_a_complete_set_settles_what_an_option_with_no_fact_requires_and_does() -> None:
    file = load(a_document(every_use("passport")))
    assert file.requires_object("check-in", "passport") is False
    assert file.does_with("check-in", "passport") is None
    file = load(a_document(every_transfer("passport")))
    assert file.requires_object("check-in", "passport") is None
    assert file.does_with("check-in", "passport") == "nothing"
    # Each set is about the OPTIONs of the FILE only.
    assert file.does_with("another", "passport") is None
    assert load(a_document(every_use("passport"))).requires_object("another", "passport") is None


def test_what_an_option_does_is_one_of_three_things_and_a_requirement_is_yes_or_no() -> None:
    assert "fits no known shape" in problems(a_document(does_with("check-in", "passport", "eats")))
    wrong = requires_object("check-in", "passport")
    wrong["requires"]["needed"] = "yes"
    assert "is not of type 'boolean'" in problems(a_document(wrong))


def test_a_requirement_with_a_part_missing_is_named_for_what_it_is_about() -> None:
    """A FACT with ``requires`` is about a CAPABILITY or about an OBJECT. What is inside says
    which, so the problem names the part that an OBJECT's requirement lacks."""
    wrong = requires_object("check-in", "passport")
    del wrong["requires"]["needed"]
    assert "'needed' is a required property" in problems(a_document(wrong))


@pytest.mark.parametrize(
    "fact",
    [
        has_object("alex", "keys"),
        lies_at("keys", "desk"),
        requires_object("check-in", "keys"),
        keeps("check-in", "keys"),
        every_use("keys"),
        every_transfer("keys"),
    ],
)
def test_each_fact_names_an_object_of_the_file(fact: Document) -> None:
    assert "keys is not an OBJECT in this FILE" in problems(a_document(fact))


def test_a_fact_about_an_object_names_a_person_a_place_or_an_option_of_the_file() -> None:
    assert "sam is not a PERSON" in problems(a_document(has_object("sam", "passport")))
    assert "gate is not a PLACE" in problems(a_document(lies_at("passport", "gate")))
    assert "boarding is not an OPTION" in problems(
        a_document(requires_object("boarding", "passport"))
    )
    assert "boarding is not an OPTION" in problems(a_document(keeps("boarding", "passport")))


def test_a_file_states_each_fact_about_an_object_once() -> None:
    twice = [
        [has_object("alex", "passport"), {**lies_at("passport", "desk"), "id": "again"}],
        [
            requires_object("check-in", "passport"),
            {**requires_object("check-in", "passport", False), "id": "again"},
        ],
        [keeps("check-in", "passport"), {**hands_over("check-in", "passport"), "id": "again"}],
        [every_use("passport"), {**every_use("passport"), "id": "again"}],
        [every_transfer("passport"), {**every_transfer("passport"), "id": "again"}],
    ]
    for facts in twice:
        assert "another FACT already states this about" in problems(a_document(*facts))


def test_a_complete_set_is_of_one_kind() -> None:
    mixed = {"id": "both", "complete": {"requires_object": "passport", "transfers": "passport"}}
    said = problems(a_document(mixed))
    assert "the OPTIONs that require an OBJECT, or the transfers of an OBJECT" in said


def test_an_object_has_an_id_of_its_own() -> None:
    document = a_document()
    document["objects"] = [{"id": "alex", "name": "the passport"}]
    assert "the id alex is used more than once" in problems(document)


def test_only_an_object_that_some_option_might_require_is_asked_for() -> None:
    silent = load(a_document())
    assert [thing.id for thing in silent.objects_asked_for()] == ["passport"]
    for settled in (every_use("passport"), requires_object("check-in", "passport", False)):
        assert load(a_document(settled)).objects_asked_for() == ()


# The CONSTRAINT, on ITINERARIES written by hand.


def a_desk(*facts: Document, persons: Sequence[str] = ("alex", "sam")) -> File:
    """Two appointments at a desk and one at an office, an hour apart, and a walk between."""
    options = [stays("first", "desk"), stays("second", "desk"), stays("third", "office")]
    times = [*at("first", 9), *at("second", 10), *at("third", 11)]
    walk = [way_between("walk", "desk", "office")]
    stated = [*times, takes("walk", "PT15M"), *facts]
    return trip(list(persons), ["desk", "office"], options, stated, [], walk, objects=["passport"])


def step(
    option: str,
    place: str,
    hour: int,
    *persons: str,
    minute: int = 0,
    handed: tuple[tuple[str, str], ...] = (),
) -> Step:
    start = seconds(hour, minute)
    return Step(option, place, place, persons, start, start + 1800, handed=handed)


def walk(person: str, origin: str, destination: str, hour: int, minute: int) -> Step:
    start = seconds(hour, minute)
    return Step(None, origin, destination, (person,), start, start + 900, "walk")


def not_at_hand(option: str, *persons: str) -> Broken:
    return Broken(Constraint.AT_HAND, option, persons, object="passport")


def test_an_object_is_at_hand_with_a_person_who_takes_part() -> None:
    file = a_desk(has_object("alex", "passport"), requires_object("first", "passport"))
    world = worst_case(replace_silence(file))
    assert broken(file, world, (step("first", "desk", 9, "alex", "sam"),)) == []
    assert broken(file, world, (step("first", "desk", 9, "sam"),)) == [not_at_hand("first", "sam")]


def replace_silence(file: File) -> File:
    """The same FILE with both sets of each OBJECT COMPLETE, so that nothing else is unknown."""
    whole = [
        fact
        for thing in file.objects
        for fact in (
            CompleteRequiresObject(f"every-use-of-{thing.id}", thing.id),
            CompleteTransfers(f"every-transfer-of-{thing.id}", thing.id),
        )
        if fact.id not in {each.id for each in file.facts}
    ]
    return replace(file, facts=(*file.facts, *whole))


def settled(file: File) -> World:
    """The one possible world of a FILE that leaves nothing unknown about its OBJECTs."""
    return worst_case(replace_silence(file))


def test_an_object_is_at_hand_where_it_lies() -> None:
    file = a_desk(lies_at("passport", "desk"), requires_object("first", "passport"))
    assert broken(file, settled(file), (step("first", "desk", 9, "sam"),)) == []
    elsewhere = a_desk(lies_at("passport", "office"), requires_object("first", "passport"))
    assert broken(elsewhere, settled(elsewhere), (step("first", "desk", 9, "sam"),)) == [
        not_at_hand("first", "sam")
    ]


def test_an_object_goes_where_its_person_goes() -> None:
    """Alex has the passport and walks to the office. Nothing hands it over on the way."""
    file = a_desk(has_object("alex", "passport"), requires_object("third", "passport"))
    plan = (walk("alex", "desk", "office", 10, 0), step("third", "office", 11, "alex"))
    assert broken(file, settled(file), plan) == []
    # It does not go with Sam.
    other = (walk("sam", "desk", "office", 10, 0), step("third", "office", 11, "sam"))
    assert broken(file, settled(file), other) == [not_at_hand("third", "sam")]


def test_an_option_that_keeps_an_object_leaves_it_where_the_option_starts() -> None:
    file = a_desk(
        has_object("alex", "passport"),
        keeps("first", "passport"),
        requires_object("second", "passport"),
        requires_object("third", "passport"),
    )
    world = settled(file)
    # At the same desk it is at hand, for anybody.
    here = (step("first", "desk", 9, "alex"), step("second", "desk", 10, "sam"))
    assert broken(file, world, here) == []
    # At the office it is not, though Alex is there.
    there = (
        step("first", "desk", 9, "alex"),
        walk("alex", "desk", "office", 10, 0),
        step("third", "office", 11, "alex"),
    )
    assert broken(file, world, there) == [not_at_hand("third", "alex")]
    assert whereabouts(file, world, there)["passport"] == (
        frozenset({Where(person="alex")}),
        frozenset({Where(place="desk")}),
        frozenset({Where(place="desk")}),
    )


def test_an_option_keeps_only_what_a_person_who_takes_part_has() -> None:
    """Sam's appointment keeps the passport, and Alex has it. It happens without the passport."""
    file = a_desk(
        has_object("alex", "passport"),
        keeps("first", "passport"),
        requires_object("third", "passport"),
    )
    plan = (
        step("first", "desk", 9, "sam"),
        walk("alex", "desk", "office", 10, 0),
        step("third", "office", 11, "alex"),
    )
    assert broken(file, settled(file), plan) == []


def test_an_object_is_handed_over_where_it_is_at_hand() -> None:
    file = a_desk(
        lies_at("passport", "desk"),
        hands_over("first", "passport"),
        requires_object("third", "passport"),
    )
    world = settled(file)
    taken = (
        step("first", "desk", 9, "alex", handed=(("passport", "alex"),)),
        walk("alex", "desk", "office", 10, 0),
        step("third", "office", 11, "alex"),
    )
    assert broken(file, world, taken) == []
    # A hand-over is a choice. Without it the passport stays on the desk.
    left = (
        step("first", "desk", 9, "alex"),
        walk("alex", "desk", "office", 10, 0),
        step("third", "office", 11, "alex"),
    )
    assert broken(file, world, left) == [not_at_hand("third", "alex")]


def test_one_person_hands_an_object_to_another() -> None:
    file = a_desk(
        has_object("sam", "passport"),
        hands_over("first", "passport"),
        requires_object("third", "passport"),
    )
    plan = (
        step("first", "desk", 9, "alex", "sam", handed=(("passport", "alex"),)),
        walk("alex", "desk", "office", 10, 0),
        step("third", "office", 11, "alex"),
    )
    assert broken(file, settled(file), plan) == []


def test_an_object_is_handed_over_only_in_an_option_that_hands_it_over() -> None:
    file = a_desk(lies_at("passport", "desk"), hands_over("first", "passport"))
    world = settled(file)
    # The second appointment leaves it alone.
    plan = (step("second", "desk", 10, "alex", handed=(("passport", "alex"),)),)
    assert broken(file, world, plan) == [not_at_hand("second", "alex")]
    # The first hands it over, and at the office it is not at hand.
    far = a_desk(lies_at("passport", "office"), hands_over("first", "passport"))
    plan = (step("first", "desk", 9, "alex", handed=(("passport", "alex"),)),)
    assert broken(far, settled(far), plan) == [not_at_hand("first", "alex")]


def test_a_step_checks_then_keeps_and_then_hands_over() -> None:
    """The appointment requires the passport and keeps it: Alex has it when the check is made.
    The next one requires it and hands it over: it lies on the desk when the check is made."""
    file = a_desk(
        has_object("alex", "passport"),
        requires_object("first", "passport"),
        keeps("first", "passport"),
        requires_object("second", "passport"),
        hands_over("second", "passport"),
        requires_object("third", "passport"),
    )
    plan = (
        step("first", "desk", 9, "alex"),
        step("second", "desk", 10, "sam", handed=(("passport", "sam"),)),
        walk("sam", "desk", "office", 10, 30),
        step("third", "office", 11, "sam"),
    )
    assert broken(file, settled(file), plan) == []


def test_steps_that_start_at_one_instant_happen_in_the_order_listed() -> None:
    """Alex's appointment keeps the passport and lasts half an hour. Sam picks it up at the
    same instant, at the same desk, and needs it at the office later. That works with Alex's
    appointment listed first, however long it takes: what it does with the passport happens
    at its start."""
    options = [stays("pick-up", "desk"), stays("appointment", "desk"), stays("later", "office")]
    facts = [
        *at("pick-up", 10, length="PT5M"),
        *at("appointment", 10),
        *at("later", 11),
        takes("walk", "PT15M"),
        complete(None, None),
        has_object("alex", "passport"),
        keeps("appointment", "passport"),
        hands_over("pick-up", "passport"),
        requires_object("later", "passport"),
        every_use("passport"),
        every_transfer("passport"),
    ]
    locks = [lock("appointment", "alex"), lock("pick-up", "sam"), lock("later", "sam")]
    ways = [way_between("walk", "desk", "office")]
    file = trip(
        ["alex", "sam"], ["desk", "office"], options, facts, locks, ways, objects=["passport"]
    )
    world = worst_case(file)
    keep = Step("appointment", "desk", "desk", ("alex",), seconds(10), seconds(10, 30))
    take = Step(
        "pick-up",
        "desk",
        "desk",
        ("sam",),
        seconds(10),
        seconds(10, 5),
        handed=(("passport", "sam"),),
    )
    there = Step(None, "desk", "office", ("sam",), seconds(10, 5), seconds(10, 20), "walk")
    later = Step("later", "office", "office", ("sam",), seconds(11), seconds(11, 30))
    assert works_as_listed(file, world, (keep, take, there, later))
    assert broken(file, world, (keep, take, there, later)) == []
    # Listed the other way round, the passport is still with Alex when Sam comes for it.
    assert broken_as_listed(file, world, (take, keep, there, later)) == [
        Broken(Constraint.AT_HAND, "pick-up", ("sam",), object="passport"),
        Broken(Constraint.AT_HAND, "later", ("sam",), object="passport"),
    ]
    # The search finds that order, though the FILE lists the pick-up first.
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert found.itinerary == (keep, take, there, later)


def test_a_hand_over_is_in_an_option_to_a_person_who_takes_part_once() -> None:
    file = a_desk(lies_at("passport", "desk"), hands_over("first", "passport"))
    world = settled(file)
    wrong: list[Itinerary] = [
        (step("first", "desk", 9, "alex", handed=(("passport", "sam"),)),),
        (step("first", "desk", 9, "alex", handed=(("keys", "alex"),)),),
        (step("first", "desk", 9, "alex", handed=(("passport", "alex"), ("passport", "alex"))),),
        (replace(walk("alex", "desk", "office", 9, 0), handed=(("passport", "alex"),)),),
    ]
    for plan in wrong:
        with pytest.raises(ValueError, match="hands"):
            broken(file, world, plan)


def test_where_an_object_is_depends_on_no_duration() -> None:
    """The same plan at the longest durations has the passport in the same places."""
    file = a_desk(
        has_object("alex", "passport"),
        keeps("first", "passport"),
        requires_object("second", "passport"),
    )
    file = replace_silence(file)
    plan = (step("first", "desk", 9, "alex"), step("second", "desk", 10, "sam"))
    worst, longest = worst_case(file), longest_case(file)
    assert whereabouts(file, worst, plan) == whereabouts(file, longest, in_world(longest, plan))


# The two cases.


def test_the_two_cases_take_what_the_file_does_not_say_each_its_own_way() -> None:
    file = a_desk()
    worst, best = worst_case(file), best_case(file)
    everything = {(option.id, "passport") for option in file.options}
    # At worst each OPTION requires the passport, hands nothing over and might keep it, and
    # the passport is somewhere the FILE does not name.
    assert worst.needs == everything
    assert dict(worst.does) == dict.fromkeys(everything, "might_keep")
    assert not worst.starts and not worst.starts_anywhere and not worst.brought
    # At best no OPTION requires it, and another transfer brings it wherever a plan needs it.
    assert not best.needs and not best.does
    assert best.brought == {"passport"}


def test_a_complete_set_of_transfers_leaves_the_start_to_pick() -> None:
    """Both sets are COMPLETE, and no FACT says where the passport starts. That is still
    unknown: at worst it is somewhere else, and at best wherever suits the plan."""
    file = a_desk(every_use("passport"), every_transfer("passport"))
    worst, best = worst_case(file), best_case(file)
    assert not worst.needs and not worst.does and not worst.starts
    assert not best.brought
    assert best.starts_anywhere == {"passport"} and not worst.starts_anywhere


def test_the_worst_case_follows_every_place_an_object_might_be() -> None:
    """Nobody said what the first appointment does with the passport. Afterwards it is with
    Alex or on the desk. An appointment at the desk with Alex finds it either way. One at the
    office does not, and neither does one at the desk without Alex."""
    file = a_desk(
        has_object("alex", "passport"),
        requires_object("first", "passport", False),
        requires_object("second", "passport"),
        requires_object("third", "passport"),
    )
    world = worst_case(file)
    both = (step("first", "desk", 9, "alex"), step("second", "desk", 10, "alex"))
    assert broken(file, world, both) == []
    assert whereabouts(file, world, both)["passport"][1] == {
        Where(person="alex"),
        Where(place="desk"),
    }
    without_alex = (step("first", "desk", 9, "alex"), step("second", "desk", 10, "sam"))
    assert broken(file, world, without_alex) == [not_at_hand("second", "sam")]
    away = (
        step("first", "desk", 9, "alex"),
        walk("alex", "desk", "office", 10, 0),
        step("third", "office", 11, "alex"),
    )
    assert broken(file, world, away) == [not_at_hand("third", "alex")]


def test_an_object_that_might_be_in_two_places_can_be_handed_over() -> None:
    """After the first appointment the passport is with Alex or on the desk. The second one
    hands it over, with Alex in it: Sam has it afterwards, wherever it was."""
    file = a_desk(
        has_object("alex", "passport"),
        requires_object("first", "passport", False),
        requires_object("second", "passport", False),
        hands_over("second", "passport"),
        requires_object("third", "passport"),
    )
    plan = (
        step("first", "desk", 9, "alex"),
        step("second", "desk", 10, "alex", "sam", handed=(("passport", "sam"),)),
        walk("sam", "desk", "office", 10, 30),
        step("third", "office", 11, "sam"),
    )
    world = worst_case(file)
    assert broken(file, world, plan) == []
    assert whereabouts(file, world, plan)["passport"][2] == {Where(person="sam")}


# The answers.


def two_desks(*more: Document) -> File:
    """Alex and Sam are LOCKed into two desks at 10:00 am. Each desk requires the one permit.

    The desks are a 15 minute walk apart, and the FILE lists every way.
    """
    options = [stays("desk-a", "north"), stays("desk-b", "south")]
    facts = [
        *at("desk-a", 10),
        *at("desk-b", 10),
        takes("walk", "PT15M"),
        complete(None, None),
        requires_object("desk-a", "permit"),
        requires_object("desk-b", "permit"),
        *more,
    ]
    locks = [lock("desk-a", "alex"), lock("desk-b", "sam")]
    ways = [way_between("walk", "north", "south")]
    return trip(
        ["alex", "sam"], ["north", "south"], options, facts, locks, ways, objects=["permit"]
    )


def test_one_object_cannot_be_at_hand_in_two_places_at_one_instant() -> None:
    """With every transfer stated, the COMPILER works that out, wherever the permit starts."""
    found = checked(two_desks(every_transfer("permit")))
    assert found.answer is Answer.INFEASIBLE
    assert {"desk-a-requires-permit", "desk-b-requires-permit"} <= set(found.conflict)
    assert "every-transfer-of-permit" in found.conflict


def test_with_the_transfers_left_open_the_compiler_says_what_it_has_not_worked_out() -> None:
    """Another transfer might bring the permit, and the COMPILER does not work out what one
    can do. So the TRIP is UNDETERMINED, and the one case is marked as not settled. It names
    both desks: that is what whoever looks into it has to make possible."""
    file = two_desks()
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    assert asked(found) == [(Unknown("another transfer", about="permit"),)]
    assert found.missing[0][0].at_hand_for == (("desk-a", True), ("desk-b", True))
    assert report.as_json(file, found)["missing"] == [
        [
            {
                "what": "another transfer",
                "object": "permit",
                "at_hand_for": [
                    {"option": "desk-a", "stated": True},
                    {"option": "desk-b", "stated": True},
                ],
                "settled": False,
            }
        ]
    ]
    words = report.as_text(file, found)
    assert "The trip might work if permit can be at hand some other way for desk-a and desk-b." in (
        words
    )
    assert "That is not settled. Nothing that the FILE lists brings permit there" in words
    assert "The trip works" not in words


def test_a_requirement_that_the_file_leaves_open_is_named_as_one_that_might_hold() -> None:
    """Nobody said whether desk-b requires the permit. At worst it does, so the plan needs
    the permit there too, and the report says: if it requires it."""
    file = two_desks()
    file = replace(file, facts=tuple(f for f in file.facts if f.id != "desk-b-requires-permit"))
    found = checked(replace(file, facts=(*file.facts, lies_at_fact("permit", "south"))))
    assert found.answer is Answer.UNDETERMINED
    assert asked(found) == [(Unknown("another transfer", about="permit"),)]
    assert found.missing[0][0].at_hand_for == (("desk-a", True), ("desk-b", False))
    words = report.as_text(file, found)
    assert "for desk-a, and for desk-b if it requires permit." in words


def lies_at_fact(thing: str, place: str) -> ObjectStarts:
    return ObjectStarts(f"{thing}-start", thing, place=place)


def two_appointments(*more: Document) -> File:
    """Only Alex may attend at 9:00 am and only Sam at 10:00 am, at one desk.

    Alex has the passport, and Sam's appointment requires it.
    """
    options = [stays("nine", "desk"), stays("ten", "desk")]
    facts = [
        *at("nine", 9),
        *at("ten", 10),
        needs_right("nine"),
        needs_right("ten"),
        booking("nine", "alex"),
        booking("ten", "sam"),
        every_right("nine"),
        every_right("ten"),
        has_object("alex", "passport"),
        requires_object("ten", "passport"),
        every_use("passport"),
        *more,
    ]
    locks = [lock("nine", "alex"), lock("ten", "sam")]
    return trip(["alex", "sam"], ["desk"], options, facts, locks, rights=True, objects=["passport"])


def test_a_report_can_ask_that_an_option_keeps_an_object() -> None:
    """If the first appointment keeps the passport, Sam finds it on the desk. If it leaves it
    with Alex, Sam does not. One FACT about a listed OPTION is enough, and the report asks
    for it before it asks for another transfer."""
    file = two_appointments()
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    assert asked(found) == [(Unknown("keeps", "nine", about="passport"),)]
    assert report.as_json(file, found)["missing"] == [
        [{"what": "keeps", "option": "nine", "object": "passport"}]
    ]
    assert "The trip works if nine keeps passport." in report.as_text(file, found)
    kept = replace(file, facts=(*file.facts, WithObject("kept", "nine", "passport", "keeps")))
    assert checked(kept).answer is Answer.FEASIBLE


def test_a_conflict_can_hold_the_fact_that_an_option_hands_an_object_over() -> None:
    """The first appointment hands the passport over, and only Alex is there to have it.
    Without that FACT the appointment might keep it, which is what Sam needs. So the FACT
    is part of the conflict, with the COMPLETE set that makes it the last word."""
    file = two_appointments(hands_over("nine", "passport"), every_transfer("passport"))
    found = checked(file)
    assert found.answer is Answer.INFEASIBLE
    assert "nine-with-passport" in found.conflict
    assert "every-transfer-of-passport" in found.conflict
    assert "every-use-of-passport" not in found.conflict
    reopened = Remaining(file).without("nine-with-passport")
    assert best_cases_work(reopened)


def best_cases_work(left: Remaining) -> bool:
    """Whether something works in some best case of what is left of a FILE."""
    return any(itineraries(left.file, world) for world in best_cases(left))


def test_a_plan_that_holds_wherever_the_object_is_can_be_robust() -> None:
    """Alex has to attend one of two appointments at 9:00 am and a check at 10:00 am, all at
    one desk. The check requires the passport. The first appointment leaves it alone and can
    run to 10:30 am. The second takes 15 minutes, and nobody said what it does with the
    passport: afterwards it is with Alex or on the desk, and the check finds it either way.
    So the second is sure to hold, and the report shows it with no WARNING."""
    options = [stays("long", "desk"), stays("short", "desk"), stays("check", "desk")]
    facts = [
        starts_at("long", 9),
        lasts_between("long", "PT30M", "PT1H30M"),
        cutoff("long", "PT0S"),
        *at("short", 9, length="PT15M"),
        *at("check", 10),
        satisfies("long", "appointment"),
        satisfies("short", "appointment"),
        every("appointment"),
        has_object("alex", "passport"),
        requires_object("check", "passport"),
        every_use("passport"),
        does_with("long", "passport", "nothing"),
    ]
    file = trip(
        ["alex"],
        ["desk"],
        options,
        facts,
        [lock("check", "alex")],
        wants=[must("appointment", "alex")],
        objects=["passport"],
    )
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert found.robust is True
    assert [each.option for each in found.itinerary] == ["short", "check"]
    either = (Where(person="alex"), Where(place="desk"))
    assert found.objects == (
        Carried(
            "passport",
            (Stay((Where(person="alex"),)), Stay(either, "short", "might be kept")),
            (Use("check", True, either),),
        ),
    )
    words = report.as_text(file, found)
    assert (
        "  passport: with alex when the TRIP starts; with alex or at desk from 9:00 am"
        " (the FILE does not say what short does with passport)"
    ) in words
    assert "    check requires passport. At its start: with alex or at desk." in words
    # At the shortest durations the rule would show the first appointment.
    assert [each.option for each in first_shown(file, worst_case(file)) or ()] == ["long", "check"]


def test_an_object_can_lie_at_one_place_twice() -> None:
    """A bag lies on a desk. Sam reads it there at 8:55 am. Alex picks it up at 9:00 am,
    needs it at the office, and brings it back to an OPTION that keeps it at 10:00 am. Sam
    reads it there again at 10:05 am. One chain of hand-overs, and two stays on the desk."""
    options = [
        stays("read-late", "desk"),
        stays("bring-back", "desk"),
        stays("use", "office"),
        stays("pick-up", "desk"),
        stays("read-early", "desk"),
    ]
    facts = [
        *at("read-early", 8, 55, "PT5M"),
        *at("pick-up", 9, 0, "PT5M"),
        *at("use", 9, 30, "PT15M"),
        *at("bring-back", 10, 0, "PT5M"),
        *at("read-late", 10, 5, "PT5M"),
        takes("walk", "PT10M"),
        complete(None, None),
        lies_at("bag", "desk"),
        requires_object("read-early", "bag"),
        hands_over("pick-up", "bag"),
        requires_object("use", "bag"),
        keeps("bring-back", "bag"),
        requires_object("read-late", "bag"),
        every_use("bag"),
        every_transfer("bag"),
    ]
    locks = [
        lock("read-early", "sam"),
        lock("pick-up", "alex"),
        lock("use", "alex"),
        lock("bring-back", "alex"),
        lock("read-late", "sam"),
    ]
    ways = [way_between("walk", "desk", "office")]
    file = trip(["alex", "sam"], ["desk", "office"], options, facts, locks, ways, objects=["bag"])
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    on_the_desk, with_alex = (Where(place="desk"),), (Where(person="alex"),)
    assert found.objects == (
        Carried(
            "bag",
            (
                Stay(on_the_desk),
                Stay(with_alex, "pick-up", "handed over"),
                Stay(on_the_desk, "bring-back", "kept"),
            ),
            (
                Use("read-early", True, on_the_desk),
                Use("use", True, with_alex),
                Use("read-late", True, on_the_desk),
            ),
        ),
    )


def test_whoever_has_an_object_cannot_be_in_two_options_at_once() -> None:
    """Jo has the keys, and two OPTIONs at 10:00 am require them. Jo is in one of them."""

    def the_keys(hour: int, minute: int) -> File:
        options = [stays("first", "garage"), stays("second", "garage")]
        facts = [
            *at("first", 10),
            *at("second", hour, minute),
            has_object("jo", "keys"),
            requires_object("first", "keys"),
            requires_object("second", "keys"),
            every_use("keys"),
            every_transfer("keys"),
        ]
        locks = [lock("first", "jo", "alex"), lock("second", "sam")]
        return trip(["alex", "sam", "jo"], ["garage"], options, facts, locks, objects=["keys"])

    assert checked(the_keys(10, 0)).answer is Answer.INFEASIBLE
    # Half an hour later Jo comes along to the second one, though no LOCK names Jo.
    later = checked(the_keys(10, 30))
    assert later.answer is Answer.FEASIBLE
    assert later.itinerary[1].persons == ("sam", "jo")


def two_bags(*more: Document, options: Sequence[Document] = ()) -> File:
    """Two bags lie on a desk. At 10:00 am Alex has to see the blue one and Sam the red one.

    At 11:00 am Alex needs the red one at the office, and Sam the blue one at the cafe. Each
    appointment at the desk hands over the bag that its PERSON needs later.
    """
    listed = [
        stays("sam-desk", "desk"),
        stays("alex-desk", "desk"),
        stays("alex-later", "office"),
        stays("sam-later", "cafe"),
        *options,
    ]
    facts = [
        *at("alex-desk", 10, length="PT5M"),
        *at("sam-desk", 10, length="PT5M"),
        *at("alex-later", 11),
        *at("sam-later", 11),
        takes("to-the-office", "PT15M"),
        takes("to-the-cafe", "PT15M"),
        complete(None, None),
        lies_at("blue", "desk"),
        lies_at("red", "desk"),
        requires_object("alex-desk", "blue"),
        hands_over("alex-desk", "red"),
        requires_object("sam-desk", "red"),
        hands_over("sam-desk", "blue"),
        requires_object("alex-later", "red"),
        requires_object("sam-later", "blue"),
        *(every_use(bag) for bag in ("blue", "red")),
        *(every_transfer(bag) for bag in ("blue", "red")),
        *more,
    ]
    locks = [
        lock("alex-desk", "alex"),
        lock("sam-desk", "sam"),
        lock("alex-later", "alex"),
        lock("sam-later", "sam"),
    ]
    ways = [
        way_between("to-the-office", "desk", "office"),
        way_between("to-the-cafe", "desk", "cafe"),
    ]
    places = ["desk", "office", "cafe"]
    return trip(["alex", "sam"], places, listed, facts, locks, ways, objects=["blue", "red"])


def test_an_order_that_goes_round_in_a_circle_is_no_order() -> None:
    """Whoever comes first takes the bag that the other has to see. Both appointments start
    at one instant, and still neither order works."""
    assert checked(two_bags()).answer is Answer.INFEASIBLE


def test_the_trip_can_still_work_with_other_hand_overs() -> None:
    """Alex can also collect the red bag at the desk at 10:30 am. So Alex goes first and
    takes nothing, Sam takes the blue bag, and Alex comes back for the red one. The FILE
    lists Sam's appointment first, and the plan still puts Alex's first."""
    collect = [*at("collect", 10, 30, "PT5M"), hands_over("collect", "red")]
    found = checked(two_bags(*collect, options=[stays("collect", "desk")]))
    assert found.answer is Answer.FEASIBLE
    steps = [(each.option, each.handed) for each in found.itinerary if each.option is not None]
    assert steps[:3] == [
        ("alex-desk", ()),
        ("sam-desk", (("blue", "sam"),)),
        ("collect", (("red", "alex"),)),
    ]


def test_an_object_is_handed_to_the_person_listed_first_who_does_not_have_it() -> None:
    """Jo has the bags and is listed first. Coffee hands them over, and Alex and Sam both
    need them later. Alex is listed before Sam, so Alex takes them."""
    options = [stays("coffee", "cafe"), stays("flight", "gate")]
    facts = [
        *at("coffee", 10),
        *at("flight", 12),
        takes("train", "PT30M"),
        complete(None, None),
        has_object("jo", "bags"),
        hands_over("coffee", "bags"),
        requires_object("flight", "bags"),
        every_use("bags"),
        every_transfer("bags"),
    ]
    locks = [lock("coffee", "jo", "alex", "sam"), lock("flight", "alex", "sam")]
    ways = [way_between("train", "cafe", "gate")]
    file = trip(
        ["jo", "alex", "sam"], ["cafe", "gate"], options, facts, locks, ways, objects=["bags"]
    )
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert found.itinerary[0].handed == (("bags", "alex"),)
    assert report.as_json(file, found)["itinerary"][0]["hands_over"] == {"bags": "alex"}  # type: ignore[index]
    words = report.as_text(file, found)
    assert "am: coffee, jo, alex and sam\n    alex takes bags here.\n" in words


def a_desk_with_two_hand_overs(
    *locks: Document, facts: Sequence[Document] = (), more: Sequence[Document] = ()
) -> File:
    """The bags lie on a desk. Two OPTIONs there hand them over, and one at the office requires
    them at 11:00 am. The FILE lists every way. ``more`` holds other OPTIONs."""
    options = [stays("first", "desk"), stays("second", "desk"), stays("use", "office"), *more]
    stated = [
        *at("first", 9),
        *at("second", 10),
        *at("use", 11),
        takes("walk", "PT15M"),
        complete(None, None),
        lies_at("bags", "desk"),
        hands_over("first", "bags"),
        hands_over("second", "bags"),
        requires_object("use", "bags"),
        every_use("bags"),
        every_transfer("bags"),
        *facts,
    ]
    ways = [way_between("walk", "desk", "office")]
    return trip(
        ["alex", "sam"], ["desk", "office"], options, stated, list(locks), ways, objects=["bags"]
    )


def hand_overs(found: Report) -> list[tuple[str | None, tuple[tuple[str, str], ...]]]:
    return [(step.option, step.handed) for step in found.itinerary if step.handed]


def test_an_object_is_handed_over_in_the_option_listed_first() -> None:
    """Alex is in both OPTIONs at the desk, and either can hand the bags over."""
    file = a_desk_with_two_hand_overs(
        lock("first", "alex"), lock("second", "alex"), lock("use", "alex")
    )
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert hand_overs(found) == [("first", (("bags", "alex"),))]


def test_the_fewest_hand_overs_come_before_the_option_listed_first() -> None:
    """Only Sam is at the desk at 9:00 am: Alex is at the office then. Sam could take the
    bags there and pass them to Alex at 10:00 am. That is two hand-overs, and Alex taking
    them at 10:00 am is one, though the first OPTION is listed first."""
    file = a_desk_with_two_hand_overs(
        lock("first", "sam"),
        lock("call", "alex"),
        lock("second", "alex", "sam"),
        lock("use", "alex"),
        facts=at("call", 9),
        more=[stays("call", "office")],
    )
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert hand_overs(found) == [("second", (("bags", "alex"),))]


def test_the_hand_overs_listed_first_win_whichever_order_of_the_steps_is_tried_first() -> None:
    """The bags lie on a desk. At 10:00 am Sam is at one OPTION there that hands them over,
    and Alex at another that requires them. Sam is at a second hand-over there at 10:30 am,
    and needs the bags at the office at 11:00 am. With Sam's OPTION first, Sam has to leave
    the bags for Alex and take them at 10:30 am. With Alex's first, Sam takes them at
    10:00 am, in the OPTION listed first. That plan is shown, though the search comes to the
    other order of the steps first."""
    options = [
        stays("sam-first", "desk"),
        stays("alex-check", "desk"),
        stays("sam-use", "office"),
        stays("sam-second", "desk"),
    ]
    facts = [
        *at("sam-first", 10, length="PT5M"),
        *at("alex-check", 10, length="PT5M"),
        *at("sam-second", 10, 30, "PT5M"),
        *at("sam-use", 11),
        takes("walk", "PT15M"),
        complete(None, None),
        lies_at("bags", "desk"),
        hands_over("sam-first", "bags"),
        hands_over("sam-second", "bags"),
        requires_object("alex-check", "bags"),
        requires_object("sam-use", "bags"),
        every_use("bags"),
        every_transfer("bags"),
    ]
    locks = [
        lock("sam-first", "sam"),
        lock("alex-check", "alex"),
        lock("sam-second", "sam"),
        lock("sam-use", "sam"),
    ]
    ways = [way_between("walk", "desk", "office")]
    file = trip(["alex", "sam"], ["desk", "office"], options, facts, locks, ways, objects=["bags"])
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert [step.option for step in found.itinerary[:2]] == ["alex-check", "sam-first"]
    assert hand_overs(found) == [("sam-first", (("bags", "sam"),))]


def test_nothing_in_a_plan_with_a_hand_over_is_needless() -> None:
    """Jo has the bags and is LOCKed into coffee. Alex comes along to take them, though no
    LOCK names Alex there. Take Alex out, and nothing is handed over to Alex either: then
    the flight has no bags."""
    options = [stays("coffee", "cafe"), stays("flight", "cafe")]
    facts = [
        *at("coffee", 10),
        *at("flight", 12),
        has_object("jo", "bags"),
        hands_over("coffee", "bags"),
        requires_object("flight", "bags"),
        every_use("bags"),
        every_transfer("bags"),
    ]
    locks = [lock("coffee", "jo"), lock("flight", "alex")]
    file = trip(["alex", "jo"], ["cafe"], options, facts, locks, objects=["bags"])
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert found.itinerary[0].persons == ("alex", "jo")
    assert found.itinerary[0].handed == (("bags", "alex"),)
    assert reference.needless(file, worst_case(file), found.itinerary) == []


def test_the_upper_bound_brings_only_the_objects_that_are_asked_for() -> None:
    """It says whether another transfer of some OBJECTs can be enough at all. With none,
    the two desks have no plan. With the permit brought, they have one."""
    file = two_desks()
    assert not itineraries(file, no_better_than(file, ()))
    assert itineraries(file, no_better_than(file, [Unknown("another transfer", about="permit")]))


def test_a_case_that_is_not_settled_is_left_out_where_another_is_settled() -> None:
    """Deep-dish pizza is a must for Alex. The one dinner that delivers it requires the bags,
    and they lie at the hotel. Another OPTION for the WANT would be enough, and so might
    another transfer of the bags. Each is one condition that asks for something new. The
    report names the one that is sure to be enough."""
    options = [stays("dinner", "restaurant")]
    facts = [
        *at("dinner", 19),
        satisfies("dinner", "deep-dish"),
        lies_at("bags", "hotel"),
        requires_object("dinner", "bags"),
    ]
    file = trip(
        ["alex"],
        ["restaurant", "hotel"],
        options,
        facts,
        [],
        wants=[must("deep-dish", "alex")],
        objects=["bags"],
    )
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    assert asked(found) == [(Unknown("another option", want="deep-dish", person="alex"),)]
    assert "The trip works if" in report.as_text(file, found)
    for unknown in (
        Unknown("another option", want="deep-dish", person="alex"),
        Unknown("another transfer", about="bags"),
    ):
        assert itineraries(file, with_these_at_best(file, [unknown]))


def a_lunch(*more: Document) -> File:
    """Alex is LOCKed into lunch in the park, and the FILE lists the bags."""
    return trip(
        ["alex"], ["park", "hotel"], [stays("lunch", "park")], [*at("lunch", 12), *more],
        [lock("lunch", "alex")], objects=["bags"],
    )  # fmt: skip


def test_a_writer_who_lists_an_object_has_more_to_state() -> None:
    """Once the FILE lists the bags and says nothing more, lunch might require them, and
    nobody knows where they are. Each of three FACTs would be enough."""
    found = checked(a_lunch())
    assert found.answer is Answer.UNDETERMINED
    assert asked(found) == [
        (Unknown("does not require", "lunch", about="bags"),),
        (Unknown("starts with", person="alex", about="bags"),),
        (Unknown("starts at", place="park", about="bags"),),
    ]
    words = report.as_text(a_lunch(), found)
    assert "  1. lunch does not require bags." in words
    assert "  2. alex has bags when the TRIP starts." in words
    assert "  3. park has bags when the TRIP starts." in words


def test_two_facts_settle_an_object_for_every_option() -> None:
    found = checked(a_lunch(every_use("bags"), every_transfer("bags")))
    assert found.answer is Answer.FEASIBLE
    assert found.objects == ()
    # The plan relies on the FACT that says lunch does not require the bags.
    assert "every-use-of-bags" in found.relies_on
    assert "every-transfer-of-bags" not in found.relies_on


def test_where_an_object_starts_stays_unknown_under_both_complete_sets() -> None:
    file = a_lunch(requires_object("lunch", "bags"), every_use("bags"), every_transfer("bags"))
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    assert asked(found) == [
        (Unknown("starts with", person="alex", about="bags"),),
        (Unknown("starts at", place="park", about="bags"),),
    ]
    assert report.as_json(file, found)["missing"] == [
        [{"what": "starts with", "person": "alex", "object": "bags"}],
        [{"what": "starts at", "object": "bags", "place": "park"}],
    ]


def test_an_object_that_starts_in_the_wrong_place_makes_the_trip_infeasible() -> None:
    file = a_lunch(
        requires_object("lunch", "bags"),
        lies_at("bags", "hotel"),
        every_use("bags"),
        every_transfer("bags"),
    )
    found = checked(file)
    assert found.answer is Answer.INFEASIBLE
    assert found.conflict == (
        "lunch-requires-bags",
        "bags-start",
        "every-transfer-of-bags",
        "lock-lunch",
    )
    words = report.as_text(file, found)
    assert "  bags-start: hotel has bags when the TRIP starts" in words
    assert "  lunch-requires-bags: lunch requires bags" in words
    assert (
        "  every-transfer-of-bags: nothing hands over or keeps bags, in this FILE or outside it"
    ) in words


def test_hands_over_is_asked_only_where_does_not_keep_is_not_enough() -> None:
    """Alex has the bags at lunch and needs them at the hotel later. Nobody said what lunch
    does with them. It is enough that lunch does not keep them. That it hands them over is
    enough too, and the report leaves that out: the first is true of more FILEs."""
    options = [stays("lunch", "park"), stays("check-in", "hotel")]
    facts = [
        *at("lunch", 12),
        *at("check-in", 14),
        takes("walk", "PT15M"),
        has_object("alex", "bags"),
        requires_object("check-in", "bags"),
        every_use("bags"),
    ]
    locks = [lock("lunch", "alex"), lock("check-in", "alex")]
    ways = [way_between("walk", "park", "hotel")]
    file = trip(["alex"], ["park", "hotel"], options, facts, locks, ways, objects=["bags"])
    found = checked(file)
    assert asked(found) == [(Unknown("does not keep", "lunch", about="bags"),)]
    for what in ("does not keep", "hands over"):
        world = with_these_at_best(file, [Unknown(what, "lunch", about="bags")])
        assert itineraries(file, world)
    assert not itineraries(
        file, with_these_at_best(file, [Unknown("keeps", "lunch", about="bags")])
    )
    # "Does not keep" is true of two FACTs that a FILE can state, and each makes the TRIP work.
    for does, answer in (
        ("nothing", Answer.FEASIBLE),
        ("hands_over", Answer.FEASIBLE),
        ("keeps", Answer.UNDETERMINED),
    ):
        stated = replace(file, facts=(*file.facts, WithObject("said", "lunch", "bags", does)))
        assert checked(stated).answer is answer


def test_a_set_says_one_thing_about_what_an_option_does_and_where_an_object_starts() -> None:
    keeps_it = Unknown("keeps", "lunch", about="bags")
    hands_it = Unknown("hands over", "lunch", about="bags")
    with_alex = Unknown("starts with", person="alex", about="bags")
    in_the_park = Unknown("starts at", place="park", about="bags")
    assert one_way_each([keeps_it, with_alex])
    assert not one_way_each([keeps_it, hands_it])
    assert not one_way_each([with_alex, in_the_park])
    with pytest.raises(ValueError, match="no possible world has two"):
        with_these_at_best(a_lunch(), [with_alex, in_the_park])


def test_the_unknown_facts_about_objects_have_a_fixed_order() -> None:
    """For each OPTION: that it does not require the OBJECT, then the three things it can do
    with it. Where the OBJECT starts comes after the OPTIONs and the WAYs: with each PERSON,
    then at each PLACE. Another transfer comes last."""
    file = a_lunch()
    about = [(each.what, each.option, each.person, each.place) for each in unknowns(file)]
    about = [each for each in about if each[0] != "other ways"]
    assert about == [
        ("does not require", "lunch", None, None),
        ("keeps", "lunch", None, None),
        ("does not keep", "lunch", None, None),
        ("hands over", "lunch", None, None),
        ("starts with", None, "alex", None),
        ("starts at", None, None, "park"),
        ("starts at", None, None, "hotel"),
        ("another transfer", None, None, None),
    ]
    # A FACT settles its own, and a COMPLETE set settles a whole kind.
    settled_file = a_lunch(has_object("alex", "bags"), every_transfer("bags"))
    left = [each.what for each in unknowns(settled_file) if each.what != "other ways"]
    assert left == ["does not require"]
    # Nothing is asked about an OBJECT that no OPTION requires or might.
    unused = a_lunch(every_use("bags"))
    assert [each.what for each in unknowns(unused) if each.what != "other ways"] == []


def test_listing_an_object_that_nothing_requires_changes_no_answer() -> None:
    """The solver's model has no OBJECTs, and it still checks such a FILE: nothing turns on
    where the OBJECT is."""
    rng = Random(404)
    seen: set[Answer] = set()
    for _ in range(60):
        plain = random_trip(rng, leave_out=0.15, with_ways=0.5)
        facts = (
            *plain.facts,
            CompleteRequiresObject("every-use-of-bags", "bags"),
            ObjectStarts("bags-start", "bags", person=plain.persons[0].id),
        )
        listed = replace(plain, objects=(Object("bags", "bags"),), facts=facts)
        assert not listed.objects_asked_for()
        before, after = answers.check(plain), compiler.check(listed)
        seen.add(before.answer)
        assert (after.answer, after.itinerary, after.missing) == (
            before.answer,
            before.itinerary,
            before.missing,
        )
        assert after.conflict == before.conflict
        assert after.objects == ()
    assert seen == set(Answer)


def test_the_answer_comes_first_for_a_file_with_objects() -> None:
    file = two_desks()
    series = list(compiler.reports(file))
    assert series == [Answer.UNDETERMINED, answers.check(file)]


# Evidence: FEASIBLE.


def relied_on(found: Report) -> list[str]:
    """The FACTs about OBJECTs that a plan relies on."""
    about = ("passport", "use-of", "transfer-of")
    return [record for record in found.relies_on if any(word in record for word in about)]


def locked_desk(*facts: Document, into: Sequence[str] = ("first", "second", "third")) -> File:
    file = a_desk(*facts, persons=("alex",))
    locks = tuple(reference_lock(option) for option in into)
    return replace(file, decisions=locks)


def reference_lock(option: str) -> answers.Lock:
    return answers.Lock(f"lock-{option}", option, ("alex",))


def test_a_plan_relies_on_what_says_where_the_object_is_while_it_still_needs_it() -> None:
    """Alex has the passport through three appointments, and the second requires it. The
    plan relies on where it starts, and on what says that the first appointment leaves it
    alone: the COMPLETE set of transfers. It relies on a FACT about each requirement."""
    file = locked_desk(
        has_object("alex", "passport"),
        requires_object("first", "passport", False),
        requires_object("second", "passport"),
        requires_object("third", "passport", False),
        every_transfer("passport"),
    )
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert relied_on(found) == [
        "passport-start",
        "first-requires-passport",
        "second-requires-passport",
        "third-requires-passport",
        "every-transfer-of-passport",
    ]


def test_a_plan_relies_on_the_fact_about_what_an_option_does_where_the_file_states_one() -> None:
    file = locked_desk(
        has_object("alex", "passport"),
        does_with("first", "passport", "nothing"),
        requires_object("second", "passport"),
        every_use("passport"),
        every_transfer("passport"),
    )
    found = checked(file)
    assert relied_on(found) == [
        "passport-start",
        "first-with-passport",
        "second-requires-passport",
        "every-use-of-passport",
    ]


def test_a_plan_relies_on_nothing_about_an_option_after_which_it_needs_the_object_no_more() -> None:
    """The second appointment is the last one that requires the passport. What it does with
    the passport, and what the third one does, changes nothing. So the plan holds with the
    transfers left open, and it says so by relying on nothing there."""
    file = locked_desk(
        has_object("alex", "passport"),
        does_with("first", "passport", "nothing"),
        requires_object("second", "passport"),
        every_use("passport"),
    )
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert relied_on(found) == [
        "passport-start",
        "first-with-passport",
        "second-requires-passport",
        "every-use-of-passport",
    ]
    # The report still says where the passport might be after each of them.
    either = (Where(person="alex"), Where(place="desk"))
    assert found.objects[0].stays == (
        Stay((Where(person="alex"),)),
        Stay(either, "second", "might be kept"),
        Stay((*either, Where(place="office")), "third", "might be kept"),
    )


def test_a_plan_relies_on_no_fact_about_an_object_that_it_does_not_need() -> None:
    """The plan has the first two appointments. The FACTs about the third, which stays out,
    are not among those it relies on. Neither is the FACT about what the second one does:
    after it, the plan needs the passport no more."""
    file = locked_desk(
        has_object("alex", "passport"),
        does_with("first", "passport", "nothing"),
        requires_object("second", "passport"),
        does_with("second", "passport", "nothing"),
        requires_object("third", "passport"),
        keeps("third", "passport"),
        every_use("passport"),
        every_transfer("passport"),
        into=("first", "second"),
    )
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert relied_on(found) == [
        "passport-start",
        "first-with-passport",
        "second-requires-passport",
        "every-use-of-passport",
    ]


def test_a_plan_relies_on_the_facts_about_a_keep_and_a_hand_over_it_goes_through() -> None:
    file = locked_desk(
        has_object("alex", "passport"),
        keeps("first", "passport"),
        hands_over("second", "passport"),
        requires_object("third", "passport"),
        every_use("passport"),
        every_transfer("passport"),
    )
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert relied_on(found) == [
        "passport-start",
        "first-with-passport",
        "second-with-passport",
        "third-requires-passport",
        "every-use-of-passport",
    ]
    assert report.as_json(file, found)["objects"] == [
        {
            "object": "passport",
            "path": [
                {"where": [{"person": "alex"}], "since": None, "how": None},
                {"where": [{"place": "desk"}], "since": "first", "how": "kept"},
                {"where": [{"person": "alex"}], "since": "second", "how": "handed over"},
            ],
            "required_by": [{"option": "third", "stated": True, "where": [{"person": "alex"}]}],
        }
    ]
    words = report.as_text(file, found)
    assert (
        "  passport: with alex when the TRIP starts; at desk from 9:00 am (kept by first);"
        " with alex from 10:00 am (handed over in second)"
    ) in words
    assert "  first-with-passport: first keeps passport" in words
    assert "  second-with-passport: second hands over passport" in words
    assert "  third-requires-passport: third requires passport" in words
    assert "of the OPTIONs in this FILE, only third requires passport" in words


def test_a_plan_says_where_the_file_leaves_a_requirement_open() -> None:
    """Nobody said whether the first appointment requires the passport. Alex has it there,
    so the plan holds if it does."""
    file = locked_desk(has_object("alex", "passport"), into=("first",))
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert found.objects[0].uses == (Use("first", False, (Where(person="alex"),)),)
    assert relied_on(found) == ["passport-start"]
    words = report.as_text(file, found)
    silent = "The FILE does not say whether first requires passport"
    assert f"    {silent}. At its start: with alex, so the plan holds if it does." in words


def test_the_report_puts_each_fact_about_an_object_in_words() -> None:
    file = locked_desk(
        lies_at("passport", "desk"),
        requires_object("first", "passport"),
        requires_object("second", "passport", False),
        does_with("first", "passport", "nothing"),
        every_transfer("passport"),
        into=("first", "second"),
    )
    words = report.as_text(file, checked(file))
    for line in (
        "  passport-start: desk has passport when the TRIP starts",
        "  first-requires-passport: first requires passport",
        "  second-requires-passport: second does not require passport",
    ):
        assert line in words
    carried = locked_desk(
        has_object("alex", "passport"),
        does_with("first", "passport", "nothing"),
        requires_object("second", "passport"),
        every_use("passport"),
    )
    words = report.as_text(carried, checked(carried))
    assert "  passport-start: alex has passport when the TRIP starts" in words
    assert "  first-with-passport: first leaves passport alone" in words
    whole = locked_desk(
        has_object("alex", "passport"),
        keeps("first", "passport"),
        hands_over("second", "passport"),
        requires_object("third", "passport"),
        every_use("passport"),
        every_transfer("passport"),
    )
    kept = replace(whole, facts=tuple(f for f in whole.facts if f.id != "second-with-passport"))
    words = report.as_text(kept, checked(kept))
    assert "INFEASIBLE" in words
    said = "only first hands over or keeps passport, and nothing outside this FILE does"
    assert f"  every-transfer-of-passport: {said}" in words


# Checked on FILEs made at random.

THINGS = ["bags", "keys"]
PLACES = ["a", "b", "c"]


def with_objects(rng: Random, file: File, most: int = 2) -> File:
    """The same FILE with one or two OBJECTs and FACTs about them, chosen at random."""
    names = THINGS[: rng.choice([1, 1, 1, 2][: 2 * most])]
    facts: list[ObjectStarts | RequiresObject | WithObject] = []
    whole: list[CompleteRequiresObject | CompleteTransfers] = []
    people = [person.id for person in file.persons]
    for name in names:
        start = rng.choice(["with", "with", "at", "at", None])
        if start == "with":
            facts.append(ObjectStarts(f"{name}-start", name, person=rng.choice(people)))
        elif start == "at":
            facts.append(ObjectStarts(f"{name}-start", name, place=rng.choice(PLACES)))
        for option in file.options:
            needed = rng.choice([None, True, True, False])
            if needed is not None:
                facts.append(
                    RequiresObject(f"{option.id}-requires-{name}", option.id, name, needed)
                )
            does = rng.choice([None, None, "hands_over", "hands_over", "keeps", "nothing"])
            if does is not None:
                facts.append(WithObject(f"{option.id}-with-{name}", option.id, name, does))
        if rng.random() < 0.5:
            whole.append(CompleteRequiresObject(f"every-use-of-{name}", name))
        if rng.random() < 0.6:
            whole.append(CompleteTransfers(f"every-transfer-of-{name}", name))
    listed = tuple(Object(name, name) for name in names)
    return replace(file, objects=listed, facts=(*file.facts, *facts, *whole))


def a_trip_to_fetch(rng: Random, most: int = 2) -> File:
    """A FILE in which the bags often have to be fetched, carried or handed on.

    They mostly lie at one PLACE, and an OPTION at another PLACE mostly requires them. An
    OPTION where they lie mostly hands them over, and a stop on the way does something with
    them at random. A walk joins the two PLACEs. With ``most`` at two, some FILEs have keys
    too, which are fetched and required at the same OPTIONs.
    """
    persons = rng.choice([["alex"], ["alex", "sam"], ["alex", "sam"]])
    options = [stays("fetch", "a"), stays("stop", rng.choice(["a", "b"])), stays("use", "b")]
    rng.shuffle(options)
    facts = [
        *(whenever("fetch") if rng.random() < 0.5 else at("fetch", 9, 0, "PT15M")),
        *at("stop", 9, 30, "PT15M"),
        *at("use", 10, 15 * rng.randrange(3), "PT15M"),
        takes("walk", f"PT{15 * rng.randrange(1, 3)}M"),
    ]
    if rng.random() < 0.7:
        facts.append(complete(None, None))
    holder = has_object(rng.choice(persons), "bags")
    start = rng.choice([lies_at("bags", "a"), lies_at("bags", "a"), holder, holder, None])
    facts += [start] if start is not None else []
    if rng.random() < 0.9:
        facts.append(requires_object("use", "bags"))
    for option, choices in (
        ("fetch", ["hands_over", "hands_over", "hands_over", None, "keeps"]),
        ("stop", [None, None, "keeps", "hands_over", "nothing"]),
        ("use", [None, "nothing", "nothing"]),
    ):
        does = rng.choice(choices)
        if does is not None:
            facts.append(does_with(option, "bags", does))
    facts += [every_use("bags")] if rng.random() < 0.6 else []
    facts += [every_transfer("bags")] if rng.random() < 0.6 else []
    things = ["bags"]
    if most > 1 and rng.random() < 0.4:
        things.append("keys")
        whose = has_object(rng.choice(persons), "keys")
        facts.append(rng.choice([lies_at("keys", "a"), lies_at("keys", "a"), whose]))
        facts += [requires_object(rng.choice(["use", "use", "stop"]), "keys")]
        facts += [hands_over("fetch", "keys")] if rng.random() < 0.8 else []
        facts += [every_use("keys")] if rng.random() < 0.7 else []
        facts += [every_transfer("keys")] if rng.random() < 0.7 else []
    locks = [lock("use", *rng.sample(persons, rng.randrange(1, len(persons) + 1)))]
    if rng.random() < 0.5:
        locks.append(lock("stop", *rng.sample(persons, rng.randrange(1, len(persons) + 1))))
    if rng.random() < 0.2:
        locks.append(lock("fetch", rng.choice(persons)))
    ways = [way_between("walk", "a", "b")]
    return trip(persons, PLACES, options, facts, locks, ways, objects=things)


def a_trip_with_objects(rng: Random, most: int = 2, **how: float) -> File:
    """A FILE with OBJECTs: about half are trips to fetch the bags, and the rest anything."""
    if rng.random() < 0.45:
        return a_trip_to_fetch(rng, most)
    persons = rng.choice([["alex"], ["alex", "sam"], ["alex", "sam"]])
    count = rng.choice([2, 2, 3])
    return with_objects(rng, random_trip(rng, persons=persons, count=count, **how), most)


def a_world_with_objects(rng: Random, file: File) -> World:
    """One way the unknown FACTs could turn out, with those about OBJECTs too.

    No transfer from outside the FILE is in it: the travelers can leave one unused, so a
    world without one is always possible.
    """
    needs: set[tuple[str, str]] = set()
    does: dict[tuple[str, str], str] = {}
    starts: dict[str, Where] = {}
    people = [person.id for person in file.persons]
    for thing in file.objects:
        for option in file.options:
            required = file.requires_object(option.id, thing.id)
            if rng.random() < 0.5 if required is None else required:
                needs.add((option.id, thing.id))
            action = file.does_with(option.id, thing.id)
            action = action or rng.choice(["nothing", "keeps", "hands_over"])
            if action != "nothing":
                does[option.id, thing.id] = action
        start = file.object_starts(thing.id)
        if start is not None:
            starts[thing.id] = Where(start.person, start.place)
        else:
            guess = rng.choice([Where(person=rng.choice(people)), Where(place=rng.choice(PLACES))])
            if rng.random() < 0.8:
                starts[thing.id] = guess
    return replace(possible_world(rng, file), needs=frozenset(needs), does=does, starts=starts)


def any_plan(rng: Random, file: File, world: World) -> Itinerary:
    """Some OPTIONs, PERSONs, WAYs, start times and hand-overs. Nothing comes from the search.

    The steps are listed with earlier starts first, and those that start at one instant in an
    order chosen at random.
    """
    from tests.test_cross_check import any_choice

    steps = list(any_choice(rng, file, world))
    rng.shuffle(steps)
    steps.sort(key=lambda each: each.start)
    listed: list[Step] = []
    for each in steps:
        handed: list[tuple[str, str]] = []
        for thing in file.objects:
            can = each.option is not None and world.does.get((each.option, thing.id))
            if can == "hands_over" and rng.random() < 0.6:
                handed.append((thing.id, rng.choice(each.persons)))
        listed.append(replace(each, handed=tuple(handed)))
    return tuple(listed)


def test_the_best_and_worst_cases_settle_the_answer_with_objects() -> None:
    """What works in the worst case works in every possible world. Where something works in
    a possible world, the search finds something there, and the TRIP is not INFEASIBLE."""
    rng = Random(1414)
    seen: set[Answer] = set()
    found_by_chance = with_hand_overs = 0
    for number in range(220):
        with_ways = 0.8 if number % 2 else 0
        file = a_trip_with_objects(rng, leave_out=0.15, with_complete=0.3, with_ways=with_ways)
        found = answers.check(file)
        seen.add(found.answer)
        always = itineraries(file, worst_case(file))
        assert bool(always) == (found.answer is Answer.FEASIBLE)
        with_hand_overs += any(step.handed for plan in always for step in plan)
        for _ in range(6):
            world = a_world_with_objects(rng, file)
            for plan in always:
                assert broken(file, world, in_world(world, plan)) == []
            by_chance = [any_plan(rng, file, world) for _ in range(14)]
            by_chance = [
                each for each in by_chance if not broken(file, world, in_world(world, each))
            ]
            found_by_chance += len(by_chance)
            searched = itineraries(file, world)
            if by_chance:
                assert searched
            if searched or by_chance:
                assert found.answer is not Answer.INFEASIBLE
    assert seen == set(Answer)
    assert found_by_chance > 200
    assert with_hand_overs > 5


type Chain = tuple[list[tuple[int, int, int]], dict[int, tuple[tuple[str, str], ...]], object]


def every_chain(
    file: File,
    world: World,
    who: tuple[tuple[str, ...], ...],
    orders: tuple[tuple[int, ...], ...],
    everything: bool,
) -> list[Chain]:
    """Every order of the OPTIONs of a plan with every choice of hand-overs. Nothing is skipped.

    It stands in for the search's own way of choosing them. Every order is given, also one
    that a PERSON's own order rules out. In each OPTION that hands an OBJECT over in this
    world, the OBJECT goes to anybody who takes part or to nobody, also where it is not at
    hand. With ``everything``, all the OPTIONs that happen are ordered and every OBJECT is
    handed about. Without it, they are the OPTIONs and OBJECTs that the rules say matter, so
    that the times come out as the rules say.
    """
    options = file.options
    people = [person.id for person in file.persons]
    happening = [index for index, persons in enumerate(who) if persons]
    things = [thing.id for thing in file.objects if thing.id not in world.brought]
    followed = [
        thing
        for thing in things
        if any((options[index].id, thing) in world.needs for index in happening)
    ]
    matter = [
        index
        for index in happening
        if any(
            (options[index].id, thing) in world.needs or (options[index].id, thing) in world.does
            for thing in followed
        )
    ]
    if everything:
        followed, matter = things, happening
    if not followed:
        return [([], {}, (0, ()))]
    chains: list[Chain] = []
    for order in permutations(matter):
        gaps = [(before, after, 0) for before, after in pairwise(order)]
        slots = [
            (index, thing)
            for index in order
            for thing in followed
            if world.does.get((options[index].id, thing)) in ("hands_over", "any")
        ]
        for chosen in product(*([None, *who[index]] for index, _ in slots)):
            handed: dict[int, tuple[tuple[str, str], ...]] = {}
            ranked: dict[str, list[tuple[int, int]]] = {thing: [] for thing in followed}
            for (index, thing), person in zip(slots, chosen, strict=True):
                if person is not None:
                    handed[index] = (*handed.get(index, ()), (thing, person))
                    ranked[thing].append((index, people.index(person)))
            count = sum(len(each) for each in ranked.values())
            chains.append(
                (gaps, handed, (count, tuple(tuple(ranked[thing]) for thing in followed)))
            )
    return chains


def those_that_matter(
    file: File, world: World, who: tuple[tuple[str, ...], ...], orders: tuple[tuple[int, ...], ...]
) -> list[Chain]:
    return every_chain(file, world, who, orders, everything=False)


def all_of_them(
    file: File, world: World, who: tuple[tuple[str, ...], ...], orders: tuple[tuple[int, ...], ...]
) -> list[Chain]:
    return every_chain(file, world, who, orders, everything=True)


def worlds_to_try(rng: Random, file: File) -> Iterator[World]:
    """The worst case, the best case, an upper bound, a possible world, and some FACTs at best."""
    yield worst_case(file)
    yield best_case(file)
    yield no_better_than(file, ())
    yield a_world_with_objects(rng, file)
    facts = [each for each in unknowns(file) if each.what != "other ways"]
    some = [each for each in facts if rng.random() < 0.3]
    while not one_way_each(some):
        some.pop(rng.randrange(len(some)))
    yield with_these_at_best(file, some)


def test_the_search_shows_the_plan_that_a_search_that_skips_nothing_shows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The search orders only the OPTIONs that matter to an OBJECT, takes each OBJECT through
    them by itself, and keeps one choice of hand-overs for each order. Here every order and
    every choice of hand-overs is timed and checked, and the rule picks among all of them.
    The ITINERARIES are the same, in the same order."""
    rng = Random(2024)
    its_own = reference._chains  # pyright: ignore[reportPrivateUsage]
    compared = with_hand_overs = with_two = 0
    for _ in range(150):
        file = a_trip_with_objects(rng, leave_out=0.1, with_ways=0.6, with_complete=0.3)
        for world in worlds_to_try(rng, file):
            monkeypatch.setattr(reference, "_chains", its_own)
            shown = itineraries(file, world)
            monkeypatch.setattr(reference, "_chains", those_that_matter)
            assert itineraries(file, world) == shown
            compared += bool(shown)
            with_hand_overs += any(step.handed for plan in shown for step in plan)
            with_two += any(sum(len(step.handed) for step in plan) > 1 for plan in shown)
    assert compared > 150
    assert with_hand_overs > 25
    assert with_two > 2


def test_ordering_only_the_options_that_matter_misses_no_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Here every OPTION that happens is put in every order, and every OBJECT is handed about
    in every way. Something works there exactly where the search finds something."""
    rng = Random(77)
    its_own = reference._chains  # pyright: ignore[reportPrivateUsage]
    works = fails = 0
    for _ in range(120):
        file = a_trip_with_objects(rng, leave_out=0.1, with_ways=0.6, with_complete=0.3)
        for world in worlds_to_try(rng, file):
            monkeypatch.setattr(reference, "_chains", its_own)
            found = bool(itineraries(file, world))
            monkeypatch.setattr(reference, "_chains", all_of_them)
            assert bool(itineraries(file, world)) == found
            works += found
            fails += not found
    assert works > 100 and fails > 100


def cannot_work(left: Remaining) -> bool:
    """Whether nothing works in any best case of what is left of a FILE, by trying everything."""
    return not best_cases_work(left)


def test_every_conflict_with_objects_is_enough_and_has_no_record_to_spare() -> None:
    """Checked by trying everything, in every best case of the FILE with records taken out.

    A conflict that turns on where an OBJECT is holds the COMPLETE set of its transfers. No
    conflict holds a FACT that an OPTION does not require an OBJECT, or a COMPLETE set of an
    OBJECT's requirements.
    """
    rng = Random(909)
    about_an_object = with_an_action = 0
    for _ in range(260):
        file = a_trip_with_objects(rng, leave_out=0.1, with_complete=0.3, with_ways=0.4)
        found = answers.check(file)
        if found.answer is not Answer.INFEASIBLE:
            continue
        records = [*(fact.id for fact in file.facts), *(each.id for each in file.decisions)]
        alone = Remaining(file)
        for record in records:
            if record not in found.conflict:
                alone = alone.without(record)
        assert cannot_work(alone)
        for record in found.conflict:
            assert not cannot_work(alone.without(record)), record
        kept = [fact for fact in file.facts if fact.id in found.conflict]
        assert not any(isinstance(fact, CompleteRequiresObject) for fact in kept)
        assert not any(isinstance(fact, RequiresObject) and not fact.needed for fact in kept)
        closed = {fact.object for fact in kept if isinstance(fact, CompleteTransfers)}
        turns_on = {
            fact.object
            for fact in kept
            if isinstance(fact, ObjectStarts | RequiresObject | WithObject)
        }
        assert turns_on <= closed
        about_an_object += bool(closed)
        with_an_action += any(isinstance(fact, WithObject) for fact in kept)
    assert about_an_object > 15
    assert with_an_action > 3


NEW = ("another option", "another transfer")


def smallest_sets(file: File) -> list[tuple[Unknown, ...]]:
    """The sets of unknown FACTs that a report names, found by trying each set.

    They ask for the fewest things that the FILE does not list, and among those they have
    the fewest FACTs. "Hands over" is left out where "does not keep" is enough in its place,
    and then a set that is not settled is left out where another is settled.
    """
    every_one = unknowns(file)
    facts = [unknown for unknown in every_one if unknown.what not in NEW]
    found = [unknown for unknown in every_one if unknown.what in NEW]
    for count in range(len(found) + 1):
        for size in range(len(facts) + 1):
            enough = [
                (*some, *others)
                for some in combinations(facts, size)
                for others in combinations(found, count)
                if one_way_each(some)
                and itineraries(file, with_these_at_best(file, (*some, *others)))
            ]
            if not enough or not count + size:
                continue

            def weaker(some: tuple[Unknown, ...], asked: Unknown) -> tuple[Unknown, ...]:
                return tuple(replace(u, what="does not keep") if u == asked else u for u in some)

            kept = [
                some
                for some in enough
                if not any(u.what == "hands over" and weaker(some, u) in enough for u in some)
            ]
            sure = [some for some in kept if all(u.what != "another transfer" for u in some)]
            return sure or kept
    return []


def test_the_sets_named_for_objects_are_all_the_smallest_that_are_enough() -> None:
    """Checked by trying every set of that size and of each smaller one."""
    rng = Random(3141)
    kinds: set[str] = set()
    compared = several = unsettled = 0
    for _ in range(170):
        file = a_trip_with_objects(rng, most=1, leave_out=0.08)
        found = answers.check(file)
        named_sets = asked(found)
        for named in named_sets:
            kinds.update(unknown.what for unknown in named)
            assert itineraries(file, with_these_at_best(file, named))
            for left_out in named:
                fewer = [unknown for unknown in named if unknown != left_out]
                assert not itineraries(file, with_these_at_best(file, fewer))
        if named_sets and len(named_sets[0]) <= 2 and len(unknowns(file)) <= 22:
            assert named_sets == smallest_sets(file)
            compared += 1
            several += len(named_sets) > 1
        for enough in found.missing:
            for needed in enough:
                if needed.unknown.what == "another transfer":
                    unsettled += 1
                    assert needed.at_hand_for
                else:
                    assert not needed.at_hand_for
    # That an OPTION keeps an OBJECT helps only where whoever has it cannot come along. The
    # story of the two appointments covers it.
    wanted = {"does not require", "does not keep", "hands over", "starts with"}
    assert wanted | {"starts at", "another transfer"} <= kinds
    assert compared > 40
    assert several > 10
    assert unsettled > 5


def test_fewer_requirements_are_never_harder_for_the_same_plan() -> None:
    """A plan that works where an OPTION requires an OBJECT works where it does not."""
    rng = Random(55)
    checked_plans = 0
    for _ in range(120):
        file = a_trip_with_objects(rng, leave_out=0.1, with_ways=0.5)
        world = a_world_with_objects(rng, file)
        for plan in itineraries(file, world):
            for pair in world.needs:
                easier = replace(world, needs=world.needs - {pair})
                assert broken_as_listed(file, easier, plan) == []
                checked_plans += 1
    assert checked_plans > 60


def test_the_compiler_gives_the_reference_checkers_report_for_objects() -> None:
    """The solver's model has no OBJECTs, so the COMPILER hands such a FILE over whole."""
    rng = Random(8)
    seen: set[Answer] = set()
    for _ in range(40):
        file = a_trip_with_objects(rng, leave_out=0.1, with_ways=0.5)
        found = answers.check(file)
        assert compiler.check(file) == found
        seen.add(found.answer)
    assert seen == set(Answer)


@pytest.mark.parametrize(
    "name", ["the-cloakroom-is-not-in-the-plan", "nobody-collects-them", "the-visit-runs-late"]
)
def test_each_conflict_about_the_bags_is_enough_and_has_no_record_to_spare(name: str) -> None:
    """The records of the conflict rule out every best case by themselves. With any one of
    them taken out as well, something works in some best case."""
    from agloe.file import read

    file = read(EXAMPLES / "the-bags" / f"{name}.json")
    conflict = answers.check(file).conflict
    alone = Remaining(file)
    for record in [*(fact.id for fact in file.facts), *(each.id for each in file.decisions)]:
        if record not in conflict:
            alone = alone.without(record)
    assert cannot_work(alone)
    for record in conflict:
        assert not cannot_work(alone.without(record)), record


def test_the_examples_about_the_bags_say_what_the_rules_page_says() -> None:
    """Each row of the rules page, by its answer and by what its report names."""
    from agloe.file import read

    def result(name: str) -> Report:
        return answers.check(read(EXAMPLES / "the-bags" / f"{name}.json"))

    def named(name: str) -> list[tuple[tuple[str, str | None, str | None], ...]]:
        return [
            tuple((u.what, u.option or u.person or u.place, u.about) for u in some)
            for some in asked(result(name))
        ]

    assert "everything-that-moves-the-bags" in result("they-carry-them").relies_on
    assert named("nobody-said-what-the-museum-does") == [
        (("does not keep", "museum-visit", "bags"),)
    ]
    kept = result("the-museum-keeps-them")
    assert [step.handed for step in kept.itinerary if step.option == "pick-up"] == [
        (("bags", "alex"),)
    ]
    assert len(result("the-cloakroom-is-not-in-the-plan").conflict) == 9
    collected = result("they-collect-them")
    assert collected.objects[0].stays[-1] == Stay(
        (Where(person="alex"),), "collect-bags", "handed over"
    )
    assert result("jo-hands-them-over").itinerary[1].handed == (("bags", "alex"),)
    assert named("nobody-said-they-can") == [(("hands over", "coffee", "bags"),)]
    assert result("nobody-collects-them").conflict == (
        "where-the-bags-start",
        "flight-needs-the-bags",
        "everything-that-moves-the-bags",
        "lock-flight",
    )
    might = result("somebody-might")
    assert named("somebody-might") == [(("another transfer", None, "bags"),)]
    assert might.missing[0][0].at_hand_for == (("flight", True),)
    late = result("the-visit-runs-late").conflict
    assert len(late) == 13
    assert "everything-that-moves-the-bags" in late and "hotel-releases-the-bags" not in late
    assert named("nobody-said-where-they-are") == [
        (("starts with", "alex", "bags"),),
        (("starts with", "sam", "bags"),),
        (("starts at", "hotel", "bags"),),
        (("starts at", "ohare", "bags"),),
    ]
    assert named("depends-on-the-museum") == [(("does not require", "museum-visit", "bags"),)]
    words = json.dumps(report.as_json(read(EXAMPLES / "the-bags" / "somebody-might.json"), might))
    assert '"settled": false' in words
