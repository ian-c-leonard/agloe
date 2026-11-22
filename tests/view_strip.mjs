// Runs the view's own code for the strip above the calendar, for tests/test_view_strip.py.
//
//   node view_strip.mjs < [{"trip": ..., "report": ..., "text": ..., "wide": ...}, ...]
//     prints, for each TRIP as the view sends it, the calendar that the page draws and the
//     strip that it draws of that calendar in so many pixels. The report is the one that the
//     TRIP came with, as JSON and in words, or null.
import { readFileSync } from "node:fs";
import { calendar } from "../src/agloe/view/static/calendar.js";
import { statedIn, lines, warningsOf } from "../src/agloe/view/static/lines.js";
import { strip } from "../src/agloe/view/static/strip.js";

const asked = JSON.parse(readFileSync(0, "utf8"));
const made = asked.map(({ trip, report, text, wide }) => {
  const tied = text === null ? [] : lines(text, report, trip);
  const laid = calendar(trip, report, warningsOf(tied), statedIn(tied));
  return { calendar: laid, strip: strip(laid, wide) };
});
process.stdout.write(JSON.stringify(made));
