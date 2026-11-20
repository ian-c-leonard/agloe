// The reference checker, in a worker of its own, so that a slow check never freezes the page.
//
// It loads Pyodide (Python for browsers), the packages Agloe needs and Agloe itself, all from
// vendor/, which tools/build_site_checker.py fills. Then it answers one message at a time:
//   in:  { id, file }            the FILE, as JSON text
//   out: { id, answer, text, json, seconds }   the report, or
//        { id, refused: [...] }                the FILE does not follow the format, or
//        { id, failed: "..." }                 something broke
// Before the first answer it posts { ready: true }, or { failed: "..." } if it cannot start.
import { loadPyodide } from "./vendor/pyodide/pyodide.mjs";

const here = (path) => new URL(path, import.meta.url).href;

const check = (async () => {
  const listed = await (await fetch(here("vendor/checker.json"))).json();
  const python = await loadPyodide({ indexURL: here("vendor/pyodide/") });
  await python.loadPackage(listed.packages, { messageCallback: () => {} });
  for (const wheel of listed.wheels) {
    python.unpackArchive(await (await fetch(here("vendor/" + wheel))).arrayBuffer(), "wheel");
  }
  python.runPython(await (await fetch(here("checker.py"))).text());
  return python.globals.get("check");
})();

check.then(
  () => self.postMessage({ ready: true }),
  (problem) => self.postMessage({ failed: String(problem && problem.message ? problem.message : problem) }),
);

self.onmessage = async ({ data }) => {
  try {
    self.postMessage({ id: data.id, ...JSON.parse((await check)(data.file)) });
  } catch (problem) {
    self.postMessage({ id: data.id, failed: String(problem && problem.message ? problem.message : problem) });
  }
};
