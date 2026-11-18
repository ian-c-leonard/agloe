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

from agloe.file import Complete, CompleteFor, Fact, File, Lock, Start
from agloe.reference import (
    Broken,
    Itinerary,
    Remaining,
    Unknown,
    World,
    any_works,
    best_cases,
    broken_as_listed,
    first_shown,
    in_world,
    longest_case,
    no_better_than,
    one_way_each,
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

    FEASIBLE: the ITINERARY shown, the FACTs, WANTs and DECISIONs it relies on, whether it is
    ROBUST, and what it breaks when every CONTINGENT duration runs longest. INFEASIBLE: FACTs and
    DECISIONs that conflict. UNDETERMINED: each smallest set of unknown FACTs that would be enough.
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
type Stuck = Callable[[Remaining], frozenset[str] | None]


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

        def every_record(given: Remaining) -> frozenset[str] | None:
            if any(works(given.file, world) for world in best_cases(given)):
                return None
            return frozenset(_records(given.file))

        stuck = every_record
    plain = shown(file, worst_case(file))
    if plain is not None:
        longest = longest_case(file)
        robust = shown(file, longest)
        chosen = plain if robust is None else robust
        relies_on = [fact.id for fact in file.facts if _relied_on(file, chosen, fact)]
        relies_on += [want.id for want in file.wants if want.musts or want.must_nots]
        relies_on += [each.id for each in file.decisions if isinstance(each, Lock) or chosen]
        at_worst: tuple[Broken, ...] = ()
        if robust is None:
            # The steps keep the order the ITINERARY lists them in: that is the plan shown.
            at_worst = tuple(broken_as_listed(file, longest, in_world(longest, chosen)))
        return Report(Answer.FEASIBLE, chosen, tuple(relies_on), robust is not None, at_worst)
    enough = stuck(Remaining(file))
    if enough is not None:
        return Report(Answer.INFEASIBLE, conflict=_conflict(file, stuck, enough))
    return Report(Answer.UNDETERMINED, missing=_missing(file, works))


def _relied_on(file: File, itinerary: Itinerary, fact: Fact) -> bool:
    """Whether a plan relies on this FACT.

    It relies on every FACT about an OPTION or a WAY it has in it. It relies on no COMPLETE set
    of travel: it takes no unlisted WAY.
    """
    if isinstance(fact, CompleteFor):
        return _settles(file, itinerary, fact)
    if isinstance(fact, Complete):
        return False
    return fact.option in {step.option or step.way for step in itinerary}


def _settles(file: File, itinerary: Itinerary, whole: CompleteFor) -> bool:
    """Whether this ITINERARY relies on the FACT that a WANT's set is COMPLETE.

    It does where a PERSON for whom the WANT is a must-not takes part in an OPTION with no FACT
    about the WANT. Only the COMPLETE set says that such an OPTION does not SATISFY it.
    """
    held_back = next(set(want.must_nots) for want in file.wants if want.id == whole.want)
    return any(
        step.option is not None
        and file.satisfies(step.option, whole.want) is None
        and held_back.intersection(step.persons)
        for step in itinerary
    )


def _conflict(file: File, stuck: Stuck, enough: frozenset[str]) -> tuple[str, ...]:
    """FACTs and DECISIONs that make the TRIP INFEASIBLE by themselves; none can be removed.

    It goes through the records in the FILE's order and removes each one that the TRIP stays
    INFEASIBLE without. ``enough`` is a set of records known to make the TRIP INFEASIBLE by
    themselves. A record outside it can go without another search: what is left still holds all
    of ``enough``, and one more record never lets an ITINERARY work in the best case that did
    not work without it. A FACT that is taken out is unknown, and the best case gives every
    unknown its most helpful value.
    """
    kept = Remaining(file)
    skipped = False
    for record in _records(file):
        without = kept.without(record)
        if record not in enough:
            kept, skipped = without, True
            continue
        smaller = stuck(without)
        if smaller is not None:
            kept, enough = without, smaller
    if skipped and stuck(kept) is None:
        raise AssertionError("records said to rule out every ITINERARY do not")
    return tuple(_records(kept.file))


def _records(file: File) -> list[str]:
    """The FACTs, then the WANTs that ask something of a PERSON, then the DECISIONs."""
    wants = [want.id for want in file.wants if want.musts or want.must_nots]
    return [*(fact.id for fact in file.facts), *wants, *(each.id for each in file.decisions)]


def _missing(file: File, works: Works) -> tuple[tuple[Missing, ...], ...]:
    """The sets of unknown FACTs that would be enough if they turned out well.

    Each set makes the TRIP FEASIBLE with every other unknown FACT at its worst. A set of one
    length of time comes with its limit.

    Which sets a report names is a choice, and the rules page states it. A report says first
    what to find out about the OPTIONs and WAYs the FILE lists. "Another OPTION is found for
    this WANT and this PERSON" asks for something new, and stands in for a listed OPTION and
    every FACT about it. So the sets returned ask for the fewest of those, and among them they
    have the fewest FACTs. The count is of WANTs and PERSONs, whichever OPTIONs are found.
    """
    every = unknowns(file)
    facts = [unknown for unknown in every if unknown.what != "another option"]
    to_find = [unknown for unknown in every if unknown.what == "another option"]
    for count in range(len(to_find) + 1):
        # Asking for these can be enough only if it is in the upper bound, where every FACT
        # helps whoever needs it. The bound only saves work: nothing is reported from it.
        hopeful = [
            some for some in combinations(to_find, count) if works(file, no_better_than(file, some))
        ]
        for size in range(len(facts) + 1 if hopeful else 0):
            enough = [
                (*stated, *some)
                for stated in combinations(facts, size)
                for some in hopeful
                if one_way_each(stated) and works(file, with_these_at_best(file, (*stated, *some)))
            ]
            if enough:
                alone = count + size == 1
                return tuple(
                    tuple(Missing(u, _limit(file, u, works) if alone else None) for u in some)
                    for some in enough
                )
    raise AssertionError("the best case works, so some unknown FACTs make it work")


def _limit(file: File, unknown: Unknown, works: Works) -> int | None:
    """The most seconds this one unknown can be for the TRIP to work.

    None for an unknown that is not a length of time, and None when any length would do.
    """
    if unknown.what in ("start", "satisfies", "does not satisfy", "another option"):
        return None

    def enough(seconds: int) -> bool:
        return works(file, with_this_long(file, unknown, seconds))

    # Only two fixed times can limit a length of time: it must fit between them. So a length
    # longer than the time between the earliest and the latest fixed time has no limit. The
    # times the TRIP starts and ends are fixed times too.
    fixed = [fact.at for fact in file.facts if isinstance(fact, Start) and fact.at is not None]
    fixed += [bound.at for bound in (file.trip_start(), file.trip_end()) if bound is not None]
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
