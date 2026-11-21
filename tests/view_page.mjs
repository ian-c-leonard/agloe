// Runs the view's own code for what the page says, for tests/test_view.py.
//
//   node view_page.mjs < [[event, ...], ...]
//     prints, for each series of events, what the page says before any event and after each one
//
// An event that the page's code does not know ends this with an error.
import { readFileSync } from "node:fs";
import { after, says, start } from "../src/agloe/view/static/state.js";

const said = JSON.parse(readFileSync(0, "utf8")).map((series) => {
  let state = start();
  const each = [says(state)];
  for (const event of series) {
    state = after(state, event);
    each.push(says(state));
  }
  return each;
});
process.stdout.write(JSON.stringify(said));
