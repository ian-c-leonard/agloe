"""What the page is sent of a TRIP, so that it can draw it.

The page reads no FILE. With each report, the view sends what a drawing needs: the PERSONs and
the PLACEs by name, the days, and the steps with who takes part in each. All of it is read from
the FILE by the reader that the COMPILER uses, or taken from the COMPILER's report.

For a FEASIBLE TRIP the steps are the ITINERARY of the report, and each says which of its
PERSONs a LOCK names. A report on any other TRIP shows no ITINERARY. Its steps are the OPTIONs
that a LOCK names, at the times the FILE states.

Every time is on the clocks that the report shows times on: those of the FILE's time zone. A
time is written as those clocks show it, such as 2027-05-15T14:00:00. The days are the days of
those clocks, and each step says which part of it lies on which day. So the page works out no
time for itself, and a night on which the clocks change is drawn as that zone had it.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import cast

from agloe import report as reports
from agloe.answers import Answer, Report
from agloe.file import File, Unwritable, local

type Trip = dict[str, object]
type _Shape = Mapping[str, type | tuple[type, ...]]

MOST_DAYS = 62  # the most days that the page is sent: it is told how many more there are
_A_DAY = 24 * 60 * 60  # seconds on the clock of a day
_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_OR_NONE = (str, type(None))
_NAMED: _Shape = {"id": str, "name": str}
_TRIP: _Shape = {
    "zone": str,
    "persons": list,
    "places": list,
    "itinerary": bool,
    "days": list,
    "left_out": int,
    "starts": (dict, type(None)),
    "ends": (dict, type(None)),
    "steps": list,
}
_BOUND: _Shape = {"at": str, "day": (int, type(None)), "second": (int, type(None))}
_STEP: _Shape = {
    "option": _OR_NONE,
    "way": _OR_NONE,
    "name": _OR_NONE,
    "from": str,
    "to": str,
    "persons": list,
    "locked": list,
    "start": _OR_NONE,
    "end": _OR_NONE,
    "latest": _OR_NONE,
    "parts": list,
}
_PART: _Shape = {"day": int, "from": int, "to": int, "begins": bool, "ends": bool}


@dataclass(frozen=True)
class _Step:
    """One step to draw: an OPTION, or a WAY that PERSONs take. A WAY may have no id.

    ``start`` is None for an OPTION that the FILE gives no time. ``end`` is None where nobody
    knows how long the step takes. ``latest`` is when the step ends if it takes the longest
    that the FILE says it can, where that is later than ``end``.
    """

    option: str | None
    way: str | None
    origin: str
    destination: str
    persons: tuple[str, ...]
    start: int | None
    end: int | None
    latest: int | None


@dataclass(frozen=True)
class _Day:
    """One day on the clocks of the FILE's time zone, from one moment up to another.

    The first day of a TRIP starts at the first moment that anything is sent of. Every other
    day starts at its first moment, and each ends at the first moment of the day after.
    """

    date: date
    start: int
    end: int


def shown(file: File, report: Report) -> Trip | None:
    """The TRIP as a page draws it, from the FILE and from the COMPILER's report on it.

    None where the TRIP holds a time outside the years 0001 to 9999: such a time cannot be
    written, so there is nothing true to draw.
    """
    planned = report.answer is Answer.FEASIBLE
    steps = _in_the_itinerary(file, report) if planned else _named_by_a_lock(file)
    names = {each.id: each.name for each in (*file.options, *file.ways)}
    locked: dict[str, set[str]] = {}
    for lock in file.locks:
        locked.setdefault(lock.option, set()).update(lock.persons)
    starts, ends = file.trip_start(), file.trip_end()
    try:
        days, left_out = _days(file, steps)
        sent: list[Trip] = [
            {
                "option": step.option,
                "way": step.way,
                "name": names.get(step.option or step.way or ""),
                "from": step.origin,
                "to": step.destination,
                # The PERSONs come in the order of the FILE, as they do in the report.
                "persons": [each.id for each in file.persons if each.id in step.persons],
                "locked": [
                    each.id
                    for each in file.persons
                    if each.id in step.persons and each.id in locked.get(step.option or "", ())
                ],
                "start": None if step.start is None else _on_the_clock(file, step.start),
                "end": None if step.end is None else _on_the_clock(file, step.end),
                "latest": None if step.latest is None else _on_the_clock(file, step.latest),
                "parts": _parts(file, step, days),
            }
            for step in steps
        ]
        return {
            "zone": file.zone,
            "persons": [{"id": each.id, "name": each.name} for each in file.persons],
            "places": [{"id": each.id, "name": each.name} for each in file.places],
            "itinerary": planned,
            "days": [day.date.isoformat() for day in days],
            "left_out": left_out,
            "starts": None if starts is None else _bound(file, starts.at, days, last=False),
            "ends": None if ends is None else _bound(file, ends.at, days, last=True),
            "steps": sent,
        }
    except Unwritable:
        return None


def _in_the_itinerary(file: File, report: Report) -> list[_Step]:
    """The steps of the report's ITINERARY, as the report in words shows them, in its order.

    PERSONs who take a WAY together are one step. Where the FILE gives a duration as a range,
    a plan ends the step after the least time or after the most. The step says how late it can
    end, where that is later than the plan has it end.
    """
    steps: list[_Step] = []
    for found in reports.together(report.itinerary):
        way = None if found.option is not None else found.way
        length = file.duration(found.option or way or "")
        latest = None
        if length is not None and found.end is not None:
            latest = (
                found.start + length.longest if found.start + length.longest > found.end else None
            )
        steps.append(
            _Step(
                found.option,
                way,
                found.origin,
                found.destination,
                found.persons,
                found.start,
                found.end,
                latest,
            )
        )
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
        end = latest = None
        if start is not None and length is not None:
            end = start + length.shortest
            latest = start + length.longest if length.longest > length.shortest else None
        takers = tuple(persons[option.id])
        steps.append(
            _Step(option.id, None, option.origin, option.destination, takers, start, end, latest)
        )
    return sorted(steps, key=lambda step: (step.start is None, step.start or 0))


def _on_the_clock(file: File, moment: int) -> str:
    """A time as the clocks of the FILE's time zone show it. Raises Unwritable where none can."""
    return local(moment, file.zone).replace(tzinfo=None).isoformat(timespec="seconds")


def _seconds_into_the_day(file: File, moment: int) -> int:
    """How far into its day a moment is, by the clock."""
    there = local(moment, file.zone)
    return there.hour * 3600 + there.minute * 60 + there.second


def _days(file: File, steps: list[_Step]) -> tuple[list[_Day], int]:
    """The days to draw, in order, and how many days after those the TRIP still reaches.

    The days run from the first moment of any step, or of the TRIP, to the last. A step that
    ends as a day starts does not reach that day, and neither does a TRIP that ends then.
    """
    moments: list[int] = []
    for step in steps:
        if step.start is not None:
            moments.append(step.start)
            if step.end is not None and step.end > step.start:
                moments.append(step.end - 1)
    starts, ends = file.trip_start(), file.trip_end()
    if starts is not None:
        moments.append(starts.at)
    if ends is not None:
        moments.append(ends.at - 1)
    if not moments:
        return [], 0
    last = max(moments)
    days: list[_Day] = []
    moment = min(moments)
    while True:
        today = local(moment, file.zone).date()
        after = _the_day_after(file, moment, today)
        days.append(_Day(today, moment, after))
        if after > last:
            return days, 0
        if len(days) == MOST_DAYS:
            return days, (local(last, file.zone).date() - today).days
        moment = after


def _the_day_after(file: File, moment: int, today: date) -> int:
    """The first moment after this one at which the clocks show a later date than today's.

    The clocks say when that is. A day can be shorter or longer than 24 hours where they
    change, and a zone can leave a date out altogether.
    """

    def later(at: int) -> bool:
        try:
            return local(at, file.zone).date() > today
        except Unwritable:  # after the last day that can be written
            return True

    early, late = moment, moment + 3 * _A_DAY
    while late - early > 1:
        middle = (early + late) // 2
        if later(middle):
            late = middle
        else:
            early = middle
    return late


def _parts(file: File, step: _Step, days: list[_Day]) -> list[Trip]:
    """The part of a step that lies on each day: from when to when by the clock of that day.

    A part that runs to the end of its day ends at 24 hours. ``begins`` says that the part
    starts where the step starts, and ``ends`` that it ends where the step is known to end.
    A step with no known end has one part with no length, at its start.

    Where the clocks go back, a part can end at an earlier time of day than it starts at. It
    is then as long as it takes, so that it is not lost.
    """
    if step.start is None:
        return []
    reach = step.start if step.end is None else max(step.start, step.end)
    parts: list[Trip] = []
    for index, day in enumerate(days):
        first, last = max(step.start, day.start), min(reach, day.end)
        # A step with no length is on the day that holds its moment, and on no other.
        on_this_day = first < last if reach > step.start else day.start <= step.start < day.end
        if not on_this_day:
            continue
        start = _seconds_into_the_day(file, first)
        end = _A_DAY if last == day.end else _seconds_into_the_day(file, last)
        if end <= start and last > first:
            end = min(start + (last - first), _A_DAY)
        parts.append(
            {
                "day": index,
                "from": start,
                "to": end,
                "begins": first == step.start,
                "ends": step.end is not None and last == reach,
            }
        )
    return parts


def _bound(file: File, at: int, days: list[_Day], last: bool) -> Trip:
    """When the TRIP starts, or ends where ``last``: the time, its day, and how far into it.

    A TRIP that ends as a day starts ends at 24 hours of the day before. The day is None where
    it is none of the days that the page is sent.
    """
    for index, day in enumerate(days):
        inside = day.start < at <= day.end if last else day.start <= at < day.end
        if inside:
            second = _A_DAY if at == day.end else _seconds_into_the_day(file, at)
            return {"at": _on_the_clock(file, at), "day": index, "second": second}
    return {"at": _on_the_clock(file, at), "day": None, "second": None}


def holds(trip: object) -> bool:
    """Whether this is a TRIP as ``shown`` gives it: all that the page reads, and no more."""
    if not _fits(trip, _TRIP):
        return False
    sent = cast("dict[str, object]", trip)
    persons, places = _ids(sent["persons"]), _ids(sent["places"])
    days = cast("list[object]", sent["days"])
    if persons is None or places is None or not _are_days(days):
        return False
    planned = sent["itinerary"] is True
    return (
        cast("int", sent["left_out"]) >= 0
        and all(_is_a_bound(sent[which], len(days)) for which in ("starts", "ends"))
        and all(
            _is_a_step(step, persons, places, len(days), planned)
            for step in cast("list[object]", sent["steps"])
        )
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


def _are_days(days: list[object]) -> bool:
    """Whether these are dates of real days, each later than the one before, and not too many."""
    dates: list[str] = []
    for day in days:
        if not isinstance(day, str) or not _DATE.fullmatch(day):
            return False
        try:
            date.fromisoformat(day)
        except ValueError:
            return False
        dates.append(day)
    in_order = all(dates[at] < dates[at + 1] for at in range(len(dates) - 1))
    return len(dates) <= MOST_DAYS and in_order


def _is_a_bound(bound: object, days: int) -> bool:
    """Whether this is when a TRIP starts or ends, or None for a TRIP that does not say."""
    if bound is None:
        return True
    if not _fits(bound, _BOUND):
        return False
    said = cast("dict[str, object]", bound)
    day, second = said["day"], said["second"]
    if not _is_a_time(said["at"]):
        return False
    if isinstance(day, int) and isinstance(second, int):
        return 0 <= day < days and 0 <= second <= _A_DAY
    return day is None and second is None


def _is_a_step(
    step: object, persons: frozenset[str], places: frozenset[str], days: int, planned: bool
) -> bool:
    """Whether this is a step of such a TRIP.

    A step of an ITINERARY has a time. Where there is no ITINERARY, every step is an OPTION,
    and a LOCK names each PERSON who takes part. An OPTION and a WAY that the FILE lists have
    a name, and a WAY that it does not list has none.
    """
    if not _fits(step, _STEP):
        return False
    said = cast("dict[str, object]", step)
    takers = _all_different(said["persons"])
    locked = _all_different(said["locked"])
    if takers is None or locked is None or not takers or not takers <= persons:
        return False
    option, way = said["option"], said["way"]
    start, end, latest = said["start"], said["end"], said["latest"]
    return (
        (option is None or way is None)
        and (said["name"] is None) is (option is None and way is None)
        and said["from"] in places
        and said["to"] in places
        and locked <= takers
        and (start is not None if planned else option is not None and locked == takers)
        and (start is None or _is_a_time(start))
        and (end is None or (start is not None and _is_a_time(end)))
        and (latest is None or (end is not None and _is_a_time(latest)))
        and _are_parts(cast("list[object]", said["parts"]), days, start is not None)
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


def _are_parts(parts: list[object], days: int, timed: bool) -> bool:
    """Whether these are the parts of one step, each on a later day than the one before.

    Only a step with a time has parts. Only its first part can begin where the step starts,
    and only its last can end where the step ends.
    """
    if parts and not timed:
        return False
    before = -1
    for position, part in enumerate(parts):
        if not _fits(part, _PART):
            return False
        said = cast("dict[str, int]", part)
        if not before < said["day"] < days or not 0 <= said["from"] <= said["to"] <= _A_DAY:
            return False
        if (said["begins"] and position > 0) or (said["ends"] and position < len(parts) - 1):
            return False
        before = said["day"]
    return True
