// Every OPTION of a FILE, as the page shows it. There is no page in here, so the tests run this
// as it is.
//
// The view sends each OPTION with what the FILE says of it: where it is, when it starts, how
// long it takes, how early people must be there, and whom a LOCK names for it. This puts that
// in words, as the report words it, and says plainly what the FILE does not say. Where the
// report shows a plan, it says who takes part in the OPTION in that plan. It marks what the
// report names: the records that rule out every plan, and the cases in which a trip that
// depends on something works.
//
// Nothing here judges a TRIP. An OPTION that no LOCK names and no plan uses is shown like any
// other: it is in the FILE.

import { casesAbout, casesIn, findsOf, listed, optionsOf, ruledOut, saidOf } from "./named.js";
import { clock, clocksOf, dateName, span } from "./times.js";

/** When an OPTION starts, as far as the FILE says. */
function whenOf(option) {
  if (option.start !== null) return `Starts at ${clock(option.start)} on ${dateName(option.start.at)}.`;
  return option.any_time ? "Can start at any time." : "The FILE does not say when it starts.";
}

/**
 * How long an OPTION takes, as far as the FILE says. A length that the world decides in a range
 * is worded as a range, as the report words it, also where the two ends are the same.
 */
function takesOf(option) {
  if (option.length === null) return "The FILE does not say how long it takes.";
  const { shortest, longest, contingent } = option.length;
  return contingent ? `Takes between ${span(shortest)} and ${span(longest)}.` : `Takes ${span(shortest)}.`;
}

/** How early people must be there, as far as the FILE says. */
function arriveOf(option) {
  if (option.margin === null) return "The FILE does not say how early people must be there.";
  return option.margin ? `People must be there ${span(option.margin)} before it starts.` : "Nobody has to be there before it starts.";
}

/**
 * What the page shows of the OPTIONs of a TRIP as the view sends it, or of no TRIP where the
 * view sends none.
 *
 * Each OPTION has its name, `where` it is, `when` it starts, how long it `takes`, how early to
 * `arrive`, and whom a LOCK names (`lock`). `plan` says who takes part in it in the plan of
 * the report, and is null where the report shows no plan. `step` is the step of the TRIP that
 * it is, where the calendar holds it. Where a row shows a time, `says` names the time zone
 * whose clocks show it.
 *
 * `report` is the report as JSON, where the page has one. `clash` on an OPTION holds its
 * `records` that the report names as ruling out every plan, and `finds` says so. `cases` holds
 * the cases that name it among what the FILE does not say, as their places in `missing` of the
 * report, and `asks` holds what the report says of them. `stated` holds the words of the
 * report for those cases, as lines.js finds them. `clash` and `asked` on the whole say that
 * something here is marked so.
 */
export function options(trip, report = null, stated = null) {
  if (trip === null || !trip.options.length) return { says: "", clash: false, asked: false, options: [] };
  const person = new Map(trip.persons.map((each) => [each.id, each.name]));
  const place = new Map(trip.places.map((each) => [each.id, each.name]));
  const ruled = ruledOut(report);
  const needed = casesIn(report);
  const shown = trip.options.map((option) => {
    const step = trip.steps.findIndex((each) => each.option === option.id);
    const locked = option.locked.map((id) => person.get(id));
    const takers = step < 0 ? [] : trip.steps[step].persons.map((id) => person.get(id));
    const clash = option.records.filter((id) => ruled.has(id));
    const cases = casesAbout(needed, (need) => optionsOf(need).includes(option.id));
    return {
      id: option.id,
      name: option.name,
      where: option.from === option.to ? place.get(option.from) : `${place.get(option.from)} to ${place.get(option.to)}`,
      when: whenOf(option),
      takes: takesOf(option),
      arrive: arriveOf(option),
      // One LOCK can name several PERSONs, and several LOCKs one each: the words fit both.
      lock: locked.length ? `${listed(locked)} ${locked.length === 1 ? "is" : "are each"} named by a LOCK.` : "No LOCK names it.",
      plan: !trip.itinerary ? null : takers.length ? `In the plan: ${listed(takers)} ${takers.length === 1 ? "takes" : "take"} part.` : "Not in the plan.",
      step: step < 0 ? null : step,
      records: option.records,
      clash,
      finds: findsOf(clash),
      cases,
      asks: saidOf(cases, stated, "The report names this OPTION in what the FILE does not say."),
    };
  });
  const clash = shown.some((each) => each.clash.length > 0);
  const asked = shown.some((each) => each.cases.length > 0);
  const says =
    "Every OPTION of the FILE, with what the FILE says of it." +
    (trip.options.some((option) => option.start !== null) ? clocksOf(trip.zone) : "") +
    (clash ? " A red edge marks what the report names among what rules out every plan." : "") +
    (asked ? " A yellow edge marks what the report names in what the FILE does not say." : "");
  return { says, clash, asked, options: shown };
}
