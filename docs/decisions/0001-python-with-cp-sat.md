# 0001. Python, with CP-SAT as the engine

- **Status:** Accepted
- **Date:** 2026-11-08
- **Decided by:** Ian Leonard

## Context

The COMPILER must decide whether any ITINERARY meets every CONSTRAINT, give the same answer and explanation every time, and run offline inside a library. The OPTIMIZER must then rank FEASIBLE ITINERARIES by SCORE. Both rest on one engine, so the engine is the most important technical choice, and it should decide the language rather than the other way round.

## Options considered

1. **Google's CP-SAT solver, used from Python.** CP-SAT is built for this shape of problem: optional activities, time windows, nobody in two places at once, shared resources and optimization. It won gold in the MiniZinc Challenge, the main constraint-solver competition, in 2018, 2024, 2025 and 2026. Its core is C++, with official interfaces for Python, Java and C#; Python is the most used. It is Apache-2.0 and very actively developed.
2. **A small engine of our own, in TypeScript.** No dependency and runs in a browser, but we would write and test the search ourselves, and the OPTIMIZER would need a second engine for speed.
3. **Z3, Microsoft's general solver.** Mature, but a 39 MB download with threads, 265 MB of memory on a trivial trip, and optimization measured at 53 seconds on a small problem that CP-SAT solved in 9 milliseconds.
4. **Others.** MiniZinc needs a separate native installation; clingo cannot reason about time without listing every minute.

## Decision

Agloe is written in Python, and CP-SAT is the engine for both the COMPILER and the OPTIMIZER.

- Whichever engine runs, Agloe's own code translates the FILE into the model, produces the three answers, and builds the explanations. CP-SAT replaces only the search, which is the part most worth taking from an established tool.
- Explanations do not use the solver's own conflict reports, which vary with its settings. They use QuickXplain over Agloe's labeled constraints, so the same FILE always gives the same explanation.
- A small brute-force checker for tiny trips cross-checks CP-SAT's answers in tests.

## Consequences

- Python 3.14 is pinned, because the current OR-Tools release (9.15) ships builds up to Python 3.14.
- Agloe is distributed through PyPI. Its command line and MCP tool run with one command; other languages reach it through the MCP tool or the command line rather than in a browser.
- OR-Tools is a large native dependency, pinned to an exact version.
- A single-threaded CP-SAT run is deterministic, provided Agloe builds the model in a fixed order. That results match across machines is tested on Linux and macOS before it is relied on.

## Confirmation

The lock file pins OR-Tools exactly; CI runs the test suite, including the brute-force cross-check, on Linux and macOS.
