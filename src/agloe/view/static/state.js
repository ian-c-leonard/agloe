// What the page says in each state. There is no page in here, so the tests run this as it is.
//
// The view sends the page events. Each one names the state of the FILE that it is about, by a
// number, its revision. `file` says that there is a new state to check, and which view says so.
// What follows is about that state: `read` as soon as the view has read the FILE, with the TRIP
// as the page draws it from the FILE alone, then `answer` as soon as the COMPILER has proved
// one, then `report`, which comes with the TRIP as the page draws it with that report. A FILE
// that does not follow the format gets `refused` with the problems, a FILE that cannot be read
// gets `unreadable`, a report that cannot be written gets `unwritable`, and a check that ends
// with none of these gets `stopped`. The page itself adds `lost` when it no longer hears the
// view.
//
// Nothing here judges a TRIP. An answer is shown only once the COMPILER has given it, and only
// for the state of the FILE it was given on. A report that is still on the page after the FILE
// has changed is marked as old. So is what the page draws of that report's TRIP, until the
// view has read the FILE as it is now: from then on the page draws that FILE, with no report.

const OLD = "What the page shows below is on the FILE as it was before.";
const OLD_REPORT = "The report below is on the FILE as it was before.";
const seconds = (length) => `${length.toFixed(2)} s`;
const none = { checking: false, read: null, answer: null, answered: null, problems: null, unreadable: null, unwritable: false, stopped: false, lost: false };

/** Before the view has sent anything. */
export function start() {
  return { ...none, view: null, name: null, revision: null, report: null, reported: null, old: false };
}

/** The state after one more event. */
export function after(state, event) {
  if (event.kind === "lost") return { ...state, checking: false, lost: true, old: state.report !== null };
  if (event.kind === "file") {
    // Each view has a name of its own. Where another view now serves this address, the report
    // on the page is on a FILE that this view knows nothing of, so the page lets it go.
    const kept = state.view === null || event.view === state.view ? state : { ...state, report: null, reported: null };
    return { ...kept, ...none, view: event.view, name: event.name, revision: event.revision, checking: true, old: kept.report !== null };
  }
  // An event about another state of the FILE than the one the page was last told of says nothing
  // about the FILE on the page, so it is passed over.
  if (event.revision !== state.revision) return state;
  const done = { ...state, checking: false, old: state.report !== null };
  // The TRIP of the FILE as it is now, before any report on it.
  if (event.kind === "read") return { ...state, read: event.trip };
  if (event.kind === "answer") return { ...state, answer: event.answer, answered: event.seconds };
  if (event.kind === "report") {
    const report = { text: event.text, json: event.json, trip: event.trip, revision: event.revision };
    return { ...done, answer: event.answer, answered: state.answered ?? event.seconds, report, reported: event.seconds, old: false };
  }
  if (event.kind === "refused") return { ...done, problems: event.problems };
  if (event.kind === "unreadable") return { ...done, unreadable: event.problem };
  // An answer that came before the check ended was proved, so it stays.
  if (event.kind === "unwritable") return { ...done, unwritable: true };
  if (event.kind === "stopped") return { ...done, stopped: true };
  throw new Error(`the view sent an event that the page does not know: ${event.kind}`);
}

/** How a report is marked: by its answer, or as a warning where its plan comes with one. */
function markOf(json) {
  if (json.answer !== "FEASIBLE") return json.answer.toLowerCase();
  return json.robust === false || json.to_buy ? "warning" : "feasible";
}

/**
 * What the page shows: a mark, a line, a note under it, the report in words, whether that
 * report is on the FILE as it was before, and the problems of a FILE that the format refuses.
 *
 * `calendar` holds the TRIP that the page draws, and the report as JSON for what the drawings
 * mark. Where the report on the page is on the FILE as it is now, that is the TRIP that came
 * with the report. Before that, it is the TRIP as the view read it from the FILE as it is now,
 * with no report, and `ahead` says so: the drawings are then ahead of any report on the page.
 * `calendar` is null where the page has neither, and the TRIP in it is null where the view
 * sent none with the report. `old` says that the report in words is on the FILE as it was
 * before. What the page draws is of that FILE too, unless it is `ahead`.
 */
export function says(state) {
  const ahead = state.read !== null && (state.report === null || state.report.revision !== state.revision);
  const calendar = ahead ? { trip: state.read, report: null } : state.report ? { trip: state.report.trip, report: state.report.json } : null;
  const shown = { name: state.name, report: state.report ? state.report.text : null, calendar, ahead, old: state.old, problems: state.problems };
  const with_old = (note) => `${note} ${state.old ? (ahead ? OLD_REPORT : OLD) : ""}`.trim();
  if (state.lost) {
    return { ...shown, mark: "lost", line: "The view is not answering.", note: with_old("Start agloe view again, and open the address that it prints.") };
  }
  if (state.problems) {
    return { ...shown, mark: "refused", line: "This FILE does not follow the format, so it has no report.", note: with_old("") };
  }
  if (state.unreadable !== null) {
    return { ...shown, mark: "unreadable", line: "The FILE cannot be read, so it has no report.", note: with_old(`${state.unreadable}.`) };
  }
  if (state.unwritable) {
    const line = state.answer ? `${state.answer}. The report cannot be written.` : "The report cannot be written.";
    return { ...shown, mark: state.answer ? state.answer.toLowerCase() : "stopped", line, note: with_old("It holds a time outside the years 0001 to 9999.") };
  }
  if (state.stopped) {
    const line = state.answer ? `${state.answer}. The check stopped before its report came.` : "The check stopped before it gave an answer.";
    return { ...shown, mark: "stopped", line, note: with_old("It runs again when the FILE changes.") };
  }
  if (state.checking && state.answer) {
    return { ...shown, mark: state.answer.toLowerCase(), line: `${state.answer}. The report is on its way.`, note: with_old(`The answer came after ${seconds(state.answered)}.`) };
  }
  if (state.checking) return { ...shown, mark: "checking", line: "The COMPILER is checking this FILE.", note: with_old("") };
  if (state.report) {
    return { ...shown, mark: markOf(state.report.json), line: shown.report.split("\n")[0], note: `The COMPILER gave the answer after ${seconds(state.answered)} and the report after ${seconds(state.reported)}.` };
  }
  return { ...shown, mark: "waiting", line: "Waiting for the FILE.", note: "" };
}
