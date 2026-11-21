// Runs the view's own code for the strip of the whole TRIP, for tests/test_view_strip.py.
//
//   node view_strip.mjs < [{"trip": ..., "report": ..., "text": ...}, ...]
//     prints, for each TRIP as the view sends it, the calendar that the page draws and the
//     strip that it draws of that calendar. The report is the one that the TRIP came with, as
//     JSON and in words, or null.
import { readFileSync } from "node:fs";
import { calendar } from "../src/agloe/view/static/calendar.js";
import { lines, warningsOf } from "../src/agloe/view/static/lines.js";
import { strip } from "../src/agloe/view/static/strip.js";

const asked = JSON.parse(readFileSync(0, "utf8"));
const made = asked.map(({ trip, report, text }) => {
  const laid = calendar(trip, report, text === null ? [] : warningsOf(lines(text, report, trip)));
  return { calendar: laid, strip: strip(laid) };
});
process.stdout.write(JSON.stringify(made));
