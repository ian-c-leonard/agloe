# 0005. The home page runs the reference checker in the reader's browser

- **Status:** Accepted
- **Date:** 2026-11-19
- **Decided by:** Ian Leonard

## Context

The home page shows one trip, and a reader can change it: move an OPTION, make it longer, add one. The page must then say whether the changed trip is FEASIBLE, INFEASIBLE or UNDETERMINED, with the evidence. That answer has to be Agloe's own. A page that answered by some other means could disagree with the COMPILER, and nobody would know.

The COMPILER uses the CP-SAT solver. The solver's Python library is published for macOS, Linux and Windows. It has no build for browsers.

## Options considered

1. **Write the rules again in JavaScript for the page.** The rules would exist a third time, and the page could drift from them.
2. **Work out every answer when the page is built.** The page could only offer changes that were foreseen, so a reader could not move anything freely.
3. **Run the COMPILER on a server that the page asks.** The answers would be exact and fast. It needs a service to host and to protect, and the trip would leave the reader's browser.
4. **Run the reference checker in the reader's browser.** Pyodide runs Python in a browser. The reference checker needs no solver, and it defines the right answer.

## Decision

The home page runs the reference checker of this repository in the reader's browser.

- [`pages/checker.py`](../../pages/checker.py) is the whole of what the page adds: it reads one FILE, calls the reference checker and returns its report. Where the solver is missing, it puts a stand-in under the solver's name, so that `import agloe` succeeds. Nothing calls the stand-in.
- The checker runs in a worker of its own. A check that runs long gives way to a newer FILE.
- [`tools/build_site_checker.py`](../../tools/build_site_checker.py) gathers what the page loads: Agloe built from `src/`, Pyodide and the packages Agloe needs, and the time zone data that `uv.lock` names. Each download is checked against a recorded checksum. agloe.ai serves these files itself, so the page asks no other host for anything.
- The page says that the reference checker gave the answer, and how long it took.

## Consequences

- The page's answers are the reference checker's, so they are right by definition. A test runs `pages/checker.py` without the solver and compares its reports with the examples.
- The reference checker tries every order, so it is slow on a busy day. The page offers a small set of things to add, which keeps a check short.
- The first change a reader makes waits for the checker to load, which is about 14 MB before compression. The page loads it only when the reader shows interest in the trip.
- A change to the checker publishes the page again, so the page never runs an old checker for long.
- The fast COMPILER can replace the reference checker on the page when the solver has a build for browsers. The reports are the same, so nothing else on the page changes.
