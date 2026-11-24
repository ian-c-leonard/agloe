"""A right for an OBJECT: the sixteenth CONSTRAINT, in the format, the two checkers and the report.

Where an OPTION needs a right for an OBJECT, one right that covers the OBJECT is needed if a
PERSON who takes part has it just before the OPTION starts, if it is handed over in the
OPTION, or if it is carried in the OPTION. A BOOKING for the OPTION covers the OBJECTs it
names. A car ferry sells a ticket for each passenger and a ticket for each car.
"""

import json
from dataclasses import replace
from random import Random

import pytest

from agloe import answers, compiler, reference, report
from agloe.answers import Answer, Report
from agloe.file import Booking, CompleteNeedsRightFor, Fact, File, FileError, NeedsRightFor
from agloe.reference import (
    Broken,
    Constraint,
    Step,
    Unknown,
    best_case,
    broken_as_listed,
    unknowns,
    with_these_at_best,
    worst_case,
)
from tests.stories import (
    Document,
    carries,
    does_with,
    every_right_for,
    every_transfer,
    every_use,
    hands_over,
    has_object,
    keeps,
    lies_at,
    lock,
    moves,
    needs_right_for,
    requires_object,
    seconds,
    starts_from,
    stays,
    trip,
)
from tests.test_objects import a_trip_with_services, at


def checked(file: File) -> Report:
    """The reference checker's Report, once the solver's search and the COMPILER gave the same."""
    found = answers.check(file)
    assert answers.check(file, compiler.shown, compiler.works, compiler.can_work) == found
    assert compiler.check(file) == found
    return found


def booking(option: str, *covers: str) -> Document:
    return {"id": f"{option}-booking", "booking": {"option": option, "covers": list(covers)}}


def a_ferry(*facts: Document, holds: bool = True, drive: bool = True) -> File:
    """Alex takes the car ferry from Milwaukee to Muskegon at 6:00 am, and a LOCK says so.

    With ``holds``, Alex has the hire car when the TRIP starts. Otherwise it stands on the
    quay at Milwaukee, and the ferry can carry it. With ``drive``, a drive at Muskegon at
    9:00 am requires the car, and Alex is LOCKed into it. The FILE says about rights for
    the car only what ``facts`` says.
    """
    options = [moves("ferry", "milwaukee", "muskegon"), stays("drive", "muskegon")]
    stated = [
        *at("ferry", 6, 0, "PT2H30M"),
        *at("drive", 9),
        starts_from("alex", "milwaukee"),
        has_object("alex", "car") if holds else lies_at("car", "milwaukee"),
        *([] if holds else [carries("ferry", "car")]),
        *([requires_object("drive", "car")] if drive else []),
        every_use("car"),
        every_transfer("car"),
        *facts,
    ]
    locks = [lock("ferry", "alex"), *([lock("drive", "alex")] if drive else [])]
    places = ["milwaukee", "muskegon"]
    return trip(["alex"], places, options, stated, locks, objects=["car"], object_rights=True)


TICKET = needs_right_for("ferry", "car")
NO_OTHER = every_right_for("car")


# The format.


def test_a_file_says_whether_an_option_needs_a_right_for_an_object() -> None:
    file = a_ferry(TICKET, needs_right_for("drive", "car", False))
    assert file.needs_right_for("ferry", "car") is True
    assert file.needs_right_for("drive", "car") is False
    assert file.object_right("ferry", "car") == NeedsRightFor(
        "ferry-right-for-car", "ferry", "car", True
    )
    # With no FACT, nobody knows, unless a FACT says that the FILE states every such OPTION.
    assert a_ferry(TICKET).needs_right_for("drive", "car") is None
    whole = a_ferry(TICKET, NO_OTHER)
    assert whole.needs_right_for("drive", "car") is False
    assert whole.needs_right_for("ferry", "car") is True
    assert whole.object_rights_complete("car") == CompleteNeedsRightFor(
        "every-right-for-car", "car"
    )


def test_a_booking_covers_persons_and_objects() -> None:
    file = a_ferry(TICKET, booking("ferry", "alex", "car"))
    covering = file.booking_for("ferry", "car")
    assert covering == Booking("ferry-booking", "ferry", ("alex",), None, ("car",))
    assert file.booking("ferry", "alex") == covering
    assert file.booking_for("drive", "car") is None
    # A BOOKING can cover an OBJECT alone.
    alone = a_ferry(TICKET, booking("ferry", "car"))
    assert alone.booking_for("ferry", "car") == Booking(
        "ferry-booking", "ferry", (), None, ("car",)
    )


@pytest.mark.parametrize(
    ("facts", "problem"),
    [
        (
            [TICKET, {**TICKET, "id": "again"}],
            "another FACT already states this about ferry and car",
        ),
        ([NO_OTHER, {**NO_OTHER, "id": "again"}], "another FACT already states this about car"),
        ([needs_right_for("ferry", "bike")], "bike is not an OBJECT in this FILE"),
        ([every_right_for("bike")], "bike is not an OBJECT in this FILE"),
        ([booking("ferry", "car", "car")], "car is covered more than once"),
        ([booking("ferry", "bike")], "bike is not a PERSON or OBJECT in this FILE"),
    ],
)
def test_the_format_refuses_a_fact_about_a_right_that_cannot_be_meant(
    facts: list[Document], problem: str
) -> None:
    with pytest.raises(FileError) as refused:
        a_ferry(*facts)
    assert problem in str(refused.value)


# The CONSTRAINT, on plans written by hand.


def a_train(*facts: Document) -> File:
    """A train from A to B at 9:00 am needs a right for the bike, and nothing covers the
    bike unless ``facts`` says so. The train can carry the bike, and the bike can be handed
    over in it. Jo and Alex can take the train. Each story says where the bike starts."""
    options = [moves("train", "a", "b")]
    stated = [*at("train", 9), starts_from("alex", "a"), starts_from("jo", "a")]
    stated += [needs_right_for("train", "bike"), every_use("bike"), *facts]
    return trip(
        ["alex", "jo"], ["a", "b"], options, stated, [], objects=["bike"], object_rights=True
    )


def uncovered(*persons: str) -> Broken:
    return Broken(Constraint.COVERED, "train", persons, object="bike")


def ride(
    *persons: str, handed: tuple[tuple[str, str], ...] = (), carried: tuple[str, ...] = ()
) -> Step:
    return Step(
        "train", "a", "b", persons, seconds(9), seconds(9, 30), handed=handed, carried=carried
    )


def test_a_right_is_needed_where_a_person_who_takes_part_has_the_object() -> None:
    file = a_train(has_object("alex", "bike"))
    world = worst_case(file)
    assert broken_as_listed(file, world, (ride("alex"),)) == [uncovered("alex")]
    # Jo does not have the bike, and Alex stays behind with it.
    assert broken_as_listed(file, world, (ride("jo"),)) == []
    # Both ride: the finding names the one who has the bike.
    assert broken_as_listed(file, world, (ride("alex", "jo"),)) == [uncovered("alex")]


def test_a_right_is_needed_where_the_object_is_handed_over() -> None:
    file = a_train(lies_at("bike", "a"), hands_over("train", "bike"))
    world = worst_case(file)
    taken = ride("alex", handed=(("bike", "alex"),))
    assert broken_as_listed(file, world, (taken,)) == [uncovered("alex")]
    # A hand-over that nobody makes needs no right: the bike stays on the platform.
    assert broken_as_listed(file, world, (ride("alex"),)) == []


def test_a_right_is_needed_where_the_object_is_carried() -> None:
    file = a_train(lies_at("bike", "a"), carries("train", "bike"))
    world = worst_case(file)
    assert broken_as_listed(file, world, (ride("alex", carried=("bike",)),)) == [uncovered("alex")]
    assert broken_as_listed(file, world, (ride("alex"),)) == []
    # With nobody in the train, the finding names nobody.
    assert broken_as_listed(file, world, (ride(carried=("bike",)),)) == [uncovered()]


def test_a_right_is_needed_where_the_object_goes_along_with_no_choice() -> None:
    """The train requires the bike and carries it, so the bike goes along whenever the train
    runs, though the plan chooses no carry."""
    facts = [lies_at("bike", "a"), carries("train", "bike"), requires_object("train", "bike")]
    file = a_train(*facts)
    assert broken_as_listed(file, worst_case(file), (ride("alex"),)) == [uncovered("alex")]


def test_the_grounds_for_a_right_make_one_finding() -> None:
    """Jo has the bike and hands it to Alex in the train. A PERSON who takes part has it,
    and it is handed over: that is one requirement, and the finding names who has it."""
    file = a_train(has_object("jo", "bike"), hands_over("train", "bike"))
    world = worst_case(file)
    handed = ride("alex", "jo", handed=(("bike", "alex"),))
    assert broken_as_listed(file, world, (handed,)) == [uncovered("jo")]


def test_a_booking_that_covers_the_object_gives_the_right() -> None:
    held = has_object("alex", "bike")
    covered = a_train(held, booking("train", "bike"))
    assert broken_as_listed(covered, worst_case(covered), (ride("alex"),)) == []
    # A BOOKING that covers only Alex gives no right for the bike.
    for_alex = a_train(held, booking("train", "alex"))
    assert broken_as_listed(for_alex, worst_case(for_alex), (ride("alex"),)) == [uncovered("alex")]
    # A BOOKING for another OPTION gives none either.
    options = [moves("train", "a", "b"), moves("bus", "a", "b")]
    facts = [*at("train", 9), *at("bus", 9), starts_from("alex", "a"), held, every_use("bike")]
    facts += [needs_right_for("train", "bike"), booking("bus", "bike")]
    elsewhere = trip(["alex"], ["a", "b"], options, facts, [], objects=["bike"], object_rights=True)
    found = broken_as_listed(elsewhere, worst_case(elsewhere), (ride("alex"),))
    assert found == [uncovered("alex")]


def test_the_two_cases_of_a_right_for_an_object() -> None:
    """With no FACT, the worst case needs the right and the best case needs none. With a FACT
    that the right is needed, the best case has another right and the worst case has none."""
    silent = a_ferry()
    pairs = {("ferry", "car"), ("drive", "car")}
    assert worst_case(silent).ticketed == pairs == worst_case(silent).uncovered
    assert not best_case(silent).ticketed and not best_case(silent).uncovered
    needed = a_ferry(TICKET, NO_OTHER)
    assert worst_case(needed).ticketed == {("ferry", "car")} == worst_case(needed).uncovered
    assert best_case(needed).ticketed == {("ferry", "car")} and not best_case(needed).uncovered
    booked = a_ferry(TICKET, NO_OTHER, booking("ferry", "car"))
    assert worst_case(booked).ticketed == {("ferry", "car")} and not worst_case(booked).uncovered
    # What is unknown: the right where nobody says, and another right where one is needed.
    about_rights = ("needs no right for", "another right for")
    listed = [(each.what, each.option) for each in unknowns(silent) if each.what in about_rights]
    assert listed == [("needs no right for", "ferry"), ("needs no right for", "drive")]
    listed = [(each.what, each.option) for each in unknowns(needed) if each.what in about_rights]
    assert listed == [("another right for", "ferry")]
    assert not [each for each in unknowns(booked) if each.what in about_rights]


# Both checkers, and the report.


def test_a_car_that_alex_has_needs_its_ticket_on_the_ferry() -> None:
    """Alex has the car and drives it onto the ferry. The ferry carries nothing, and the car
    needs its ticket all the same: it is with Alex, who takes part."""
    file = a_ferry(TICKET, NO_OTHER, booking("ferry", "alex", "car"))
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert not any(step.carried for step in found.itinerary)
    for record in ("ferry-right-for-car", "every-right-for-car", "ferry-booking"):
        assert record in found.relies_on
    words = report.as_text(file, found)
    covers = "    ferry needs a right for car. Just before it starts: with alex."
    assert f"{covers} ferry-booking covers car.\n" in words
    assert (
        "  ferry-booking: a BOOKING for ferry covers alex and car; this plan uses it for car\n"
        in words
    )
    assert (
        "  every-right-for-car: of the OPTIONs in this FILE, only ferry needs a right for car\n"
        in words
    )
    assert "  ferry-right-for-car: ferry needs a right for car\n" in words
    said = json.loads(json.dumps(report.as_json(file, found)))["objects"][0]["covered_in"]
    assert said == [
        {
            "option": "ferry",
            "stated": True,
            "where": [{"person": "alex"}],
            "booking": "ferry-booking",
        }
    ]


def test_a_car_with_no_ticket_might_have_another() -> None:
    file = a_ferry(TICKET, NO_OTHER)
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    assert "The trip works if a right to ferry is found that covers car." in report.as_text(
        file, found
    )
    # A BOOKING that covers Alex alone does not cover the car.
    assert (
        checked(a_ferry(TICKET, NO_OTHER, booking("ferry", "alex"))).answer is Answer.UNDETERMINED
    )


def test_nobody_said_whether_the_car_needs_a_ticket() -> None:
    file = a_ferry()
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    words = report.as_text(file, found)
    assert "The trip works if ferry and drive need no right for car.\n" in words
    # A BOOKING that covers the car is enough too, whatever the ferry needs.
    instead = (
        "If ferry does need a right for car, a BOOKING for it that covers car is enough instead."
    )
    assert f"\n{instead}\n" in words
    # A BOOKING that covers the car on the ferry settles the ferry, whatever it needs.
    booked = a_ferry(booking("ferry", "car"), needs_right_for("drive", "car", False))
    found = checked(booked)
    assert found.answer is Answer.FEASIBLE
    silent = "    The FILE does not say whether ferry needs a right for car."
    holds = (
        "Just before it starts: with alex. ferry-booking covers car, so the plan holds if it does."
    )
    assert f"{silent} {holds}\n" in report.as_text(booked, found)
    # One FACT says that nothing needs a right for the car.
    whole = a_ferry(NO_OTHER)
    found = checked(whole)
    assert found.answer is Answer.FEASIBLE
    assert "every-right-for-car" in found.relies_on
    assert (
        "  every-right-for-car: no OPTION in this FILE needs a right for car\n"
        in report.as_text(whole, found)
    )


def test_a_car_on_the_quay_stays_there_where_nothing_covers_it() -> None:
    """The car stands on the quay, and the ferry can carry it. No drive needs it. Nothing
    covers it on the ferry, so the plan does not carry it, and that works."""
    file = a_ferry(TICKET, NO_OTHER, holds=False, drive=False)
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert [(step.option, step.carried) for step in found.itinerary] == [("ferry", ())]
    # With the drive on the far side, the car has to cross, and it has no right.
    needed = a_ferry(TICKET, NO_OTHER, holds=False)
    found = checked(needed)
    assert found.answer is Answer.UNDETERMINED
    assert "works if a right to ferry is found that covers car." in report.as_text(needed, found)
    # With a BOOKING that covers it, the ferry carries it.
    booked = a_ferry(TICKET, NO_OTHER, booking("ferry", "car"), holds=False)
    found = checked(booked)
    assert found.answer is Answer.FEASIBLE
    assert [(step.option, step.carried) for step in found.itinerary[:1]] == [("ferry", ("car",))]


def test_a_person_leaves_the_object_behind_where_nothing_covers_it() -> None:
    """Alex has the bike. A cloakroom at A keeps bikes, and the train needs a right for the
    bike that nothing gives. So Alex stops at the cloakroom first, though no LOCK says so."""
    options = [stays("cloakroom", "a"), moves("train", "a", "b")]
    facts = [*at("cloakroom", 8), *at("train", 9), starts_from("alex", "a")]
    facts += [has_object("alex", "bike"), keeps("cloakroom", "bike")]
    facts += [
        every_use("bike"),
        every_transfer("bike"),
        needs_right_for("train", "bike"),
        every_right_for("bike"),
    ]
    file = trip(
        ["alex"],
        ["a", "b"],
        options,
        facts,
        [lock("train", "alex")],
        objects=["bike"],
        object_rights=True,
    )
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert [step.option for step in found.itinerary] == ["cloakroom", "train"]
    # With no cloakroom on the way, the bike is with Alex on the train.
    without = replace(
        file,
        options=file.options[1:],
        facts=tuple(f for f in file.facts if getattr(f, "option", "") != "cloakroom"),
    )
    assert checked(without).answer is Answer.UNDETERMINED


def test_a_service_with_nobody_in_it_needs_the_right_for_what_it_carries() -> None:
    """A luggage service takes the bags from the hotel to the airport with nobody in it, and a
    pickup at the airport requires them. The service needs a right for the bags."""
    options = [moves("service", "hotel", "airport"), stays("pickup", "airport")]

    def service(*more: Document) -> File:
        facts = [*at("service", 9), *at("pickup", 11), starts_from("alex", "airport")]
        facts += [
            lies_at("bags", "hotel"),
            carries("service", "bags"),
            requires_object("pickup", "bags"),
        ]
        facts += [
            every_use("bags"),
            every_transfer("bags"),
            needs_right_for("service", "bags"),
            every_right_for("bags"),
            *more,
        ]
        places = ["hotel", "airport"]
        return trip(
            ["alex"],
            places,
            options,
            facts,
            [lock("pickup", "alex")],
            objects=["bags"],
            object_rights=True,
        )

    assert checked(service()).answer is Answer.UNDETERMINED
    booked = service(booking("service", "bags"))
    found = checked(booked)
    assert found.answer is Answer.FEASIBLE
    assert [(step.option, step.persons, step.carried) for step in found.itinerary] == [
        ("service", (), ("bags",)),
        ("pickup", ("alex",), ()),
    ]
    words = report.as_text(booked, found)
    assert "  service-booking: a BOOKING for service covers bags\n" in words
    needs = "    service needs a right for bags. Just before it starts: at hotel."
    assert f"{needs} service-booking covers bags.\n" in words


def test_another_transfer_does_not_cover_an_object_that_the_option_takes_along() -> None:
    """The ferry requires the car and carries it, so the car goes along whenever the ferry
    sails. The ferry needs a right for the car, and nothing covers it. The FILE does not say
    that it states every transfer of the car. Another transfer can put the car anywhere,
    and that changes nothing: the ferry still takes the car, with no right. So the trip
    works only if a right is found."""
    options = [moves("ferry", "milwaukee", "muskegon")]
    facts = [*at("ferry", 6, 0, "PT2H30M"), starts_from("alex", "milwaukee")]
    facts += [lies_at("car", "milwaukee"), carries("ferry", "car"), requires_object("ferry", "car")]
    facts += [every_use("car"), needs_right_for("ferry", "car"), every_right_for("car")]
    places, locks = ["milwaukee", "muskegon"], [lock("ferry", "alex")]
    file = trip(["alex"], places, options, facts, locks, objects=["car"], object_rights=True)
    world = with_these_at_best(file, [Unknown("another transfer", about="car")])
    assert world.brought == {"car"} and world.uncovered == {("ferry", "car")}
    assert not reference.any_works(file, world)
    assert not compiler.works(file, world)
    sailing = Step("ferry", "milwaukee", "muskegon", ("alex",), seconds(6), seconds(8, 30))
    lacks = Broken(Constraint.COVERED, "ferry", ("alex",), object="car")
    assert broken_as_listed(file, world, (sailing,)) == [lacks]
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    asked = [[each.unknown.what for each in group] for group in found.missing]
    assert asked == [["another right for"]]


def test_a_booking_names_persons_and_objects_so_that_no_two_look_alike() -> None:
    """A BOOKING covers Alex, Sam and the car. Where the car is called Alex too, both show
    their ids. Where the car is called "camera and tripod", the name is in quotes: the list
    is joined with "and"."""
    file = a_ferry(TICKET, NO_OTHER, booking("ferry", "alex", "car"))

    def words(car: str) -> str:
        named = replace(file, objects=(replace(file.objects[0], name=car),))
        return next(
            line
            for line in report.as_text(named, checked(named)).split("\n")
            if line.startswith("  ferry-booking: ")
        )

    assert words("alex") == (
        "  ferry-booking: a BOOKING for ferry covers alex (alex) and alex (car);"
        " this plan uses it for alex (car)"
    )
    assert words("camera and tripod") == (
        '  ferry-booking: a BOOKING for ferry covers alex and "camera and tripod";'
        ' this plan uses it for "camera and tripod"'
    )


def a_quay(*facts: Document, bike_at: str = "town") -> File:
    """A ferry goes from the quay to town at 9:00 am, and a LOCK puts Alex on it. The ferry
    needs a right for the bike, and nothing covers the bike. The FILE does not say that it
    states every transfer of the bike. The bike lies in town unless the story says otherwise."""
    options = [moves("ferry", "quay", "town")]
    stated = [*at("ferry", 9), starts_from("alex", "quay"), lies_at("bike", bike_at)]
    stated += [every_use("bike"), needs_right_for("ferry", "bike"), every_right_for("bike"), *facts]
    places, locks = ["quay", "town"], [lock("ferry", "alex")]
    return trip(["alex"], places, options, stated, locks, objects=["bike"], object_rights=True)


def cases_of(file: File, found: Report) -> list[str]:
    """The cases that an UNDETERMINED report names, each in its words."""
    lines = report.as_text(file, found).split("\n")
    one = [
        line.removeprefix("The trip might work if ") for line in lines if " might work if " in line
    ]
    return one or [line.strip()[3:] for line in lines if line.startswith("  ") and ". " in line[:5]]


def test_another_transfer_and_an_option_of_which_nobody_knows_what_it_does() -> None:
    """The ferry requires the bike, which lies in town. Another transfer can bring it to the
    quay. Where nobody knows what the ferry does with the bike, it might take it along,
    and then the bike needs its right. So the transfer is not enough by itself: the ferry
    does not carry the bike, or a right is found. Where a FACT says that the ferry carries
    it, only the right helps. Where a FACT says that it leaves the bike alone, the
    transfer is enough, and it has to leave the bike on the quay and not with Alex."""
    needs = requires_object("ferry", "bike")
    unknown_action = a_quay(needs)
    found = checked(unknown_action)
    assert found.answer is Answer.UNDETERMINED
    assert cases_of(unknown_action, found) == [
        "ferry does not carry bike and another transfer puts bike where ferry starts.",
        "A right to ferry is found that covers bike"
        " and another transfer puts bike at hand for ferry.",
    ]
    carried = a_quay(needs, carries("ferry", "bike"))
    found = checked(carried)
    assert cases_of(carried, found) == [
        "a right to ferry is found that covers bike"
        " and another transfer puts bike at hand for ferry."
    ]
    left_alone = a_quay(needs, does_with("ferry", "bike", "nothing"))
    found = checked(left_alone)
    assert cases_of(left_alone, found) == ["another transfer puts bike where ferry starts."]
    said = json.loads(json.dumps(report.as_json(left_alone, found)))
    checks = [(each["option"], each["check"]) for each in said["missing"][0][0]["at_hand_for"]]
    assert checks == [("ferry", "requires"), ("ferry", "needs a right for")]


def test_an_option_that_cannot_happen_does_not_run_with_nobody_in_it() -> None:
    """A van takes a bag from A to B with nobody in it, and Alex collects the bag. The van
    also requires a bike and carries it. The bike lies at B, the van needs a right for it,
    and nothing covers it. Where another transfer brings the bike, the van takes it along
    with no right, so the van cannot run, with or without a PERSON."""
    options = [moves("van", "a", "b"), stays("pickup", "b")]
    facts = [*at("van", 9), *at("pickup", 11), lies_at("bag", "a"), carries("van", "bag")]
    facts += [requires_object("pickup", "bag"), every_transfer("bag"), every_right_for("bag")]
    facts += [lies_at("bike", "b"), requires_object("van", "bike"), carries("van", "bike")]
    facts += [needs_right_for("van", "bike")]
    locks = [lock("pickup", "alex")]
    file = trip(
        ["alex"], ["a", "b"], options, facts, locks, objects=["bag", "bike"], object_rights=True
    )
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    world = with_these_at_best(file, [Unknown("another transfer", about="bike")])
    assert reference.taken_with_no_right(world, "van", "bike")
    assert not reference.any_works(file, world) and not compiler.works(file, world)


def test_a_right_is_needed_only_where_the_hand_over_or_the_carry_happens() -> None:
    """The bike lies in town, out of reach of the train at A. A plan that hands it over in
    the train, or carries it there, breaks the fourteenth CONSTRAINT: the bike is not at
    hand. It does not break the sixteenth as well: the bike never gets into the train."""
    out_of_reach = Broken(Constraint.AT_HAND, "train", ("alex",), object="bike")
    handing = a_train(lies_at("bike", "b"), hands_over("train", "bike"))
    taken = ride("alex", handed=(("bike", "alex"),))
    assert broken_as_listed(handing, worst_case(handing), (taken,)) == [out_of_reach]
    carrying = a_train(lies_at("bike", "b"), carries("train", "bike"))
    loaded = ride("alex", carried=("bike",))
    assert broken_as_listed(carrying, worst_case(carrying), (loaded,)) == [out_of_reach]


def test_another_transfer_does_not_undo_a_hand_over_or_a_carry_that_the_plan_chooses() -> None:
    """The bike lies at A, and the FILE does not say that it states every transfer. Another
    transfer can do much, and it cannot undo what the plan itself does: a plan that hands
    the bike to Alex in the train, or carries it there, does so with no right."""
    for does, step in (
        (hands_over("train", "bike"), ride("alex", handed=(("bike", "alex"),))),
        (carries("train", "bike"), ride("alex", carried=("bike",))),
    ):
        file = a_train(lies_at("bike", "a"), does)
        world = with_these_at_best(file, [Unknown("another transfer", about="bike")])
        assert world.brought == {"bike"}
        assert broken_as_listed(file, world, (step,)) == [uncovered("alex")]
        assert not reference.works_as_listed(file, world, (step,))
        # The plan that leaves the bike alone works there.
        assert reference.works_as_listed(file, world, (ride("alex"),))


def test_the_report_names_every_right_for_one_object_at_once() -> None:
    """Alex has the bike on four trains in a row, and each needs a right for it. The report
    names the four together, and the search for them asks the checker a few times and not
    thousands of times."""
    places = [f"stop-{number}" for number in range(5)]
    options = [moves(f"train-{n}", places[n], places[n + 1]) for n in range(4)]
    facts = [starts_from("alex", "stop-0"), has_object("alex", "bike"), every_use("bike")]
    facts += [every_transfer("bike"), every_right_for("bike")]
    for number in range(4):
        facts += [*at(f"train-{number}", 9 + number), needs_right_for(f"train-{number}", "bike")]
    locks = [lock(f"train-{number}", "alex") for number in range(4)]
    file = trip(["alex"], places, options, facts, locks, objects=["bike"], object_rights=True)
    asked = 0

    def counted(file: File, world: reference.World) -> bool:
        nonlocal asked
        asked += 1
        return compiler.works(file, world)

    found = answers.check(file, compiler.shown, counted, compiler.can_work)
    assert found == checked(file)
    assert asked < 30
    trains = "train-0, train-1, train-2 and train-3"
    assert f"The trip works if a right to each of {trains} is found that covers bike.\n" in (
        report.as_text(file, found)
    )


def with_rights(rng: Random, file: File) -> File:
    """The same FILE, with FACTs about rights for its OBJECTs chosen at random: some OPTIONs
    need a right for an OBJECT, some need none, of some nobody says, and some BOOKINGs cover
    an OBJECT. Some OBJECTs keep the FACT that the FILE states every OPTION that needs one."""
    facts: list[Fact] = [fact for fact in file.facts if not isinstance(fact, CompleteNeedsRightFor)]
    for thing in file.objects:
        if rng.random() < 0.4:
            facts.append(CompleteNeedsRightFor(f"every-right-for-{thing.id}", thing.id))
        for option in file.options:
            roll = rng.random()
            name = f"{option.id}-right-for-{thing.id}"
            if roll < 0.4:
                facts.append(NeedsRightFor(name, option.id, thing.id, True))
                if rng.random() < 0.6:
                    covers = Booking(
                        f"{option.id}-covers-{thing.id}", option.id, (), None, (thing.id,)
                    )
                    facts.append(covers)
            elif roll < 0.5:
                facts.append(NeedsRightFor(name, option.id, thing.id, False))
    return replace(file, facts=tuple(facts))


def test_both_checkers_agree_on_trips_with_rights_for_objects() -> None:
    """On random trips with vans and FACTs about rights for the OBJECTs, the solver's search and
    the COMPILER give the report that the reference checker gives. A plan that is shown
    works as listed in the worst case, and it relies on each BOOKING that it names."""
    rng = Random(16)
    seen: dict[Answer, int] = {}
    covered = asked = 0
    for _ in range(120):
        file = with_rights(rng, a_trip_with_services(rng))
        found = checked(file)
        seen[found.answer] = seen.get(found.answer, 0) + 1
        if found.answer is Answer.FEASIBLE:
            assert reference.works_as_listed(file, worst_case(file), found.itinerary)
        named = [use.by for carried in found.objects for use in carried.uses if use.by is not None]
        assert set(named) <= set(found.relies_on)
        covered += bool(named)
        about = ("needs no right for", "another right for")
        asked += any(each.unknown.what in about for group in found.missing for each in group)
    assert seen[Answer.FEASIBLE] > 20 and seen[Answer.UNDETERMINED] > 20
    assert covered > 5 and asked > 15
