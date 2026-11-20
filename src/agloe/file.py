"""Reading a FILE: its structure, its references and its exact values.

The schema in ``schema/file.schema.json`` is the source of truth for a FILE's shape, and
``file_types`` is generated from it. This module refuses anything the schema or the checks below
do not accept, and repairs nothing. What it accepts becomes exact values: a time is a whole number
of seconds since 1970-01-01T00:00:00Z, and a length of time is a whole number of seconds. A time
must agree with the time zone it names.
"""

import json
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import cache, cached_property
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast
from zoneinfo import ZoneInfo

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

if TYPE_CHECKING:
    from agloe import file_types as shape

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_DEEPEST = 16  # a FILE that follows the format nests far less deeply than this
_LENGTH = re.compile(r"PT(?:([0-9]{1,9})H)?(?:([0-9]{1,9})M)?(?:([0-9]{1,9})S)?")
_MOST_DIGITS = 18  # a whole number in a FILE has far fewer digits; a longer one stays as written
_ZERO = re.compile(r"-?0(?:\.0+)?(?:[eE][+-]?[0-9]+)?")  # zero, whatever its sign and exponent


class Unwritable(ValueError):
    """A time outside the years 0001 to 9999, which the format cannot write."""


class _Validator(Protocol):
    def iter_errors(self, instance: object) -> Iterable[ValidationError]: ...


class FileError(Exception):
    """The FILE does not follow the format. Each problem names where it is and what is wrong."""

    def __init__(self, problems: Iterable[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("\n".join(self.problems))


@dataclass(frozen=True)
class Person:
    id: str
    name: str


@dataclass(frozen=True)
class Money:
    """An amount in one currency, kept exactly. Two ways to write one amount are equal."""

    amount: Decimal
    currency: str

    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"

    @property
    def units(self) -> int:
        """The amount in whole ten-thousandths. A FILE states no finer amount."""
        _, digits, exponent = self.amount.as_tuple()
        return int("".join(str(digit) for digit in digits)) * 10 ** (4 + int(exponent))


@dataclass(frozen=True)
class Budget:
    """A named source of money.

    ``persons`` may draw on it for what the TRIP still has to buy, and it pays only prices in
    the ``currencies`` it holds.
    """

    id: str
    name: str
    persons: tuple[str, ...]
    currencies: tuple[str, ...]


@dataclass(frozen=True)
class Place:
    id: str
    name: str


@dataclass(frozen=True)
class Option:
    """Something that happens at one PLACE, or moves from one PLACE to another."""

    id: str
    name: str
    origin: str
    destination: str  # the same PLACE as the origin when the OPTION happens at one PLACE


@dataclass(frozen=True)
class Way:
    """A means of getting from one PLACE to another, at any time and as often as needed."""

    id: str
    name: str
    origin: str
    destination: str
    both_ways: bool  # whether a PERSON can also take it from the destination to the origin


@dataclass(frozen=True)
class Want:
    """Something PERSONs want, or want to avoid, from the TRIP."""

    id: str
    name: str
    musts: tuple[str, ...]  # the PERSONs for whom it is a must: a DEGREE OF WANT of +10
    must_nots: tuple[str, ...] = ()  # those for whom it is a must-not: a DEGREE OF WANT of -10
    # The PLACE where each holder ends the TRIP, for a WANT that asks that. Such a WANT is about
    # the whole ITINERARY, and no OPTION delivers it.
    ends_at: str | None = None


@dataclass(frozen=True)
class Start:
    """A FACT: when an OPTION can start."""

    id: str
    option: str
    at: int | None  # None: at any time the planners choose


@dataclass(frozen=True)
class Duration:
    """A FACT: how long an OPTION or a WAY takes. CONTINGENT means the world decides in the range.

    ``option`` holds the id of the OPTION or of the WAY. Ids are unique across the FILE.
    """

    id: str
    option: str
    shortest: int
    longest: int
    contingent: bool


@dataclass(frozen=True)
class Cutoff:
    """A FACT: how long before an OPTION starts each PERSON must reach its PLACE."""

    id: str
    option: str
    margin: int


@dataclass(frozen=True)
class Complete:
    """A FACT: the FILE lists every OPTION and WAY that goes straight from one PLACE to another.

    A PLACE that is None stands for every PLACE.
    """

    id: str
    origin: str | None
    destination: str | None
    earliest: int  # the span of starting times the FACT covers, both ends included
    latest: int

    def covers(self, origin: str, destination: str) -> bool:
        """Whether this FACT is about travel straight from one of these PLACEs to the other."""
        return self.origin in (None, origin) and self.destination in (None, destination)

    def rules_out(self, origin: str, destination: str, start: int) -> bool:
        """Whether this FACT says no unlisted WAY goes between these PLACEs at this time."""
        return self.covers(origin, destination) and self.earliest <= start <= self.latest


@dataclass(frozen=True)
class Satisfies:
    """A FACT: how fully an OPTION delivers what a WANT describes.

    ``degree`` is the DEGREE OF SATISFACTION, from 0 to 10. Zero says that the OPTION does not
    deliver it, and any value above zero says that it does.
    """

    id: str
    option: str
    want: str
    degree: int


@dataclass(frozen=True)
class Lock:
    """A DECISION: the TRIP includes this OPTION, and these PERSONs take part."""

    id: str
    option: str
    persons: tuple[str, ...]


@dataclass(frozen=True)
class CompleteFor:
    """A FACT: the FILE states every OPTION that SATISFIES this WANT.

    Each one is listed, with a FACT that it SATISFIES the WANT. So an OPTION with no such FACT
    does not SATISFY it, and no OPTION outside the FILE does.
    """

    id: str
    want: str


@dataclass(frozen=True)
class TripStart:
    """A DECISION: when the TRIP starts. Nothing in an ITINERARY starts before this time."""

    id: str
    at: int


@dataclass(frozen=True)
class TripEnd:
    """A DECISION: when the TRIP ends. Nothing in an ITINERARY ends after this time."""

    id: str
    at: int


@dataclass(frozen=True)
class Cap:
    """A DECISION: the TRIP spends at most this much from a BUDGET, in the currency of the amount.

    The cap is for the whole TRIP, with what is already paid.
    """

    id: str
    budget: str
    limit: Money


@dataclass(frozen=True)
class StartsFrom:
    """A FACT: where a PERSON starts from. The PERSON's path begins at this PLACE."""

    id: str
    person: str
    place: str


@dataclass(frozen=True)
class NeedsRight:
    """A FACT: whether a PERSON needs a right to take part in an OPTION."""

    id: str
    option: str
    needed: bool


@dataclass(frozen=True)
class Payment:
    """What a BOOKING paid: its whole price, with nothing left to pay.

    ``budget`` is the BUDGET the money came from, and ``by`` the PERSON who paid. None: nobody
    knows.
    """

    money: Money
    budget: str | None = None
    by: str | None = None


@dataclass(frozen=True)
class Booking:
    """A FACT: a BOOKING. It secures a right to one OPTION for each PERSON it covers.

    ``paid`` is what it paid. None: nobody knows.
    """

    id: str
    option: str
    covers: tuple[str, ...]
    paid: Payment | None = None


@dataclass(frozen=True)
class Offer:
    """A FACT: an OFFER. Rights to one OPTION can still be bought, one for each of its places.

    ``price`` is what one place costs. None: nobody knows.
    """

    id: str
    option: str
    places: int
    price: Money | None = None


@dataclass(frozen=True)
class CompleteRights:
    """A FACT: the rights to an OPTION are COMPLETE.

    The BOOKINGs in the FILE secure every right to it that anybody on the TRIP holds. Nobody
    on the TRIP can get another, except by a place of an OFFER that the FACT names in
    ``offers``. Those are all the OFFERs the FILE has for the OPTION.
    """

    id: str
    option: str
    offers: tuple[str, ...] = ()


type Fact = (
    Start
    | Duration
    | Cutoff
    | Complete
    | Satisfies
    | CompleteFor
    | StartsFrom
    | NeedsRight
    | Booking
    | Offer
    | CompleteRights
)
type Decision = Lock | TripStart | TripEnd | Cap


@dataclass(frozen=True)
class File:
    """One TRIP as the FILE records it. Every tuple keeps the FILE's order."""

    persons: tuple[Person, ...]
    places: tuple[Place, ...]
    options: tuple[Option, ...]
    ways: tuple[Way, ...]
    wants: tuple[Want, ...]
    facts: tuple[Fact, ...]
    decisions: tuple[Decision, ...]
    zone: str = "UTC"  # the time zone of the first time in the FILE; reports show times in it
    budgets: tuple[Budget, ...] = ()

    @property
    def locks(self) -> tuple[Lock, ...]:
        """The LOCKs among the DECISIONs, in the FILE's order."""
        return tuple(each for each in self.decisions if isinstance(each, Lock))

    def option(self, id: str) -> Option:
        return next(option for option in self.options if option.id == id)

    def way(self, id: str) -> Way:
        return next(way for way in self.ways if way.id == id)

    def start(self, option: str) -> Start | None:
        return self._start_of.get(option)

    def duration(self, option: str) -> Duration | None:
        return self._duration_of.get(option)

    def cutoff(self, option: str) -> Cutoff | None:
        return self._cutoff_of.get(option)

    @cached_property
    def _start_of(self) -> dict[str, Start]:
        """The start of each OPTION that has one stated, looked up once."""
        return {fact.option: fact for fact in self.facts if isinstance(fact, Start)}

    @cached_property
    def _duration_of(self) -> dict[str, Duration]:
        """How long each OPTION and WAY takes, where the FILE says, looked up once."""
        return {fact.option: fact for fact in self.facts if isinstance(fact, Duration)}

    @cached_property
    def _cutoff_of(self) -> dict[str, Cutoff]:
        """The access cutoff of each OPTION that has one stated, looked up once."""
        return {fact.option: fact for fact in self.facts if isinstance(fact, Cutoff)}

    def satisfies(self, option: str, want: str) -> Satisfies | None:
        """The FACT about whether this OPTION SATISFIES this WANT, if the FILE states one."""
        for fact in self.facts:
            if isinstance(fact, Satisfies) and (fact.option, fact.want) == (option, want):
                return fact
        return None

    def trip_start(self) -> TripStart | None:
        """The DECISION about when the TRIP starts, if the FILE holds one."""
        return next((each for each in self.decisions if isinstance(each, TripStart)), None)

    def trip_end(self) -> TripEnd | None:
        """The DECISION about when the TRIP ends, if the FILE holds one."""
        return next((each for each in self.decisions if isinstance(each, TripEnd)), None)

    def starts_from(self, person: str) -> StartsFrom | None:
        """The FACT about where this PERSON starts from, if the FILE states one."""
        return self._starts.get(person)

    @cached_property
    def _starts(self) -> dict[str, StartsFrom]:
        """The FACT about where each PERSON starts from, looked up once."""
        return {fact.person: fact for fact in self.facts if isinstance(fact, StartsFrom)}

    def needs_right(self, option: str) -> bool | None:
        """Whether a PERSON needs a right to take part in this OPTION. None: nobody knows."""
        return self._needs_right.get(option)

    def booking(self, option: str, person: str) -> Booking | None:
        """The BOOKING that covers this PERSON for this OPTION: the first one the FILE lists."""
        return self._bookings.get((option, person))

    def listed(self, person: str) -> bool:
        """Whether some BUDGET lists this PERSON. If none does, nobody has said who pays."""
        return person in self._listed

    def pays(self, person: str, price: Money) -> Budget | None:
        """The BUDGET that pays this price for this PERSON: the first one the FILE lists.

        It lists the PERSON and holds the currency. None where no BUDGET does, and for a price
        of nothing, which draws on no BUDGET.
        """
        return self._payers.get((person, price.currency)) if price.amount else None

    @cached_property
    def _listed(self) -> frozenset[str]:
        return frozenset(person for budget in self.budgets for person in budget.persons)

    @cached_property
    def _payers(self) -> dict[tuple[str, str], Budget]:
        """The first BUDGET that lists each PERSON and holds each currency, looked up once."""
        first: dict[tuple[str, str], Budget] = {}
        for budget in self.budgets:
            for person in budget.persons:
                for currency in budget.currencies:
                    first.setdefault((person, currency), budget)
        return first

    def payers(self, person: str, currency: str) -> tuple[Budget, ...]:
        """The BUDGETs that list this PERSON and hold this currency, in the FILE's order."""
        return tuple(
            budget
            for budget in self.budgets
            if person in budget.persons and currency in budget.currencies
        )

    @cached_property
    def caps(self) -> dict[tuple[str, str], Cap]:
        """The cap on each BUDGET and currency that has one."""
        return {
            (each.budget, each.limit.currency): each
            for each in self.decisions
            if isinstance(each, Cap)
        }

    def bookings(self, option: str) -> tuple[Booking, ...]:
        """The BOOKINGs for this OPTION, in the FILE's order."""
        return self._bookings_for.get(option, ())

    @cached_property
    def _bookings_for(self) -> dict[str, tuple[Booking, ...]]:
        found: dict[str, tuple[Booking, ...]] = {}
        for fact in self.facts:
            if isinstance(fact, Booking):
                found[fact.option] = (*found.get(fact.option, ()), fact)
        return found

    def charge_is_open(self, booking: Booking) -> bool:
        """Whether a cap could turn on what this BOOKING charged, and the FILE does not say.

        That is a BOOKING with no stated payment, in a FILE with a cap. It is also a payment
        above nothing that names no BUDGET, in a currency that some cap is in.
        """
        if not self.caps:
            return False
        if booking.paid is None:
            return True
        money = booking.paid.money
        capped = any(currency == money.currency for _, currency in self.caps)
        return bool(money.amount) and booking.paid.budget is None and capped

    def offers(self, option: str) -> tuple[Offer, ...]:
        """The OFFERs for this OPTION, in the FILE's order."""
        return self._offers.get(option, ())

    def places_on_offer(self, option: str) -> int:
        """How many PERSONs can still buy a right to this OPTION."""
        return sum(offer.places for offer in self.offers(option))

    @cached_property
    def _offers(self) -> dict[str, tuple[Offer, ...]]:
        found: dict[str, tuple[Offer, ...]] = {}
        for fact in self.facts:
            if isinstance(fact, Offer):
                found[fact.option] = (*found.get(fact.option, ()), fact)
        return found

    def rights_complete(self, option: str) -> CompleteRights | None:
        """The FACT that the rights to this OPTION are COMPLETE, if there is one."""
        return self._rights_complete.get(option)

    @cached_property
    def _needs_right(self) -> dict[str, bool]:
        return {fact.option: fact.needed for fact in self.facts if isinstance(fact, NeedsRight)}

    @cached_property
    def _bookings(self) -> dict[tuple[str, str], Booking]:
        first: dict[tuple[str, str], Booking] = {}
        for fact in self.facts:
            if isinstance(fact, Booking):
                for person in fact.covers:
                    first.setdefault((fact.option, person), fact)
        return first

    @cached_property
    def _rights_complete(self) -> dict[str, CompleteRights]:
        return {fact.option: fact for fact in self.facts if isinstance(fact, CompleteRights)}

    @cached_property
    def _about_the_end(self) -> frozenset[str]:
        """Each WANT to end the TRIP at a PLACE, looked up once."""
        return frozenset(want.id for want in self.wants if want.ends_at is not None)

    def complete_for(self, want: str) -> CompleteFor | None:
        """The FACT that the FILE states every OPTION that SATISFIES this WANT, if there is one."""
        return next((f for f in self.facts if isinstance(f, CompleteFor) and f.want == want), None)

    def says(self, option: str, want: str) -> bool | None:
        """Whether this OPTION SATISFIES this WANT, as far as the FILE says. None: nobody knows.

        A FACT about the two settles it. Without one, a FACT that the WANT's set is COMPLETE
        settles it too: the OPTION does not. No OPTION delivers a WANT to end the TRIP at a
        PLACE, so that is settled as well.
        """
        stated = self.satisfies(option, want)
        if stated is not None:
            return stated.degree > 0
        if want in self._about_the_end:
            return False
        return None if self.complete_for(want) is None else False

    def without(self, record: str) -> File:
        """The same FILE with one FACT, WANT or DECISION left out.

        A WANT that is left out stays in the FILE with no holders, so it asks nothing of anyone
        and the FACTs about it still name a WANT.
        """
        return replace(
            self,
            wants=tuple(
                replace(want, musts=(), must_nots=()) if want.id == record else want
                for want in self.wants
            ),
            facts=tuple(fact for fact in self.facts if fact.id != record),
            decisions=tuple(each for each in self.decisions if each.id != record),
        )


def instant(text: str) -> int:
    """A time as whole seconds since 1970-01-01T00:00:00Z. Raises ValueError if it is not real."""
    moment = datetime.fromisoformat(text[: text.index("[")])
    return (moment - _EPOCH) // timedelta(seconds=1)


def written(moment: int, zone: str) -> str:
    """A time as a FILE writes it: date and time, offset from UTC, and time zone in brackets.

    A FILE writes an offset in hours and minutes. Where the time zone's offset at that moment
    has seconds too, as Paris had before 1911, the time is written in UTC. So whatever this
    writes can be read back.
    """
    there = local(moment, zone)
    offset = there.utcoffset() or timedelta()
    if offset.total_seconds() % 60:
        return written(moment, "UTC")
    return f"{there.isoformat(timespec='seconds')}[{zone}]"


def local(moment: int, zone: str) -> datetime:
    """A time on the clocks of a time zone, by the time-zone database pinned with Agloe.

    Raises Unwritable for a time outside the years 0001 to 9999, there or in UTC.
    """
    try:
        return (_EPOCH + timedelta(seconds=moment)).astimezone(_zone(zone))
    except OverflowError:
        message = f"a time {moment} seconds from 1970 is outside the years 0001 to 9999"
        raise Unwritable(message) from None


def length_written(seconds: int) -> str:
    """A length of time as a FILE writes it, such as PT2H30M."""
    hours, rest = divmod(seconds, 3600)
    minutes, left = divmod(rest, 60)
    parts = [
        f"{amount}{unit}" for amount, unit in ((hours, "H"), (minutes, "M"), (left, "S")) if amount
    ]
    return "PT" + ("".join(parts) or "0S")


def _zone_problem(text: str) -> str | None:
    """Why a time does not agree with the time zone it names, or None when it does.

    The time-zone database is the one pinned with Agloe, never the computer's own, so the same
    FILE gives the same answer on every machine.
    """
    bracket = text.index("[")
    name = text[bracket + 1 : -1]
    if name not in _zone_names():
        return f"{name} is not a time zone in the time-zone database"
    moment = datetime.fromisoformat(text[:bracket])
    try:
        there = moment.astimezone(_zone(name))
    except OverflowError:
        return f"{text} is outside the years 0001 to 9999 in UTC"
    if there.utcoffset() != moment.utcoffset():
        offset = there.isoformat(timespec="seconds")[19:]
        return f"{text} does not agree with its time zone: {name} is at {offset} then"
    return None


@cache
def _zone_names() -> frozenset[str]:
    return frozenset(resources.files("tzdata").joinpath("zones").read_text().split())


@cache
def _zone(name: str) -> ZoneInfo:
    with resources.files("tzdata.zoneinfo").joinpath(*name.split("/")).open("rb") as data:
        return ZoneInfo.from_file(data, key=name)


def length(text: str) -> int:
    """A length of time as whole seconds."""
    parts = _LENGTH.fullmatch(text)
    if parts is None:
        raise ValueError(text)
    hours, minutes, seconds = (int(part or 0) for part in parts.groups())
    return hours * 3600 + minutes * 60 + seconds


def read(path: Path) -> File:
    """Read a FILE from disk. Raises FileError if it is not JSON or does not follow the format."""
    try:
        text = path.read_text(encoding="utf-8")
    except ValueError as problem:
        raise FileError([f"not readable as JSON: {problem}"]) from problem
    return parse(text)


def parse(text: str) -> File:
    """Read a FILE from its text. Raises FileError as ``read`` does for the same text."""

    def no_constants(name: str) -> object:
        raise ValueError(f"{name} is not a JSON value")

    try:
        written: object = json.loads(
            text,
            object_pairs_hook=_Pairs,
            parse_constant=no_constants,
            parse_float=_exactly,
        )
    except ValueError as problem:
        raise FileError([f"not readable as JSON: {problem}"]) from problem
    except RecursionError as problem:
        raise FileError(["not readable as JSON: it is nested too deeply"]) from problem
    if _too_deep(written):
        raise FileError(["not readable as JSON: it is nested too deeply"])
    repeats: list[str] = []
    document = _stated_once(written, "", repeats)
    if repeats:
        raise FileError(repeats)
    return load(document)


class _Pairs(list[tuple[str, object]]):
    """One JSON object as it was written: its keys and values in order, repeats included."""


class _AsWritten(Decimal):
    """A number that is not whole, kept exactly as the FILE writes it and shown that way."""

    def __repr__(self) -> str:
        return str(self)


def _exactly(text: str) -> int | _AsWritten:
    """A number written with a fraction or an exponent, with nothing rounded.

    Binary floating point would turn 9.9999999999999999 into 10. A whole number such as 10.0
    becomes the same whole number. Anything else stays exactly as written, so that the schema
    refuses it where it asks for a whole number. Zero is zero with any exponent, however large.
    """
    if _ZERO.fullmatch(text):
        return 0
    try:
        value = _AsWritten(text)
        # ``adjusted`` is the power of ten of the first digit: no arithmetic, so no overflow.
        small = value.is_zero() or value.adjusted() < _MOST_DIGITS
        whole = small and value == value.to_integral_value()
    except ArithmeticError:
        raise ValueError(f"{text} is not a number the format can read") from None
    return int(value) if whole else value


def _stated_once(value: object, where: str, problems: list[str]) -> object:
    """The document as plain dictionaries and lists, noting every key an object states twice."""
    if isinstance(value, _Pairs):
        keys = [key for key, _ in value]
        for key in sorted({key for key in keys if keys.count(key) > 1}):
            problems.append(f"{where or 'the FILE'}: states {_shown(key)} more than once")
        return {key: _stated_once(inside, _inside(where, key), problems) for key, inside in value}
    if isinstance(value, list):
        return [
            _stated_once(inside, _inside(where, index), problems)
            for index, inside in enumerate(cast("list[object]", value))
        ]
    return value


def _too_deep(value: object) -> bool:
    """Whether lists and objects nest more deeply than any FILE that follows the format."""
    level: list[object] = [value]
    for _ in range(_DEEPEST):
        inner: list[object] = []
        for each in level:
            if isinstance(each, _Pairs):
                inner += [inside for _, inside in each]
            elif isinstance(each, dict):
                inner += list(cast("dict[str, object]", each).values())
            elif isinstance(each, list):
                inner += cast("list[object]", each)
        if not inner:
            return False
        level = inner
    return True


def _shown(key: str) -> str:
    """A key as it can always be printed: anything but plain letters and marks is escaped."""
    return ascii(key)[1:-1]


def _inside(where: str, key: str | int) -> str:
    """The path to one member of a list or an object, as a JSON Pointer (RFC 6901).

    A slash inside a key is written ``~1`` and a tilde ``~0``, so two different places never
    get the same path. The path of the whole document is empty.
    """
    return f"{where}/{_shown(str(key)).replace('~', '~0').replace('/', '~1')}"


def load(document: object) -> File:
    """Turn a parsed JSON document into a FILE. Raises FileError if it breaks the format."""
    if _too_deep(document):
        raise FileError(["the FILE: it is nested too deeply"])
    schema = json.loads(resources.files("agloe").joinpath("schema/file.schema.json").read_text())
    validator = cast("_Validator", Draft202012Validator(schema))
    shapes = schema["$defs"]
    problems = sorted(_describe(error, shapes) for error in validator.iter_errors(document))
    problems += _unwritable_characters(document, "")
    if problems:
        raise FileError(problems)
    raw = cast("shape.File", document)

    seen: set[str] = set()

    def claim(where: str, id: str) -> None:
        if id in seen:
            problems.append(f"{where}: the id {id} is used more than once")
        seen.add(id)

    def known(where: str, id: str, kind: str, ids: set[str]) -> bool:
        if id not in ids:
            article = "an" if kind[0] in "AEIOU" else "a"
            problems.append(f"{where}: {id} is not {article} {kind} in this FILE")
        return id in ids

    zones: list[str] = []

    def when(where: str, text: str) -> int | None:
        """The moment a time states. None, with the problem noted, where it is no real time."""
        try:
            moment = instant(text)
        except ValueError:
            problems.append(f"{where}: {text} is not a real date and time")
            return None
        disagreement = _zone_problem(text)
        if disagreement is not None:
            problems.append(f"{where}: {disagreement}")
            return None
        zones.append(text[text.index("[") + 1 : -1])
        return moment

    persons = tuple(Person(p["id"], p["name"]) for p in raw["persons"])
    places = tuple(Place(p["id"], p["name"]) for p in raw["places"])
    for kind, records in (("persons", persons), ("places", places)):
        for index, record in enumerate(records):
            claim(f"/{kind}/{index}", record.id)
    person_ids = {person.id for person in persons}
    place_ids = {place.id for place in places}
    budgets: list[Budget] = []
    for index, budget in enumerate(raw.get("budgets", ())):
        where = f"/budgets/{index}"
        claim(where, budget["id"])
        for person in budget["persons"]:
            known(where, person, "PERSON", person_ids)
        budgets.append(
            Budget(
                budget["id"], budget["name"], tuple(budget["persons"]), tuple(budget["currencies"])
            )
        )

    held = {budget.id: budget.currencies for budget in budgets}
    budget_ids = set(held)
    options: list[Option] = []
    for index, option in enumerate(raw["options"]):
        where = f"/options/{index}"
        claim(where, option["id"])
        if "place" in option:
            known(where, option["place"], "PLACE", place_ids)
            options.append(Option(option["id"], option["name"], option["place"], option["place"]))
        else:
            known(where, option["from"], "PLACE", place_ids)
            known(where, option["to"], "PLACE", place_ids)
            if option["from"] == option["to"]:
                problems.append(f"{where}: an OPTION that moves needs two different PLACEs")
            options.append(Option(option["id"], option["name"], option["from"], option["to"]))
    option_ids = {option.id for option in options}

    ways: list[Way] = []
    for index, way in enumerate(raw["ways"]):
        where = f"/ways/{index}"
        claim(where, way["id"])
        origin, destination = way["between"] if "between" in way else (way["from"], way["to"])
        known(where, origin, "PLACE", place_ids)
        known(where, destination, "PLACE", place_ids)
        if origin == destination:
            problems.append(f"{where}: a WAY needs two different PLACEs")
        ways.append(Way(way["id"], way["name"], origin, destination, "between" in way))
    way_ids = {way.id for way in ways}

    wants: list[Want] = []
    for index, want in enumerate(raw["wants"]):
        where = f"/wants/{index}"
        claim(where, want["id"])
        holders = [holder["person"] for holder in want["holders"]]
        for person in holders:
            known(where, person, "PERSON", person_ids)
        for person in sorted({person for person in holders if holders.count(person) > 1}):
            problems.append(f"{where}: {person} is a holder more than once")
        musts = tuple(each["person"] for each in want["holders"] if each["degree"] == 10)
        must_nots = tuple(each["person"] for each in want["holders"] if each["degree"] == -10)
        ends_at = want["itinerary"]["ends_at"] if "itinerary" in want else None
        if ends_at is not None:
            known(where, ends_at, "PLACE", place_ids)
        wants.append(Want(want["id"], want["name"], musts, must_nots, ends_at))
    want_ids = {want.id for want in wants}
    not_delivered = {want.id for want in wants if want.ends_at is not None}

    facts: list[Fact] = []
    stated: set[tuple[str, type]] = set()
    complete: set[tuple[str | None, str | None, int, int]] = set()
    satisfied: set[tuple[str, str]] = set()
    offered: list[tuple[str, str, str]] = []  # where an OFFER is, its id and its OPTION
    closures: list[tuple[str, str, tuple[str, ...]]] = []  # the same for a COMPLETE set of rights
    for index, fact in enumerate(raw["facts"]):
        where = f"/facts/{index}"
        claim(where, fact["id"])
        if "complete" in fact:
            whole = fact["complete"]
            if "satisfies" in whole:
                known(where, whole["satisfies"], "WANT", want_ids)
                if whole["satisfies"] in not_delivered:
                    problems.append(f"{where}: no OPTION delivers {whole['satisfies']}")
                if (whole["satisfies"], CompleteFor) in stated:
                    about = whole["satisfies"]
                    problems.append(f"{where}: another FACT already states this about {about}")
                stated.add((whole["satisfies"], CompleteFor))
                facts.append(CompleteFor(fact["id"], whole["satisfies"]))
                continue
            if "rights_to" in whole:
                about = whole["rights_to"]
                known(where, about, "OPTION", option_ids)
                if (about, CompleteRights) in stated:
                    problems.append(f"{where}: another FACT already states this about {about}")
                stated.add((about, CompleteRights))
                open_offers = tuple(whole.get("offers", ()))
                closures.append((where, about, open_offers))
                facts.append(CompleteRights(fact["id"], about, open_offers))
                continue
            origin, destination = whole.get("from"), whole.get("to")
            for place in (origin, destination):
                if place is not None:
                    known(where, place, "PLACE", place_ids)
            if origin is not None and origin == destination:
                problems.append(f"{where}: a COMPLETE FACT needs two different PLACEs")
            earliest = when(where, whole["leaving"]["earliest"])
            latest = when(where, whole["leaving"]["latest"])
            if earliest is None or latest is None:
                continue
            if earliest > latest:
                problems.append(f"{where}: the span ends before it starts")
            if (origin, destination, earliest, latest) in complete:
                problems.append(f"{where}: another FACT already states this")
            complete.add((origin, destination, earliest, latest))
            facts.append(Complete(fact["id"], origin, destination, earliest, latest))
            continue
        if "booking" in fact:
            agreed = fact["booking"]
            known(where, agreed["option"], "OPTION", option_ids)
            covers = list(agreed["covers"])
            for person in covers:
                known(where, person, "PERSON", person_ids)
            for person in sorted({person for person in covers if covers.count(person) > 1}):
                problems.append(f"{where}: {person} is covered more than once")
            paid = None
            if "paid" in agreed:
                receipt = agreed["paid"]
                money = Money(Decimal(receipt["amount"]), receipt["currency"])
                source, payer = receipt.get("budget"), receipt.get("by")
                listed = source is not None and known(where, source, "BUDGET", budget_ids)
                if source is not None and listed and money.currency not in held[source]:
                    problems.append(f"{where}: {source} holds no {money.currency}")
                if payer is not None:
                    known(where, payer, "PERSON", person_ids)
                paid = Payment(money, source, payer)
            facts.append(Booking(fact["id"], agreed["option"], tuple(covers), paid))
            continue
        if "offer" in fact:
            known(where, fact["offer"]["option"], "OPTION", option_ids)
            offered.append((where, fact["id"], fact["offer"]["option"]))
            quoted = [
                Money(Decimal(each["amount"]), each["currency"])
                for each in fact["offer"].get("prices", ())
            ]
            on_offer = int(fact["offer"]["places"])
            price = next(iter(quoted), None)
            facts.append(Offer(fact["id"], fact["offer"]["option"], on_offer, price))
            continue
        if "person" in fact:
            known(where, fact["person"], "PERSON", person_ids)
            known(where, fact["starts_from"], "PLACE", place_ids)
            if (fact["person"], StartsFrom) in stated:
                problems.append(f"{where}: another FACT already states this about {fact['person']}")
            stated.add((fact["person"], StartsFrom))
            facts.append(StartsFrom(fact["id"], fact["person"], fact["starts_from"]))
            continue
        made: Fact
        if "way" in fact:
            known(where, fact["way"], "WAY", way_ids)
            if "duration" in fact:
                exact = length(fact["duration"])
                made = Duration(fact["id"], fact["way"], exact, exact, contingent=False)
            else:
                shortest = length(fact["contingent_duration"]["shortest"])
                longest = length(fact["contingent_duration"]["longest"])
                if shortest > longest:
                    problems.append(f"{where}: the shortest duration is longer than the longest")
                made = Duration(fact["id"], fact["way"], shortest, longest, contingent=True)
            if (fact["way"], Duration) in stated:
                problems.append(f"{where}: another FACT already states this about {fact['way']}")
            stated.add((fact["way"], Duration))
            facts.append(made)
            continue
        known(where, fact["option"], "OPTION", option_ids)
        if "satisfies" in fact:
            about = fact["satisfies"]
            known(where, about["want"], "WANT", want_ids)
            if about["want"] in not_delivered:
                problems.append(f"{where}: no OPTION delivers {about['want']}")
            if (fact["option"], about["want"]) in satisfied:
                both = f"{fact['option']} and {about['want']}"
                problems.append(f"{where}: another FACT already states this about {both}")
            satisfied.add((fact["option"], about["want"]))
            facts.append(Satisfies(fact["id"], fact["option"], about["want"], int(about["degree"])))
            continue
        if "starts_at" in fact:
            made = Start(fact["id"], fact["option"], when(where, fact["starts_at"]))
        elif "starts_any_time" in fact:
            made = Start(fact["id"], fact["option"], None)
        elif "duration" in fact:
            exact = length(fact["duration"])
            made = Duration(fact["id"], fact["option"], exact, exact, contingent=False)
        elif "contingent_duration" in fact:
            shortest = length(fact["contingent_duration"]["shortest"])
            longest = length(fact["contingent_duration"]["longest"])
            if shortest > longest:
                problems.append(f"{where}: the shortest duration is longer than the longest")
            made = Duration(fact["id"], fact["option"], shortest, longest, contingent=True)
        elif "needs_right" in fact:
            made = NeedsRight(fact["id"], fact["option"], fact["needs_right"])
        else:
            made = Cutoff(fact["id"], fact["option"], length(fact["arrive_before_start"]))
        if (fact["option"], type(made)) in stated:
            problems.append(f"{where}: another FACT already states this about {fact['option']}")
        stated.add((fact["option"], type(made)))
        facts.append(made)
    # A COMPLETE set of rights and the OFFERs for its OPTION have to say the same thing.
    for where, option, open_offers in closures:
        for offer in open_offers:
            if (offer, option) not in {(id, about) for _, id, about in offered}:
                problems.append(f"{where}: {offer} is not an OFFER for {option}")
        for at, offer, about in offered:
            if about == option and offer not in open_offers:
                said = (
                    f"the rights to {option} are COMPLETE, and that FACT does not name this OFFER"
                )
                problems.append(f"{at}: {said}")

    decisions: list[Decision] = []
    capped: set[tuple[str, str]] = set()
    for index, decision in enumerate(raw["decisions"]):
        where = f"/decisions/{index}"
        claim(where, decision["id"])
        if "lock" in decision:
            known(where, decision["lock"], "OPTION", option_ids)
            for person in decision["persons"]:
                known(where, person, "PERSON", person_ids)
            decisions.append(Lock(decision["id"], decision["lock"], tuple(decision["persons"])))
            continue
        if "spend_at_most" in decision:
            source = decision["budget"]
            most = decision["spend_at_most"]
            limit = Money(Decimal(most["amount"]), most["currency"])
            if known(where, source, "BUDGET", budget_ids):
                if limit.currency not in held[source]:
                    problems.append(f"{where}: {source} holds no {limit.currency}")
                if (source, limit.currency) in capped:
                    problems.append(
                        f"{where}: another DECISION already caps {source} in {limit.currency}"
                    )
                capped.add((source, limit.currency))
            decisions.append(Cap(decision["id"], source, limit))
            continue
        if "trip_starts_at" in decision:
            kind, at = TripStart, when(where, decision["trip_starts_at"])
        else:
            kind, at = TripEnd, when(where, decision["trip_ends_at"])
        if ("the TRIP", kind) in stated:
            problems.append(f"{where}: another DECISION already states this about the TRIP")
        stated.add(("the TRIP", kind))
        if at is not None:
            decisions.append(kind(decision["id"], at))

    starts = next((each.at for each in decisions if isinstance(each, TripStart)), None)
    ends = next((each.at for each in decisions if isinstance(each, TripEnd)), None)
    if starts is not None and ends is not None and ends < starts:
        problems.append("/decisions: the TRIP ends before it starts")
    if problems:
        raise FileError(problems)
    zone = zones[0] if zones else "UTC"
    return File(
        persons,
        places,
        tuple(options),
        tuple(ways),
        tuple(wants),
        tuple(facts),
        tuple(decisions),
        zone,
        tuple(budgets),
    )


def _unwritable_characters(value: object, where: str) -> list[str]:
    """Problems for text that holds a control character, a line break or half a character.

    The schema's patterns end with ``$``. In the schema's own dialect that is the very end of the
    text, but Python also lets it match before a final line break. Refusing line breaks and
    control characters everywhere closes that gap. Half of a surrogate pair is refused because it
    cannot be written back out.
    """
    if isinstance(value, str):
        kinds = {unicodedata.category(character) for character in value}
        if kinds & {"Cc", "Zl", "Zp"}:
            return [f"{where or 'the FILE'}: {value!r} holds a control character"]
        if "Cs" in kinds:
            return [f"{where or 'the FILE'}: {value!r} holds half of a character"]
        return []
    found: list[str] = []
    if isinstance(value, dict):
        for key, inside in cast("dict[str, object]", value).items():
            found += _unwritable_characters(inside, _inside(where, key))
    elif isinstance(value, list):
        for index, inside in enumerate(cast("list[object]", value)):
            found += _unwritable_characters(inside, _inside(where, index))
    return found


def _describe(error: ValidationError, shapes: dict[str, dict[str, object]]) -> str:
    """One schema problem as 'where: what'. A record that fits no shape gets its closest miss.

    The closest miss is the one for the shape the record was meant to have: the shape whose
    required keys the record has most of. So a key that belongs to that shape is never named as
    the problem. ``shapes`` holds each shape of the schema by its name. A FACT with ``complete``
    is about travel, about a WANT or about the rights to an OPTION, and what is inside
    ``complete`` says which.
    """
    where = "".join(_inside("", part) for part in error.absolute_path) or "the FILE"
    if not error.context:
        return f"{where}: {error.message}"
    misses = list(error.context)
    written: object = error.instance
    if isinstance(written, dict):
        record = cast("dict[str, object]", written)
        names = [
            each["$ref"].rsplit("/", 1)[-1]
            for each in cast("dict[str, list[dict[str, str]]]", error.schema)["oneOf"]
        ]

        def name(miss: ValidationError) -> str:
            return names[cast("int", miss.relative_schema_path[0])]

        def fit(miss: ValidationError) -> int:
            required = cast("list[str]", shapes[name(miss)].get("required", []))
            return len(set(required) & set(record))

        best = max(fit(miss) for miss in misses)
        misses = [miss for miss in misses if fit(miss) == best]
        whole = record.get("complete")
        if isinstance(whole, dict) and list(error.absolute_path)[:1] == ["facts"]:
            keys = set(cast("dict[str, object]", whole))
            kinds = {
                "complete_set": bool(keys & {"from", "to", "leaving"}),
                "complete_for_a_want": "satisfies" in keys,
                "complete_rights": bool(keys & {"rights_to", "offers"}),
            }
            meant = [kind for kind, there in kinds.items() if there] or ["complete_set"]
            if len(meant) > 1:
                return (
                    f"{where}: a COMPLETE set is of one kind: travel, the OPTIONs that SATISFY"
                    " a WANT, or the rights to an OPTION"
                )
            misses = [miss for miss in misses if name(miss) == meant[0]] or misses
    closest = max(misses, key=lambda miss: len(miss.absolute_path))
    return f"{where}: fits no known shape; the closest miss: {closest.message}"
