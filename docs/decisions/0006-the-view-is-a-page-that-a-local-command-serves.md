# 0006. The view is a page that a local command serves

- **Status:** Accepted
- **Date:** 2026-11-20
- **Decided by:** Ian Leonard

## Context

The COMPILER's report is made for an agent that plans a TRIP. A person needs to see the same TRIP: who is where and when, what is decided, what is still open, and what the report says. A person and their agent work on one FILE, so what the person sees has to follow the FILE as the agent changes it. Whatever it says about whether a TRIP works has to be Agloe's own answer.

The COMPILER answers a weekend for four PERSONs in about a second where the TRIP works. Its solver has no build for browsers. The reference checker runs in a browser, and it is too slow for a weekend.

## Options considered

1. **A page that runs the reference checker in the browser,** as the home page does. Only small TRIPs get an answer.
2. **A service on the internet that runs the COMPILER.** Anyone with a browser can use it. It needs a host to run and to protect, and the FILE leaves the person's machine.
3. **A page that a command serves on the person's own machine.** The COMPILER runs beside the FILE. It works for whoever has Agloe installed.

## Decision

The view is a page that the command `agloe view FILE` serves on the person's own machine.

- The command watches the FILE. Each time the FILE changes, it runs the COMPILER on it in a process of its own. It tells the page that there is a FILE to check, then sends the answer as soon as it is proved, then the report in words and as JSON. A check that is still running when the FILE changes again is stopped.
- Nothing in the view judges a TRIP. Every mark on the page comes from the FILE or from the COMPILER's report on that FILE.
- The page shows no answer on a FILE until the COMPILER has answered on that FILE. While a check runs, the page marks what it still shows of the report on the FILE as it was before.
- A FILE that does not follow the format has no report. The page shows the problems that the format names.
- The command serves the person's own machine only, and the page asks no other host for anything.
- The view lives in [`src/agloe/view/`](../../src/agloe/view/), so it is installed with Agloe: the program that serves, and the page as files beside it. The page is plain HTML, CSS and JavaScript, with nothing to build.
- The view has its own part of the [roadmap](../ROADMAP.md), beside the releases. It grows in steps of its own and holds no release up.

## Consequences

- A person needs Agloe on their machine to use the view. A view for people without it needs the first or the second option, by a decision of its own.
- The view shows what a report holds. A report gives a plan only for a FEASIBLE TRIP.
- A check that takes long shows its answer first, and the page says that the report is on its way.
- The words the page shows for each state are worked out in [`src/agloe/view/static/state.js`](../../src/agloe/view/static/state.js), which has no page in it. A test runs it with Node on what the command sends for the examples.
- A test starts the command's server on an example, changes the FILE, and reads what the page is sent.
