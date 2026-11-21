// Runs the view's own code for the WANTs of a FILE, for tests/test_view_wants.py.
//
//   node view_wants.mjs < [{"trip": ..., "report": ..., "text": ...}, ...]
//     prints, for each TRIP as the view sends it, what the page shows of its WANTs. The report
//     is the one that the TRIP came with, as JSON and in words, or null. Where the report in
//     words is given, the WANTs get the words of each case in which it says the trip works.
import { readFileSync } from "node:fs";
import { casesOf, lines } from "../src/agloe/view/static/lines.js";
import { wants } from "../src/agloe/view/static/wants.js";

const asked = JSON.parse(readFileSync(0, "utf8"));
const shown = asked.map(({ trip, report, text }) => wants(trip, report, text === null ? null : casesOf(lines(text, report, trip))));
process.stdout.write(JSON.stringify(shown));
