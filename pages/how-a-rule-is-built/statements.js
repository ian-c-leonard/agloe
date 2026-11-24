// Statements about yes-or-no variables, as the page on how a rule is built shows them.
//
// The COMPILER states each rule as statements about variables. The page shows three kinds for
// one drive, and writes each in a few words:
//
//   "is alex"               the variable alex is yes
//   "or !used sam"          one of these holds: used is no, sam is yes
//   "max used alex sam jo"  used is yes exactly when one of alex, sam and jo is yes
//
// They stand for the COMPILER's `model.add(takes == 1)`, `model.add_bool_or(...)` and
// `model.add_max_equality(...)`. Nothing here touches the page, so the tests run it as it is.

/** Whether a statement is true when exactly these variables are yes. */
export function holds(says, yes) {
  const [kind, ...rest] = says.trim().split(/\s+/);
  const literal = (name) => (name.startsWith("!") ? !yes.has(name.slice(1)) : yes.has(name));
  if (kind === "is") return rest.every(literal);
  if (kind === "or") return rest.some(literal);
  if (kind === "max") return yes.has(rest[0]) === rest.slice(1).some((name) => yes.has(name));
  throw new Error(`no such statement: ${says}`);
}

/** Every setting of these variables that makes every statement true. Each is the list of variables that are yes. */
export function settings(statements, variables) {
  const found = [];
  for (let bits = 0; bits < 2 ** variables.length; bits += 1) {
    const yes = new Set(variables.filter((_, at) => bits & (1 << at)));
    if (statements.every((says) => holds(says, yes))) found.push([...yes]);
  }
  return found;
}
