// Who is in an OPTION of a FILE, and whether they need a right to be, as the page says it.
// There is no page in here, so the tests run this as it is.
//
// The view sends every OPTION with the PERSONs that a LOCK names for it, the steps of the
// plan of the report with who takes part in each, and the FACT about whether a PERSON needs a
// right to take part in an OPTION. Each part of the page that shows an OPTION says the same
// of it, in the same words.

import { listed, someone } from "./named.js";

/**
 * Whether a PERSON needs a right to take part in each OPTION of a TRIP as the view sends it,
 * as far as the FILE says: give it the id of an OPTION. `needed` is yes, no, or null where
 * the FILE does not say, and `says` puts it in words.
 */
export function needsARight(trip) {
  const stated = new Map(trip.rights.map((each) => [each.option, each.needs]));
  return (id) => {
    const needed = stated.get(id)?.needed ?? null;
    const says = needed === null ? "The FILE does not say whether people need a right to take part." : needed ? "People need a right to take part." : "Nobody needs a right to take part.";
    return { needed, says };
  };
}

/**
 * What the page says of who is in each OPTION of a TRIP as the view sends it: give it the id
 * of an OPTION.
 *
 * `step` is the step of the TRIP that the OPTION is, where the calendar holds one. `lock` says
 * whom a LOCK names for it. `plan` says who takes part in it in the plan of the report, and is
 * null where the report shows no plan. `takes` is the one of the two for a part with room for
 * one: the plan, where the report shows one.
 */
export function whoIsIn(trip) {
  const person = new Map(trip.persons.map((each) => [each.id, each.name]));
  // A PERSON who is called nobody is told from nobody at all.
  const names = (ids) => ids.map((id) => someone(person.get(id)));
  return (id) => {
    const step = trip.steps.findIndex((each) => each.option === id);
    const locked = names(trip.options.find((each) => each.id === id)?.locked ?? []);
    const takers = step < 0 ? [] : names(trip.steps[step].persons);
    // One LOCK can name several PERSONs, and several LOCKs one each: the words fit both.
    const lock = locked.length ? `${listed(locked)} ${locked.length === 1 ? "is" : "are each"} named by a LOCK.` : "No LOCK names it.";
    // An OPTION of the plan can have nobody in it: a luggage service carries the bags.
    const empty = step < 0 ? "Not in the plan." : "In the plan, with nobody of the TRIP in it.";
    const taking = takers.length ? `In the plan: ${listed(takers)} ${takers.length === 1 ? "takes" : "take"} part.` : empty;
    const plan = trip.itinerary ? taking : null;
    return { step: step < 0 ? null : step, lock, plan, takes: plan ?? lock };
  };
}
