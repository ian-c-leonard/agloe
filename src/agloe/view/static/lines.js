// The lines of a report in words, and what on the calendar each line is about. There is no page
// in here, so the tests run this as it is.
//
// A report in words shows the plan one step to a line, and under a step what it warns of. Where
// it names FACTs, WANTs and DECISIONs, it shows them one to a line, each line starting with the
// id, in the order in which the report as JSON lists them. The view sends the steps of the plan
// in the report's order. Where a trip depends on what the FILE does not say, the report states
// each case in which the trip works: one case in a sentence, several in a numbered list, in
// the order of the report as JSON. So a line can be tied to the step it shows, to the record
// it names, or to the case it states, and to nothing else.
//
// Nothing here judges a TRIP. It finds what the report already says, line by line.

import { casesIn } from "./named.js";

/** A line that shows one step of a plan: "  2:00 pm to 3:00 pm: Museum visit, Alex and Sam". */
const STEP = /^ {2}\d{1,2}:\d\d(:\d\d)? [ap]m.* to .+: .+, .+$/;
/** A line under a step that says what the report warns of there. */
const WARNING = /^ {4}! /;

/** How the line starts that states the one case in which a trip works. */
const ONE_CASE = "The trip works if ";
/** The line above the cases in which a trip works, where the report lists several. */
const CASES = "The trip works in any of these cases:";

/** The lists of ids that a report as JSON names one after another in its words. */
function listsOf(report) {
  const paid = Array.isArray(report?.money?.paid) ? report.money.paid.map((each) => each?.booking) : null;
  return [report?.relies_on, report?.conflict, paid].filter((list) => Array.isArray(list) && list.length && list.every((id) => typeof id === "string"));
}

/**
 * Each line of a report in words: its text, the step of the TRIP that it shows or warns about,
 * the record that it names, and the case that it states, as its place in `missing` of the
 * report as JSON. `step`, `record` and `case` are null where a line has none. `warns` says
 * that the line is a warning under its step.
 *
 * The lines of a plan are tied to steps only where there is one line for each step that the
 * view sent, in the same order: then the two are the same plan. Lines are tied to records only
 * where they name a whole list of the report as JSON, one id after another. So a line that
 * only starts like an id, such as the total in a currency, is tied to nothing. Lines are tied
 * to cases only where the words state as many cases as the report as JSON holds.
 */
export function lines(text, report, trip) {
  const all = text.split("\n");
  const plan = all.filter((line) => STEP.test(line)).length;
  const tied = trip !== null && trip.itinerary && plan === trip.steps.length;
  let step = -1;
  let under = false; // whether this line can still be a warning under the step above it
  const found = all.map((line) => {
    if (tied && STEP.test(line)) {
      step += 1;
      under = true;
      return { text: line, step, warns: false, record: null, case: null };
    }
    if (under && WARNING.test(line)) return { text: line, step, warns: true, record: null, case: null };
    under = false;
    return { text: line, step: null, warns: false, record: null, case: null };
  });
  for (const ids of listsOf(report)) {
    // The first place where the lines name these ids one after another.
    const names = (at) => ids.every((id, n) => at + n < found.length && found[at + n].step === null && found[at + n].record === null && found[at + n].text.startsWith(`  ${id}: `));
    const at = found.findIndex((_, n) => names(n));
    if (at >= 0) ids.forEach((id, n) => (found[at + n].record = id));
  }
  // The cases in which the trip works. One case is the only sentence that starts so. Several
  // are under their heading, each on a line with its number. What the report says of a case
  // is under that line, further in. The list ends at the first line that is neither. Its
  // lines are tied where they are numbered in turn, as many as the report as JSON holds.
  const cases = casesIn(report);
  const free = (line) => line !== undefined && line.step === null && line.record === null;
  if (cases.length === 1) {
    const states = found.filter((line) => line.text.startsWith(ONE_CASE));
    if (states.length === 1 && free(states[0])) states[0].case = 0;
  } else if (cases.length > 1) {
    const heads = found.flatMap((line, at) => (line.text === CASES ? [at] : []));
    const numbered = [];
    for (let at = heads[0] + 1; heads.length === 1 && at < found.length; at += 1) {
      if (/^ {2}\d+\. /.test(found[at].text)) numbered.push(at);
      else if (!/^ {3,}\S/.test(found[at].text)) break;
    }
    if (numbered.length === cases.length && numbered.every((at, n) => free(found[at]) && found[at].text.startsWith(`  ${n + 1}. `))) {
      numbered.forEach((at, n) => (found[at].case = n));
    }
  }
  return found;
}

/**
 * The words of the report for the cases in which the trip works, from its lines: the line of
 * each case, at the place of the case, and the heading over them where the report lists
 * several.
 */
export function casesOf(tied) {
  const cases = [];
  for (const line of tied) {
    if (line.case !== null) cases[line.case] = line.text.trim();
  }
  return { heading: cases.length > 1 ? CASES : null, cases };
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
