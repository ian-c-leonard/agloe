"""The three answers, ROBUST and the evidence, for any search.

``check`` follows the sections "The three answers", "ROBUST" and "Evidence" of spec/rules.md.
It asks a search three things: which ITINERARY is shown in a world, whether anything works in a
world, and which FACTs and DECISIONs rule out every ITINERARY. By default the search is the
reference checker's, which tries everything. The COMPILER passes its solver search instead, and
the answers and the evidence are worked out here in either case.
"""

from collections.abc import Callable, Iterable, Iterator, Sequence, Set
from dataclasses import dataclass
from enum import Enum
from itertools import combinations

from agloe.file import (
    Booking,
    Complete,
    CompleteFor,
    CompleteRights,
    Fact,
    File,
    Lock,
    Money,
    Offer,
    Start,
    StartsFrom,
)
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
    has_to_end_at,
    in_world,
    longest_case,
    no_better_than,
    one_way_each,
    placed,
    unknowns,
    with_no_offer,
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
class Cover:
    """What gives a PERSON their right to an OPTION in the plan shown.

    ``by`` is the id of a BOOKING, or of an OFFER from which the PERSON takes a place. A place
    is ``to_buy``: nothing secures it until a BOOKING does. It has a ``price``, and the
    ``budget`` that pays it. A price of nothing has no BUDGET.
    """

    option: str
    person: str
    by: str
    to_buy: bool
    price: Money | None = None
    budget: str | None = None


@dataclass(frozen=True)
class Report:
    """The answer and its evidence.

    FEASIBLE: the ITINERARY shown, the FACTs, WANTs and DECISIONs it relies on, whether it is
    ROBUST, what it breaks when every CONTINGENT duration runs longest, and what gives each
    PERSON their right to each OPTION that needs one or might. INFEASIBLE: FACTs and DECISIONs
    that conflict. UNDETERMINED: each smallest set of unknown FACTs that would be enough.
    """

    answer: Answer
    itinerary: Itinerary = ()
    relies_on: tuple[str, ...] = ()
    robust: bool | None = None
    at_worst: tuple[Broken, ...] = ()
    rights: tuple[Cover, ...] = ()
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
    worst = worst_case(file)
    plain = shown(file, worst)
    if plain is not None:
        longest = longest_case(file)
        # A ROBUST plan comes first, and then a plan that takes no place of an OFFER. The
        # OFFERs stay in the FILE for that: the plan only may not spend their places.
        better = [(longest, True)]
        if any(isinstance(fact, Offer) for fact in file.facts):
            better = [(with_no_offer(longest), True), *better, (with_no_offer(worst), False)]
        chosen, robust = plain, False
        for world, holds in better:
            found = shown(file, world)
            if found is not None:
                chosen, robust = found, holds
                break
        rights = _covers(file, worst, chosen)
        used = {cover.by for cover in rights}
        relies_on = [fact.id for fact in file.facts if _relied_on(file, chosen, fact, used)]
        relies_on += [want.id for want in file.wants if want.musts or want.must_nots]
        relies_on += [each.id for each in file.decisions if isinstance(each, Lock) or chosen]
        at_worst: tuple[Broken, ...] = ()
        if not robust:
            # The steps keep the order the ITINERARY lists them in: that is the plan shown.
            at_worst = tuple(broken_as_listed(file, longest, in_world(longest, chosen)))
        return Report(Answer.FEASIBLE, chosen, tuple(relies_on), robust, at_worst, rights)
    enough = stuck(Remaining(file))
    if enough is not None:
        return Report(Answer.INFEASIBLE, conflict=_conflict(file, stuck, enough))
    return Report(Answer.UNDETERMINED, missing=_missing(file, works))


def _relied_on(file: File, itinerary: Itinerary, fact: Fact, used: Set[str]) -> bool:
    """Whether a plan relies on this FACT.

    It relies on every FACT about an OPTION or a WAY it has in it. It relies on no COMPLETE set
    of travel: it takes no unlisted WAY. It relies on where a PERSON starts from where the
    PERSON is in it, or has to end the TRIP at a PLACE: their path begins there, or they stay
    there. It relies on the BOOKINGs and the OFFERs that give its PERSONs their rights:
    ``used`` holds those. It relies on no FACT that the rights to an OPTION are COMPLETE.
    """
    if isinstance(fact, CompleteFor):
        return _settles(file, itinerary, fact)
    if isinstance(fact, Booking | Offer):
        return fact.id in used
    if isinstance(fact, CompleteRights):
        return False
    if isinstance(fact, StartsFrom):
        in_it = any(fact.person in step.persons for step in itinerary)
        return in_it or bool(has_to_end_at(file, fact.person))
    if isinstance(fact, Complete):
        return False
    return fact.option in {step.option or step.way for step in itinerary}


def _covers(file: File, worst: World, itinerary: Itinerary) -> tuple[Cover, ...]:
    """What gives each PERSON in a plan their right to each of its OPTIONs.

    It leaves out an OPTION that a FACT says needs no right. A PERSON whom a BOOKING covers
    has the first such BOOKING in the FILE. The other PERSONs who take part take places of
    the OPTION's OFFERs that they can pay for, as ``placed`` shares them out, and each place
    is paid from the first BUDGET in the FILE that can pay it. The plan works in the worst
    case, which has no other right, so there is a place for each of them.
    """
    order = {person.id: number for number, person in enumerate(file.persons)}
    covers: list[Cover] = []
    for step in itinerary:
        if step.option is None or file.needs_right(step.option) is False:
            continue
        persons = sorted(step.persons, key=order.__getitem__)
        without = [person for person in persons if file.booking(step.option, person) is None]
        taken = placed(file, worst, step.option, without)
        offers = {offer.id: offer for offer in file.offers(step.option)}
        for person in persons:
            booked = file.booking(step.option, person)
            if booked is not None:
                covers.append(Cover(step.option, person, booked.id, False))
                continue
            price = offers[taken[person]].price
            payer = None if price is None else file.pays(person, price)
            budget = None if payer is None else payer.id
            covers.append(Cover(step.option, person, taken[person], True, price, budget))
    return tuple(covers)


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

    Every set holds the FACTs that a LOCK cannot be honored without, and enough rights for
    the PERSONs it names. So only sets that do are tried. A FILE that says little about its
    LOCKed OPTIONs needs many FACTs at once, and those are most of them.
    """
    every = unknowns(file)
    facts = [unknown for unknown in every if unknown.what != "another option"]
    to_find = [unknown for unknown in every if unknown.what == "another option"]
    place = {unknown: number for number, unknown in enumerate(facts)}
    in_every_set, at_least = _asked_by_a_lock(file)
    others = [unknown for unknown in facts if unknown not in in_every_set]
    fewest = len(in_every_set) + sum(number for _, number in at_least)
    for count in range(len(to_find) + 1):
        # Asking for these can be enough only if it is in the upper bound, where every FACT
        # helps whoever needs it. The bound only saves work: nothing is reported from it.
        hopeful = [
            some for some in combinations(to_find, count) if works(file, no_better_than(file, some))
        ]
        for size in range(fewest, len(facts) + 1 if hopeful else 0):
            picked = _with_enough_of_each(others, at_least, size - len(in_every_set))
            sets: Iterable[list[Unknown]] = (
                sorted((*in_every_set, *more), key=place.__getitem__) for more in picked
            )
            if at_least:
                # They were picked group by group. A report lists them in the order of their
                # FACTs, as if every set had been tried.
                sets = sorted(sets, key=lambda stated: [place[fact] for fact in stated])
            enough = [
                (*stated, *some)
                for stated in sets
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


def _with_enough_of_each(
    facts: Sequence[Unknown], at_least: Sequence[tuple[frozenset[Unknown], int]], size: int
) -> Iterator[tuple[Unknown, ...]]:
    """Every way to pick so many FACTs with at least a stated number from each group.

    No group shares a FACT with another. Only the picks that qualify are made: a pick takes
    from a group no more than the later groups leave room for. So a FILE with many FACTs
    outside the groups costs nothing for the sizes that the groups rule out. The picks come
    in no particular order.
    """
    grouped = frozenset[Unknown]().union(*(group for group, _ in at_least))
    outside = [fact for fact in facts if fact not in grouped]
    owed = [sum(number for _, number in at_least[index:]) for index in range(len(at_least) + 1)]
    partly: list[tuple[int, tuple[Unknown, ...], int]] = [(0, (), size)]
    while partly:
        index, picked, left = partly.pop()
        if index == len(at_least):
            for more in combinations(outside, left):
                yield (*picked, *more)
            continue
        group, number = at_least[index]
        inside = [fact for fact in facts if fact in group]
        for count in range(number, min(len(inside), left - owed[index + 1]) + 1):
            for chosen in combinations(inside, count):
                partly.append((index + 1, (*picked, *chosen), left - count))


def _asked_by_a_lock(file: File) -> tuple[frozenset[Unknown], list[tuple[frozenset[Unknown], int]]]:
    """What the LOCKs ask of every set of unknown FACTs that is enough. It takes no search.

    First, the FACTs that every such set holds. A LOCK puts its PERSONs into its OPTION in
    every ITINERARY. An OPTION with no stated start can be used only if its start turns out
    free. And where nobody knows whether the OPTION needs a right, the PERSONs whom no BOOKING
    covers can take part only if it turns out to need none, once they are more than the places
    on OFFER: no set asks for another right to such an OPTION. Nothing else can stand in for
    either FACT.

    Second, groups of FACTs with a number: every such set holds at least that many of the
    group. Where a FACT says the OPTION needs a right, each of those PERSONs needs one. The
    places on OFFER serve some of them, whoever they are, and each of the rest needs another
    right. So a set asks for another right for at least that many of them.
    """
    asked: set[Unknown] = set()
    at_least: list[tuple[frozenset[Unknown], int]] = []
    locked: dict[str, set[str]] = {}
    for lock in file.locks:
        if file.start(lock.option) is None:
            asked.add(Unknown("start", lock.option))
        locked.setdefault(lock.option, set()).update(lock.persons)
    for option, persons in locked.items():
        without = [person for person in persons if file.booking(option, person) is None]
        short = len(without) - file.places_on_offer(option)
        if file.needs_right(option) is None and short > 0:
            asked.add(Unknown("needs no right", option))
        if file.needs_right(option) and file.rights_complete(option) is None and short > 0:
            rights = (Unknown("another right", option, person=person) for person in without)
            at_least.append((frozenset(rights), short))
    return frozenset(asked), at_least


def _limit(file: File, unknown: Unknown, works: Works) -> int | None:
    """The most seconds this one unknown can be for the TRIP to work.

    None for an unknown that is not a length of time, and None when any length would do.
    """
    no_length = ("start", "satisfies", "does not satisfy", "another option")
    if unknown.what in (*no_length, "needs no right", "another right", "price", "funding"):
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
