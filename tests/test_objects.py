"""OBJECTs: where a thing is, and which OPTIONs require it, hand it over, keep it or carry it."""

import json
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import replace
from itertools import combinations, pairwise, permutations, product
from random import Random
from typing import Any

import pytest
from ortools.sat.python import cp_model

from agloe import answers, compiler, reference, report
from agloe.answers import Answer, Carried, Report, Stay, Use
from agloe.file import (
    Capability,
    CompleteRequires,
    CompleteRequiresObject,
    CompleteTransfers,
    File,
    FileError,
    Has,
    Object,
    ObjectStarts,
    RefusesObject,
    Requires,
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
    just_before,
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
    budget,
    can,
    cannot,
    cap,
    carries,
    complete,
    cutoff,
    does_with,
    ends_at,
    every,
    every_requirement,
    every_right,
    every_transfer,
    every_use,
    hands_over,
    has_object,
    keeps,
    lasts,
    lasts_between,
    lets_in,
    lies_at,
    lock,
    moves,
    must,
    must_not,
    needs_no_right,
    needs_right,
    offer,
    refuses_object,
    requires,
    requires_object,
    satisfies,
    seconds,
    starts_at,
    starts_from,
    stays,
    takes,
    trip,
    trip_ends,
    trip_starts,
    way,
    way_between,
)
from tests.stories import at as moment
from tests.test_capabilities import with_capabilities
from tests.test_cross_check import possible_world, random_trip


def at(option: str, hour: int, minute: int = 0, length: str = "PT30M") -> list[Document]:
    """An OPTION that starts at a fixed time, takes this long and has no access cutoff."""
    return [starts_at(option, hour, minute), lasts(option, length), cutoff(option, "PT0S")]


def whenever(option: str, length: str = "PT5M") -> list[Document]:
    """An OPTION that can start at any time, takes this long and has no access cutoff."""
    return [any_time(option), lasts(option, length), cutoff(option, "PT0S")]


def checked(file: File) -> Report:
    """The reference checker's Report, once the solver's own search has given the same one."""
    found = answers.check(file)
    assert answers.check(file, compiler.shown, compiler.works, compiler.can_work) == found
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


def test_a_file_lists_objects_and_states_six_facts_about_them() -> None:
    file = load(
        a_document(
            has_object("alex", "passport"),
            requires_object("check-in", "passport"),
            refuses_object("check-in", "passport"),
            keeps("check-in", "passport"),
            every_use("passport"),
            every_transfer("passport"),
        )
    )
    assert file.objects == (Object("passport", "the passport"),)
    assert file.facts == (
        ObjectStarts("passport-start", "passport", person="alex"),
        RequiresObject("check-in-requires-passport", "check-in", "passport", True),
        RefusesObject("check-in-refuses-passport", "check-in", "passport", True),
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
    assert file.refuses_object("check-in", "passport") is None
    assert file.does_with("check-in", "passport") is None


def test_a_fact_states_whether_an_option_requires_an_object() -> None:
    for needed in (True, False):
        file = load(a_document(requires_object("check-in", "passport", needed)))
        assert file.requires_object("check-in", "passport") is needed
        # It says nothing about whether the OPTION refuses the OBJECT.
        assert file.refuses_object("check-in", "passport") is None


def test_a_fact_states_whether_an_option_refuses_an_object() -> None:
    for refused in (True, False):
        stated = refuses_object("check-in", "passport", refused)
        file = load(a_document(stated))
        assert file.refuses_object("check-in", "passport") is refused
        assert file.object_refusal("check-in", "passport") == RefusesObject(
            "check-in-refuses-passport", "check-in", "passport", refused
        )
        # It says nothing about whether the OPTION requires the OBJECT.
        assert file.requires_object("check-in", "passport") is None
    assert load(a_document()).object_refusal("check-in", "passport") is None


@pytest.mark.parametrize("does", ["hands_over", "keeps", "carries", "nothing"])
def test_a_fact_states_what_an_option_does_with_an_object(does: str) -> None:
    file = load(a_document(does_with("check-in", "passport", does)))
    assert file.does_with("check-in", "passport") == does


def test_a_complete_set_settles_what_an_option_with_no_fact_requires_and_does() -> None:
    file = load(a_document(every_use("passport")))
    assert file.requires_object("check-in", "passport") is False
    assert file.refuses_object("check-in", "passport") is False
    assert file.does_with("check-in", "passport") is None
    file = load(a_document(every_transfer("passport")))
    assert file.requires_object("check-in", "passport") is None
    assert file.refuses_object("check-in", "passport") is None
    assert file.does_with("check-in", "passport") == "nothing"
    # Nothing outside the FILE transfers the passport either. The set of requirements is
    # about the OPTIONs of the FILE only.
    assert file.does_with("another", "passport") == "nothing"
    whole = load(a_document(every_use("passport")))
    assert whole.requires_object("another", "passport") is None
    assert whole.refuses_object("another", "passport") is None


def test_a_complete_set_leaves_a_stated_requirement_and_a_stated_refusal_as_they_are() -> None:
    """The two are settled apart: an OPTION with a FACT that it requires the OBJECT and no
    FACT about refusing it does not refuse it."""
    file = load(a_document(every_use("passport"), requires_object("check-in", "passport")))
    assert file.requires_object("check-in", "passport") is True
    assert file.refuses_object("check-in", "passport") is False
    file = load(a_document(every_use("passport"), refuses_object("check-in", "passport")))
    assert file.requires_object("check-in", "passport") is False
    assert file.refuses_object("check-in", "passport") is True


def test_what_an_option_does_is_one_of_four_things_and_a_requirement_is_yes_or_no() -> None:
    assert "fits no known shape" in problems(a_document(does_with("check-in", "passport", "eats")))
    wrong = requires_object("check-in", "passport")
    wrong["requires"]["needed"] = "yes"
    assert "is not of type 'boolean'" in problems(a_document(wrong))
    wrong = refuses_object("check-in", "passport")
    wrong["refuses"]["refused"] = "yes"
    assert "is not of type 'boolean'" in problems(a_document(wrong))
    del wrong["refuses"]["refused"]
    assert "'refused' is a required property" in problems(a_document(wrong))


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
        refuses_object("check-in", "keys"),
        keeps("check-in", "keys"),
        carries("check-in", "keys"),
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
    assert "boarding is not an OPTION" in problems(
        a_document(refuses_object("boarding", "passport"))
    )


def test_a_file_states_each_fact_about_an_object_once() -> None:
    twice = [
        [has_object("alex", "passport"), {**lies_at("passport", "desk"), "id": "again"}],
        [
            requires_object("check-in", "passport"),
            {**requires_object("check-in", "passport", False), "id": "again"},
        ],
        [
            refuses_object("check-in", "passport"),
            {**refuses_object("check-in", "passport", False), "id": "again"},
        ],
        [keeps("check-in", "passport"), {**hands_over("check-in", "passport"), "id": "again"}],
        [carries("check-in", "passport"), {**keeps("check-in", "passport"), "id": "again"}],
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


def test_only_an_object_that_some_option_might_require_or_refuse_is_asked_for() -> None:
    silent = load(a_document())
    assert [thing.id for thing in silent.objects_asked_for()] == ["passport"]
    neither = [
        requires_object("check-in", "passport", False),
        refuses_object("check-in", "passport", False),
    ]
    for settled in ([every_use("passport")], neither):
        assert load(a_document(*settled)).objects_asked_for() == ()
    # One of the two FACTs leaves the other thing open.
    for one in neither:
        assert [thing.id for thing in load(a_document(one)).objects_asked_for()] == ["passport"]
    # An OBJECT that an OPTION refuses is asked for, though none requires it.
    refused = load(a_document(every_use("passport"), refuses_object("check-in", "passport")))
    assert [thing.id for thing in refused.objects_asked_for()] == ["passport"]


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
    carried: tuple[str, ...] = (),
) -> Step:
    start = seconds(hour, minute)
    end = start + 1800
    return Step(option, place, place, persons, start, end, handed=handed, carried=carried)


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


def refused(option: str, *persons: str) -> Broken:
    return Broken(Constraint.REFUSED, option, persons, object="passport")


def test_nobody_who_takes_part_has_an_object_that_the_option_refuses() -> None:
    file = a_desk(has_object("alex", "passport"), refuses_object("first", "passport"))
    world = settled(file)
    assert broken(file, world, (step("first", "desk", 9, "sam"),)) == []
    # The finding names who has it, and nobody else who takes part.
    both = (step("first", "desk", 9, "alex", "sam"),)
    assert broken(file, world, both) == [refused("first", "alex")]
    # An OPTION that does not refuse it lets Alex in.
    assert broken(file, world, (step("second", "desk", 10, "alex"),)) == []


def test_an_object_may_lie_where_an_option_that_refuses_it_starts() -> None:
    file = a_desk(lies_at("passport", "desk"), refuses_object("first", "passport"))
    assert broken(file, settled(file), (step("first", "desk", 9, "alex", "sam"),)) == []


def test_an_object_is_not_handed_over_in_an_option_that_refuses_it() -> None:
    """The passport lies on the desk, and the appointment hands it over and refuses it. So
    nobody takes it there."""
    file = a_desk(
        lies_at("passport", "desk"),
        hands_over("first", "passport"),
        refuses_object("first", "passport"),
    )
    world = settled(file)
    taken = (step("first", "desk", 9, "alex", handed=(("passport", "alex"),)),)
    assert broken(file, world, taken) == [refused("first", "alex")]
    assert whereabouts(file, world, taken)["passport"][1] == {Where(place="desk")}
    assert broken(file, world, (step("first", "desk", 9, "alex"),)) == []
    # A hand-over there of a passport that is not at hand breaks both CONSTRAINTs. So does
    # one in an OPTION that refuses the passport and does not hand it over.
    far = a_desk(
        lies_at("passport", "office"),
        hands_over("first", "passport"),
        refuses_object("first", "passport"),
    )
    both = [refused("first", "alex"), not_at_hand("first", "alex")]
    assert broken(far, settled(far), taken) == both
    plain = a_desk(lies_at("passport", "desk"), refuses_object("first", "passport"))
    assert broken(plain, settled(plain), taken) == both
    # The search finds no hand-over there either: an appointment that requires the passport
    # at the office cannot be reached with it.
    needed = replace(
        file,
        facts=(*file.facts, RequiresObject("third-requires-passport", "third", "passport", True)),
        decisions=(reference_lock("third"),),
    )
    assert checked(replace_silence(needed)).answer is Answer.INFEASIBLE
    allowed = replace(
        needed, facts=tuple(f for f in needed.facts if f.id != "first-refuses-passport")
    )
    assert checked(replace_silence(allowed)).answer is Answer.FEASIBLE


def test_an_option_can_require_an_object_and_refuse_it() -> None:
    """Then the passport lies on the desk, and nobody brings it in."""
    both = [requires_object("first", "passport"), refuses_object("first", "passport")]
    lying = a_desk(lies_at("passport", "desk"), *both)
    assert broken(lying, settled(lying), (step("first", "desk", 9, "alex"),)) == []
    carried = a_desk(has_object("alex", "passport"), *both)
    world = settled(carried)
    assert broken(carried, world, (step("first", "desk", 9, "alex"),)) == [refused("first", "alex")]
    without = (step("first", "desk", 9, "sam"),)
    assert broken(carried, world, without) == [not_at_hand("first", "sam")]


def test_an_option_that_keeps_an_object_and_refuses_it_checks_first() -> None:
    """The check comes before the keep. So the PERSON who has the passport is never let in."""
    file = a_desk(
        has_object("alex", "passport"),
        keeps("first", "passport"),
        refuses_object("first", "passport"),
    )
    plan = (step("first", "desk", 9, "alex"),)
    assert broken(file, settled(file), plan) == [refused("first", "alex")]
    # An OPTION that refuses the passport moves nothing: Alex still has it afterwards.
    assert whereabouts(file, settled(file), plan)["passport"] == (
        frozenset({Where(person="alex")}),
        frozenset({Where(person="alex")}),
    )
    # Where nobody said what the appointment does with it, that is no different.
    silent = a_desk(
        has_object("alex", "passport"), every_use("passport"), refuses_object("first", "passport")
    )
    assert worst_case(silent).does["first", "passport"] == "might_keep"
    assert whereabouts(silent, worst_case(silent), plan)["passport"][1] == {Where(person="alex")}


def test_an_option_that_keeps_an_object_clears_whoever_takes_part_for_one_that_refuses_it() -> None:
    """The first appointment keeps the passport, and the second refuses it."""
    file = a_desk(
        has_object("alex", "passport"),
        keeps("first", "passport"),
        refuses_object("second", "passport"),
    )
    world = settled(file)
    after = (step("first", "desk", 9, "alex"), step("second", "desk", 10, "alex", "sam"))
    assert broken(file, world, after) == []
    alone = (step("second", "desk", 10, "alex", "sam"),)
    assert broken(file, world, alone) == [refused("second", "alex")]
    # The search puts the first appointment in the plan, though no LOCK names it.
    locked = replace(replace_silence(file), decisions=(reference_lock("second"),))
    found = checked(locked)
    assert found.answer is Answer.FEASIBLE
    assert [(each.option, each.persons) for each in found.itinerary] == [
        ("first", ("alex",)),
        ("second", ("alex",)),
    ]
    assert found.objects[0].uses == (Use("second", True, (Where(place="desk"),), "refuses"),)
    words = report.as_text(locked, found)
    assert "    second refuses passport. Just before it starts: at desk." in words
    assert "  second-refuses-passport: second refuses passport" in words
    assert "none requires passport, and only second refuses passport" in words


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


def test_a_carry_is_in_an_option_once_and_not_beside_a_hand_over() -> None:
    file = a_desk(lies_at("passport", "desk"), carries("first", "passport"))
    world = settled(file)
    wrong: list[Itinerary] = [
        (step("first", "desk", 9, "alex", carried=("keys",)),),
        (step("first", "desk", 9, "alex", carried=("passport", "passport")),),
        (replace(walk("alex", "desk", "office", 9, 0), carried=("passport",)),),
        (step("first", "desk", 9, "alex", handed=(("passport", "alex"),), carried=("passport",)),),
    ]
    for plan in wrong:
        with pytest.raises(ValueError, match="carrie"):
            broken(file, world, plan)


def test_where_an_object_is_depends_on_no_duration_unless_it_is_carried() -> None:
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
    # At worst each OPTION requires the passport and refuses it, hands nothing over and might
    # keep it, and nobody knows where the passport is.
    assert worst.needs == everything
    assert worst.refuses == everything
    assert dict(worst.does) == dict.fromkeys(everything, "might_keep")
    assert not worst.starts and not worst.starts_anywhere and not worst.brought
    # At best no OPTION requires it or refuses it, and another transfer brings it wherever a
    # plan needs it.
    assert not best.needs and not best.refuses and not best.does
    assert best.brought == {"passport"}


def test_a_complete_set_of_transfers_leaves_the_start_to_pick() -> None:
    """Both sets are COMPLETE, and no FACT says where the passport starts. That is still
    unknown: at worst it is somewhere else, and at best wherever suits the plan."""
    file = a_desk(every_use("passport"), every_transfer("passport"))
    worst, best = worst_case(file), best_case(file)
    assert not worst.needs and not worst.refuses and not worst.does and not worst.starts
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
        *lets_in("passport", "first", "second", "third"),
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


def test_an_object_that_might_be_with_a_person_is_refused() -> None:
    """Nobody said what the first appointment does with the passport. Afterwards it is with
    Alex or on the desk, and the second appointment refuses it. So Alex stays out of that
    one."""
    file = a_desk(
        has_object("alex", "passport"),
        every_use("passport"),
        refuses_object("second", "passport"),
    )
    world = worst_case(file)
    plan = (step("first", "desk", 9, "alex"), step("second", "desk", 10, "alex", "sam"))
    assert broken(file, world, plan) == [refused("second", "alex")]
    assert broken(file, world, (plan[0], step("second", "desk", 10, "sam"))) == []


def test_where_nobody_knows_where_an_object_starts_the_worst_case_follows_every_place() -> None:
    """It might be with Alex, with Sam, at the desk, at the office or somewhere the FILE does
    not name, and a plan has to work wherever it is."""
    file = a_desk(
        every_use("passport"),
        every_transfer("passport"),
        keeps("first", "passport"),
        refuses_object("second", "passport"),
    )
    world = worst_case(file)
    anywhere = {
        Where(person="alex"),
        Where(person="sam"),
        Where(place="desk"),
        Where(place="office"),
        Where(),
    }
    # The first appointment keeps the passport, so Alex does not have it afterwards.
    plan = (step("first", "desk", 9, "alex"), step("second", "desk", 10, "alex"))
    assert broken(file, world, plan) == []
    assert whereabouts(file, world, plan)["passport"] == (
        anywhere,
        anywhere - {Where(person="alex")},
        anywhere - {Where(person="alex")},
    )
    # Sam was not there, and might have it still.
    with_sam = (plan[0], step("second", "desk", 10, "alex", "sam"))
    assert broken(file, world, with_sam) == [refused("second", "sam")]
    # An appointment that only might keep it clears nobody.
    unsaid = replace(file, facts=tuple(f for f in file.facts if f.id != "first-with-passport"))
    unsaid = replace(unsaid, facts=tuple(f for f in unsaid.facts if "transfer" not in f.id))
    assert worst_case(unsaid).does["first", "passport"] == "might_keep"
    assert broken(unsaid, worst_case(unsaid), plan) == [refused("second", "alex")]
    # It is at hand for nothing: it might be somewhere the FILE does not name. So nobody can
    # take it either.
    needed = a_desk(
        every_use("passport"),
        every_transfer("passport"),
        requires_object("first", "passport"),
        hands_over("second", "passport"),
    )
    everybody = (step("first", "desk", 9, "alex", "sam"),)
    assert broken(needed, worst_case(needed), everybody) == [not_at_hand("first", "alex", "sam")]
    taken = (step("second", "desk", 10, "alex", "sam", handed=(("passport", "sam"),)),)
    assert broken(needed, worst_case(needed), taken) == [not_at_hand("second", "sam")]


def test_at_best_another_transfer_takes_an_object_away_before_an_option_refuses_it() -> None:
    """Alex has the passport, and the first appointment refuses it. Where the FILE does not
    state every transfer, the best case asks nothing of the passport. Where it does, the
    best case checks the refusal."""
    file = a_desk(has_object("alex", "passport"), refuses_object("first", "passport"))
    plan = (step("first", "desk", 9, "alex"),)
    best = best_case(file)
    assert best.refuses == {("first", "passport")} and best.brought == {"passport"}
    assert broken(file, best, plan) == []
    assert whereabouts(file, best, plan) == {}
    whole = replace_silence(file)
    assert broken(whole, best_case(whole), plan) == [refused("first", "alex")]
    # At best an OPTION with no FACT about it does not refuse the passport, and at worst it
    # does.
    silent = a_desk(has_object("alex", "passport"), every_transfer("passport"))
    assert broken(silent, best_case(silent), plan) == []
    assert refused("first", "alex") in broken(silent, worst_case(silent), plan)
    one = with_these_at_best(silent, [Unknown("does not refuse", "first", about="passport")])
    assert ("first", "passport") not in one.refuses and ("second", "passport") in one.refuses


def test_an_object_that_might_be_in_two_places_can_be_handed_over() -> None:
    """After the first appointment the passport is with Alex or on the desk. The second one
    hands it over, with Alex in it: Sam has it afterwards, wherever it was."""
    file = a_desk(
        has_object("alex", "passport"),
        requires_object("first", "passport", False),
        requires_object("second", "passport", False),
        hands_over("second", "passport"),
        requires_object("third", "passport"),
        *lets_in("passport", "first", "second", "third"),
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

    The desks are a 15 minute walk apart, and the FILE lists every way. Neither desk refuses
    the permit.
    """
    options = [stays("desk-a", "north"), stays("desk-b", "south")]
    facts = [
        *at("desk-a", 10),
        *at("desk-b", 10),
        takes("walk", "PT15M"),
        complete(None, None),
        requires_object("desk-a", "permit"),
        requires_object("desk-b", "permit"),
        *lets_in("permit", "desk-a", "desk-b"),
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
    assert found.missing[0][0].at_hand_for == (
        ("desk-a", "requires", True, False),
        ("desk-b", "requires", True, False),
    )
    assert report.as_json(file, found)["missing"] == [
        [
            {
                "what": "another transfer",
                "object": "permit",
                "at_hand_for": [
                    {"option": "desk-a", "check": "requires", "stated": True, "covered": False},
                    {"option": "desk-b", "check": "requires", "stated": True, "covered": False},
                ],
                "settled": False,
            }
        ]
    ]
    words = report.as_text(file, found)
    assert (
        "The trip might work if another transfer puts permit at hand for desk-a and desk-b."
    ) in words
    assert "That is not settled. What the FILE lists does not do that for permit" in words
    assert "The trip works" not in words


def test_a_requirement_that_the_file_leaves_open_is_named_as_one_that_might_hold() -> None:
    """Nobody said whether desk-b requires the permit. At worst it does, so the plan needs
    the permit there too, and the report says: if it requires it."""
    file = two_desks()
    file = replace(file, facts=tuple(f for f in file.facts if f.id != "desk-b-requires-permit"))
    found = checked(replace(file, facts=(*file.facts, lies_at_fact("permit", "south"))))
    assert found.answer is Answer.UNDETERMINED
    assert asked(found) == [(Unknown("another transfer", about="permit"),)]
    # The permit lies where desk-b is. So what the FILE lists already puts it at hand there,
    # and another transfer has to leave it at hand there.
    assert found.missing[0][0].at_hand_for == (
        ("desk-a", "requires", True, False),
        ("desk-b", "requires", False, True),
    )
    words = report.as_text(file, found)
    assert (
        "The trip might work if another transfer puts permit at hand for desk-a, and leaves"
        " permit at hand for desk-b if it requires permit."
    ) in words


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
    for it before it asks for another transfer. A carry in the first appointment is enough
    too: it takes the passport from Alex, and leaves it on the desk when it is over."""
    file = two_appointments()
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    assert asked(found) == [
        (Unknown("keeps", "nine", about="passport"),),
        (Unknown("carries", "nine", about="passport"),),
    ]
    assert report.as_json(file, found)["missing"] == [
        [{"what": "keeps", "option": "nine", "object": "passport"}],
        [{"what": "carries", "option": "nine", "object": "passport"}],
    ]
    words = report.as_text(file, found)
    assert "  1. nine keeps passport.\n  2. nine can carry passport.\n" in words
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
    assert "    check requires passport. Just before it starts: with alex or at desk." in words
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
    """Once the FILE lists the bags and says nothing more, lunch might require them, it might
    refuse them, and nobody knows where they are. One FACT would be enough: the bags lie in
    the park. Then they are at hand for lunch, and nobody brings them in."""
    found = checked(a_lunch())
    assert found.answer is Answer.UNDETERMINED
    assert asked(found) == [(Unknown("starts at", place="park", about="bags"),)]
    assert "The trip works if the TRIP starts with bags at park." in report.as_text(
        a_lunch(), found
    )
    # Where a FACT says that lunch does not refuse the bags, each of three FACTs would be
    # enough.
    file = a_lunch(*lets_in("bags", "lunch"))
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    assert asked(found) == [
        (Unknown("does not require", "lunch", about="bags"),),
        (Unknown("starts with", person="alex", about="bags"),),
        (Unknown("starts at", place="park", about="bags"),),
    ]
    words = report.as_text(file, found)
    assert "  1. lunch does not require bags." in words
    assert "  2. alex has bags when the TRIP starts." in words
    assert "  3. The TRIP starts with bags at park." in words
    # Where a FACT says that lunch does not require them, it might still refuse them, and
    # Alex might have them.
    file = a_lunch(requires_object("lunch", "bags", False))
    found = checked(file)
    assert asked(found) == [
        (Unknown("does not refuse", "lunch", about="bags"),),
        (Unknown("starts at", place="park", about="bags"),),
        (Unknown("starts at", place="hotel", about="bags"),),
    ]
    assert "  1. lunch does not refuse bags." in report.as_text(file, found)


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
    assert "  bags-start: the TRIP starts with bags at hotel" in words
    assert "  lunch-requires-bags: lunch requires bags" in words
    whole = "the FILE states every OPTION that hands over, keeps or carries bags: there is none"
    assert f"  every-transfer-of-bags: {whole}" in words


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
    """For each OPTION: that it does not require the OBJECT, that it does not refuse it, then
    the four ways that what it does with it can help. Where the OBJECT starts comes after the
    OPTIONs and the WAYs: with each PERSON, then at each PLACE. Another transfer comes last."""
    file = a_lunch()
    about = [(each.what, each.option, each.person, each.place) for each in unknowns(file)]
    about = [each for each in about if each[0] != "other ways"]
    assert about == [
        ("does not require", "lunch", None, None),
        ("does not refuse", "lunch", None, None),
        ("keeps", "lunch", None, None),
        ("does not keep", "lunch", None, None),
        ("hands over", "lunch", None, None),
        ("carries", "lunch", None, None),
        ("starts with", None, "alex", None),
        ("starts at", None, None, "park"),
        ("starts at", None, None, "hotel"),
        ("another transfer", None, None, None),
    ]
    # A FACT settles its own, and a COMPLETE set settles a whole kind.
    settled_file = a_lunch(has_object("alex", "bags"), every_transfer("bags"))
    left = [each.what for each in unknowns(settled_file) if each.what != "other ways"]
    assert left == ["does not require", "does not refuse"]
    # A FACT about whether an OPTION refuses the OBJECT settles that only.
    stated = a_lunch(has_object("alex", "bags"), every_transfer("bags"), *lets_in("bags", "lunch"))
    assert [each.what for each in unknowns(stated) if each.what != "other ways"] == [
        "does not require"
    ]
    # Nothing is asked about an OBJECT that no OPTION requires or refuses, or might.
    unused = a_lunch(every_use("bags"))
    assert [each.what for each in unknowns(unused) if each.what != "other ways"] == []


def test_listing_an_object_that_nothing_requires_changes_no_answer() -> None:
    """Nothing turns on where the OBJECT is, so the solver's model leaves it out."""
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
        *lets_in("passport", "first", "second", "third"),
    )
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    # It relies on a FACT about each refusal too: Alex has the passport in all three.
    assert relied_on(found) == [
        "passport-start",
        "first-requires-passport",
        "second-requires-passport",
        "third-requires-passport",
        "every-transfer-of-passport",
        "first-refuses-passport",
        "second-refuses-passport",
        "third-refuses-passport",
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
    # Alex has the passport in all three. A FACT says what the first one does, and only the
    # COMPLETE set says that the other two leave it alone.
    assert relied_on(found) == [
        "passport-start",
        "first-with-passport",
        "second-requires-passport",
        "every-use-of-passport",
        "every-transfer-of-passport",
    ]


def test_where_the_file_says_nothing_about_an_option_the_report_names_each_place() -> None:
    """Nothing says what the second and the third appointment do with the passport. The plan
    holds either way: the second requires it while Alex has it, and nothing requires it
    afterwards. The report says each place where it might be from then on."""
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
    either = (Where(person="alex"), Where(place="desk"))
    assert found.objects[0].stays == (
        Stay((Where(person="alex"),)),
        Stay(either, "second", "might be kept"),
        Stay((*either, Where(place="office")), "third", "might be kept"),
    )


def test_a_plan_relies_on_no_fact_about_an_object_that_it_does_not_need() -> None:
    """The plan has the first two appointments. The FACTs about the third, which stays out,
    are not among those it relies on. A FACT says what each of the first two does with the
    passport, so the plan does not rely on the COMPLETE set of transfers either."""
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
        "second-with-passport",
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
        "every-transfer-of-passport",
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
            "refused_by": [],
        }
    ]
    words = report.as_text(file, found)
    assert (
        "  passport: with alex when the TRIP starts; at desk from 9:00 am (kept by first);"
        " with alex from 10:00 am (handed over in second)"
    ) in words
    assert "  first-with-passport: first keeps passport" in words
    assert "  second-with-passport: passport can be handed over in second" in words
    assert "  third-requires-passport: third requires passport" in words
    assert "only third requires passport, and none refuses passport" in words


def test_a_plan_says_where_the_file_leaves_a_requirement_open() -> None:
    """Nobody said whether the first appointment requires the passport. Alex has it there,
    so the plan holds if it does."""
    file = locked_desk(
        has_object("alex", "passport"), *lets_in("passport", "first"), into=("first",)
    )
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert found.objects[0].uses == (Use("first", False, (Where(person="alex"),)),)
    assert relied_on(found) == ["passport-start", "first-refuses-passport"]
    words = report.as_text(file, found)
    silent = "The FILE does not say whether first requires passport"
    assert f"    {silent}. Just before it starts: with alex, so the plan holds if it does." in words


def test_a_plan_says_where_the_file_leaves_a_refusal_open() -> None:
    """Nobody said whether the first appointment refuses the passport. It lies on the desk,
    so the plan holds if it does."""
    file = locked_desk(
        lies_at("passport", "desk"), requires_object("first", "passport", False), into=("first",)
    )
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert found.objects[0].uses == (Use("first", False, (Where(place="desk"),), "refuses"),)
    assert relied_on(found) == ["passport-start", "first-requires-passport"]
    words = report.as_text(file, found)
    silent = "The FILE does not say whether first refuses passport"
    assert f"    {silent}. Just before it starts: at desk, so the plan holds if it does." in words
    assert report.as_json(file, found)["objects"] == [
        {
            "object": "passport",
            "path": [{"where": [{"place": "desk"}], "since": None, "how": None}],
            "required_by": [],
            "refused_by": [{"option": "first", "stated": False, "where": [{"place": "desk"}]}],
        }
    ]
    # With Alex carrying it, the plan does not hold if the appointment refuses it.
    carried = locked_desk(
        has_object("alex", "passport"), requires_object("first", "passport", False), into=("first",)
    )
    found = checked(carried)
    assert asked(found) == [(Unknown("does not refuse", "first", about="passport"),)]
    assert "The trip works if first does not refuse passport." in report.as_text(carried, found)


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
        "  passport-start: the TRIP starts with passport at desk",
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
    loaded = locked_desk(
        has_object("alex", "passport"),
        carries("first", "passport"),
        refuses_object("second", "passport"),
        every_use("passport"),
        every_transfer("passport"),
        into=("first", "second"),
    )
    words = report.as_text(loaded, checked(loaded))
    assert "  first-with-passport: first can carry passport" in words
    assert "    This carries passport." in words
    path = "with alex when the TRIP starts; in first from 9:00 am (carried); at desk from 9:30 am"
    assert f"  passport: {path} (where first ends)" in words
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
    said = "the FILE states every OPTION that hands over, keeps or carries passport: first"
    assert f"  every-transfer-of-passport: {said}" in words


# An OPTION that refuses an OBJECT: the answers.


def a_cloakroom(*more: Document, start: Document | None = None) -> File:
    """Alex and Sam are LOCKed into a visit at 10:00 am that refuses the bags.

    A stop at the cloakroom takes 5 minutes, can start at any time and keeps the bags. The
    TRIP starts at 9:00 am. The FILE states every OPTION that requires the bags or refuses
    them, and every one that hands them over or keeps them.
    """
    options = [stays("cloakroom", "museum"), stays("visit", "museum")]
    facts = [
        *whenever("cloakroom"),
        *at("visit", 10),
        keeps("cloakroom", "bags"),
        refuses_object("visit", "bags"),
        every_use("bags"),
        every_transfer("bags"),
        *([start] if start is not None else []),
        *more,
    ]
    locks = [trip_starts(9), lock("visit", "alex", "sam")]
    return trip(["alex", "sam"], ["museum", "hotel"], options, facts, locks, objects=["bags"])


def test_whoever_has_an_object_leaves_it_where_it_is_kept_before_an_option_refuses_it() -> None:
    """Alex has the bags. The plan has Alex at the cloakroom first, though no LOCK names it.
    Sam has nothing to leave there."""
    file = a_cloakroom(start=has_object("alex", "bags"))
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert [(each.option, each.persons) for each in found.itinerary] == [
        ("cloakroom", ("alex",)),
        ("visit", ("alex", "sam")),
    ]
    assert compiler.check(file) == found
    # Where the bags lie at the museum, nobody has to go to the cloakroom.
    lying = a_cloakroom(start=lies_at("bags", "museum"))
    assert [each.option for each in checked(lying).itinerary] == ["visit"]
    # With no cloakroom to keep them, nothing works.
    kept = "cloakroom-with-bags"
    without = replace(file, facts=tuple(fact for fact in file.facts if fact.id != kept))
    found = checked(without)
    assert found.answer is Answer.INFEASIBLE
    assert found.conflict == (
        "visit-refuses-bags",
        "every-transfer-of-bags",
        "bags-start",
        "lock-visit",
    )


def test_where_nobody_knows_who_has_an_object_everybody_stops_where_it_is_kept() -> None:
    """No FACT says where the bags are. Alex might have them, and so might Sam. So both stop
    at the cloakroom, and then neither has them, wherever they were."""
    file = a_cloakroom()
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert [(each.option, each.persons) for each in found.itinerary] == [
        ("cloakroom", ("alex", "sam")),
        ("visit", ("alex", "sam")),
    ]
    assert compiler.check(file) == found
    elsewhere = (Where(place="museum"), Where(place="hotel"), Where())
    (bags,) = found.objects
    # Nobody knows whether Alex or Sam has the bags. So the report does not say that the
    # cloakroom kept them: it keeps them if anybody there has them.
    assert bags.stays == (
        Stay((Where(person="alex"), Where(person="sam"), *elsewhere)),
        Stay(elsewhere, "cloakroom", "kept if held"),
    )
    assert bags.uses == (Use("visit", True, elsewhere, "refuses"),)
    relied = [record for record in found.relies_on if "bags" in record]
    assert relied == ["cloakroom-with-bags", "visit-refuses-bags", "every-use-of-bags"]
    words = report.as_text(file, found)
    there = "at museum, at hotel or somewhere the FILE does not name"
    assert f"  bags: nobody knows where when the TRIP starts; {there} from " in words
    assert " (kept by cloakroom if anybody there has bags)\n" in words
    assert f"    visit refuses bags. Just before it starts: {there}." in words
    said = json.loads(json.dumps(report.as_json(file, found)))
    assert said["objects"][0]["refused_by"] == [
        {
            "option": "visit",
            "stated": True,
            "where": [{"place": "museum"}, {"place": "hotel"}, {"place": None}],
        }
    ]
    # Where nobody said what the cloakroom does with the bags, it clears nobody. Then one
    # FACT is enough: that it keeps them, or that they lie at a PLACE.
    gone = ("cloakroom-with-bags", "every-transfer-of-bags")
    unsaid = replace(file, facts=tuple(fact for fact in file.facts if fact.id not in gone))
    found = checked(unsaid)
    assert asked(found) == [
        (Unknown("keeps", "cloakroom", about="bags"),),
        (Unknown("starts at", place="museum", about="bags"),),
        (Unknown("starts at", place="hotel", about="bags"),),
    ]


def test_two_refusals_whose_orders_go_round_in_a_circle_leave_no_plan() -> None:
    """Alex has a red bag and a blue bag, and is LOCKed into two stops at 10:00 am that take
    no time. One keeps the red bag and refuses the blue one. The other keeps the blue bag and
    refuses the red one. Each bag has an order that works by itself, and the two orders go
    round in a circle."""
    options = [stays("red-stop", "desk"), stays("blue-stop", "desk")]
    facts = [
        *at("red-stop", 10, length="PT0S"),
        *at("blue-stop", 10, length="PT0S"),
        has_object("alex", "red"),
        has_object("alex", "blue"),
        keeps("red-stop", "red"),
        refuses_object("red-stop", "blue"),
        keeps("blue-stop", "blue"),
        refuses_object("blue-stop", "red"),
        *(every_use(thing) for thing in ("red", "blue")),
        *(every_transfer(thing) for thing in ("red", "blue")),
    ]
    locks = [lock("red-stop", "alex"), lock("blue-stop", "alex")]
    file = trip(["alex"], ["desk"], options, facts, locks, objects=["red", "blue"])
    assert checked(file).answer is Answer.INFEASIBLE
    # With one refusal gone, the other bag puts the two stops in its order: the stop that
    # keeps a bag comes before the stop that refuses it, wherever the FILE lists it.
    for gone, order in (
        ("red-stop-refuses-blue", ["red-stop", "blue-stop"]),
        ("blue-stop-refuses-red", ["blue-stop", "red-stop"]),
    ):
        one = replace(file, facts=tuple(fact for fact in file.facts if fact.id != gone))
        found = checked(one)
        assert found.answer is Answer.FEASIBLE
        assert [each.option for each in found.itinerary] == order


def lunch_and_check_in(*more: Document) -> File:
    """Alex is LOCKed into lunch in the park at noon, and Sam into a check-in at the hotel
    then. The check-in requires the bags and does not refuse them."""
    options = [stays("lunch", "park"), stays("check-in", "hotel")]
    facts = [
        *at("lunch", 12),
        *at("check-in", 12),
        requires_object("check-in", "bags"),
        *lets_in("bags", "check-in"),
        *more,
    ]
    locks = [lock("lunch", "alex"), lock("check-in", "sam")]
    return trip(["alex", "sam"], ["park", "hotel"], options, facts, locks, objects=["bags"])


def might_work_if(
    file: File, thing: str = "bags"
) -> tuple[tuple[tuple[str, str, bool, bool], ...], str]:
    """What another transfer has to do in the one case of a report, as checks and in words."""
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    assert asked(found) == [(Unknown("another transfer", about=thing),)]
    (words,) = [
        line for line in report.as_text(file, found).splitlines() if line.startswith("The trip")
    ]
    return found.missing[0][0].at_hand_for, words.removeprefix("The trip might work if ")


def test_another_transfer_is_worded_by_what_it_has_to_do_at_each_option() -> None:
    # Alex has the bags, and lunch refuses them. No FACT says that the FILE states every
    # transfer, so somebody might take them.
    carried = [has_object("alex", "bags"), refuses_object("lunch", "bags")]
    file = a_lunch(*carried, requires_object("lunch", "bags", False))
    assert might_work_if(file) == (
        (("lunch", "refuses", True, False),),
        "another transfer keeps bags out of lunch.",
    )
    # Lunch requires them too. So they have to lie in the park, and Alex does not bring them
    # in. One check holds as it is, and the report still says "puts": the other does not.
    file = a_lunch(*carried, requires_object("lunch", "bags"))
    assert might_work_if(file) == (
        (("lunch", "requires", True, True), ("lunch", "refuses", True, False)),
        "another transfer puts bags where lunch starts.",
    )
    said = json.loads(json.dumps(report.as_json(file, checked(file))))
    assert said["missing"][0][0]["at_hand_for"] == [
        {"option": "lunch", "check": "requires", "stated": True, "covered": True},
        {"option": "lunch", "check": "refuses", "stated": True, "covered": False},
    ]
    # The bags lie in the park, where lunch requires them and refuses them. Both checks hold,
    # and another transfer has to leave it so while it brings the bags to the check-in.
    both = [requires_object("lunch", "bags"), refuses_object("lunch", "bags")]
    file = lunch_and_check_in(lies_at("bags", "park"), *both)
    assert might_work_if(file) == (
        (
            ("lunch", "requires", True, True),
            ("lunch", "refuses", True, True),
            ("check-in", "requires", True, False),
        ),
        "another transfer puts bags at hand for check-in, and leaves bags where lunch starts.",
    )
    # Alex has the bags, and nobody said whether lunch refuses them.
    file = lunch_and_check_in(has_object("alex", "bags"), requires_object("lunch", "bags", False))
    assert might_work_if(file) == (
        (("lunch", "refuses", False, False), ("check-in", "requires", True, False)),
        "another transfer puts bags at hand for check-in, and keeps bags out of lunch if it"
        " refuses bags.",
    )
    # Two OPTIONs that might refuse the bags are named together.
    file = lunch_and_check_in(
        lies_at("bags", "park"), requires_object("lunch", "bags", False), *lets_in("bags", "lunch")
    )
    file = replace(file, facts=tuple(f for f in file.facts if f.id != "lunch-refuses-bags"))
    file = replace(file, facts=tuple(f for f in file.facts if f.id != "check-in-refuses-bags"))
    assert might_work_if(file) == (
        (
            ("lunch", "refuses", False, True),
            ("check-in", "requires", True, False),
            ("check-in", "refuses", False, True),
        ),
        "another transfer puts bags at hand for check-in, and leaves bags out of lunch and"
        " check-in if they refuse bags.",
    )


def test_a_refusing_option_is_not_credited_with_what_it_cannot_do() -> None:
    """Alex has the bag, and is LOCKed into the entry at 9:00 am and the gallery at 10:00 am.
    The entry refuses the bag and keeps it. The gallery requires it and refuses it. No FACT
    says that the FILE states every transfer.

    Alex cannot bring the bag through the entry, so the entry keeps nothing. Another
    transfer has to keep the bag out of the entry, and put it where the gallery starts.
    Whatever the FILE says the entry does with the bag, the report is the same."""
    options = [stays("entry", "museum"), stays("gallery", "museum")]

    def said(*entry_does: Document) -> tuple[tuple[tuple[str, str, bool, bool], ...], str]:
        facts = [
            *at("entry", 9),
            *at("gallery", 10),
            has_object("alex", "bag"),
            refuses_object("entry", "bag"),
            *entry_does,
            requires_object("gallery", "bag"),
            refuses_object("gallery", "bag"),
            every_use("bag"),
        ]
        locks = [lock("entry", "alex"), lock("gallery", "alex")]
        file = trip(["alex"], ["museum"], options, facts, locks, objects=["bag"])
        found = checked(file)
        (words,) = [
            line for line in report.as_text(file, found).splitlines() if line.startswith("The trip")
        ]
        return found.missing[0][0].at_hand_for, words

    expected = (
        (
            ("entry", "refuses", True, False),
            ("gallery", "requires", True, True),
            ("gallery", "refuses", True, False),
        ),
        "The trip might work if another transfer keeps bag out of entry, and puts bag where"
        " gallery starts.",
    )
    assert said(keeps("entry", "bag")) == expected
    assert said(does_with("entry", "bag", "nothing")) == expected
    assert said(hands_over("entry", "bag")) == expected
    assert said() == expected


def test_what_the_file_lists_covers_a_check_only_whichever_way_an_open_refusal_turns_out() -> None:
    """Alex has the bag. The shuttle from the hotel at 9:00 am keeps it there, and the flight
    at 10:00 am requires it. No FACT says that the FILE states every transfer.

    Where the shuttle refuses the bag, it keeps nothing, and Alex still has the bag for the
    flight. Where it does not refuse it, it keeps it, and the flight is without it. Where
    nobody said, the report counts on neither: another transfer has to put the bag at hand
    for the flight."""
    options = [
        moves("shuttle", "hotel", "airport"),
        stays("desk", "hotel"),
        moves("flight", "airport", "away"),
    ]

    def said(*refusal: Document) -> tuple[tuple[tuple[str, str, bool, bool], ...], str]:
        facts = [
            *at("shuttle", 9),
            *at("desk", 9, 30),
            *at("flight", 10),
            starts_from("sam", "hotel"),
            has_object("alex", "bag"),
            keeps("shuttle", "bag"),
            requires_object("shuttle", "bag", False),
            requires_object("desk", "bag"),
            requires_object("flight", "bag"),
            *lets_in("bag", "desk", "flight"),
            does_with("desk", "bag", "nothing"),
            does_with("flight", "bag", "nothing"),
            complete(None, None),
            *refusal,
        ]
        locks = [lock("shuttle", "alex"), lock("desk", "sam"), lock("flight", "alex")]
        places = ["hotel", "airport", "away"]
        file = trip(["alex", "sam"], places, options, facts, locks, objects=["bag"])
        return might_work_if(file, "bag")

    # Sam is at a desk in the hotel at 9:30 am that requires the bag too. It is at hand
    # there only where the shuttle is sure to have kept it.
    assert said() == (
        (
            ("shuttle", "refuses", False, False),
            ("desk", "requires", True, False),
            ("flight", "requires", True, False),
        ),
        "another transfer puts bag at hand for desk and flight, and keeps bag out of shuttle"
        " if it refuses bag.",
    )
    assert said(refuses_object("shuttle", "bag")) == (
        (
            ("shuttle", "refuses", True, False),
            ("desk", "requires", True, False),
            ("flight", "requires", True, True),
        ),
        "another transfer puts bag at hand for desk, and leaves bag at hand for flight, and"
        " keeps bag out of shuttle.",
    )
    assert said(refuses_object("shuttle", "bag", False)) == (
        (("desk", "requires", True, True), ("flight", "requires", True, False)),
        "another transfer puts bag at hand for flight, and leaves bag at hand for desk.",
    )


def five_museum_visitors(
    *more: Document, collection: bool = False, meeting: bool = False, briefing: bool = False
) -> File:
    """Five visitors, each LOCKed into two visits of their own at the museum.

    Every visit takes half an hour, can start at any time and refuses the bag. A stop at the
    cloakroom at 9:00 am keeps the bag. The TRIP starts at 8:00 am, and both sets of the bag
    are COMPLETE. With ``collection``, all five are LOCKed into a collection at noon that
    takes five minutes and hands the bag over, and the TRIP ends when it is over. With
    ``meeting``, all five are LOCKed into a meeting at 8:00 am that takes five minutes and
    hands the bag over. With ``briefing``, all five are LOCKed into a briefing at 8:00 am,
    and nobody said what it does with the bag: no FACT says that the FILE states every
    OPTION that hands the bag over or keeps it."""
    people = [f"person-{number}" for number in range(5)]
    visits = [f"visit-{number}" for number in range(10)]
    options = [stays("cloakroom", "museum"), *(stays(name, "museum") for name in visits)]
    facts = [*at("cloakroom", 9, length="PT5M"), keeps("cloakroom", "bag")]
    for name in visits:
        facts += [*whenever(name, "PT30M"), refuses_object(name, "bag")]
    facts += [every_use("bag"), *([] if briefing else [every_transfer("bag")]), *more]
    locks = [trip_starts(8)]
    for number, person in enumerate(people):
        locks += [lock(f"visit-{2 * number}", person), lock(f"visit-{2 * number + 1}", person)]
    if briefing:
        options.append(stays("briefing", "museum"))
        facts += [*at("briefing", 8, length="PT5M")]
        facts += [does_with(name, "bag", "nothing") for name in visits]
        locks += [lock("briefing", *people)]
    if collection:
        options.append(stays("collection", "museum"))
        facts += [*at("collection", 12, length="PT5M"), hands_over("collection", "bag")]
        locks += [lock("collection", *people), trip_ends(12, 5)]
    if meeting:
        options.append(stays("meeting", "museum"))
        facts += [*at("meeting", 8, length="PT5M"), hands_over("meeting", "bag")]
        locks += [lock("meeting", *people)]
    return trip(people, ["museum"], options, facts, locks, objects=["bag"])


def test_a_refusal_orders_only_the_options_of_those_who_can_have_the_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One visitor has the bag. Nobody else can ever have it, so the refusals of the other
    eight visits ask nothing, wherever those visits come. Only the cloakroom and the two
    visits of whoever has the bag have an order. The eleven OPTIONs have very many."""
    file = five_museum_visitors(has_object("person-0", "bag"))
    # What each visitor does, in order. Only the first stops at the cloakroom.
    orders = ((0, 1, 2), *((2 * number + 1, 2 * number + 2) for number in range(1, 5)))
    happening = list(range(len(file.options)))
    ordered = reference._ordered_by(  # pyright: ignore[reportPrivateUsage]
        file, worst_case(file), orders, happening, "bag"
    )
    assert ordered == ((1, 2), (0, 1, 2))
    timed = 0
    its_own = reference._times  # pyright: ignore[reportPrivateUsage]

    def counted(
        count: int,
        gaps: list[tuple[int, int, int]],
        fixed: dict[int, int],
        not_before: dict[int, int],
        no_later: dict[int, int],
    ) -> list[int] | None:
        nonlocal timed
        timed += 1
        return its_own(count, gaps, fixed, not_before, no_later)

    monkeypatch.setattr(reference, "_times", counted)
    found = compiler.check(file)
    assert found.answer is Answer.FEASIBLE
    assert timed < 10
    # Whoever has the bag stops at the cloakroom first. The others start when the TRIP starts.
    starts = {each.option: each.start for each in found.itinerary}
    assert [each.persons for each in found.itinerary if each.option == "cloakroom"] == [
        ("person-0",)
    ]
    assert starts["visit-0"] == seconds(9, 5) and starts["visit-2"] == seconds(8)


def the_solver_gives_up_after(monkeypatch: pytest.MonkeyPatch, conflicts: int) -> None:
    """Each question to the solver stops after so many conflicts, and the COMPILER fails then.

    The solver goes through the same conflicts every time. So a test that passes with this
    has a report that the solver finds at once.
    """
    its_own = compiler._solver  # pyright: ignore[reportPrivateUsage]

    def capped(relax: bool = True) -> cp_model.CpSolver:
        solver = its_own(relax)
        solver.parameters.max_number_of_conflicts = conflicts
        return solver

    monkeypatch.setattr(compiler, "_solver", capped)


def test_the_model_says_nothing_about_an_order_that_fixed_starts_rule_out() -> None:
    """The gallery at 10:00 am refuses the camera that Alex has. At coffee at 11:00 am Alex
    could hand it to Jo, and a locker at 9:00 am keeps it. Coffee comes after the gallery,
    so it is no way for Alex to be rid of the camera before the gallery, and the model has
    no choice for that. The locker comes before, and the model has one."""

    def choices(*more: Document, show: bool = False) -> list[str]:
        """The names of the choices in the solver's model of the worst case."""
        names = ["locker", "gallery", "coffee", *(["show"] if show else [])]
        facts = [
            *at("locker", 9),
            *at("gallery", 10),
            *at("coffee", 11),
            has_object("alex", "camera"),
            keeps("locker", "camera"),
            refuses_object("gallery", "camera"),
            hands_over("coffee", "camera"),
            every_use("camera"),
            every_transfer("camera"),
            *more,
        ]
        locks = [lock("gallery", "alex"), lock("coffee", "alex", "jo")]
        locks += [lock("show", "jo")] if show else []
        options = [stays(name, "museum") for name in names]
        file = trip(["alex", "jo"], ["museum"], options, facts, locks, objects=["camera"])
        found = checked(file)
        assert [(each.option, each.persons) for each in found.itinerary][:3] == [
            ("locker", ("alex",)),
            ("gallery", ("alex",)),
            ("coffee", ("alex", "jo")),
        ]
        search = compiler._Search(file, worst_case(file), plain=True)  # pyright: ignore[reportPrivateUsage]
        model: Any = search.model.proto
        return [str(each.name) for each in model.variables]

    names = choices()
    assert [name for name in names if " is rid of " in name] == [
        "0 is rid of camera in locker before gallery"
    ]
    assert "gallery after coffee" not in names
    # A show at noon refuses the camera too, and Jo is LOCKed into it. Jo can take the
    # camera at coffee. The locker is over by then, so it is no way for Jo to be rid of what
    # Jo takes at coffee, and the model has no choice for that either.
    names = choices(*at("show", 12), refuses_object("show", "camera"), show=True)
    assert "show after coffee" in names
    assert not any(name.startswith("1 is rid of camera in locker") for name in names)


def test_five_visitors_are_shown_at_once_whoever_might_have_the_bag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One visitor has the bag, or nobody knows who has it. With a collection at noon that
    hands the bag over, each visitor can come to have it, but only from noon on. With a
    meeting at 8:00 am that hands it over, each can have it all day, and nobody takes it. In
    all six FILEs the report comes at once: the solver's model says outright that whoever has
    the bag is rid of it before a visit, and the search times a few plans."""
    the_solver_gives_up_after(monkeypatch, 2000)
    everybody = tuple(f"person-{number}" for number in range(5))
    for holder in ([has_object("person-0", "bag")], []):
        for collection, meeting in ((False, False), (True, False), (False, True)):
            file = five_museum_visitors(*holder, collection=collection, meeting=meeting)
            found, timed = timings_for_the_report(monkeypatch, file)
            assert found.answer is Answer.FEASIBLE
            assert timed < 10
            stops = [each.persons for each in found.itinerary if each.option == "cloakroom"]
            assert stops == [("person-0",) if holder else everybody]
            assert not any(each.handed for each in found.itinerary)
    # A briefing that only might keep the bag takes it from nobody for sure. So all five
    # still stop at the cloakroom, and the report comes at once.
    found, timed = timings_for_the_report(monkeypatch, five_museum_visitors(briefing=True))
    assert found.answer is Answer.FEASIBLE
    assert timed < 10
    assert [each.persons for each in found.itinerary if each.option == "cloakroom"] == [everybody]


def carried_by_alex(things: Sequence[str], person: str = "alex") -> list[Document]:
    """A FACT for each of these OBJECTs: Alex has it when the TRIP starts, or this PERSON."""
    return [{**has_object(person, thing), "id": f"{thing}-start"} for thing in things]


def sets_tried_for(monkeypatch: pytest.MonkeyPatch, file: File) -> tuple[Report, int]:
    """The COMPILER's report on a FILE, and how many sets of unknown FACTs it tried for it.

    The reference checker's own search gives the same report.
    """
    tried = 0
    its_own = answers.with_these_at_best

    def counted(given: File, unknown: Iterable[Unknown]) -> World:
        nonlocal tried
        tried += 1
        return its_own(given, unknown)

    monkeypatch.setattr(answers, "with_these_at_best", counted)
    found = compiler.check(file)
    monkeypatch.setattr(answers, "with_these_at_best", its_own)
    assert answers.check(file) == found
    return found, tried


def test_a_visit_with_five_things_is_explained_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Alex is LOCKed into one visit and brings five things. Nothing says whether the visit
    refuses them, what it does with them, or whether the FILE states every transfer. The
    trip works if the visit refuses none of the five. The FILE has more than twenty unknown
    FACTs, and the sets of five of them are tens of thousands. The search first asks which
    FACTs no set can do without, and then tries very few sets."""
    things = ["camera", "daypack", "stroller", "water", "umbrella"]
    facts = [*at("visit", 10), *carried_by_alex(things)]
    options, locks = [stays("visit", "museum")], [lock("visit", "alex")]
    file = trip(["alex"], ["museum"], options, facts, locks, objects=things)
    assert len(unknowns(file)) > 20
    found, tried = sets_tried_for(monkeypatch, file)
    assert asked(found) == [
        tuple(Unknown("does not refuse", "visit", about=thing) for thing in things)
    ]
    assert tried < 10


def test_two_options_for_one_want_are_explained_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """A show is a must for Alex, and the matinee and the evening performance both deliver
    it. Alex brings four things, and nobody said whether either performance refuses them.
    No single FACT is in every set: Alex can go to the other performance. But for each
    thing, one of the two performances has to let it in. The search finds those four groups
    and tries sixteen sets. Two are enough: one performance lets all four in."""
    things = ["daypack", "camera", "bottle", "umbrella"]
    facts = [
        *at("matinee", 13),
        *at("evening", 20),
        satisfies("matinee", "show"),
        satisfies("evening", "show"),
        every("show"),
        *carried_by_alex(things),
    ]
    options = [stays("matinee", "hall"), stays("evening", "hall")]
    wants = [must("show", "alex")]
    file = trip(["alex"], ["hall"], options, facts, [], wants=wants, objects=things)
    found, tried = sets_tried_for(monkeypatch, file)
    assert asked(found) == [
        tuple(Unknown("does not refuse", show, about=thing) for thing in things)
        for show in ("matinee", "evening")
    ]
    assert tried <= 16


def test_a_cloakroom_and_a_gallery_are_explained_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Alex brings four things and is LOCKed into the gallery at 10:00 am. A stop at the
    cloakroom at 9:00 am does not refuse them. Nobody said what the cloakroom does with
    them, or whether the gallery refuses them. For each thing, the cloakroom keeps it, or
    the cloakroom can carry it, or the gallery does not refuse it: eighty-one cases. The
    search finds those four groups, each with the four FACTs about what the cloakroom does
    and the one about the gallery, and tries a few hundred sets where the sets of four
    FACTs are tens of thousands."""
    things = ["daypack", "camera", "stroller", "umbrella"]
    facts = [*at("cloakroom", 9), *at("gallery", 10), *carried_by_alex(things)]
    for thing in things:
        facts += lets_in(thing, "cloakroom")
    options = [stays("cloakroom", "museum"), stays("gallery", "museum")]
    file = trip(["alex"], ["museum"], options, facts, [lock("gallery", "alex")], objects=things)
    found, tried = sets_tried_for(monkeypatch, file)
    either = [
        (
            Unknown("keeps", "cloakroom", about=thing),
            Unknown("carries", "cloakroom", about=thing),
            Unknown("does not refuse", "gallery", about=thing),
        )
        for thing in things
    ]
    assert len(asked(found)) == 81
    assert {frozenset(named) for named in asked(found)} == {
        frozenset(chosen) for chosen in product(*either)
    }
    assert tried <= 625


def test_each_choice_of_new_things_has_its_own_facts_that_no_set_can_do_without(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Music is a must for Alex and Jo, and the recital has one place left. Alex brings five
    things. Where Alex takes the place, the recital has to refuse none of them, and Jo
    needs another OPTION. Where Jo takes it, the recital has to require none of them, and
    Alex needs another OPTION. Each choice has its own five FACTs, and the search tries one
    set for each."""
    things = ["camera", "recorder", "stroller", "bag", "umbrella"]

    def a_recital(carrier: str, *more: Document) -> File:
        facts = [
            *at("recital", 19),
            satisfies("recital", "music"),
            needs_right("recital"),
            offer("recital", 1, price="0.00 USD"),
            every_right("recital", "recital-offer"),
            *carried_by_alex(things, carrier),
            *more,
        ]
        options, wants = [stays("recital", "hall")], [must("music", "alex", "jo")]
        people = ["alex", "jo"]
        return trip(people, ["hall"], options, facts, [], wants=wants, rights=True, objects=things)

    def not_required(some: Sequence[str]) -> list[Unknown]:
        return [Unknown("does not require", "recital", about=thing) for thing in some]

    def not_refused(some: Sequence[str]) -> list[Unknown]:
        return [Unknown("does not refuse", "recital", about=thing) for thing in some]

    def another_for(person: str) -> Unknown:
        return Unknown("another option", want="music", person=person)

    found, tried = sets_tried_for(monkeypatch, a_recital("alex"))
    assert asked(found) == [
        (*not_required(things), another_for("alex")),
        (*not_refused(things), another_for("jo")),
    ]
    assert tried < 10
    # The sets are listed in the order of their FACTs, whichever new thing each comes with.
    # Where Jo brings the five things, the set that comes first is the one with another
    # OPTION for Jo, though Alex is listed before Jo.
    found, tried = sets_tried_for(monkeypatch, a_recital("jo"))
    assert asked(found) == [
        (*not_required(things), another_for("jo")),
        (*not_refused(things), another_for("alex")),
    ]
    # FACTs say that the recital does not require three of the things. Where Jo takes the
    # place, two FACTs are left to ask, and where Alex takes it, five. The report names the
    # smaller set, and the search tries no set of two FACTs for the choice that asks five.
    stated = [requires_object("recital", thing, False) for thing in things[:3]]
    found, tried = sets_tried_for(monkeypatch, a_recital("alex", *stated))
    assert asked(found) == [(*not_required(things[3:]), another_for("alex"))]
    assert tried < 10


def test_a_hand_over_that_comes_later_puts_no_earlier_refusal_in_the_order() -> None:
    """Alex has the bag, leaves it at the cloakroom at 9:00 am, and then has two visits that
    refuse it. Sam has one such visit. Both are LOCKed into a collection at noon that hands
    the bag over. Sam can have the bag only from noon on, so the refusal asks nothing of
    Sam's visit, and nothing ties it to what Alex does. The plan is the same as where the
    collection leaves the bag alone: Sam's visit is as late as the collection allows."""
    names = ["cloakroom", "alex-first", "alex-second", "sam-visit", "collection"]

    def shown(collection_does: str) -> list[tuple[str | None, int]]:
        facts = [
            *at("cloakroom", 9, length="PT5M"),
            *at("collection", 12, length="PT5M"),
            has_object("alex", "bag"),
            keeps("cloakroom", "bag"),
            does_with("collection", "bag", collection_does),
            every_use("bag"),
            every_transfer("bag"),
        ]
        for name in names[1:4]:
            facts += [*whenever(name, "PT30M"), refuses_object(name, "bag")]
        locks = [
            trip_starts(8),
            trip_ends(12, 5),
            lock("alex-first", "alex"),
            lock("alex-second", "alex"),
            lock("sam-visit", "sam"),
            lock("collection", "alex", "sam"),
        ]
        options = [stays(name, "museum") for name in names]
        file = trip(["alex", "sam"], ["museum"], options, facts, locks, objects=["bag"])
        found = checked(file)
        assert found.answer is Answer.FEASIBLE
        return [(each.option, each.start) for each in found.itinerary]

    plan = shown("hands_over")
    assert plan == shown("nothing")
    assert dict(plan)["sam-visit"] == seconds(11, 30)
    assert dict(plan)["cloakroom"] == seconds(9)


def test_an_option_that_hands_an_object_over_and_refuses_it_gives_it_to_nobody() -> None:
    """The bag lies on a desk. Alex's security appointment at 10:00 am hands it over and
    refuses it, so nobody takes it there. Sam's inspection requires the bag at that desk and
    can start at any time. Nothing can move the bag, so nothing ties the inspection to the
    appointment: it starts when the TRIP starts, at 8:00 am."""

    def a_desk_with(security_at: int, *deposit: Document) -> File:
        options = [stays("security", "desk"), stays("inspection", "desk")]
        facts = [
            *at("security", security_at),
            *whenever("inspection"),
            lies_at("bag", "desk"),
            hands_over("security", "bag"),
            refuses_object("security", "bag"),
            requires_object("inspection", "bag"),
            every_use("bag"),
            every_transfer("bag"),
            *deposit,
        ]
        locks = [trip_starts(8), lock("security", "alex"), lock("inspection", "sam")]
        if deposit:
            options.append(stays("deposit", "desk"))
            locks.append(lock("deposit", "alex"))
        return trip(["alex", "sam"], ["desk"], options, facts, locks, objects=["bag"])

    found = checked(a_desk_with(10))
    assert found.answer is Answer.FEASIBLE
    assert [(each.option, each.start) for each in found.itinerary] == [
        ("inspection", seconds(8)),
        ("security", seconds(10)),
    ]
    # Alex cannot come to have the bag through security. So a deposit that Alex is in keeps
    # nothing from Alex, and it ties the inspection to nothing either.
    found = checked(a_desk_with(9, *at("deposit", 10), keeps("deposit", "bag")))
    assert found.answer is Answer.FEASIBLE
    assert [(each.option, each.start) for each in found.itinerary] == [
        ("inspection", seconds(8)),
        ("security", seconds(9)),
        ("deposit", seconds(10)),
    ]


def test_nobody_takes_an_object_in_an_option_that_refuses_it_though_a_lock_puts_them_there() -> (
    None
):
    """Sam has the bag and leaves it at a drop at the desk at 8:00 am, which keeps it. Alex
    is LOCKed into security at the desk at 9:00 am, which hands the bag over and refuses it,
    and into a check at the gate at 10:00 am that requires it. The bag lies at the desk when
    Alex is at security, and Alex does not have it, so the refusal is kept. But nobody takes
    the bag there, and nothing else hands it over. So nothing works. Without the refusal,
    Alex takes the bag at security."""
    options = [stays("drop", "desk"), stays("security", "desk"), stays("check", "gate")]
    facts = [
        *at("drop", 8),
        *at("security", 9),
        *at("check", 10),
        takes("walk", "PT10M"),
        complete(None, None),
        has_object("sam", "bag"),
        keeps("drop", "bag"),
        hands_over("security", "bag"),
        refuses_object("security", "bag"),
        requires_object("check", "bag"),
        every_use("bag"),
        every_transfer("bag"),
    ]
    locks = [lock("drop", "sam"), lock("security", "alex"), lock("check", "alex")]
    ways = [way_between("walk", "desk", "gate")]
    file = trip(["alex", "sam"], ["desk", "gate"], options, facts, locks, ways, objects=["bag"])
    assert checked(file).answer is Answer.INFEASIBLE
    refusal = "security-refuses-bag"
    allowed = replace(file, facts=tuple(fact for fact in file.facts if fact.id != refusal))
    found = checked(allowed)
    assert found.answer is Answer.FEASIBLE
    assert [each.handed for each in found.itinerary if each.option == "security"] == [
        (("bag", "alex"),)
    ]


# Checked on FILEs made at random.

THINGS = ["bags", "keys"]
PLACES = ["a", "b", "c"]


def with_objects(rng: Random, file: File, most: int = 2) -> File:
    """The same FILE with one or two OBJECTs and FACTs about them, chosen at random."""
    names = THINGS[: rng.choice([1, 1, 1, 2][: 2 * most])]
    facts: list[ObjectStarts | RequiresObject | RefusesObject | WithObject] = []
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
            refused = rng.choice([None, None, True, False, False])
            if refused is not None:
                facts.append(RefusesObject(f"{option.id}-refuses-{name}", option.id, name, refused))
            does = rng.choice(
                [None, None, "hands_over", "hands_over", "keeps", "carries", "nothing"]
            )
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
    them at random. Some of the three refuse the bags, and FACTs say of some that they do
    not. A walk joins the two PLACEs. With ``most`` at two, some FILEs have keys too, which
    are fetched and required at the same OPTIONs.
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
    for option, how_often in (("fetch", 0.1), ("stop", 0.35), ("use", 0.1)):
        said = rng.random()
        if said < how_often + 0.3:
            facts.append(refuses_object(option, "bags", said < how_often))
    facts += [every_use("bags")] if rng.random() < 0.6 else []
    facts += [every_transfer("bags")] if rng.random() < 0.6 else []
    things = ["bags"]
    if most > 1 and rng.random() < 0.4:
        things.append("keys")
        whose = has_object(rng.choice(persons), "keys")
        facts.append(rng.choice([lies_at("keys", "a"), lies_at("keys", "a"), whose]))
        facts += [requires_object(rng.choice(["use", "use", "stop"]), "keys")]
        facts += [hands_over("fetch", "keys")] if rng.random() < 0.8 else []
        facts += [refuses_object("stop", "keys")] if rng.random() < 0.3 else []
        facts += [every_use("keys")] if rng.random() < 0.7 else []
        facts += [every_transfer("keys")] if rng.random() < 0.7 else []
    locks = [lock("use", *rng.sample(persons, rng.randrange(1, len(persons) + 1)))]
    if rng.random() < 0.5:
        locks.append(lock("stop", *rng.sample(persons, rng.randrange(1, len(persons) + 1))))
    if rng.random() < 0.2:
        locks.append(lock("fetch", rng.choice(persons)))
    ways = [way_between("walk", "a", "b")]
    return trip(persons, PLACES, options, facts, locks, ways, objects=things)


def a_trip_to_ship(rng: Random, extra: int = 1) -> File:
    """A FILE in which the bags often have to be carried across.

    They mostly lie at one PLACE or are with a PERSON, and an OPTION at another PLACE mostly
    requires them. A ship goes across and mostly carries them, and some FILEs have a boat
    that does too. Each leaves at a fixed time or at any time, and takes a known time, a
    range of times, no time, or nobody knows how long. A claim on the far side mostly hands
    the bags over. Some FILEs have a store on the near side that carries them and stays
    where it is, and some have a second use at a third PLACE. Some OPTIONs refuse the bags.
    A walk joins the PLACEs in some FILEs. ``extra`` is the most that a FILE has of the boat,
    the store and the second use. The reference checker tries everything, so a FILE with more
    than four OPTIONs takes it minutes.
    """
    persons = rng.choice([["alex"], ["alex", "sam"], ["alex", "sam"]])
    options = [moves("ship", "a", "b"), stays("claim", "b"), stays("use", "b")]
    boat, store, later = rng.random() < 0.4, rng.random() < 0.3, rng.random() < 0.4
    while boat + store + later > extra:
        boat, store, later = rng.choice(
            [(False, store, later), (boat, False, later), (boat, store, False)]
        )
    options += [moves("boat", "a", "b")] if boat else []
    options += [stays("store", "a")] if store else []
    options += [stays("later", "c")] if later else []
    rng.shuffle(options)

    def timed(
        option: str,
        starts: Sequence[tuple[int, int] | None],
        lengths: Sequence[str | tuple[str, str] | None],
    ) -> list[Document]:
        start, length = rng.choice(starts), rng.choice(lengths)
        out = [cutoff(option, "PT0S")]
        out.append(any_time(option) if start is None else starts_at(option, *start))
        if isinstance(length, tuple):
            out.append(lasts_between(option, *length))
        elif isinstance(length, str):
            out.append(lasts(option, length))
        return out

    crossing: list[str | tuple[str, str] | None] = [
        "PT30M",
        "PT30M",
        "PT15M",
        ("PT15M", "PT45M"),
        None,
        "PT0S",
    ]
    facts = [
        *timed("ship", [None, (9, 0), (9, 0), (9, 15)], crossing),
        *timed("claim", [None, (9, 30), (9, 45), (10, 0)], ["PT15M"]),
        *timed("use", [None, (9, 30), (9, 45), (10, 0), (10, 15)], ["PT15M"]),
    ]
    facts += timed("boat", [None, (9, 15), (9, 30)], ["PT15M", "PT15M", "PT30M"]) if boat else []
    facts += timed("store", [None, (8, 30), (8, 45)], ["PT15M", "PT0S"]) if store else []
    facts += timed("later", [None, (10, 30), (11, 0)], ["PT15M"]) if later else []
    for person in persons:
        if rng.random() < 0.7:
            facts.append(starts_from(person, rng.choice(["a", "a", "b"])))
    holder = has_object(rng.choice(persons), "bags")
    start = rng.choice([lies_at("bags", "a"), lies_at("bags", "a"), holder, holder, None])
    facts += [start] if start is not None else []
    for option, how_often in (("use", 0.9), ("later", 0.8), ("ship", 0.15)):
        if option in ("use", "ship") or later:
            facts += [requires_object(option, "bags")] if rng.random() < how_often else []
    said = [
        ("ship", ["carries", "carries", "carries", None, "nothing"]),
        ("claim", ["hands_over", "hands_over", "hands_over", None, "nothing"]),
        ("use", [None, "nothing", "nothing", "keeps"]),
    ]
    said += [("boat", ["carries", "carries", None])] if boat else []
    said += [("store", ["carries", "carries", "keeps"])] if store else []
    for option, choices in said:
        does = rng.choice(choices)
        if does is not None:
            facts.append(does_with(option, "bags", does))
    for option, how_often in (("ship", 0.35), ("use", 0.15), ("claim", 0.05)):
        draw = rng.random()
        if draw < how_often + 0.3:
            facts.append(refuses_object(option, "bags", draw < how_often))
    facts += [every_use("bags")] if rng.random() < 0.6 else []
    facts += [every_transfer("bags")] if rng.random() < 0.6 else []
    locks = [lock("use", *rng.sample(persons, rng.randrange(1, len(persons) + 1)))]
    for option, how_often in (("ship", 0.6), ("claim", 0.3), ("boat", 0.3), ("later", 0.7)):
        if rng.random() < how_often and any(each["id"] == option for each in options):
            locks.append(lock(option, rng.choice(persons)))
    ways: list[Document] = []
    if rng.random() < 0.5:
        ways.append(way_between("walk", "a", "b"))
        facts.append(takes("walk", f"PT{15 * rng.choice([1, 2, 4])}M"))
    if later:
        ways.append(way_between("path", "b", "c"))
        facts.append(takes("path", "PT15M"))
    if rng.random() < 0.7:
        facts.append(complete(None, None))
    return trip(persons, PLACES, options, facts, locks, ways, objects=["bags"])


def a_trip_with_objects(rng: Random, most: int = 2, extra: int = 1, **how: float) -> File:
    """A FILE with OBJECTs: trips to fetch the bags, trips to carry them across, or anything.

    ``most`` is the most OBJECTs it has, and ``extra`` goes to ``a_trip_to_ship``.
    """
    kind = rng.random()
    if kind < 0.35:
        return a_trip_to_fetch(rng, most)
    if kind < 0.65:
        return a_trip_to_ship(rng, extra)
    persons = rng.choice([["alex"], ["alex", "sam"], ["alex", "sam"]])
    count = rng.choice([2, 2, 3])
    return with_objects(rng, random_trip(rng, persons=persons, count=count, **how), most)


def a_world_with_objects(rng: Random, file: File) -> World:
    """One way the unknown FACTs could turn out, with those about OBJECTs too.

    No transfer from outside the FILE is in it: the travelers can leave one unused, so a
    world without one is always possible. An OBJECT with no FACT about where it starts is
    with a PERSON, at a PLACE, or somewhere the FILE does not name.
    """
    needs: set[tuple[str, str]] = set()
    refuses: set[tuple[str, str]] = set()
    does: dict[tuple[str, str], str] = {}
    starts: dict[str, Where] = {}
    people = [person.id for person in file.persons]
    for thing in file.objects:
        for option in file.options:
            required = file.requires_object(option.id, thing.id)
            if rng.random() < 0.5 if required is None else required:
                needs.add((option.id, thing.id))
            refused = file.refuses_object(option.id, thing.id)
            if rng.random() < 0.4 if refused is None else refused:
                refuses.add((option.id, thing.id))
            action = file.does_with(option.id, thing.id)
            action = action or rng.choice(["nothing", "keeps", "hands_over", "carries"])
            if action != "nothing":
                does[option.id, thing.id] = action
        start = file.object_starts(thing.id)
        if start is not None:
            starts[thing.id] = Where(start.person, start.place)
        else:
            guess = rng.choice([Where(person=rng.choice(people)), Where(place=rng.choice(PLACES))])
            starts[thing.id] = guess if rng.random() < 0.8 else Where()
    world = possible_world(rng, file)
    return replace(
        world, needs=frozenset(needs), refuses=frozenset(refuses), does=does, starts=starts
    )


def any_plan(rng: Random, file: File, world: World) -> Itinerary:
    """Some OPTIONs, PERSONs, WAYs, start times, hand-overs and carries. None is from the search.

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
        carried: list[str] = []
        for thing in file.objects:
            can = each.option is not None and world.does.get((each.option, thing.id))
            if can == "hands_over" and rng.random() < 0.6:
                handed.append((thing.id, rng.choice(each.persons)))
            if can == "carries" and rng.random() < 0.6:
                carried.append(thing.id)
        listed.append(replace(each, handed=tuple(handed), carried=tuple(carried)))
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


def ordered_by(
    file: File,
    world: World,
    who: tuple[tuple[str, ...], ...],
    orders: tuple[tuple[int, ...], ...],
    happening: list[int],
    thing: str,
) -> list[int]:
    """The OPTIONs of a plan that one OBJECT puts in an order, as the rules page says.

    Those that require it, those that can move it, and those that refuse it where a PERSON
    who takes part can have it by then, where some OPTION can move it. An OPTION can move it
    where it hands it over or carries it, or where it keeps it and a PERSON who takes part
    can have it by then. An OPTION that refuses it can move it only by carrying it. A PERSON
    can have it in an OPTION who has it when the TRIP starts, or might, or who takes part
    before that OPTION in one that hands it over and does not refuse it. "Might" counts as
    "does".
    """
    options = file.options
    hands = [
        index
        for index in happening
        if world.does.get((options[index].id, thing)) in ("hands_over", "any")
        and (options[index].id, thing) not in world.refuses
    ]
    if thing in world.starts:
        at_first = {world.starts[thing].person or ""}
    else:
        # The world leaves the start to pick, or nobody knows it: anybody might have it.
        at_first = {person.id for person in file.persons}

    def can_have_it_in(index: int) -> bool:
        """Whether somebody in this OPTION can have the OBJECT just before it starts."""
        for person, order in zip(file.persons, orders, strict=True):
            if person.id not in who[index]:
                continue
            before = order[: order.index(index)]
            if person.id in at_first or any(earlier in hands for earlier in before):
                return True
        return False

    keeps_it = [
        index
        for index in happening
        if world.does.get((options[index].id, thing)) in ("keeps", "might_keep")
        and (options[index].id, thing) not in world.refuses
        and can_have_it_in(index)
    ]
    carries_it = [
        index
        for index in happening
        if world.does.get((options[index].id, thing)) in ("carries", "any")
    ]
    if not hands and not keeps_it and not carries_it:
        return []
    refuses_it = [
        index
        for index in happening
        if (options[index].id, thing) in world.refuses and can_have_it_in(index)
    ]
    return [
        index
        for index in happening
        if (options[index].id, thing) in world.needs
        or index in refuses_it
        or index in hands
        or index in keeps_it
        or index in carries_it
    ]


type Chain = tuple[
    list[tuple[int, int, int]], dict[int, tuple[tuple[str, str | None], ...]], object
]
# One order of some OPTIONs as gaps, with hand-overs and carries: an OPTION, an OBJECT and a
# PERSON, or no PERSON for a carry.
type Ordered = tuple[list[tuple[int, int, int]], list[tuple[int, str, str | None]]]


def for_arrivals(
    file: File,
    world: World,
    order: Sequence[int],
    thing: str,
    given: Sequence[tuple[int, str, str | None]],
) -> list[tuple[int, int, int]]:
    """The gaps that the carries of one OBJECT add to an order, as the rules page says.

    An OPTION uses the OBJECT where it requires it, or where the OBJECT is handed over or
    carried in it. The first OPTION after a carry that uses the OBJECT starts no earlier
    than the carrying OPTION ends. Where nobody knows when that ends, there is no gap to
    add: the check of the ITINERARY then finds that the OBJECT never arrives.
    """
    options = file.options
    moved = {index for index, name, _ in given if name == thing}
    loaded = {index for index, name, person in given if name == thing and person is None}
    gaps: list[tuple[int, int, int]] = []
    carrier: int | None = None
    for index in order:
        if carrier is not None and ((options[index].id, thing) in world.needs or index in moved):
            terms = world.terms[options[carrier].id]
            if terms.longest is not None:
                gaps.append((carrier, index, terms.shortest))
            carrier = None
        if index in loaded:
            carrier = index
    return gaps


def every_chain(
    file: File,
    world: World,
    who: tuple[tuple[str, ...], ...],
    orders: tuple[tuple[int, ...], ...],
    everything: bool,
) -> list[Chain] | None:
    """Every order of the OPTIONs of a plan with every choice of hand-overs and carries.

    Nothing is skipped. It stands in for the search's own way of choosing them. Every order
    is given, also one that a PERSON's own order rules out. In each OPTION that hands an
    OBJECT over in this world, the OBJECT goes to anybody who takes part or to nobody, also
    where it is not at hand. In each OPTION that carries it, it is carried or not, also
    where it is not at hand. Each carry adds its gap, as ``for_arrivals`` says. With
    ``everything``, all the OPTIONs that happen are put in one order and every
    OBJECT is handed about. Without it, each OBJECT that the rules say matters has an order
    of its own among its own OPTIONs, so that the times come out as the rules say: the
    OPTIONs that require it, refuse it or can move it, and none where no OPTION can move it.
    An OBJECT that another transfer brings has an order too, and no hand-over.
    """
    options = file.options
    people = [person.id for person in file.persons]
    happening = [index for index, persons in enumerate(who) if persons]
    things = [thing.id for thing in file.objects if thing.id not in world.brought]
    checked_by = world.needs | world.refuses
    followed = [
        thing.id
        for thing in file.objects
        if any((options[index].id, thing.id) in checked_by for index in happening)
    ]
    if not followed:
        return None
    # Each group: the OPTIONs that are put in one order, and the OBJECTs handed about in them.
    groups: list[tuple[list[int], list[str]]] = [(happening, things)]
    if not everything:
        groups = [
            (ordered_by(file, world, who, orders, happening, thing), [thing]) for thing in followed
        ]
        # An OBJECT with no order is handed about nowhere: nothing hands it over.
    for_each: list[list[Ordered]] = []
    for matter, mine in groups:
        ways: list[Ordered] = []
        for order in permutations(matter):
            gaps = [(before, after, 0) for before, after in pairwise(order)]
            slots = [
                (index, thing, does)
                for index in order
                for thing in mine
                for does in [world.does.get((options[index].id, thing))]
                if does in ("hands_over", "carries", "any") and thing not in world.brought
            ]
            # In each of them: nothing, a hand-over to one who takes part, or a carry. A
            # choice names its kind, so that no id of a PERSON can be taken for one.
            choices: list[list[tuple[str, str | None]]] = [
                [
                    ("leave", None),
                    *(("hand", person) for person in (who[index] if does != "carries" else ())),
                    *([("carry", None)] if does != "hands_over" else []),
                ]
                for index, _, does in slots
            ]
            for chosen in product(*choices):
                given = [
                    (index, thing, person)
                    for (index, thing, _), (kind, person) in zip(slots, chosen, strict=True)
                    if kind != "leave"
                ]
                arrive = [
                    gap for thing in mine for gap in for_arrivals(file, world, order, thing, given)
                ]
                ways.append(([*gaps, *arrive], given))
        for_each.append(ways)
    chains: list[Chain] = []
    for combined in product(*for_each):
        gaps = [gap for some, _ in combined for gap in some]
        handed: dict[int, tuple[tuple[str, str | None], ...]] = {}
        ranked: dict[str, list[tuple[int, int]]] = {thing: [] for thing in (*things, *followed)}
        for _, given in combined:
            for index, thing, person in given:
                handed[index] = (*handed.get(index, ()), (thing, person))
                ranked[thing].append((index, -1 if person is None else people.index(person)))
        count = sum(len(each) for each in ranked.values())
        chains.append((gaps, handed, (count, tuple(tuple(ranked[thing]) for thing in followed))))
    return chains


def those_that_matter(
    file: File,
    world: World,
    who: tuple[tuple[str, ...], ...],
    orders: tuple[tuple[int, ...], ...],
    *hints: object,
) -> list[Chain] | None:
    """Every order, whatever the search says about which orders it can leave out."""
    return every_chain(file, world, who, orders, everything=False)


def all_of_them(
    file: File,
    world: World,
    who: tuple[tuple[str, ...], ...],
    orders: tuple[tuple[int, ...], ...],
    *hints: object,
) -> list[Chain] | None:
    """Every order of every OPTION, whatever the search says about which it can leave out."""
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


def never(*given: object) -> bool:
    """Stands in for a short cut of the search that is switched off."""
    return False


def no_order_first(*given: object) -> list[object]:
    """Stands in for the orders that the search tries before the others: there are none."""
    return []


class EveryOrder:
    """Switches the search between its own way and one that skips nothing.

    Its own way makes only some orders of the OPTIONs that matter to an OBJECT, tries some
    orders before the others, and stops at an ITINERARY that none can come before. The other
    way takes the orders that a stand-in gives and no other, times every one of them, and
    ranks every ITINERARY that works.
    """

    SHORT_CUTS = ("_orders_differ_only_in_the_listing", "_nothing_comes_before", "_to_try_first")
    OFF = (never, never, no_order_first)

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.monkeypatch = monkeypatch
        self.built = {name: getattr(reference, name) for name in ("_chains", *self.SHORT_CUTS)}

    def as_built(self) -> None:
        for name, its_own in self.built.items():
            self.monkeypatch.setattr(reference, name, its_own)

    def skipping_nothing(self, chains: object | None = None) -> None:
        self.monkeypatch.setattr(reference, "_chains", chains or self.built["_chains"])
        for name, off in zip(self.SHORT_CUTS, self.OFF, strict=True):
            self.monkeypatch.setattr(reference, name, off)


def test_the_search_shows_the_plan_that_a_search_that_skips_nothing_shows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The search orders only the OPTIONs that matter to an OBJECT, takes each OBJECT through
    them by itself, and keeps one choice of hand-overs for each order. Here every order and
    every choice of hand-overs is timed and checked, and the rule picks among all of them.
    The ITINERARIES are the same, in the same order."""
    rng = Random(2024)
    search = EveryOrder(monkeypatch)
    compared = with_hand_overs = with_two = with_carries = with_both = 0
    for _ in range(150):
        file = a_trip_with_objects(rng, leave_out=0.1, with_ways=0.6, with_complete=0.3)
        for world in worlds_to_try(rng, file):
            search.as_built()
            shown = itineraries(file, world)
            search.skipping_nothing(those_that_matter)
            assert itineraries(file, world) == shown
            compared += bool(shown)
            with_hand_overs += any(step.handed for plan in shown for step in plan)
            with_two += any(sum(len(step.handed) for step in plan) > 1 for plan in shown)
            carried = [any(step.carried for step in plan) for plan in shown]
            with_carries += any(carried)
            with_both += any(
                any(step.handed for step in plan) and loaded
                for plan, loaded in zip(shown, carried, strict=True)
            )
    assert compared > 150
    assert with_hand_overs > 25
    assert with_two > 2
    assert with_carries > 25
    assert with_both > 3


def test_ordering_only_the_options_that_matter_misses_no_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Here every OPTION that happens is put in every order, and every OBJECT is handed about
    in every way. Something works there exactly where the search finds something."""
    rng = Random(77)
    search = EveryOrder(monkeypatch)
    works = fails = 0
    for _ in range(120):
        file = a_trip_with_objects(rng, extra=0, leave_out=0.1, with_ways=0.6, with_complete=0.3)
        for world in worlds_to_try(rng, file):
            search.as_built()
            found = bool(itineraries(file, world))
            search.skipping_nothing(all_of_them)
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

    They ask for the fewest things that the FILE does not list. Among those, the settled
    sets come first, whatever their size: the ones with no other transfer. Then they have
    the fewest FACTs. "Hands over" is left out where "does not keep" is enough in its place,
    and so is "carries".
    """
    every_one = unknowns(file)
    facts = [unknown for unknown in every_one if unknown.what not in NEW]
    found = [unknown for unknown in every_one if unknown.what in NEW]

    def weaker(some: tuple[Unknown, ...], asked: Unknown) -> tuple[Unknown, ...]:
        return tuple(replace(u, what="does not keep") if u == asked else u for u in some)

    for count in range(len(found) + 1):
        new = list(combinations(found, count))
        settled = [some for some in new if all(u.what != "another transfer" for u in some)]
        for those in (settled, [some for some in new if some not in settled]):
            for size in range(len(facts) + 1):
                enough = [
                    (*some, *others)
                    for some in combinations(facts, size)
                    for others in those
                    if one_way_each(some)
                    and itineraries(file, with_these_at_best(file, (*some, *others)))
                ]
                if enough and count + size:
                    return [
                        some
                        for some in enough
                        if not any(
                            u.what in ("hands over", "carries") and weaker(some, u) in enough
                            for u in some
                        )
                    ]
    return []


def test_the_sets_named_for_objects_are_all_the_smallest_that_are_enough(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Checked by trying every set of that size and of each smaller one."""
    rng = Random(3143)
    kinds: set[str] = set()
    compared = several = unsettled = held = pairs = 0
    its_own = answers._asked_of_objects  # pyright: ignore[reportPrivateUsage]

    def counted(*given: object) -> object:
        nonlocal held, pairs
        groups = its_own(*given)  # type: ignore[arg-type]
        held += any(len(group) == 1 for group in groups)
        pairs += any(len(group) > 1 for group in groups)
        return groups

    monkeypatch.setattr(answers, "_asked_of_objects", counted)
    for _ in range(260):
        file = a_trip_with_objects(rng, most=1, leave_out=0.08)
        found = answers.check(file)
        named_sets = asked(found)
        for named in named_sets:
            kinds.update(unknown.what for unknown in named)
            assert itineraries(file, with_these_at_best(file, named))
            for left_out in named:
                fewer = [unknown for unknown in named if unknown != left_out]
                assert not itineraries(file, with_these_at_best(file, fewer))
        plain = [unknown for unknown in unknowns(file) if unknown.what not in NEW]
        if named_sets and len(named_sets[0]) <= 3 and len(plain) <= 13:
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
    wanted = {"does not require", "does not refuse", "does not keep", "hands over", "starts with"}
    assert wanted | {"starts at", "another transfer", "carries", "duration"} <= kinds
    assert compared > 40
    assert several > 10
    assert unsettled > 5
    # The search asked first which FACTs about the OBJECTs no set can do without. It found
    # single FACTs, and groups of which every set holds one.
    assert held > 20 and pairs > 3


def test_fewer_requirements_are_never_harder_for_the_same_plan() -> None:
    """A plan that works where an OPTION requires an OBJECT works where it does not, and one
    that works where an OPTION refuses an OBJECT works where it does not."""
    rng = Random(55)
    checked_plans = refused = 0
    for _ in range(120):
        file = a_trip_with_objects(rng, leave_out=0.1, with_ways=0.5)
        world = a_world_with_objects(rng, file)
        for plan in itineraries(file, world):
            for pair in world.needs:
                easier = replace(world, needs=world.needs - {pair})
                assert broken_as_listed(file, easier, plan) == []
                checked_plans += 1
            for pair in world.refuses:
                easier = replace(world, refuses=world.refuses - {pair})
                assert broken_as_listed(file, easier, plan) == []
                refused += 1
    assert checked_plans > 60 and refused > 30


def test_the_compiler_gives_the_reference_checkers_report_for_objects() -> None:
    """With the solver's own search for every part of it."""
    rng = Random(8)
    seen: set[Answer] = set()
    for _ in range(220):
        file = a_trip_with_objects(rng, leave_out=0.12, with_ways=0.6, with_complete=0.3)
        found = answers.check(file)
        assert answers.check(file, compiler.shown, compiler.works, compiler.can_work) == found
        assert compiler.check(file) == found
        seen.add(found.answer)
    assert seen == set(Answer)


@pytest.mark.parametrize(
    "name",
    [
        "the-cloakroom-is-not-in-the-plan",
        "nobody-collects-them",
        "the-visit-runs-late",
        "the-galleries-refuse-them",
    ],
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
    assert might.missing[0][0].at_hand_for == (("flight", "requires", True, False),)
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
    # The galleries refuse the bags.
    assert result("the-galleries-refuse-them").conflict == (
        "where-the-bags-start",
        "galleries-refuse-the-bags",
        "everything-that-moves-the-bags",
        "lock-visit",
    )
    left = result("they-leave-them-at-the-cloakroom")
    assert [step.option for step in left.itinerary][:3] == ["drop-off", "museum-visit", "pick-up"]
    assert [stay.since for stay in left.objects[0].stays] == [None, "drop-off", "pick-up"]
    assert left.objects[0].uses == (
        Use("museum-visit", True, (Where(place="art-institute"),), "refuses"),
        Use("flight", True, (Where(person="alex"),)),
    )
    assert named("nobody-said-whether-they-refuse-them") == [
        (("does not refuse", "museum-visit", "bags"),)
    ]
    taken = result("somebody-might-take-them")
    assert named("somebody-might-take-them") == [(("another transfer", None, "bags"),)]
    # The visit refuses the bags, so it cannot keep them: Alex still has them for the flight.
    assert taken.missing[0][0].at_hand_for == (
        ("museum-visit", "refuses", True, False),
        ("flight", "requires", True, True),
    )


# What the reviewer's FILEs showed.


def test_each_order_of_the_steps_is_timed_by_the_rule_before_the_orders_are_compared() -> None:
    """Alex has a check at the hotel at any time, and an appointment in the park at noon that
    requires the key Alex carries. Sam has a check in the park at 10:00 am. Only an unlisted
    WAY joins the hotel to the park, and none leaves from 9:00 am to 10:00 am. Each check
    hands the key over, so the two have an order.

    With Alex's check first, it is at 10:00 am, as late as it can be, and Alex travels at
    noon. With Sam's first, Alex's is at 10:00 am too, as early as it can be, and Alex
    travels just after the span. Both work. Sam's check is listed first in the FILE, so the
    plan with Sam's check first is the one shown. Nothing moves a step earlier than the
    rule for start times puts it."""
    options = [stays("sam-check", "park"), stays("alex-check", "hotel"), stays("meeting", "park")]
    span = {"from": "hotel", "to": "park", "leaving": {"earliest": moment(9), "latest": moment(10)}}
    facts = [
        *at("sam-check", 10, length="PT0S"),
        *whenever("alex-check", "PT0S"),
        *at("meeting", 12, length="PT0S"),
        starts_from("alex", "hotel"),
        starts_from("sam", "park"),
        {"id": "ways", "complete": span},
        has_object("alex", "key"),
        requires_object("meeting", "key"),
        hands_over("sam-check", "key"),
        hands_over("alex-check", "key"),
        every_use("key"),
        every_transfer("key"),
    ]
    locks = [lock("sam-check", "sam"), lock("alex-check", "alex"), lock("meeting", "alex")]
    file = trip(["alex", "sam"], ["hotel", "park"], options, facts, locks, objects=["key"])
    world = with_these_at_best(file, [Unknown("other ways", origin="hotel", destination="park")])
    shown = first_shown(file, world)
    assert shown is not None
    assert [(step.option, step.start) for step in shown] == [
        ("sam-check", seconds(10)),
        ("alex-check", seconds(10)),
        (None, seconds(10) + 1),
        ("meeting", seconds(12)),
    ]


def test_a_plan_is_checked_in_the_order_it_lists_its_steps() -> None:
    """Two appointments at one desk at 10:00 am. Alex has the bag. Sam's appointment requires
    it, and Alex's keeps it. Listed with Sam's first, the bag is not there yet. The check
    says so: it does not look for another order that would work."""
    options = [stays("sam-uses", "desk"), stays("alex-leaves", "desk")]
    facts = [
        *at("sam-uses", 10),
        *at("alex-leaves", 10, length="PT0S"),
        has_object("alex", "bag"),
        requires_object("sam-uses", "bag"),
        keeps("alex-leaves", "bag"),
        every_use("bag"),
        every_transfer("bag"),
    ]
    locks = [lock("sam-uses", "sam"), lock("alex-leaves", "alex")]
    file = trip(["alex", "sam"], ["desk"], options, facts, locks, objects=["bag"])
    world = worst_case(file)
    uses = Step("sam-uses", "desk", "desk", ("sam",), seconds(10), seconds(10, 30))
    leaves = Step("alex-leaves", "desk", "desk", ("alex",), seconds(10), seconds(10))
    too_soon = [Broken(Constraint.AT_HAND, "sam-uses", ("sam",), object="bag")]
    assert broken(file, world, (uses, leaves)) == too_soon
    assert broken_as_listed(file, world, (uses, leaves)) == too_soon
    assert broken(file, world, (leaves, uses)) == []
    assert checked(file).itinerary == (leaves, uses)


def test_a_case_that_is_not_settled_says_what_the_file_already_covers() -> None:
    """Alex takes a train from the desk to the gate, and then a flight. Both require the bag.
    It lies at the desk, and the train leaves it there. So it is at hand for the train, and
    nothing brings it to the flight. The report says which is which. The plan under it buys
    the place on the train, and the report says that this plan works in that case."""
    options = [moves("train", "desk", "gate"), moves("flight", "gate", "away")]
    facts = [
        *at("train", 9),
        *at("flight", 11),
        needs_right("train"),
        offer("train", 1, price="1.00 USD"),
        every_right("train", "train-offer"),
        needs_no_right("flight"),
        lies_at("bag", "desk"),
        requires_object("train", "bag"),
        does_with("train", "bag", "nothing"),
        requires_object("flight", "bag"),
        *lets_in("bag", "train", "flight"),
    ]
    locks = [lock("train", "alex"), lock("flight", "alex"), cap("money", "10.00 USD")]
    file = trip(
        ["alex"],
        ["desk", "gate", "away"],
        options,
        facts,
        locks,
        rights=True,
        budgets=[budget("money", "alex")],
        objects=["bag"],
    )
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    assert asked(found) == [(Unknown("another transfer", about="bag"),)]
    assert found.missing[0][0].at_hand_for == (
        ("train", "requires", True, True),
        ("flight", "requires", True, False),
    )
    words = report.as_text(file, found)
    assert (
        "The trip might work if another transfer puts bag at hand for flight, and leaves bag"
        " at hand for train."
    ) in words
    assert "  One plan that works then: alex buys a place from train-offer for 1.00 USD" in words
    assert "That is not settled." in words


def test_a_settled_case_comes_before_one_that_is_not_however_many_facts_it_holds() -> None:
    """Music and food are musts for Alex. The gala delivers both and requires the bag, which
    lies at the hotel. Supper delivers the food, and nobody said when it starts. Another
    transfer of the bag is one new thing, and might be enough. Another OPTION for the music
    is one new thing too, and with supper free to start it is sure to be enough. The report
    names that one: it asks one FACT more, and its answer gives a plan that works."""
    options = [stays("gala", "venue"), stays("supper", "venue")]
    facts = [
        *at("gala", 19),
        lasts("supper", "PT1H"),
        cutoff("supper", "PT0S"),
        satisfies("gala", "music"),
        satisfies("gala", "food"),
        satisfies("supper", "food"),
        satisfies("supper", "music", 0),
        lies_at("bag", "hotel"),
        requires_object("gala", "bag"),
        every_use("bag"),
    ]
    wants = [must("music", "alex"), must("food", "alex")]
    file = trip(["alex"], ["venue", "hotel"], options, facts, [], wants=wants, objects=["bag"])
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    settled_set = (
        Unknown("start", "supper"),
        Unknown("another option", want="music", person="alex"),
    )
    assert asked(found) == [settled_set]
    assert itineraries(file, with_these_at_best(file, [Unknown("another transfer", about="bag")]))
    assert "The trip works if" in report.as_text(file, found)


def test_another_option_is_named_before_another_transfer_in_words_and_in_json() -> None:
    """Lunch requires the bags, which lie at the hotel, and it does not deliver the music
    that is a must for Alex. The TRIP needs both new things. Nobody said whether lunch
    refuses the bags, and nobody has them, so another transfer has to leave it so."""
    file = trip(
        ["alex"],
        ["park", "hotel"],
        [stays("lunch", "park")],
        [
            *at("lunch", 12),
            lies_at("bags", "hotel"),
            requires_object("lunch", "bags"),
            satisfies("lunch", "music", 0),
        ],
        [lock("lunch", "alex")],
        wants=[must("music", "alex")],
        objects=["bags"],
    )
    found = checked(file)
    assert asked(found) == [
        (
            Unknown("another option", want="music", person="alex"),
            Unknown("another transfer", about="bags"),
        )
    ]
    assert (
        "The trip might work if another OPTION that SATISFIES music is found for alex and"
        " another transfer puts bags at hand for lunch, and leaves bags out of lunch if it"
        " refuses bags."
    ) in report.as_text(file, found)


def test_the_upper_bound_takes_its_conditions_from_anything_that_gives_them_once() -> None:
    file = two_desks()
    brought = iter([Unknown("another transfer", about="permit")])
    assert itineraries(file, no_better_than(file, brought))


def test_a_requirement_of_an_object_with_no_object_named_says_what_is_missing() -> None:
    wrong: Document = {"id": "f", "option": "check-in", "requires": {"needed": True}}
    assert "'object' is a required property" in problems(a_document(wrong))


def test_an_object_that_no_option_requires_puts_no_option_in_an_order() -> None:
    """The TRIP starts at 8:00 am. Alex's appointment at 10:00 am requires Alex's key. Sam's
    appointment can start at any time and keeps Sam's spare bag, which nothing requires. So
    Sam's appointment is tied to no other, and starts when the TRIP starts."""
    options = [stays("alex-appointment", "desk"), stays("sam-appointment", "desk")]
    facts = [
        *at("alex-appointment", 10),
        *whenever("sam-appointment"),
        has_object("alex", "key"),
        has_object("sam", "bag"),
        requires_object("alex-appointment", "key"),
        keeps("sam-appointment", "bag"),
        *(every_use(thing) for thing in ("key", "bag")),
        *(every_transfer(thing) for thing in ("key", "bag")),
    ]
    locks = [trip_starts(8), lock("alex-appointment", "alex"), lock("sam-appointment", "sam")]
    file = trip(["alex", "sam"], ["desk"], options, facts, locks, objects=["key", "bag"])
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert [(step.option, step.start) for step in found.itinerary] == [
        ("sam-appointment", seconds(8)),
        ("alex-appointment", seconds(10)),
    ]


# What the second review's FILEs showed.


def test_what_another_transfer_has_to_do_is_read_off_the_plan_that_the_rules_put_first() -> None:
    """Alex has the bag at the hotel and is LOCKed into a bag drop there, which keeps it, and
    into a check in the park at 10:00 am. Sam has a check at the hotel at 10:00 am. Both
    checks require the bag. Only an unlisted WAY leads to the park, and none leaves from
    9:00 am to 9:30 am. Nothing that the FILE lists brings the bag to the park.

    The drop is at 10:00 am, as late as it can be, in whichever order it comes with Sam's
    check. Sam's check is listed first in the FILE, so the plan with Sam's check first is
    the one shown. In it the bag is still with Alex at Sam's check, so the report says that
    another transfer has to put it at hand for both checks."""
    options = [stays("sam-check", "hotel"), stays("bag-drop", "hotel"), stays("alex-check", "park")]
    span = {
        "from": "hotel",
        "to": "park",
        "leaving": {"earliest": moment(9), "latest": moment(9, 30)},
    }
    facts = [
        *at("sam-check", 10),
        *whenever("bag-drop", "PT0S"),
        *at("alex-check", 10),
        starts_from("alex", "hotel"),
        starts_from("sam", "hotel"),
        {"id": "ways", "complete": span},
        has_object("alex", "bag"),
        requires_object("sam-check", "bag"),
        requires_object("alex-check", "bag"),
        keeps("bag-drop", "bag"),
        every_use("bag"),
    ]
    locks = [lock("sam-check", "sam"), lock("bag-drop", "alex"), lock("alex-check", "alex")]
    file = trip(["alex", "sam"], ["hotel", "park"], options, facts, locks, objects=["bag"])
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    assert asked(found) == [
        (
            Unknown("other ways", origin="hotel", destination="park"),
            Unknown("another transfer", about="bag"),
        )
    ]
    assert found.missing[0][1].at_hand_for == (
        ("sam-check", "requires", True, False),
        ("alex-check", "requires", True, False),
    )


def test_two_objects_that_have_nothing_to_do_with_each_other_have_two_orders() -> None:
    """The TRIP starts at 8:00 am. Alex's appointment at 10:00 am requires Alex's key. Sam's
    appointment can start at any time and requires Sam's bag. Neither OBJECT has anything to
    do with the other OPTION, so nothing ties Sam's appointment to Alex's: it starts when the
    TRIP starts."""
    options = [stays("alex-appointment", "desk"), stays("sam-appointment", "desk")]
    facts = [
        *at("alex-appointment", 10),
        *whenever("sam-appointment"),
        has_object("alex", "key"),
        has_object("sam", "bag"),
        requires_object("alex-appointment", "key"),
        requires_object("sam-appointment", "bag"),
        *(every_use(thing) for thing in ("key", "bag")),
        *(every_transfer(thing) for thing in ("key", "bag")),
    ]
    locks = [trip_starts(8), lock("alex-appointment", "alex"), lock("sam-appointment", "sam")]
    file = trip(["alex", "sam"], ["desk"], options, facts, locks, objects=["key", "bag"])
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert [(step.option, step.start) for step in found.itinerary] == [
        ("sam-appointment", seconds(8)),
        ("alex-appointment", seconds(10)),
    ]


def test_a_plan_with_its_steps_the_wrong_way_round_in_time_is_refused() -> None:
    """In a FILE that lists an OBJECT, a plan lists its steps in the order they happen. Alex
    walks to the gate at 9:00 am and back at 10:00 am. Listed the other way round, that is
    no plan, and no check puts it right."""
    ways = [way_between("walk", "hotel", "gate")]
    facts = [takes("walk", "PT30M"), starts_from("alex", "hotel"), every_use("key")]
    file = trip(["alex"], ["hotel", "gate"], [], facts, [], ways, objects=["key"])
    world = worst_case(file)
    out = Step(None, "hotel", "gate", ("alex",), seconds(9), seconds(9, 30), "walk")
    back = Step(None, "gate", "hotel", ("alex",), seconds(10), seconds(10, 30), "walk")
    assert broken(file, world, (out, back)) == []
    assert works_as_listed(file, world, (out, back))
    assert not works_as_listed(file, world, (back, out))
    for check in (broken, broken_as_listed):
        with pytest.raises(ValueError, match="in the order they happen"):
            check(file, world, (back, out))


def test_a_drop_that_is_listed_first_does_not_cover_an_earlier_check() -> None:
    """Alex has the key and drops it at a desk at 10:00 am. Sam needs it there at 9:00 am.
    Listed in the order they happen, Sam's check has no key. Listed with the drop first,
    that is no plan."""
    options = [stays("drop", "desk"), stays("need", "desk")]
    facts = [
        *at("drop", 10, length="PT0S"),
        *at("need", 9, length="PT0S"),
        has_object("alex", "key"),
        keeps("drop", "key"),
        requires_object("need", "key"),
        every_use("key"),
        every_transfer("key"),
    ]
    locks = [lock("drop", "alex"), lock("need", "sam")]
    file = trip(["alex", "sam"], ["desk"], options, facts, locks, objects=["key"])
    world = worst_case(file)
    drop = Step("drop", "desk", "desk", ("alex",), seconds(10), seconds(10))
    need = Step("need", "desk", "desk", ("sam",), seconds(9), seconds(9))
    assert broken(file, world, (need, drop)) == [
        Broken(Constraint.AT_HAND, "need", ("sam",), object="key")
    ]
    with pytest.raises(ValueError, match="in the order they happen"):
        broken(file, world, (drop, need))
    # The plan that works has Alex at Sam's check too, with the key.
    assert checked(file).itinerary[0].persons == ("alex", "sam")


def an_evening() -> File:
    """Music and shellfish are musts for Alex, and shellfish is a must-not for Sam. A cruise
    at 7:00 pm delivers both and requires a bag that lies at the hotel. Sam is LOCKed into
    an outing at 6:00 pm with no music, and nobody said whether it has shellfish."""
    options = [moves("cruise", "pier", "quay"), moves("outing", "quay", "cove")]
    facts = [
        *at("cruise", 19),
        *at("outing", 18),
        satisfies("cruise", "music"),
        satisfies("cruise", "shellfish"),
        satisfies("outing", "music", 0),
        lies_at("bag", "hotel"),
        requires_object("cruise", "bag"),
    ]
    wants = [must("music", "alex"), must("shellfish", "alex", never=["sam"])]
    places = ["pier", "quay", "cove", "hotel"]
    return trip(
        ["alex", "sam"],
        places,
        options,
        facts,
        [lock("outing", "sam")],
        wants=wants,
        objects=["bag"],
    )


def test_the_upper_bound_does_not_count_on_an_option_that_a_lock_makes_break_a_must_not() -> None:
    """If the outing has shellfish, Sam breaks a must-not in every plan. So no plan that
    works anywhere counts on the outing for Alex's shellfish, and neither does the bound."""
    file = an_evening()
    with_music = [Unknown("another option", want="music", person="alex")]
    assert not itineraries(file, no_better_than(file, with_music))
    # With Sam free to stay away, the outing could be Alex's shellfish.
    free = replace(file, decisions=())
    assert itineraries(free, no_better_than(free, with_music))


def test_looking_for_a_settled_case_takes_few_questions_where_none_can_be() -> None:
    """The report asks that the outing has no shellfish, and for another transfer of the bag.
    No settled set asks for as few new things, and the upper bound says so at once: the
    search does not go through every set of FACTs to find that out."""
    file = an_evening()
    asked_of_the_search = 0

    def counted(left: File, world: World) -> bool:
        nonlocal asked_of_the_search
        asked_of_the_search += 1
        return reference.any_works(left, world)

    found = answers.check(file, works=counted)
    assert asked(found) == [
        (
            Unknown("does not satisfy", "outing", want="shellfish"),
            Unknown("another transfer", about="bag"),
        )
    ]
    assert asked_of_the_search < 400


def test_whether_anything_works_is_settled_by_the_first_plan_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Six travelers are LOCKed into lunch in the park, and one of them carries the key that
    lunch requires. Only an unlisted WAY leads there, and four spans rule it out. Each
    traveler can leave in any of six ways around those spans. To say that something works,
    the first way is enough. To show a plan, every one is compared."""
    people = ["alex", "sam", "jo", "kit", "lee", "max"]
    closed = [
        {
            "id": f"closed-{number}",
            "complete": {
                "from": "hotel",
                "to": "park",
                "leaving": {
                    "earliest": moment(9, 15 * number),
                    "latest": moment(9, 15 * number + 5),
                },
            },
        }
        for number in range(4)
    ]
    facts = [
        *at("lunch", 12),
        *(starts_from(person, "hotel") for person in people),
        *closed,
        has_object("alex", "key"),
        requires_object("lunch", "key"),
        every_use("key"),
        every_transfer("key"),
    ]
    file = trip(
        people, ["hotel", "park"], [stays("lunch", "park")], facts, [lock("lunch", *people)],
        objects=["key"],
    )  # fmt: skip
    world = with_these_at_best(file, [Unknown("other ways", origin="hotel", destination="park")])
    timed = 0
    its_own = reference._times  # pyright: ignore[reportPrivateUsage]

    def counted(
        count: int,
        gaps: list[tuple[int, int, int]],
        fixed: dict[int, int],
        not_before: dict[int, int],
        no_later: dict[int, int],
    ) -> list[int] | None:
        nonlocal timed
        timed += 1
        return its_own(count, gaps, fixed, not_before, no_later)

    monkeypatch.setattr(reference, "_times", counted)
    assert reference.any_works(file, world)
    assert timed < 20
    found = answers.check(file)
    assert asked(found) == [(Unknown("other ways", origin="hotel", destination="park"),)]


# What the third review's FILEs showed.


def test_an_object_that_another_transfer_brings_still_has_an_order() -> None:
    """Alex has the bag and is LOCKed onto a bus to the park, which keeps the bag at the hotel
    when it leaves, and into a check in the park at noon. Sam is LOCKed onto a train from the
    hotel at 10:00 am. The train and the check require the bag, and nothing brings it to the
    park. The bus can leave at any time.

    With the bus before the train, it leaves at 10:00 am, and it is listed first: then the
    bag is at the hotel for the train. That plan comes first by the rules, so the report
    says that only the check in the park is not covered."""
    options = [
        moves("bus", "hotel", "park"),
        moves("train", "hotel", "park"),
        stays("check", "park"),
    ]
    facts = [
        *whenever("bus"),
        *at("train", 10),
        *at("check", 12),
        starts_from("alex", "hotel"),
        starts_from("sam", "hotel"),
        has_object("alex", "bag"),
        keeps("bus", "bag"),
        requires_object("train", "bag"),
        does_with("train", "bag", "nothing"),
        requires_object("check", "bag"),
        does_with("check", "bag", "nothing"),
        every_use("bag"),
    ]
    locks = [lock("bus", "alex"), lock("train", "sam"), lock("check", "alex"), trip_ends(12, 30)]
    file = trip(["alex", "sam"], ["hotel", "park"], options, facts, locks, objects=["bag"])
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    assert asked(found) == [(Unknown("another transfer", about="bag"),)]
    assert found.missing[0][0].at_hand_for == (
        ("train", "requires", True, True),
        ("check", "requires", True, False),
    )
    world = with_these_at_best(file, [Unknown("another transfer", about="bag")])
    shown = first_shown(file, world)
    assert shown is not None
    assert [(step.option, step.start) for step in shown] == [
        ("bus", seconds(10)),
        ("train", seconds(10)),
        ("check", seconds(12)),
    ]


def keys_on_a_desk(checks: int, keys: int, handed: bool = True) -> File:
    """So many checks at one desk at 10:00 am, each with its own PERSON, and so many keys
    lying there. Each check requires each key. With ``handed`` each check also hands each key
    over, so that where a key is turns on the order of the checks."""
    people = [f"person-{number}" for number in range(checks)]
    things = [f"key-{number}" for number in range(keys)]
    options = [stays(f"check-{number}", "desk") for number in range(checks)]
    facts = [fact for number in range(checks) for fact in at(f"check-{number}", 10, length="PT5M")]
    for thing in things:
        facts += [lies_at(thing, "desk"), every_use(thing), every_transfer(thing)]
        facts += [requires_object(f"check-{number}", thing) for number in range(checks)]
        if handed:
            facts += [hands_over(f"check-{number}", thing) for number in range(checks)]
    locks = [lock(f"check-{number}", people[number]) for number in range(checks)]
    return trip(people, ["desk"], options, facts, locks, objects=things)


def test_the_orders_of_two_objects_are_combined_only_where_they_can_go_together() -> None:
    """Each key gives the checks an order, and the orders have to agree: two that put two
    checks at one instant in opposite orders go round in a circle. With three checks and six
    keys there are six orders that agree. The search builds those, and not each of the
    46,656 ways to give every key an order of its own."""
    its_own = reference._chains  # pyright: ignore[reportPrivateUsage]
    for checks, keys, agree in ((2, 2, 2), (3, 6, 6)):
        file = keys_on_a_desk(checks, keys)
        world = worst_case(file)
        who = tuple((f"person-{number}",) for number in range(checks))
        orders = tuple((number,) for number in range(checks))
        chains = its_own(file, world, who, orders)
        assert chains is not None and len(list(chains)) == agree
        assert checked(file).answer is Answer.FEASIBLE


def test_a_way_is_tried_only_in_the_openings_that_the_times_of_the_trip_leave(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Six travelers are LOCKed into a lunch in the park that can start at any time. The TRIP
    starts at 9:47 am. Four spans rule the only WAY out, and three of them are over before
    the TRIP starts. So each traveler has one opening to leave in, and not five."""
    people = ["alex", "sam", "jo", "kit", "lee", "max"]
    closed = [
        {
            "id": f"closed-{number}",
            "complete": {
                "from": "hotel",
                "to": "park",
                "leaving": {
                    "earliest": moment(9, 15 * number),
                    "latest": moment(9, 15 * number + 5),
                },
            },
        }
        for number in range(4)
    ]
    facts = [
        *whenever("lunch", "PT30M"),
        *(starts_from(person, "hotel") for person in people),
        *closed,
        has_object("alex", "key"),
        requires_object("lunch", "key"),
        every_use("key"),
        every_transfer("key"),
    ]
    file = trip(
        people, ["hotel", "park"], [stays("lunch", "park")], facts,
        [trip_starts(9, 47), lock("lunch", *people)], objects=["key"],
    )  # fmt: skip
    world = with_these_at_best(file, [Unknown("other ways", origin="hotel", destination="park")])
    timed = 0
    its_own = reference._times  # pyright: ignore[reportPrivateUsage]

    def counted(
        count: int,
        gaps: list[tuple[int, int, int]],
        fixed: dict[int, int],
        not_before: dict[int, int],
        no_later: dict[int, int],
    ) -> list[int] | None:
        nonlocal timed
        timed += 1
        return its_own(count, gaps, fixed, not_before, no_later)

    monkeypatch.setattr(reference, "_times", counted)
    assert reference.any_works(file, world)
    assert timed <= 2**6


def test_an_order_that_the_fixed_starts_rule_out_is_not_tried() -> None:
    """Three PERSONs have checks at 9:00 am, 10:00 am and 11:00 am. Each check requires the
    key on the desk and hands it over. Only one order of the three keeps their times, so only
    that one is timed and checked."""
    people = ["alex", "sam", "jo"]
    options = [stays(f"check-{number}", "desk") for number in range(3)]
    facts = [fact for number in range(3) for fact in at(f"check-{number}", 11 - number)]
    facts += [lies_at("key", "desk"), every_use("key"), every_transfer("key")]
    facts += [requires_object(f"check-{number}", "key") for number in range(3)]
    facts += [hands_over(f"check-{number}", "key") for number in range(3)]
    locks = [lock(f"check-{number}", people[number]) for number in range(3)]
    file = trip(people, ["desk"], options, facts, locks, objects=["key"])
    who = tuple((person,) for person in people)
    orders = tuple((number,) for number in range(3))
    chains = reference._chains(file, worst_case(file), who, orders)  # pyright: ignore[reportPrivateUsage]
    assert chains is not None
    assert [gaps for gaps, _, _ in chains] == [[(2, 1, 0), (1, 0, 0)]]
    assert [step.option for step in checked(file).itinerary] == ["check-2", "check-1", "check-0"]


# What the fourth review's FILEs showed.


def test_an_opening_that_a_way_cannot_leave_in_times_nothing_else() -> None:
    """Alex takes a train to the desk at 10:00 am, joins Sam's meeting there, and has to be
    back in the park when the TRIP ends at 10:35 am. Sam has five minutes of prep before the
    meeting. Only an unlisted WAY leads back, and none leaves from 9:00 am to 9:05 am. Alex
    cannot leave before that span, so it times nothing: the prep is at 10:25 am, after the
    train starts. The train and the prep cost 1 USD each, and the cash has 1 USD. The
    purchases go in the order of the steps, so Alex's train takes the cash."""
    options = [moves("train", "park", "desk"), stays("prep", "desk"), stays("meeting", "desk")]
    span = {
        "from": "desk",
        "to": "park",
        "leaving": {"earliest": moment(9), "latest": moment(9, 5)},
    }
    facts = [
        *at("train", 10),
        *whenever("prep"),
        *whenever("meeting"),
        starts_from("alex", "park"),
        starts_from("sam", "desk"),
        {"id": "ways", "complete": span},
        needs_right("train"),
        offer("train", 1, price="1.00 USD"),
        needs_right("prep"),
        offer("prep", 1, price="1.00 USD"),
        needs_no_right("meeting"),
        lies_at("key", "desk"),
        requires_object("meeting", "key"),
        every_use("key"),
        every_transfer("key"),
    ]
    decisions = [
        trip_ends(10, 35),
        lock("train", "alex"),
        lock("prep", "sam"),
        lock("meeting", "alex", "sam"),
        cap("cash", "1.00 USD"),
    ]
    file = trip(
        ["alex", "sam"],
        ["park", "desk"],
        options,
        facts,
        decisions,
        wants=[ends_at("park", "alex")],
        rights=True,
        budgets=[budget("cash", "alex", "sam"), budget("card", "alex", "sam")],
        objects=["key"],
    )
    world = with_these_at_best(file, [Unknown("other ways", origin="desk", destination="park")])
    shown = first_shown(file, world)
    assert shown is not None
    assert [(step.option, step.start) for step in shown] == [
        ("train", seconds(10)),
        ("prep", seconds(10, 25)),
        ("meeting", seconds(10, 30)),
        (None, seconds(10, 35)),
    ]
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    assert [(cover.person, cover.option, cover.budget) for cover in found.plans[0].buys] == [
        ("alex", "train", "cash"),
        ("sam", "prep", "card"),
    ]


def test_an_opening_does_not_move_a_start_that_is_tied_to_no_fixed_time() -> None:
    """Sam has a check that takes a second and can start at any time, and has to end at
    home. The TRIP has no times. Only an unlisted WAY leads home, and none leaves in the first
    second of 1970. The check starts then, as the rule says, and Sam leaves a second later.
    Leaving before that second would put the check in 1969, and only a TRIP that ends too
    soon moves it there."""
    first_second = "1970-01-01T00:00:00+00:00[UTC]"
    span = {
        "from": "desk",
        "to": "home",
        "leaving": {"earliest": first_second, "latest": first_second},
    }
    facts = [
        *whenever("check", "PT1S"),
        starts_from("sam", "desk"),
        {"id": "ways", "complete": span},
        lies_at("key", "desk"),
        requires_object("check", "key"),
        every_use("key"),
        every_transfer("key"),
    ]
    file = trip(
        ["sam"], ["desk", "home"], [stays("check", "desk")], facts, [lock("check", "sam")],
        wants=[ends_at("home", "sam")], objects=["key"],
    )  # fmt: skip
    world = with_these_at_best(file, [Unknown("other ways", origin="desk", destination="home")])
    shown = first_shown(file, world)
    assert shown is not None
    assert [(step.option, step.start) for step in shown] == [("check", 0), (None, 1)]


def test_very_many_objects_need_no_deep_stack() -> None:
    """One check with a thousand keys lying on the desk. Nobody said that the check requires
    them, so at worst it requires each one, and each one has an order of its own."""
    things = [f"key-{number}" for number in range(1000)]
    facts = [*at("check", 10, length="PT0S"), *(lies_at(thing, "desk") for thing in things)]
    file = trip(
        ["alex"], ["desk"], [stays("check", "desk")], facts, [lock("check", "alex")], objects=things
    )
    assert answers.check(file).answer is Answer.FEASIBLE


def test_the_first_orders_that_go_together_answer_whether_anything_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Seven checks at one instant, each with its own PERSON, and two keys that each check
    requires. Each key gives the seven an order, and the two orders have to agree. The
    second is made to go with the first, so the first pair that is made is one that works,
    and whether anything works is settled by it."""
    file = keys_on_a_desk(7, 2)
    timed = 0
    its_own = reference._times  # pyright: ignore[reportPrivateUsage]

    def counted(
        count: int,
        gaps: list[tuple[int, int, int]],
        fixed: dict[int, int],
        not_before: dict[int, int],
        no_later: dict[int, int],
    ) -> list[int] | None:
        nonlocal timed
        timed += 1
        return its_own(count, gaps, fixed, not_before, no_later)

    monkeypatch.setattr(reference, "_times", counted)
    assert reference.any_works(file, worst_case(file))
    assert timed == 1


# What the fifth review's FILEs showed.

FIRST_SECOND = "1970-01-01T00:00:00+00:00[UTC]"


def the_way_home(*decisions: Document) -> File:
    """Sam starts at the desk and has to end at home. No WAY is listed, and none leaves in
    the first second of 1970."""
    span = {
        "from": "desk",
        "to": "home",
        "leaving": {"earliest": FIRST_SECOND, "latest": FIRST_SECOND},
    }
    facts = [starts_from("sam", "desk"), {"id": "ways", "complete": span}]
    return trip(
        ["sam"], ["desk", "home"], [], facts, list(decisions), wants=[ends_at("home", "sam")]
    )


def test_the_rule_for_which_start_is_shown_rules_no_start_out() -> None:
    """The TRIP ends in the first second of 1970, and no WAY leaves in that second. Sam can
    leave a second earlier. So the TRIP is UNDETERMINED: it turns on other WAYs home."""
    file = the_way_home({"id": "trip-end", "trip_ends_at": FIRST_SECOND})
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    assert asked(found) == [(Unknown("other ways", origin="desk", destination="home"),)]
    world = with_these_at_best(file, [Unknown("other ways", origin="desk", destination="home")])
    shown = first_shown(file, world)
    assert shown is not None and [step.start for step in shown] == [-1]


def test_the_solvers_choice_of_when_a_way_leaves_is_checked_as_it_chose() -> None:
    """With no end of the TRIP, Sam can leave before that second or after it. Whichever the
    solver takes, the reference checker times it there."""
    file = the_way_home()
    found = answers.check(file)
    assert found.answer is Answer.UNDETERMINED
    assert compiler.check(file) == found
    world = with_these_at_best(file, [Unknown("other ways", origin="desk", destination="home")])
    assert compiler.works(file, world)


def test_a_span_that_is_over_does_not_move_the_start_that_is_shown() -> None:
    """Sam goes home for a check that takes a second and requires the key lying there. The
    TRIP has no times. No WAY leaves three seconds before 1970, and that changes nothing:
    the WAY and the check start in the first second of 1970, as the rule says."""
    before = "1969-12-31T23:59:57+00:00[UTC]"
    span = {"from": "desk", "to": "home", "leaving": {"earliest": before, "latest": before}}
    facts = [
        *whenever("check", "PT1S"),
        starts_from("sam", "desk"),
        {"id": "ways", "complete": span},
        lies_at("key", "home"),
        requires_object("check", "key"),
        every_use("key"),
        every_transfer("key"),
    ]
    file = trip(
        ["sam"], ["desk", "home"], [stays("check", "home")], facts, [lock("check", "sam")],
        objects=["key"],
    )  # fmt: skip
    world = with_these_at_best(file, [Unknown("other ways", origin="desk", destination="home")])
    shown = first_shown(file, world)
    assert shown is not None
    assert [(step.option, step.start) for step in shown] == [(None, 0), ("check", 0)]


# What the sixth review's FILE showed. It has no OBJECT: it is about the rule for start times.


def test_a_way_that_cannot_leave_before_a_span_does_not_time_what_comes_before_it() -> None:
    """Sam has a class at the desk from 10:00 am to 10:30 am. Alex has five minutes of prep
    at home, joins Sam for a meeting at the desk, and has to end at home. No WAY is listed,
    and none leaves either way from 10:10 am to 10:30 am.

    The meeting is after the class, so Alex cannot be back before the span, and a return
    before it times nothing. Alex goes out just before the span, at 10:09:59 am, and the
    prep is five minutes before that. The class and the prep cost 1 USD each, and the cash
    has 1 USD. The class comes first in the plan, so Sam's place takes the cash."""
    options = [stays("class", "desk"), stays("prep", "home"), stays("meeting", "desk")]
    closed = [
        {
            "id": f"closed-{origin}",
            "complete": {
                "from": origin,
                "to": destination,
                "leaving": {"earliest": moment(10, 10), "latest": moment(10, 30)},
            },
        }
        for origin, destination in (("home", "desk"), ("desk", "home"))
    ]
    facts = [
        *at("class", 10),
        *whenever("meeting", "PT15M"),
        *whenever("prep"),
        starts_from("alex", "home"),
        starts_from("sam", "desk"),
        *closed,
        needs_right("class"),
        offer("class", 1, price="1.00 USD"),
        needs_right("prep"),
        offer("prep", 1, price="1.00 USD"),
        needs_no_right("meeting"),
    ]
    decisions = [
        lock("class", "sam"),
        lock("meeting", "alex", "sam"),
        lock("prep", "alex"),
        cap("cash", "1.00 USD"),
    ]
    file = trip(
        ["alex", "sam"],
        ["home", "desk"],
        options,
        facts,
        decisions,
        wants=[ends_at("home", "alex")],
        rights=True,
        budgets=[budget("cash", "alex", "sam"), budget("card", "alex", "sam")],
    )
    both_ways = [
        Unknown("other ways", origin="home", destination="desk"),
        Unknown("other ways", origin="desk", destination="home"),
    ]
    shown = first_shown(file, with_these_at_best(file, both_ways))
    assert shown is not None
    just_before = seconds(10, 10) - 1
    assert [(step.option, step.start) for step in shown] == [
        ("class", seconds(10)),
        ("prep", just_before - 300),
        (None, just_before),
        ("meeting", seconds(10, 30)),
        (None, seconds(10, 45)),
    ]
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    assert [(cover.person, cover.option, cover.budget) for cover in found.plans[0].buys] == [
        ("sam", "class", "cash"),
        ("alex", "prep", "card"),
    ]


# The solver.


def with_a_signature(rng: Random, file: File) -> File:
    """The same FILE, where an OPTION often requires a signature, and mostly one PERSON can sign.

    So whoever fetches the bags often needs the other PERSON there to sign.
    """
    people = [person.id for person in file.persons]
    signer = rng.choice(people)
    facts: list[Has | Requires | CompleteRequires] = [
        Has(f"{person}-signing", person, "signing", person == signer)
        for person in people
        if rng.random() < 0.9
    ]
    for option in file.options:
        of = rng.choice(["one", "one", "one", "each", "none", None])
        if of is not None:
            facts.append(Requires(f"{option.id}-signing", option.id, "signing", of))
    if rng.random() < 0.7:
        facts.append(CompleteRequires("every-signing", "signing"))
    listed = (Capability("signing", "signing"),)
    return replace(file, capabilities=listed, facts=(*file.facts, *facts))


def a_trip_with_a_key_to_sign_for(rng: Random) -> File:
    """A deposit and a check at a desk, a key, and signatures that the stays require.

    Mostly one PERSON can sign and another has the key. Mostly the check comes last, requires
    the key and lets in only those who can sign, and the deposit keeps the key and requires
    one signature. Sometimes the check refuses the key. Each of these is otherwise at random,
    and so is who is LOCKed in. So a stay often happens only for the key, and often needs a
    PERSON there who can sign and who can never have the key.
    """
    people = ["alex", "sam", "jo"][: rng.choice([2, 2, 3])]
    signers = [rng.choice(people)] if rng.random() < 0.7 else rng.sample(people, 2)
    others = [person for person in people if person not in signers]
    names = ["deposit", "counter", "check"] if rng.random() < 0.3 else ["deposit", "check"]
    options = [stays(name, rng.choice(["desk"] * 5 + ["vault"])) for name in names]
    facts: list[Document] = [takes("walk", "PT10M"), complete(None, None)]
    for number, name in enumerate(names):
        facts += at(name, 9 + number) if rng.random() < 0.8 else whenever(name)
        last = name == "check"
        does = rng.choice(
            [None, "nothing", "keeps"] if last else ["keeps"] * 3 + ["hands_over", None]
        )
        if does is not None:
            facts.append(does_with(name, "key", does))
        if rng.random() < (0.8 if last else 0.2):
            facts.append(requires_object(name, "key"))
        if last and rng.random() < 0.3:
            facts.append(refuses_object(name, "key"))
        of = rng.choice(["each"] * 3 + ["one", "none"] if last else ["one"] * 3 + ["each", "none"])
        facts.append(requires(name, "signing", of))
    holder = has_object(rng.choice(others if others and rng.random() < 0.7 else people), "key")
    facts.append(rng.choice([holder, holder, holder, lies_at("key", "desk")]))
    facts += [can(person, "signing", person in signers) for person in people]
    facts += [every_requirement("signing"), every_use("key")]
    facts += [every_transfer("key")] if rng.random() < 0.8 else []
    some = rng.sample(people, rng.randrange(1, len(people)))
    locks = [lock("check", *(signers if rng.random() < 0.6 else some))]
    if rng.random() < 0.2:
        locks.append(lock("deposit", rng.choice(people)))
    ways = [way_between("walk", "desk", "vault")]
    return trip(
        people,
        ["desk", "vault"],
        options,
        facts,
        locks,
        ways,
        capabilities=["signing"],
        objects=["key"],
    )


def trips_with_objects(rng: Random) -> list[File]:
    """Random trips of every kind the other tests build, each with OBJECTs."""
    trips = [a_trip_with_objects(rng, leave_out=0.12) for _ in range(120)]
    trips += [
        a_trip_with_objects(rng, leave_out=0.1, with_ways=0.8, with_complete=0.3)
        for _ in range(100)
    ]
    trips += [
        with_objects(
            rng,
            random_trip(rng, 0.15, ["alex", "sam"], with_wants=0.8, must_nots=0.3, whole_sets=0.4),
        )
        for _ in range(60)
    ]
    trips += [
        with_objects(rng, random_trip(rng, 0.15, ["alex", "sam"], with_rights=0.4))
        for _ in range(60)
    ]
    trips += [
        with_objects(
            rng,
            random_trip(rng, 0.1, ["alex", "sam"], with_ends=0.5, with_ways=0.8, with_times=0.5),
        )
        for _ in range(60)
    ]
    # A stay that happens for an OBJECT can require a CAPABILITY, and a right.
    trips += [with_a_signature(rng, a_trip_to_fetch(rng)) for _ in range(40)]
    trips += [a_trip_with_a_key_to_sign_for(rng) for _ in range(150)]
    trips += [
        with_capabilities(
            rng, with_objects(rng, random_trip(rng, 0.1, ["alex", "sam"], with_rights=0.4))
        )
        for _ in range(40)
    ]
    return trips


def test_the_compiler_and_the_reference_checker_agree_on_trips_with_objects() -> None:
    """The same answer ahead and the same Report for every TRIP."""
    rng = Random(6161)
    seen: set[Answer] = set()
    handed = carried = unsettled = 0
    for file in trips_with_objects(rng):
        series = list(answers.reports(file))
        assert list(compiler.reports(file)) == series
        found = series[-1]
        assert isinstance(found, Report)
        seen.add(found.answer)
        handed += any(step.handed for step in found.itinerary)
        carried += bool(found.objects)
        unsettled += any(
            needed.unknown.what == "another transfer"
            for enough in found.missing
            for needed in enough
        )
    assert seen == set(Answer)
    assert handed > 15
    assert carried > 60
    assert unsettled > 15


def test_the_two_searches_agree_in_every_kind_of_world_with_objects() -> None:
    """The same ITINERARY first, or none, in the worlds the answers and the evidence are built on.

    Those are the worst case, the best case, an upper bound, worlds in which a few unknown
    FACTs turn out well, and possible worlds chosen at random.
    """
    rng = Random(7171)
    found: set[bool] = set()
    handed = 0
    for file in trips_with_objects(rng)[::3]:
        for world in worlds_to_try(rng, file):
            first = reference.first_shown(file, world)
            assert compiler.shown(file, world) == first
            assert compiler.works(file, world) == (first is not None)
            found.add(first is not None)
            handed += any(step.handed for step in first or ())
    assert found == {True, False}
    assert handed > 20


def test_the_two_searches_agree_on_what_is_left_of_a_file_with_objects() -> None:
    """With records taken out one after another, as the search for a conflict takes them."""
    rng = Random(8181)
    answers_seen: set[bool] = set()
    reopened = 0
    for file in trips_with_objects(rng)[::3]:
        records = [*(fact.id for fact in file.facts), *(each.id for each in file.decisions)]
        records += [want.id for want in file.wants if want.musts or want.must_nots]
        left = Remaining(file)
        for record in rng.sample(records, min(len(records), 5)):
            left = left.without(record)
            can = reference.can_work(left)
            assert compiler.can_work(left) == can
            answers_seen.add(can)
            reopened += bool(left.might_do_anything())
    assert answers_seen == {True, False}
    assert reopened > 10


def test_the_solver_brings_whoever_has_an_object_into_a_stay() -> None:
    """Alex is LOCKed into an appointment that requires the key. Jo has the key. The solver
    considers whoever can have an OBJECT for a stay that requires it, so it finds the plan
    with Jo."""

    def appointment(start: Document) -> File:
        facts = [
            *at("appointment", 10),
            start,
            requires_object("appointment", "key"),
            every_use("key"),
            every_transfer("key"),
        ]
        locks = [lock("appointment", "alex")]
        options = [stays("appointment", "desk")]
        return trip(["alex", "jo"], ["desk", "vault"], options, facts, locks, objects=["key"])

    file = appointment(has_object("jo", "key"))
    shown = compiler.shown(file, worst_case(file))
    assert shown is not None and shown[0].persons == ("alex", "jo")
    # With the key at another PLACE, nobody can bring it.
    away = appointment(lies_at("key", "vault"))
    assert compiler.shown(away, worst_case(away)) is None
    assert checked(away).answer is Answer.INFEASIBLE


def test_many_appointments_with_one_object_are_quick_for_the_solver() -> None:
    """Eleven appointments in a row for one traveler, and the last requires the passport
    that the traveler carries. The reference checker would try every order of the eleven.
    The solver's own search gives the plan, and the reference checker only checks it."""
    count = 11
    options = [stays(f"stop-{number}", "desk") for number in range(count)]
    facts = [fact for number in range(count) for fact in at(f"stop-{number}", 8 + number)]
    facts += [
        has_object("alex", "passport"),
        requires_object(f"stop-{count - 1}", "passport"),
        every_use("passport"),
        every_transfer("passport"),
    ]
    locks = [lock(f"stop-{number}", "alex") for number in range(count)]
    file = trip(["alex"], ["desk"], options, facts, locks, objects=["passport"])
    found = compiler.check(file)
    assert found.answer is Answer.FEASIBLE
    assert len(found.itinerary) == count
    assert found.objects[0].uses == (Use(f"stop-{count - 1}", True, (Where(person="alex"),)),)


# What the review of the solver showed.


@pytest.mark.parametrize("stated", [True, False])
def test_an_object_that_nothing_moves_puts_no_option_in_an_order(stated: bool) -> None:
    """The key lies on the desk, and nothing hands it over or keeps it. Alex's check at
    10:00 am and Sam's check at any time both require it. Where it is turns on no order, so
    Sam's check is tied to nothing and starts when the TRIP starts. That is so too where
    the FILE does not state every transfer: a check might keep the key, but only from a
    PERSON who has it, and nobody can have it."""
    options = [stays("alex-check", "desk"), stays("sam-check", "desk")]
    facts = [
        *at("alex-check", 10),
        *whenever("sam-check"),
        lies_at("key", "desk"),
        requires_object("alex-check", "key"),
        requires_object("sam-check", "key"),
        every_use("key"),
        *([every_transfer("key")] if stated else []),
    ]
    locks = [trip_starts(8), lock("alex-check", "alex"), lock("sam-check", "sam")]
    file = trip(["alex", "sam"], ["desk"], options, facts, locks, objects=["key"])
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert [(step.option, step.start) for step in found.itinerary] == [
        ("sam-check", seconds(8)),
        ("alex-check", seconds(10)),
    ]


def test_eight_checks_of_a_key_that_nothing_moves_are_timed_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Eight PERSONs each have a check at 10:00 am that requires the key on the desk. The
    checks have 40,320 orders, and none of them matters: the key stays where it is."""
    file = keys_on_a_desk(8, 1, handed=False)
    timed = 0
    its_own = reference._times  # pyright: ignore[reportPrivateUsage]

    def counted(
        count: int,
        gaps: list[tuple[int, int, int]],
        fixed: dict[int, int],
        not_before: dict[int, int],
        no_later: dict[int, int],
    ) -> list[int] | None:
        nonlocal timed
        timed += 1
        return its_own(count, gaps, fixed, not_before, no_later)

    monkeypatch.setattr(reference, "_times", counted)
    assert answers.check(file).answer is Answer.FEASIBLE
    assert timed < 10


def test_the_hand_overs_shown_are_found_without_trying_every_choice() -> None:
    """Thirty stays at one desk, each with eight PERSONs, and each hands the key over. The
    first PERSON has the key, and the last stay requires it. There are more ways to hand the
    key about than could ever be tried: nine to the power of thirty. The rules put no
    hand-over first, and the search keeps only the first choice for each place the key can
    be, so it comes back at once."""
    people = [f"person-{number}" for number in range(8)]
    options = [stays(f"stay-{number}", "desk") for number in range(30)]
    facts = [has_object("person-0", "key"), requires_object("stay-29", "key")]
    facts += [hands_over(f"stay-{number}", "key") for number in range(30)]
    facts += [every_use("key"), every_transfer("key")]
    file = trip(people, ["desk"], options, facts, [], objects=["key"])
    world = worst_case(file)
    visits = [(option.id, tuple(people), "desk") for option in file.options]
    found = first_hand_overs(
        world, "key", visits, [frozenset({Where(person="person-0")})], lambda option, person: (0, 0)
    )
    assert found == [((), ())]
    # With the key on the desk and only the last PERSON in the last stay, one hand-over is
    # the fewest: to that PERSON, in the stay listed first.
    alone = [*visits[:-1], ("stay-29", ("person-7",), "office")]

    def by_position(option: str, person: str | None) -> tuple[int, int]:
        return (int(option.removeprefix("stay-")), people.index(person or ""))

    assert first_hand_overs(
        world, "key", alone, [frozenset({Where(place="desk")})], by_position
    ) == [(((0, 7),), ())]


def a_stay_with_a_voucher(
    *more: Document,
    start: Document,
    desk: Sequence[Document] | None = None,
    rights: bool = False,
    wants: Sequence[Document] = (),
    capabilities: Sequence[str] = (),
    others: Sequence[Document] = (),
    locks: Sequence[Document] = (),
) -> File:
    """Alex is LOCKed into an appointment at the hotel that requires the voucher. Sam starts
    at the station and has nothing to do. An hour before, the desk of the hotel is open.

    ``desk`` says when the desk is open, where that is not 9:00 am. With ``rights``, the
    story says whether the desk needs a right. ``others`` holds other OPTIONs, and ``locks``
    other LOCKs.
    """
    options = [stays("appointment", "hotel"), stays("desk", "hotel"), *others]
    facts = [
        *at("appointment", 10),
        *(at("desk", 9) if desk is None else desk),
        starts_from("alex", "hotel"),
        starts_from("sam", "station"),
        takes("walk", "PT5M"),
        start,
        requires_object("appointment", "voucher"),
        every_use("voucher"),
        every_transfer("voucher"),
        *([needs_no_right("appointment")] if rights else []),
        *more,
    ]
    ways = [way_between("walk", "hotel", "station")]
    places = ["hotel", "station"]
    return trip(
        ["alex", "sam"],
        places,
        options,
        facts,
        [lock("appointment", "alex"), *locks],
        ways,
        wants,
        rights=rights,
        capabilities=capabilities,
        objects=["voucher"],
    )


def left_out_of(file: File) -> set[tuple[int, int]]:
    """Each PERSON and OPTION that the solver's model of the worst case rules out."""
    return compiler._Search(file, worst_case(file)).left_out  # pyright: ignore[reportPrivateUsage]


def test_nobody_is_brought_to_a_stay_for_an_object_that_they_can_never_have() -> None:
    """The model considers a PERSON for a stay because of an OBJECT only where they can
    have it at some time. A voucher that lies at the hotel is nobody's. One that Alex carries
    is only Alex's. Where an OPTION hands it over, it can come to be anybody's who can take
    part there."""

    sam_at_the_appointment = (1, 0)
    lying = a_stay_with_a_voucher(start=lies_at("voucher", "hotel"))
    carried = a_stay_with_a_voucher(start=has_object("alex", "voucher"))
    passed_on = a_stay_with_a_voucher(
        hands_over("desk", "voucher"), start=lies_at("voucher", "hotel")
    )
    assert sam_at_the_appointment in left_out_of(lying)
    assert sam_at_the_appointment in left_out_of(carried)
    assert sam_at_the_appointment not in left_out_of(passed_on)
    for file in (lying, carried, passed_on):
        assert checked(file).answer is Answer.FEASIBLE


def test_a_stay_that_refuses_an_object_brings_nobody_for_the_object() -> None:
    """The desk hands the voucher over, so Sam can have it, and the model considers Sam for
    the appointment that requires it. Where the appointment refuses the voucher too, nobody
    who has it takes part, and whoever comes changes nothing about where it is. So the model
    does not consider Sam for it. Where the desk refuses the voucher, nobody takes it there,
    and Sam can never have it."""
    sam_at_the_appointment, sam_at_the_desk = (1, 0), (1, 1)
    lying = lies_at("voucher", "hotel")
    handed = hands_over("desk", "voucher")
    anybody = a_stay_with_a_voucher(handed, start=lying)
    assert not {sam_at_the_appointment, sam_at_the_desk} & left_out_of(anybody)
    refusing = a_stay_with_a_voucher(handed, refuses_object("appointment", "voucher"), start=lying)
    assert sam_at_the_appointment in left_out_of(refusing)
    assert sam_at_the_desk not in left_out_of(refusing)
    barred = a_stay_with_a_voucher(handed, refuses_object("desk", "voucher"), start=lying)
    assert {sam_at_the_appointment, sam_at_the_desk} <= left_out_of(barred)
    for file in (refusing, barred):
        assert checked(file).answer is Answer.FEASIBLE


def test_where_nobody_knows_who_has_an_object_the_model_considers_everybody() -> None:
    """The cloakroom keeps the bags. Where Alex has them, Sam has no reason to stop there.
    Where nobody knows who has them, Sam might, and so the model considers Sam too."""
    sam_at_the_cloakroom = (1, 0)
    assert sam_at_the_cloakroom in left_out_of(a_cloakroom(start=has_object("alex", "bags")))
    assert sam_at_the_cloakroom not in left_out_of(a_cloakroom())
    # Nobody has bags that lie at the museum.
    lying = left_out_of(a_cloakroom(start=lies_at("bags", "museum")))
    assert {(0, 0), sam_at_the_cloakroom} <= lying


def test_an_option_that_refuses_an_object_cannot_move_it() -> None:
    """The first appointment hands the passport over, and the second requires it. So the two
    have an order. Where the first refuses the passport, nobody takes it there: nothing can
    move it, and it puts no OPTION in an order. The same holds for one that keeps it."""
    orders = ((0,), (1,))
    ordered_by_it = reference._ordered_by  # pyright: ignore[reportPrivateUsage]
    # The OPTIONs that check the passport, with the first appointment refusing it. Where
    # the passport lies on the desk, Alex can never have it, and the refusal asks nothing.
    for does, start, checking in (
        (hands_over("first", "passport"), lies_at("passport", "desk"), (1,)),
        (keeps("first", "passport"), has_object("alex", "passport"), (0, 1)),
    ):
        file = a_desk(start, does, requires_object("second", "passport"))
        assert ordered_by_it(file, settled(file), orders, [0, 1], "passport") == ((1,), (0, 1))
        barred = a_desk(
            start,
            does,
            refuses_object("first", "passport"),
            requires_object("second", "passport"),
        )
        assert ordered_by_it(barred, settled(barred), orders, [0, 1], "passport") == (checking, ())


def test_the_compiler_asks_its_solver_about_a_file_with_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The COMPILER gives the reference checker's report, and it gets there with its own
    search: it does not hand a FILE with OBJECTs to the reference checker's search."""
    searched: list[object] = []
    its_own = answers.reports

    def recorded(file: File, *how: object, **named: object) -> Iterator[Answer | Report]:
        searched.append(how[0] if how else None)
        return its_own(file, *how, **named)  # type: ignore[arg-type]

    monkeypatch.setattr(answers, "reports", recorded)
    rng = Random(99)
    for _ in range(30):
        file = a_trip_to_fetch(rng)
        searched.clear()
        list(compiler.reports(file))
        assert searched == [compiler.shown]


def test_nobody_can_have_an_object_from_an_option_that_they_are_sure_to_be_out_of() -> None:
    """The desk hands the voucher over, an hour before Alex's appointment. Sam can have the
    voucher only by taking part at the desk. Where Sam is sure to be out of the desk, the
    model does not consider Sam for the appointment either: the desk needs a right that
    only Alex has, it requires of each PERSON a CAPABILITY that Sam lacks, it would give Sam
    what Sam must not get, or nobody knows when it is open."""
    sam_at_the_appointment = (1, 0)
    lying = lies_at("voucher", "hotel")
    handed = hands_over("desk", "voucher")
    anybody = a_stay_with_a_voucher(handed, start=lying)
    assert sam_at_the_appointment not in left_out_of(anybody)
    only_alex_has_a_right = a_stay_with_a_voucher(
        handed, needs_right("desk"), booking("desk", "alex"), every_right("desk"), start=lying,
        rights=True,
    )  # fmt: skip
    sam_cannot_sign = a_stay_with_a_voucher(
        handed, requires("desk", "signing", "each"), cannot("sam", "signing"),
        can("alex", "signing"), every_requirement("signing"), start=lying,
        capabilities=["signing"],
    )  # fmt: skip
    sam_must_not = a_stay_with_a_voucher(
        handed, satisfies("desk", "queueing"), every("queueing"), start=lying,
        wants=[must_not("queueing", "sam")],
    )  # fmt: skip
    never_open = a_stay_with_a_voucher(handed, start=lying, desk=[])
    for file in (only_alex_has_a_right, sam_cannot_sign, sam_must_not, never_open):
        assert sam_at_the_appointment in left_out_of(file)
        assert checked(file).answer is Answer.FEASIBLE
    # A right that Sam can still buy lets Sam in.
    sam_can_buy = a_stay_with_a_voucher(
        handed, needs_right("desk"), booking("desk", "alex"), offer("desk", 1), start=lying,
        rights=True,
    )  # fmt: skip
    assert sam_at_the_appointment not in left_out_of(sam_can_buy)


def a_key_to_deposit() -> File:
    """Alex has the key and cannot sign. Sam can. At 9:00 am the desk takes a key in, and
    that requires somebody who can sign. At 10:00 am Sam is LOCKed into a check that
    requires the key, and everybody at the check has to be able to sign."""
    options = [stays("deposit", "desk"), stays("check", "desk")]
    facts = [
        *at("deposit", 9),
        *at("check", 10),
        has_object("alex", "key"),
        keeps("deposit", "key"),
        requires_object("check", "key"),
        every_use("key"),
        every_transfer("key"),
        cannot("alex", "signing"),
        can("sam", "signing"),
        requires("deposit", "signing", "one"),
        requires("check", "signing", "each"),
        every_requirement("signing"),
    ]
    locks = [lock("check", "sam")]
    return trip(
        ["alex", "sam"], ["desk"], options, facts, locks, capabilities=["signing"], objects=["key"]
    )


def test_a_stay_that_happens_for_an_object_brings_whoever_meets_what_it_requires() -> None:
    """Alex cannot come to the check, so the key has to lie on the desk by then. Alex leaves
    it at the deposit, and Sam comes along to sign. No LOCK and no must takes anybody to the
    deposit: it happens for the key. The solver still considers Sam for it."""
    file = a_key_to_deposit()
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert [(step.option, step.persons) for step in found.itinerary] == [
        ("deposit", ("alex", "sam")),
        ("check", ("sam",)),
    ]
    assert compiler.check(file) == found


# What an OBJECT breaks: at which OPTION, which CONSTRAINT, and who was to have it there.
type Breaks = tuple[tuple[int, Constraint, str | None], ...]
type Trail = tuple[frozenset[Where], ...]  # where an OBJECT might be, step after step
type Run = tuple[Breaks, Trail, Trail]
# An OPTION, who takes part, where it starts, and the OPTIONs that are over by then.
type Visit = tuple[str, tuple[str, ...], str, frozenset[str]]
THE_CARRY = ""  # what a break names where a carry of the plan cannot be


def left_by(
    does: str, places: frozenset[Where], persons: Sequence[str], origin: str
) -> frozenset[Where]:
    """Where an OBJECT might be after an OPTION that keeps it, might keep it, or does neither."""
    held = frozenset(each for each in places if each.person in persons)
    there = frozenset({Where(place=origin)}) if held else frozenset[Where]()
    if does == "keeps":
        return (places - held) | there
    return places | there if does == "might_keep" else places


def every_way(
    world: World,
    thing: str,
    visits: Sequence[Visit],
    begins: Sequence[frozenset[Where]],
    handed: dict[str, str],
    carried: Iterable[str] = (),
    ends_at: dict[str, str] | None = None,
) -> Iterator[Run]:
    """Each way one OBJECT can go through the OPTIONs of a plan. Nothing is skipped.

    There is a way for each start: the places where the OBJECT might be then. An OPTION
    first finds an OBJECT that was carried at the PLACE where the carrying OPTION ends,
    where that OPTION is over. Then it checks what it requires and refuses. An OPTION that
    does whichever thing suits the plan gives a way in which it leaves the OBJECT alone,
    then one in which it keeps it, then one in which it hands it over, where the plan has a
    hand-over there, and then one in which it carries it, where the plan has a carry there.

    A hand-over of the plan that does not happen is broken: the OPTION does not hand the
    OBJECT over, or the OBJECT is not at hand, or the OPTION refuses it. A carry of the
    plan that does not happen is broken where the OPTION does not carry the OBJECT, or the
    OBJECT is not at hand. An OPTION that refuses the OBJECT takes it from nobody: it keeps
    nothing, and it carries the OBJECT only where no PERSON who takes part has it.

    Each way says what it breaks, where the OBJECT might be when the TRIP starts and after
    each OPTION, and where it might be just before each OPTION.
    """
    loaded_in = set(carried)
    lands_at = ends_at or {}
    kinds = {
        "nothing": ["leave"],
        "keeps": ["keep"],
        "might_keep": ["might"],
        "hands_over": ["hand"],
        "carries": ["carry"],
        "any": ["leave", "keep", "hand", "carry"],
    }

    def go(
        position: int, places: frozenset[Where], broke: Breaks, trail: Trail, seen: Trail
    ) -> Iterator[Run]:
        if position == len(visits):
            yield broke, trail, seen
            return
        option, persons, origin, over = visits[position]
        places = frozenset(
            Where(place=lands_at[each.option]) if each.option in over else each for each in places
        )
        seen = (*seen, places)
        held = any(each.person in persons for each in places)
        refused = (option, thing) in world.refuses
        at_hand = all(each.person in persons or each.place == origin for each in places)
        if (option, thing) in world.needs and not at_hand:
            broke = (*broke, (position, Constraint.AT_HAND, None))
        if refused and held:
            broke = (*broke, (position, Constraint.REFUSED, None))
        action = world.does.get((option, thing), "nothing")
        taker = handed.get(option)
        loaded = option in loaded_in
        for kind in kinds[action]:
            if action == "any" and kind == "hand" and taker is None:
                continue  # that is the way in which it leaves the OBJECT alone
            if action == "any" and kind == "carry" and not loaded:
                continue  # and so is this
            after, found = places, broke
            if kind in ("keep", "might") and not refused:
                after = left_by(
                    "keeps" if kind == "keep" else "might_keep", places, persons, origin
                )
            reach = all(each.person in persons or each.place == origin for each in after)
            if taker is not None:
                if kind == "hand" and reach and not refused:
                    after = frozenset({Where(person=taker)})
                else:
                    if refused:
                        found = (*found, (position, Constraint.REFUSED, taker))
                    if kind != "hand" or not reach:
                        found = (*found, (position, Constraint.AT_HAND, taker))
            if loaded:
                if kind == "carry" and reach and not (refused and held):
                    after = frozenset({Where(option=option)})
                elif kind != "carry" or not reach:
                    found = (*found, (position, Constraint.AT_HAND, THE_CARRY))
            yield from go(position + 1, after, found, (*trail, after), seen)

    for start in begins:
        yield from go(0, start, (), (start,), ())


def as_visits(
    visits: Sequence[Visit] | Sequence[tuple[str, tuple[str, ...], str]],
) -> list[reference._Visit]:  # pyright: ignore[reportPrivateUsage]
    """These OPTIONs as the reference checker takes them. With three parts, none is over."""
    made: list[reference._Visit] = []  # pyright: ignore[reportPrivateUsage]
    for option, persons, origin, *over in visits:
        ended = over[0] if over else frozenset[str]()
        made.append(reference._Visit(option, persons, origin, ended))  # pyright: ignore[reportPrivateUsage]
    return made


def least_broken(
    world: World,
    thing: str,
    visits: Sequence[Visit] | Sequence[tuple[str, tuple[str, ...], str]],
    begins: Sequence[frozenset[Where]],
    handed: dict[str, str],
    carried: Iterable[str] = (),
    ends_at: dict[str, str] | None = None,
) -> Run:
    """What the reference checker's own walk gives for these OPTIONs."""
    return reference._least_broken(  # pyright: ignore[reportPrivateUsage]
        world,
        thing,
        as_visits(visits),
        begins,
        handed,
        set(carried),
        ends_at or {},
    )


def first_hand_overs(
    world: World,
    thing: str,
    visits: Sequence[tuple[str, tuple[str, ...], str]],
    begins: Sequence[frozenset[Where]],
    rank: Callable[[str, str | None], tuple[int, int]],
    ends_at: dict[str, str] | None = None,
) -> list[tuple[tuple[tuple[int, int], ...], tuple[tuple[str, str], ...]]]:
    """Each choice of hand-overs and carries that the search keeps for these OPTIONs in order.

    Each comes with the arrivals it counts on, and the choice that the rules put first comes
    first. The list is empty where no choice works.
    """
    reached = reference._first_hand_overs(  # pyright: ignore[reportPrivateUsage]
        world,
        thing,
        as_visits(visits),
        begins,
        rank,
        ends_at or {},
    )
    return reference._first_of(reached)  # pyright: ignore[reportPrivateUsage]


def test_the_way_an_object_goes_is_found_without_trying_every_way() -> None:
    """Where a world leaves the start to pick, or lets an OPTION do whichever thing suits the
    plan, an OBJECT can go many ways. The check takes the way that breaks the least, and the
    first of those. It keeps one way for each set of places the OBJECT might be in, and that
    gives the way that trying every one of them gives."""
    rng = Random(4242)
    people, places = ["alex", "sam", "jo"], ["desk", "vault"]
    base = worst_case(trip(people, places, [stays("stay", "desk")], [], []))
    anywhere = [*(Where(person=each) for each in people), *(Where(place=each) for each in places)]
    anywhere.append(Where())
    # The start is one place, or the world's to pick, or nobody knows it: every place at once.
    starts = [
        [frozenset({Where(person="alex")})],
        [frozenset({Where(place="desk")})],
        [frozenset({Where()})],
        [frozenset({each}) for each in anywhere],
        [frozenset(anywhere)],
    ]
    several = broke = picked = barred = aboard = landed = 0
    for _ in range(1500):
        stays_there = [
            (f"stay-{number}", tuple(rng.sample(people, rng.randrange(1, 4))), rng.choice(places))
            for number in range(rng.randrange(1, 8))
        ]
        # Each stay is over from some later stay on, or from none of them.
        over_from = {
            option: rng.choice([None, *range(number + 1, len(stays_there))])
            for number, (option, _, _) in enumerate(stays_there)
        }
        visits = [
            (
                option,
                persons,
                origin,
                frozenset(
                    other
                    for other, since in over_from.items()
                    if since is not None and since <= number
                ),
            )
            for number, (option, persons, origin) in enumerate(stays_there)
        ]
        ends_at = {option: rng.choice(places) for option, _, _ in stays_there}
        kinds = ["keeps", "might_keep", "hands_over", "carries", "carries", "any", "any"]
        does = {
            (option, "key"): rng.choice(kinds) for option, _, _ in stays_there if rng.random() < 0.8
        }
        needs = frozenset((option, "key") for option, _, _ in stays_there if rng.random() < 0.4)
        refuses = frozenset((option, "key") for option, _, _ in stays_there if rng.random() < 0.3)
        handed = {option: rng.choice(people) for option, _, _ in stays_there if rng.random() < 0.25}
        carried = {option for option, _, _ in stays_there if rng.random() < 0.3}
        begins = rng.choice(starts)
        world = replace(base, needs=needs, refuses=refuses, does=does)
        ways = list(every_way(world, "key", visits, begins, handed, carried, ends_at))
        first = min(ways, key=lambda way: len(way[0]))
        found = least_broken(world, "key", visits, begins, handed, carried, ends_at)
        assert found == first
        several += len(ways) > 1
        broke += bool(first[0])
        picked += len({way[0] for way in ways}) > 1
        barred += any(why is Constraint.REFUSED for _, why, _ in first[0])
        in_a_stay = [any(each.option for each in places) for places in first[1]]
        aboard += any(in_a_stay)
        landed += any(was and not still for was, still in pairwise(in_a_stay))
    assert several > 500 and broke > 300 and picked > 300 and barred > 200
    assert aboard > 150 and landed > 60


def test_many_sessions_that_might_do_anything_are_gone_through_once() -> None:
    """Sixty sessions at one desk, and each does whichever thing suits the plan: it keeps the
    badge that Alex carries or leaves it alone. The last requires the badge. There are more
    ways for the badge to go than could ever be tried: two to the power of sixty."""
    count = 60
    visits = [(f"session-{number}", ("alex",), "desk") for number in range(count)]
    base = worst_case(trip(["alex"], ["desk", "vault"], [stays("stay", "desk")], [], []))
    world = replace(
        base,
        needs=frozenset({(f"session-{count - 1}", "badge")}),
        does={(option, "badge"): "any" for option, _, _ in visits},
    )
    broke, trail, _ = least_broken(world, "badge", visits, [frozenset({Where(person="alex")})], {})
    assert broke == ()
    assert set(trail) == {frozenset({Where(person="alex")})}
    # Somewhere else, the last session is one that breaks. With the badge at the vault,
    # nothing brings it, and the first way is the one in which every session leaves it alone.
    away = [("session-0", ("alex",), "desk"), *visits[1:-1], (visits[-1][0], ("alex",), "vault")]
    broke, trail, _ = least_broken(world, "badge", away, [frozenset({Where(place="desk")})], {})
    assert broke == ((count - 1, Constraint.AT_HAND, None),)
    assert set(trail) == {frozenset({Where(place="desk")})}


def test_a_conference_with_a_badge_is_reported_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Alex is LOCKed into twenty-four sessions and has the badge. Only the first session
    requires it. Nobody said what the sessions do with it, or whether the last one needs a
    right. The report says that the trip turns on that right, and it goes through the
    sessions a few times, where the ways the badge could go are millions."""
    count = 24
    options = [stays(f"session-{number}", "hall") for number in range(count)]
    facts = [
        fact
        for number in range(count)
        for fact in at(f"session-{number}", 8 + number // 3, 20 * (number % 3), "PT15M")
    ]
    facts += [needs_no_right(f"session-{number}") for number in range(count - 1)]
    facts += [has_object("alex", "badge"), requires_object("session-0", "badge")]
    facts += [every_use("badge")]
    locks = [lock(f"session-{number}", "alex") for number in range(count)]
    file = trip(["alex"], ["hall"], options, facts, locks, rights=True, objects=["badge"])
    gone = 0
    its_own = reference._left  # pyright: ignore[reportPrivateUsage]

    def counted(*given: object) -> frozenset[Where]:
        nonlocal gone
        gone += 1
        return its_own(*given)  # type: ignore[arg-type]

    monkeypatch.setattr(reference, "_left", counted)
    found = compiler.check(file)
    assert found.answer is Answer.UNDETERMINED
    assert [needed.unknown.what for enough in found.missing for needed in enough] == [
        "needs no right"
    ]
    assert gone < 5_000


def a_voucher_on_the_desk(*more: Document) -> File:
    """Four travelers are LOCKed into four, three, two and two sessions at one hotel, each at
    any time. The voucher lies on the desk, and only the last session requires it."""
    sessions = {"alex": 4, "sam": 3, "jo": 2, "kim": 2}
    names = [f"{person}-{number}" for person, count in sessions.items() for number in range(count)]
    options = [stays(name, "hotel") for name in names]
    facts = [fact for name in names for fact in whenever(name, "PT30M")]
    facts += [lies_at("voucher", "hotel"), requires_object(names[-1], "voucher")]
    facts += [every_use("voucher"), *more]
    locks = [trip_starts(8), *(lock(name, name.split("-")[0]) for name in names)]
    return trip(list(sessions), ["hotel"], options, facts, locks, objects=["voucher"])


def test_an_object_that_nobody_can_have_puts_no_option_in_an_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nobody said what a session does with the voucher, so each might keep it. But a session
    keeps it only from a PERSON who has it, and nobody has it: it lies on the desk, and
    nothing hands it over. So it stays there, and the 69,300 orders of the sessions are not
    tried. The plan is timed as often as where the FILE states every transfer."""
    timed = 0
    its_own = reference._times  # pyright: ignore[reportPrivateUsage]

    def counted(
        count: int,
        gaps: list[tuple[int, int, int]],
        fixed: dict[int, int],
        not_before: dict[int, int],
        no_later: dict[int, int],
    ) -> list[int] | None:
        nonlocal timed
        timed += 1
        return its_own(count, gaps, fixed, not_before, no_later)

    monkeypatch.setattr(reference, "_times", counted)
    stated = answers.check(a_voucher_on_the_desk(every_transfer("voucher")))
    with_every_transfer_stated, timed = timed, 0
    found = answers.check(a_voucher_on_the_desk())
    assert timed == with_every_transfer_stated
    assert found.answer is stated.answer is Answer.FEASIBLE
    assert found.itinerary == stated.itinerary
    assert compiler.check(a_voucher_on_the_desk()) == found


def test_an_option_that_keeps_an_object_from_whoever_has_it_is_in_the_order() -> None:
    """Two appointments at one desk at 10:00 am. Alex has the bag. Sam's appointment requires
    it, and Alex's keeps it. Alex's can take the bag from Alex, so the two have an order, and
    the plan that works has Alex's first, though the FILE lists Sam's first. Where Jo has
    the bag instead, Alex's appointment keeps it from nobody, and nothing brings it."""

    def appointments(holder: str) -> File:
        options = [stays("sam-uses", "desk"), stays("alex-leaves", "desk")]
        facts = [
            *at("sam-uses", 10),
            *at("alex-leaves", 10, length="PT0S"),
            has_object(holder, "bag"),
            requires_object("sam-uses", "bag"),
            keeps("alex-leaves", "bag"),
            every_use("bag"),
            every_transfer("bag"),
        ]
        locks = [lock("sam-uses", "sam"), lock("alex-leaves", "alex")]
        return trip(["alex", "sam", "jo"], ["desk"], options, facts, locks, objects=["bag"])

    found = checked(appointments("alex"))
    assert found.answer is Answer.FEASIBLE
    assert [step.option for step in found.itinerary] == ["alex-leaves", "sam-uses"]
    with_jo = checked(appointments("jo"))
    assert with_jo.answer is Answer.FEASIBLE
    assert [(step.option, step.persons) for step in with_jo.itinerary] == [
        ("sam-uses", ("sam", "jo")),
        ("alex-leaves", ("alex",)),
    ]


def test_a_hand_over_of_the_plan_is_left_undone_where_that_breaks_less() -> None:
    """The key lies on the desk. The plan hands it to Alex at 9:00 am. At 10:00 am Sam's stay
    requires it, and the plan hands it to Sam there. In a world where the first stay does
    whichever thing suits, the least that breaks is one thing: the first stay does not hand
    the key over, and then Sam finds it on the desk. With it handed to Alex, both of Sam's
    would break."""
    base = worst_case(trip(["alex", "sam"], ["desk"], [stays("stay", "desk")], [], []))
    world = replace(
        base,
        needs=frozenset({("at-ten", "key")}),
        does={("at-nine", "key"): "any", ("at-ten", "key"): "hands_over"},
    )
    visits = [("at-nine", ("alex",), "desk"), ("at-ten", ("sam",), "desk")]
    handed = {"at-nine": "alex", "at-ten": "sam"}
    on_the_desk = frozenset({Where(place="desk")})
    broke, trail, _ = least_broken(world, "key", visits, [frozenset({Where(place="desk")})], handed)
    assert broke == ((0, Constraint.AT_HAND, "alex"),)
    assert trail == (on_the_desk, on_the_desk, frozenset({Where(person="sam")}))


def five_at_each_hour(deposit_last: bool, stamp: int = 0) -> File:
    """Five travelers, each LOCKed into an appointment of their own at one desk at 9:00 am, at
    10:00 am and at 11:00 am. One traveler has the voucher, and their appointment at 9:00 am
    keeps it at the desk. Every other appointment requires it. The FILE lists that traveler's
    appointments first, or with ``deposit_last`` last, among those of each hour. With
    ``stamp``, the appointment listed first also requires a stamp that lies on the desk, and
    can hand it over. With ``stamp`` at two, the same traveler's next appointment requires
    the stamp too."""
    people = [f"person-{number}" for number in range(5)]
    listed = [*people[1:], people[0]] if deposit_last else people
    names = [f"{person}-at-{hour}" for hour in (9, 10, 11) for person in listed]
    options = [stays(name, "desk") for name in names]
    facts = [fact for name in names for fact in at(name, int(name.rsplit("-", 1)[1]))]
    facts += [has_object("person-0", "voucher"), keeps("person-0-at-9", "voucher")]
    facts += [requires_object(name, "voucher") for name in names if name != "person-0-at-9"]
    facts += [every_use("voucher"), every_transfer("voucher")]
    if stamp:
        facts += [lies_at("stamp", "desk"), requires_object(names[0], "stamp")]
        facts += [hands_over(names[0], "stamp"), every_use("stamp"), every_transfer("stamp")]
        facts += [requires_object(names[5], "stamp")] if stamp > 1 else []
    locks = [lock(name, name.split("-at-")[0]) for name in names]
    things = ["voucher", "stamp"] if stamp else ["voucher"]
    return trip(people, ["desk"], options, facts, locks, objects=things)


def test_an_order_is_given_up_at_the_first_option_where_the_object_is_not_at_hand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fifteen appointments, five at each hour. The deposit of the voucher has to come first
    at 9:00 am: every other appointment requires the voucher on the desk. Where the FILE
    lists the deposit last of the five, an order that starts with another appointment is
    given up there, with the millions of orders that start the same way. So the first
    answer takes as few steps as where the FILE lists the deposit first."""
    gone = 0
    its_own = reference._one_further  # pyright: ignore[reportPrivateUsage]

    def counted(*how: object) -> object:
        nonlocal gone
        gone += 1
        return its_own(*how)  # type: ignore[arg-type]

    monkeypatch.setattr(reference, "_one_further", counted)
    for deposit_last in (False, True):
        gone = 0
        file = five_at_each_hour(deposit_last)
        assert reference.any_works(file, worst_case(file))
        assert gone < 100


def a_register_and_a_voucher() -> File:
    """Four travelers, each LOCKed into an appointment of their own at one desk at each hour
    from 9:00 am to noon. Every appointment requires the register that lies on the desk. One
    traveler has the voucher, and their appointment at 9:00 am keeps it at the desk and can
    hand the register over. Every other appointment requires the voucher. The FILE lists the
    register first, and that traveler's appointments last among those of each hour."""
    people = [f"person-{number}" for number in range(4)]
    names = [
        f"{person}-at-{hour}" for hour in (9, 10, 11, 12) for person in (*people[1:], people[0])
    ]
    deposit = "person-0-at-9"
    options = [stays(name, "desk") for name in names]
    facts = [fact for name in names for fact in at(name, int(name.rsplit("-", 1)[1]))]
    facts += [lies_at("register", "desk"), hands_over(deposit, "register")]
    facts += [requires_object(name, "register") for name in names]
    facts += [has_object("person-0", "voucher"), keeps(deposit, "voucher")]
    facts += [requires_object(name, "voucher") for name in names if name != deposit]
    facts += [every_use("register"), every_transfer("register")]
    facts += [every_use("voucher"), every_transfer("voucher")]
    locks = [lock(name, name.split("-at-")[0]) for name in names]
    return trip(people, ["desk"], options, facts, locks, objects=["register", "voucher"])


def a_key_check_after_breakfast() -> File:
    """Alex has breakfast from 8:45 am to 9:30 am, and a key check at any time. Four other
    guests each have a key check at each hour from 9:00 am to noon. Each key check requires
    the key that lies at the desk and can hand it over. Each stay lets in only the guest who
    is LOCKed into it. The TRIP starts at 8:45 am. The FILE lists Alex's key check first."""
    guests = [f"guest-{number}" for number in range(4)]
    checks = [f"{guest}-at-{hour}" for hour in (9, 10, 11, 12) for guest in guests]
    names = ["alex-check", "breakfast", *checks]
    options = [stays(name, "desk") for name in names]
    facts = [*whenever("alex-check"), *at("breakfast", 8, 45, "PT45M")]
    facts += [fact for name in checks for fact in at(name, int(name.rsplit("-", 1)[1]), 0, "PT5M")]
    facts += [lies_at("key", "desk"), every_use("key"), every_transfer("key")]
    for name in ("alex-check", *checks):
        facts += [requires_object(name, "key"), hands_over(name, "key")]
    whose = {"alex-check": "alex", "breakfast": "alex"}
    whose.update({name: name.split("-at-")[0] for name in checks})
    for name, guest in whose.items():
        facts += [needs_right(name), booking(name, guest), every_right(name)]
    locks = [trip_starts(8, 45), *(lock(name, guest) for name, guest in whose.items())]
    return trip(["alex", *guests], ["desk"], options, facts, locks, rights=True, objects=["key"])


def test_the_first_answer_checks_the_plan_in_the_order_the_solver_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The solver's own search has every OPTION that matters to an OBJECT in an order that
    works. To answer whether anything works, the reference checker tries that order first,
    and it works. So it does not look for an order itself.

    Its own search would take long in both of these FILEs. In the first, an order of the
    register's appointments is made in full before the voucher rules out how it starts. In
    the second, Alex's key check is tried before the checks at 9:00 am, where breakfast
    leaves no time for it, with every order of the checks that come later."""
    timed = gone = 0
    times, further = reference._times, reference._one_further  # pyright: ignore[reportPrivateUsage]

    def counted_times(*how: object) -> object:
        nonlocal timed
        timed += 1
        return times(*how)  # type: ignore[arg-type]

    def counted_further(*how: object) -> object:
        nonlocal gone
        gone += 1
        return further(*how)  # type: ignore[arg-type]

    monkeypatch.setattr(reference, "_times", counted_times)
    monkeypatch.setattr(reference, "_one_further", counted_further)
    for file in (a_register_and_a_voucher(), a_key_check_after_breakfast()):
        timed = gone = 0
        assert compiler.works(file, worst_case(file))
        assert timed == 1
        assert gone < 100
    # The reference checker works out the hand-overs for the solver's order itself. Here
    # Alex has to take the voucher at the desk of the hotel, and that is found at once too.
    carried = a_stay_with_a_voucher(
        hands_over("desk", "voucher"),
        *at("visit", 11),
        requires_object("visit", "voucher"),
        start=lies_at("voucher", "hotel"),
        others=[stays("visit", "station")],
        locks=[lock("visit", "alex")],
    )
    timed = 0
    assert compiler.works(carried, worst_case(carried))
    assert timed == 1
    found = checked(carried)
    assert [(step.option, step.handed) for step in found.itinerary if step.handed] == [
        ("desk", (("voucher", "alex"),))
    ]


def test_the_first_hand_overs_are_taken_wherever_they_leave_the_object() -> None:
    """The key lies on the desk, and the last stay requires it at the office. Two ways bring
    it there, and they leave it with different PERSONs. The search keeps one way for each
    PERSON, and then takes the way that the rules put first: the fewest hand-overs, and not
    the way that starts in the OPTION listed first, or the way that was found first."""
    base = worst_case(trip(["alex", "sam", "jo"], ["desk"], [stays("stay", "desk")], [], []))
    names = ["first", "second", "third", "use"]
    world = replace(
        base,
        needs=frozenset({("use", "key")}),
        does={(name, "key"): "hands_over" for name in names[:3]},
    )
    people = ["alex", "sam", "jo"]

    def by_position(option: str, person: str | None) -> tuple[int, int]:
        return (names.index(option), people.index(person or ""))

    def the_first(third: tuple[str, ...], use: tuple[str, ...]) -> object:
        visits = [
            ("first", ("sam",), "desk"),
            ("second", ("alex",), "desk"),
            ("third", third, "lobby"),
            ("use", use, "office"),
        ]
        found = first_hand_overs(
            world, "key", visits, [frozenset({Where(place="desk")})], by_position
        )
        return [taken for taken, _ in found]

    # Alex takes it in the second stay and brings it: one hand-over. Or Sam takes it in the
    # first stay and hands it to Jo in the third: two, and they start in the stay listed first.
    assert the_first(("sam", "jo"), ("alex", "jo")) == [((1, 0),)]
    # Sam takes it in the first stay and brings it: one hand-over. Or Alex takes it in the
    # second and hands it to Jo in the third: two, and that way is found before the other.
    assert the_first(("alex", "jo"), ("sam", "jo")) == [((0, 1),)]


def test_an_object_that_is_out_of_reach_for_good_is_seen_before_anything_is_timed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The key lies at the vault, and nothing hands it over or keeps it. Alex's appointment
    at the desk requires it. No order and no route changes that, so the choice is given up
    before any start time is worked out."""
    options = [stays("appointment", "desk")]
    facts = [
        *at("appointment", 10),
        lies_at("key", "vault"),
        requires_object("appointment", "key"),
        every_use("key"),
        every_transfer("key"),
    ]
    locks = [lock("appointment", "alex")]
    file = trip(["alex"], ["desk", "vault"], options, facts, locks, objects=["key"])
    timed = 0
    its_own = reference._times  # pyright: ignore[reportPrivateUsage]

    def counted(*how: object) -> object:
        nonlocal timed
        timed += 1
        return its_own(*how)  # type: ignore[arg-type]

    monkeypatch.setattr(reference, "_times", counted)
    assert not reference.any_works(file, worst_case(file))
    assert timed == 0


def answered_at_once(search: compiler._Search) -> tuple[bool, int]:  # pyright: ignore[reportPrivateUsage]
    """Whether anything works in a model, and how many conflicts the solver went through.

    The solver gives the same count every time. It gives up after a thousand conflicts,
    and the test fails here: an answer that takes more is not one the solver sees at once.
    """
    solver = compiler._solver(relax=False)  # pyright: ignore[reportPrivateUsage]
    solver.parameters.max_number_of_conflicts = 1000
    status = solver.solve(search.model)
    assert status != cp_model.UNKNOWN, "the solver went through a thousand conflicts"
    return search.read(solver, status) is not None, solver.num_conflicts


def conflicts_to_answer(file: File) -> tuple[bool, int]:
    """Whether anything works in the worst case by the solver's own search, and how many
    conflicts the solver went through to say so."""
    search = compiler._Search(file, worst_case(file), plain=True)  # pyright: ignore[reportPrivateUsage]
    return answered_at_once(search)


def a_register_at_two_places(airport_at: int = 9, guests: int = 11) -> File:
    """Eleven guests each have an appointment at the hotel desk at 9:00 am, and a clerk has
    one at the airport. Every appointment requires the register, which lies at the hotel.
    Each appointment at the hotel can hand it over. A shuttle takes 15 minutes."""
    people = [f"guest-{number}" for number in range(guests)]
    desks = [f"{person}-desk" for person in people]
    options = [*(stays(desk, "hotel") for desk in desks), stays("airport-desk", "airport")]
    facts = [fact for desk in desks for fact in at(desk, 9)]
    facts += [*at("airport-desk", airport_at), starts_from("clerk", "airport")]
    facts += [starts_from(person, "hotel") for person in people]
    facts += [takes("shuttle", "PT15M"), complete(None, None)]
    facts += [lies_at("register", "hotel"), requires_object("airport-desk", "register")]
    for desk in desks:
        facts += [hands_over(desk, "register"), requires_object(desk, "register")]
    facts += [every_use("register"), every_transfer("register")]
    locks = [lock(desk, person) for desk, person in zip(desks, people, strict=True)]
    locks.append(lock("airport-desk", "clerk"))
    ways = [way_between("shuttle", "hotel", "airport")]
    places = ["hotel", "airport"]
    return trip([*people, "clerk"], places, options, facts, locks, ways, objects=["register"])


def a_pass_at_the_hotel(hour: int, minute: int) -> File:
    """Alex is LOCKed into an admission at the hall at 4:00 pm that requires the pass. The
    pass lies at the hotel, where a pickup of half an hour hands it over. Nine counters at
    the hall, each at any time, can hand it over too. The walk takes 15 minutes."""
    counters = [f"counter-{number}" for number in range(9)]
    options = [stays("admission", "hall"), stays("pickup", "hotel")]
    options += [stays(name, "hall") for name in counters]
    facts = [*at("admission", 16), *at("pickup", hour, minute)]
    for name in counters:
        facts += [*whenever(name), hands_over(name, "pass")]
    facts += [starts_from("alex", "hotel"), takes("walk", "PT15M"), complete(None, None)]
    facts += [lies_at("pass", "hotel"), hands_over("pickup", "pass")]
    facts += [requires_object("admission", "pass"), every_use("pass"), every_transfer("pass")]
    ways = [way_between("walk", "hotel", "hall")]
    locks = [lock("admission", "alex")]
    return trip(["alex"], ["hotel", "hall"], options, facts, locks, ways, objects=["pass"])


def test_an_object_cannot_be_at_hand_in_two_places_with_no_time_to_cross() -> None:
    """The register is required at the hotel and at the airport at 9:00 am, and the shuttle
    takes 15 minutes. The model says outright that the two are at least that far apart, so
    the solver need not try each guest as the one who carries the register. An hour later
    at the airport, there is time, and a guest brings it."""
    works, conflicts = conflicts_to_answer(a_register_at_two_places())
    assert not works
    assert conflicts < 1000
    works, conflicts = conflicts_to_answer(a_register_at_two_places(airport_at=10))
    assert works
    assert conflicts < 1000


def test_an_object_leaves_the_place_where_it_lies_only_by_a_hand_over_there() -> None:
    """The pass lies at the hotel, and the admission at the hall requires it at 4:00 pm. A
    pickup at the hotel at 4:30 pm is too late, and the counters at the hall hand over only
    what is at hand there. The model says outright that the pass leaves the hotel only by a
    hand-over there, early enough to be over and across. At 3:15 pm the pickup of half an
    hour and the walk just fit. A minute later they do not."""
    works, conflicts = conflicts_to_answer(a_pass_at_the_hotel(16, 30))
    assert not works
    assert conflicts < 1000
    just_in_time = compiler.check(a_pass_at_the_hotel(15, 15))
    assert just_in_time.answer is Answer.FEASIBLE
    assert [(step.option, step.handed) for step in just_in_time.itinerary if step.handed] == [
        ("pickup", (("pass", "alex"),))
    ]
    works, conflicts = conflicts_to_answer(a_pass_at_the_hotel(15, 16))
    assert not works
    assert conflicts < 1000


# Short cuts in the search for the ITINERARY shown.


def a_trip_with_steps_at_one_time(rng: Random) -> File:
    """Two or three PERSONs, each LOCKed into stays of their own at a desk, and one key.

    Most stays start at 9:00 am or at 10:00 am, and some at any time. Each requires the key,
    refuses it, hands it over or keeps it, at random. So several OPTIONs that matter to the
    key start at one instant, and the key has many orders to go through them in.
    """
    people = ["alex", "sam", "jo"][: rng.choice([2, 3, 3])]
    names = [f"{person}-{number}" for person in people for number in range(rng.choice([1, 2, 2]))]
    rng.shuffle(names)
    options = [stays(name, rng.choice(["desk"] * 4 + ["vault"])) for name in names]
    facts: list[Document] = [takes("walk", "PT10M"), complete(None, None)]
    for name in names:
        hour = rng.choice([9, 9, 10, None])
        length = rng.choice(["PT0S", "PT15M", "PT30M"])
        facts += whenever(name, length) if hour is None else at(name, hour, 0, length)
        if rng.random() < 0.6:
            facts.append(requires_object(name, "key"))
        elif rng.random() < 0.5:
            facts.append(refuses_object(name, "key"))
        does = rng.choice(["hands_over", "hands_over", "keeps", None, None])
        if does is not None:
            facts.append(does_with(name, "key", does))
    holder = has_object(rng.choice(people), "key")
    facts.append(rng.choice([holder, lies_at("key", "desk"), lies_at("key", "desk")]))
    facts += [every_use("key")]
    facts += [every_transfer("key")] if rng.random() < 0.7 else []
    things = ["key"]
    if rng.random() < 0.5:
        # A stamp as well, at a few of the stays. So two OBJECTs can order the steps.
        things = rng.choice([["key", "stamp"], ["stamp", "key"]])
        for name in rng.sample(names, min(len(names), rng.choice([1, 2, 2, 3]))):
            if rng.random() < 0.7:
                facts.append(requires_object(name, "stamp"))
            does = rng.choice(["hands_over", "keeps", None])
            if does is not None:
                facts.append(does_with(name, "stamp", does))
        whose = has_object(rng.choice(people), "stamp")
        facts += [rng.choice([whose, lies_at("stamp", "desk")]), every_use("stamp")]
        facts += [every_transfer("stamp")] if rng.random() < 0.7 else []
    locks = [lock(name, name.split("-")[0]) for name in names]
    locks += [trip_starts(8)] if rng.random() < 0.6 else []
    ways = [way_between("walk", "desk", "vault")]
    return trip(people, ["desk", "vault"], options, facts, locks, ways, objects=things)


def a_trip_through_a_gate(rng: Random) -> File:
    """Alex and Sam go through a gate from the foyer to the hall, and a bag lies in the foyer.

    Mostly: the gate takes no time, can start at any time and hands the bag over. Alex has a
    visit in the hall at any time that refuses the bag. Sam has an appointment at a desk in
    the hall at 10:00 am that hands the bag over, with an hour to be there before. The FILE
    lists the three in an order chosen at random, so the OPTION that comes first for a
    PERSON is often listed last. Each part is now and then something else.
    """

    def mostly(usual: str, *others: str) -> str:
        return usual if rng.random() < 0.8 else rng.choice(others)

    names = ["gallery", "gate", "desk"]
    rng.shuffle(names)
    kinds = {"gallery": stays("gallery", "hall"), "desk": stays("desk", "hall")}
    kinds["gate"] = moves("gate", "foyer", "hall")
    facts: list[Document] = [
        *(whenever("gallery", "PT30M") if rng.random() < 0.8 else at("gallery", 9)),
        *(whenever("gate", "PT0S") if rng.random() < 0.8 else at("gate", 9, length="PT0S")),
        starts_at("desk", 10),
        lasts("desk", "PT5M"),
        cutoff("desk", mostly("PT1H", "PT0S", "PT30M")),
        starts_from("alex", "foyer"),
        starts_from("sam", "foyer"),
        rng.choice([lies_at("bag", "foyer")] * 3 + [has_object("alex", "bag")]),
        every_use("bag"),
        every_transfer("bag"),
    ]
    about_the_gallery = mostly("refuses", "requires", "keeps")
    if about_the_gallery == "refuses":
        facts.append(refuses_object("gallery", "bag"))
    elif about_the_gallery == "requires":
        facts.append(requires_object("gallery", "bag"))
    else:
        facts += [keeps("gallery", "bag"), requires_object("desk", "bag")]
    for name in ("gate", "desk"):
        does = mostly("hands_over", "keeps", "nothing")
        facts.append(does_with(name, "bag", does))
    locks = [lock("gallery", "alex"), lock("gate", "alex", "sam"), lock("desk", "sam")]
    locks += [trip_starts(8)] if rng.random() < 0.9 else []
    options = [kinds[name] for name in names]
    return trip(["alex", "sam"], ["foyer", "hall"], options, facts, locks, objects=["bag"])


def test_who_can_have_an_object_goes_by_each_persons_own_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The TRIP starts at 8:00 am, and the bag lies in the foyer. The FILE lists Alex's visit
    to the gallery first: half an hour in the hall at any time, and it refuses the bag. Then
    comes the gate from the foyer to the hall, which Alex and Sam go through, and then Sam's
    appointment at the desk in the hall at 10:00 am, with an hour to be there before. The
    gate and the desk hand the bag over.

    Sam has to be in the hall by 9:00 am, so the gate is at 9:00 am. Alex goes through the
    gate before the gallery, and can have the bag by then. So the bag puts the gallery in
    an order with the desk, and either way the gallery is at 10:00 am. The FILE's order of
    the three says nothing about what Alex does first."""
    options = [stays("gallery", "hall"), moves("gate", "foyer", "hall"), stays("desk", "hall")]
    facts = [
        *whenever("gallery", "PT30M"),
        *whenever("gate", "PT0S"),
        starts_at("desk", 10),
        lasts("desk", "PT5M"),
        cutoff("desk", "PT1H"),
        starts_from("alex", "foyer"),
        starts_from("sam", "foyer"),
        lies_at("bag", "foyer"),
        refuses_object("gallery", "bag"),
        hands_over("gate", "bag"),
        hands_over("desk", "bag"),
        every_use("bag"),
        every_transfer("bag"),
    ]
    locks = [
        trip_starts(8),
        lock("gallery", "alex"),
        lock("gate", "alex", "sam"),
        lock("desk", "sam"),
    ]
    file = trip(["alex", "sam"], ["foyer", "hall"], options, facts, locks, objects=["bag"])
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    starts = {each.option: each.start for each in found.itinerary}
    assert starts == {"gate": seconds(9), "gallery": seconds(10), "desk": seconds(10)}
    # Ranking every order shows the same plan.
    search = EveryOrder(monkeypatch)
    search.skipping_nothing(those_that_matter)
    assert itineraries(file, worst_case(file))[0] == found.itinerary


def a_trip_with_two_things_at_one_desk(rng: Random) -> File:
    """Two PERSONs with five or six stays at one desk, a key that one of them has, and a
    stamp that lies on the desk.

    Mostly: a stay of both at 8:00 am can hand the key over, stays at any time keep the key
    or require it, and stays at 9:00 am and 10:00 am require the stamp or can hand it over.
    So the key leaves a choice of order among stays at any time, while the stamp orders
    stays at fixed times, and the two orders have to go together. Each part is now and then
    something else.
    """

    def mostly(usual: str, *others: str | None) -> str | None:
        return usual if rng.random() < 0.85 else rng.choice(others)

    people = ["sam", "jo"]
    names = ["together", "sam-fixed", "sam-free", "jo-free", "jo-fixed", "jo-other"]
    names = names if rng.random() < 0.85 else names[:5]
    whose = {"together": people, "sam-fixed": ["sam"], "sam-free": ["sam"]}
    whose.update({"jo-free": ["jo"], "jo-fixed": ["jo"], "jo-other": ["jo"]})
    listed = names if rng.random() < 0.8 else rng.sample(names, len(names))
    options = [stays(name, "desk") for name in listed]
    facts: list[Document] = []
    sam_at, jo_at = (10, 9) if rng.random() < 0.8 else rng.choice([(9, 10), (9, 9), (10, 10)])
    hours = {"together": 8, "sam-fixed": sam_at, "jo-fixed": jo_at}
    for name in listed:
        fixed = name in hours and rng.random() < 0.95
        facts += at(name, hours[name], length="PT5M") if fixed else whenever(name)
    key_does = {"together": "hands_over", "sam-free": "keeps", "jo-free": "keeps"}
    for name in listed:
        does = mostly(key_does.get(name) or "", "keeps", None) or None
        if does is not None:
            facts.append(does_with(name, "key", does))
    needs_key = "jo-other" if "jo-other" in listed else "jo-free"
    facts.append(requires_object(mostly(needs_key, *listed) or needs_key, "key"))
    facts += [has_object(mostly("sam", "jo") or "sam", "key"), lies_at("stamp", "desk")]
    facts += [requires_object(mostly("jo-fixed", "sam-fixed") or "jo-fixed", "stamp")]
    facts += [hands_over(mostly("sam-fixed", "jo-fixed") or "sam-fixed", "stamp")]
    facts += [every_use("key"), every_transfer("key"), every_use("stamp")]
    facts += [every_transfer("stamp")] if rng.random() < 0.9 else []
    locks = [lock(name, *whose[name]) for name in listed]
    locks += [trip_starts(8)] if rng.random() < 0.5 else []
    things = ["key", "stamp"] if rng.random() < 0.8 else ["stamp", "key"]
    return trip(people, ["desk"], options, facts, locks, objects=things)


def test_the_short_cuts_show_the_plan_that_ranking_every_order_shows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The search leaves out an order that an order made before it always beats, and it
    stops at an ITINERARY that none can come before. Here it makes every order, times each
    one and ranks them all. The ITINERARY shown is the same. The solver chooses who takes
    part, so that the comparison is about the orders alone."""
    rng = Random(3131)
    search = EveryOrder(monkeypatch)
    left_out = stopped = with_hand_overs = compared = 0
    alike, nothing_before = (
        reference._orders_differ_only_in_the_listing,  # pyright: ignore[reportPrivateUsage]
        reference._nothing_comes_before,  # pyright: ignore[reportPrivateUsage]
    )

    def counted_alike(*given: object) -> bool:
        nonlocal left_out
        found = alike(*given)  # type: ignore[arg-type]
        left_out += found
        return found

    def counted_stop(*given: object) -> bool:
        nonlocal stopped
        found = nothing_before(*given)  # type: ignore[arg-type]
        stopped += found
        return found

    trips = [a_trip_with_steps_at_one_time(rng) for _ in range(300)]
    trips += [a_trip_with_two_things_at_one_desk(rng) for _ in range(300)]
    trips += [a_trip_through_a_gate(rng) for _ in range(200)]
    for file in trips:
        for world in (worst_case(file), best_case(file), no_better_than(file, ())):
            search.as_built()
            monkeypatch.setattr(reference, "_orders_differ_only_in_the_listing", counted_alike)
            monkeypatch.setattr(reference, "_nothing_comes_before", counted_stop)
            shown = compiler.shown(file, world)
            search.skipping_nothing()
            assert compiler.shown(file, world) == shown
            compared += shown is not None
            with_hand_overs += any(step.handed for step in shown or ())
    assert compared > 300
    assert left_out > 40
    assert stopped > 60
    assert with_hand_overs > 50


def test_an_order_is_left_out_only_where_what_comes_before_ranks_before() -> None:
    """Alex and Sam each have a check at the desk at 9:00 am that requires the key lying
    there, and Jo's check at 10:00 am can hand it over. Alex also has a note to hand in at
    9:00 am, which takes no time, comes before Alex's check, and is listed last in the FILE.
    With Alex's check before Sam's, the plan lists the note first. With Sam's first, it
    lists Sam's check first, and that comes before the note. Both orders leave the key on
    the desk. So the order that is made second gives the ITINERARY that comes first, and
    the search may not leave it out."""
    names = ["alex-check", "sam-check", "jo-check", "alex-note"]
    options = [stays(name, "desk") for name in names]
    facts = [
        *at("alex-check", 9),
        *at("sam-check", 9),
        *at("jo-check", 10),
        *at("alex-note", 9, length="PT0S"),
        lies_at("key", "desk"),
        requires_object("alex-check", "key"),
        requires_object("sam-check", "key"),
        hands_over("jo-check", "key"),
        every_use("key"),
        every_transfer("key"),
    ]
    locks = [lock(name, name.split("-")[0]) for name in names]
    file = trip(["alex", "sam", "jo"], ["desk"], options, facts, locks, objects=["key"])
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert [step.option for step in found.itinerary] == [
        "sam-check",
        "alex-note",
        "alex-check",
        "jo-check",
    ]


def test_an_order_is_left_out_only_where_one_object_orders_the_steps() -> None:
    """Three stays at the desk at 9:00 am, listed as Sam's, Jo's and then Alex's. Alex has
    the voucher and deposits it. Sam's stay requires the voucher, so the deposit comes
    before it. Sam's and Jo's stays require the key that lies on the desk, and Jo's stay at
    10:00 am can hand it over, so the key gives those three an order as well. With Jo's
    first, the plan lists Jo's stay, the deposit and Sam's stay. With Sam's first, the
    deposit has to be listed first of all, and it ranks last. Both orders leave the key on
    the desk. Two OBJECTs order the steps here, so no order is left out for being like
    another."""
    names = ["sam-stay", "jo-stay", "deposit", "jo-later"]
    options = [stays(name, "desk") for name in names]
    facts = [
        *at("sam-stay", 9),
        *at("jo-stay", 9),
        *at("deposit", 9),
        *at("jo-later", 10),
        has_object("alex", "voucher"),
        keeps("deposit", "voucher"),
        requires_object("sam-stay", "voucher"),
        every_use("voucher"),
        every_transfer("voucher"),
        lies_at("key", "desk"),
        requires_object("sam-stay", "key"),
        requires_object("jo-stay", "key"),
        hands_over("jo-later", "key"),
        every_use("key"),
        every_transfer("key"),
    ]
    locks = [lock("sam-stay", "sam"), lock("jo-stay", "jo"), lock("deposit", "alex")]
    locks.append(lock("jo-later", "jo"))
    things = ["voucher", "key"]
    file = trip(["alex", "sam", "jo"], ["desk"], options, facts, locks, objects=things)
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert [step.option for step in found.itinerary] == [
        "jo-stay",
        "deposit",
        "sam-stay",
        "jo-later",
    ]
    assert not any(step.handed for step in found.itinerary)


def test_an_unlisted_way_crosses_once_the_span_that_rules_it_out_is_over() -> None:
    """The key lies at the hotel, where Alex takes it at 9:30 am. Alex's meeting in the park
    at 11:00 am requires it. Only an unlisted WAY joins the two, and none leaves from
    9:00 am to 10:00 am. The pickup is inside that span and the meeting is after it, so
    there is time to cross once the span is over."""
    options = [stays("pickup", "hotel"), stays("meeting", "park")]
    span = {"from": "hotel", "to": "park", "leaving": {"earliest": moment(9), "latest": moment(10)}}
    facts = [
        *at("pickup", 9, 30, "PT0S"),
        *at("meeting", 11),
        starts_from("alex", "hotel"),
        {"id": "ways", "complete": span},
        lies_at("key", "hotel"),
        hands_over("pickup", "key"),
        requires_object("meeting", "key"),
        every_use("key"),
        every_transfer("key"),
    ]
    locks = [lock("meeting", "alex")]
    file = trip(["alex"], ["hotel", "park"], options, facts, locks, objects=["key"])
    world = with_these_at_best(file, [Unknown("other ways", origin="hotel", destination="park")])
    shown = first_shown(file, world)
    assert shown is not None
    assert [(step.option, step.handed) for step in shown if step.handed] == [
        ("pickup", (("key", "alex"),))
    ]
    assert compiler.shown(file, world) == shown
    assert compiler.works(file, world)


def test_the_earliest_starts_count_from_fixed_starts_and_limits() -> None:
    """Step 0 starts at a fixed time, and step 1 comes ten seconds or more after it. Step 2
    is tied to nothing but its own limit. Step 3 has nothing to count from. Step 4 comes
    after step 2 and after its own limit, and the later of the two counts. A fixed start
    stays where it is, whatever comes before it and whatever its limit."""
    gaps = [(0, 1, 10), (2, 4, 5), (1, 5, 100)]
    soonest = reference._earliest_starts(  # pyright: ignore[reportPrivateUsage]
        6, gaps, fixed={0: 1000, 5: 1050}, not_before={2: 300, 4: 400, 5: 2000}
    )
    assert soonest == {0: 1000, 1: 1010, 2: 300, 4: 400, 5: 1050}
    later = reference._earliest_starts(  # pyright: ignore[reportPrivateUsage]
        6, [(2, 4, 500)], fixed={}, not_before={2: 300, 4: 400}
    )
    assert later == {2: 300, 4: 800}


def timings_for_the_report(monkeypatch: pytest.MonkeyPatch, file: File) -> tuple[Report, int]:
    """The COMPILER's report on a FILE, and how often a plan was timed on the way to it."""
    timed = 0
    its_own = reference._times  # pyright: ignore[reportPrivateUsage]

    def counted(*how: object) -> object:
        nonlocal timed
        timed += 1
        return its_own(*how)  # type: ignore[arg-type]

    monkeypatch.setattr(reference, "_times", counted)
    found = compiler.check(file)
    monkeypatch.setattr(reference, "_times", its_own)
    return found, timed


def test_steps_at_one_time_do_not_have_every_order_timed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fifteen appointments, five at each of three hours, all about one voucher. They have
    345,600 orders that work, and all of them give the same start times. The search makes
    one order for each way the voucher can end up, and the report lists the deposit first
    at 9:00 am, then the other appointments as the FILE lists them."""
    found, timed = timings_for_the_report(monkeypatch, five_at_each_hour(deposit_last=True))
    assert found.answer is Answer.FEASIBLE
    assert timed < 50
    people = ["person-0", "person-1", "person-2", "person-3", "person-4"]
    in_order = [
        *(f"{person}-at-9" for person in people),
        *(f"{person}-at-{hour}" for hour in (10, 11) for person in (*people[1:], people[0])),
    ]
    assert [step.option for step in found.itinerary] == in_order
    # A stamp that one appointment alone has to do with puts nothing in an order. So the
    # voucher is still the one OBJECT that orders the appointments.
    with_a_stamp = five_at_each_hour(deposit_last=True, stamp=1)
    found, timed = timings_for_the_report(monkeypatch, with_a_stamp)
    assert timed < 50
    assert [step.option for step in found.itinerary] == in_order
    # Nor does a stamp at two appointments of one traveler: the traveler does them one after
    # the other, so the stamp leaves no choice of order.
    stamped_twice = five_at_each_hour(deposit_last=True, stamp=2)
    found, timed = timings_for_the_report(monkeypatch, stamped_twice)
    assert timed < 50
    assert [step.option for step in found.itinerary] == in_order


def test_a_hand_over_among_steps_at_one_time_is_found_without_every_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Eleven guests each have an appointment at the hotel at 9:00 am that requires the
    register and can hand it over. The clerk at the airport requires it at 10:00 am. So one
    guest takes it, in the appointment that comes last of the eleven, and brings it. The
    plan shown has the guest listed last go to the airport, so that guest's appointment is
    the last one. The eleven have forty million orders, and the search makes one for each
    way the register can end up. With four guests, every order can be ranked, and the plan
    shown is the same."""
    found, timed = timings_for_the_report(monkeypatch, a_register_at_two_places(airport_at=10))
    assert found.answer is Answer.FEASIBLE
    assert timed < 100
    at_nine = [step for step in found.itinerary if step.option and step.start == seconds(9)]
    assert [step.option for step in at_nine] == [f"guest-{number}-desk" for number in range(11)]
    assert [step.handed for step in at_nine] == [*[()] * 10, (("register", "guest-10"),)]
    few = a_register_at_two_places(airport_at=10, guests=4)
    shown = compiler.shown(few, worst_case(few))
    assert shown is not None and any(step.handed for step in shown)
    EveryOrder(monkeypatch).skipping_nothing()
    assert compiler.shown(few, worst_case(few)) == shown


def four_at_a_pickup() -> File:
    """Four travelers are all LOCKed into a pickup at 8:00 am that can hand the voucher
    over, and then into four, three, two and two stays at any time. The voucher lies at the
    hotel, where everything happens, and the last stay requires it. Nobody said what a stay
    does with it."""
    sessions = {"alex": 4, "sam": 3, "jo": 2, "kim": 2}
    names = [f"{person}-{number}" for person, count in sessions.items() for number in range(count)]
    options = [stays("pickup", "hotel"), *(stays(name, "hotel") for name in names)]
    facts = [*at("pickup", 8, length="PT5M")]
    facts += [fact for name in names for fact in whenever(name, "PT30M")]
    facts += [lies_at("voucher", "hotel"), requires_object(names[-1], "voucher")]
    facts += [hands_over("pickup", "voucher"), every_use("voucher")]
    locks = [trip_starts(8), lock("pickup", *sessions)]
    locks += [lock(name, name.split("-")[0]) for name in names]
    return trip(list(sessions), ["hotel"], options, facts, locks, objects=["voucher"])


def test_the_search_stops_at_a_plan_that_no_order_can_beat(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each of the four can have the voucher after the pickup, so each stay might keep it,
    and the eleven stays have 69,300 orders. The order in which the stays fall anyway works
    with no hand-over, and every stay starts as early as it can. No order can give a plan
    that comes before that one, so the search stops there."""
    found, timed = timings_for_the_report(monkeypatch, four_at_a_pickup())
    assert found.answer is Answer.FEASIBLE
    assert timed < 50
    assert not any(step.handed for step in found.itinerary)
    assert [step.start for step in found.itinerary if step.option == "kim-1"] == [seconds(8, 35)]


def test_the_time_to_cross_counts_the_hours_in_which_no_unlisted_way_leaves() -> None:
    """The search for a conflict takes FACTs out of the FILE. With the time and the length
    of one guest's appointment taken out, that guest could bring the register early. The
    other ten still require it at the hotel at 9:00 am, when the clerk requires it at the
    airport. In the best case an unlisted WAY joins the two PLACEs, but the FILE lists every
    WAY for that day. So between two fixed times of that day, only the shuttle crosses, and
    the solver sees at once that nothing works."""
    file = a_register_at_two_places()
    left = Remaining(file).without("guest-0-desk-length").without("guest-0-desk-time")
    world, open_pairs = reference.best_case_left(left)
    assert world.unlisted is None or world.unlisted
    search = compiler._Search(file, world, open_pairs, plain=True)  # pyright: ignore[reportPrivateUsage]
    works, conflicts = answered_at_once(search)
    assert not works
    assert conflicts < 1000
    assert not compiler.can_work(left)


def four_on_a_shuttle() -> File:
    """Four travelers are all LOCKed into the shuttle from the lodge to the resort at
    8:00 am, which can hand the voucher over, and then into four, three, two and two
    sessions at the resort at any time. The voucher lies at the lodge, and the last session
    requires it. Nobody said what a session does with it."""
    sessions = {"alex": 4, "sam": 3, "jo": 2, "kim": 2}
    names = [f"{person}-{number}" for person, count in sessions.items() for number in range(count)]
    options = [moves("shuttle", "lodge", "resort"), *(stays(name, "resort") for name in names)]
    facts = [*at("shuttle", 8, length="PT20M")]
    facts += [fact for name in names for fact in whenever(name, "PT30M")]
    facts += [starts_from(person, "lodge") for person in sessions]
    facts += [lies_at("voucher", "lodge"), requires_object(names[-1], "voucher")]
    facts += [hands_over("shuttle", "voucher"), every_use("voucher"), complete(None, None)]
    locks = [trip_starts(8), lock("shuttle", *sessions)]
    locks += [lock(name, name.split("-")[0]) for name in names]
    places = ["lodge", "resort"]
    return trip(list(sessions), places, options, facts, locks, objects=["voucher"])


def test_the_search_stops_at_a_plan_whose_hand_over_no_order_can_do_without(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kim's last session requires the voucher, so Kim has to take it on the shuttle. Every
    order of the eleven sessions has that hand-over, and none has one that comes before it.
    The order in which the sessions fall anyway has every step at the earliest it can
    start. So the search stops there, where it would time 69,300 orders."""
    found, timed = timings_for_the_report(monkeypatch, four_on_a_shuttle())
    assert found.answer is Answer.FEASIBLE
    assert timed < 50
    assert [(step.option, step.handed) for step in found.itinerary if step.handed] == [
        ("shuttle", (("voucher", "kim"),))
    ]


def conflicts_in_the_best_case(file: File) -> tuple[bool, int]:
    """Whether anything works in the best case by the solver's own search, and how many
    conflicts the solver went through to say so."""
    world, open_pairs = reference.best_case_left(Remaining(file))
    search = compiler._Search(file, world, open_pairs, plain=True)  # pyright: ignore[reportPrivateUsage]
    return answered_at_once(search)


def eleven_signatures(
    *more: Document,
    spans: Sequence[Document],
    others: Sequence[Document] = (),
    places: Sequence[str] = (),
    ways: Sequence[Document] = (),
    at_the_airport: Sequence[Document] | None = None,
    decisions: Sequence[Document] = (),
    sign_at_any_time: bool = False,
) -> File:
    """Eleven guests each sign at the hotel desk at 9:00 am, which takes no time. Each
    signature requires the register that lies at the hotel and can hand it over. A clerk at
    the airport requires the register at 9:05 am. The shuttle takes 15 minutes. ``others``
    holds other OPTIONs, ``places`` other PLACEs, ``ways`` other WAYs, and ``more`` the FACTs
    about them. ``at_the_airport`` says when the clerk's check is, where that is not
    9:05 am, and ``decisions`` holds other DECISIONs. With ``sign_at_any_time``, the guests
    sign at any time."""
    people = [f"guest-{number}" for number in range(11)]
    desks = [f"{person}-desk" for person in people]
    options = [*(stays(desk, "hotel") for desk in desks), stays("airport-desk", "airport")]
    options += others
    facts = [
        fact
        for desk in desks
        for fact in (whenever(desk, "PT0S") if sign_at_any_time else at(desk, 9, length="PT0S"))
    ]
    facts += at("airport-desk", 9, 5) if at_the_airport is None else at_the_airport
    facts += [starts_from("clerk", "airport")]
    facts += [starts_from(person, "hotel") for person in people]
    facts += [takes("shuttle", "PT15M")]
    facts += [lies_at("register", "hotel"), requires_object("airport-desk", "register")]
    for desk in desks:
        facts += [hands_over(desk, "register"), requires_object(desk, "register")]
    facts += [every_use("register"), every_transfer("register"), *spans, *more]
    locks = [lock(desk, person) for desk, person in zip(desks, people, strict=True)]
    locks += [lock("airport-desk", "clerk"), *decisions]
    all_ways = [way_between("shuttle", "hotel", "airport"), *ways]
    everywhere = ["hotel", "airport", *places]
    return trip(
        [*people, "clerk"], everywhere, options, facts, locks, all_ways, objects=["register"]
    )


def no_way_leaves(id: str, earliest: str, latest: str) -> Document:
    """A FACT that the FILE lists every way between any two PLACEs that leaves in a span."""
    return {"id": id, "complete": {"leaving": {"earliest": earliest, "latest": latest}}}


def test_two_spans_that_meet_rule_an_unlisted_way_out_as_one_does() -> None:
    """The register is at the hotel at 9:00 am and has to be at the airport at 9:05 am. The
    shuttle takes 15 minutes. One FACT lists every way that leaves until 9:02 am, and
    another every way from the second after. Together they leave no time for an unlisted
    WAY, and the solver sees at once that nothing works. With one second left open between
    them, an unlisted WAY can leave then."""
    day = "2027-05-15T{}-05:00[America/Chicago]"
    spans = [
        no_way_leaves("ways-early", day.format("00:00:00"), day.format("09:02:00")),
        no_way_leaves("ways-late", day.format("09:02:01"), day.format("23:59:00")),
    ]
    works, conflicts = conflicts_in_the_best_case(eleven_signatures(spans=spans))
    assert not works
    assert conflicts < 1000
    spans[1] = no_way_leaves("ways-late", day.format("09:02:02"), day.format("23:59:00"))
    works, conflicts = conflicts_in_the_best_case(eleven_signatures(spans=spans))
    assert works


def test_a_ride_that_leaves_too_late_does_not_count_for_the_time_to_cross() -> None:
    """An express from the hotel to the airport takes one minute and leaves at 3:00 pm. The
    register has to cross between 9:00 am and 9:05 am, so the express is no help, and the
    solver sees at once that nothing works. With the express at 9:02 am, a guest takes the
    register along."""

    def with_an_express(hour: int, minute: int) -> File:
        return eleven_signatures(
            *at("express", hour, minute, "PT1M"),
            spans=[complete(None, None)],
            others=[moves("express", "hotel", "airport")],
        )

    works, conflicts = conflicts_in_the_best_case(with_an_express(15, 0))
    assert not works
    assert conflicts < 1000
    works, conflicts = conflicts_in_the_best_case(with_an_express(9, 2))
    assert works


def test_whoever_takes_an_object_stays_until_the_option_is_over() -> None:
    """Each guest's appointment at the hotel takes half an hour from 9:00 am, and the clerk
    requires the register at the airport at 9:00 am. Nobody said how long the shuttle takes,
    so in the best case it takes no time. A guest who takes the register is still in the
    appointment until 9:30 am. So no hand-over at the hotel is early enough, and the solver
    sees at once that nothing works."""
    file = a_register_at_two_places()
    without = replace(file, facts=tuple(fact for fact in file.facts if fact.id != "shuttle-length"))
    works, conflicts = conflicts_in_the_best_case(without)
    assert not works
    assert conflicts < 1000


def test_the_time_to_cross_is_worked_out_only_from_the_places_that_matter() -> None:
    """A line of 200 stops, with a ride from each to the next. Alex takes the pass at the
    first stop and needs it at the second. The model works out the time to cross from those
    two stops, and not between every two stops of the line."""
    stops = [f"stop-{number}" for number in range(200)]
    ways = [
        way_between(f"ride-{a}", here, there) for a, (here, there) in enumerate(pairwise(stops))
    ]
    options = [stays("pickup", "stop-0"), stays("meeting", "stop-1")]
    facts = [*at("pickup", 9, length="PT5M"), *at("meeting", 10), starts_from("alex", "stop-0")]
    facts += [takes(each["id"], "PT5M") for each in ways]
    facts += [lies_at("pass", "stop-0"), hands_over("pickup", "pass")]
    facts += [requires_object("meeting", "pass"), every_use("pass"), every_transfer("pass")]
    facts.append(complete(None, None))
    locks = [lock("meeting", "alex")]
    file = trip(["alex"], stops, options, facts, locks, ways, objects=["pass"])
    search = compiler._Search(file, worst_case(file), plain=True)  # pyright: ignore[reportPrivateUsage]
    worked_out = {origin for origin, _ in search._crossing}  # pyright: ignore[reportPrivateUsage]
    assert worked_out and worked_out <= {"stop-0", "stop-1"}
    assert compiler.works(file, worst_case(file))


def test_a_connection_that_is_missed_does_not_count_for_the_time_to_cross() -> None:
    """The register is at the hotel at 9:00 am and has to be at the airport at 9:05 am. A
    shuttle from the hotel reaches the pier at 9:04 am, and the ferry on to the airport
    leaves at 9:02 am. The two rides take five minutes together, but the ferry has left
    when the shuttle gets there, and the taxi takes 15 minutes. The solver sees at once
    that nothing works. With the ferry at 9:04 am, a guest brings the register."""

    def by_ferry(minute: int) -> File:
        return eleven_signatures(
            *at("pier-shuttle", 9, 0, "PT4M"),
            *at("ferry", 9, minute, "PT1M"),
            spans=[complete(None, None)],
            others=[moves("pier-shuttle", "hotel", "pier"), moves("ferry", "pier", "airport")],
            places=["pier"],
        )

    works, conflicts = conflicts_in_the_best_case(by_ferry(2))
    assert not works
    assert conflicts < 1000
    works, conflicts = conflicts_in_the_best_case(by_ferry(4))
    assert works
    # The same where the clerk's check is at any time and the TRIP ends at 9:05 am. The
    # register still sets out at 9:00 am, so the missed ferry still does not count.
    any_time_before_the_end = eleven_signatures(
        *at("pier-shuttle", 9, 0, "PT4M"),
        *at("ferry", 9, 2, "PT1M"),
        spans=[complete(None, None)],
        others=[moves("pier-shuttle", "hotel", "pier"), moves("ferry", "pier", "airport")],
        places=["pier"],
        at_the_airport=whenever("airport-desk", "PT0S"),
        decisions=[trip_ends(9, 5)],
    )
    works, conflicts = conflicts_in_the_best_case(any_time_before_the_end)
    assert not works
    assert conflicts < 1000

    # And where the guests sign at any time too, in a TRIP from 9:00 am to 9:05 am. Nobody
    # signs before the TRIP starts, so the register still misses the ferry.
    def within_five_minutes(minute: int) -> File:
        return eleven_signatures(
            *at("pier-shuttle", 9, 0, "PT4M"),
            *at("ferry", 9, minute, "PT1M"),
            spans=[complete(None, None)],
            others=[moves("pier-shuttle", "hotel", "pier"), moves("ferry", "pier", "airport")],
            places=["pier"],
            at_the_airport=whenever("airport-desk", "PT0S"),
            decisions=[trip_starts(9), trip_ends(9, 5)],
            sign_at_any_time=True,
        )

    works, conflicts = conflicts_in_the_best_case(within_five_minutes(2))
    assert not works
    assert conflicts < 1000
    works, conflicts = conflicts_in_the_best_case(within_five_minutes(4))
    assert works


def test_a_way_with_no_known_length_does_not_count_for_the_time_to_cross() -> None:
    """Besides the shuttle of 15 minutes, a tunnel joins the hotel and the airport, and
    nobody said how long it takes. In the worst case it has no limit, so nothing follows it,
    and the register that goes through it is at hand nowhere afterwards. The solver sees at
    once that nothing works in the worst case."""
    file = eleven_signatures(spans=[complete(None, None)], ways=[way("tunnel", "hotel", "airport")])
    works, conflicts = conflicts_to_answer(file)
    assert not works
    assert conflicts < 1000
    works, _ = conflicts_in_the_best_case(file)
    assert works
    # The same for a ride at 9:02 am that nobody knows the length of.
    by_ride = eleven_signatures(
        starts_at("express", 9, 2),
        cutoff("express", "PT0S"),
        spans=[complete(None, None)],
        others=[moves("express", "hotel", "airport")],
    )
    works, conflicts = conflicts_to_answer(by_ride)
    assert not works
    assert conflicts < 1000
    works, _ = conflicts_in_the_best_case(by_ride)
    assert works


def four_on_a_bus() -> File:
    """Four riders are LOCKed into the bus from the lodge, which gets to the resort at
    8:20 am and can hand the voucher over. Alex has the voucher. Kim's check at 8:25 am
    requires it. Alex's deposit keeps it, at any time, but Alex has to be there two hours
    before it starts. Each rider also has three stays at the resort at any time, and nobody
    said what those do with the voucher."""
    riders = ["alex", "sam", "jo", "kim"]
    stays_at = [f"{rider}-{number}" for rider in riders for number in range(3)]
    options = [moves("bus", "lodge", "resort"), stays("kim-check", "resort")]
    options += [stays("alex-deposit", "resort"), *(stays(name, "resort") for name in stays_at)]
    facts = [*at("bus", 8, 0, "PT20M"), *at("kim-check", 8, 25, "PT5M")]
    facts += [
        any_time("alex-deposit"),
        lasts("alex-deposit", "PT5M"),
        cutoff("alex-deposit", "PT2H"),
    ]
    facts += [fact for name in stays_at for fact in whenever(name, "PT30M")]
    facts += [starts_from(rider, "lodge") for rider in riders]
    facts += [has_object("alex", "voucher"), hands_over("bus", "voucher")]
    facts += [keeps("alex-deposit", "voucher"), requires_object("kim-check", "voucher")]
    facts += [every_use("voucher"), complete(None, None)]
    locks = [trip_starts(8), lock("bus", *riders), lock("kim-check", "kim")]
    locks += [lock("alex-deposit", "alex")]
    locks += [lock(name, name.split("-")[0]) for name in stays_at]
    return trip(riders, ["lodge", "resort"], options, facts, locks, objects=["voucher"])


def test_an_order_that_the_earliest_starts_rule_out_is_not_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kim needs the voucher at 8:25 am. Alex's deposit would leave it at the resort with no
    hand-over, but it cannot start before 10:20 am, so it never comes before Kim's check.
    The hand-over to Kim on the bus is then the one that no order can do without, and the
    search stops at the plan that has it."""
    found, timed = timings_for_the_report(monkeypatch, four_on_a_bus())
    assert found.answer is Answer.FEASIBLE
    assert timed < 100
    assert [(step.option, step.handed) for step in found.itinerary if step.handed] == [
        ("bus", (("voucher", "kim"),))
    ]


def test_the_hand_overs_that_no_order_can_do_without_are_those_of_each_object_by_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sam has the key, and the stamp lies on the desk. Jo's check at any time requires the
    key. Sam can hand the key to Jo at 8:00 am, or leave it on the desk after 10:00 am, in a
    stay that keeps it. The second plan has no hand-over, so it comes first. Jo's check of
    the stamp at 9:00 am and Sam's stay at 10:00 am that can hand the stamp over are in one
    order by their times. That order may not hide the plan with no hand-over from the
    search for the hand-overs that no order can do without. Ranking every order shows the
    same plan."""
    names = ["together", "sam-at-ten", "sam-leaves", "jo-leaves", "jo-at-nine", "jo-checks"]
    options = [stays(name, "desk") for name in names]
    facts = [
        *at("together", 8, length="PT5M"),
        *at("sam-at-ten", 10, length="PT5M"),
        *whenever("sam-leaves"),
        *whenever("jo-leaves"),
        *at("jo-at-nine", 9, length="PT5M"),
        *whenever("jo-checks"),
        has_object("sam", "key"),
        lies_at("stamp", "desk"),
        hands_over("together", "key"),
        hands_over("sam-at-ten", "stamp"),
        keeps("sam-leaves", "key"),
        keeps("jo-leaves", "key"),
        requires_object("jo-at-nine", "stamp"),
        requires_object("jo-checks", "key"),
        every_use("key"),
        every_transfer("key"),
        every_use("stamp"),
        every_transfer("stamp"),
    ]
    locks = [lock("together", "sam", "jo"), lock("sam-at-ten", "sam"), lock("sam-leaves", "sam")]
    locks += [lock("jo-leaves", "jo"), lock("jo-at-nine", "jo"), lock("jo-checks", "jo")]
    file = trip(["sam", "jo"], ["desk"], options, facts, locks, objects=["key", "stamp"])
    world = worst_case(file)
    shown = compiler.shown(file, world)
    assert shown is not None
    assert not any(step.handed for step in shown)
    EveryOrder(monkeypatch).skipping_nothing()
    assert compiler.shown(file, world) == shown


def test_two_uses_away_from_where_an_object_lies_need_the_time_between_them() -> None:
    """The register lies at the hotel, where eleven guests sign at 8:00 am and each can take
    it. A clerk at the airport requires it at 9:00 am and an officer at the harbour at
    9:05 am. A shuttle of 15 minutes joins each two of the three PLACEs. A guest gets the
    register to the airport in time, but not on to the harbour five minutes later. The
    model says outright that the two uses are 15 minutes apart, so the solver need not try
    each guest. With the officer at 9:15 am, a guest takes it to both."""

    def two_desks(minute: int) -> File:
        people = [f"guest-{number}" for number in range(11)]
        desks = [f"{person}-desk" for person in people]
        options = [stays(desk, "hotel") for desk in desks]
        options += [stays("airport-desk", "airport"), stays("harbour-desk", "harbour")]
        facts = [fact for desk in desks for fact in at(desk, 8, length="PT0S")]
        facts += [*at("airport-desk", 9, length="PT0S"), *at("harbour-desk", 9, minute, "PT0S")]
        facts += [starts_from(person, "hotel") for person in people]
        facts += [starts_from("clerk", "airport"), starts_from("officer", "harbour")]
        places = ["hotel", "airport", "harbour"]
        ways = [way_between(f"{a}-{b}", a, b) for a, b in combinations(places, 2)]
        facts += [takes(each["id"], "PT15M") for each in ways]
        facts += [lies_at("register", "hotel"), complete(None, None)]
        facts += [requires_object("airport-desk", "register")]
        facts += [requires_object("harbour-desk", "register")]
        facts += [hands_over(desk, "register") for desk in desks]
        facts += [every_use("register"), every_transfer("register")]
        locks = [lock(desk, person) for desk, person in zip(desks, people, strict=True)]
        locks += [lock("airport-desk", "clerk"), lock("harbour-desk", "officer")]
        everybody = [*people, "clerk", "officer"]
        return trip(everybody, places, options, facts, locks, ways, objects=["register"])

    works, conflicts = conflicts_to_answer(two_desks(5))
    assert not works
    assert conflicts < 1000
    works, conflicts = conflicts_to_answer(two_desks(15))
    assert works


def test_an_object_with_an_option_at_any_time_leaves_a_choice_of_order() -> None:
    """Alex and Sam each have an appointment at 9:00 am about the voucher, so the voucher
    leaves a choice of order. Jo's two stays require the stamp, and one can hand it over.
    With both of Jo's stays at fixed times, the stamp has one order and moves no start, and
    the voucher is the one OBJECT that orders the steps. With one of them at any time, the
    order of the stamp can move that start, so the stamp counts as leaving a choice too."""

    def the_one_order(*later: Document) -> tuple[int, ...] | None:
        names = ["alex-deposit", "sam-check", "jo-early", "jo-later"]
        options = [stays(name, "desk") for name in names]
        facts = [
            *at("alex-deposit", 9),
            *at("sam-check", 9),
            *at("jo-early", 9),
            *later,
            has_object("alex", "voucher"),
            keeps("alex-deposit", "voucher"),
            requires_object("sam-check", "voucher"),
            lies_at("stamp", "desk"),
            requires_object("jo-early", "stamp"),
            requires_object("jo-later", "stamp"),
            hands_over("jo-early", "stamp"),
        ]
        facts += [every_use(thing) for thing in ("voucher", "stamp")]
        facts += [every_transfer(thing) for thing in ("voucher", "stamp")]
        locks = [lock(name, name.split("-")[0]) for name in names]
        things = ["voucher", "stamp"]
        file = trip(["alex", "sam", "jo"], ["desk"], options, facts, locks, objects=things)
        who = (("alex",), ("sam",), ("jo",), ("jo",))
        orders = ((0,), (1,), (2, 3))
        return reference._the_one_order(  # pyright: ignore[reportPrivateUsage]
            file, worst_case(file), who, orders
        )

    assert the_one_order(*at("jo-later", 10)) == (0, 1)
    assert the_one_order(*whenever("jo-later")) is None


def test_an_unlisted_way_leaves_in_the_first_second_after_the_span() -> None:
    """The register has to be at the airport at 9:05 am. The FILE lists every way that
    leaves until 9:05 am, to the second. In the best case an unlisted WAY takes no time, but
    it leaves a second after the span at the earliest, which is a second too late. The
    solver sees that at once. With the span over a second sooner, the unlisted WAY leaves
    at 9:05 am and is there in time."""
    day = "2027-05-15T{}-05:00[America/Chicago]"
    to_the_second = [no_way_leaves("ways", day.format("00:00:00"), day.format("09:05:00"))]
    works, conflicts = conflicts_in_the_best_case(eleven_signatures(spans=to_the_second))
    assert not works
    assert conflicts < 1000
    a_second_sooner = [no_way_leaves("ways", day.format("00:00:00"), day.format("09:04:59"))]
    works, conflicts = conflicts_in_the_best_case(eleven_signatures(spans=a_second_sooner))
    assert works


def test_an_object_is_not_at_hand_in_two_places_that_nothing_joins() -> None:
    """The register lies at the hotel and the clerk at the airport requires it an hour
    after the guests sign. The FILE lists every way, and none joins the hotel and the
    airport. The model says outright that nothing gets from the one to the other, so the
    solver need not try each guest as the one who takes the register."""
    file = a_register_at_two_places(airport_at=10)
    apart = replace(
        file,
        ways=(),
        facts=tuple(fact for fact in file.facts if fact.id != "shuttle-length"),
    )
    works, conflicts = conflicts_to_answer(apart)
    assert not works
    assert conflicts < 1000


def four_on_a_shuttle_with_a_key(key_at: str) -> File:
    """The four on the shuttle, and a key as well. Alex's last session requires the key,
    which lies at the lodge or at the resort. Kim's last session requires the voucher,
    which lies at the lodge. The shuttle can hand both over."""
    file = four_on_a_shuttle()
    key = [
        ObjectStarts("key-start", "key", place=key_at),
        RequiresObject("alex-3-requires-key", "alex-3", "key", True),
        WithObject("shuttle-with-key", "shuttle", "key", "hands_over"),
        CompleteRequiresObject("every-use-of-key", "key"),
    ]
    listed = (*file.objects, Object("key", "key"))
    return replace(file, objects=listed, facts=(*file.facts, *key))


def test_the_search_stops_at_the_hand_overs_that_each_object_needs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the key at the lodge too, Alex has to take the key on the shuttle and Kim the
    voucher. With the key at the resort, only the voucher changes hands. Either way those
    are the hand-overs that no order can do without, OBJECT by OBJECT, and the search stops
    at the plan that has them."""
    found, timed = timings_for_the_report(monkeypatch, four_on_a_shuttle_with_a_key("lodge"))
    assert found.answer is Answer.FEASIBLE
    assert timed < 100
    assert [(step.option, step.handed) for step in found.itinerary if step.handed] == [
        ("shuttle", (("voucher", "kim"), ("key", "alex")))
    ]
    found, timed = timings_for_the_report(monkeypatch, four_on_a_shuttle_with_a_key("resort"))
    assert found.answer is Answer.FEASIBLE
    assert timed < 100
    assert [(step.option, step.handed) for step in found.itinerary if step.handed] == [
        ("shuttle", (("voucher", "kim"),))
    ]


# An OPTION that carries an OBJECT, on ITINERARIES written by hand.


def a_crossing(*facts: Document, persons: Sequence[str] = ("alex", "sam")) -> File:
    """A ferry from the quay to the island that leaves at 9:00 am and takes an hour.

    At the quay there is a counter at 8:00 am, a booth at 8:15 am and a kiosk at 9:30 am. On
    the island there is a desk at 9:30 am, an office at 10:00 am and a hut at 11:00 am. Each
    of those takes half an hour.
    """
    options = [
        stays("counter", "quay"),
        stays("booth", "quay"),
        moves("ferry", "quay", "island"),
        stays("kiosk", "quay"),
        stays("desk", "island"),
        stays("office", "island"),
        stays("hut", "island"),
    ]
    times = [
        *at("counter", 8),
        *at("booth", 8, 15),
        *at("ferry", 9, 0, "PT1H"),
        *at("kiosk", 9, 30),
        *at("desk", 9, 30),
        *at("office", 10),
        *at("hut", 11),
    ]
    return trip(list(persons), ["quay", "island"], options, [*times, *facts], [], objects=["bag"])


def sail(*persons: str, carried: tuple[str, ...] = (), lands: int | None = 10) -> Step:
    """The ferry of ``a_crossing``. ``lands`` is the hour it ends, and None where nobody knows."""
    end = None if lands is None else seconds(lands)
    return Step("ferry", "quay", "island", persons, seconds(9), end, carried=carried)


def bag_not_at_hand(option: str, *persons: str, late: int | None = None) -> Broken:
    """The bag is not at hand for an OPTION. ``late`` is how many seconds after its start
    the bag would be, where the bag is in an OPTION that ends at the same PLACE."""
    return Broken(Constraint.AT_HAND, option, persons, late, object="bag")


AT_THE_QUAY = frozenset({Where(place="quay")})
ON_THE_ISLAND = frozenset({Where(place="island")})
IN_THE_FERRY = frozenset({Where(option="ferry")})
WITH_ALEX = frozenset({Where(person="alex")})


def test_an_object_that_is_carried_lies_where_the_option_ends_once_it_is_over() -> None:
    """The bag lies at the quay and the ferry carries it. The office opens in the second in
    which the ferry lands, and finds the bag on the island."""
    file = a_crossing(
        lies_at("bag", "quay"), carries("ferry", "bag"), requires_object("office", "bag")
    )
    world = settled(file)
    plan = (sail("alex", carried=("bag",)), step("office", "island", 10, "sam"))
    assert broken(file, world, plan) == []
    assert whereabouts(file, world, plan)["bag"] == (AT_THE_QUAY, IN_THE_FERRY, ON_THE_ISLAND)
    assert just_before(file, world, plan)["bag"] == (AT_THE_QUAY, ON_THE_ISLAND)


def test_an_object_is_at_hand_for_nothing_while_it_is_carried() -> None:
    """The desk opens at 9:30 am, and the ferry is at sea until 10:00 am."""
    file = a_crossing(
        lies_at("bag", "quay"), carries("ferry", "bag"), requires_object("desk", "bag")
    )
    world = settled(file)
    plan = (sail("alex", carried=("bag",)), step("desk", "island", 9, "sam", minute=30))
    # The finding says how long after the desk opens the bag would be there.
    assert broken(file, world, plan) == [bag_not_at_hand("desk", "sam", late=1800)]
    assert just_before(file, world, plan)["bag"][1] == IN_THE_FERRY
    # It is still in the ferry after the desk, and nothing lists a later step.
    assert whereabouts(file, world, plan)["bag"][2] == IN_THE_FERRY


def test_a_carry_takes_an_object_from_the_person_who_has_it() -> None:
    """Alex has the bag and the ferry carries it. On the island it lies there, and Alex goes
    into a hut that refuses it."""
    file = a_crossing(
        has_object("alex", "bag"), carries("ferry", "bag"), refuses_object("hut", "bag")
    )
    world = settled(file)
    plan = (sail("alex", carried=("bag",)), step("hut", "island", 11, "alex"))
    assert broken(file, world, plan) == []
    assert just_before(file, world, plan)["bag"] == (WITH_ALEX, ON_THE_ISLAND)
    # A bag that is not carried stays with Alex, on the ferry and into the hut.
    with_it = (sail("alex"), step("hut", "island", 11, "alex"))
    assert broken(file, world, with_it) == [
        Broken(Constraint.REFUSED, "hut", ("alex",), object="bag")
    ]
    assert just_before(file, world, with_it)["bag"] == (WITH_ALEX, WITH_ALEX)


def test_whether_an_object_is_carried_is_a_choice() -> None:
    """The kiosk at the quay requires the bag after the ferry has left. The ferry can carry
    the bag, and the plan leaves it."""
    file = a_crossing(
        lies_at("bag", "quay"), carries("ferry", "bag"), requires_object("kiosk", "bag")
    )
    world = settled(file)
    kiosk = step("kiosk", "quay", 9, "sam", minute=30)
    assert broken(file, world, (sail("alex"), kiosk)) == []
    assert broken(file, world, (sail("alex", carried=("bag",)), kiosk)) == [
        bag_not_at_hand("kiosk", "sam")
    ]


def test_an_object_is_carried_only_where_it_is_at_hand() -> None:
    file = a_crossing(lies_at("bag", "island"), carries("ferry", "bag"))
    world = settled(file)
    plan = (sail("alex", carried=("bag",)),)
    assert broken(file, world, plan) == [bag_not_at_hand("ferry", "alex")]
    assert whereabouts(file, world, plan)["bag"] == (ON_THE_ISLAND, ON_THE_ISLAND)
    # With a PERSON who takes part, it is at hand. With anybody else, it is not.
    held = a_crossing(has_object("sam", "bag"), carries("ferry", "bag"))
    assert broken(held, settled(held), (sail("sam", carried=("bag",)),)) == []
    assert broken(held, settled(held), plan) == [bag_not_at_hand("ferry", "alex")]


@pytest.mark.parametrize("does", [None, keeps, hands_over])
def test_an_object_is_carried_only_in_an_option_that_carries_it(does: Any) -> None:
    facts = [lies_at("bag", "quay")] + ([] if does is None else [does("ferry", "bag")])
    file = a_crossing(*facts)
    plan = (sail("alex", carried=("bag",)),)
    assert broken(file, settled(file), plan) == [bag_not_at_hand("ferry", "alex")]
    assert whereabouts(file, settled(file), plan)["bag"] == (AT_THE_QUAY, AT_THE_QUAY)


def test_an_option_that_stays_at_one_place_can_carry_an_object() -> None:
    """Alex leaves the bag at the counter for half an hour. Meanwhile nobody has it, and it is
    at hand for nothing. Afterwards it lies at the quay, for anybody."""
    file = a_crossing(
        has_object("alex", "bag"),
        carries("counter", "bag"),
        requires_object("booth", "bag"),
        requires_object("kiosk", "bag"),
    )
    world = settled(file)
    counter = step("counter", "quay", 8, "alex", carried=("bag",))
    later = (counter, step("kiosk", "quay", 9, "sam", minute=30))
    assert broken(file, world, later) == []
    assert just_before(file, world, later)["bag"] == (WITH_ALEX, AT_THE_QUAY)
    meanwhile = (counter, step("booth", "quay", 8, "sam", minute=15))
    assert broken(file, world, meanwhile) == [bag_not_at_hand("booth", "sam", late=900)]
    assert just_before(file, world, meanwhile)["bag"][1] == {Where(option="counter")}


def test_an_option_that_refuses_an_object_carries_it_only_from_where_it_lies() -> None:
    """The cabin lets no bag in, and the hold takes it."""
    hold = [carries("ferry", "bag"), refuses_object("ferry", "bag")]
    file = a_crossing(lies_at("bag", "quay"), *hold)
    plan = (sail("alex", carried=("bag",)),)
    assert broken(file, settled(file), plan) == []
    assert whereabouts(file, settled(file), plan)["bag"] == (AT_THE_QUAY, IN_THE_FERRY)
    # Alex has the bag: that breaks the refusal, and the bag is not carried.
    held = a_crossing(has_object("alex", "bag"), *hold)
    assert broken(held, settled(held), plan) == [
        Broken(Constraint.REFUSED, "ferry", ("alex",), object="bag")
    ]
    assert whereabouts(held, settled(held), plan)["bag"] == (WITH_ALEX, WITH_ALEX)
    # Sam sails alone: the bag that Alex has is not at hand.
    alone = (sail("sam", carried=("bag",)),)
    assert broken(held, settled(held), alone) == [bag_not_at_hand("ferry", "sam")]


def test_an_option_checks_what_it_requires_before_it_carries() -> None:
    file = a_crossing(
        lies_at("bag", "island"), carries("ferry", "bag"), requires_object("ferry", "bag")
    )
    world = settled(file)
    assert broken(file, world, (sail("alex"),)) == [bag_not_at_hand("ferry", "alex")]
    # The requirement and the carry both miss the bag. The two findings are the same, and
    # one is given.
    assert broken(file, world, (sail("alex", carried=("bag",)),)) == [
        bag_not_at_hand("ferry", "alex")
    ]
    # At the quay the ferry happens, with the bag carried or left.
    there = a_crossing(
        lies_at("bag", "quay"), carries("ferry", "bag"), requires_object("ferry", "bag")
    )
    for plan in ((sail("alex"),), (sail("alex", carried=("bag",)),)):
        assert broken(there, settled(there), plan) == []


def test_nothing_takes_an_object_out_of_the_option_that_carries_it() -> None:
    """While the ferry is at sea, the desk on the island cannot hand the bag over, and cannot
    carry it. Either way the bag still lands with the ferry, and the hut finds it."""
    for does in (hands_over, carries):
        file = a_crossing(
            lies_at("bag", "quay"),
            carries("ferry", "bag"),
            does("desk", "bag"),
            requires_object("hut", "bag"),
        )
        world = settled(file)
        desk = step("desk", "island", 9, "sam", minute=30, carried=("bag",))
        if does is hands_over:
            desk = step("desk", "island", 9, "sam", minute=30, handed=(("bag", "sam"),))
        plan = (sail("alex", carried=("bag",)), desk, step("hut", "island", 11, "sam"))
        # The bag would be at the desk half an hour after it opens.
        assert broken(file, world, plan) == [bag_not_at_hand("desk", "sam", late=1800)]
        assert just_before(file, world, plan)["bag"] == (AT_THE_QUAY, IN_THE_FERRY, ON_THE_ISLAND)


def an_instant_at_the_quay(*facts: Document) -> File:
    """A drop that takes no time and a check, both at the quay at 9:00 am."""
    options = [stays("drop", "quay"), stays("check", "quay")]
    times = [*at("drop", 9, 0, "PT0S"), *at("check", 9, 0, "PT0S")]
    stated = [has_object("alex", "bag"), carries("drop", "bag"), requires_object("check", "bag")]
    return trip(["alex", "sam"], ["quay"], options, [*times, *stated, *facts], [], objects=["bag"])


def test_a_carry_that_takes_no_time_is_over_for_the_steps_listed_after_it() -> None:
    """Alex drops the bag in a carry that takes no time, and Sam's check requires it in the
    same second. Listed after the drop, the check finds the bag at the quay. Listed before
    it, the check finds the bag with Alex, who is not there."""
    file = an_instant_at_the_quay()
    world = settled(file)
    nine = seconds(9)
    drop = Step("drop", "quay", "quay", ("alex",), nine, nine, carried=("bag",))
    check = Step("check", "quay", "quay", ("sam",), nine, nine)
    assert broken_as_listed(file, world, (drop, check)) == []
    assert just_before(file, world, (drop, check))["bag"] == (WITH_ALEX, AT_THE_QUAY)
    assert broken_as_listed(file, world, (check, drop)) == [bag_not_at_hand("check", "sam")]


def test_nobody_knows_when_an_object_arrives_from_an_option_of_unknown_length() -> None:
    """Nobody said how long the ferry takes. At worst it never lands, so the bag is at hand
    for nothing afterwards. At best it takes no time."""
    stated = a_crossing(
        lies_at("bag", "quay"), carries("ferry", "bag"), requires_object("hut", "bag")
    )
    file = replace_silence(
        replace(stated, facts=tuple(f for f in stated.facts if f.id != "ferry-length"))
    )
    plan = (sail("alex", carried=("bag",), lands=None), step("hut", "island", 11, "sam"))
    worst = worst_case(file)
    assert broken(file, worst, in_world(worst, plan)) == [bag_not_at_hand("hut", "sam")]
    assert just_before(file, worst, in_world(worst, plan))["bag"][1] == IN_THE_FERRY
    best = best_case(file)
    assert broken(file, best, in_world(best, plan)) == []
    assert just_before(file, best, in_world(best, plan))["bag"][1] == ON_THE_ISLAND


def test_a_carry_needs_an_object_at_hand_wherever_it_might_be() -> None:
    """Nobody says what the counter does with the bag that Alex has. It might keep it, so the
    bag might be with Alex or at the quay. The ferry carries it from either, and from then on
    it is in the ferry for sure. A carry from the island is not sure to find it."""
    file = a_crossing(
        has_object("alex", "bag"),
        carries("ferry", "bag"),
        carries("office", "bag"),
        requires_object("office", "bag", False),
        requires_object("hut", "bag"),
        every_use("bag"),
    )
    world = worst_case(file)
    counter = step("counter", "quay", 8, "alex")
    plan = (counter, sail("alex", carried=("bag",)), step("hut", "island", 11, "sam"))
    assert broken(file, world, plan) == []
    assert whereabouts(file, world, plan)["bag"] == (
        WITH_ALEX,
        WITH_ALEX | AT_THE_QUAY,
        IN_THE_FERRY,
        ON_THE_ISLAND,
    )
    from_the_island = (
        counter,
        sail("alex"),
        step("office", "island", 10, "alex", carried=("bag",)),
    )
    assert broken(file, world, from_the_island) == [bag_not_at_hand("office", "alex")]


def test_an_option_with_no_fact_about_an_object_carries_nothing_at_worst() -> None:
    """A carry is a choice of the travelers, so nobody can count on one that no FACT states.
    With the FACT turned out well, the plan works."""
    file = a_crossing(lies_at("bag", "quay"), requires_object("office", "bag"), every_use("bag"))
    plan = (sail("alex", carried=("bag",)), step("office", "island", 10, "sam"))
    assert broken(file, worst_case(file), plan) == [
        bag_not_at_hand("ferry", "alex"),
        bag_not_at_hand("office", "sam"),
    ]
    said = with_these_at_best(file, [Unknown("carries", "ferry", about="bag")])
    assert broken(file, said, plan) == []


# An OPTION that carries an OBJECT, in the search for a plan.


def carried_in(plan: Itinerary | None) -> list[tuple[str | None, tuple[str, ...]]]:
    """Each OPTION of a plan in which an OBJECT is carried, with those OBJECTs."""
    return [(each.option, each.carried) for each in plan or () if each.carried]


def start_of(plan: Itinerary | None, option: str) -> int:
    return next(each.start for each in plan or () if each.option == option)


def a_voyage(
    options: Sequence[Document], facts: Sequence[Document], locks: Sequence[Document]
) -> File:
    """Alex, Sam and Jo, a quay, an island and a village, and a path from the island to the
    village that takes half an hour. Both sets of the bag are COMPLETE."""
    path = [way_between("path", "island", "village")]
    stated = [*facts, takes("path", "PT30M"), every_use("bag"), every_transfer("bag")]
    places = ["quay", "island", "village"]
    return trip(
        ["alex", "sam", "jo"], places, list(options), stated, list(locks), path, objects=["bag"]
    )


def test_the_plan_carries_an_object_to_where_an_option_requires_it() -> None:
    """The bag lies at the quay. Alex takes the ferry, and Sam's office on the island requires
    the bag when the ferry lands. So the bag is carried. Where nothing requires it on the
    island, it is left at the quay: the rules put the fewest carries first."""
    options = [moves("ferry", "quay", "island"), stays("office", "island")]
    times = [*at("ferry", 9, 0, "PT1H"), *at("office", 10)]
    locks = [lock("ferry", "alex"), lock("office", "sam")]
    bag = [lies_at("bag", "quay"), carries("ferry", "bag")]
    file = a_voyage(options, [*times, *bag, requires_object("office", "bag")], locks)
    assert carried_in(first_shown(file, worst_case(file))) == [("ferry", ("bag",))]
    unused = a_voyage(options, [*times, *bag], locks)
    assert carried_in(first_shown(unused, worst_case(unused))) == []
    # An office that opens while the ferry is at sea cannot have the bag.
    early = a_voyage(
        options,
        [*at("ferry", 9, 0, "PT1H"), *at("office", 9, 30), *bag, requires_object("office", "bag")],
        locks,
    )
    assert first_shown(early, worst_case(early)) is None


def test_an_option_that_uses_a_carried_object_waits_until_it_has_arrived() -> None:
    """The office can open at any time. It requires the bag, so it opens when the ferry lands."""
    options = [moves("ferry", "quay", "island"), stays("office", "island")]
    facts = [
        *at("ferry", 9, 0, "PT1H"),
        *whenever("office"),
        lies_at("bag", "quay"),
        carries("ferry", "bag"),
        requires_object("office", "bag"),
    ]
    file = a_voyage(options, facts, [lock("ferry", "alex"), lock("office", "sam")])
    shown = first_shown(file, worst_case(file))
    assert carried_in(shown) == [("ferry", ("bag",))]
    assert start_of(shown, "office") == seconds(10)


def two_ferries(desk_at: tuple[int, int], fast_leaves: tuple[int, int] = (9, 5)) -> File:
    """A slow ferry from 9:00 am to 10:00 am and a fast one that takes ten minutes, from
    9:05 am unless the story says otherwise. Both can carry the bag that lies at the quay,
    and the slow one is listed first. Jo's desk on the island requires the bag."""
    options = [
        moves("slow", "quay", "island"),
        moves("fast", "quay", "island"),
        stays("desk", "island"),
    ]
    facts = [
        *at("slow", 9, 0, "PT1H"),
        *at("fast", *fast_leaves, "PT10M"),
        *at("desk", *desk_at),
        lies_at("bag", "quay"),
        carries("slow", "bag"),
        carries("fast", "bag"),
        requires_object("desk", "bag"),
    ]
    locks = [lock("slow", "alex"), lock("fast", "sam"), lock("desk", "jo")]
    return a_voyage(options, facts, locks)


def test_two_carries_that_end_at_one_place_are_told_apart_by_their_times() -> None:
    """Both ferries leave the bag on the island, and only the fast one is there by 9:30 am.
    The slow one is listed first, so it is the one tried first, and it is given up for its
    times. At 10:00 am both are there in time, and the plan takes the one listed first."""
    file = two_ferries((9, 30))
    assert carried_in(first_shown(file, worst_case(file))) == [("fast", ("bag",))]
    later = two_ferries((10, 0))
    assert carried_in(first_shown(later, worst_case(later))) == [("slow", ("bag",))]
    neither = two_ferries((9, 10))
    assert first_shown(neither, worst_case(neither)) is None
    # The fast ferry is kept beside the slow one whichever of them leaves first.
    before = two_ferries((9, 30), fast_leaves=(8, 55))
    assert carried_in(first_shown(before, worst_case(before))) == [("fast", ("bag",))]
    # The solver's search gives the same reports.
    assert carried_in(checked(file).itinerary) == [("fast", ("bag",))]
    assert carried_in(checked(before).itinerary) == [("fast", ("bag",))]
    assert carried_in(checked(later).itinerary) == [("slow", ("bag",))]
    assert checked(neither).answer is Answer.INFEASIBLE


def test_only_the_first_use_after_a_carry_waits_for_the_object() -> None:
    """A flight of ten minutes can leave at any time and carries the bag. Sam's counter at
    10:05 am can hand the bag over, and nobody takes it there. Jo's pick-up at 10:20 am
    requires it. The flight leaves as late as the counter lets it: at 10:05 am. The counter
    does not use the bag, so it does not wait for the flight to be over."""
    options = [
        moves("flight", "quay", "island"),
        stays("counter", "island"),
        stays("pick-up", "island"),
    ]
    facts = [
        *whenever("flight", "PT10M"),
        *at("counter", 10, 5),
        *at("pick-up", 10, 20),
        lies_at("bag", "quay"),
        carries("flight", "bag"),
        hands_over("counter", "bag"),
        requires_object("pick-up", "bag"),
    ]
    locks = [lock("flight", "alex"), lock("counter", "sam"), lock("pick-up", "jo")]
    file = a_voyage(options, facts, locks)
    shown = first_shown(file, worst_case(file))
    assert carried_in(shown) == [("flight", ("bag",))]
    assert [each.handed for each in shown or ()] == [(), (), ()]
    assert start_of(shown, "flight") == seconds(10, 5)
    assert checked(file).itinerary == shown


def test_an_object_is_carried_twice_one_option_after_the_other() -> None:
    """A ferry carries the bag to the island, and a bus carries it on to the village. The bus
    uses the bag, so it leaves no earlier than the ferry lands."""
    options = [
        moves("ferry", "quay", "island"),
        moves("bus", "island", "village"),
        stays("inn", "village"),
    ]
    facts = [
        *at("ferry", 9, 0, "PT1H"),
        *whenever("bus", "PT20M"),
        *at("inn", 11),
        lies_at("bag", "quay"),
        carries("ferry", "bag"),
        carries("bus", "bag"),
        requires_object("inn", "bag"),
    ]
    locks = [lock("ferry", "alex"), lock("bus", "sam"), lock("inn", "jo")]
    file = a_voyage(options, facts, locks)
    world = worst_case(file)
    shown = first_shown(file, world)
    assert shown is not None
    assert carried_in(shown) == [("ferry", ("bag",)), ("bus", ("bag",))]
    # The bus comes after the ferry, so it leaves as early as it can: when the ferry lands.
    assert start_of(shown, "bus") == seconds(10)
    assert just_before(file, world, shown)["bag"] == (
        frozenset({Where(place="quay")}),
        frozenset({Where(place="island")}),
        frozenset({Where(place="village")}),
    )
    assert checked(file).itinerary == shown
    # A bus that has to leave before the ferry lands cannot have the bag.
    missed = a_voyage(options, [*facts[:3], *at("bus", 9, 30, "PT20M"), *facts[6:]], locks)
    assert first_shown(missed, worst_case(missed)) is None
    assert checked(missed).answer is Answer.INFEASIBLE


def test_a_carried_object_is_handed_over_where_it_lands() -> None:
    """The ferry carries the bag to the island. Alex takes it at the claim there and walks to
    the inn in the village, which requires it."""
    options = [moves("ferry", "quay", "island"), stays("claim", "island"), stays("inn", "village")]
    facts = [
        *at("ferry", 9, 0, "PT1H"),
        *whenever("claim"),
        *at("inn", 11),
        lies_at("bag", "quay"),
        carries("ferry", "bag"),
        hands_over("claim", "bag"),
        requires_object("inn", "bag"),
    ]
    file = a_voyage(options, facts, [lock("ferry", "alex"), lock("inn", "alex")])
    world = worst_case(file)
    shown = first_shown(file, world)
    assert shown is not None
    assert [(each.option, each.carried, each.handed) for each in shown if each.option] == [
        ("ferry", ("bag",), ()),
        ("claim", (), (("bag", "alex"),)),
        ("inn", (), ()),
    ]
    assert just_before(file, world, shown)["bag"][1:] == (
        frozenset({Where(place="island")}),
        frozenset({Where(person="alex")}),
    )
    assert checked(file).itinerary == shown


def test_a_bag_that_the_cabin_refuses_is_dropped_and_carried_in_the_hold() -> None:
    """Alex has the bag, and the ferry refuses it and carries it. A drop at the quay keeps it.
    So Alex goes to the drop, the ferry carries the bag, and the office on the island finds
    it there. With no drop, Alex cannot be rid of the bag, and nothing works."""
    options = [stays("drop", "quay"), moves("ferry", "quay", "island"), stays("office", "island")]
    facts = [
        *at("drop", 8, 30),
        *at("ferry", 9, 0, "PT1H"),
        *at("office", 10),
        has_object("alex", "bag"),
        keeps("drop", "bag"),
        carries("ferry", "bag"),
        refuses_object("ferry", "bag"),
        requires_object("office", "bag"),
    ]
    locks = [lock("ferry", "alex"), lock("office", "alex")]
    file = a_voyage(options, facts, locks)
    shown = first_shown(file, worst_case(file))
    assert [(each.option, each.persons, each.carried) for each in shown or ()] == [
        ("drop", ("alex",), ()),
        ("ferry", ("alex",), ("bag",)),
        ("office", ("alex",), ()),
    ]
    assert checked(file).itinerary == shown
    no_drop = a_voyage(options[1:], [fact for fact in facts if fact.get("option") != "drop"], locks)
    assert first_shown(no_drop, worst_case(no_drop)) is None
    assert checked(no_drop).answer is Answer.INFEASIBLE


def nine_bags(*boats: tuple[str, int, int, str]) -> File:
    """Nine things lie at the quay, and Alex's collection on the island at 11:00 am requires
    them all. Each boat goes across with its own traveler, and can carry every one of them:
    its name, when it leaves, and how long it takes."""
    things = ["case", "trunk", "boots", "skis", "poles", "helmet", "wax", "tent", "stove"]
    riders = ["sam", "jo", "lee", "kim"]
    options = [moves(name, "quay", "island") for name, _, _, _ in boats]
    options.append(stays("collection", "island"))
    facts = [
        fact for name, hour, minute, length in boats for fact in at(name, hour, minute, length)
    ]
    facts += at("collection", 11)
    for thing in things:
        facts += [lies_at(thing, "quay"), requires_object("collection", thing)]
        facts += [carries(name, thing) for name, _, _, _ in boats]
        facts += [every_use(thing), every_transfer(thing)]
    locks = [lock(name, rider) for (name, _, _, _), rider in zip(boats, riders, strict=False)]
    locks.append(lock("collection", "alex"))
    people = ["alex", *riders[: len(boats)]]
    return trip(people, ["quay", "island"], options, facts, locks, objects=things)


def test_many_objects_with_several_carries_each_are_not_tried_in_every_combination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nine things and four boats: each thing can go four ways, a quarter of a million ways
    together. Only the last boat listed is there in time. A way that no start times keep
    is left out for each thing by itself, so the plan is timed a few times."""
    slow = [("barge", 9, 0, "PT3H"), ("raft", 9, 10, "PT3H"), ("tug", 9, 20, "PT3H")]
    file = nine_bags(*slow, ("launch", 9, 30, "PT35M"))
    found, timed = timings_for_the_report(monkeypatch, file)
    assert found.answer is Answer.FEASIBLE
    assert carried_in(found.itinerary) == [("launch", tuple(thing.id for thing in file.objects))]
    assert timed < 200
    # Where every boat is there in time, the first choice of each thing is the plan.
    easy = [("barge", 9, 0, "PT35M"), ("raft", 9, 10, "PT35M"), ("tug", 9, 20, "PT35M")]
    found, timed = timings_for_the_report(monkeypatch, nine_bags(*easy, ("launch", 9, 30, "PT35M")))
    assert carried_in(found.itinerary) == [("barge", tuple(thing.id for thing in file.objects))]
    assert timed < 200


def a_missed_connection(*more: Document) -> File:
    """A ferry carries the bag from the quay to the island and takes 30 to 75 minutes from
    9:00 am. Sam's bus at 10:00 am carries it on to the village, where Jo's inn requires it
    at 11:00 am."""
    options = [
        moves("ferry", "quay", "island"),
        moves("bus", "island", "village"),
        stays("inn", "village"),
    ]
    facts = [
        starts_at("ferry", 9),
        lasts_between("ferry", "PT30M", "PT1H15M"),
        cutoff("ferry", "PT0S"),
        *at("bus", 10, 0, "PT20M"),
        *at("inn", 11),
        lies_at("bag", "quay"),
        carries("ferry", "bag"),
        carries("bus", "bag"),
        requires_object("inn", "bag"),
        *more,
    ]
    locks = [lock("ferry", "alex"), lock("bus", "sam"), lock("inn", "jo")]
    return a_voyage(options, facts, locks)


def test_a_warning_about_a_missed_carry_names_who_and_how_late() -> None:
    """If the ferry runs longest, it lands at 10:15 am, and the bus has left without the bag.
    The finding at the bus names Sam and the quarter of an hour. The inn then has no bag
    either, and nobody can say how late: it is not on its way there."""
    file = a_missed_connection()
    found = checked(file)
    assert found.answer is Answer.FEASIBLE and found.robust is False
    assert found.at_worst == (
        bag_not_at_hand("bus", "sam", late=900),
        bag_not_at_hand("inn", "jo"),
    )
    words = report.as_text(file, found)
    assert "    ! bag would arrive 15 min after this starts.\n" in words
    assert "    ! bag would not be at hand when this starts.\n" in words
    at_hand = Constraint.AT_HAND.value
    assert report.as_json(file, found)["at_worst"] == [
        {
            "constraint": at_hand,
            "option": "bus",
            "persons": ["sam"],
            "late": "PT15M",
            "object": "bag",
        },
        {"constraint": at_hand, "option": "inn", "persons": ["jo"], "late": None, "object": "bag"},
    ]
    # A bus that also requires the bag has one finding, not two that say the same.
    both = a_missed_connection(requires_object("bus", "bag"))
    assert checked(both).at_worst == found.at_worst


def test_a_carry_that_ends_sooner_can_break_one_constraint_and_no_plan_that_works() -> None:
    """A ferry takes 15 to 45 minutes from 9:00 am. The plan has Sam take the bag at a claim
    at 9:30 am and then go into a gallery at 10:00 am that refuses it. With the short
    crossing Sam takes the bag, and the gallery refuses it. With the long one the bag is not
    there to take, and the gallery lets Sam in. So one CONSTRAINT alone can be harder with
    a shorter time. A plan that works with the longer time still works with the shorter."""
    options = [
        moves("ferry", "quay", "island"),
        stays("claim", "island"),
        stays("gallery", "island"),
    ]
    facts = [
        starts_at("ferry", 9),
        lasts_between("ferry", "PT15M", "PT45M"),
        cutoff("ferry", "PT0S"),
        *at("claim", 9, 30),
        *at("gallery", 10),
        lies_at("bag", "quay"),
        carries("ferry", "bag"),
        hands_over("claim", "bag"),
        refuses_object("gallery", "bag"),
    ]
    file = a_voyage(options, facts, [])
    nine = seconds(9)
    taken = (
        Step("ferry", "quay", "island", ("alex",), nine, None, carried=("bag",)),
        step("claim", "island", 9, "sam", minute=30, handed=(("bag", "sam"),)),
        step("gallery", "island", 10, "sam"),
    )
    short, long = worst_case(file), longest_case(file)
    assert broken(file, short, in_world(short, taken)) == [
        Broken(Constraint.REFUSED, "gallery", ("sam",), object="bag")
    ]
    assert broken(file, long, in_world(long, taken)) == [bag_not_at_hand("claim", "sam", late=900)]
    # The plan without the hand-over works with both, and so does every plan that works
    # with the longer time.
    left = (taken[0], replace(taken[1], handed=()), taken[2])
    for world in (short, long):
        assert broken(file, world, in_world(world, left)) == []


def test_the_choices_for_an_order_that_is_known_to_work_are_made_one_at_a_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Four ferries go across, each with its own traveler, and nine things lie at the quay.
    Three ferries refuse them, and nobody said what those three do with them. Where every
    unknown FACT helps, each thing can go across four ways: a quarter of a million ways
    together. The first of them works, and the search makes no other."""
    boats = ["early", "express", "fast", "family-ferry"]
    things = ["case", "trunk", "boots", "skis", "poles", "helmet", "wax", "tent", "stove"]
    options = [*(moves(boat, "quay", "island") for boat in boats), stays("collection", "island")]
    facts = [
        fact for number, boat in enumerate(boats) for fact in at(boat, 9, 10 * number, "PT35M")
    ]
    facts += [*at("collection", 11), *(needs_no_right(boat) for boat in boats)]
    for thing in things:
        facts += [lies_at(thing, "quay"), hands_over("family-ferry", thing)]
        facts += [requires_object("collection", thing), every_use(thing)]
        facts += [refuses_object(boat, thing) for boat in boats[:3]]
    people = ["alex", "sam", "jo", "lee"]
    locks = [
        lock(boat, rider) for boat, rider in zip(boats, ["sam", "jo", "lee", "alex"], strict=True)
    ]
    locks.append(lock("collection", "alex"))
    file = trip(people, ["quay", "island"], options, facts, locks, rights=True, objects=things)
    made = 0
    its_own = reference._as_chain  # pyright: ignore[reportPrivateUsage]

    def counted(*given: object) -> object:
        nonlocal made
        made += 1
        return its_own(*given)  # type: ignore[arg-type]

    monkeypatch.setattr(reference, "_as_chain", counted)
    found = compiler.check(file)
    assert found.answer is Answer.UNDETERMINED
    assert asked(found) == [(Unknown("needs no right", "collection"),)]
    assert made < 500


def test_nothing_uses_an_object_again_where_nobody_knows_when_its_carry_ends() -> None:
    """A ferry of unknown length carries the key, and an office on the island requires it.
    At worst the ferry never lands, so no choice of carries works. With an hour for the
    crossing, the carry works, and it counts on the arrival."""
    file = trip(["alex"], ["quay", "island"], [moves("ferry", "quay", "island")], [], [])
    base = worst_case(file)
    assert base.terms["ferry"].longest is None
    world = replace(base, needs=frozenset({("office", "key")}), does={("ferry", "key"): "carries"})
    visits = [("ferry", ("alex",), "quay"), ("office", ("alex",), "island")]
    at_the_quay = [frozenset({Where(place="quay")})]

    def by_position(option: str, person: str | None) -> tuple[int, int]:
        return (["ferry", "office"].index(option), -1 if person is None else 0)

    lands_at = {"ferry": "island", "office": "island"}
    assert first_hand_overs(world, "key", visits, at_the_quay, by_position, lands_at) == []
    an_hour = replace(base.terms["ferry"], shortest=3600, longest=3600)
    timed = replace(world, terms={**world.terms, "ferry": an_hour})
    assert first_hand_overs(timed, "key", visits, at_the_quay, by_position, lands_at) == [
        (((0, -1),), (("ferry", "office"),))
    ]


def test_a_carried_object_is_no_sooner_there_than_its_carry_though_a_person_is() -> None:
    """A ferry carries the bag across from 9:00 am to 10:00 am, and a walk across takes a
    quarter of an hour. Jo's desk on the island requires the bag at 9:30 am. Jo can be
    there, and the bag cannot: only the ferry moves it. Both searches say so. With the desk
    at 10:00 am the trip works."""
    options = [moves("ferry", "quay", "island"), stays("desk", "island")]
    bridge = [way_between("bridge", "quay", "island")]

    def with_the_desk_at(hour: int, minute: int, held: bool = False) -> File:
        facts = [
            *at("ferry", 9, 0, "PT1H"),
            *at("desk", hour, minute),
            takes("bridge", "PT15M"),
            has_object("alex", "bag") if held else lies_at("bag", "quay"),
            carries("ferry", "bag"),
            requires_object("desk", "bag"),
            every_use("bag"),
            every_transfer("bag"),
            complete(None, None),
        ]
        locks = [lock("ferry", "alex"), lock("desk", "jo")]
        places = ["quay", "island"]
        return trip(["alex", "jo"], places, options, facts, locks, bridge, objects=["bag"])

    early = checked(with_the_desk_at(9, 30))
    assert early.answer is Answer.INFEASIBLE
    assert {"ferry-time", "ferry-length", "desk-time"} <= set(early.conflict)
    later = checked(with_the_desk_at(10, 0))
    assert later.answer is Answer.FEASIBLE
    assert carried_in(later.itinerary) == [("ferry", ("bag",))]
    # It is the same where Alex has the bag and is on the ferry with it.
    assert checked(with_the_desk_at(9, 30, held=True)).answer is Answer.INFEASIBLE
    in_time = checked(with_the_desk_at(10, 0, held=True))
    assert carried_in(in_time.itinerary) == [("ferry", ("bag",))]


def test_a_choice_that_comes_first_is_kept_beside_one_that_counts_on_no_arrival() -> None:
    """The bag lies at the quay. Sam can take it at a pick-up there and bring it on the
    ferry, or the ferry can carry it. Either way Alex takes it at a claim on the island and
    walks on to an inn that requires it. Both ways have two hand-overs or carries. The
    carry is in the OPTION listed first, so it is the one shown, though it counts on an
    arrival and the other way counts on none."""
    options = [
        moves("ferry", "quay", "island"),
        stays("pick-up", "quay"),
        stays("errand", "quay"),
        stays("claim", "island"),
        stays("inn", "village"),
    ]
    facts = [
        *at("ferry", 9, 0, "PT1H"),
        *at("pick-up", 8, 30),
        *at("errand", 8, 30),
        *whenever("claim"),
        *at("inn", 11, 30),
        lies_at("bag", "quay"),
        carries("ferry", "bag"),
        hands_over("pick-up", "bag"),
        hands_over("claim", "bag"),
        requires_object("inn", "bag"),
    ]
    locks = [
        lock("errand", "alex"),
        lock("pick-up", "sam"),
        lock("ferry", "alex", "sam"),
        lock("claim", "alex", "sam"),
        lock("inn", "alex"),
    ]
    file = a_voyage(options, facts, locks)
    shown = first_shown(file, worst_case(file))
    moved = [(each.option, each.carried, each.handed) for each in shown or () if each.option]
    assert [each for each in moved if each[1] or each[2]] == [
        ("ferry", ("bag",), ()),
        ("claim", (), (("bag", "alex"),)),
    ]
    assert checked(file).itinerary == shown
