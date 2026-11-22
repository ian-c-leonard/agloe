// The OBJECTs of a FILE, as the page shows them. There is no page in here, so the tests run
// this as it is.
//
// The view sends the OBJECTs with each report: where each is when the TRIP starts, each OPTION
// of which a FACT says whether it requires the OBJECT, each OPTION of which a FACT says that
// it hands the OBJECT over, keeps it or leaves it alone, and the FACTs that the FILE states
// every OPTION of each kind. This puts them in words, as the report words them. Beside each
// of those OPTIONs it says who takes part in it, as the other parts of the page do. It marks
// what the report names: the records that rule out every plan, and the cases in which a trip
// that depends on something works.
//
// Nothing here judges a TRIP. Where an OBJECT is in a plan, and whether it is at hand for an
// OPTION that requires it, is for the COMPILER to say: the report says it, and the page ties
// those lines to the OBJECT.

import { atHandFor, marksBy } from "./named.js";
import { whoIsIn } from "./who.js";

/** What a case of a report can need that is about whether an OPTION requires an OBJECT. */
const ABOUT_REQUIRING = new Set(["does not require"]);
/** What a case of a report can need that is about what an OPTION does with an OBJECT. */
const ABOUT_MOVING = new Set(["hands over", "keeps", "does not keep"]);

/** What an OPTION does with an OBJECT, as the report words it. */
const DOES = { hands_over: "it can be handed over here", keeps: "keeps it", nothing: "leaves it alone" };

/**
 * Whether the OPTIONs under an OBJECT are all that require it, as far as the FILE says.
 * `others` says that the FILE has an OPTION with no FACT about whether it requires the OBJECT.
 * It never says that an OPTION requires the OBJECT where the FILE names none that does.
 */
function requiredBy(thing, others) {
  const some = thing.requires.some((each) => each.needed);
  if (thing.requires_complete !== null) return some ? "The FILE states every one of its OPTIONs that requires it." : "The FILE states every one of its OPTIONs that requires it, and it names none.";
  if (!others) return thing.requires.length ? "The FILE says of each of its OPTIONs whether it requires this OBJECT." : "The FILE lists no OPTION.";
  if (some) return "Other OPTIONs of the FILE may require it too: the FILE does not say that these are all.";
  return thing.requires.length ? "The FILE leaves open whether another of its OPTIONs requires this OBJECT." : "The FILE says of no OPTION whether it requires this OBJECT.";
}

/**
 * Whether the OPTIONs under an OBJECT are all that hand it over or keep it, as far as the FILE
 * says. Without a FACT that they are, another OPTION may, in the FILE or outside it.
 */
function movedBy(thing) {
  const some = thing.transfers.some((each) => each.does !== "nothing");
  if (thing.transfers_complete === null) return "Another OPTION may hand it over or keep it: the FILE does not say that these are all.";
  return some ? "The FILE states every OPTION that hands it over or keeps it." : "The FILE states every OPTION that hands it over or keeps it, and it names none.";
}

/**
 * What the page shows of the OBJECTs of a TRIP as the view sends it, or of no TRIP where the
 * view sends none.
 *
 * Each OBJECT has its name, where it is when the TRIP starts (`starts`), the OPTIONs of which
 * the FILE says whether they require it (`requires`), those of which the FILE says what they
 * do with it (`transfers`), and in `whole` whether each of those lists is all there is. Each
 * OPTION has its name, what the FILE says of it and the OBJECT (`says`), who takes part
 * (`takes`), and the `step` of the TRIP that it is, where the calendar holds it. `does` says
 * that the OPTION requires the OBJECT, or hands it over or keeps it.
 *
 * `report` is the report as JSON, where the page has one. `clash` on an OBJECT or on one of
 * its OPTIONs holds its `records` that the report names as ruling out every plan, and `finds`
 * says so. `cases` holds the cases that name it among what the FILE does not say, as their
 * places in `missing` of the report, and `asks` holds what the report says of them. `stated`
 * holds the words of the report for those cases, as lines.js finds them. `clash` and `asked`
 * on the whole say that something here is marked so.
 */
export function objects(trip, report = null, stated = null) {
  if (trip === null || !trip.objects.length) return { says: "", clash: false, asked: false, objects: [] };
  const people = new Map(trip.persons.map((each) => [each.id, each.name]));
  const places = new Map(trip.places.map((each) => [each.id, each.name]));
  const who = whoIsIn(trip);
  const marked = marksBy(report, stated);
  const shown = trip.objects.map((thing) => {
    // An OPTION under the OBJECT shows one thing of the two: whether it requires the OBJECT,
    // or what it does with it. A case marks it where the case is about that. An OPTION that
    // requires the OBJECT is also marked where a case has the OBJECT at hand for it.
    const under = (each, does, says, kinds, atHand) => {
      const { step, takes } = who(each.option);
      const about = (need) => need.object === thing.id && ((need.option === each.option && kinds.has(need.what)) || (atHand && atHandFor(need).includes(each.option)));
      return {
        option: each.option,
        name: each.name,
        does,
        says,
        takes,
        step,
        ...marked([each.record], about, "The report names this OPTION and this OBJECT in what the FILE does not say."),
      };
    };
    const asked = new Set(thing.requires.map((each) => each.option));
    const { starts } = thing;
    // The report says it so: Alex has the bags when the TRIP starts, the TRIP starts with the
    // bags at the hotel.
    const where = starts === null ? "The FILE does not say where it is when the TRIP starts." : starts.person !== null ? `${people.get(starts.person)} has it when the TRIP starts.` : `The TRIP starts with it at ${places.get(starts.place)}.`;
    return {
      id: thing.id,
      name: thing.name,
      starts: where,
      requires: thing.requires.map((each) => under(each, each.needed, each.needed ? "requires it" : "does not require it", ABOUT_REQUIRING, true)),
      transfers: thing.transfers.map((each) => under(each, each.does !== "nothing", DOES[each.does], ABOUT_MOVING, false)),
      whole: [requiredBy(thing, trip.options.some((option) => !asked.has(option.id))), movedBy(thing)],
      // An OBJECT's own records: the FACT about where it is when the TRIP starts, and the FACTs
      // that the FILE states every OPTION that requires it, and every one that moves it.
      ...marked(
        [...(starts === null ? [] : [starts.record]), ...[thing.requires_complete, thing.transfers_complete].filter((id) => id !== null)],
        (need) => need.object === thing.id,
        "The report names this OBJECT in what the FILE does not say.",
      ),
    };
  });
  const all = shown.flatMap((thing) => [thing, ...thing.requires, ...thing.transfers]);
  const clash = all.some((each) => each.clash.length > 0);
  const asked = all.some((each) => each.cases.length > 0);
  const says =
    "The OBJECTs of the FILE, each with where it is when the TRIP starts, the OPTIONs that the FILE says require it, and those that it says hand it over or keep it." +
    (clash ? " A red edge marks what the report names among what rules out every plan." : "") +
    (asked ? " A yellow edge marks what the report names in what the FILE does not say." : "");
  return { says, clash, asked, objects: shown };
}
