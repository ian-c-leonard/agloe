// Runs the view's own code for the lines of a report, for tests/test_view_lines.py.
//
//   node view_lines.mjs < [{"text": ..., "report": ..., "trip": ...}, ...]
//     prints, for each report in words, its lines and what each is about. The report is the
//     same report as JSON, and the TRIP is the one that the view sends with it.
import { readFileSync } from "node:fs";
import { lines } from "../src/agloe/view/static/lines.js";

const asked = JSON.parse(readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(asked.map(({ text, report, trip }) => lines(text, report, trip))));
