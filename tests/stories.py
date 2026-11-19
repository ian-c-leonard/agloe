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


def must(id: str, *persons: str, never: Sequence[str] = ()) -> Document:
    """A WANT that is a must for these PERSONs, and a must-not for those in ``never``."""
    holders = [{"person": person, "degree": 10} for person in persons]
    holders += [{"person": person, "degree": -10} for person in never]
    return {"id": id, "name": id, "holders": holders}


def must_not(id: str, *persons: str) -> Document:
    """A WANT that is a must-not for these PERSONs."""
    return must(id, never=persons)


def starts_from(person: str, place: str) -> Document:
    """A FACT about where a PERSON starts from."""
    return {"id": f"{person}-start", "person": person, "starts_from": place}


def ends_at(place: str, *persons: str, id: str = "ending") -> Document:
    """The WANT to end the TRIP at a PLACE, as a must for these PERSONs."""
    holders = [{"person": person, "degree": 10} for person in persons]
    return {"id": id, "name": id, "itinerary": {"ends_at": place}, "holders": holders}


def trip_starts(hour: int, minute: int = 0) -> Document:
    """A DECISION about when the TRIP starts."""
    return {"id": "trip-start", "trip_starts_at": at(hour, minute)}


def trip_ends(hour: int, minute: int = 0) -> Document:
    """A DECISION about when the TRIP ends."""
    return {"id": "trip-end", "trip_ends_at": at(hour, minute)}


def every(want: str) -> Document:
    """A FACT that the FILE states every OPTION that SATISFIES this WANT."""
    return {"id": f"every-{want}", "complete": {"satisfies": want}}


def satisfies(option: str, want: str, degree: int = 10) -> Document:
    """A FACT about how fully an OPTION delivers a WANT. A degree of zero says it does not."""
    about = {"want": want, "degree": degree}
    return {"id": f"{option}-gives-{want}", "option": option, "satisfies": about}


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


def needs_no_right(option: str) -> Document:
    """A FACT that nobody needs a right to take part in an OPTION."""
    return {"id": f"{option}-open", "option": option, "needs_right": False}


def needs_right(option: str) -> Document:
    """A FACT that a PERSON can take part in an OPTION only with a right to it."""
    return {"id": f"{option}-needs-right", "option": option, "needs_right": True}


def booking(
    option: str,
    *persons: str,
    id: str | None = None,
    paid: str | None = None,
    budget: str | None = None,
    by: str | None = None,
) -> Document:
    """A BOOKING for an OPTION that covers these PERSONs.

    ``paid`` is what it paid, such as "32.00 USD", ``budget`` the BUDGET the money came from
    and ``by`` the PERSON who paid.
    """
    covers: Document = {"option": option, "covers": list(persons)}
    if paid is not None:
        amount, currency = paid.split()
        covers["paid"] = {"amount": amount, "currency": currency}
        if budget is not None:
            covers["paid"]["budget"] = budget
        if by is not None:
            covers["paid"]["by"] = by
    return {"id": id or f"{option}-booking", "booking": covers}


def offer(
    option: str, places: int, id: str | None = None, price: str | None = "10.00 USD"
) -> Document:
    """An OFFER: this many PERSONs can still buy a right to an OPTION, at this price each.

    With no price, nobody knows what a place costs.
    """
    offered: Document = {"option": option, "places": places}
    if price is not None:
        amount, currency = price.split()
        offered["prices"] = [{"amount": amount, "currency": currency}]
    return {"id": id or f"{option}-offer", "offer": offered}


def budget(id: str, *persons: str, holds: Sequence[str] = ("USD",)) -> Document:
    """A BUDGET that these PERSONs may draw on, and the currencies it holds."""
    return {"id": id, "name": id, "persons": list(persons), "currencies": list(holds)}


def every_right(option: str, *offers: str) -> Document:
    """A FACT that the rights to an OPTION are COMPLETE. It names the OFFERs that are still open."""
    whole: Document = {"rights_to": option}
    if offers:
        whole["offers"] = list(offers)
    return {"id": f"every-right-to-{option}", "complete": whole}


def trip(
    persons: list[str],
    places: list[str],
    options: list[Document],
    facts: list[Document],
    decisions: list[Document],
    ways: Sequence[Document] = (),
    wants: Sequence[Document] = (),
    tickets: bool = False,
    budgets: Sequence[Document] | None = None,
) -> File:
    """A FILE. None of its OPTIONs needs a right, unless the story is about tickets.

    After the FACTs given, one more for each OPTION says that nobody needs a right to it. With
    ``tickets``, the FILE says about rights only what ``facts`` says.

    Unless the story is about money, one BUDGET called money pays for everybody, in USD.
    ``budgets`` are the BUDGETs of a story that is.
    """
    if budgets is None:
        budgets = [budget("money", *persons)]
    stated = facts if tickets else [*facts, *(needs_no_right(option["id"]) for option in options)]
    return load(
        {
            "persons": named(*persons),
            "places": named(*places),
            "budgets": list(budgets),
            "options": options,
            "ways": list(ways),
            "wants": list(wants),
            "facts": stated,
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
