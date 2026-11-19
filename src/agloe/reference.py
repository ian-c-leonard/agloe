"""The reference checker: the rules of spec/rules.md applied directly, with no solver.

It is slow on purpose and meant for small TRIPs. It defines the right answer, and anything faster
must agree with it. It refuses an ITINERARY too large for it to try everything.

Read it beside spec/rules.md. The worlds are the section "What is unknown". No world here has
an unlisted WAY that SATISFIES a WANT, and the answers do not need one. In the best case another
OPTION already meets every must on a WANT whose set is not COMPLETE, no unlisted WAY SATISFIES a
WANT whose set is COMPLETE, and none has to break a must-not. The worst case has no unlisted WAY
at all.

``broken`` is the section "The CONSTRAINTs": it checks a finished ITINERARY against all of
them, and nothing here or in the solver counts as working unless it passes. ``itineraries`` is the
section "Which ITINERARY is shown". The sections "The three answers", "ROBUST" and "Evidence"
are in ``answers``, which works them out from this module's search or from a faster one.
"""

from collections import deque
from collections.abc import Iterable, Iterator, Mapping, Sequence, Sized
from dataclasses import dataclass, field, replace
from enum import Enum
from heapq import heapify, heappop, heappush
from itertools import combinations, groupby, pairwise, permutations, product

from agloe.file import Booking, Complete, File, Offer, Satisfies, StartsFrom, Want

_MOST_TO_TAKE_OUT = 12  # ``needless`` tries every combination of things to take out


class Constraint(Enum):
    """The CONSTRAINTs, named by their headings in spec/rules.md."""

    LOCK = "LOCKs are honored"
    START = "Each OPTION starts when it can"
    DURATION = "Each OPTION and WAY takes as long as it takes"
    PLACE = "Each PERSON is in one place at a time"
    ARRIVAL = "Each PERSON arrives in time"
    LISTED = "A COMPLETE set is the whole set"
    MUST = "Every must is met"
    MUST_NOT = "Every must-not is kept"
    WITHIN = "Everything happens within the TRIP"
    RIGHT = "Each PERSON has the rights they need"
    PAID = "Each place is paid for"
    CAP = "No cap is passed"


@dataclass(frozen=True)
class Step:
    """One thing in an ITINERARY: an OPTION that happens, or a WAY that PERSONs take.

    ``option`` names an OPTION. Otherwise the step is a WAY: ``way`` names a listed one, and both
    are None for a WAY the FILE does not list. ``end`` follows from the duration, and is None when
    nobody knows how long the step takes.
    """

    option: str | None
    origin: str
    destination: str
    persons: tuple[str, ...]
    start: int
    end: int | None
    way: str | None = None


type Itinerary = tuple[Step, ...]
type Leg = tuple[str | None, str, str]  # a WAY, or None for an unlisted one; from; to


@dataclass(frozen=True)
class Broken:
    """A CONSTRAINT an ITINERARY does not meet: at which step, for whom, by how many seconds.

    ``option`` names the OPTION where it happens. Where it happens at a WAY, ``option`` is None
    and ``step`` is the position of that step in the ITINERARY, counting from zero.

    A must that is not met happens at no step. Then ``want`` names the WANT, and ``option`` and
    ``step`` are both None. A must-not that is broken names the WANT and the OPTION that
    SATISFIES it.

    A cap that is passed happens at no step and names no PERSON. ``cap`` names the DECISION
    where what the BOOKINGs charged passes it by itself. It is None where every way to pay
    for the places of the ITINERARY passes some cap: no single cap is the one.
    """

    constraint: Constraint
    option: str | None
    persons: tuple[str, ...]
    late: int | None = None
    step: int | None = None
    want: str | None = None
    cap: str | None = None


@dataclass(frozen=True)
class Terms:
    """What a world says about one OPTION.

    With no ``fixed_start``, ``free_start`` says whether it can start at any time; if not, nobody
    knows when it starts. ``longest`` is None when there is no limit to how long it can take.
    ``margin`` is the access cutoff, and None when there is no limit to how early a PERSON must
    arrive.
    """

    fixed_start: int | None
    free_start: bool
    shortest: int
    longest: int | None
    margin: int | None


@dataclass(frozen=True)
class World:
    """One way the unknown FACTs turn out, or the worst of all the ways at once.

    ``no_better_than`` makes a third kind, an upper bound that is no possible world at all.

    ``unlisted`` holds the pairs of PLACEs that an unlisted WAY joins directly, and None means
    every pair. Each unlisted WAY takes ``unlisted_takes`` seconds. ``takes`` gives the shortest
    and the longest time of each listed WAY, and the longest is None when there is no limit.

    ``satisfies`` holds each OPTION and WANT where the OPTION SATISFIES the WANT, and a must can
    count on it. ``might_satisfy`` holds each OPTION and WANT where it SATISFIES the WANT or
    nobody knows, and a must-not has to stay clear of it. In one possible world the two are the
    same. In the worst of all the ways at once they differ: an OPTION with no FACT about a WANT
    is only in the second. ``another_option`` holds each WANT and PERSON for whom another
    OPTION is found: one outside the FILE that SATISFIES the WANT, and that the PERSON can take
    part in whatever else they do. It holds conditions, one for each WANT and PERSON. It does
    not say how many OPTIONs meet them: one OPTION can be found for several.

    ``needs_right`` holds each OPTION that a PERSON can take part in only with a right.
    ``rights`` holds each OPTION and PERSON where the PERSON has one: a BOOKING covers them, or
    another right is found for them. ``places`` says how many more PERSONs can take part in an
    OPTION that needs a right: each takes one place of an OFFER. ``payable`` holds each OFFER
    and PERSON where the PERSON can pay for a place of it: the place costs nothing, or a
    BUDGET that lists the PERSON holds the currency of its price.

    ``spent`` says, for each cap by its BUDGET and currency, the most that the BOOKINGs might
    have charged to it in ten-thousandths. None: no upper bound. Each cap has its own sum, so
    the sums of the worst case need not be true together.
    """

    terms: Mapping[str, Terms]
    unlisted: frozenset[tuple[str, str]] | None
    unlisted_takes: int = 0
    takes: Mapping[str, tuple[int, int | None]] = field(
        default_factory=dict[str, tuple[int, int | None]]
    )
    satisfies: frozenset[tuple[str, str]] = frozenset()
    might_satisfy: frozenset[tuple[str, str]] = frozenset()
    another_option: frozenset[tuple[str, str]] = frozenset()
    needs_right: frozenset[str] = frozenset()
    rights: frozenset[tuple[str, str]] = frozenset()
    places: Mapping[str, int] = field(default_factory=dict[str, int])
    payable: frozenset[tuple[str, str]] = frozenset()
    spent: Mapping[tuple[str, str], int | None] = field(
        default_factory=dict[tuple[str, str], int | None]
    )


@dataclass(frozen=True)
class Unknown:
    """A FACT the FILE does not state.

    ``what`` is "start", "duration" or "cutoff" for an OPTION, "duration" for a WAY, or "other
    ways" from one PLACE to another: unlisted WAYs that go straight there. For an OPTION and a
    WANT it is "satisfies" or "does not satisfy": the two ways the one unknown can turn out.
    For an OPTION it is also "needs no right", and for an OPTION and a PERSON "another right":
    a right to the OPTION for that PERSON that no BOOKING in the FILE secures. It
    is "another option" for a WANT and a PERSON: an OPTION outside the FILE
    that SATISFIES the WANT, and that the PERSON can take part in. That is one condition for one
    WANT and one PERSON, whichever OPTION meets it.
    """

    what: str
    option: str | None = None
    origin: str | None = None
    destination: str | None = None
    way: str | None = None
    want: str | None = None
    person: str | None = None
    about: str | None = None


# ------------------------------- What is unknown -------------------------------


def unknowns(file: File) -> tuple[Unknown, ...]:
    """Every FACT the FILE leaves out that could help, in the order of the rules page.

    That an OPTION SATISFIES a WANT can help only where the WANT is a must for some PERSON,
    and that it does not only where the WANT is a must-not for some PERSON. So only those are
    listed. Where a FACT says a WANT's set is COMPLETE, nothing about the WANT is unknown.
    A price and who pays can help only where somebody might have to pay for a place. So a
    price is listed only for an OFFER that ``for_sale`` gives, and who pays only for a PERSON
    with no BOOKING for the OPTION of one of those.
    """
    sold = for_sale(file)
    to_pay = {offer.id for offer in sold}
    buyers = [
        person.id
        for person in file.persons
        if any(file.booking(offer.option, person.id) is None for offer in sold)
    ]
    musts = [
        want
        for want in file.wants
        if want.musts and want.ends_at is None and file.complete_for(want.id) is None
    ]
    out: list[Unknown] = []
    for option in file.options:
        if file.start(option.id) is None:
            out.append(Unknown("start", option.id))
        if file.duration(option.id) is None:
            out.append(Unknown("duration", option.id))
        if file.cutoff(option.id) is None:
            out.append(Unknown("cutoff", option.id))
        if file.needs_right(option.id) is None:
            out.append(Unknown("needs no right", option.id))
        if file.needs_right(option.id) is True and file.rights_complete(option.id) is None:
            for person in file.persons:
                if file.booking(option.id, person.id) is None:
                    out.append(Unknown("another right", option.id, person=person.id))
        for offer in file.offers(option.id):
            if offer.price is None and offer.id in to_pay:
                out.append(Unknown("price", option.id, about=offer.id))
        for booking in file.bookings(option.id):
            if file.charge_is_open(booking):
                out.append(Unknown("charged", option.id, about=booking.id))
        for want in file.wants:
            if file.says(option.id, want.id) is None:
                if want.musts:
                    out.append(Unknown("satisfies", option.id, want=want.id))
                if want.must_nots:
                    out.append(Unknown("does not satisfy", option.id, want=want.id))
    for way in file.ways:
        if file.duration(way.id) is None:
            out.append(Unknown("duration", way=way.id))
    for origin in file.places:
        for destination in file.places:
            if origin != destination:
                out.append(Unknown("other ways", origin=origin.id, destination=destination.id))
    for person in buyers:
        if not file.listed(person):
            out.append(Unknown("funding", person=person))
    for want in musts:
        for person in _in_file_order_of_persons(file, want.musts):
            out.append(Unknown("another option", want=want.id, person=person))
    return tuple(out)


def for_sale(file: File) -> list[Offer]:
    """The OFFERs with a place that somebody might have to pay for.

    Only a PERSON with no BOOKING for an OPTION takes a place of it. An OFFER is left out
    where its price is nothing, where a FACT says its OPTION needs no right, and where the
    OPTION has a place that costs nothing for each of those PERSONs: nobody has to pay then.
    """
    sold: list[Offer] = []
    for option in file.options:
        offers = file.offers(option.id)
        free = sum(
            each.places for each in offers if each.price is not None and not each.price.amount
        )
        buyers = sum(file.booking(option.id, person.id) is None for person in file.persons)
        if file.needs_right(option.id) is not False and free < buyers:
            sold += [each for each in offers if each.price is None or each.price.amount]
    return sold


def has_to_end_at(file: File, person: str) -> list[Want]:
    """The WANTs to end the TRIP at a PLACE that are a must for this PERSON."""
    return [want for want in file.wants if want.ends_at is not None and person in want.musts]


def best_case(file: File) -> World:
    """The possible world in which every unknown FACT turns out as well as it can."""
    return _world(file, None)


@dataclass(frozen=True)
class Remaining:
    """What is left of a FILE while a conflict is looked for: the FILE with records taken out.

    Taking a FACT out makes what it stated unknown. That is more than leaving the FACT out.
    Where a FACT says a WANT's set is COMPLETE, an OPTION with no FACT about the WANT does not
    SATISFY it. An OPTION whose FACT about the WANT was taken out might. ``unsaid`` holds each
    such OPTION and WANT. A BOOKING that is taken out is the same: nobody knows whom it covers,
    so it might cover anybody. ``open_to_all`` holds the OPTION of each such BOOKING. Both
    belong to the search for a conflict: no FILE that is read has them, and no answer is ever
    given for what is left.
    """

    file: File
    unsaid: frozenset[tuple[str, str]] = frozenset()
    open_to_all: frozenset[str] = frozenset()

    def without(self, record: str) -> Remaining:
        """What is left with one more FACT, WANT or DECISION taken out."""
        found = [fact for fact in self.file.facts if fact.id == record]
        taken = {(fact.option, fact.want) for fact in found if isinstance(fact, Satisfies)}
        opened = {fact.option for fact in found if isinstance(fact, Booking | Offer)}
        return Remaining(self.file.without(record), self.unsaid | taken, self.open_to_all | opened)

    def might_cover(self) -> frozenset[tuple[str, str]]:
        """Each OPTION and PERSON that a BOOKING taken out might cover: anybody, for its OPTION."""
        people = self.file.persons
        return frozenset((option, person.id) for option in self.open_to_all for person in people)

    def reopened(self) -> list[tuple[str, str]]:
        """Each OPTION and WANT that nobody knows about though the WANT's set is COMPLETE.

        They come in the FILE's order of OPTIONs and then of WANTs.
        """
        file = self.file
        return [
            (option.id, want.id)
            for option in file.options
            for want in file.wants
            if (option.id, want.id) in self.unsaid
            and file.satisfies(option.id, want.id) is None
            and file.complete_for(want.id) is not None
        ]


def best_cases(remaining: Remaining) -> Iterator[World]:
    """Each best case of what is left of a FILE, one at a time. A FILE as it is read has one.

    In that one, an OPTION with no FACT about a WANT does not SATISFY it. That is as good as it
    gets: another OPTION meets every must on a WANT whose set is not COMPLETE, and a COMPLETE
    set leaves nothing unknown.

    An OPTION and a WANT that are reopened are different: nobody knows, and no other OPTION can
    stand in. Where the WANT is a must for some PERSON and a must-not for nobody, the best case
    is that the OPTION SATISFIES it. Where it is only a must-not, the best case is that it does
    not. Where it is both, a must may need what a must-not fears, so each way it could turn out
    is a best case of its own. Only those are tried both ways.
    """
    file = remaining.file
    best = best_case(file)
    best = replace(best, rights=best.rights | remaining.might_cover())
    wants = {want.id: want for want in file.wants}
    helps = {pair for pair in remaining.reopened() if not wants[pair[1]].must_nots}
    helps = {pair for pair in helps if wants[pair[1]].musts}
    either = [
        pair for pair in remaining.reopened() if wants[pair[1]].musts and wants[pair[1]].must_nots
    ]
    for chosen in product([False, True], repeat=len(either)):
        does = helps | {pair for pair, yes in zip(either, chosen, strict=True) if yes}
        yield replace(
            best, satisfies=best.satisfies | does, might_satisfy=best.might_satisfy | does
        )


def with_no_offer(world: World) -> World:
    """The same world with every OFFER left out: what works here takes no place of one."""
    return replace(world, places={}, payable=frozenset())


def worst_case(file: File) -> World:
    """Every unknown FACT at its worst. What works here works in every possible world."""
    return _world(file, frozenset())


def longest_case(file: File) -> World:
    """The worst case, with every CONTINGENT duration at its longest value."""
    return _world(file, frozenset(), longest=True)


def with_these_at_best(file: File, unknown: Iterable[Unknown]) -> World:
    """These unknown FACTs turned out well, and every other unknown FACT as in the worst case.

    A start, a length of time, other WAYs and another OPTION turn out as in the best case. For
    an OPTION and a WANT, the unknown says which way it turns out: "satisfies" or "does not
    satisfy". Saying both about one OPTION and one WANT is refused: no possible world has both.
    """
    kind = frozenset(unknown)
    if not one_way_each(kind):
        raise ValueError("an OPTION cannot both SATISFY a WANT and not SATISFY it")
    return _world(file, kind)


def one_way_each(unknown: Iterable[Unknown]) -> bool:
    """Whether no two of these say opposite things about one OPTION and one WANT."""
    signed = ("satisfies", "does not satisfy")
    about = [(each.option, each.want) for each in unknown if each.what in signed]
    return len(about) == len(set(about))


def no_better_than(file: File, found: Iterable[Unknown]) -> World:
    """An upper bound that is no possible world: every unknown FACT helps whoever needs it.

    Everything is as in the best case, with two differences. Another OPTION is found only for
    the WANTs and PERSONs in ``found``. And an OPTION with no FACT about a WANT counts for a
    must while it breaks no must-not, which no possible world allows.

    Whatever works in a possible world with those other OPTIONs works here too. So this can
    show that those other OPTIONs are not enough, whatever else turns out well. It can show
    nothing else, and no answer and no evidence is ever read from it.
    """
    best = best_case(file)
    unknown = {
        (option.id, want.id)
        for option in file.options
        for want in file.wants
        if file.says(option.id, want.id) is None
    }
    conditions = frozenset(
        (each.want, each.person)
        for each in found
        if each.want is not None and each.person is not None
    )
    return replace(best, satisfies=best.satisfies | unknown, another_option=conditions)


def with_this_long(file: File, unknown: Unknown, seconds: int) -> World:
    """The worst case, except that one unknown length of time is exactly this many seconds.

    For other WAYs between two PLACEs, those WAYs exist and each takes this long.
    """
    kind = frozenset({unknown}) if unknown.what == "other ways" else frozenset[Unknown]()
    return _world(file, kind, pinned=(unknown, seconds))


def _world(
    file: File,
    kind: frozenset[Unknown] | None,
    *,
    longest: bool = False,
    pinned: tuple[Unknown, int] | None = None,
) -> World:
    """A world in which the unknowns in ``kind`` turn out well and the rest badly.

    With ``kind`` None, every unknown turns out well. ``longest`` gives every CONTINGENT duration
    its longest value. ``pinned`` gives one unknown an exact value.
    """

    def well(unknown: Unknown) -> bool:
        return kind is None or unknown in kind

    def value(unknown: Unknown) -> int | None:
        if pinned is not None and pinned[0] == unknown:
            return pinned[1]
        return 0 if well(unknown) else None

    terms: dict[str, Terms] = {}
    for option in file.options:
        start = file.start(option.id)
        duration = file.duration(option.id)
        cutoff = file.cutoff(option.id)
        if start is not None:
            fixed, free = start.at, start.at is None
        else:
            fixed, free = None, well(Unknown("start", option.id))
        if duration is not None:
            most: int | None = duration.longest
            least = duration.longest if longest else duration.shortest
        else:
            most = value(Unknown("duration", option.id))
            least = most or 0
        margin = cutoff.margin if cutoff is not None else value(Unknown("cutoff", option.id))
        terms[option.id] = Terms(fixed, free, least, most, margin)
    takes: dict[str, tuple[int, int | None]] = {}
    for way in file.ways:
        duration = file.duration(way.id)
        if duration is not None:
            takes[way.id] = (duration.longest if longest else duration.shortest, duration.longest)
        else:
            most = value(Unknown("duration", way=way.id))
            takes[way.id] = (most or 0, most)
    unlisted = None
    if kind is not None:
        unlisted = frozenset(
            (u.origin, u.destination)
            for u in kind
            if u.what == "other ways" and u.origin is not None and u.destination is not None
        )
    unlisted_takes = pinned[1] if pinned is not None and pinned[0].what == "other ways" else 0
    # Whether an OPTION SATISFIES a WANT helps a must and hurts a must-not. So an unknown one
    # counts for a must only where ``kind`` says it does, and against a must-not unless
    # ``kind`` says it does not. In the best case it does not: another OPTION meets every must
    # on a WANT whose set is not COMPLETE, and a COMPLETE set leaves nothing unknown.
    satisfies: set[tuple[str, str]] = set()
    might_satisfy: set[tuple[str, str]] = set()
    for option in file.options:
        for want in file.wants:
            pair = (option.id, want.id)
            said = file.says(*pair)
            if said is not None:
                if said:
                    satisfies.add(pair)
                    might_satisfy.add(pair)
                continue
            does = kind is not None and Unknown("satisfies", option.id, want=want.id) in kind
            does_not = kind is None or Unknown("does not satisfy", option.id, want=want.id) in kind
            if does:
                satisfies.add(pair)
            if not does_not:
                might_satisfy.add(pair)
    # Whether an OPTION needs a right, and who has one. A FACT settles the first in every
    # world. A BOOKING covers the PERSONs it names. Another right can be found only where no
    # FACT says that the rights to the OPTION are COMPLETE.
    needs_right = {
        option.id
        for option in file.options
        if file.needs_right(option.id) is True
        or (file.needs_right(option.id) is None and not well(Unknown("needs no right", option.id)))
    }
    rights = {
        (option.id, person.id)
        for option in file.options
        for person in file.persons
        if file.booking(option.id, person.id) is not None
        or (
            file.rights_complete(option.id) is None
            and well(Unknown("another right", option.id, person=person.id))
        )
    }
    another_option = frozenset(
        (want.id, person)
        for want in file.wants
        for person in want.musts
        if want.ends_at is None
        and file.complete_for(want.id) is None
        and well(Unknown("another option", want=want.id, person=person))
    )
    # Who can pay for a place of each OFFER. A price of nothing needs nobody to pay. A price
    # that nobody knows is one quote for all the places: at best nothing, at worst one that
    # no BUDGET of the FILE is sure to hold. Where no BUDGET lists a PERSON, nobody knows who
    # pays for them: at best a BUDGET that pays for whatever they take, at worst none.
    funded = {
        person.id
        for person in file.persons
        if not file.listed(person.id) and well(Unknown("funding", person=person.id))
    }
    payable: set[tuple[str, str]] = set()
    for offer in (fact for fact in file.facts if isinstance(fact, Offer)):
        price = offer.price
        if price is None:
            free = well(Unknown("price", offer.option, about=offer.id))
        else:
            free = not price.amount
        for person in file.persons:
            paid = price is not None and file.pays(person.id, price) is not None
            if free or paid or person.id in funded:
                payable.add((offer.id, person.id))
    # What the BOOKINGs might have charged to each cap. A payment that names its BUDGET is
    # charged there. One that names none might have been charged to any BUDGET that holds its
    # currency, so it counts against each cap in that currency. A BOOKING that states no
    # payment has no upper bound. Where its unknown FACT turns out well, a BOOKING charged
    # nothing to a BUDGET with a cap.
    spent: dict[tuple[str, str], int | None] = {}
    if file.caps:
        stated = dict.fromkeys(file.caps, 0)
        anywhere: dict[str, int] = {}
        no_bound = False
        for fact in file.facts:
            if not isinstance(fact, Booking):
                continue
            charged_nothing = well(Unknown("charged", fact.option, about=fact.id))
            if fact.paid is None:
                no_bound = no_bound or not charged_nothing
            elif fact.paid.budget is not None:
                key = (fact.paid.budget, fact.paid.money.currency)
                if key in stated:
                    stated[key] += fact.paid.money.units
            elif not charged_nothing:
                currency = fact.paid.money.currency
                anywhere[currency] = anywhere.get(currency, 0) + fact.paid.money.units
        for key, known in stated.items():
            spent[key] = None if no_bound else known + anywhere.get(key[1], 0)
    return World(
        terms,
        unlisted,
        unlisted_takes,
        takes,
        frozenset(satisfies),
        frozenset(might_satisfy),
        another_option,
        frozenset(needs_right),
        frozenset(rights),
        {option.id: file.places_on_offer(option.id) for option in file.options},
        frozenset(payable),
        spent,
    )


# ------------------------------- The CONSTRAINTs -------------------------------


def in_world(world: World, itinerary: Itinerary) -> Itinerary:
    """The same OPTIONs, PERSONs, WAYs and start times, with each end as this world makes it.

    An end is None when the world sets no limit to how long the step takes.
    """

    def end(step: Step) -> int | None:
        if step.option is not None:
            terms = world.terms[step.option]
            return None if terms.longest is None else step.start + terms.shortest
        if step.way is None:
            return step.start + world.unlisted_takes
        shortest, longest = world.takes[step.way]
        return None if longest is None else step.start + shortest

    return tuple(replace(step, end=end(step)) for step in itinerary)


def broken(file: File, world: World, itinerary: Itinerary) -> list[Broken]:
    """The CONSTRAINTs this ITINERARY does not meet in this world. An empty list means it works.

    Steps that take no time and share an instant can happen in any order. The order in which the
    ITINERARY lists them is tried first, then every other order. The result is that of the order
    that breaks the least.
    """
    _well_formed(file, itinerary)
    fewest: list[Broken] | None = None
    for order in _in_each_order(itinerary):
        found = _along_each_path(file, world, itinerary, order)
        if fewest is None or len(found) < len(fewest):
            fewest = found
        if not found:
            break
    return [*_each_alone(file, world, itinerary), *(fewest or [])]


def broken_as_listed(file: File, world: World, itinerary: Itinerary) -> list[Broken]:
    """The CONSTRAINTs this ITINERARY does not meet with its steps in the order it lists them.

    This says what one particular plan breaks. ``broken`` may put steps that share an instant
    in another order, and that would describe a different plan.
    """
    _well_formed(file, itinerary)
    placed = list(enumerate(itinerary))
    return [*_each_alone(file, world, itinerary), *_along_each_path(file, world, itinerary, placed)]


def works_as_listed(file: File, world: World, itinerary: Itinerary) -> bool:
    """Whether this ITINERARY meets every CONSTRAINT with its steps in the order it lists them.

    The steps must be listed in an order their times allow: earlier starts first.
    """
    in_order = all(before.start <= after.start for before, after in pairwise(itinerary))
    return in_order and not broken_as_listed(file, world, itinerary)


def _each_alone(file: File, world: World, itinerary: Itinerary) -> list[Broken]:
    """The CONSTRAINTs that hold or not whatever order the steps happen in."""
    taking_part = {step.option: step.persons for step in itinerary if step.option is not None}
    return [
        *_locks(file, itinerary),
        *_starts(world, itinerary),
        *_durations(world, itinerary),
        *_musts(file, world, taking_part),
        *_must_nots(file, world, taking_part),
        *_within(file, itinerary),
        *_rights(file, world, taking_part),
    ]


def _rights(file: File, world: World, taking_part: Mapping[str, tuple[str, ...]]) -> list[Broken]:
    """Each PERSON has the rights they need, and each place they take is paid for.

    The PERSONs with no right of their own take the places of the OPTION's OFFERs, as
    ``placed`` shares them out: as many as can pay for one have one. The others go in the
    FILE's order. Each takes a place that is still free, and cannot pay for it. Once no place
    is free, the rest have no right.
    """
    out: list[Broken] = []
    for option, persons in taking_part.items():
        if option not in world.needs_right:
            continue
        lacking = [person for person in persons if (option, person) not in world.rights]
        without = _in_file_order_of_persons(file, lacking)
        taken = placed(file, world, option, without)
        left_out = tuple(person for person in without if person not in taken)
        free = max(world.places.get(option, 0) - len(taken), 0)
        if left_out[free:]:
            out.append(Broken(Constraint.RIGHT, option, left_out[free:]))
        if left_out[:free]:
            out.append(Broken(Constraint.PAID, option, left_out[:free]))
    for key, cap in file.caps.items():
        charged = world.spent.get(key, 0)
        if charged is None or charged > cap.limit.units:
            out.append(Broken(Constraint.CAP, None, (), cap=cap.id))
    if file.caps and not out and way_to_pay(file, world, taking_part) is None:
        out.append(Broken(Constraint.CAP, None, ()))
    return out


def way_to_pay(
    file: File, world: World, taking_part: Mapping[str, Sequence[str]]
) -> dict[tuple[str, str], tuple[str, str | None]] | None:
    """The way to pay for the places these OPTIONs need, by the fixed rule, or None.

    ``taking_part`` gives the PERSONs in each OPTION, in the order of the steps. The result
    gives, for each OPTION and PERSON who takes a place, the OFFER it is from and the BUDGET
    that pays. The BUDGET is None for a place that costs nothing, and for a PERSON whom no
    BUDGET of the FILE lists. None: there is no way to pay in this world.

    With no cap in the FILE, each OPTION is by itself: ``placed`` shares out its places, and
    the first BUDGET that can pay pays. With caps, one BUDGET can run short over several
    OPTIONs, and a place that one PERSON leaves can be the only one another can pay for. So
    the purchases are taken in order, and each tries its pairs of an OFFER and a BUDGET in
    the FILE's order: the first that still fits, and that the purchases after it can follow.
    A purchase with no pair left sends the one before it on to its next pair.
    """
    buyers: list[tuple[str, str]] = []
    for option, persons in taking_part.items():
        if option in world.needs_right:
            lacking = [person for person in persons if (option, person) not in world.rights]
            buyers += [(option, person) for person in _in_file_order_of_persons(file, lacking)]
    if not file.caps:
        chosen: dict[tuple[str, str], tuple[str, str | None]] = {}
        groups: dict[str, list[str]] = {}
        for option, person in buyers:
            groups.setdefault(option, []).append(person)
        for option, group in groups.items():
            taken = placed(file, world, option, group)
            if len(taken) < len(group):
                return None
            prices = {offer.id: offer.price for offer in file.offers(option)}
            for person in group:
                price = prices[taken[person]]
                payer = None if price is None else file.pays(person, price)
                chosen[option, person] = (taken[person], None if payer is None else payer.id)
        return chosen
    room: dict[tuple[str, str], int] = {}
    for key, cap in file.caps.items():
        charged = world.spent.get(key, 0)
        if charged is None or charged > cap.limit.units:
            return None
        room[key] = cap.limit.units - charged
    # Each pair a purchase can take: the OFFER, the BUDGET, and what it draws on which cap.
    pairs: list[list[tuple[str, str | None, tuple[str, str] | None, int]]] = []
    for option, person in buyers:
        able: list[tuple[str, str | None, tuple[str, str] | None, int]] = []
        for offer in file.offers(option):
            if (offer.id, person) not in world.payable:
                continue
            price = offer.price
            sources = (
                () if price is None or not price.amount else file.payers(person, price.currency)
            )
            if price is None or not sources:
                # It costs nothing, or money from outside the FILE pays: no cap counts it.
                able.append((offer.id, None, None, 0))
                continue
            free_to_spend = False
            for budget in sources:
                key = (budget.id, price.currency)
                if key in room:
                    able.append((offer.id, budget.id, key, price.units))
                elif not free_to_spend:
                    # BUDGETs with no cap in this currency are alike: the first one pays.
                    able.append((offer.id, budget.id, None, price.units))
                    free_to_spend = True
        pairs.append(able)
    left = {offer.id: offer.places for option in taking_part for offer in file.offers(option)}
    picked: list[int] = []
    start = 0
    while len(picked) < len(buyers):
        able = pairs[len(picked)]
        found = None
        for number in range(start, len(able)):
            offer, _, key, units = able[number]
            if left[offer] and (key is None or room[key] >= units):
                found = number
                break
        if found is None:
            if not picked:
                return None
            start = picked.pop() + 1
            offer, _, key, units = pairs[len(picked)][start - 1]
            left[offer] += 1
            if key is not None:
                room[key] += units
            continue
        offer, _, key, units = able[found]
        left[offer] -= 1
        if key is not None:
            room[key] -= units
        picked.append(found)
        start = 0
    return {
        buyer: (able[number][0], able[number][1])
        for buyer, able, number in zip(buyers, pairs, picked, strict=True)
    }


def placed(file: File, world: World, option: str, persons: Sequence[str]) -> dict[str, str]:
    """The OFFER whose place each of these PERSONs takes, for as many as can have one.

    They are the PERSONs in an OPTION with no right of their own, in the FILE's order. Each
    can take only a place they can pay for, and no place is taken twice. A PERSON gets a place
    if there is a way to give one to them and to everybody before them who got one. Then each
    takes a place of the first OFFER, in the FILE's order, that leaves a way for the rest.

    This is bipartite matching, done with augmenting paths. One way to seat everybody who has
    a place is kept throughout. A PERSON finds a place by moving others along: they take a
    place, its holder takes another, and so on to a place that is free.
    """
    listed = file.offers(option)
    persons = [who for who in persons if any((each.id, who) in world.payable for each in listed)]
    offers = [
        offer for offer in listed if any((offer.id, person) in world.payable for person in persons)
    ]
    if all((offer.id, person) in world.payable for offer in offers for person in persons):
        # Each of them who can pay for a place at all can pay for every place that anybody
        # can. So the places go round in order.
        spread = (offer.id for offer in offers for _ in range(min(offer.places, len(persons))))
        return dict(zip(persons, spread, strict=False))
    room = {offer.id: offer.places for offer in offers}
    can_pay = {
        person: [offer.id for offer in offers if (offer.id, person) in world.payable]
        for person in persons
    }
    place: dict[str, str] = {}
    holders: dict[str, dict[str, None]] = {offer.id: {} for offer in offers}
    settled: set[str] = set()

    def take(person: str, offer: str) -> None:
        if person in place:
            del holders[place[person]][person]
        place[person] = offer
        holders[offer][person] = None

    def find_a_place(seekers: Sequence[str], full: str | None = None) -> bool:
        """Moves one of these PERSONs to a place that is free, or changes nothing.

        Whoever is in the way moves along, except a PERSON who is settled. Nobody moves to a
        place of the OFFER that is ``full``.
        """
        first = frozenset(seekers)
        reached: dict[str, str] = {}
        waiting = deque(seekers)
        while waiting:
            person = waiting.popleft()
            for offer in can_pay[person]:
                if offer in reached or offer == full:
                    continue
                reached[offer] = person
                if len(holders[offer]) >= room[offer]:
                    waiting.extend(each for each in holders[offer] if each not in settled)
                    continue
                while person not in first:
                    left = place[person]
                    take(person, offer)
                    offer, person = left, reached[left]
                take(person, offer)
                return True
        return False

    for person in persons:
        find_a_place([person])
    for person in persons:
        if person not in place:
            continue
        settled.add(person)
        last = place[person]
        for offer in can_pay[person]:
            if offer == last:
                break
            take(person, offer)
            if len(holders[offer]) <= room[offer]:
                break
            if find_a_place([each for each in holders[offer] if each not in settled], offer):
                break
            take(person, last)
    return {person: place[person] for person in persons if person in place}


def _within(file: File, itinerary: Itinerary) -> list[Broken]:
    """Everything happens within the TRIP: nothing starts before it starts or ends after it ends.

    A step with no end that anybody knows is not over when the TRIP ends. ``late`` is how long
    before the start of the TRIP a step starts, or how long after its end the step ends.
    """
    opens, closes = file.trip_start(), file.trip_end()
    out: list[Broken] = []
    for placed in enumerate(itinerary):
        step = placed[1]
        if opens is not None and step.start < opens.at:
            out.append(_at(Constraint.WITHIN, placed, step.persons, opens.at - step.start))
        if closes is not None and (step.end is None or step.end > closes.at):
            late = None if step.end is None else step.end - closes.at
            out.append(_at(Constraint.WITHIN, placed, step.persons, late))
    return out


def _well_formed(file: File, itinerary: Itinerary) -> None:
    """An ITINERARY names PERSONs, PLACEs, OPTIONs and WAYs from the FILE, each OPTION once."""
    persons = {person.id for person in file.persons}
    places = {place.id for place in file.places}
    options = {option.id: option for option in file.options}
    ways = {way.id: way for way in file.ways}
    listed = [step.option for step in itinerary if step.option is not None]
    if len(listed) != len(set(listed)):
        raise ValueError("an OPTION happens at most once")
    for step in itinerary:
        named_once = len(set(step.persons)) == len(step.persons)
        if not step.persons or not named_once or not persons.issuperset(step.persons):
            raise ValueError("each step needs PERSONs from the FILE, each named once")
        ends = (step.origin, step.destination)
        if step.option is not None:
            if step.way is not None or step.option not in options:
                raise ValueError(f"{step.option} is not an OPTION in the FILE")
            if ends != (options[step.option].origin, options[step.option].destination):
                raise ValueError(f"{step.option} does not happen where the FILE says")
        elif step.way is not None:
            if step.way not in ways:
                raise ValueError(f"{step.way} is not a WAY in the FILE")
            way = ways[step.way]
            there = ends == (way.origin, way.destination)
            back = way.both_ways and ends == (way.destination, way.origin)
            if not (there or back):
                raise ValueError(f"{step.way} does not go where the FILE says")
        elif not set(ends) <= places or step.origin == step.destination:
            raise ValueError("an unlisted WAY still joins two PLACEs from the FILE")
        if step.end is not None and step.end < step.start:
            raise ValueError("a step ends before it starts")


type _Placed = tuple[int, Step]  # a step with its position in the ITINERARY


def _at(
    constraint: Constraint, placed: _Placed, persons: tuple[str, ...], late: int | None
) -> Broken:
    """A Broken at one step: an OPTION by its id, a WAY by its position in the ITINERARY."""
    position, step = placed
    return Broken(constraint, step.option, persons, late, None if step.option else position)


def _in_file_order_of_persons(file: File, persons: Iterable[str]) -> tuple[str, ...]:
    order = [person.id for person in file.persons]
    return tuple(sorted(set(persons), key=order.index))


def _locks(file: File, itinerary: Itinerary) -> list[Broken]:
    """LOCKs are honored: every LOCKed OPTION happens, and the PERSONs its LOCK names take part."""
    taking_part = {step.option: step.persons for step in itinerary if step.option is not None}
    left_out: dict[str, list[str]] = {}
    for lock in file.locks:
        for person in lock.persons:
            if person not in taking_part.get(lock.option, ()):
                left_out.setdefault(lock.option, []).append(person)
    return [
        Broken(Constraint.LOCK, option, _in_file_order_of_persons(file, people))
        for option, people in left_out.items()
    ]


def _musts(file: File, world: World, taking_part: Mapping[str, tuple[str, ...]]) -> list[Broken]:
    """Every must is met: the PERSON takes part in an OPTION that SATISFIES the WANT.

    ``taking_part`` names the PERSONs in each OPTION that happens. Where the world has another
    OPTION for the WANT and the PERSON, the must is met without a step: that OPTION is outside
    the FILE, and the PERSON can take part in it whatever else they do.
    """
    out: list[Broken] = []
    for want in file.wants:
        if want.ends_at is not None:
            continue  # checked along each PERSON's path
        met = {
            person
            for option, persons in taking_part.items()
            if (option, want.id) in world.satisfies
            for person in persons
        }
        met |= {person for wanted, person in world.another_option if wanted == want.id}
        unmet = [person for person in want.musts if person not in met]
        if unmet:
            who = _in_file_order_of_persons(file, unmet)
            out.append(Broken(Constraint.MUST, None, who, want=want.id))
    return out


def _must_nots(
    file: File, world: World, taking_part: Mapping[str, tuple[str, ...]]
) -> list[Broken]:
    """Every must-not is kept: the PERSON takes part in no OPTION that SATISFIES the WANT.

    Where nobody knows whether an OPTION SATISFIES the WANT, the PERSON stays clear of it too.
    One Broken for each OPTION and WANT, naming every PERSON it affects in the FILE's order.
    """
    out: list[Broken] = []
    for option, persons in taking_part.items():
        for want in file.wants:
            if (option, want.id) not in world.might_satisfy:
                continue
            who = [person for person in persons if person in want.must_nots]
            if who:
                named = _in_file_order_of_persons(file, who)
                out.append(Broken(Constraint.MUST_NOT, option, named, want=want.id))
    return out


def _starts(world: World, itinerary: Itinerary) -> list[Broken]:
    """Each OPTION starts when it can: at its fixed start, or at any time if a FACT says so."""
    out: list[Broken] = []
    for step in itinerary:
        if step.option is None:
            continue
        terms = world.terms[step.option]
        fits = terms.free_start if terms.fixed_start is None else step.start == terms.fixed_start
        if not fits:
            out.append(Broken(Constraint.START, step.option, step.persons))
    return out


def _durations(world: World, itinerary: Itinerary) -> list[Broken]:
    """Each OPTION and WAY takes as long as it takes: it ends after a duration the FACTs allow."""
    out: list[Broken] = []
    for position, step in enumerate(itinerary):
        if step.option is not None:
            terms = world.terms[step.option]
            shortest, longest = terms.shortest, terms.longest
        elif step.way is not None:
            shortest, longest = world.takes[step.way]
        else:
            shortest = longest = world.unlisted_takes
        if longest is None or step.end is None:
            fits = longest is None and step.end is None
        else:
            fits = shortest <= step.end - step.start <= longest
        if not fits:
            out.append(_at(Constraint.DURATION, (position, step), step.persons, None))
    return out


type _Found = list[tuple[Constraint, _Placed, int | None]]  # which, at which step, how late


def _along_each_path(
    file: File, world: World, itinerary: Itinerary, order: list[_Placed]
) -> list[Broken]:
    """The CONSTRAINTs about what each PERSON does, with the steps in one order.

    One Broken for each step and amount, naming every PERSON it affects in the FILE's order.
    A must to end the TRIP at a PLACE that is not met has no step: one Broken for each such WANT.
    """
    groups: dict[tuple[Constraint, int, int | None], list[str]] = {}
    elsewhere: dict[str, list[str]] = {}
    for person in file.persons:
        path = [placed for placed in order if person.id in placed[1].persons]
        start = file.starts_from(person.id)
        for constraint, (position, _), late in (
            *_places(path, None if start is None else start.place),
            *_arrivals(world, path),
            *_listed(file, world, path),
        ):
            groups.setdefault((constraint, position, late), []).append(person.id)
        asked = has_to_end_at(file, person.id)
        for want in asked:
            if want.ends_at != _ends(path, start, asked[0]):
                elsewhere.setdefault(want.id, []).append(person.id)
    kinds = [Constraint.PLACE, Constraint.ARRIVAL, Constraint.LISTED]
    return [
        *(
            _at(kind, (position, itinerary[position]), _in_file_order_of_persons(file, who), late)
            for kind in kinds
            for (constraint, position, late), who in groups.items()
            if constraint is kind
        ),
        *(Broken(Constraint.MUST, None, tuple(who), want=want) for want, who in elsewhere.items()),
    ]


def _ends(path: list[_Placed], start: StartsFrom | None, asked: Want) -> str | None:
    """The PLACE where a PERSON's path ends, for a PERSON who has to end the TRIP somewhere.

    A path ends where its last step ends, and a path with nothing in it ends where it begins:
    at the PLACE a FACT says the PERSON starts from. With no such FACT, nobody has said where
    the PERSON is, and a path can begin wherever it suits. So a PERSON who does nothing is where
    they have to end. ``asked`` is the first WANT that says where that is.
    """
    if path:
        return path[-1][1].destination
    return asked.ends_at if start is None else start.place


def _in_each_order(itinerary: Itinerary) -> Iterator[list[_Placed]]:
    """The steps of an ITINERARY, in each order that their times allow.

    Steps that take no time and share an instant can happen in any order. The order is one order
    for the whole ITINERARY, so every PERSON sees those steps happen in the same order. Only the
    order among steps that share a PERSON, directly or through other steps, can matter, so only
    those are tried in every order. The orders are made one at a time, and the first keeps such
    steps in the order the ITINERARY lists them.
    """

    def moment(placed: _Placed) -> tuple[int, bool, int]:
        step = placed[1]
        return (step.start, step.end is None, step.end or 0)

    groups: list[list[_Placed]] = []
    for _, steps in groupby(sorted(enumerate(itinerary), key=moment), key=moment):
        same = list(steps)
        instant = same[0][1].end == same[0][1].start
        groups += _sharing_persons(same) if instant else [[placed] for placed in same]

    chosen = [tuple(group) for group in groups]
    choices = [number for number, group in enumerate(groups) if len(group) > 1]
    orders = [permutations(groups[number]) for number in choices]
    for place, number in enumerate(choices):
        chosen[number] = next(orders[place])
    while True:
        yield [placed for steps in chosen for placed in steps]
        # Move on like a mileage counter: the last group that has another order takes it, and
        # every group after it starts again from its first order.
        place = len(choices) - 1
        while place >= 0:
            following = next(orders[place], None)
            if following is not None:
                chosen[choices[place]] = following
                break
            orders[place] = permutations(groups[choices[place]])
            chosen[choices[place]] = next(orders[place])
            place -= 1
        else:
            return


def _sharing_persons(steps: list[_Placed]) -> list[list[_Placed]]:
    """These steps in groups: two steps are in one group when PERSONs link them.

    Each group keeps its steps in the order given.
    """
    groups: list[list[_Placed]] = []
    for placed in steps:
        linked = [
            group
            for group in groups
            if any(set(placed[1].persons) & set(other.persons) for _, other in group)
        ]
        for group in linked:
            groups.remove(group)
        groups.append(sorted([member for group in linked for member in group] + [placed]))
    return groups


def _places(path: list[_Placed], start: str | None = None) -> _Found:
    """Each PERSON is in one place at a time: no overlap, and each step starts where they are.

    ``start`` is the PLACE a FACT says the PERSON starts from: their first step starts there.
    A PERSON is busy until the latest end of the steps they have started. So a step is found
    to overlap even when the step it overlaps is not the one just before it.
    """
    found: _Found = []
    if start is not None and path and path[0][1].origin != start:
        found.append((Constraint.PLACE, path[0], None))
    busy_until: int | None = None  # the latest end so far
    endless = False  # whether a step so far has no end that anybody knows
    for (_, before), after in pairwise(path):
        if before.end is None:
            endless = True
        else:
            busy_until = before.end if busy_until is None else max(busy_until, before.end)
        if endless:
            found.append((Constraint.PLACE, after, None))
        elif busy_until is not None and busy_until > after[1].start:
            found.append((Constraint.PLACE, after, busy_until - after[1].start))
        elif before.destination != after[1].origin:
            found.append((Constraint.PLACE, after, None))
    return found


def _arrivals(world: World, path: list[_Placed]) -> _Found:
    """Each PERSON arrives in time: whoever travels to an OPTION gets there before its cutoff."""
    found: _Found = []
    arrived: Step | None = None  # the step that last brought this PERSON to a new PLACE
    for placed in path:
        step = placed[1]
        margin = 0 if step.option is None else world.terms[step.option].margin
        if arrived is not None and step.option is not None:
            if arrived.end is None or margin is None:
                found.append((Constraint.ARRIVAL, placed, None))
            elif arrived.end + margin > step.start:
                found.append((Constraint.ARRIVAL, placed, arrived.end + margin - step.start))
        if step.origin != step.destination:
            arrived = step
    return found


def _listed(file: File, world: World, path: list[_Placed]) -> _Found:
    """A COMPLETE set is the whole set: an unlisted WAY needs a world that has it.

    No world has one that goes straight between the PLACEs of a COMPLETE FACT and starts within
    its span. The span includes both of its ends.
    """
    found: _Found = []
    for placed in path:
        step = placed[1]
        if step.option is not None or step.way is not None:
            continue
        here = (step.origin, step.destination)
        if world.unlisted is not None and here not in world.unlisted:
            found.append((Constraint.LISTED, placed, None))
        for fact in file.facts:
            if isinstance(fact, Complete) and fact.rules_out(*here, step.start):
                found.append((Constraint.LISTED, placed, None))
    return found


# ------------------------------- Which ITINERARY is shown -------------------------------


def needless(file: File, world: World, itinerary: Itinerary) -> list[tuple[str | None, str]]:
    """What could be taken out of an ITINERARY that works: each an OPTION and a PERSON in it.

    It tries every combination of PERSONs in OPTIONs that no LOCK requires, with all the times
    left as they are. An empty list means the ITINERARY works without none of them.
    """
    locked = {(lock.option, person) for lock in file.locks for person in lock.persons}
    free = [
        (index, person)
        for index, step in enumerate(itinerary)
        for person in step.persons
        if (step.option, person) not in locked
    ]
    if len(free) > _MOST_TO_TAKE_OUT:
        raise ValueError("this ITINERARY is too large for the reference checker")
    for size in range(1, len(free) + 1):
        for out in combinations(free, size):
            smaller: list[Step] = []
            for index, step in enumerate(itinerary):
                staying = tuple(person for person in step.persons if (index, person) not in out)
                if staying:
                    smaller.append(replace(step, persons=staying))
            if not broken(file, world, tuple(smaller)):
                return [(itinerary[index].option, person) for index, person in out]
    return []


def itineraries(file: File, world: World, known: Routes | None = None) -> list[Itinerary]:
    """The ITINERARIES that work in this world with PERSONs taking part the fewest times.

    It tries every choice of who takes part in which OPTION and in what order. Where a PERSON's
    next OPTION starts somewhere else, WAYs take them there, listed or not. The start times follow
    the rule of "Which ITINERARY is shown". Where a COMPLETE FACT rules out an unlisted WAY for a
    span of time, taking it before the span and after it are tried too. A choice works when the
    orders it names work: no other order is tried in their place.

    Nothing can be taken out of an ITINERARY in which PERSONs take part the fewest times, so
    ``needless`` finds nothing in any ITINERARY returned. They come in the order of "Which
    ITINERARY is shown". That rule covers the plans a report shows, which take no unlisted WAY.
    In a world with unlisted WAYs the order and the times are still the same every time, and no
    more is promised.

    ``known`` can hold the routes of this world that are already worked out.
    """
    best: list[tuple[_Shown, Itinerary]] = []
    fewest: int | None = None
    known = known or Routes(file, world)
    for who in _who_takes_part(file, world):
        if fewest is not None and sum(len(persons) for persons in who) > fewest:
            break
        happening = {
            option.id: persons for option, persons in zip(file.options, who, strict=True) if persons
        }
        wanted = _musts(file, world, happening) or _must_nots(file, world, happening)
        if wanted or _rights(file, world, happening):
            continue  # no order and no timing changes these: only who takes part counts
        mine = [
            [i for i, persons in enumerate(who) if person.id in persons] for person in file.persons
        ]
        for orders in product(*(list(_orders(file, world, indexes, known)) for indexes in mine)):
            found = scheduled(file, world, who, orders, known=known)
            if found is None:
                continue
            taking_part = sum(len(step.persons) for step in found)
            if fewest is None or taking_part < fewest:
                best, fewest = [], taking_part
            if taking_part == fewest:
                best.append((_in_file_order(file, found, orders), found))
    shown: list[Itinerary] = []
    for _, found in sorted(best, key=lambda each: each[0]):
        if found not in shown:
            shown.append(found)
    return shown


def scheduled(
    file: File,
    world: World,
    who: tuple[tuple[str, ...], ...],
    orders: tuple[tuple[int, ...], ...],
    by: Mapping[tuple[int, int], Route] | None = None,
    known: Routes | None = None,
) -> Itinerary | None:
    """The ITINERARY for one choice of PERSONs and orders, or None when it breaks a CONSTRAINT.

    Each time a PERSON takes a WAY is a step of its own, and the steps are listed in the order
    they happen. Every ITINERARY returned has passed ``works_as_listed``.

    ``who`` names the PERSONs in each OPTION, in the FILE's order of OPTIONs. ``orders`` gives,
    for each PERSON in the FILE's order, the OPTIONs they do, by position in the FILE, in the
    order they do them. The start times are those of "Which ITINERARY is shown". So are the
    WAYs the PERSONs take, unless ``by`` names them.

    With ``by``, only one choice of WAYs is tried: for a PERSON, by position in the FILE, and
    the position of an OPTION in their order, the route they take after that OPTION. The
    position is -1 for the route before their first OPTION, and for the one route of a PERSON
    who takes part in no OPTION. Without it,
    ``known`` can hold the routes of this world that are already worked out.
    """
    if by is not None:
        return next(_timings(file, world, who, orders, by), None)
    return next(_schedules(file, world, who, orders, known or Routes(file, world)), None)


def _who_takes_part(file: File, world: World) -> Iterator[tuple[tuple[str, ...], ...]]:
    """Every choice of PERSONs for every OPTION that honors the LOCKs, fewest PERSONs first."""
    people = [person.id for person in file.persons]
    choices: list[list[tuple[str, ...]]] = []
    for option in file.options:
        must = {
            person for lock in file.locks if lock.option == option.id for person in lock.persons
        }
        terms = world.terms[option.id]
        can_happen = terms.fixed_start is not None or terms.free_start
        groups = [group for size in range(len(people) + 1) for group in combinations(people, size)]
        choices.append(
            [group for group in groups if must.issubset(group) and (can_happen or not group)]
        )
    return _fewest_first(choices)


def _orders(
    file: File, world: World, indexes: list[int], known: Routes
) -> Iterator[tuple[int, ...]]:
    """Every order in which one PERSON could do their OPTIONs."""

    def can_follow(first: int, then: int) -> bool:
        before, after = file.options[first], file.options[then]
        early, late = world.terms[before.id].fixed_start, world.terms[after.id].fixed_start
        if early is not None and late is not None and early > late:
            return False
        if before.destination == after.origin:
            return True
        return bool(known.between(before.destination, after.origin))

    for order in permutations(indexes):
        if all(can_follow(first, then) for first, then in pairwise(order)):
            yield order


type Route = tuple[Leg, ...]


def routes(
    file: File, world: World, here: str, there: str, last: bool = False, thin: bool = True
) -> list[Route]:
    """Every route from one PLACE to another by WAYs alone that is worth trying, shortest first.

    ``last`` says that the PERSON does nothing after the route. Four kinds of route are left
    out, because another route is never worse.

    - A route that passes through a PLACE twice. A PERSON who came back to a PLACE could have
      waited there instead: every WAY they take after that starts at the same time either way,
      and no CONSTRAINT asks how they spent the wait.
    - A route in which something follows a listed WAY that has no limit to how long it takes.
      Nothing could follow it. Such a WAY can only be the last thing a PERSON does.
    - A route in which one unlisted WAY could stand in for a stretch of two or more WAYs that
      takes an unlisted WAY. The PERSON waits where the stretch began, takes the one WAY when
      they would have taken the other, and arrives no later. For this the one WAY must exist in
      this world, and every COMPLETE FACT about its two PLACEs must also be about the two PLACEs
      of the other: then the one is ruled out only at times when the other is too.
    - With ``thin``, a route that takes a listed WAY where a WAY listed before it goes between
      the same two PLACEs and is never slower: its shortest time is no longer, and neither is
      its longest. The same route with that other WAY has as many WAYs, arrives no later, and
      comes first by the rule for the WAYs listed first. This is right only where each WAY
      takes as long as this world says. A search that can switch a FACT off asks for every
      route.

    A WAY SATISFIES no WANT. So which WAYs a PERSON takes never changes which musts are met.

    The search does not walk into a PLACE from which no WAY of this world leads on to the
    destination: no route goes that way.
    """
    places = [place.id for place in file.places]
    complete = [fact for fact in file.facts if isinstance(fact, Complete)]
    about: dict[tuple[str, str], frozenset[str]] = {}

    def cover(origin: str, destination: str) -> frozenset[str]:
        """The COMPLETE FACTs about travel between these two PLACEs, looked up once."""
        if (origin, destination) not in about:
            about[origin, destination] = frozenset(
                fact.id for fact in complete if fact.covers(origin, destination)
            )
        return about[origin, destination]

    def joined(origin: str, destination: str) -> bool:
        return world.unlisted is None or (origin, destination) in world.unlisted

    def stands_in(origin: str, destination: str, stretch: Route) -> bool:
        """Whether one unlisted WAY between these PLACEs is never worse than this stretch."""
        return joined(origin, destination) and any(
            way is None and cover(origin, destination) <= cover(start, end)
            for way, start, end in stretch
        )

    # Each PLACE with the WAYs that leave it, in the FILE's order, and where each one leads.
    leaving: dict[str, list[tuple[str, str]]] = {}
    for way in file.ways:
        leaving.setdefault(way.origin, []).append((way.id, way.destination))
        if way.both_ways:
            leaving.setdefault(way.destination, []).append((way.id, way.origin))

    # The PLACEs from which some WAYs of this world lead to the destination. Where an unlisted
    # WAY joins any two PLACEs, that is every PLACE.
    leads_there: set[str] | None = None
    if world.unlisted is not None:
        arriving: dict[str, list[str]] = {}
        for origin, exits in leaving.items():
            for _, destination in exits:
                arriving.setdefault(destination, []).append(origin)
        for origin, destination in world.unlisted:
            arriving.setdefault(destination, []).append(origin)
        leads_there, reached = {there}, [there]
        while reached:
            for origin in arriving.get(reached.pop(), ()):
                if origin not in leads_there:
                    leads_there.add(origin)
                    reached.append(origin)

    def onward(place: str) -> Iterator[tuple[str | None, str]]:
        taken: dict[str, list[tuple[int, int]]] = {}
        for way, ahead in leaving.get(place, ()):
            shortest, longest = world.takes[way]
            if longest is None:
                if last and ahead == there:
                    yield way, ahead
                continue
            if thin:
                quicker = taken.setdefault(ahead, [])
                if any(least <= shortest and most <= longest for least, most in quicker):
                    continue
                quicker.append((shortest, longest))
            yield way, ahead
        for other in places:
            if other != place and joined(place, other):
                yield None, other

    found: list[Route] = []
    # The PLACEs passed so far, the WAYs taken, and what is still to try from there. A list, and
    # no call inside a call: a route through very many PLACEs needs no deep stack.
    begun: list[tuple[tuple[str, ...], Route, Iterator[tuple[str | None, str]]]] = [
        ((here,), (), onward(here))
    ]
    while begun:
        passed, legs, ahead = begun[-1]
        step = next(ahead, None)
        if step is None:
            begun.pop()
            continue
        way, place = step
        if place in passed or (leads_there is not None and place not in leads_there):
            continue
        longer = (*legs, (way, passed[-1], place))
        if any(stands_in(passed[first], place, longer[first:]) for first in range(len(legs))):
            continue
        if place == there:
            found.append(longer)
        else:
            begun.append(((*passed, place), longer, onward(place)))
    return sorted(found, key=lambda route: (len(route), _legs_in_file_order(file, route)))


class Routes:
    """The routes between the PLACEs of one world, with each pair worked out once."""

    def __init__(self, file: File, world: World, thin: bool = True) -> None:
        """``thin`` leaves out a route with a WAY that an earlier WAY is never slower than.

        That is right where each WAY takes as long as this world says.
        """
        self._file, self._world, self._thin = file, world, thin
        self._found: dict[tuple[str, str, bool], list[Route]] = {}

    def between(self, here: str, there: str, last: bool = False) -> list[Route]:
        """Every route from one PLACE to another that is worth trying, shortest first.

        ``last`` says that the PERSON does nothing after the route.
        """
        if (here, there, last) not in self._found:
            self._found[here, there, last] = routes(
                self._file, self._world, here, there, last, self._thin
            )
        return self._found[here, there, last]


def _legs_in_file_order(file: File, route: Route) -> list[tuple[int, int, int]]:
    """The WAYs listed first come first, then the PLACEs listed first. Unlisted WAYs come last."""
    ways = [way.id for way in file.ways]
    places = [place.id for place in file.places]
    return [
        (len(ways) if way is None else ways.index(way), places.index(origin), places.index(to))
        for way, origin, to in route
    ]


def _schedules(
    file: File,
    world: World,
    who: tuple[tuple[str, ...], ...],
    orders: tuple[tuple[int, ...], ...],
    known: Routes,
) -> Iterator[Itinerary]:
    """The ITINERARIES for one choice of PERSONs and orders.

    Where a PERSON's next OPTION starts somewhere else, WAYs must take them there. The routes
    are tried with the fewest WAYs first, then in the order of "Which ITINERARY is shown": PERSON
    by PERSON, the WAYs listed first. Then each way the timing can fall is tried.
    """
    # Which PERSON, after which of their OPTIONs, the routes. Before their first OPTION is -1.
    needed: list[tuple[int, int, list[Route]]] = []
    for number, order in enumerate(orders):
        person = file.persons[number].id
        start, asked = file.starts_from(person), has_to_end_at(file, person)
        end = asked[0].ends_at if asked else None  # where this PERSON's path has to end
        stops = [(file.options[index].origin, file.options[index].destination) for index in order]
        # After which OPTION, from where, to where, and whether the PERSON does nothing after it.
        hops = [
            (spot, here, there, False)
            for spot, ((_, here), (there, _)) in enumerate(pairwise(stops))
        ]
        first = stops[0][0] if stops else end
        if start is not None and first is not None:
            hops.insert(0, (-1, start.place, first, not stops))
        if stops and end is not None:
            hops.append((len(stops) - 1, stops[-1][1], end, True))
        for spot, here, there, last in hops:
            if here != there:
                possible = known.between(here, there, last)
                if not possible:
                    return
                needed.append((number, spot, possible))

    # The routes at each point in the order of the WAYs they take. No route is the beginning of
    # another one between the same two PLACEs. So going through the points in turn puts the
    # choices in the order of "Which ITINERARY is shown": PERSON by PERSON, WAY by WAY.
    possible = [
        sorted(routes, key=lambda route: _legs_in_file_order(file, route))
        for _, _, routes in needed
    ]
    for chosen in _fewest_first(possible):
        hops = {
            (number, position): route
            for (number, position, _), route in zip(needed, chosen, strict=True)
        }
        yield from _timings(file, world, who, orders, hops)


def _fewest_first[T: Sized](choices: Sequence[Sequence[T]]) -> Iterator[tuple[T, ...]]:
    """One thing from each list, in every combination, the smallest combinations first.

    The size of a combination is the lengths of its things added up. Among combinations of one
    size the lists' own order decides, and the first list counts most.

    Each combination is made when it is asked for. So a search that stops at the first one that
    works never makes the rest, however many there are. It keeps its own list of what is picked,
    with no call inside a call, so very many lists need no deep stack.
    """
    if not all(choices):
        return
    # The smallest and the largest size that the lists from each point on can add.
    least = [0] * (len(choices) + 1)
    greatest = [0] * (len(choices) + 1)
    for rest in reversed(range(len(choices))):
        sizes = [len(thing) for thing in choices[rest]]
        least[rest] = least[rest + 1] + min(sizes)
        greatest[rest] = greatest[rest + 1] + max(sizes)
    for total in range(least[0], greatest[0] + 1):
        picked: list[int] = []  # which thing is taken from each list so far
        nth, left = 0, total  # the next thing to try in the list after those; the size left
        while True:
            point = len(picked)
            here: Sequence[T] = choices[point] if point < len(choices) else ()
            while nth < len(here):
                after = left - len(here[nth])
                if least[point + 1] <= after <= greatest[point + 1]:
                    break
                nth += 1
            if nth < len(here):
                picked.append(nth)
                nth, left = 0, left - len(here[nth])
                continue
            if point == len(choices):
                yield tuple(choices[at][which] for at, which in enumerate(picked))
            if not picked:
                break
            nth = picked.pop()
            left += len(choices[len(picked)][nth])
            nth += 1


def _timings(
    file: File,
    world: World,
    who: tuple[tuple[str, ...], ...],
    orders: tuple[tuple[int, ...], ...],
    hops: Mapping[tuple[int, int], Route],
) -> Iterator[Itinerary]:
    """The ITINERARIES for one choice of PERSONs, orders and routes, one for each timing.

    Start times are as early as the CONSTRAINTs allow. A COMPLETE FACT rules out an unlisted WAY
    only within its span. So each unlisted WAY between the PLACEs of such a FACT is tried as it
    falls, then before the first span that rules it out, then after each one.
    """
    listed = len(file.options)
    legs: list[tuple[str, Leg]] = []  # each WAY taken: who takes it, and which one
    lines: list[list[int]] = []  # what each PERSON does in order, the WAYs they take included
    for number, (person, order) in enumerate(zip(file.persons, orders, strict=True)):
        line: list[int] = []
        for position in range(-1, len(order)):
            if position >= 0:
                line.append(order[position])
            for leg in hops.get((number, position), ()):
                legs.append((person.id, leg))
                line.append(listed + len(legs) - 1)
        lines.append(line)

    def takes(node: int) -> int | None:
        if node < listed:
            terms = world.terms[file.options[node].id]
            return None if terms.longest is None else terms.shortest
        way = legs[node - listed][1][0]
        if way is None:
            return world.unlisted_takes
        shortest, longest = world.takes[way]
        return None if longest is None else shortest

    def origin(node: int) -> str:
        return legs[node - listed][1][1] if node >= listed else file.options[node].origin

    def destination(node: int) -> str:
        return legs[node - listed][1][2] if node >= listed else file.options[node].destination

    def moves(node: int) -> bool:
        return origin(node) != destination(node)

    def unlisted(node: int) -> bool:
        return node >= listed and legs[node - listed][1][0] is None

    gaps: list[tuple[int, int, int]] = []  # (before, after, least seconds between their starts)
    for line in lines:
        arrived: int | None = None  # the step that last brought this PERSON to a new PLACE
        for position, node in enumerate(line):
            if position:
                lasts = takes(line[position - 1])
                if lasts is None:
                    return
                gaps.append((line[position - 1], node, lasts))
            margin = 0 if node >= listed else world.terms[file.options[node].id].margin
            if arrived is not None and margin != 0:
                lasts = takes(arrived)
                if lasts is None or margin is None:
                    return
                gaps.append((arrived, node, lasts + margin))
            if moves(node):
                arrived = node

    count = listed + len(legs)
    if _goes_round(count, gaps):
        return  # two PERSONs would do the same OPTIONs at one instant in opposite orders
    fixed: dict[int, int] = {}
    for index, option in enumerate(file.options):
        at = world.terms[option.id].fixed_start
        if who[index] and at is not None:
            fixed[index] = at

    # The limits on each start that fix no start themselves. No step starts before the TRIP
    # starts, and a step with a known length starts early enough to be over when the TRIP ends.
    trip_starts, trip_ends = file.trip_start(), file.trip_end()
    not_before: dict[int, int] = {}
    no_later: dict[int, int] = {}
    for node in range(count):
        lasts = takes(node)
        if trip_starts is not None:
            not_before[node] = trip_starts.at
        if trip_ends is not None and lasts is not None:
            no_later[node] = trip_ends.at - lasts

    ruled_out = [
        (node, spans)
        for node in range(listed, count)
        if unlisted(node)
        for spans in [_closed(file, origin(node), destination(node))]
        if spans
    ]
    # Each such WAY as it falls, then in each opening: before the first span, after each one.
    # An opening is one more limit on when the WAY starts. It fixes no start either.
    openings = [[None, *range(len(spans) + 1)] for _, spans in ruled_out]
    for choice in product(*openings):
        earliest, latest = dict(not_before), dict(no_later)
        for (node, spans), opening in zip(ruled_out, choice, strict=True):
            if opening is None:
                continue
            if opening > 0:
                after = spans[opening - 1][1] + 1
                earliest[node] = max(after, earliest.get(node, after))
            if opening < len(spans):
                before = spans[opening][0] - 1
                latest[node] = min(before, latest.get(node, before))
        starts = _times(count, gaps, fixed, earliest, latest)
        if starts is None:
            continue
        steps: dict[int, Step] = {}
        for index, option in enumerate(file.options):
            if who[index]:
                lasts = takes(index)
                start = starts[index]
                end = None if lasts is None else start + lasts
                steps[index] = Step(
                    option.id, option.origin, option.destination, who[index], start, end
                )
        for number, (person_id, (way, start_place, end_place)) in enumerate(legs):
            start = starts[listed + number]
            lasts = takes(listed + number)
            end = None if lasts is None else start + lasts
            steps[listed + number] = Step(
                None, start_place, end_place, (person_id,), start, end, way
            )
        itinerary = _in_the_order_they_happen(file, steps, gaps)
        if works_as_listed(file, world, itinerary):
            yield itinerary


def _closed(file: File, origin: str, destination: str) -> list[tuple[int, int]]:
    """The spans of time in which no unlisted WAY goes straight from one PLACE to another.

    These are the spans of the COMPLETE FACTs about the two PLACEs, earliest first, with spans
    that overlap or meet joined into one.
    """
    spans = sorted(
        (fact.earliest, fact.latest)
        for fact in file.facts
        if isinstance(fact, Complete) and fact.covers(origin, destination)
    )
    joined: list[tuple[int, int]] = []
    for earliest, latest in spans:
        if joined and earliest <= joined[-1][1] + 1:
            joined[-1] = (joined[-1][0], max(joined[-1][1], latest))
        else:
            joined.append((earliest, latest))
    return joined


def _in_the_order_they_happen(
    file: File, steps: Mapping[int, Step], gaps: list[tuple[int, int, int]]
) -> Itinerary:
    """These steps as an ITINERARY: earlier steps first, each after whatever must come before it.

    A gap from one step to another says the first comes before the second. Steps that could
    come in either order follow the FILE's order.
    """

    def rank(node: int) -> tuple[_StepOrder, int]:
        return (_step_in_file_order(file, steps[node]), node)

    waiting = dict.fromkeys(steps, 0)
    later: dict[int, list[int]] = {node: [] for node in steps}
    for before, after, _ in gaps:
        waiting[after] += 1
        later[before].append(after)
    ready = [(rank(node), node) for node in steps if not waiting[node]]
    heapify(ready)
    listed: list[Step] = []
    while ready:
        _, node = heappop(ready)
        listed.append(steps[node])
        for after in later[node]:
            waiting[after] -= 1
            if not waiting[after]:
                heappush(ready, (rank(after), after))
    return tuple(listed)


def _goes_round(count: int, gaps: list[tuple[int, int, int]]) -> bool:
    """Whether the order these gaps give goes round in a circle."""
    waiting = [0] * count
    for _, after, _ in gaps:
        waiting[after] += 1
    ready = [node for node in range(count) if not waiting[node]]
    done = 0
    while ready:
        node = ready.pop()
        done += 1
        for before, after, _ in gaps:
            if before == node:
                waiting[after] -= 1
                if not waiting[after]:
                    ready.append(after)
    return done < count


def _times(
    count: int,
    gaps: list[tuple[int, int, int]],
    fixed: Mapping[int, int],
    not_before: Mapping[int, int],
    no_later: Mapping[int, int],
) -> list[int] | None:
    """Start times that keep every gap and every fixed start, or None when there are none.

    A start that comes after one already timed is as early as the gaps allow. Then a start that
    comes before one already timed is as late as they allow. Those two steps repeat until they
    time nothing more. What is left is tied to no fixed start, and counts from its own limit, or
    from zero.

    ``not_before`` and ``no_later`` are limits on single starts: the times of the TRIP, and the
    opening in which an unlisted WAY leaves. They fix no start, so they time nothing by
    themselves. But "as early as it can" and "as late as it can" keep to them, for the step and
    for whatever comes before or after it. So each limit is first carried along the gaps: a
    start can be no earlier than what comes before it allows, and no later than what comes after
    it allows.

    This finds a timing whenever one exists. The gaps and limits say only that one start is at
    least so long after another, or after or before a known time. With starts of that kind, any
    start chosen inside its own limits leaves room for all the others.
    """
    floor = {node: moment for node, moment in not_before.items() if node not in fixed}
    cap = {node: moment for node, moment in no_later.items() if node not in fixed}
    for _ in range(count + 1):
        carried = False
        for before, after, gap in gaps:
            later = before in floor and after not in fixed
            if later and (after not in floor or floor[before] + gap > floor[after]):
                floor[after] = floor[before] + gap
                carried = True
            sooner = after in cap and before not in fixed
            if sooner and (before not in cap or cap[after] - gap < cap[before]):
                cap[before] = cap[after] - gap
                carried = True
        if not carried:
            break
    else:
        return None  # the order goes round in a circle

    times: list[int | None] = [fixed.get(node) for node in range(count)]
    for _ in range(count + 1):
        moved = False
        for before, after, gap in gaps:
            base, current = times[before], times[after]
            if base is None:
                continue
            earliest = max(base + gap, floor.get(after, base + gap))
            if current is None or earliest > current:
                if after in fixed:
                    return None  # something before a fixed start runs past it
                times[after] = earliest
                moved = True
        if not moved:
            break
    else:
        return None  # the order goes round in a circle

    while True:
        untimed = {node for node in range(count) if times[node] is None}
        if not untimed:
            break
        if not _settle(gaps, times, untimed, late=True, limit=cap):
            return None
        still = {node for node in untimed if times[node] is None}
        if not _settle(gaps, times, still, late=False, limit=floor):
            return None
        if len(still) == len(untimed) and all(times[node] is None for node in still):
            for node in still:
                # From its earliest start. With none, from zero, or from its latest start
                # where that is before zero: then zero would be too late.
                times[node] = floor.get(node, min(0, cap.get(node, 0)))
            if not _settle(gaps, times, still, late=False, limit=floor):
                return None
    return [moment for moment in times if moment is not None]


def _settle(
    gaps: list[tuple[int, int, int]],
    times: list[int | None],
    free: set[int],
    *,
    late: bool,
    limit: Mapping[int, int],
) -> bool:
    """Time the starts in ``free`` from those already timed. False if the gaps go round in a circle.

    With ``late``, a start takes the latest time that the timed starts after it allow, and no
    later than its own ``limit``. Otherwise it takes the earliest time that the timed starts
    before it allow, and no earlier than its own ``limit``.
    """
    for _ in range(len(times) + 1):
        moved = False
        for before, after, gap in gaps:
            if late:
                bound, current = times[after], times[before]
                if before not in free or bound is None:
                    continue
                latest = min(bound - gap, limit.get(before, bound - gap))
                if current is None or latest < current:
                    times[before] = latest
                    moved = True
            else:
                base, current = times[before], times[after]
                if after not in free or base is None:
                    continue
                earliest = max(base + gap, limit.get(after, base + gap))
                if current is None or earliest > current:
                    times[after] = earliest
                    moved = True
        if not moved:
            return True
    return False


type _StepOrder = tuple[int, int, tuple[int, ...], int, int, int]


def _step_in_file_order(file: File, step: Step) -> _StepOrder:
    """Earlier steps first, then the FILE's order of OPTIONs, WAYs, PERSONs and PLACEs."""
    options = [option.id for option in file.options]
    ways = [way.id for way in file.ways]
    people = [person.id for person in file.persons]
    places = [place.id for place in file.places]
    if step.option is not None:
        index = options.index(step.option)
    else:
        index = len(options) + (len(ways) if step.way is None else ways.index(step.way))
    persons = tuple(people.index(person) for person in step.persons)
    origin, destination = places.index(step.origin), places.index(step.destination)
    end = -1 if step.end is None else step.end
    return (step.start, index, persons, origin, destination, end)


type _Shown = tuple[int, list[int], tuple[tuple[int, ...], ...], list[_StepOrder]]


def _in_file_order(file: File, itinerary: Itinerary, orders: tuple[tuple[int, ...], ...]) -> _Shown:
    """The order of "Which ITINERARY is shown" among ITINERARIES that tie on its first two rules.

    Fewest OPTIONs; then the OPTIONs listed first in the FILE; then, PERSON by PERSON, the
    OPTIONs each one does, in the order they do them, with the OPTIONs listed first coming first.
    The WAYs are already those listed first: ``scheduled`` gives one ITINERARY for each order.
    """
    options = [option.id for option in file.options]
    used = sorted(options.index(step.option) for step in itinerary if step.option is not None)
    steps = [_step_in_file_order(file, step) for step in itinerary]
    return (len(used), used, orders, steps)


def first_shown(file: File, world: World) -> Itinerary | None:
    """The ITINERARY that "Which ITINERARY is shown" puts first in this world, if any works."""
    found = itineraries(file, world)
    return found[0] if found else None


def any_works(file: File, world: World) -> bool:
    """Whether any ITINERARY works in this world."""
    return bool(itineraries(file, world))
