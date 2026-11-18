"""The COMPILER finds with a solver what the reference checker finds by trying everything."""

import json
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from random import Random

import pytest

from agloe import answers, compiler, reference
from agloe.answers import Answer, Missing
from agloe.file import File, load, read
from agloe.reference import (
    Remaining,
    Unknown,
    World,
    best_case,
    longest_case,
    unknowns,
    with_these_at_best,
    worst_case,
)
from agloe.report import together
from tests.stories import (
    EXAMPLES,
    Document,
    any_time,
    at,
    complete,
    cutoff,
    ends_at,
    lasts,
    lasts_between,
    lock,
    moves,
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
from tests.test_answers import (
    WALKS,
    a_morning,
    a_ride_there_and_back,
    lunch_away_from_the_museum,
    two_who_swap_places,
)
from tests.test_cross_check import (
    a_group_that_meets,
    a_shared_ride,
    possible_world,
    random_trip,
    two_places_with_no_listed_way,
)

FILES = sorted(
    path for path in EXAMPLES.rglob("*.json") if not path.name.endswith(".expected.json")
)


@pytest.mark.parametrize("path", FILES, ids=lambda path: f"{path.parent.name}/{path.stem}")
def test_the_compiler_gives_the_reference_checkers_report(path: Path) -> None:
    """With the solver's own search for every part of it: no example is too big for the solver."""
    file = read(path)
    found = answers.check(file, compiler.shown, compiler.works, compiler.stuck)
    assert found == answers.check(file)


def test_a_trip_too_big_for_the_solver_gets_the_reference_checkers_answer() -> None:
    """Sam goes through ten PLACES. Three WAYs join each to the next: 19,683 routes in all.

    One WAY takes 999,999,999 hours. Where every FACT can be switched off, each route has its
    own times in the model, and together they are more than the solver can count.
    """
    places = [f"p{number}" for number in range(10)]
    ways = [way(f"w{n}-{k}", f"p{n}", f"p{n + 1}") for n in range(9) for k in range(3)]
    facts = [starts_from("sam", "p0"), takes("w0-0", "PT999999999H")]
    now = [trip_starts(9), trip_ends(9)]
    file = trip(["sam"], places, [], facts, now, ways=ways, wants=[ends_at("p9", "sam")])
    with pytest.raises(compiler.DoesNotFit):
        compiler.stuck(Remaining(file))
    found = compiler.check(file)
    assert found == answers.check(file)
    assert found.missing == ((Missing(Unknown("other ways", origin="p0", destination="p9"), 0),),)


def test_times_too_far_apart_for_the_solver_get_the_reference_checkers_answer() -> None:
    """One WAY takes over 100,000 years. Nobody takes it, but the solver has to leave room.

    With 1,122 PLACES and as many visits that nobody has to make, a path could take longer than
    a 64-bit number of seconds can say.
    """
    places = [f"p{number}" for number in range(1122)]
    visits = [stays(f"visit-{number}", "p0") for number in range(1122)]
    far = [takes("far", "PT999999999H999999999M999999999S")]
    file = trip(["sam"], places, visits, far, [], ways=[way("far", "p0", "p1")])
    with pytest.raises(compiler.DoesNotFit):
        compiler.works(file, worst_case(file))
    found = compiler.check(file)
    assert found == answers.check(file)
    assert (found.answer, found.itinerary) == (Answer.FEASIBLE, ())


def test_a_fault_in_the_model_is_not_taken_for_a_trip_that_is_too_big() -> None:
    """Only numbers that do not fit send a TRIP to the reference checker's search."""
    file = trip(["sam"], ["a"], [stays("visit", "a")], [], [])
    search = compiler._Search(file, worst_case(file))  # pyright: ignore[reportPrivateUsage]
    # A choice the model does not have, put where only the solver looks at it.
    search.model.proto.constraints.add().bool_or.literals.append(  # pyright: ignore[reportUnknownMemberType]
        99999
    )
    with pytest.raises(AssertionError, match="the solver refused the model"):
        search.any()


def test_the_compiler_and_the_reference_checker_agree_on_random_trips() -> None:
    """The same Report for every TRIP: the answer, the ITINERARY shown and the evidence."""
    rng = Random(404)
    trips = [random_trip(rng, leave_out=0) for _ in range(80)]
    trips += [a_shared_ride(rng) for _ in range(80)]
    trips += [random_trip(rng, leave_out=0, contingent=0.6) for _ in range(80)]
    trips += [random_trip(rng, 0.25, contingent=0.3, with_complete=0.4) for _ in range(120)]
    trips += [two_places_with_no_listed_way(rng) for _ in range(80)]
    trips += [random_trip(rng, leave_out=0, contingent=0.5, with_ways=0.9) for _ in range(80)]
    trips += [
        random_trip(rng, 0.2, contingent=0.3, with_complete=0.4, with_ways=0.9) for _ in range(120)
    ]
    seen: set[Answer] = set()
    robust: set[bool | None] = set()
    for file in trips:
        report = answers.check(file)
        assert compiler.check(file) == report
        if report.answer is Answer.FEASIBLE:
            assert reference.broken(file, worst_case(file), report.itinerary) == []
            shown = tuple(together(report.itinerary))
            assert reference.works_as_listed(file, worst_case(file), shown)
        seen.add(report.answer)
        robust.add(report.robust)
    assert seen == set(Answer)
    assert robust == {True, False, None}


def test_the_two_searches_agree_in_every_kind_of_world() -> None:
    """The same ITINERARY first, or none, in the worlds the answers and the evidence are built on.

    Those are the worst case, the longest durations, the best case, worlds in which a few unknown
    FACTs turn out well, and possible worlds chosen at random.
    """
    rng = Random(505)
    trips = [random_trip(rng, 0.3, contingent=0.2, with_complete=0.5) for _ in range(60)]
    trips += [
        random_trip(rng, 0.3, contingent=0.2, with_complete=0.5, with_ways=1) for _ in range(100)
    ]
    trips += [two_places_with_no_listed_way(rng) for _ in range(40)]
    trips += [a_shared_ride(rng) for _ in range(20)]
    found: set[bool] = set()
    unlisted = listed = 0
    for file in trips:
        every = unknowns(file)
        worlds = [worst_case(file), longest_case(file), best_case(file)]
        for _ in range(2):
            some = rng.sample(every, min(len(every), rng.randrange(1, 4)))
            worlds.append(with_these_at_best(file, some))
            worlds.append(possible_world(rng, file))
        for world in worlds:
            first = reference.first_shown(file, world)
            assert compiler.shown(file, world) == first
            assert compiler.works(file, world) == (first is not None)
            found.add(first is not None)
            unlisted += any(step.option is None and step.way is None for step in first or ())
            listed += any(step.way is not None for step in first or ())
    assert found == {True, False}
    assert unlisted > 50
    assert listed > 30


def test_a_limit_does_not_depend_on_how_far_the_solver_can_count() -> None:
    """Alex's two OPTIONs can start at any time, so another way between them can take any time.

    With OR-Tools 9.15, the solver's simplification step once said that a way of about eight
    years could not work, though shorter and longer ones could.
    """
    file = trip(
        ["alex"],
        ["a", "b", "c"],
        [moves("option-0", "b", "a"), stays("option-1", "b"), moves("option-2", "c", "a")],
        [
            starts_at("option-0", 9, 45),
            lasts("option-0", "PT15M"),
            cutoff("option-0", "PT0S"),
            any_time("option-1"),
            lasts_between("option-1", "PT15M", "PT30M"),
            cutoff("option-1", "PT15M"),
            any_time("option-2"),
            lasts_between("option-2", "PT0S", "PT30M"),
            cutoff("option-2", "PT15M"),
        ],
        [lock("option-1", "alex"), lock("option-2", "alex")],
    )
    report = compiler.check(file)
    assert report == answers.check(file)
    assert [needed.at_most for enough in report.missing for needed in enough] == [None, None, None]
    years = with_these_at_best(file, [Unknown("other ways", origin="a", destination="b")])
    for seconds_taken in (262_223_455, 262_223_456, 268_435_456, 2**40):
        assert compiler.works(file, replace(years, unlisted_takes=seconds_taken))


def stops(*visits: tuple[str, str, int, int], more: Sequence[Document] = ()) -> File:
    """Alex is LOCKed onto a stop at each of these PLACEs, at these times. Each takes no time."""
    names = [name for name, _, _, _ in visits]
    return trip(
        ["alex"],
        ["a", "b", "c", "d"],
        [stays(name, place) for name, place, _, _ in visits],
        [
            fact
            for name, _, hour, minute in visits
            for fact in (starts_at(name, hour, minute), lasts(name, "PT0S"), cutoff(name, "PT0S"))
        ]
        + list(more),
        [lock(name, "alex") for name in names],
    )


def same_in_both(file: File, world: World) -> bool:
    """Whether anything works in this world, once both searches have agreed on what is shown."""
    first = reference.first_shown(file, world)
    assert compiler.shown(file, world) == first
    assert compiler.works(file, world) == (first is not None)
    return first is not None


def test_a_complete_set_about_two_places_leaves_the_way_through_a_third_open() -> None:
    """Every way straight from a to b is listed: there is none. A listed ride runs from c to b."""

    def with_ride(ways: Document) -> File:
        return trip(
            ["alex"],
            ["a", "b", "c", "d"],
            [stays("first", "a"), stays("last", "b"), moves("ride", "c", "b")],
            [
                starts_at("first", 9),
                lasts("first", "PT0S"),
                cutoff("first", "PT0S"),
                starts_at("last", 10),
                lasts("last", "PT0S"),
                cutoff("last", "PT0S"),
                starts_at("ride", 9, 30),
                lasts("ride", "PT10M"),
                cutoff("ride", "PT0S"),
                ways,
            ],
            [lock("first", "alex"), lock("last", "alex")],
        )

    through_c = with_ride(complete("a", "b"))
    assert same_in_both(through_c, best_case(through_c))
    # Every way from a is listed, and there is none. So Alex cannot leave a at all.
    shut_in = with_ride(complete("a", None))
    assert not same_in_both(shut_in, best_case(shut_in))
    freed = shut_in.without("ways-from-a")
    assert same_in_both(freed, best_case(freed))


def test_a_span_starts_on_its_first_second() -> None:
    """Every way from a that leaves from 9:00:00 on is listed, and there is none.

    No way leads to a either, so Alex cannot do the stop at b first.
    """
    from_nine = {"from": "a", "leaving": {"earliest": at(9), "latest": at(12)}}
    ways = [{"id": "ways", "complete": from_nine}, complete(None, "a")]
    on_the_dot = stops(("first", "a", 9, 0), ("last", "b", 9, 0), more=ways)
    assert not same_in_both(on_the_dot, best_case(on_the_dot))
    a_minute_before = stops(("first", "a", 8, 59), ("last", "b", 9, 0), more=ways)
    assert same_in_both(a_minute_before, best_case(a_minute_before))


def test_other_ways_can_follow_a_listed_one() -> None:
    """Alex takes the listed ride from a to b, then goes on to c and back to b by other ways."""
    ride = [
        moves("ride", "a", "b"),
        starts_at("ride", 9),
        lasts("ride", "PT10M"),
        cutoff("ride", "PT0S"),
    ]
    file = trip(
        ["alex"],
        ["a", "b", "c", "d"],
        [stays("first", "a"), ride[0], stays("far", "c"), stays("last", "b")],
        [
            starts_at("first", 8, 50),
            lasts("first", "PT0S"),
            *ride[1:],
            starts_at("far", 10),
            lasts("far", "PT0S"),
            cutoff("far", "PT0S"),
            starts_at("last", 10, 30),
            lasts("last", "PT0S"),
            cutoff("last", "PT0S"),
            complete("a", "b"),
        ],
        [lock("first", "alex"), lock("far", "alex"), lock("last", "alex")],
    )
    assert same_in_both(file, best_case(file))


def test_every_route_between_two_places_is_tried() -> None:
    """Unlisted WAYs lead from a to d through b or through c. Only the way through c is open."""
    file = stops(("first", "a", 9, 0), ("last", "d", 10, 0), more=[complete("a", "b")])
    ways = frozenset({("a", "b"), ("b", "d"), ("a", "c"), ("c", "d")})
    assert same_in_both(file, World(worst_case(file).terms, ways))
    only_through_b = frozenset({("a", "b"), ("b", "d")})
    assert not same_in_both(file, World(worst_case(file).terms, only_through_b))


def at_one_instant(rng: Random) -> File:
    """Three or four OPTIONs that take no time, all at 9:00, between two PLACEs."""
    options = [
        stays(f"option-{number}", rng.choice("ab"))
        if rng.random() < 0.4
        else moves(f"option-{number}", *rng.sample("ab", 2))
        for number in range(rng.choice([3, 4]))
    ]
    facts = [
        fact
        for option in options
        for fact in (
            starts_at(option["id"], 9),
            lasts(option["id"], "PT0S"),
            cutoff(option["id"], "PT0S"),
        )
    ]
    decisions = [
        lock(option["id"], *rng.sample(["alex", "sam"], rng.choice([1, 2])))
        for option in options
        if rng.random() < 0.7
    ]
    return trip(["alex", "sam"], ["a", "b"], options, facts, decisions)


def test_the_compiler_and_the_reference_checker_agree_at_one_instant() -> None:
    """OPTIONs that share an instant must happen in one order for everyone."""
    rng = Random(9)
    feasible: set[bool] = set()
    for _ in range(200):
        file = at_one_instant(rng)
        every = reference.itineraries(file, worst_case(file))
        assert compiler.shown(file, worst_case(file)) == (every[0] if every else None)
        feasible.add(bool(every))
    assert feasible == {True, False}


def test_two_persons_cannot_take_two_rides_in_opposite_orders() -> None:
    """Alex starts at a and Sam at b. Two rides that take no time leave at 9:30, one each way."""
    file = trip(
        ["alex", "sam"],
        ["a", "b"],
        [
            stays("first", "a"),
            stays("second", "b"),
            moves("out", "a", "b"),
            moves("back", "b", "a"),
        ],
        [
            starts_at("first", 9),
            lasts("first", "PT30M"),
            starts_at("second", 9),
            lasts("second", "PT30M"),
            starts_at("out", 9, 30),
            lasts("out", "PT0S"),
            cutoff("out", "PT0S"),
            starts_at("back", 9, 30),
            lasts("back", "PT0S"),
            cutoff("back", "PT0S"),
        ],
        [
            lock("first", "alex"),
            lock("second", "sam"),
            lock("out", "alex", "sam"),
            lock("back", "alex", "sam"),
        ],
    )
    assert compiler.shown(file, worst_case(file)) is None


def test_a_cutoff_counts_from_the_arrival_however_long_ago() -> None:
    """Alex rides to the airport, has a coffee there, and then finds bag drop closed."""

    def with_ride_at(hour: int, minute: int) -> File:
        return trip(
            ["alex"],
            ["hotel", "airport", "home"],
            [
                moves("ride", "hotel", "airport"),
                stays("coffee", "airport"),
                moves("flight", "airport", "home"),
            ],
            [
                starts_at("ride", hour, minute),
                lasts("ride", "PT30M"),
                cutoff("ride", "PT0S"),
                any_time("coffee"),
                lasts("coffee", "PT10M"),
                cutoff("coffee", "PT0S"),
                starts_at("flight", 10),
                lasts("flight", "PT2H"),
                cutoff("flight", "PT45M"),
            ],
            [lock("ride", "alex"), lock("coffee", "alex"), lock("flight", "alex")],
        )

    in_time, too_late = with_ride_at(8, 45), with_ride_at(9, 0)
    assert compiler.check(in_time).answer is Answer.FEASIBLE
    assert compiler.shown(too_late, worst_case(too_late)) is None
    assert compiler.check(too_late) == answers.check(too_late)


def two_ways_through(*ids: str) -> File:
    """Alex goes from a through b to c. An early pair of rides and a late pair both work."""
    rides = {
        "early-to-b": (moves("early-to-b", "a", "b"), 9, 0),
        "early-to-c": (moves("early-to-c", "b", "c"), 9, 30),
        "late-to-b": (moves("late-to-b", "a", "b"), 10, 0),
        "late-to-c": (moves("late-to-c", "b", "c"), 10, 30),
    }
    stops = {"start": (stays("start", "a"), 8, 30), "finish": (stays("finish", "c"), 11, 30)}
    every = {**rides, **stops}
    return trip(
        ["alex"],
        ["a", "b", "c"],
        [every[id][0] for id in ids],
        [
            fact
            for id in ids
            for fact in (
                starts_at(id, every[id][1], every[id][2]),
                lasts(id, "PT20M"),
                cutoff(id, "PT0S"),
            )
        ],
        [lock("start", "alex"), lock("finish", "alex")],
    )


def test_the_options_listed_first_matter_more_than_the_order_they_are_done_in() -> None:
    """The early pair holds the OPTION listed first, though Alex starts with one listed last."""
    file = two_ways_through("early-to-c", "late-to-b", "late-to-c", "start", "finish", "early-to-b")
    report = compiler.check(file)
    assert [step.option for step in report.itinerary] == [
        "start",
        "early-to-b",
        "early-to-c",
        "finish",
    ]
    assert report == answers.check(file)


def a_day_in_chicago(*more: dict[str, object], flight_at: int = 17) -> File:
    """Three PERSONs, ten OPTIONs: far more choices than the reference checker can try."""
    everyone = ("alex", "sam", "jo")
    options = [
        stays("breakfast", "hotel"),
        moves("walk-to-museum", "hotel", "art-institute"),
        stays("museum-visit", "art-institute"),
        moves("cab-to-river", "hotel", "river"),
        stays("boat-tour", "river"),
        moves("walk-to-pier", "art-institute", "pier"),
        moves("water-taxi", "river", "pier"),
        stays("lunch", "pier"),
        moves("cab-to-ohare", "pier", "ohare"),
        moves("flight", "ohare", "home"),
    ]
    facts = [
        starts_at("breakfast", 8),
        lasts("breakfast", "PT1H"),
        any_time("walk-to-museum"),
        lasts("walk-to-museum", "PT20M"),
        starts_at("museum-visit", 10),
        lasts("museum-visit", "PT2H"),
        any_time("cab-to-river"),
        lasts("cab-to-river", "PT15M"),
        starts_at("boat-tour", 10, 30),
        lasts("boat-tour", "PT1H30M"),
        any_time("walk-to-pier"),
        lasts("walk-to-pier", "PT25M"),
        starts_at("water-taxi", 12, 15),
        lasts("water-taxi", "PT20M"),
        starts_at("lunch", 13),
        lasts("lunch", "PT1H"),
        any_time("cab-to-ohare"),
        *more,
        starts_at("flight", flight_at),
        lasts("flight", "PT2H30M"),
        cutoff("flight", "PT45M"),
    ]
    facts += [cutoff(option["id"], "PT0S") for option in options[1:9]]
    decisions = [
        lock("breakfast", *everyone),
        lock("museum-visit", "alex", "sam"),
        lock("boat-tour", "jo"),
        lock("lunch", *everyone),
        lock("flight", *everyone),
    ]
    places = ["hotel", "art-institute", "river", "pier", "ohare", "home"]
    return trip(list(everyone), places, options, facts, decisions)


def test_the_compiler_plans_a_day_the_reference_checker_cannot_try() -> None:
    file = a_day_in_chicago(lasts("cab-to-ohare", "PT50M"))
    report = compiler.check(file)
    assert report.answer is Answer.FEASIBLE
    assert report.robust is True
    assert [(step.option, step.persons, step.start) for step in report.itinerary] == [
        ("breakfast", ("alex", "sam", "jo"), seconds(8)),
        ("walk-to-museum", ("alex", "sam"), seconds(9)),
        ("cab-to-river", ("jo",), seconds(9)),
        ("museum-visit", ("alex", "sam"), seconds(10)),
        ("boat-tour", ("jo",), seconds(10, 30)),
        ("walk-to-pier", ("alex", "sam"), seconds(12)),
        ("water-taxi", ("jo",), seconds(12, 15)),
        ("lunch", ("alex", "sam", "jo"), seconds(13)),
        ("cab-to-ohare", ("alex", "sam", "jo"), seconds(14)),
        ("flight", ("alex", "sam", "jo"), seconds(17)),
    ]
    assert reference.broken(file, worst_case(file), report.itinerary) == []


def test_the_compiler_warns_when_the_day_is_not_robust() -> None:
    """The cab to O'Hare can take up to two and a half hours."""
    file = a_day_in_chicago(lasts_between("cab-to-ohare", "PT40M", "PT2H30M"))
    report = compiler.check(file)
    assert report.answer is Answer.FEASIBLE
    assert report.robust is False
    assert [(found.constraint, found.option, found.late) for found in report.at_worst] == [
        (reference.Constraint.ARRIVAL, "flight", 15 * 60)
    ]


def test_the_compiler_names_what_is_missing_from_a_day() -> None:
    """The flight leaves at 3:00 pm. Lunch ends at 2:00 pm, and the cab takes 50 minutes."""
    file = a_day_in_chicago(lasts("cab-to-ohare", "PT50M"), flight_at=15)
    report = compiler.check(file)
    assert report.answer is Answer.UNDETERMINED
    another = Unknown("other ways", origin="pier", destination="ohare")
    assert report.missing == ((Missing(another, at_most=15 * 60),),)


def test_the_compiler_names_the_conflict_in_a_day() -> None:
    """The same day, with a FACT that the cab from the pier is the only way to O'Hare."""
    file = a_day_in_chicago(lasts("cab-to-ohare", "PT50M"), complete(None, "ohare"), flight_at=15)
    report = compiler.check(file)
    assert report.answer is Answer.INFEASIBLE
    assert report.conflict == (
        "lunch-time",
        "lunch-length",
        "cab-to-ohare-length",
        "ways-to-ohare",
        "flight-time",
        "flight-cutoff",
        "lock-lunch",
        "lock-flight",
    )
    without_the_fact = file.without("ways-to-ohare")
    assert compiler.works(without_the_fact, best_case(without_the_fact))


def test_the_conflict_named_is_the_one_found_in_the_files_order() -> None:
    """Two things are wrong at once. Sam has two fixed stops that overlap, listed first.

    Alex cannot make the flight, as in the story. Going through the records in the FILE's order
    takes Sam's out first, since Alex's still clash without them. So the conflict named is
    Alex's. The solver's own search may find either one: that depends on its proof.
    """
    document = json.loads((EXAMPLES / "flight-home" / "cannot-work.json").read_text())
    document["options"] = [stays("call", "home"), stays("nap", "home"), *document["options"]]
    document["facts"] = [
        starts_at("call", 9),
        lasts("call", "PT1H"),
        starts_at("nap", 9, 30),
        lasts("nap", "PT1H"),
        *document["facts"],
    ]
    document["decisions"] = [lock("call", "sam"), lock("nap", "sam"), *document["decisions"]]
    file = load(document)
    report = compiler.check(file)
    of_alex = (
        "visit-time",
        "visit-length",
        "train-length",
        "flight-time",
        "bag-drop",
        "ways-to-ohare",
        "lock-visit",
        "lock-flight",
    )
    of_sam = {"call-time", "call-length", "nap-time", "lock-call", "lock-nap"}
    assert report.conflict == of_alex
    assert compiler.stuck(Remaining(file)) in (frozenset(of_alex), frozenset(of_sam))


def test_two_conflicts_at_once_give_the_reference_checkers_report() -> None:
    """Alex has two stops that overlap, and so has Sam. Sam's are listed last."""
    stops = [("call", "alex"), ("nap", "alex"), ("swim", "sam"), ("lunch", "sam")]
    file = trip(
        ["alex", "sam"],
        ["hotel"],
        [stays(name, "hotel") for name, _ in stops],
        [
            fact
            for number, (name, _) in enumerate(stops)
            for fact in (starts_at(name, 9, 30 * (number % 2)), lasts(name, "PT1H"))
        ],
        [lock(name, person) for name, person in stops],
    )
    report = compiler.check(file)
    assert report == answers.check(file)
    assert report.conflict == ("swim-time", "swim-length", "lunch-time", "lock-swim", "lock-lunch")
    assert compiler.stuck(Remaining(file)) == frozenset(
        {"call-time", "call-length", "nap-time", "lock-call", "lock-nap"}
    )


def a_day_on_foot(*more: dict[str, object], flight_at: int = 17) -> File:
    """The same day, with walks and cabs as WAYs. Only the water taxi and the flight are timed."""
    everyone = ("alex", "sam", "jo")
    stops = [
        ("breakfast", "hotel", 8, 0, "PT1H"),
        ("museum-visit", "art-institute", 10, 0, "PT2H"),
        ("boat-tour", "river", 10, 30, "PT1H30M"),
        ("lunch", "pier", 13, 0, "PT1H"),
    ]
    options = [stays(name, place) for name, place, _, _, _ in stops]
    options += [moves("water-taxi", "river", "pier"), moves("flight", "ohare", "home")]
    facts = [
        fact
        for name, _, hour, minute, length in stops
        for fact in (starts_at(name, hour, minute), lasts(name, length), cutoff(name, "PT0S"))
    ]
    facts += [
        starts_at("water-taxi", 12, 15),
        lasts("water-taxi", "PT20M"),
        cutoff("water-taxi", "PT0S"),
        takes("walk-to-museum", "PT20M"),
        takes("cab-to-river", "PT15M"),
        takes("walk-to-pier", "PT25M"),
        takes("cab-to-ohare", "PT50M"),
        *more,
        starts_at("flight", flight_at),
        lasts("flight", "PT2H30M"),
        cutoff("flight", "PT45M"),
    ]
    ways = [
        way_between("walk-to-museum", "hotel", "art-institute"),
        way_between("cab-to-river", "hotel", "river"),
        way_between("walk-to-pier", "art-institute", "pier"),
        way("cab-to-ohare", "pier", "ohare"),
    ]
    decisions = [
        lock("breakfast", *everyone),
        lock("museum-visit", "alex", "sam"),
        lock("boat-tour", "jo"),
        lock("lunch", *everyone),
        lock("flight", *everyone),
    ]
    places = ["hotel", "art-institute", "river", "pier", "ohare", "home"]
    return trip(list(everyone), places, options, facts, decisions, ways)


def test_the_compiler_plans_a_day_with_ways() -> None:
    file = a_day_on_foot()
    report = compiler.check(file)
    assert report.answer is Answer.FEASIBLE
    assert report.robust is True
    shown = together(report.itinerary)
    assert [(step.option or step.way, step.persons, step.start) for step in shown] == [
        ("breakfast", ("alex", "sam", "jo"), seconds(8)),
        ("walk-to-museum", ("alex", "sam"), seconds(9)),
        ("cab-to-river", ("jo",), seconds(9)),
        ("museum-visit", ("alex", "sam"), seconds(10)),
        ("boat-tour", ("jo",), seconds(10, 30)),
        ("walk-to-pier", ("alex", "sam"), seconds(12)),
        ("water-taxi", ("jo",), seconds(12, 15)),
        ("lunch", ("alex", "sam", "jo"), seconds(13)),
        ("cab-to-ohare", ("alex", "sam", "jo"), seconds(14)),
        ("flight", ("alex", "sam", "jo"), seconds(17)),
    ]
    assert reference.broken(file, worst_case(file), report.itinerary) == []


def test_the_compiler_names_what_is_missing_from_a_day_with_ways() -> None:
    file = a_day_on_foot(flight_at=15)
    report = compiler.check(file)
    another = Unknown("other ways", origin="pier", destination="ohare")
    assert report.missing == ((Missing(another, at_most=15 * 60),),)


def test_the_compiler_names_the_conflict_in_a_day_with_ways() -> None:
    file = a_day_on_foot(complete(None, "ohare"), flight_at=15)
    report = compiler.check(file)
    assert report.answer is Answer.INFEASIBLE
    assert report.conflict == (
        "lunch-time",
        "lunch-length",
        "cab-to-ohare-length",
        "ways-to-ohare",
        "flight-time",
        "flight-cutoff",
        "lock-lunch",
        "lock-flight",
    )


def test_two_quick_ways_are_taken_where_one_slow_way_is_too_late() -> None:
    """The walk to the gallery takes seventy minutes. Through the station it takes ten."""
    file = a_morning(
        *WALKS,
        way_between("to-station", "hotel", "station"),
        way_between("from-station", "station", "gallery"),
        more=[
            takes("walk-to-gallery", "PT1H10M"),
            takes("walk-to-cafe", "PT10M"),
            takes("to-station", "PT5M"),
            takes("from-station", "PT5M"),
        ],
    )
    report = compiler.check(file)
    assert report == answers.check(file)
    ways = [step.way for step in together(report.itinerary) if step.way]
    assert ways[:2] == ["to-station", "from-station"]


def test_the_tie_break_counts_exactly_with_many_options() -> None:
    """Fifty-four OPTIONs: one more than the whole numbers a floating-point number can hold."""
    count = 54
    last = f"o{count - 1}"
    file = trip(
        ["alex"],
        ["a"],
        [stays(f"o{index}", "a") for index in range(count)],
        [starts_at("o0", 9), lasts("o0", "PT0S"), starts_at(last, 10), lasts(last, "PT0S")],
        [lock("o0", "alex"), lock(last, "alex")],
    )
    report = compiler.check(file)
    assert report.answer is Answer.FEASIBLE
    assert report.robust is True
    assert [step.option for step in report.itinerary] == ["o0", last]


def test_a_choice_is_scheduled_only_if_it_meets_every_constraint() -> None:
    """The check that every choice of the solver goes through covers all six CONSTRAINTs."""
    file = trip(
        ["alex"],
        ["a"],
        [stays("dinner", "a"), stays("show", "a")],
        [starts_at("dinner", 19), lasts("dinner", "PT1H"), lasts("show", "PT1H")],
        [lock("dinner", "alex")],
    )
    world = worst_case(file)
    assert reference.scheduled(file, world, (("alex",), ()), ((0,),)) is not None
    # Nobody takes part, so the LOCK is not honored.
    assert reference.scheduled(file, world, ((), ()), ((),)) is None
    # The show has no stated start, so in the worst case it cannot be used.
    assert reference.scheduled(file, world, (("alex",), ("alex",)), ((0, 1),)) is None


def test_the_compiler_agrees_where_a_stop_nobody_needs_is_listed() -> None:
    """The solver leaves out a stop that no LOCK asks for. That must never change the answer."""
    files = [a_ride_there_and_back(), a_ride_there_and_back(stays("pause", "b"))]
    files += [lunch_away_from_the_museum(), lunch_away_from_the_museum(complete(None, "ohare"))]
    for file in files:
        assert compiler.check(file) == answers.check(file)


def test_the_compiler_keeps_each_use_of_a_way_apart() -> None:
    """Two PERSONs take one WAY at one instant in opposite orders, and both checkers agree."""
    file = two_who_swap_places()
    report = compiler.check(file)
    assert report == answers.check(file)
    assert reference.broken(file, longest_case(file), report.itinerary) == []


def between_two_stops(*spans: tuple[tuple[int, int], tuple[int, int]], arrive: int) -> File:
    """Alex is at a at 9:00 and at b at a later hour. Every way from a to b is listed, for spans.

    Each span runs from one hour and minute to another, and the FILE lists no WAY at all.
    """
    ways = [
        {
            "id": f"ways-{number}",
            "complete": {
                "from": "a",
                "to": "b",
                "leaving": {"earliest": at(*first), "latest": at(*last)},
            },
        }
        for number, (first, last) in enumerate(spans)
    ]
    return stops(("first", "a", 9, 0), ("last", "b", arrive, 0), more=ways)


def test_complete_facts_that_overlap_rule_out_one_span() -> None:
    """Sixteen FACTs cover 8:00 to some minute after 10:00. Together they cover 8:00 to 10:16."""
    file = between_two_stops(*(((8, 0), (10, minute)) for minute in range(1, 17)), arrive=11)
    other_ways = Unknown("other ways", origin="a", destination="b")
    after_the_last_span = 44 * 60 - 1
    report = compiler.check(file)
    assert report.missing == ((Missing(other_ways, at_most=after_the_last_span),),)
    assert report == answers.check(file)


def test_an_unlisted_way_can_leave_in_the_opening_between_two_spans() -> None:
    """The FACTs cover 8:00 to 9:30 and 9:40 to 10:30. Alex must be at b by 10:00."""
    file = between_two_stops(((8, 0), (9, 30)), ((9, 40), (10, 30)), arrive=10)
    other_ways = Unknown("other ways", origin="a", destination="b")
    report = compiler.check(file)
    assert report.missing == ((Missing(other_ways, at_most=30 * 60 - 1),),)
    assert report == answers.check(file)
    # With no opening, a WAY straight from a to b is no help. Only a way round through c or d is.
    shut = between_two_stops(((8, 0), (9, 30)), ((9, 30), (10, 30)), arrive=10)
    report = compiler.check(shut)
    assert report == answers.check(shut)
    assert [len(enough) for enough in report.missing] == [2, 2]
    assert all(other_ways not in [needed.unknown for needed in enough] for enough in report.missing)


def test_the_two_checkers_agree_on_a_group_that_splits_up_and_meets_again() -> None:
    """The same Report for three PERSONs who do two things apart and one thing together."""
    rng = Random(15)
    seen: set[Answer] = set()
    for _ in range(30):
        file = a_group_that_meets(rng)
        report = compiler.check(file)
        assert report == answers.check(file)
        if report.answer is Answer.FEASIBLE:
            shown = tuple(together(report.itinerary))
            assert reference.works_as_listed(file, worst_case(file), shown)
        seen.add(report.answer)
    assert seen == set(Answer)


def test_a_plan_may_cross_a_night_that_the_file_says_nothing_about() -> None:
    """Dinner on Friday and breakfast on Saturday, with no night listed between them.

    The FILE asks for nothing overnight, so neither checker does. The plan has two steps.
    """
    friday_dinner = {"id": "dinner-time", "option": "dinner", "starts_at": at(19, 0, day=14)}
    file = trip(
        ["alex"],
        ["hotel"],
        [stays("dinner", "hotel"), stays("breakfast", "hotel")],
        [
            friday_dinner,
            lasts("dinner", "PT1H"),
            starts_at("breakfast", 8),
            lasts("breakfast", "PT45M"),
        ],
        [lock("dinner", "alex"), lock("breakfast", "alex")],
    )
    report = compiler.check(file)
    assert report == answers.check(file)
    assert report.answer is Answer.FEASIBLE
    assert [step.option for step in report.itinerary] == ["dinner", "breakfast"]
    assert report.itinerary[1].start - report.itinerary[0].start == 13 * 3600
