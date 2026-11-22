// Every WAY of a FILE, and the travel that the FILE says it lists in full, as the page shows
// them. There is no page in here, so the tests run this as it is.
//
// The view sends each WAY with what the FILE says of it: the PLACEs it goes between, whether a
// PERSON can take it in both directions, and how long it takes. It sends each FACT that the
// FILE lists every way of some travel: from which PLACE, to which, and within which span of
// time. This puts both in words, as the report words them, and says plainly what the FILE does
// not say. Where the report shows a plan, it says who takes each WAY in that plan, and when.
// It marks what the report names: the records that rule out every plan, and the cases in which
// a trip that depends on something works.
//
// Nothing here judges a TRIP. A WAY that no plan uses is shown like any other: it is in the
// FILE.

import { listed, marksBy } from "./named.js";
import { clock, clocksOf, dateName, lasts } from "./times.js";

/** Where a WAY goes, and in which direction a PERSON can take it. */
function whereOf(way, place) {
  return way.both_ways ? `Between ${place(way.from)} and ${place(way.to)}, in both directions.` : `From ${place(way.from)} to ${place(way.to)}, in that direction only.`;
}

/**
 * Which travel a FACT says that the FILE lists in full, as the report words it. A PLACE that
 * the FACT leaves out stands for every PLACE. The span includes both of its ends.
 */
function travelOf(fact, place) {
  const from = fact.from === null ? null : place(fact.from);
  const to = fact.to === null ? null : place(fact.to);
  const which = from === null && to === null ? "Every way from one PLACE straight to another" : from === null ? `Every way straight to ${to}` : to === null ? `Every way straight from ${from}` : `Every way straight from ${from} to ${to}`;
  return `${which} that leaves between ${clock(fact.earliest)} on ${dateName(fact.earliest.at)} and ${clock(fact.latest, fact.earliest)} is listed.`;
}

/**
 * What the page shows of the WAYs of a TRIP as the view sends it, or of no TRIP where the view
 * sends none.
 *
 * Each WAY has its name, `where` it goes, and how long it `takes`. `plan` holds a sentence for
 * each time somebody takes it in the plan of the report, or one that says nobody does, and is
 * empty where the report shows no plan. `steps` holds the steps of the TRIP in which somebody
 * takes it. `travel` holds each FACT that the FILE lists every way of some travel, with what
 * it `says`.
 *
 * `report` is the report as JSON, where the page has one. `clash` on a WAY or on such a FACT
 * holds its `records` that the report names as ruling out every plan, and `finds` says so.
 * `cases` on a WAY holds the cases that name it among what the FILE does not say, as their
 * places in `missing` of the report, and `asks` holds what the report says of them. `stated`
 * holds the words of the report for those cases, as lines.js finds them. `clash` and `asked`
 * on the whole say that something here is marked so.
 */
export function ways(trip, report = null, stated = null) {
  if (trip === null || (!trip.ways.length && !trip.complete_travel.length)) return { says: "", clash: false, asked: false, ways: [], travel: [] };
  const person = new Map(trip.persons.map((each) => [each.id, each.name]));
  const places = new Map(trip.places.map((each) => [each.id, each.name]));
  const place = (id) => places.get(id);
  const marked = marksBy(report, stated);
  const shown = trip.ways.map((way) => {
    const steps = trip.steps.flatMap((step, at) => (step.way === way.id ? [at] : []));
    const taken = steps.map((at) => {
      const { persons, start } = trip.steps[at];
      const takers = persons.map((id) => person.get(id));
      return `In the plan: ${listed(takers)} ${takers.length === 1 ? "takes" : "take"} it at ${clock(start)} on ${dateName(start.at)}.`;
    });
    return {
      id: way.id,
      name: way.name,
      where: whereOf(way, place),
      takes: lasts(way.length),
      plan: !trip.itinerary ? [] : taken.length ? taken : ["Not in the plan."],
      steps,
      ...marked(way.records, (need) => need.way === way.id, "The report names this WAY in what the FILE does not say."),
    };
  });
  const travel = trip.complete_travel.map((fact) => {
    const { records, clash, finds } = marked([fact.record], () => false, "");
    return { record: fact.record, says: travelOf(fact, place), records, clash, finds };
  });
  const clash = [...shown, ...travel].some((each) => each.clash.length > 0);
  const asked = shown.some((each) => each.cases.length > 0);
  const timed = travel.length > 0 || shown.some((way) => way.steps.length > 0);
  const says =
    (!shown.length ? "The FILE has no WAY. It says which travel it lists in full." : `Every WAY of the FILE, with what the FILE says of it${travel.length ? ", and the travel that the FILE says it lists in full" : ""}.`) +
    (timed ? clocksOf(trip.zone) : "") +
    (clash ? " A red edge marks what the report names among what rules out every plan." : "") +
    (asked ? " A yellow edge marks what the report names in what the FILE does not say." : "");
  return { says, clash, asked, ways: shown, travel };
}
