"""A Report as JSON and in plain words.

The JSON has the shape of the expected results beside the examples. The words are for a person:
the plan with its times, or the FACTs and DECISIONs that clash, or what the FILE would have to
say for the TRIP to work. Times are shown on the clocks of the first time zone the FILE names,
and the words name that zone. Where those clocks change during the times shown, each time also
gives its offset from UTC.

What a plan would break at the longest durations is printed under the line of the plan it is
about. So the words never have to describe which step they mean.
"""

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal
from itertools import groupby

from agloe.answers import Answer, CapRow, Cover, Missing, Plan, Report
from agloe.file import (
    Booking,
    Budget,
    Cap,
    Capability,
    Complete,
    CompleteFor,
    CompleteRequires,
    CompleteRights,
    Cutoff,
    Duration,
    File,
    Has,
    Lock,
    Money,
    NeedsRight,
    Offer,
    Option,
    Payment,
    Person,
    Place,
    Requires,
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

_WITH_AN_ID = re.compile(r" \([a-z0-9]+(-[a-z0-9]+)*\)$")  # how a name ends when its id is shown
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


# What an answer says when it comes ahead of its Report. FEASIBLE promises no more than every
# FEASIBLE Report says: the WARNINGs are known only once the plan to show is chosen. INFEASIBLE
# leaves open whether the conflict turns on the BUDGETs, as the Report does until its last test.
_AHEAD = {
    Answer.FEASIBLE: [
        "FEASIBLE: this trip can work.",
        "",
        "The check is still choosing the plan to show. The report will say whether that plan"
        " is sure to hold, and what is still to buy.",
    ],
    Answer.INFEASIBLE: [
        "INFEASIBLE: this trip cannot work.",
        "",
        "The check is still working out which FACTs, WANTs and DECISIONs rule out every plan,"
        " and whether they do so only with the BUDGETs of this FILE.",
    ],
    Answer.UNDETERMINED: [
        "UNDETERMINED: the FILE does not say enough to tell.",
        "",
        "The check is still working out which missing FACTs would be enough.",
    ],
}


def answer_as_text(answer: Answer) -> str:
    """An answer given ahead of its Report, in plain words, ending with a line break."""
    return "\n".join(_AHEAD[answer]) + "\n"


def answer_as_json(answer: Answer) -> dict[str, object]:
    """An answer given ahead of its Report: the answer, and that the Report is unfinished."""
    return {"answer": answer.value, "unfinished": True}


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
        if report.supplies:
            out["requirements"] = [
                {
                    "option": supply.option,
                    "capability": supply.capability,
                    "of": supply.of,
                    "persons": list(supply.persons),
                }
                for supply in report.supplies
            ]
        if _to_buy(report):
            out["to_buy"] = [
                {
                    "option": option,
                    "offer": offer,
                    "persons": [cover.person for cover in covers],
                    "only_if_needed": file.needs_right(option) is None,
                    "price": _money_as_json(covers[0].price),
                    "budget": budget,
                }
                for (option, offer, budget), covers in _to_buy(report).items()
            ]
        money = _money(file, report)
        if money is not None:
            out["money"] = {
                "paid": [
                    {
                        "booking": fact.id,
                        **(_money_as_json(fact.paid.money) or {}),
                        "budget": fact.paid.budget,
                        "by": fact.paid.by,
                    }
                    for fact in file.facts
                    if isinstance(fact, Booking) and fact.paid is not None
                ],
                "not_stated": _with_no_payment(file),
                "totals": [
                    {
                        "currency": currency,
                        "paid": _added(sums.paid),
                        "to_buy": _added(sums.to_buy),
                        "to_buy_at_most_if_needed": _added(sums.if_needed),
                    }
                    for currency, sums in money.items()
                ],
            }
    if report.at_worst:
        out["at_worst"] = [_broken_as_json(file, report, found) for found in report.at_worst]
    if report.conflict:
        out["conflict"] = list(report.conflict)
    if report.missing:
        out["missing"] = [
            [_missing_as_json(needed) for needed in enough] for enough in report.missing
        ]
    if report.caps:
        out["caps"] = [_cap_as_json(file, row) for row in report.caps]
    if report.plans:
        out["plans"] = [
            {
                "buys": [
                    {
                        "person": cover.person,
                        "option": cover.option,
                        "offer": cover.by,
                        "price": _money_as_json(cover.price),
                        "budget": cover.budget,
                        "only_if_needed": file.needs_right(cover.option) is None,
                    }
                    for cover in plan.buys
                ],
                "caps": [_cap_as_json(file, row) for row in plan.caps],
            }
            for plan in report.plans
        ]
    if report.conflict and file.caps:
        held = [each for each in file.caps.values() if each.id in report.conflict]
        out["caps"] = [
            {
                "cap": each.id,
                "budget": each.budget,
                "currency": each.limit.currency,
                "limit": str(each.limit.amount),
            }
            for each in held
        ]
        out["payments"] = [
            {
                "booking": fact.id,
                **(_money_as_json(fact.paid.money) or {}),
                "budget": fact.paid.budget,
                "by": fact.paid.by,
            }
            for fact in file.facts
            if isinstance(fact, Booking) and fact.paid is not None and fact.id in report.conflict
        ]
        out["not_stated"] = [each for each in _with_no_payment(file) if each in report.conflict]
    if _turns_on_who_pays(report):
        out["budgets"] = [
            {"id": each.id, "persons": list(each.persons), "currencies": list(each.currencies)}
            for each in file.budgets
        ]
    return out


def _cap_as_json(file: File, row: CapRow) -> dict[str, object]:
    """One cap with the amounts of its sum, each as text in the cap's currency."""
    cap = next(each for each in file.caps.values() if each.id == row.cap)
    places = -int(cap.limit.amount.as_tuple().exponent)
    return {
        "cap": cap.id,
        "budget": cap.budget,
        "currency": cap.limit.currency,
        "limit": str(cap.limit.amount),
        "paid": _amount(row.paid, places),
        "might_be_paid": [
            {"booking": booking, "amount": None if units is None else _amount(units, places)}
            for booking, units in row.might
        ],
        "asked": list(row.asked),
        "to_buy": _amount(row.to_buy, places),
        "to_buy_at_most_if_needed": _amount(row.if_needed, places),
        "left": _amount(row.left, places),
    }


def _amount(units: int, places: int) -> str:
    """An amount of whole ten-thousandths as text, with at least so many decimal places.

    It shows more where the amount needs them, so nothing is rounded.
    """
    whole, rest = divmod(units, 10**4)
    digits = f"{rest:04d}".rstrip("0")
    return f"{whole}.{digits.ljust(places, '0')}" if digits or places else str(whole)


def _turns_on_who_pays(report: Report) -> bool:
    """Whether a report needs the BUDGETs of the FILE beside it, to be checked against.

    An UNDETERMINED report does where a set asks for a price or for a BUDGET that can pay, and
    wherever the FILE has a cap. An INFEASIBLE one does where its records conflict only with
    the BUDGETs as the FILE lists them.
    """
    asked = {needed.unknown.what for enough in report.missing for needed in enough}
    return report.given_budgets or bool(report.plans) or bool(asked & {"price", "funding"})


@dataclass
class _Sums:
    """The money of one currency: what BOOKINGs state they paid, and what the plan shown buys.

    ``if_needed`` holds the prices of the places it buys only if an OPTION turns out to need
    a right. The OPTIONs are separate, so their sum is the most that those can come to. The
    places bought come with the ids of their OFFERs.
    """

    paid: list[Decimal] = field(default_factory=list[Decimal])
    to_buy: list[Decimal] = field(default_factory=list[Decimal])
    if_needed: list[Decimal] = field(default_factory=list[Decimal])
    offers: dict[str, None] = field(default_factory=dict[str, None])
    offers_if_needed: dict[str, None] = field(default_factory=dict[str, None])


def _money(file: File, report: Report) -> dict[str, _Sums] | None:
    """The money of a plan for each currency, or None where the FILE and the plan state none.

    That is where no BOOKING states a payment and the plan buys no place at a price above
    nothing. Every BOOKING of the FILE that states a payment counts, used or not: the money
    is spent. A payment or a price of nothing counts in no currency, so the result can be
    empty.
    """
    money: dict[str, _Sums] = {}
    stated = False
    for fact in file.facts:
        if isinstance(fact, Booking) and fact.paid is not None:
            stated = True
            if fact.paid.money.amount:
                money.setdefault(fact.paid.money.currency, _Sums()).paid.append(
                    fact.paid.money.amount
                )
    for cover in report.rights:
        if cover.to_buy and cover.price is not None and cover.price.amount:
            sums = money.setdefault(cover.price.currency, _Sums())
            if file.needs_right(cover.option) is None:
                sums.if_needed.append(cover.price.amount)
                sums.offers_if_needed[cover.by] = None
            else:
                sums.to_buy.append(cover.price.amount)
                sums.offers[cover.by] = None
    return money if money or stated else None


def _added(amounts: Sequence[Decimal]) -> str:
    """The sum of amounts, as text. It is exact whatever decimal settings the caller has.

    The amounts are added as whole ten-thousandths. The sum shows as many decimal places as
    the amount that states the most.
    """
    places = units = 0
    for amount in amounts:
        _, digits, exponent = amount.as_tuple()
        shift = int(exponent)
        places = max(places, -shift)
        units += int("".join(str(digit) for digit in digits)) * 10 ** (4 + shift)
    whole, rest = divmod(units, 10**4)
    return f"{whole}.{rest:04d}"[: len(str(whole)) + 1 + places] if places else str(whole)


def _with_no_payment(file: File) -> list[str]:
    """Each BOOKING that states no payment, in the FILE's order."""
    return [fact.id for fact in file.facts if isinstance(fact, Booking) and fact.paid is None]


def _to_buy(report: Report) -> dict[tuple[str, str, str | None], list[Cover]]:
    """Who still has to buy a right, for each OPTION, each OFFER it is from and each BUDGET."""
    buyers: dict[tuple[str, str, str | None], list[Cover]] = {}
    for cover in report.rights:
        if cover.to_buy:
            buyers.setdefault((cover.option, cover.by, cover.budget), []).append(cover)
    return buyers


def _money_as_json(price: Money | None) -> dict[str, str] | None:
    return None if price is None else {"amount": str(price.amount), "currency": price.currency}


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
    if unknown.what == "requirement":
        # The most the OPTION can require where the set asks nothing else. In a larger set,
        # what the set is enough with: the OPTION requires nothing.
        out["capability"] = unknown.about
        if needed.of is None:
            out["of"] = "none"
        else:
            out["of_at_most"] = needed.of
        return out
    if unknown.what == "has":
        out["capability"] = unknown.about
        return out
    if unknown.about is not None:
        out["booking" if unknown.what == "charged" else "offer"] = unknown.about
    if needed.buys:
        out["buys"] = [
            {
                "person": cover.person,
                "option": cover.option,
                "offer": cover.by,
                "price": _money_as_json(cover.price),
            }
            for cover in needed.buys
        ]
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
        how = ", given the BUDGETs of this FILE" if report.given_budgets else " by themselves"
        lines = [
            "INFEASIBLE: this trip cannot work.",
            "",
            f"These {_kinds(file, report.conflict)} rule out every plan{how}. Take"
            " any one away and they no longer do. A FACT that is taken away leaves what it"
            f" said unknown. Times are in {file.zone}.",
            *(f"  {record}: {_record(file, clock, record)}" for record in report.conflict),
        ]
        of_one = any(
            isinstance(fact, Requires) and fact.of == "one" and fact.id in report.conflict
            for fact in file.facts
        )
        if of_one:
            everybody = _people(file, tuple(person.id for person in file.persons))
            lines += [
                "",
                "Only a PERSON of this FILE can meet a requirement of one PERSON. The FILE"
                f" lists {everybody}.",
            ]
        if report.given_budgets:
            lines += ["", *_budgets(file)]
    else:
        lines = ["UNDETERMINED: the FILE does not say enough to tell.", ""]
        cases = [_case(file, enough) for enough in report.missing]
        plans = [_plan_in_words(file, plan) for plan in report.plans] or [[] for _ in cases]
        if len(cases) == 1:
            lines.append(f"The trip works if {cases[0]}.")
            lines += [f"  {line}" for line in plans[0]]
        else:
            lines.append("The trip works in any of these cases:")
            for number, (case, plan) in enumerate(zip(cases, plans, strict=True), 1):
                lines.append(f"  {number}. {_with_a_capital(case)}.")
                lines += [f"     {line}" for line in plan]
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
            names = [
                _name(file, each.id, "or") for each in file.options if each.id in might_be_booked
            ]
            lines += [
                "",
                f"If {_listed(names, 'or')} does need a right, a BOOKING for each PERSON who"
                " takes part in it is enough instead.",
            ]
            if file.caps:
                lines[-1] = lines[-1][:-1] + ", if what those BOOKINGs paid fits the caps."
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
            if file.capabilities:
                lines[-1] += " The PERSONs who take them have to meet whatever they require."
        if report.plans:
            lines += [
                "",
                "Whatever the FILE comes to state counts against a cap like everything else: what"
                " a BOOKING paid from its BUDGET in its currency, and each place that its BUDGET"
                " pays for. All of it has to fit in what the cap has left.",
            ]
        if _turns_on_who_pays(report):
            one_way = "Who buys which place is from one plan that works in that case. "
            lines += ["", *_budgets(file, one_way)]
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
            if file.capabilities:
                lines[-1] += (
                    " Whatever it requires has to be met. Everybody who takes part in it has"
                    " each CAPABILITY that it requires of each PERSON. For each CAPABILITY that"
                    " it requires of one PERSON, somebody who takes part in it from its start"
                    " to its end has it, and can still do everything else the trip asks of"
                    " them. Different PERSONs can meet different requirements."
                )
    return "\n".join(lines) + "\n"


def _budgets(file: File, first: str = "") -> list[str]:
    """The BUDGETs of a FILE in words: who may draw on each, and the currencies it holds.

    ``first`` is a sentence to start with.
    """
    rule = (
        f"{first}A place with a price above nothing is paid from a BUDGET that lists the PERSON"
        " who takes it and holds the currency of the price."
    )
    if not file.budgets:
        return [f"{rule} This FILE names no BUDGET."]
    lines = [f"{rule} The BUDGETs of this FILE:"]
    for budget in file.budgets:
        who = _people(file, budget.persons)
        whose = f"for {who}" if who else "it lists no PERSON"
        holds = _listed(budget.currencies)
        lines.append(f"  {_names(file.budgets)[budget.id]}: {whose}; it holds {holds}")
    return lines


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
            f' Each line marked "!"{" that names no OFFER" if to_buy else ""} says what would'
            " go wrong at the step above it.",
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
        for record in report.relies_on:
            # A BOOKING can cover more PERSONs than the plan credits to it.
            found = next((fact for fact in file.facts if fact.id == record), None)
            credited = tuple(cover.person for cover in report.rights if cover.by == record)
            used_for = ""
            if isinstance(found, Booking) and not credited:
                # In a FILE with a cap, a plan relies on a BOOKING whose right nobody uses.
                used_for = "; this plan counts what it paid, and nobody uses its right"
            elif isinstance(found, Booking) and set(credited) != set(found.covers):
                used_for = f"; this plan uses it for {_people(file, credited)}"
            lines.append(f"  {record}: {_record(file, clock, record)}{used_for}")
    if report.supplies:
        lines += ["", "Who meets the requirements:"]
        able = _names(file.capabilities)
        for supply in report.supplies:
            name, what = _name(file, supply.option), able[supply.capability]
            who = _people(file, supply.persons)
            one = len(supply.persons) == 1
            if supply.of is None:
                silent = f"The FILE does not say whether {name} requires {what}"
                have = "has" if one else "have"
                lines.append(
                    f"  {silent}. {who} {have} that CAPABILITY, so the plan holds if it does."
                )
            else:
                whom = "one PERSON" if supply.of == "one" else "each PERSON"
                meet = "meets" if one else "meet"
                lines.append(f"  {name} requires {what} of {whom}. {who} {meet} that requirement.")
    money = _money(file, report)
    if money is not None:
        people, pots = _names(file.persons, "and"), _names(file.budgets)
        receipts = [
            f"  {fact.id}: {_paid(fact.paid, people, pots)}"
            for fact in file.facts
            if isinstance(fact, Booking) and fact.paid is not None
        ]
        unstated = _with_no_payment(file)
        if unstated:
            receipts.append(f"  No payment is stated for {_listed(unstated)}.")
        if receipts:
            lines += ["", "What the BOOKINGs state that they paid:", *receipts]
        if money:
            lines += ["", "The money of this plan, by currency:"]
        for currency, sums in money.items():
            parts = [f"{_added(sums.paid)} paid"] if sums.paid else []
            if sums.to_buy:
                parts.append(f"{_added(sums.to_buy)} still to buy ({_listed(list(sums.offers))})")
            if sums.if_needed:
                parts.append(
                    f"up to {_added(sums.if_needed)} more, depending on which OPTIONs need a"
                    f" right ({_listed(list(sums.offers_if_needed))})"
                )
            lines.append(f"  {currency}: {'; '.join(parts)}")
    if report.caps:
        lines += ["", "The caps:", *(f"  {_cap_in_words(file, row)}" for row in report.caps)]
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
    for (option, offer, budget), covers in _to_buy(report).items():
        buyers = [cover.person for cover in covers]
        have = "has" if len(buyers) == 1 else "have"
        if_needed = "" if file.needs_right(option) else " if it needs one"
        price = covers[0].price
        if price is not None and budget is not None:
            each = " each" if len(buyers) > 1 else ""
            offer = f"{offer}, for {price}{each} from {_names(file.budgets)[budget]}"
        elif price is not None:
            offer = f"{offer}, at no cost"
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


class _OwnWords(str):
    """Words that begin with a word of the report's own, and not with a name from the FILE.

    Only such a word can take a capital letter at the start of a sentence. A name stays as
    the FILE writes it: "jo" and "Jo" can be two PERSONs.
    """

    __slots__ = ()


def _with_a_capital(words: str) -> str:
    """The words as the start of a sentence. A name at the start is left as it is."""
    return f"{words[0].upper()}{words[1:]}" if isinstance(words, _OwnWords) else words


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
            names = [_name(file, needed.unknown.option, "or") for needed in group]
            parts.append(_OwnWords(f"nobody needs a right to take part in {_listed(names, 'or')}"))
        elif unknown.what == "another right":
            # A right that is found is one more than the places on OFFER, and the words say so.
            places = file.places_on_offer(unknown.option or "")
            more = "" if not places else f", in addition to the {_places(places)} on OFFER"
            more += ", at a cost that fits the caps" if file.caps else ""
            each = "each of " if len(group) > 1 else ""
            who = _people(file, tuple(needed.unknown.person or "" for needed in group))
            right = f"a right to {_name(file, unknown.option)} is found for {each}{who}{more}"
            parts.append(_OwnWords(right))
        else:
            parts.append(_wanted(file, group[0], len(enough) == 1))
    for want, persons in for_whom.items():
        who = _people(file, tuple(persons))
        each = "each of " if len(persons) > 1 else ""
        other = f"another OPTION that SATISFIES {_want(file, want)} is found for {each}{who}"
        parts.append(_OwnWords(other))
    whole = " and ".join(parts)
    return _OwnWords(whole) if isinstance(parts[0], _OwnWords) else whole


def _places(count: int) -> str:
    return "1 place" if count == 1 else f"{count} places"


def _named_with(needed: Missing) -> object:
    """What an unknown FACT shares with those a report names it with. Otherwise it stands alone."""
    unknown = needed.unknown
    if unknown.what == "needs no right":
        return unknown.what
    if unknown.what == "another right":
        return (unknown.what, unknown.option)
    return needed


def _wanted(file: File, needed: Missing, alone: bool) -> str:
    """What one unknown FACT would have to be, in words. ``alone`` means nothing else is needed.

    Words that begin with a word of the report's own are ``_OwnWords``. The others begin with
    a name from the FILE.
    """
    unknown, limit = needed.unknown, needed.at_most
    if unknown.what == "start":
        return f"{_name(file, unknown.option)} can start at any time"
    if unknown.what == "satisfies":
        return f"{_name(file, unknown.option)} SATISFIES {_want(file, unknown.want)}"
    if unknown.what == "does not satisfy":
        return f"{_name(file, unknown.option)} does not SATISFY {_want(file, unknown.want)}"
    if unknown.what == "requirement":
        name, what = _name(file, unknown.option), _names(file.capabilities)[unknown.about or ""]
        if needed.of == "one":
            return f"{name} requires {what} of one PERSON who takes part, or does not require it"
        return f"{name} does not require {what}"
    if unknown.what == "has":
        what = _names(file.capabilities)[unknown.about or ""]
        return f"{_people(file, (unknown.person or '',))} has the CAPABILITY {what}"
    if unknown.what == "price":
        buyers = tuple(cover.person for cover in needed.buys)
        each = " each" if len(buyers) > 1 else ""
        who = _people(file, buyers)
        return _OwnWords(f"a place from {unknown.about} has a price that {who} can{each} pay")
    if unknown.what == "charged":
        booking = next(
            fact for fact in file.facts if isinstance(fact, Booking) and fact.id == unknown.about
        )
        if booking.paid is None:
            return _OwnWords(f"the FILE states what {booking.id} paid and from which BUDGET")
        paid = f"the {booking.paid.money} of {booking.id}"
        return _OwnWords(f"the FILE states which BUDGET {paid} came from")
    if unknown.what == "funding":
        who = _people(file, (unknown.person or "",))
        places = [
            f"one from {cover.by} at a price that the FILE has yet to state"
            if cover.price is None
            else f"one from {cover.by} for {cover.price}"
            for cover in needed.buys
        ]
        within = ", within its caps" if file.caps else ""
        can_be_paid = f"can be paid from a BUDGET that lists {who}{within}"
        return _OwnWords(f"each place that {who} has to buy {can_be_paid} ({', '.join(places)})")
    if unknown.what == "other ways":
        places = _names(file.places)
        there = f"there are other WAYs from {places[unknown.origin or '']} to "
        there += places[unknown.destination or ""]
        if limit is not None:
            return _OwnWords(f"{there} that take {_at_most(limit)}")
        return _OwnWords(there if alone else f"{there} that are quick enough")
    name = _name(file, unknown.option or unknown.way)
    if unknown.what == "duration":
        if limit is not None:
            return f"{name} takes {_at_most(limit)}"
        if alone:
            return _OwnWords(f"the FILE says how long {name} takes")
        return f"{name} is quick enough"
    place = _starts_at(file, unknown.option)
    if limit == 0:
        return _OwnWords(f"nobody has to be at {place} before {name} starts")
    if limit is not None:
        return _OwnWords(f"people must be at {place} {_span(limit)} or less before {name} starts")
    if alone:
        return _OwnWords(f"the FILE says how long before {name} starts people must be at {place}")
    return _OwnWords(f"people need not be at {place} long before {name} starts")


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
    if isinstance(found, Cap):
        return f"the TRIP spends at most {found.limit} from {_names(file.budgets)[found.budget]}"
    if isinstance(found, TripStart):
        return f"the TRIP starts at {clock.moment(found.at)}"
    if isinstance(found, TripEnd):
        return f"the TRIP ends at {clock.moment(found.at)}"
    if isinstance(found, CompleteFor):
        which = [
            _name(file, fact.option, "and")
            for fact in file.facts
            if isinstance(fact, Satisfies) and fact.want == found.want and fact.degree > 0
        ]
        said = _listed(which) if which else "there is none"
        return f"the FILE states every OPTION that SATISFIES {_want(file, found.want)}: {said}"
    if isinstance(found, StartsFrom):
        place = _names(file.places)[found.place]
        return f"{_people(file, (found.person,))} starts from {place}"
    if isinstance(found, Has):
        what = _names(file.capabilities)[found.capability]
        has = "has" if found.has else "does not have"
        return f"{_people(file, (found.person,))} {has} the CAPABILITY {what}"
    if isinstance(found, CompleteRequires):
        which = [
            _name(file, fact.option, "and")
            for fact in file.facts
            if isinstance(fact, Requires) and fact.capability == found.capability
            if fact.of != "none"
        ]
        what = _names(file.capabilities)[found.capability]
        if not which:
            return f"no OPTION in this FILE requires {what}"
        verb = "requires" if len(which) == 1 else "require"
        return f"of the OPTIONs in this FILE, only {_listed(which)} {verb} {what}"
    if isinstance(found, Requires):
        what = _names(file.capabilities)[found.capability]
        if found.of == "none":
            return f"{_name(file, found.option)} does not require {what}"
        whom = "one PERSON" if found.of == "one" else "each PERSON"
        return f"{_name(file, found.option)} requires {what} of {whom} who takes part"
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
        covers = f"a BOOKING for {name} covers {_people(file, found.covers)}"
        if not file.caps:
            return covers
        if found.paid is None:
            return f"{covers}; it states no payment"
        people, pots = _names(file.persons, "and"), _names(file.budgets)
        return f"{covers}; its payment: {_paid(found.paid, people, pots)}"
    if isinstance(found, Offer):
        each = " each" if found.places > 1 else ""
        price = "; nobody knows the price" if found.price is None else f", for {found.price}{each}"
        return f"an OFFER has {_places(found.places)} for {name} that can still be bought{price}"
    if isinstance(found, CompleteRights):
        closed = "nobody on the trip holds another or can get one"
        if found.offers:
            closed += f", except from {_listed(found.offers)}"
        return f"the FILE lists every right to {name}: {closed}"
    return _cutoff(file, name, found)


def _cap_in_words(file: File, row: CapRow) -> str:
    """One cap of a plan that works: its limit, and what is charged to it."""
    cap = next(each for each in file.caps.values() if each.id == row.cap)
    places = -int(cap.limit.amount.as_tuple().exponent)
    parts = [f"{_amount(row.paid, places)} paid"]
    known = [(booking, units) for booking, units in row.might if units is not None]
    if known:
        most = _amount(sum(units for _, units in known), places)
        names = _listed([booking for booking, _ in known])
        parts.append(f"up to {most} more that {names} might have paid from it")
    parts.append(f"{_amount(row.to_buy, places)} still to buy")
    if row.if_needed:
        more = _amount(row.if_needed, places)
        parts.append(f"up to {more} more to buy, depending on which OPTIONs need a right")
    # A BOOKING that might have charged the cap is counted in full, so more may be left.
    parts.append(f"{'at least ' if known else ''}{_amount(row.left, places)} left")
    pot = _names(file.budgets)[cap.budget]
    return f"{cap.id}: at most {cap.limit} from {pot}: {'; '.join(parts)}"


def _plan_in_words(file: File, plan: Plan) -> list[str]:
    """One plan for a set of unknown FACTs: who buys what, and the sum for each cap."""
    pots = _names(file.budgets)
    buys: list[str] = []
    for cover in plan.buys:
        place = f"{_people(file, (cover.person,))} buys a place from {cover.by}"
        if cover.price is None:
            place += " at a price that the FILE has yet to state"
        elif not cover.price.amount:
            place += " at no cost"
        else:
            place += f" for {cover.price}"
        if cover.budget is not None:
            place += f" from {pots[cover.budget]}"
        if file.needs_right(cover.option) is None:
            place += ", if the OPTION needs a right"
        buys.append(place)
    nothing = "nobody buys a place from an OFFER of this FILE"
    lines = [f"One plan that works then: {'; '.join(buys) or nothing}."]
    for row in plan.caps:
        cap = next(each for each in file.caps.values() if each.id == row.cap)
        places = -int(cap.limit.amount.as_tuple().exponent)
        terms = [f"{_amount(row.paid, places)} paid"] if row.paid else []
        terms += [
            f"up to {_amount(units, places)} that {booking} might have charged it"
            for booking, units in row.might
            if units is not None and booking not in row.asked
        ]
        if row.to_buy:
            terms.append(f"{_amount(row.to_buy, places)} still to buy")
        if row.if_needed:
            terms.append(f"up to {_amount(row.if_needed, places)} more if OPTIONs need a right")
        counted = "; ".join(terms) or "nothing so far"
        left = f"{_amount(row.left, places)} {cap.limit.currency}"
        open_ended = [booking for booking, units in row.might if units and booking not in row.asked]
        names = _listed(open_ended, "or")
        more = f", and more once the FILE says that {names} charged it less"
        lines.append(
            f"{cap.id}, on {pots[cap.budget]}: {counted}, of at most {cap.limit}."
            f" That leaves {left} for whatever else is charged to it{more if open_ended else ''}."
        )
    return lines


def _paid(paid: Payment, people: dict[str, str], pots: dict[str, str]) -> str:
    """What a BOOKING paid, in words: the amount, then who paid and the BUDGET, where stated.

    ``people`` and ``pots`` are the names to show for the PERSONs and the BUDGETs. Commas
    keep the parts apart, and a name that holds a comma is shown in quotes.
    """
    parts = [str(paid.money) if paid.money.amount else "nothing"]
    if paid.by is not None:
        parts.append(f"paid by {people[paid.by]}")
    if paid.budget is not None:
        parts.append(f"from {pots[paid.budget]}")
    return ", ".join(parts)


def _cutoff(file: File, name: str, found: Cutoff) -> str:
    place = _starts_at(file, found.option)
    if not found.margin:
        return f"nobody has to be at {place} before {name} starts"
    return f"people must be at {place} {_span(found.margin)} before {name} starts"


def _starts_at(file: File, option: str | None) -> str:
    """The name of the PLACE where an OPTION starts."""
    origin = next(each.origin for each in file.options if each.id == option)
    return _names(file.places)[origin]


def _names(
    records: Sequence[Person | Place | Option | Way | Want | Budget | Capability],
    joins: str | None = None,
) -> dict[str, str]:
    """The name to show for each record, so that no two records show the same.

    A record whose name another record has shows its id too. If two would still show the same,
    every record shows its id: no two ids are the same.

    A name is shown in quotes where it could be taken for something else: one with a comma,
    a colon, a semicolon or a quote mark, one that ends like a name with its id, and one that
    holds the word ``joins``, which joins the list the names are for. The quotes go on
    before the id.
    """
    shared = Counter(record.name for record in records)
    shown = {
        record.id: _quoted(record.name, joins)
        if shared[record.name] == 1
        else f"{_quoted(record.name, joins)} ({record.id})"
        for record in records
    }
    if len(set(shown.values())) < len(shown):
        return {record.id: f"{_quoted(record.name, joins)} ({record.id})" for record in records}
    return shown


def _quoted(name: str, joins: str | None) -> str:
    """A name, in quotes where it could be taken for something else."""
    marks = any(mark in name for mark in ",:;")  # what a report puts between its own parts
    splits = marks or (joins is not None and joins in name.casefold().split())
    if splits or '"' in name or _WITH_AN_ID.search(name):
        return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return name


def _name(file: File, id: str | None, joins: str | None = None) -> str:
    """The name of an OPTION or a WAY. ``joins`` is the word of the list it is for, if any."""
    return _names((*file.options, *file.ways), joins).get(id or "", "another WAY")


def _want(file: File, id: str | None) -> str:
    """The name of a WANT."""
    return _names(file.wants)[id or ""]


def _people(file: File, persons: tuple[str, ...]) -> str:
    """Names joined as a sentence would: Alex, Sam and Jo."""
    shown = _names(file.persons, "and")
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
