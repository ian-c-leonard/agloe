# Engineering principles

These principles govern how Agloe is built. What Agloe means, its product principles, lives in the [specification](../spec/foundation.md).

A principle earns its place here only if it passes five tests:

1. **It decides something.** It settles a choice the builder will face again and again.
2. **Its opposite is reasonable.** A competent engineer could choose the opposite; otherwise it says nothing.
3. **It is grounded.** It rests on the project's own standing rules, an established source, or measured evidence.
4. **It is distinct.** It is not already a product principle, and not just a detail of another principle.
5. **It is actionable.** The builder can apply it without asking.

Practices that serve a principle are listed under it, not as principles of their own.

## 1. Correct before fast

The COMPILER is exact first. When it cannot finish, it says UNDETERMINED; it never guesses to save time. Anything faster built later must give the same answers.

- *Decides:* what to do when exact checking is slow.
- *Rejects:* heuristic-first planners that are fast but sometimes wrong, as most AI trip planners are.
- *Source:* the project's rule that the reference COMPILER establishes meaning before search performance; differential testing (McKeeman, "Differential Testing for Software", Digital Technical Journal, 1998).
- *In practice:* the OPTIMIZER is tested against the COMPILER on the same FILEs, and real trips with known verdicts are the acceptance tests.

## 2. The simplest thing that fully works

Build only what is needed now, once, and properly: no speculative features, no duplicated logic, no stopgaps meant to be replaced.

- *Decides:* how much to build, and whether to generalize.
- *Rejects:* designing ahead for imagined needs, and quick hacks.
- *Source:* the project's standing rules ("Choose the simplest implementation that fully meets the current requirements"; "Do not accept a stopgap"); Kent Beck's rules of simple design (Extreme Programming Explained, 1999).
- *In practice:* one engine for every CONSTRAINT, and a concept enters the model only with the slice of work that needs it.

## 3. Build on established methods

Before designing anything, find how mature tools or research already solve it, and use that. Use a maintained library where one fits; otherwise implement the published method.

- *Decides:* invent or adopt.
- *Rejects:* bespoke approaches built from scratch.
- *Source:* the project's standing rules ("Study how established products solve the problem before designing a solution"; "Prefer established, well-maintained libraries").
- *In practice:* Google's CP-SAT solver is the engine, explanations use QuickXplain, and anything genuinely new needs a short decision record saying why nothing established fits.

## 4. Grow in thin, working slices

Each step works from FILE to report before the next begins, and lands on main the same day.

- *Decides:* what to build next, and when to merge.
- *Rejects:* building one layer at a time and connecting the layers at the end; long-lived branches.
- *Source:* the project's standing rule ("Grow the system in layers ... Never trade a working product for unfinished complexity"); the walking skeleton (Cockburn, Crystal Clear, 2004); tracer bullets (Hunt and Thomas, The Pragmatic Programmer, 1999).
- *In practice:* the first slice checks a ferry connection from end to end.

## 5. General, never special-cased

Rules describe trips in general. When a real trip does not fit, fix its data or change the model by decision; never add a branch for one FILE, place or kind of trip.

- *Decides:* what to do when a case fails.
- *Rejects:* patching a rule so one example passes, the usual pragmatic fix.
- *Source:* the project's standing rules ("Rules describe the world, never our files"; "Examples are probes, not ontology").
- *In practice:* an example proves the model can express something; it never adds a type or a rule on its own.

## 6. Strict at the edges

Malformed input is refused with a precise ERROR. Nothing is silently repaired, defaulted or guessed, and an internal inconsistency stops the run loudly rather than returning a partial answer.

- *Decides:* how to treat input that is almost right, and internal surprises.
- *Rejects:* "be liberal in what you accept", the old robustness principle; auto-fixing agents' mistakes.
- *Source:* RFC 9413, Maintaining Robust Protocols (Thomson and Schinazi, 2023), which found that tolerating bad input erodes interoperability over time; Fail Fast (Shore, IEEE Software, 2004).
- *In practice:* one accepted shape for each thing and no lenient modes, which matters doubly because many different agents write FILEs.

## 7. Free to change until 1.0

Before 1.0, the format and the code change freely: no migrations, compatibility layers, deprecated fields or leftover markers.

- *Decides:* what to do with old shapes when the format changes.
- *Rejects:* preserving compatibility from the first release.
- *Source:* the project's standing rule ("Do not preserve backward compatibility"); Semantic Versioning 2.0.0, rule 4 ("Anything MAY change at any time").
- *In practice:* examples and tests are rewritten in the current shape, and compatibility promises begin at 1.0, by decision.

## 8. Agreement is enforced by the build

Anything that must stay in step is checked automatically, and a mismatch fails the build: a CONSTRAINT with its specification, examples, tests and explanation page; the schema with the code; the structure rules. Nothing relies on someone remembering.

- *Decides:* how to keep things in sync.
- *Rejects:* keeping them in sync through review and discipline.
- *Source:* fitness functions (Ford, Parsons and Kua, Building Evolutionary Architectures, 2017).
- *Evidence:* inside Rust's own compiler, explanation pages are enforced by the build and all 518 error codes have one, while per-code tests only trigger a warning and 42% have one.
- *In practice:* tests use only the public interface, specification examples run as tests, and import structure and size limits are checked.
