// Runs the view's own code for the calendar, for tests/test_view_calendar.py.
//
//   node view_calendar.mjs < [{"trip": ..., "report": ..., "text": ...}, ...]
//     prints, for each TRIP as the view sends it, the calendar that the page draws. The report
//     is the one that the TRIP came with, as JSON and in words, or null. Where the report in
//     words is given, the calendar gets what that report warns of at each step, and the words
//     of each case in which it says the trip works, as on the page.
import { readFileSync } from "node:fs";
import { calendar } from "../src/agloe/view/static/calendar.js";
import { statedIn, lines, warningsOf } from "../src/agloe/view/static/lines.js";

const asked = JSON.parse(readFileSync(0, "utf8"));
const laid = asked.map(({ trip, report, text }) => {
  const tied = text === null ? [] : lines(text, report, trip);
  return calendar(trip, report, warningsOf(tied), statedIn(tied));
});
process.stdout.write(JSON.stringify(laid));
