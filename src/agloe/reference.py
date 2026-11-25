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
from collections.abc import (
    Callable,
    Collection,
    Iterable,
    Iterator,
    Mapping,
    Sequence,
    Set,
    Sized,
)
from dataclasses import dataclass, field, replace
from enum import Enum
from functools import partial
from heapq import heapify, heappop, heappush
from itertools import chain, combinations, groupby, pairwise, permutations, product
from math import inf
from typing import Literal, NamedTuple

from agloe.file import Booking, Complete, File, Offer, Satisfies, StartsFrom, Want, WithObject

_MOST_PLANS_TO_CHECK = 4096  # ``needless`` checks every plan with something taken out


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
    REQUIRED = "Each requirement of an OPTION is met"
    AT_HAND = "Each OBJECT is at hand where it is required, handed over or carried"
    REFUSED = "No PERSON has an OBJECT in an OPTION that refuses it"
    COVERED = "Each OBJECT is covered where an OPTION needs a right for it"


@dataclass(frozen=True)
class Step:
    """One thing in an ITINERARY: an OPTION that happens, or a WAY that PERSONs take.

    ``option`` names an OPTION. Otherwise the step is a WAY: ``way`` names a listed one, and both
    are None for a WAY the FILE does not list. ``end`` follows from the duration, and is None when
    nobody knows how long the step takes.

    ``handed`` holds each hand-over in an OPTION: an OBJECT, and the PERSON who has it from the
    start of the OPTION. ``carried`` holds each OBJECT that the travelers choose to carry in
    an OPTION: it is in the OPTION from its start, and lies at the PLACE where the OPTION ends
    from its end. An OBJECT that the OPTION requires and carries goes along with no choice,
    and needs no entry here.
    """

    option: str | None
    origin: str
    destination: str
    persons: tuple[str, ...]
    start: int
    end: int | None
    way: str | None = None
    handed: tuple[tuple[str, str], ...] = ()
    carried: tuple[str, ...] = ()


@dataclass(frozen=True)
class Where:
    """Where an OBJECT is: with a PERSON, at a PLACE, or in an OPTION that carries it.

    With none of the three, it is somewhere the FILE does not name. There, and in an OPTION,
    it is at hand for no OPTION, and no PERSON has it.
    """

    person: str | None = None
    place: str | None = None
    option: str | None = None


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

    A requirement that is not met names the OPTION and the ``capability``. Where the OPTION
    requires it of one PERSON, ``persons`` holds everybody who takes part: none of them has
    it. Where it requires it of each PERSON, ``persons`` holds those who lack it.

    An OBJECT that is not at hand names the OPTION and the ``object``. Where the OPTION
    requires it, ``persons`` holds everybody who takes part, and so it does where the OBJECT
    cannot be carried there. Where it cannot be handed over there, ``persons`` holds the
    PERSON who was to have it. ``late`` says how long after the OPTION starts the OBJECT
    would be at hand at the latest, where it is in an OPTION that ends at the PLACE where
    this one starts. Where it might be in several such OPTIONs, ``sooner`` says how long
    after the start the first of them ends. ``might`` says that the OBJECT might also be at
    hand when the OPTION starts.

    An OBJECT in an OPTION that refuses it names the OPTION and the ``object``. ``persons``
    holds each PERSON who takes part and has the OBJECT just before the OPTION starts, or
    might. Where the plan hands the OBJECT over in the OPTION, ``persons`` holds the PERSON
    who was to have it.
    """

    constraint: Constraint
    option: str | None
    persons: tuple[str, ...]
    late: int | None = None
    step: int | None = None
    want: str | None = None
    cap: str | None = None
    capability: str | None = None
    object: str | None = None
    might: bool = False
    sooner: int | None = None


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
    BUDGET that lists the PERSON holds the currency of its price. It holds the same for
    each OFFER and each OBJECT that the OFFER names.

    ``spent`` says, for each cap by its BUDGET and currency, the most that the BOOKINGs might
    have charged to it in ten-thousandths. None: no upper bound. Each cap has its own sum, so
    the sums of the worst case need not be true together.

    ``requires`` says what an OPTION requires of a CAPABILITY: "one" where a PERSON who takes
    part has to have it, and "each" where every PERSON who takes part has to. A pair that is
    not in it requires nothing. ``has`` holds each PERSON and CAPABILITY where the PERSON has it.

    ``needs`` holds each OPTION and OBJECT where the OPTION requires the OBJECT, and
    ``refuses`` each one where the OPTION refuses it. ``open_needs`` holds those of
    ``needs`` that nobody is sure of: no FACT says whether the OPTION requires the OBJECT,
    and the worst of the ways at once has it require it. ``does`` says
    what an OPTION does with an OBJECT: "hands_over", "keeps" or "carries". A pair that is not
    in it leaves the OBJECT alone. An OPTION that requires the OBJECT and carries it takes
    it along whenever it happens, whether or not a plan chooses that: ``goes_along`` says
    so. Five more values are no single possible world.
    "might_keep" is the worst of the ways at once for an OPTION that does not require the
    OBJECT: it hands nothing over and carries nothing, and nobody knows whether it keeps
    the OBJECT. "might_take" is the worst for an OPTION that requires the OBJECT, or might:
    nobody knows whether it keeps it, and nobody knows whether it takes it along.
    "might_carry" is the second alone, where all that is known is that such an OPTION does
    not keep the OBJECT. "any" is the best of them: the OPTION does whichever of the four
    suits the plan. "carries_unless_refused" is in no world that ``_world`` makes. A
    report uses it to say what the FILE's own OPTIONs do without another transfer: the
    OPTION takes the OBJECT along with no choice, and nobody knows whether it refuses it.
    ``starts`` says where each OBJECT is when the TRIP starts. An OBJECT that is in
    ``starts_anywhere`` starts with whichever PERSON or at whichever PLACE suits the plan, or
    somewhere the FILE does not name, and each of those is one possible world. An OBJECT
    that is in neither might be anywhere: with any PERSON, at any PLACE, or somewhere the
    FILE does not name. That is the worst of the ways at once, and a plan has to work
    wherever the OBJECT is. ``brought`` holds each OBJECT that the fourteenth and the
    fifteenth CONSTRAINT ask nothing of: another transfer might put it at hand wherever a
    plan needs it, and take it out of an OPTION that refuses it. That is an upper bound, and
    no possible world.

    ``ticketed`` holds each OPTION and OBJECT where the OPTION needs a right for the
    OBJECT. ``uncovered`` holds those of them where nothing covers the OBJECT: no BOOKING
    of the FILE, no other right, and no OFFER that names the OBJECT. ``offered`` holds
    those where only a place of an OFFER can cover it: no BOOKING and no other right does,
    and an OFFER for the OPTION names the OBJECT. There the OBJECT takes one place where
    it needs the right. The sixteenth CONSTRAINT asks about those two kinds of pairs only.

    ``undecided`` holds each OPTION and OBJECT where the FILE does not say what the OPTION
    does with the OBJECT, and this world does not say either. That is so in the best case,
    for an OBJECT that another transfer brings: nothing follows it there, so ``does`` has
    no entry for the pair. The OPTION then does what suits a plan.
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
    requires: Mapping[tuple[str, str], str] = field(default_factory=dict[tuple[str, str], str])
    has: frozenset[tuple[str, str]] = frozenset()
    needs: frozenset[tuple[str, str]] = frozenset()
    open_needs: frozenset[tuple[str, str]] = frozenset()
    refuses: frozenset[tuple[str, str]] = frozenset()
    does: Mapping[tuple[str, str], str] = field(default_factory=dict[tuple[str, str], str])
    starts: Mapping[str, Where] = field(default_factory=dict[str, Where])
    starts_anywhere: frozenset[str] = frozenset()
    brought: frozenset[str] = frozenset()
    ticketed: frozenset[tuple[str, str]] = frozenset()
    uncovered: frozenset[tuple[str, str]] = frozenset()
    undecided: frozenset[tuple[str, str]] = frozenset()
    offered: frozenset[tuple[str, str]] = frozenset()


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
    WANT and one PERSON, whichever OPTION meets it. It is "price" for an OFFER, with the
    OFFER in ``about``, and "funding" for a PERSON or for an OBJECT: a BUDGET that can pay
    for them. The OBJECT is in ``about``.

    For an OPTION and a CAPABILITY it is "requirement": what the OPTION requires of it. For a
    PERSON and a CAPABILITY it is "has". ``about`` names the CAPABILITY.

    For an OPTION and an OBJECT it is "does not require", "does not refuse", or one of the
    six ways that what the OPTION does with the OBJECT can help: "keeps", "does not keep",
    "does not carry", "does not keep or carry", "hands over" and "carries". For an OBJECT
    it is "starts with" a PERSON or "starts at" a PLACE, or "another transfer": something
    outside the FILE that puts the OBJECT at hand where a plan needs it, and takes it out
    of an OPTION that refuses it. ``about`` names the OBJECT.
    """

    what: str
    option: str | None = None
    origin: str | None = None
    destination: str | None = None
    way: str | None = None
    want: str | None = None
    person: str | None = None
    about: str | None = None
    place: str | None = None


# ------------------------------- What is unknown -------------------------------


def unknowns(file: File) -> tuple[Unknown, ...]:
    """Every FACT the FILE leaves out that could help, in the order of the rules page.

    That an OPTION SATISFIES a WANT can help only where the WANT is a must for some PERSON,
    and that it does not only where the WANT is a must-not for some PERSON. So only those are
    listed. Where a FACT says a WANT's set is COMPLETE, nothing about the WANT is unknown.
    That a PERSON has a CAPABILITY can help only where some OPTION requires it or might.
    A price and who pays can help only where somebody might have to pay for a place. So a
    price is listed only for an OFFER that ``for_sale`` gives, and who pays only for a PERSON
    with no BOOKING for the OPTION of one of those, and for an OBJECT that one of those
    names and that no BOOKING for its OPTION covers. A FACT about an OBJECT can help only where
    some OPTION requires the OBJECT or refuses it, or needs a right for it, or might. That
    an OPTION needs no right for an OBJECT is unknown where no FACT and no COMPLETE set
    says. Another right for the OBJECT can be found where a FACT says that the OPTION needs
    one. Neither can help where a BOOKING for the OPTION covers the OBJECT, so neither is
    listed there.
    """
    sold = for_sale(file)
    to_pay = {offer.id for offer in sold}
    buyers = [
        person.id
        for person in file.persons
        if any(
            not offer.objects and file.booking(offer.option, person.id) is None for offer in sold
        )
    ]
    # The OBJECTs that might have to take a place that costs something, in the FILE's order.
    placed_things = [
        thing.id
        for thing in file.objects
        if any(
            thing.id in offer.objects and file.booking_for(offer.option, thing.id) is None
            for offer in sold
        )
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
        for capability in file.capabilities:
            if file.requires(option.id, capability.id) is None:
                out.append(Unknown("requirement", option.id, about=capability.id))
        for thing in file.objects_asked_for():
            if file.requires_object(option.id, thing.id) is None:
                out.append(Unknown("does not require", option.id, about=thing.id))
            if file.refuses_object(option.id, thing.id) is None:
                out.append(Unknown("does not refuse", option.id, about=thing.id))
            if file.does_with(option.id, thing.id) is None:
                # Only an OPTION that requires the OBJECT, or might, takes it along with
                # no choice. So only of such an OPTION does it help to know that it does
                # not carry the OBJECT.
                might_take = file.requires_object(option.id, thing.id) is not False
                out += [
                    Unknown(what, option.id, about=thing.id)
                    for what in _ACTIONS
                    if might_take or what not in _ABOUT_GOING_ALONG
                ]
        for thing in file.objects_asked_for():
            # A BOOKING that covers the OBJECT settles the pair: whether or not the OPTION
            # needs the right, the OBJECT has one.
            if file.booking_for(option.id, thing.id) is not None:
                continue
            needed = file.needs_right_for(option.id, thing.id)
            if needed is None:
                out.append(Unknown("needs no right for", option.id, about=thing.id))
            elif needed and file.rights_complete_for(option.id, thing.id) is None:
                # Where the rights for the OBJECT are COMPLETE, there is no other right.
                out.append(Unknown("another right for", option.id, about=thing.id))
        if file.needs_right(option.id) is True and file.rights_complete(option.id) is None:
            for person in file.persons:
                if file.booking(option.id, person.id) is None:
                    out.append(Unknown("another right", option.id, person=person.id))
        for offer in file.every_offer(option.id):
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
    asked_for = [
        capability.id
        for capability in file.capabilities
        if any(file.requires(option.id, capability.id) != "none" for option in file.options)
    ]
    for person in file.persons:
        for capability in asked_for:
            if file.has(person.id, capability) is None:
                out.append(Unknown("has", person=person.id, about=capability))
    for thing in file.objects_asked_for():
        if file.object_starts(thing.id) is None:
            out += [Unknown("starts with", person=each.id, about=thing.id) for each in file.persons]
            out += [Unknown("starts at", place=each.id, about=thing.id) for each in file.places]
    for person in buyers:
        if not file.listed(person):
            out.append(Unknown("funding", person=person))
    for thing in placed_things:
        if not file.listed(thing):
            out.append(Unknown("funding", about=thing))
    for want in musts:
        for person in _in_file_order_of_persons(file, want.musts):
            out.append(Unknown("another option", want=want.id, person=person))
    for thing in file.objects_asked_for():
        if file.transfers_complete(thing.id) is None:
            out.append(Unknown("another transfer", about=thing.id))
    return tuple(out)


# How what an OPTION does with an OBJECT can help.
_ACTIONS = (
    "keeps",
    "does not keep",
    "does not carry",
    "does not keep or carry",
    "hands over",
    "carries",
)
# Those that say something only of an OPTION that requires the OBJECT, or might.
_ABOUT_GOING_ALONG = ("does not carry", "does not keep or carry")
_STARTS = ("starts with", "starts at")  # where an OBJECT can turn out to start


def for_sale(file: File) -> list[Offer]:
    """The OFFERs with a place that somebody might have to pay for.

    Only a PERSON with no BOOKING for an OPTION takes a place of it. An OFFER is left out
    where its price is nothing, where a FACT says its OPTION needs no right, and where the
    OPTION has a place that costs nothing for each of those PERSONs: nobody has to pay then.

    An OFFER for OBJECTs is the same. Only an OBJECT that it names takes a place of it, and
    only where no BOOKING for the OPTION covers the OBJECT and no FACT says that the OPTION
    needs no right for it. It is left out where its price is nothing.
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
        for each in file.offers_for_objects(option.id):
            might_take = any(
                file.needs_right_for(option.id, thing) is not False
                and file.booking_for(option.id, thing) is None
                for thing in each.objects
            )
            if might_take and (each.price is None or each.price.amount):
                sold.append(each)
    return sold


def has_to_end_at(file: File, person: str) -> list[Want]:
    """The WANTs to end the TRIP at a PLACE that are a must for this PERSON."""
    return [want for want in file.wants if want.ends_at is not None and person in want.musts]


def best_case(file: File) -> World:
    """Every unknown FACT turned out as well as it can.

    Without OBJECTs that is one possible world. An OBJECT makes it more. Where no FACT says
    where it starts, the world leaves the start to pick, and each pick is a possible world.
    Where the set of its transfers is not COMPLETE, the fourteenth and the fifteenth
    CONSTRAINT ask nothing of it here. That is an upper bound and no possible world: whatever
    works in a possible world works here, and no more is claimed.
    """
    return _world(file, None)


@dataclass(frozen=True)
class Remaining:
    """What is left of a FILE while a conflict is looked for: the FILE with records taken out.

    Taking a FACT out makes what it stated unknown. That is more than leaving the FACT out.
    Where a FACT says a WANT's set is COMPLETE, an OPTION with no FACT about the WANT does not
    SATISFY it. An OPTION whose FACT about the WANT was taken out might. ``unsaid`` holds each
    such OPTION and WANT. A BOOKING that is taken out is the same: nobody knows whom it covers,
    so it might cover anybody. ``open_to_all`` holds the OPTION of each such BOOKING, and of
    each OFFER for PERSONs that is taken out: it might have a place for every PERSON. A
    BOOKING that is taken out might cover any OBJECT too, and ``covering_any`` holds its
    OPTION. An OFFER for OBJECTs that is taken out might have a place for each OBJECT it
    names, at no cost: ``open_to`` holds its OPTION with each of them. It still has no
    place for a PERSON or for another OBJECT, as an OFFER for PERSONs has none for an
    OBJECT. These belong to the search for a conflict: no FILE that is read has them, and
    no answer is ever given for what is left.

    What an OPTION requires of a CAPABILITY or of an OBJECT needs nothing of the kind, and
    neither does whether it refuses an OBJECT. Only best cases are asked about what is left,
    and the best an unknown requirement or refusal can be is none: what a COMPLETE set says
    of an OPTION with no FACT.

    What an OPTION does with an OBJECT is like a WANT's set. Where a FACT says that the set of
    the OBJECT's transfers is COMPLETE, an OPTION with no FACT about the OBJECT leaves it
    alone. An OPTION whose FACT was taken out might hand it over, keep it, carry it or leave
    it alone.
    ``undone`` holds each such OPTION and OBJECT.
    """

    file: File
    unsaid: frozenset[tuple[str, str]] = frozenset()
    open_to_all: frozenset[str] = frozenset()
    undone: frozenset[tuple[str, str]] = frozenset()
    covering_any: frozenset[str] = frozenset()
    open_to: frozenset[tuple[str, str]] = frozenset()

    def without(self, record: str) -> Remaining:
        """What is left with one more FACT, WANT or DECISION taken out."""
        found = [fact for fact in self.file.facts if fact.id == record]
        taken = {(fact.option, fact.want) for fact in found if isinstance(fact, Satisfies)}
        opened = {
            fact.option
            for fact in found
            if isinstance(fact, Booking) or (isinstance(fact, Offer) and not fact.objects)
        }
        acted = {(fact.option, fact.object) for fact in found if isinstance(fact, WithObject)}
        booked = {fact.option for fact in found if isinstance(fact, Booking)}
        named = {
            (fact.option, thing)
            for fact in found
            if isinstance(fact, Offer)
            for thing in fact.objects
        }
        return Remaining(
            self.file.without(record),
            self.unsaid | taken,
            self.open_to_all | opened,
            self.undone | acted,
            self.covering_any | booked,
            self.open_to | named,
        )

    def might_cover(self) -> frozenset[tuple[str, str]]:
        """Each OPTION and PERSON that a BOOKING taken out might cover: anybody, for its OPTION."""
        people = self.file.persons
        return frozenset((option, person.id) for option in self.open_to_all for person in people)

    def might_cover_objects(self) -> frozenset[tuple[str, str]]:
        """Each OPTION and OBJECT that a record taken out might cover.

        A BOOKING might cover any OBJECT, for its OPTION. An OFFER for OBJECTs might have a
        place for each OBJECT it named, at no cost.
        """
        things = self.file.objects
        booked = frozenset((option, thing.id) for option in self.covering_any for thing in things)
        return booked | self.open_to

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

    def might_do_anything(self) -> dict[tuple[str, str], str]:
        """Each OPTION and OBJECT where nobody knows what the OPTION does, in a COMPLETE set.

        The FACT about the two was taken out, and a FACT still says that the set of the
        OBJECT's transfers is COMPLETE.
        """
        file = self.file
        return {
            (option, thing): "any"
            for option, thing in self.undone
            if file.action(option, thing) is None and file.transfers_complete(thing) is not None
        }


def best_case_left(remaining: Remaining) -> tuple[World, list[tuple[str, str]]]:
    """The best case of what is left of a FILE, and the pairs that it leaves open.

    An OPTION with no FACT about a WANT does not SATISFY it there. That is as good as it gets:
    another OPTION meets every must on a WANT whose set is not COMPLETE, and a COMPLETE set
    leaves nothing unknown.

    An OPTION and a WANT that are reopened are different: nobody knows, and no other OPTION can
    stand in. Where the WANT is a must for some PERSON and a must-not for nobody, the best case
    is that the OPTION SATISFIES it. Where it is only a must-not, the best case is that it does
    not. Where it is both, a must may need what a must-not fears, so the pair is left open: it
    can turn out either way. The world returned says that an open pair does not SATISFY, and
    the pairs come with it, each an OPTION and a WANT.

    An OPTION and an OBJECT that are reopened are in the world itself: the OPTION does
    whichever of the four things suits the plan.
    """
    file = remaining.file
    best = best_case(file)
    wants = {want.id: want for want in file.wants}
    reopened = [pair for pair in remaining.reopened() if wants[pair[1]].musts]
    helps = {pair for pair in reopened if not wants[pair[1]].must_nots}
    either = [pair for pair in reopened if wants[pair[1]].must_nots]
    world = replace(
        best,
        rights=best.rights | remaining.might_cover(),
        uncovered=best.uncovered - remaining.might_cover_objects(),
        offered=best.offered - remaining.might_cover_objects(),
        satisfies=best.satisfies | helps,
        might_satisfy=best.might_satisfy | helps,
        does={**best.does, **remaining.might_do_anything()},
    )
    return world, either


def best_cases(remaining: Remaining) -> Iterator[World]:
    """Each best case of what is left of a FILE, one at a time. A FILE as it is read has one.

    There is one for each way the open pairs of ``best_case_left`` could turn out.
    """
    best, either = best_case_left(remaining)
    for chosen in product([False, True], repeat=len(either)):
        does = {pair for pair, yes in zip(either, chosen, strict=True) if yes}
        yield replace(
            best, satisfies=best.satisfies | does, might_satisfy=best.might_satisfy | does
        )


def can_work(remaining: Remaining) -> bool:
    """Whether any ITINERARY works in some best case of what is left of a FILE."""
    return any(any_works(remaining.file, world) for world in best_cases(remaining))


def with_no_offer(world: World) -> World:
    """The same world with every OFFER left out: what works here takes no place of one.

    An OBJECT that only a place of an OFFER can cover has nothing to cover it.
    """
    return replace(
        world,
        places={},
        payable=frozenset(),
        uncovered=world.uncovered | world.offered,
        offered=frozenset(),
    )


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
    So is saying two things about what one OPTION does with one OBJECT, or about where one
    OBJECT starts.
    """
    kind = frozenset(unknown)
    if not one_way_each(kind):
        raise ValueError("no possible world has two of these unknown FACTs together")
    return _world(file, kind)


def one_way_each(unknown: Iterable[Unknown]) -> bool:
    """Whether no two of these say different things about one and the same unknown.

    Those are whether one OPTION SATISFIES one WANT, what one OPTION does with one OBJECT, and
    where one OBJECT starts.
    """
    said: list[tuple[str, str | None, str | None]] = []
    for each in unknown:
        if each.what in ("satisfies", "does not satisfy"):
            said.append(("satisfies", each.option, each.want))
        elif each.what in _ACTIONS:
            said.append(("does", each.option, each.about))
        elif each.what in _STARTS:
            said.append(("starts", None, each.about))
    return len(said) == len(set(said))


def no_better_than(file: File, found: Iterable[Unknown]) -> World:
    """An upper bound that is no possible world: every unknown FACT helps whoever needs it.

    Everything is as in the best case, with two differences. Another OPTION is found only for
    the WANTs and PERSONs in ``found``. And an OPTION with no FACT about a WANT counts for a
    must while it breaks no must-not, which no possible world allows. One such OPTION is left
    out: one that a LOCK puts a PERSON into for whom the WANT is a must-not. Where it
    SATISFIES the WANT, that PERSON breaks the must-not in every ITINERARY, so nothing that
    works anywhere counts on it.

    Another transfer is the same: it brings only the OBJECTs in ``found``. An OPTION with no
    FACT about what it does with any other OBJECT does whichever of the four things suits
    the plan.

    Whatever works in a possible world with those other OPTIONs and those other transfers
    works here too. So this can show that they are not enough, whatever else turns out well.
    It can show nothing else, and no answer and no evidence is ever read from it.
    """
    best = best_case(file)
    found = tuple(found)
    locked = {(lock.option, person) for lock in file.locks for person in lock.persons}
    unknown = {
        (option.id, want.id)
        for option in file.options
        for want in file.wants
        if file.says(option.id, want.id) is None
        and not any((option.id, person) in locked for person in want.must_nots)
    }
    conditions = frozenset(
        (each.want, each.person)
        for each in found
        if each.want is not None and each.person is not None
    )
    moved = frozenset(each.about for each in found if each.what == "another transfer")
    does = dict(best.does)
    for thing in best.brought - moved:
        for option in file.options:
            if file.does_with(option.id, thing) is None:
                does[option.id, thing] = "any"
    return replace(
        best,
        satisfies=best.satisfies | unknown,
        another_option=conditions,
        does=does,
        brought=best.brought & moved,
    )


def with_one_required(file: File, unknown: Unknown) -> World:
    """The worst case, except that one OPTION requires one CAPABILITY of one PERSON only.

    ``unknown`` is a "requirement" that the FILE does not state.
    """
    if unknown.what != "requirement" or unknown.option is None or unknown.about is None:
        raise ValueError("only what an OPTION requires can be of one PERSON")
    worst = worst_case(file)
    return replace(worst, requires={**worst.requires, (unknown.option, unknown.about): "one"})


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
    # An OBJECT is the same: the BUDGETs that list it pay for its places, and where none
    # lists it, nobody knows who pays for them. An OFFER has places for PERSONs, or for the
    # OBJECTs it names.
    funded = {
        person.id
        for person in file.persons
        if not file.listed(person.id) and well(Unknown("funding", person=person.id))
    }
    funded |= {
        thing.id
        for thing in file.objects
        if not file.listed(thing.id) and well(Unknown("funding", about=thing.id))
    }
    payable: set[tuple[str, str]] = set()
    for offer in (fact for fact in file.facts if isinstance(fact, Offer)):
        price = offer.price
        if price is None:
            free = well(Unknown("price", offer.option, about=offer.id))
        else:
            free = not price.amount
        for buyer in offer.objects or [person.id for person in file.persons]:
            paid = price is not None and file.pays(buyer, price) is not None
            if free or paid or buyer in funded:
                payable.add((offer.id, buyer))
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
    # What each OPTION requires of each CAPABILITY, and who has it. A FACT settles either, and
    # a COMPLETE set settles what an OPTION with no FACT requires: nothing. Otherwise the FILE
    # does not say. At best the OPTION requires nothing and the PERSON has the CAPABILITY. At
    # worst the OPTION requires it of each PERSON, and the PERSON does not have it.
    requires: dict[tuple[str, str], str] = {}
    has: set[tuple[str, str]] = set()
    for capability in file.capabilities:
        for option in file.options:
            of = file.requires(option.id, capability.id)
            if of is None:
                nothing = well(Unknown("requirement", option.id, about=capability.id))
                of = "none" if nothing else "each"
            if of != "none":
                requires[option.id, capability.id] = of
        for person in file.persons:
            can = file.has(person.id, capability.id)
            if can or (can is None and well(Unknown("has", person=person.id, about=capability.id))):
                has.add((person.id, capability.id))
    # What each OPTION requires of each OBJECT, whether it refuses it and what it does with
    # it, and where each OBJECT starts. A FACT settles each, and a COMPLETE set settles what
    # an OPTION with no FACT requires, refuses or does: nothing. Otherwise the FILE does not
    # say. At worst the OPTION requires the OBJECT and refuses it, hands nothing over,
    # carries nothing and might keep it, and the OBJECT might be anywhere when the TRIP
    # starts. At best the OPTION does not require it and does not refuse it. Where the set
    # of an OBJECT's transfers is not COMPLETE, another transfer might bring it or take it
    # away at best. Where it is COMPLETE, the best start is whichever suits the plan.
    needs: set[tuple[str, str]] = set()
    open_needs: set[tuple[str, str]] = set()
    refuses: set[tuple[str, str]] = set()
    acts: dict[tuple[str, str], str] = {}
    undecided: set[tuple[str, str]] = set()
    begins: dict[str, Where] = {}
    begins_anywhere: set[str] = set()
    brought: set[str] = set()
    turns_out = {
        "keeps": "keeps",
        "hands over": "hands_over",
        "carries": "carries",
        "does not keep": "nothing",
        "does not carry": "might_keep",
        "does not keep or carry": "nothing",
    }
    favoured = {
        (each.what, each.option, each.about): each
        for each in kind or ()
        if each.what in (*_ACTIONS, *_STARTS)
    }
    # Whether an OPTION needs a right for an OBJECT, and whether something covers the
    # OBJECT there. A FACT settles the first, and so does a COMPLETE set for an OPTION with
    # no FACT: it needs none. Otherwise the FILE does not say: at best it needs none, at
    # worst it needs one. A BOOKING for the OPTION covers the OBJECTs it names. Another
    # right for the OBJECT can be found at best, and at worst there is none. Where a FACT
    # says that the rights to the OPTION for the OBJECT are COMPLETE, there is none at all.
    # What is left is a place of an OFFER for the OPTION that names the OBJECT.
    ticketed: set[tuple[str, str]] = set()
    uncovered: set[tuple[str, str]] = set()
    offered: set[tuple[str, str]] = set()
    for thing in file.objects:
        another = Unknown("another transfer", about=thing.id)
        if file.transfers_complete(thing.id) is None and well(another):
            brought.add(thing.id)
        for option in file.options:
            pair = (option.id, thing.id)
            ticket = file.needs_right_for(*pair)
            if ticket is None:
                ticket = not well(Unknown("needs no right for", option.id, about=thing.id))
            closed = file.rights_complete_for(*pair) is not None
            found_one = not closed and well(Unknown("another right for", option.id, about=thing.id))
            if ticket:
                ticketed.add(pair)
                if file.booking_for(*pair) is None and not found_one:
                    (offered if file.offers_for(*pair) else uncovered).add(pair)
            required = file.requires_object(*pair)
            if required is None:
                required = not well(Unknown("does not require", option.id, about=thing.id))
                if required:
                    open_needs.add(pair)
            if required:
                needs.add(pair)
            refused = file.refuses_object(*pair)
            if refused is None:
                refused = not well(Unknown("does not refuse", option.id, about=thing.id))
            if refused:
                refuses.add(pair)
            action = file.does_with(*pair)
            if action is None and kind is not None:
                # An OPTION that requires the OBJECT takes it along where it carries it. So
                # where nobody knows what such an OPTION does, it might: also where all
                # that is known is that it does not keep the OBJECT.
                found = [what for what in _ACTIONS if (what, *pair) in favoured]
                if not found:
                    action = "might_take" if required else "might_keep"
                elif found[0] == "does not keep" and required:
                    action = "might_carry"
                else:
                    action = turns_out[found[0]]
            if action is not None and action != "nothing":
                acts[pair] = action
            elif action is None:
                undecided.add(pair)
        start = file.object_starts(thing.id)
        with_whom = favoured.get(("starts with", None, thing.id))
        lies_at = favoured.get(("starts at", None, thing.id))
        if start is not None:
            begins[thing.id] = Where(start.person, start.place)
        elif kind is None:
            begins_anywhere.add(thing.id)
        elif with_whom is not None:
            begins[thing.id] = Where(person=with_whom.person)
        elif lies_at is not None:
            begins[thing.id] = Where(place=lies_at.place)
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
        requires,
        frozenset(has),
        frozenset(needs),
        frozenset(open_needs),
        frozenset(refuses),
        acts,
        begins,
        frozenset(begins_anywhere),
        frozenset(brought),
        frozenset(ticketed),
        frozenset(uncovered),
        frozenset(undecided),
        frozenset(offered),
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

    A FILE that lists an OBJECT is different. Where an OBJECT is turns on the order of all
    the steps that start at one instant, whatever time they take, and that order is part of
    the plan. So the steps are checked in the order the ITINERARY lists them, and in no
    other: the result is that of ``broken_as_listed``.
    """
    if file.objects:
        return broken_as_listed(file, world, itinerary)
    _well_formed(file, itinerary)
    fewest: list[Broken] | None = None
    for order in _in_each_order(itinerary):
        found = _in_this_order(file, world, itinerary, order)
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
    found, taking, together = _objects(file, world, placed)
    return [
        *_each_alone(file, world, itinerary, taking, together),
        *_along_each_path(file, world, itinerary, placed),
        *found,
    ]


def works_as_listed(file: File, world: World, itinerary: Itinerary) -> bool:
    """Whether this ITINERARY meets every CONSTRAINT with its steps in the order it lists them.

    The steps must be listed in an order their times allow: earlier starts first.
    """
    in_order = all(before.start <= after.start for before, after in pairwise(itinerary))
    return in_order and not broken_as_listed(file, world, itinerary)


def _in_this_order(
    file: File, world: World, itinerary: Itinerary, order: list[_Placed]
) -> list[Broken]:
    """The CONSTRAINTs that turn on the order of the steps, with the steps in one order.

    This is for a FILE that lists no OBJECT, so no OBJECT takes a place of an OFFER.
    """
    return [*_along_each_path(file, world, itinerary, order), *_objects(file, world, order)[0]]


# An OBJECT that takes a place of an OFFER in an OPTION of a plan: the OPTION, the OBJECT,
# the PERSONs that a finding about it names, and whether it is sure to take the place. It
# is not sure where the OBJECT only might be in the OPTION.
type _Placing = tuple[str, str, tuple[str, ...], bool]


def _each_alone(
    file: File,
    world: World,
    itinerary: Itinerary,
    taking: Sequence[_Placing] = (),
    together: Mapping[str, Collection[frozenset[str]]] | None = None,
) -> list[Broken]:
    """The CONSTRAINTs that hold or not whatever order the steps happen in.

    ``taking`` holds each OBJECT that takes a place of an OFFER in the order the steps
    happen in: where an OBJECT is turns on that order, and what its place costs is paid
    with the places of the PERSONs. ``together`` says which of its places an OBJECT takes
    together, as for ``way_to_pay``.
    """
    taking_part = {step.option: step.persons for step in itinerary if step.option is not None}
    moved, more = _where_a_transfer_brings_it(file, world, itinerary)
    return [
        *_locks(file, itinerary),
        *_starts(world, itinerary),
        *_durations(world, itinerary),
        *_musts(file, world, taking_part),
        *_must_nots(file, world, taking_part),
        *_requirements(file, world, taking_part),
        *_within(file, itinerary),
        *_rights(file, world, taking_part, [*taking, *more], together),
        *moved,
    ]


def taken_along(world: World, option: str, thing: str) -> bool:
    """Whether an OPTION takes an OBJECT along that another transfer brings, or might.

    The transfer puts the OBJECT at hand where a plan needs it, and nothing follows the
    OBJECT through the plan. An OPTION that requires the OBJECT and carries it takes it
    along whenever it happens. One of which nobody knows whether it requires the OBJECT
    might, and so might one that requires it, or might, of which nobody knows what it does
    with it.
    """
    if thing not in world.brought:
        return False
    unknown_action = world.does.get((option, thing)) in ("might_take", "might_carry")
    return unknown_action or goes_along(world, option, thing) is not None


def taken_with_no_right(world: World, option: str, thing: str) -> bool:
    """Whether an OPTION takes an OBJECT along that another transfer brings, with no right.

    ``taken_along`` says when it takes it along. Where such an OPTION needs a right for the
    OBJECT and nothing covers the OBJECT there, it cannot happen: no transfer cures that.
    """
    return (option, thing) in world.uncovered and taken_along(world, option, thing)


def _where_a_transfer_brings_it(
    file: File, world: World, itinerary: Itinerary
) -> tuple[list[Broken], list[_Placing]]:
    """What a plan breaks with an OBJECT that another transfer might bring.

    Nothing follows such an OBJECT through a plan: the transfer puts it at hand where the
    plan needs it, and takes it from a PERSON before an OPTION that refuses it or needs a
    right for it. No transfer cures what the plan itself does, or what an OPTION does with
    no choice.

    A hand-over of the plan is in an OPTION that hands the OBJECT over: the fourteenth
    CONSTRAINT otherwise. That OPTION does not refuse the OBJECT: the fifteenth otherwise,
    since nobody takes the OBJECT there. Both name the PERSON who was to have it. A carry
    of the plan is in an OPTION that carries the OBJECT: the fourteenth CONSTRAINT
    otherwise, and it names everybody who takes part. Where the FILE does not say what the
    OPTION does with the OBJECT, the world says it: the worst of it, or what a set of
    unknown FACTs says. The best case leaves it ``undecided``: there the OPTION does what
    suits the plan.

    The sixteenth CONSTRAINT is the same. An OPTION that takes the OBJECT along with no
    choice, or might, cannot happen where nothing covers the OBJECT there:
    ``taken_with_no_right`` says when. And a plan that hands the OBJECT over there, or
    carries it there by choice, does so with no right. A hand-over or a carry that does
    not happen needs none. The Broken names whoever is to have the OBJECT, or else
    everybody who takes part.

    Where an OFFER for the OPTION names the OBJECT, the OBJECT takes a place of it in
    those cases. The second result holds each of them, with the PERSONs that a finding
    about it names.
    """
    out: list[Broken] = []
    taking: list[_Placing] = []
    for step in itinerary:
        if step.option is None:
            continue
        takers = dict(step.handed)
        everybody = _in_file_order_of_persons(file, step.persons)
        for thing in file.objects:
            if thing.id not in world.brought:
                continue
            pair = (step.option, thing.id)
            action = "any" if pair in world.undecided else world.does.get(pair, "nothing")
            taker, loaded = takers.get(thing.id), thing.id in step.carried
            refused = pair in world.refuses
            if taker is not None and refused:
                out.append(Broken(Constraint.REFUSED, step.option, (taker,), object=thing.id))
            if taker is not None and action not in ("hands_over", "any"):
                out.append(Broken(Constraint.AT_HAND, step.option, (taker,), object=thing.id))
            if loaded and action not in ("carries", "any"):
                out.append(Broken(Constraint.AT_HAND, step.option, everybody, object=thing.id))
            if pair not in world.uncovered and pair not in world.offered:
                continue
            handed = taker is not None and action in ("hands_over", "any") and not refused
            carried = loaded and action in ("carries", "any")
            if handed or carried or taken_along(world, *pair):
                who = (taker,) if handed and taker is not None else everybody
                if pair in world.offered:
                    # The plan's own hand-over or carry is sure, and so is an OBJECT that
                    # goes along with no choice. One that only might go along is not.
                    sure = handed or carried or goes_along(world, *pair) == "sure"
                    taking.append((step.option, thing.id, who, sure))
                else:
                    out.append(Broken(Constraint.COVERED, step.option, who, object=thing.id))
    return out, taking


def _rights(
    file: File,
    world: World,
    taking_part: Mapping[str, tuple[str, ...]],
    taking: Sequence[_Placing] = (),
    together: Mapping[str, Collection[frozenset[str]]] | None = None,
) -> list[Broken]:
    """Each PERSON has the rights they need, and each place they take is paid for.

    The PERSONs with no right of their own take the places of the OPTION's OFFERs, as
    ``placed`` shares them out: as many as can pay for one have one. The others go in the
    FILE's order. Each takes a place that is still free, and cannot pay for it. Once no place
    is free, the rest have no right.

    ``taking`` holds each OBJECT that takes a place of an OFFER in one of these OPTIONs.
    They take the places of the OFFERs that name them in the same way. An OBJECT that is
    left with a free place of an OFFER that names it cannot pay for it: the eleventh
    CONSTRAINT. One with no such place has no right: the sixteenth. A cap counts what the
    PERSONs and the OBJECTs buy together. ``together`` says which of its places an OBJECT
    takes together, as for ``way_to_pay``.
    """
    out: list[Broken] = []
    order = {thing.id: number for number, thing in enumerate(file.objects)}
    things: dict[str, list[_Placing]] = {}
    for each in sorted(taking, key=lambda each: order[each[1]]):
        things.setdefault(each[0], []).append(each)
    for option, persons in taking_part.items():
        if option in world.needs_right:
            lacking = [person for person in persons if (option, person) not in world.rights]
            without = _in_file_order_of_persons(file, lacking)
            taken = placed(file, world, option, without)
            left_out = tuple(person for person in without if person not in taken)
            free = max(world.places.get(option, 0) - len(taken), 0)
            if left_out[free:]:
                out.append(Broken(Constraint.RIGHT, option, left_out[free:]))
            if left_out[:free]:
                out.append(Broken(Constraint.PAID, option, left_out[:free]))
        if option in things:
            out += _with_no_place(file, world, option, things[option])
    out += [
        Broken(Constraint.CAP, None, (), cap=cap) for cap in passed_by_the_bookings(file, world)
    ]
    places = {option: [thing for _, thing, _, _ in theirs] for option, theirs in things.items()}
    paying = way_to_pay(file, world, taking_part, places, together) if file.caps and not out else {}
    if paying is None:
        out.append(Broken(Constraint.CAP, None, ()))
    return out


def taking_a_place(file: File, world: World, itinerary: Itinerary) -> dict[str, dict[str, bool]]:
    """The OBJECTs that take a place of an OFFER in each OPTION of an ITINERARY, in this world.

    They are in the FILE's order. An OBJECT takes a place where an OFFER for the OPTION
    names it, nothing else covers it, and it needs the right there: a PERSON who takes part
    has it just before the OPTION starts, or might, or it is handed over or carried there.

    With each comes whether it is sure to take the place. It is not where the OBJECT only
    might be in the OPTION: nobody knows where it is, or whether the OPTION takes it along.
    It has the place either way, and a report says that it might have to be bought.
    """
    return places_taken(file, world, itinerary)[0]


def places_taken(
    file: File, world: World, itinerary: Itinerary
) -> tuple[dict[str, dict[str, bool]], dict[str, frozenset[frozenset[str]]]]:
    """What ``taking_a_place`` and ``taken_together`` give, from one walk through the plan."""
    order = {thing.id: number for number, thing in enumerate(file.objects)}
    _, followed, together = _objects(file, world, list(enumerate(itinerary)))
    _, moved = _where_a_transfer_brings_it(file, world, itinerary)
    taking: dict[str, dict[str, bool]] = {}
    for option, thing, _, sure in sorted([*followed, *moved], key=lambda each: order[each[1]]):
        taking.setdefault(option, {})[thing] = sure
    return taking, together


def taken_together(
    file: File, world: World, itinerary: Itinerary
) -> dict[str, frozenset[frozenset[str]]]:
    """The OPTIONs where each OBJECT takes a place of an OFFER together, in this world.

    An OBJECT is in one place at a time. Where nobody knows which, it might take a place
    in one OPTION or in another, and never in both. So each OBJECT that is followed through
    the ITINERARY and takes a place has its sets of OPTIONs here: one set for each way
    things can turn out, and only the sets that no other of them holds. The OBJECT takes
    the places of one set, and a cap counts the most that one of them costs.

    An OBJECT that another transfer might bring is left out: it can take every place that
    ``taking_a_place`` gives for it.
    """
    return places_taken(file, world, itinerary)[1]


def _with_no_place(
    file: File, world: World, option: str, taking: Sequence[_Placing]
) -> list[Broken]:
    """What the OBJECTs that take a place in one OPTION break, in the FILE's order of OBJECTs.

    Nothing is broken where ``placed`` gives each of them a place that can be paid for.
    Otherwise as many of them as can have a place of an OFFER that names them have one,
    whoever pays. Which of them are on a place that can be paid for comes first, going
    through them in the FILE's order: an OBJECT is, where that leaves a place for as many
    as before. Then the others have a place in the FILE's order, while one is left. An
    OBJECT on a place that cannot be paid for breaks the eleventh CONSTRAINT, and an OBJECT
    with no place the sixteenth.

    A car and a bike cross, a free rack takes either, and a car deck that nobody pays for
    takes only the car: the bike has the rack, and the car's place is not paid for. With
    the rack alone, at a price that a BUDGET pays for the bike only, the bike has the rack
    and the car has no right.
    """
    offers = file.offers_for_objects(option)
    things = [thing for _, thing, _, _ in taking]
    if len(placed(file, world, option, things, offers)) == len(things):
        return []
    named = {(each.id, thing) for each in offers for thing in each.objects}

    def seated(paying: Sequence[str]) -> dict[str, str]:
        """A place for as many as can have one, with these on places that can be paid for.

        These come first, and the others follow in the FILE's order.
        """
        theirs = {pair for pair in world.payable if pair[1] in paying}
        any_place = {pair for pair in named if pair[1] not in paying}
        trial = replace(world, payable=frozenset(theirs | any_place))
        rest = [thing for thing in things if thing not in paying]
        return placed(file, trial, option, [*paying, *rest], offers)

    most = len(seated(()))
    paid: list[str] = []
    for thing in things:
        found = seated((*paid, thing))
        if thing in found and len(found) == most:
            paid.append(thing)
    have = seated(paid)
    out: list[Broken] = []
    for _, thing, who, _ in taking:
        if thing not in paid:
            missing = Constraint.PAID if thing in have else Constraint.COVERED
            out.append(Broken(missing, option, who, object=thing))
    return out


def passed_by_the_bookings(file: File, world: World) -> list[str]:
    """Each cap that what the BOOKINGs charged passes in this world, or might, by itself."""
    return [
        cap.id
        for key, cap in file.caps.items()
        if (charged := world.spent.get(key, 0)) is None or charged > cap.limit.units
    ]


type Pair = tuple[str, str | None, tuple[str, str] | None, int]


def pairs_to_pay(file: File, world: World, option: str, buyer: str) -> list[Pair]:
    """Each pair of an OFFER and a BUDGET this PERSON can take for a place, in the FILE's order.

    ``buyer`` can be an OBJECT too: then the pairs are for a place that covers it, from the
    OFFERs that name it and the BUDGETs that list it.

    A pair holds the OFFER, the BUDGET, the cap that counts the purchase by its BUDGET and
    currency, and the price in ten-thousandths. The BUDGET is None for a place that costs
    nothing, and where money from outside the FILE pays: no cap counts those. BUDGETs with no
    cap in the currency of the price are alike, so only the first of them makes a pair.
    """
    able: list[Pair] = []
    for offer in file.offers_open_to(option, buyer):
        if (offer.id, buyer) not in world.payable:
            continue
        price = offer.price
        sources = () if price is None or not price.amount else file.payers(buyer, price.currency)
        if price is None or not sources:
            able.append((offer.id, None, None, 0))
            continue
        free_to_spend = False
        for budget in sources:
            key = (budget.id, price.currency)
            if key in file.caps:
                able.append((offer.id, budget.id, key, price.units))
            elif not free_to_spend:
                able.append((offer.id, budget.id, None, price.units))
                free_to_spend = True
    return able


def way_to_pay(
    file: File,
    world: World,
    taking_part: Mapping[str, Sequence[str]],
    taking: Mapping[str, Iterable[str]] | None = None,
    together: Mapping[str, Collection[frozenset[str]]] | None = None,
) -> dict[tuple[str, str], tuple[str, str | None]] | None:
    """The way to pay for the places these OPTIONs need, by the fixed rule, or None.

    ``taking_part`` gives the PERSONs in each OPTION, in the order of the steps. The result
    gives, for each OPTION and PERSON who takes a place, the OFFER it is from and the BUDGET
    that pays. The BUDGET is None for a place that costs nothing, and for a PERSON whom no
    BUDGET of the FILE lists. None: there is no way to pay in this world.

    ``taking`` gives the OBJECTs that take a place in each OPTION, in the FILE's order.
    The result has them too, by the OPTION and the OBJECT. Within an OPTION the PERSONs
    come first.

    ``together`` is for an OBJECT that might be in one place or another. It takes a place
    in each OPTION where it might need one, and each of those places has its OFFER and its
    BUDGET. But it pays only for the places it takes together: ``taken_together`` gives
    those sets of OPTIONs. So a cap counts the most that one of the sets costs. An OBJECT
    that ``together`` leaves out pays for every place it takes.

    With no cap in the FILE, each OPTION is by itself: ``placed`` shares out its places, and
    the first BUDGET that can pay pays. With caps, one BUDGET can run short over several
    OPTIONs, and a place that one PERSON leaves can be the only one another can pay for. So
    the purchases are taken in order, and each tries its pairs of an OFFER and a BUDGET in
    the FILE's order: the first that still fits, and that the purchases after it can follow.
    A purchase with no pair left sends the one before it on to its next pair.

    Once the search has had to go back, it looks at the purchases after a pair before it
    takes the pair: see ``_can_follow``. A pair that they cannot follow is passed over at
    once. The search would give it up anyway, after trying everything behind it, so the way
    to pay is the same. Where the first pairs all fit, nothing is looked at.

    From then on it also remembers where it has been: see ``_tried``. Different pairs for
    the purchases so far can leave the same places and the same room for the same purchases
    to come. Where those had no way to pay once, they have none now, and the pair that leads
    there is passed over too.

    A purchase draws on its cap what it adds to what the cap counts: see ``_Caps``.
    """
    # Those who take a place in each OPTION, with the OFFERs that have places for them.
    groups: list[tuple[str, Sequence[str], Sequence[Offer]]] = []
    for option, persons in taking_part.items():
        if option in world.needs_right:
            lacking = [person for person in persons if (option, person) not in world.rights]
            without = _in_file_order_of_persons(file, lacking)
            groups.append((option, without, file.offers(option)))
        if taking is not None and taking.get(option):
            groups.append((option, list(taking[option]), file.offers_for_objects(option)))
    buyers = [(option, buyer) for option, group, _ in groups for buyer in group]
    if not file.caps:
        chosen: dict[tuple[str, str], tuple[str, str | None]] = {}
        for option, group, offers in groups:
            taken = placed(file, world, option, group, offers)
            if len(taken) < len(group):
                return None
            prices = {offer.id: offer.price for offer in offers}
            for buyer in group:
                price = prices[taken[buyer]]
                payer = None if price is None else file.pays(buyer, price)
                chosen[option, buyer] = (taken[buyer], None if payer is None else payer.id)
        return chosen
    room: dict[tuple[str, str], int] = {}
    for key, cap in file.caps.items():
        charged = world.spent.get(key, 0)
        if charged is None or charged > cap.limit.units:
            return None
        room[key] = cap.limit.units - charged
    pairs = [pairs_to_pay(file, world, option, buyer) for option, buyer in buyers]
    left = {offer.id: offer.places for _, _, offers in groups for offer in offers}
    caps = _Caps(room, buyers, together or {})
    picked: list[tuple[int, int]] = []  # the pair each purchase takes, and what it drew
    start = 0
    looks_ahead = False
    no_way: set[_Tried] = set()  # where the purchases to come were found to have no way to pay
    while len(picked) < len(buyers):
        purchase = len(picked)
        able = pairs[purchase]
        found = None
        for number in range(start, len(able)):
            offer, _, key, units = able[number]
            if not left[offer] or (
                key is not None and room[key] < caps.draws(purchase, key, units)
            ):
                continue
            left[offer] -= 1
            drew = 0 if key is None else caps.take(purchase, key, units)
            if not looks_ahead or (
                _tried(left, caps) not in no_way and _can_follow(pairs, purchase + 1, left, caps)
            ):
                found = (number, drew)
                break
            left[offer] += 1
            if key is not None:
                caps.give_back(purchase, key, units, drew)
        if found is None:
            if not picked:
                return None
            # Every pair of this purchase has been tried from here, now or before the search
            # last came back to it.
            no_way.add(_tried(left, caps))
            looks_ahead = True
            last, drew = picked.pop()
            start = last + 1
            offer, _, key, units = pairs[len(picked)][last]
            left[offer] += 1
            if key is not None:
                caps.give_back(len(picked), key, units, drew)
            continue
        picked.append(found)
        start = 0
    return {
        buyer: (able[number][0], able[number][1])
        for buyer, able, (number, _) in zip(buyers, pairs, picked, strict=True)
    }


class _Caps:
    """What each cap still allows, while the purchases of a way to pay are made one by one.

    A purchase for a PERSON draws its price on the cap of its BUDGET. So does a purchase
    for an OBJECT, unless ``together`` says in which OPTIONs the OBJECT takes places
    together. Such an OBJECT takes the places of one of those sets, and nobody knows of
    which. So the cap counts the most that one set has cost so far, and a purchase draws
    what it adds to that. Two racks at 10 dollars each, on two trains that the bike cannot
    both be on, draw 10 dollars and then nothing.

    ``room`` is what each cap still allows. ``buyers`` names each purchase: the OPTION, and
    the PERSON or the OBJECT.
    """

    def __init__(
        self,
        room: dict[tuple[str, str], int],
        buyers: Sequence[tuple[str, str]],
        together: Mapping[str, Collection[frozenset[str]]],
    ) -> None:
        self.room = room
        # For each purchase of such an OBJECT: the OBJECT, and which of its sets hold the OPTION.
        self._sets: dict[int, tuple[str, list[int]]] = {}
        # What each set of each such OBJECT has cost so far, by cap.
        self._cost: dict[tuple[str, tuple[str, str]], list[int]] = {}
        for purchase, (option, buyer) in enumerate(buyers):
            sets = sorted(together.get(buyer, ()), key=sorted)
            holding = [number for number, some in enumerate(sets) if option in some]
            if holding:
                self._sets[purchase] = (buyer, holding)
                for key in room:
                    self._cost.setdefault((buyer, key), [0] * len(sets))

    def counted_by_sets(self, purchase: int) -> str | None:
        """The OBJECT of this purchase, where a cap counts the most it takes together."""
        return self._sets[purchase][0] if purchase in self._sets else None

    def draws(self, purchase: int, key: tuple[str, str], units: int) -> int:
        """What this purchase would add to what its cap counts, at this price."""
        if purchase not in self._sets:
            return units
        buyer, holding = self._sets[purchase]
        cost = self._cost[buyer, key]
        return max(max(cost[number] for number in holding) + units - max(cost), 0)

    def take(self, purchase: int, key: tuple[str, str], units: int) -> int:
        """Makes this purchase at this price. The result is what it drew on the cap."""
        drew = self.draws(purchase, key, units)
        self.room[key] -= drew
        if purchase in self._sets:
            buyer, holding = self._sets[purchase]
            for number in holding:
                self._cost[buyer, key][number] += units
        return drew

    def give_back(self, purchase: int, key: tuple[str, str], units: int, drew: int) -> None:
        """Undoes this purchase, the last one made that has not been undone."""
        self.room[key] += drew
        if purchase in self._sets:
            buyer, holding = self._sets[purchase]
            for number in holding:
                self._cost[buyer, key][number] -= units

    def so_far(self) -> tuple[int, ...]:
        """The room of each cap, and what each set of each OBJECT has cost."""
        return (*self.room.values(), *(units for cost in self._cost.values() for units in cost))


type _Tried = tuple[tuple[int, ...], tuple[int, ...]]


def _tried(left: Mapping[str, int], caps: _Caps) -> _Tried:
    """What decides whether the purchases still to come have a way to pay.

    It is the places each OFFER still has, the room each cap still has, and what each set
    of places that an OBJECT takes together has cost. Each purchase takes one place, so
    the places left also say how many purchases are behind, and which are still to come.
    Which pairs the purchases behind took plays no part beyond that. So the search for the
    rest goes the same way each time these are the same.
    """
    return tuple(left.values()), caps.so_far()


def _can_follow(
    pairs: Sequence[Sequence[Pair]], first: int, left: Mapping[str, int], caps: _Caps
) -> bool:
    """Whether nothing yet rules out the purchases from this one on. False is a proof.

    ``left`` says how many places each OFFER still has, and ``caps`` what each cap still
    allows, after the purchases before these. A pair is open to a purchase while its OFFER
    has a place and its cap has room for what the purchase would draw. The purchases
    before it only ever take places and room away, so the pair a purchase ends with is one
    that is open to it now.

    So a purchase with no pair open cannot be made. And where every pair still open to a
    purchase draws on one cap, that cap owes it the least that one of them draws. A cap
    that owes more than it has left cannot pay for all of them.

    An OBJECT that takes places together in one set of OPTIONs or in another is owed less.
    What a pair would draw now is the least that its purchase adds to the most the OBJECT
    takes together. Two such purchases can be for places that are never both taken, so
    the cap owes the OBJECT the largest of those amounts, and not their sum.

    True promises nothing: the purchases can still turn out to have no way to pay.
    """
    room = caps.room
    owed: dict[tuple[str, str], int] = {}
    most: dict[tuple[str, tuple[str, str]], int] = {}
    for purchase in range(first, len(pairs)):
        only: tuple[str, str] | None = None
        least = 0
        choice = False
        for offer, _, key, units in pairs[purchase]:
            if not left[offer]:
                continue
            if key is None:
                choice = True
                break
            draws = caps.draws(purchase, key, units)
            if room[key] < draws:
                continue
            if only is not None and key != only:
                choice = True
                break
            least = draws if only is None else min(least, draws)
            only = key
        if choice:
            continue
        if only is None:
            return False
        thing = caps.counted_by_sets(purchase)
        if thing is not None:
            before = most.get((thing, only), 0)
            most[thing, only] = max(before, least)
            least = most[thing, only] - before
        owed[only] = owed.get(only, 0) + least
        if owed[only] > room[only]:
            return False
    return True


def placed(
    file: File,
    world: World,
    option: str,
    persons: Sequence[str],
    offers: Sequence[Offer] | None = None,
) -> dict[str, str]:
    """The OFFER whose place each of these PERSONs takes, for as many as can have one.

    They are the PERSONs in an OPTION with no right of their own, in the FILE's order. Each
    can take only a place they can pay for, and no place is taken twice. A PERSON gets a place
    if there is a way to give one to them and to everybody before them who got one. Then each
    takes a place of the first OFFER, in the FILE's order, that leaves a way for the rest.

    With ``offers``, the places are those of these OFFERs for the OPTION, and ``persons``
    can hold OBJECTs: the OBJECTs that take a place there, in the FILE's order, and the
    OFFERs for OBJECTs. An OBJECT can take only a place of an OFFER that names it.

    This is bipartite matching, done with augmenting paths. One way to seat everybody who has
    a place is kept throughout. A PERSON finds a place by moving others along: they take a
    place, its holder takes another, and so on to a place that is free.
    """
    listed = file.offers(option) if offers is None else offers
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
    """An ITINERARY names PERSONs, PLACEs, OPTIONs and WAYs from the FILE, each OPTION once.

    An OBJECT is handed over in an OPTION, to a PERSON who takes part in it, and at most once
    in one OPTION. It is carried in an OPTION, at most once, and not where it is handed over
    there. In a FILE that lists an OBJECT, the steps come in the order they happen,
    earlier starts first: where an OBJECT is turns on that order.
    """
    persons = {person.id for person in file.persons}
    objects = {thing.id for thing in file.objects}
    if objects and any(before.start > after.start for before, after in pairwise(itinerary)):
        raise ValueError("an ITINERARY lists its steps in the order they happen")
    places = {place.id for place in file.places}
    options = {option.id: option for option in file.options}
    ways = {way.id: way for way in file.ways}
    listed = [step.option for step in itinerary if step.option is not None]
    if len(listed) != len(set(listed)):
        raise ValueError("an OPTION happens at most once")
    for step in itinerary:
        named_once = len(set(step.persons)) == len(step.persons)
        if not named_once or not persons.issuperset(step.persons):
            raise ValueError("each step names PERSONs from the FILE, each once")
        if step.option is None and not step.persons:
            raise ValueError("a PERSON takes each WAY")
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
        things = [thing for thing, _ in step.handed]
        takers = {person for _, person in step.handed}
        if things and (step.option is None or not objects.issuperset(things)):
            raise ValueError("only an OPTION hands over an OBJECT, and the FILE lists the OBJECT")
        if len(things) != len(set(things)) or not takers.issubset(step.persons):
            raise ValueError("an OPTION hands an OBJECT over once, to a PERSON who takes part")
        if step.carried and (step.option is None or not objects.issuperset(step.carried)):
            raise ValueError("only an OPTION carries an OBJECT, and the FILE lists the OBJECT")
        if len(step.carried) != len(set(step.carried)) or set(step.carried) & set(things):
            raise ValueError("an OBJECT is carried once in an OPTION, and not handed over there")


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


def _requirements(
    file: File, world: World, taking_part: Mapping[str, tuple[str, ...]]
) -> list[Broken]:
    """Each requirement of an OPTION is met by the PERSONs who take part in it.

    Where an OPTION requires a CAPABILITY of one PERSON, somebody in it has the CAPABILITY.
    Where it requires it of each PERSON, everybody in it has, and somebody is in it: a
    requirement is about the PERSONs in the OPTION, so an OPTION with a requirement happens
    only with a PERSON. Only who takes part counts: no time and no order changes it. One
    Broken for each OPTION and CAPABILITY, naming the PERSONs in the FILE's order: everybody
    in the OPTION where none of them has it, and those who lack it where each of them has
    to have it. It names nobody where nobody takes part.
    """
    out: list[Broken] = []
    for option, persons in taking_part.items():
        for capability in file.capabilities:
            of = world.requires.get((option, capability.id))
            if of is None:
                continue
            lacking = [person for person in persons if (person, capability.id) not in world.has]
            if not persons or (lacking and (of == "each" or len(lacking) == len(persons))):
                named = _in_file_order_of_persons(file, lacking)
                out.append(Broken(Constraint.REQUIRED, option, named, capability=capability.id))
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


# ------------------------------- Where each OBJECT is -------------------------------


class _Visit(NamedTuple):
    """An OPTION of a plan, as an OBJECT meets it.

    Its id, who takes part, the PLACE where it starts, and ``over``: the OPTIONs that have
    ended by the time it starts. Only a walk through a finished plan fills ``over`` in. A
    search over orders leaves it empty, and says itself when a carried OBJECT has arrived.
    """

    option: str
    persons: tuple[str, ...]
    origin: str
    over: frozenset[str] = frozenset()


# Each hand-over and each carry in one OPTION: an OBJECT, and the PERSON who has it from then
# on. A carry has no PERSON.
type _Taken = tuple[tuple[str, str | None], ...]
# What an OBJECT breaks at one OPTION of a plan: the position of the OPTION, the CONSTRAINT,
# and what the plan has there that cannot be: the PERSON who was to have the OBJECT where the
# plan hands it over, or ``_CARRY`` where the plan carries it. None for a check of the OPTION.
type _Miss = tuple[int, Constraint, str | None]
# Where an OBJECT takes a place of an OFFER: the position of the OPTION, what the plan
# has there, as for ``_Miss``, and whether the OBJECT is sure to take the place.
type _Place = tuple[int, str | None, bool]
# The OPTIONs where one OBJECT takes a place of an OFFER together, as things can turn out:
# one set for each way, and only the sets that no other of them holds. Nobody knows which of
# Alex and Jo has the bike. Alex takes the north train and Jo the south: the bike takes a
# place on one of them, and never on both.
type _Together[T] = frozenset[frozenset[T]]
# The same for an OBJECT part of the way through a plan: by each place where it might be,
# the places it has taken on the ways that lead there. It is empty for an OBJECT that no
# OFFER names: nothing is kept for it.
type _SoFar[T] = frozenset[tuple[Where, _Together[T]]]
# One way an OBJECT can go: what it breaks, where it might be when the TRIP starts and then
# after each OPTION, where it might be just before each OPTION starts, where it takes a
# place of an OFFER, and which of those places it takes together, by position.
type _Run = tuple[
    tuple[_Miss, ...],
    tuple[frozenset[Where], ...],
    tuple[frozenset[Where], ...],
    tuple[_Place, ...],
    _Together[int],
]
# A way so far: the picks that led there, what an OBJECT breaks, where it might be, where it
# takes a place, and which places it has taken together by each place where it might be.
type _Way = tuple[
    tuple[int, ...],
    tuple[_Miss, ...],
    tuple[frozenset[Where], ...],
    tuple[frozenset[Where], ...],
    tuple[_Place, ...],
    _SoFar[int],
]
_CARRY = ""  # stands for a carry where a PERSON's id stands for a hand-over: no id is empty


def _begins(file: File, world: World, thing: str) -> list[frozenset[Where]]:
    """Each way this world lets an OBJECT start: the places where it might be then.

    One way with one place, where the world says where the OBJECT starts. Where the start is
    the world's to pick, each place is a way. Otherwise nobody knows where it starts: that
    is one way, with every place at once.
    """
    if thing in world.starts:
        return [frozenset({world.starts[thing]})]
    people = [Where(person=person.id) for person in file.persons]
    anywhere = [*people, *(Where(place=place.id) for place in file.places), Where()]
    if thing in world.starts_anywhere:
        return [frozenset({each}) for each in anywhere]
    return [frozenset(anywhere)]


def within_reach(places: Set[Where], persons: Sequence[str], origin: str) -> bool:
    """Whether an OBJECT is at hand for an OPTION, wherever among these places it is.

    Each place is at hand: the PLACE where the OPTION starts, or a PERSON who takes part.
    An OBJECT that is in an OPTION is at hand for nothing.
    """
    return all(each.person in persons or each.place == origin for each in places)


def brought_in(places: Set[Where], persons: Sequence[str]) -> bool:
    """Whether a PERSON who takes part in an OPTION has an OBJECT, or might.

    That is so where one of these places is such a PERSON.
    """
    return any(each.person in persons for each in places)


def arrived(
    places: frozenset[Where], over: Set[str], ends_at: Mapping[str, str]
) -> frozenset[Where]:
    """Where an OBJECT might be once these OPTIONs are over.

    An OBJECT that was carried in one of them lies at the PLACE where that OPTION ends.
    ``ends_at`` gives that PLACE for each OPTION.
    """
    there = {
        each: Where(place=ends_at[each.option])
        for each in places
        if each.option is not None and each.option in over
    }
    return frozenset(there.get(each, each) for each in places) if there else places


def goes_along(world: World, option: str, thing: str) -> str | None:
    """Whether an OBJECT goes along in an OPTION with no choice: "sure", "might" or None.

    It does where the OPTION requires the OBJECT and carries it. Where nobody is sure that
    the OPTION requires it, it might: a plan that chooses the carry has the OBJECT go along
    for sure, and a plan that does not has to hold with both.
    """
    pair = (option, thing)
    if world.does.get(pair) != "carries" or pair not in world.needs:
        return None
    return "might" if pair in world.open_needs else "sure"


def _left(
    does: str,
    places: frozenset[Where],
    persons: Sequence[str],
    origin: str,
    option: str,
    refused: bool = False,
) -> frozenset[Where]:
    """Where an OBJECT might be once an OPTION has done what it does with no choice.

    An OPTION that keeps it moves it from whoever takes part to the PLACE where the OPTION
    starts. One that might keep it leaves it in both places. One that might take it along
    leaves it where it was and in the OPTION, where it is at hand in one of the places it
    might be. "might_take" is both: it might keep it, and it might take it along.
    "might_carry" is the second alone.

    An OPTION that refuses the OBJECT takes it from no PERSON. It keeps nothing, and it
    takes along only what lies at the PLACE where it starts.

    "carries_unless_refused" is for an OPTION that takes the OBJECT along with no choice,
    where nobody knows whether it refuses it. What lies where it starts is in the OPTION.
    What a PERSON who takes part has might be: it stays with them if the OPTION refuses it.
    """
    held = {each for each in places if each.person in persons}
    lying = {each for each in places if each.place == origin}
    after = places
    if not refused and held:
        if does == "keeps":
            after = (places - held) | {Where(place=origin)}
        elif does in ("might_keep", "might_take"):
            after = places | {Where(place=origin)}
    if does in ("might_take", "might_carry") and (lying or (held and not refused)):
        after = after | {Where(option=option)}
    if does == "carries_unless_refused" and (lying or held):
        after = (places - lying) | {Where(option=option)}
    return after


def _moved(
    places: frozenset[Where], persons: Sequence[str], origin: str, refused: bool, to: Where
) -> frozenset[Where]:
    """Where an OBJECT might be once an OPTION has moved it from each place where it was at hand.

    That is a hand-over, a carry that the travelers choose, and a carry that is no choice.
    The OBJECT is at hand where it lies at the PLACE where the OPTION starts, or a PERSON who
    takes part has it. An OPTION that refuses the OBJECT takes it from no PERSON. Where the
    OBJECT might be somewhere else, it is still there in that case. So afterwards it is
    where the OPTION put it, or in a place where it was out of reach.
    """
    reached = {
        each for each in places if each.place == origin or (each.person in persons and not refused)
    }
    return (places - reached) | {to} if reached else places


def _after(
    does: str,
    places: frozenset[Where],
    visit: _Visit,
    refused: bool,
    taker: str | None,
    loaded: bool,
    along: str | None,
) -> frozenset[Where]:
    """Where an OBJECT might be after an OPTION of a plan, from where it might be before it.

    The OPTION does what it does with no choice. Then the OBJECT is handed over to
    ``taker``, where the plan hands it over there and the OPTION does that. Then it is
    carried: where the plan carries it there, with ``loaded``, or with no choice, as
    ``along`` says.

    Each place is moved by itself. So the result for several places is the results for each
    of them, taken together.
    """
    option, persons, origin, _ = visit
    after = _left(does, places, persons, origin, option, refused)
    if taker is not None and does == "hands_over" and not refused:
        after = _moved(after, persons, origin, False, Where(person=taker))
    if does == "carries" and (loaded or along == "sure"):
        return _moved(after, persons, origin, refused, Where(option=option))
    if along == "might":
        return _left("might_carry", after, persons, origin, option, refused)
    return after


def _takes(was: Where, now: Where, visit: _Visit, taker: str | None = None) -> bool:
    """Whether an OBJECT needs the right in an OPTION, on one way through it.

    The OBJECT is in one place before the OPTION and in one place after it. It needs the
    right where a PERSON who takes part has it, where it is handed over to ``taker``, and
    where it is in the OPTION afterwards.
    """
    handed = taker is not None and now == Where(person=taker)
    return was.person in visit.persons or handed or now == Where(option=visit.option)


def _never(was: Where, now: Where) -> bool:
    """For an OPTION where the OBJECT takes no place of an OFFER, whatever way it goes."""
    return False


def _put(places: frozenset[Where], to: Where) -> frozenset[Where]:
    """For an OPTION that moves the OBJECT to one place, from wherever it is."""
    return frozenset({to})


def _stay(places: frozenset[Where]) -> frozenset[Where]:
    """For an OPTION that leaves the OBJECT where it is."""
    return places


def _largest[T](sets: Iterable[frozenset[T]]) -> _Together[T]:
    """These sets, without each one that another of them holds."""
    found = set(sets)
    return frozenset(one for one in found if not any(one < other for other in found))


def _no_more[T](one: Iterable[frozenset[T]], other: Collection[frozenset[T]]) -> bool:
    """Whether some set of the second holds each set of the first.

    Then whatever pays for the places of the second pays for those of the first: a cap
    counts the most that an OBJECT takes together.
    """
    return all(any(mine <= theirs for theirs in other) for mine in one)


def _all_together[T](so_far: _SoFar[T]) -> _Together[T]:
    """The places an OBJECT has taken together, wherever it might be now."""
    return _largest(each for _, sets in so_far for each in sets)


def _not_yet[T](places: Iterable[Where]) -> _SoFar[T]:
    """An OBJECT that might be in these places and has taken no place of an OFFER."""
    return frozenset((each, frozenset({frozenset[T]()})) for each in places)


def _takes_no_more[T](one: _SoFar[T], other: _SoFar[T]) -> bool:
    """Whether the first has taken no more together than the second, place by place.

    Both are for the same places where the OBJECT might be. Then the first can stand in for
    the second: whatever follows, some way of the second takes each set of places that a
    way of the first takes.
    """
    theirs = dict(other)
    return all(_no_more(sets, theirs[where]) for where, sets in one)


def _further[T](
    so_far: _SoFar[T],
    onward: Callable[[frozenset[Where]], frozenset[Where]],
    takes: Callable[[Where, Where], bool],
    here: T,
) -> _SoFar[T]:
    """The places an OBJECT has taken together, one OPTION further.

    ``onward`` says where the OBJECT might be afterwards, from where it might be before.
    It is asked about one place at a time: the OBJECT is in one place, and each place it
    might go to from there is one way things can turn out. ``takes`` says whether the
    OBJECT takes a place of an OFFER on the way from one place to another, and ``here``
    names that place.
    """
    reached: dict[Where, set[frozenset[T]]] = {}
    for was, sets in so_far:
        for now in onward(frozenset({was})):
            taken = {each | {here} for each in sets} if takes(was, now) else sets
            reached.setdefault(now, set()).update(taken)
    return frozenset((where, _largest(sets)) for where, sets in reached.items())


def _least_broken(
    world: World,
    thing: str,
    visits: Sequence[_Visit],
    begins: Sequence[frozenset[Where]],
    handed: Mapping[str, str],
    carried: Set[str],
    ends_at: Mapping[str, str],
) -> list[_Run]:
    """How one OBJECT goes through the OPTIONs of a plan, in the order they happen.

    ``visits`` holds those OPTIONs in that order, each with the OPTIONs that are over by the
    time it starts. ``handed`` names, for each OPTION that hands the OBJECT over in the plan,
    the PERSON who has it from then on. ``carried`` holds each OPTION in which the plan
    carries the OBJECT, and ``ends_at`` gives the PLACE where each OPTION ends.

    The result says what the OBJECT breaks, each with the position of the OPTION in
    ``visits``. Where the OPTION requires the OBJECT and it is not at hand, that is the
    fourteenth CONSTRAINT. Where the OPTION refuses it and a PERSON who takes part has it,
    or might, that is the fifteenth. Where the plan hands the OBJECT over there and it
    cannot be, the PERSON who was to have it comes with it: the fifteenth CONSTRAINT where
    the OPTION refuses the OBJECT, and the fourteenth where the OBJECT is not at hand or
    the OPTION does not hand it over. One hand-over can break both. Where the plan carries
    the OBJECT there and it cannot be, that is the fourteenth CONSTRAINT, and ``_CARRY``
    comes with it: the OBJECT is not at hand, or the OPTION does not carry it. And the
    result says where the OBJECT might be: when the TRIP starts and then after each OPTION,
    and just before each OPTION starts.

    An OBJECT that was carried lies at the PLACE where the carrying OPTION ends once that
    OPTION is over. So each OPTION first finds the OBJECT there, where it starts no earlier
    than that end. Then it checks what it requires and what it refuses, then keeps what it
    keeps, and then the OBJECT is handed over or carried in it. An OPTION that refuses the
    OBJECT takes it from no PERSON: it keeps the OBJECT from nobody, and nobody takes the
    OBJECT there. It carries the OBJECT only where no PERSON who takes part has it. A
    hand-over and a carry move the OBJECT from each place where it is at hand, also in a
    plan that they break: where the OBJECT might be out of reach, it is still there in
    that case, and it is moved in the other. An OPTION that requires the OBJECT and carries
    it takes it along in the same way, whether or not the requirement is met. In a
    world that leaves nothing to pick there is one way to go. An OPTION that does whichever
    thing suits the plan gives a way for each: it leaves the OBJECT alone, it keeps it, it
    hands it over as the plan says, or it carries it as the plan says. Where it does not
    hand it over, a hand-over that the plan has there is broken, and a carry is the same.
    Each start the world can pick gives a way too. Then the result is the way that breaks
    the least, and among those the first: the start that ``begins`` gives first, and then,
    going through the OPTIONs in order, the way in which the OPTION leaves the OBJECT alone,
    then the way in which it keeps it, then the way in which it hands it over, then the way
    in which it carries it.

    Not every way is tried. All that matters about a way so far is where it leaves the
    OBJECT: what can follow turns on nothing else. Take two ways that leave it in the same
    places. The same ends can follow both, and the way that comes first stays first with each
    of them: it breaks no more, and where it breaks as much, the first difference is still
    the first difference. So after each OPTION, only the first way is kept for each set of
    places where the OBJECT might be. Those are few, where all the ways are as many as two
    to the power of the OPTIONs that do whichever thing suits.

    Where an OFFER for the OPTION names the OBJECT and nothing else covers it, the OBJECT
    takes a place of the OFFER in the cases where it needs the right. That breaks nothing
    here: whether the place can be had and paid for turns on what everybody else takes. So
    a way also says where the OBJECT takes a place, and two ways that leave the OBJECT in
    the same places are both kept where they take places in different OPTIONs. The result
    holds the ways that break the least, the first of them first.

    An OBJECT that might be in one place or another takes a place in one OPTION or in
    another, and may never take both. A cap counts the most it takes together. So a way
    also says which places the OBJECT takes together: each place where it might be is
    followed by itself, as ``_further`` says. Two ways that leave the OBJECT in the same
    places are both kept where they differ in that. A way is left out of the result where
    a way before it takes no more together: whatever can be paid for with the later way
    can be paid for with the earlier one. In a world that leaves nothing to pick there is
    one way.
    """
    named = any((visit.option, thing) in world.offered for visit in visits)
    reached: dict[tuple[frozenset[Where], tuple[_Place, ...], _SoFar[int]], _Way] = {}
    for pick, start in enumerate(begins):
        none_yet: _SoFar[int] = _not_yet(start) if named else frozenset()
        reached.setdefault((start, (), none_yet), ((pick,), (), (start,), (), (), none_yet))
    for position, visit in enumerate(visits):
        option, persons, origin, over = visit
        action = world.does.get((option, thing), "nothing")
        refused = (option, thing) in world.refuses
        uncovered = (option, thing) in world.uncovered
        offered = (option, thing) in world.offered
        taker = handed.get(option)
        loaded = option in carried
        along = goes_along(world, option, thing)
        takes = partial(_takes, visit=visit, taker=taker) if offered else _never
        # Whatever was carried in an OPTION that is over lies where that OPTION ends.
        found_there: dict[tuple[frozenset[Where], tuple[_Place, ...], _SoFar[int]], _Way] = {}
        for (places, _, so_far), way in reached.items():
            lying = arrived(places, over, ends_at)
            if so_far and lying != places:
                arrive = partial(arrived, over=over, ends_at=ends_at)
                so_far = _further(so_far, arrive, _never, position)
            there = (lying, way[4], so_far)
            known = found_there.get(there)
            if known is None or (len(way[1]), way[0]) < (len(known[1]), known[0]):
                found_there[there] = (*way[:5], so_far)
        following: dict[tuple[frozenset[Where], tuple[_Place, ...], _SoFar[int]], _Way] = {}
        for (places, _, so_far), (picks, broken, trail, seen, bought, _) in found_there.items():
            if (option, thing) in world.needs and not within_reach(places, persons, origin):
                broken = (*broken, (position, Constraint.AT_HAND, None))
            held = brought_in(places, persons)
            if refused and held:
                broken = (*broken, (position, Constraint.REFUSED, None))
            choices = (action,)
            if action == "any":
                choices = ("nothing", "keeps", "hands_over", "carries")
            for pick, does in enumerate(choices):
                if action == "any" and does == "hands_over" and taker is None:
                    continue  # with no hand-over planned, that is "nothing"
                if action == "any" and does == "carries" and not loaded:
                    continue  # and so is a carry that is not planned
                # A hand-over and a carry need the OBJECT at hand once the OPTION has done
                # what it does with no choice.
                found = broken
                at_hand = within_reach(
                    _left(does, places, persons, origin, option, refused), persons, origin
                )
                if taker is not None:
                    if refused:
                        found = (*found, (position, Constraint.REFUSED, taker))
                    if does != "hands_over" or not at_hand:
                        found = (*found, (position, Constraint.AT_HAND, taker))
                if loaded and (does != "carries" or not at_hand):
                    found = (*found, (position, Constraint.AT_HAND, _CARRY))
                # It is handed over as the plan says. It is carried by choice, or it goes
                # along with no choice, and the plan has no entry for that.
                onward = partial(
                    _after,
                    does,
                    visit=visit,
                    refused=refused,
                    taker=taker,
                    loaded=loaded,
                    along=along,
                )
                after = onward(places)
                # A right is needed where a PERSON who takes part has the OBJECT, where it
                # is handed over and where it is carried. That is one requirement, so one
                # finding: for whoever has it, or else for whoever takes it, or else for
                # the carry. A hand-over or a carry that does not happen needs none.
                needed: tuple[str | None, ...] = ()
                if held:
                    needed = (None,)
                elif taker is not None and Where(person=taker) in after:
                    needed = (taker,)
                elif Where(option=option) in after:
                    needed = (_CARRY,)
                if uncovered and needed:
                    found = (*found, (position, Constraint.COVERED, needed[0]))
                # Where an OFFER names the OBJECT, it takes a place of it there instead.
                # That is sure where whoever might have it takes part, and where it is
                # with the PERSON who takes it, or in the OPTION, and nowhere else.
                sure = (
                    all(each.person in persons for each in places)
                    or (taker is not None and after == frozenset({Where(person=taker)}))
                    or after == frozenset({Where(option=option)})
                )
                paid = bought
                if offered and needed:
                    paid = (*bought, (position, needed[0], sure))
                later = _further(so_far, onward, takes, position) if so_far else so_far
                known = following.get((after, paid, later))
                if known is None or (len(found), (*picks, pick)) < (len(known[1]), known[0]):
                    following[after, paid, later] = (
                        (*picks, pick),
                        found,
                        (*trail, after),
                        (*seen, places),
                        paid,
                        later,
                    )
        reached = following
    ways = sorted(reached.values(), key=lambda way: (len(way[1]), way[0]))
    kept: list[_Run] = []
    for _, broken, trail, seen, bought, so_far in ways:
        if len(broken) > len(ways[0][1]):
            break
        together = _all_together(so_far) or frozenset({frozenset[int]()})
        if not any(_no_more(run[4], together) for run in kept):
            kept.append((broken, trail, seen, bought, together))
    return kept


# Where an OBJECT might be, and the arrivals that got it there: each an OPTION that carried
# it, and the OPTION that first used it afterwards. The second starts no earlier than the
# first ends. Then the OPTIONs in which it has taken places of OFFERs together.
type _Spot = tuple[frozenset[Where], tuple[tuple[str, str], ...], _SoFar[str]]
# Each ``_Spot`` that a search has reached, with the first hand-overs and carries that lead
# to it.
type _Reached = dict[_Spot, _Ranked]
# What a choice counts on: its arrivals, and the places of OFFERs it takes together.
type _Counted = tuple[tuple[tuple[str, str], ...], _SoFar[str]]


def _to_begin(world: World, thing: str, begins: Iterable[frozenset[Where]]) -> _Reached:
    """Where a search for one OBJECT starts: each way it can start, with nothing done yet."""
    named = any(each == thing for _, each in world.offered)
    return {(start, (), _not_yet(start) if named else frozenset()): () for start in begins}


def _first_hand_overs(
    world: World,
    thing: str,
    visits: Sequence[_Visit],
    begins: Sequence[frozenset[Where]],
    rank: Callable[[str, str | None], tuple[int, int]],
    ends_at: Mapping[str, str],
) -> _Reached:
    """The hand-overs and carries of one OBJECT that work through these OPTIONs in order.

    The result is empty where no choice of them keeps the fourteenth and the fifteenth
    CONSTRAINT. Otherwise it holds each place where a choice can leave the OBJECT, with the
    arrivals that the choice counts on, and the choice that the rules put first among those
    that end there: the fewest hand-overs and carries, and among those the OPTION listed
    first and then the PERSON listed first, going through them in the order they happen.
    ``rank`` gives the positions of an OPTION and a PERSON in the FILE, and a carry comes
    with no PERSON.

    Not every choice is tried. All that matters about a choice so far is where it leaves the
    OBJECT, and which arrivals it counts on: what can follow turns on the first, and which
    start times can keep it turns on the second. Take two choices that leave the OBJECT in
    the same places, where the first counts on no arrival that the second does not count on,
    and the rules put the first no later. The same hand-overs and carries can follow both,
    with the same arrivals. Start times that keep the second keep the first. And the first
    stays first with whatever follows: it has no more hand-overs and carries, and where it
    has as many, the first difference is still the first difference. So the second is never
    the choice shown, and it is left out. Those kept are few, where all the choices are as
    many as the PERSONs of each OPTION multiplied together.

    Two choices that leave the OBJECT in the same place are both kept where each counts on
    an arrival that the other does not. A slow ferry and a fast one both carry the bag to
    the island, and only one of them may be there in time: the start times decide, and they
    are not known here.

    A place of an OFFER is the same. Where an OFFER for an OPTION names the OBJECT and
    nothing else covers it, the OBJECT takes a place there in the cases where it needs the
    right. Whether that place can be had and paid for turns on what everybody else takes,
    and that is not known here. So a choice is left out only where the other also takes
    no more places together, wherever the OBJECT might be: ``_takes_no_more`` says when.
    Sam hands the bike to Jo before the ferry: that is one hand-over more, and the only
    plan the trip money can pay for.
    """
    reached = _to_begin(world, thing, begins)
    for visit in visits:
        reached = _one_further(world, thing, reached, visit, rank, ends_at)
    return reached


def _one_further(
    world: World,
    thing: str,
    reached: _Reached,
    visit: _Visit,
    rank: Callable[[str, str | None], tuple[int, int]],
    ends_at: Mapping[str, str],
) -> _Reached:
    """The search of ``_first_hand_overs``, one OPTION further.

    ``reached`` holds each place where the OBJECT might be before the OPTION, with the
    arrivals counted on so far and the places of OFFERs it has taken together, and the
    first hand-overs and carries that lead there. The result holds the same for after the
    OPTION. It is empty where the fourteenth or the fifteenth CONSTRAINT cannot be kept,
    whatever was handed over or carried.

    An OPTION uses the OBJECT where it requires it, or where the OBJECT is handed over or
    carried in it. An OBJECT that was carried is used again only once the OPTION that
    carried it is over. So the first OPTION that uses it afterwards counts on that arrival:
    it starts no earlier than the carrying OPTION ends. Where nobody knows when that OPTION
    ends, nothing uses the OBJECT again. An OPTION that does not use the OBJECT counts on
    nothing. It does the same with the OBJECT in the carrying OPTION and at the PLACE where
    that ends: a refusal asks only who has the OBJECT, and an OPTION keeps it only from a
    PERSON. So the search leaves the OBJECT in the carrying OPTION until something uses it.
    """
    option, persons, origin, _ = visit
    refused = (option, thing) in world.refuses
    # Where the OPTION needs a right for the OBJECT and nothing covers it, no PERSON who
    # takes part has it, and it is not handed over or carried there, by choice or with none.
    uncovered = (option, thing) in world.uncovered
    # Where an OFFER names the OBJECT instead, it takes a place of it in those cases.
    offered = (option, thing) in world.offered
    action = world.does.get((option, thing), "nothing")
    kept: dict[frozenset[Where], dict[_Counted, _Ranked]] = {}

    def keep(
        places: frozenset[Where],
        arrivals: tuple[tuple[str, str], ...],
        bought: _SoFar[str],
        taken: _Ranked,
    ) -> None:
        """Keep this choice, unless one that is kept counts on no more and comes no later.

        A choice counts on its arrivals and on the places of OFFERs it takes together.
        """
        there = kept.setdefault(places, {})
        counted, rank = set(arrivals), (len(taken), taken)
        if any(
            counted.issuperset(others)
            and _takes_no_more(theirs, bought)
            and (len(first), first) <= rank
            for (others, theirs), first in there.items()
        ):
            return
        for key in [
            (others, theirs)
            for (others, theirs), first in there.items()
            if counted.issubset(others)
            and _takes_no_more(bought, theirs)
            and rank <= (len(first), first)
        ]:
            del there[key]
        there[arrivals, bought] = taken

    def further(
        so_far: _SoFar[str],
        onward: Callable[[frozenset[Where]], frozenset[Where]],
        taker: str | None = None,
    ) -> _SoFar[str]:
        """The places taken together once the OBJECT has gone ``onward`` in this OPTION.

        It takes a place here where a PERSON who takes part has it, or might, and where
        it is in the OPTION afterwards or handed over in it.
        """
        if not so_far:
            return so_far
        takes = partial(_takes, visit=visit, taker=taker) if offered else _never
        return _further(so_far, onward, takes, option)

    aboard = Where(option=option)
    for (places, arrivals, before), taken in reached.items():
        # Where the OBJECT is for an OPTION that uses it, with the arrivals that takes. None
        # where nobody knows when an OPTION that carried it ends.
        in_use: tuple[frozenset[Where], tuple[tuple[str, str], ...]] | None = (places, arrivals)
        there_by_then = before
        carriers = sorted({each.option for each in places if each.option is not None})
        if carriers:
            in_use = None
            if all(world.terms[carrier].longest is not None for carrier in carriers):
                there = arrived(places, set(carriers), ends_at)
                more = ((carrier, option) for carrier in carriers)
                in_use = (there, tuple(sorted((*arrivals, *more))))
                if before:
                    arrive = partial(arrived, over=set(carriers), ends_at=ends_at)
                    there_by_then = _further(before, arrive, _never, option)
        if (option, thing) in world.needs:
            if in_use is None or not within_reach(in_use[0], persons, origin):
                continue
            places, arrivals = in_use
            before = there_by_then
        if (refused or uncovered) and brought_in(places, persons):
            continue
        at_hand = in_use is not None and within_reach(in_use[0], persons, origin)
        for does in ("nothing", "keeps", "hands_over", "carries") if action == "any" else (action,):
            if does not in ("hands_over", "carries"):
                # It takes the OBJECT from no PERSON where it refuses it.
                left = _left(does, places, persons, origin, option, refused)
                if not (uncovered and aboard in left):
                    leave = partial(
                        _left, does, persons=persons, origin=origin, option=option, refused=refused
                    )
                    keep(left, arrivals, further(before, leave), taken)
                continue
            along = goes_along(world, option, thing)
            if along == "sure":
                # It goes along with no choice: the OPTION requires it, so it is at hand.
                if not uncovered:
                    load = partial(_put, to=aboard)
                    keep(frozenset({aboard}), arrivals, further(before, load), taken)
                continue
            if along == "might":
                # A plan that does not choose the carry has to hold with both.
                gone = _left("might_carry", places, persons, origin, option, refused)
                if uncovered and aboard in gone:
                    continue
                go = partial(
                    _left,
                    "might_carry",
                    persons=persons,
                    origin=origin,
                    option=option,
                    refused=refused,
                )
                keep(gone, arrivals, further(before, go), taken)
            elif action != "any":  # with "any" that is "nothing"
                keep(places, arrivals, further(before, _stay), taken)
            if in_use is None or not at_hand or uncovered:
                continue
            if does == "carries":
                loaded = further(there_by_then, partial(_put, to=aboard))
                keep(frozenset({aboard}), in_use[1], loaded, (*taken, rank(option, None)))
            elif not refused:
                for person in persons:
                    there = frozenset({Where(person=person)})
                    if in_use[0] != there:  # they have it already
                        given = further(
                            there_by_then, partial(_put, to=Where(person=person)), person
                        )
                        keep(there, in_use[1], given, (*taken, rank(option, person)))
    return {
        (places, arrivals, bought): taken
        for places, there in kept.items()
        for (arrivals, bought), taken in there.items()
    }


def _first_of(reached: _Reached) -> list[tuple[_Ranked, tuple[tuple[str, str], ...]]]:
    """What a search has reached, as the choices that can still be the one shown.

    Each is the hand-overs and carries of one OBJECT, with the arrivals they count on. Where
    the OBJECT ends up no longer matters. So a choice is left out where another counts on
    no arrival that it does not count on, takes no more places of OFFERs together, and the
    rules put the other no later: start times that keep the first keep the other, and so
    does a way to pay. They come in the order of the rules, the first choice first.
    """
    ranked = sorted(
        ((len(taken), taken, arrivals, bought) for (_, arrivals, bought), taken in reached.items()),
        key=lambda each: each[:3],
    )
    found: list[tuple[_Ranked, tuple[tuple[str, str], ...]]] = []
    counted: list[tuple[tuple[tuple[str, str], ...], _Together[str]]] = []
    for _, taken, arrivals, bought in ranked:
        together = _all_together(bought)
        if not any(
            set(arrivals).issuperset(others) and _no_more(theirs, together)
            for others, theirs in counted
        ):
            counted.append((arrivals, together))
            if (taken, arrivals) not in found:
                found.append((taken, arrivals))
    return found


def _as_planned(
    file: File, world: World, steps: Sequence[Step]
) -> list[tuple[str, list[_Visit], _Run]]:
    """How each OBJECT goes through the OPTIONs among these steps, as the plan says.

    One result for each OBJECT that the fourteenth and the fifteenth CONSTRAINT ask about in
    this world: the OBJECT, the OPTIONs in the order given, and the way the OBJECT goes with
    the hand-overs and the carries of the plan. An OPTION is over for another where it ends
    no later than the other starts. Where the world leaves something to pick, that is the
    first way that breaks the least.

    Where several ways break as little and take places of OFFERs in different OPTIONs, the
    ways of all the OBJECTs are picked together: the first ways, in the FILE's order of
    OBJECTs, whose places can all be had and paid for with those of the PERSONs. Where no
    ways can, each OBJECT goes its first way.

    The ways are picked one OBJECT at a time. Places that cannot be had or paid for cannot
    be either with more places taken besides. So a way of one OBJECT is given up as soon
    as its places do not fit with those of the OBJECTs before it, and with it every pick
    that starts the same way. Eight bags that can each start in four places have 65,536
    picks, and 32 ways to try where no bag can pay. The places of an OBJECT with one way
    only are counted from the start: no pick does without them. So is each place that
    every way of an OBJECT takes, by itself, until a way is picked for that OBJECT.
    """
    found = list(_each_way(file, world, steps))
    first = [(thing, visits, runs[0]) for thing, visits, runs in found]
    if all(len(runs) == 1 for _, _, runs in found):
        return first
    taking_part = {step.option: step.persons for step in steps if step.option is not None}
    _, moved = _where_a_transfer_brings_it(file, world, tuple(steps))
    settled = [(thing, visits, runs[0]) for thing, visits, runs in found if len(runs) == 1]
    # The OBJECTs with several ways, each with the places that every one of its ways takes.
    several = [each for each in found if len(each[2]) > 1]
    at_least = [(thing, visits, _in_every_way(runs)) for thing, visits, runs in several]
    taking, together = _taking(file, [*settled, *at_least])
    if _rights(file, world, taking_part, [*taking, *moved], together):
        return first  # these places cannot be had or paid for, whatever the other OBJECTs do
    # The ways taken so far, and the ways still to try.
    chosen: list[tuple[str, list[_Visit], _Run]] = []
    to_try = [iter(several[0][2])]
    while to_try:
        thing, visits, _ = several[len(to_try) - 1]
        del chosen[len(to_try) - 1 :]
        run = next(to_try[-1], None)
        if run is None:
            to_try.pop()
            continue
        chosen.append((thing, visits, run))
        # A way that takes no place fits where the ways before it fit.
        taking, together = _taking(file, [*settled, *chosen, *at_least[len(chosen) :]])
        if run[3] and _rights(file, world, taking_part, [*taking, *moved], together):
            continue
        if len(chosen) < len(several):
            to_try.append(iter(several[len(chosen)][2]))
            continue
        picked = {thing: run for thing, _, run in chosen}
        return [(thing, visits, picked.get(thing, runs[0])) for thing, visits, runs in found]
    return first


def _in_every_way(runs: Sequence[_Run]) -> _Run:
    """The least that one OBJECT takes, whichever of these ways it goes.

    It is no way of its own: it holds each place of an OFFER that every one of the ways
    takes, each by itself. Whatever the OBJECT's way turns out to be, it takes those
    places, so places that cannot be had or paid for with these cannot be with any of the
    ways.
    """
    misses, trail, seen, bought, _ = runs[0]
    taken = [{position for position, _, _ in run[3]} for run in runs[1:]]
    shared = tuple(place for place in bought if all(place[0] in each for each in taken))
    alone = frozenset(frozenset({position}) for position, _, _ in shared)
    return misses, trail, seen, shared, alone or frozenset({frozenset[int]()})


def _taking(
    file: File, planned: Iterable[tuple[str, list[_Visit], _Run]]
) -> tuple[list[_Placing], dict[str, _Together[str]]]:
    """Each OBJECT that takes a place of an OFFER, as these ways of the OBJECTs have it.

    Each comes with the PERSONs that a finding about it names: whoever takes the OBJECT
    where it is handed over, everybody who takes part where it is carried, and otherwise
    each PERSON who takes part and has it just before the OPTION starts, or might.

    The second result says, for each OBJECT that takes a place, in which OPTIONs it takes
    places together: ``taken_together`` says what that is.
    """
    out: list[_Placing] = []
    together: dict[str, _Together[str]] = {}
    for thing, visits, (_, _, seen, bought, sets) in planned:
        if bought:
            together[thing] = frozenset(
                frozenset(visits[position].option for position in some) for some in sets
            )
        for position, taker, sure in bought:
            option, persons, _, _ = visits[position]
            if taker is not None and taker != _CARRY:
                who: tuple[str, ...] = (taker,)
            elif taker is None:
                have = [each for each in persons if Where(person=each) in seen[position]]
                who = _in_file_order_of_persons(file, have)
            else:
                who = _in_file_order_of_persons(file, persons)
            out.append((option, thing, who, sure))
    return out, together


def _each_way(
    file: File, world: World, steps: Iterable[Step]
) -> Iterator[tuple[str, list[_Visit], list[_Run]]]:
    """What ``_as_planned`` picks from: for each OBJECT, the ways that ``_least_broken`` gives."""
    options = [step for step in steps if step.option is not None]
    ended: list[tuple[int, str]] = []  # each OPTION so far with a known end
    visits: list[_Visit] = []
    for step in options:
        over = frozenset(option for end, option in ended if end <= step.start)
        visits.append(_Visit(step.option or "", step.persons, step.origin, over))
        if step.end is not None:
            ended.append((step.end, step.option or ""))
    ends_at = {option.id: option.destination for option in file.options}
    for thing in file.objects:
        if thing.id in world.brought:
            continue
        handed = {
            step.option or "": person
            for step in options
            for name, person in step.handed
            if name == thing.id
        }
        carried = {step.option or "" for step in options if thing.id in step.carried}
        begins = _begins(file, world, thing.id)
        runs = _least_broken(world, thing.id, visits, begins, handed, carried, ends_at)
        yield thing.id, visits, runs


def _objects(
    file: File, world: World, order: list[_Placed]
) -> tuple[list[Broken], list[_Placing], dict[str, _Together[str]]]:
    """The fourteenth and the fifteenth CONSTRAINT, with the steps in one order.

    Each OBJECT is at hand where it is required, handed over or carried, and no PERSON has
    it in an OPTION that refuses it. Where it is not at hand for an OPTION that requires
    it, the Broken names everybody who takes part, and so it does where the OBJECT cannot
    be carried. Where a PERSON has it in an OPTION that refuses it, the Broken names each
    PERSON who takes part and has it just before the OPTION starts, or might. Where it
    cannot be handed over, the Broken names the PERSON who was to have it.

    An OBJECT that is not at hand can be on its way: it is in an OPTION that ends at the
    PLACE where this one starts. Then the Broken says how long after the start of this
    OPTION that one ends. Where the OBJECT might be in several such OPTIONs, it says when
    the last of them ends, and when the first does. It has no delay where the OBJECT might
    be somewhere that it does not come from. Whether the OBJECT might be at hand after all
    is said apart from that: it is so where one of the places it might be is at hand. One
    OPTION can ask for an OBJECT twice: it requires it and carries it. Both findings are
    the same then, and one is given.

    The second result holds each OBJECT that takes a place of an OFFER in the plan, as
    ``_taking`` gives them. The sixteenth CONSTRAINT asks whether each has one. The third
    says which of its places each OBJECT takes together.
    """
    steps = {step.option: step for _, step in order if step.option is not None}
    out: list[Broken] = []
    planned = _as_planned(file, world, [step for _, step in order])
    for thing, visits, (broken, _, seen, _, _) in planned:
        for position, constraint, taker in broken:
            option, persons, origin, _ = visits[position]
            late: int | None = None
            sooner: int | None = None
            if taker is not None and taker != _CARRY:
                who: tuple[str, ...] = (taker,)
            elif constraint is Constraint.REFUSED or (
                constraint is Constraint.COVERED and taker is None
            ):
                have = [each for each in persons if Where(person=each) in seen[position]]
                who = _in_file_order_of_persons(file, have)
            else:
                who = _in_file_order_of_persons(file, persons)
            away = [each for each in seen[position] if not within_reach({each}, persons, origin)]
            carriers = [steps[each.option] for each in away if each.option is not None]
            ends = [carrier.end for carrier in carriers if carrier.destination == origin]
            known = [end for end in ends if end is not None]
            unmet = constraint is Constraint.AT_HAND and bool(away)
            if unmet and len(known) == len(away):
                late = max(known) - steps[option].start
                sooner = min(known) - steps[option].start if min(known) < max(known) else None
            might = unmet and len(away) < len(seen[position])
            found = Broken(constraint, option, who, late, object=thing, might=might, sooner=sooner)
            if found not in out:
                out.append(found)
    return out, *_taking(file, planned)


def whereabouts(
    file: File, world: World, itinerary: Itinerary
) -> dict[str, tuple[frozenset[Where], ...]]:
    """Where each OBJECT might be through an ITINERARY, in this world.

    For each OBJECT: when the TRIP starts, and then after each OPTION of the ITINERARY, in the
    order it lists them. An OBJECT that the fourteenth and the fifteenth CONSTRAINT ask
    nothing of in this world is left out. Where the world leaves something to pick, this is
    the first way that breaks the least. An OBJECT that was carried is in the OPTION here
    until the next OPTION that starts no earlier than that one ends: ``just_before`` says
    where that OPTION finds it.
    """
    return {thing: run[1] for thing, _, run in _as_planned(file, world, itinerary)}


def just_before(
    file: File, world: World, itinerary: Itinerary
) -> dict[str, tuple[frozenset[Where], ...]]:
    """Where each OBJECT might be just before each OPTION of an ITINERARY starts, in this world.

    The OPTIONs come in the order the ITINERARY lists them, and the OBJECTs are those of
    ``whereabouts``. An OBJECT that was carried in an OPTION that is over by then lies at the
    PLACE where that OPTION ends.
    """
    return {thing: run[2] for thing, _, run in _as_planned(file, world, itinerary)}


type _Chain = tuple[list[tuple[int, int, int]], dict[int, _Taken], tuple[int, tuple[_Ranked, ...]]]
# The hand-overs and the carries of one OBJECT, in the order they happen: each the position
# of the OPTION in the FILE, and the position of the PERSON who has the OBJECT from then on.
# A carry has -1 for the PERSON.
type _Ranked = tuple[tuple[int, int], ...]
_NOTHING_TO_ORDER: list[_Chain] = [([], {}, (0, ()))]  # no OBJECT turns on the order of the steps
# One order of an OBJECT's OPTIONs with one choice of hand-overs and carries: the order, the
# choice, and the arrivals it counts on, each from an OPTION that carried the OBJECT to the
# OPTION that first uses it afterwards.
type _Choice = tuple[tuple[int, ...], _Ranked, tuple[tuple[int, int], ...]]
type _Ordered = tuple[
    Iterator[_Choice],
    dict[int, set[int]],
    list[tuple[int, int, int]],
    tuple[_Ranked, ...],
]


def _asked_about(
    file: File, world: World, who: tuple[tuple[str, ...], ...], empty: Set[int] = frozenset()
) -> tuple[list[int], list[str]]:
    """The OPTIONs of a plan that happen, and the OBJECTs that one of them asks about.

    An OPTION asks about an OBJECT where it requires it or refuses it, and where it needs a
    right for it that nothing gives: a PERSON who has the OBJECT hands it on first, or
    leaves it where an OPTION keeps it. It asks too where only a place of an OFFER gives
    the right: a plan can get by with fewer places that way. The OPTIONs are by position in
    the FILE. ``who`` names the PERSONs in each, and ``empty`` holds the OPTIONs that
    happen with nobody in them.
    """
    happening = [index for index, persons in enumerate(who) if persons or index in empty]
    checked = world.needs | world.refuses | world.uncovered | world.offered
    asked = [
        thing.id
        for thing in file.objects
        if any((file.options[index].id, thing.id) in checked for index in happening)
    ]
    return happening, asked


def _chains(
    file: File,
    world: World,
    who: tuple[tuple[str, ...], ...],
    orders: tuple[tuple[int, ...], ...],
    only_the_first_of_a_kind: bool = False,
    soonest: Mapping[int, int] | None = None,
    fits: Callable[[list[tuple[int, int, int]]], bool] | None = None,
    empty: Set[int] = frozenset(),
    whether_any: bool = False,
) -> Iterator[_Chain] | None:
    """Each order of the OPTIONs that matter to each OBJECT, with the hand-overs that work in it.

    Where an OBJECT is turns on the order in which the OPTIONs happen, also among OPTIONs of
    different PERSONs that start at one instant. Each PERSON's own order is given. So every
    order that keeps those is a candidate. Only the OPTIONs that check the OBJECT or can
    move it matter to it, as ``_ordered_by`` and ``_can_move`` say: the others change
    nothing, wherever they come. And the OBJECTs do not affect each other. So each OBJECT that some
    OPTION of the plan requires or refuses and some OPTION can move has an order of its own,
    among its own OPTIONs.

    For each such order, the OBJECT is taken through it with every choice of hand-overs and
    carries. A choice counts on arrivals: the first OPTION that uses the OBJECT after a
    carry starts no earlier than the carrying OPTION ends, as ``_one_further`` says. For
    each set of arrivals, the choice that works with the fewest hand-overs and carries is
    kept, and among those the one with the OPTION listed first, then the PERSON listed
    first, going through them in the order they happen. Choices with different arrivals
    are all kept: which of them can be timed is not known here. An order in which the
    OBJECT has no choice that works is left out. Where another transfer brings the OBJECT,
    every order works, with no hand-over and no carry: which OPTIONs the OBJECT is at hand
    for without that transfer still turns on the order, and so does who has it in an
    OPTION that refuses it.

    A result takes one order and one choice for each OBJECT. It holds the gaps that keep
    them: each from one OPTION of an order to the next with no time between their starts,
    and each from an OPTION that carried the OBJECT to the OPTION that first uses it
    afterwards, with the time the first takes. It holds the hand-overs and the carries in
    each OPTION, by its position in the FILE. And it holds how they rank: how many they
    are, and then, for each OBJECT in the FILE's order, its hand-overs and carries by the
    positions of the OPTION and the PERSON in the FILE.

    The results are made one at a time, as they are asked for. The OBJECTs are taken in the
    FILE's order, and the order of each is made to go with those already taken: it keeps
    what the PERSONs do and what the earlier orders say comes before what. So two orders
    that would go round in a circle together are never made. Neither is an order that puts
    an OPTION with a later fixed start before one with an earlier fixed start: no start
    times keep it.

    Every ITINERARY that works lists its OPTIONs in one order, and that order gives each
    OBJECT its own, so it is made, with the hand-overs and the carries of the ITINERARY or
    with ones that the rules put before them for the same arrivals. The start times of the
    ITINERARY keep these gaps: an OPTION that uses the OBJECT finds it at hand, so it
    starts no earlier than the OPTION that carried it ends. So the rule for start times
    finds times too. Where no OPTION of the plan requires or refuses an OBJECT, there is
    nothing to order, and the result is None.

    With ``only_the_first_of_a_kind``, an order is left out where an order made before it
    starts with the same OPTIONs, in another order, and leaves the OBJECT in the same places
    with the same hand-overs, carries and arrivals. Whatever follows the one can follow the
    other, with the same hand-overs. ``_orders_differ_only_in_the_listing`` says when the
    earlier one then gives the ITINERARY that comes first, so that the later one is never
    the one shown.

    ``soonest`` holds the earliest that some OPTIONs can start, whatever the order. An
    OPTION that cannot start until after the fixed start of another never comes before it.

    With ``whether_any``, the caller asks only whether there is a result, and takes none.
    Then orders that end alike are left out too where one OBJECT is asked about, as
    ``_one_object_is_asked_about`` says. That is so only with no ``fits``: the start times
    turn on the order so far, so with them two beginnings that end alike are not alike.

    ``fits`` says whether some start times keep a list of gaps with what the PERSONs do. A
    choice of one OBJECT that counts on an arrival is left out where its own gaps do not
    fit: then they do not fit with the gaps of the other OBJECTs either. Nine bags that
    only the last of four ferries brings in time have one choice each that way, and a
    quarter of a million together without it.
    """
    happening, asked = _asked_about(file, world, who, empty)
    if not asked:
        return None
    alike = only_the_first_of_a_kind
    if whether_any and fits is None:
        alike = alike or _one_object_is_asked_about(asked)
    return _orders_together(file, world, who, orders, happening, asked, alike, soonest or {}, fits)


def _can_have(
    file: File, world: World, orders: tuple[tuple[int, ...], ...], thing: str
) -> dict[int, set[str]]:
    """For each OPTION of a plan, the PERSONs in it who can have an OBJECT just before it.

    The OPTIONs are by position in the FILE. A PERSON can have the OBJECT in an OPTION who
    has it when the TRIP starts, or might, or who takes part before that in an OPTION of
    the plan that hands it over and does not refuse it. An OPTION that needs a right for
    the OBJECT that nothing gives is like one that refuses it here: nobody takes the
    OBJECT in it. ``orders`` says what comes before what for each PERSON. An OPTION that
    only might hand it over counts as one that does.
    Nobody else has the OBJECT just before the OPTION starts: nobody comes to have it by a
    carry.
    """
    options = file.options
    at_first = {each.person for start in _begins(file, world, thing) for each in start}
    holders: dict[int, set[str]] = {}
    for person, order in zip(file.persons, orders, strict=True):
        can = person.id in at_first
        for index in order:
            if can:
                holders.setdefault(index, set()).add(person.id)
            pair = (options[index].id, thing)
            barred = pair in world.refuses or pair in world.uncovered
            if world.does.get(pair) in ("hands_over", "any") and not barred:
                can = True
    return holders


def _can_move(
    file: File,
    world: World,
    orders: tuple[tuple[int, ...], ...],
    happening: Sequence[int],
    thing: str,
) -> set[int]:
    """The OPTIONs of a plan that can move an OBJECT, by position in the FILE.

    An OPTION can move it where it hands it over or carries it, or where it keeps it and a
    PERSON who takes part can have it by then, as ``_can_have`` says: an OPTION keeps
    nothing from anybody else. An OPTION that only might do one of these counts as well.
    An OPTION that refuses the OBJECT can move it only by carrying it: nobody who has it
    takes part, and nobody takes it there. An OPTION that carries it can move it also where
    no PERSON can ever have it: then it lies at the PLACE where the OPTION starts. An
    OPTION with nobody in it can move it only by carrying it too: an OBJECT is handed over
    to a PERSON who takes part. An OPTION that needs a right for the OBJECT that nothing
    gives does not move it: in a plan that works, the OBJECT is never in it.
    """
    options = file.options
    holders = _can_have(file, world, orders, thing)
    attended = {index for order in orders for index in order}
    moving: set[int] = set()
    for index in happening:
        pair = (options[index].id, thing)
        action = world.does.get(pair)
        if pair in world.uncovered:
            continue
        if action in ("carries", "any", "might_take", "might_carry"):
            moving.add(index)
        elif pair in world.refuses or index not in attended:
            continue
        elif action == "hands_over" or (action in ("keeps", "might_keep") and index in holders):
            moving.add(index)
    return moving


def _ordered_by(
    file: File,
    world: World,
    orders: tuple[tuple[int, ...], ...],
    happening: Sequence[int],
    thing: str,
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """The OPTIONs of a plan that check one OBJECT, and those that it puts in an order.

    Both are by position in the FILE. ``orders`` gives, for each PERSON, the OPTIONs they do
    in order. An OPTION checks the OBJECT where it requires it, or where it refuses it and a
    PERSON who takes part can have it by then, as ``_can_have`` says. Nobody else has the
    OBJECT then, so a refusal asks nothing of an OPTION with nobody else in it, wherever
    that OPTION comes. An OPTION that needs a right for the OBJECT that nothing gives
    checks it in the same way: no PERSON who takes part has it. So does one where only a
    place of an OFFER gives the right: the OBJECT takes a place where such a PERSON has it.

    The second are the OPTIONs that check the OBJECT or can move it. An OBJECT that no
    OPTION of the plan can move stays where it starts. So the order of the OPTIONs that
    check it changes nothing, and it puts none in an order.
    """
    options = file.options
    holders = _can_have(file, world, orders, thing)
    checking = tuple(
        index
        for index in happening
        if (options[index].id, thing) in world.needs
        or ((options[index].id, thing) in world.refuses and index in holders)
        or ((options[index].id, thing) in world.uncovered and index in holders)
        or ((options[index].id, thing) in world.offered and index in holders)
    )
    can_move = _can_move(file, world, orders, happening, thing)
    if not can_move:
        return checking, ()
    return checking, tuple(index for index in happening if index in checking or index in can_move)


def _as_chain(
    file: File,
    asked: Sequence[str],
    gaps: list[tuple[int, int, int]],
    ranked: tuple[_Ranked, ...],
) -> _Chain:
    """One result of ``_chains``, from its gaps and the hand-overs and carries of each OBJECT."""
    handed: dict[int, _Taken] = {}
    for each, theirs in zip(asked, ranked, strict=True):
        for index, person in theirs:
            taker = None if person < 0 else file.persons[person].id
            handed[index] = (*handed.get(index, ()), (each, taker))
    return gaps, handed, (sum(map(len, ranked)), ranked)


def _for_arrivals(
    file: File, world: World, arrivals: Iterable[tuple[int, int]]
) -> list[tuple[int, int, int]]:
    """The gaps that keep these arrivals, each from a carrying OPTION to one that uses the OBJECT.

    The second starts no earlier than the first ends: the gap is the time the first takes
    in this world. The OPTIONs are by position in the FILE.
    """
    return [
        (carrier, user, world.terms[file.options[carrier].id].shortest)
        for carrier, user in arrivals
    ]


def _chains_in_order(
    file: File,
    world: World,
    who: tuple[tuple[str, ...], ...],
    orders: tuple[tuple[int, ...], ...],
    in_order: Sequence[int],
    fits: Callable[[list[tuple[int, int, int]]], bool],
    empty: Set[int] = frozenset(),
) -> Iterator[_Chain]:
    """What ``_chains`` gives for one order of all the OPTIONs of a plan.

    ``in_order`` holds the OPTIONs that happen, by position in the FILE. ``orders`` holds
    what each PERSON does, in their own order. Each OBJECT that some OPTION of the plan
    requires or refuses takes the order of its own OPTIONs from ``in_order``, with each
    choice of hand-overs and carries that ``_first_of`` gives for that order. A result
    takes one choice for each OBJECT, and the first has the first choice of each. There is
    none where an OBJECT has no choice that works in that order, and where no OPTION of the
    plan requires or refuses an OBJECT.

    The results are made one at a time, as they are asked for: nine bags with four ferries
    each have a quarter of a million of them, and the first is often enough. A choice that
    counts on an arrival is left out where ``fits`` says that no start times keep its own
    gaps: then none keep them with the gaps of the other OBJECTs besides.

    ``in_order`` need not keep each PERSON's own order. Where it puts two OPTIONs of one
    OBJECT the other way round than a PERSON does them, the result goes round in a circle
    with what the PERSON does, and whoever asks for it leaves it out.
    """
    happening, asked = _asked_about(file, world, who, empty)
    place = {index: number for number, index in enumerate(in_order)}
    if not asked or any(index not in place for index in happening):
        return
    options = file.options
    people = {person.id: number for number, person in enumerate(file.persons)}
    place_of = {option.id: number for number, option in enumerate(options)}
    ends_at = {option.id: option.destination for option in options}

    def by_position(option: str, person: str | None) -> tuple[int, int]:
        return (place_of[option], -1 if person is None else people[person])

    each: list[list[tuple[_Ranked, list[tuple[int, int, int]]]]] = []
    for thing in asked:
        checking, matters = _ordered_by(file, world, orders, happening, thing)
        order = sorted(matters, key=place.__getitem__)
        gaps = [(before, after, 0) for before, after in pairwise(order)]
        if thing in world.brought:
            each.append([((), gaps)])
            continue
        visits = [
            _Visit(options[index].id, who[index], options[index].origin)
            for index in (order if matters else checking)
        ]
        begins = _begins(file, world, thing)
        reached = _first_hand_overs(world, thing, visits, begins, by_position, ends_at)
        choices: list[tuple[_Ranked, list[tuple[int, int, int]]]] = []
        for taken, arrivals in _first_of(reached):
            landed = ((place_of[one], place_of[other]) for one, other in arrivals)
            own = [*gaps, *_for_arrivals(file, world, landed)]
            if not arrivals or fits(own):
                choices.append((taken, own))
        if not choices:
            return
        each.append(choices)
    for choice in product(*each):
        gaps = [gap for _, own in choice for gap in own]
        yield _as_chain(file, asked, gaps, tuple(taken for taken, _ in choice))


def _with_what_follows(later: dict[int, set[int]]) -> dict[int, set[int]]:
    """What comes after what, with everything that follows from it. It is added in place."""
    grew = True
    while grew:
        grew = False
        for after in later.values():
            more = set[int]().union(*(later[index] for index in after)) - after
            if more:
                after |= more
                grew = True
    return later


def _later_for_the_persons(
    orders: tuple[tuple[int, ...], ...], happening: Sequence[int]
) -> dict[int, set[int]]:
    """What comes after each OPTION: a PERSON does it later, or a chain of PERSONs does."""
    later: dict[int, set[int]] = {index: set() for index in happening}
    for order in orders:
        for place, index in enumerate(order):
            later[index].update(order[place + 1 :])
    return _with_what_follows(later)


def _orders_together(
    file: File,
    world: World,
    who: tuple[tuple[str, ...], ...],
    orders: tuple[tuple[int, ...], ...],
    happening: Sequence[int],
    asked: Sequence[str],
    only_the_first_of_a_kind: bool,
    soonest: Mapping[int, int],
    fits: Callable[[list[tuple[int, int, int]]], bool] | None = None,
) -> Iterator[_Chain]:
    """What ``_chains`` gives, for the OPTIONs that happen and the OBJECTs they require or refuse.

    It keeps its own list of the orders taken so far, with no call inside a call, so very
    many OBJECTs need no deep stack.
    """
    options = file.options
    fixed = {index: world.terms[options[index].id].fixed_start for index in happening}
    people = {person.id: number for number, person in enumerate(file.persons)}
    place_of = {option.id: number for number, option in enumerate(options)}
    ends_at = {option.id: option.destination for option in options}
    each = [_ordered_by(file, world, orders, happening, thing) for thing in asked]
    checking = [theirs for theirs, _ in each]
    matters = [theirs for _, theirs in each]
    moved = [bool(theirs) for theirs in matters]

    def by_position(option: str, person: str | None) -> tuple[int, int]:
        return (place_of[option], -1 if person is None else people[person])

    def visit(index: int) -> _Visit:
        return _Visit(options[index].id, who[index], options[index].origin)

    def can_arrive(arrivals: Iterable[tuple[str, str]]) -> bool:
        """Whether fixed starts leave the time for each of these arrivals.

        An arrival is from an OPTION that the OBJECT is in to one that uses it afterwards,
        which starts no earlier than the first ends. Where both start at fixed times, that
        holds or it does not, whatever else is chosen.
        """
        for carrier, user in arrivals:
            leaves, used = fixed[place_of[carrier]], fixed[place_of[user]]
            lasts = world.terms[carrier].shortest
            if leaves is not None and used is not None and used < leaves + lasts:
                return False
        return True

    def choices(done: tuple[int, ...], reached: _Reached) -> Iterator[_Choice]:
        """Each choice that a finished order leaves, with its arrivals by position in the FILE."""
        for taken, arrivals in _first_of(reached):
            yield done, taken, tuple((place_of[one], place_of[other]) for one, other in arrivals)

    unordered: dict[int, list[_Choice]] = {}

    def in_each_order(number: int, later: Mapping[int, Set[int]]) -> Iterator[_Choice]:
        """Each order of one OBJECT's OPTIONs that works, with each choice ``_first_of`` gives.

        ``number`` is the place of the OBJECT among those asked about. An order keeps what
        comes after what and the fixed starts. The OBJECT is taken through the OPTIONs as
        the order is made. So an order is given up at the first OPTION where the OBJECT
        cannot be at hand whatever was handed over or carried, or where a PERSON has it in
        an OPTION that refuses it, and with it every order that starts the same way. A way
        that counts on an arrival that fixed starts leave no time for is given up there
        too. Where
        another transfer brings the OBJECT, every order works, with no hand-over and no
        carry. An OBJECT that nothing moves has no order, and is taken through the OPTIONs
        that check it as the FILE lists them.
        """
        thing = asked[number]
        brought = thing in world.brought
        begins = _to_begin(world, thing, _begins(file, world, thing))
        # The OPTIONs done and where they leave the OBJECT, for each start of an order made.
        made: set[tuple[frozenset[int], frozenset[tuple[_Spot, _Ranked]]]] = set()

        def can_come_first(index: int, left: tuple[int, ...]) -> bool:
            mine = fixed[index] if fixed[index] is not None else soonest.get(index)
            for other in left:
                theirs = fixed[other]
                sooner = mine is not None and theirs is not None and theirs < mine
                if index in later[other] or sooner:
                    return False
            return True

        def go(
            done: tuple[int, ...], left: tuple[int, ...], reached: _Reached
        ) -> Iterator[_Choice]:
            if not left:
                if brought:
                    yield done, (), ()
                else:
                    yield from choices(done, reached)
            for index in left:
                if not can_come_first(index, left):
                    continue
                further = reached
                if not brought:
                    further = _one_further(
                        world, thing, reached, visit(index), by_position, ends_at
                    )
                    further = {
                        spot: taken for spot, taken in further.items() if can_arrive(spot[1])
                    }
                    if not further:
                        continue
                if only_the_first_of_a_kind:
                    kind = (frozenset((*done, index)), frozenset(further.items()))
                    if kind in made:
                        continue
                    made.add(kind)
                yield from go((*done, index), tuple(i for i in left if i != index), further)

        if moved[number]:
            yield from go((), matters[number], begins)
            return
        if number not in unordered:
            unordered[number] = [((), (), ())]
            if not brought:
                visits = [visit(index) for index in checking[number]]
                starts = _begins(file, world, thing)
                found = _first_hand_overs(world, thing, visits, starts, by_position, ends_at)
                unordered[number] = list(choices((), found))
        yield from unordered[number]

    own = _later_for_the_persons(orders, happening)
    # The OBJECTs taken so far: the orders still to try for the next one, what comes after
    # what with the orders taken, their gaps, and their hand-overs and carries.
    taken: list[_Ordered] = [(in_each_order(0, own), own, [], ())]
    while taken:
        ahead, later, gaps, chosen = taken[-1]
        following = next(ahead, None)
        if following is None:
            taken.pop()
            continue
        order, found, arrivals = following
        own = [
            *((before, after, 0) for before, after in pairwise(order)),
            *_for_arrivals(file, world, arrivals),
        ]
        if arrivals and fits is not None and not fits(own):
            continue  # no start times keep this choice, whatever the other OBJECTs do
        longer = [*gaps, *own]
        ranked = (*chosen, found)
        if len(ranked) == len(asked):
            yield _as_chain(file, asked, longer, ranked)
            continue
        further = {index: set(after) for index, after in later.items()}
        for place, index in enumerate(order):
            further[index].update(order[place + 1 :])
        _with_what_follows(further)
        taken.append((in_each_order(len(ranked), further), further, longer, ranked))


# ------------------------------- Which ITINERARY is shown -------------------------------


def needless(file: File, world: World, itinerary: Itinerary) -> list[tuple[int, str | None]]:
    """What could be taken out of an ITINERARY that works, or an empty list where nothing can.

    Each thing taken out is named with the position of its step in the ITINERARY: a PERSON
    out of an OPTION or a WAY, or a whole OPTION, with None for the PERSON. It tries every
    combination of PERSONs in OPTIONs that no LOCK requires. All the times are left as they
    are, and so is the order in which the ITINERARY lists the steps that stay: what is
    left has to work as listed. An OPTION that has nobody in it can be taken out by itself.

    An OPTION whose last PERSON is taken out goes with them, or stays with nobody in it.
    Both are tried where the OPTION can carry an OBJECT, or might: then a later step of the
    plan can count on what it moves. Any other OPTION goes: with nobody in it, it keeps
    nothing, hands nothing over and meets no must, so it changes nothing for the rest.
    """
    locked = {(lock.option, person) for lock in file.locks for person in lock.persons}
    free = [
        (index, person)
        for index, step in enumerate(itinerary)
        for person in step.persons
        if (step.option, person) not in locked
    ]
    still = ("nothing", "hands_over", "keeps", "might_keep")
    moving = {
        option.id
        for option in file.options
        if any(
            world.does.get((option.id, thing.id), "nothing") not in still for thing in file.objects
        )
    }
    # How many plans there are to check: each step with every group of its free PERSONs
    # taken out. Where that leaves an OPTION with nobody, it goes, or stays if it can move
    # an OBJECT.
    plans = 1
    for index, step in enumerate(itinerary):
        loose = sum((index, person) in free for person in step.persons)
        if step.option is None or loose < len(step.persons):
            plans *= 2**loose
        else:
            plans *= 2**loose - 1 + (2 if step.option in moving else 1)
    if plans > _MOST_PLANS_TO_CHECK:
        raise ValueError("this ITINERARY is too large for the reference checker")
    for size in range(len(free) + 1):
        for out in combinations(free, size):
            staying = [
                tuple(person for person in step.persons if (index, person) not in out)
                for index, step in enumerate(itinerary)
            ]
            # The OPTIONs with nobody in them now. Each that can move an OBJECT goes or
            # stays, the most gone first. The others go.
            nobody = [
                index
                for index, step in enumerate(itinerary)
                if step.option is not None and not staying[index]
            ]
            can_stay = [index for index in nobody if itinerary[index].option in moving]
            for count in range(len(can_stay), -1, -1):
                for more in combinations(can_stay, count):
                    gone = [index for index in nobody if index in more or index not in can_stay]
                    if not out and not gone:
                        continue  # nothing is taken out
                    smaller: list[Step] = []
                    for index, step in enumerate(itinerary):
                        if index in gone or (step.option is None and not staying[index]):
                            continue
                        # A PERSON who is taken out has nothing handed over to them there.
                        handed = tuple(each for each in step.handed if each[1] in staying[index])
                        smaller.append(replace(step, persons=staying[index], handed=handed))
                    if not broken_as_listed(file, world, tuple(smaller)):
                        return [*out, *((index, None) for index in gone)]
    return []


def itineraries(file: File, world: World, known: Routes | None = None) -> list[Itinerary]:
    """ITINERARIES that work in this world with PERSONs taking part the fewest times.

    It tries every choice of who takes part in which OPTION and in what order. Where a PERSON's
    next OPTION starts somewhere else, WAYs take them there, listed or not. The start times follow
    the rule of "Which ITINERARY is shown". Where a COMPLETE FACT rules out an unlisted WAY for a
    span of time, taking it before the span and after it are tried too. A choice works when the
    orders it names work: no other order is tried in their place.

    A choice is who takes part, which OPTIONs happen with nobody in them, and the order in
    which each PERSON does their OPTIONs. Only an OPTION that ``could_run_alone`` names is
    tried with nobody in it. Where a choice works with another one, the same choice works
    without it and comes first: no OPTION requires or refuses what it moves. There is one
    ITINERARY for each choice that is left, the one that ``scheduled`` gives. Another
    ITINERARY for the same choice, with other WAYs, other hand-overs or other carries, is
    not returned, though PERSONs take part in it as few times.

    An OPTION with nobody in it adds nothing to the times PERSONs take part. So an
    ITINERARY returned can have one that it does not need, and ``needless`` then names it
    with no PERSON.
    Nothing else can be taken out of an ITINERARY in which PERSONs take part the fewest
    times, and nothing at all out of the first one returned. They come in the order of "Which
    ITINERARY is shown". That rule covers the plans a report shows, which take no unlisted WAY.
    In a world with unlisted WAYs the order and the times are still the same every time, and no
    more is promised.

    ``known`` can hold the routes of this world that are already worked out.
    """
    return _that_work(file, world, known, "all")


def _that_work(
    file: File, world: World, known: Routes | None, which: Literal["any", "first", "all"]
) -> list[Itinerary]:
    """The ITINERARIES of ``itineraries``, or one of them, or the first one that is found.

    With "all", they are the ITINERARIES of ``itineraries``. With "any", the list holds the
    first one that is found. It works, like every one that ``scheduled`` returns. It need not
    be one in which PERSONs take part the fewest times, nor the one a report shows.

    With "first", the list starts with the ITINERARY that ``itineraries`` returns first, and
    the rest of it is not complete. An OPTION can happen with nobody in it. For each choice
    of PERSONs, every set of the OPTIONs that ``could_run_alone`` gives is tried, in the
    order of ``_sets``. For one order of the PERSONs, the search stops at the first set
    that works with the fewest WAYs that this order can have. A later set with this order
    gives a plan with as many WAYs or more, so PERSONs take part in it as many times or
    more. And it has more OPTIONs, or as many with the first one that differs listed
    later in the FILE. So the plan of the earlier set comes first. A plan that takes more
    WAYs than the fewest stops nothing: a later set can bring an OBJECT to a PERSON who
    then travels less.

    An order in which a PERSON has no route is never timed. Where no set works for
    another order, every set is tried for it.
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
        if wanted or _requirements(file, world, happening) or _rights(file, world, happening):
            continue  # no order and no timing changes these: only who takes part counts
        mine = [
            [i for i, persons in enumerate(who) if person.id in persons] for person in file.persons
        ]
        in_turn = [list(_orders(file, world, indexes, known)) for indexes in mine]
        # For an order of the PERSONs: the fewest WAYs it can have, and whether a set of
        # OPTIONs with nobody in them has worked with so few.
        least: dict[tuple[tuple[int, ...], ...], int | None] = {}
        done: set[tuple[tuple[int, ...], ...]] = set()
        for empty in _sets(could_run_alone(file, world, who)):
            tried = False
            for orders in product(*in_turn):
                if orders not in least:
                    least[orders] = _fewest_ways(file, world, orders, known)
                if least[orders] is None or orders in done:
                    continue  # a PERSON has no route, or an earlier set comes first
                tried = True
                found = scheduled(
                    file, world, who, orders, None, known, None, which == "any", None, empty
                )
                if found is None:
                    continue
                if which == "any":
                    return [found]
                ways = sum(len(step.persons) for step in found if step.option is None)
                if which == "first" and ways == least[orders]:
                    done.add(orders)
                taking_part = sum(len(step.persons) for step in found)
                if fewest is None or taking_part < fewest:
                    best, fewest = [], taking_part
                if taking_part == fewest:
                    best.append((_in_file_order(file, found, orders), found))
            if not tried:
                break  # no order is left for this set, so none is left for a later one
    shown: list[Itinerary] = []
    for _, found in sorted(best, key=lambda each: each[0]):
        if found not in shown:
            shown.append(found)
    return shown


def _sets(things: Sequence[int]) -> Iterator[frozenset[int]]:
    """Every set of some things, each made when it is asked for.

    The smallest come first. Of two sets of one size, the one that comes first has the
    earlier thing, of the things that only one of them has.
    """
    for size in range(len(things) + 1):
        for chosen in combinations(things, size):
            yield frozenset(chosen)


def could_run_alone(
    file: File, world: World, who: tuple[tuple[str, ...], ...] | None = None
) -> list[int]:
    """The OPTIONs that could happen with nobody in them to some purpose, by position in the FILE.

    With ``who``, they are OPTIONs that this choice of PERSONs leaves out. Such an OPTION
    has a start it can take. It requires no CAPABILITY: a requirement is about the PERSONs
    in the OPTION. And it can move an OBJECT that some OPTION of the FILE requires or
    refuses: it carries it, or might. An OPTION with nobody in it keeps nothing and hands
    nothing over, and it meets no must. So any other one changes nothing for anybody: a
    plan that works with it works without it, and rules 4 and 5 put the plan without it
    first.

    An OBJECT that an OPTION only needs a right for gives it no purpose. Such an OBJECT is
    in the way only while a PERSON who takes part has it: it is handed over or carried
    there only by a choice of the plan, and it goes along with no choice only where the
    OPTION requires it. An OPTION with nobody in it takes nothing from a PERSON.
    """
    asked = {thing for _, thing in world.needs | world.refuses} - world.brought
    carrying = ("carries", "any", "might_take", "might_carry")
    alone: list[int] = []
    for index, option in enumerate(file.options):
        terms = world.terms[option.id]
        taken = who is not None and bool(who[index])
        if taken or (terms.fixed_start is None and not terms.free_start):
            continue
        if any((option.id, capability.id) in world.requires for capability in file.capabilities):
            continue
        if any(world.does.get((option.id, thing)) in carrying for thing in asked):
            alone.append(index)
    return alone


def scheduled(
    file: File,
    world: World,
    who: tuple[tuple[str, ...], ...],
    orders: tuple[tuple[int, ...], ...],
    by: Mapping[tuple[int, int], Route] | None = None,
    known: Routes | None = None,
    falls: Mapping[tuple[int, int, int], int] | None = None,
    any_will_do: bool = False,
    in_order: Sequence[int] | None = None,
    empty: Set[int] = frozenset(),
) -> Itinerary | None:
    """The ITINERARY for one choice of PERSONs and orders, or None when it breaks a CONSTRAINT.

    Each time a PERSON takes a WAY is a step of its own, and the steps are listed in the order
    they happen. Every ITINERARY returned has passed ``works_as_listed``. Where an OPTION of
    the plan requires or refuses an OBJECT, the ITINERARY has the hand-overs that "Which
    ITINERARY is shown" puts first, and its OPTIONs in the order that goes with them.

    ``who`` names the PERSONs in each OPTION, in the FILE's order of OPTIONs, and ``empty``
    holds the OPTIONs that happen with nobody in them, by position in the FILE. ``orders`` gives,
    for each PERSON in the FILE's order, the OPTIONs they do, by position in the FILE, in the
    order they do them. The start times are those of "Which ITINERARY is shown". So are the
    WAYs the PERSONs take, unless ``by`` names them.

    With ``by``, only one choice of WAYs is tried: for a PERSON, by position in the FILE, and
    the position of an OPTION in their order, the route they take after that OPTION. The
    position is -1 for the route before their first OPTION, and for the one route of a PERSON
    who takes part in no OPTION. Without it,
    ``known`` can hold the routes of this world that are already worked out.

    ``falls`` goes with ``by``. It says when a PERSON starts each unlisted WAY of those routes
    that a COMPLETE FACT rules out for some span: for the PERSON, the position of the OPTION
    and the place of the WAY in the route. Then that WAY is tried only in the opening between
    spans that holds its time, and no other. Within that opening the start times follow the
    usual rule, so they need not be the times given.

    With ``any_will_do``, the ITINERARY is the first one found that works. It answers whether
    anything works for this choice, and it need not be the one that rules 9 to 11 put first.
    ``in_order`` goes with ``any_will_do`` and ``by``. It holds the OPTIONs that happen, by
    position in the FILE, in the order they happen in a plan that is known to work. The
    OPTIONs that matter to each OBJECT are tried in that order first.
    """
    if by is not None:
        first = in_order if any_will_do else None
        timed = _timings(file, world, who, orders, by, falls, any_will_do, first, empty)
        return next(timed, None)
    known = known or Routes(file, world)
    return next(_schedules(file, world, who, orders, known, any_will_do, empty), None)


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

    ``last`` says that the PERSON does nothing after the route. Five kinds of route are left
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
      the same two PLACEs and takes no longer when both run shortest, and no longer when both
      run longest. Those are the two cases a route is checked in. The same route with that
      other WAY has as many WAYs, arrives no later in either case, and comes first by the
      rule for the WAYs listed first. This is right only where each WAY takes as long as this
      world says.
    - With ``thin``, a route in which one listed WAY could stand in for a stretch of two or
      more WAYs. That WAY goes straight between the two ends of the stretch, and takes no
      longer than the whole stretch when all run shortest, and no longer when all run
      longest. The PERSON takes it when they would have set out on the stretch, arrives no
      later in either case, and waits. A listed WAY leaves at any time. The route with that
      WAY has fewer WAYs, so it is tried first, and it works wherever the other does. Where a
      walk joins every two of ten PLACEs, this leaves one route between two of them, and
      not the hundred thousand that pass through the others.

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

    # Each PLACE with the WAYs a route can leave it by, in the FILE's order, and where each
    # one leads. A WAY with no limit to how long it takes can only be the last leg of a
    # PERSON's last route. And for each two PLACEs, how long each listed WAY straight from
    # the one to the other takes, shortest and longest, where it has a limit.
    leaving: dict[str, list[tuple[str, str]]] = {}
    straight: dict[tuple[str, str], list[tuple[int, int]]] = {}
    for way in file.ways:
        ends = [(way.origin, way.destination)]
        ends += [(way.destination, way.origin)] if way.both_ways else []
        shortest, longest = world.takes[way.id]
        for origin, destination in ends:
            if longest is not None or (last and destination == there):
                leaving.setdefault(origin, []).append((way.id, destination))
            if longest is not None:
                straight.setdefault((origin, destination), []).append((shortest, longest))

    def as_quick(origin: str, destination: str, stretch: Route) -> bool:
        """Whether one listed WAY between these PLACEs is never slower than this stretch."""
        if (origin, destination) not in straight:
            return False
        least = most = 0
        for way, _, _ in stretch:
            shortest, longest = (world.unlisted_takes,) * 2 if way is None else world.takes[way]
            if longest is None:
                return False
            least, most = least + shortest, most + longest
        return any(
            shortest <= least and longest <= most
            for shortest, longest in straight[origin, destination]
        )

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

    def onward(passed: tuple[str, ...]) -> Iterator[tuple[str | None, str]]:
        """Each WAY to try next from the last PLACE passed, and the PLACE it leads to."""
        place = passed[-1]
        taken: dict[str, list[tuple[int, int]]] = {}
        for way, ahead in leaving.get(place, ()):
            if ahead in passed or (leads_there is not None and ahead not in leads_there):
                continue
            shortest, longest = world.takes[way]
            if thin and longest is not None:
                quicker = taken.setdefault(ahead, [])
                if any(least <= shortest and most <= longest for least, most in quicker):
                    continue
                quicker.append((shortest, longest))
            yield way, ahead
        for other in places:
            if other not in passed and joined(place, other):
                yield None, other

    found: list[Route] = []
    # The PLACEs passed so far, the WAYs taken, and what is still to try from there. A list, and
    # no call inside a call: a route through very many PLACEs needs no deep stack.
    begun: list[tuple[tuple[str, ...], Route, Iterator[tuple[str | None, str]]]] = [
        ((here,), (), onward((here,)))
    ]
    while begun:
        passed, legs, ahead = begun[-1]
        step = next(ahead, None)
        if step is None:
            begun.pop()
            continue
        way, place = step
        if leads_there is not None and place not in leads_there:
            continue
        longer = (*legs, (way, passed[-1], place))
        if any(stands_in(passed[first], place, longer[first:]) for first in range(len(legs))):
            continue
        if thin and any(
            as_quick(passed[first], place, longer[first:]) for first in range(len(legs))
        ):
            continue
        if place == there:
            found.append(longer)
        else:
            begun.append(((*passed, place), longer, onward((*passed, place))))
    return sorted(found, key=lambda route: (len(route), _legs_in_file_order(file, route)))


class Routes:
    """The routes between the PLACEs of one world, with each pair worked out once."""

    def __init__(self, file: File, world: World, thin: bool = True) -> None:
        """``thin`` leaves out a route with a WAY that an earlier WAY is never slower than.

        That is right where each WAY takes as long as this world says.
        """
        self._file, self._world, self._thin = file, world, thin
        self._found: dict[tuple[str, str, bool], list[Route]] = {}
        self._fitting: dict[tuple[int, int], list[Route]] = {}
        self._at_the_ends: dict[tuple[str, str, int | None, int | None], list[Route]] = {}
        self._lengths: dict[tuple[str, str, bool], list[int | None]] = {}
        self._longest: dict[tuple[str, str, bool], int] = {}

    def between(self, here: str, there: str, last: bool = False) -> list[Route]:
        """Every route from one PLACE to another that is worth trying, shortest first.

        ``last`` says that the PERSON does nothing after the route.
        """
        if (here, there, last) not in self._found:
            self._found[here, there, last] = routes(
                self._file, self._world, here, there, last, self._thin
            )
        return self._found[here, there, last]

    def _within(
        self, here: str, there: str, last: bool, leaves: int | None, there_by: int | None
    ) -> list[Route]:
        """The routes between two PLACEs that can start at one time and be over by another.

        How long each route takes is worked out once for the two PLACEs.
        """
        possible = self.between(here, there, last)
        if leaves is None or there_by is None:
            return possible
        if (here, there, last) not in self._lengths:
            self._lengths[here, there, last] = [_length(self._world, each) for each in possible]
        lengths = self._lengths[here, there, last]
        if (here, there, last) not in self._longest:
            self._longest[here, there, last] = max((each for each in lengths if each), default=0)
        if _in_time(leaves, there_by, self._longest[here, there, last]):
            return possible  # even the longest of them fits, so the list is as it was
        return [
            route
            for route, takes in zip(possible, lengths, strict=True)
            if _in_time(leaves, there_by, takes)
        ]

    def after(self, first: int, then: int) -> list[Route]:
        """The routes from one OPTION to the next one a PERSON does, by position in the FILE.

        They are the routes between the two PLACEs that fit between the two OPTIONs, worked
        out once for the pair. The PERSON leaves when the first OPTION ends at the earliest,
        and has to be there the access cutoff of the second one before it starts: see
        ``_in_time``.
        """
        if (first, then) not in self._fitting:
            file, world = self._file, self._world
            before, after = file.options[first], file.options[then]
            leaves = _over(world.terms[before.id])
            there_by = _open_until(world.terms[after.id])
            self._fitting[first, then] = self._within(
                before.destination, after.origin, False, leaves, there_by
            )
        return self._fitting[first, then]

    def at_an_end(self, here: str, there: str, first: int | None, then: int | None) -> list[Route]:
        """The routes at an end of a PERSON's path that the times of the TRIP allow.

        ``then`` is the OPTION the PERSON does first, where the route leads to one, and
        ``first`` the OPTION they do last, where the route comes after one. Both are positions
        in the FILE, and both are None for a PERSON who takes part in no OPTION. A route that
        starts a path cannot start before the TRIP starts, and a route that ends one has to be
        over when the TRIP ends: see ``_in_time``. Each is worked out once.
        """
        key = (here, there, first, then)
        if key not in self._at_the_ends:
            file, world = self._file, self._world
            opens, closes = file.trip_start(), file.trip_end()
            leaves = None if opens is None else opens.at
            there_by = None if closes is None else closes.at
            if first is not None:
                leaves = _over(world.terms[file.options[first].id])
            if then is not None:
                there_by = _open_until(world.terms[file.options[then].id])
            self._at_the_ends[key] = self._within(here, there, then is None, leaves, there_by)
        return self._at_the_ends[key]


class NoTimeBetween:
    """Which two OPTIONs no PERSON takes part in both, in one world, for lack of time.

    Both OPTIONs start at fixed times. A PERSON does their OPTIONs one after another, so one of
    the two comes first, and the other has to be able to follow it. ``apart`` says that
    neither can follow the other. Then no ITINERARY that works in this world has a PERSON in
    both, whatever else is in it.

    One OPTION cannot follow another:

    - where the first has no limit to how long it takes: nobody does anything after it;
    - where it starts before the first is over at the earliest;
    - where it starts at another PLACE than the first ends at, and the PERSON cannot be there
      its access cutoff before it starts. They travel between the two, so the cutoff counts.
      Whatever they do on the way, each thing starts where the one before it ended. So the
      things that move them lead from the one PLACE to the other: listed WAYs, unlisted WAYs
      and OPTIONs that move. Together these take at least as long as the quickest chain of
      them does, with each at its shortest in this world and no waiting. A WAY or an OPTION
      with no limit to how long it takes is in no chain: nothing follows it. Where even the
      quickest chain is too slow, or there is none, the second OPTION cannot follow.

    An unlisted WAY counts wherever this world has one and it could start at some time
    between the two OPTIONs. One COMPLETE FACT whose span holds that whole time rules it out.
    Where an unlisted WAY might join any two PLACEs, this sees only a FACT about all travel
    between all PLACEs. With no such FACT it says nothing about the pair. An access cutoff
    with no limit is not looked at either.

    So ``apart`` says yes only with a proof. Where it says no, the two OPTIONs can still be
    apart: FACTs about travel from one PLACE can close every way out of it, and the timing
    finds that.
    """

    def __init__(self, file: File, world: World) -> None:
        self._file, self._world = file, world
        self._complete = [fact for fact in file.facts if isinstance(fact, Complete)]
        # From each PLACE: where a listed WAY or an OPTION that moves leads, and how long it
        # takes at the least.
        self._leaving: dict[str, list[tuple[str, int]]] = {}
        for way in file.ways:
            shortest, longest = world.takes[way.id]
            if longest is None:
                continue
            self._leaving.setdefault(way.origin, []).append((way.destination, shortest))
            if way.both_ways:
                self._leaving.setdefault(way.destination, []).append((way.origin, shortest))
        for option in file.options:
            terms = world.terms[option.id]
            if option.origin != option.destination and terms.longest is not None:
                self._leaving.setdefault(option.origin, []).append(
                    (option.destination, terms.shortest)
                )
        self._unlisted: dict[tuple[int, ...], tuple[tuple[str, str], ...] | None] = {}
        self._soonest: dict[tuple[str, tuple[int, ...]], dict[str, int]] = {}
        self._apart: dict[tuple[int, int], bool] = {}

    def apart(self, one: int, other: int) -> bool:
        """Whether no PERSON takes part in both of these OPTIONs, by position in the FILE."""
        pair = (min(one, other), max(one, other))
        if pair not in self._apart:
            self._apart[pair] = (
                one != other and self._cannot_follow(one, other) and self._cannot_follow(other, one)
            )
        return self._apart[pair]

    def _cannot_follow(self, first: int, then: int) -> bool:
        """Whether no PERSON does the second OPTION after the first. Both start at fixed times."""
        options, terms = self._file.options, self._world.terms
        before, after = terms[options[first].id], terms[options[then].id]
        if before.fixed_start is None or after.fixed_start is None:
            return False
        over = before.fixed_start + before.shortest
        if before.longest is None or over > after.fixed_start:
            return True
        here, there = options[first].destination, options[then].origin
        if here == there or after.margin is None:
            return False
        there_by = after.fixed_start - after.margin
        if over > there_by:
            return True
        ruling = tuple(
            number
            for number, fact in enumerate(self._complete)
            if fact.earliest <= over and there_by <= fact.latest
        )
        if self._joined(ruling) is None:
            return False
        takes = self._reached(here, ruling).get(there)
        return takes is None or over + takes > there_by

    def _joined(self, ruling: tuple[int, ...]) -> tuple[tuple[str, str], ...] | None:
        """The PLACEs an unlisted WAY can join while these COMPLETE FACTs rule, or None for any.

        ``ruling`` holds the FACTs whose span holds the whole time between two OPTIONs.
        """
        if ruling not in self._unlisted:
            facts = [self._complete[number] for number in ruling]
            pairs = self._world.unlisted
            if pairs is None:
                everywhere = any(fact.origin is None and fact.destination is None for fact in facts)
                self._unlisted[ruling] = () if everywhere else None
            else:
                self._unlisted[ruling] = tuple(
                    sorted(pair for pair in pairs if not any(fact.covers(*pair) for fact in facts))
                )
        return self._unlisted[ruling]

    def _reached(self, here: str, ruling: tuple[int, ...]) -> dict[str, int]:
        """The least time from one PLACE to each PLACE that anything leads to from it."""
        if (here, ruling) not in self._soonest:
            leaving = self._leaving
            unlisted = self._joined(ruling)
            if unlisted:
                leaving = {origin: list(exits) for origin, exits in leaving.items()}
                for origin, destination in unlisted:
                    leaving.setdefault(origin, []).append((destination, self._world.unlisted_takes))
            least: dict[str, int] = {}
            ahead = [(0, here)]
            while ahead:
                takes, place = heappop(ahead)
                if place in least:
                    continue
                least[place] = takes
                for onward, more in leaving.get(place, ()):
                    if onward not in least:
                        heappush(ahead, (takes + more, onward))
            self._soonest[here, ruling] = least
        return self._soonest[here, ruling]


def _legs_in_file_order(file: File, route: Route) -> list[tuple[int, int, int]]:
    """The WAYs listed first come first, then the PLACEs listed first. Unlisted WAYs come last."""
    ways = [way.id for way in file.ways]
    places = [place.id for place in file.places]
    return [
        (len(ways) if way is None else ways.index(way), places.index(origin), places.index(to))
        for way, origin, to in route
    ]


def _travel(
    file: File, world: World, orders: tuple[tuple[int, ...], ...], known: Routes
) -> list[tuple[int, int, list[Route]]] | None:
    """Where the PERSONs have to travel with these orders, and the routes that can take them.

    Each is a PERSON, by position in the FILE, the position in their order of the OPTION
    that they travel after, and the routes. The position is -1 before their first OPTION.
    None where a PERSON has to travel and no route takes them.
    """
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
                if 0 <= spot < len(order) - 1:
                    possible = known.after(order[spot], order[spot + 1])
                else:
                    before = order[spot] if spot >= 0 else None
                    after = None if last else order[spot + 1]
                    possible = known.at_an_end(here, there, before, after)
                if not possible:
                    return None
                needed.append((number, spot, possible))
    return needed


def _fewest_ways(
    file: File, world: World, orders: tuple[tuple[int, ...], ...], known: Routes
) -> int | None:
    """The fewest WAYs that the PERSONs take with these orders, each PERSON's WAYs counted.

    It is what the shortest route for each stretch adds up to. ``_schedules`` takes its
    routes from the same lists, so no ITINERARY with these orders has fewer. None where a
    PERSON has no route.
    """
    needed = _travel(file, world, orders, known)
    if needed is None:
        return None
    return sum(min(len(route) for route in routes) for _, _, routes in needed)


def _schedules(
    file: File,
    world: World,
    who: tuple[tuple[str, ...], ...],
    orders: tuple[tuple[int, ...], ...],
    known: Routes,
    any_will_do: bool = False,
    empty: Set[int] = frozenset(),
) -> Iterator[Itinerary]:
    """The ITINERARIES for one choice of PERSONs and orders.

    ``empty`` holds the OPTIONs that happen with nobody in them, by position in the FILE.

    Where a PERSON's next OPTION starts somewhere else, WAYs must take them there. The routes
    are tried with the fewest WAYs first, then in the order of "Which ITINERARY is shown": PERSON
    by PERSON, the WAYs listed first. Then each way the timing can fall is tried.

    A route is left out where two times are known, the earliest it can start and the latest
    it can be over, and it takes longer than the time between them: see ``_in_time``. Between
    two OPTIONs that both start at fixed times, those are the end of the first and the access
    cutoff of the second. At an end of a path, one of them is the start or the end of the
    TRIP. No ITINERARY that works in this world takes such a route in that order, whatever
    the other PERSONs do. So the routes that are left come in the same order, and the first
    ITINERARY that works is the same one. Every other route is left to the timing.
    """
    # A first check, before any WAY or time: does some order of the OPTIONs let each OBJECT be
    # where it has to be? Only whether there is one matters here, and not which.
    found = _chains(file, world, who, orders, empty=empty, whether_any=True)
    if found is not None and next(iter(found), None) is None:
        return  # an OBJECT is not at hand where it has to be, whatever the WAYs and the times
    needed = _travel(file, world, orders, known)
    if needed is None:
        return

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
        yield from _timings(file, world, who, orders, hops, None, any_will_do, empty=empty)


def _one_object_is_asked_about(asked: Sequence[str]) -> bool:
    """Whether a search for any order at all can leave out orders that end alike.

    ``asked`` holds the OBJECTs that the OPTIONs of a plan ask about. The first check of
    ``_schedules`` asks ``_chains`` only whether it has a result.

    ``_chains`` makes each order of an OBJECT's OPTIONs one OPTION at a time. Take two
    beginnings with the same OPTIONs, in different orders, that leave the OBJECT in the same
    places with the same hand-overs, carries and arrivals. The same OPTIONs are left for
    both. Which of them can come next turns on what is left, on the fixed starts and on what
    the PERSONs do, and not on the order so far. Where the OBJECT can go from there turns on
    where it is. So whatever finishes the one finishes the other, and where the first
    beginning leads to no order that works, neither does the second. No start time has a
    say in that: the check gives ``_chains`` nothing to time an order with.

    That holds while no other OBJECT has an order to go with. The order of one OBJECT is
    made to go with the orders of the OBJECTs before it, so with two OBJECTs the second
    beginning can be the only one that suits the other OBJECT. So the check leaves out the
    second beginning only where one OBJECT is asked about. Eight vans that all bring the
    bag too late have 40,320 orders, and 256 sets of vans that have left.
    """
    return len(asked) == 1


def _over(terms: Terms) -> int | None:
    """The earliest an OPTION that starts at a fixed time is over, where it has a known end."""
    if terms.fixed_start is None or terms.longest is None:
        return None
    return terms.fixed_start + terms.shortest


def _open_until(terms: Terms) -> int | None:
    """The latest a PERSON who travels to an OPTION that starts at a fixed time can arrive."""
    if terms.fixed_start is None or terms.margin is None:
        return None
    return terms.fixed_start - terms.margin


def _length(world: World, route: Route) -> int | None:
    """How long a route takes in this world at the least, or None where a WAY has no limit."""
    takes = 0
    for way, _, _ in route:
        if way is None:
            takes += world.unlisted_takes
            continue
        shortest, longest = world.takes[way]
        if longest is None:
            return None
        takes += shortest
    return takes


def _in_time(leaves: int | None, there_by: int | None, takes: int | None) -> bool:
    """Whether a route that starts no earlier than one time can be over by another.

    ``takes`` is how long the route takes at the least. Waiting, and a span that rules an
    unlisted WAY out, only make a PERSON arrive later. True where a time is not known, or the
    route has a WAY with no limit to how long it takes: then the timing decides.
    """
    if leaves is None or there_by is None or takes is None:
        return True
    return leaves + takes <= there_by


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
    falls: Mapping[tuple[int, int, int], int] | None = None,
    any_will_do: bool = False,
    in_order: Sequence[int] | None = None,
    empty: Set[int] = frozenset(),
) -> Iterator[Itinerary]:
    """The ITINERARIES for one choice of PERSONs, orders and routes, one for each timing.

    ``empty`` holds the OPTIONs that happen with nobody in them, by position in the FILE.
    Such an OPTION is on no PERSON's path. It has its start, its limits and its step like
    any other, and the order of an OBJECT can tie it to the others.

    The start times are those of "Which ITINERARY is shown". A COMPLETE FACT rules out an
    unlisted WAY only within its span. So each unlisted WAY between the PLACEs of such a FACT
    is tried as it falls, then before the first span that rules it out, then after each one.

    ``falls`` says when each such WAY is started in a plan that is known to work. Then the
    WAY is tried only in the opening that holds its time. The opening leaves fixed starts,
    limits and gaps, and the plan's own times meet them all. So the rule for start times has
    an answer within that opening.

    Where an OPTION of the plan requires or refuses an OBJECT, ``_chains`` gives the orders
    of the OPTIONs that matter to each OBJECT, with their hand-overs. Each of those orders
    gives one ITINERARY:
    it is timed as the rule times it, in the first way the timing can fall that works. Of
    the ITINERARIES of the orders, only the one that "Which ITINERARY is shown" puts first
    is given: the fewest hand-overs, then the hand-overs listed first, then the steps that
    come first with their times. So they are all found before it is given, and only the
    first so far is kept. That holds too where another transfer brings the OBJECT: which
    OPTIONs it has to be brought to is read off the ITINERARY that comes first. Where no
    OPTION requires or refuses an OBJECT, or with ``any_will_do``, each ITINERARY is given
    as soon as it is found, for each way the timing can fall.

    Not every order has to be timed for that. The orders are many where several OPTIONs
    that matter to an OBJECT start at one instant, or at any time. Two short cuts leave the
    ITINERARY that comes first as it is. An order that another order always beats is not
    made: see ``_orders_differ_only_in_the_listing``. And the search stops at an ITINERARY
    that none can come before: see ``_nothing_comes_before``. The order that the earliest
    possible starts give is tried first, since it is the one that can stop the search.

    ``in_order`` holds the OPTIONs that happen in the order of a plan that is known to work.
    Then the OPTIONs that matter to each OBJECT are tried in that order before any other.
    The plan's own times keep that order, so the rule for start times has an answer for it,
    and no other order has to be looked for. Every other order is still tried after it.
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

    def step(node: int, start: int, handed: _Taken = ()) -> Step:
        """The step that an OPTION or a WAY of this plan is, where it starts at this time."""
        lasts = takes(node)
        end = None if lasts is None else start + lasts
        if node < listed:
            option = file.options[node]
            given = tuple((thing, taker) for thing, taker in handed if taker is not None)
            loaded = tuple(thing for thing, taker in handed if taker is None)
            return Step(
                option.id,
                option.origin,
                option.destination,
                who[node],
                start,
                end,
                handed=given,
                carried=loaded,
            )
        person, (way, start_place, end_place) = legs[node - listed]
        return Step(None, start_place, end_place, (person,), start, end, way)

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
    happens = [bool(persons) or index in empty for index, persons in enumerate(who)]
    fixed: dict[int, int] = {}
    for index, option in enumerate(file.options):
        at = world.terms[option.id].fixed_start
        if happens[index] and at is not None:
            fixed[index] = at

    # The limits on each start that fix no start themselves. No step starts before the TRIP
    # starts, and a step with a known length starts early enough to be over when the TRIP ends.
    # An OPTION that does not happen is no step, and has no limit.
    trip_starts, trip_ends = file.trip_start(), file.trip_end()
    not_before: dict[int, int] = {}
    no_later: dict[int, int] = {}
    for node in range(count):
        if node < listed and not happens[node]:
            continue
        lasts = takes(node)
        if trip_starts is not None:
            not_before[node] = trip_starts.at
        if trip_ends is not None and lasts is not None:
            no_later[node] = trip_ends.at - lasts

    ruled_out = [
        (node, spans)
        for node in range(listed, count)
        if unlisted(node)
        for spans in [spans_closed(file, origin(node), destination(node))]
        if spans
    ]
    # Each such WAY as it falls, then in each opening: before the first span, after each one.
    # An opening is one more limit on when the WAY starts. It fixes no start either. An
    # opening that is over before the WAY can start, or that begins after it has to have
    # started, holds no time for it: the times of the TRIP rule it out, whatever else is
    # chosen. So it is left out.
    openings: list[list[int | None]] = []
    for node, spans in ruled_out:
        fits: list[int | None] = [None]
        for opening in range(len(spans) + 1):
            too_early = opening < len(spans) and spans[opening][0] - 1 < not_before.get(node, -inf)
            too_late = opening > 0 and spans[opening - 1][1] + 1 > no_later.get(node, inf)
            if not too_early and not too_late:
                fits.append(opening)
        openings.append(fits)
    if falls is not None:
        # The PERSON, the position and the place of each WAY, in the order of ``legs``. The
        # opening that holds the time of a WAY comes after each span that ends before it.
        taken = [
            (number, position, place)
            for number, order in enumerate(orders)
            for position in range(-1, len(order))
            for place in range(len(hops.get((number, position), ())))
        ]
        openings = [
            [sum(latest < falls[taken[node - listed]] for _, latest in spans)]
            for node, spans in ruled_out
        ]
    nodes = [*(index for index in range(listed) if happens[index]), *range(listed, count)]
    # The steps as the rule times them with no order of an OBJECT, where the timing can fall
    # in one way only. Each is ranked as the listing of an ITINERARY ranks it.
    as_timed: dict[int, _StepOrder] | None = None
    if not any_will_do and not ruled_out and _asked_about(file, world, who, empty)[1]:
        plain = _times(count, gaps, fixed, not_before, no_later)
        if plain is not None:
            as_timed = {node: _step_in_file_order(file, step(node, plain[node])) for node in nodes}
    alike = _orders_differ_only_in_the_listing(
        file, world, who, orders, fixed, gaps, as_timed, empty
    )
    soonest = _earliest_starts(count, gaps, fixed, not_before)

    def can_be_timed(more: list[tuple[int, int, int]]) -> bool:
        """Whether some start times keep these gaps with what the PERSONs do."""
        return _times(count, [*gaps, *more], fixed, not_before, no_later) is not None

    found = _chains(file, world, who, orders, alike, soonest, can_be_timed, empty=empty)
    chains: Iterable[_Chain] = _NOTHING_TO_ORDER if found is None else found
    in_turn = any_will_do or found is None
    bound: list[_StepOrder] | None = None
    as_they_fall: list[int] | None = None
    if not in_turn and all(node in soonest for node in nodes):
        lowest = {node: _step_in_file_order(file, step(node, soonest[node])) for node in nodes}
        bound = sorted(lowest.values())
        as_they_fall = sorted((node for node in nodes if node < listed), key=lowest.__getitem__)
    if found is not None:
        known = [in_order, as_they_fall]
        first_tries = _to_try_first(file, world, who, orders, known, can_be_timed, empty)
        chains = chain(first_tries, chains)
    least: list[tuple[int, tuple[_Ranked, ...]] | None] = []

    def fewest() -> tuple[int, tuple[_Ranked, ...]] | None:
        """Hand-overs that no ITINERARY of this choice has hand-overs before, where known."""
        if not least:
            least.append(_fewest_hand_overs(file, world, who, orders, soonest, empty))
        return least[0]

    first: tuple[_Comes, Itinerary] | None = None
    for more, handed, rank in chains:
        # Each order of the OPTIONs that matter to an OBJECT is more gaps. An order that goes
        # round in a circle with what the PERSONs do is no order, also where every step in
        # the circle starts at one instant.
        all_gaps = [*gaps, *more] if more else gaps
        if more and _goes_round(count, all_gaps):
            continue
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
            starts = _times(count, all_gaps, fixed, earliest, latest)
            if starts is None:
                continue
            steps = {node: step(node, starts[node], handed.get(node, ())) for node in nodes}
            itinerary = _in_the_order_they_happen(file, steps, all_gaps)
            if not works_as_listed(file, world, itinerary):
                continue
            if in_turn:
                yield itinerary
                continue
            comes = (rank, [_step_in_file_order(file, each) for each in itinerary])
            if _nothing_comes_before(comes, bound, fewest):
                yield itinerary
                return
            if first is None or comes < first[0]:
                first = (comes, itinerary)
            break  # this order is timed: the first way the timing can fall that works
    if first is not None:
        yield first[1]


def _earliest_starts(
    count: int,
    gaps: list[tuple[int, int, int]],
    fixed: Mapping[int, int],
    not_before: Mapping[int, int],
) -> dict[int, int]:
    """The earliest each start can be, whichever order the OPTIONs of an OBJECT take.

    A fixed start is where it is. Another start is no earlier than its own limit, and no
    earlier than a start before it with the gap between them. An order of the OPTIONs that
    matter to an OBJECT only adds gaps, and so does the opening that a WAY leaves in. So no
    timing of this plan has a start before the one given here. A start with nothing to
    count from is left out.
    """
    soonest = {**not_before, **fixed}
    for _ in range(count + 1):
        moved = False
        for before, after, gap in gaps:
            if before not in soonest or after in fixed:
                continue
            if after not in soonest or soonest[before] + gap > soonest[after]:
                soonest[after] = soonest[before] + gap
                moved = True
        if not moved:
            break
    return soonest


def _nothing_comes_before(
    comes: _Comes,
    bound: list[_StepOrder] | None,
    fewest: Callable[[], tuple[int, tuple[_Ranked, ...]] | None],
) -> bool:
    """Whether an ITINERARY comes first among those of one choice, whatever the others are.

    ``comes`` is how it ranks: its hand-overs, and its steps as it lists them. ``bound``
    holds every step of the plan at the earliest it can start, in the order of the listing,
    or None where some step has no earliest start. ``fewest`` gives the hand-overs that
    come first among those of every order, or None where that is not known. It is asked
    only where the answer turns on it.

    It comes first where its hand-overs are those and it lists its steps exactly as
    ``bound`` has them. No ITINERARY has hand-overs that come before those, and none has
    fewer hand-overs than none at all. And none lists its steps before ``bound``: each of
    its steps starts no earlier than the same step there, so its steps put in the order of
    the listing come no earlier, one by one. However it lists them, that comes no earlier
    than listing them in that order. An ITINERARY that ranks the same is the same ITINERARY.
    """
    if bound is None or comes[1] != bound:
        return False
    return comes[0][0] == 0 or comes[0] == fewest()


def _orders_differ_only_in_the_listing(
    file: File,
    world: World,
    who: tuple[tuple[str, ...], ...],
    orders: tuple[tuple[int, ...], ...],
    fixed: Mapping[int, int],
    gaps: list[tuple[int, int, int]],
    as_timed: Mapping[int, _StepOrder] | None,
    empty: Set[int] = frozenset(),
) -> bool:
    """Whether an order of an OBJECT's OPTIONs changes nothing but how the steps are listed.

    Then ``_chains`` can leave out an order that starts with the same OPTIONs as an order
    made before it, and leaves the OBJECT in the same places with the same hand-overs.

    That is so where four things hold. One OBJECT alone leaves a choice of order, as
    ``_the_one_order`` says. Each of the OPTIONs it orders starts at a fixed time. The
    timing can fall in one way only: ``as_timed`` holds how each step ranks in
    the listing as the rule times it, and is None otherwise. And each step that has to come
    before another by what the PERSONs do also ranks before it there.

    The order adds gaps between fixed starts only, and those move no start. So every order
    gives the same start times, and the ITINERARIES differ only in their hand-overs and in
    how they list the steps that start at one instant.

    Take two orders that start with the same OPTIONs and leave the OBJECT in the same places
    with the same hand-overs, and let the same OPTIONs follow both in the same order. They
    end with the same hand-overs. An ITINERARY lists, of the steps that are free to come
    next, the one that ranks first. Go through the two listings to the first step where
    they differ. Up to there the two orders have used the same OPTIONs, in the same order,
    and the next OPTION of the order made first ranks before the next OPTION of the other.
    It is free to come next: whatever has to come before it ranks before it, and so was
    listed already or is free itself and ranks before it. So the listing of the order made
    first has that OPTION there, or a step that ranks before it and that the other listing
    could have had too. Either way it lists the earlier step. The order made first wins.
    """
    if as_timed is None:
        return False
    ordered = _the_one_order(file, world, who, orders, empty)
    if ordered is None or any(index not in fixed for index in ordered):
        return False
    return all(as_timed[before] < as_timed[after] for before, after, _ in gaps)


def _fewest_hand_overs(
    file: File,
    world: World,
    who: tuple[tuple[str, ...], ...],
    orders: tuple[tuple[int, ...], ...],
    soonest: Mapping[int, int],
    empty: Set[int] = frozenset(),
) -> tuple[int, tuple[_Ranked, ...]] | None:
    """Hand-overs that no ITINERARY of this choice has hand-overs before, as ``_chains`` ranks them.

    Each OBJECT is taken by itself: of all the orders of its own OPTIONs, the hand-overs
    that the rules put first. The other OBJECTs are not looked at, so an order counts here
    that the orders of the others rule out, and one that cannot be timed. That only makes
    the result come earlier than it has to. One order of each kind is enough: two orders
    that start with the same OPTIONs and leave the OBJECT in the same places with the same
    hand-overs end with the same hand-overs, whatever follows.

    Put together, these are a lower limit for every ITINERARY. Its hand-overs of each
    OBJECT come no earlier than these. So it has at least as many in all, and where it has
    as many, it has as many of each OBJECT, and they come no earlier OBJECT by OBJECT.

    None where some OBJECT has no order that works.
    """
    happening, asked = _asked_about(file, world, who, empty)
    least: list[_Ranked] = []
    for thing in asked:
        alone = _orders_together(file, world, who, orders, happening, [thing], True, soonest)
        ranked = [rank[1][0] for _, _, rank in alone]
        if not ranked:
            return None
        least.append(min(ranked, key=lambda taken: (len(taken), taken)))
    return sum(map(len, least)), tuple(least)


def _the_one_order(
    file: File,
    world: World,
    who: tuple[tuple[str, ...], ...],
    orders: tuple[tuple[int, ...], ...],
    empty: Set[int] = frozenset(),
) -> tuple[int, ...] | None:
    """The OPTIONs that one OBJECT puts in an order, where no other OBJECT changes anything.

    None where no OBJECT or more than one leaves a choice. An OBJECT leaves a choice unless
    every two of its OPTIONs start at two different fixed times. Then it has one order, the
    order of those times, and that order says nothing new and moves no start.
    """
    happening, asked = _asked_about(file, world, who, empty)
    fixed = {index: world.terms[file.options[index].id].fixed_start for index in happening}

    def either_way(one: int, other: int) -> bool:
        return fixed[one] is None or fixed[other] is None or fixed[one] == fixed[other]

    open_to_choice = [
        matters
        for thing in asked
        for _, matters in [_ordered_by(file, world, orders, happening, thing)]
        if any(either_way(one, other) for one, other in combinations(matters, 2))
    ]
    return open_to_choice[0] if len(open_to_choice) == 1 else None


def _to_try_first(
    file: File,
    world: World,
    who: tuple[tuple[str, ...], ...],
    orders: tuple[tuple[int, ...], ...],
    in_orders: Iterable[Sequence[int] | None],
    fits: Callable[[list[tuple[int, int, int]]], bool],
    empty: Set[int] = frozenset(),
) -> Iterator[_Chain]:
    """What ``_chains`` would give for each of these orders of all the OPTIONs of a plan.

    They are tried before any other, and every one of them that the search can time is
    among the others too. One that goes round in a circle with what the PERSONs do is left
    out there, as any order is. Any other keeps each PERSON's order of the OPTIONs that
    matter to each OBJECT, and so does some order of all the OPTIONs, which gives the same.
    So they change how soon the search is over, and not what it finds. They are made one at
    a time, as they are asked for, and ``fits`` is as for ``_chains_in_order``.
    """
    for each in in_orders:
        if each is not None:
            yield from _chains_in_order(file, world, who, orders, each, fits, empty)


def spans_closed(file: File, origin: str, destination: str) -> list[tuple[int, int]]:
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
    start chosen inside its own limits leaves room for all the others. So where a start comes
    out outside its limits, there is no timing, and the result is None. That is about the
    starts that are not fixed. A fixed start outside the TRIP comes back as it is, and the
    check of the ITINERARY finds it.
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
    timed = [moment for moment in times if moment is not None]
    for node, moment in enumerate(timed):
        if moment < floor.get(node, moment) or moment > cap.get(node, moment):
            return None  # a start outside its own limits: nothing fits inside them
    return timed


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
# How an ITINERARY ranks among those of one choice: its hand-overs, then its steps in order.
type _Comes = tuple[tuple[int, tuple[_Ranked, ...]], list[_StepOrder]]


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
    found = _that_work(file, world, None, "first")
    return found[0] if found else None


def any_works(file: File, world: World) -> bool:
    """Whether any ITINERARY works in this world. The search stops at the first that does."""
    return bool(_that_work(file, world, None, "any"))
