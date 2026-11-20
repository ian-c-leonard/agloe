// Runs the home page's own code for reading and changing a FILE, for tests/test_website.py.
//
//   node website_gestures.mjs files < { stories, additions }
//     makes each change a reader can make to each version of the story, and prints the FILEs
//   node website_gestures.mjs draw < [{ name, file, report }]
//     reads each FILE with its report as the page does, and prints the FILEs that a further
//     change would write
//
// A change that the page's code cannot make, or a report that it cannot read, ends this with an error.
import { readFileSync } from "node:fs";
import { answerOf, change, gesture, holds, scene, text } from "../pages/trip-file.js";

const given = JSON.parse(readFileSync(0, "utf8"));
const copy = (value) => structuredClone(value);
// What a reader can do to each kind of thing on the day.
const ACTS = { event: ["move", "stretch"], departure: ["move", "cutoff"], ride: ["ride", "late"] };

/** Every change to one FILE, each by each of these many minutes. */
function changes(name, file, report, minutes) {
  const made = [];
  for (const item of scene(file, report).items) {
    for (const act of ACTS[item.kind] || []) {
      for (const by of minutes) {
        const changed = copy(file);
        if (gesture(changed, act, item, by)) made.push({ name: `${name}: ${act} ${item.id} by ${by}`, file: changed });
      }
    }
  }
  return made;
}

if (process.argv[2] === "files") {
  const made = [];
  for (const [version, file] of Object.entries(given.stories)) {
    // A little, a lot, and far past every limit.
    made.push(...changes(version, file, null, [-30, 5, 400]));
    for (const [piece, records] of Object.entries(given.additions)) {
      if (holds(file, records)) continue;
      const more = copy(file);
      change.add(more, records);
      made.push({ name: `${version}: add ${piece}`, file: more });
      made.push(...changes(`${version} with ${piece}`, more, null, [5]));
      const back = copy(more);
      change.remove(back, records);
      if (JSON.stringify(back) !== JSON.stringify(file)) throw new Error(`${version}: adding ${piece} and taking it away does not give the FILE back`);
    }
  }
  // A trip whose report asks for several things together, and gives no length for some of them.
  const odd = copy(given.stories["cannot-work"]);
  change.remove(odd, given.additions.complete);
  change.add(odd, given.additions.coffee);
  gesture(odd, "move", scene(odd, null).items.find((item) => item.id === "coffee"), -170);
  made.push({ name: "cannot-work: the ways are not all listed, and coffee is at 1:30 pm", file: odd });
  console.log(JSON.stringify(made));
} else {
  const made = [];
  for (const { name, file, report } of given) {
    const view = scene(file, report);
    for (const item of view.items) {
      const numbers = item.kind === "event" ? [item.start, item.length] : item.kind === "departure" ? [item.start] : [item.leaves, item.shown];
      if (!numbers.every(Number.isFinite)) throw new Error(`${name}: ${item.id} cannot be drawn`);
    }
    if (!["feasible", "risky", "infeasible", "undetermined"].includes(answerOf(report))) throw new Error(`${name}: the report gives no answer`);
    text(file);
    made.push(...changes(name, file, report, [5]));
  }
  console.log(JSON.stringify(made));
}
