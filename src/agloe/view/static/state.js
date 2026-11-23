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
// has changed is marked as old. So is what the page draws, until the view has read the FILE as
// it is now: from then on the page draws that FILE, with no report. The page always draws the
// newest TRIP that it was sent, and marks it as old where it is not of the FILE as it is now,
// or where the page no longer hears the view.

const OLD = "What the page shows below is on the FILE as it was before.";
const OLD_REPORT = "The report below is on the FILE as it was before.";
// What the page says while it no longer hears the view. Where it knows of no change to the
// FILE, it says of none.
const LAST = "What the page shows below is the last that the view sent. The FILE may have changed since then.";
const EARLIER = "The report is on an earlier state of the FILE than what the page draws.";
const SAID = "When the page last heard the view, it said:";
const seconds = (length) => `${length.toFixed(2)} s`;
const none = { checking: false, answer: null, answered: null, problems: null, unreadable: null, unwritable: false, stopped: false, lost: false };

/** Before the view has sent anything. */
export function start() {
  return { ...none, view: null, name: null, revision: null, read: null, report: null, reported: null, old: false };
}

/** The state after one more event. */
export function after(state, event) {
  if (event.kind === "lost") return { ...state, checking: false, lost: true, old: state.report !== null };
  if (event.kind === "file") {
    // The view speaks again of the state that the page knows, after the page had lost it. All
    // that the page was told of that state stands, and the check goes on where it has no end
    // yet.
    if (state.view !== null && event.view === state.view && event.revision === state.revision) {
      return { ...state, lost: false, checking: !ended(state), old: state.report !== null && !reportedOn(state) };
    }
    // Each view has a name of its own. Where another view now serves this address, what is
    // on the page is of a FILE that this view knows nothing of, so the page lets it go.
    const kept = state.view === null || event.view === state.view ? state : { ...state, read: null, report: null, reported: null };
    return { ...kept, ...none, view: event.view, name: event.name, revision: event.revision, checking: true, old: kept.report !== null };
  }
  // An event about another state of the FILE than the one the page was last told of says nothing
  // about the FILE on the page, so it is passed over.
  if (event.revision !== state.revision) return state;
  const done = { ...state, checking: false, old: state.report !== null };
  // The TRIP of the FILE as it is now, before any report on it. A state is read once: what
  // the view says of it again changes nothing. Where the view has no TRIP to send, the page
  // keeps the last one that it was sent.
  if (event.kind === "read") {
    if (event.trip === null || (state.read !== null && state.read.revision === event.revision)) return state;
    return { ...state, read: { trip: event.trip, revision: event.revision } };
  }
  if (event.kind === "answer") return { ...state, answer: event.answer, answered: event.seconds };
  if (event.kind === "report") {
    // A state has one report. Where the view sends it again, the one on the page stands.
    if (reportedOn(state)) return { ...state, checking: false, old: false };
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

/** Whether the report on the page is on the state of the FILE that the page was last told of. */
function reportedOn(state) {
  return state.report !== null && state.report.revision === state.revision;
}

/** Whether the check of the state that the page was last told of has come to an end. */
function ended(state) {
  return reportedOn(state) || state.problems !== null || state.unreadable !== null || state.unwritable || state.stopped;
}

/**
 * What the page says of the check of the state that it was last told of, while it hears the
 * view: how it is marked, a line, and under it `why`, what a reader needs beside the line.
 * `checking` says whether that check is running.
 */
function saidOf(state, checking) {
  if (state.problems) return { mark: "refused", line: "This FILE does not follow the format, so it has no report.", why: "" };
  if (state.unreadable !== null) return { mark: "unreadable", line: "The FILE cannot be read, so it has no report.", why: `${state.unreadable}.` };
  if (state.unwritable) {
    const line = state.answer ? `${state.answer}. The report cannot be written.` : "The report cannot be written.";
    return { mark: state.answer ? state.answer.toLowerCase() : "stopped", line, why: "It holds a time outside the years 0001 to 9999." };
  }
  if (state.stopped) {
    const line = state.answer ? `${state.answer}. The check stopped before its report came.` : "The check stopped before it gave an answer.";
    return { mark: "stopped", line, why: "It runs again when the FILE changes." };
  }
  if (checking && state.answer) return { mark: state.answer.toLowerCase(), line: `${state.answer}. The report is on its way.`, why: `The answer came after ${seconds(state.answered)}.` };
  // The page says what it knows: the check may have ended, and its answer be on its way here.
  if (checking) return { mark: "checking", line: "Waiting for the COMPILER's answer on this FILE.", why: "" };
  if (state.report) {
    const why = `The COMPILER gave the answer after ${seconds(state.answered)} and the report after ${seconds(state.reported)}.`;
    return { mark: markOf(state.report.json), line: state.report.text.split("\n")[0], why };
  }
  return { mark: "waiting", line: "Waiting for the FILE.", why: "" };
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
 * mark. It is the newest TRIP that the page was sent: the one that came with the report on
 * the page, or one that the view read from a later state of the FILE, with no report. `ahead`
 * says that it is the second: the drawings are then ahead of any report on the page.
 * `calendar` is null where the page has neither, and the TRIP in it is null where the view
 * sent none with the report. `old` says that the report in words is on the FILE as it was
 * before. `past` says that of what the page draws: its TRIP is not of the FILE as it is now,
 * or the page no longer hears the view.
 */
export function says(state) {
  const ahead = state.read !== null && (state.report === null || state.read.revision > state.report.revision);
  const calendar = ahead ? { trip: state.read.trip, report: null } : state.report ? { trip: state.report.trip, report: state.report.json } : null;
  const past = calendar !== null && (ahead ? state.lost || state.read.revision !== state.revision : state.old);
  const shown = { name: state.name, report: state.report ? state.report.text : null, calendar, ahead, old: state.old, past, problems: state.problems };
  // A report on the page and a drawing of a later state of the FILE: the page says which is which.
  const earlier = state.report !== null && ahead ? [EARLIER] : [];
  const with_old = (note) => [note, ...(past ? [OLD, ...earlier] : state.old ? [OLD_REPORT] : [])].join(" ").trim();
  if (!state.lost) {
    const { mark, line, why } = saidOf(state, state.checking);
    return { ...shown, mark, line, note: with_old(why) };
  }
  // The page no longer hears the view. It repeats what it said last, as the last that it
  // said: the check was running unless it had come to an end. A report on that state of the
  // FILE is there to read, and so are the problems of a FILE that the format refused: the
  // line above them says whose they are.
  const last = saidOf(state, state.revision !== null && !ended(state));
  const line = state.problems ? "The view is not answering. The problems below are from the last check that it sent." : "The view is not answering.";
  const said = state.problems || reportedOn(state) || last.mark === "waiting" ? [] : [SAID, last.line, ...(last.why ? [last.why] : [])];
  // What the page shows is the last that it was sent. Where the view had said that there is
  // a newer state of the FILE, the page knows that the FILE changed.
  const behind = calendar !== null && (ahead ? state.read.revision : state.report.revision) !== state.revision;
  const below = calendar !== null ? [behind ? OLD : LAST, ...earlier] : [];
  return { ...shown, mark: "lost", line, note: ["If agloe view has stopped, start it again and open the address that it prints.", ...said, ...below].join(" ") };
}
