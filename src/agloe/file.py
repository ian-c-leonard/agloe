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
from functools import cache
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
_MOST_DIGITS = 9  # a whole number in a FILE has far fewer digits; a longer one stays as written


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
    """Something PERSONs want from the TRIP that an OPTION can deliver."""

    id: str
    name: str
    musts: tuple[str, ...]  # the PERSONs for whom it is a must: a DEGREE OF WANT of +10


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


type Fact = Start | Duration | Cutoff | Complete | Satisfies


@dataclass(frozen=True)
class File:
    """One TRIP as the FILE records it. Every tuple keeps the FILE's order."""

    persons: tuple[Person, ...]
    places: tuple[Place, ...]
    options: tuple[Option, ...]
    ways: tuple[Way, ...]
    wants: tuple[Want, ...]
    facts: tuple[Fact, ...]
    locks: tuple[Lock, ...]
    zone: str = "UTC"  # the time zone of the first time in the FILE; reports show times in it

    def option(self, id: str) -> Option:
        return next(option for option in self.options if option.id == id)

    def way(self, id: str) -> Way:
        return next(way for way in self.ways if way.id == id)

    def start(self, option: str) -> Start | None:
        return next((f for f in self.facts if isinstance(f, Start) and f.option == option), None)

    def duration(self, option: str) -> Duration | None:
        return next((f for f in self.facts if isinstance(f, Duration) and f.option == option), None)

    def cutoff(self, option: str) -> Cutoff | None:
        return next((f for f in self.facts if isinstance(f, Cutoff) and f.option == option), None)

    def satisfies(self, option: str, want: str) -> Satisfies | None:
        """The FACT about whether this OPTION SATISFIES this WANT, if the FILE states one."""
        for fact in self.facts:
            if isinstance(fact, Satisfies) and (fact.option, fact.want) == (option, want):
                return fact
        return None

    def without(self, record: str) -> File:
        """The same FILE with one FACT or DECISION taken out, so that what it stated is unknown."""
        return replace(
            self,
            facts=tuple(fact for fact in self.facts if fact.id != record),
            locks=tuple(lock for lock in self.locks if lock.id != record),
        )


def instant(text: str) -> int:
    """A time as whole seconds since 1970-01-01T00:00:00Z. Raises ValueError if it is not real."""
    moment = datetime.fromisoformat(text[: text.index("[")])
    return (moment - _EPOCH) // timedelta(seconds=1)


def written(moment: int, zone: str) -> str:
    """A time as a FILE writes it: date and time, offset from UTC, and time zone in brackets."""
    return f"{local(moment, zone).isoformat(timespec='seconds')}[{zone}]"


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

    def no_constants(name: str) -> object:
        raise ValueError(f"{name} is not a JSON value")

    try:
        written: object = json.loads(
            path.read_text(encoding="utf-8"),
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
    refuses it where it asks for a whole number.
    """
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
    problems = sorted(_describe(error) for error in validator.iter_errors(document))
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

    def when(where: str, text: str) -> int:
        try:
            moment = instant(text)
        except ValueError:
            problems.append(f"{where}: {text} is not a real date and time")
            return 0
        disagreement = _zone_problem(text)
        if disagreement is not None:
            problems.append(f"{where}: {disagreement}")
        zones.append(text[text.index("[") + 1 : -1])
        return moment

    persons = tuple(Person(p["id"], p["name"]) for p in raw["persons"])
    places = tuple(Place(p["id"], p["name"]) for p in raw["places"])
    for kind, records in (("persons", persons), ("places", places)):
        for index, record in enumerate(records):
            claim(f"/{kind}/{index}", record.id)
    person_ids = {person.id for person in persons}
    place_ids = {place.id for place in places}

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
        wants.append(Want(want["id"], want["name"], tuple(holders)))
    want_ids = {want.id for want in wants}

    facts: list[Fact] = []
    stated: set[tuple[str, type]] = set()
    complete: set[tuple[str | None, str | None, int, int]] = set()
    satisfied: set[tuple[str, str]] = set()
    for index, fact in enumerate(raw["facts"]):
        where = f"/facts/{index}"
        claim(where, fact["id"])
        if "complete" in fact:
            whole = fact["complete"]
            origin, destination = whole.get("from"), whole.get("to")
            for place in (origin, destination):
                if place is not None:
                    known(where, place, "PLACE", place_ids)
            if origin is not None and origin == destination:
                problems.append(f"{where}: a COMPLETE FACT needs two different PLACEs")
            earliest = when(where, whole["leaving"]["earliest"])
            latest = when(where, whole["leaving"]["latest"])
            if earliest > latest:
                problems.append(f"{where}: the span ends before it starts")
            if (origin, destination, earliest, latest) in complete:
                problems.append(f"{where}: another FACT already states this")
            complete.add((origin, destination, earliest, latest))
            facts.append(Complete(fact["id"], origin, destination, earliest, latest))
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
        else:
            made = Cutoff(fact["id"], fact["option"], length(fact["arrive_before_start"]))
        if (fact["option"], type(made)) in stated:
            problems.append(f"{where}: another FACT already states this about {fact['option']}")
        stated.add((fact["option"], type(made)))
        facts.append(made)

    locks: list[Lock] = []
    for index, decision in enumerate(raw["decisions"]):
        where = f"/decisions/{index}"
        claim(where, decision["id"])
        known(where, decision["lock"], "OPTION", option_ids)
        for person in decision["persons"]:
            known(where, person, "PERSON", person_ids)
        locks.append(Lock(decision["id"], decision["lock"], tuple(decision["persons"])))

    if problems:
        raise FileError(problems)
    zone = zones[0] if zones else "UTC"
    return File(
        persons, places, tuple(options), tuple(ways), tuple(wants), tuple(facts), tuple(locks), zone
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


def _describe(error: ValidationError) -> str:
    """One schema problem as 'where: what'. A record that fits no shape gets its closest miss."""
    where = "".join(_inside("", part) for part in error.absolute_path) or "the FILE"
    if error.context:
        closest = max(error.context, key=lambda miss: len(miss.absolute_path))
        return f"{where}: fits no known shape; the closest miss: {closest.message}"
    return f"{where}: {error.message}"
