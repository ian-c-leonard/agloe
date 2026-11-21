// Runs the view's own code for the calendar, for tests/test_view_calendar.py.
//
//   node view_calendar.mjs < [{"trip": ..., "report": ..., "text": ...}, ...]
//     prints, for each TRIP as the view sends it, the calendar that the page draws. The report
//     is the one that the TRIP came with, as JSON and in words, or null. Where the report in
//     words is given, the calendar gets what that report warns of at each step, as on the page.
import { readFileSync } from "node:fs";
import { calendar } from "../src/agloe/view/static/calendar.js";
import { lines, warningsOf } from "../src/agloe/view/static/lines.js";

const asked = JSON.parse(readFileSync(0, "utf8"));
const laid = asked.map(({ trip, report, text }) => calendar(trip, report, text === null ? [] : warningsOf(lines(text, report, trip))));
process.stdout.write(JSON.stringify(laid));
