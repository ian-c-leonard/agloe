"""The three answers, ROBUST and the evidence, for any search.

``check`` follows the sections "The three answers", "ROBUST" and "Evidence" of spec/rules.md.
It asks a search three things: which ITINERARY is shown in a world, whether anything works in a
world, and whether anything can work once records are taken out of the FILE. By default the
search is the reference checker's, which tries everything. The COMPILER passes its solver
search instead, and the answers and the evidence are worked out here in either case.
"""

from collections.abc import Callable, Iterable, Iterator, Sequence, Set
from dataclasses import dataclass, replace
from enum import Enum
from itertools import combinations

from agloe.file import (
    Booking,
    Cap,
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
    broken_as_listed,
    can_work,
    first_shown,
    has_to_end_at,
    in_world,
    longest_case,
    no_better_than,
    one_way_each,
    unknowns,
    way_to_pay,
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
class Missing:
    """An unknown FACT the answer depends on.

    ``at_most`` is the most seconds a length of time can be for a FEASIBLE TRIP. ``buys``
    comes with a FACT about money, and says who buys which place in one plan that works when
    the FACT's set turns out well. For a price, they are the places of its OFFER. For a
    BUDGET that can pay for a PERSON, they are the places that PERSON has to pay for.
    """

    unknown: Unknown
    at_most: int | None
    buys: tuple[Cover, ...] = ()


@dataclass(frozen=True)
class CapRow:
    """What a report says about one cap, so that anybody can check it.

    ``paid`` is what the BOOKINGs charged to it for sure. ``might`` holds each BOOKING that
    might have charged it besides, with the amount where the FILE states one, and None where
    the BOOKING states no payment. ``asked`` holds those among them whose charge a set of
    unknown FACTs asks about. ``to_buy`` is what the plan buys from it, and ``if_needed`` the
    most it buys besides, if OPTIONs turn out to need a right. ``left`` is what the cap still
    allows after all of that, with each BOOKING in ``might`` counted in full unless the set
    asks about it. Whatever else comes to be charged to the cap has to fit in it. The
    amounts are whole ten-thousandths of the cap's currency.
    """

    cap: str
    paid: int
    might: tuple[tuple[str, int | None], ...]
    asked: tuple[str, ...]
    to_buy: int
    if_needed: int
    left: int


@dataclass(frozen=True)
class Plan:
    """One plan that works where a set of unknown FACTs turns out well, in a FILE with a cap.

    ``buys`` says who buys which place, at what price and from which BUDGET. ``caps`` gives
    the sum that has to hold for each cap.
    """

    buys: tuple[Cover, ...]
    caps: tuple[CapRow, ...]


@dataclass(frozen=True)
class Report:
    """The answer and its evidence.

    FEASIBLE: the ITINERARY shown, the FACTs, WANTs and DECISIONs it relies on, whether it is
    ROBUST, what it breaks when every CONTINGENT duration runs longest, and what gives each
    PERSON their right to each OPTION that needs one or might. INFEASIBLE: FACTs, WANTs and
    DECISIONs that conflict, and whether they conflict only ``given_budgets``: with the BUDGETs
    as the FILE lists them. UNDETERMINED: each smallest set of unknown FACTs that would be
    enough.

    In a FILE with a cap, a FEASIBLE Report has a row for each cap in ``caps``, and an
    UNDETERMINED one has a plan for each set of ``missing`` in ``plans``, in the same order.
    """

    answer: Answer
    itinerary: Itinerary = ()
    relies_on: tuple[str, ...] = ()
    robust: bool | None = None
    at_worst: tuple[Broken, ...] = ()
    rights: tuple[Cover, ...] = ()
    conflict: tuple[str, ...] = ()
    given_budgets: bool = False
    missing: tuple[tuple[Missing, ...], ...] = ()
    caps: tuple[CapRow, ...] = ()
    plans: tuple[Plan, ...] = ()


type Shown = Callable[[File, World], Itinerary | None]
type Works = Callable[[File, World], bool]
type CanWork = Callable[[Remaining], bool]


def check(
    file: File, shown: Shown = first_shown, works: Works = any_works, can_work: CanWork = can_work
) -> Report:
    """The answer for this TRIP, with its evidence.

    ``shown``, ``works`` and ``can_work`` are how ITINERARIES are found. By default the
    reference checker tries every choice. A solver can stand in for that search. The answers
    and the evidence are worked out here in either case, from what the search says: the
    ITINERARY that the rule puts first in a world, whether any ITINERARY works in a world,
    and whether any works in some best case of what is left of a FILE.
    """
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
        # Every LOCK and every cap, and the times of the TRIP where the plan has anything.
        relies_on += [each.id for each in file.decisions if isinstance(each, Lock | Cap) or chosen]
        at_worst: tuple[Broken, ...] = ()
        if not robust:
            # The steps keep the order the ITINERARY lists them in: that is the plan shown.
            at_worst = tuple(broken_as_listed(file, longest, in_world(longest, chosen)))
        caps = _cap_rows(file, rights, ())
        return Report(
            Answer.FEASIBLE, chosen, tuple(relies_on), robust, at_worst, rights, caps=caps
        )
    found = _conflict(file, can_work)
    if found is not None:
        conflict, given_budgets = found
        return Report(Answer.INFEASIBLE, conflict=conflict, given_budgets=given_budgets)
    missing = _missing(file, works, shown)
    plans = tuple(_plan(file, some, shown) for some in missing) if file.caps else ()
    return Report(Answer.UNDETERMINED, missing=missing, plans=plans)


def _relied_on(file: File, itinerary: Itinerary, fact: Fact, used: Set[str]) -> bool:
    """Whether a plan relies on this FACT.

    It relies on every FACT about an OPTION or a WAY it has in it. It relies on no COMPLETE set
    of travel: it takes no unlisted WAY. It relies on where a PERSON starts from where the
    PERSON is in it, or has to end the TRIP at a PLACE: their path begins there, or they stay
    there. It relies on the BOOKINGs and the OFFERs that give its PERSONs their rights:
    ``used`` holds those. In a FILE with a cap it relies on every BOOKING: each says what it
    charged, and that is how each cap is known to hold. It relies on no FACT that the rights
    to an OPTION are COMPLETE.
    """
    if isinstance(fact, CompleteFor):
        return _settles(file, itinerary, fact)
    if isinstance(fact, Booking) and file.caps:
        return True
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


def _covers(file: File, world: World, itinerary: Itinerary) -> tuple[Cover, ...]:
    """What gives each PERSON in a plan their right to each of its OPTIONs, in this world.

    It leaves out an OPTION that needs no right in this world. A PERSON whom a BOOKING covers
    has the first such BOOKING in the FILE. A PERSON with another right in this world is left
    out: no record gives it. The other PERSONs who take part take places of the OPTIONs'
    OFFERs, each paid from a BUDGET, as ``way_to_pay`` gives them for the whole TRIP. The plan
    works in this world, so there is a way to pay.
    """
    order = {person.id: number for number, person in enumerate(file.persons)}
    taking_part = {step.option: step.persons for step in itinerary if step.option is not None}
    paying = way_to_pay(file, world, taking_part)
    if paying is None:
        raise AssertionError("a plan that works has no way to pay")
    covers: list[Cover] = []
    for step in itinerary:
        if step.option is None or step.option not in world.needs_right:
            continue
        offers = {offer.id: offer for offer in file.offers(step.option)}
        for person in sorted(step.persons, key=order.__getitem__):
            booked = file.booking(step.option, person)
            if booked is not None:
                covers.append(Cover(step.option, person, booked.id, False))
            elif (step.option, person) in paying:
                offer, budget = paying[step.option, person]
                covers.append(Cover(step.option, person, offer, True, offers[offer].price, budget))
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


def _conflict(file: File, can_work: CanWork) -> tuple[tuple[str, ...], bool] | None:
    """FACTs, WANTs and DECISIONs that make the TRIP INFEASIBLE by themselves, or None.

    None says that an ITINERARY works in the best case, so the TRIP is not INFEASIBLE.
    Otherwise no record can be removed from the set returned.

    The search asks one question again and again: with this record taken out as well, can
    anything work in some best case of what is left? A FACT that is taken out is unknown,
    and a best case gives every unknown its most helpful value. So where something can work,
    something still can once one more record is out. It need not be the same ITINERARY, nor
    the same best case.

    The records are tried one at a time, in the FILE's order. A record goes where the TRIP
    stays INFEASIBLE without it, and it stays out for the questions that follow.

    The BUDGETs stay as the FILE lists them throughout. The last test takes them all out at
    once: then nobody knows who pays for anybody, and the best case has a BUDGET for each
    PERSON. The second value returned says whether the records rule out every ITINERARY only
    with the BUDGETs there. Only a place with a price above nothing needs a BUDGET, so the
    test is made only where a record left is an OFFER with one. A conflict that holds a cap
    needs no test: the cap is about its BUDGET.
    """
    kept = Remaining(file)
    if can_work(kept):
        return None
    for record in _records(file):
        smaller = kept.without(record)
        if not can_work(smaller):
            kept = smaller
    priced = any(
        isinstance(fact, Offer) and fact.price is not None and fact.price.amount
        for fact in kept.file.facts
    )
    if kept.file.caps:
        # A cap names its BUDGET, so the conflict is about the BUDGETs as they are.
        return tuple(_records(kept.file)), True
    with_no_budget = replace(kept, file=replace(kept.file, budgets=()))
    given_budgets = bool(priced and file.budgets) and can_work(with_no_budget)
    return tuple(_records(kept.file)), given_budgets


def _records(file: File) -> list[str]:
    """The FACTs, then the WANTs that ask something of a PERSON, then the DECISIONs."""
    wants = [want.id for want in file.wants if want.musts or want.must_nots]
    return [*(fact.id for fact in file.facts), *wants, *(each.id for each in file.decisions)]


def _missing(file: File, works: Works, shown: Shown) -> tuple[tuple[Missing, ...], ...]:
    """The sets of unknown FACTs that would be enough if they turned out well.

    Each set makes the TRIP FEASIBLE with every other unknown FACT at its worst. A set of one
    length of time comes with its limit. A FACT about money comes with who buys which place
    in the ITINERARY that would be shown if its set turned out well.

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
                    tuple(
                        Missing(u, _limit(file, u, works) if alone else None, bought)
                        for u, bought in zip(some, _bought(file, some, shown), strict=True)
                    )
                    for some in enough
                )
    raise AssertionError("the best case works, so some unknown FACTs make it work")


def _bought(file: File, enough: Sequence[Unknown], shown: Shown) -> list[tuple[Cover, ...]]:
    """For each FACT of a set that is enough, who buys which place because of it.

    The places are those of the ITINERARY shown in the world where the set turns out well and
    every other unknown FACT badly. A price is about the places of its OFFER. That a BUDGET
    can pay for a PERSON is about the places that PERSON takes and has to pay for there: at
    a price above nothing, or at a price that nobody knows and that the set does not ask
    for. A price the set asks for turns out well, and that place goes with the price. Any
    other FACT has none, and a set that asks nothing about money is not searched.
    """
    if not any(unknown.what in ("price", "funding") for unknown in enough):
        return [() for _ in enough]
    places = _purchases(file, enough, shown)
    quoted = {unknown.about for unknown in enough if unknown.what == "price"}
    bought: list[tuple[Cover, ...]] = []
    for unknown in enough:
        if unknown.what == "price":
            bought.append(tuple(cover for cover in places if cover.by == unknown.about))
        elif unknown.what == "funding":
            to_pay = (
                cover
                for cover in places
                if cover.by not in quoted and (cover.price is None or cover.price.amount)
            )
            bought.append(tuple(cover for cover in to_pay if cover.person == unknown.person))
        else:
            bought.append(())
    return bought


def _purchases(
    file: File, enough: Sequence[Unknown], shown: Shown, world: World | None = None
) -> list[Cover]:
    """Who buys which place in the ITINERARY shown where a set of unknown FACTs turns out well.

    Every other unknown FACT turns out badly there. ``world`` is that world, where it is not
    the one in which each FACT of the set turns out as well as it can.
    """
    world = world or with_these_at_best(file, enough)
    plan = shown(file, world)
    if plan is None:
        raise AssertionError("a set of unknown FACTs that is enough shows no ITINERARY")
    return [cover for cover in _covers(file, world, plan) if cover.to_buy]


def _plan(file: File, enough: Sequence[Missing], shown: Shown) -> Plan:
    """One plan that works where this set turns out well, with the sum for each cap.

    A set of one length of time says the most that length can be, or that any length would
    do. The plan is one that works at that length: a plan for no time at all could buy a
    place that the PERSON then misses.
    """
    unknowns = [needed.unknown for needed in enough]
    world = None
    if len(enough) == 1 and unknowns[0].what in ("duration", "cutoff", "other ways"):
        longest = enough[0].at_most
        world = with_this_long(file, unknowns[0], _beyond(file) if longest is None else longest)
    buys = _purchases(file, unknowns, shown, world)
    asked = [unknown.about or "" for unknown in unknowns if unknown.what == "charged"]
    return Plan(tuple(buys), _cap_rows(file, buys, asked))


def _cap_rows(file: File, covers: Sequence[Cover], asked: Sequence[str]) -> tuple[CapRow, ...]:
    """A row for each cap of the FILE, in the FILE's order, for a plan with these purchases.

    A BOOKING that names the cap's BUDGET in its currency charged it for sure. One that states
    no payment might have charged any cap, and one that states a payment with no BUDGET might
    have charged any cap in its currency. ``asked`` holds the BOOKINGs whose charge the set
    of the plan asks about: what they charged is not counted, and has to fit in what is left.
    """
    rows: list[CapRow] = []
    bookings = [fact for fact in file.facts if isinstance(fact, Booking)]
    for cap in file.caps.values():
        currency = cap.limit.currency
        paid = sum(
            fact.paid.money.units
            for fact in bookings
            if fact.paid is not None
            and fact.paid.budget == cap.budget
            and fact.paid.money.currency == currency
        )
        might = tuple(
            (fact.id, None if fact.paid is None else fact.paid.money.units)
            for fact in bookings
            if file.charge_is_open(fact)
            and (fact.paid is None or fact.paid.money.currency == currency)
        )
        mine = [
            cover
            for cover in covers
            if cover.to_buy
            and cover.price is not None
            and cover.budget == cap.budget
            and cover.price.currency == currency
        ]
        sure = sum(c.price.units for c in mine if c.price and file.needs_right(c.option) is True)
        most = sum(c.price.units for c in mine if c.price and file.needs_right(c.option) is None)
        named = tuple(booking for booking, _ in might if booking in asked)
        besides = sum(units or 0 for booking, units in might if booking not in named)
        left = cap.limit.units - paid - besides - sure - most
        rows.append(CapRow(cap.id, paid, might, named, sure, most, left))
    return tuple(rows)


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

    In a FILE with a cap, every set also holds what each BOOKING with no stated payment
    charged: at its worst that has no upper bound, and no cap can be shown to hold.

    Second, groups of FACTs with a number: every such set holds at least that many of the
    group. Where a FACT says the OPTION needs a right, each of those PERSONs needs one. The
    places on OFFER serve some of them, whoever they are, and each of the rest needs another
    right. So a set asks for another right for at least that many of them.
    """
    asked: set[Unknown] = set()
    at_least: list[tuple[frozenset[Unknown], int]] = []
    locked: dict[str, set[str]] = {}
    for fact in file.facts:
        if isinstance(fact, Booking) and fact.paid is None and file.caps:
            asked.add(Unknown("charged", fact.option, about=fact.id))
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


def _beyond(file: File) -> int:
    """A length of time that no limit can be longer than, in seconds.

    Only two fixed times can limit a length of time: it must fit between them. So a length
    longer than the time between the earliest and the latest fixed time has no limit. The
    times the TRIP starts and ends are fixed times too.
    """
    fixed = [fact.at for fact in file.facts if isinstance(fact, Start) and fact.at is not None]
    fixed += [bound.at for bound in (file.trip_start(), file.trip_end()) if bound is not None]
    for fact in file.facts:
        if isinstance(fact, Complete):
            fixed += [fact.earliest - 1, fact.latest + 1]
    return max(fixed) - min(fixed) + 1 if fixed else 1


def _limit(file: File, unknown: Unknown, works: Works) -> int | None:
    """The most seconds this one unknown can be for the TRIP to work.

    None for an unknown that is not a length of time, and None when any length would do.
    """
    no_length = ("start", "satisfies", "does not satisfy", "another option")
    about_rights = ("needs no right", "another right", "price", "funding", "charged")
    if unknown.what in (*no_length, *about_rights):
        return None

    def enough(seconds: int) -> bool:
        return works(file, with_this_long(file, unknown, seconds))

    under, over = 0, _beyond(file)
    if enough(over):
        return None
    while over - under > 1:
        middle = (under + over) // 2
        under, over = (middle, over) if enough(middle) else (under, middle)
    return under
