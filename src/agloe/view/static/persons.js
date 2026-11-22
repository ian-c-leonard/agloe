// Every PERSON of a FILE, as the page shows them. There is no page in here, so the tests run
// this as it is.
//
// The view sends the PERSONs, each FACT about where a PERSON starts from, and the WANTs. This
// says of each PERSON where the FILE says they start from, or that it does not say, and where
// a WANT has them end the TRIP. It marks what the report names: the records that rule out
// every plan, and the cases in which a trip that depends on something works.
//
// Nothing here judges a TRIP. Where a PERSON's path begins and ends in a plan is for the
// COMPILER to say: the page shows what the FILE states about the two.

import { marksBy } from "./named.js";

/**
 * What the page shows of the PERSONs of a TRIP as the view sends it, or of no TRIP where the
 * view sends none.
 *
 * Each PERSON has their name, `where` they start from as far as the FILE says, and in `ends` a
 * sentence for each WANT that has them end the TRIP at a PLACE, or not end it there.
 *
 * `report` is the report as JSON, where the page has one. `clash` on a PERSON holds the FACT
 * about where they start from, where the report names it as ruling out every plan, and `finds`
 * says so. `cases` holds the cases that name the PERSON among what the FILE does not say, as
 * their places in `missing` of the report, and `asks` holds what the report says of them.
 * `stated` holds the words of the report for those cases, as lines.js finds them. `clash` and
 * `asked` on the whole say that somebody here is marked so.
 */
export function persons(trip, report = null, stated = null) {
  if (trip === null || !trip.persons.length) return { says: "", clash: false, asked: false, persons: [] };
  const places = new Map(trip.places.map((each) => [each.id, each.name]));
  const start = new Map(trip.starts_from.map((fact) => [fact.person, fact]));
  const marked = marksBy(report, stated);
  // A WANT about where the TRIP ends is a must for some of its holders, and a must-not for others.
  const endsOf = (id) =>
    trip.wants.flatMap((want) => {
      if (want.ends_at === null) return [];
      const at = places.get(want.ends_at);
      return want.musts.includes(id) ? [`Must end the TRIP at ${at}.`] : want.must_nots.includes(id) ? [`Must not end the TRIP at ${at}.`] : [];
    });
  const shown = trip.persons.map(({ id, name }) => {
    const fact = start.get(id) ?? null;
    return {
      id,
      name,
      where: fact === null ? "The FILE does not say where this PERSON starts from." : `Starts from ${places.get(fact.place)}.`,
      ends: endsOf(id),
      ...marked(fact === null ? [] : [fact.record], (need) => need.person === id, "The report names this PERSON in what the FILE does not say."),
    };
  });
  const clash = shown.some((each) => each.clash.length > 0);
  const asked = shown.some((each) => each.cases.length > 0);
  const says =
    "Every PERSON of the FILE, with where the FILE says they start from." +
    (shown.some((each) => each.ends.length > 0) ? " Where a WANT has a PERSON end the TRIP at a PLACE, the row says so." : "") +
    (clash ? " A red edge marks what the report names among what rules out every plan." : "") +
    (asked ? " A yellow edge marks what the report names in what the FILE does not say." : "");
  return { says, clash, asked, persons: shown };
}
