// The WANTs of a FILE, as the page shows them. There is no page in here, so the tests run this
// as it is.
//
// The view sends the WANTs with each report: for whom each is a must or a must-not, the PLACE
// where a WANT has its holders end the TRIP, and each OPTION that a FACT says SATISFIES the
// WANT or does not. This puts them in words. Beside each of those OPTIONs it says who takes
// part in it in the plan of the report, or whom a LOCK names for it where the report shows no
// plan, as the calendar does. It marks what the report names: the records that rule out every
// plan, and the cases in which a trip that depends on something works.
//
// Nothing here judges a TRIP. Whether an ITINERARY SATISFIES a WANT is for the COMPILER to say:
// the page puts the WANT, its OPTIONs and who takes part side by side, and says no more.

import { listed, marksBy } from "./named.js";
import { whoIsIn } from "./who.js";

/**
 * For whom a WANT is a must, and for whom a must-not. A WANT about where the TRIP ends says
 * what it asks of its holders: another WANT can ask other PERSONs to end somewhere else. It
 * is a must for each of them.
 */
function holdsOf(want, name, place) {
  if (want.ends_at !== null) return `${listed(want.musts.map(name))} must end the TRIP at ${place(want.ends_at)}.`;
  const said = [];
  if (want.musts.length) said.push(`A must for ${listed(want.musts.map(name))}.`);
  if (want.must_nots.length) said.push(`A must-not for ${listed(want.must_nots.map(name))}.`);
  return said.join(" ");
}

/**
 * Whether the OPTIONs under a WANT are all that SATISFY it, as far as the FILE says. It never
 * says that an OPTION SATISFIES the WANT where the FILE names none that does.
 */
function wholeOf(want) {
  if (want.ends_at !== null) return null;
  const some = want.options.some((option) => option.degree > 0);
  if (want.complete !== null) return some ? "The FILE states every OPTION that SATISFIES it." : "The FILE states every OPTION that SATISFIES it, and it names none.";
  if (some) return "Other OPTIONs may SATISFY it too: the FILE does not say that these are all.";
  return want.options.length ? "The FILE leaves open whether another OPTION SATISFIES this WANT." : "The FILE says of no OPTION whether it SATISFIES this WANT.";
}

/**
 * What the page shows of the WANTs of a TRIP as the view sends it, or of no TRIP where the
 * view sends none.
 *
 * Each WANT has its name, for whom it is a must or a must-not (`holds`), what it says of the
 * end of the TRIP (`ends`), and whether its OPTIONs are all that SATISFY it (`whole`). Each of
 * its `options` has its name, what the FILE says of it (`says`), who takes part (`takes`), and
 * the `step` of the TRIP that it is, where the calendar holds it.
 *
 * `report` is the report as JSON, where the page has one. `clash` on a WANT or on one of its
 * OPTIONs holds its `records` that the report names as ruling out every plan, and `finds` says
 * so. `cases` holds the cases that name it among what the FILE does not say, as their places
 * in `missing` of the report, and `asks` holds what the report says of them. `stated` holds
 * the words of the report for those cases, as lines.js finds them. `clash` and `asked` on the
 * whole say that something here is marked so.
 */
export function wants(trip, report = null, stated = null) {
  if (trip === null || !trip.wants.length) return { says: "", clash: false, asked: false, wants: [] };
  const person = new Map(trip.persons.map((each) => [each.id, each.name]));
  const place = new Map(trip.places.map((each) => [each.id, each.name]));
  const name = (id) => person.get(id);
  const who = whoIsIn(trip);
  const marked = marksBy(report, stated);
  const shown = trip.wants.map((want) => ({
    id: want.id,
    name: want.name,
    holds: holdsOf(want, name, (id) => place.get(id)),
    ends: want.ends_at === null ? null : "It is about the whole ITINERARY: no OPTION delivers it.",
    whole: wholeOf(want),
    // A WANT's own records: itself, and the FACT that the FILE states every OPTION for it.
    ...marked([want.id, ...(want.complete === null ? [] : [want.complete])], (need) => need.want === want.id, "The report names this WANT in what the FILE does not say."),
    options: want.options.map((option) => {
      // In a plan, those who take part. With no plan, those whom a LOCK names.
      const { step, takes } = who(option.option);
      return {
        option: option.option,
        name: option.name,
        degree: option.degree,
        // The report says a DEGREE OF SATISFACTION so: 9 out of 10.
        says: option.degree > 0 ? `SATISFIES it, ${option.degree} out of 10` : "does not SATISFY it",
        takes,
        step,
        ...marked([option.record], (need) => need.want === want.id && need.option === option.option, "The report names this OPTION and this WANT in what the FILE does not say."),
      };
    }),
  }));
  const all = shown.flatMap((want) => [want, ...want.options]);
  const clash = all.some((each) => each.clash.length > 0);
  const asked = all.some((each) => each.cases.length > 0);
  const says =
    "The WANTs of the FILE, each with the OPTIONs that the FILE says SATISFY it or do not." +
    (clash ? " A red edge marks what the report names among what rules out every plan." : "") +
    (asked ? " A yellow edge marks what the report names in what the FILE does not say." : "");
  return { says, clash, asked, wants: shown };
}
