"""The three answers, ROBUST and the evidence, for any search.

``check`` follows the sections "The three answers", "ROBUST" and "Evidence" of spec/rules.md.
It asks a search three things: which ITINERARY is shown in a world, whether anything works in a
world, and whether anything can work once records are taken out of the FILE. By default the
search is the reference checker's, which tries everything. The COMPILER passes its solver
search instead, and the answers and the evidence are worked out here in either case.
"""

from collections.abc import Callable, Container, Iterator, Sequence, Set
from dataclasses import dataclass, replace
from enum import Enum
from itertools import chain, combinations

from agloe.file import (
    FIRST_TIME,
    Booking,
    Cap,
    Complete,
    CompleteFor,
    CompleteNeedsRightFor,
    CompleteRequires,
    CompleteRequiresObject,
    CompleteRights,
    CompleteRightsFor,
    CompleteTransfers,
    Fact,
    File,
    Has,
    Lock,
    Money,
    NeedsRightFor,
    Now,
    ObjectStarts,
    Offer,
    RefusesObject,
    Requires,
    RequiresObject,
    Start,
    StartsFrom,
    Term,
    WithObject,
)
from agloe.reference import (
    Broken,
    Itinerary,
    Remaining,
    Unknown,
    Where,
    World,
    any_works,
    arrived,
    broken_as_listed,
    brought_in,
    can_work,
    first_shown,
    goes_along,
    has_to_end_at,
    in_world,
    just_before,
    longest_case,
    no_better_than,
    one_way_each,
    places_taken,
    taking_a_place,
    unknowns,
    way_to_pay,
    whereabouts,
    with_no_offer,
    with_one_required,
    with_these_at_best,
    with_this_long,
    within_reach,
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

    A place that covers an OBJECT names the ``object``, and no PERSON. ``might`` says that
    the OBJECT only might be in the OPTION: nobody knows where it is, or whether the OPTION
    takes it along. The place has to be bought only if the OBJECT is there.

    ``together`` comes with a place for an OBJECT that takes places in one set of OPTIONs
    or in another, and never in two of the sets: nobody knows where it is, and it is in one
    place at a time. It holds each set, with the OPTIONs in the order of the plan. A cap
    counts the set that costs the most.
    """

    option: str
    person: str | None
    by: str
    to_buy: bool
    price: Money | None = None
    budget: str | None = None
    object: str | None = None
    might: bool = False
    together: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class Missing:
    """An unknown FACT the answer depends on.

    ``at_most`` is the most seconds a length of time can be for a FEASIBLE TRIP. ``buys``
    comes with a FACT about money, and says who buys which place in one plan that works when
    the FACT's set turns out well. For a price, they are the places of its OFFER. For a
    BUDGET that can pay for a PERSON, they are the places that PERSON has to pay for.

    ``of`` comes with what an OPTION requires of a CAPABILITY, where that is the only FACT of
    its set. It is the most the OPTION can require for a FEASIBLE TRIP: "one" where it can
    require it of one PERSON, and "none" where it can require nothing.

    ``at_hand_for`` comes with another transfer of an OBJECT. It holds each check of the
    OBJECT in one plan that works when the set turns out well: an OPTION, and "requires"
    where the OBJECT has to be at hand for it, or "refuses" where no PERSON may have the
    OBJECT in it. With each comes whether a FACT says that the OPTION requires or refuses
    the OBJECT: without one, the OPTION might. Then comes whether the check already holds
    with what the FILE lists, in that plan. Nobody has worked out whether another transfer
    can make all of them hold: the set is not settled.
    """

    unknown: Unknown
    at_most: int | None
    buys: tuple[Cover, ...] = ()
    of: str | None = None
    at_hand_for: tuple[tuple[str, str, bool, bool], ...] = ()


@dataclass(frozen=True)
class CapRow:
    """What a report says about one cap, so that anybody can check it.

    ``paid`` is what the BOOKINGs charged to it for sure. ``might`` holds each BOOKING that
    might have charged it besides, with the amount where the FILE states one, and None where
    the BOOKING states no payment. ``asked`` holds those among them whose charge a set of
    unknown FACTs asks about. ``to_buy`` is what the plan buys from it, and ``if_needed`` the
    most it buys besides, if OPTIONs turn out to need a right or an OBJECT turns out to be
    there: ``bought_if_needed`` says which purchases that counts. ``left`` is what the cap still
    allows after all of that, with each BOOKING in ``might`` counted in full unless the set
    asks about it. Whatever else comes to be charged to the cap has to fit in it. The
    amounts are whole ten-thousandths of the cap's currency.

    ``left_for`` is for an OFFER with no price yet whose places cover OBJECTs: the OFFER,
    and what the cap allows for each place that the plan takes of it, where that is more
    than an equal share of ``left``. The cap counts the set of an OBJECT's places that
    costs the most, and a place is bought only with the others of its own sets.
    """

    cap: str
    paid: int
    might: tuple[tuple[str, int | None], ...]
    asked: tuple[str, ...]
    to_buy: int
    if_needed: int
    left: int
    left_for: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class Supply:
    """Who meets one requirement of an OPTION in the plan shown.

    ``of`` is "one" or "each", as the FILE states it, and None where the FILE does not say
    what the OPTION requires of the CAPABILITY. ``persons`` have the CAPABILITY by a FACT:
    the first of those who take part, in the FILE's order, where one PERSON is enough, and
    everybody who takes part otherwise.
    """

    option: str
    capability: str
    of: str | None
    persons: tuple[str, ...]


@dataclass(frozen=True)
class Stay:
    """Where an OBJECT is from one point of the plan shown.

    ``where`` holds each place it might be: one, or several where the FILE leaves open what an
    OPTION does with it or where it starts. ``since`` is the OPTION from whose start it is
    there, and None from the start of the TRIP. ``how`` says what the OPTION did: "handed
    over", "kept" or "carried". It is "kept if held" where the OPTION keeps the OBJECT and
    nobody knows whether a PERSON in it has it: then the OPTION keeps it if one does. It is
    "unknown action" where the FILE does not say what the OPTION does with the OBJECT: it
    might keep it, or take it along where it requires it. It is "unknown requirement"
    where the FILE says that the OPTION carries the OBJECT and not whether it requires it:
    the OBJECT goes along if it does. It is "arrived" where the OBJECT was in the OPTION, or
    might have been, and lies at the PLACE where the OPTION ends: then it is there from the
    end of the OPTION.
    """

    where: tuple[Where, ...]
    since: str | None = None
    how: str | None = None


@dataclass(frozen=True)
class Use:
    """An OPTION of the plan shown that requires an OBJECT or refuses it, or might.

    ``check`` is "requires" or "refuses". ``stated`` says whether a FACT says that it does.
    ``where`` holds each place the OBJECT might be just before the OPTION starts. Each is at
    hand where the OPTION requires the OBJECT. None is a PERSON who takes part where the
    OPTION refuses it.

    ``check`` is "needs a right for" where the OPTION needs a right for the OBJECT, or
    might, and a PERSON who takes part has the OBJECT, or it is handed over or carried
    there. ``by`` is then the BOOKING that covers the OBJECT. Where none does, ``offer`` is
    the OFFER that the OBJECT takes a place of there.
    """

    option: str
    stated: bool
    where: tuple[Where, ...]
    check: str = "requires"
    by: str | None = None
    offer: str | None = None


@dataclass(frozen=True)
class Carried:
    """One OBJECT in the plan shown: where it is, and which OPTIONs require or refuse it."""

    object: str
    stays: tuple[Stay, ...]
    uses: tuple[Use, ...]


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

    An UNDETERMINED Report of a FILE that states no time now, and has an OFFER that states
    when it expires, says in ``before`` until when each set of ``missing`` is enough, in the
    same order. None: at any time. A set can be empty there: the TRIP works before that
    time with nothing else found out. Any other Report leaves ``before`` empty.

    A FEASIBLE Report says in ``supplies`` who meets each requirement of an OPTION in the
    ITINERARY shown. It says in ``objects`` where each OBJECT is that an OPTION of the
    ITINERARY requires or refuses, or might.
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
    before: tuple[int | None, ...] = ()
    supplies: tuple[Supply, ...] = ()
    objects: tuple[Carried, ...] = ()


type Shown = Callable[[File, World], Itinerary | None]
type Works = Callable[[File, World], bool]
type CanWork = Callable[[Remaining], bool]


@dataclass(frozen=True)
class Deadline:
    """A DEADLINE: the time at which a term of a BOOKING starts, for cancelling or for changing.

    ``after`` is what cancelling costs in that term, and ``before`` what it costs in the
    term before it: one amount for each currency, and none where it costs nothing. None: the
    FILE states no cost there. ``first`` says that the term is the first of its list, so
    that the FILE states nothing of the time before it. The two costs are never the same
    stated cost.

    ``kind`` is "cancelling" or "changing". For a term for changing, the two costs are what
    the seller charges for a change: the fee alone.
    """

    at: int
    booking: str
    before: tuple[Money, ...] | None
    after: tuple[Money, ...] | None
    first: bool = False
    kind: str = "cancelling"

    @property
    def change(self) -> str:
        """How the cost changes: it "rises", "falls" or "differs", or a side is not stated.

        It differs where it is more in one currency and less in another: amounts in different
        currencies are never added or compared.
        """
        if self.before is None or self.after is None:
            sides = [(self.before, "before"), (self.after, "from then")]
            return "not stated " + " or ".join(side for cost, side in sides if cost is None)
        more, less = _more_and_less(self.before, self.after)
        if more and less:
            return "differs"
        return "rises" if more else "falls"

    @property
    def stake(self) -> tuple[Money, ...] | None:
        """The STAKE: what cancelling costs more once the DEADLINE has passed, or the fee.

        Empty: nothing. That is so where the cost falls, and wherever it is nothing
        in the new term, whatever it was before. None: unknown, because the FILE states no
        cost on one side or on both, or not one sum, because the cost is more in one currency
        and less in another.
        """
        if self.after == ():
            return ()
        if self.before is None or self.after is None:
            return None
        more, less = _more_and_less(self.before, self.after)
        if less:
            return None if more else ()
        return more


def _more_and_less(
    before: Sequence[Money], after: Sequence[Money]
) -> tuple[tuple[Money, ...], bool]:
    """What the later cost has more of, by currency, and whether it has less of any.

    An amount in a currency that the earlier cost does not have is more by all of it, as the
    FILE states it.
    """
    was = {each.currency: each for each in before}
    now = {each.currency: each for each in after}
    more = tuple(
        each.less(was[each.currency]) if each.currency in was else each
        for each in after
        if each.currency not in was or each.units > was[each.currency].units
    )
    less = any(each.currency not in now or each.units > now[each.currency].units for each in before)
    return more, less


# The two lists of terms that a BOOKING can state, in the order a report names them.
KINDS_OF_TERMS = ("cancelling", "changing")


def deadlines(file: File) -> tuple[Deadline, ...]:
    """The DEADLINEs that a report of this FILE lists, earliest first.

    The time of a term for cancelling is a DEADLINE, unless the FILE states the same cost for
    that term and for the one before it. A term with no stated cost is one, also after a term
    with none: the terms change there, and nobody has said how. Before a first term that
    states its time, the FILE states nothing. The terms for changing give DEADLINEs in the
    same way, apart from those for cancelling.

    Where the FILE states the time now, these are the DEADLINEs after it. One at that very
    time has passed: its term holds already. Where it states none, they are all of them.
    DEADLINEs at one instant come in the FILE's order of BOOKINGs, and those of one BOOKING
    with cancelling first.
    """
    now = file.now()
    found: list[Deadline] = []
    for fact in file.facts:
        if not isinstance(fact, Booking):
            continue
        for kind in KINDS_OF_TERMS:
            held: Term | None = None
            for term in fact.terms(kind):
                before = None if held is None else held.costs
                changes = not _the_same(before, term.costs)
                if term.since is not None and changes and (now is None or term.since > now.at):
                    first = held is None
                    found.append(Deadline(term.since, fact.id, before, term.costs, first, kind))
                held = term
    return tuple(sorted(found, key=lambda each: each.at))


@dataclass(frozen=True)
class Expiry:
    """A DEADLINE: the time at which an OFFER expires. Its places can be bought before it."""

    at: int
    offer: str


def expiries(file: File) -> tuple[Expiry, ...]:
    """The expiries that a report of this FILE lists, earliest first.

    Each OFFER that states when it expires has one. Where the FILE states the time now,
    these are the ones after it: an OFFER has expired at the time it states. Where it
    states none, they are all of them. Expiries at one instant come in the FILE's order.
    """
    found = [
        Expiry(offer.expires, offer.id)
        for offer in file.dated_offers()
        if offer.expires is not None and offer.id not in file.expired
    ]
    return tuple(sorted(found, key=lambda each: each.at))


def every_deadline(file: File) -> tuple[Deadline | Expiry, ...]:
    """Every DEADLINE that a report of this FILE lists, earliest first.

    Those at one instant come in the FILE's order of FACTs, a BOOKING and an OFFER alike.
    """
    order = {fact.id: at for at, fact in enumerate(file.facts)}

    def place(found: Deadline | Expiry) -> tuple[int, int]:
        return found.at, order[found.booking if isinstance(found, Deadline) else found.offer]

    return tuple(sorted([*deadlines(file), *expiries(file)], key=place))


def with_no_expiry(file: File) -> tuple[str, ...]:
    """The OFFERs that do not state when they expire, in the FILE's order."""
    return tuple(fact.id for fact in file.facts if isinstance(fact, Offer) and fact.expires is None)


def _the_same(one: Sequence[Money] | None, other: Sequence[Money] | None) -> bool:
    """Whether two costs are stated and are the same amount in every currency."""
    if one is None or other is None:
        return False
    return {each.currency: each.units for each in one} == {
        each.currency: each.units for each in other
    }


def costs_now(file: File, kind: str) -> tuple[tuple[str, tuple[Money, ...] | None], ...]:
    """What cancelling each BOOKING with terms costs at the time now, in the FILE's order.

    It is the cost of the term that holds at that time: the last one that has started. None:
    the FILE states no cost for that time. Empty where the FILE does not state the time now.
    ``kind`` is "cancelling", or "changing" for what the seller charges for a change.
    """
    now = file.now()
    if now is None:
        return ()
    costs: list[tuple[str, tuple[Money, ...] | None]] = []
    for fact in file.facts:
        if isinstance(fact, Booking) and fact.terms(kind):
            held = None
            for term in fact.terms(kind):
                if term.since is None or term.since <= now.at:
                    held = term.costs
            costs.append((fact.id, held))
    return tuple(costs)


def costs_at_any_time(file: File, kind: str) -> tuple[tuple[str, tuple[Money, ...]], ...]:
    """What cancelling costs for each BOOKING whose terms state one cost for all time.

    Its first term holds from when the BOOKING was made, and every term states that same
    cost. So a report can say what cancelling it costs though the FILE does not state the
    time now. They come in the FILE's order. ``kind`` is "cancelling", or "changing" for
    what the seller charges for a change.
    """
    costs: list[tuple[str, tuple[Money, ...]]] = []
    for fact in file.facts:
        if isinstance(fact, Booking) and fact.terms(kind):
            first = fact.terms(kind)[0]
            same = all(_the_same(first.costs, term.costs) for term in fact.terms(kind))
            if first.since is None and first.costs is not None and same:
                costs.append((fact.id, first.costs))
    return tuple(costs)


def with_no_terms(file: File, kind: str) -> tuple[str, ...]:
    """The BOOKINGs that state no terms of one kind, in the FILE's order.

    ``kind`` is "cancelling" or "changing".
    """
    return tuple(
        fact.id for fact in file.facts if isinstance(fact, Booking) and not fact.terms(kind)
    )


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
    *_, report = reports(file, shown, works, can_work, ahead=False)
    if not isinstance(report, Report):
        raise AssertionError("a check ended with no Report")
    return report


def reports(
    file: File,
    shown: Shown = first_shown,
    works: Works = any_works,
    can_work: CanWork = can_work,
    ahead: bool = True,
) -> Iterator[Answer | Report]:
    """The answer as soon as it is proved, and then the Report that ``check`` gives.

    The answer comes ahead by itself, as an Answer. No evidence comes with it: a Report with
    an empty ITINERARY says that nobody has to do anything, and that is not known yet. Each
    answer is proved at one point, and nothing is given from less.

    - FEASIBLE, once some ITINERARY works in the worst case. That takes one question more:
      ``works`` stops at the first ITINERARY that does, where ``shown`` looks for the one
      the rule puts first. The ITINERARY it found is not given. It can differ from one
      machine to the next, and it need not be the one the rule puts first.
    - INFEASIBLE, once nothing works in any best case of the whole FILE.
    - UNDETERMINED, once nothing works in the worst case and something does in a best case.

    The searches are exact, so the answer ahead is the answer of the Report, and the same on
    every machine. Without ``ahead`` only the Report is given, and the extra question is not
    asked: this is how ``check`` runs.
    """
    worst = worst_case(file)
    sure = works(file, worst) if ahead else None
    if sure:
        yield Answer.FEASIBLE
    plain = None if sure is False else shown(file, worst)
    if plain is not None:
        longest = longest_case(file)
        # A ROBUST plan comes first, and then a plan that takes no place of an OFFER. The
        # OFFERs stay in the FILE for that: the plan only may not spend their places.
        better = [(longest, True)]
        if any(isinstance(fact, Offer) for fact in file.facts):
            better = [(with_no_offer(longest), True), *better, (with_no_offer(worst), False)]
        chosen, robust = plain, False
        for world, holds in better:
            # With no CONTINGENT duration the longest case is the worst case, and the plan
            # found there is the plan for it: the same world has the same plan.
            found = plain if world == worst else shown(file, world)
            if found is not None:
                chosen, robust = found, holds
                break
        rights = _covers(file, worst, chosen)
        supplies, brought = _supplied(file, chosen)
        objects, held = _carried(file, worst, chosen, rights)
        used = {cover.by for cover in rights} | brought | held
        relies_on = [fact.id for fact in file.facts if _relied_on(file, chosen, fact, used)]
        relies_on += [want.id for want in file.wants if want.musts or want.must_nots]
        # Every LOCK and every cap, and the times of the TRIP where the plan has anything.
        relies_on += [each.id for each in file.decisions if isinstance(each, Lock | Cap) or chosen]
        at_worst: tuple[Broken, ...] = ()
        if not robust:
            # The steps keep the order the ITINERARY lists them in: that is the plan shown.
            at_worst = tuple(broken_as_listed(file, longest, in_world(longest, chosen)))
        caps = _cap_rows(file, rights, ())
        yield Report(
            Answer.FEASIBLE,
            chosen,
            tuple(relies_on),
            robust,
            at_worst,
            rights,
            caps=caps,
            supplies=supplies,
            objects=objects,
        )
        return
    if sure:
        raise AssertionError("an ITINERARY works in the worst case, and the rule shows none")
    whole = Remaining(file)
    if not can_work(whole):
        if ahead:
            yield Answer.INFEASIBLE
        conflict, given_budgets = _conflict(whole, can_work)
        yield Report(Answer.INFEASIBLE, conflict=conflict, given_budgets=given_budgets)
        return
    if ahead:
        yield Answer.UNDETERMINED
    if file.now() is None and file.dated_offers():
        cases = _by_stretch(file, works, shown, can_work)
        missing = tuple(some for some, _, _ in cases)
        before = tuple(until for _, _, until in cases)
        plans = tuple(plan for _, plan, _ in cases if plan is not None)
        yield Report(Answer.UNDETERMINED, missing=missing, plans=plans, before=before)
        return
    missing = _missing(file, works, shown)
    plans = tuple(_plan(file, some, shown) for some in missing) if file.caps else ()
    yield Report(Answer.UNDETERMINED, missing=missing, plans=plans)


def as_seen(file: File, before: int | None) -> File:
    """A FILE that states no time now, as it is in the stretch of time that ends at a moment.

    The times at which its OFFERs expire cut time into stretches, and in each stretch the
    OFFERs that are open are known. This is the FILE with a time now in the stretch just
    before ``before``. None: in the last stretch, after every OFFER that states when it
    expires has expired.
    """
    if before is not None:
        return file.as_of(before - 1)
    return file.as_of(max(offer.expires or 0 for offer in file.dated_offers()))


def _by_stretch(
    file: File, works: Works, shown: Shown, can_work: CanWork
) -> list[tuple[tuple[Missing, ...], Plan | None, int | None]]:
    """The cases of a TRIP whose FILE states no time now, each with the time it holds until.

    Nobody knows which OFFERs have expired. So the cases are worked out once for each
    stretch of time between two expiries, on the FILE as it is in that stretch, from the
    last stretch to the first. Every purchase that is possible later is possible earlier,
    so a case of one stretch holds in every stretch before it. Each case comes with the
    time at which its stretch ends. None: it holds at any time. In a FILE with a cap it
    comes with its plan, as the FILE is in that stretch.

    A case says more than which FACTs it asks for: how long a length of time can be, what
    an OPTION can require, who buys which place, what another transfer has to do, what
    each cap has left. An earlier stretch can differ in any of those, with the same FACTs.
    So a case is left out only where a later stretch has the very same case, in all of
    that: then the later one holds for longer. Nothing is worked out about one case
    covering another, so a report can list a case that asks more than another one does.

    Where the TRIP works in a stretch with nothing else found out, that is a case with no
    unknown FACT, and no earlier stretch adds one: each would end sooner.
    """
    ends = sorted({offer.expires for offer in file.dated_offers() if offer.expires is not None})
    cases: list[tuple[tuple[Missing, ...], Plan | None, int | None]] = []
    listed: set[tuple[tuple[Missing, ...], Plan | None]] = set()
    for until in (None, *reversed(ends)):
        if until is not None and until <= FIRST_TIME:
            # No time now is before the first time a FILE can state: this stretch is empty.
            continue
        seen = as_seen(file, until)
        if works(seen, worst_case(seen)):
            if until is None:
                # The worst case of the FILE has every such OFFER closed, as this stretch has.
                raise AssertionError("the TRIP works after every expiry, and not at worst")
            cases.append(((), _plan(seen, (), shown) if file.caps else None, until))
            break
        if not can_work(Remaining(seen)):
            continue
        for some in _missing(seen, works, shown):
            plan = _plan(seen, some, shown) if file.caps else None
            if (some, plan) not in listed:
                listed.add((some, plan))
                cases.append((some, plan, until))
    return cases


def _relied_on(file: File, itinerary: Itinerary, fact: Fact, used: Set[str]) -> bool:
    """Whether a plan relies on this FACT.

    It relies on every FACT about an OPTION or a WAY it has in it, also where nobody is in
    the OPTION: a FACT about the PERSONs who take part can be why nobody does. It relies on
    no COMPLETE set of travel: it takes no unlisted WAY. It relies on where a PERSON starts
    from where the PERSON is in it, or has to end the TRIP at a PLACE: their path begins
    there, or they stay there. It relies on the BOOKINGs and the OFFERs that give its
    PERSONs their rights:
    ``used`` holds those. In a FILE with a cap it relies on every BOOKING: each says what it
    charged, and that is how each cap is known to hold. It relies on no FACT that the rights
    to an OPTION are COMPLETE. ``used`` also holds the FACTs about CAPABILITIES and about
    OBJECTs that it relies on. It relies on the time now where it takes a place of an OFFER
    that states when it expires: the place can be bought only before that time.
    """
    if isinstance(fact, Now):
        return any(offer.id in used for offer in file.dated_offers())
    if isinstance(fact, Has | Requires | CompleteRequires):
        return fact.id in used
    if isinstance(fact, ObjectStarts | RequiresObject | RefusesObject | WithObject):
        return fact.id in used
    if isinstance(fact, CompleteRequiresObject | CompleteTransfers):
        return fact.id in used
    if isinstance(fact, NeedsRightFor | CompleteNeedsRightFor):
        return fact.id in used
    if isinstance(fact, CompleteFor):
        return _settles(file, itinerary, fact)
    if isinstance(fact, Booking) and (file.caps or fact.id in used):
        return True
    if isinstance(fact, Booking | Offer):
        return fact.id in used
    if isinstance(fact, CompleteRights | CompleteRightsFor):
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

    After the PERSONs of an OPTION come the OBJECTs that take a place of an OFFER there, as
    ``taking_a_place`` gives them, each with its OFFER and the BUDGET that pays. Where an
    OBJECT takes places in one set of OPTIONs or in another, as ``taken_together`` says,
    each of its places comes with those sets.
    """
    order = {person.id: number for number, person in enumerate(file.persons)}
    taking_part = {step.option: step.persons for step in itinerary if step.option is not None}
    taking, together = places_taken(file, world, itinerary)
    paying = way_to_pay(file, world, taking_part, taking, together)
    if paying is None:
        raise AssertionError("a plan that works has no way to pay")
    turn = {step.option: number for number, step in enumerate(itinerary)}

    def sets_of(thing: str) -> tuple[tuple[str, ...], ...]:
        """The sets of OPTIONs where this OBJECT takes places together, where it has several."""
        sets = together.get(thing, ())
        if len(sets) < 2:
            return ()
        in_order = [sorted(turn[option] for option in some) for some in sets]
        return tuple(
            tuple(itinerary[number].option or "" for number in some) for some in sorted(in_order)
        )

    covers: list[Cover] = []
    for step in itinerary:
        if step.option is None:
            continue
        offers = {offer.id: offer for offer in file.offers(step.option)}
        needed = step.option in world.needs_right
        for person in sorted(step.persons, key=order.__getitem__) if needed else ():
            booked = file.booking(step.option, person)
            if booked is not None:
                covers.append(Cover(step.option, person, booked.id, False))
            elif (step.option, person) in paying:
                offer, budget = paying[step.option, person]
                covers.append(Cover(step.option, person, offer, True, offers[offer].price, budget))
        for_objects = {offer.id: offer for offer in file.offers_for_objects(step.option)}
        for thing, sure in taking.get(step.option, {}).items():
            offer, budget = paying[step.option, thing]
            price = for_objects[offer].price
            covers.append(
                Cover(
                    step.option, None, offer, True, price, budget, thing, not sure, sets_of(thing)
                )
            )
    return tuple(covers)


def _supplied(file: File, itinerary: Itinerary) -> tuple[tuple[Supply, ...], set[str]]:
    """Who meets each requirement in a plan, and the FACTs about CAPABILITIES it relies on.

    For each OPTION in the plan and each CAPABILITY, the plan relies on the FACT about what
    the OPTION requires, where the FILE states one. Where the FILE states none and the
    CAPABILITY's set is COMPLETE, it relies on that FACT: only it says that the OPTION
    requires nothing. Where the OPTION requires the CAPABILITY of one PERSON, the plan relies
    on the FACT that the first PERSON in it who has the CAPABILITY has it, in the FILE's
    order. Where it requires it of each PERSON, or the FILE does not say what it requires,
    the plan relies on that FACT for everybody in the OPTION.

    The plan works in the worst case, so those FACTs are there.
    """
    order = {person.id: number for number, person in enumerate(file.persons)}
    taking_part = {step.option: step.persons for step in itinerary if step.option is not None}
    supplies: list[Supply] = []
    relied: set[str] = set()
    for option, persons in taking_part.items():
        for capability in file.capabilities:
            stated = file.requirement(option, capability.id)
            of = file.requires(option, capability.id)
            if stated is not None:
                relied.add(stated.id)
            if of == "none":
                whole = file.requires_complete(capability.id)
                if stated is None and whole is not None:
                    relied.add(whole.id)
                continue
            able = [person for person in persons if file.has(person, capability.id)]
            able.sort(key=order.__getitem__)
            chosen = able[:1] if of == "one" else able
            for person in chosen:
                known = file.ability(person, capability.id)
                if known is not None:
                    relied.add(known.id)
            supplies.append(Supply(option, capability.id, of, tuple(chosen)))
    return tuple(supplies), relied


def _carried(
    file: File, world: World, itinerary: Itinerary, rights: Sequence[Cover] = ()
) -> tuple[tuple[Carried, ...], set[str]]:
    """Where each OBJECT of a plan is, and the FACTs about OBJECTs that the plan relies on.

    For each OPTION in the plan and each OBJECT, the plan relies on the FACT about whether the
    OPTION requires the OBJECT, where the FILE states one, and on the FACT about whether it
    refuses the OBJECT. Where the FILE states none of a kind and the set of the OBJECT's
    requirements is COMPLETE, it relies on that FACT: only it says that the OPTION does not
    require the OBJECT, or does not refuse it.

    The rest is about each OBJECT that an OPTION of the plan requires or refuses, or might.
    The report says where it is throughout the plan, and the plan relies on each record that
    says so.
    That is the FACT about where it starts. It is the FACT about what an OPTION does with it,
    for each OPTION of the plan in which it is handed over or carried, and for each one in
    which a PERSON has it or might. Where the FILE states no such FACT and the set of the OBJECT's
    transfers is COMPLETE, the plan relies on that FACT: only it says that the OPTION leaves
    the OBJECT alone. Where the FILE has neither, the report says each place where the
    OBJECT might be from then on.

    For each OPTION in the plan and each OBJECT, the plan also relies on the FACT about
    whether the OPTION needs a right for the OBJECT, where the FILE states one. Where it
    states none and a FACT says that the FILE states every OPTION that needs a right for
    the OBJECT, it relies on that FACT. Where the OPTION needs the right, or might, and a
    PERSON who takes part has the OBJECT, or it is handed over or carried there, the plan
    relies on the BOOKING that covers the OBJECT, and the report names it. Where no BOOKING
    does and the OBJECT takes a place of an OFFER there, the report names the OFFER:
    ``rights`` holds those places.

    An OBJECT that is carried is in the OPTION from its start, and lies at the PLACE where
    the OPTION ends from its end, as the plan shows that end. That is said whether or not a
    later step uses the OBJECT, and whether the travelers chose the carry or the OBJECT
    goes along with no choice. Where an OPTION only might take the OBJECT along, the
    OBJECT might be in it, and then might lie where it ends. An OPTION with no known end
    is said last: nobody knows when the OBJECT lies there.

    ``world`` is the worst case, and the plan works in it. So the FACTs are there, and the
    OBJECT is where this says wherever the steps end as the plan shows them. An OBJECT that
    is carried arrives when its OPTION ends, and that can be sooner in a possible world:
    the plan works then too, as the rules page says of a shorter duration.
    """
    people = {person.id: number for number, person in enumerate(file.persons)}
    places = {place.id: number for number, place in enumerate(file.places)}
    carriers = {option.id: number for number, option in enumerate(file.options)}

    def in_order(where: Set[Where]) -> tuple[Where, ...]:
        """PERSONs in the FILE's order, then PLACEs, then OPTIONs, each in the FILE's order."""

        def rank(each: Where) -> tuple[int, int]:
            if each.person is not None:
                return (0, people[each.person])
            if each.place is not None:
                return (1, places[each.place])
            return (2, carriers[each.option]) if each.option is not None else (3, 0)  # no name

        return tuple(sorted(where, key=rank))

    steps = [step for step in itinerary if step.option is not None]
    ends = {step.option or "": step.end for step in steps}
    ends_at = {option.id: option.destination for option in file.options}
    trails = whereabouts(file, world, itinerary)
    found_at = just_before(file, world, itinerary)

    def arrivals(left: frozenset[Where], found: frozenset[Where] | None) -> list[Stay]:
        """Where an OBJECT lies once the OPTION that it was in, or might be in, is over.

        ``left`` is where the last OPTION left it, and ``found`` where the next one finds
        it, or None after the last OPTION of the plan. A plan that works has the OBJECT in
        one OPTION at most. It is carried only where it is at hand, by choice or with
        none, and an OBJECT that might be in another OPTION is at hand for nothing.
        """
        there, said = left, list[Stay]()
        over = [each.option for each in left if each.option is not None]
        if found is not None:
            over = [name for name in over if Where(option=name) not in found]
        for name in over:
            there = arrived(there, {name}, ends_at)
            said.append(Stay(in_order(there), name, "arrived"))
        return said

    relied: set[str] = set()
    carried: list[Carried] = []
    on_offer = {(cover.option, cover.object): cover.by for cover in rights if cover.object}
    for thing in file.objects:
        every = file.object_requirements_complete(thing.id)
        for step in steps:
            required = file.object_requirement(step.option or "", thing.id)
            refused = file.object_refusal(step.option or "", thing.id)
            for stated in (required, refused):
                if stated is not None:
                    relied.add(stated.id)
                elif every is not None:
                    relied.add(every.id)
            ticket = file.object_right(step.option or "", thing.id)
            listed = file.object_rights_complete(thing.id)
            if ticket is not None:
                relied.add(ticket.id)
            elif listed is not None:
                relied.add(listed.id)
        checked = world.needs | world.refuses | world.ticketed
        if thing.id not in trails or not any((step.option, thing.id) in checked for step in steps):
            continue
        trail, seen = trails[thing.id], found_at[thing.id]
        start = file.object_starts(thing.id)
        if start is not None:
            relied.add(start.id)
        stays = [Stay(in_order(trail[0]))]
        uses: list[Use] = []

        for number, step in enumerate(steps):
            option = step.option or ""
            stays += arrivals(trail[number], seen[number])
            before, after = seen[number], trail[number + 1]
            taker = dict(step.handed).get(thing.id)
            aboard = Where(option=option)
            held = any(each.person in step.persons for each in before)
            # The FACT about what the OPTION does says whether the OBJECT goes along where
            # the OPTION requires it. So the plan relies on it there too.
            required = (option, thing.id) in world.needs
            if taker is not None or held or required or aboard in after:
                done = file.action(option, thing.id)
                whole = file.transfers_complete(thing.id)
                if done is not None:
                    relied.add(done.id)
                elif whole is not None:
                    relied.add(whole.id)
            if (option, thing.id) in world.needs:
                stated = file.requires_object(option, thing.id) is True
                uses.append(Use(option, stated, in_order(before)))
            if (option, thing.id) in world.refuses:
                # Nobody knows when an OPTION with no known end is over. So the OBJECT
                # might still be in it, and it might lie where it ends. An OPTION that
                # requires the OBJECT never finds it so: the plan would not be sure to hold.
                landed = {
                    Where(place=ends_at[each.option])
                    for each in before
                    if each.option is not None and ends[each.option] is None
                }
                stated = file.refuses_object(option, thing.id) is True
                uses.append(Use(option, stated, in_order(before | landed), "refuses"))
            covering = file.booking_for(option, thing.id)
            in_it = taker is not None or held or aboard in after
            if (option, thing.id) in world.ticketed and in_it and covering is not None:
                relied.add(covering.id)
                stated = file.needs_right_for(option, thing.id) is True
                uses.append(Use(option, stated, in_order(before), "needs a right for", covering.id))
            elif (option, thing.id) in on_offer:
                stated = file.needs_right_for(option, thing.id) is True
                offer = on_offer[option, thing.id]
                uses.append(Use(option, stated, in_order(before), "needs a right for", offer=offer))
            if after != before:
                # It is kept for sure where whoever might have it takes part.
                sure = all(each.person in step.persons for each in before)
                how = "unknown action"
                if after == frozenset({aboard}):
                    how = "carried"
                elif taker is not None:
                    how = "handed over"
                elif world.does.get((option, thing.id)) == "keeps":
                    how = "kept" if sure else "kept if held"
                elif goes_along(world, option, thing.id) == "might":
                    how = "unknown requirement"
                stays.append(Stay(in_order(after), option, how))
        stays += arrivals(trail[-1], None)
        carried.append(Carried(thing.id, tuple(stays), tuple(uses)))
    return tuple(carried), relied


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


def _conflict(whole: Remaining, can_work: CanWork) -> tuple[tuple[str, ...], bool]:
    """FACTs, WANTs and DECISIONs that make the TRIP INFEASIBLE by themselves.

    ``whole`` is the whole FILE, and nothing works in any best case of it. No record can be
    removed from the set returned.

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
    file, kept = whole.file, whole
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

    "Another transfer of this OBJECT" asks for something new as well, and it is counted with
    the other OPTIONs. It differs in one way: a set that holds it is not settled. The TRIP
    works with the OBJECT at hand wherever the plan needs it, and nobody has worked out
    whether another transfer can bring it there. So such a set is listed only where no
    settled set asks for as few new things, however many FACTs that one holds. It names the
    OPTIONs for which the OBJECT has to be at hand, and those that it has to stay out of.
    And "this OPTION hands the OBJECT over"
    is listed only where "this OPTION does not keep the OBJECT" is not enough in its place:
    the second is true of more FILEs. "This OPTION carries the OBJECT" is the same.

    Not every set is tried. Take two sets that differ in one FACT about what an OPTION does
    with an OBJECT, where one FACT says more than the other: whatever turns out, the one
    that says more leaves the other true. Every way the set that says more can turn out is
    a way the other set can turn out. A set is enough where a plan holds whichever way it
    turns out, so where the set that says more is not enough, the other is not either. The
    sets are made one at a time, and each comes after every set that says more than it in
    one place: ``_with_enough_of_each`` keeps to the order of the FACTs it is given, and
    the FACTs that say most are given first. So a set is tried only where each of those
    sets was enough. The sets that were enough are kept once, as they were before there
    was this short cut, and nothing else is kept. This only saves work: a FILE that says
    little about its OBJECTs has six unknown FACTs about each thing that an OPTION does.
    """
    every = unknowns(file)
    new = ("another option", "another transfer")
    facts = [unknown for unknown in every if unknown.what not in new]
    to_find = [unknown for unknown in every if unknown.what in new]
    place = {unknown: number for number, unknown in enumerate(facts)}
    by_a_lock, at_least_by_a_lock = _asked_by_a_lock(file)
    for count in range(len(to_find) + 1):
        # Asking for these can be enough only if it is in the upper bound, where every FACT
        # helps whoever needs it. The bound only saves work: nothing is reported from it.
        hopeful = [
            some for some in combinations(to_find, count) if works(file, no_better_than(file, some))
        ]
        # The sets that are settled come first, whatever their size: those with no other
        # transfer. A set that is not settled is listed only where none of them is enough.
        settled = [some for some in hopeful if all(u.what != "another transfer" for u in some)]
        for those in (settled, [some for some in hopeful if some not in settled]):
            # What every set has to hold, for each choice of new things: what the LOCKs ask,
            # and what the OBJECTs ask of the sets that come with those new things.
            asked: list[tuple[frozenset[Unknown], list[tuple[frozenset[Unknown], int]]]] = []
            for some in those:
                groups = _asked_of_objects(file, works, some)
                alone_in_one = (unknown for group in groups if len(group) == 1 for unknown in group)
                several = [(group, 1) for group in groups if len(group) > 1]
                asked.append((by_a_lock.union(alone_in_one), [*at_least_by_a_lock, *several]))
            fewest = [len(held) + sum(number for _, number in groups) for held, groups in asked]
            for size in range(min(fewest, default=0), len(facts) + 1 if those else 0):
                # The sets of this size that are enough, each with where a report lists it:
                # in the order of its FACTs, as if every set had been tried, and then in
                # the order of the new things.
                # They are kept by the new things and the FACTs, so that the same collection
                # tells whether a set that says more was enough.
                found: dict[
                    tuple[int, frozenset[Unknown]], tuple[list[int], tuple[Unknown, ...]]
                ] = {}
                for number, (some, (in_every_set, at_least)) in enumerate(
                    zip(those, asked, strict=True)
                ):
                    if size < fewest[number]:
                        continue
                    # The FACTs that say most come first. Then a set comes only after each
                    # set that says more than it in one place.
                    others = sorted(
                        (unknown for unknown in facts if unknown not in in_every_set),
                        key=lambda unknown: len(_more_than(unknown.what)),
                    )
                    for more in _with_enough_of_each(others, at_least, size - len(in_every_set)):
                        stated = sorted((*in_every_set, *more), key=place.__getitem__)
                        if not one_way_each(stated):
                            continue
                        if not all(
                            (number, stronger) in found for stronger in _saying_more(stated, place)
                        ) or not works(file, with_these_at_best(file, (*stated, *some))):
                            continue
                        listed = [place[fact] for fact in stated]
                        found[number, frozenset(stated)] = (listed, (*stated, *some))
                enough = [
                    named
                    for _, (_, named) in sorted(
                        found.items(), key=lambda each: (each[1][0], each[0][0])
                    )
                ]
                if enough:
                    alone = count + size == 1
                    return tuple(
                        tuple(
                            Missing(
                                u,
                                _limit(file, u, works) if alone else None,
                                bought,
                                _most_required(file, u, works) if alone else None,
                                _to_bring(file, some, u, shown),
                            )
                            for u, bought in zip(some, _bought(file, some, shown), strict=True)
                        )
                        for some in _worth_listing(enough)
                    )
    raise AssertionError("the best case works, so some unknown FACTs make it work")


def _worth_listing(enough: Sequence[tuple[Unknown, ...]]) -> list[tuple[Unknown, ...]]:
    """The sets a report lists, of the sets of one size that are enough. The order stays.

    A set is left out where the same set is enough with a FACT that says less in the place
    of one of its FACTs about what an OPTION does with an OBJECT. ``_SAYS_MORE_THAN`` says
    which FACT says more than which: whatever turns out, the one that says more leaves the
    other true.
    """

    def with_less(some: tuple[Unknown, ...], asked: Unknown, what: str) -> tuple[Unknown, ...]:
        return tuple(replace(u, what=what) if u == asked else u for u in some)

    found = set(enough)
    return [
        some
        for some in enough
        if not any(
            with_less(some, u, what) in found
            for u in some
            for what in _SAYS_MORE_THAN.get(u.what, ())
        )
    ]


# About what an OPTION does with an OBJECT: each unknown FACT, with those that say less. An
# OPTION that hands the OBJECT over neither keeps it nor carries it. One that keeps it does
# not carry it, and one that carries it does not keep it.
_SAYS_MORE_THAN = {
    "hands over": ("does not keep or carry", "does not keep", "does not carry"),
    "does not keep or carry": ("does not keep", "does not carry"),
    "keeps": ("does not carry",),
    "carries": ("does not keep",),
}


def _more_than(what: str) -> list[str]:
    """Each unknown FACT about what an OPTION does with an OBJECT that says more than this.

    A FACT that says more than another has fewer of these: whatever says more than it says
    more than the other too.
    """
    return [more for more, less in _SAYS_MORE_THAN.items() if what in less]


def _saying_more(
    some: Sequence[Unknown], listed: Container[Unknown]
) -> Iterator[frozenset[Unknown]]:
    """The same set with a FACT that says more in the place of one of its FACTs, each way.

    Only an unknown FACT of the FILE takes the place: ``listed`` holds those.
    """
    for asked in some:
        for what in _more_than(asked.what):
            more = replace(asked, what=what)
            if more in listed:
                yield frozenset(more if u == asked else u for u in some)


def _to_bring(
    file: File, enough: Sequence[Unknown], unknown: Unknown, shown: Shown
) -> tuple[tuple[str, str, bool, bool], ...]:
    """For another transfer of an OBJECT, each check of the OBJECT that the plan has to pass.

    They are read off the ITINERARY shown in the world where the set turns out well and every
    other unknown FACT badly, in the order of its steps. Each OPTION that requires the
    OBJECT there is a check, "requires": the OBJECT has to be at hand. Each OPTION that
    refuses it there is a check, "refuses": no PERSON may have the OBJECT in it. So is each
    OPTION that needs a right for the OBJECT where nothing covers it, "needs a right for".
    An OPTION where only a place of an OFFER could cover it is the same where the plan
    takes no place there: the plan counts on the OBJECT being out of the OPTION.
    With each comes whether a FACT says that the OPTION requires or refuses the OBJECT, or
    needs the right, and whether
    the check holds in the same plan without another transfer: with what the FILE lists,
    and everything else as in that world. Any other FACT has none.

    Where the OBJECT is in that plan is worked out from what the FILE lists. The plan has no
    hand-over and no chosen carry of the OBJECT: another transfer brings it. An OPTION
    that requires the OBJECT and carries it still takes it along, from each place where it
    is at hand, and it lies where that OPTION ends once it is over. An OPTION that a FACT
    says refuses the OBJECT takes it from no PERSON. One that only might refuse it is
    different: if it does not, it keeps the OBJECT from a PERSON who brings it in, where it
    keeps the OBJECT, and it takes the OBJECT along from that PERSON, where it takes it
    along. So the OBJECT might be in either place afterwards, and a check holds only where
    it holds in both.
    """
    if unknown.what != "another transfer":
        return ()
    thing = unknown.about or ""
    world = with_these_at_best(file, enough)
    plan = shown(file, world)
    if plan is None:
        raise AssertionError("a set of unknown FACTs that is enough shows no ITINERARY")
    might_refuse = {
        pair
        for pair in world.refuses
        if pair[1] == thing and file.refuses_object(*pair) is not True
    }
    does = dict(world.does)
    for pair in might_refuse:
        if does.get(pair) == "keeps":
            does[pair] = "might_keep"
        elif goes_along(world, *pair) == "sure":
            does[pair] = "carries_unless_refused"
    listed_only = replace(
        world, brought=world.brought - {thing}, refuses=world.refuses - might_refuse, does=does
    )
    steps = [step for step in plan if step.option is not None]
    placed = taking_a_place(file, world, plan)
    checks: list[tuple[str, str, bool, bool]] = []
    # Where the OBJECT might be just before each OPTION of the plan starts.
    for before, step in zip(just_before(file, listed_only, plan)[thing], steps, strict=True):
        option = step.option or ""
        if (option, thing) in world.needs:
            stated = file.requires_object(option, thing) is True
            holds = within_reach(before, step.persons, step.origin)
            checks.append((option, "requires", stated, holds))
        if (option, thing) in world.refuses:
            stated = file.refuses_object(option, thing) is True
            holds = not brought_in(before, step.persons)
            checks.append((option, "refuses", stated, holds))
        no_place = (option, thing) in world.offered and thing not in placed.get(option, {})
        if (option, thing) in world.uncovered or no_place:
            # Nothing covers the OBJECT there, so no PERSON who takes part may have it:
            # another transfer has to leave it where it needs no right.
            stated = file.needs_right_for(option, thing) is True
            holds = not brought_in(before, step.persons)
            checks.append((option, "needs a right for", stated, holds))
    return tuple(checks)


def _bought(file: File, enough: Sequence[Unknown], shown: Shown) -> list[tuple[Cover, ...]]:
    """For each FACT of a set that is enough, who buys which place because of it.

    The places are those of the ITINERARY shown in the world where the set turns out well and
    every other unknown FACT badly. A price is about the places of its OFFER. That a BUDGET
    can pay for a PERSON is about the places that PERSON takes and has to pay for there: at
    a price above nothing, or at a price that nobody knows and that the set does not ask
    for. A price the set asks for turns out well, and that place goes with the price. That
    a BUDGET can pay for an OBJECT is about the places that cover that OBJECT, in the same
    way. Any other FACT has none, and a set that asks nothing about money is not searched.
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
            # The FACT names a PERSON or an OBJECT, and a place is for one of the two.
            asked = (unknown.person, unknown.about)
            bought.append(tuple(cover for cover in to_pay if (cover.person, cover.object) == asked))
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
    if len(enough) == 1 and enough[0].of == "one":
        # The plan is one that works at the most the OPTION can require.
        world = with_one_required(file, unknowns[0])
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
        sure = sum(c.price.units for c in mine if c.price and right_needed(file, c) is True)
        most = sum(c.price.units for c in bought_if_needed(file, mine) if c.price)
        named = tuple(booking for booking, _ in might if booking in asked)
        besides = sum(units or 0 for booking, units in might if booking not in named)
        left = cap.limit.units - paid - besides - sure - most
        unpriced = [
            cover
            for cover in covers
            if cover.to_buy and cover.price is None and cover.object is not None
        ]
        left_for = tuple(
            (offer, each)
            for offer in dict.fromkeys(cover.by for cover in unpriced)
            if (each := _each_can_cost(mine, [c for c in unpriced if c.by == offer], left))
            is not None
        )
        rows.append(CapRow(cap.id, paid, might, named, sure, most, left, left_for))
    return tuple(rows)


def _each_can_cost(priced: Sequence[Cover], places: Sequence[Cover], left: int) -> int | None:
    """What each place of one OFFER with no price can cost, where a cap leaves more for it
    than an equal share of what it has left.

    ``priced`` are the purchases that the cap counts, ``places`` the places that the plan
    takes of the OFFER, each for an OBJECT, and ``left`` what the cap has left. One price
    holds for every place of the OFFER. Of an OBJECT that takes places in one set of
    OPTIONs or in another, the cap counts the set that costs the most. So a place adds
    nothing until its own sets cost as much as the dearest one. The result is the highest
    price at which the cap still holds, in whole ten-thousandths. None: that is no more
    than what is left, shared equally among the places.
    """
    if left < 0 or not any(place.together for place in places):
        return None

    def added(price: int) -> int:
        """What the cap counts more once each of the places has this price."""
        more = 0
        for place in places:
            theirs = [cover for cover in priced if cover.object == place.object]
            costs = [
                sum(c.price.units for c in theirs if c.price and c.option in some)
                for some in place.together
            ]
            with_it = [
                cost + price * (place.option in some)
                for cost, some in zip(costs, place.together, strict=True)
            ]
            more += max(with_it) - max(costs) if costs else price
        return more

    # The highest price that still fits: what is added only grows with the price.
    fits, too_much = 0, left + sum(cover.price.units for cover in priced if cover.price) + 1
    while too_much - fits > 1:
        price = (fits + too_much) // 2
        fits, too_much = (price, too_much) if added(price) <= left else (fits, price)
    return fits if fits > left // len(places) else None


def bought_if_needed(file: File, covers: Sequence[Cover]) -> list[Cover]:
    """The purchases among these that make up the most they can cost, besides the sure ones.

    The purchases are in one currency. One is sure where the FILE says that its right is
    needed. The others are made only if an OPTION turns out to need a right, or if an
    OBJECT turns out to be there. They are separate, so the most they can cost is their
    sum. An OBJECT that takes places in one set of OPTIONs or in another is different. It
    takes the places of one set, so its purchases count for the set that costs the most,
    and for the first such set.
    """
    open_ones = [cover for cover in covers if right_needed(file, cover) is None]
    counted = [cover for cover in open_ones if not cover.together]
    for thing in dict.fromkeys(cover.object for cover in covers if cover.together):
        theirs = [cover for cover in covers if cover.object == thing]
        sets = theirs[0].together
        costs = [
            sum(c.price.units for c in theirs if c.price and c.option in some) for some in sets
        ]
        worst = sets[costs.index(max(costs))]
        counted += [cover for cover in open_ones if cover.object == thing and cover.option in worst]
    return [cover for cover in open_ones if cover in counted]


def right_needed(file: File, cover: Cover) -> bool | None:
    """Whether the right that a place gives is needed, as the FILE says. None: nobody knows.

    For a PERSON that is whether the OPTION needs a right. For an OBJECT it is whether the
    OPTION needs a right for the OBJECT. Nobody knows either where the OBJECT only might be
    in the OPTION.
    """
    if cover.object is not None:
        return None if cover.might else file.needs_right_for(cover.option, cover.object)
    return file.needs_right(cover.option)


def _with_enough_of_each(
    facts: Sequence[Unknown], at_least: Sequence[tuple[frozenset[Unknown], int]], size: int
) -> Iterator[tuple[Unknown, ...]]:
    """Every way to pick so many FACTs with at least a stated number from each group.

    No group shares a FACT with another. Only the picks that qualify are made: a pick takes
    from a group no more than the later groups leave room for. So a FILE with many FACTs
    outside the groups costs nothing for the sizes that the groups rule out.

    The picks are made one at a time, and they keep to the order of ``facts``. Take a pick,
    and put a FACT that comes earlier in ``facts`` in the place of one of its FACTs, from
    the same group or, like it, from no group. That pick comes first. The groups are gone
    through in their order, and then the FACTs of no group: what is picked from the first
    counts most. From one group, the picks of one number of FACTs come in the order of
    ``combinations``. The other pick takes as many from each group, takes the same from
    every other group, and comes earlier among the picks of that number from that one.
    """
    grouped = frozenset[Unknown]().union(*(group for group, _ in at_least))
    inside = [[fact for fact in facts if fact in group] for group, _ in at_least]
    outside = [fact for fact in facts if fact not in grouped]
    owed = [sum(number for _, number in at_least[index:]) for index in range(len(at_least) + 1)]

    def from_part(index: int, left: int) -> Iterator[tuple[Unknown, ...]]:
        """Each pick from one group, or from the FACTs of no group after the last one."""
        if index == len(at_least):
            return combinations(outside, left)
        most = min(len(inside[index]), left - owed[index + 1])
        counts = range(at_least[index][1], most + 1)
        return chain.from_iterable(combinations(inside[index], count) for count in counts)

    # One part after another, with no call inside a call: the picks so far, how many FACTs
    # are still to pick after each, and what is still to try from each part.
    picked: list[tuple[Unknown, ...]] = []
    left = [size]
    to_try = [from_part(0, size)]
    while to_try:
        chosen = next(to_try[-1], None)
        if chosen is None:
            to_try.pop()
            left.pop()
            if picked:
                picked.pop()
        elif len(to_try) > len(at_least):
            yield tuple(fact for part in (*picked, chosen) for fact in part)
        else:
            picked.append(chosen)
            left.append(left[-1] - len(chosen))
            to_try.append(from_part(len(to_try), left[-1]))


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

    A LOCKed OPTION that requires a CAPABILITY of each PERSON asks that each PERSON the LOCK
    names has it. Where the FILE does not say whether one of them has, every set holds that
    they do. And where a FACT says that one of them does not have a CAPABILITY, and the FILE
    does not say what the OPTION requires of it, every set holds what it requires: at its
    worst that is of each PERSON.

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
        for capability in file.capabilities:
            of = file.requires(option, capability.id)
            for person in file.persons:
                if person.id not in persons:
                    continue
                has = file.has(person.id, capability.id)
                if of == "each" and has is None:
                    asked.add(Unknown("has", person=person.id, about=capability.id))
                if of is None and has is False:
                    asked.add(Unknown("requirement", option, about=capability.id))
        without = [person for person in persons if file.booking(option, person) is None]
        short = len(without) - file.places_on_offer(option)
        if file.needs_right(option) is None and short > 0:
            asked.add(Unknown("needs no right", option))
        if file.needs_right(option) and file.rights_complete(option) is None and short > 0:
            rights = (Unknown("another right", option, person=person) for person in without)
            at_least.append((frozenset(rights), short))
    return frozenset(asked), at_least


def _asked_of_objects(
    file: File, works: Works, some: Sequence[Unknown]
) -> list[frozenset[Unknown]]:
    """What the OBJECTs ask of every set of unknown FACTs that is enough with these new things.

    ``some`` holds conditions for another OPTION and other transfers. The sets meant are
    those that hold them and no other new thing. The result is groups of unknown FACTs:
    every such set holds one FACT at least of each group, and no two groups share a FACT.

    Three things can be unknown about an OPTION and an OBJECT: whether the OPTION requires
    the OBJECT, whether it refuses it, and what it does with it. Each has its unknown FACTs:
    that the OPTION does not require the OBJECT, that it does not refuse it, and the six
    about what it does. A set that holds none of them leaves the thing at its worst: the
    OPTION requires the OBJECT, or refuses it, or hands nothing over, carries nothing by
    choice and might keep the OBJECT. Where it requires the OBJECT, it might take it along
    as well. Where only what it does is at its worst here, and the bound has it not require
    the OBJECT, it might keep it and no more. That asks less of a plan than any set that
    leaves both unknown, so nothing that such a set allows is lost.

    A fourth thing can be unknown about an OPTION and an OBJECT: whether a right is needed
    there and something covers the OBJECT. Its unknown FACT is that the OPTION needs no
    right for the OBJECT, or that another right covers it, whichever the FILE leaves open.
    A set that holds neither leaves the OBJECT with no right there, or with a place of an
    OFFER for the OPTION that names it and nothing else.

    Some of those things are tested together in the upper bound of ``no_better_than``,
    where every unknown FACT helps whoever needs it: there each of them is put at its
    worst. Where nothing works then, no set without a FACT of theirs is enough. Such a set
    leaves them all at their worst, and everything else in it turns out no better than in
    the bound. So every set that is enough holds one of their FACTs.

    The groups are found one after another. All the things that are left are tested
    together. Where nothing works, they are taken out one at a time, in the FILE's order,
    as long as nothing works without them. What stays is a group that nothing can leave,
    and the search goes on with the things outside it. A group of one FACT is a FACT that
    every set holds. Something works in the bound as it is: the search asks only about
    new things that can be enough. So no group is empty.

    This only saves work. A FILE that says little about its OBJECTs has many unknown FACTs
    about them, and the sets of a size are too many to try one by one.
    """
    bound = no_better_than(file, some)
    kinds = {"does not require": "requires", "does not refuse": "refuses"}
    about_doing = ("keeps", "does not keep", "does not carry", "does not keep or carry")
    kinds.update(dict.fromkeys((*about_doing, "hands over", "carries"), "does"))
    kinds.update(dict.fromkeys(("needs no right for", "another right for"), "right"))
    # Each thing that is unknown, with its unknown FACTs: an OPTION, an OBJECT and a kind.
    facts: dict[tuple[str, str, str], list[Unknown]] = {}
    for unknown in unknowns(file):
        if unknown.what in kinds and unknown.option is not None and unknown.about is not None:
            thing = (unknown.option, unknown.about, kinds[unknown.what])
            facts.setdefault(thing, []).append(unknown)

    def nothing_works(group: Sequence[tuple[str, str, str]]) -> bool:
        """Whether nothing works in the bound with each of these things at its worst."""
        needs = {(option, about) for option, about, kind in group if kind == "requires"}
        refuses = {(option, about) for option, about, kind in group if kind == "refuses"}
        open_to_do = {(option, about) for option, about, kind in group if kind == "does"}
        no_right = {(option, about) for option, about, kind in group if kind == "right"}
        required = bound.needs | needs
        # At its worst, an OPTION that requires the OBJECT might keep it or take it along.
        # Whether anything works does not turn on how sure the requirement is: a plan can
        # choose the carry that a sure requirement would make.
        worst = {pair: "might_take" if pair in required else "might_keep" for pair in open_to_do}
        on_offer = {pair for pair in no_right if file.offers_for(*pair)}
        harder = replace(
            bound,
            needs=required,
            refuses=bound.refuses | refuses,
            does={**bound.does, **worst},
            ticketed=bound.ticketed | no_right,
            uncovered=bound.uncovered | (no_right - on_offer),
            offered=bound.offered | on_offer,
        )
        return not works(file, harder)

    groups: list[frozenset[Unknown]] = []
    left = list(facts)
    while left and nothing_works(left):
        group = left
        for thing in left:
            fewer = [each for each in group if each != thing]
            if nothing_works(fewer):
                group = fewer
        if not group:
            raise AssertionError("nothing works in the upper bound, so no set is enough")
        groups.append(frozenset(unknown for thing in group for unknown in facts[thing]))
        left = [each for each in left if each not in group]
    return groups


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


def _most_required(file: File, unknown: Unknown, works: Works) -> str | None:
    """The most that one OPTION can require of a CAPABILITY for the TRIP to work.

    "one" where the TRIP works with the OPTION requiring it of one PERSON and every other
    unknown FACT at its worst, and "none" where it works only if the OPTION requires nothing.
    None for an unknown that is not what an OPTION requires.
    """
    if unknown.what != "requirement":
        return None
    return "one" if works(file, with_one_required(file, unknown)) else "none"


def _limit(file: File, unknown: Unknown, works: Works) -> int | None:
    """The most seconds this one unknown can be for the TRIP to work.

    None for an unknown that is not a length of time, and None when any length would do.
    """
    no_length = ("start", "satisfies", "does not satisfy", "another option")
    no_length += ("requirement", "has", "does not require", "does not refuse", "keeps")
    no_length += ("does not keep", "does not carry", "does not keep or carry", "carries")
    no_length += ("hands over", "starts with", "starts at", "another transfer")
    about_rights = ("needs no right", "another right", "price", "funding", "charged")
    about_rights += ("needs no right for", "another right for")
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
