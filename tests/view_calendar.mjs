// Runs the view's own code for the calendar, for tests/test_view_calendar.py.
//
//   node view_calendar.mjs < [{"trip": ..., "report": ...}, ...]
//     prints, for each TRIP as the view sends it, the calendar that the page draws. The report
//     is the one that the TRIP came with, as JSON, or null.
import { readFileSync } from "node:fs";
import { calendar } from "../src/agloe/view/static/calendar.js";

const asked = JSON.parse(readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(asked.map(({ trip, report }) => calendar(trip, report))));
