"""A Report as JSON and in plain words.

The JSON has the shape of the expected results beside the examples. The words are for a person:
the plan with its times, or the FACTs and DECISIONs that clash, or what the FILE would have to
say for the TRIP to work. Times are shown on the clocks of the first time zone the FILE names,
and the words name that zone. Where those clocks change during the times shown, each time also
gives its offset from UTC.

What a plan would break at the longest durations is printed under the line of the plan it is
about. So the words never have to describe which step they mean.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from itertools import groupby
from math import comb

from agloe.answers import Answer, Missing, Report
from agloe.file import (
    Booking,
    Complete,
    CompleteFor,
    CompleteRights,
    Cutoff,
    Duration,
    File,
    Lock,
    NeedsRight,
    Offer,
    Option,
    Person,
    Place,
    Satisfies,
    Start,
    StartsFrom,
    TripEnd,
    TripStart,
    Want,
    Way,
    length_written,
    local,
    written,
)
from agloe.reference import Broken, Constraint, Itinerary, Step

_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def as_json(file: File, report: Report) -> dict[str, object]:
    """The Report in the shape of the expected results beside the examples."""
    out: dict[str, object] = {"answer": report.answer.value}
    if report.answer is Answer.FEASIBLE:
        rights: dict[str | None, dict[str, str]] = {}
        for cover in report.rights:
            rights.setdefault(cover.option, {})[cover.person] = cover.by
        out["itinerary"] = [
            {
                ("way" if step.option is None else "option"): step.option or step.way,
                "persons": list(step.persons),
                "start": written(step.start, file.zone),
                "end": None if step.end is None else written(step.end, file.zone),
                **({"rights": rights[step.option]} if step.option in rights else {}),
            }
            for step in report.itinerary
        ]
        out["relies_on"] = list(report.relies_on)
        out["robust"] = report.robust
        if _to_buy(report):
            out["to_buy"] = [
                {"option": option, "offer": offer, "persons": persons}
                for (option, offer), persons in _to_buy(report).items()
            ]
    if report.at_worst:
        out["at_worst"] = [_broken_as_json(file, report, found) for found in report.at_worst]
    if report.conflict:
        out["conflict"] = list(report.conflict)
    if report.missing:
        out["missing"] = [
            [_missing_as_json(needed) for needed in enough] for enough in report.missing
        ]
    return out


def _to_buy(report: Report) -> dict[tuple[str, str], list[str]]:
    """The PERSONs who still have to buy a right, for each OPTION and each OFFER it is from."""
    buyers: dict[tuple[str, str], list[str]] = {}
    for cover in report.rights:
        if cover.to_buy:
            buyers.setdefault((cover.option, cover.by), []).append(cover.person)
    return buyers


def _broken_as_json(file: File, report: Report, found: Broken) -> dict[str, object]:
    """One broken CONSTRAINT. At a WAY, ``step`` is the position of that step in the itinerary."""
    out: dict[str, object] = {"constraint": found.constraint.value}
    if found.step is None:
        out["option"] = found.option
    else:
        step = report.itinerary[found.step]
        out["step"] = found.step
        out["way"], out["from"], out["to"] = step.way, step.origin, step.destination
        out["start"] = written(step.start, file.zone)
    out["persons"] = list(found.persons)
    out["late"] = None if found.late is None else length_written(found.late)
    return out


def _missing_as_json(needed: Missing) -> dict[str, object]:
    unknown = needed.unknown
    out: dict[str, object] = {"what": unknown.what}
    if unknown.option is not None:
        out["option"] = unknown.option
    elif unknown.way is not None:
        out["way"] = unknown.way
    elif unknown.origin is not None:
        out["from"], out["to"] = unknown.origin, unknown.destination
    if unknown.want is not None:
        out["want"] = unknown.want
    if unknown.person is not None:
        out["person"] = unknown.person
    out["at_most"] = None if needed.at_most is None else length_written(needed.at_most)
    return out


@dataclass(frozen=True)
class _Clock:
    """How times are put in words: on the clocks of one time zone.

    With ``offsets``, each time also gives its offset from UTC, because the clocks change during
    the times shown and a time of day alone could mean two moments.
    """

    zone: str
    offsets: bool

    def day(self, moment: int) -> date:
        return local(moment, self.zone).date()

    def day_name(self, moment: int) -> str:
        """A day: Saturday 15 May 2027."""
        there = local(moment, self.zone)
        return f"{_DAYS[there.weekday()]} {there.day} {_MONTHS[there.month - 1]} {there.year}"

    def time(self, moment: int, day: date | None = None) -> str:
        """A time of day: 2:00 pm. The date is added when it is not the day given.

        The year is added too when it is not that day's year.
        """
        there = local(moment, self.zone)
        seconds = f":{there.second:02d}" if there.second else ""
        half = "am" if there.hour < 12 else "pm"
        clock = f"{there.hour % 12 or 12}:{there.minute:02d}{seconds} {half}"
        if self.offsets:
            clock += f" ({_offset(there.utcoffset() or timedelta())})"
        if day is None or there.date() == day:
            return clock
        year = "" if there.year == day.year else f" {there.year}"
        return f"{clock} on {there.day} {_MONTHS[there.month - 1]}{year}"

    def moment(self, moment: int) -> str:
        """A time with its day: 2:00 pm on Saturday 15 May 2027."""
        return f"{self.time(moment)} on {self.day_name(moment)}"


def _offset(ahead: timedelta) -> str:
    """An offset from UTC, to the second where it has seconds: UTC-5, UTC+5:30, UTC+0:09:21."""
    seconds = round(ahead.total_seconds())
    hours, rest = divmod(abs(seconds), 3600)
    minutes, left = divmod(rest, 60)
    shown = f"UTC{'-' if seconds < 0 else '+'}{hours}"
    if minutes or left:
        shown += f":{minutes:02d}"
    if left:
        shown += f":{left:02d}"
    return shown


def _times_stated(file: File, records: tuple[str, ...]) -> list[int]:
    """The times that these FACTs and DECISIONs state."""
    stated = {each.id: each for each in (*file.facts, *file.decisions)}
    times: list[int] = []
    for record in records:
        found = stated.get(record)
        if isinstance(found, (Start, TripStart, TripEnd)):
            times += [] if found.at is None else [found.at]
        elif isinstance(found, Complete):
            times += [found.earliest, found.latest]
    return times


def _clock_for(file: File, report: Report) -> _Clock:
    """The clock for one report: with offsets if the times it shows have more than one."""
    moments = [step.start for step in report.itinerary]
    moments += [step.end for step in report.itinerary if step.end is not None]
    moments += _times_stated(file, (*report.relies_on, *report.conflict))
    offsets = {local(moment, file.zone).utcoffset() for moment in moments}
    return _Clock(file.zone, len(offsets) > 1)


def as_text(file: File, report: Report) -> str:
    """The Report in plain words, ending with a line break."""
    clock = _clock_for(file, report)
    if report.answer is Answer.FEASIBLE:
        lines = _feasible(file, clock, report)
    elif report.answer is Answer.INFEASIBLE:
        lines = [
            "INFEASIBLE: this trip cannot work.",
            "",
            f"These {_kinds(file, report.conflict)} rule out every plan by themselves. Take"
            " any one away and they no longer do. A FACT that is taken away leaves what it"
            f" said unknown. Times are in {file.zone}.",
            *(f"  {record}: {_record(file, clock, record)}" for record in report.conflict),
        ]
    else:
        lines = ["UNDETERMINED: the FILE does not say enough to tell.", ""]
        cases = [_case(file, enough) for enough in report.missing]
        any_of_them = _any_of_them(file, report.missing)
        if any_of_them is not None:
            cases = [any_of_them]
        if len(cases) == 1:
            lines.append(f"The trip works if {cases[0]}.")
        else:
            lines.append("The trip works in any of these cases:")
            lines += [
                f"  {number}. {case[0].upper()}{case[1:]}." for number, case in enumerate(cases, 1)
            ]
        asked = [needed.unknown for enough in report.missing for needed in enough]
        kinds = {unknown.what for unknown in asked}
        # A BOOKING can stand in for that answer, for an OPTION whose rights are not COMPLETE.
        might_be_booked = {
            unknown.option
            for unknown in asked
            if unknown.what == "needs no right"
            and file.rights_complete(unknown.option or "") is None
        }
        if might_be_booked:
            names = [_name(file, each.id) for each in file.options if each.id in might_be_booked]
            lines += [
                "",
                f"If {_listed(names, 'or')} does need a right, a BOOKING for each PERSON who"
                " takes part in it is enough instead.",
            ]
        if "other ways" in kinds:
            helps = (
                "Other WAYs help only if they can be taken when the plan needs them, with a"
                " right where they need one"
            )
            lines += ["", f"{helps}."]
            if any(want.must_nots for want in file.wants):
                lines[-1] = (
                    f"{helps}, and only if they SATISFY nothing that is a must-not for a PERSON"
                    " who takes them."
                )
        if "another option" in kinds:
            lines += [
                "",
                "Another OPTION helps only if the PERSON it is for can take part in it and still"
                " do everything else the trip asks of them.",
            ]
            most = max(
                sum(needed.unknown.what == "another option" for needed in enough)
                for enough in report.missing
            )
            if most > 1:
                lines[-1] += " One OPTION can be found for several PERSONs and several WANTs."
    return "\n".join(lines) + "\n"


def _feasible(file: File, clock: _Clock, report: Report) -> list[str]:
    to_buy = _to_buy(report)
    if not report.robust:
        lines = ["FEASIBLE, with a WARNING: this trip can work, but no plan is sure to hold."]
    elif to_buy:
        lines = ["FEASIBLE, with a WARNING: this trip works, but not everything is booked yet."]
    else:
        lines = ["FEASIBLE: this trip works."]
    marks = _marks(file, report)
    day = None
    for number, (step, _) in enumerate(_lines(report.itinerary)):
        if clock.day(step.start) != day:
            day = clock.day(step.start)
            lines += ["", f"{clock.day_name(step.start)} (times in {file.zone})"]
        end = "an unknown time" if step.end is None else clock.time(step.end, day)
        who = _people(file, step.persons)
        what = _name(file, step.option or step.way)
        lines.append(f"  {clock.time(step.start)} to {end}: {what}, {who}")
        lines += [f"    ! {mark}" for mark in marks.get(number, [])]
    if not report.itinerary:
        lines += ["", "Nobody has to do anything."]
    relied_on = [fact for fact in file.facts if fact.id in report.relies_on]
    if not report.robust:
        lines += [
            "",
            "WARNING: no plan is sure to hold if the uncertain parts take their longest."
            ' Each line marked "!" says what would go wrong at the step above it.',
        ]
    elif any(isinstance(fact, Duration) and fact.contingent for fact in relied_on):
        lines += [
            "",
            "This plan holds however long the uncertain parts take, within the ranges the FILE"
            " states.",
        ]
    if to_buy:
        lines += [
            "",
            "WARNING: not everything is booked yet."
            ' A line marked "!" that names an OFFER says who still has to buy a right.'
            " Only a BOOKING secures one.",
        ]
    if report.relies_on:
        lines += ["", f"The plan relies on these {_kinds(file, report.relies_on)}:"]
        lines += [f"  {record}: {_record(file, clock, record)}" for record in report.relies_on]
    return lines


def _kinds(file: File, records: Sequence[str]) -> str:
    """The kinds of record in a list, and no kind that is not in it: FACTs, WANTs and DECISIONs."""
    kinds = (("FACTs", file.facts), ("WANTs", file.wants), ("DECISIONs", file.decisions))
    return _listed([kind for kind, held in kinds if any(each.id in records for each in held)])


def together(itinerary: Itinerary) -> list[Step]:
    """The steps as a plan shows them, in the same order.

    Steps next to each other that differ only in the PERSON share a line: those PERSONs take the
    same WAY at the same time. Nothing is moved and nothing is left out. So what each PERSON
    does, and in what order, reads the same as in the ITINERARY.
    """
    return [step for step, _ in _lines(itinerary)]


def _lines(itinerary: Itinerary) -> list[tuple[Step, list[int]]]:
    """Each line of the plan: the step it shows, and the positions of the steps it stands for."""
    lines: list[tuple[Step, list[int]]] = []
    for position, step in enumerate(itinerary):
        if lines and step.option is None:
            shown, positions = lines[-1]
            alike = replace(shown, persons=step.persons) == step
            if alike and not set(shown.persons) & set(step.persons):
                both = replace(shown, persons=(*shown.persons, *step.persons))
                lines[-1] = (both, [*positions, position])
                continue
        lines.append((step, [position]))
    return lines


def _marks(file: File, report: Report) -> dict[int, list[str]]:
    """The WARNINGs about a plan, in words, for each line of the plan.

    First who still has to buy a right to an OPTION, and from which OFFER. Then what the plan
    would break at the longest durations.

    A line is known by its number, counting from zero. PERSONs who share a line and are in the
    same trouble are named together. Longer durations break only CONSTRAINTs about time, and
    those are broken at one of the plan's steps. So a finding with no line is a fault in this
    program, and it stops here.
    """
    lines = _lines(report.itinerary)
    line_of = {
        position: number for number, (_, positions) in enumerate(lines) for position in positions
    }
    line_of_option: dict[str | None, int] = {
        step.option: number for number, (step, _) in enumerate(lines) if step.option is not None
    }
    together: dict[tuple[int, Constraint, int | None], list[str]] = {}
    for found in report.at_worst:
        number = line_of[found.step] if found.step is not None else line_of_option[found.option]
        together.setdefault((number, found.constraint, found.late), []).extend(found.persons)
    marks: dict[int, list[str]] = {}
    for (option, offer), buyers in _to_buy(report).items():
        have = "has" if len(buyers) == 1 else "have"
        if_needed = "" if file.needs_right(option) else " if it needs one"
        mark = f"{_people(file, tuple(buyers))} still {have} to buy a right to this{if_needed}"
        marks.setdefault(line_of_option[option], []).append(f"{mark}, from {offer}.")
    for (number, constraint, late), persons in together.items():
        who = _people(file, tuple(persons))
        if constraint is Constraint.ARRIVAL and late is not None:
            mark = f"{who} would be {_span(late)} too late for this."
        elif constraint is Constraint.PLACE and late is not None:
            mark = f"{who} would still be busy for {_span(late)} when this starts."
        elif constraint is Constraint.PLACE:
            mark = f"{who} would not be free when this starts."
        elif constraint is Constraint.WITHIN and late is not None:
            mark = f"This would end {_span(late)} after the trip ends."
        else:
            mark = f'This would break the rule "{constraint.value}" for {who}.'
        marks.setdefault(number, []).append(mark)
    return marks


def _case(file: File, enough: Sequence[Missing]) -> str:
    """One set of unknown FACTs that would be enough, in words.

    PERSONs who need another OPTION for the same WANT are named together, as "each of". The
    condition is one for each PERSON: whether one OPTION or several meet it is left open. The
    OPTIONs that have to need no right are named together where they follow one another in the
    set. So are the PERSONs who need a right to one OPTION. Nothing else changes the order.
    """
    parts: list[str] = []
    for_whom: dict[str | None, list[str]] = {}
    for _, run in groupby(enough, key=_named_with):
        group = list(run)
        unknown = group[0].unknown
        if unknown.what == "another option":
            for_whom.setdefault(unknown.want, []).append(unknown.person or "")
        elif unknown.what == "needs no right":
            names = [_name(file, needed.unknown.option) for needed in group]
            parts.append(f"nobody needs a right to take part in {_listed(names, 'or')}")
        elif unknown.what == "another right":
            each = "each of " if len(group) > 1 else ""
            who = _people(file, tuple(needed.unknown.person or "" for needed in group))
            parts.append(f"a right to {_name(file, unknown.option)} is found for {each}{who}")
        else:
            parts.append(_wanted(file, group[0], len(enough) == 1))
    for want, persons in for_whom.items():
        who = _people(file, tuple(persons))
        each = "each of " if len(persons) > 1 else ""
        parts.append(f"another OPTION that SATISFIES {_want(file, want)} is found for {each}{who}")
    return " and ".join(parts)


def _any_of_them(file: File, missing: Sequence[Sequence[Missing]]) -> str | None:
    """Sets that differ only in which PERSONs get a right to one OPTION, in one sentence.

    Where the places on OFFER cover some of the PERSONs who need a right, any of them can take
    a place. The sets then name every way to pick the others. One sentence says the same: a
    right is found for so many of them. None where the sets are not of that kind.
    """
    asked = [[needed.unknown for needed in enough] for enough in missing]
    shared = [needed for needed in missing[0] if all(needed.unknown in each for each in asked)]
    kept = {needed.unknown for needed in shared}
    varying = [[unknown for unknown in each if unknown not in kept] for each in asked]
    about = {(unknown.what, unknown.option) for each in varying for unknown in each}
    if len(missing) < 2 or len(about) != 1 or about != {("another right", varying[0][0].option)}:
        return None
    group = {unknown.person or "" for each in varying for unknown in each}
    picked = len(varying[0])
    if any(len(each) != picked for each in varying) or len(missing) != comb(len(group), picked):
        return None
    count = "one" if picked == 1 else str(picked)
    who = _people(file, tuple(group))
    found = f"a right to {_name(file, varying[0][0].option)} is found for {count} of {who}"
    return " and ".join([*([_case(file, shared)] if shared else []), found])


def _named_with(needed: Missing) -> object:
    """What an unknown FACT shares with those a report names it with. Otherwise it stands alone."""
    unknown = needed.unknown
    if unknown.what == "needs no right":
        return unknown.what
    if unknown.what == "another right":
        return (unknown.what, unknown.option)
    return needed


def _wanted(file: File, needed: Missing, alone: bool) -> str:
    """What one unknown FACT would have to be, in words. ``alone`` means nothing else is needed."""
    unknown, limit = needed.unknown, needed.at_most
    if unknown.what == "start":
        return f"{_name(file, unknown.option)} can start at any time"
    if unknown.what == "satisfies":
        return f"{_name(file, unknown.option)} SATISFIES {_want(file, unknown.want)}"
    if unknown.what == "does not satisfy":
        return f"{_name(file, unknown.option)} does not SATISFY {_want(file, unknown.want)}"
    if unknown.what == "other ways":
        places = _names(file.places)
        there = f"there are other WAYs from {places[unknown.origin or '']} to "
        there += places[unknown.destination or ""]
        if limit is not None:
            return f"{there} that take {_at_most(limit)}"
        return there if alone else f"{there} that are quick enough"
    name = _name(file, unknown.option or unknown.way)
    if unknown.what == "duration":
        if limit is not None:
            return f"{name} takes {_at_most(limit)}"
        return f"the FILE says how long {name} takes" if alone else f"{name} is quick enough"
    place = _starts_at(file, unknown.option)
    if limit == 0:
        return f"nobody has to be at {place} before {name} starts"
    if limit is not None:
        return f"people must be at {place} {_span(limit)} or less before {name} starts"
    if alone:
        return f"the FILE says how long before {name} starts people must be at {place}"
    return f"people need not be at {place} long before {name} starts"


def _record(file: File, clock: _Clock, record: str) -> str:
    """One FACT, WANT or DECISION in words."""
    records = (*file.facts, *file.wants, *file.decisions)
    found = next(each for each in records if each.id == record)
    if isinstance(found, Want):
        said = [
            f"a {kind} for {_people(file, persons)}"
            for kind, persons in (("must", found.musts), ("must-not", found.must_nots))
            if persons
        ]
        asked = f"{_want(file, found.id)} is {' and '.join(said)}"
        if found.ends_at is None:
            return asked
        return f"{asked}: to end the TRIP at {_names(file.places)[found.ends_at]}"
    if isinstance(found, Complete):
        places = _names(file.places)
        first = clock.day(found.earliest)
        span = f"{clock.moment(found.earliest)} and {clock.time(found.latest, first)}"
        if found.origin is None and found.destination is None:
            ways = "every way from one PLACE straight to another"
        elif found.origin is None:
            ways = f"every way straight to {places[found.destination or '']}"
        elif found.destination is None:
            ways = f"every way straight from {places[found.origin]}"
        else:
            ways = f"every way straight from {places[found.origin]} to {places[found.destination]}"
        return f"{ways} that leaves between {span} is listed"
    if isinstance(found, TripStart):
        return f"the TRIP starts at {clock.moment(found.at)}"
    if isinstance(found, TripEnd):
        return f"the TRIP ends at {clock.moment(found.at)}"
    if isinstance(found, CompleteFor):
        which = [
            _name(file, fact.option)
            for fact in file.facts
            if isinstance(fact, Satisfies) and fact.want == found.want and fact.degree > 0
        ]
        said = _listed(which) if which else "there is none"
        return f"the FILE states every OPTION that SATISFIES {_want(file, found.want)}: {said}"
    if isinstance(found, StartsFrom):
        place = _names(file.places)[found.place]
        return f"{_people(file, (found.person,))} starts from {place}"
    name = _name(file, found.option)
    if isinstance(found, Lock):
        verb = "takes" if len(found.persons) == 1 else "take"
        return f"{_people(file, found.persons)} {verb} part in {name}"
    if isinstance(found, Start):
        if found.at is None:
            return f"{name} can start at any time"
        return f"{name} starts at {clock.moment(found.at)}"
    if isinstance(found, Duration):
        if found.contingent:
            return f"{name} takes between {_span(found.shortest)} and {_span(found.longest)}"
        return f"{name} takes {_span(found.shortest)}"
    if isinstance(found, Satisfies):
        if not found.degree:
            return f"{name} does not SATISFY {_want(file, found.want)}"
        return f"{name} SATISFIES {_want(file, found.want)}, {found.degree} out of 10"
    if isinstance(found, NeedsRight):
        who = "people need" if found.needed else "nobody needs"
        return f"{who} a right to take part in {name}"
    if isinstance(found, Booking):
        return f"a BOOKING for {name} covers {_people(file, found.covers)}"
    if isinstance(found, Offer):
        places = "1 place" if found.places == 1 else f"{found.places} places"
        return f"an OFFER has {places} for {name} that can still be bought"
    if isinstance(found, CompleteRights):
        closed = "nobody on the trip holds another or can get one"
        if found.offers:
            closed += f", except from {_listed(found.offers)}"
        return f"the FILE lists every right to {name}: {closed}"
    return _cutoff(file, name, found)


def _cutoff(file: File, name: str, found: Cutoff) -> str:
    place = _starts_at(file, found.option)
    if not found.margin:
        return f"nobody has to be at {place} before {name} starts"
    return f"people must be at {place} {_span(found.margin)} before {name} starts"


def _starts_at(file: File, option: str | None) -> str:
    """The name of the PLACE where an OPTION starts."""
    origin = next(each.origin for each in file.options if each.id == option)
    return _names(file.places)[origin]


def _names(records: Sequence[Person | Place | Option | Way | Want]) -> dict[str, str]:
    """The name to show for each record, so that no two records show the same.

    A record whose name another record has shows its id too. If two would still show the same,
    every record shows its id: no two ids are the same.
    """
    shared = Counter(record.name for record in records)
    shown = {
        record.id: record.name if shared[record.name] == 1 else f"{record.name} ({record.id})"
        for record in records
    }
    if len(set(shown.values())) < len(shown):
        return {record.id: f"{record.name} ({record.id})" for record in records}
    return shown


def _name(file: File, id: str | None) -> str:
    """The name of an OPTION or a WAY."""
    return _names((*file.options, *file.ways)).get(id or "", "another WAY")


def _want(file: File, id: str | None) -> str:
    """The name of a WANT."""
    return _names(file.wants)[id or ""]


def _people(file: File, persons: tuple[str, ...]) -> str:
    """Names joined as a sentence would: Alex, Sam and Jo."""
    shown = _names(file.persons)
    return _listed([shown[person.id] for person in file.persons if person.id in persons])


def _listed(names: Sequence[str], last: str = "and") -> str:
    """Names joined as a sentence would: one, two and three."""
    if len(names) < 2:
        return "".join(names)
    return f"{', '.join(names[:-1])} {last} {names[-1]}"


def _at_most(seconds: int) -> str:
    """The most a length of time can be: 45 min or less. Nothing is less than no time."""
    return f"{_span(seconds)} or less" if seconds else "no time"


def _span(seconds: int) -> str:
    """A length of time: 45 min, 1 h, 2 h 30 min."""
    hours, rest = divmod(seconds, 3600)
    minutes, left = divmod(rest, 60)
    parts = [
        f"{amount} {unit}"
        for amount, unit in ((hours, "h"), (minutes, "min"), (left, "s"))
        if amount
    ]
    return " ".join(parts) or "no time"
