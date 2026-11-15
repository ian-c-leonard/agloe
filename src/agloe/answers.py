"""The three answers, ROBUST and the evidence, for any search.

``check`` follows the sections "The three answers", "ROBUST" and "Evidence" of spec/rules.md.
It asks a search three things: which ITINERARY is shown in a world, whether anything works in a
world, and which FACTs and DECISIONs rule out every ITINERARY. By default the search is the
reference checker's, which tries everything. The COMPILER passes its solver search instead, and
the answers and the evidence are worked out here in either case.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from itertools import combinations

from agloe.file import Complete, File, Start
from agloe.reference import (
    Broken,
    Itinerary,
    Unknown,
    World,
    any_works,
    best_case,
    broken_as_listed,
    first_shown,
    in_world,
    longest_case,
    unknowns,
    with_these_at_best,
    with_this_long,
    worst_case,
)


class Answer(Enum):
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    UNDETERMINED = "UNDETERMINED"


@dataclass(frozen=True)
class Missing:
    """An unknown FACT the answer depends on, and the most seconds it can be for a FEASIBLE TRIP."""

    unknown: Unknown
    at_most: int | None


@dataclass(frozen=True)
class Report:
    """The answer and its evidence.

    FEASIBLE: the ITINERARY shown, the FACTs and DECISIONs it relies on, whether it is ROBUST, and
    what it breaks when every CONTINGENT duration runs longest. INFEASIBLE: FACTs and DECISIONs
    that conflict. UNDETERMINED: each smallest set of unknown FACTs that would be enough.
    """

    answer: Answer
    itinerary: Itinerary = ()
    relies_on: tuple[str, ...] = ()
    robust: bool | None = None
    at_worst: tuple[Broken, ...] = ()
    conflict: tuple[str, ...] = ()
    missing: tuple[tuple[Missing, ...], ...] = ()


type Shown = Callable[[File, World], Itinerary | None]
type Works = Callable[[File, World], bool]
type Stuck = Callable[[File], frozenset[str] | None]


def check(
    file: File, shown: Shown = first_shown, works: Works = any_works, stuck: Stuck | None = None
) -> Report:
    """The answer for this TRIP, with its evidence.

    ``shown`` and ``works`` are how ITINERARIES are found. By default the reference checker tries
    every choice. A solver can stand in for that search. The answers and the evidence are worked
    out here in either case.

    ``stuck`` names FACTs and DECISIONs that rule out every ITINERARY by themselves, or None when
    one works in the best case. The set need not be small. A search that can name a small one
    saves most of the work of finding the conflict. Without it, every record counts.
    """
    if stuck is None:

        def every_record(given: File) -> frozenset[str] | None:
            if works(given, best_case(given)):
                return None
            return frozenset([fact.id for fact in given.facts] + [lock.id for lock in given.locks])

        stuck = every_record
    plain = shown(file, worst_case(file))
    if plain is not None:
        longest = longest_case(file)
        robust = shown(file, longest)
        chosen = plain if robust is None else robust
        used = {step.option or step.way for step in chosen}
        relies_on = [
            fact.id for fact in file.facts if not isinstance(fact, Complete) and fact.option in used
        ]
        relies_on += [lock.id for lock in file.locks]
        at_worst: tuple[Broken, ...] = ()
        if robust is None:
            # The steps keep the order the ITINERARY lists them in: that is the plan shown.
            at_worst = tuple(broken_as_listed(file, longest, in_world(longest, chosen)))
        return Report(Answer.FEASIBLE, chosen, tuple(relies_on), robust is not None, at_worst)
    enough = stuck(file)
    if enough is not None:
        return Report(Answer.INFEASIBLE, conflict=_conflict(file, stuck, enough))
    return Report(Answer.UNDETERMINED, missing=_missing(file, works))


def _conflict(file: File, stuck: Stuck, enough: frozenset[str]) -> tuple[str, ...]:
    """FACTs and DECISIONs that make the TRIP INFEASIBLE by themselves; none can be removed.

    It goes through the records in the FILE's order and removes each one that the TRIP stays
    INFEASIBLE without. ``enough`` is a set of records known to make the TRIP INFEASIBLE by
    themselves. A record outside it can go without another search: what is left still holds all
    of ``enough``, and more records never make a TRIP easier.
    """
    kept = file
    skipped = False
    for record in [fact.id for fact in file.facts] + [lock.id for lock in file.locks]:
        without = kept.without(record)
        if record not in enough:
            kept, skipped = without, True
            continue
        smaller = stuck(without)
        if smaller is not None:
            kept, enough = without, smaller
    if skipped and stuck(kept) is None:
        raise AssertionError("records said to rule out every ITINERARY do not")
    return tuple([fact.id for fact in kept.facts] + [lock.id for lock in kept.locks])


def _missing(file: File, works: Works) -> tuple[tuple[Missing, ...], ...]:
    """Every smallest set of unknown FACTs that would be enough if they turned out well.

    Each set makes the TRIP FEASIBLE with every other unknown FACT at its worst. A set of one
    length of time comes with its limit.
    """
    every = unknowns(file)
    for size in range(1, len(every) + 1):
        enough = [
            some
            for some in combinations(every, size)
            if works(file, with_these_at_best(file, some))
        ]
        if enough:
            return tuple(
                tuple(Missing(u, _limit(file, u, works) if size == 1 else None) for u in some)
                for some in enough
            )
    raise AssertionError("the best case works, so some unknown FACTs make it work")


def _limit(file: File, unknown: Unknown, works: Works) -> int | None:
    """The most seconds this one unknown can be for the TRIP to work.

    None for an unknown start, and None when any length of time would do.
    """
    if unknown.what == "start":
        return None

    def enough(seconds: int) -> bool:
        return works(file, with_this_long(file, unknown, seconds))

    # Only two fixed times can limit a length of time: it must fit between them. So a length
    # longer than the time between the earliest and the latest fixed time has no limit.
    fixed = [fact.at for fact in file.facts if isinstance(fact, Start) and fact.at is not None]
    for fact in file.facts:
        if isinstance(fact, Complete):
            fixed += [fact.earliest - 1, fact.latest + 1]
    under, over = 0, max(fixed) - min(fixed) + 1 if fixed else 1
    if enough(over):
        return None
    while over - under > 1:
        middle = (under + over) // 2
        under, over = (middle, over) if enough(middle) else (under, middle)
    return under
