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
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence, Set, Sized
from dataclasses import dataclass, field, replace
from enum import Enum
from heapq import heapify, heappop, heappush
from itertools import chain, combinations, groupby, pairwise, permutations, product
from math import inf
from typing import NamedTuple

from agloe.file import Booking, Complete, File, Offer, Satisfies, StartsFrom, Want, WithObject

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
    REQUIRED = "Each requirement of an OPTION is met"
    AT_HAND = "Each OBJECT is at hand where it is required, handed over or carried"
    REFUSED = "No PERSON has an OBJECT in an OPTION that refuses it"


@dataclass(frozen=True)
class Step:
    """One thing in an ITINERARY: an OPTION that happens, or a WAY that PERSONs take.

    ``option`` names an OPTION. Otherwise the step is a WAY: ``way`` names a listed one, and both
    are None for a WAY the FILE does not list. ``end`` follows from the duration, and is None when
    nobody knows how long the step takes.

    ``handed`` holds each hand-over in an OPTION: an OBJECT, and the PERSON who has it from the
    start of the OPTION. ``carried`` holds each OBJECT that is carried in an OPTION: it is in
    the OPTION from its start, and lies at the PLACE where the OPTION ends from its end.
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
    would be at hand, where it is in an OPTION that ends at the PLACE where this one starts.

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

    ``requires`` says what an OPTION requires of a CAPABILITY: "one" where a PERSON who takes
    part has to have it, and "each" where every PERSON who takes part has to. A pair that is
    not in it requires nothing. ``has`` holds each PERSON and CAPABILITY where the PERSON has it.

    ``needs`` holds each OPTION and OBJECT where the OPTION requires the OBJECT, and
    ``refuses`` each one where the OPTION refuses it. ``does`` says
    what an OPTION does with an OBJECT: "hands_over", "keeps" or "carries". A pair that is not
    in it leaves the OBJECT alone. Two more values are no single possible world. "might_keep"
    is the worst of the ways at once: the OPTION hands nothing over and carries nothing, and
    nobody knows whether it keeps the OBJECT. "any" is the best of them: the OPTION does
    whichever of the four suits the plan.
    ``starts`` says where each OBJECT is when the TRIP starts. An OBJECT that is in
    ``starts_anywhere`` starts with whichever PERSON or at whichever PLACE suits the plan, or
    somewhere the FILE does not name, and each of those is one possible world. An OBJECT
    that is in neither might be anywhere: with any PERSON, at any PLACE, or somewhere the
    FILE does not name. That is the worst of the ways at once, and a plan has to work
    wherever the OBJECT is. ``brought`` holds each OBJECT that the fourteenth and the
    fifteenth CONSTRAINT ask nothing of: another transfer might put it at hand wherever a
    plan needs it, and take it out of an OPTION that refuses it. That is an upper bound, and
    no possible world.
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
    refuses: frozenset[tuple[str, str]] = frozenset()
    does: Mapping[tuple[str, str], str] = field(default_factory=dict[tuple[str, str], str])
    starts: Mapping[str, Where] = field(default_factory=dict[str, Where])
    starts_anywhere: frozenset[str] = frozenset()
    brought: frozenset[str] = frozenset()


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

    For an OPTION and a CAPABILITY it is "requirement": what the OPTION requires of it. For a
    PERSON and a CAPABILITY it is "has". ``about`` names the CAPABILITY.

    For an OPTION and an OBJECT it is "does not require", "does not refuse", or one of the
    four ways that what the OPTION does with the OBJECT can help: "keeps", "does not keep",
    "hands over" and "carries". For an OBJECT it is "starts with" a PERSON or "starts at" a
    PLACE, or "another transfer": something outside the FILE that puts the OBJECT at hand
    where a plan needs it, and takes it out of an OPTION that refuses it. ``about`` names the
    OBJECT.
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
    with no BOOKING for the OPTION of one of those. A FACT about an OBJECT can help only where
    some OPTION requires the OBJECT or refuses it, or might.
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
        for capability in file.capabilities:
            if file.requires(option.id, capability.id) is None:
                out.append(Unknown("requirement", option.id, about=capability.id))
        for thing in file.objects_asked_for():
            if file.requires_object(option.id, thing.id) is None:
                out.append(Unknown("does not require", option.id, about=thing.id))
            if file.refuses_object(option.id, thing.id) is None:
                out.append(Unknown("does not refuse", option.id, about=thing.id))
            if file.does_with(option.id, thing.id) is None:
                out += [Unknown(what, option.id, about=thing.id) for what in _ACTIONS]
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
    for want in musts:
        for person in _in_file_order_of_persons(file, want.musts):
            out.append(Unknown("another option", want=want.id, person=person))
    for thing in file.objects_asked_for():
        if file.transfers_complete(thing.id) is None:
            out.append(Unknown("another transfer", about=thing.id))
    return tuple(out)


# How what an OPTION does with an OBJECT can help.
_ACTIONS = ("keeps", "does not keep", "hands over", "carries")
_STARTS = ("starts with", "starts at")  # where an OBJECT can turn out to start


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
    so it might cover anybody. ``open_to_all`` holds the OPTION of each such BOOKING. Both
    belong to the search for a conflict: no FILE that is read has them, and no answer is ever
    given for what is left.

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

    def without(self, record: str) -> Remaining:
        """What is left with one more FACT, WANT or DECISION taken out."""
        found = [fact for fact in self.file.facts if fact.id == record]
        taken = {(fact.option, fact.want) for fact in found if isinstance(fact, Satisfies)}
        opened = {fact.option for fact in found if isinstance(fact, Booking | Offer)}
        acted = {(fact.option, fact.object) for fact in found if isinstance(fact, WithObject)}
        return Remaining(
            self.file.without(record),
            self.unsaid | taken,
            self.open_to_all | opened,
            self.undone | acted,
        )

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
    refuses: set[tuple[str, str]] = set()
    acts: dict[tuple[str, str], str] = {}
    begins: dict[str, Where] = {}
    begins_anywhere: set[str] = set()
    brought: set[str] = set()
    turns_out = {
        "keeps": "keeps",
        "hands over": "hands_over",
        "carries": "carries",
        "does not keep": "nothing",
    }
    favoured = {
        (each.what, each.option, each.about): each
        for each in kind or ()
        if each.what in (*_ACTIONS, *_STARTS)
    }
    for thing in file.objects:
        another = Unknown("another transfer", about=thing.id)
        if file.transfers_complete(thing.id) is None and well(another):
            brought.add(thing.id)
        for option in file.options:
            pair = (option.id, thing.id)
            required = file.requires_object(*pair)
            if required is None:
                required = not well(Unknown("does not require", option.id, about=thing.id))
            if required:
                needs.add(pair)
            refused = file.refuses_object(*pair)
            if refused is None:
                refused = not well(Unknown("does not refuse", option.id, about=thing.id))
            if refused:
                refuses.add(pair)
            action = file.does_with(*pair)
            if action is None and kind is not None:
                found = [what for what in _ACTIONS if (what, *pair) in favoured]
                action = turns_out[found[0]] if found else "might_keep"
            if action is not None and action != "nothing":
                acts[pair] = action
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
        frozenset(refuses),
        acts,
        begins,
        frozenset(begins_anywhere),
        frozenset(brought),
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
    return [*_each_alone(file, world, itinerary), *_in_this_order(file, world, itinerary, placed)]


def works_as_listed(file: File, world: World, itinerary: Itinerary) -> bool:
    """Whether this ITINERARY meets every CONSTRAINT with its steps in the order it lists them.

    The steps must be listed in an order their times allow: earlier starts first.
    """
    in_order = all(before.start <= after.start for before, after in pairwise(itinerary))
    return in_order and not broken_as_listed(file, world, itinerary)


def _in_this_order(
    file: File, world: World, itinerary: Itinerary, order: list[_Placed]
) -> list[Broken]:
    """The CONSTRAINTs that turn on the order of the steps, with the steps in one order."""
    return [*_along_each_path(file, world, itinerary, order), *_objects(file, world, order)]


def _each_alone(file: File, world: World, itinerary: Itinerary) -> list[Broken]:
    """The CONSTRAINTs that hold or not whatever order the steps happen in."""
    taking_part = {step.option: step.persons for step in itinerary if step.option is not None}
    return [
        *_locks(file, itinerary),
        *_starts(world, itinerary),
        *_durations(world, itinerary),
        *_musts(file, world, taking_part),
        *_must_nots(file, world, taking_part),
        *_requirements(file, world, taking_part),
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
    out += [
        Broken(Constraint.CAP, None, (), cap=cap) for cap in passed_by_the_bookings(file, world)
    ]
    if file.caps and not out and way_to_pay(file, world, taking_part) is None:
        out.append(Broken(Constraint.CAP, None, ()))
    return out


def passed_by_the_bookings(file: File, world: World) -> list[str]:
    """Each cap that what the BOOKINGs charged passes in this world, or might, by itself."""
    return [
        cap.id
        for key, cap in file.caps.items()
        if (charged := world.spent.get(key, 0)) is None or charged > cap.limit.units
    ]


type Pair = tuple[str, str | None, tuple[str, str] | None, int]


def pairs_to_pay(file: File, world: World, option: str, person: str) -> list[Pair]:
    """Each pair of an OFFER and a BUDGET this PERSON can take for a place, in the FILE's order.

    A pair holds the OFFER, the BUDGET, the cap that counts the purchase by its BUDGET and
    currency, and the price in ten-thousandths. The BUDGET is None for a place that costs
    nothing, and where money from outside the FILE pays: no cap counts those. BUDGETs with no
    cap in the currency of the price are alike, so only the first of them makes a pair.
    """
    able: list[Pair] = []
    for offer in file.offers(option):
        if (offer.id, person) not in world.payable:
            continue
        price = offer.price
        sources = () if price is None or not price.amount else file.payers(person, price.currency)
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

    Once the search has had to go back, it looks at the purchases after a pair before it
    takes the pair: see ``_can_follow``. A pair that they cannot follow is passed over at
    once. The search would give it up anyway, after trying everything behind it, so the way
    to pay is the same. Where the first pairs all fit, nothing is looked at.

    From then on it also remembers where it has been: see ``_tried``. Different pairs for
    the purchases so far can leave the same places and the same room for the same purchases
    to come. Where those had no way to pay once, they have none now, and the pair that leads
    there is passed over too.
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
    pairs = [pairs_to_pay(file, world, option, person) for option, person in buyers]
    left = {offer.id: offer.places for option in taking_part for offer in file.offers(option)}
    picked: list[int] = []
    start = 0
    looks_ahead = False
    no_way: set[_Tried] = set()  # where the purchases to come were found to have no way to pay
    while len(picked) < len(buyers):
        able = pairs[len(picked)]
        found = None
        for number in range(start, len(able)):
            offer, _, key, units = able[number]
            if not left[offer] or (key is not None and room[key] < units):
                continue
            left[offer] -= 1
            if key is not None:
                room[key] -= units
            ahead = len(picked) + 1
            if not looks_ahead or (
                _tried(left, room) not in no_way and _can_follow(pairs, ahead, left, room)
            ):
                found = number
                break
            left[offer] += 1
            if key is not None:
                room[key] += units
        if found is None:
            if not picked:
                return None
            # Every pair of this purchase has been tried from here, now or before the search
            # last came back to it.
            no_way.add(_tried(left, room))
            looks_ahead = True
            start = picked.pop() + 1
            offer, _, key, units = pairs[len(picked)][start - 1]
            left[offer] += 1
            if key is not None:
                room[key] += units
            continue
        picked.append(found)
        start = 0
    return {
        buyer: (able[number][0], able[number][1])
        for buyer, able, number in zip(buyers, pairs, picked, strict=True)
    }


type _Tried = tuple[tuple[int, ...], tuple[int, ...]]


def _tried(left: Mapping[str, int], room: Mapping[tuple[str, str], int]) -> _Tried:
    """What decides whether the purchases still to come have a way to pay.

    It is the places each OFFER still has and the room each cap still has. Each purchase
    takes one place, so the places left also say how many purchases are behind, and which
    are still to come. Which pairs the purchases behind took plays no part beyond that. So
    the search for the rest goes the same way each time the two are the same.
    """
    return tuple(left.values()), tuple(room.values())


def _can_follow(
    pairs: Sequence[Sequence[Pair]],
    first: int,
    left: Mapping[str, int],
    room: Mapping[tuple[str, str], int],
) -> bool:
    """Whether nothing yet rules out the purchases from this one on. False is a proof.

    ``left`` says how many places each OFFER still has, and ``room`` what each cap still
    allows, after the purchases before these. A pair is open to a purchase while its OFFER
    has a place and its cap has room for the price. The purchases before it only ever take
    places and room away, so the pair a purchase ends with is one that is open to it now.

    So a purchase with no pair open cannot be made. And where every pair still open to a
    purchase draws on one cap, that cap owes it the cheapest of them at least. A cap that
    owes more than it has left cannot pay for all of them.

    True promises nothing: the purchases can still turn out to have no way to pay.
    """
    owed: dict[tuple[str, str], int] = {}
    for able in pairs[first:]:
        only: tuple[str, str] | None = None
        least = 0
        choice = False
        for offer, _, key, units in able:
            if not left[offer] or (key is not None and room[key] < units):
                continue
            if key is None or (only is not None and key != only):
                choice = True
                break
            least = units if only is None else min(least, units)
            only = key
        if choice:
            continue
        if only is None:
            return False
        owed[only] = owed.get(only, 0) + least
        if owed[only] > room[only]:
            return False
    return True


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
    Where it requires it of each PERSON, everybody in it has. Only who takes part counts:
    no time and no order changes it. One Broken for each OPTION and CAPABILITY, naming the
    PERSONs in the FILE's order: everybody in the OPTION where none of them has it, and
    those who lack it where each of them has to have it.
    """
    out: list[Broken] = []
    for option, persons in taking_part.items():
        for capability in file.capabilities:
            of = world.requires.get((option, capability.id))
            if of is None or not persons:
                continue
            lacking = [person for person in persons if (person, capability.id) not in world.has]
            if lacking and (of == "each" or len(lacking) == len(persons)):
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
# One way an OBJECT can go: what it breaks, where it might be when the TRIP starts and then
# after each OPTION, and where it might be just before each OPTION starts.
type _Run = tuple[tuple[_Miss, ...], tuple[frozenset[Where], ...], tuple[frozenset[Where], ...]]
type _Way = tuple[tuple[int, ...], *_Run]  # the picks that led somewhere, and what came of them
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


def _left(
    does: str, places: frozenset[Where], persons: Sequence[str], origin: str
) -> frozenset[Where]:
    """Where an OBJECT might be once an OPTION has kept it, might have kept it, or has not.

    An OPTION that keeps it moves it from whoever takes part to the PLACE where the OPTION
    starts. One that might keep it leaves it in both places.
    """
    if does == "keeps":
        return frozenset(Where(place=origin) if each.person in persons else each for each in places)
    if does == "might_keep":
        return places | {Where(place=origin) for each in places if each.person in persons}
    return places


def _least_broken(
    world: World,
    thing: str,
    visits: Sequence[_Visit],
    begins: Sequence[frozenset[Where]],
    handed: Mapping[str, str],
    carried: Set[str],
    ends_at: Mapping[str, str],
) -> _Run:
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
    OBJECT there. It carries the OBJECT only where no PERSON who takes part has it. In a
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
    """
    reached: dict[frozenset[Where], _Way] = {}
    for pick, start in enumerate(begins):
        reached.setdefault(start, ((pick,), (), (start,), ()))
    for position, (option, persons, origin, over) in enumerate(visits):
        action = world.does.get((option, thing), "nothing")
        refused = (option, thing) in world.refuses
        taker = handed.get(option)
        loaded = option in carried
        # Whatever was carried in an OPTION that is over lies where that OPTION ends.
        found_there: dict[frozenset[Where], _Way] = {}
        for places, way in reached.items():
            there = arrived(places, over, ends_at)
            known = found_there.get(there)
            if known is None or (len(way[1]), way[0]) < (len(known[1]), known[0]):
                found_there[there] = way
        following: dict[frozenset[Where], _Way] = {}
        for places, (picks, broken, trail, seen) in found_there.items():
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
                after = places if refused else _left(does, places, persons, origin)
                found = broken
                at_hand = within_reach(after, persons, origin)
                if taker is not None:
                    if does == "hands_over" and at_hand and not refused:
                        after = frozenset({Where(person=taker)})
                    else:
                        # Not handed over: it stays, or is kept.
                        if refused:
                            found = (*found, (position, Constraint.REFUSED, taker))
                        if does != "hands_over" or not at_hand:
                            found = (*found, (position, Constraint.AT_HAND, taker))
                if loaded:
                    if does == "carries" and at_hand and not (refused and held):
                        after = frozenset({Where(option=option)})
                    elif does != "carries" or not at_hand:
                        # Not carried: it stays, or is kept.
                        found = (*found, (position, Constraint.AT_HAND, _CARRY))
                known = following.get(after)
                if known is None or (len(found), (*picks, pick)) < (len(known[1]), known[0]):
                    following[after] = ((*picks, pick), found, (*trail, after), (*seen, places))
        reached = following
    _, broken, trail, seen = min(reached.values(), key=lambda way: (len(way[1]), way[0]))
    return broken, trail, seen


# Where an OBJECT might be, and the arrivals that got it there: each an OPTION that carried
# it, and the OPTION that first used it afterwards. The second starts no earlier than the
# first ends.
type _Spot = tuple[frozenset[Where], tuple[tuple[str, str], ...]]
# Each ``_Spot`` that a search has reached, with the first hand-overs and carries that lead
# to it.
type _Reached = dict[_Spot, _Ranked]


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
    """
    reached: _Reached = {(start, ()): () for start in begins}
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
    arrivals counted on so far, and the first hand-overs and carries that lead there. The
    result holds the same for after the OPTION. It is empty where the fourteenth or the
    fifteenth CONSTRAINT cannot be kept, whatever was handed over or carried.

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
    action = world.does.get((option, thing), "nothing")
    kept: dict[frozenset[Where], dict[tuple[tuple[str, str], ...], _Ranked]] = {}

    def keep(
        places: frozenset[Where], arrivals: tuple[tuple[str, str], ...], taken: _Ranked
    ) -> None:
        """Keep this choice, unless one that is kept counts on no more and comes no later."""
        there = kept.setdefault(places, {})
        counted, rank = set(arrivals), (len(taken), taken)
        if any(
            counted.issuperset(others) and (len(theirs), theirs) <= rank
            for others, theirs in there.items()
        ):
            return
        for others in [
            others
            for others, theirs in there.items()
            if counted.issubset(others) and rank <= (len(theirs), theirs)
        ]:
            del there[others]
        there[arrivals] = taken

    for (places, arrivals), taken in reached.items():
        # Where the OBJECT is for an OPTION that uses it, with the arrivals that takes. None
        # where nobody knows when an OPTION that carried it ends.
        in_use: _Spot | None = (places, arrivals)
        carriers = sorted({each.option for each in places if each.option is not None})
        if carriers:
            in_use = None
            if all(world.terms[carrier].longest is not None for carrier in carriers):
                there = arrived(places, set(carriers), ends_at)
                more = ((carrier, option) for carrier in carriers)
                in_use = (there, tuple(sorted((*arrivals, *more))))
        if (option, thing) in world.needs:
            if in_use is None or not within_reach(in_use[0], persons, origin):
                continue
            places, arrivals = in_use
        if refused and brought_in(places, persons):
            continue
        at_hand = in_use is not None and within_reach(in_use[0], persons, origin)
        for does in ("nothing", "keeps", "hands_over", "carries") if action == "any" else (action,):
            if does not in ("hands_over", "carries"):
                # It takes the OBJECT from no PERSON where it refuses it.
                keep(places if refused else _left(does, places, persons, origin), arrivals, taken)
                continue
            if action != "any":  # with "any" that is "nothing"
                keep(places, arrivals, taken)
            if in_use is None or not at_hand:
                continue
            if does == "carries":
                keep(frozenset({Where(option=option)}), in_use[1], (*taken, rank(option, None)))
            elif not refused:
                for person in persons:
                    there = frozenset({Where(person=person)})
                    if in_use[0] != there:  # they have it already
                        keep(there, in_use[1], (*taken, rank(option, person)))
    return {
        (places, arrivals): taken
        for places, there in kept.items()
        for arrivals, taken in there.items()
    }


def _first_of(reached: _Reached) -> list[tuple[_Ranked, tuple[tuple[str, str], ...]]]:
    """What a search has reached, as the choices that can still be the one shown.

    Each is the hand-overs and carries of one OBJECT, with the arrivals they count on. Where
    the OBJECT ends up no longer matters. So a choice is left out where another counts on
    no arrival that it does not count on, and the rules put the other no later: start times
    that keep the first keep the other. They come in the order of the rules, the first
    choice first.
    """
    ranked = sorted(
        ((len(taken), taken, arrivals) for (_, arrivals), taken in reached.items()),
    )
    found: list[tuple[_Ranked, tuple[tuple[str, str], ...]]] = []
    for _, taken, arrivals in ranked:
        if not any(set(arrivals).issuperset(others) for _, others in found):
            found.append((taken, arrivals))
    return found


def _as_planned(
    file: File, world: World, steps: Iterable[Step]
) -> Iterator[tuple[str, list[_Visit], _Run]]:
    """How each OBJECT goes through the OPTIONs among these steps, as the plan says.

    One result for each OBJECT that the fourteenth and the fifteenth CONSTRAINT ask about in
    this world: the OBJECT, the OPTIONs in the order given, and the way the OBJECT goes with
    the hand-overs and the carries of the plan. An OPTION is over for another where it ends
    no later than the other starts. Where the world leaves something to pick, that is the
    first way that breaks the least.
    """
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
        run = _least_broken(world, thing.id, visits, begins, handed, carried, ends_at)
        yield thing.id, visits, run


def _objects(file: File, world: World, order: list[_Placed]) -> list[Broken]:
    """The fourteenth and the fifteenth CONSTRAINT, with the steps in one order.

    Each OBJECT is at hand where it is required, handed over or carried, and no PERSON has
    it in an OPTION that refuses it. Where it is not at hand for an OPTION that requires
    it, the Broken names everybody who takes part, and so it does where the OBJECT cannot
    be carried. Where a PERSON has it in an OPTION that refuses it, the Broken names each
    PERSON who takes part and has it just before the OPTION starts, or might. Where it
    cannot be handed over, the Broken names the PERSON who was to have it.

    An OBJECT that is not at hand can be on its way: it is in an OPTION that ends at the
    PLACE where this one starts. Then the Broken says how long after the start of this
    OPTION that one ends. One OPTION can ask for an OBJECT twice: it requires it and
    carries it. Both findings are the same then, and one is given.
    """
    steps = {step.option: step for _, step in order if step.option is not None}
    out: list[Broken] = []
    for thing, visits, (broken, _, seen) in _as_planned(file, world, (step for _, step in order)):
        for position, constraint, taker in broken:
            option, persons, _, _ = visits[position]
            late: int | None = None
            if taker is not None and taker != _CARRY:
                who: tuple[str, ...] = (taker,)
            elif constraint is Constraint.REFUSED:
                have = [each for each in persons if Where(person=each) in seen[position]]
                who = _in_file_order_of_persons(file, have)
            else:
                who = _in_file_order_of_persons(file, persons)
            aboard = [each.option for each in seen[position]]
            if constraint is Constraint.AT_HAND and len(aboard) == 1 and aboard[0] is not None:
                carrier, here = steps[aboard[0]], steps[option]
                if carrier.end is not None and carrier.destination == here.origin:
                    late = carrier.end - here.start
            found = Broken(constraint, option, who, late, object=thing)
            if found not in out:
                out.append(found)
    return out


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
    return {thing: trail for thing, _, (_, trail, _) in _as_planned(file, world, itinerary)}


def just_before(
    file: File, world: World, itinerary: Itinerary
) -> dict[str, tuple[frozenset[Where], ...]]:
    """Where each OBJECT might be just before each OPTION of an ITINERARY starts, in this world.

    The OPTIONs come in the order the ITINERARY lists them, and the OBJECTs are those of
    ``whereabouts``. An OBJECT that was carried in an OPTION that is over by then lies at the
    PLACE where that OPTION ends.
    """
    return {thing: seen for thing, _, (_, _, seen) in _as_planned(file, world, itinerary)}


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
    file: File, world: World, who: tuple[tuple[str, ...], ...]
) -> tuple[list[int], list[str]]:
    """The OPTIONs of a plan that happen, and the OBJECTs that one of them requires or refuses.

    The OPTIONs are by position in the FILE.
    """
    happening = [index for index, persons in enumerate(who) if persons]
    checked = world.needs | world.refuses
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

    ``fits`` says whether some start times keep a list of gaps with what the PERSONs do. A
    choice of one OBJECT that counts on an arrival is left out where its own gaps do not
    fit: then they do not fit with the gaps of the other OBJECTs either. Nine bags that
    only the last of four ferries brings in time have one choice each that way, and a
    quarter of a million together without it.
    """
    happening, asked = _asked_about(file, world, who)
    if not asked:
        return None
    alike = only_the_first_of_a_kind
    return _orders_together(file, world, who, orders, happening, asked, alike, soonest or {}, fits)


def _can_have(
    file: File, world: World, orders: tuple[tuple[int, ...], ...], thing: str
) -> dict[int, set[str]]:
    """For each OPTION of a plan, the PERSONs in it who can have an OBJECT just before it.

    The OPTIONs are by position in the FILE. A PERSON can have the OBJECT in an OPTION who
    has it when the TRIP starts, or might, or who takes part before that in an OPTION of
    the plan that hands it over and does not refuse it. ``orders`` says what comes before
    what for each PERSON. An OPTION that only might hand it over counts as one that does.
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
            if world.does.get(pair) in ("hands_over", "any") and pair not in world.refuses:
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
    no PERSON can ever have it: then it lies at the PLACE where the OPTION starts.
    """
    options = file.options
    holders = _can_have(file, world, orders, thing)
    moving: set[int] = set()
    for index in happening:
        pair = (options[index].id, thing)
        action = world.does.get(pair)
        if action in ("carries", "any"):
            moving.add(index)
        elif pair in world.refuses:
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
    that OPTION comes.

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
    happening, asked = _asked_about(file, world, who)
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
        an OPTION that refuses it, and with it every order that starts the same way. Where
        another transfer brings the OBJECT, every order works, with no hand-over and no
        carry. An OBJECT that nothing moves has no order, and is taken through the OPTIONs
        that check it as the FILE lists them.
        """
        thing = asked[number]
        brought = thing in world.brought
        begins: _Reached = {(start, ()): () for start in _begins(file, world, thing)}
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
                    # A PERSON who is taken out has nothing handed over to them there.
                    handed = tuple(each for each in step.handed if each[1] in staying)
                    smaller.append(replace(step, persons=staying, handed=handed))
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
    return _that_work(file, world, known, one_is_enough=False)


def _that_work(
    file: File, world: World, known: Routes | None, one_is_enough: bool
) -> list[Itinerary]:
    """The ITINERARIES of ``itineraries``, or with ``one_is_enough`` the first one that is found.

    The first one found works, like every one that ``scheduled`` returns. It need not be one in
    which PERSONs take part the fewest times, nor the one a report shows.
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
        for orders in product(*(list(_orders(file, world, indexes, known)) for indexes in mine)):
            found = scheduled(file, world, who, orders, known=known, any_will_do=one_is_enough)
            if found is None:
                continue
            if one_is_enough:
                return [found]
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
    falls: Mapping[tuple[int, int, int], int] | None = None,
    any_will_do: bool = False,
    in_order: Sequence[int] | None = None,
) -> Itinerary | None:
    """The ITINERARY for one choice of PERSONs and orders, or None when it breaks a CONSTRAINT.

    Each time a PERSON takes a WAY is a step of its own, and the steps are listed in the order
    they happen. Every ITINERARY returned has passed ``works_as_listed``. Where an OPTION of
    the plan requires or refuses an OBJECT, the ITINERARY has the hand-overs that "Which
    ITINERARY is shown" puts first, and its OPTIONs in the order that goes with them.

    ``who`` names the PERSONs in each OPTION, in the FILE's order of OPTIONs. ``orders`` gives,
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
        return next(_timings(file, world, who, orders, by, falls, any_will_do, first), None)
    known = known or Routes(file, world)
    return next(_schedules(file, world, who, orders, known, any_will_do), None)


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


def _schedules(
    file: File,
    world: World,
    who: tuple[tuple[str, ...], ...],
    orders: tuple[tuple[int, ...], ...],
    known: Routes,
    any_will_do: bool = False,
) -> Iterator[Itinerary]:
    """The ITINERARIES for one choice of PERSONs and orders.

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
    found = _chains(file, world, who, orders)
    if found is not None and next(iter(found), None) is None:
        return  # an OBJECT is not at hand where it has to be, whatever the WAYs and the times
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
                if 0 <= spot < len(order) - 1:
                    possible = known.after(order[spot], order[spot + 1])
                else:
                    before = order[spot] if spot >= 0 else None
                    after = None if last else order[spot + 1]
                    possible = known.at_an_end(here, there, before, after)
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
        yield from _timings(file, world, who, orders, hops, None, any_will_do)


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
) -> Iterator[Itinerary]:
    """The ITINERARIES for one choice of PERSONs, orders and routes, one for each timing.

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
    fixed: dict[int, int] = {}
    for index, option in enumerate(file.options):
        at = world.terms[option.id].fixed_start
        if who[index] and at is not None:
            fixed[index] = at

    # The limits on each start that fix no start themselves. No step starts before the TRIP
    # starts, and a step with a known length starts early enough to be over when the TRIP ends.
    # An OPTION that does not happen is no step, and has no limit.
    trip_starts, trip_ends = file.trip_start(), file.trip_end()
    not_before: dict[int, int] = {}
    no_later: dict[int, int] = {}
    for node in range(count):
        if node < listed and not who[node]:
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
    nodes = [*(index for index in range(listed) if who[index]), *range(listed, count)]
    # The steps as the rule times them with no order of an OBJECT, where the timing can fall
    # in one way only. Each is ranked as the listing of an ITINERARY ranks it.
    as_timed: dict[int, _StepOrder] | None = None
    if not any_will_do and not ruled_out and _asked_about(file, world, who)[1]:
        plain = _times(count, gaps, fixed, not_before, no_later)
        if plain is not None:
            as_timed = {node: _step_in_file_order(file, step(node, plain[node])) for node in nodes}
    alike = _orders_differ_only_in_the_listing(file, world, who, orders, fixed, gaps, as_timed)
    soonest = _earliest_starts(count, gaps, fixed, not_before)

    def can_be_timed(more: list[tuple[int, int, int]]) -> bool:
        """Whether some start times keep these gaps with what the PERSONs do."""
        return _times(count, [*gaps, *more], fixed, not_before, no_later) is not None

    found = _chains(file, world, who, orders, alike, soonest, can_be_timed)
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
        first_tries = _to_try_first(file, world, who, orders, known, can_be_timed)
        chains = chain(first_tries, chains)
    least: list[tuple[int, tuple[_Ranked, ...]] | None] = []

    def fewest() -> tuple[int, tuple[_Ranked, ...]] | None:
        """Hand-overs that no ITINERARY of this choice has hand-overs before, where known."""
        if not least:
            least.append(_fewest_hand_overs(file, world, who, orders, soonest))
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
    ordered = _the_one_order(file, world, who, orders)
    if ordered is None or any(index not in fixed for index in ordered):
        return False
    return all(as_timed[before] < as_timed[after] for before, after, _ in gaps)


def _fewest_hand_overs(
    file: File,
    world: World,
    who: tuple[tuple[str, ...], ...],
    orders: tuple[tuple[int, ...], ...],
    soonest: Mapping[int, int],
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
    happening, asked = _asked_about(file, world, who)
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
) -> tuple[int, ...] | None:
    """The OPTIONs that one OBJECT puts in an order, where no other OBJECT changes anything.

    None where no OBJECT or more than one leaves a choice. An OBJECT leaves a choice unless
    every two of its OPTIONs start at two different fixed times. Then it has one order, the
    order of those times, and that order says nothing new and moves no start.
    """
    happening, asked = _asked_about(file, world, who)
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
            yield from _chains_in_order(file, world, who, orders, each, fits)


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
    found = itineraries(file, world)
    return found[0] if found else None


def any_works(file: File, world: World) -> bool:
    """Whether any ITINERARY works in this world. The search stops at the first that does."""
    return bool(_that_work(file, world, None, one_is_enough=True))
