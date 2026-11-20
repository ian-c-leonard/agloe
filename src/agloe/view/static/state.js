// What the page says in each state. There is no page in here, so the tests run this as it is.
//
// The view sends the page events about the FILE: `file` when there is a FILE to check, then
// `answer` as soon as the COMPILER has proved one, then `report`. A FILE with no report gets
// `refused`, with the problems, and a check that ends with neither gets `stopped`.
//
// Nothing here judges a TRIP: an answer is shown only once the COMPILER has given it, and only
// for the FILE it was given on.

const OLD = "The report below is on the FILE as it was before.";
const seconds = (length) => `${length.toFixed(2)} s`;

/** Before the view has sent anything. */
export function start() {
  return { name: null, checking: false, stopped: false, answer: null, answered: null, report: null, reported: null, old: false, problems: null };
}

/** The state after one more event. A report that is on the page stays, marked as old, until the next one comes. */
export function after(state, event) {
  if (event.kind === "file") {
    return { ...state, name: event.name, checking: true, stopped: false, answer: null, answered: null, problems: null, old: state.report !== null };
  }
  if (event.kind === "answer") return { ...state, answer: event.answer, answered: event.seconds };
  if (event.kind === "report") {
    return { ...state, checking: false, answer: event.answer, answered: state.answered ?? event.seconds, report: { text: event.text, json: event.json }, reported: event.seconds, old: false };
  }
  if (event.kind === "refused") {
    return { ...state, checking: false, answer: null, answered: null, problems: event.problems, old: state.report !== null };
  }
  // The check ended with no report. An answer that came before that stays: it was proved.
  if (event.kind === "stopped") return { ...state, checking: false, stopped: true, old: state.report !== null };
  throw new Error(`the view sent an event that the page does not know: ${event.kind}`);
}

/** How a report is marked: by its answer, or as a warning where its plan comes with one. */
function markOf(json) {
  if (json.answer !== "FEASIBLE") return json.answer.toLowerCase();
  return json.robust === false || json.to_buy ? "warning" : "feasible";
}

/**
 * What the page shows: a mark, a line, a note under it, the report in words, whether that
 * report is on the FILE as it was before, and the problems of a FILE that has no report.
 */
export function says(state) {
  const shown = { name: state.name, report: state.report ? state.report.text : null, old: state.old, problems: state.problems };
  const old = state.old ? OLD : "";
  if (state.problems) {
    return { ...shown, mark: "refused", line: "This FILE does not follow the format, so it has no report.", note: old };
  }
  if (state.stopped) {
    const line = state.answer ? `${state.answer}. The check stopped before its report came.` : "The check stopped before it gave an answer.";
    return { ...shown, mark: "stopped", line, note: `It runs again when the FILE changes. ${old}`.trim() };
  }
  if (state.checking && state.answer) {
    return { ...shown, mark: state.answer.toLowerCase(), line: `${state.answer}. The report is on its way.`, note: `The answer came after ${seconds(state.answered)}. ${old}`.trim() };
  }
  if (state.checking) return { ...shown, mark: "checking", line: "The COMPILER is checking this FILE.", note: old };
  if (state.report) {
    return { ...shown, mark: markOf(state.report.json), line: shown.report.split("\n")[0], note: `The COMPILER gave the answer after ${seconds(state.answered)} and the report after ${seconds(state.reported)}.` };
  }
  return { ...shown, mark: "waiting", line: "Waiting for the FILE.", note: "" };
}
