"""The routes between two PLACEs: which are worth trying, and what the search skips."""

from random import Random

from agloe import answers, compiler
from agloe.answers import Answer
from agloe.file import File
from agloe.reference import Itinerary, Routes, World, itineraries, routes, worst_case
from tests.stories import (
    Document,
    complete,
    cutoff,
    lasts,
    lock,
    starts_at,
    starts_from,
    stays,
    takes,
    takes_between,
    trip,
    way,
    way_between,
)
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


def test_a_way_is_left_out_where_an_earlier_way_is_never_slower() -> None:
    """Five WAYs from the museum to the hall. The first takes ten minutes."""
    ways = [way(name, "museum", "hall") for name in ("first", "same", "quicker", "range", "open")]
    facts = [takes("first", "PT10M"), takes("same", "PT10M"), takes("quicker", "PT5M")]
    facts.append(takes_between("range", "PT5M", "PT20M"))
    file = a_visit_then_a_show(ways, facts)
    worst = worst_case(file)
    # A WAY as slow as the first is left out. So is one that an earlier WAY is quicker than at
    # its shortest and at its longest. A WAY with no known length can only come last.
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


def test_leaving_those_ways_out_changes_no_report() -> None:
    """The reference checker with every route, the reference checker as it is, and the solver."""
    rng = Random(5656)
    seen: set[Answer] = set()
    thinned = 0
    for _ in range(300):
        file = with_parallel_ways(rng)
        found = answers.check(file)
        assert found == answers.check(file, with_every_route_shown, with_every_route_works)
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


def test_each_route_left_out_has_one_that_is_never_worse() -> None:
    """Through the same PLACEs, with the same WAY or an earlier one that is never slower."""
    rng = Random(5757)
    left_out = 0
    for _ in range(300):
        file = with_parallel_ways(rng)
        worst = worst_case(file)
        order = [each.id for each in file.ways]
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
                    assert any(
                        len(other) == len(route)
                        and all(
                            (mine, origin, to) == (theirs, start, end)
                            or (
                                (origin, to) == (start, end)
                                and mine is not None
                                and theirs is not None
                                and order.index(theirs) < order.index(mine)
                                and worst.takes[theirs][0] <= worst.takes[mine][0]
                                and (worst.takes[theirs][1] or 0) <= (worst.takes[mine][1] or 0)
                            )
                            for (mine, origin, to), (theirs, start, end) in zip(
                                route, other, strict=True
                            )
                        )
                        for other in kept
                    )
    assert left_out > 200


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
