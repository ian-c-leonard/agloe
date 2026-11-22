"""The routes between two PLACEs: which are worth trying, and what the search skips."""

from collections.abc import Sequence
from itertools import pairwise, product
from random import Random
from typing import Any

import pytest

from agloe import answers, compiler, reference
from agloe.answers import Answer
from agloe.file import File
from agloe.reference import (
    Itinerary,
    Remaining,
    Routes,
    World,
    best_case,
    best_cases,
    itineraries,
    longest_case,
    routes,
    worst_case,
)
from tests.stories import (
    Document,
    complete,
    cutoff,
    ends_at,
    lasts,
    lock,
    moves,
    starts_at,
    starts_from,
    stays,
    takes,
    takes_between,
    trip,
    trip_ends,
    trip_starts,
    way,
    way_between,
)
from tests.test_cross_check import random_trip
from tests.test_where_a_path_ends import checked, has_no_record_to_spare


def a_visit_then_a_show(
    ways: list[Document], facts: list[Document], show_at: tuple[int, int] = (11, 0)
) -> File:
    """Sam visits a museum from 9:00 to 10:00 am, then has a show at a hall somewhere else."""
    options = [stays("visit", "museum"), stays("show", "hall")]
    timed = [starts_at("visit", 9), lasts("visit", "PT1H"), cutoff("visit", "PT0S")]
    timed += [starts_at("show", *show_at), lasts("show", "PT1H"), cutoff("show", "PT0S")]
    locked = [lock("visit", "sam"), lock("show", "sam")]
    return trip(["sam"], ["museum", "hall"], options, [*timed, *facts], locked, ways=ways)


def names(found: list[tuple[tuple[str | None, str, str], ...]]) -> list[list[str | None]]:
    return [[leg for leg, _, _ in route] for route in found]


# ------------------------------- A WAY that is never the better one ----------------------------


def test_a_way_is_left_out_where_an_earlier_way_takes_no_longer() -> None:
    """Five WAYs from the museum to the hall. The first takes ten minutes."""
    ways = [way(name, "museum", "hall") for name in ("first", "same", "quicker", "range", "open")]
    facts = [takes("first", "PT10M"), takes("same", "PT10M"), takes("quicker", "PT5M")]
    facts.append(takes_between("range", "PT5M", "PT20M"))
    file = a_visit_then_a_show(ways, facts)
    worst = worst_case(file)
    # A WAY as slow as the first is left out. So is one that an earlier WAY takes no longer
    # than, both when they run shortest and when they run longest. A WAY with no known length
    # can only come last.
    assert names(routes(file, worst, "museum", "hall")) == [["first"], ["quicker"]]
    assert names(routes(file, worst, "museum", "hall", last=True)) == [
        ["first"],
        ["quicker"],
        ["open"],
    ]
    every = routes(file, worst, "museum", "hall", thin=False)
    assert names(every) == [["first"], ["same"], ["quicker"], ["range"]]


def test_a_way_that_is_quicker_only_some_of_the_time_stays() -> None:
    """The second WAY can be quicker than the first, and it can be slower."""
    ways = [way("steady", "museum", "hall"), way("uneven", "museum", "hall")]
    facts = [takes("steady", "PT10M"), takes_between("uneven", "PT5M", "PT20M")]
    file = a_visit_then_a_show(ways, facts)
    assert names(routes(file, worst_case(file), "museum", "hall")) == [["steady"], ["uneven"]]


def test_a_way_both_ways_is_compared_in_the_direction_it_is_taken() -> None:
    ways = [way_between("path", "museum", "hall"), way("shuttle", "hall", "museum")]
    facts = [takes("path", "PT10M"), takes("shuttle", "PT10M")]
    file = a_visit_then_a_show(ways, facts)
    worst = worst_case(file)
    assert names(routes(file, worst, "museum", "hall")) == [["path"]]
    assert names(routes(file, worst, "hall", "museum")) == [["path"]]
    assert names(routes(file, worst, "hall", "museum", thin=False)) == [["path"], ["shuttle"]]


def test_the_plan_takes_the_way_listed_first_of_two_that_are_alike() -> None:
    ways = [way("first", "museum", "hall"), way("second", "museum", "hall")]
    file = a_visit_then_a_show(ways, [takes("first", "PT10M"), takes("second", "PT10M")])
    found = checked(file)
    assert [step.way for step in found.itinerary if step.way] == ["first"]
    assert "second-length" not in found.relies_on


def test_a_conflict_still_holds_the_way_that_was_left_out() -> None:
    """Both WAYs take thirty minutes, and the show starts fifteen minutes after the visit."""
    ways = [way("first", "museum", "hall"), way("second", "museum", "hall")]
    facts = [takes("first", "PT30M"), takes("second", "PT30M"), complete("museum", "hall")]
    file = a_visit_then_a_show(ways, facts, show_at=(10, 15))
    found = checked(file)
    assert found.answer is Answer.INFEASIBLE
    # Without the length of either WAY, that WAY might be quick enough.
    assert {"first-length", "second-length"} <= set(found.conflict)
    assert has_no_record_to_spare(file, found.conflict)


# ------------------------------- Against the search that skips nothing -------------------------


def with_parallel_ways(rng: Random) -> File:
    """Sam does two or three things at three PLACEs, with several WAYs between each two."""
    places = ["a", "b", "c"]
    spots = [rng.choice(places) for _ in range(rng.choice([2, 3]))]
    options = [stays(f"stop-{number}", place) for number, place in enumerate(spots)]
    facts: list[Document] = []
    for number, option in enumerate(options):
        facts += [starts_at(option["id"], 9 + number, rng.choice([0, 15, 30]))]
        facts += [lasts(option["id"], "PT30M"), cutoff(option["id"], rng.choice(["PT0S", "PT5M"]))]
    ways: list[Document] = []
    lengths = ["PT5M", "PT10M", "PT10M", "PT20M", "PT40M"]
    for count in range(rng.randrange(2, 8)):
        origin, destination = rng.sample(places, 2)
        name = f"way-{count}"
        ways.append(rng.choice([way, way_between])(name, origin, destination))
        kind = rng.random()
        if kind < 0.6:
            facts.append(takes(name, rng.choice(lengths)))
        elif kind < 0.85:
            shortest, longest = sorted(rng.sample(lengths, 2), key=lengths.index)
            facts.append(takes_between(name, shortest, longest))
    if rng.random() < 0.5:
        facts.append(starts_from("sam", rng.choice(places)))
    if rng.random() < 0.5:
        facts.append(complete(None, None))
    locked = [lock(option["id"], "sam") for option in options if rng.random() < 0.9]
    return trip(["sam"], places, options, facts, locked, ways=ways)


def with_every_route_shown(file: File, world: World) -> Itinerary | None:
    found = itineraries(file, world, Routes(file, world, thin=False))
    return found[0] if found else None


def with_every_route_works(file: File, world: World) -> bool:
    return bool(itineraries(file, world, Routes(file, world, thin=False)))


def with_every_route_can_work(remaining: Remaining) -> bool:
    return any(with_every_route_works(remaining.file, world) for world in best_cases(remaining))


def test_leaving_those_ways_out_changes_no_report() -> None:
    """The reference checker with every route, the reference checker as it is, and the solver."""
    rng = Random(5656)
    seen: set[Answer] = set()
    thinned = 0
    for _ in range(300):
        file = with_parallel_ways(rng)
        found = answers.check(file)
        every_route = (with_every_route_shown, with_every_route_works, with_every_route_can_work)
        assert found == answers.check(file, *every_route)
        assert found == compiler.check(file)
        seen.add(found.answer)
        worst = worst_case(file)
        pairs = [(here, there) for here in "abc" for there in "abc" if here != there]
        thinned += any(
            len(routes(file, worst, here, there))
            < len(routes(file, worst, here, there, thin=False))
            for here, there in pairs
        )
    assert seen == set(Answer)
    assert thinned > 100


type Route = tuple[tuple[str | None, str, str], ...]


def never_slower(world: World, one: str, stretch: Route) -> bool:
    """Whether one listed WAY takes no longer than these WAYs together, shortest and longest."""
    shortest, longest = world.takes[one]
    least = most = 0
    for each, _, _ in stretch:
        low, high = (world.unlisted_takes,) * 2 if each is None else world.takes[each]
        if high is None:
            return False
        least, most = least + low, most + high
    return longest is not None and shortest <= least and longest <= most


def one_before_it_that_is_never_worse(
    file: File, world: World, route: Route, every: list[Route]
) -> Route | None:
    """A route that is tried before this one and is never worse, of those in ``every``.

    It has the same legs, but for one WAY that is listed earlier, joins the same two PLACEs
    and is never slower. Or one listed WAY stands in for a stretch of two or more of its
    WAYs, and is never slower than the stretch.
    """
    order = [each.id for each in file.ways]
    for other in every[: every.index(route)]:
        if len(other) == len(route):
            differ = [at for at in range(len(route)) if route[at] != other[at]]
            if len(differ) != 1 or route[differ[0]][1:] != other[differ[0]][1:]:
                continue
            mine, theirs = route[differ[0]][0], other[differ[0]][0]
            earlier = mine is not None and theirs is not None
            earlier = earlier and order.index(theirs or "") < order.index(mine or "")
            if earlier and never_slower(world, theirs or "", (route[differ[0]],)):
                return other
            continue
        for first in range(len(route)):
            for last in range(first + 1, len(route)):
                rest = (*route[:first], *route[last + 1 :])
                if len(other) != len(rest) + 1 or (*other[:first], *other[first + 1 :]) != rest:
                    continue
                one, origin, destination = other[first]
                straight = (origin, destination) == (route[first][1], route[last][2])
                if one and straight and never_slower(world, one, route[first : last + 1]):
                    return other
    return None


def test_each_route_left_out_has_one_that_is_never_worse() -> None:
    """A route that is left out has one that is tried before it and is never worse: with an
    earlier WAY that is never slower, or with one listed WAY in place of a stretch of
    several. Going from one such route to the next ends at a route that is kept."""
    rng = Random(5757)
    left_out = shorter = 0
    for _ in range(300):
        file = with_parallel_ways(rng)
        worst = worst_case(file)
        for here in "abc":
            for there in "abc":
                if here == there:
                    continue
                kept = routes(file, worst, here, there)
                every = routes(file, worst, here, there, thin=False)
                assert [route for route in every if route in kept] == kept
                for route in every:
                    if route in kept:
                        continue
                    left_out += 1
                    better: Route | None = route
                    while better is not None and better not in kept:
                        better = one_before_it_that_is_never_worse(file, worst, better, every)
                    assert better is not None
                    shorter += len(better) < len(route)
    assert left_out > 200
    assert shorter > 50


def a_city_to_walk(places: int) -> File:
    """So many PLACEs with a walk of five minutes between every two of them. Sam starts at
    the first and is LOCKed into an appointment at the last."""
    names_of = [f"place-{number}" for number in range(places)]
    walks = [
        way_between(f"walk-{a}-{b}", names_of[a], names_of[b])
        for a in range(places)
        for b in range(a + 1, places)
    ]
    facts = [takes(each["id"], "PT5M") for each in walks]
    facts += [starts_at("appointment", 10), lasts("appointment", "PT30M")]
    facts += [cutoff("appointment", "PT0S"), starts_from("sam", names_of[0])]
    options = [stays("appointment", names_of[-1])]
    return trip(["sam"], names_of, options, facts, [lock("appointment", "sam")], ways=walks)


def test_a_walk_between_every_two_places_leaves_one_route() -> None:
    """Ten PLACEs with a walk between every two. From one to another, 109,601 chains of
    walks pass through the others. The walk straight there is as quick as any stretch of
    them, so it is the one route that is tried. With thirty PLACEs it still is."""
    file = a_city_to_walk(10)
    assert names(routes(file, worst_case(file), "place-0", "place-9")) == [["walk-0-9"]]
    found = compiler.check(file)
    assert found.answer is Answer.FEASIBLE
    assert [step.way for step in found.itinerary if step.option is None] == ["walk-0-9"]
    wide = a_city_to_walk(30)
    assert names(routes(wide, worst_case(wide), "place-0", "place-29")) == [["walk-0-29"]]


def test_a_longer_chain_is_kept_where_it_is_quicker_than_the_way_straight_there() -> None:
    """The walk straight from the hotel to the hall takes an hour. The metro to the square
    and the tram on take twenty minutes together, so that chain is kept and tried second.
    With the walk at twenty minutes it is as quick, and the chain is left out. A walk that
    can take up to an hour is as quick only at its shortest, so the chain is kept."""

    def city(*walk: Document) -> File:
        ways = [way("walk", "hotel", "hall"), way("metro", "hotel", "square")]
        ways.append(way("tram", "square", "hall"))
        facts = [*walk, takes("metro", "PT10M"), takes("tram", "PT10M")]
        facts += [starts_at("show", 10), lasts("show", "PT1H"), cutoff("show", "PT0S")]
        facts.append(starts_from("sam", "hotel"))
        places = ["hotel", "square", "hall"]
        options = [stays("show", "hall")]
        return trip(["sam"], places, options, facts, [lock("show", "sam")], ways=ways)

    def found(file: File) -> list[list[str | None]]:
        return names(routes(file, worst_case(file), "hotel", "hall"))

    assert found(city(takes("walk", "PT1H"))) == [["walk"], ["metro", "tram"]]
    assert found(city(takes("walk", "PT20M"))) == [["walk"]]
    assert found(city(takes_between("walk", "PT20M", "PT1H"))) == [["walk"], ["metro", "tram"]]


# ------------------------------- What the search does not walk through -------------------------


def a_chain(legs: int, branch: int = 0, places: int = 0) -> File:
    """A chain of PLACEs with two WAYs alike for each leg, and a visit at each end.

    ``branch`` adds a second chain of that many legs from the start that leads nowhere, and
    ``places`` adds that many PLACEs that no WAY reaches.
    """
    stops = [f"p{number}" for number in range(legs + 1)]
    ways = [way(f"w{n}-{k}", f"p{n}", f"p{n + 1}") for n in range(legs) for k in range(2)]
    side = ["p0", *(f"d{number}" for number in range(branch))]
    ways += [way(f"x{n}-{k}", side[n], side[n + 1]) for n in range(branch) for k in range(2)]
    apart = [f"q{number}" for number in range(places)]
    options = [stays("first", "p0"), stays("last", f"p{legs}")]
    facts = [starts_at("first", 9), lasts("first", "PT1H"), cutoff("first", "PT0S")]
    facts += [starts_at("last", 20), lasts("last", "PT1H"), cutoff("last", "PT0S")]
    facts += [takes(each["id"], "PT1M") for each in ways]
    locked = [lock("first", "sam"), lock("last", "sam")]
    return trip(["sam"], [*stops, *side[1:], *apart], options, facts, locked, ways=ways)


def test_sixty_three_legs_of_two_ways_alike_are_one_route() -> None:
    file = a_chain(63)
    found = routes(file, worst_case(file), "p0", "p63")
    assert names(found) == [[f"w{number}-0" for number in range(63)]]
    report = checked(file)
    assert report.answer is Answer.FEASIBLE
    assert len([step for step in report.itinerary if step.way]) == 63


def test_a_chain_that_leads_nowhere_is_not_walked() -> None:
    """One leg leads to the last visit. Sixty-three legs beside it lead nowhere."""
    file = a_chain(1, branch=63)
    worst = worst_case(file)
    assert names(routes(file, worst, "p0", "p1")) == [["w0-0"]]
    assert len(routes(file, worst, "p0", "p1", thin=False)) == 2
    assert checked(file).answer is Answer.FEASIBLE


def test_places_that_no_way_reaches_cost_the_search_nothing() -> None:
    """Four thousand PLACEs beside the two that matter: sixteen million pairs of PLACEs."""
    file = a_chain(1, places=4000)
    assert names(routes(file, worst_case(file), "p0", "p1")) == [["w0-0"]]


def test_ways_back_to_a_place_already_passed_are_not_compared() -> None:
    """Two thousand WAYs lead back to the start, each quicker than the one before."""
    ways = [way("direct", "a", "c"), way("out", "a", "b"), way("on", "b", "c")]
    back = [way(f"back-{number}", "b", "a") for number in range(2000)]
    facts = [takes("direct", "PT1H"), takes("out", "PT10M"), takes("on", "PT10M")]
    facts += [takes(each["id"], f"PT{3000 - number}S") for number, each in enumerate(back)]
    options = [stays("first", "a"), stays("last", "c")]
    timed = [starts_at("first", 9), lasts("first", "PT1H"), cutoff("first", "PT0S")]
    timed += [starts_at("last", 20), lasts("last", "PT1H"), cutoff("last", "PT0S")]
    locked = [lock("first", "sam"), lock("last", "sam")]
    file = trip(["sam"], ["a", "b", "c"], options, [*timed, *facts], locked, ways=[*ways, *back])
    assert names(routes(file, worst_case(file), "a", "c")) == [["direct"], ["out", "on"]]


def test_a_way_that_no_route_can_take_leads_nowhere() -> None:
    """A chain of sixty-three legs ends in a WAY to the hall that nobody knows the length of."""
    chain = ["museum", *(f"d{number}" for number in range(63))]
    ways = [way("direct", "museum", "hall")]
    ways += [way(f"x{n}-{k}", chain[n], chain[n + 1]) for n in range(63) for k in range(2)]
    ways.append(way("exit", "d62", "hall"))
    facts = [takes("direct", "PT10M")]
    # The second WAY of each leg is the quicker one, so neither is left out.
    facts += [takes(f"x{n}-{k}", f"PT{2 - k}S") for n in range(63) for k in range(2)]
    options = [stays("visit", "museum"), stays("show", "hall")]
    timed = [starts_at("visit", 9), lasts("visit", "PT1H"), cutoff("visit", "PT0S")]
    timed += [starts_at("show", 11), lasts("show", "PT1H"), cutoff("show", "PT0S")]
    locked = [lock("visit", "sam"), lock("show", "sam")]
    places = [*chain, "hall"]
    file = trip(["sam"], places, options, [*timed, *facts], locked, ways=ways)
    assert names(routes(file, worst_case(file), "museum", "hall")) == [["direct"]]


# ------------------------------- Routes that do not fit between two fixed times ----------------


def a_group_for_a_train(count: int, minutes: Sequence[int]) -> File:
    """A group has breakfast until 08:30 and is LOCKed onto the train at 09:00.

    Each transfer from the hotel to the station is a WAY, in the order given.
    """
    people = [f"person-{number}" for number in range(count)]
    options = [stays("breakfast", "hotel"), moves("train", "station", "city")]
    facts = [starts_at("breakfast", 8), lasts("breakfast", "PT30M")]
    facts += [starts_at("train", 9), lasts("train", "PT1H"), cutoff("train", "PT0S")]
    ways = [way(f"transfer-{number}", "hotel", "station") for number in range(len(minutes))]
    facts += [takes(each["id"], f"PT{length}M") for each, length in zip(ways, minutes, strict=True)]
    locks = [lock("breakfast", *people), lock("train", *people)]
    return trip(people, ["hotel", "station", "city"], options, facts, locks, ways=ways)


def test_a_transfer_too_slow_for_the_train_is_tried_for_nobody(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Eight travelers, and only the last of five transfers takes them there in half an hour.

    Each of the other four is too slow whoever takes it. So the search does not try them for
    one traveler after another: that would be five to the power of eight choices.
    """
    file = a_group_for_a_train(8, [36, 35, 34, 33, 20])
    tried = 0
    timings = reference._timings  # pyright: ignore[reportPrivateUsage]

    def counted(*given: Any, **named: Any) -> Any:
        nonlocal tried
        tried += 1
        return timings(*given, **named)

    monkeypatch.setattr(reference, "_timings", counted)
    found = compiler.check(file)
    assert found.answer is Answer.FEASIBLE
    assert {step.way for step in found.itinerary if step.way} == {"transfer-4"}
    assert tried < 20
    small = a_group_for_a_train(2, [36, 20])
    assert compiler.check(small) == answers.check(small)


def fits(world: World, before: reference.Terms, after: reference.Terms, route: Any) -> bool:
    """Whether the search keeps this route between two OPTIONs."""
    leaves = reference._over(before)  # pyright: ignore[reportPrivateUsage]
    there_by = reference._open_until(after)  # pyright: ignore[reportPrivateUsage]
    takes = reference._length(world, route)  # pyright: ignore[reportPrivateUsage]
    return reference._in_time(leaves, there_by, takes)  # pyright: ignore[reportPrivateUsage]


def test_a_route_that_does_not_fit_is_in_no_plan() -> None:
    """Each route that is left out is refused by the timing too, whatever else is chosen.

    Sam starts wherever the first stop is, so that nothing else can refuse the plan.
    """
    rng = Random(7070)
    refused = 0
    for _ in range(600):
        file = with_parallel_ways(rng)
        if file.starts_from("sam") is not None:
            continue
        for world in (worst_case(file), best_case(file), longest_case(file)):
            known = Routes(file, world)
            count = len(file.options)
            who = tuple(("sam",) for _ in range(count))
            order = tuple(range(count))
            stops = [(option.origin, option.destination) for option in file.options]
            hops = [
                (spot, known.between(here, there))
                for spot, ((_, here), (there, _)) in enumerate(pairwise(stops))
                if here != there
            ]
            if not all(found for _, found in hops):
                continue
            for spot, found in hops:
                before = world.terms[file.options[spot].id]
                after = world.terms[file.options[spot + 1].id]
                for route in found:
                    if fits(world, before, after, route):
                        continue
                    for others in product(*(each for other, each in hops if other != spot)):
                        rest = iter(others)
                        by = {
                            (0, other): route if other == spot else next(rest) for other, _ in hops
                        }
                        assert reference.scheduled(file, world, who, (order,), by) is None
                        refused += 1
    assert refused > 100


def test_leaving_out_routes_that_do_not_fit_changes_no_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reference checker and the solver give the report of the search without this cut."""
    rng = Random(8080)
    files = [with_parallel_ways(rng) for _ in range(300)]
    found = [(answers.check(file), compiler.check(file)) for file in files]

    def every_route_fits(*_: object) -> bool:
        return True

    monkeypatch.setattr(reference, "_in_time", every_route_fits)
    seen: set[Answer] = set()
    for file, (slow, fast) in zip(files, found, strict=True):
        every_route = answers.check(file)
        assert slow == every_route
        assert fast == every_route
        seen.add(every_route.answer)
    assert seen == set(Answer)


# ------------------------------- Routes at the two ends of a path ------------------------------


def a_group_from_the_hotel(count: int, minutes: Sequence[int], back: bool = False) -> File:
    """A group starts at the hotel when the TRIP starts, at 08:30, for a visit at 09:00.

    Each transfer is a WAY, in the order given. With ``back``, the visit ends at 17:00, the
    TRIP ends at 17:30, the group has to end it at the hotel, and the WAYs lead back there.
    """
    people = [f"person-{number}" for number in range(count)]
    facts: list[Document] = [starts_at("visit", 16 if back else 9), lasts("visit", "PT1H")]
    facts.append(cutoff("visit", "PT0S"))
    ends = ("museum", "hotel") if back else ("hotel", "museum")
    ways = [way(f"transfer-{number}", *ends) for number in range(len(minutes))]
    facts += [takes(each["id"], f"PT{length}M") for each, length in zip(ways, minutes, strict=True)]
    decisions = [lock("visit", *people)]
    wants: list[Document] = []
    if back:
        decisions.append(trip_ends(17, 30))
        wants.append(ends_at("hotel", *people))
    else:
        decisions.append(trip_starts(8, 30))
        facts += [starts_from(person, "hotel") for person in people]
    options = [stays("visit", "museum")]
    return trip(people, ["hotel", "museum"], options, facts, decisions, ways=ways, wants=wants)


@pytest.mark.parametrize("back", [False, True])
def test_a_transfer_the_times_of_the_trip_leave_no_time_for_is_tried_for_nobody(
    monkeypatch: pytest.MonkeyPatch, back: bool
) -> None:
    """Eight travelers have half an hour at one end of the TRIP, and one transfer of five fits."""
    file = a_group_from_the_hotel(8, [36, 35, 34, 33, 30], back)
    tried = 0
    timings = reference._timings  # pyright: ignore[reportPrivateUsage]

    def counted(*given: Any, **named: Any) -> Any:
        nonlocal tried
        tried += 1
        return timings(*given, **named)

    monkeypatch.setattr(reference, "_timings", counted)
    found = compiler.check(file)
    assert found.answer is Answer.FEASIBLE
    assert {step.way for step in found.itinerary if step.way} == {"transfer-4"}
    assert tried < 20
    small = a_group_from_the_hotel(2, [31, 30], back)
    assert compiler.check(small) == answers.check(small)


def test_leaving_out_routes_with_no_time_at_the_ends_changes_no_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reference checker and the solver give the report of the search without these cuts."""
    rng = Random(8181)
    files = [
        random_trip(rng, 0.3, with_ways=0.9, with_ends=0.7, with_times=0.7) for _ in range(250)
    ]
    # How many routes each kind of end leaves out: to a first OPTION, after a last one, and
    # for a PERSON who takes part in none.
    cut = {"first": 0, "last": 0, "none": 0}
    at_an_end = Routes.at_an_end

    def counted(
        self: Routes, here: str, there: str, first: int | None, then: int | None
    ) -> list[reference.Route]:
        left = at_an_end(self, here, there, first, then)
        kind = "first" if then is not None else "last" if first is not None else "none"
        cut[kind] += len(self.between(here, there, then is None)) - len(left)
        return left

    monkeypatch.setattr(Routes, "at_an_end", counted)
    found = [(answers.check(file), compiler.check(file)) for file in files]
    assert all(count > 5 for count in cut.values()), cut

    def every_route_is_in_time(*_: object) -> bool:
        return True

    monkeypatch.setattr(reference, "_in_time", every_route_is_in_time)
    seen: set[Answer] = set()
    for file, (slow, fast) in zip(files, found, strict=True):
        every_route = answers.check(file)
        assert slow == every_route
        assert fast == every_route
        seen.add(every_route.answer)
    assert seen == set(Answer)
