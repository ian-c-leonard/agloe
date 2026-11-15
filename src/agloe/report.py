"""A Report as JSON and in plain words.

The JSON has the shape of the expected results beside the examples. The words are for a person:
the plan with its times, or the FACTs and DECISIONs that clash, or what the FILE would have to
say for the TRIP to work. Times are shown on the clocks of the first time zone the FILE names.
"""

from agloe.file import (
    Complete,
    Cutoff,
    Duration,
    File,
    Lock,
    Start,
    length_written,
    local,
    written,
)
from agloe.reference import Answer, Broken, Constraint, Missing, Report

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
        out["at_worst"] = [
            {
                "constraint": found.constraint.value,
                "option": found.option,
                "persons": list(found.persons),
                "late": None if found.late is None else length_written(found.late),
            }
            for found in report.at_worst
        ]
    if report.conflict:
        out["conflict"] = list(report.conflict)
    if report.missing:
        out["missing"] = [
            [_missing_as_json(needed) for needed in enough] for enough in report.missing
        ]
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


def as_text(file: File, report: Report) -> str:
    """The Report in plain words, ending with a line break."""
    if report.answer is Answer.FEASIBLE:
        lines = _feasible(file, report)
    elif report.answer is Answer.INFEASIBLE:
        lines = [
            "INFEASIBLE: this trip cannot work.",
            "",
            "These FACTs and DECISIONs clash. Each one is needed for the clash.",
            *(f"  {record}: {_record(file, record)}" for record in report.conflict),
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
    return "\n".join(lines) + "\n"


def _feasible(file: File, report: Report) -> list[str]:
    lines = [
        "FEASIBLE: this trip works."
        if report.robust
        else "FEASIBLE, with a WARNING: this trip works, but only if the uncertain parts go well."
    ]
    day = None
    for step in report.itinerary:
        start = local(step.start, file.zone)
        if start.date() != day:
            day = start.date()
            name = f"{_DAYS[start.weekday()]} {start.day} {_MONTHS[start.month - 1]} {start.year}"
            lines += ["", f"{name} (times in {file.zone})"]
        end = "an unknown time" if step.end is None else _clock(file, step.end, start.date())
        who = _people(file, step.persons)
        what = _name(file, step.option or step.way)
        lines.append(f"  {_clock(file, step.start)} to {end}: {what}, {who}")
    if not report.itinerary:
        lines += ["", "Nobody has to do anything."]
    lines.append("")
    if report.robust:
        lines.append("This plan holds however long the uncertain parts take.")
    else:
        lines.append("WARNING: no plan holds if every uncertain part takes its longest. Then:")
        lines += [f"  {_broken(file, found)}" for found in report.at_worst]
    if report.relies_on:
        lines += ["", "The plan relies on these FACTs and DECISIONs:"]
        lines += [f"  {record}: {_record(file, record)}" for record in report.relies_on]
    return lines


def _broken(file: File, found: Broken) -> str:
    """One CONSTRAINT a plan would break at the longest durations, in words."""
    who, name = _people(file, found.persons), _name(file, found.option)
    if found.constraint is Constraint.ARRIVAL and found.late is not None:
        return f"{who} would be {_span(found.late)} too late for {name}."
    if found.constraint is Constraint.PLACE and found.late is not None:
        return f"{who} would still be busy for {_span(found.late)} when {name} starts."
    if found.constraint is Constraint.PLACE:
        return f"{who} would not be free in time for {name}."
    return f'{name} would break the rule "{found.constraint.value}" for {who}.'


def _wanted(file: File, needed: Missing, alone: bool) -> str:
    """What one unknown FACT would have to be, in words. ``alone`` means nothing else is needed."""
    unknown, limit = needed.unknown, needed.at_most
    if unknown.what == "start":
        return f"{_name(file, unknown.option)} can start at any time"
    if unknown.what == "other ways":
        places = {place.id: place.name for place in file.places}
        there = f"there are other WAYs from {places[unknown.origin or '']} to "
        there += places[unknown.destination or ""]
        if limit is not None:
            return f"{there} that take {_span(limit)} or less"
        return there if alone else f"{there} that are quick enough"
    name = _name(file, unknown.option or unknown.way)
    if unknown.what == "duration":
        if limit is not None:
            return f"{name} takes {_span(limit)} or less"
        return f"the FILE says how long {name} takes" if alone else f"{name} is quick enough"
    place = _starts_at(file, unknown.option)
    if limit is not None:
        return f"people must be at {place} {_span(limit)} or less before {name} starts"
    if alone:
        return f"the FILE says how long before {name} starts people must be at {place}"
    return f"people need not be at {place} long before {name} starts"


def _record(file: File, record: str) -> str:
    """One FACT or DECISION in words."""
    found = next(each for each in (*file.facts, *file.locks) if each.id == record)
    if isinstance(found, Complete):
        places = {place.id: place.name for place in file.places}
        first = local(found.earliest, file.zone).date()
        span = f"{_moment(file, found.earliest)} and {_clock(file, found.latest, first)}"
        return (
            f"every way from {places[found.origin]} to {places[found.destination]}"
            f" that leaves between {span} is listed"
        )
    name = _name(file, found.option)
    if isinstance(found, Lock):
        verb = "takes" if len(found.persons) == 1 else "take"
        return f"{_people(file, found.persons)} {verb} part in {name}"
    if isinstance(found, Start):
        if found.at is None:
            return f"{name} can start at any time"
        return f"{name} starts at {_moment(file, found.at)}"
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
    return next(place.name for place in file.places if place.id == origin)


def _name(file: File, id: str | None) -> str:
    """The name of an OPTION or a WAY."""
    return next((each.name for each in (*file.options, *file.ways) if each.id == id), "another WAY")


def _people(file: File, persons: tuple[str, ...]) -> str:
    """Names joined as a sentence would: Alex, Sam and Jo."""
    names = [person.name for person in file.persons if person.id in persons]
    if len(names) < 2:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _moment(file: File, moment: int) -> str:
    """A time with its day: 2:00 pm on Saturday 15 May 2027."""
    there = local(moment, file.zone)
    day = f"{_DAYS[there.weekday()]} {there.day} {_MONTHS[there.month - 1]} {there.year}"
    return f"{_clock(file, moment)} on {day}"


def _clock(file: File, moment: int, day: object = None) -> str:
    """A time of day: 2:00 pm. The date is added when it is not the day given."""
    there = local(moment, file.zone)
    seconds = f":{there.second:02d}" if there.second else ""
    clock = (
        f"{there.hour % 12 or 12}:{there.minute:02d}{seconds} {'am' if there.hour < 12 else 'pm'}"
    )
    if day is None or there.date() == day:
        return clock
    return f"{clock} on {there.day} {_MONTHS[there.month - 1]}"


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
