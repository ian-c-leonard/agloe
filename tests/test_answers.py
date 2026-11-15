"""The three answers, ROBUST, the ITINERARY shown and the evidence, on small TRIPs."""

from dataclasses import replace

from agloe.file import File, load
from agloe.reference import (
    Answer,
    Broken,
    Constraint,
    Missing,
    Step,
    Unknown,
    World,
    broken,
    check,
    in_world,
    itineraries,
    worst_case,
)
from tests.stories import (
    any_time,
    at,
    complete,
    cutoff,
    flight_home,
    lasts,
    lasts_between,
    lock,
    moves,
    seconds,
    starts_at,
    stays,
    trip,
    without,
)

MORNING = [
    stays("breakfast", "hotel"),
    moves("walk", "hotel", "office"),
    stays("meeting", "office"),
]
MORNING_FACTS = [
    starts_at("breakfast", 8),
    lasts("breakfast", "PT1H"),
    any_time("walk"),
    starts_at("meeting", 10),
    lasts("meeting", "PT30M"),
]
MORNING_LOCKS = [lock("breakfast", "alex"), lock("meeting", "alex")]


def test_an_unrecorded_duration_is_not_a_choice() -> None:
    """Nobody recorded how long the walk takes, so the COMPILER does not pick a length.

    Either of two unknown FACTs would be enough: a short walk, or another way to the office.
    """
    facts = [*MORNING_FACTS, cutoff("meeting", "PT0S")]
    report = check(trip(["alex"], ["hotel", "office"], MORNING, facts, MORNING_LOCKS))
    assert report.answer is Answer.UNDETERMINED
    another = Unknown("other ways", origin="hotel", destination="office")
    assert report.missing == (
        (Missing(Unknown("duration", "walk"), at_most=3600),),
        (Missing(another, at_most=3600),),
    )


def test_two_unknown_facts_can_both_matter() -> None:
    report = check(trip(["alex"], ["hotel", "office"], MORNING, MORNING_FACTS, MORNING_LOCKS))
    assert report.answer is Answer.UNDETERMINED
    another = Unknown("other ways", origin="hotel", destination="office")
    assert report.missing == (
        (
            Missing(Unknown("duration", "walk"), at_most=None),
            Missing(Unknown("cutoff", "meeting"), at_most=None),
        ),
        (
            Missing(Unknown("cutoff", "meeting"), at_most=None),
            Missing(another, at_most=None),
        ),
    )


def test_each_unknown_fact_that_would_be_enough_is_named() -> None:
    """A cab and a bus both go to the office, and nobody recorded how long either takes."""
    options = [*MORNING[:1], moves("cab", "hotel", "office"), moves("bus", "hotel", "office")]
    facts = [
        starts_at("breakfast", 8),
        lasts("breakfast", "PT1H"),
        any_time("cab"),
        any_time("bus"),
        starts_at("meeting", 10),
        lasts("meeting", "PT30M"),
        cutoff("meeting", "PT0S"),
        complete("hotel", "office"),
    ]
    file = trip(["alex"], ["hotel", "office"], [*options, MORNING[2]], facts, MORNING_LOCKS)
    report = check(file)
    assert report.answer is Answer.UNDETERMINED
    assert report.missing == (
        (Missing(Unknown("duration", "cab"), at_most=3600),),
        (Missing(Unknown("duration", "bus"), at_most=3600),),
    )


def test_a_limit_can_be_no_time_at_all() -> None:
    """Breakfast ends as the meeting starts, so the walk must take no time."""
    facts = [
        lasts("breakfast", "PT2H") if fact["id"] == "breakfast-length" else fact
        for fact in MORNING_FACTS
    ]
    file = trip(
        ["alex"],
        ["hotel", "office"],
        MORNING,
        [*facts, cutoff("meeting", "PT0S"), complete("hotel", "office")],
        MORNING_LOCKS,
    )
    report = check(file)
    assert report.missing == ((Missing(Unknown("duration", "walk"), at_most=0),),)


def test_a_limit_is_left_out_when_any_length_of_time_would_do() -> None:
    """The event can start at any time, so it can wait out any access cutoff.

    Nobody recorded the cutoff, though, so no start time can be fixed now. A way back to a would
    be enough too: Alex could then go to the event first.
    """
    file = trip(
        ["alex"],
        ["a", "b"],
        [moves("ride", "a", "b"), stays("event", "b")],
        [
            starts_at("ride", 9),
            lasts("ride", "PT0S"),
            cutoff("ride", "PT0S"),
            any_time("event"),
            lasts("event", "PT1H"),
        ],
        [lock("ride", "alex"), lock("event", "alex")],
    )
    report = check(file)
    assert report.answer is Answer.UNDETERMINED
    assert report.missing == (
        (Missing(Unknown("cutoff", "event"), at_most=None),),
        (Missing(Unknown("other ways", origin="b", destination="a"), at_most=None),),
    )


def test_other_ways_are_as_many_as_the_persons_need() -> None:
    """Alex must go from a to b twice, with a listed ride back in between.

    The evidence names other ways from a to b. One more listed OPTION is not enough, because an
    OPTION happens once. Two are.
    """

    def with_ways(count: int) -> File:
        ways = [moves(f"way-{number}", "a", "b") for number in range(count)]
        return trip(
            ["alex"],
            ["a", "b"],
            [stays("first", "a"), moves("back", "b", "a"), stays("last", "b"), *ways],
            [
                starts_at("first", 9),
                lasts("first", "PT0S"),
                starts_at("back", 10),
                lasts("back", "PT0S"),
                cutoff("back", "PT0S"),
                starts_at("last", 11),
                cutoff("last", "PT0S"),
                *(
                    fact
                    for way in ways
                    for fact in (
                        any_time(way["id"]),
                        lasts(way["id"], "PT0S"),
                        cutoff(way["id"], "PT0S"),
                    )
                ),
            ],
            [lock("first", "alex"), lock("back", "alex"), lock("last", "alex")],
        )

    others = Unknown("other ways", origin="a", destination="b")
    assert check(with_ways(0)).missing == ((Missing(others, at_most=3600),),)
    assert check(with_ways(1)).missing == ((Missing(others, at_most=3600),),)
    assert check(with_ways(2)).answer is Answer.FEASIBLE


def test_an_unrecorded_start_is_not_a_choice() -> None:
    file = trip(
        ["alex"],
        ["hotel"],
        [stays("dinner", "hotel")],
        [lasts("dinner", "PT1H")],
        [lock("dinner", "alex")],
    )
    report = check(file)
    assert report.answer is Answer.UNDETERMINED
    assert report.missing == ((Missing(Unknown("start", "dinner"), at_most=None),),)


def test_an_unrecorded_cutoff_matters_to_someone_who_travels() -> None:
    """With no FACT about bag drop, it works only if bag drop closes at most an hour before."""
    report = check(load(without(flight_home(), "bag-drop")))
    assert report.answer is Answer.UNDETERMINED
    assert report.missing == ((Missing(Unknown("cutoff", "flight"), at_most=3600),),)


def test_an_unrecorded_duration_does_not_matter_when_nothing_follows() -> None:
    report = check(load(without(flight_home(), "flight-length")))
    assert report.answer is Answer.FEASIBLE
    assert report.itinerary[-1].option == "flight"
    assert report.itinerary[-1].end is None
    assert "flight-length" not in report.relies_on


def test_being_in_two_places_at_once_needs_no_complete_fact() -> None:
    file = trip(
        ["alex"],
        ["museum", "theater"],
        [stays("visit", "museum"), stays("show", "theater")],
        [
            starts_at("visit", 14),
            lasts("visit", "PT1H"),
            starts_at("show", 14, 30),
            lasts("show", "PT1H"),
        ],
        [lock("visit", "alex"), lock("show", "alex")],
    )
    report = check(file)
    assert report.answer is Answer.INFEASIBLE
    assert report.conflict == ("visit-time", "visit-length", "show-time", "lock-visit", "lock-show")


def test_listed_options_join_up() -> None:
    file = trip(
        ["alex"],
        ["a", "b", "c"],
        [
            stays("pack", "a"),
            moves("first-leg", "a", "b"),
            moves("second-leg", "b", "c"),
            stays("meeting", "c"),
        ],
        [
            starts_at("pack", 9),
            lasts("pack", "PT0S"),
            any_time("first-leg"),
            lasts("first-leg", "PT1M"),
            any_time("second-leg"),
            lasts("second-leg", "PT1M"),
            cutoff("second-leg", "PT0S"),
            starts_at("meeting", 9, 3),
            lasts("meeting", "PT10M"),
            cutoff("meeting", "PT0S"),
        ],
        [lock("pack", "alex"), lock("meeting", "alex")],
    )
    report = check(file)
    assert report.answer is Answer.FEASIBLE
    assert [(step.option, step.start) for step in report.itinerary] == [
        ("pack", seconds(9)),
        ("first-leg", seconds(9)),
        ("second-leg", seconds(9, 1)),
        ("meeting", seconds(9, 3)),
    ]


def test_an_option_nobody_needs_changes_nothing() -> None:
    document = flight_home()
    document["options"].append(stays("night-tour", "home"))
    document["facts"] += [starts_at("night-tour", 3), lasts("night-tour", "PT9H")]
    assert check(load(document)) == check(load(flight_home()))


def test_only_those_who_need_an_option_take_part() -> None:
    document = flight_home()
    document["decisions"][1]["persons"] = ["alex"]
    report = check(load(document))
    assert report.answer is Answer.FEASIBLE
    assert [(step.option, step.persons) for step in report.itinerary] == [
        ("museum-visit", ("alex", "sam")),
        ("blue-line", ("alex",)),
        ("flight", ("alex",)),
    ]


def with_a_cab_listed_first(length: dict[str, object]) -> dict[str, object]:
    document = flight_home()
    document["options"].insert(0, moves("cab", "art-institute", "ohare"))
    document["facts"] += [any_time("cab"), length]
    return document


def test_the_itinerary_shown_uses_the_options_listed_first() -> None:
    report = check(load(with_a_cab_listed_first(lasts("cab", "PT30M"))))
    assert [step.option for step in report.itinerary] == ["museum-visit", "cab", "flight"]
    assert report.robust is True


def test_a_person_takes_the_option_listed_first() -> None:
    """Two shuttles run to the airport, and each already has a rider. Alex can take either."""

    def with_shuttles(*shuttles: str) -> File:
        return trip(
            ["alex", "carol", "dave"],
            ["hotel", "airport"],
            [
                stays("breakfast", "hotel"),
                *(moves(shuttle, "hotel", "airport") for shuttle in shuttles),
                stays("check-in", "airport"),
            ],
            [
                starts_at("breakfast", 8),
                lasts("breakfast", "PT30M"),
                starts_at("early-shuttle", 9),
                lasts("early-shuttle", "PT30M"),
                cutoff("early-shuttle", "PT0S"),
                starts_at("late-shuttle", 10),
                lasts("late-shuttle", "PT30M"),
                cutoff("late-shuttle", "PT0S"),
                starts_at("check-in", 11),
                lasts("check-in", "PT10M"),
                cutoff("check-in", "PT0S"),
            ],
            [
                lock("breakfast", "alex"),
                lock("check-in", "alex"),
                lock("early-shuttle", "carol"),
                lock("late-shuttle", "dave"),
            ],
        )

    def riders(file: File) -> dict[str | None, tuple[str, ...]]:
        return {step.option: step.persons for step in check(file).itinerary}

    early_first = riders(with_shuttles("early-shuttle", "late-shuttle"))
    assert early_first["early-shuttle"] == ("alex", "carol")
    assert early_first["late-shuttle"] == ("dave",)
    late_first = riders(with_shuttles("late-shuttle", "early-shuttle"))
    assert late_first["late-shuttle"] == ("alex", "dave")
    assert late_first["early-shuttle"] == ("carol",)


def test_each_person_does_their_options_in_the_files_order_where_they_can() -> None:
    """Lunch and a call can happen at any time, in either order."""

    def in_order(*ids: str) -> list[str | None]:
        file = trip(
            ["alex"],
            ["hotel"],
            [stays(id, "hotel") for id in ids],
            [fact for id in ids for fact in (any_time(id), lasts(id, "PT30M"))],
            [lock(id, "alex") for id in ids],
        )
        return [step.option for step in check(file).itinerary]

    assert in_order("lunch", "call") == ["lunch", "call"]
    assert in_order("call", "lunch") == ["call", "lunch"]


def test_the_files_order_decides_before_the_clock_does() -> None:
    """An errand takes half an hour and fits before or after a 10:00 meeting at the same PLACE."""

    def starts(*ids: str) -> list[tuple[str | None, int]]:
        file = trip(
            ["alex"],
            ["office"],
            [stays(id, "office") for id in ids],
            [
                starts_at("meeting", 10),
                lasts("meeting", "PT30M"),
                any_time("errand"),
                lasts("errand", "PT30M"),
            ],
            [lock(id, "alex") for id in ids],
        )
        return [(step.option, step.start) for step in check(file).itinerary]

    assert starts("errand", "meeting") == [("errand", seconds(9, 30)), ("meeting", seconds(10))]
    assert starts("meeting", "errand") == [("meeting", seconds(10)), ("errand", seconds(10, 30))]


def test_a_robust_itinerary_is_shown_before_any_other() -> None:
    """The cab is listed first but can take 90 minutes. The train always makes it."""
    report = check(load(with_a_cab_listed_first(lasts_between("cab", "PT30M", "PT1H30M"))))
    assert report.answer is Answer.FEASIBLE
    assert [step.option for step in report.itinerary] == ["museum-visit", "blue-line", "flight"]
    assert report.robust is True
    assert report.at_worst == ()


def test_a_robust_itinerary_allows_for_the_longest_durations() -> None:
    document = flight_home()
    document["facts"][3] = lasts_between("blue-line", "PT50M", "PT1H10M")
    document["facts"][3]["id"] = "train-length"
    report = check(load(document))
    assert report.robust is True
    train = report.itinerary[1]
    assert (train.start, train.end) == (seconds(15), seconds(16, 10))


def test_a_trip_with_no_fixed_time_still_has_an_order() -> None:
    file = trip(
        ["alex"],
        ["a", "b"],
        [stays("pack", "a"), moves("ride", "a", "b")],
        [any_time("pack"), lasts("pack", "PT30M"), any_time("ride"), lasts("ride", "PT1H")],
        [lock("pack", "alex"), lock("ride", "alex")],
    )
    report = check(file)
    assert report.answer is Answer.FEASIBLE
    assert [(step.option, step.start, step.end) for step in report.itinerary] == [
        ("pack", 0, 1800),
        ("ride", 1800, 5400),
    ]


def test_an_option_before_a_fixed_time_starts_as_late_as_it_can() -> None:
    file = trip(
        ["alex"],
        ["hotel", "office"],
        [moves("walk", "hotel", "office"), stays("meeting", "office")],
        [
            any_time("walk"),
            lasts("walk", "PT20M"),
            starts_at("meeting", 10),
            lasts("meeting", "PT30M"),
            cutoff("meeting", "PT10M"),
        ],
        [lock("meeting", "alex"), lock("walk", "alex")],
    )
    report = check(file)
    assert [(step.option, step.start) for step in report.itinerary] == [
        ("walk", seconds(9, 30)),
        ("meeting", seconds(10)),
    ]


def test_a_complete_set_says_nothing_after_its_span() -> None:
    """The listed train is far too slow. An unlisted way that leaves after the span might exist."""
    document = flight_home()
    document["facts"][3] = lasts("blue-line", "PT5H")
    document["facts"][4] = starts_at("flight", 19)
    ways = {
        "from": "art-institute",
        "to": "ohare",
        "leaving": {"earliest": at(12), "latest": at(16)},
    }
    document["facts"].append({"id": "ways-to-ohare", "complete": ways})
    report = check(load(document))
    assert report.answer is Answer.UNDETERMINED
    another = Unknown("other ways", origin="art-institute", destination="ohare")
    assert report.missing == ((Missing(another, at_most=2 * 3600 + 14 * 60 + 59),),)


def test_a_complete_set_says_nothing_before_its_span() -> None:
    """Packing can be done at any time, so Alex could leave before the span begins."""
    ways = {"from": "a", "to": "b", "leaving": {"earliest": at(9), "latest": at(10, 30)}}
    file = trip(
        ["alex"],
        ["a", "b"],
        [stays("pack", "a"), stays("meeting", "b")],
        [
            any_time("pack"),
            lasts("pack", "PT30M"),
            starts_at("meeting", 10),
            lasts("meeting", "PT1H"),
            cutoff("meeting", "PT0S"),
            {"id": "ways", "complete": ways},
        ],
        [lock("pack", "alex"), lock("meeting", "alex")],
    )
    report = check(file)
    assert report.answer is Answer.UNDETERMINED
    assert report.missing == ((Missing(Unknown("other ways", origin="a", destination="b"), None),),)


def test_a_complete_set_that_covers_every_leaving_time_makes_it_infeasible() -> None:
    ways = {"from": "a", "to": "b", "leaving": {"earliest": at(0), "latest": at(23, 59)}}
    file = trip(
        ["alex"],
        ["a", "b"],
        [stays("breakfast", "a"), stays("meeting", "b")],
        [
            starts_at("breakfast", 8),
            lasts("breakfast", "PT30M"),
            starts_at("meeting", 10),
            lasts("meeting", "PT1H"),
            cutoff("meeting", "PT0S"),
            {"id": "ways", "complete": ways},
        ],
        [lock("breakfast", "alex"), lock("meeting", "alex")],
    )
    report = check(file)
    assert report.answer is Answer.INFEASIBLE
    assert report.conflict == (
        "breakfast-time",
        "meeting-time",
        "ways",
        "lock-breakfast",
        "lock-meeting",
    )


def test_a_step_after_a_shared_step_takes_its_time_from_it() -> None:
    """Alex's meeting fixes when both finish packing. Sam's tram and nap follow from that."""
    file = trip(
        ["alex", "sam"],
        ["hotel", "office", "beach"],
        [
            stays("pack", "hotel"),
            moves("walk", "hotel", "office"),
            stays("meeting", "office"),
            moves("tram", "hotel", "beach"),
            stays("nap", "beach"),
        ],
        [
            any_time("pack"),
            lasts("pack", "PT30M"),
            any_time("walk"),
            lasts("walk", "PT15M"),
            starts_at("meeting", 10),
            lasts("meeting", "PT1H"),
            cutoff("meeting", "PT0S"),
            any_time("tram"),
            lasts("tram", "PT20M"),
            any_time("nap"),
            lasts("nap", "PT1H"),
            cutoff("nap", "PT0S"),
        ],
        [lock("pack", "alex", "sam"), lock("meeting", "alex"), lock("nap", "sam")],
    )
    report = check(file)
    assert report.answer is Answer.FEASIBLE
    assert [(step.option, step.persons, step.start) for step in report.itinerary] == [
        ("pack", ("alex", "sam"), seconds(9, 15)),
        ("walk", ("alex",), seconds(9, 45)),
        ("tram", ("sam",), seconds(9, 45)),
        ("meeting", ("alex",), seconds(10)),
        ("nap", ("sam",), seconds(10, 5)),
    ]


def there_and_back(*more: dict[str, object]) -> File:
    """Alex must ride from a to b at 9:00 and be at b for an event at 9:00 that takes no time.

    A ride back leaves b at 9:00 and takes no time. Whether Alex needs it depends on how long the
    first ride takes.
    """
    return trip(
        ["alex"],
        ["a", "b"],
        [moves("ride", "a", "b"), stays("event", "b"), moves("back", "b", "a")],
        [
            starts_at("ride", 9),
            cutoff("ride", "PT0S"),
            *more,
            starts_at("event", 9),
            lasts("event", "PT0S"),
            cutoff("event", "PT0S"),
            starts_at("back", 9),
            lasts("back", "PT0S"),
        ],
        [lock("ride", "alex"), lock("event", "alex")],
    )


def when_it_takes(file: File, option: str, time: int) -> World:
    """The worst case, except that this OPTION takes exactly this many seconds."""
    world = worst_case(file)
    terms = {**world.terms, option: replace(world.terms[option], shortest=time, longest=time)}
    return replace(world, terms=terms)


def test_an_option_can_be_there_for_the_possible_worlds_that_need_it() -> None:
    """If the ride takes any time at all, Alex must do the event first and ride back to a.

    If it takes no time, the ride back is not needed, but taking it does no harm. So one choice
    of OPTIONs and start times works however long the ride takes.
    """
    file = there_and_back()
    report = check(file)
    assert report.answer is Answer.FEASIBLE
    assert [(step.option, step.end) for step in report.itinerary] == [
        ("ride", None),
        ("event", seconds(9)),
        ("back", seconds(9)),
    ]
    for time in (0, 60, 86400):
        world = when_it_takes(file, "ride", time)
        assert broken(file, world, in_world(world, report.itinerary)) == []
    without_the_ride_back = report.itinerary[:2]
    world = when_it_takes(file, "ride", 60)
    assert broken(file, world, in_world(world, without_the_ride_back)) != []


def test_a_robust_itinerary_works_at_the_shortest_durations_too() -> None:
    file = there_and_back(lasts_between("ride", "PT0S", "PT1M"))
    report = check(file)
    assert report.answer is Answer.FEASIBLE
    assert report.robust is True
    assert [step.option for step in report.itinerary] == ["ride", "event", "back"]
    for time in (0, 30, 60):
        world = when_it_takes(file, "ride", time)
        assert broken(file, world, in_world(world, report.itinerary)) == []


def test_a_warning_names_only_what_the_longest_durations_break() -> None:
    """The ride can take two hours, and the event at b starts an hour after the ride leaves.

    Nobody recorded how long the event takes. That is not part of the WARNING.
    """
    file = trip(
        ["alex"],
        ["a", "b"],
        [moves("ride", "a", "b"), stays("event", "b")],
        [
            starts_at("ride", 9),
            lasts_between("ride", "PT0S", "PT2H"),
            cutoff("ride", "PT0S"),
            starts_at("event", 10),
            cutoff("event", "PT0S"),
        ],
        [lock("ride", "alex"), lock("event", "alex")],
    )
    report = check(file)
    assert report.answer is Answer.FEASIBLE
    assert report.robust is False
    assert report.at_worst == (Broken(Constraint.PLACE, "event", ("alex",), late=3600),)


def test_unlisted_options_join_up_one_after_another() -> None:
    """Alex must be at a at 9:00 and at c at 10:00. Unlisted OPTIONs join a to b and b to c."""
    file = trip(
        ["alex"],
        ["a", "b", "c"],
        [stays("first", "a"), stays("last", "c")],
        [
            starts_at("first", 9),
            lasts("first", "PT0S"),
            cutoff("first", "PT0S"),
            starts_at("last", 10),
            lasts("last", "PT0S"),
            cutoff("last", "PT0S"),
        ],
        [lock("first", "alex"), lock("last", "alex")],
    )
    world = World(worst_case(file).terms, frozenset({("a", "b"), ("b", "c")}))
    two_legs = (
        Step("first", "a", "a", ("alex",), seconds(9), seconds(9)),
        Step(None, "a", "b", ("alex",), seconds(9, 20), seconds(9, 20)),
        Step(None, "b", "c", ("alex",), seconds(9, 40), seconds(9, 40)),
        Step("last", "c", "c", ("alex",), seconds(10), seconds(10)),
    )
    assert broken(file, world, two_legs) == []
    assert [
        (step.option, step.origin, step.destination) for step in itineraries(file, world)[0]
    ] == [
        ("first", "a", "a"),
        (None, "a", "b"),
        (None, "b", "c"),
        ("last", "c", "c"),
    ]
    assert itineraries(file, World(world.terms, frozenset({("a", "b")}))) == []


def test_a_way_through_another_place_is_not_a_direct_way() -> None:
    """Alex must get from a to c, and Sam from b to c. Every way from a to b is listed: none.

    Unlisted OPTIONs from a to b and from b to c would not be enough. Alex would have to go
    through b, and the COMPLETE FACT rules that out.
    """
    file = trip(
        ["alex", "sam"],
        ["a", "b", "c"],
        [stays("first", "a"), stays("second", "b"), stays("last", "c")],
        [
            starts_at("first", 9),
            lasts("first", "PT0S"),
            starts_at("second", 9),
            lasts("second", "PT0S"),
            starts_at("last", 10),
            cutoff("last", "PT0S"),
            complete("a", "b"),
        ],
        [lock("first", "alex"), lock("second", "sam"), lock("last", "alex", "sam")],
    )
    report = check(file)
    assert report.answer is Answer.UNDETERMINED

    def way(origin: str, destination: str) -> Missing:
        return Missing(Unknown("other ways", origin=origin, destination=destination), None)

    assert report.missing == (
        (way("a", "c"), way("b", "a")),
        (way("a", "c"), way("b", "c")),
    )


def test_a_free_option_takes_its_time_from_what_comes_before_it() -> None:
    """The meeting is ten seconds before 1970. Sam's nap follows the ride they share."""
    before_1970 = {
        "id": "meeting-time",
        "option": "meeting",
        "starts_at": "1969-12-31T23:59:50+00:00[UTC]",
    }
    file = trip(
        ["alex", "sam"],
        ["a", "b"],
        [moves("ride", "a", "b"), stays("meeting", "b"), stays("nap", "b")],
        [
            any_time("ride"),
            lasts("ride", "PT0S"),
            before_1970,
            lasts("meeting", "PT0S"),
            cutoff("meeting", "PT0S"),
            any_time("nap"),
            lasts("nap", "PT0S"),
            cutoff("nap", "PT0S"),
        ],
        [lock("ride", "alex", "sam"), lock("meeting", "alex"), lock("nap", "sam")],
    )
    report = check(file)
    assert [(step.option, step.start) for step in report.itinerary] == [
        ("ride", -10),
        ("meeting", -10),
        ("nap", -10),
    ]


def test_a_free_option_before_a_timed_one_starts_as_late_as_it_can() -> None:
    """Alex's meeting times the packing, and the packing times Sam's tram and nap.

    Jo stretches on the beach before sharing the nap. The stretch has nothing before it, so it
    starts as late as the nap allows.
    """
    file = trip(
        ["alex", "sam", "jo"],
        ["hotel", "office", "beach"],
        [
            stays("pack", "hotel"),
            moves("walk", "hotel", "office"),
            stays("meeting", "office"),
            moves("tram", "hotel", "beach"),
            stays("stretch", "beach"),
            stays("nap", "beach"),
        ],
        [
            any_time("pack"),
            lasts("pack", "PT30M"),
            any_time("walk"),
            lasts("walk", "PT15M"),
            starts_at("meeting", 10),
            lasts("meeting", "PT1H"),
            cutoff("meeting", "PT0S"),
            any_time("tram"),
            lasts("tram", "PT20M"),
            any_time("stretch"),
            lasts("stretch", "PT10M"),
            any_time("nap"),
            lasts("nap", "PT1H"),
            cutoff("nap", "PT0S"),
        ],
        [
            lock("pack", "alex", "sam"),
            lock("meeting", "alex"),
            lock("stretch", "jo"),
            lock("nap", "sam", "jo"),
        ],
    )
    report = check(file)
    assert [(step.option, step.start) for step in report.itinerary] == [
        ("pack", seconds(9, 15)),
        ("walk", seconds(9, 45)),
        ("tram", seconds(9, 45)),
        ("stretch", seconds(9, 55)),
        ("meeting", seconds(10)),
        ("nap", seconds(10, 5)),
    ]


def test_options_at_one_instant_happen_in_one_order_for_everyone() -> None:
    """Two rides take no time and leave at 9:30: one from a to b, one from b to a.

    Alex starts at a and Sam at b, and both must take both rides. Alex would need the ride to b
    first, and Sam the ride to a first. No single order works for both.
    """

    def with_riders(*riders: str) -> File:
        return trip(
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
                complete("a", "b"),
                complete("b", "a"),
            ],
            [
                lock("first", "alex"),
                lock("second", "sam"),
                lock("out", *riders),
                lock("back", *riders),
            ],
        )

    assert check(with_riders("alex")).answer is Answer.FEASIBLE
    assert check(with_riders("sam")).answer is Answer.FEASIBLE
    report = check(with_riders("alex", "sam"))
    assert report.answer is Answer.INFEASIBLE
    assert report.conflict == (
        "first-time",
        "second-time",
        "out-time",
        "back-time",
        "ways-a-b",
        "ways-b-a",
        "lock-first",
        "lock-second",
        "lock-out",
        "lock-back",
    )


def test_an_empty_file_is_feasible() -> None:
    report = check(load({"persons": [], "places": [], "options": [], "facts": [], "decisions": []}))
    assert report.answer is Answer.FEASIBLE
    assert report.itinerary == ()
