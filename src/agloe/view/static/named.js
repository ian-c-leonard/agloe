// What a report names, for the parts of the page that mark it. There is no page in here, so
// the tests run this as it is.
//
// A report on a TRIP that cannot work names the FACTs, WANTs and DECISIONs that rule out every
// plan. A report on a TRIP that depends on what the FILE does not say names, for each case in
// which the trip works, the things that the case needs. Each part of the page marks what it
// shows of those. Nothing here judges a TRIP: it reads what the report as JSON already holds.

/** Names as a sentence joins them: Alex, Sam and Jo. */
export function listed(names) {
  return names.length < 2 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/**
 * The ids of the records that a report names as ruling out every plan. Only a report on a TRIP
 * that cannot work names any.
 */
export function ruledOut(report) {
  const named = report !== null && typeof report === "object" && report.answer === "INFEASIBLE" && Array.isArray(report.conflict) ? report.conflict : [];
  return new Set(named.filter((id) => typeof id === "string"));
}

/** What a part of the page says of the records of one thing that the report names so. */
export function findsOf(clash) {
  return clash.length ? `The report names ${listed(clash)} among what rules out every plan.` : null;
}

/**
 * The cases in which a report says the trip works, where the trip depends on what the FILE
 * does not say: for each case, the list of the things that it needs. Only a report with the
 * answer UNDETERMINED holds any. Each case needs one thing at least, and a list that is not of
 * that shape is none.
 */
export function casesIn(report) {
  const missing = report !== null && typeof report === "object" && report.answer === "UNDETERMINED" ? report.missing : null;
  const isNeed = (need) => need !== null && typeof need === "object" && !Array.isArray(need);
  const isCase = (needs) => Array.isArray(needs) && needs.length > 0 && needs.every(isNeed);
  return Array.isArray(missing) && missing.every(isCase) ? missing : [];
}

/** The OPTIONs that one of those things names: its own, and each that somebody has to buy a place for. */
export function optionsOf(need) {
  const bought = Array.isArray(need.buys) ? need.buys.filter((buy) => buy !== null && typeof buy === "object").map((buy) => buy.option) : [];
  return [need.option, ...bought].filter((id) => typeof id === "string");
}

/** The cases that need something for which `about` says yes, as their places among the cases. */
export function casesAbout(needed, about) {
  return needed.flatMap((needs, at) => (needs.some(about) ? [at] : []));
}

/**
 * What the report says of these cases, in its own lines: the line of the one case, or the
 * heading of the list and the line of each of these. `stated` holds those words, as lines.js
 * finds them. Where the page has no words for one of the cases, this says `otherwise`.
 */
export function saidOf(cases, stated, otherwise) {
  const known = stated !== null && typeof stated === "object";
  const words = known && Array.isArray(stated.cases) ? stated.cases : [];
  const heading = known && typeof stated.heading === "string" ? stated.heading : null;
  const said = cases.map((at) => (typeof words[at] === "string" ? words[at] : null));
  if (!said.length) return [];
  if (said.includes(null)) return [otherwise];
  return heading === null ? said : [heading, ...said];
}
