// What is still open about a TRIP, as the page lists it above its drawings. There is no page
// in here, so the tests run this as it is.
//
// The list is for a person who watches an agent plan a trip. It holds what has to be done or
// decided: what the COMPILER's report says rules out every plan, the cases in which it says
// the trip works, what it warns of, and the OPTIONs of a plan that no LOCK decides.
//
// Nothing here judges a TRIP. What rules out every plan, what the FILE does not say and what
// could go wrong are for the COMPILER to say: each such item is a line of the report, in the
// report's own words, and it is tied like that line. Which PERSON a LOCK names for an OPTION
// is in the FILE, and the view sends it with each step.

import { casesIn, listed, ruledOut, someone } from "./named.js";
import { clock, clocksOf, dateName } from "./times.js";

/** When a step of a plan happens: Saturday 15 May 2027, 3:00 pm to 4:00 pm. */
function whenOf(step) {
  return `${dateName(step.start.at)}, ${clock(step.start)} to ${step.end === null ? "an unknown time" : clock(step.end, step.start)}`;
}

/**
 * What the page lists as open about a TRIP as the view sends it, or nothing where the page has
 * no report on that TRIP, or cannot read what the report states.
 *
 * `report` is the report as JSON. `stated` holds the report's own words, as lines.js finds
 * them: the line of each record, the line of each case in which the trip works with the
 * heading over them, and what the report warns of at each step.
 *
 * The list is in `groups`, each with its `kind`, its heading in `says`, and its `items`:
 *
 * - `conflict`, for a TRIP that cannot work: each FACT, WANT and DECISION that the report
 *   names as ruling out every plan, by its id and with its line.
 * - `cases`, for a TRIP that depends on what the FILE does not say: each case in which the
 *   report says the trip works, with its line.
 * - `warnings`, for a plan: each thing that the report warns of at a step, with the step.
 * - `choices`, for a plan: each OPTION of the plan with the PERSONs in it whom no LOCK names
 *   for it. The COMPILER chose it for them, and nobody has decided it.
 *
 * An item has a `name`, what is said of it in `says`, and `when` it happens where it is a
 * step. `of` is the step of the TRIP that it is a drawing of, and `records` holds what it is
 * tied to: a record by its id, or a case under a name that no record can have. So pointing at
 * an item lights up what a line of the report about it would. `mark` says how it is marked:
 * "clash" where the report names it in what rules out every plan, "asked" where the report
 * names it in what the FILE does not say, "warned" where the report warns of it.
 *
 * `count` is how many items there are. `clash` and `asked` say that the list holds something
 * that is marked red, or yellow.
 */
export function open(trip, report = null, stated = null) {
  const none = { says: "", count: 0, clash: false, asked: false, groups: [] };
  if (trip === null || stated === null || report === null || typeof report !== "object") return none;
  const clocks = typeof trip.zone === "string" ? clocksOf(trip.zone) : "";
  const item = (name, says, more = {}) => ({ name, says, when: null, of: null, records: [], mark: "", ...more });
  if (report.answer === "INFEASIBLE") {
    const records = [...ruledOut(report)];
    if (!records.length) return none;
    const items = records.map((id) => item(id, stated.records[id] ?? "", { records: [id], mark: "clash" }));
    const says = records.length === 1 ? "This FACT, WANT or DECISION rules out every plan by itself:" : `These ${records.length} FACTs, WANTs and DECISIONs rule out every plan together. Take any one away, and they no longer do:`;
    return { says: `No plan works.${clocks}`, count: items.length, clash: true, asked: false, groups: [{ kind: "conflict", says, items }] };
  }
  if (report.answer === "UNDETERMINED") {
    const cases = casesIn(report);
    // Every case has its line in the report, or the page lists none of them.
    if (!cases.length || cases.some((_, n) => typeof stated.cases[n] !== "string")) return none;
    const items = cases.map((_, n) => item("", stated.cases[n], { records: [`case:${n}`], mark: "asked" }));
    return { says: "The FILE does not say enough to tell whether this trip works.", count: items.length, clash: false, asked: true, groups: [{ kind: "cases", says: stated.heading ?? "", items }] };
  }
  if (report.answer !== "FEASIBLE" || trip.itinerary !== true) return none;
  const person = new Map(trip.persons.map((each) => [each.id, each.name]));
  const steps = trip.steps.map((step, n) => ({ ...step, n, name: step.name ?? "another WAY" }));
  const warnings = steps.flatMap((step) => (stated.warnings[step.n] ?? []).map((words) => item(step.name, words, { when: whenOf(step), of: step.n, mark: "warned" })));
  // A LOCK names the PERSONs who take part. So an OPTION with nobody of the TRIP in it is no
  // choice that a LOCK could decide.
  const choices = steps.flatMap((step) => {
    const free = step.option === null ? [] : step.persons.filter((id) => !step.locked.includes(id));
    return free.length ? [item(step.name, listed(free.map((id) => someone(person.get(id)))), { when: whenOf(step), of: step.n })] : [];
  });
  const groups = [
    ...(warnings.length ? [{ kind: "warnings", says: "The report warns:", items: warnings }] : []),
    ...(choices.length ? [{ kind: "choices", says: "In the plan, and not decided. No LOCK names these PERSONs for these OPTIONs:", items: choices }] : []),
  ];
  const count = warnings.length + choices.length;
  const says = count ? `${count === 1 ? "1 thing is" : `${count} things are`} open.${clocks}` : "Nothing is open: the report warns of nothing, and a LOCK decides every OPTION of the plan.";
  return { says, count, clash: false, asked: warnings.length > 0, groups };
}
