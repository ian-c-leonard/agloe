// The lines of a report in words, and what on the calendar each line is about. There is no page
// in here, so the tests run this as it is.
//
// A report in words shows the plan one step to a line, and under a step what it warns of. Where
// it names FACTs, WANTs and DECISIONs, it shows them one to a line, each line starting with the
// id, in the order in which the report as JSON lists them. The view sends the steps of the plan
// in the report's order. Where a trip depends on what the FILE does not say, the report states
// each case in which the trip works: one case in a sentence, several in a numbered list, in
// the order of the report as JSON. Under a plan, it says who meets what each OPTION requires,
// one requirement to a line, in the order of the report as JSON. So a line can be tied to the
// step it shows or is about, to the record it names, or to the case it states, and to nothing
// else.
//
// Nothing here judges a TRIP. It finds what the report already says, line by line.

import { boughtIn, cappedIn, casesIn, listed, objectsIn, requirementsIn, takenIn, toBuyIn } from "./named.js";

/** A line that shows one step of a plan: "  2:00 pm to 3:00 pm: Museum visit, Alex and Sam". */
const STEP = /^ {2}\d{1,2}:\d\d(:\d\d)? [ap]m.* to .+: .+, .+$/;
/** A line under a step that says what the report warns of there. */
const WARNING = /^ {4}! /;

/** How the line starts that states the one case in which a trip works, or might work. */
const ONE_CASE = /^The trip (?:works|might work) if /;
/** The line above the cases in which a trip works or might, where the report lists several. */
const CASES = /^The trip (?:works|might work) in any of these cases:$/;
/** A warning that says who still has to buy a right, and from which OFFER. */
const TO_BUY = /^ {4}! .+ still ha(?:s|ve) to buy a right to this(?: if it needs one)?, from (.+)\.$/;
/** How the line starts that gives one plan for a case: who buys which place. */
const ONE_PLAN = "One plan that works then: ";
/** The line above the sums of a plan in each currency. */
const SUMS = "The money of this plan, by currency:";
/** The line above what a plan charges to each cap. */
const CAPS = "The caps:";
/** The line above where each OBJECT is in a plan. */
const OBJECTS = "Where each OBJECT is:";
/** How the line ends that is above the BUDGETs of the FILE, where a report states them. */
const BUDGETS = " The BUDGETs of this FILE:";
/** The line above who meets what the OPTIONs of a plan require. */
const MEETS = "Who meets the requirements:";

/**
 * The lists of ids that a report as JSON names one after another in its words, each with what
 * says that a line is the heading over that list. An id can be the id of two things, or start
 * a line about something else: a currency, the name of an OBJECT. So a list is read only
 * under its own heading.
 */
function listsOf(report) {
  const paid = Array.isArray(report?.money?.paid) ? report.money.paid.map((each) => each?.booking) : null;
  // A report on a plan states each cap once more, with what is charged to it.
  const caps = report?.answer === "FEASIBLE" && Array.isArray(report.caps) ? report.caps.map((each) => each?.cap) : null;
  const lists = [
    [report?.relies_on, (text) => /^The plan relies on these .+:$/.test(text)],
    [report?.conflict, (text) => /^These .+ rule out every plan/.test(text)],
    [paid, (text) => text === "What the BOOKINGs state that they paid:"],
    [caps, (text) => text === CAPS],
  ];
  return lists.filter(([list]) => Array.isArray(list) && list.length && list.every((id) => typeof id === "string"));
}

/**
 * Each line of a report in words: its text, the step of the TRIP that it shows or is about,
 * the record that it names, and the case that it states, as its place in `missing` of the
 * report as JSON. `step`, `record` and `case` are null where a line has none. `warns` says
 * that the line is a warning under its step. `meets` is null, or the place in `requirements`
 * of the report as JSON of the requirement that the line says somebody meets. `about` holds
 * what else the line is about, each as the page names a thing: `offer:ID` for an OFFER that
 * the line says somebody buys a place of, `budget:ID` for a BUDGET that the line states,
 * `cap:ID` for a cap that the line states under the plan of a case, `booking:ID` for a
 * BOOKING that the line says states no payment, and `object:ID` for an OBJECT that the line is
 * about. A line about an OBJECT at a step of the plan holds that step
 * too, by its number, as the page names a step.
 *
 * The lines of a plan are tied to steps only where there is one line for each step that the
 * view sent, in the same order: then the two are the same plan. Lines are tied to records only
 * where they name a whole list of the report as JSON, one id after another, under the heading
 * of that list. So a line that only starts like an id, such as the total in a currency, is
 * tied to nothing. Lines are tied
 * to cases only where the words state as many cases as the report as JSON holds. A line that
 * says who meets a requirement is tied to the step that its OPTION is, only where the words
 * hold one line for each requirement of the report as JSON. A line that says who buys a place
 * is tied to the OFFER only where the report as JSON names that OFFER for the same step, or
 * for the same case.
 */
export function lines(text, report, trip) {
  const all = text.split("\n");
  const plan = all.filter((line) => STEP.test(line)).length;
  const tied = trip !== null && trip.itinerary && plan === trip.steps.length;
  let step = -1;
  let under = false; // whether this line can still be a warning under the step above it
  const one = (text, at = null, warns = false) => ({ text, step: at, warns, record: null, case: null, meets: null, about: [] });
  const found = all.map((line) => {
    if (tied && STEP.test(line)) {
      step += 1;
      under = true;
      return one(line, step);
    }
    if (under && WARNING.test(line)) return one(line, step, true);
    under = false;
    return one(line);
  });
  // A warning that says who still has to buy a right names its OFFER after "from". It is tied
  // to that OFFER where the report as JSON has the plan buy a place of it for the same step.
  for (const line of found) {
    const from = line.warns ? TO_BUY.exec(line.text) : null;
    if (from === null) continue;
    const named = (offer) => from[1] === offer || from[1].startsWith(`${offer}, `);
    const bought = toBuyIn(report).filter((buy) => buy.option === trip.steps[line.step].option && named(buy.offer));
    line.about = [...new Set(bought.map((buy) => `offer:${buy.offer}`))];
  }
  for (const [ids, isHeading] of listsOf(report)) {
    // The lines under the one heading of this list, where they name its ids one after another.
    const heads = found.flatMap((line, n) => (isHeading(line.text) ? [n] : []));
    const at = heads.length === 1 ? heads[0] + 1 : found.length;
    const names = ids.every((id, n) => at + n < found.length && found[at + n].step === null && found[at + n].record === null && found[at + n].text.startsWith(`  ${id}: `));
    if (names) ids.forEach((id, n) => (found[at + n].record = id));
  }
  // The cases in which the trip works. One case is the only sentence that starts so. Several
  // are under their heading, each on a line with its number. What the report says of a case
  // is under that line, further in. The list ends at the first line that is neither. Its
  // lines are tied where they are numbered in turn, as many as the report as JSON holds.
  const cases = casesIn(report);
  const free = (line) => line !== undefined && line.step === null && line.record === null;
  if (cases.length === 1) {
    const states = found.filter((line) => ONE_CASE.test(line.text));
    if (states.length === 1 && free(states[0])) states[0].case = 0;
  } else if (cases.length > 1) {
    const heads = found.flatMap((line, at) => (CASES.test(line.text) ? [at] : []));
    const numbered = [];
    for (let at = heads[0] + 1; heads.length === 1 && at < found.length; at += 1) {
      if (/^ {2}\d+\. /.test(found[at].text)) numbered.push(at);
      else if (!/^ {3,}\S/.test(found[at].text)) break;
    }
    if (numbered.length === cases.length && numbered.every((at, n) => free(found[at]) && found[at].text.startsWith(`  ${n + 1}. `))) {
      numbered.forEach((at, n) => (found[at].case = n));
    }
  }
  // The one plan that the report gives for a case is under the line of the case, further in.
  // It is tied to the OFFERs that somebody buys a place of in that plan. Under it, the report
  // states each cap with what that plan charges to it, on a line that starts with the id of
  // the cap. Each of those is tied to its cap.
  const bought = boughtIn(report);
  const capped = cappedIn(report);
  found.forEach((line, at) => {
    if (line.case === null) return;
    const offers = bought[line.case] ?? [];
    const caps = capped[line.case] ?? [];
    const inset = (text) => text.length - text.trimStart().length;
    for (let next = at + 1; next < found.length && found[next].text.trim() !== "" && inset(found[next].text) > inset(line.text); next += 1) {
      if (!free(found[next])) continue;
      const words = found[next].text.trimStart();
      if (words.startsWith(ONE_PLAN)) found[next].about = offers.map((offer) => `offer:${offer}`);
      const cap = caps.find((id) => words.startsWith(`${id}, on `));
      if (cap !== undefined) found[next].about = [`cap:${cap}`];
    }
  });
  // The money of a plan. One line names the BOOKINGs that state no payment: it is about each
  // of them. Under their heading, one line for each currency sums what the plan pays in it:
  // it is about each OFFER that the plan still buys a place of at a price in that currency.
  const money = report !== null && typeof report === "object" && report.answer === "FEASIBLE" && report.money !== null && typeof report.money === "object" ? report.money : null;
  const unstated = money !== null && Array.isArray(money.not_stated) && money.not_stated.every((id) => typeof id === "string") ? money.not_stated : [];
  if (unstated.length) {
    const says = found.filter((line) => free(line) && line.text === `  No payment is stated for ${listed(unstated)}.`);
    if (says.length === 1) says[0].about = unstated.map((id) => `booking:${id}`);
  }
  const totals = money !== null && Array.isArray(money.totals) && money.totals.every((each) => each !== null && typeof each === "object" && typeof each.currency === "string") ? money.totals : [];
  const sums = found.flatMap((line, at) => (line.text === SUMS ? [at] : []));
  if (totals.length && sums.length === 1 && totals.every((each, n) => found[sums[0] + 1 + n] !== undefined && free(found[sums[0] + 1 + n]) && found[sums[0] + 1 + n].text.startsWith(`  ${each.currency}: `))) {
    totals.forEach((each, n) => {
      const line = found[sums[0] + 1 + n];
      // The line names those OFFERs in brackets. One is tied where the line names it too.
      const named = new Set([...line.text.matchAll(/\(([^)]*)\)/g)].flatMap((group) => group[1].split(/, | and /)));
      const offers = toBuyIn(report).filter((buy) => buy.price !== null && typeof buy.price === "object" && buy.price.currency === each.currency && named.has(buy.offer)).map((buy) => buy.offer);
      line.about = [...new Set(offers)].map((id) => `offer:${id}`);
    });
  }
  // The BUDGETs of the FILE, where the report states them: one to a line under their heading,
  // in the FILE's order. They are tied only where the words hold one line for each BUDGET that
  // the view sent. A line starts with the name of its BUDGET as the FILE spells it, which the
  // page can show with its id added, so the names are not compared.
  const pots = trip === null ? [] : trip.budgets;
  const over = found.flatMap((line, at) => (line.text.endsWith(BUDGETS) ? [at] : []));
  if (pots.length && over.length === 1) {
    const stated = [];
    for (let at = over[0] + 1; at < found.length && found[at].text.startsWith("  "); at += 1) stated.push(at);
    if (stated.length === pots.length && stated.every((at) => free(found[at]))) {
      stated.forEach((at, n) => (found[at].about = [`budget:${pots[n].id}`]));
    }
  }
  // Under a step of the plan, after what the report warns of there, a line says who takes
  // an OBJECT at that step: one line for each OBJECT that the report as JSON has somebody take
  // at that OPTION, in the FILE's order of OBJECTs. Each is about the step and about the
  // OBJECT. A line under a step is set in by four spaces, whatever the name it starts with.
  const planned = trip !== null && trip.itinerary;
  const stepOf = (option) => (planned ? trip.steps.findIndex((each) => each.option === option) : -1);
  const placeOf = new Map((trip === null ? [] : trip.objects).map((each, n) => [each.id, n]));
  for (const { option, objects } of takenIn(report)) {
    const at = found.findIndex((line) => line.step !== null && line.step === stepOf(option) && !line.warns && line.meets === null);
    if (at < 0 || !objects.every((id) => placeOf.has(id))) continue;
    const inOrder = [...objects].sort((one, other) => placeOf.get(one) - placeOf.get(other));
    let next = at + 1;
    while (next < found.length && found[next].warns) next += 1;
    const said = [];
    for (; next < found.length && found[next].text.startsWith("    ") && free(found[next]) && !found[next].about.length; next += 1) said.push(found[next]);
    if (said.length === inOrder.length) said.forEach((line, n) => (line.about = [String(found[at].step), `object:${inOrder[n]}`]));
  }
  // Where each OBJECT is in the plan: under their heading, up to the first line that is not
  // set in, one line for each OBJECT of the report as JSON, and after it one line for each
  // OPTION that requires it. They are tied only where the words hold exactly as many lines as
  // that. How far a line is set in is not compared: a name can start with a space. A line
  // about a requirement is about the OBJECT and about the step that its OPTION is.
  const things = objectsIn(report);
  const above = found.flatMap((line, at) => (line.text === OBJECTS ? [at] : []));
  if (things.length && above.length === 1) {
    const under = [];
    for (let at = above[0] + 1; at < found.length && found[at].text.startsWith("  "); at += 1) under.push(found[at]);
    const ties = things.flatMap(({ object, options }) => [
      [`object:${object}`],
      ...options.map((option) => [...(stepOf(option) < 0 ? [] : [String(stepOf(option))]), `object:${object}`]),
    ]);
    if (under.length === ties.length && under.every(free)) under.forEach((line, n) => (line.about = ties[n]));
  }
  // Who meets what each OPTION of the plan requires: the lines under their heading, up to the
  // first line that is not set in. A line starts with the name of its OPTION, whatever that
  // name starts with. Each is about the step that its OPTION is.
  const met = requirementsIn(report);
  const heads = found.flatMap((line, at) => (line.text === MEETS ? [at] : []));
  if (trip !== null && trip.itinerary && met.length && heads.length === 1) {
    const under = [];
    for (let at = heads[0] + 1; at < found.length && found[at].text.startsWith("  "); at += 1) under.push(at);
    const steps = met.map((each) => trip.steps.findIndex((step) => step.option === each.option));
    if (under.length === met.length && steps.every((step) => step >= 0) && under.every((at) => free(found[at]))) {
      under.forEach((at, n) => Object.assign(found[at], { step: steps[n], meets: n }));
    }
  }
  return found;
}

/**
 * What the report states, in its own words, for the parts of the page that say it again, from
 * its lines. For the cases in which the trip works: the line of each case, at the place of the
 * case, and the heading over them where the report lists several. For the caps of a plan, in
 * `charged`: what the report says is charged to each cap and what it has left, by the id of
 * the cap.
 */
export function statedIn(tied) {
  const cases = [];
  const charged = {};
  let capped = false;
  for (const line of tied) {
    if (line.case !== null) cases[line.case] = line.text.trim();
    // Under "The caps:", and nowhere else, a line states the cap with its limit and its
    // BUDGET, and after the last colon what is charged to it. A line that is not set in ends
    // what is under a heading.
    if (!line.text.startsWith("  ")) capped = line.text === CAPS;
    else if (capped && line.record !== null && line.text.startsWith(`  ${line.record}: at most `)) charged[line.record] = line.text.slice(line.text.lastIndexOf(": ") + 2);
  }
  const heading = tied.find((line) => CASES.test(line.text));
  return { heading: cases.length > 1 && heading !== undefined ? heading.text : null, cases, charged };
}

/**
 * What the report warns of at each step, in its own words, from the lines of the report: a list
 * for each step that has a warning, at the place of that step.
 */
export function warningsOf(tied) {
  const warnings = [];
  for (const line of tied) {
    if (line.warns) (warnings[line.step] ??= []).push(line.text.replace(/^ {4}! /, ""));
  }
  return warnings;
}
