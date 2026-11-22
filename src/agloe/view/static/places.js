// Every PLACE of a FILE, as the page shows them. There is no page in here, so the tests run
// this as it is.
//
// The view sends the PLACEs. With the other things of the FILE it sends where each of them
// is: each FACT about where a PERSON starts from, where each OBJECT is when the TRIP starts,
// the PLACE or the two PLACEs of each OPTION, the PLACEs that each WAY goes between, and each
// WANT about where the TRIP ends. This says of each PLACE what the FILE puts there. It marks
// what the report names: the records that rule out every plan, and the cases in which a trip
// that depends on something works.
//
// Nothing here judges a TRIP. Who is at a PLACE at a time of a plan is for the COMPILER to
// say: the calendar shows the plan of the report.

import { listed, marksBy } from "./named.js";
import { lasts } from "./times.js";
import { whoIsIn } from "./who.js";

/**
 * What the page shows of the PLACEs of a TRIP as the view sends it, or of no TRIP where the
 * view sends none.
 *
 * Each PLACE has its name. `holds` has a sentence for the PERSONs that the FILE says start
 * from it, one for each OBJECT that the FILE says is there when the TRIP starts, and one for
 * each WANT that has PERSONs end the TRIP there. A PLACE that nothing in the FILE is at says
 * so. `options` holds each OPTION that happens at the PLACE, or goes from it or to it: its
 * name, what it does there (`says`), who takes part (`takes`), and the `step` of the TRIP that
 * it is, where the calendar holds it. `ways` holds each WAY that goes from the PLACE or to it:
 * its name, where it goes (`says`), how long it takes (`takes`), and the `steps` of the TRIP
 * in which somebody takes it.
 *
 * `report` is the report as JSON, where the page has one. `clash` on a PLACE holds its
 * `records` that the report names as ruling out every plan, and `finds` says so: the FACTs
 * about who and what starts there, and the WANTs about ending the TRIP there. `cases` holds
 * the cases that name the PLACE among what the FILE does not say, as their places in `missing`
 * of the report: that an OBJECT is there when the TRIP starts, or that there are other WAYs
 * from it or to it. `asks` holds what the report says of them. `stated` holds the words of the
 * report for those cases, as lines.js finds them. `clash` and `asked` on the whole say that a
 * PLACE here is marked so.
 */
export function places(trip, report = null, stated = null) {
  if (trip === null || !trip.places.length) return { says: "", clash: false, asked: false, places: [] };
  const people = new Map(trip.persons.map((each) => [each.id, each.name]));
  const named = new Map(trip.places.map((each) => [each.id, each.name]));
  const who = whoIsIn(trip);
  const marked = marksBy(report, stated);
  // An OPTION or a WAY under a PLACE has no FACT about the two: where it is, is part of what
  // it is. So it has no record, and no case names the two.
  const plain = () => marked([], () => false, "");
  const shown = trip.places.map(({ id, name }) => {
    const starters = trip.starts_from.filter((fact) => fact.place === id);
    const things = trip.objects.filter((thing) => thing.starts !== null && thing.starts.place === id);
    const ends = trip.wants.filter((want) => want.ends_at === id);
    const from = starters.map((fact) => people.get(fact.person));
    const holds = [
      ...(from.length ? [`${listed(from)} ${from.length === 1 ? "starts" : "start"} from here.`] : []),
      ...things.map((thing) => `The TRIP starts with ${thing.name} here.`),
      // A WANT about where the TRIP ends is a must for some of its holders, and a must-not for others.
      ...ends.flatMap((want) => [
        ...(want.musts.length ? [`${listed(want.musts.map((person) => people.get(person)))} must end the TRIP here.`] : []),
        ...(want.must_nots.length ? [`${listed(want.must_nots.map((person) => people.get(person)))} must not end the TRIP here.`] : []),
      ]),
    ];
    const options = trip.options
      .filter((option) => option.from === id || option.to === id)
      .map((option) => {
        const { step, takes } = who(option.id);
        const says = option.from === option.to ? "happens here" : option.from === id ? `goes from here to ${named.get(option.to)}` : `comes here from ${named.get(option.from)}`;
        return { option: option.id, name: option.name, says, takes, step, ...plain() };
      });
    const ways = trip.ways
      .filter((way) => way.from === id || way.to === id)
      .map((way) => {
        const other = named.get(way.from === id ? way.to : way.from);
        const says = way.both_ways ? `between here and ${other}, in both directions` : way.from === id ? `from here to ${other}, in that direction only` : `from ${other} to here, in that direction only`;
        const steps = trip.steps.flatMap((step, at) => (step.way === way.id ? [at] : []));
        return { way: way.id, name: way.name, says, takes: lasts(way.length), steps, ...plain() };
      });
    return {
      id,
      name,
      holds: holds.length || options.length || ways.length ? holds : ["Nothing in the FILE is at this PLACE."],
      options,
      ways,
      // A PLACE's own records: the FACTs about who and what starts there, and the WANTs about
      // ending the TRIP there. A case names it where an OBJECT is there when the TRIP starts,
      // or where there are other WAYs from it or to it.
      ...marked(
        [...starters.map((fact) => fact.record), ...things.map((thing) => thing.starts.record), ...ends.map((want) => want.id)],
        (need) => need.place === id || need.from === id || need.to === id,
        "The report names this PLACE in what the FILE does not say.",
      ),
    };
  });
  const clash = shown.some((each) => each.clash.length > 0);
  const asked = shown.some((each) => each.cases.length > 0);
  const says =
    "Every PLACE of the FILE, with what the FILE puts there: who starts from it, and the OPTIONs and the WAYs that are at it or go from it or to it." +
    (clash ? " A red edge marks what the report names among what rules out every plan." : "") +
    (asked ? " A yellow edge marks what the report names in what the FILE does not say." : "");
  return { says, clash, asked, places: shown };
}
