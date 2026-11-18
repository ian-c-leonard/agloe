"""Where a PERSON starts from, and ending the TRIP at home."""

from collections.abc import Iterator, Sequence
from itertools import combinations_with_replacement, permutations
from random import Random

import pytest

from agloe import answers, compiler, report
from agloe.answers import Answer, Missing, Report
from agloe.file import File, FileError, ReturnsTo, StartsFrom, load
from agloe.reference import (
    Broken,
    Constraint,
    Leg,
    Remaining,
    Step,
    Unknown,
    World,
    any_works,
    best_case,
    best_cases,
    broken,
    in_world,
    itineraries,
    needless,
    no_better_than,
    staying,
    unknowns,
    with_these_at_best,
    worst_case,
)
from tests.stories import (
    Document,
    at,
    complete,
    cutoff,
    ends_at_home,
    lasts,
    lock,
    moves,
    must,
    named,
    returns_to,
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
from tests.test_cross_check import (
    PLACES,
    QUARTER,
    any_choice,
    at_second,
    possible_world,
    random_trip,
)

WALK = way_between("walk", "hotel", "museum")
TRAIN = way("train", "museum", "cottage")
CAB = way("cab", "museum", "cottage")


def day_out(
    *more: Document,
    without: Sequence[str] = (),
    decisions: Sequence[Document] = (),
    ways: Sequence[Document] = (WALK, TRAIN),
    wants: Sequence[Document] | None = None,
    persons: Sequence[str] = ("alex",),
) -> Document:
    """Alex starts from the hotel and must end the TRIP at the cottage.

    Alex is LOCKed for a visit to the museum at 2:00 pm that takes an hour. The walk between the
    hotel and the museum takes 15 minutes, and the train from the museum to the cottage takes an
    hour. ``without`` names FACTs to leave out, and ``more`` are FACTs to add.
    """
    facts = [
        starts_from("alex", "hotel"),
        returns_to("alex", "cottage"),
        starts_at("visit", 14),
        lasts("visit", "PT1H"),
        cutoff("visit", "PT0S"),
        takes("walk", "PT15M"),
        takes("train", "PT1H"),
    ]
    return {
        "persons": named(*persons),
        "places": named("hotel", "museum", "cottage"),
        "options": [stays("visit", "museum")],
        "ways": list(ways),
        "wants": [ends_at_home("alex")] if wants is None else list(wants),
        "facts": [*(fact for fact in facts if fact["id"] not in without), *more],
        "decisions": [lock("visit", *persons), *decisions],
    }


def walk(person: str = "alex", back: bool = False) -> Step:
    """The walk to the museum just before the visit, or back to the hotel just after it."""
    if back:
        return Step(None, "museum", "hotel", (person,), seconds(15), seconds(15, 15), "walk")
    return Step(None, "hotel", "museum", (person,), seconds(13, 45), seconds(14), "walk")


def visit(*persons: str) -> Step:
    return Step("visit", "museum", "museum", persons or ("alex",), seconds(14), seconds(15))


def train(person: str = "alex", end: int | None = seconds(16)) -> Step:
    return Step(None, "museum", "cottage", (person,), seconds(15), end, "train")


def not_home(*persons: str) -> Broken:
    return Broken(Constraint.MUST, None, persons, want="home")


def returns(place: str | None, person: str = "alex") -> Missing:
    """That a PERSON returns to this PLACE. None is a PLACE the FILE has yet to name."""
    return Missing(Unknown("returns to", person=person, destination=place), None)


def other_ways(origin: str, destination: str, at_most: int | None) -> Missing:
    return Missing(Unknown("other ways", origin=origin, destination=destination), at_most)


def checked(file: File) -> Report:
    """The reference checker's Report, once the COMPILER has given the same one."""
    found = answers.check(file)
    assert compiler.check(file) == found
    return found


def problems(document: Document) -> str:
    with pytest.raises(FileError) as refused:
        load(document)
    return str(refused.value)


# ------------------------------- What a FILE holds -------------------------------


def test_a_file_can_say_where_a_person_starts_from_and_returns_to() -> None:
    file = load(day_out())
    assert file.starts_from("alex") == StartsFrom("alex-start", "alex", "hotel")
    assert file.returns_to("alex") == ReturnsTo("alex-home", "alex", "cottage")
    assert [want.ends_at_home for want in file.wants] == [True]
    nothing_said = load(day_out(without=["alex-start", "alex-home"]))
    assert nothing_said.starts_from("alex") is None
    assert nothing_said.returns_to("alex") is None


def test_a_file_says_each_of_them_once_for_a_person() -> None:
    again = {"id": "alex-start-again", "person": "alex", "starts_from": "museum"}
    assert problems(day_out(again)) == "/facts/7: another FACT already states this about alex"
    again = {"id": "alex-home-again", "person": "alex", "returns_to": "cottage"}
    assert problems(day_out(again)) == "/facts/7: another FACT already states this about alex"


def test_they_name_a_person_and_a_place_of_the_file() -> None:
    assert problems(day_out(starts_from("sam", "hotel"))) == (
        "/facts/7: sam is not a PERSON in this FILE"
    )
    assert problems(day_out(returns_to("alex", "moon"), without=["alex-home"])) == (
        "/facts/6: moon is not a PLACE in this FILE"
    )


def test_a_file_states_the_want_to_end_at_home_only_as_a_must() -> None:
    never = ends_at_home("alex")
    never["holders"][0]["degree"] = -10
    assert problems(day_out(wants=[never])) == "/wants/0/holders/0/degree: 10 was expected"


def test_no_option_delivers_the_want_to_end_at_home() -> None:
    assert problems(day_out(satisfies("visit", "home"))) == "/facts/7: no OPTION delivers home"
    whole = {"id": "every-home", "complete": {"satisfies": "home"}}
    assert problems(day_out(whole)) == "/facts/7: no OPTION delivers home"
    file = load(day_out())
    for world in (best_case(file), worst_case(file), no_better_than(file, [])):
        assert "home" not in {want for _, want in world.satisfies | world.might_satisfy}


def test_a_want_about_the_whole_itinerary_names_a_property_the_format_knows() -> None:
    other = ends_at_home("alex") | {"itinerary": "ends_anywhere"}
    assert "'ends_anywhere' is not one of ['ends_at_home']" in problems(day_out(wants=[other]))


# ------------------------------- The CONSTRAINTs -------------------------------


def test_a_path_begins_where_the_fact_says() -> None:
    file = load(day_out())
    worst = worst_case(file)
    assert broken(file, worst, (walk(), visit(), train())) == []
    assert broken(file, worst, (visit(), train())) == [Broken(Constraint.PLACE, "visit", ("alex",))]
    anywhere = load(day_out(without=["alex-start"]))
    assert broken(anywhere, worst_case(anywhere), (visit(), train())) == []


def test_a_must_to_end_at_home_is_met_where_the_path_ends() -> None:
    file = load(day_out())
    assert broken(file, worst_case(file), (walk(), visit())) == [not_home("alex")]


def test_a_person_who_comes_home_and_leaves_again_is_not_home() -> None:
    back = way("back", "cottage", "museum")
    file = load(day_out(takes("back", "PT1H"), ways=[WALK, TRAIN, back]))
    again = Step(None, "cottage", "museum", ("alex",), seconds(16), seconds(17), "back")
    assert broken(file, worst_case(file), (walk(), visit(), train(), again)) == [not_home("alex")]


def stays_put(*facts: Document) -> File:
    """Alex takes part in nothing and must end the TRIP at home."""
    return trip(["alex"], ["hotel", "cottage"], [], list(facts), [], wants=[ends_at_home("alex")])


def test_a_person_who_does_nothing_ends_where_they_start() -> None:
    at_home = stays_put(starts_from("alex", "cottage"), returns_to("alex", "cottage"))
    assert broken(at_home, worst_case(at_home), ()) == []
    found = checked(at_home)
    assert (found.answer, found.itinerary) == (Answer.FEASIBLE, ())
    assert found.relies_on == ("alex-start", "alex-home", "home")

    elsewhere = stays_put(starts_from("alex", "hotel"), returns_to("alex", "cottage"))
    assert broken(elsewhere, worst_case(elsewhere), ()) == [not_home("alex")]
    found = checked(elsewhere)
    assert found.answer is Answer.UNDETERMINED
    assert found.missing == ((other_ways("hotel", "cottage", None),),)


def test_a_path_with_no_stated_start_can_begin_at_home() -> None:
    """With no FACT about where Alex starts from, the ITINERARY chooses where the path begins."""
    file = stays_put(returns_to("alex", "cottage"))
    worst = worst_case(file)
    assert broken(file, worst, (), {"alex": "cottage"}) == []
    assert broken(file, worst, (), {"alex": "hotel"}) == [not_home("alex")]
    assert broken(file, worst, (), {}) == [not_home("alex")]
    found = checked(file)
    assert (found.answer, found.itinerary) == (Answer.FEASIBLE, ())
    assert found.stays == (("alex", "cottage"),)
    assert found.relies_on == ("alex-home", "home")
    assert report.as_json(file, found)["stays"] == [{"person": "alex", "place": "cottage"}]
    assert report.as_text(file, found).splitlines()[:5] == [
        "FEASIBLE: this trip works.",
        "",
        "Nobody has to do anything.",
        "",
        "alex stays at cottage.",
    ]


def test_a_plan_says_where_only_those_stay_who_must_end_at_home() -> None:
    """Alex has a FACT about the start, and Sam holds no WANT: the plan chooses for neither."""
    found = checked(load(day_out()))
    assert found.stays == ()
    assert "stays" not in report.as_json(load(day_out()), found)
    facts = [starts_from("alex", "cottage"), returns_to("alex", "cottage")]
    facts += [returns_to("sam", "hotel")]
    wants = [ends_at_home("alex")]
    file = trip(["alex", "sam"], ["hotel", "cottage"], [], facts, [], wants=wants)
    assert checked(file).stays == ()


def test_a_stay_is_one_choice_that_does_not_follow_the_world() -> None:
    """Nobody knows where home is. Staying at the hotel works only if home is the hotel."""
    file = stays_put()
    at_the_hotel = {"alex": "hotel"}
    for home in ("hotel", "cottage", None):
        world = with_these_at_best(file, [returns(home).unknown])
        assert staying(file, world, ()) == {"alex": home}
        assert broken(file, world, (), staying(file, world, ())) == []
        expected = [] if home == "hotel" else [not_home("alex")]
        assert broken(file, world, (), at_the_hotel) == expected
    assert staying(file, worst_case(file), ()) == {}
    assert broken(file, worst_case(file), (), at_the_hotel) == [not_home("alex")]
    assert checked(file).answer is Answer.UNDETERMINED


def test_each_holder_ends_at_their_own_home() -> None:
    both = [ends_at_home("alex", "sam")]
    more = [starts_from("sam", "hotel"), returns_to("sam", "hotel")]
    file = load(day_out(*more, wants=both, persons=["alex", "sam"]))
    worst = worst_case(file)
    together = (walk(), walk("sam"), visit("alex", "sam"))
    assert broken(file, worst, (*together, train(), walk("sam", back=True))) == []
    assert broken(file, worst, (*together, train(), train("sam"))) == [not_home("sam")]
    assert broken(file, worst, together) == [not_home("alex", "sam")]

    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert set(found.itinerary) == {*together, train(), walk("sam", back=True)}


def test_a_path_of_ways_alone_can_end_at_home() -> None:
    facts = [starts_from("alex", "hotel"), returns_to("alex", "cottage")]
    facts += [takes("walk", "PT15M"), takes("train", "PT1H")]
    places = ["hotel", "museum", "cottage"]
    wants = [ends_at_home("alex")]
    file = trip(["alex"], places, [], facts, [trip_starts(12)], ways=[WALK, TRAIN], wants=wants)
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert found.itinerary == (
        Step(None, "hotel", "museum", ("alex",), seconds(12), seconds(12, 15), "walk"),
        Step(None, "museum", "cottage", ("alex",), seconds(12, 15), seconds(13, 15), "train"),
    )
    assert found.relies_on == (
        "alex-start",
        "alex-home",
        "walk-length",
        "train-length",
        "home",
        "trip-start",
    )


def test_a_movement_that_takes_no_time_can_end_at_home_as_the_trip_ends() -> None:
    document = day_out(takes("train", "PT0S"), without=["train-length"], decisions=[trip_ends(15)])
    found = checked(load(document))
    assert found.answer is Answer.FEASIBLE
    assert found.itinerary == (walk(), visit(), train(end=seconds(15)))


# ------------------------------- Where home is -------------------------------


def test_nobody_is_home_where_nobody_knows_where_home_is() -> None:
    file = load(day_out(without=["alex-home"]))
    assert broken(file, worst_case(file), (walk(), visit(), train())) == [not_home("alex")]
    assert broken(file, best_case(file), (walk(), visit(), train())) == []
    assert broken(file, best_case(file), (walk(), visit())) == []


def test_a_report_names_each_place_that_home_could_be() -> None:
    """Each PLACE needs its own plan: back to the hotel, stay at the museum, or take the train."""
    file = load(day_out(without=["alex-home"]))
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    assert found.missing == ((returns("hotel"),), (returns("museum"),), (returns("cottage"),))
    for place, plan in [
        ("hotel", (walk(), visit(), walk(back=True))),
        ("museum", (walk(), visit())),
        ("cottage", (walk(), visit(), train())),
    ]:
        there = with_these_at_best(file, [returns(place).unknown])
        assert itineraries(file, there)[0] == plan


def test_a_report_names_only_the_places_a_plan_can_end_at() -> None:
    """No OPTION or WAY goes to a PLACE the FILE has yet to name, and Alex cannot stay there."""
    file = load(day_out(without=["alex-home", "train-length"], ways=[WALK]))
    assert checked(file).missing == ((returns("hotel"),), (returns("museum"),))
    from_the_hotel = stays_put(starts_from("alex", "hotel"))
    assert checked(from_the_hotel).missing == ((returns("hotel"),),)


def test_a_home_comes_before_another_option_in_a_set() -> None:
    """The unknown FACTs have one order, in a set and between sets: ``unknowns`` gives it."""
    wants = [must("lunch", "sam"), ends_at_home("sam")]
    file = trip(["sam"], ["hotel"], [], [], [], wants=wants)
    found = checked(file)
    another = Missing(Unknown("another option", want="lunch", person="sam"), None)
    assert found.missing == ((returns("hotel", "sam"), another), (returns(None, "sam"), another))
    assert [needed.unknown for enough in found.missing for needed in enough[:1]] == [
        unknown for unknown in unknowns(file) if unknown.what == "returns to"
    ]
    assert report.as_text(file, found).splitlines()[3] == (
        "  1. Sam returns to hotel and another OPTION that SATISFIES lunch is found for sam."
    )


def test_no_possible_world_has_two_homes_for_one_person() -> None:
    file = load(day_out(without=["alex-home"]))
    with pytest.raises(ValueError, match="two different things"):
        with_these_at_best(file, [returns("hotel").unknown, returns("museum").unknown])


def test_home_can_be_a_place_the_file_has_yet_to_name() -> None:
    """Alex has nothing to do and no stated start, so Alex can stay wherever home is."""
    found = checked(stays_put())
    assert found.answer is Answer.UNDETERMINED
    assert found.missing == ((returns("hotel"),), (returns("cottage"),), (returns(None),))

    file = trip(["alex"], [], [], [], [], wants=[ends_at_home("alex")])
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    assert found.missing == ((returns(None),),)
    assert report.as_json(file, found)["missing"] == [
        [{"what": "returns to", "person": "alex", "to": None, "at_most": None}]
    ]
    assert report.as_text(file, found).splitlines()[-1] == (
        "The trip works if alex returns to a PLACE that the FILE has yet to name."
    )

    wants = [ends_at_home("alex")]
    named_now = trip(["alex"], ["cottage"], [], [returns_to("alex", "cottage")], [], wants=wants)
    assert checked(named_now).answer is Answer.FEASIBLE


def test_a_missing_home_does_not_hide_a_conflict() -> None:
    file = load(day_out(without=["alex-home"], decisions=[trip_starts(15)]))
    found = checked(file)
    assert found.answer is Answer.INFEASIBLE
    assert found.conflict == ("visit-time", "lock-visit", "trip-start")


# ------------------------------- The three answers -------------------------------


def test_a_person_travels_from_where_they_start_and_home_again() -> None:
    """The walk is as late as the visit allows, and the train home is as early as it can be."""
    found = checked(load(day_out()))
    assert found.answer is Answer.FEASIBLE
    assert found.itinerary == (walk(), visit(), train())
    assert found.relies_on == (
        "alex-start",
        "alex-home",
        "visit-time",
        "visit-length",
        "visit-cutoff",
        "walk-length",
        "train-length",
        "home",
        "lock-visit",
    )
    assert found.robust is True


def test_a_plan_relies_on_a_home_only_where_someone_must_end_there() -> None:
    found = checked(load(day_out(wants=[])))
    assert found.itinerary == (walk(), visit())
    assert found.relies_on == (
        "alex-start",
        "visit-time",
        "visit-length",
        "visit-cutoff",
        "walk-length",
        "lock-visit",
    )


def test_a_plan_relies_on_a_start_only_for_a_person_it_is_about() -> None:
    """Sam is in no OPTION and holds no WANT, so nothing in the plan is about Sam."""
    document = day_out(starts_from("sam", "cottage"), returns_to("sam", "hotel"))
    document["persons"] = named("alex", "sam")
    found = checked(load(document))
    assert found.itinerary == (walk(), visit(), train())
    assert "sam-start" not in found.relies_on
    assert "sam-home" not in found.relies_on


def test_a_person_who_travels_to_their_first_option_has_to_be_in_time() -> None:
    """Alex walks to the museum, so the visit's access cutoff counts."""
    file = load(day_out(without=["visit-cutoff"], decisions=[trip_starts(12)]))
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    assert found.missing == ((Missing(Unknown("cutoff", "visit"), 105 * 60),),)

    there_all_along = load(day_out(without=["visit-cutoff", "alex-start"]))
    assert checked(there_all_along).answer is Answer.FEASIBLE


def test_a_person_who_cannot_reach_their_first_option_makes_the_trip_infeasible() -> None:
    """The FILE lists no way from the hotel, and a FACT says it lists every one, all day."""
    no_walk = day_out(without=["walk-length"], ways=[TRAIN])
    found = checked(load(no_walk))
    assert found.answer is Answer.UNDETERMINED
    assert found.missing == ((other_ways("hotel", "museum", None),),)

    no_walk["facts"].append(complete("hotel", None))
    no_walk["decisions"].append(trip_starts(0))
    found = checked(load(no_walk))
    assert found.answer is Answer.INFEASIBLE
    assert found.conflict == (
        "alex-start",
        "visit-time",
        "ways-from-hotel",
        "lock-visit",
        "trip-start",
    )


def too_late(*spans: Document) -> File:
    """The TRIP ends at 3:30 pm, half an hour before the train would reach the cottage."""
    return load(day_out(*spans, decisions=[trip_ends(15, 30)]))


def test_other_ways_home_might_be_in_time() -> None:
    found = checked(too_late())
    assert found.answer is Answer.UNDETERMINED
    assert found.missing == (
        (other_ways("hotel", "cottage", 15 * 60),),
        (other_ways("museum", "cottage", 30 * 60),),
    )


def ruled_out(remaining: Remaining) -> bool:
    """Whether nothing works in any best case of what is left of a FILE."""
    return not any(any_works(remaining.file, world) for world in best_cases(remaining))


def has_no_record_to_spare(file: File, conflict: Sequence[str]) -> bool:
    """Whether these records rule out every plan by themselves, and no fewer of them do."""
    left = Remaining(file)
    for record in (*file.facts, *file.wants, *file.decisions):
        if record.id not in conflict:
            left = left.without(record.id)
    return ruled_out(left) and not any(ruled_out(left.without(record)) for record in conflict)


def test_a_must_to_end_at_home_can_make_a_trip_infeasible() -> None:
    file = too_late(complete(None, "cottage"))
    found = checked(file)
    assert found.answer is Answer.INFEASIBLE
    assert found.conflict == (
        "alex-home",
        "visit-time",
        "visit-length",
        "train-length",
        "ways-to-cottage",
        "home",
        "lock-visit",
        "trip-end",
    )
    assert has_no_record_to_spare(file, found.conflict)


def span(id: str, earliest: str, latest: str, to: str = "cottage") -> Document:
    """A FACT that the FILE lists every way straight to a PLACE that leaves in this span."""
    leaving = {"earliest": earliest, "latest": latest}
    return {"id": id, "complete": {"to": to, "leaving": leaving}}


def test_every_time_a_person_could_still_leave_has_to_be_ruled_out() -> None:
    """Two spans that meet at 3:10 pm rule out every way home. Either one alone does not."""
    early = span("early", at(0), at(15, 10))
    late = span("late", at(15, 10), at(15, 30))
    found = checked(too_late(early, late))
    assert found.answer is Answer.INFEASIBLE
    assert {"early", "late", "home", "trip-end"} <= set(found.conflict)

    found = checked(too_late(early))
    assert found.missing == (
        (other_ways("hotel", "cottage", 15 * 60),),
        (other_ways("museum", "cottage", 20 * 60 - 1),),
    )
    found = checked(too_late(late))
    assert found.missing == ((other_ways("museum", "cottage", 30 * 60),),)


def test_without_an_end_of_the_trip_a_person_can_wait_for_a_span_to_pass() -> None:
    file = load(day_out(complete(None, "cottage"), without=["train-length"], ways=[WALK]))
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    assert found.missing == (
        (other_ways("hotel", "cottage", None),),
        (other_ways("museum", "cottage", None),),
    )


# ------------------------------- A last step with no known end -------------------------------


def test_a_last_ride_of_unknown_length_gets_a_person_home_where_the_trip_has_no_end() -> None:
    """Whatever the train takes, it ends, and then Alex is home. Nothing has to follow it."""
    file = load(day_out(without=["train-length"]))
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert found.itinerary == (walk(), visit(), train(end=None))
    assert "train-length" not in found.relies_on
    for hours in (0, 1, 1000):
        known = load(day_out(takes("train", f"PT{hours}H"), without=["train-length"]))
        world = worst_case(known)
        assert broken(known, world, in_world(world, found.itinerary)) == []


def test_a_last_ride_of_unknown_length_has_to_be_over_when_the_trip_ends() -> None:
    file = load(day_out(without=["train-length"], decisions=[trip_ends(17)]))
    assert broken(file, worst_case(file), (walk(), visit(), train(end=None))) == [
        Broken(Constraint.WITHIN, None, ("alex",), None, 2)
    ]
    found = checked(file)
    assert found.answer is Answer.UNDETERMINED
    assert found.missing == (
        (Missing(Unknown("duration", way="train"), 2 * 3600),),
        (other_ways("hotel", "cottage", 105 * 60),),
        (other_ways("museum", "cottage", 2 * 3600),),
    )


def test_nothing_follows_a_ride_of_unknown_length() -> None:
    """The walk has no known length, so Alex is not known to reach the museum, or to be in time."""
    found = checked(load(day_out(without=["walk-length"])))
    assert found.answer is Answer.UNDETERMINED
    assert found.missing == (
        (Missing(Unknown("duration", way="walk"), None),),
        (other_ways("hotel", "museum", None),),
    )


def test_a_ride_of_known_length_is_found_where_the_trip_has_an_end() -> None:
    """The cab is listed first and nobody knows how long it takes. The train takes an hour."""
    ways = [WALK, CAB, TRAIN]
    found = checked(load(day_out(ways=ways, decisions=[trip_ends(16)])))
    assert found.answer is Answer.FEASIBLE
    assert found.itinerary == (walk(), visit(), train())

    found = checked(load(day_out(ways=ways)))
    assert found.answer is Answer.FEASIBLE
    cab = Step(None, "museum", "cottage", ("alex",), seconds(15), None, "cab")
    assert found.itinerary == (walk(), visit(), cab)


def test_a_locked_ride_home_of_unknown_length_gets_a_person_home() -> None:
    places = ["museum", "cottage"]
    facts = [returns_to("alex", "cottage"), starts_at("ride", 17)]
    wants = [ends_at_home("alex")]
    ride = [moves("ride", "museum", "cottage")]
    file = trip(["alex"], places, ride, facts, [lock("ride", "alex")], wants=wants)
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert found.itinerary == (Step("ride", "museum", "cottage", ("alex",), seconds(17), None),)

    ends = [lock("ride", "alex"), trip_ends(18)]
    found = checked(trip(["alex"], places, ride, facts, ends, wants=wants))
    assert found.missing == ((Missing(Unknown("duration", "ride"), 3600),),)


def test_a_stay_at_home_of_unknown_length_keeps_a_person_home() -> None:
    facts = [returns_to("alex", "cottage"), starts_at("supper", 19)]
    wants = [ends_at_home("alex")]
    supper = [stays("supper", "cottage")]
    file = trip(["alex"], ["cottage"], supper, facts, [lock("supper", "alex")], wants=wants)
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert found.itinerary == (Step("supper", "cottage", "cottage", ("alex",), seconds(19), None),)


# ------------------------------- With the other WANTs -------------------------------


def test_another_option_never_meets_the_must_to_end_at_home() -> None:
    """Alex cannot leave the hotel. Another OPTION might give Alex a view, but not a way home."""
    facts = [starts_from("alex", "hotel"), returns_to("alex", "cottage"), complete("hotel", None)]
    wants = [ends_at_home("alex"), must("a-view", "alex")]
    places = ["hotel", "cottage"]
    file = trip(["alex"], places, [], facts, [trip_starts(0), trip_ends(23)], wants=wants)
    assert best_case(file).another_option == {("a-view", "alex")}
    found = checked(file)
    assert found.answer is Answer.INFEASIBLE
    assert found.conflict == (
        "alex-start",
        "alex-home",
        "ways-from-hotel",
        "home",
        "trip-start",
        "trip-end",
    )


# ------------------------------- Large trips -------------------------------


def test_very_many_persons_can_take_one_way_home() -> None:
    """One step for each PERSON, and more PERSONs than Python allows calls inside calls."""

    def bus_home(count: int) -> File:
        people = [f"p{number}" for number in range(count)]
        facts = [takes("bus", "PT1S")]
        for person in people:
            facts += [starts_from(person, "hotel"), returns_to(person, "cottage")]
        bus = [way("bus", "hotel", "cottage")]
        wants = [ends_at_home(*people)]
        return trip(people, ["hotel", "cottage"], [], facts, [], ways=bus, wants=wants)

    found = answers.check(bus_home(1100))
    assert found.answer is Answer.FEASIBLE
    assert len(found.itinerary) == 1100
    assert len(checked(bus_home(150)).itinerary) == 150


def test_a_way_home_can_go_through_very_many_places() -> None:
    """A route of 1,099 WAYs, one after another."""
    places = [f"p{number}" for number in range(1100)]
    ways = [way(f"w{number}", f"p{number}", f"p{number + 1}") for number in range(1099)]
    facts = [starts_from("sam", "p0"), returns_to("sam", "p1099")]
    facts += [takes(each["id"], "PT1S") for each in ways]
    file = trip(["sam"], places, [], facts, [], ways=ways, wants=[ends_at_home("sam")])
    found = answers.check(file)
    assert found.answer is Answer.FEASIBLE
    assert [step.way for step in found.itinerary] == [each["id"] for each in ways]


# ------------------------------- Random trips -------------------------------


def a_way_home(rng: Random) -> File:
    """Alex, three PLACES, at most one OPTION, and one or two WAYs, all on a quarter-hour grid.

    The OPTION starts at 9:00 am or at 9:15 am. Alex usually starts from a stated PLACE,
    returns to a stated PLACE and must end the TRIP there. The TRIP usually ends between
    9:15 am and 10:00 am. A COMPLETE FACT often rules out unlisted WAYs to one PLACE, or to
    every PLACE, from some quarter hour until after the latest time the TRIP can end. Its span
    starts one second after a grid time and ends one second before another, so the times just
    outside it are on the grid.
    """
    options: list[Document] = []
    facts: list[Document] = []
    decisions: list[Document] = []
    if rng.random() < 0.8:
        origin, destination = rng.sample(PLACES, 2)
        stay = rng.random() < 0.5
        options.append(stays("visit", origin) if stay else moves("visit", origin, destination))
        facts.append(starts_at("visit", 9, 15 * rng.randrange(2)))
        stated = [
            lasts("visit", f"PT{15 * rng.randrange(2)}M"),
            cutoff("visit", f"PT{15 * rng.randrange(2)}M"),
        ]
        facts += [fact for fact in stated if rng.random() < 0.9]
        if rng.random() < 0.9:
            decisions.append(lock("visit", "alex"))
    ways: list[Document] = []
    for number in range(rng.choice([1, 1, 2])):
        id = f"way-{number}"
        origin, destination = rng.sample(PLACES, 2)
        both = rng.random() < 0.5
        ways.append(way_between(id, origin, destination) if both else way(id, origin, destination))
        if rng.random() < 0.7:
            facts.append(takes(id, f"PT{15 * rng.randrange(2)}M"))
    if rng.random() < 0.7:
        facts.append(starts_from("alex", rng.choice(PLACES)))
    if rng.random() < 0.85:
        facts.append(returns_to("alex", rng.choice(PLACES)))
    if rng.random() < 0.8:
        earliest = seconds(8, 30) + QUARTER * rng.randrange(4) + 1
        leaving = {"earliest": at_second(earliest), "latest": at_second(seconds(10, 15) - 1)}
        whole: Document = {"leaving": leaving}
        if rng.random() < 0.3:
            whole["to"] = rng.choice(PLACES)
        facts.append({"id": "ways", "complete": whole})
    wants = [ends_at_home("alex")] if rng.random() < 0.9 else []
    if rng.random() < 0.5:
        decisions.append(trip_starts(8, 30 + 15 * rng.randrange(2)))
    if rng.random() < 0.8:
        ends = seconds(9, 15) + QUARTER * rng.randrange(4)
        decisions.append({"id": "trip-end", "trip_ends_at": at_second(ends)})
    return trip(["alex"], PLACES, options, facts, decisions, ways, wants)


def any_path_works(file: File, world: World) -> bool:
    """Whether Alex has a path that works in this world, with nothing skipped.

    It tries up to two WAYs before the OPTION and up to two after it, listed or not, each at
    every quarter hour from 8:15 am to 10:15 am, and it tries doing without the OPTION. Three
    PLACES need no more than two WAYs in a row, and no path needs an earlier or a later time:
    the OPTION starts at 9:00 am or at 9:15 am, nothing takes more than a quarter hour, and
    the span of a COMPLETE FACT starts after 8:30 am and ends just before 10:15 am. The rules
    decide whether a path works.
    """
    grid = [seconds(8, 15) + QUARTER * quarter for quarter in range(9)]
    legs: list[Leg] = []
    for each in file.ways:
        legs.append((each.id, each.origin, each.destination))
        if each.both_ways:
            legs.append((each.id, each.destination, each.origin))
    legs += [
        (None, origin, destination)
        for origin, destination in permutations(PLACES, 2)
        if world.unlisted is None or (origin, destination) in world.unlisted
    ]

    def chains(start: str | None, end: str | None) -> Iterator[tuple[Leg, ...]]:
        """Every row of up to two WAYs from one PLACE to another. None is any PLACE."""
        if start is None or end is None or start == end:
            yield ()
        for first in legs:
            if start in (None, first[1]):
                if end in (None, first[2]):
                    yield (first,)
                for second in legs:
                    if second[1] == first[2] and end in (None, second[2]):
                        yield (first, second)

    def works(before: tuple[Leg, ...], option: Step | None, after: tuple[Leg, ...]) -> bool:
        legs = (*before, *after)
        for times in combinations_with_replacement(grid, len(legs)):
            steps = [
                Step(None, origin, destination, ("alex",), moment, None, id)
                for (id, origin, destination), moment in zip(legs, times, strict=True)
            ]
            if option is not None:
                steps.insert(len(before), option)
            if not broken(file, world, in_world(world, tuple(steps))):
                return True
        return False

    locked = any(found.option == "visit" for found in file.locks)
    if not locked and any(works(chain, None, ()) for chain in chains(None, None)):
        return True
    for option in file.options:
        start = world.terms[option.id].fixed_start
        if start is not None:
            step = Step(option.id, option.origin, option.destination, ("alex",), start, None)
            if any(
                works(before, step, after)
                for before in chains(None, option.origin)
                for after in chains(option.destination, None)
            ):
                return True
    return False


def test_the_search_finds_a_way_home_whenever_trying_every_path_does() -> None:
    """Both ends of the answer: something works in the worst case, and in the best case."""
    rng = Random(1919)
    seen: set[Answer] = set()
    for _ in range(40):
        file = a_way_home(rng)
        found = checked(file)
        seen.add(found.answer)
        assert (found.answer is Answer.FEASIBLE) == any_path_works(file, worst_case(file))
        assert (found.answer is not Answer.INFEASIBLE) == any_path_works(file, best_case(file))
    assert seen == set(Answer)


def test_the_two_checkers_agree_on_random_trips_with_starts_and_homes() -> None:
    rng = Random(2020)
    trips = [a_way_home(rng) for _ in range(150)]
    trips += [
        random_trip(rng, 0.2, contingent=0.3, with_complete=0.4, with_ways=0.9, with_ends=0.6)
        for _ in range(100)
    ]
    trips += [
        random_trip(rng, 0, ["alex", "sam"], count=2, with_ways=0.9, with_ends=0.6, with_times=0.5)
        for _ in range(60)
    ]
    seen: set[Answer] = set()
    names_the_want = at_an_end = unknown_home = no_end = 0
    for file in trips:
        found = checked(file)
        seen.add(found.answer)
        names_the_want += "home" in found.conflict
        unknown_home += any(
            needed.unknown.what == "returns to" for enough in found.missing for needed in enough
        )
        place = {unknown: number for number, unknown in enumerate(unknowns(file))}
        sets = [[place[needed.unknown] for needed in enough] for enough in found.missing]
        assert sets == sorted(sorted(each) for each in sets)
        if found.answer is Answer.FEASIBLE:
            worst = worst_case(file)
            assert broken(file, worst, found.itinerary, dict(found.stays)) == []
            assert needless(file, worst, found.itinerary) == []
        if found.itinerary:
            last = found.itinerary[-1]
            at_an_end += found.itinerary[0].option is None or last.option is None
            no_end += last.option is None and last.end is None
    assert seen == set(Answer)
    assert names_the_want >= 10
    assert at_an_end >= 25
    assert unknown_home >= 50
    assert no_end >= 2


def test_a_conflict_about_getting_home_has_no_record_to_spare() -> None:
    rng = Random(2121)
    checked_conflicts = 0
    while checked_conflicts < 25:
        file = a_way_home(rng)
        found = answers.check(file)
        if "home" not in found.conflict:
            continue
        checked_conflicts += 1
        assert has_no_record_to_spare(file, found.conflict)


def test_the_best_and_worst_cases_settle_the_answer_with_starts_and_homes() -> None:
    """What works in the worst case works in every possible world, and so on, as before.

    A possible world gives each PERSON one home. Each set of unknown FACTs a report names is
    enough, and no part of it is.
    """
    rng = Random(2222)
    seen: set[Answer] = set()
    by_chance_at_home = 0
    for number in range(160):
        if number % 2:
            file = a_way_home(rng)
        else:
            file = random_trip(rng, 0.3, with_complete=0.3, with_ways=0.8, with_ends=0.7)
        found = answers.check(file)
        seen.add(found.answer)
        best, worst = best_case(file), worst_case(file)
        always = itineraries(file, worst)
        assert bool(always) == (found.answer is Answer.FEASIBLE)
        for enough in found.missing:
            asked = [needed.unknown for needed in enough]
            assert itineraries(file, with_these_at_best(file, asked))
            for left_out in asked:
                fewer = [unknown for unknown in asked if unknown != left_out]
                assert not itineraries(file, with_these_at_best(file, fewer))
        for _ in range(6):
            world = possible_world(rng, file)
            for choice in always:
                stays = staying(file, worst, choice)
                assert broken(file, world, in_world(world, choice), stays) == []
            by_chance = [any_choice(rng, file, world) for _ in range(12)]
            by_chance = [
                each for each in by_chance if not broken(file, world, in_world(world, each))
            ]
            by_chance_at_home += bool(by_chance) and any(want.ends_at_home for want in file.wants)
            if by_chance:
                assert itineraries(file, world)
            for choice in (*itineraries(file, world), *by_chance):
                assert broken(file, best, in_world(best, choice)) == []
            if found.answer is Answer.INFEASIBLE:
                assert not by_chance
                assert not itineraries(file, world)
    assert seen == set(Answer)
    assert by_chance_at_home > 40
