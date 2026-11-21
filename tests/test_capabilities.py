"""CAPABILITIES: what a PERSON can do, and what an OPTION requires of the PERSONs in it."""

import json
from dataclasses import replace
from random import Random

import pytest

from agloe import answers, compiler, report
from agloe.answers import Answer, Missing, Report, Supply
from agloe.file import Capability, CompleteRequires, File, FileError, Has, Requires, load
from agloe.reference import (
    Broken,
    Constraint,
    Remaining,
    Step,
    Unknown,
    World,
    best_case,
    best_cases,
    broken,
    in_world,
    itineraries,
    unknowns,
    with_one_required,
    with_these_at_best,
    worst_case,
)
from tests.stories import (
    EXAMPLES,
    Document,
    booking,
    budget,
    can,
    cannot,
    cap,
    complete,
    cutoff,
    every_requirement,
    every_right,
    lasts,
    lock,
    moves,
    must,
    must_not,
    needs_right,
    offer,
    requires,
    satisfies,
    seconds,
    starts_at,
    stays,
    trip,
)
from tests.test_cross_check import any_choice, possible_world, random_trip

TOUR = Step("tour", "dock", "dock", ("alex", "sam", "jo"), seconds(15), seconds(17))


def at_three(option: str) -> list[Document]:
    return [starts_at(option, 15), lasts(option, "PT2H"), cutoff(option, "PT0S")]


def a_tour(
    *more: Document,
    persons: tuple[str, ...] = ("alex", "sam", "jo"),
    locked: tuple[str, ...] | None = None,
    capabilities: tuple[str, ...] = ("swimming",),
) -> File:
    """A kayak tour at 3:00 pm for two hours, with these PERSONs LOCKed into it.

    The FILE says about CAPABILITIES only what ``more`` says.
    """
    names = persons if locked is None else locked
    locks = [lock("tour", *names)] if names else []
    options = [stays("tour", "dock")]
    return trip(
        list(persons),
        ["dock"],
        options,
        [*at_three("tour"), *more],
        locks,
        capabilities=capabilities,
    )


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
    """The kayak tour as the JSON an agent would write, with these FACTs about swimming."""
    return {
        "persons": [{"id": "alex", "name": "Alex"}],
        "places": [{"id": "dock", "name": "the dock"}],
        "capabilities": [{"id": "swimming", "name": "swimming"}],
        "options": [stays("tour", "dock")],
        "ways": [],
        "wants": [],
        "facts": list(facts),
        "decisions": [],
    }


# What a FILE holds.


def test_a_file_lists_capabilities_and_states_three_facts_about_them() -> None:
    file = a_tour(
        requires("tour", "swimming", "each"), can("alex", "swimming"), cannot("jo", "swimming")
    )
    assert file.capabilities == (Capability("swimming", "swimming"),)
    assert file.requirement("tour", "swimming") == Requires(
        "tour-requires-swimming", "tour", "swimming", "each"
    )
    assert file.ability("jo", "swimming") == Has("jo-swimming", "jo", "swimming", False)
    assert file.has("alex", "swimming") is True
    assert file.has("jo", "swimming") is False
    assert file.has("sam", "swimming") is None
    whole = a_tour(every_requirement("swimming"))
    assert whole.requires_complete("swimming") == CompleteRequires("every-swimming", "swimming")


def test_a_file_without_capabilities_lists_none() -> None:
    file = trip(["alex"], ["dock"], [stays("tour", "dock")], at_three("tour"), [])
    assert file.capabilities == ()
    assert best_case(file).requires == {} == worst_case(file).requires


@pytest.mark.parametrize("of", ["none", "one", "each"])
def test_a_fact_states_what_an_option_requires(of: str) -> None:
    assert a_tour(requires("tour", "swimming", of)).requires("tour", "swimming") == of


def test_with_no_fact_nobody_knows_what_an_option_requires() -> None:
    assert a_tour().requires("tour", "swimming") is None


def test_a_complete_set_says_that_an_option_with_no_fact_requires_nothing() -> None:
    assert a_tour(every_requirement("swimming")).requires("tour", "swimming") == "none"
    stated = a_tour(every_requirement("swimming"), requires("tour", "swimming", "each"))
    assert stated.requires("tour", "swimming") == "each"


def test_a_requirement_is_of_none_one_or_each() -> None:
    document = a_document(requires("tour", "swimming", "two"))
    assert "/facts/0" in problems(document)


def test_a_fact_about_a_person_says_yes_or_no() -> None:
    fact = can("alex", "swimming")
    del fact["has"]
    assert "/facts/0" in problems(a_document(fact))


@pytest.mark.parametrize(
    "fact",
    [can("alex", "diving"), requires("tour", "diving"), every_requirement("diving")],
    ids=["has", "requires", "complete"],
)
def test_each_fact_names_a_capability_of_the_file(fact: Document) -> None:
    assert problems(a_document(fact)) == "/facts/0: diving is not a CAPABILITY in this FILE"


def test_a_fact_about_a_capability_names_a_person_or_an_option_of_the_file() -> None:
    nobody = a_document(can("max", "swimming"))
    assert problems(nobody) == "/facts/0: max is not a PERSON in this FILE"
    nothing = a_document(requires("cruise", "swimming"))
    assert problems(nothing) == "/facts/0: cruise is not an OPTION in this FILE"


def test_a_person_has_one_fact_about_each_capability() -> None:
    again = cannot("alex", "swimming")
    again["id"] = "alex-swimming-again"
    document = a_document(can("alex", "swimming"), again)
    assert problems(document) == (
        "/facts/1: another FACT already states this about alex and swimming"
    )


def test_an_option_has_one_fact_about_each_capability() -> None:
    again = requires("tour", "swimming", "none")
    again["id"] = "tour-swimming-again"
    document = a_document(requires("tour", "swimming", "each"), again)
    assert problems(document) == (
        "/facts/1: another FACT already states this about tour and swimming"
    )


def test_a_capability_has_one_fact_that_its_set_is_complete() -> None:
    again = every_requirement("swimming")
    again["id"] = "every-swimming-again"
    document = a_document(every_requirement("swimming"), again)
    assert problems(document) == "/facts/1: another FACT already states this about swimming"


def test_a_capability_has_an_id_of_its_own() -> None:
    document = a_document()
    document["capabilities"].append({"id": "alex", "name": "being Alex"})
    assert "alex" in problems(document)


# The CONSTRAINT.


def not_met(option: str, *persons: str, capability: str = "swimming") -> Broken:
    return Broken(Constraint.REQUIRED, option, persons, capability=capability)


def test_a_requirement_of_one_person_is_met_by_anybody_who_takes_part() -> None:
    file = a_tour(
        requires("tour", "swimming", "one"),
        cannot("alex", "swimming"),
        can("sam", "swimming"),
        cannot("jo", "swimming"),
        locked=(),
    )
    world = worst_case(file)
    assert broken(file, world, (TOUR,)) == []
    without_sam = replace(TOUR, persons=("jo", "alex"))
    assert broken(file, world, (without_sam,)) == [not_met("tour", "alex", "jo")]


def test_a_requirement_of_each_person_names_those_who_lack_it() -> None:
    file = a_tour(
        requires("tour", "swimming", "each"),
        can("alex", "swimming"),
        cannot("sam", "swimming"),
        cannot("jo", "swimming"),
        locked=(),
    )
    world = worst_case(file)
    assert broken(file, world, (TOUR,)) == [not_met("tour", "sam", "jo")]
    assert broken(file, world, (replace(TOUR, persons=("alex",)),)) == []


def test_an_option_that_requires_nothing_asks_nothing() -> None:
    file = a_tour(requires("tour", "swimming", "none"), cannot("alex", "swimming"))
    assert broken(file, worst_case(file), (TOUR,)) == []


def test_only_a_person_who_takes_part_counts() -> None:
    """Sam can swim and stays ashore. That does nothing for Alex and Jo."""
    file = a_tour(
        requires("tour", "swimming", "one"),
        can("sam", "swimming"),
        cannot("alex", "swimming"),
        cannot("jo", "swimming"),
        locked=("alex", "jo"),
    )
    ashore = replace(TOUR, persons=("alex", "jo"))
    assert broken(file, worst_case(file), (ashore,)) == [not_met("tour", "alex", "jo")]
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert found.itinerary == (TOUR,)


def test_one_person_can_meet_several_requirements_and_two_can_meet_different_ones() -> None:
    both = ("swimming", "steering")
    asked = [requires("tour", "swimming", "one"), requires("tour", "steering", "one")]
    alone = a_tour(
        *asked,
        can("alex", "swimming"),
        can("alex", "steering"),
        persons=("alex",),
        capabilities=both,
    )
    assert checked(alone).answer is Answer.FEASIBLE
    shared = a_tour(
        *asked,
        can("alex", "swimming"),
        cannot("alex", "steering"),
        cannot("sam", "swimming"),
        can("sam", "steering"),
        persons=("alex", "sam"),
        capabilities=both,
    )
    found = checked(shared)
    assert found.answer is Answer.FEASIBLE
    assert found.supplies == (
        Supply("tour", "swimming", "one", ("alex",)),
        Supply("tour", "steering", "one", ("sam",)),
    )


def test_both_kinds_on_one_option_are_met_together() -> None:
    """Alex has to come, can swim and cannot drive. Sam can drive and cannot swim.

    The trip there requires one driver and requires everybody to swim. Each can be met by
    itself, and the two cannot be met together.
    """
    people = [
        can("alex", "swimming"),
        cannot("alex", "driving"),
        cannot("sam", "swimming"),
        can("sam", "driving"),
    ]
    both = ("swimming", "driving")
    a_driver = requires("tour", "driving", "one")
    swimmers = requires("tour", "swimming", "each")
    nothing = [requires("tour", "driving", "none"), requires("tour", "swimming", "none")]

    def the_trip(*asked: Document) -> File:
        stated = {fact["requires"]["capability"]: fact for fact in (*nothing, *asked)}
        return a_tour(
            *stated.values(),
            *people,
            persons=("alex", "sam"),
            locked=("alex",),
            capabilities=both,
        )

    assert checked(the_trip(a_driver)).answer is Answer.FEASIBLE
    assert checked(the_trip(swimmers)).answer is Answer.FEASIBLE
    found = checked(the_trip(a_driver, swimmers))
    assert found.answer is Answer.INFEASIBLE
    assert found.conflict == (
        "tour-requires-driving",
        "tour-requires-swimming",
        "alex-driving",
        "sam-swimming",
        "lock-tour",
    )


# The best case and the worst case.


def test_the_two_cases_take_what_the_file_does_not_say_each_its_own_way() -> None:
    file = a_tour(can("alex", "swimming"), cannot("sam", "swimming"))
    best, worst = best_case(file), worst_case(file)
    assert best.requires == {}
    assert worst.requires == {("tour", "swimming"): "each"}
    assert best.has == {("alex", "swimming"), ("jo", "swimming")}
    assert worst.has == {("alex", "swimming")}


def test_a_complete_set_settles_what_an_option_requires_and_not_who_has_it() -> None:
    file = a_tour(every_requirement("swimming"))
    assert worst_case(file).requires == {}
    assert worst_case(file).has == frozenset()
    assert unknowns(file) == ()


def test_with_no_fact_an_option_might_require_it_of_each_person() -> None:
    """Alex can swim and Jo cannot. Requiring it of one PERSON would be met, and that is not the
    worst the tour can require."""
    file = a_tour(can("alex", "swimming"), cannot("jo", "swimming"), persons=("alex", "jo"))
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    asked = Unknown("requires nothing", "tour", about="swimming")
    assert found.missing == ((Missing(asked, None, of="one"),),)


def test_the_same_lunch_is_settled_by_a_complete_set() -> None:
    """Jo is LOCKed into lunch and cannot drive. Nobody has recorded what lunch requires."""
    people = [cannot("jo", "driving")]
    left_open = a_tour(*people, persons=("jo",), capabilities=("driving",))
    found = checked(left_open)
    assert found.answer is Answer.UNDETERMINED
    asked = Unknown("requires nothing", "tour", about="driving")
    assert found.missing == ((Missing(asked, None, of="none"),),)
    whole = a_tour(
        *people, every_requirement("driving"), persons=("jo",), capabilities=("driving",)
    )
    settled = checked(whole)
    assert settled.answer is Answer.FEASIBLE
    assert "every-driving" in settled.relies_on
    assert settled.supplies == ()


def test_listing_a_capability_that_nothing_requires_changes_no_answer() -> None:
    rng = Random(5150)
    seen: set[Answer] = set()
    for _ in range(60):
        file = random_trip(rng, leave_out=0.3, with_ways=0.5)
        listed = replace(
            file,
            capabilities=(Capability("diving", "diving"),),
            facts=(*file.facts, CompleteRequires("every-diving", "diving")),
        )
        before, after = answers.check(file), answers.check(listed)
        seen.add(before.answer)
        assert after.answer is before.answer
        assert after.itinerary == before.itinerary
        assert after.conflict == before.conflict
        assert after.missing == before.missing
    assert seen == set(Answer)


# The answers, with everything else that a TRIP asks.


def two_drives(*more: Document, locks: list[Document]) -> File:
    """Two cars leave the hotel for the dunes at 8:00 am, and each takes an hour."""
    options = [moves("first-car", "hotel", "dunes"), moves("second-car", "hotel", "dunes")]
    facts: list[Document] = []
    for option in ("first-car", "second-car"):
        facts += [starts_at(option, 8), lasts(option, "PT1H"), requires(option, "driving")]
    return trip(
        ["alex", "sam", "jo"],
        ["hotel", "dunes"],
        options,
        [*facts, *more],
        locks,
        capabilities=["driving"],
    )


SAM_DRIVES = [cannot("alex", "driving"), can("sam", "driving"), cannot("jo", "driving")]


def test_one_driver_cannot_be_in_two_cars_at_once() -> None:
    locks = [lock("first-car", "alex"), lock("second-car", "jo")]
    found = checked(two_drives(*SAM_DRIVES, locks=locks))
    assert found.answer is Answer.INFEASIBLE
    assert found.conflict == (
        "first-car-time",
        "first-car-length",
        "first-car-requires-driving",
        "second-car-time",
        "second-car-length",
        "second-car-requires-driving",
        "alex-driving",
        "jo-driving",
        "lock-first-car",
        "lock-second-car",
    )


def test_a_car_that_nobody_has_to_take_can_stay_at_the_hotel() -> None:
    found = checked(two_drives(*SAM_DRIVES, locks=[lock("first-car", "alex")]))
    assert found.answer is Answer.FEASIBLE
    assert [step.option for step in found.itinerary] == ["first-car"]
    assert found.itinerary[0].persons == ("alex", "sam")


def test_a_must_not_can_keep_the_only_driver_out() -> None:
    """Sam must not go to the dunes, and a FACT says the first car SATISFIES that."""
    file = trip(
        ["alex", "sam"],
        ["hotel", "dunes"],
        [moves("first-car", "hotel", "dunes")],
        [
            starts_at("first-car", 8),
            lasts("first-car", "PT1H"),
            requires("first-car", "driving"),
            satisfies("first-car", "sand"),
            cannot("alex", "driving"),
            can("sam", "driving"),
        ],
        [lock("first-car", "alex")],
        wants=[must_not("sand", "sam")],
        capabilities=["driving"],
    )
    found = checked(file)
    assert found.answer is Answer.INFEASIBLE
    assert found.conflict == (
        "first-car-requires-driving",
        "first-car-gives-sand",
        "alex-driving",
        "sand",
        "lock-first-car",
    )


def test_a_missing_right_can_keep_the_only_driver_out() -> None:
    """The car has one seat that is booked, for Alex, and no other can be had."""
    file = trip(
        ["alex", "sam"],
        ["hotel", "dunes"],
        [moves("first-car", "hotel", "dunes")],
        [
            starts_at("first-car", 8),
            lasts("first-car", "PT1H"),
            requires("first-car", "driving"),
            needs_right("first-car"),
            booking("first-car", "alex"),
            every_right("first-car"),
            cannot("alex", "driving"),
            can("sam", "driving"),
        ],
        [lock("first-car", "alex")],
        rights=True,
        capabilities=["driving"],
    )
    found = checked(file)
    assert found.answer is Answer.INFEASIBLE
    assert found.conflict == (
        "first-car-requires-driving",
        "first-car-needs-right",
        "first-car-booking",
        "every-right-to-first-car",
        "alex-driving",
        "lock-first-car",
    )


def test_the_driver_has_to_get_to_the_car_in_time() -> None:
    """Sam is LOCKed into breakfast at the dunes until the car leaves the hotel."""
    file = trip(
        ["alex", "sam"],
        ["hotel", "dunes"],
        [moves("first-car", "hotel", "dunes"), stays("breakfast", "dunes")],
        [
            starts_at("first-car", 8),
            lasts("first-car", "PT1H"),
            requires("first-car", "driving"),
            starts_at("breakfast", 7),
            lasts("breakfast", "PT1H"),
            requires("breakfast", "driving", "none"),
            complete("dunes", "hotel"),
            cannot("alex", "driving"),
            can("sam", "driving"),
        ],
        [lock("first-car", "alex"), lock("breakfast", "sam")],
        capabilities=["driving"],
    )
    found = checked(file)
    assert found.answer is Answer.INFEASIBLE
    assert "first-car-requires-driving" in found.conflict
    assert "ways-dunes-hotel" in found.conflict


# Evidence: FEASIBLE.


def relied_on(found: Report) -> list[str]:
    """The FACTs about CAPABILITIES that a plan relies on."""
    about = ("-swimming", "every-swimming")
    return [record for record in found.relies_on if record.endswith(about)]


def test_a_plan_relies_on_the_fact_that_an_option_requires_nothing() -> None:
    found = checked(a_tour(requires("tour", "swimming", "none"), can("alex", "swimming")))
    assert relied_on(found) == ["tour-requires-swimming"]
    assert found.supplies == ()


def test_a_plan_relies_on_the_first_person_in_it_who_meets_a_requirement_of_one() -> None:
    file = a_tour(
        requires("tour", "swimming", "one"),
        cannot("alex", "swimming"),
        can("sam", "swimming"),
        can("jo", "swimming"),
    )
    found = checked(file)
    assert relied_on(found) == ["tour-requires-swimming", "sam-swimming"]
    assert found.supplies == (Supply("tour", "swimming", "one", ("sam",)),)


def test_a_plan_relies_on_everybody_where_each_person_has_to_have_it() -> None:
    file = a_tour(
        requires("tour", "swimming", "each"),
        can("alex", "swimming"),
        can("sam", "swimming"),
        can("jo", "swimming"),
    )
    found = checked(file)
    assert relied_on(found) == [
        "tour-requires-swimming",
        "alex-swimming",
        "sam-swimming",
        "jo-swimming",
    ]
    assert found.supplies == (Supply("tour", "swimming", "each", ("alex", "sam", "jo")),)


def test_a_plan_relies_on_the_complete_set_where_no_fact_is_about_its_option() -> None:
    file = a_tour(every_requirement("swimming"), can("alex", "swimming"), cannot("jo", "swimming"))
    found = checked(file)
    assert relied_on(found) == ["every-swimming"]
    assert found.supplies == ()


def test_a_plan_relies_on_everybody_where_the_file_leaves_the_requirement_open() -> None:
    file = a_tour(can("alex", "swimming"), can("sam", "swimming"), can("jo", "swimming"))
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert relied_on(found) == ["alex-swimming", "sam-swimming", "jo-swimming"]
    assert found.supplies == (Supply("tour", "swimming", None, ("alex", "sam", "jo")),)


def test_a_plan_relies_on_no_fact_about_an_option_that_stays_out() -> None:
    file = trip(
        ["alex"],
        ["dock"],
        [stays("tour", "dock"), stays("dive", "dock")],
        [
            *at_three("tour"),
            *at_three("dive"),
            requires("tour", "swimming", "none"),
            requires("dive", "swimming", "each"),
            can("alex", "swimming"),
        ],
        [lock("tour", "alex")],
        capabilities=["swimming"],
    )
    found = checked(file)
    assert relied_on(found) == ["tour-requires-swimming"]


def test_a_plan_relies_on_no_fact_that_a_person_lacks_a_capability() -> None:
    """Sam is in the plan because Alex cannot drive. The plan holds whether or not Alex can."""
    found = checked(two_drives(*SAM_DRIVES, locks=[lock("first-car", "alex")]))
    assert "sam-driving" in found.relies_on
    assert "alex-driving" not in found.relies_on
    assert "jo-driving" not in found.relies_on


# Evidence: INFEASIBLE.


def cannot_work(left: Remaining) -> bool:
    """Whether nothing works in any best case of what is left of a FILE, by trying everything."""
    return not any(itineraries(left.file, world) for world in best_cases(left))


def test_a_conflict_names_the_requirement_the_lock_and_who_lacks_it() -> None:
    file = a_tour(
        requires("tour", "swimming", "each"),
        can("alex", "swimming"),
        can("sam", "swimming"),
        cannot("jo", "swimming"),
    )
    found = checked(file)
    assert found.answer is Answer.INFEASIBLE
    assert found.conflict == ("tour-requires-swimming", "jo-swimming", "lock-tour")


def test_a_fact_that_is_taken_out_under_a_complete_set_leaves_the_requirement_unknown() -> None:
    """Taking the FACT out of the FILE would say that the tour requires nothing. Removing it
    while a conflict is looked for says no more than that: the tour might require nothing."""
    file = a_tour(
        requires("tour", "swimming", "each"),
        every_requirement("swimming"),
        cannot("jo", "swimming"),
    )
    found = checked(file)
    assert found.answer is Answer.INFEASIBLE
    assert found.conflict == ("tour-requires-swimming", "jo-swimming", "lock-tour")
    forgotten = Remaining(file).without("tour-requires-swimming")
    assert not cannot_work(forgotten)


def with_capabilities(rng: Random, file: File) -> File:
    """The same FILE with one or two CAPABILITIES and FACTs about them, chosen at random."""
    names = ["driving", "swimming"][: rng.choice([1, 1, 2])]
    facts: list[Has | Requires | CompleteRequires] = []
    for name in names:
        for option in file.options:
            of = rng.choice([None, None, "none", "one", "one", "each", "each"])
            if of is not None:
                facts.append(Requires(f"{option.id}-{name}", option.id, name, of))
        if rng.random() < 0.3:
            facts.append(CompleteRequires(f"every-{name}", name))
        for person in file.persons:
            has = rng.choice([None, True, True, False, False])
            if has is not None:
                facts.append(Has(f"{person.id}-{name}", person.id, name, has))
    listed = tuple(Capability(name, name) for name in names)
    return replace(file, capabilities=listed, facts=(*file.facts, *facts))


def a_trip_with_capabilities(rng: Random, **how: float) -> File:
    persons = rng.choice([["alex"], ["alex", "sam"], ["alex", "sam"], ["alex", "sam", "jo"]])
    return with_capabilities(rng, random_trip(rng, persons=persons, count=2, **how))


def test_every_conflict_is_enough_and_has_no_record_to_spare() -> None:
    """Checked by trying everything, in every best case of the FILE with records taken out."""
    rng = Random(1313)
    about_a_requirement = 0
    for _ in range(260):
        file = a_trip_with_capabilities(rng, leave_out=0.1, with_complete=0.3)
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
        assert not any(isinstance(fact, CompleteRequires) for fact in kept)
        about_a_requirement += any(isinstance(fact, Requires) for fact in kept)
    assert about_a_requirement > 20


# Evidence: UNDETERMINED.


def test_the_unknown_facts_have_a_fixed_order() -> None:
    file = trip(
        ["alex", "sam"],
        ["dock", "hotel"],
        [stays("tour", "dock"), stays("lunch", "hotel")],
        [starts_at("tour", 15), starts_at("lunch", 12), can("sam", "driving")],
        [],
        rights=True,
        capabilities=["swimming", "driving"],
    )
    listed = [
        (unknown.what, unknown.option or unknown.person, unknown.about)
        for unknown in unknowns(file)
        if unknown.what in ("needs no right", "requires nothing", "another right", "has")
    ]
    assert listed == [
        ("needs no right", "tour", None),
        ("requires nothing", "tour", "swimming"),
        ("requires nothing", "tour", "driving"),
        ("needs no right", "lunch", None),
        ("requires nothing", "lunch", "swimming"),
        ("requires nothing", "lunch", "driving"),
        ("has", "alex", "swimming"),
        ("has", "alex", "driving"),
        ("has", "sam", "swimming"),
    ]
    whats = [unknown.what for unknown in unknowns(file)]
    assert whats.index("has") > max(i for i, what in enumerate(whats) if what == "other ways")


def test_whether_a_person_has_a_capability_is_asked_only_where_an_option_might_require_it() -> None:
    nothing_requires = a_tour(requires("tour", "swimming", "none"))
    assert unknowns(nothing_requires) == ()
    whole = a_tour(every_requirement("swimming"))
    assert unknowns(whole) == ()
    might = a_tour(persons=("alex",))
    assert unknowns(might) == (
        Unknown("requires nothing", "tour", about="swimming"),
        Unknown("has", person="alex", about="swimming"),
    )


def test_a_set_of_one_requirement_says_the_most_the_option_can_require() -> None:
    asked = Unknown("requires nothing", "tour", about="swimming")
    a_swimmer = a_tour(can("alex", "swimming"), cannot("jo", "swimming"), persons=("alex", "jo"))
    assert checked(a_swimmer).missing == ((Missing(asked, None, of="one"),),)
    nobody = a_tour(cannot("alex", "swimming"), cannot("jo", "swimming"), persons=("alex", "jo"))
    assert checked(nobody).missing == ((Missing(asked, None, of="none"),),)


def test_the_most_an_option_can_require_is_for_the_whole_trip() -> None:
    """Sam can swim and is LOCKed into lunch at the hotel while the tour runs.

    The tour would be fine with one swimmer, and no swimmer can be there.
    """
    file = trip(
        ["jo", "sam"],
        ["dock", "hotel"],
        [stays("tour", "dock"), stays("lunch", "hotel")],
        [
            *at_three("tour"),
            *at_three("lunch"),
            requires("lunch", "swimming", "none"),
            cannot("jo", "swimming"),
            can("sam", "swimming"),
        ],
        [lock("tour", "jo"), lock("lunch", "sam")],
        capabilities=["swimming"],
    )
    asked = Unknown("requires nothing", "tour", about="swimming")
    assert checked(file).missing == ((Missing(asked, None, of="none"),),)


def test_a_requirement_and_a_person_left_open_give_two_sets_of_one() -> None:
    file = a_tour(can("alex", "swimming"), persons=("alex", "jo"))
    found = checked(file)
    assert found.missing == (
        (Missing(Unknown("requires nothing", "tour", about="swimming"), None, of="one"),),
        (Missing(Unknown("has", person="jo", about="swimming"), None),),
    )
    assert report.as_text(file, found).splitlines()[2:] == [
        "The trip works in any of these cases:",
        "  1. Tour requires swimming of one PERSON at most.",
        "  2. Jo has the CAPABILITY swimming.",
    ]


def two_tours() -> File:
    """Two tours at 3:00 pm. Alex is LOCKed into one and Jo into the other, and neither can swim.

    Sam can swim, and can join one of them.
    """
    options = [stays("river-tour", "dock"), stays("lake-tour", "beach")]
    people = [cannot("alex", "swimming"), can("sam", "swimming"), cannot("jo", "swimming")]
    return trip(
        ["alex", "sam", "jo"],
        ["dock", "beach"],
        options,
        [*at_three("river-tour"), *at_three("lake-tour"), *people],
        [lock("river-tour", "alex"), lock("lake-tour", "jo")],
        capabilities=["swimming"],
    )


def test_a_larger_set_says_that_each_of_its_options_requires_nothing() -> None:
    """Either tour could require one swimmer if the other required none. Both cannot.

    So the limits found one at a time would be false together, and the set gives none.
    """
    file = two_tours()
    river = Unknown("requires nothing", "river-tour", about="swimming")
    lake = Unknown("requires nothing", "lake-tour", about="swimming")
    assert itineraries(file, with_one_required(file, river)) == []
    one_each = replace(
        with_these_at_best(file, [river, lake]),
        requires={("river-tour", "swimming"): "one", ("lake-tour", "swimming"): "one"},
    )
    assert itineraries(file, one_each) == []
    for only in (river, lake):
        relaxed = replace(
            with_these_at_best(file, [river, lake]),
            requires={(only.option or "", "swimming"): "one"},
        )
        assert itineraries(file, relaxed)
    found = checked(file)
    assert found.missing == ((Missing(river, None), Missing(lake, None)),)
    assert report.as_text(file, found).splitlines()[2] == (
        "The trip works if river-tour does not require swimming and lake-tour does not require"
        " swimming."
    )


def test_the_plan_for_a_requirement_of_one_person_works_at_that_requirement() -> None:
    """Jo is LOCKed into the tour and cannot swim. Sam can swim and can come along.

    Jo's place is paid for. Sam's would cost 5 USD, from a BUDGET that has 5 USD left under
    its cap. If the tour requires nothing, Jo goes alone and the 5 USD stay. The report says
    that the tour can require swimming of one PERSON, so its plan has Sam buy the place.
    """
    file = trip(
        ["jo", "sam"],
        ["dock"],
        [stays("tour", "dock")],
        [
            *at_three("tour"),
            needs_right("tour"),
            booking("tour", "jo", paid="5.00 USD", budget="money"),
            offer("tour", 1, price="5.00 USD"),
            every_right("tour", "tour-offer"),
            cannot("jo", "swimming"),
            can("sam", "swimming"),
        ],
        [lock("tour", "jo"), cap("money", "10.00 USD")],
        rights=True,
        budgets=[budget("money", "jo", "sam")],
        capabilities=["swimming"],
    )
    found = checked(file)
    asked = Unknown("requires nothing", "tour", about="swimming")
    assert found.missing == ((Missing(asked, None, of="one"),),)
    (plan,) = found.plans
    assert [(cover.person, cover.by) for cover in plan.buys] == [("sam", "tour-offer")]
    (row,) = plan.caps
    assert (row.paid, row.to_buy, row.left) == (50000, 50000, 0)
    at_nothing = answers.check(
        replace(file, facts=(*file.facts, Requires("nothing", "tour", "swimming", "none")))
    )
    assert at_nothing.answer is Answer.FEASIBLE
    assert at_nothing.caps[0].left == 50000


def test_every_set_named_is_enough_and_no_part_of_it_is() -> None:
    rng = Random(2718)
    limits: set[str | None] = set()
    kinds: set[str] = set()
    for _ in range(200):
        file = a_trip_with_capabilities(rng, leave_out=0.15)
        found = answers.check(file)
        for enough in found.missing:
            named = [needed.unknown for needed in enough]
            kinds.update(unknown.what for unknown in named)
            assert itineraries(file, with_these_at_best(file, named))
            for left_out in named:
                fewer = [unknown for unknown in named if unknown != left_out]
                assert not itineraries(file, with_these_at_best(file, fewer))
            for needed in enough:
                if needed.unknown.what != "requires nothing" or len(enough) > 1:
                    assert needed.of is None
                    continue
                limits.add(needed.of)
                one = bool(itineraries(file, with_one_required(file, needed.unknown)))
                assert needed.of == ("one" if one else "none")
    assert limits == {"one", "none"}
    assert {"requires nothing", "has"} <= kinds


# The two cases settle the answer for every possible world.


def a_world_with_capabilities(rng: Random, file: File) -> World:
    """One way the unknown FACTs could turn out, with those about CAPABILITIES too."""
    asked: dict[tuple[str, str], str] = {}
    able: set[tuple[str, str]] = set()
    for capability in file.capabilities:
        for option in file.options:
            of = file.requires(option.id, capability.id) or rng.choice(["none", "one", "each"])
            if of != "none":
                asked[option.id, capability.id] = of
        for person in file.persons:
            has = file.has(person.id, capability.id)
            if rng.random() < 0.5 if has is None else has:
                able.add((person.id, capability.id))
    return replace(possible_world(rng, file), requires=asked, has=frozenset(able))


def test_the_best_and_worst_cases_settle_the_answer_for_every_possible_world() -> None:
    """What works in the worst case works in every possible world. What works in a possible
    world works in the best case with the same start times. And an INFEASIBLE TRIP has
    nothing that works in any possible world."""
    rng = Random(1618)
    seen: set[Answer] = set()
    found_by_chance = 0
    for number in range(240):
        with_ways = 0.8 if number % 2 else 0
        file = a_trip_with_capabilities(rng, leave_out=0.2, with_complete=0.3, with_ways=with_ways)
        found = answers.check(file)
        seen.add(found.answer)
        best, worst = best_case(file), worst_case(file)
        always = itineraries(file, worst)
        assert bool(always) == (found.answer is Answer.FEASIBLE)
        for _ in range(8):
            world = a_world_with_capabilities(rng, file)
            for choice in always:
                assert broken(file, world, in_world(world, choice)) == []
            by_chance = [any_choice(rng, file, world) for _ in range(12)]
            by_chance = [
                each for each in by_chance if not broken(file, world, in_world(world, each))
            ]
            found_by_chance += len(by_chance)
            if by_chance:
                assert itineraries(file, world)
            working_here = [*itineraries(file, world), *by_chance]
            for choice in working_here:
                assert broken(file, best, in_world(best, choice)) == []
            if found.answer is Answer.INFEASIBLE:
                assert working_here == []
    assert seen == set(Answer)
    assert found_by_chance > 300


def test_a_stronger_requirement_is_never_easier_for_the_same_plan() -> None:
    """None, then of one PERSON, then of each PERSON: what meets the later meets the earlier."""
    rng = Random(4242)
    told_apart = 0
    for _ in range(200):
        file = a_trip_with_capabilities(rng, leave_out=0.1)
        world = a_world_with_capabilities(rng, file)
        pairs = [(o.id, c.id) for o in file.options for c in file.capabilities]
        option, capability = rng.choice(pairs)
        works: list[bool] = []
        choices = [any_choice(rng, file, world) for _ in range(12)]
        for of in ("none", "one", "each"):
            asked = {**world.requires, (option, capability): of}
            if of == "none":
                del asked[option, capability]
            here = replace(world, requires=asked)
            works.append(
                any(not broken(file, here, in_world(here, each)) for each in choices)
                or bool(itineraries(file, here))
            )
        assert works == sorted(works, reverse=True)
        told_apart += works[0] and not works[2]
    assert told_apart > 10


# The report.


def test_a_feasible_report_says_who_meets_each_requirement() -> None:
    path = EXAMPLES / "a-driver" / "works.json"
    text = path.with_name("works.expected.txt").read_text()
    assert text.splitlines()[-3:] == [
        "What the plan requires of the PERSONs in it:",
        "  Drive to the dunes requires driving a manual car of one PERSON: Sam has it.",
        "  Drive back to the hotel requires driving a manual car of one PERSON: Sam has it.",
    ]
    result = json.loads(path.with_name("works.expected.json").read_text())
    assert result["requirements"] == [
        {"option": "drive-out", "capability": "drive-manual", "of": "one", "persons": ["sam"]},
        {"option": "drive-back", "capability": "drive-manual", "of": "one", "persons": ["sam"]},
    ]


def test_a_feasible_report_says_where_the_file_leaves_a_requirement_open() -> None:
    file = a_tour(can("alex", "swimming"), can("sam", "swimming"), can("jo", "swimming"))
    found = checked(file)
    assert report.as_text(file, found).splitlines()[-2:] == [
        "What the plan requires of the PERSONs in it:",
        "  tour might require swimming: the FILE does not say. alex, sam and jo have it.",
    ]
    assert report.as_json(file, found)["requirements"] == [
        {"option": "tour", "capability": "swimming", "of": None, "persons": ["alex", "sam", "jo"]}
    ]


def test_a_report_with_no_requirement_to_meet_says_nothing_about_them() -> None:
    file = a_tour(every_requirement("swimming"))
    found = checked(file)
    assert "requires" not in report.as_text(file, found).split("every-swimming")[0]
    assert "What the plan requires" not in report.as_text(file, found)
    assert "requirements" not in report.as_json(file, found)


def test_the_report_puts_each_fact_about_a_capability_in_words() -> None:
    def at(option: str, hour: int) -> list[Document]:
        return [starts_at(option, hour), lasts(option, "PT1H"), cutoff(option, "PT0S")]

    file = trip(
        ["alex", "sam"],
        ["dock"],
        [stays("tour", "dock"), stays("dive", "dock"), stays("lunch", "dock")],
        [
            *at("tour", 9),
            *at("dive", 11),
            *at("lunch", 13),
            requires("tour", "swimming", "one"),
            requires("dive", "swimming", "each"),
            requires("lunch", "swimming", "none"),
            every_requirement("swimming"),
            every_requirement("driving"),
            can("alex", "swimming"),
            can("sam", "swimming"),
        ],
        [lock("tour", "alex"), lock("dive", "alex", "sam"), lock("lunch", "sam")],
        capabilities=["swimming", "driving"],
    )
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    lines = [line.strip() for line in report.as_text(file, found).splitlines()]
    about = ("-swimming: ", "every-driving: ")
    assert [line for line in lines if any(part in line for part in about)] == [
        "tour-requires-swimming: tour requires swimming of one PERSON who takes part",
        "dive-requires-swimming: dive requires swimming of each PERSON who takes part",
        "lunch-requires-swimming: lunch does not require swimming",
        "every-driving: the FILE states every OPTION that requires driving: there is none",
        "alex-swimming: alex has the CAPABILITY swimming",
        "sam-swimming: sam has the CAPABILITY swimming",
    ]
    assert lines[-3:] == [
        "What the plan requires of the PERSONs in it:",
        "tour requires swimming of one PERSON: alex has it.",
        "dive requires swimming of each PERSON: alex and sam have it.",
    ]
    whole = EXAMPLES / "a-driver" / "every-drive-is-stated.expected.txt"
    assert (
        "  every-drive-that-needs-a-driver: the FILE states every OPTION that requires driving a"
        " manual car: Drive to the dunes and Drive back to the hotel"
    ) in whole.read_text().splitlines()
    lacking = EXAMPLES / "a-kayak-tour" / "cannot-work.expected.txt"
    assert (
        "  jo-does-not-swim: Jo does not have the CAPABILITY swimming"
        in lacking.read_text().splitlines()
    )


def test_the_json_of_a_missing_fact_names_its_capability() -> None:
    file = a_tour(can("alex", "swimming"), persons=("alex", "jo"))
    assert report.as_json(file, checked(file))["missing"] == [
        [
            {
                "what": "requires nothing",
                "option": "tour",
                "capability": "swimming",
                "of_at_most": "one",
                "at_most": None,
            }
        ],
        [{"what": "has", "person": "jo", "capability": "swimming", "at_most": None}],
    ]


def test_the_answer_comes_first_for_a_file_with_capabilities() -> None:
    file = a_tour(requires("tour", "swimming", "each"), cannot("jo", "swimming"))
    first, last = compiler.reports(file)
    assert first is Answer.INFEASIBLE
    assert last == answers.check(file)


def test_a_must_for_another_option_says_what_that_option_has_to_meet() -> None:
    file = trip(
        ["alex"],
        ["dock"],
        [stays("tour", "dock")],
        [*at_three("tour"), requires("tour", "swimming", "none"), satisfies("tour", "paddling", 0)],
        [lock("tour", "alex")],
        wants=[must("paddling", "alex")],
        capabilities=["swimming"],
    )
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    assert report.as_text(file, found).splitlines()[-1] == (
        "Another OPTION helps only if the PERSON it is for can take part in it and still do"
        " everything else the trip asks of them. Whatever it requires has to be met: the PERSON"
        " has each CAPABILITY that it requires of each PERSON, and somebody who takes part in it"
        " from its start to its end has each CAPABILITY that it requires of one PERSON."
    )
