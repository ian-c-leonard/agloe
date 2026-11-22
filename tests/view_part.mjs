// Runs the view's own code for one part of the page that shows what a FILE holds: its WANTs,
// its OPTIONs or its CAPABILITIES. For the tests of each of those parts.
//
//   node view_part.mjs wants < [{"trip": ..., "report": ..., "text": ...}, ...]
//     prints, for each TRIP as the view sends it, what the page shows of its WANTs. The report
//     is the one that the TRIP came with, as JSON and in words, or null. Where the report in
//     words is given, the part gets the words of each case in which it says the trip works.
//     In the place of wants: options, or capabilities.
import { readFileSync } from "node:fs";
import { statedIn, lines } from "../src/agloe/view/static/lines.js";

const name = process.argv[2];
const part = (await import(`../src/agloe/view/static/${name}.js`))[name];
const asked = JSON.parse(readFileSync(0, "utf8"));
const shown = asked.map(({ trip, report, text }) => part(trip, report, text === null ? null : statedIn(lines(text, report, trip))));
process.stdout.write(JSON.stringify(shown));
