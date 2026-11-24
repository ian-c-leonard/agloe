"""What the page is sent of a TRIP, so that it can draw it.

The page reads no FILE. The view sends what a drawing needs: the PERSONs and the PLACEs by
name, the days, and the steps with who takes part in each. All of it is read from the FILE by
the reader that the COMPILER uses, or taken from the COMPILER's report. The view sends it as
soon as the FILE is read, from the FILE alone, and once more with the report.

For a FEASIBLE TRIP the steps are the ITINERARY of the report, and each says which of its
PERSONs a LOCK names. A report on any other TRIP shows no ITINERARY. Its steps are the OPTIONs
that a LOCK names, at the times the FILE states. So they are before there is a report, and
the TRIP then says that it has none.

Each step names the FACTs and DECISIONs of the FILE that are about its OPTION or its WAY. A
report names FACTs and DECISIONs too. So the page can mark the steps that a report is about,
and judges nothing by itself.

The page is also sent the WANTs of the FILE: for whom each is a must or a must-not, the PLACE
where a WANT has its holders end the TRIP, and each OPTION that a FACT says SATISFIES the WANT
or does not, with its DEGREE OF SATISFACTION. Whether an ITINERARY SATISFIES a WANT is for the
COMPILER to say, and the page is not told.

Every time is on the clocks that the report shows times on: those of the FILE's time zone. A
time is written as those clocks show it, such as 2027-05-15T14:00:00. Each time comes with its
offset from UTC where the report gives its times with theirs, where the times sent are not all
at one offset, and where the clocks show one of them twice. The offset is written as the
report writes it.

The page is sent every OPTION of the FILE too, whether or not a LOCK names it or a plan uses
it: where it is, when the FILE says it starts, how long it takes, how early people must be
there, and whom a LOCK names for it. What the FILE does not say is sent as nothing.

The page is sent each FACT about where a PERSON starts from. A PERSON with no such FACT has
none here: nobody has said where they are before the TRIP.

The page is sent every WAY of the FILE: the PLACEs it goes between, whether a PERSON can
take it in both directions, and how long it takes. It is sent each FACT that the FILE lists
every way of some travel: from which PLACE, to which, and within which span of time.

The page is sent what the FILE says of the rights to each OPTION: whether a PERSON needs a
right to take part, each BOOKING with the PERSONs it covers and what it paid, each OFFER with
its places and the price of one, and the FACT that the FILE lists every right to the OPTION.
Who uses which right in a plan is for the COMPILER to say, and the page reads it from the
report. The page is sent the BUDGETs of the FILE: the PERSONs who may draw on each, the
currencies it holds, and each cap on what the TRIP spends from it.

The page is sent the CAPABILITIES of the FILE as well: each PERSON of whom a FACT says that
they have the CAPABILITY or do not, each OPTION of which a FACT says what it requires of the
CAPABILITY, and the FACT that the FILE states every one of its OPTIONs that requires it.
Whether the PERSONs in an OPTION meet what it requires is for the COMPILER to say.

The page is sent the OBJECTs of the FILE: where each is when the TRIP starts, each OPTION of
which a FACT says whether it requires the OBJECT, each OPTION of which a FACT says whether it
refuses the OBJECT, each OPTION of which a FACT says that it hands the OBJECT over, keeps
it, carries it or leaves it alone, and the FACTs that the FILE states every OPTION of each
kind. Where an OBJECT is in a plan is for the COMPILER to say.

Each name is sent as the report shows it. A PERSON, a PLACE, an OPTION, a WAY, a WANT, a
CAPABILITY, a BUDGET or an OBJECT whose name another of its kind has comes with its id, and a
name that could be taken for something else comes in quotes. So the page tells two apart
where the report does, in the same words.
A page shows two names alike that a report in words does not: those that differ only in how
an accent is put on a letter, in how many spaces they hold, or in characters that a page
shows nothing for. Those come with their ids too.

A day is sent as the stretch of it in which the clocks run on without a change. So most days
are one stretch, from midnight to midnight. A day on which the clocks change is two, and each
says its offset from UTC. Each step says which part of it lies in which stretch, from when to
when by the clock. So the page works out no time for itself, and two moments that the clocks
show as one time of day are never drawn as one.
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import cast

from agloe import report as reports
from agloe.answers import Answer, Report
from agloe.file import (
    Complete,
    Duration,
    File,
    Money,
    NeedsRight,
    Start,
    Unwritable,
    local,
)
from agloe.names import to_show as _names

type Trip = dict[str, object]
type _Shape = Mapping[str, type | tuple[type, ...]]

MOST_DAYS = 62  # the most stretches of days that the page is sent: it is told where the TRIP ends
_A_DAY = 24 * 60 * 60  # seconds on the clock of a day
_AN_HOUR = 60 * 60
_AT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_OFFSET = re.compile(r"UTC[+-][0-9]{1,2}(:[0-9]{2}(:[0-9]{2})?)?")
_NONE = type(None)
_NAMED: _Shape = {"id": str, "name": str}
_TRIP: _Shape = {
    "zone": str,
    "persons": list,
    "places": list,
    "starts_from": list,
    "itinerary": (bool, _NONE),
    "days": list,
    "until": (str, _NONE),
    "starts": (dict, _NONE),
    "ends": (dict, _NONE),
    "steps": list,
    "wants": list,
    "options": list,
    "ways": list,
    "complete_travel": list,
    "rights": list,
    "budgets": list,
    "capabilities": list,
    "objects": list,
}
_WAY: _Shape = {
    "id": str,
    "name": str,
    "from": str,
    "to": str,
    "both_ways": bool,
    "length": (dict, _NONE),
    "records": list,
}
_STARTS_FROM: _Shape = {"person": str, "place": str, "record": str}
_TRAVEL: _Shape = {
    "record": str,
    "from": (str, _NONE),
    "to": (str, _NONE),
    "earliest": dict,
    "latest": dict,
}
_OPTION: _Shape = {
    "id": str,
    "name": str,
    "from": str,
    "to": str,
    "start": (dict, _NONE),
    "any_time": bool,
    "length": (dict, _NONE),
    "margin": (int, _NONE),
    "locked": list,
    "records": list,
}
_LENGTH: _Shape = {"shortest": int, "longest": int, "contingent": bool}
_WANT: _Shape = {
    "id": str,
    "name": str,
    "musts": list,
    "must_nots": list,
    "ends_at": (str, _NONE),
    "complete": (str, _NONE),
    "options": list,
}
_DELIVERY: _Shape = {"option": str, "name": str, "degree": int, "record": str}
_RIGHTS: _Shape = {
    "option": str,
    "name": str,
    "needs": (dict, _NONE),
    "bookings": list,
    "offers": list,
    "complete": (dict, _NONE),
}
_NEEDS: _Shape = {"needed": bool, "record": str}
_BOOKING: _Shape = {
    "id": str,
    "covers": list,
    "objects": list,
    "names": dict,
    "paid": (dict, _NONE),
}
_PAID: _Shape = {"amount": str, "currency": str, "budget": (str, _NONE), "by": (str, _NONE)}
_BUDGET: _Shape = {"id": str, "name": str, "persons": list, "currencies": list, "caps": list}
_CAP: _Shape = {"id": str, "limit": dict}
_OFFER: _Shape = {"id": str, "places": int, "price": (dict, _NONE)}
_MONEY: _Shape = {"amount": str, "currency": str}
_ALL_RIGHTS: _Shape = {"record": str, "offers": list}
_AMOUNT = re.compile(r"[0-9]+(\.[0-9]+)?")  # an amount of money, as a FILE writes one
_OBJECT: _Shape = {
    "id": str,
    "name": str,
    "starts": (dict, _NONE),
    "requires": list,
    "refuses": list,
    "requires_complete": (str, _NONE),
    "transfers": list,
    "transfers_complete": (str, _NONE),
    "rights": list,
    "rights_complete": (str, _NONE),
    "rights_closed": list,
}
_OBJECT_CLOSED: _Shape = {"option": str, "name": str, "record": str, "called": str}
_OBJECT_STARTS: _Shape = {"person": (str, _NONE), "place": (str, _NONE), "record": str}
_OBJECT_NEED: _Shape = {"option": str, "name": str, "needed": bool, "record": str}
_OBJECT_REFUSAL: _Shape = {"option": str, "name": str, "refused": bool, "record": str}
_TRANSFER: _Shape = {"option": str, "name": str, "does": str, "record": str}
# What an OPTION does with an OBJECT.
_DOES = frozenset({"hands_over", "keeps", "carries", "nothing"})
_CAPABILITY: _Shape = {
    "id": str,
    "name": str,
    "has": list,
    "complete": (str, _NONE),
    "options": list,
}
_ABILITY: _Shape = {"person": str, "has": bool, "record": str}
_REQUIREMENT: _Shape = {"option": str, "name": str, "of": str, "record": str}
_OF = frozenset({"none", "one", "each"})  # of whom an OPTION requires a CAPABILITY
_DAY: _Shape = {"date": str, "offset": (str, _NONE), "opens": int, "closes": int}
_TIME: _Shape = {"at": str, "offset": (str, _NONE)}
_BOUND: _Shape = {**_TIME, "day": (int, _NONE), "second": (int, _NONE), "record": str}
_STEP: _Shape = {
    "option": (str, _NONE),
    "way": (str, _NONE),
    "name": (str, _NONE),
    "from": str,
    "to": str,
    "persons": list,
    "locked": list,
    "start": (dict, _NONE),
    "end": (dict, _NONE),
    "latest": (dict, _NONE),
    "parts": list,
    "records": list,
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
    """A stretch of one day in which the clocks of the FILE's time zone run on without a change.

    It runs from ``start`` up to ``end``, which is the first moment of the next stretch. At
    ``start`` the clocks show ``opens`` seconds into the day. ``offset`` is how far they are
    ahead of UTC. ``changes`` says that the clocks change as the stretch starts or as it ends.
    """

    date: date
    offset: timedelta
    start: int
    end: int
    opens: int
    changes: bool


def shown(file: File, report: Report | None = None) -> Trip | None:
    """The TRIP as a page draws it, from the FILE and from the COMPILER's report on it.

    With no report, it is the TRIP as the FILE alone gives it: the COMPILER has not reported
    yet. Its steps are then the OPTIONs that a LOCK names, and it says that it has no report.

    None where the TRIP holds a time outside the years 0001 to 9999: such a time cannot be
    written, so there is nothing true to draw.
    """
    planned = report is not None and report.answer is Answer.FEASIBLE
    steps = (
        _in_the_itinerary(file, report)
        if report is not None and planned
        else _named_by_a_lock(file)
    )
    names = _names((*file.options, *file.ways))
    people, sites = _names(file.persons, "and"), _names(file.places)
    locked: dict[str, set[str]] = {}
    for lock in file.locks:
        locked.setdefault(lock.option, set()).update(lock.persons)
    starts, ends = file.trip_start(), file.trip_end()
    # The FACTs and DECISIONs that name each OPTION or WAY, in the FILE's order.
    about: dict[str, list[str]] = {}
    for record in (*file.facts, *file.decisions):
        named: object = getattr(record, "option", None)
        if isinstance(named, str):
            about.setdefault(named, []).append(record.id)
    # Every time that the page is sent, and every moment that its days have to hold.
    times = [
        moment
        for step in steps
        for moment in (step.start, step.end, step.latest)
        if moment is not None
    ]
    times += [bound.at for bound in (starts, ends) if bound is not None]
    # The time that the FILE states for an OPTION is sent too, whether or not it is a step.
    stated = {option.id: file.start(option.id) for option in file.options}
    times += [start.at for start in stated.values() if start is not None and start.at is not None]
    # So are the two ends of each span in which the FILE lists every way of some travel.
    listed = [fact for fact in file.facts if isinstance(fact, Complete)]
    times += [moment for fact in listed for moment in (fact.earliest, fact.latest)]
    held = [
        moment
        for step in steps
        if step.start is not None
        for moment in _first_and_last(step.start, step.end)
    ]
    held += [] if starts is None else [starts.at]
    # A TRIP that takes any time ends as its last moment does. One that ends as a day starts
    # does not reach that day. Where the FILE says when the TRIP starts, that says whether it
    # takes any time. Where it does not, anything before its end does.
    closes = ends is not None and (
        any(moment < ends.at for moment in held) if starts is None else ends.at > starts.at
    )
    held += [] if ends is None else [ends.at - 1 if closes else ends.at]
    try:
        days, until = _days(file, held)
        # Each time gives its offset where the report's do, where these are not at one, and
        # where the clocks show one of them twice: only its offset says which of the two it is.
        offsets = (
            (report is not None and reports.clock_for(file, report).offsets)
            or len({local(moment, file.zone).utcoffset() for moment in times}) > 1
            or any(_comes_twice(file, moment) for moment in times)
        )

        def time(moment: int | None) -> Trip | None:
            return None if moment is None else _time(file, moment, offsets)

        return {
            "zone": file.zone,
            "persons": [{"id": each.id, "name": people[each.id]} for each in file.persons],
            "places": [{"id": each.id, "name": sites[each.id]} for each in file.places],
            # Each FACT about where a PERSON starts from, in the FILE's order of PERSONs.
            "starts_from": [
                {"person": fact.person, "place": fact.place, "record": fact.id}
                for fact in (file.starts_from(each.id) for each in file.persons)
                if fact is not None
            ],
            # Yes where the steps are the ITINERARY of the report, no where the report shows
            # none, and nothing where there is no report yet.
            "itinerary": None if report is None else planned,
            "days": [
                {
                    "date": day.date.isoformat(),
                    # A stretch with a change of the clocks at one end says its offset.
                    "offset": reports.offset_from_utc(day.offset) if day.changes else None,
                    "opens": day.opens,
                    "closes": day.opens + (day.end - day.start),
                }
                for day in days
            ],
            "until": None if until is None else until.isoformat(),
            "starts": None
            if starts is None
            else {**_bound(file, starts.at, days, False, offsets), "record": starts.id},
            "ends": None
            if ends is None
            else {**_bound(file, ends.at, days, closes, offsets), "record": ends.id},
            "steps": [
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
                    "start": time(step.start),
                    "end": time(step.end),
                    "latest": time(step.latest),
                    "parts": _parts(step, days),
                    "records": about.get(step.option or step.way or "", []),
                }
                for step in steps
            ],
            "wants": _wants(file, names),
            "options": [
                {
                    "id": option.id,
                    "name": names[option.id],
                    "from": option.origin,
                    "to": option.destination,
                    **_said_of(file, option.id, stated[option.id], time),
                    "locked": [
                        each.id for each in file.persons if each.id in locked.get(option.id, ())
                    ],
                    "records": about.get(option.id, []),
                }
                for option in file.options
            ],
            "ways": [
                {
                    "id": way.id,
                    "name": names[way.id],
                    "from": way.origin,
                    "to": way.destination,
                    "both_ways": way.both_ways,
                    "length": _length(file.duration(way.id)),
                    "records": about.get(way.id, []),
                }
                for way in file.ways
            ],
            # Each FACT that the FILE lists every OPTION and WAY that goes straight from one
            # PLACE to another and leaves within a span of time. A PLACE that the FACT leaves
            # out stands for every PLACE.
            "complete_travel": [
                {
                    "record": fact.id,
                    "from": fact.origin,
                    "to": fact.destination,
                    "earliest": time(fact.earliest),
                    "latest": time(fact.latest),
                }
                for fact in listed
            ],
            "rights": _rights(file, names),
            "budgets": _budgets(file),
            "capabilities": _capabilities(file, names),
            "objects": _objects(file, names),
        }
    except Unwritable:
        return None


def _said_of(
    file: File, option: str, stated: Start | None, time: Callable[[int | None], Trip | None]
) -> Trip:
    """What the FILE says of when an OPTION starts, how long it takes, and how early to be there.

    ``start`` is the time that the FILE states. ``any_time`` says that the FILE lets it start
    at any time, which is not a time. With neither, the FILE does not say when it starts.
    ``length`` is how long it takes. ``margin`` is how many seconds before its start people
    must be there. Each is None where the FILE is silent.
    """
    margin = file.cutoff(option)
    return {
        "start": time(None if stated is None else stated.at),
        "any_time": stated is not None and stated.at is None,
        "length": _length(file.duration(option)),
        "margin": None if margin is None else margin.margin,
    }


def _length(stated: Duration | None) -> Trip | None:
    """How long an OPTION or a WAY takes, as the FILE states it, or None where it does not.

    In seconds, from the shortest to the longest. It is ``contingent`` where the FILE states it
    as a range, in which the world decides.
    """
    if stated is None:
        return None
    return {
        "shortest": stated.shortest,
        "longest": stated.longest,
        "contingent": stated.contingent,
    }


def _wants(file: File, names: Mapping[str, str]) -> list[Trip]:
    """The WANTs of the FILE, in its order, each with what the FILE says of it.

    ``options`` holds each OPTION that a FACT says SATISFIES the WANT or does not, in the
    FILE's order of OPTIONs, with the FACT. A DEGREE OF SATISFACTION of zero says that the
    OPTION does not. ``complete`` is the FACT that the FILE states every OPTION that SATISFIES
    the WANT, where it holds one.
    """
    wants: list[Trip] = []
    called = _names(file.wants)
    for want in file.wants:
        complete = file.complete_for(want.id)
        stated = [(option, file.satisfies(option.id, want.id)) for option in file.options]
        wants.append(
            {
                "id": want.id,
                "name": called[want.id],
                # The PERSONs come in the order of the FILE.
                "musts": [each.id for each in file.persons if each.id in want.musts],
                "must_nots": [each.id for each in file.persons if each.id in want.must_nots],
                "ends_at": want.ends_at,
                "complete": None if complete is None else complete.id,
                "options": [
                    {
                        "option": option.id,
                        "name": names[option.id],
                        "degree": fact.degree,
                        "record": fact.id,
                    }
                    for option, fact in stated
                    if fact is not None
                ],
            }
        )
    return wants


def _rights(file: File, names: Mapping[str, str]) -> list[Trip]:
    """What the FILE says of the rights to its OPTIONs, in its order of OPTIONs.

    One for each OPTION of which the FILE says anything about rights, or that a FACT says
    needs a right for an OBJECT. ``needs`` is the FACT
    about whether a PERSON needs a right to take part. ``bookings`` holds each BOOKING for the
    OPTION with the PERSONs it covers, and ``offers`` each OFFER with its places and the price
    of one place, each in the FILE's order. ``complete`` is the FACT that the FILE lists every
    right to the OPTION, with the OFFERs that it names. Each is None, or empty, where the FILE
    is silent.

    A BOOKING covers PERSONs and OBJECTs, and the report names them in one list. So each
    BOOKING comes with the name to show for each of them (``names``): no PERSON and no
    OBJECT of the FILE shows the same name as another there.
    """
    needs = {fact.option: fact for fact in file.facts if isinstance(fact, NeedsRight)}
    holders = _names([*file.persons, *file.objects], "and")
    rights: list[Trip] = []
    for option in file.options:
        need, complete = needs.get(option.id), file.rights_complete(option.id)
        bookings, offers = file.bookings(option.id), file.offers(option.id)
        # An OPTION that needs a right for an OBJECT has rights to show too.
        ticketed = any(
            file.needs_right_for(option.id, thing.id) is True
            or file.rights_complete_for(option.id, thing.id) is not None
            for thing in file.objects
        )
        if need is None and complete is None and not bookings and not offers and not ticketed:
            continue
        rights.append(
            {
                "option": option.id,
                "name": names[option.id],
                "needs": None if need is None else {"needed": need.needed, "record": need.id},
                "bookings": [
                    {
                        "id": booking.id,
                        # The PERSONs come in the order of the FILE, as they do in the report.
                        "covers": [each.id for each in file.persons if each.id in booking.covers],
                        # The OBJECTs it covers, in the order of the FILE.
                        "objects": [each.id for each in file.objects if each.id in booking.objects],
                        "names": {
                            each: holders[each] for each in (*booking.covers, *booking.objects)
                        },
                        # What it paid, with the BUDGET that the money came from and the PERSON
                        # who paid, where it names them. None: the BOOKING states no payment.
                        "paid": None
                        if booking.paid is None
                        else {
                            **_money(booking.paid.money),
                            "budget": booking.paid.budget,
                            "by": booking.paid.by,
                        },
                    }
                    for booking in bookings
                ],
                "offers": [
                    {
                        "id": offer.id,
                        "places": offer.places,
                        "price": None if offer.price is None else _money(offer.price),
                    }
                    for offer in offers
                ],
                "complete": None
                if complete is None
                else {"record": complete.id, "offers": list(complete.offers)},
            }
        )
    return rights


def _objects(file: File, names: Mapping[str, str]) -> list[Trip]:
    """The OBJECTs of the FILE, in its order, each with what the FILE says of it.

    ``starts`` is the FACT about where the OBJECT is when the TRIP starts: a PERSON has it, or
    it lies at a PLACE. ``requires`` holds each OPTION of which a FACT says whether it requires
    the OBJECT, and ``refuses`` each one of which a FACT says whether it refuses it.
    ``transfers`` holds each OPTION of which a FACT says what it does with the OBJECT: it
    hands it over, keeps it, carries it, or leaves it alone. All three are in the FILE's
    order of OPTIONs, each with its FACT. ``requires_complete`` is the FACT that the FILE
    states every one of its OPTIONs that requires the OBJECT or refuses it, and
    ``transfers_complete`` the FACT that it states every OPTION that hands the OBJECT over,
    keeps it or carries it. ``rights`` holds each OPTION of which a FACT says whether it
    needs a right for the OBJECT, and ``rights_complete`` is the FACT that the FILE states
    every one of its OPTIONs that does. ``rights_closed`` holds each OPTION of which a FACT
    says that the FILE lists every right to it that covers the OBJECT, with that FACT. The
    report names the OBJECT there as a BOOKING names it, so that no PERSON shows the same
    name, and ``called`` is that name.
    """
    objects: list[Trip] = []
    called = _names(file.objects)
    among_all = _names([*file.persons, *file.objects], "and")
    for thing in file.objects:
        starts = file.object_starts(thing.id)
        needs = [(option, file.object_requirement(option.id, thing.id)) for option in file.options]
        bars = [(option, file.object_refusal(option.id, thing.id)) for option in file.options]
        does = [(option, file.action(option.id, thing.id)) for option in file.options]
        tickets = [(option, file.object_right(option.id, thing.id)) for option in file.options]
        ticketed = file.object_rights_complete(thing.id)
        closed = [
            (option, file.rights_complete_for(option.id, thing.id)) for option in file.options
        ]
        required, moved = (
            file.object_requirements_complete(thing.id),
            file.transfers_complete(thing.id),
        )
        objects.append(
            {
                "id": thing.id,
                "name": called[thing.id],
                "starts": None
                if starts is None
                else {"person": starts.person, "place": starts.place, "record": starts.id},
                "requires": [
                    {
                        "option": option.id,
                        "name": names[option.id],
                        "needed": fact.needed,
                        "record": fact.id,
                    }
                    for option, fact in needs
                    if fact is not None
                ],
                "refuses": [
                    {
                        "option": option.id,
                        "name": names[option.id],
                        "refused": fact.refused,
                        "record": fact.id,
                    }
                    for option, fact in bars
                    if fact is not None
                ],
                "requires_complete": None if required is None else required.id,
                "transfers": [
                    {
                        "option": option.id,
                        "name": names[option.id],
                        "does": fact.does,
                        "record": fact.id,
                    }
                    for option, fact in does
                    if fact is not None
                ],
                "transfers_complete": None if moved is None else moved.id,
                "rights": [
                    {
                        "option": option.id,
                        "name": names[option.id],
                        "needed": fact.needed,
                        "record": fact.id,
                    }
                    for option, fact in tickets
                    if fact is not None
                ],
                "rights_complete": None if ticketed is None else ticketed.id,
                "rights_closed": [
                    {
                        "option": option.id,
                        "name": names[option.id],
                        "record": fact.id,
                        "called": among_all[thing.id],
                    }
                    for option, fact in closed
                    if fact is not None
                ],
            }
        )
    return objects


def _money(money: Money) -> Trip:
    """An amount of money as the FILE writes it, with its currency."""
    return {"amount": str(money.amount), "currency": money.currency}


def _budgets(file: File) -> list[Trip]:
    """The BUDGETs of the FILE, in its order, each with what the FILE says of it.

    ``persons`` are those who may draw on the BUDGET for what the TRIP still has to buy, in the
    FILE's order of PERSONs. ``currencies`` are those it holds. ``caps`` holds each DECISION
    that the TRIP spends at most an amount from the BUDGET, in the FILE's order.
    """
    called = _names(file.budgets)
    return [
        {
            "id": budget.id,
            "name": called[budget.id],
            "persons": [each.id for each in file.persons if each.id in budget.persons],
            "currencies": list(budget.currencies),
            "caps": [
                {"id": cap.id, "limit": _money(cap.limit)}
                for cap in file.caps.values()
                if cap.budget == budget.id
            ],
        }
        for budget in file.budgets
    ]


def _capabilities(file: File, names: Mapping[str, str]) -> list[Trip]:
    """The CAPABILITIES of the FILE, in its order, each with what the FILE says of it.

    ``has`` holds each PERSON of whom a FACT says that they have the CAPABILITY or do not, in
    the FILE's order of PERSONs, with the FACT. ``options`` holds each OPTION of which a FACT
    says what it requires of the CAPABILITY, in the FILE's order of OPTIONs, with the FACT:
    ``of`` is "one" PERSON who takes part, "each" of them, or "none". ``complete`` is the FACT
    that the FILE states every one of its OPTIONs that requires the CAPABILITY, where it holds
    one.
    """
    capabilities: list[Trip] = []
    called = _names(file.capabilities)
    for capability in file.capabilities:
        complete = file.requires_complete(capability.id)
        able = [(person, file.ability(person.id, capability.id)) for person in file.persons]
        asked = [(option, file.requirement(option.id, capability.id)) for option in file.options]
        capabilities.append(
            {
                "id": capability.id,
                "name": called[capability.id],
                "has": [
                    {"person": person.id, "has": fact.has, "record": fact.id}
                    for person, fact in able
                    if fact is not None
                ],
                "complete": None if complete is None else complete.id,
                "options": [
                    {
                        "option": option.id,
                        "name": names[option.id],
                        "of": fact.of,
                        "record": fact.id,
                    }
                    for option, fact in asked
                    if fact is not None
                ],
            }
        )
    return capabilities


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
            most = found.start + length.longest
            latest = most if most > found.end else None
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


def _first_and_last(start: int, end: int | None) -> list[int]:
    """The first moment of a step and its last. A step that ends as a day starts is not on it."""
    return [start] if end is None or end <= start else [start, end - 1]


def _clocks(file: File, moment: int) -> tuple[date, timedelta]:
    """What the clocks of the FILE's time zone show at a moment: the date, and their offset."""
    there = local(moment, file.zone)
    return there.date(), there.utcoffset() or timedelta()


def _seconds_into_the_day(file: File, moment: int) -> int:
    """How far into its day a moment is, by the clock."""
    there = local(moment, file.zone)
    return there.hour * 3600 + there.minute * 60 + there.second


def _comes_twice(file: File, moment: int) -> bool:
    """Whether the clocks of the FILE's time zone show this time twice, as when they go back."""
    there = local(moment, file.zone)
    return there.replace(fold=1 - there.fold).utcoffset() != there.utcoffset()


def _time(file: File, moment: int, with_its_offset: bool) -> Trip:
    """A time as the clocks of the FILE's time zone show it. Raises Unwritable where none can."""
    there = local(moment, file.zone)
    return {
        "at": there.replace(tzinfo=None).isoformat(timespec="seconds"),
        "offset": reports.offset_from_utc(there.utcoffset() or timedelta())
        if with_its_offset
        else None,
    }


def _days(file: File, held: list[int]) -> tuple[list[_Day], date | None]:
    """The stretches of days that hold these moments, in order, from the first to the last.

    At most ``MOST_DAYS`` of them. Where the last moment is after those, the date it is on
    comes with them.
    """
    if not held:
        return [], None
    last = max(held)
    days: list[_Day] = []
    start = _where_the_stretch_starts(file, min(held))
    while True:
        today, offset = _clocks(file, start)
        end = _where_the_stretch_ends(file, start)
        opens = _seconds_into_the_day(file, start)
        changes = _the_clocks_change(file, start) or _the_clocks_change(file, end)
        # The first and the last day that can be written are whole days too: no clock
        # changes where the times that can be written start or end.
        first = start if _can_be_written(file, start - 1) else start - opens
        after = end if _can_be_written(file, end) else first + _A_DAY
        days.append(_Day(today, offset, first, after, 0 if first < start else opens, changes))
        if end > last:
            return days, None
        if len(days) == MOST_DAYS:
            return days, local(last, file.zone).date()
        start = end


def _can_be_written(file: File, moment: int) -> bool:
    """Whether a moment is in the years 0001 to 9999 on the clocks of the FILE's time zone."""
    try:
        local(moment, file.zone)
    except Unwritable:
        return False
    return True


def _the_clocks_change(file: File, moment: int) -> bool:
    """Whether the clocks are at another offset from UTC at this moment than just before it."""
    try:
        return _clocks(file, moment - 1)[1] != _clocks(file, moment)[1]
    except Unwritable:
        return False


def _where_the_stretch_ends(file: File, moment: int) -> int:
    """The first moment after this one at which the clocks show another date, or change.

    The clocks say when that is. A day can be shorter or longer than 24 hours, a zone can leave
    a date out, and its clocks can go back over midnight to the day before.
    """
    now = _clocks(file, moment)

    def other(at: int) -> bool:
        try:
            return _clocks(file, at) != now
        except Unwritable:  # after the last day that can be written
            return True

    # No stretch comes back within the hour in which it ends. So there is one change between
    # the last moment that is like this one and the first that is not.
    same, later = moment, moment + _AN_HOUR
    while not other(later):
        same, later = later, later + _AN_HOUR
    while later - same > 1:
        middle = (same + later) // 2
        if other(middle):
            later = middle
        else:
            same = middle
    return later


def _where_the_stretch_starts(file: File, moment: int) -> int:
    """The first moment of the stretch that this moment is in."""
    now = _clocks(file, moment)

    def other(at: int) -> bool:
        try:
            return _clocks(file, at) != now
        except Unwritable:  # before the first day that can be written
            return True

    same, earlier = moment, moment - _AN_HOUR
    while not other(earlier):
        same, earlier = earlier, earlier - _AN_HOUR
    while same - earlier > 1:
        middle = (same + earlier) // 2
        if other(middle):
            earlier = middle
        else:
            same = middle
    return same


def _parts(step: _Step, days: list[_Day]) -> list[Trip]:
    """The part of a step that lies in each stretch: from when to when by its clock.

    ``begins`` says that the part starts where the step starts, and ``ends`` that it ends where
    the step is known to end. A step with no known end has one part with no length, at its
    start. So has a step that takes no time.
    """
    if step.start is None:
        return []
    reach = step.start if step.end is None else max(step.start, step.end)
    parts: list[Trip] = []
    for index, day in enumerate(days):
        first, last = max(step.start, day.start), min(reach, day.end)
        # A step with no length is in the stretch that holds its moment, and in no other.
        on_this_day = first < last if reach > step.start else day.start <= step.start < day.end
        if on_this_day:
            parts.append(
                {
                    "day": index,
                    "from": day.opens + (first - day.start),
                    "to": day.opens + (last - day.start),
                    "begins": first == step.start,
                    "ends": step.end is not None and last == reach,
                }
            )
    return parts


def _bound(file: File, at: int, days: list[_Day], closes: bool, offsets: bool) -> Trip:
    """When the TRIP starts or ends: the time, its stretch of a day, and how far into the day.

    ``closes`` says that this is the end of a TRIP that takes any time. Such an end, at the
    moment a stretch starts, is at the end of the stretch before. The day is None where it is
    none of those that the page is sent.
    """
    for as_an_end in (True, False) if closes else (False,):
        for index, day in enumerate(days):
            inside = day.start < at <= day.end if as_an_end else day.start <= at < day.end
            if inside:
                second = day.opens + (at - day.start)
                return {**_time(file, at, offsets), "day": index, "second": second}
    return {**_time(file, at, offsets), "day": None, "second": None}


def holds(trip: object) -> bool:
    """Whether this is a TRIP as ``shown`` gives it: all that the page reads, and no more."""
    if not _fits(trip, _TRIP):
        return False
    sent = cast("dict[str, object]", trip)
    persons, places = _ids(sent["persons"]), _ids(sent["places"])
    days = _the_days(sent["days"])
    until = sent["until"]
    if (
        persons is None
        or places is None
        or days is None
        or not (until is None or _is_a_date(until))
    ):
        return False
    planned = sent["itinerary"] is True
    options = _the_options(sent["options"], persons, places)
    ways = _the_ways(sent["ways"], places)
    budgets = _the_budgets(sent["budgets"], persons)
    steps = cast("list[object]", sent["steps"])
    return (
        options is not None
        and ways is not None
        # An OPTION and a WAY never have one id: ids are unique across the FILE.
        and not options & ways
        and _are_where_persons_start_from(sent["starts_from"], persons, places)
        and _is_travel_listed_in_full(sent["complete_travel"], places)
        and all(_is_a_bound(sent[which], days) for which in ("starts", "ends"))
        and all(
            _is_a_step(step, persons, places, days, planned, until is not None) for step in steps
        )
        # Each step that is an OPTION is one of the OPTIONs of the FILE, and each that is a
        # WAY which the FILE lists is one of its WAYs.
        and all(
            (step["option"] is None or step["option"] in options)
            and (step["way"] is None or step["way"] in ways)
            for step in cast("list[dict[str, object]]", steps)
        )
        and _are_wants(sent["wants"], persons, places, options)
        and budgets is not None
        and _are_rights(sent["rights"], persons, options, budgets, _object_ids(sent["objects"]))
        and _are_capabilities(sent["capabilities"], persons, options)
        and _are_objects(sent["objects"], persons, places, options)
    )


def _the_options(
    options: object, persons: frozenset[str], places: frozenset[str]
) -> frozenset[str] | None:
    """The ids of the OPTIONs of such a TRIP, or None where these are not its OPTIONs.

    Each has an id of its own. It has a time or can start at any time, and never both.
    """
    ids: list[object] = []
    for option in cast("list[object]", options):
        if not _fits(option, _OPTION):
            return None
        said = cast("dict[str, object]", option)
        locked, records = _all_different(said["locked"]), _all_different(said["records"])
        start, length, margin = said["start"], said["length"], said["margin"]
        if (
            not cast("str", said["name"]).strip()
            or said["from"] not in places
            or said["to"] not in places
            or locked is None
            or not locked <= persons
            or records is None
            or not (start is None or (_is_a_time(start) and said["any_time"] is False))
            or not (margin is None or cast("int", margin) >= 0)
        ):
            return None
        if not _is_a_length(length):
            return None
        ids.append(said["id"])
    return _all_different(ids)


def _is_a_length(length: object) -> bool:
    """Whether this is how long an OPTION or a WAY takes, or None where the FILE does not say.

    It takes no less than no time, and no longer at its shortest than at its longest. Only a
    length that the world decides in a range has two ends that differ.
    """
    if length is None:
        return True
    if not _fits(length, _LENGTH):
        return False
    span = cast("dict[str, int]", length)
    return 0 <= span["shortest"] <= span["longest"] and (
        span["shortest"] == span["longest"] or bool(span["contingent"])
    )


def _the_ways(ways: object, places: frozenset[str]) -> frozenset[str] | None:
    """The ids of the WAYs of such a TRIP, or None where these are not its WAYs."""
    ids: list[object] = []
    for way in cast("list[object]", ways):
        if not _fits(way, _WAY):
            return None
        said = cast("dict[str, object]", way)
        if (
            not cast("str", said["name"]).strip()
            or said["from"] not in places
            or said["to"] not in places
            or _all_different(said["records"]) is None
            or not _is_a_length(said["length"])
        ):
            return None
        ids.append(said["id"])
    return _all_different(ids)


def _are_where_persons_start_from(
    starts: object, persons: frozenset[str], places: frozenset[str]
) -> bool:
    """Whether these are the FACTs of such a TRIP about where a PERSON starts from.

    Each is a FACT of its own, about a PERSON and a PLACE of the TRIP. A PERSON has one at most.
    """
    who: list[object] = []
    records: list[object] = []
    for fact in cast("list[object]", starts):
        if not _fits(fact, _STARTS_FROM):
            return False
        said = cast("dict[str, object]", fact)
        if not said["record"] or said["place"] not in places:
            return False
        who.append(said["person"])
        records.append(said["record"])
    named = _all_different(who)
    return named is not None and named <= persons and _all_different(records) is not None


def _is_travel_listed_in_full(travel: object, places: frozenset[str]) -> bool:
    """Whether these are the FACTs of such a TRIP that the FILE lists every way of some travel.

    Each is a FACT of its own. It names a PLACE of the TRIP, or none for every PLACE, at each
    end, and a span between two times.
    """
    records: list[object] = []
    for fact in cast("list[object]", travel):
        if not _fits(fact, _TRAVEL):
            return False
        said = cast("dict[str, object]", fact)
        if (
            not said["record"]
            or not all(said[end] is None or said[end] in places for end in ("from", "to"))
            or not all(_is_a_time(said[end]) for end in ("earliest", "latest"))
        ):
            return False
        records.append(said["record"])
    return _all_different(records) is not None


def _the_budgets(budgets: object, persons: frozenset[str]) -> frozenset[str] | None:
    """The ids of the BUDGETs of such a TRIP, or None where these are not its BUDGETs.

    Each has an id of its own and a name. It lists PERSONs of the TRIP, each once, and holds
    one currency at least, each once. It has one cap at most in a currency, and each cap is a
    DECISION of its own with an amount of money.
    """
    ids: list[object] = []
    caps: list[object] = []
    for budget in cast("list[object]", budgets):
        if not _fits(budget, _BUDGET):
            return None
        said = cast("dict[str, object]", budget)
        who, held = _all_different(said["persons"]), _all_different(said["currencies"])
        if (
            not cast("str", said["name"]).strip()
            or who is None
            or not who <= persons
            or not held
            or not all(currency.strip() for currency in held)
        ):
            return None
        capped: list[object] = []
        for cap in cast("list[object]", said["caps"]):
            if not _fits(cap, _CAP):
                return None
            stated = cast("dict[str, object]", cap)
            if not stated["id"] or stated["limit"] is None or not _is_money(stated["limit"]):
                return None
            caps.append(stated["id"])
            capped.append(cast("dict[str, str]", stated["limit"])["currency"])
        if _all_different(capped) is None:
            return None
        ids.append(said["id"])
    return None if _all_different(caps) is None else _all_different(ids)


def _is_a_payment(paid: object, persons: frozenset[str], budgets: frozenset[str]) -> bool:
    """Whether this is what a BOOKING paid, or None where it states no payment.

    An amount of money, with a BUDGET of the TRIP or none, and a PERSON of the TRIP or none.
    """
    if paid is None:
        return True
    if not _fits(paid, _PAID):
        return False
    said = cast("dict[str, object]", paid)
    return (
        _is_money({"amount": said["amount"], "currency": said["currency"]})
        and (said["budget"] is None or said["budget"] in budgets)
        and (said["by"] is None or said["by"] in persons)
    )


def _are_rights(
    rights: object,
    persons: frozenset[str],
    options: frozenset[str],
    budgets: frozenset[str],
    objects: frozenset[str],
) -> bool:
    """Whether this is what such a TRIP says of the rights to its OPTIONs.

    Each OPTION of the TRIP is there once at most, and each BOOKING and each OFFER once. A
    BOOKING covers PERSONs and OBJECTs of the TRIP, each once and one at least, with a name
    to show for each, and what it paid names a BUDGET and a PERSON of the TRIP, or none. An
    OFFER has one place at least, and a price that is an amount in a currency. A FACT that
    the FILE lists every right to an OPTION names OFFERs for that OPTION.
    """
    which: list[object] = []
    ids: list[object] = []
    for each in cast("list[object]", rights):
        if not _fits(each, _RIGHTS):
            return False
        said = cast("dict[str, object]", each)
        needs, complete = said["needs"], said["complete"]
        if not cast("str", said["name"]).strip():
            return False
        if needs is not None and (
            not _fits(needs, _NEEDS) or not cast("dict[str, object]", needs)["record"]
        ):
            return False
        on_offer: list[object] = []
        for booking in cast("list[object]", said["bookings"]):
            if not _fits(booking, _BOOKING):
                return False
            stated = cast("dict[str, object]", booking)
            covered, things = _all_different(stated["covers"]), _all_different(stated["objects"])
            if not stated["id"] or covered is None or things is None:
                return False
            if not (covered or things) or not covered <= persons or not things <= objects:
                return False
            named = cast("dict[str, object]", stated["names"])
            if frozenset(named) != covered | things:
                return False
            if not all(isinstance(name, str) and name.strip() for name in named.values()):
                return False
            if not _is_a_payment(stated["paid"], persons, budgets):
                return False
            ids.append(stated["id"])
        for offer in cast("list[object]", said["offers"]):
            if not _fits(offer, _OFFER):
                return False
            stated = cast("dict[str, object]", offer)
            if not stated["id"] or cast("int", stated["places"]) < 1:
                return False
            if not _is_money(stated["price"]):
                return False
            ids.append(stated["id"])
            on_offer.append(stated["id"])
        if complete is not None:
            if not _fits(complete, _ALL_RIGHTS):
                return False
            closed = cast("dict[str, object]", complete)
            named = _all_different(closed["offers"])
            if not closed["record"] or named is None or not named <= set(on_offer):
                return False
        which.append(said["option"])
    found = _all_different(which)
    return found is not None and found <= options and _all_different(ids) is not None


def _is_money(money: object) -> bool:
    """Whether this is an amount of money in a currency, or None where the FILE states none."""
    if money is None:
        return True
    if not _fits(money, _MONEY):
        return False
    said = cast("dict[str, str]", money)
    return bool(_AMOUNT.fullmatch(said["amount"])) and bool(said["currency"].strip())


def _are_objects(
    objects: object, persons: frozenset[str], places: frozenset[str], options: frozenset[str]
) -> bool:
    """Whether these are the OBJECTs of such a TRIP, each with an id of its own.

    An OBJECT starts with a PERSON of the TRIP or at a PLACE of the TRIP, and never both. It
    names each OPTION once among those that require it or do not, once among those that
    refuse it or do not, and once among those that do something with it: an OPTION of the
    TRIP, which hands it over, keeps it, carries it, or leaves it alone.
    """
    seen: set[str] = set()
    for thing in cast("list[object]", objects):
        if not _fits(thing, _OBJECT):
            return False
        said = cast("dict[str, object]", thing)
        if said["id"] in seen or not cast("str", said["name"]).strip():
            return False
        seen.add(cast("str", said["id"]))
        starts = said["starts"]
        if starts is not None:
            if not _fits(starts, _OBJECT_STARTS):
                return False
            where = cast("dict[str, object]", starts)
            person, place = where["person"], where["place"]
            if not where["record"] or (person is None) is (place is None):
                return False
            if not (person is None or person in persons) or not (place is None or place in places):
                return False
        kinds = (
            ("requires", _OBJECT_NEED),
            ("refuses", _OBJECT_REFUSAL),
            ("transfers", _TRANSFER),
            ("rights", _OBJECT_NEED),
            ("rights_closed", _OBJECT_CLOSED),
        )
        for kind, shape in kinds:
            named: list[object] = []
            for each in cast("list[object]", said[kind]):
                if not _fits(each, shape):
                    return False
                stated = cast("dict[str, object]", each)
                if not cast("str", stated["name"]).strip() or not stated["record"]:
                    return False
                if kind == "rights_closed" and not cast("str", stated["called"]).strip():
                    return False
                if kind == "transfers" and stated["does"] not in _DOES:
                    return False
                named.append(stated["option"])
            which = _all_different(named)
            if which is None or not which <= options:
                return False
    return True


def _are_capabilities(
    capabilities: object, persons: frozenset[str], options: frozenset[str]
) -> bool:
    """Whether these are the CAPABILITIES of such a TRIP, each with an id of its own.

    A CAPABILITY names each PERSON once, and each OPTION once: an OPTION of the TRIP, with
    whether it requires the CAPABILITY of one PERSON, of each, or of none.
    """
    seen: set[str] = set()
    for capability in cast("list[object]", capabilities):
        if not _fits(capability, _CAPABILITY):
            return False
        said = cast("dict[str, object]", capability)
        if said["id"] in seen or not cast("str", said["name"]).strip():
            return False
        seen.add(cast("str", said["id"]))
        able: list[object] = []
        for ability in cast("list[object]", said["has"]):
            if not _fits(ability, _ABILITY):
                return False
            able.append(cast("dict[str, object]", ability)["person"])
        asked: list[object] = []
        for requirement in cast("list[object]", said["options"]):
            if not _fits(requirement, _REQUIREMENT):
                return False
            stated = cast("dict[str, object]", requirement)
            if not cast("str", stated["name"]).strip() or stated["of"] not in _OF:
                return False
            asked.append(stated["option"])
        who, which = _all_different(able), _all_different(asked)
        if who is None or which is None or not who <= persons or not which <= options:
            return False
    return True


def _are_wants(
    wants: object, persons: frozenset[str], places: frozenset[str], options: frozenset[str]
) -> bool:
    """Whether these are the WANTs of such a TRIP, each with an id of its own.

    A WANT is a must for some of the PERSONs and a must-not for others, and for nobody both.
    Somebody holds it. No OPTION delivers a WANT about where the TRIP ends, and it is a must
    for each PERSON who holds it.
    It names each OPTION once, an OPTION of the TRIP, with a DEGREE OF SATISFACTION from 0 to 10.
    """
    seen: set[str] = set()
    for want in cast("list[object]", wants):
        if not _fits(want, _WANT):
            return False
        said = cast("dict[str, object]", want)
        holders = _all_different(
            [*cast("list[object]", said["musts"]), *_listed(said["must_nots"])]
        )
        ends_at = said["ends_at"]
        if (
            said["id"] in seen
            or not cast("str", said["name"]).strip()
            or not holders
            or not holders <= persons
            or not (
                ends_at is None
                or (ends_at in places and not said["options"] and not said["must_nots"])
            )
        ):
            return False
        seen.add(cast("str", said["id"]))
        delivered: list[object] = []
        for delivery in cast("list[object]", said["options"]):
            if not _fits(delivery, _DELIVERY):
                return False
            stated = cast("dict[str, object]", delivery)
            if (
                not cast("str", stated["name"]).strip()
                or not 0 <= cast("int", stated["degree"]) <= 10
            ):
                return False
            delivered.append(stated["option"])
        which = _all_different(delivered)
        if which is None or not which <= options:
            return False
    return True


def _listed(value: object) -> list[object]:
    """A list as it is, read as a list of anything."""
    return cast("list[object]", value)


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
        asked = kinds if isinstance(kinds, tuple) else (kinds,)
        if isinstance(held, bool) and bool not in asked:
            return False
        if not isinstance(held, kinds):
            return False
    return True


def _object_ids(objects: object) -> frozenset[str]:
    """The ids that the OBJECTs of a TRIP give themselves. ``_are_objects`` checks the rest."""
    ids: list[str] = []
    for each in cast("list[object]", objects):
        named = cast("dict[str, object]", each).get("id") if isinstance(each, dict) else None
        if isinstance(named, str):
            ids.append(named)
    return frozenset(ids)


def _ids(records: object) -> frozenset[str] | None:
    """The ids of the PERSONs or of the PLACEs, or None where the records are not such a list.

    Each has a name that is more than blank, as the format asks.
    """
    ids: list[str] = []
    for record in cast("list[object]", records):
        if not _fits(record, _NAMED):
            return None
        named = cast("dict[str, str]", record)
        if not named["name"].strip():
            return None
        ids.append(named["id"])
    return frozenset(ids) if len(set(ids)) == len(ids) else None


def _the_days(days: object) -> list[dict[str, object]] | None:
    """The stretches of days as a page is sent them, or None where they are not that.

    Each has the date of a real day, and opens and closes within the 24 hours of its clock.
    """
    found: list[dict[str, object]] = []
    for day in cast("list[object]", days):
        if not _fits(day, _DAY):
            return None
        said = cast("dict[str, object]", day)
        opens, closes = cast("int", said["opens"]), cast("int", said["closes"])
        offset = said["offset"]
        if not _is_a_date(said["date"]) or not 0 <= opens <= closes <= _A_DAY:
            return None
        if not (offset is None or _OFFSET.fullmatch(cast("str", offset))):
            return None
        found.append(said)
    return found if len(found) <= MOST_DAYS else None


def _is_a_date(written: object) -> bool:
    """Whether this is the date of a real day, written as 2027-05-15."""
    if not isinstance(written, str) or not _DATE.fullmatch(written):
        return False
    try:
        date.fromisoformat(written)
    except ValueError:
        return False
    return True


def _is_a_time(time: object) -> bool:
    """Whether this is a time of a real day, as ``shown`` writes one, with or without its offset."""
    if not _fits(time, _TIME):
        return False
    said = cast("dict[str, object]", time)
    written, offset = cast("str", said["at"]), said["offset"]
    if not _AT.fullmatch(written) or not (offset is None or _OFFSET.fullmatch(cast("str", offset))):
        return False
    try:
        datetime.strptime(written, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return False
    return True


def _is_a_bound(bound: object, days: list[dict[str, object]]) -> bool:
    """Whether this is when a TRIP starts or ends, or None for a TRIP that does not say."""
    if bound is None:
        return True
    if not _fits(bound, _BOUND):
        return False
    said = cast("dict[str, object]", bound)
    day, second = said["day"], said["second"]
    if not _is_a_time({"at": said["at"], "offset": said["offset"]}):
        return False
    if not cast("str", said["record"]):
        return False
    if isinstance(day, int) and isinstance(second, int):
        if not 0 <= day < len(days):
            return False
        return cast("int", days[day]["opens"]) <= second <= cast("int", days[day]["closes"])
    return day is None and second is None


def _is_a_step(
    step: object,
    persons: frozenset[str],
    places: frozenset[str],
    days: list[dict[str, object]],
    planned: bool,
    cut: bool,
) -> bool:
    """Whether this is a step of such a TRIP.

    A step of an ITINERARY has a time. Where there is no ITINERARY, every step is an OPTION,
    and a LOCK names each PERSON who takes part. An OPTION and a WAY that the FILE lists have
    a name, and a WAY that it does not list has none. An OPTION of an ITINERARY can have
    nobody in it: a luggage service carries the bags while everybody is somewhere else.
    """
    if not _fits(step, _STEP):
        return False
    said = cast("dict[str, object]", step)
    takers = _all_different(said["persons"])
    locked = _all_different(said["locked"])
    alone = planned and said["option"] is not None
    if takers is None or locked is None or not takers <= persons or not (takers or alone):
        return False
    if _all_different(said["records"]) is None:
        return False
    option, way, name = said["option"], said["way"], said["name"]
    start, end, latest = said["start"], said["end"], said["latest"]
    return (
        (option is None or way is None)
        and (name is None) is (option is None and way is None)
        and (name is None or bool(cast("str", name).strip()))
        and said["from"] in places
        and said["to"] in places
        and locked <= takers
        and (start is not None if planned else option is not None and locked == takers)
        and (start is None or _is_a_time(start))
        and (end is None or (start is not None and _is_a_time(end)))
        and (latest is None or (end is not None and _is_a_time(latest)))
        and _are_parts(cast("list[object]", said["parts"]), days, start, end is not None, cut)
    )


def _all_different(ids: object) -> frozenset[str] | None:
    """These ids as a set, or None where they are not a list of ids that are all different."""
    listed = cast("list[object]", ids)
    if not all(isinstance(each, str) for each in listed):
        return None
    found = frozenset(cast("list[str]", listed))
    return found if len(found) == len(listed) else None


def _are_parts(
    parts: list[object],
    days: list[dict[str, object]],
    start: object,
    has_an_end: bool,
    cut: bool,
) -> bool:
    """Whether these are the parts of one step, each in a later stretch than the one before.

    A step with a time has a part, unless days are left out. Its first part begins the step,
    on the date and at the time of day of its start. Only its last part can end it. A step
    with no known end has one part, with no length. A step with no time has no part.
    """
    if start is None:
        return not parts
    if not parts:
        return cut
    before = -1
    for position, part in enumerate(parts):
        if not _fits(part, _PART):
            return False
        said = cast("dict[str, int]", part)
        if not before < said["day"] < len(days):
            return False
        day = days[said["day"]]
        opens, closes = cast("int", day["opens"]), cast("int", day["closes"])
        if not opens <= said["from"] <= said["to"] <= closes:
            return False
        if said["begins"] is not (position == 0) or (said["ends"] and position < len(parts) - 1):
            return False
        before = said["day"]
    first = cast("dict[str, int]", parts[0])
    at = datetime.strptime(cast("dict[str, str]", start)["at"], "%Y-%m-%dT%H:%M:%S")
    on_its_day = days[first["day"]]["date"] == at.date().isoformat()
    at_its_time = first["from"] == at.hour * 3600 + at.minute * 60 + at.second
    with_no_end = has_an_end or (
        len(parts) == 1 and first["from"] == first["to"] and not first["ends"]
    )
    return on_its_day and at_its_time and with_no_end
