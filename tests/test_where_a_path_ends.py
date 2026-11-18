"""Where a PERSON starts from, and where they have to end the TRIP."""

from collections.abc import Iterator, Sequence
from itertools import combinations_with_replacement, permutations
from random import Random
from time import perf_counter

import pytest

from agloe import answers, compiler, report
from agloe.answers import Answer, Missing, Report
from agloe.file import File, FileError, StartsFrom, load
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
    unknowns,
    with_these_at_best,
    works_as_listed,
    worst_case,
)
from tests.stories import (
    Document,
    any_time,
    at,
    complete,
    cutoff,
    ends_at,
    lasts,
    lock,
    moves,
    must,
    named,
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
    """Alex starts from the hotel and has to end the TRIP at the cottage.

    Alex is LOCKed for a visit to the museum at 2:00 pm that takes an hour. The walk between the
    hotel and the museum takes 15 minutes, and the train from the museum to the cottage takes an
    hour. ``without`` names FACTs to leave out, and ``more`` are FACTs to add.
    """
    facts = [
        starts_from("alex", "hotel"),
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
        "wants": [ends_at("cottage", "alex")] if wants is None else list(wants),
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


def elsewhere(*persons: str, want: str = "ending") -> Broken:
    """These PERSONs do not end the TRIP where this WANT asks."""
    return Broken(Constraint.MUST, None, persons, want=want)


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


def test_a_file_can_say_where_a_person_starts_from_and_has_to_end() -> None:
    file = load(day_out())
    assert file.starts_from("alex") == StartsFrom("alex-start", "alex", "hotel")
    assert [want.ends_at for want in file.wants] == ["cottage"]
    assert load(day_out(without=["alex-start"])).starts_from("alex") is None


def test_a_file_says_once_where_a_person_starts_from() -> None:
    again = {"id": "alex-start-again", "person": "alex", "starts_from": "museum"}
    assert problems(day_out(again)) == "/facts/6: another FACT already states this about alex"


def test_a_start_and_an_end_name_a_person_and_a_place_of_the_file() -> None:
    assert problems(day_out(starts_from("sam", "hotel"))) == (
        "/facts/6: sam is not a PERSON in this FILE"
    )
    assert problems(day_out(starts_from("alex", "moon"), without=["alex-start"])) == (
        "/facts/5: moon is not a PLACE in this FILE"
    )
    assert problems(day_out(wants=[ends_at("moon", "alex")])) == (
        "/wants/0: moon is not a PLACE in this FILE"
    )


def test_a_file_states_the_want_to_end_at_a_place_only_as_a_must() -> None:
    never = ends_at("cottage", "alex")
    never["holders"][0]["degree"] = -10
    assert problems(day_out(wants=[never])) == "/wants/0/holders/0/degree: 10 was expected"


def test_no_option_delivers_the_want_to_end_at_a_place() -> None:
    assert problems(day_out(satisfies("visit", "ending"))) == "/facts/6: no OPTION delivers ending"
    whole = {"id": "every-ending", "complete": {"satisfies": "ending"}}
    assert problems(day_out(whole)) == "/facts/6: no OPTION delivers ending"
    file = load(day_out())
    assert file.says("visit", "ending") is False
    for world in (best_case(file), worst_case(file), no_better_than(file, [])):
        assert "ending" not in {want for _, want in world.satisfies | world.might_satisfy}
    assert {unknown.what for unknown in unknowns(load(day_out(without=["train-length"])))} == {
        "duration",
        "other ways",
    }


def test_a_want_about_the_whole_itinerary_says_where_it_ends() -> None:
    nowhere = ends_at("cottage", "alex")
    del nowhere["itinerary"]["ends_at"]
    assert problems(day_out(wants=[nowhere])) == (
        "/wants/0/itinerary: 'ends_at' is a required property"
    )


# ------------------------------- The CONSTRAINTs -------------------------------


def test_a_path_begins_where_the_fact_says() -> None:
    file = load(day_out())
    worst = worst_case(file)
    assert broken(file, worst, (walk(), visit(), train())) == []
    assert broken(file, worst, (visit(), train())) == [Broken(Constraint.PLACE, "visit", ("alex",))]
    anywhere = load(day_out(without=["alex-start"]))
    assert broken(anywhere, worst_case(anywhere), (visit(), train())) == []


def test_a_must_to_end_at_a_place_is_met_where_the_path_ends() -> None:
    file = load(day_out())
    assert broken(file, worst_case(file), (walk(), visit())) == [elsewhere("alex")]


def test_a_person_who_gets_there_and_leaves_again_does_not_end_there() -> None:
    back = way("back", "cottage", "museum")
    file = load(day_out(takes("back", "PT1H"), ways=[WALK, TRAIN, back]))
    again = Step(None, "cottage", "museum", ("alex",), seconds(16), seconds(17), "back")
    assert broken(file, worst_case(file), (walk(), visit(), train(), again)) == [elsewhere("alex")]


def stays_put(*facts: Document, wants: Sequence[Document] | None = None) -> File:
    """Alex takes part in nothing and has to end the TRIP at the cottage."""
    asked = [ends_at("cottage", "alex")] if wants is None else wants
    return trip(["alex"], ["hotel", "cottage"], [], list(facts), [], wants=asked)


def test_a_person_who_does_nothing_ends_where_they_start() -> None:
    there = stays_put(starts_from("alex", "cottage"))
    assert broken(there, worst_case(there), ()) == []
    found = checked(there)
    assert (found.answer, found.itinerary) == (Answer.FEASIBLE, ())
    assert found.relies_on == ("alex-start", "ending")

    away = stays_put(starts_from("alex", "hotel"))
    assert broken(away, worst_case(away), ()) == [elsewhere("alex")]
    found = checked(away)
    assert found.answer is Answer.UNDETERMINED
    assert found.missing == ((other_ways("hotel", "cottage", None),),)


def test_a_person_who_does_nothing_and_has_no_stated_start_is_where_they_have_to_end() -> None:
    """Nobody has said where Alex is, and a path can begin wherever it suits."""
    file = stays_put()
    assert broken(file, worst_case(file), ()) == []
    found = checked(file)
    assert (found.answer, found.itinerary) == (Answer.FEASIBLE, ())
    assert found.relies_on == ("ending",)


def test_nobody_ends_the_trip_at_two_places() -> None:
    first, second = ends_at("hotel", "alex", id="first"), ends_at("cottage", "alex", id="second")
    file = stays_put(wants=[first, second])
    assert broken(file, worst_case(file), ()) == [elsewhere("alex", want="second")]
    found = checked(file)
    assert found.answer is Answer.INFEASIBLE
    assert found.conflict == ("first", "second")
    assert report.as_text(file, found).splitlines()[-2:] == [
        "  first: first is a must for alex: to end the TRIP at hotel",
        "  second: second is a must for alex: to end the TRIP at cottage",
    ]

    same = stays_put(wants=[first, ends_at("hotel", "alex", id="second")])
    assert checked(same).answer is Answer.FEASIBLE


def test_each_holder_ends_at_the_place_their_own_want_names() -> None:
    wants = [ends_at("cottage", "alex", id="for-alex"), ends_at("hotel", "sam", id="for-sam")]
    file = load(day_out(starts_from("sam", "hotel"), wants=wants, persons=["alex", "sam"]))
    worst = worst_case(file)
    together = (walk(), walk("sam"), visit("alex", "sam"))
    assert broken(file, worst, (*together, train(), walk("sam", back=True))) == []
    assert broken(file, worst, (*together, train(), train("sam"))) == [
        elsewhere("sam", want="for-sam")
    ]
    assert broken(file, worst, together) == [
        elsewhere("alex", want="for-alex"),
        elsewhere("sam", want="for-sam"),
    ]
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert set(found.itinerary) == {*together, train(), walk("sam", back=True)}

    both = [ends_at("cottage", "alex", "sam")]
    file = load(day_out(starts_from("sam", "hotel"), wants=both, persons=["alex", "sam"]))
    assert broken(file, worst_case(file), together) == [elsewhere("alex", "sam")]


def test_a_path_of_ways_alone_can_end_where_it_has_to() -> None:
    facts = [starts_from("alex", "hotel"), takes("walk", "PT15M"), takes("train", "PT1H")]
    places = ["hotel", "museum", "cottage"]
    wants = [ends_at("cottage", "alex")]
    file = trip(["alex"], places, [], facts, [trip_starts(12)], ways=[WALK, TRAIN], wants=wants)
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert found.itinerary == (
        Step(None, "hotel", "museum", ("alex",), seconds(12), seconds(12, 15), "walk"),
        Step(None, "museum", "cottage", ("alex",), seconds(12, 15), seconds(13, 15), "train"),
    )
    assert found.relies_on == ("alex-start", "walk-length", "train-length", "ending", "trip-start")


def test_a_movement_that_takes_no_time_can_end_the_path_as_the_trip_ends() -> None:
    document = day_out(takes("train", "PT0S"), without=["train-length"], decisions=[trip_ends(15)])
    found = checked(load(document))
    assert found.answer is Answer.FEASIBLE
    assert found.itinerary == (walk(), visit(), train(end=seconds(15)))


# ------------------------------- The three answers -------------------------------


def test_a_person_travels_from_where_they_start_to_where_they_have_to_end() -> None:
    """The walk is as late as the visit allows, and the train is as early as it can be."""
    found = checked(load(day_out()))
    assert found.answer is Answer.FEASIBLE
    assert found.itinerary == (walk(), visit(), train())
    assert found.relies_on == (
        "alex-start",
        "visit-time",
        "visit-length",
        "visit-cutoff",
        "walk-length",
        "train-length",
        "ending",
        "lock-visit",
    )
    assert found.robust is True


def test_a_person_with_no_place_to_end_at_stops_after_their_last_option() -> None:
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
    document = day_out(starts_from("sam", "cottage"))
    document["persons"] = named("alex", "sam")
    found = checked(load(document))
    assert found.itinerary == (walk(), visit(), train())
    assert "alex-start" in found.relies_on
    assert "sam-start" not in found.relies_on


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


def test_other_ways_might_get_a_person_there_in_time() -> None:
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


def test_a_must_to_end_at_a_place_can_make_a_trip_infeasible() -> None:
    file = too_late(complete(None, "cottage"))
    found = checked(file)
    assert found.answer is Answer.INFEASIBLE
    assert found.conflict == (
        "visit-time",
        "visit-length",
        "train-length",
        "ways-to-cottage",
        "ending",
        "lock-visit",
        "trip-end",
    )
    assert has_no_record_to_spare(file, found.conflict)


def span(id: str, earliest: str, latest: str) -> Document:
    """A FACT that the FILE lists every way straight to the cottage that leaves in this span."""
    leaving = {"earliest": earliest, "latest": latest}
    return {"id": id, "complete": {"to": "cottage", "leaving": leaving}}


def test_every_time_a_person_could_still_leave_has_to_be_ruled_out() -> None:
    """Two spans that meet at 3:10 pm rule out every way to the cottage. Either alone does not."""
    early = span("early", at(0), at(15, 10))
    late = span("late", at(15, 10), at(15, 30))
    found = checked(too_late(early, late))
    assert found.answer is Answer.INFEASIBLE
    assert {"early", "late", "ending", "trip-end"} <= set(found.conflict)

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


def test_another_option_never_meets_the_must_to_end_at_a_place() -> None:
    """Alex cannot leave the hotel. Another OPTION might give Alex a view, but not a way out."""
    facts = [starts_from("alex", "hotel"), complete("hotel", None)]
    wants = [ends_at("cottage", "alex"), must("a-view", "alex")]
    places = ["hotel", "cottage"]
    file = trip(["alex"], places, [], facts, [trip_starts(0), trip_ends(23)], wants=wants)
    assert best_case(file).another_option == {("a-view", "alex")}
    found = checked(file)
    assert found.answer is Answer.INFEASIBLE
    assert found.conflict == ("alex-start", "ways-from-hotel", "ending", "trip-start", "trip-end")


def test_the_way_listed_first_decides_though_its_route_takes_more_ways() -> None:
    """Alex goes from a to c and on to e, and has two hours for both stretches.

    Each stretch has a slow direct WAY and a quick route of two WAYs. Both slow WAYs together
    take too long, so one stretch goes by two WAYs. The plan shown takes the WAY listed first:
    by b on the first stretch.
    """
    ways = [
        way("a-b", "a", "b"),
        way("b-c", "b", "c"),
        way("c-d", "c", "d"),
        way("d-e", "d", "e"),
        way("a-c", "a", "c"),
        way("c-e", "c", "e"),
    ]
    facts = [starts_from("alex", "a"), any_time("stop"), lasts("stop", "PT0S")]
    facts += [cutoff("stop", "PT0S")]
    facts += [takes(each["id"], "PT20M") for each in ways[:4]]
    facts += [takes("a-c", "PT70M"), takes("c-e", "PT70M")]
    limits = [trip_starts(9), trip_ends(11), lock("stop", "alex")]
    places = ["a", "b", "c", "d", "e"]
    wants = [ends_at("e", "alex")]
    file = trip(["alex"], places, [stays("stop", "c")], facts, limits, ways=ways, wants=wants)
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert [step.option or step.way for step in found.itinerary] == ["a-b", "b-c", "stop", "c-e"]


# ------------------------------- A last step with no known end -------------------------------


def test_a_last_ride_of_unknown_length_gets_a_person_there_where_the_trip_has_no_end() -> None:
    """Whatever the train takes, it ends, and then Alex is at the cottage. Nothing follows it."""
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


def test_a_locked_ride_of_unknown_length_gets_a_person_there() -> None:
    places = ["museum", "cottage"]
    wants = [ends_at("cottage", "alex")]
    ride = [moves("ride", "museum", "cottage")]
    leaves_at_five = [starts_at("ride", 17)]
    file = trip(["alex"], places, ride, leaves_at_five, [lock("ride", "alex")], wants=wants)
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert found.itinerary == (Step("ride", "museum", "cottage", ("alex",), seconds(17), None),)

    ends = [lock("ride", "alex"), trip_ends(18)]
    found = checked(trip(["alex"], places, ride, leaves_at_five, ends, wants=wants))
    assert found.missing == ((Missing(Unknown("duration", "ride"), 3600),),)


def test_a_stay_of_unknown_length_keeps_a_person_where_they_have_to_end() -> None:
    wants = [ends_at("cottage", "alex")]
    supper = [stays("supper", "cottage")]
    at_seven = [starts_at("supper", 19)]
    file = trip(["alex"], ["cottage"], supper, at_seven, [lock("supper", "alex")], wants=wants)
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert found.itinerary == (Step("supper", "cottage", "cottage", ("alex",), seconds(19), None),)


# ------------------------------- Large trips -------------------------------


def test_very_many_persons_can_take_one_way() -> None:
    """One step for each PERSON, and more PERSONs than Python allows calls inside calls."""

    def by_bus(count: int) -> File:
        people = [f"p{number}" for number in range(count)]
        facts = [takes("bus", "PT1S"), *(starts_from(person, "hotel") for person in people)]
        bus = [way("bus", "hotel", "cottage")]
        wants = [ends_at("cottage", *people)]
        return trip(people, ["hotel", "cottage"], [], facts, [], ways=bus, wants=wants)

    found = answers.check(by_bus(1100))
    assert found.answer is Answer.FEASIBLE
    assert len(found.itinerary) == 1100
    assert len(checked(by_bus(150)).itinerary) == 150


def test_a_large_group_with_two_ways_to_choose_from_is_planned_at_once() -> None:
    """63 PERSONs and two WAYs give more choices of WAYs than a list can hold.

    The first choice works, and the search makes no other one.
    """
    people = [f"p{number}" for number in range(63)]
    facts = [takes("bus", "PT1S"), takes("tram", "PT1S")]
    facts += [starts_from(person, "hotel") for person in people]
    ways = [way("bus", "hotel", "cottage"), way("tram", "hotel", "cottage")]
    wants = [ends_at("cottage", *people)]
    file = trip(people, ["hotel", "cottage"], [], facts, [], ways=ways, wants=wants)
    found = checked(file)
    assert found.answer is Answer.FEASIBLE
    assert [step.way for step in found.itinerary] == ["bus"] * 63


def test_no_routes_are_looked_for_from_an_option_that_cannot_happen() -> None:
    """Sam has to end the TRIP on an island that no WAY reaches, and nobody says where Sam starts.

    Eleven towns are joined to each other, and a visit in one of them has no stated start, so
    it cannot happen. The plan with nothing in it works. Looking for a route from the visit to
    the island would go through every row of towns for nothing.
    """
    towns = [f"t{number}" for number in range(11)]
    ways = [
        way_between(f"{one}-{other}", one, other)
        for at, one in enumerate(towns)
        for other in towns[at + 1 :]
    ]
    visit_in_town = [stays("visit", "t0")]
    facts = [lasts("visit", "PT1S"), *(takes(each["id"], "PT1M") for each in ways)]
    wants = [ends_at("island", "sam")]
    places = ["island", *towns]
    file = trip(["sam"], places, visit_in_town, facts, [], ways=ways, wants=wants)
    begun = perf_counter()
    found = checked(file)
    assert (found.answer, found.itinerary, found.robust) == (Answer.FEASIBLE, (), True)
    assert perf_counter() - begun < 20


def test_a_path_can_go_through_very_many_places() -> None:
    """A route of 1,099 WAYs, one after another."""
    places = [f"p{number}" for number in range(1100)]
    ways = [way(f"w{number}", f"p{number}", f"p{number + 1}") for number in range(1099)]
    facts = [starts_from("sam", "p0"), *(takes(each["id"], "PT1S") for each in ways)]
    file = trip(["sam"], places, [], facts, [], ways=ways, wants=[ends_at("p1099", "sam")])
    found = answers.check(file)
    assert found.answer is Answer.FEASIBLE
    assert [step.way for step in found.itinerary] == [each["id"] for each in ways]


# ------------------------------- Random trips -------------------------------


def a_way_there(rng: Random) -> File:
    """Alex, three PLACES, at most one OPTION, and one or two WAYs, all on a quarter-hour grid.

    The OPTION starts at 9:00 am or at 9:15 am. Alex usually starts from a stated PLACE and
    has to end the TRIP at one. The TRIP usually ends between 9:15 am and 10:00 am. A COMPLETE
    FACT often rules out unlisted WAYs to one PLACE, or to every PLACE, from some quarter hour
    until after the latest time the TRIP can end. Its span starts one second after a grid time
    and ends one second before another, so the times just outside it are on the grid.
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
    if rng.random() < 0.8:
        earliest = seconds(8, 30) + QUARTER * rng.randrange(4) + 1
        leaving = {"earliest": at_second(earliest), "latest": at_second(seconds(10, 15) - 1)}
        whole: Document = {"leaving": leaving}
        if rng.random() < 0.3:
            whole["to"] = rng.choice(PLACES)
        facts.append({"id": "ways", "complete": whole})
    wants = [ends_at(rng.choice(PLACES), "alex")] if rng.random() < 0.9 else []
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
        taken = (*before, *after)
        for times in combinations_with_replacement(grid, len(taken)):
            steps = [
                Step(None, origin, destination, ("alex",), moment, None, id)
                for (id, origin, destination), moment in zip(taken, times, strict=True)
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


def test_the_search_finds_a_path_whenever_trying_every_path_does() -> None:
    """Both ends of the answer: something works in the worst case, and in the best case."""
    rng = Random(1919)
    seen: set[Answer] = set()
    for _ in range(40):
        file = a_way_there(rng)
        found = checked(file)
        seen.add(found.answer)
        assert (found.answer is Answer.FEASIBLE) == any_path_works(file, worst_case(file))
        assert (found.answer is not Answer.INFEASIBLE) == any_path_works(file, best_case(file))
    assert seen == set(Answer)


def test_the_two_checkers_agree_on_random_trips_with_starts_and_ends() -> None:
    rng = Random(2020)
    trips = [a_way_there(rng) for _ in range(150)]
    trips += [
        random_trip(rng, 0.2, contingent=0.3, with_complete=0.4, with_ways=0.9, with_ends=0.6)
        for _ in range(100)
    ]
    trips += [
        random_trip(rng, 0, ["alex", "sam"], count=2, with_ways=0.9, with_ends=0.6, with_times=0.5)
        for _ in range(60)
    ]
    seen: set[Answer] = set()
    names_a_want = at_an_end = 0
    for file in trips:
        found = checked(file)
        seen.add(found.answer)
        asking = {want.id for want in file.wants if want.ends_at is not None}
        names_a_want += bool(asking & set(found.conflict))
        if found.answer is Answer.FEASIBLE:
            worst = worst_case(file)
            assert broken(file, worst, found.itinerary) == []
            assert needless(file, worst, found.itinerary) == []
        if found.itinerary:
            last = found.itinerary[-1]
            at_an_end += found.itinerary[0].option is None or last.option is None
    assert seen == set(Answer)
    assert names_a_want >= 25
    assert at_an_end >= 20


def test_a_conflict_about_where_a_path_ends_has_no_record_to_spare() -> None:
    rng = Random(2121)
    conflicts = 0
    while conflicts < 25:
        file = a_way_there(rng)
        found = answers.check(file)
        if "ending" not in found.conflict:
            continue
        conflicts += 1
        assert has_no_record_to_spare(file, found.conflict)


def test_the_best_and_worst_cases_settle_the_answer_with_starts_and_ends() -> None:
    """What works in the worst case works in every possible world, and so on, as before.

    Where a PERSON starts from and where they have to end are the same in every possible world:
    nothing about them is unknown. Each set of unknown FACTs a report names is enough, and no
    part of it is.
    """
    rng = Random(2222)
    seen: set[Answer] = set()
    by_chance_with_an_end = 0
    for number in range(160):
        if number % 2:
            file = a_way_there(rng)
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
                assert works_as_listed(file, world, in_world(world, choice))
            by_chance = [any_choice(rng, file, world) for _ in range(12)]
            by_chance = [
                each for each in by_chance if not broken(file, world, in_world(world, each))
            ]
            asks = any(want.ends_at is not None for want in file.wants)
            by_chance_with_an_end += bool(by_chance) and asks
            if by_chance:
                assert itineraries(file, world)
            for choice in (*itineraries(file, world), *by_chance):
                assert broken(file, best, in_world(best, choice)) == []
            if found.answer is Answer.INFEASIBLE:
                assert not by_chance
                assert not itineraries(file, world)
    assert seen == set(Answer)
    assert by_chance_with_an_end > 40
