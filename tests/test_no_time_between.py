"""Two OPTIONs at fixed times with no time to get from one to the other: nobody takes both."""

from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from itertools import combinations
from random import Random

import pytest

from agloe import answers, compiler, reference
from agloe.answers import Answer
from agloe.file import Complete, File, Lock
from agloe.reference import NoTimeBetween, Remaining, World, best_case, longest_case, worst_case
from tests.stories import (
    Document,
    any_time,
    at,
    complete,
    cutoff,
    every,
    lasts,
    lasts_between,
    lock,
    moves,
    must,
    satisfies,
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
from tests.test_conflict import searched, solves_counted
from tests.test_cross_check import possible_world, random_trip, two_places_with_no_listed_way

PLACES = ["hotel", "museum", "dock", "pier"]


def a_day_of_stops(rng: Random) -> File:
    """Three or four stops at fixed times in four PLACEs, with WAYs of many lengths between them.

    Some stops are rides. Some WAYs can run long, and some have no stated length. Half the
    time a FACT says the FILE lists every way, for the whole day or for part of it, between
    all PLACEs or from one of them. Sam is LOCKed into some stops, and must have a view that
    one or two stops give. Sometimes a DECISION says when the TRIP starts, or when it ends.
    """
    options: list[Document] = []
    facts: list[Document] = []
    for number in range(rng.choice([3, 4])):
        id = f"stop-{number}"
        here = rng.choice(PLACES)
        if rng.random() < 0.25:
            options.append(
                moves(id, here, rng.choice([place for place in PLACES if place != here]))
            )
        else:
            options.append(stays(id, here))
        if rng.random() < 0.9:
            facts.append(starts_at(id, 9 + rng.randrange(4), rng.choice([0, 15, 30, 45])))
        kind = rng.random()
        if kind < 0.7:
            facts.append(lasts(id, rng.choice(["PT0S", "PT15M", "PT30M", "PT1H"])))
        elif kind < 0.85:
            facts.append(lasts_between(id, "PT15M", "PT45M"))
        if rng.random() < 0.8:
            facts.append(cutoff(id, rng.choice(["PT0S", "PT0S", "PT10M", "PT15M"])))
    ways: list[Document] = []
    lengths = ["PT0S", "PT5M", "PT10M", "PT20M", "PT40M"]
    for number in range(rng.randrange(1, 7)):
        origin, destination = rng.sample(PLACES, 2)
        id = f"way-{number}"
        ways.append(rng.choice([way, way_between])(id, origin, destination))
        kind = rng.random()
        if kind < 0.65:
            facts.append(takes(id, rng.choice(lengths)))
        elif kind < 0.85:
            shortest, longest = sorted(rng.sample(lengths, 2), key=lengths.index)
            facts.append(takes_between(id, shortest, longest))
    kind = rng.random()
    if kind < 0.3:
        facts.append(complete(None, None))
    elif kind < 0.4:
        facts.append(complete(rng.choice(PLACES), None))
    elif kind < 0.5:
        whole = complete(None, None)
        whole["complete"]["leaving"] = {
            "earliest": starts_at("x", 9 + rng.randrange(2))["starts_at"],
            "latest": starts_at("x", 11 + rng.randrange(3))["starts_at"],
        }
        facts.append(whole)
    if rng.random() < 0.4:
        facts.append(starts_from("sam", rng.choice(PLACES)))
    wants: list[Document] = []
    if rng.random() < 0.6:
        wants.append(must("a-view", "sam"))
        for option in rng.sample(options, rng.choice([1, 1, 2])):
            facts.append(satisfies(option["id"], "a-view"))
        if rng.random() < 0.7:
            facts.append(every("a-view"))
    people = ["sam", "jo"] if rng.random() < 0.25 else ["sam"]
    locked = [lock(option["id"], "sam") for option in options if rng.random() < 0.4]
    if rng.random() < 0.4:
        locked.append(trip_starts(rng.choice([8, 9])))
    if rng.random() < 0.4:
        locked.append(trip_ends(rng.choice([13, 15, 18])))
    return trip(people, PLACES, options, facts, locked, ways=ways, wants=wants)


GENERATORS: list[Callable[[Random], File]] = [
    a_day_of_stops,
    two_places_with_no_listed_way,
    lambda rng: random_trip(rng, 0.25, contingent=0.3, with_complete=0.4, with_ways=0.9),
    lambda rng: random_trip(rng, 0.1, persons=["alex", "sam"], with_ways=0.9, with_complete=0.5),
]


def with_other_ways(rng: Random, file: File, world: World) -> World:
    """The same world, with unlisted WAYs between some PLACEs of this FILE, at some length."""
    places = [place.id for place in file.places]
    pairs = [(here, there) for here in places for there in places if here != there]
    joined = frozenset(pair for pair in pairs if rng.random() < 0.15)
    return replace(world, unlisted=joined, unlisted_takes=rng.choice([0, 300, 900, 3600]))


def kind_of(file: File, world: World, one: int, other: int) -> str:
    """Why two OPTIONs are apart: their times overlap, or the travel between them takes too long."""
    first, then = sorted(
        (world.terms[file.options[index].id] for index in (one, other)),
        key=lambda terms: terms.fixed_start or 0,
    )
    assert first.fixed_start is not None
    assert then.fixed_start is not None
    if first.longest is None or first.fixed_start + first.shortest > then.fixed_start:
        return "at once"
    return "too far"


def test_no_itinerary_has_a_person_in_two_options_that_are_apart() -> None:
    """The claim, tried on every pair it names: LOCK a PERSON into both, and nothing works.

    The reference checker tries every choice, in the worst case, the best case, the case where
    every duration runs longest, and some possible worlds.
    """
    rng = Random(2027)
    seen: Counter[str] = Counter()
    for round_ in range(700):
        file = GENERATORS[round_ % len(GENERATORS)](rng)
        worlds = [worst_case(file), best_case(file), longest_case(file)]
        worlds += [with_other_ways(rng, file, possible_world(rng, file)) for _ in range(2)]
        spans = [fact for fact in file.facts if isinstance(fact, Complete)]
        for world in worlds:
            no_time = NoTimeBetween(file, world)
            for one, other in combinations(range(len(file.options)), 2):
                if not no_time.apart(one, other):
                    continue
                kind = kind_of(file, world, one, other)
                seen[kind] += 1
                if any(option.origin != option.destination for option in file.options):
                    seen[f"{kind}, with a ride in the FILE"] += 1
                if world.unlisted:
                    seen[f"{kind}, in a world with unlisted WAYs"] += 1
                    if any(
                        fact.rules_out(*pair, fact.earliest)
                        for fact in spans
                        for pair in world.unlisted
                    ):
                        seen[f"{kind}, where a COMPLETE FACT is about one of them"] += 1
                both = (
                    Lock("both-one", file.options[one].id, (file.persons[0].id,)),
                    Lock("both-other", file.options[other].id, (file.persons[0].id,)),
                )
                locked = replace(file, decisions=(*file.decisions, *both))
                assert not reference.any_works(locked, world), (round_, one, other)
    assert seen["at once"] > 100
    assert seen["too far"] > 100
    assert seen["too far, with a ride in the FILE"] > 20
    assert seen["too far, in a world with unlisted WAYs"] > 20
    assert seen["too far, where a COMPLETE FACT is about one of them"] > 20


def lunch_and_a_boat(*more: Document, walk: str = "PT20M", others: int = 0) -> File:
    """Sam is LOCKed into lunch until 2:00 pm and must go on the river. One boat leaves at 2:15.

    The dock is a walk away, boarding closes 15 minutes before the boat leaves, and a FACT
    says the FILE lists every way. ``others`` adds stops that nobody has to make.
    """
    stops = [stays(f"stop-{number}", "museum") for number in range(others)]
    extra = [
        fact
        for number in range(others)
        for fact in (
            starts_at(f"stop-{number}", 15 + number // 2, 30 * (number % 2)),
            lasts(f"stop-{number}", "PT30M"),
        )
    ]
    return trip(
        ["sam"],
        PLACES,
        [stays("lunch", "hotel"), stays("boat", "dock"), *stops],
        [
            starts_at("lunch", 12, 30),
            lasts("lunch", "PT1H30M"),
            starts_at("boat", 14, 15),
            lasts("boat", "PT1H"),
            cutoff("boat", "PT15M"),
            satisfies("boat", "the-river"),
            every("the-river"),
            takes("walk", walk),
            complete(None, None),
            *extra,
            *more,
        ],
        [lock("lunch", "sam")],
        ways=[way_between("walk", "hotel", "dock"), way_between("stroll", "hotel", "museum")],
        wants=[must("the-river", "sam")],
    )


def never(*given: object, **named: object) -> bool:
    return False


def nothing(*given: object, **named: object) -> None:
    return None


def as_it_is(file: File, world: World) -> World:
    return world


def apart(file: File, world: World, one: str, other: str) -> bool:
    ids = [option.id for option in file.options]
    return NoTimeBetween(file, world).apart(ids.index(one), ids.index(other))


def test_lunch_until_two_and_a_boat_that_boards_at_two_are_apart() -> None:
    file = lunch_and_a_boat()
    assert apart(file, worst_case(file), "lunch", "boat")
    assert apart(file, best_case(file), "boat", "lunch")
    report = compiler.check(file)
    assert report == answers.check(file)
    assert report.answer is Answer.INFEASIBLE
    assert set(report.conflict) >= {"lunch-time", "boat-time", "walk-length", "lock-lunch"}


def test_a_walk_that_takes_no_time_leaves_them_together() -> None:
    file = lunch_and_a_boat(walk="PT0S")
    assert not apart(file, worst_case(file), "lunch", "boat")
    assert compiler.check(file).answer is Answer.FEASIBLE


def test_a_ride_that_gets_there_in_time_leaves_them_together() -> None:
    """A water taxi from the hotel to the dock takes no time that anybody has stated."""
    taxi = moves("taxi", "hotel", "dock")
    file = lunch_and_a_boat()
    with_taxi = replace(file, options=(*file.options, trip([], PLACES, [taxi], [], []).options[0]))
    best = best_case(with_taxi)
    assert not apart(with_taxi, best, "lunch", "boat")
    assert apart(file, best_case(file), "lunch", "boat")


def test_an_unlisted_way_counts_where_the_file_does_not_rule_it_out() -> None:
    """With no FACT that the ways are COMPLETE, another way to the dock might exist."""
    file = lunch_and_a_boat()
    open_ = replace(file, facts=tuple(fact for fact in file.facts if fact.id != "ways"))
    assert not apart(open_, best_case(open_), "lunch", "boat")
    # The worst case has no unlisted WAY, so there the walk is all there is.
    assert apart(open_, worst_case(open_), "lunch", "boat")


def test_a_boat_with_no_boarding_time_stated_is_left_to_the_search() -> None:
    """Nobody knows how early Sam has to board. In the worst case no time is early enough."""
    file = lunch_and_a_boat()
    unknown = replace(file, facts=tuple(fact for fact in file.facts if fact.id != "boat-cutoff"))
    assert not apart(unknown, worst_case(unknown), "lunch", "boat")
    assert compiler.check(unknown) == answers.check(unknown)


def models_built(file: File, monkeypatch: pytest.MonkeyPatch) -> int:
    """How many models a check builds."""
    built: list[object] = []
    search = compiler._Search.__init__  # pyright: ignore[reportPrivateUsage]

    def counted(self: object, *given: object, **named: object) -> None:
        built.append(self)
        search(self, *given, **named)  # type: ignore[arg-type]

    monkeypatch.setattr(compiler._Search, "__init__", counted)  # pyright: ignore[reportPrivateUsage]
    compiler.check(file)
    monkeypatch.undo()
    return len(built)


def test_a_person_who_has_to_take_two_options_apart_needs_no_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A question about a record outside the conflict is answered before a model is built.

    Twelve stops that nobody has to make bring 24 FACTs. Without the look, each of them costs
    a model.
    """
    file = lunch_and_a_boat(others=12)
    with_the_look = models_built(file, monkeypatch)
    monkeypatch.setattr(compiler, "_has_to_take_two_apart", never)
    without = models_built(file, monkeypatch)
    assert with_the_look < 20
    assert without > with_the_look + 24


def test_the_looks_change_no_report(monkeypatch: pytest.MonkeyPatch) -> None:
    """The same Reports with the two looks and without them, and the reference checker's."""
    rng = Random(75)
    trips = [GENERATORS[number % len(GENERATORS)](rng) for number in range(400)]
    trips += [lunch_and_a_boat(), lunch_and_a_boat(walk="PT10M", others=2)]
    with_them = [compiler.check(file) for file in trips]
    assert {report.answer for report in with_them} == set(Answer)
    # The reference checker tries every route, so it gets the FILEs with few WAYs.
    small = [number for number, file in enumerate(trips) if len(file.ways) < 3]
    assert len(small) > 100
    for number in small[::2]:
        assert with_them[number] == answers.check(trips[number])
    monkeypatch.setattr(compiler, "_has_to_take_two_apart", never)
    monkeypatch.setattr(compiler._Search, "_take_one_of_two_apart", nothing)  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(compiler, "_with_the_ways_that_can_start", as_it_is)
    assert [compiler.check(file) for file in trips] == with_them


def test_another_boat_might_be_found_where_the_set_is_not_complete() -> None:
    """With no FACT that the FILE lists every boat, Sam does not have to take this one."""
    file = lunch_and_a_boat()
    open_ = replace(file, facts=tuple(fact for fact in file.facts if fact.id != "every-the-river"))
    report = compiler.check(open_)
    assert report == answers.check(open_)
    assert report.answer is Answer.UNDETERMINED


def test_an_option_that_might_meet_a_must_leaves_the_other_one_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sam must go on the river and Jo must not. A ferry at 4:00 pm would do for Sam.

    Jo is LOCKed into two talks at 6:00 pm, so the TRIP is INFEASIBLE. The search for the
    conflict first takes out the FACT that the ferry SATISFIES the WANT: then nobody knows
    whether it does. Sam still does not have to take the boat, which lunch rules out. So the
    talks stay the whole conflict, as they are with no look at all.
    """
    file = trip(
        ["sam", "jo"],
        PLACES,
        [
            stays("lunch", "hotel"),
            stays("boat", "dock"),
            stays("ferry", "dock"),
            stays("talk-a", "museum"),
            stays("talk-b", "museum"),
        ],
        [
            satisfies("ferry", "the-river"),
            starts_at("talk-a", 18),
            lasts("talk-a", "PT1H"),
            starts_at("talk-b", 18),
            lasts("talk-b", "PT1H"),
            starts_at("lunch", 12, 30),
            lasts("lunch", "PT1H30M"),
            starts_at("boat", 14, 15),
            lasts("boat", "PT1H"),
            cutoff("boat", "PT15M"),
            satisfies("boat", "the-river"),
            starts_at("ferry", 16),
            lasts("ferry", "PT1H"),
            cutoff("ferry", "PT15M"),
            every("the-river"),
            takes("walk", "PT20M"),
            complete(None, None),
        ],
        [lock("lunch", "sam"), lock("talk-a", "jo"), lock("talk-b", "jo")],
        ways=[way_between("walk", "hotel", "dock")],
        wants=[must("the-river", "sam", never=["jo"])],
    )
    report = compiler.check(file)
    assert report.answer is Answer.INFEASIBLE
    talks = {"talk-a-time", "talk-a-length", "talk-b-time", "talk-b-length"}
    assert set(report.conflict) == talks | {"lock-talk-a", "lock-talk-b"}
    monkeypatch.setattr(compiler, "_has_to_take_two_apart", never)
    monkeypatch.setattr(compiler._Search, "_take_one_of_two_apart", nothing)  # pyright: ignore[reportPrivateUsage]
    assert compiler.check(file) == report


def test_a_way_that_opens_after_ten_is_there_for_noon_and_not_for_ten() -> None:
    """Sam is LOCKed at the hotel at 9:00 and at the dock at noon. A ride back leaves at 10:00.

    A FACT says the FILE lists every way from the hotel to the dock that leaves from 9:00 to
    10:00, and it lists none. So nobody gets from the hotel to the ride. Sam can still leave
    for the dock a second after 10:00, by a way that nobody has listed, and be there at noon.
    The two pairs leave the same PLACE, and each has its own answer.
    """
    closed = complete("hotel", "dock")
    closed["complete"]["leaving"] = {"earliest": at(9), "latest": at(10)}
    stops = {"morning": 9, "noon": 12, "back": 10}
    file = trip(
        ["sam"],
        ["hotel", "dock"],
        [stays("morning", "hotel"), stays("noon", "dock"), moves("back", "dock", "hotel")],
        [
            *(
                fact
                for stop, hour in stops.items()
                for fact in (starts_at(stop, hour), lasts(stop, "PT0S"), cutoff(stop, "PT0S"))
            ),
            closed,
        ],
        [lock("morning", "sam"), lock("noon", "sam")],
    )
    report = compiler.check(file)
    assert report == answers.check(file)
    assert report.answer is Answer.UNDETERMINED
    ((needed,),) = report.missing
    assert (needed.unknown.what, needed.at_most) == ("other ways", 2 * 3600 - 1)
    # In a world with such a way, the answer for each pair is the same whichever is asked first.
    world = replace(best_case(file), unlisted=frozenset({("hotel", "dock")}))
    for first, then in (
        (("morning", "back"), ("morning", "noon")),
        (("morning", "noon"), ("morning", "back")),
    ):
        no_time = NoTimeBetween(file, world)
        ids = [option.id for option in file.options]
        said = {pair: no_time.apart(*(ids.index(id) for id in pair)) for pair in (first, then)}
        assert said == {("morning", "back"): True, ("morning", "noon"): False}


def lunch_and_two_boats(stops: int) -> File:
    """Sam is LOCKed into lunch until 2:00 pm and must go on the river. Two boats would do.

    They leave at 2:15 pm and 2:16 pm from a dock that is a walk away, so lunch rules both
    out. Sam is also LOCKed into ``stops`` stops at no stated time.
    """
    boats = {"boat": 15, "later-boat": 16}
    names = [f"stop-{number}" for number in range(stops)]
    return trip(
        ["sam"],
        PLACES,
        [
            stays("lunch", "hotel"),
            *(stays(boat, "dock") for boat in boats),
            *(stays(name, PLACES[1 + number % 3]) for number, name in enumerate(names)),
        ],
        [
            starts_at("lunch", 12, 30),
            lasts("lunch", "PT1H30M"),
            *(
                fact
                for boat, minute in boats.items()
                for fact in (
                    starts_at(boat, 14, minute),
                    lasts(boat, "PT1H"),
                    cutoff(boat, "PT15M"),
                    satisfies(boat, "the-river"),
                )
            ),
            every("the-river"),
            takes("walk", "PT20M"),
            takes("stroll", "PT10M"),
            takes("bus", "PT15M"),
            complete(None, None),
            *(lasts(name, "PT30M") for name in names),
        ],
        [lock("lunch", "sam"), *(lock(name, "sam") for name in names)],
        ways=[
            way_between("walk", "hotel", "dock"),
            way_between("stroll", "hotel", "museum"),
            way_between("bus", "dock", "pier"),
        ],
        wants=[must("the-river", "sam")],
    )


def test_the_model_rules_out_what_is_apart_from_what_a_person_has_to_take(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two boats can meet the must, so Sam has to take neither, and a model is built.

    The model says outright that Sam takes no boat: each is apart from the lunch. Without
    that, the solver tries the stops with no stated time in every order between the lunch
    and a boat.
    """
    file = lunch_and_two_boats(5)
    solves = solves_counted(monkeypatch)
    assert not compiler.can_work(Remaining(file))
    assert len(solves) == 1
    assert searched(solves) < 10
    solves.clear()
    monkeypatch.setattr(compiler._Search, "_take_one_of_two_apart", nothing)  # pyright: ignore[reportPrivateUsage]
    assert not compiler.can_work(Remaining(file))
    assert searched(solves) > 1000


def two_stops_with_no_listed_way(
    span: tuple[str, str],
    starts: str | None = "08:00:00",
    ends: str | None = "13:00:00",
    about: tuple[str | None, str | None] = (None, None),
) -> File:
    """Sam is LOCKed at the hotel at 9:00 and into a stop at the dock at no stated time.

    The FILE lists no WAY. A FACT says it lists every way that leaves within ``span``,
    between the PLACEs in ``about``. DECISIONs say when the TRIP starts and ends, unless one
    is None. So Sam needs a way that nobody has listed, at a time the FACT leaves open.
    """

    def moment(clock: str) -> str:
        return at(9).replace("09:00:00", clock)

    closed = complete(*about)
    closed["complete"]["leaving"] = {"earliest": moment(span[0]), "latest": moment(span[1])}
    decisions = [lock("morning", "sam"), lock("later", "sam")]
    if starts is not None:
        decisions.append({"id": "trip-start", "trip_starts_at": moment(starts)})
    if ends is not None:
        decisions.append({"id": "trip-end", "trip_ends_at": moment(ends)})
    return trip(
        ["sam"],
        ["hotel", "dock", "pier"],
        [stays("morning", "hotel"), stays("later", "dock")],
        [
            starts_at("morning", 9),
            lasts("morning", "PT0S"),
            cutoff("morning", "PT0S"),
            any_time("later"),
            lasts("later", "PT0S"),
            cutoff("later", "PT0S"),
            closed,
        ],
        decisions,
    )


WHOLE_TRIP = ("08:00:00", "13:00:00")


@pytest.mark.parametrize(
    ("file", "leaves_none", "answer"),
    [
        (two_stops_with_no_listed_way(WHOLE_TRIP), True, Answer.INFEASIBLE),
        (two_stops_with_no_listed_way(("00:00:00", "23:59:00")), True, Answer.INFEASIBLE),
        (two_stops_with_no_listed_way(("08:00:01", "13:00:00")), False, Answer.UNDETERMINED),
        (two_stops_with_no_listed_way(("08:00:00", "12:59:59")), False, Answer.UNDETERMINED),
        (two_stops_with_no_listed_way(WHOLE_TRIP, starts=None), False, Answer.UNDETERMINED),
        (two_stops_with_no_listed_way(WHOLE_TRIP, ends=None), False, Answer.UNDETERMINED),
        (
            two_stops_with_no_listed_way(WHOLE_TRIP, about=("pier", None)),
            False,
            Answer.UNDETERMINED,
        ),
        (
            two_stops_with_no_listed_way(WHOLE_TRIP, about=(None, "pier")),
            False,
            Answer.UNDETERMINED,
        ),
    ],
    ids=[
        "the span is the whole TRIP",
        "the span is the whole day",
        "the span starts a second after the TRIP",
        "the span ends a second before the TRIP",
        "the TRIP has no start",
        "the TRIP has no end",
        "the FACT is about the ways from the pier",
        "the FACT is about the ways to the pier",
    ],
)
def test_no_unlisted_way_is_tried_where_none_can_start(
    file: File, leaves_none: bool, answer: Answer
) -> None:
    """A FACT about all travel for the whole TRIP leaves no time for an unlisted WAY.

    Then the solver is given a world with none. A second of the TRIP outside the span, a
    TRIP with no start or no end, or a FACT about some PLACEs only, and the world stays as
    it is: a way that nobody has listed could still help.
    """
    best = best_case(file)
    narrowed = compiler._with_the_ways_that_can_start(file, best)  # pyright: ignore[reportPrivateUsage]
    assert best.unlisted is None
    assert narrowed == (replace(best, unlisted=frozenset()) if leaves_none else best)
    report = compiler.check(file)
    assert report == answers.check(file)
    assert report.answer is answer


def test_the_model_has_no_route_that_nobody_can_take(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lunch and a boat, with the times of the TRIP stated: each model is of a world with no
    unlisted WAY, and it is smaller for that.
    """
    day = [trip_starts(8), trip_ends(20)]
    file = lunch_and_a_boat(others=3)
    file = replace(file, decisions=(*file.decisions, *trip([], [], [], [], day).decisions))
    seen: list[tuple[frozenset[tuple[str, str]] | None, int]] = []
    search = compiler._Search.__init__  # pyright: ignore[reportPrivateUsage]

    def noted(self: compiler._Search, *given: object, **named: object) -> None:  # pyright: ignore[reportPrivateUsage]
        search(self, *given, **named)  # type: ignore[arg-type]
        size = len(self.model.proto.variables)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        seen.append((self.world.unlisted, size))

    monkeypatch.setattr(compiler._Search, "__init__", noted)  # pyright: ignore[reportPrivateUsage]
    report = compiler.check(file)
    with_none = list(seen)
    seen.clear()
    monkeypatch.setattr(compiler, "_with_the_ways_that_can_start", as_it_is)
    assert compiler.check(file) == report
    assert report.answer is Answer.INFEASIBLE
    # The records go one by one. While the two times of the TRIP and the FACT are all still in,
    # the world has no unlisted WAY.
    assert frozenset() in {unlisted for unlisted, _ in with_none}
    assert frozenset() not in {unlisted for unlisted, _ in seen}
    assert sum(size for _, size in with_none) < sum(size for _, size in seen)
