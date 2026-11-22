// The CAPABILITIES of a FILE, as the page shows them. There is no page in here, so the tests
// run this as it is.
//
// The view sends the CAPABILITIES with each report: each PERSON of whom a FACT says that they
// have the CAPABILITY or do not, each OPTION of which a FACT says what it requires of the
// CAPABILITY, and the FACT that the FILE states every one of its OPTIONs that requires it.
// This puts them in words, as the report words them. Beside each of those OPTIONs it says who
// takes part in it, as the other parts of the page do, and who meets what it requires in the
// plan, where the report says so. It marks what the report names: the records that rule out
// every plan, and the cases in which a trip that depends on something works.
//
// Nothing here judges a TRIP. Whether the PERSONs in an OPTION meet what it requires is for
// the COMPILER to say: the page shows who meets a requirement only where the report names them.

import { casesAbout, casesIn, findsOf, listed, requirementsIn, ruledOut, saidOf } from "./named.js";
import { whoIsIn } from "./who.js";

/** What an OPTION requires of a CAPABILITY, as the report words it. */
function requiresOf(of) {
  return of === "none" ? "does not require it" : `requires it of ${of === "one" ? "one PERSON" : "each PERSON"} who takes part`;
}

/**
 * Whether the OPTIONs under a CAPABILITY are all that require it, as far as the FILE says.
 * `others` says that the FILE has an OPTION with no FACT about the CAPABILITY. It never says
 * that an OPTION requires the CAPABILITY where the FILE names none that does.
 */
function wholeOf(capability, others) {
  const some = capability.options.some((option) => option.of !== "none");
  if (capability.complete !== null) return some ? "The FILE states every one of its OPTIONs that requires it." : "The FILE states every one of its OPTIONs that requires it, and it names none.";
  if (!others) return null;
  if (some) return "Other OPTIONs of the FILE may require it too: the FILE does not say that these are all.";
  return capability.options.length ? "The FILE leaves open whether another of its OPTIONs requires this CAPABILITY." : "The FILE says of no OPTION whether it requires this CAPABILITY.";
}

/**
 * What the page shows of the CAPABILITIES of a TRIP as the view sends it, or of no TRIP where
 * the view sends none.
 *
 * Each CAPABILITY has its name, its `people` and its `options`, and whether its OPTIONs are all
 * that require it (`whole`). `people` holds every PERSON of the TRIP, with what the FILE says:
 * that they have it, that they do not, or nothing. Each of its `options` has its name, what
 * the FILE says that it requires (`says`), who takes part (`takes`), who meets what it
 * requires in the plan of the report (`meets`, null where the report names nobody), and the
 * `step` of the TRIP that it is, where the calendar holds it.
 *
 * `report` is the report as JSON, where the page has one. `clash` on a CAPABILITY, on one of
 * its PERSONs or on one of its OPTIONs holds its `records` that the report names as ruling out
 * every plan, and `finds` says so. `cases` holds the cases that name it among what the FILE
 * does not say, as their places in `missing` of the report, and `asks` holds what the report
 * says of them. `stated` holds the words of the report for those cases, as lines.js finds
 * them. `clash` and `asked` on the whole say that something here is marked so.
 */
export function capabilities(trip, report = null, stated = null) {
  if (trip === null || !trip.capabilities.length) return { says: "", clash: false, asked: false, capabilities: [] };
  const who = whoIsIn(trip);
  const person = new Map(trip.persons.map((each) => [each.id, each.name]));
  const ruled = ruledOut(report);
  const needed = casesIn(report);
  const met = requirementsIn(report);
  const marked = (records, about, otherwise) => {
    const clash = records.filter((id) => ruled.has(id));
    const cases = casesAbout(needed, about);
    return { records, clash, finds: findsOf(clash), cases, asks: saidOf(cases, stated, otherwise) };
  };
  const shown = trip.capabilities.map((capability) => {
    const able = new Map(capability.has.map((each) => [each.person, each]));
    const asked = new Set(capability.options.map((each) => each.option));
    return {
      id: capability.id,
      name: capability.name,
      people: trip.persons.map(({ id, name }) => {
        const fact = able.get(id) ?? null;
        return {
          person: id,
          name,
          // The report says it so: Sam has the CAPABILITY, Alex does not have the CAPABILITY.
          says: fact === null ? "the FILE does not say" : fact.has ? "has it" : "does not have it",
          has: fact === null ? null : fact.has,
          ...marked(fact === null ? [] : [fact.record], (need) => need.capability === capability.id && need.person === id && need.option === undefined, "The report names this PERSON and this CAPABILITY in what the FILE does not say."),
        };
      }),
      options: capability.options.map((option) => {
        const { step, takes } = who(option.option);
        const meeting = met.find((each) => each.option === option.option && each.capability === capability.id) ?? null;
        const meets = meeting === null ? [] : meeting.persons.map((id) => person.get(id) ?? id);
        return {
          option: option.option,
          name: option.name,
          of: option.of,
          says: requiresOf(option.of),
          takes,
          // The report says it so: Sam meets that requirement.
          meets: meets.length ? `${listed(meets)} ${meets.length === 1 ? "meets" : "meet"} that requirement.` : null,
          step,
          ...marked([option.record], (need) => need.capability === capability.id && need.option === option.option, "The report names this OPTION and this CAPABILITY in what the FILE does not say."),
        };
      }),
      whole: wholeOf(capability, trip.options.some((option) => !asked.has(option.id))),
      // A CAPABILITY's own record: the FACT that the FILE states every OPTION that requires it.
      ...marked(capability.complete === null ? [] : [capability.complete], (need) => need.capability === capability.id, "The report names this CAPABILITY in what the FILE does not say."),
    };
  });
  const all = shown.flatMap((capability) => [capability, ...capability.people, ...capability.options]);
  const clash = all.some((each) => each.clash.length > 0);
  const asked = all.some((each) => each.cases.length > 0);
  const says =
    "The CAPABILITIES of the FILE, each with who has it and the OPTIONs that the FILE says require it or do not." +
    (clash ? " A red edge marks what the report names among what rules out every plan." : "") +
    (asked ? " A yellow edge marks what the report names in what the FILE does not say." : "");
  return { says, clash, asked, capabilities: shown };
}
