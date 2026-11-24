// Runs the code behind the figure of variables and statements on the page "How a rule is built",
// for tests/test_website.py.
//
//   node website_statements.mjs < [{ statements, variables, yes }]
//     prints, for each board of the figure: every setting of its variables that makes every
//     statement true, and whether each statement is true with the variables in `yes` set to yes
import { readFileSync } from "node:fs";
import { holds, settings } from "../pages/how-a-rule-is-built/statements.js";

const given = JSON.parse(readFileSync(0, "utf8"));
console.log(JSON.stringify(given.map(({ statements, variables, yes }) => ({
  settings: settings(statements, variables),
  holds: statements.map((says) => holds(says, new Set(yes))),
}))));
