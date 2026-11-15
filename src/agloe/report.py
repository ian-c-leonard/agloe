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

from agloe.answers import Answer, Missing, Report
from agloe.file import (
    Complete,
    Cutoff,
    Duration,
    File,
    Lock,
    Option,
    Person,
    Place,
    Start,
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
        out["itinerary"] = [
            {
                ("way" if step.option is None else "option"): step.option or step.way,
                "persons": list(step.persons),
                "start": written(step.start, file.zone),
                "end": None if step.end is None else written(step.end, file.zone),
            }
            for step in report.itinerary
        ]
        out["relies_on"] = list(report.relies_on)
        out["robust"] = report.robust
    if report.at_worst:
        out["at_worst"] = [_broken_as_json(file, report, found) for found in report.at_worst]
    if report.conflict:
        out["conflict"] = list(report.conflict)
    if report.missing:
        out["missing"] = [
            [_missing_as_json(needed) for needed in enough] for enough in report.missing
        ]
    return out


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
    else:
        out["from"], out["to"] = unknown.origin, unknown.destination
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
    """The times that these FACTs state."""
    facts = {fact.id: fact for fact in file.facts}
    times: list[int] = []
    for record in records:
        found = facts.get(record)
        if isinstance(found, Start) and found.at is not None:
            times.append(found.at)
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
            "These FACTs and DECISIONs clash. Each one is needed for the clash."
            f" Times are in {file.zone}.",
            *(f"  {record}: {_record(file, clock, record)}" for record in report.conflict),
        ]
    else:
        lines = ["UNDETERMINED: the FILE does not say enough to tell.", ""]
        cases = [
            " and ".join(_wanted(file, needed, len(enough) == 1) for needed in enough)
            for enough in report.missing
        ]
        if len(cases) == 1:
            lines.append(f"The trip works if {cases[0]}.")
        else:
            lines.append("The trip works in any of these cases:")
            lines += [
                f"  {number}. {case[0].upper()}{case[1:]}." for number, case in enumerate(cases, 1)
            ]
        if any(
            needed.unknown.what == "other ways" for enough in report.missing for needed in enough
        ):
            lines += ["", "Other WAYs help only if they can be taken when the plan needs them."]
    return "\n".join(lines) + "\n"


def _feasible(file: File, clock: _Clock, report: Report) -> list[str]:
    lines = [
        "FEASIBLE: this trip works."
        if report.robust
        else "FEASIBLE, with a WARNING: this trip can work, but no plan is sure to hold."
    ]
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
    if report.relies_on:
        lines += ["", "The plan relies on these FACTs and DECISIONs:"]
        lines += [f"  {record}: {_record(file, clock, record)}" for record in report.relies_on]
    return lines


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
    """What the plan would break at the longest durations, in words, for each line of the plan.

    A line is known by its number, counting from zero. PERSONs who share a line and are in the
    same trouble are named together. Everything a plan can break happens at one of its steps,
    so a finding with no line is a fault in this program, and it stops here.
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
    for (number, constraint, late), persons in together.items():
        who = _people(file, tuple(persons))
        if constraint is Constraint.ARRIVAL and late is not None:
            mark = f"{who} would be {_span(late)} too late for this."
        elif constraint is Constraint.PLACE and late is not None:
            mark = f"{who} would still be busy for {_span(late)} when this starts."
        elif constraint is Constraint.PLACE:
            mark = f"{who} would not be free when this starts."
        else:
            mark = f'This would break the rule "{constraint.value}" for {who}.'
        marks.setdefault(number, []).append(mark)
    return marks


def _wanted(file: File, needed: Missing, alone: bool) -> str:
    """What one unknown FACT would have to be, in words. ``alone`` means nothing else is needed."""
    unknown, limit = needed.unknown, needed.at_most
    if unknown.what == "start":
        return f"{_name(file, unknown.option)} can start at any time"
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
    """One FACT or DECISION in words."""
    found = next(each for each in (*file.facts, *file.locks) if each.id == record)
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


def _names(records: Sequence[Person | Place | Option | Way]) -> dict[str, str]:
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


def _people(file: File, persons: tuple[str, ...]) -> str:
    """Names joined as a sentence would: Alex, Sam and Jo."""
    shown = _names(file.persons)
    names = [shown[person.id] for person in file.persons if person.id in persons]
    if len(names) < 2:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


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
