"""A Report as JSON and in plain words.

The JSON has the shape of the expected results beside the examples. The words are for a person:
the plan with its times, or the FACTs and DECISIONs that clash, or what the FILE would have to
say for the TRIP to work. Times are shown on the clocks of the first time zone the FILE names,
and the words name that zone. Where those clocks change during the times shown, each time also
gives its offset from UTC.

What a plan would break at the longest durations is printed under the line of the plan it is
about. So the words never have to describe which step they mean.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal
from itertools import groupby

from agloe.answers import (
    Answer,
    CapRow,
    Carried,
    Cover,
    Deadline,
    Expiry,
    Missing,
    Plan,
    Report,
    as_seen,
    bought_if_needed,
    cancelling_at_any_time,
    cancelling_now,
    every_deadline,
    right_needed,
    with_no_expiry,
    with_no_terms,
)
from agloe.file import (
    Booking,
    Cap,
    Complete,
    CompleteFor,
    CompleteNeedsRightFor,
    CompleteRequires,
    CompleteRequiresObject,
    CompleteRights,
    CompleteRightsFor,
    CompleteTransfers,
    Cutoff,
    Duration,
    File,
    Has,
    Lock,
    Money,
    NeedsRight,
    NeedsRightFor,
    Now,
    ObjectStarts,
    Offer,
    Payment,
    RefusesObject,
    Requires,
    RequiresObject,
    Satisfies,
    Start,
    StartsFrom,
    TripEnd,
    TripStart,
    Want,
    WithObject,
    comes_twice,
    length_written,
    local,
    written,
)
from agloe.names import to_show as _names
from agloe.reference import Broken, Constraint, Itinerary, Step, Where

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
        "The check is still working out what the FILE would have to say for the trip to work.",
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
        # What gives each PERSON their right. A place that covers an OBJECT is under
        # "to_buy", and with the OBJECT under "objects".
        rights: dict[str | None, dict[str, str]] = {}
        for cover in report.rights:
            if cover.person is not None:
                rights.setdefault(cover.option, {})[cover.person] = cover.by
        carried = _carried_in(report)
        out["itinerary"] = [
            {
                ("way" if step.option is None else "option"): step.option or step.way,
                "persons": list(step.persons),
                "start": written(step.start, file.zone),
                "end": None if step.end is None else written(step.end, file.zone),
                **({"rights": rights[step.option]} if step.option in rights else {}),
                **({"hands_over": dict(step.handed)} if step.handed else {}),
                **({"carries": carried[step.option]} if step.option in carried else {}),
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
        if report.objects:
            out["objects"] = [
                {
                    "object": carried.object,
                    "path": [
                        {
                            "where": [_where_as_json(each) for each in stay.where],
                            "since": stay.since,
                            "how": stay.how,
                        }
                        for stay in carried.stays
                    ],
                    **{
                        key: [
                            {
                                "option": use.option,
                                "stated": use.stated,
                                "where": [_where_as_json(each) for each in use.where],
                            }
                            for use in carried.uses
                            if use.check == check
                        ]
                        for key, check in (("required_by", "requires"), ("refused_by", "refuses"))
                    },
                    "covered_in": [
                        {
                            "option": use.option,
                            "stated": use.stated,
                            "where": [_where_as_json(each) for each in use.where],
                            "booking": use.by,
                            **({"offer": use.offer} if use.offer is not None else {}),
                        }
                        for use in carried.uses
                        if use.by is not None or use.offer is not None
                    ],
                }
                for carried in report.objects
            ]
        if _to_buy(file, report):
            out["to_buy"] = [
                {
                    "option": option,
                    "offer": offer,
                    "persons": [cover.person for cover in covers if cover.person is not None],
                    **(
                        {"objects": [cover.object for cover in covers]}
                        if covers[0].object is not None
                        else {}
                    ),
                    "only_if_needed": if_needed,
                    "price": _money_as_json(covers[0].price),
                    "budget": budget,
                }
                for (option, offer, budget, if_needed), covers in _to_buy(file, report).items()
            ]
        if _together(report.rights):
            out["places_together"] = _together_as_json(report.rights)
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
    if report.missing or report.before:
        # A case that holds only before a time has that time as its last condition.
        untils = report.before or [None] * len(report.missing)
        out["missing"] = [
            [
                *(_missing_as_json(needed) for needed in enough),
                *([] if until is None else [{"what": "time", "before": written(until, file.zone)}]),
            ]
            for enough, until in zip(report.missing, untils, strict=True)
        ]
    if report.caps:
        out["caps"] = [_cap_as_json(file, row) for row in report.caps]
    if report.plans:
        out["plans"] = [
            {
                "buys": [
                    {
                        "person": cover.person,
                        **({"object": cover.object} if cover.object is not None else {}),
                        "option": cover.option,
                        "offer": cover.by,
                        "price": _money_as_json(cover.price),
                        "budget": cover.budget,
                        "only_if_needed": right_needed(file, cover) is None,
                    }
                    for cover in plan.buys
                ],
                **(
                    {"places_together": _together_as_json(plan.buys)}
                    if _together(plan.buys)
                    else {}
                ),
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
            {
                "id": each.id,
                "persons": list(each.persons),
                **({"objects": list(each.objects)} if each.objects else {}),
                "currencies": list(each.currencies),
            }
            for each in file.budgets
        ]
    out.update(_terms_as_json(file))
    return out


def _together(covers: Sequence[Cover]) -> dict[str, tuple[tuple[str, ...], ...]]:
    """The sets of OPTIONs where an OBJECT takes places together, for each OBJECT with several.

    Such an OBJECT is in one place at a time, and nobody knows where. So it takes the
    places of one set, and never of two.
    """
    return {
        cover.object: cover.together
        for cover in covers
        if cover.object is not None and cover.together
    }


def _together_as_json(covers: Sequence[Cover]) -> list[dict[str, object]]:
    return [
        {"object": thing, "options": [list(some) for some in sets]}
        for thing, sets in _together(covers).items()
    ]


def _together_in_words(file: File, name: str, sets: Sequence[Sequence[str]]) -> str:
    """Which places for one OBJECT have to be bought together at most, in words.

    ``name`` is the name to show for the OBJECT. Where each set is one OPTION, "or" joins
    their names. Otherwise each OPTION has its own "for", and a semicolon parts the sets: a
    name with a comma or a semicolon in it is shown in quotes.
    """
    if all(len(some) == 1 for some in sets):
        options = _listed([_name(file, some[0], "or") for some in sets], "or")
        return f"Of the places for {name}, at most one has to be bought: for {options}."
    groups = [", ".join(f"for {_name(file, option)}" for option in some) for some in sets]
    said = "; or ".join(groups)
    return f"Of the places for {name}, at most these have to be bought together: {said}."


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
        **(
            {
                "left_for_places": [
                    {"offer": offer, "each": _amount(units, places)}
                    for offer, units in row.left_for
                ]
            }
            if row.left_for
            else {}
        ),
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
    a right, or an OBJECT turns out to be there: those that ``bought_if_needed`` counts, so
    their sum is the most that such places can come to. The places bought come with the ids
    of their OFFERs.
    """

    paid: list[Decimal] = field(default_factory=list[Decimal])
    to_buy: list[Decimal] = field(default_factory=list[Decimal])
    if_needed: list[Decimal] = field(default_factory=list[Decimal])
    offers: dict[str, None] = field(default_factory=dict[str, None])
    offers_if_needed: dict[str, None] = field(default_factory=dict[str, None])
    might_be_there: bool = False  # a place for an OBJECT that only might be in its OPTION


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
    bought = [
        cover
        for cover in report.rights
        if cover.to_buy and cover.price is not None and cover.price.amount
    ]
    for cover in bought:
        if cover.price is None:
            continue
        sums = money.setdefault(cover.price.currency, _Sums())
        if right_needed(file, cover) is None:
            sums.offers_if_needed[cover.by] = None
            sums.might_be_there = sums.might_be_there or cover.might
        else:
            sums.to_buy.append(cover.price.amount)
            sums.offers[cover.by] = None
    for currency, sums in money.items():
        theirs = [cover for cover in bought if cover.price and cover.price.currency == currency]
        sums.if_needed += [c.price.amount for c in bought_if_needed(file, theirs) if c.price]
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


def _to_buy(file: File, report: Report) -> dict[tuple[str, str, str | None, bool], list[Cover]]:
    """Who still has to buy a right, for each OPTION, each OFFER it is from and each BUDGET.

    An OFFER for OBJECTs has the OBJECTs that still need a right. With each group comes
    whether the right has to be bought only if it turns out to be needed. That is the same
    for all the PERSONs of an OPTION, and it can differ from one OBJECT to the next.
    """
    buyers: dict[tuple[str, str, str | None, bool], list[Cover]] = {}
    for cover in report.rights:
        if cover.to_buy:
            if_needed = right_needed(file, cover) is None
            buyers.setdefault((cover.option, cover.by, cover.budget, if_needed), []).append(cover)
    return buyers


def _carried_in(report: Report) -> dict[str | None, list[str]]:
    """The OBJECTs that are carried in each OPTION of the plan shown, in the report's order.

    An OBJECT is carried where the travelers choose that, and where it goes along with no
    choice: the OPTION requires it and carries it. Either way it is in the OPTION from its
    start. An OBJECT that only might go along is not among them.
    """
    carried: dict[str | None, list[str]] = {}
    for thing in report.objects:
        for stay in thing.stays:
            if stay.how == "carried":
                carried.setdefault(stay.since, []).append(thing.object)
    return carried


def _where_as_json(where: Where) -> dict[str, str | None]:
    """Where an OBJECT is: the PERSON who has it, the PLACE where it lies, or the OPTION it is in.

    A PLACE of null is somewhere the FILE does not name.
    """
    if where.option is not None:
        return {"option": where.option}
    return {"person": where.person} if where.person is not None else {"place": where.place}


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
    if found.object is not None:
        out["object"] = found.object
    if found.sooner is not None:
        out["sooner"] = length_written(found.sooner)
    if found.might:
        out["might"] = True
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
    if unknown.what in _ABOUT_AN_OBJECT:
        out["object"] = unknown.about
        if unknown.place is not None:
            out["place"] = unknown.place
        if unknown.what == "another transfer":
            # Each check of the OBJECT in one plan: an OPTION that requires it, so that it
            # has to be at hand, or one that refuses it, so that no PERSON may have it there.
            # With each comes whether the check already holds with what the FILE lists.
            # Nobody has worked out whether another transfer can make all of them hold.
            out["at_hand_for"] = [
                {"option": option, "check": check, "stated": stated, "covered": covered}
                for option, check, stated, covered in needed.at_hand_for
            ]
            out["settled"] = False
        return out
    if unknown.about is not None:
        # What a BOOKING charged, the price of an OFFER, or a BUDGET that pays for an OBJECT.
        kinds = {"charged": "booking", "funding": "object"}
        out[kinds.get(unknown.what, "offer")] = unknown.about
    if needed.buys:
        out["buys"] = [
            {
                "person": cover.person,
                **({"object": cover.object} if cover.object is not None else {}),
                "option": cover.option,
                "offer": cover.by,
                "price": _money_as_json(cover.price),
            }
            for cover in needed.buys
        ]
    out["at_most"] = None if needed.at_most is None else length_written(needed.at_most)
    return out


_ABOUT_AN_OBJECT = (
    "does not require",
    "does not refuse",
    "keeps",
    "does not keep",
    "does not carry",
    "does not keep or carry",
    "hands over",
    "carries",
    "starts with",
    "starts at",
    "needs no right for",
    "another right for",
    "another transfer",
)


@dataclass(frozen=True)
class Clock:
    """How times are put in words: on the clocks of one time zone.

    With ``offsets``, each time also gives its offset from UTC, because the clocks change during
    the times shown and a time of day alone could mean two moments. A time that the clocks
    show twice, as when they go back, gives its offset in any case.
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
        if self.offsets or comes_twice(moment, self.zone):
            clock += f" ({offset_from_utc(there.utcoffset() or timedelta())})"
        if day is None or there.date() == day:
            return clock
        year = "" if there.year == day.year else f" {there.year}"
        return f"{clock} on {there.day} {_MONTHS[there.month - 1]}{year}"

    def moment(self, moment: int) -> str:
        """A time with its day: 2:00 pm on Saturday 15 May 2027."""
        return f"{self.time(moment)} on {self.day_name(moment)}"


def offset_from_utc(ahead: timedelta) -> str:
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
        elif isinstance(found, Offer):
            times += [] if found.expires is None else [found.expires]
    return times


def clock_for(file: File, report: Report) -> Clock:
    """The clock for one report: with offsets if the times it shows have more than one."""
    moments = [step.start for step in report.itinerary]
    moments += [step.end for step in report.itinerary if step.end is not None]
    moments += _times_stated(file, (*report.relies_on, *report.conflict))
    # The time now and the DEADLINEs are shown with every report of a FILE that states them.
    now = file.now()
    moments += [each.at for each in every_deadline(file)] + ([] if now is None else [now.at])
    offsets = {local(moment, file.zone).utcoffset() for moment in moments}
    return Clock(file.zone, len(offsets) > 1)


def as_text(file: File, report: Report) -> str:
    """The Report in plain words, ending with a line break."""
    clock = clock_for(file, report)
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
        # A FILE that states no time now is seen as it is in the stretch of each case: the
        # OFFERs that are open there are the ones its words count.
        untils = report.before or [None] * len(report.missing)
        seen = [file if not report.before else as_seen(file, until) for until in untils]
        cases = [
            _timed(clock, _case(at, enough) if enough else "", until)
            for at, enough, until in zip(seen, report.missing, untils, strict=True)
        ]
        # A set with another transfer is not settled. Among the sets of one stretch of time,
        # a report lists such sets only where it lists no other. A FILE that states no time
        # now can have a settled case in one stretch and an unsettled one in another.
        unsettled = [
            number
            for number, enough in enumerate(report.missing, 1)
            if any(needed.unknown.what == "another transfer" for needed in enough)
        ]
        plans = [
            _plan_in_words(at, plan, number not in unsettled)
            for number, (at, plan) in enumerate(zip(seen, report.plans, strict=False), 1)
        ] or [[] for _ in cases]
        asked = [needed.unknown for enough in report.missing for needed in enough]
        kinds = {unknown.what for unknown in asked}
        works = "works"
        if unsettled:
            works = "might work" if len(unsettled) == len(cases) else "works, or might work,"
        if len(cases) == 1:
            lines.append(f"The trip {works} if {cases[0]}.")
            lines += [f"  {line}" for line in plans[0]]
        else:
            lines.append(f"The trip {works} in any of these cases:")
            for number, (case, plan) in enumerate(zip(cases, plans, strict=True), 1):
                lines.append(f"  {number}. {_with_a_capital(case)}.")
                lines += [f"     {line}" for line in plan]
        if "another transfer" in kinds:
            moved = {unknown.about for unknown in asked if unknown.what == "another transfer"}
            names = [_names(file.objects)[each.id] for each in file.objects if each.id in moved]
            this = "That is" if len(cases) == 1 else "These cases are"
            if len(unsettled) < len(cases):
                one = len(unsettled) == 1
                which = _listed([str(number) for number in unsettled])
                this = f"Case {which} is" if one else f"Cases {which} are"
            lines += [
                "",
                f"{this} not settled. What the FILE lists does not do that for"
                f" {_listed(names)}, and the COMPILER has not worked out whether another"
                " transfer can.",
            ]
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
        # A BOOKING that covers the OBJECT can stand in for the answer that an OPTION needs
        # no right for it, unless a FACT says that no other right for the OBJECT can be had.
        about_a_right = [
            unknown
            for unknown in asked
            if unknown.what == "needs no right for"
            and file.rights_complete_for(unknown.option or "", unknown.about or "") is None
        ]
        might_be_covered = list(dict.fromkeys(about_a_right))  # each OPTION and OBJECT once
        if might_be_covered:
            things = _names(file.objects)
            fits = ", if what it paid fits the caps" if file.caps else ""
            lines.append("")
            for unknown in might_be_covered:
                name, thing = _name(file, unknown.option), things[unknown.about or ""]
                lines.append(
                    f"If {name} does need a right for {thing}, a BOOKING for it that covers"
                    f" {thing} is enough instead{fits}."
                )
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
            if any(row.left_for for plan in report.plans for row in plan.caps):
                lines[-1] += " A place of which a line above says what it can cost has that much."
        if _turns_on_who_pays(report):
            one_way = "Who buys which place is from one plan that works in that case. "
            if report.missing and any(
                needed.unknown.what == "another transfer"
                for enough in report.missing
                for needed in enough
            ):
                one_way = (
                    "Who buys which place is from one plan for that case: it works, or might"
                    " work where the case is not settled. "
                )
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
    lines += _terms_in_words(file, clock)
    return "\n".join(lines) + "\n"


def _terms_in_words(file: File, clock: Clock) -> list[str]:
    """The time now, the DEADLINEs and what cancelling costs now, after the rest of a report.

    A FILE that states no time now and no terms for cancelling gets nothing here. Every other
    FILE gets this with each of the three answers: none of it turns on a plan.
    """
    now = file.now()
    bookings = {fact.id: fact for fact in file.facts if isinstance(fact, Booking)}
    if not _states_terms(file):
        return []
    held = {
        id: f"{id}, the BOOKING for {_name(file, booking.option)}"
        for id, booking in bookings.items()
    }
    offers = {fact.id: fact for fact in file.facts if isinstance(fact, Offer)}
    rows = [
        f"  {clock.moment(each.at)}: a term for cancelling {held[each.booking]}, starts."
        f" {_change_in_words(each)}"
        if isinstance(each, Deadline)
        else f"  {clock.moment(each.at)}: {_expiry_in_words(file, offers[each.offer])}"
        for each in every_deadline(file)
    ]
    zone = f"(times in {file.zone})"
    if now is None:
        lines = ["", "This FILE does not state the time now."]
        if rows:
            lines[-1] += (
                " So nobody knows which of its DEADLINEs have passed. All of them, earliest"
                f" first {zone}:"
            )
            lines += rows
        else:
            lines[-1] += " Its terms have no DEADLINE."
        always = cancelling_at_any_time(file)
        if always:
            lines += ["", "What cancelling costs at any time:"]
            lines += [f"  {held[id]}: {_loss(cost)}" for id, cost in always]
    else:
        used = f"This report uses {clock.moment(now.at)} as the time now {zone}."
        lines = ["", f"{used} The FACT {now.id} states it."]
        costs = cancelling_now(file)
        if rows:
            lines += ["", "DEADLINEs after that time, earliest first:", *rows]
        elif costs or file.dated_offers():
            lines += ["", "No DEADLINE comes after that time."]
        if costs:
            lines += ["", "What cancelling costs now:"]
            for id, cost in costs:
                said = "the FILE does not say" if cost is None else _loss(cost)
                lines.append(f"  {held[id]}: {said}")
    unstated = with_no_terms(file)
    if unstated:
        lines += ["", f"No terms for cancelling are stated for {_listed(unstated)}."]
    undated = with_no_expiry(file)
    if undated:
        lines += ["", f"No time of expiry is stated for {_listed(undated)}."]
    return lines


def _states_terms(file: File) -> bool:
    """Whether a report of this FILE has a last part: the time now, DEADLINEs, terms.

    It has one where the FILE states the time now, terms for cancelling a BOOKING, or when
    an OFFER expires.
    """
    stated = any(isinstance(fact, Booking) and fact.cancelling for fact in file.facts)
    return file.now() is not None or stated or bool(file.dated_offers())


def _with_expired(file: File, offers: Sequence[str]) -> list[str]:
    """The OFFERs that a COMPLETE set of rights names, each marked where it has expired.

    The set names an OFFER as long as the FILE holds it. Whether a place of it can still be
    bought is another matter.
    """
    return [f"{id} (expired)" if id in file.expired else id for id in offers]


def _expiry_in_words(file: File, offer: Offer) -> str:
    """What ends when an OFFER expires: the chance to buy its places, at its price.

    Nothing is added up: nobody loses the price of every place by waiting.
    """
    one = offer.places == 1
    places = "1 place" if one else f"up to {offer.places} places"
    if offer.price is None:
        price = ""
    elif not offer.price.amount:
        price = " at no cost"
    else:
        price = f" at {offer.price}{'' if one else ' each'}"
    ends = f"The chance to buy {places}{price} ends."
    if offer.price is None:
        ends += f" The FILE does not state {'its' if one else 'their'} price."
    return f"{offer.id}, the OFFER for {_name(file, offer.option)}, expires. {ends}"


def _change_in_words(found: Deadline) -> str:
    """What cancelling costs in the term that starts at a DEADLINE and in the one before it.

    The words are about those two terms and nothing else: a cost holds until the next term
    starts, and another line says what that term states.
    """
    before = "before it" if found.first else "in the term before it"
    if found.after is None:
        unsaid = "The FILE does not say what cancelling costs in it"
        if found.before is None:
            return f"{unsaid}, or {before}. The STAKE is unknown."
        return (
            f"{unsaid}. It costs {_loss(found.before)} in the term before it. The STAKE is unknown."
        )
    later = f"Cancelling costs {_loss(found.after)} in it"
    if found.before is None:
        at_stake = "Nothing is at STAKE." if found.stake == () else "The STAKE is unknown."
        return f"{later}. The FILE does not say what it costs {before}. {at_stake}"
    sides = f"{later}, and {_loss(found.before)} in the term before it."
    if found.stake is None:
        # More in one currency and less in another: the two are stated, and nothing is added up.
        return f"{sides} At STAKE: {_loss(found.after)}, in place of {_loss(found.before)}."
    if not found.stake:
        return f"{sides} Nothing is at STAKE."
    return f"{sides} At STAKE: {_loss(found.stake)}."


def _loss(costs: Sequence[Money]) -> str:
    """What cancelling costs, in words: each amount with its currency, or nothing."""
    return _listed([str(each) for each in costs]) if costs else "nothing"


def _terms_as_json(file: File) -> dict[str, object]:
    """The time now, the DEADLINEs and what cancelling costs now, for the report as JSON.

    Empty for a FILE that states no time now and no terms for cancelling. A list of amounts
    that is empty says nothing. None says that the FILE states no cost, and for a STAKE that
    it is unknown or not one sum. Where the FILE states no time now, the costs that hold at
    any time stand in for the costs now.
    """
    now = file.now()
    bookings = {fact.id: fact for fact in file.facts if isinstance(fact, Booking)}
    offers = {fact.id: fact for fact in file.facts if isinstance(fact, Offer)}
    if not _states_terms(file):
        return {}

    def amounts(costs: Sequence[Money] | None) -> list[dict[str, str] | None] | None:
        return None if costs is None else [_money_as_json(each) for each in costs]

    out: dict[str, object] = {}
    if now is not None:
        out["now"] = {"fact": now.id, "at": written(now.at, file.zone)}
    out["deadlines"] = [
        {
            "at": written(each.at, file.zone),
            "kind": "cancelling",
            "booking": each.booking,
            "option": bookings[each.booking].option,
            "before": amounts(each.before),
            "from_then": amounts(each.after),
            "change": each.change,
            "stake": amounts(each.stake),
            "first_term": each.first,
        }
        if isinstance(each, Deadline)
        else _expiry_as_json(file, each, offers[each.offer])
        for each in every_deadline(file)
    ]
    costs = cancelling_now(file)
    if costs:
        out["cancelling_now"] = [
            {"booking": id, "option": bookings[id].option, "costs": amounts(cost)}
            for id, cost in costs
        ]
    always = cancelling_at_any_time(file)
    if now is None and always:
        out["cancelling_at_any_time"] = [
            {"booking": id, "option": bookings[id].option, "costs": amounts(cost)}
            for id, cost in always
        ]
    unstated = with_no_terms(file)
    if unstated:
        out["no_terms_for_cancelling"] = list(unstated)
    undated = with_no_expiry(file)
    if undated:
        out["no_expiry_stated"] = list(undated)
    return out


def _expiry_as_json(file: File, found: Expiry, offer: Offer) -> dict[str, object]:
    """One expiry for the report as JSON: the OFFER, its places and its price.

    The price is None where the FILE states none.
    """
    return {
        "at": written(found.at, file.zone),
        "kind": "expiry",
        "offer": offer.id,
        "option": offer.option,
        "places": offer.places,
        "price": _money_as_json(offer.price),
    }


def _budgets(file: File, first: str = "") -> list[str]:
    """The BUDGETs of a FILE in words: who may draw on each, and the currencies it holds.

    ``first`` is a sentence to start with.
    """
    for_objects = any(isinstance(fact, Offer) and fact.objects for fact in file.facts)
    whom = "the PERSON who takes it, or the OBJECT that it covers," if for_objects else "the PERSON"
    rule = (
        f"{first}A place with a price above nothing is paid from a BUDGET that lists {whom}"
        f"{'' if for_objects else ' who takes it'} and holds the currency of the price."
    )
    if not file.budgets:
        return [f"{rule} This FILE names no BUDGET."]
    lines = [f"{rule} The BUDGETs of this FILE:"]
    # One list of PERSONs and OBJECTs: no two of them show the same name.
    shown = _names([*file.persons, *file.objects], "and")
    for budget in file.budgets:
        listed = [shown[person.id] for person in file.persons if person.id in budget.persons]
        listed += [shown[thing.id] for thing in file.objects if thing.id in budget.objects]
        whose = f"for {_listed(listed)}" if listed else "it lists no PERSON"
        holds = _listed(budget.currencies)
        lines.append(f"  {_names(file.budgets)[budget.id]}: {whose}; it holds {holds}")
    return lines


def _feasible(file: File, clock: Clock, report: Report) -> list[str]:
    to_buy = _to_buy(file, report)
    if not report.robust:
        lines = ["FEASIBLE, with a WARNING: this trip can work, but no plan is sure to hold."]
    elif to_buy:
        lines = ["FEASIBLE, with a WARNING: this trip works, but not everything is booked yet."]
    else:
        lines = ["FEASIBLE: this trip works."]
    marks = _marks(file, clock, report)
    carried = _carried_in(report)
    day = None
    for number, (step, _) in enumerate(_lines(report.itinerary)):
        if clock.day(step.start) != day:
            day = clock.day(step.start)
            lines += ["", f"{clock.day_name(step.start)} (times in {file.zone})"]
        end = "an unknown time" if step.end is None else clock.time(step.end, day)
        what = _name(file, step.option or step.way)
        # An OPTION can happen with nobody in it: then the line names nobody.
        who = f", {_people(file, step.persons)}" if step.persons else ""
        lines.append(f"  {clock.time(step.start)} to {end}: {what}{who}")
        lines += [f"    ! {mark}" for mark in marks.get(number, [])]
        for thing, person in step.handed:
            taker = _people(file, (person,))
            lines.append(f"    {taker} takes {_names(file.objects)[thing]} here.")
        for thing in carried.get(step.option, []):
            lines.append(f"    This carries {_names(file.objects)[thing]}.")
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
        people = any(cover.person is not None for covers in to_buy.values() for cover in covers)
        things = any(cover.object is not None for covers in to_buy.values() for cover in covers)
        says = "who still has to buy a right" if people else ""
        if things:
            # A place for an OBJECT can be one that only might have to be bought.
            for_sure = any(
                covers[0].object is not None and not if_needed
                for (_, _, _, if_needed), covers in to_buy.items()
            )
            maybe = any(
                covers[0].object is not None and if_needed
                for (_, _, _, if_needed), covers in to_buy.items()
            )
            needs = "still needs" if for_sure else "might still need"
            a_right = "one" if people else "a right"
            says += f"{' and ' if people else ''}which OBJECT {needs} {a_right}"
            if for_sure and maybe:
                says += ", or might"
        lines += [
            "",
            "WARNING: not everything is booked yet."
            f' A line marked "!" that names an OFFER says {says}.'
            " Only a BOOKING secures one.",
        ]
    if report.relies_on:
        lines += ["", f"The plan relies on these {_kinds(file, report.relies_on)}:"]
        for record in report.relies_on:
            # A BOOKING can cover more PERSONs than the plan credits to it.
            found = next((fact for fact in file.facts if fact.id == record), None)
            credited = tuple(
                cover.person
                for cover in report.rights
                if cover.by == record and cover.person is not None
            )
            # The OBJECTs that the plan uses the BOOKING for.
            things = [
                carried.object
                for carried in report.objects
                if any(use.by == record for use in carried.uses)
            ]
            used_for = ""
            if isinstance(found, Booking) and not credited and not things:
                # In a FILE with a cap, a plan relies on a BOOKING whose right nobody uses.
                used_for = "; this plan counts what it paid, and nobody uses its right"
            elif isinstance(found, Booking) and (
                set(credited) != set(found.covers) or set(things) != set(found.objects)
            ):
                # One list of PERSONs and OBJECTs: no two of them show the same name.
                shown = _names([*file.persons, *file.objects], "and")
                users = [shown[person.id] for person in file.persons if person.id in credited]
                users += [shown[thing.id] for thing in file.objects if thing.id in things]
                used_for = f"; this plan uses it for {_listed(users)}"
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
    if report.objects:
        lines += ["", "Where each OBJECT is:"]
        together = _together(report.rights)
        for carried in report.objects:
            lines += _carried_in_words(file, clock, report.itinerary, carried)
            if carried.object in together:
                name = _names(file.objects)[carried.object]
                said = _together_in_words(file, name, together[carried.object])
                lines.append(f"    {said}")
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
                where = " and on where each OBJECT is" if sums.might_be_there else ""
                parts.append(
                    f"up to {_added(sums.if_needed)} more, depending on which OPTIONs need a"
                    f" right{where} ({_listed(list(sums.offers_if_needed))})"
                )
            lines.append(f"  {currency}: {'; '.join(parts)}")
    if report.caps:
        rows = (f"  {_cap_in_words(file, row, report.rights)}" for row in report.caps)
        lines += ["", "The caps:", *rows]
    return lines


def _carried_in_words(
    file: File, clock: Clock, itinerary: Itinerary, carried: Carried
) -> list[str]:
    """One OBJECT of a plan in words: where it is, then each OPTION that requires or refuses it.

    A time has its date where it is not on the day the plan starts.
    """
    thing = _names(file.objects)[carried.object]
    starts = {step.option: step.start for step in itinerary if step.option is not None}
    ends = {step.option: step.end for step in itinerary if step.option is not None}
    first_day = clock.day(itinerary[0].start)
    stays: list[str] = []
    for stay in carried.stays:
        where = _where(file, stay.where)
        if stay.since is None:
            stays.append(f"{where} when the TRIP starts")
            continue
        name = _name(file, stay.since)
        if stay.how == "arrived":
            # It lies there from the end of the OPTION that it was in, or might have been
            # in. Where nobody knows when that OPTION ends, nobody knows from when.
            over = ends[stay.since]
            if over is None:
                stays.append(f"{where} when {name} ends")
            else:
                stays.append(f"{where} from {clock.time(over, first_day)} (where {name} ends)")
            continue
        how = {
            "handed over": f"handed over in {name}",
            "kept": f"kept by {name}",
            "kept if held": f"kept by {name} if anybody there has {thing}",
            "unknown action": f"the FILE does not say what {name} does with {thing}",
            "unknown requirement": f"the FILE does not say whether {name} requires {thing}",
            "carried": "carried",
        }[stay.how or ""]
        stays.append(f"{where} from {clock.time(starts[stay.since], first_day)} ({how})")
    lines = [f"  {thing}: {'; '.join(stays)}"]
    for use in carried.uses:
        name, where = _name(file, use.option), _where(file, use.where)
        if use.offer is not None and use.stated:
            before = f"Just before it starts: {where}. A place from {use.offer} covers {thing}"
            lines.append(f"    {name} {use.check} {thing}. {before}, once it is bought.")
        elif use.offer is not None:
            silent = f"The FILE does not say whether {name} {use.check} {thing}"
            holds = f"A place from {use.offer} covers {thing}, so the plan holds if it does"
            lines.append(f"    {silent}. Just before it starts: {where}. {holds}.")
        elif use.by is not None and use.stated:
            before = f"Just before it starts: {where}. {use.by} covers {thing}"
            lines.append(f"    {name} {use.check} {thing}. {before}.")
        elif use.by is not None:
            silent = f"The FILE does not say whether {name} {use.check} {thing}"
            holds = f"{use.by} covers {thing}, so the plan holds if it does"
            lines.append(f"    {silent}. Just before it starts: {where}. {holds}.")
        elif use.stated:
            lines.append(f"    {name} {use.check} {thing}. Just before it starts: {where}.")
        else:
            silent = f"The FILE does not say whether {name} {use.check} {thing}"
            holds = f"Just before it starts: {where}, so the plan holds if it does"
            lines.append(f"    {silent}. {holds}.")
    return lines


def _where(file: File, where: Sequence[Where]) -> str:
    """Where an OBJECT is, or each place it might be: with Alex or at the Art Institute.

    A place with no name is somewhere the FILE does not name. An OBJECT that might be with
    any PERSON, at any PLACE or somewhere the FILE does not name is nobody knows where. An
    OPTION that it might be in is not one of those: it is named beside the others.
    """
    outside = [each for each in where if each.option is None]
    if len(outside) == len(file.persons) + len(file.places) + 1:
        return "nobody knows where"
    people, places = _names(file.persons, "or"), _names(file.places, "or")

    def one(each: Where) -> str:
        if each.person is not None:
            return f"with {people[each.person]}"
        if each.place is not None:
            return f"at {places[each.place]}"
        if each.option is not None:
            return f"in {_name(file, each.option, 'or')}"
        return "somewhere the FILE does not name"

    return _listed([one(each) for each in where], "or")


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


def _marks(file: File, clock: Clock, report: Report) -> dict[int, list[str]]:
    """The WARNINGs about a plan, in words, for each line of the plan.

    First who still has to buy a right to an OPTION, and from which OFFER. Then what the plan
    would break at the longest durations.

    A line is known by its number, counting from zero. PERSONs who share a line and are in the
    same trouble are named together. Longer durations break only CONSTRAINTs about time, and
    the fourteenth where an OBJECT that was carried would arrive too late. Those are broken
    at one of the plan's steps. So a finding with no line is a fault in this program, and it
    stops here. An OBJECT that would not be at hand has one mark at its step, whatever needs
    it there: the OPTION requires it, or it is handed over or carried there. The mark says
    how long after the start of the step the OBJECT would arrive, where a finding knows.
    It says "might" where the OBJECT might also be at hand: nobody knows whether an OPTION
    took it along. Where the OBJECT might be in one of several OPTIONs, it says between
    which two times the OBJECT would arrive, or up to which time it might.
    """
    lines = _lines(report.itinerary)
    line_of = {
        position: number for number, (_, positions) in enumerate(lines) for position in positions
    }
    line_of_option: dict[str | None, int] = {
        step.option: number for number, (step, _) in enumerate(lines) if step.option is not None
    }
    together: dict[tuple[int, Constraint, int | None], list[str]] = {}
    # At each line, each OBJECT that would not be at hand: the finding says how late it
    # would arrive, and whether it might be at hand after all.
    not_at_hand: dict[int, dict[str, Broken]] = {}
    for found in report.at_worst:
        number = line_of[found.step] if found.step is not None else line_of_option[found.option]
        if found.constraint is Constraint.AT_HAND and found.object is not None:
            # Each finding about this OBJECT at this step has the same delay.
            not_at_hand.setdefault(number, {})[found.object] = found
            continue
        together.setdefault((number, found.constraint, found.late), []).extend(found.persons)
    marks: dict[int, list[str]] = {}
    # One list of PERSONs and OBJECTs: no two of them show the same name.
    shown = _names([*file.persons, *file.objects], "and")
    expiries = {each.id: each.expires for each in file.dated_offers()}
    for (option, offer, budget, only_if_needed), covers in _to_buy(file, report).items():
        # A place of an OFFER that states when it expires has to be bought before then.
        expires = expiries.get(offer or "")
        by_when = "" if expires is None else f", before {clock.moment(expires)}"
        buyers = [cover.person for cover in covers if cover.person is not None]
        covered = [cover.object for cover in covers if cover.object is not None]
        one = len(covers) == 1
        price = covers[0].price
        if price is not None and budget is not None:
            each = "" if one else " each"
            offer = f"{offer}, for {price}{each} from {_names(file.budgets)[budget]}"
        elif price is not None:
            offer = f"{offer}, at no cost"
        if covered:
            # A place that covers an OBJECT: nobody takes it, so the mark names the OBJECT.
            # A name can be of one thing or of several, so no verb follows it.
            named = [shown[thing.id] for thing in file.objects if thing.id in covered]
            things = named[0] if one else f"each of {_listed(named)}"
            # Where nobody knows whether the right is needed, it might have to be bought:
            # the OPTION might need none, or the OBJECT might not be in it.
            might = "might still have" if only_if_needed else "still has"
            mark = f"A right to this {might} to be bought for {things}"
        else:
            if_needed = " if it needs one" if only_if_needed else ""
            who = _people(file, tuple(buyers))
            mark = f"{who} still {'has' if one else 'have'} to buy a right to this{if_needed}"
        marks.setdefault(line_of_option[option], []).append(f"{mark}, from {offer}{by_when}.")
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
    things = _names(file.objects)
    for number, missing in not_at_hand.items():
        for thing in file.objects:
            if thing.id not in missing:
                continue
            late, sooner = missing[thing.id].late, missing[thing.id].sooner
            would = "might" if missing[thing.id].might else "would"
            if late is None:
                mark = f"{things[thing.id]} {would} not be at hand when this starts."
            elif sooner is None:
                mark = f"{things[thing.id]} {would} arrive {_span(late)} after this starts."
            elif missing[thing.id].might:
                mark = f"{things[thing.id]} might arrive up to {_span(late)} after this starts."
            else:
                between = f"between {_span(sooner)} and {_span(late)}"
                mark = f"{things[thing.id]} would arrive {between} after this starts."
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


def _timed(clock: Clock, case: str, until: int | None) -> str:
    """A case with the time that it holds until: the last condition of the case.

    A case with no unknown FACT holds before that time and asks nothing else.
    """
    if until is None:
        return case
    # The case is said again where no other line names the clocks, so it names them itself.
    cutoff = f"it is before {clock.moment(until)} ({clock.zone})"
    if not case:
        return _OwnWords(cutoff)
    return (
        _OwnWords(f"{case}, and {cutoff}")
        if isinstance(case, _OwnWords)
        else f"{case}, and {cutoff}"
    )


def _case(file: File, enough: Sequence[Missing]) -> str:
    """One set of unknown FACTs that would be enough, in words.

    PERSONs who need another OPTION for the same WANT are named together, as "each of". The
    condition is one for each PERSON: whether one OPTION or several meet it is left open. The
    OPTIONs that have to need no right are named together where they follow one another in the
    set. So are the PERSONs who need a right to one OPTION. The OPTIONs that need a right for
    one OBJECT, or have to need none for it, are named together wherever they come in the
    set, at the place of the first. Nothing else changes the order.
    """
    parts: list[str] = []
    for_whom: dict[str | None, list[str]] = {}
    transfers: list[str] = []  # they come last, as in the fixed order
    for _, run in groupby(_side_by_side(enough), key=_named_with):
        group = list(run)
        unknown = group[0].unknown
        if unknown.what == "another option":
            for_whom.setdefault(unknown.want, []).append(unknown.person or "")
        elif unknown.what == "needs no right":
            names = [_name(file, needed.unknown.option, "or") for needed in group]
            parts.append(_OwnWords(f"nobody needs a right to take part in {_listed(names, 'or')}"))
        elif unknown.what == "another transfer":
            transfers.append(_another_transfer(file, group[0]))
        elif unknown.what == "another right":
            # A right that is found is one more than the places on OFFER, and the words say so.
            places = file.places_on_offer(unknown.option or "")
            more = "" if not places else f", in addition to the {_places(places)} on OFFER"
            more += ", at a cost that fits the caps" if file.caps else ""
            each = "each of " if len(group) > 1 else ""
            who = _people(file, tuple(needed.unknown.person or "" for needed in group))
            right = f"a right to {_name(file, unknown.option)} is found for {each}{who}{more}"
            parts.append(_OwnWords(right))
        elif unknown.what in ("needs no right for", "another right for"):
            # One OBJECT in several OPTIONs: the OPTIONs are named together.
            names = [_name(file, needed.unknown.option, "and") for needed in group]
            thing = _names(file.objects)[unknown.about or ""]
            if unknown.what == "needs no right for":
                needs = "needs" if len(names) == 1 else "need"
                parts.append(f"{_listed(names)} {needs} no right for {thing}")
            else:
                each = "each of " if len(names) > 1 else ""
                found = f"a right to {each}{_listed(names)} is found that covers {thing}"
                parts.append(_OwnWords(found))
        else:
            parts.append(_wanted(file, group[0], len(enough) == 1))
    for want, persons in for_whom.items():
        who = _people(file, tuple(persons))
        each = "each of " if len(persons) > 1 else ""
        other = f"another OPTION that SATISFIES {_want(file, want)} is found for {each}{who}"
        parts.append(_OwnWords(other))
    parts += transfers
    whole = " and ".join(parts)
    return _OwnWords(whole) if isinstance(parts[0], _OwnWords) else whole


def _another_transfer(file: File, needed: Missing) -> str:
    """Another transfer of an OBJECT, in words.

    It names the OPTIONs for which another transfer has to put the OBJECT at hand in one
    plan, and then those for which what the FILE lists already does: another transfer has
    to leave it at hand there. Then come the OPTIONs that it has to keep the OBJECT out of,
    and those that it has to leave it out of: the ones that refuse it, and then the ones
    that need a right for it where nothing covers it. An OPTION that only might require or
    refuse the OBJECT is named so. An OPTION that a FACT says requires the OBJECT, and that
    a FACT says refuses it or needs a right for it, comes last: the OBJECT has to lie where
    it starts, and with no PERSON who takes part.
    """
    thing = _names(file.objects)[needed.unknown.about or ""]
    said = {(option, check) for option, check, stated, _ in needed.at_hand_for if stated}
    barred = {option for option, check in said if check in ("refuses", "needs a right for")}
    both = {option for option, check in said if check == "requires" and option in barred}

    def those(check: str, covered: bool, link: str) -> str:
        mine = [
            (option, stated)
            for option, kind, stated, holds in needed.at_hand_for
            if kind == check and holds is covered and option not in both
        ]
        stated = [_name(file, option, "and") for option, stated in mine if stated]
        might = [_name(file, option, "and") for option, stated in mine if not stated]
        named = [f"{link} {_listed(stated)}"] if stated else []
        if might:
            several = "need a right for" if check == "needs a right for" else check[:-1]
            they = f"it {check}" if len(might) == 1 else f"they {several}"
            named.append(f"{link} {_listed(might)} if {they} {thing}")
        return ", and ".join(named)

    def lies_there(covered: bool) -> str:
        """The OPTIONs that require and refuse the OBJECT, by whether both checks hold."""
        holds = {
            option: all(held for name, _, _, held in needed.at_hand_for if name == option)
            for option, _, _, _ in needed.at_hand_for
            if option in both
        }
        mine = [_name(file, option, "and") for option, held in holds.items() if held is covered]
        starts = "starts" if len(mine) == 1 else "start"
        return f"where {_listed(mine)} {starts}" if mine else ""

    parts = [
        (f"puts {thing} at hand", those("requires", False, "for")),
        (f"leaves {thing} at hand", those("requires", True, "for")),
        (f"keeps {thing}", those("refuses", False, "out of")),
        (f"leaves {thing}", those("refuses", True, "out of")),
        (f"keeps {thing}", those("needs a right for", False, "away from whoever is in")),
        (f"leaves {thing}", those("needs a right for", True, "away from whoever is in")),
        (f"puts {thing}", lies_there(False)),
        (f"leaves {thing}", lies_there(True)),
    ]
    does = ", and ".join(f"{verb} {named}" for verb, named in parts if named)
    return _OwnWords(f"another transfer {does}")


def _places(count: int) -> str:
    return "1 place" if count == 1 else f"{count} places"


def _side_by_side(enough: Sequence[Missing]) -> list[Missing]:
    """A set of unknown FACTs with those about a right for one OBJECT next to each other.

    The fixed order puts the FACTs of one OPTION together. So with two OBJECTs, the OPTIONs
    that need a right for the first are apart. Each such FACT moves up to the others of its
    kind about its OBJECT, and nothing else moves.
    """
    placed: list[Missing] = []
    for needed in enough:
        at = len(placed)
        if needed.unknown.what in ("needs no right for", "another right for"):
            key = _named_with(needed)
            alike = [n for n, other in enumerate(placed) if _named_with(other) == key]
            at = alike[-1] + 1 if alike else at
        placed.insert(at, needed)
    return placed


def _named_with(needed: Missing) -> object:
    """What an unknown FACT shares with those a report names it with. Otherwise it stands alone."""
    unknown = needed.unknown
    if unknown.what == "needs no right":
        return unknown.what
    if unknown.what == "another right":
        return (unknown.what, unknown.option)
    if unknown.what in ("needs no right for", "another right for"):
        return (unknown.what, unknown.about)
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
    if unknown.what in _ABOUT_AN_OBJECT:
        thing = _names(file.objects)[unknown.about or ""]
        if unknown.what == "starts with":
            return f"{_people(file, (unknown.person or '',))} has {thing} when the TRIP starts"
        if unknown.what == "starts at":
            place = _names(file.places)[unknown.place or ""]
            return _OwnWords(f"the TRIP starts with {thing} at {place}")
        name = _name(file, unknown.option)
        return {
            "does not require": f"{name} does not require {thing}",
            "does not refuse": f"{name} does not refuse {thing}",
            "keeps": f"{name} keeps {thing}",
            "does not keep": f"{name} does not keep {thing}",
            "does not carry": f"{name} does not carry {thing}",
            "does not keep or carry": f"{name} neither keeps nor carries {thing}",
            "hands over": f"{thing} can be handed over in {name}",
            "carries": f"{name} can carry {thing}",
            "needs no right for": f"{name} needs no right for {thing}",
            "another right for": _OwnWords(f"a right to {name} is found that covers {thing}"),
        }[unknown.what]
    if unknown.what == "price":
        covered = [cover.object for cover in needed.buys if cover.object is not None]
        if covered:
            # The places of an OFFER for OBJECTs: nobody takes them, so the OBJECTs are named.
            shown = _names([*file.persons, *file.objects], "and")
            things = _listed([shown[thing.id] for thing in file.objects if thing.id in covered])
            each = "each of " if len(covered) > 1 else ""
            can_be_paid = f"has a price that can be paid for {each}{things}"
            return _OwnWords(f"a place from {unknown.about} {can_be_paid}")
        buyers = tuple(cover.person for cover in needed.buys if cover.person is not None)
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
        places = [
            f"one from {cover.by} at a price that the FILE has yet to state"
            if cover.price is None
            else f"one from {cover.by} for {cover.price}"
            for cover in needed.buys
        ]
        within = ", within its caps" if file.caps else ""
        if unknown.person is None:
            # A BUDGET that can pay for an OBJECT: the places are those that cover it.
            what = _names([*file.persons, *file.objects], "and")[unknown.about or ""]
            can_be_paid = f"can be paid from a BUDGET that lists {what}{within}"
            return _OwnWords(f"each place that covers {what} {can_be_paid} ({', '.join(places)})")
        who = _people(file, (unknown.person,))
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


def _record(file: File, clock: Clock, record: str) -> str:
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
    if isinstance(found, ObjectStarts):
        thing = _names(file.objects)[found.object]
        if found.person is not None:
            return f"{_people(file, (found.person,))} has {thing} when the TRIP starts"
        return f"the TRIP starts with {thing} at {_names(file.places)[found.place or '']}"
    if isinstance(found, RequiresObject):
        does = "requires" if found.needed else "does not require"
        return f"{_name(file, found.option)} {does} {_names(file.objects)[found.object]}"
    if isinstance(found, RefusesObject):
        does = "refuses" if found.refused else "does not refuse"
        return f"{_name(file, found.option)} {does} {_names(file.objects)[found.object]}"
    if isinstance(found, WithObject):
        thing = _names(file.objects)[found.object]
        return {
            "hands_over": f"{thing} can be handed over in {_name(file, found.option)}",
            "keeps": f"{_name(file, found.option)} keeps {thing}",
            "carries": f"{_name(file, found.option)} can carry {thing}",
            "nothing": f"{_name(file, found.option)} leaves {thing} alone",
        }[found.does]
    if isinstance(found, CompleteRequiresObject):
        requiring = [
            _name(file, fact.option, "and")
            for fact in file.facts
            if isinstance(fact, RequiresObject) and fact.object == found.object and fact.needed
        ]
        refusing = [
            _name(file, fact.option, "and")
            for fact in file.facts
            if isinstance(fact, RefusesObject) and fact.object == found.object and fact.refused
        ]
        thing = _names(file.objects)[found.object]
        if not requiring and not refusing:
            return f"no OPTION in this FILE requires or refuses {thing}"

        def only(which: list[str], one: str, several: str) -> str:
            if not which:
                return f"none {one} {thing}"
            return f"only {_listed(which)} {one if len(which) == 1 else several} {thing}"

        asks = only(requiring, "requires", "require")
        return f"of the OPTIONs in this FILE, {asks}, and {only(refusing, 'refuses', 'refuse')}"
    if isinstance(found, CompleteTransfers):
        which = [
            _name(file, fact.option, "and")
            for fact in file.facts
            if isinstance(fact, WithObject) and fact.object == found.object
            if fact.does != "nothing"
        ]
        thing = _names(file.objects)[found.object]
        said = _listed(which) if which else "there is none"
        return f"the FILE states every OPTION that hands over, keeps or carries {thing}: {said}"
    if isinstance(found, CompleteNeedsRightFor):
        which = [
            _name(file, fact.option, "and")
            for fact in file.facts
            if isinstance(fact, NeedsRightFor) and fact.object == found.object and fact.needed
        ]
        thing = _names(file.objects)[found.object]
        if not which:
            return f"no OPTION in this FILE needs a right for {thing}"
        needs = "needs" if len(which) == 1 else "need"
        return f"of the OPTIONs in this FILE, only {_listed(which)} {needs} a right for {thing}"
    if isinstance(found, Now):
        return f"the time now is {clock.moment(found.at)}"
    name = _name(file, found.option)
    if isinstance(found, NeedsRightFor):
        needs = "needs a right" if found.needed else "needs no right"
        return f"{name} {needs} for {_names(file.objects)[found.object]}"
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
        # One list of PERSONs and OBJECTs: no two of them show the same name.
        shown = _names([*file.persons, *file.objects], "and")
        covered = [shown[person.id] for person in file.persons if person.id in found.covers]
        covered += [shown[thing.id] for thing in file.objects if thing.id in found.objects]
        covers = f"a BOOKING for {name} covers {_listed(covered)}"
        if not file.caps:
            return covers
        if found.paid is None:
            return f"{covers}; it states no payment"
        people, pots = _names(file.persons, "and"), _names(file.budgets)
        return f"{covers}; its payment: {_paid(found.paid, people, pots)}"
    if isinstance(found, Offer):
        each = " each" if found.places > 1 else ""
        price = "; nobody knows the price" if found.price is None else f", for {found.price}{each}"
        # An OFFER that has expired by the time now had its places until then. Where the
        # FILE states no time now, nobody knows whether one that states its expiry can
        # still be bought.
        gone = found.id in file.expired
        bought = "that can still be bought"
        if found.expires is not None:
            can = "could be bought" if gone else "can still be bought"
            if file.now() is None and not gone:
                can = "can be bought"
            bought = f"that {can} until {clock.moment(found.expires)}"
        if found.objects:
            # Each place covers one of the OBJECTs it names. They are named as a BOOKING
            # names them: no PERSON shows the same name.
            shown = _names([*file.persons, *file.objects], "or")
            named = [shown[thing.id] for thing in file.objects if thing.id in found.objects]
            bought += f" to cover {_listed(named, 'or')}"
        has = "had" if gone else "has"
        return f"an OFFER {has} {_places(found.places)} for {name} {bought}{price}"
    if isinstance(found, CompleteRights):
        # Each such FACT says what it is about: the PERSONs who take part, or one OBJECT.
        closed = "nobody on the trip holds another or can get one"
        if found.offers:
            closed += f", except from {_listed(_with_expired(file, found.offers))}"
        return f"the FILE lists every right for a PERSON to take part in {name}: {closed}"
    if isinstance(found, CompleteRightsFor):
        # The OBJECT is named as a BOOKING names it: no PERSON shows the same name, and a
        # name with "and" in it is in quotes, so that it is not read as two things.
        thing = _names([*file.persons, *file.objects], "and")[found.object]
        closed = "nobody on the trip holds another or can get one"
        if found.offers:
            closed += f", except from {_listed(_with_expired(file, found.offers))}"
        return f"the FILE lists every right to {name} that covers {thing}: {closed}"
    return _cutoff(file, name, found)


def _cap_in_words(file: File, row: CapRow, rights: Sequence[Cover] = ()) -> str:
    """One cap of a plan that works: its limit, and what is charged to it.

    ``rights`` holds what the plan buys: a place for an OBJECT that only might be in its
    OPTION is bought only if the OBJECT is there.
    """
    cap = next(each for each in file.caps.values() if each.id == row.cap)
    places = -int(cap.limit.amount.as_tuple().exponent)
    parts = [f"{_amount(row.paid, places)} paid"]
    known = [(booking, units) for booking, units in row.might if units is not None]
    if known:
        most = _amount(sum(units for _, units in known), places)
        names = _listed([booking for booking, _ in known])
        parts.append(f"up to {most} more that {names} might have paid from it")
    parts.append(f"{_amount(row.to_buy, places)} still to buy")
    # A place for an OBJECT that only might be in its OPTION, charged to this cap.
    there = any(_charged_to(cap, cover) and cover.might for cover in rights)
    if row.if_needed:
        more = _amount(row.if_needed, places)
        where = " and on where each OBJECT is" if there else ""
        parts.append(f"up to {more} more to buy, depending on which OPTIONs need a right{where}")
    # A BOOKING that might have charged the cap is counted in full, so more may be left.
    # So is a place that is bought only if a right turns out to be needed, or an OBJECT
    # turns out to be there.
    least = known or row.if_needed
    parts.append(f"{'at least ' if least else ''}{_amount(row.left, places)} left")
    pot = _names(file.budgets)[cap.budget]
    return f"{cap.id}: at most {cap.limit} from {pot}: {'; '.join(parts)}"


def _charged_to(cap: Cap, cover: Cover) -> bool:
    """Whether what a place costs is charged to this cap: to its BUDGET, in its currency."""
    price = cover.price
    return cover.budget == cap.budget and price is not None and price.currency == cap.limit.currency


def _plan_in_words(file: File, plan: Plan, settled: bool = True) -> list[str]:
    """One plan for a set of unknown FACTs: who buys what, and the sum for each cap.

    Where the set is not settled, nobody has worked out whether the plan works.
    """
    pots = _names(file.budgets)
    buys: list[str] = []
    for cover in plan.buys:
        if cover.person is None:
            # A place that covers an OBJECT: nobody takes it, so the OBJECT is named. A
            # name can be of one thing or of several, so no verb follows it.
            thing = _names([*file.persons, *file.objects], "and")[cover.object or ""]
            place = f"a place from {cover.by} covers {thing},"
        else:
            place = f"{_people(file, (cover.person,))} buys a place from {cover.by}"
        if cover.price is None:
            place += " at a price that the FILE has yet to state"
        elif not cover.price.amount:
            place += " at no cost"
        else:
            place += f" for {cover.price}"
        if cover.budget is not None:
            place += f" from {pots[cover.budget]}"
        if right_needed(file, cover) is None and cover.person is None:
            place += ", if a right is needed there"
        elif right_needed(file, cover) is None:
            place += ", if the OPTION needs a right"
        buys.append(place)
    nothing = "nobody buys a place from an OFFER of this FILE"
    works = "works" if settled else "might work"
    lines = [f"One plan that {works} then: {'; '.join(buys) or nothing}."]
    shown = _names([*file.persons, *file.objects], "and")
    lines += [
        _together_in_words(file, shown[thing], sets) for thing, sets in _together(plan.buys).items()
    ]
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
            # A place for an OBJECT that only might be in its OPTION is bought if it is there.
            there = any(_charged_to(cap, cover) and cover.might for cover in plan.buys)
            or_there = " or an OBJECT is there" if there else ""
            more = _amount(row.if_needed, places)
            terms.append(f"up to {more} more if OPTIONs need a right{or_there}")
        counted = "; ".join(terms) or "nothing so far"
        # What is bought only if it is needed is counted, so more is left if it is not.
        least = "at least " if row.if_needed else ""
        left = f"{least}{_amount(row.left, places)} {cap.limit.currency}"
        open_ended = [booking for booking, units in row.might if units and booking not in row.asked]
        names = _listed(open_ended, "or")
        more = f", and more once the FILE says that {names} charged it less"
        lines.append(
            f"{cap.id}, on {pots[cap.budget]}: {counted}, of at most {cap.limit}."
            f" That leaves {left} for whatever else is charged to it{more if open_ended else ''}."
        )
        # A place of an OFFER with no price yet can cost more than its share of that, where
        # it covers an OBJECT whose places are not all bought together.
        for offer, units in row.left_for:
            lines[-1] += (
                f" A place from {offer} can cost up to {_amount(units, places)}"
                f" {cap.limit.currency}: not every place counted here is bought with it."
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
