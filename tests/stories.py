"""Small FILEs for the tests, built as the JSON documents an agent would write."""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from agloe.file import File, instant, load

EXAMPLES = Path(__file__).parent.parent / "examples"

type Document = dict[str, Any]


def at(hour: int, minute: int = 0, day: int = 15) -> str:
    """A time on the day of the stories, in Chicago."""
    return f"2027-05-{day:02d}T{hour:02d}:{minute:02d}:00-05:00[America/Chicago]"


def seconds(hour: int, minute: int = 0) -> int:
    return instant(at(hour, minute))


def named(*ids: str) -> list[Document]:
    return [{"id": id, "name": id} for id in ids]


def stays(id: str, place: str) -> Document:
    return {"id": id, "name": id, "place": place}


def moves(id: str, origin: str, destination: str) -> Document:
    return {"id": id, "name": id, "from": origin, "to": destination}


def starts_at(option: str, hour: int, minute: int = 0) -> Document:
    return {"id": f"{option}-time", "option": option, "starts_at": at(hour, minute)}


def any_time(option: str) -> Document:
    return {"id": f"{option}-time", "option": option, "starts_any_time": True}


def lasts(option: str, duration: str) -> Document:
    return {"id": f"{option}-length", "option": option, "duration": duration}


def lasts_between(option: str, shortest: str, longest: str) -> Document:
    span = {"shortest": shortest, "longest": longest}
    return {"id": f"{option}-length", "option": option, "contingent_duration": span}


def cutoff(option: str, margin: str) -> Document:
    return {"id": f"{option}-cutoff", "option": option, "arrive_before_start": margin}


def complete(origin: str | None, destination: str | None) -> Document:
    """Every way straight from one PLACE to another is listed, all day. None is every PLACE."""
    ways: Document = {"leaving": {"earliest": at(0), "latest": at(23, 59)}}
    name = "ways"
    if origin is not None:
        ways["from"] = origin
        name += f"-{origin}" if destination is not None else f"-from-{origin}"
    if destination is not None:
        ways["to"] = destination
        name += f"-{destination}" if origin is not None else f"-to-{destination}"
    return {"id": name, "complete": ways}


def lock(option: str, *persons: str) -> Document:
    return {"id": f"lock-{option}", "lock": option, "persons": list(persons)}


def way(id: str, origin: str, destination: str) -> Document:
    """A WAY in one direction."""
    return {"id": id, "name": id, "from": origin, "to": destination}


def way_between(id: str, first: str, second: str) -> Document:
    """A WAY in both directions."""
    return {"id": id, "name": id, "between": [first, second]}


def takes(way: str, duration: str) -> Document:
    return {"id": f"{way}-length", "way": way, "duration": duration}


def takes_between(way: str, shortest: str, longest: str) -> Document:
    span = {"shortest": shortest, "longest": longest}
    return {"id": f"{way}-length", "way": way, "contingent_duration": span}


def trip(
    persons: list[str],
    places: list[str],
    options: list[Document],
    facts: list[Document],
    decisions: list[Document],
    ways: Sequence[Document] = (),
) -> File:
    return load(
        {
            "persons": named(*persons),
            "places": named(*places),
            "options": options,
            "ways": list(ways),
            "facts": facts,
            "decisions": decisions,
        }
    )


def flight_home() -> Document:
    """The story in which Alex and Sam leave the Art Institute at 3:00 pm and make their flight."""
    document: Document = json.loads((EXAMPLES / "flight-home" / "works.json").read_text())
    return document


def without(document: Document, *records: str) -> Document:
    """The same FILE without these FACTs and DECISIONs."""
    kept = dict(document)
    for part in ("facts", "decisions"):
        kept[part] = [record for record in document[part] if record["id"] not in records]
    return kept
