"""Reading a FILE: its structure, its references and its exact values.

The schema in ``schema/file.schema.json`` is the source of truth for a FILE's shape, and
``file_types`` is generated from it. This module refuses anything the schema or the checks below
do not accept, and repairs nothing. What it accepts becomes exact values: a time is a whole number
of seconds since 1970-01-01T00:00:00Z, and a length of time is a whole number of seconds.
"""

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

if TYPE_CHECKING:
    from agloe import file_types as shape

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_LENGTH = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


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
class Start:
    """A FACT: when an OPTION can start."""

    id: str
    option: str
    at: int | None  # None: at any time the planners choose


@dataclass(frozen=True)
class Duration:
    """A FACT: how long an OPTION takes. CONTINGENT means the world decides within the range."""

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
    """A FACT: the FILE lists every OPTION that gets a PERSON from one PLACE to another."""

    id: str
    origin: str
    destination: str
    earliest: int  # the span of leaving times the FACT covers
    latest: int


@dataclass(frozen=True)
class Lock:
    """A DECISION: the TRIP includes this OPTION, and these PERSONs take part."""

    id: str
    option: str
    persons: tuple[str, ...]


type Fact = Start | Duration | Cutoff | Complete


@dataclass(frozen=True)
class File:
    """One TRIP as the FILE records it. Every tuple keeps the FILE's order."""

    persons: tuple[Person, ...]
    places: tuple[Place, ...]
    options: tuple[Option, ...]
    facts: tuple[Fact, ...]
    locks: tuple[Lock, ...]

    def option(self, id: str) -> Option:
        return next(option for option in self.options if option.id == id)

    def start(self, option: str) -> Start | None:
        return next((f for f in self.facts if isinstance(f, Start) and f.option == option), None)

    def duration(self, option: str) -> Duration | None:
        return next((f for f in self.facts if isinstance(f, Duration) and f.option == option), None)

    def cutoff(self, option: str) -> Cutoff | None:
        return next((f for f in self.facts if isinstance(f, Cutoff) and f.option == option), None)

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


def length(text: str) -> int:
    """A length of time as whole seconds."""
    parts = _LENGTH.fullmatch(text)
    if parts is None:
        raise ValueError(text)
    hours, minutes, seconds = (int(part or 0) for part in parts.groups())
    return hours * 3600 + minutes * 60 + seconds


def read(path: Path) -> File:
    """Read a FILE from disk. Raises FileError if it is not JSON or does not follow the format."""

    def no_repeats(pairs: list[tuple[str, object]]) -> dict[str, object]:
        keys = [key for key, _ in pairs]
        repeated = sorted({key for key in keys if keys.count(key) > 1})
        if repeated:
            shown = ", ".join(f"{json.dumps(key)}: {json.dumps(value)}" for key, value in pairs)
            raise ValueError(
                f"an object states {', '.join(repeated)} more than once: {{{shown[:120]}}}"
            )
        return dict(pairs)

    def no_constants(name: str) -> object:
        raise ValueError(f"{name} is not a JSON value")

    try:
        document: object = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=no_repeats,
            parse_constant=no_constants,
        )
    except ValueError as problem:
        raise FileError([f"not readable as JSON: {problem}"]) from problem
    return load(document)


def load(document: object) -> File:
    """Turn a parsed JSON document into a FILE. Raises FileError if it breaks the format."""
    schema = json.loads(resources.files("agloe").joinpath("schema/file.schema.json").read_text())
    validator = cast("_Validator", Draft202012Validator(schema))
    problems = sorted(_describe(error) for error in validator.iter_errors(document))
    problems += _control_characters(document, "")
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
            problems.append(f"{where}: {id} is not a {kind} in this FILE")
        return id in ids

    def when(where: str, text: str) -> int:
        try:
            return instant(text)
        except ValueError:
            problems.append(f"{where}: {text} is not a real date and time")
            return 0

    persons = tuple(Person(p["id"], p["name"]) for p in raw["persons"])
    places = tuple(Place(p["id"], p["name"]) for p in raw["places"])
    for kind, records in (("persons", persons), ("places", places)):
        for index, record in enumerate(records):
            claim(f"{kind}/{index}", record.id)
    person_ids = {person.id for person in persons}
    place_ids = {place.id for place in places}

    options: list[Option] = []
    for index, option in enumerate(raw["options"]):
        where = f"options/{index}"
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

    facts: list[Fact] = []
    stated: set[tuple[str, type]] = set()
    complete: set[tuple[str, str, int, int]] = set()
    for index, fact in enumerate(raw["facts"]):
        where = f"facts/{index}"
        claim(where, fact["id"])
        if "complete" in fact:
            ways = fact["complete"]
            known(where, ways["from"], "PLACE", place_ids)
            known(where, ways["to"], "PLACE", place_ids)
            if ways["from"] == ways["to"]:
                problems.append(f"{where}: a COMPLETE FACT needs two different PLACEs")
            earliest = when(where, ways["leaving"]["earliest"])
            latest = when(where, ways["leaving"]["latest"])
            if earliest > latest:
                problems.append(f"{where}: the span ends before it starts")
            if (ways["from"], ways["to"], earliest, latest) in complete:
                problems.append(f"{where}: another FACT already states this")
            complete.add((ways["from"], ways["to"], earliest, latest))
            facts.append(Complete(fact["id"], ways["from"], ways["to"], earliest, latest))
            continue
        known(where, fact["option"], "OPTION", option_ids)
        made: Fact
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
        where = f"decisions/{index}"
        claim(where, decision["id"])
        known(where, decision["lock"], "OPTION", option_ids)
        for person in decision["persons"]:
            known(where, person, "PERSON", person_ids)
        locks.append(Lock(decision["id"], decision["lock"], tuple(decision["persons"])))

    if problems:
        raise FileError(problems)
    return File(persons, places, tuple(options), tuple(facts), tuple(locks))


def _control_characters(value: object, where: str) -> list[str]:
    """Problems for text that holds a line break or another control character.

    The schema's patterns end with ``$``. In the schema's own dialect that is the very end of the
    text, but Python also lets it match before a final line break. Refusing control characters
    everywhere closes that gap.
    """
    if isinstance(value, str):
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            return [f"{where or 'the FILE'}: {value!r} holds a control character"]
        return []
    found: list[str] = []
    if isinstance(value, dict):
        for key, inside in cast("dict[str, object]", value).items():
            found += _control_characters(inside, f"{where}/{key}".lstrip("/"))
    elif isinstance(value, list):
        for index, inside in enumerate(cast("list[object]", value)):
            found += _control_characters(inside, f"{where}/{index}".lstrip("/"))
    return found


def _describe(error: ValidationError) -> str:
    """One schema problem as 'where: what'. A record that fits no shape gets its closest miss."""
    where = "/".join(str(part) for part in error.absolute_path) or "the FILE"
    if error.context:
        closest = max(error.context, key=lambda miss: len(miss.absolute_path))
        return f"{where}: fits no known shape; the closest miss: {closest.message}"
    return f"{where}: {error.message}"
