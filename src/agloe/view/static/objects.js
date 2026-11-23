// The OBJECTs of a FILE, as the page shows them. There is no page in here, so the tests run
// this as it is.
//
// The view sends the OBJECTs with each report: where each is when the TRIP starts, each OPTION
// of which a FACT says whether it requires the OBJECT, each OPTION of which a FACT says
// whether it refuses the OBJECT, each OPTION of which a FACT says that it hands the OBJECT
// over, keeps it or leaves it alone, and the FACTs that the FILE states every OPTION of each
// kind. This puts them in words, as the report words them. Beside each
// of those OPTIONs it says who takes part in it, as the other parts of the page do. It marks
// what the report names: the records that rule out every plan, and the cases in which a trip
// that depends on something works.
//
// Nothing here judges a TRIP. Where an OBJECT is in a plan, whether it is at hand for an
// OPTION that requires it, and whether a PERSON has it in an OPTION that refuses it, is for
// the COMPILER to say: the report says it, the page ties
// those lines to the OBJECT, and the card of the OBJECT says the same, worded as the report
// words it, from what the report as JSON holds.

import { atHandFor, carriedIn, either, listed, marksBy } from "./named.js";
import { clock, clocksOf } from "./times.js";
import { whoIsIn } from "./who.js";

/** What a case of a report can need that is about whether an OPTION requires an OBJECT. */
const ABOUT_REQUIRING = new Set(["does not require"]);
/** What a case of a report can need that is about whether an OPTION refuses an OBJECT. */
const ABOUT_REFUSING = new Set(["does not refuse"]);
/** What a case of a report can need that is about what an OPTION does with an OBJECT. */
const ABOUT_MOVING = new Set(["hands over", "keeps", "does not keep"]);

/**
 * How an OBJECT came to be where it is from the start of an OPTION, as the report words it:
 * give it the name of the OPTION and the name of the OBJECT.
 */
const HOW = new Map([
  ["handed over", (option) => `handed over in ${option}`],
  ["kept", (option) => `kept by ${option}`],
  ["might be kept", (option, thing) => `the FILE does not say what ${option} does with ${thing}`],
]);

/** What an OPTION does with an OBJECT, as the report words it. */
const DOES = { hands_over: "it can be handed over here", keeps: "keeps it", nothing: "leaves it alone" };

/**
 * Whether the OPTIONs under an OBJECT are all that require it, and all that refuse it, as far
 * as the FILE says. One FACT says both, so where the FILE has it, this is one line. Without
 * it, there is a line for each: `silent` says, for "requires" and for "refuses", that the
 * FILE has an OPTION with no FACT about whether it does that. It never says that an OPTION
 * requires or refuses the OBJECT where the FILE names none that does.
 */
function checkedBy(thing, silent) {
  const requires = thing.requires.some((each) => each.needed);
  const refuses = thing.refuses.some((each) => each.refused);
  if (thing.requires_complete !== null) {
    const all = "The FILE states every one of its OPTIONs that requires it or refuses it";
    return [requires || refuses ? `${all}.` : `${all}, and it names none.`];
  }
  const one = (stated, some, others, does, verb) => {
    if (!others) return stated.length ? `The FILE says of each of its OPTIONs whether it ${does} this OBJECT.` : "The FILE lists no OPTION.";
    if (some) return `Other OPTIONs of the FILE may ${verb} it too: the FILE does not say that these are all.`;
    return stated.length ? `The FILE leaves open whether another of its OPTIONs ${does} this OBJECT.` : `The FILE says of no OPTION whether it ${does} this OBJECT.`;
  };
  return [one(thing.requires, requires, silent.requires, "requires", "require"), one(thing.refuses, refuses, silent.refuses, "refuses", "refuse")];
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
 * the FILE says whether they require it (`requires`), those of which the FILE says whether
 * they refuse it (`refuses`), those of which the FILE says what they do with it
 * (`transfers`), and in `whole` whether each of those lists is all there is. Each
 * OPTION has its name, what the FILE says of it and the OBJECT (`says`), who takes part
 * (`takes`), and the `step` of the TRIP that it is, where the calendar holds it. `does` says
 * that the OPTION requires the OBJECT, refuses it, or hands it over or keeps it.
 *
 * Where the report shows a plan and says where each OBJECT is in it, the page says the same,
 * worded as the report words it, with each name as the page shows it. `plan` on an OBJECT
 * says where it is throughout the plan. `plan` on an OPTION that requires it or refuses it
 * says where it is just before that OPTION starts. `might` holds each OPTION of the plan of
 * which the report says that the FILE does not say whether it requires the OBJECT, or
 * whether it refuses it, with the same. Where the report names something that the TRIP does
 * not hold, nothing is said of that OBJECT.
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
  const named = new Map(trip.options.map((each) => [each.id, each.name]));
  // When each OPTION of the plan starts, and the first step of the plan: a time has its date
  // where it is not on the day that the plan starts.
  const startOf = new Map(trip.itinerary ? trip.steps.flatMap((step) => (step.option === null ? [] : [[step.option, step.start]])) : []);
  const first = trip.itinerary && trip.steps.length ? trip.steps[0].start : null;
  // Where an OBJECT is, or each place it might be: with Alex or at the Art Institute. Each
  // name is as "or" joins it, as in the report. A place with no name is somewhere the FILE
  // does not name, and an OBJECT that might be with any PERSON, at any PLACE or somewhere the
  // FILE does not name is nobody knows where. Null where the TRIP has no such PERSON or PLACE.
  const whereIs = (where) => {
    const one = (each) => {
      if (typeof each.person === "string") return people.has(each.person) ? `with ${either(people.get(each.person))}` : null;
      if (each.place === null) return "somewhere the FILE does not name";
      return places.has(each.place) ? `at ${either(places.get(each.place))}` : null;
    };
    const each = where.map(one);
    if (each.includes(null)) return null;
    return where.length === people.size + places.size + 1 ? "nobody knows where" : listed(each, "or");
  };
  const carried = new Map(carriedIn(report).map((each) => [each.object, each]));
  // Whether a card gives a time of the plan. The part then says whose clocks it is on.
  let timed = false;
  const shown = trip.objects.map((thing) => {
    // What the report says of this OBJECT in its plan: where it is from the start of the
    // TRIP on, and where it is just before each OPTION that requires it or refuses it, or
    // might. All of it is said, or nothing: a stay or a use that names something the TRIP
    // does not hold leaves the OBJECT with no word on the plan.
    const said = carried.get(thing.id) ?? null;
    const stays = (said === null ? [] : said.stays).map((stay) => {
      const where = whereIs(stay.where);
      if (where === null || stay.since === null) return where === null ? null : `${where} when the TRIP starts`;
      const how = HOW.get(stay.how);
      if (how === undefined || !startOf.has(stay.since) || !named.has(stay.since)) return null;
      return `${where} from ${clock(startOf.get(stay.since), first)} (${how(named.get(stay.since), thing.name)})`;
    });
    const usesOf = (list, check) => list.map((use) => ({ option: use.option, check, stated: use.stated, where: startOf.has(use.option) ? whereIs(use.where) : null }));
    const all = said === null ? [] : [...usesOf(said.uses, "requires"), ...usesOf(said.refusals, "refuses")];
    const known = stays.length > 0 && !stays.includes(null) && all.every((use) => use.where !== null);
    const uses = known ? all : [];
    timed ||= known && said.stays.some((stay) => stay.since !== null);
    // Where the OBJECT is just before an OPTION starts, where the report says that a FACT
    // has the OPTION require it, or refuse it.
    const before = (option, check) => {
      const use = uses.find((each) => each.option === option && each.check === check && each.stated);
      return use === undefined ? null : `Just before it starts: ${use.where}.`;
    };
    // An OPTION under the OBJECT shows one thing of the three: whether it requires the
    // OBJECT, whether it refuses it, or what it does with it. A case marks it where the case
    // is about that. An OPTION that requires the OBJECT is also marked where a case has the
    // OBJECT at hand for it, and one that refuses it where a case keeps the OBJECT out of it.
    const under = (each, does, says, kinds, check) => {
      const { step, takes } = who(each.option);
      const about = (need) => need.object === thing.id && ((need.option === each.option && kinds.has(need.what)) || (check !== null && atHandFor(need, check).includes(each.option)));
      return {
        option: each.option,
        name: each.name,
        does,
        says,
        takes,
        step,
        plan: check !== null && does ? before(each.option, check) : null,
        ...marked([each.record], about, "The report names this OPTION and this OBJECT in what the FILE does not say."),
      };
    };
    const asked = { requires: new Set(thing.requires.map((each) => each.option)), refuses: new Set(thing.refuses.map((each) => each.option)) };
    // An OPTION of the plan of which the report says that the FILE does not say whether it
    // requires the OBJECT, or whether it refuses it. No FACT is about the two, and no case
    // names them: the plan holds either way.
    const might = uses
      .filter((use) => !use.stated && !asked[use.check].has(use.option))
      .map((use) => {
        const { step, takes } = who(use.option);
        const plan = `Just before it starts: ${use.where}, so the plan holds if it does.`;
        return { option: use.option, name: named.get(use.option), does: false, says: `the FILE does not say whether this ${use.check} it`, takes, step, plan, ...marked([], () => false, "") };
      });
    const { starts } = thing;
    // The report says it so: Alex has the bags when the TRIP starts, the TRIP starts with the
    // bags at the hotel.
    const where = starts === null ? "The FILE does not say where it is when the TRIP starts." : starts.person !== null ? `${people.get(starts.person)} has it when the TRIP starts.` : `The TRIP starts with it at ${places.get(starts.place)}.`;
    return {
      id: thing.id,
      name: thing.name,
      starts: where,
      plan: known ? `In the plan: ${stays.join("; ")}.` : null,
      requires: thing.requires.map((each) => under(each, each.needed, each.needed ? "requires it" : "does not require it", ABOUT_REQUIRING, "requires")),
      refuses: thing.refuses.map((each) => under(each, each.refused, each.refused ? "refuses it" : "does not refuse it", ABOUT_REFUSING, "refuses")),
      might,
      transfers: thing.transfers.map((each) => under(each, each.does !== "nothing", DOES[each.does], ABOUT_MOVING, null)),
      whole: [
        ...checkedBy(thing, {
          requires: trip.options.some((option) => !asked.requires.has(option.id)),
          refuses: trip.options.some((option) => !asked.refuses.has(option.id)),
        }),
        movedBy(thing),
      ],
      // An OBJECT's own records: the FACT about where it is when the TRIP starts, and the FACTs
      // that the FILE states every OPTION that requires it or refuses it, and every one that
      // moves it.
      ...marked(
        [...(starts === null ? [] : [starts.record]), ...[thing.requires_complete, thing.transfers_complete].filter((id) => id !== null)],
        (need) => need.object === thing.id,
        "The report names this OBJECT in what the FILE does not say.",
      ),
    };
  });
  const all = shown.flatMap((thing) => [thing, ...thing.requires, ...thing.refuses, ...thing.transfers]);
  const clash = all.some((each) => each.clash.length > 0);
  const asked = all.some((each) => each.cases.length > 0);
  const says =
    "The OBJECTs of the FILE, each with where it is when the TRIP starts, the OPTIONs that the FILE says require it or refuse it, and those that it says hand it over or keep it." +
    (timed ? clocksOf(trip.zone) : "") +
    (clash ? " A red edge marks what the report names among what rules out every plan." : "") +
    (asked ? " A yellow edge marks what the report names in what the FILE does not say." : "");
  return { says, clash, asked, objects: shown };
}
