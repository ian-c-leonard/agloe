// Runs the view's own code for the calendar, for tests/test_view_calendar.py.
//
//   node view_calendar.mjs < [trip, ...]
//     prints, for each TRIP as the view sends it, the calendar that the page draws
import { readFileSync } from "node:fs";
import { calendar } from "../src/agloe/view/static/calendar.js";

process.stdout.write(JSON.stringify(JSON.parse(readFileSync(0, "utf8")).map((trip) => calendar(trip))));
