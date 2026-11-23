// What a report names, for the parts of the page that mark it. There is no page in here, so
// the tests run this as it is.
//
// A report on a TRIP that cannot work names the FACTs, WANTs and DECISIONs that rule out every
// plan. A report on a TRIP that depends on what the FILE does not say names, for each case in
// which the trip works, the things that the case needs. A report that shows a plan names who
// meets what each OPTION of the plan requires, which right each PERSON uses, and where each
// OBJECT is. Each part of the page marks what it shows of those. Nothing here judges a TRIP: it reads what the report as JSON already holds.

/** How a name ends where the page shows its id after it. */
const WITH_AN_ID = / \([a-z0-9]+(-[a-z0-9]+)*\)$/;
/**
 * What a page shows nothing for, as the view tells it where it says which names look alike:
 * the characters that Unicode calls default ignorable, such as a soft hyphen or a mark of
 * direction, and the format characters.
 */
const UNSEEN = /[\p{Default_Ignorable_Code_Point}\p{Cf}]/gu;

/**
 * A name as the page shows it, for a list that "or" joins: in quotation marks where it holds
 * that word, as the report puts it, so that it reads as one name. It holds the word where a
 * page shows it so: a character that a page shows nothing for does not hide the word, and
 * does not part it from its neighbour. The view sends a name in quotation marks already
 * where it could be taken for something else, and with its id after it where another name
 * looks like it. The quotation marks go on before the id, around the spelling of the FILE.
 */
export function either(name) {
  return apart(name, (seen) => seen.split(/\s+/).includes("or"));
}

/**
 * A name as the page shows it, in quotation marks where it could be taken for a word of the
 * sentence around it: where `misleads` says so of the name as a page shows it, in small
 * letters. A name that is in quotation marks already stays as it is.
 */
export function apart(name, misleads) {
  if (name.startsWith('"')) return name;
  const id = name.match(WITH_AN_ID);
  const bare = id === null ? name : name.slice(0, id.index);
  if (!misleads(bare.normalize("NFKC").replace(UNSEEN, "").toLowerCase())) return name;
  return `"${bare.replace(/\\/g, "\\\\")}"${id === null ? "" : id[0]}`;
}

/** Names as a sentence joins them: Alex, Sam and Jo. `last` is the word before the last one. */
export function listed(names, last = "and") {
  return names.length < 2 ? names.join("") : `${names.slice(0, -1).join(", ")} ${last} ${names[names.length - 1]}`;
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

/**
 * What the OPTIONs of a plan require, and who meets it, as a report states it: for each
 * requirement its OPTION, its CAPABILITY and the PERSONs who meet it. Only a report that shows
 * a plan holds any, and a list that is not of that shape is none.
 */
export function requirementsIn(report) {
  const stated = report !== null && typeof report === "object" && report.answer === "FEASIBLE" ? report.requirements : null;
  const isText = (id) => typeof id === "string";
  const isOne = (each) => each !== null && typeof each === "object" && isText(each.option) && isText(each.capability) && Array.isArray(each.persons) && each.persons.every(isText);
  return Array.isArray(stated) && stated.every(isOne) ? stated : [];
}

/**
 * Which right each PERSON uses for each OPTION of a plan, as a report states it: for each use
 * its OPTION, its PERSON, and the BOOKING or the OFFER that gives the right (`by`). Only a
 * report that shows a plan holds any, and a step that states none in that shape has none.
 */
export function usesIn(report) {
  const steps = report !== null && typeof report === "object" && report.answer === "FEASIBLE" && Array.isArray(report.itinerary) ? report.itinerary : [];
  const isRecord = (each) => each !== null && typeof each === "object" && !Array.isArray(each);
  return steps.flatMap((step) => {
    if (!isRecord(step) || typeof step.option !== "string" || !isRecord(step.rights)) return [];
    return Object.entries(step.rights).flatMap(([person, by]) => (typeof by === "string" ? [{ option: step.option, person, by }] : []));
  });
}

/**
 * The places that a plan still buys, as a report states them: for each its OPTION, its OFFER,
 * and whether somebody buys it only if the OPTION turns out to need a right. Only a report
 * that shows a plan holds any, and a list that is not of that shape is none.
 */
export function toBuyIn(report) {
  const stated = report !== null && typeof report === "object" && report.answer === "FEASIBLE" ? report.to_buy : null;
  const isOne = (each) => each !== null && typeof each === "object" && typeof each.option === "string" && typeof each.offer === "string";
  return Array.isArray(stated) && stated.every(isOne) ? stated : [];
}

/**
 * The OFFERs that somebody buys a place of in the one plan that a report gives for each case
 * in which the trip works: a list for each case, at the place of the case. Only a report with
 * one plan for each of its cases holds any.
 */
export function boughtIn(report) {
  const cases = casesIn(report);
  const plans = cases.length && Array.isArray(report.plans) && report.plans.length === cases.length ? report.plans : [];
  const isRecord = (each) => each !== null && typeof each === "object" && !Array.isArray(each);
  if (!plans.every((plan) => isRecord(plan) && Array.isArray(plan.buys) && plan.buys.every((buy) => isRecord(buy) && typeof buy.offer === "string"))) return [];
  return plans.map((plan) => [...new Set(plan.buys.map((buy) => buy.offer))]);
}

/**
 * The caps that a report states under the one plan that it gives for each case in which the
 * trip works: a list of their ids for each case, at the place of the case. Only a report with
 * one plan for each of its cases holds any.
 */
export function cappedIn(report) {
  const cases = casesIn(report);
  const plans = cases.length && Array.isArray(report.plans) && report.plans.length === cases.length ? report.plans : [];
  const isRecord = (each) => each !== null && typeof each === "object" && !Array.isArray(each);
  if (!plans.every((plan) => isRecord(plan) && Array.isArray(plan.caps) && plan.caps.every((row) => isRecord(row) && typeof row.cap === "string"))) return [];
  return plans.map((plan) => plan.caps.map((row) => row.cap));
}

/** The OPTIONs that a list in one of those things names, each in a record of its own. */
function namedIn(list) {
  return Array.isArray(list) ? list.filter((each) => each !== null && typeof each === "object").map((each) => each.option).filter((id) => typeof id === "string") : [];
}

/**
 * The OPTIONs that an OBJECT has to be at hand for, in one of those things, or those that it
 * has to stay out of: give it "requires" for the first, and "refuses" for the second.
 */
export function atHandFor(need, check) {
  const mine = Array.isArray(need.at_hand_for) ? need.at_hand_for.filter((each) => each !== null && typeof each === "object" && each.check === check) : [];
  return namedIn(mine);
}

/**
 * The OPTIONs that one of those things names: its own, each that somebody has to buy a place
 * for, each that an OBJECT has to be at hand for, and each that it has to stay out of.
 */
export function optionsOf(need) {
  return [...(typeof need.option === "string" ? [need.option] : []), ...namedIn(need.buys), ...namedIn(need.at_hand_for)];
}

/**
 * The OBJECTs that somebody takes at each OPTION of a plan, and those that are carried in it,
 * as a report states it: for each such OPTION its id, the ids of the OBJECTs that somebody
 * takes there (`objects`) and the ids of those that are carried in it (`carried`), each in
 * the report's order. Only a report that shows a plan holds any.
 */
export function takenIn(report) {
  const steps = report !== null && typeof report === "object" && report.answer === "FEASIBLE" && Array.isArray(report.itinerary) ? report.itinerary : [];
  const isRecord = (each) => each !== null && typeof each === "object" && !Array.isArray(each);
  return steps.flatMap((step) => {
    if (!isRecord(step) || typeof step.option !== "string") return [];
    const objects = isRecord(step.hands_over) ? Object.keys(step.hands_over) : [];
    const carried = Array.isArray(step.carries) && step.carries.every((id) => typeof id === "string") ? step.carries : [];
    return objects.length || carried.length ? [{ option: step.option, objects, carried }] : [];
  });
}

/**
 * The OBJECTs that would not be at hand at each OPTION of a plan if the uncertain parts took
 * their longest, as a report states it: for each such OPTION its id and the ids of those
 * OBJECTs, each once, in the report's order. Only a report that shows a plan holds any.
 */
export function notAtHandIn(report) {
  const found = report !== null && typeof report === "object" && report.answer === "FEASIBLE" && Array.isArray(report.at_worst) ? report.at_worst : [];
  const isRecord = (each) => each !== null && typeof each === "object" && !Array.isArray(each);
  const late = new Map();
  for (const each of found) {
    if (!isRecord(each) || typeof each.option !== "string" || typeof each.object !== "string") continue;
    if (typeof each.constraint !== "string" || !each.constraint.startsWith("Each OBJECT is at hand")) continue;
    if (!late.has(each.option)) late.set(each.option, []);
    if (!late.get(each.option).includes(each.object)) late.get(each.option).push(each.object);
  }
  return [...late].map(([option, objects]) => ({ option, objects }));
}

/**
 * Where each OBJECT is in a plan, as a report states it: for each OBJECT its id, and the
 * OPTIONs that the report says require it or refuse it, one for each line that the report in
 * words has under the OBJECT. Those lines go in the order of the steps of the plan, and an
 * OPTION that requires the OBJECT and refuses it has the line about requiring first. Only a
 * report that shows a plan holds any, and a list that is not of that shape is none. So is one
 * that names an OPTION that the plan does not hold: its lines have no order.
 */
export function objectsIn(report) {
  const stated = report !== null && typeof report === "object" && report.answer === "FEASIBLE" ? report.objects : null;
  const isRecord = (each) => each !== null && typeof each === "object" && !Array.isArray(each);
  const isBy = (list) => Array.isArray(list) && list.every((by) => isRecord(by) && typeof by.option === "string");
  const isOne = (each) => isRecord(each) && typeof each.object === "string" && isBy(each.required_by) && isBy(each.refused_by);
  if (!Array.isArray(stated) || !stated.every(isOne)) return [];
  const steps = Array.isArray(report.itinerary) ? report.itinerary.map((step) => (isRecord(step) && typeof step.option === "string" ? step.option : null)) : [];
  const things = stated.map((each) => {
    const checks = [...each.required_by.map((by) => [steps.indexOf(by.option), 0, by.option]), ...each.refused_by.map((by) => [steps.indexOf(by.option), 1, by.option])];
    checks.sort((one, other) => one[0] - other[0] || one[1] - other[1]);
    return { object: each.object, options: checks.map(([, , option]) => option), placed: checks.every(([at]) => at >= 0) };
  });
  return things.every((each) => each.placed) ? things.map(({ object, options }) => ({ object, options })) : [];
}

/**
 * Where a report on a plan has each OBJECT, as the report as JSON holds it: for each `object`,
 * its `stays` from the start of the TRIP on, and its `uses`, the OPTIONs of the plan that
 * require it or might. `refusals` holds the OPTIONs of the plan that refuse it or might, each
 * as a use is. A stay has `where` the OBJECT is, or each place it might be: each with
 * a `person`, at a `place` or in an `option`, and a `place` of null is somewhere the FILE
 * does not name. `since` is the OPTION from whose start it is there, and `how`
 * says what that OPTION did, and both are null from the start of the TRIP. Where `how` is
 * "arrived", the OBJECT was carried in that OPTION and is there from its end. A use has its
 * `option`, whether a FACT says that the OPTION requires the OBJECT (`stated`), and `where`
 * the OBJECT is just before the OPTION starts. Only a report that shows a plan holds any, and
 * a list that is not of that shape is none.
 */
export function carriedIn(report) {
  const stated = report !== null && typeof report === "object" && report.answer === "FEASIBLE" ? report.objects : null;
  const isRecord = (each) => each !== null && typeof each === "object" && !Array.isArray(each);
  const kinds = (each) => [typeof each.person === "string", typeof each.place === "string" || each.place === null, typeof each.option === "string"];
  const isWhere = (list) => Array.isArray(list) && list.length > 0 && list.every((each) => isRecord(each) && kinds(each).filter(Boolean).length === 1);
  const isStay = (each) => isRecord(each) && isWhere(each.where) && (typeof each.since === "string" ? typeof each.how === "string" : each.since === null && each.how === null);
  const isUse = (each) => isRecord(each) && typeof each.option === "string" && typeof each.stated === "boolean" && isWhere(each.where);
  const areUses = (list) => Array.isArray(list) && list.every(isUse);
  const isOne = (each) => isRecord(each) && typeof each.object === "string" && Array.isArray(each.path) && each.path.every(isStay) && areUses(each.required_by) && areUses(each.refused_by);
  return Array.isArray(stated) && stated.every(isOne) ? stated.map((each) => ({ object: each.object, stays: each.path, uses: each.required_by, refusals: each.refused_by })) : [];
}

/** The cases that need something for which `about` says yes, as their places among the cases. */
export function casesAbout(needed, about) {
  return needed.flatMap((needs, at) => (needs.some(about) ? [at] : []));
}

/**
 * What a part of the page marks of the things that it shows, by a report and by the words of
 * the report for its cases, as lines.js finds them: give it the `records` of a thing, what
 * says that a need of a case is `about` the thing, and what to say `otherwise`, where the
 * page has no words for a case. `clash` holds the records that the report names as ruling out
 * every plan, and `finds` says so. `cases` holds the cases that name the thing, as their
 * places among the cases, and `asks` holds what the report says of them.
 */
export function marksBy(report, stated) {
  const ruled = ruledOut(report);
  const needed = casesIn(report);
  return (records, about, otherwise) => {
    const clash = records.filter((id) => ruled.has(id));
    const cases = casesAbout(needed, about);
    return { records, clash, finds: findsOf(clash), cases, asks: saidOf(cases, stated, otherwise) };
  };
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
