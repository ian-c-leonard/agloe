// What is still open about a TRIP, as the page lists it above its drawings. There is no page
// in here, so the tests run this as it is.
//
// The list is for a person who watches an agent plan a trip. It holds what has to be done or
// decided: what the COMPILER's report says rules out every plan, the cases in which it says
// the trip works, what it warns of, and the OPTIONs of a plan that no LOCK decides.
//
// Nothing here judges a TRIP. What rules out every plan, what the FILE does not say and what
// could go wrong are for the COMPILER to say: each such item is a line of the report, in the
// report's own words, and it is tied like that line. What the report says further of an item,
// or of all of them, stays with it, in the report's own lines: a case can hold only under a
// condition that the report states on another line. Which PERSON a LOCK names for an OPTION
// is in the FILE, and the view sends it with each step.

import { casesIn, listed, ruledOut, someone, toBuyIn } from "./named.js";
import { clock, clocksOf, dateName } from "./times.js";

/** When a step of a plan happens: Saturday 15 May 2027, 3:00 pm to 4:00 pm. */
function whenOf(step) {
  return `${dateName(step.start.at)}, ${clock(step.start)} to ${step.end === null ? "an unknown time" : clock(step.end, step.start)}`;
}

/**
 * What the page lists as open about a TRIP as the view sends it, or nothing where the page has
 * no report on that TRIP, or where the report in words does not state what the report as JSON
 * names. Half a list would read as the whole.
 *
 * `report` is the report as JSON. `stated` holds the report's own words, as lines.js finds
 * them: the line of each record with the line over them, the line of each case in which the
 * trip works with the heading over them and the lines under it, what the report says after
 * those, and what it warns of at each step.
 *
 * The list is in `groups`, each with its `kind`, its heading in `says`, and its `items`:
 *
 * - `conflict`, for a TRIP that cannot work: each FACT, WANT and DECISION that the report
 *   names as ruling out every plan, by its id and with its line. The heading is the report's
 *   own line over them.
 * - `cases`, for a TRIP that depends on what the FILE does not say: each case in which the
 *   report says the trip works, with its line.
 * - `warnings`, for a plan: each thing that the report warns of at a step, with the step.
 * - `choices`, for a plan: each OPTION of the plan with the PERSONs in it whom no LOCK names
 *   for it. The COMPILER chose it for them, and nobody has decided it.
 *
 * An item has a `name`, what is said of it in `says`, and `when` it happens where it is a
 * step. `of` holds what it is a drawing of, as the page names things: its step, and whatever
 * else its line of the report is about, such as the OFFER that somebody still has to buy a
 * place of. `records` holds what it is tied to: a record by its id, or a case under a name
 * that no record can have. So pointing at an item lights up what a line of the report about it
 * would. `mark` says how it is marked: "clash" where the report names it in what rules out
 * every plan, "asked" where the report names it in what the FILE does not say, "warned" where
 * the report warns of it. `more` holds the lines that the report sets under the item's own,
 * each with its words in `says` and what it is `of`. `who` says which PERSONs a purchase is
 * for, where the report in words does not name them as the page does.
 *
 * `also`, of a group, holds what the report says after the items: each of its paragraphs as
 * the list of its lines, like `more`. A report that shows no plan says nothing else, so the
 * list leaves out no condition under which a case holds or a record rules out every plan.
 *
 * `count` is how many items there are. `clash` and `asked` say that the list holds something
 * that is marked red, or yellow.
 */
export function open(trip, report = null, stated = null) {
  const none = { says: "", count: 0, clash: false, asked: false, groups: [] };
  if (trip === null || stated === null || report === null || typeof report !== "object") return none;
  const item = (name, says, more = {}) => ({ name, says, who: "", when: null, of: [], records: [], mark: "", more: [], ...more });
  // Lines that the list takes from the report as they are, each with what it is of.
  const further = (lines) => lines.map((line) => ({ says: line.says, of: line.about }));
  const group = (kind, says, items, also = []) => ({ kind, says, items, also: also.map(further) });
  if (report.answer === "INFEASIBLE") {
    const records = [...ruledOut(report)];
    // The report in words names each of them under one line. Where it does not, the page
    // cannot say what rules out every plan.
    if (!records.length || typeof stated.conflict !== "string" || records.some((id) => typeof stated.records[id] !== "string")) return none;
    const items = records.map((id) => item(id, stated.records[id], { records: [id], mark: "clash" }));
    return { says: "No plan works.", count: items.length, clash: true, asked: false, groups: [group("conflict", stated.conflict, items, stated.also)] };
  }
  if (report.answer === "UNDETERMINED") {
    const cases = casesIn(report);
    if (!cases.length || cases.some((_, n) => typeof stated.cases[n] !== "string")) return none;
    const items = cases.map((_, n) => item("", stated.cases[n], { records: [`case:${n}`], mark: "asked", more: further(stated.under[n] ?? []) }));
    return { says: "The FILE does not say enough to tell whether this trip works.", count: items.length, clash: false, asked: true, groups: [group("cases", stated.heading ?? "", items, stated.also)] };
  }
  if (report.answer !== "FEASIBLE" || trip.itinerary !== true || !stated.whole) return none;
  const clocks = typeof trip.zone === "string" ? clocksOf(trip.zone) : "";
  const person = new Map(trip.persons.map((each) => [each.id, someone(each.name)]));
  const steps = trip.steps.map((step, n) => ({ ...step, n, name: step.name ?? "another WAY" }));
  // A warning that somebody still has to buy a right is tied to its OFFER, and the report as
  // JSON says who buys from that OFFER for that OPTION. The report in words names them by its
  // own rule. Where that is not how the page names them, the item says who they are here.
  const buyers = (step, warned) => {
    const offers = warned.about.flatMap((thing) => (thing.startsWith("offer:") ? [thing.slice("offer:".length)] : []));
    const ids = new Set(toBuyIn(report).flatMap((buy) => (buy.option === step.option && offers.includes(buy.offer) && Array.isArray(buy.persons) ? buy.persons : [])));
    const names = trip.persons.flatMap((each) => (ids.has(each.id) ? [person.get(each.id)] : []));
    return names.some((name) => !warned.says.includes(name)) ? `On this page, that is ${listed(names)}.` : "";
  };
  const warnings = steps.flatMap((step) => (stated.warnings[step.n] ?? []).map((warned) => item(step.name, warned.says, { who: buyers(step, warned), when: whenOf(step), of: [String(step.n), ...warned.about], mark: "warned" })));
  const choices = steps.flatMap((step) => {
    const free = step.option === null ? [] : step.persons.filter((id) => !step.locked.includes(id));
    return free.length ? [item(step.name, listed(free.map((id) => person.get(id))), { when: whenOf(step), of: [String(step.n)] })] : [];
  });
  const groups = [...(warnings.length ? [group("warnings", "The report warns:", warnings)] : []), ...(choices.length ? [group("choices", "No LOCK names these PERSONs for these OPTIONs of the plan:", choices)] : [])];
  const count = warnings.length + choices.length;
  const says = count ? `${count === 1 ? "1 thing is" : `${count} things are`} open.${clocks}` : "Nothing is open. The report gives no warnings, and a LOCK names each PERSON for every OPTION they take part in.";
  return { says, count, clash: false, asked: warnings.length > 0, groups };
}
