"""What the page is sent of a TRIP, so that it can draw it.

The page reads no FILE. With each report, the view sends what a drawing needs: the PERSONs and
the PLACEs by name, the steps with who takes part in each, and each time on the clocks that the
report shows times on. All of it is read from the FILE by the reader that the COMPILER uses, or
taken from the COMPILER's report.

For a FEASIBLE TRIP the steps are the ITINERARY of the report, and each says which of its
PERSONs a LOCK names. A report on any other TRIP shows no ITINERARY. Its steps are the OPTIONs
that a LOCK names, at the times the FILE states.

A time is written as the clocks of the FILE's time zone show it, such as 2027-05-15T14:00:00.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import cast

from agloe.answers import Answer, Report
from agloe.file import File, Unwritable, local

type Trip = dict[str, object]
type _Shape = Mapping[str, type | tuple[type, ...]]

_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}")
_NAMED: _Shape = {"id": str, "name": str}
_TRIP: _Shape = {"zone": str, "persons": list, "places": list, "itinerary": bool, "steps": list}
_STEP: _Shape = {
    "option": (str, type(None)),
    "way": (str, type(None)),
    "name": (str, type(None)),
    "from": str,
    "to": str,
    "persons": list,
    "start": (str, type(None)),
    "end": (str, type(None)),
    "locked": list,
}


@dataclass(frozen=True)
class _Step:
    """One step to draw: an OPTION, or a WAY that PERSONs take. A WAY may have no id.

    ``start`` is None for an OPTION that the FILE gives no time. ``end`` is None where nobody
    knows how long the step takes.
    """

    option: str | None
    way: str | None
    origin: str
    destination: str
    persons: tuple[str, ...]
    start: int | None
    end: int | None


def shown(file: File, report: Report) -> Trip | None:
    """The TRIP as a page draws it, from the FILE and from the COMPILER's report on it.

    None where the TRIP holds a time outside the years 0001 to 9999: such a time cannot be
    written, so there is nothing true to draw.
    """
    planned = report.answer is Answer.FEASIBLE
    steps = _in_the_itinerary(report) if planned else _named_by_a_lock(file)
    names = {each.id: each.name for each in (*file.options, *file.ways)}
    locked: dict[str, set[str]] = {}
    for lock in file.locks:
        locked.setdefault(lock.option, set()).update(lock.persons)
    try:
        sent: list[Trip] = [
            {
                "option": step.option,
                "way": step.way,
                "name": names.get(step.option or step.way or ""),
                "from": step.origin,
                "to": step.destination,
                # The PERSONs come in the order of the FILE, as they do in the report.
                "persons": [each.id for each in file.persons if each.id in step.persons],
                "start": None if step.start is None else _on_the_clock(file, step.start),
                "end": None if step.end is None else _on_the_clock(file, step.end),
                "locked": [
                    each.id
                    for each in file.persons
                    if each.id in step.persons and each.id in locked.get(step.option or "", ())
                ],
            }
            for step in steps
        ]
    except Unwritable:
        return None
    return {
        "zone": file.zone,
        "persons": [{"id": each.id, "name": each.name} for each in file.persons],
        "places": [{"id": each.id, "name": each.name} for each in file.places],
        "itinerary": planned,
        "steps": sent,
    }


def _in_the_itinerary(report: Report) -> list[_Step]:
    """The steps of the report's ITINERARY, in its order.

    PERSONs who take a WAY together are one step. The report in words names them on one line.
    """
    steps: list[_Step] = []
    for found in report.itinerary:
        way = None if found.option is not None else found.way
        step = _Step(
            found.option,
            way,
            found.origin,
            found.destination,
            found.persons,
            found.start,
            found.end,
        )
        last = steps[-1] if steps else None
        together = (
            last is not None
            and step.option is None
            and replace(last, persons=step.persons) == step
            and not set(last.persons) & set(step.persons)
        )
        if last is not None and together:
            steps[-1] = replace(last, persons=(*last.persons, *step.persons))
        else:
            steps.append(step)
    return steps


def _named_by_a_lock(file: File) -> list[_Step]:
    """The OPTIONs that a LOCK names, each with the PERSONs that its LOCKs name.

    Each is at the time the FILE states, and ends after the least time it can take, as a step
    of an ITINERARY does. Those with a time come first, in the order of their starts. Those
    with none follow. OPTIONs that are level keep the FILE's order.
    """
    persons: dict[str, set[str]] = {}
    for lock in file.locks:
        persons.setdefault(lock.option, set()).update(lock.persons)
    steps: list[_Step] = []
    for option in file.options:
        if option.id not in persons:
            continue
        stated, length = file.start(option.id), file.duration(option.id)
        start = None if stated is None else stated.at
        end = None if start is None or length is None else start + length.shortest
        takers = tuple(persons[option.id])
        steps.append(_Step(option.id, None, option.origin, option.destination, takers, start, end))
    return sorted(steps, key=lambda step: (step.start is None, step.start or 0))


def _on_the_clock(file: File, moment: int) -> str:
    """A time as the clocks of the FILE's time zone show it. Raises Unwritable where none can."""
    return local(moment, file.zone).replace(tzinfo=None).isoformat(timespec="seconds")


def holds(trip: object) -> bool:
    """Whether this is a TRIP as ``shown`` gives it: all that the page reads, and no more."""
    if not _fits(trip, _TRIP):
        return False
    sent = cast("dict[str, object]", trip)
    persons, places = _ids(sent["persons"]), _ids(sent["places"])
    if persons is None or places is None:
        return False
    planned = sent["itinerary"] is True
    return all(
        _is_a_step(step, persons, places, planned) for step in cast("list[object]", sent["steps"])
    )


def _fits(value: object, shape: _Shape) -> bool:
    """Whether a value is a record with exactly these parts, each of its kind."""
    if not isinstance(value, dict):
        return False
    record = cast("dict[object, object]", value)
    if set(record) != set(shape):
        return False
    for name, kinds in shape.items():
        held = record[name]
        # In Python a yes or no is a number too. Here it is one only where a yes or no is asked.
        if isinstance(held, bool) and kinds is not bool:
            return False
        if not isinstance(held, kinds):
            return False
    return True


def _ids(records: object) -> frozenset[str] | None:
    """The ids of the PERSONs or of the PLACEs, or None where the records are not such a list."""
    ids: list[str] = []
    for record in cast("list[object]", records):
        if not _fits(record, _NAMED):
            return None
        ids.append(cast("dict[str, str]", record)["id"])
    return frozenset(ids) if len(set(ids)) == len(ids) else None


def _is_a_step(
    step: object, persons: frozenset[str], places: frozenset[str], planned: bool
) -> bool:
    """Whether this is a step of such a TRIP.

    A step of an ITINERARY has a time. Where there is no ITINERARY, every step is an OPTION,
    and a LOCK names each PERSON who takes part.
    """
    if not _fits(step, _STEP):
        return False
    said = cast("dict[str, object]", step)
    takers = _all_different(said["persons"])
    locked = _all_different(said["locked"])
    if takers is None or locked is None or not takers or not takers <= persons:
        return False
    start, end = said["start"], said["end"]
    return (
        (said["option"] is None or said["way"] is None)
        and said["from"] in places
        and said["to"] in places
        and locked <= takers
        and (start is not None if planned else said["option"] is not None and locked == takers)
        and (start is None or _is_a_time(start))
        and (end is None or (start is not None and _is_a_time(end)))
    )


def _all_different(ids: object) -> frozenset[str] | None:
    """These ids as a set, or None where they are not a list of ids that are all different."""
    listed = cast("list[object]", ids)
    if not all(isinstance(each, str) for each in listed):
        return None
    found = frozenset(cast("list[str]", listed))
    return found if len(found) == len(listed) else None


def _is_a_time(written: object) -> bool:
    """Whether this is a time of a real day, written as ``shown`` writes one."""
    if not isinstance(written, str) or not _TIME.fullmatch(written):
        return False
    try:
        datetime.strptime(written, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return False
    return True
