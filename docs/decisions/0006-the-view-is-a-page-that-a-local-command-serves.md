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

- The command watches the FILE. A state of the FILE is its content at one look, and each new state gets a number, its revision. For each state the command tells the page that there is a FILE to check, runs the COMPILER on that content in a process of its own, and sends the answer as soon as it is proved, then the report in words and as JSON. A check that is still running when the FILE changes again is ended.
- Nothing in the view judges a TRIP. Every mark on the page comes from the FILE or from the COMPILER's report on that FILE.
- The command reads the FILE for the page, with the reader that the COMPILER uses. With each report it sends what a drawing needs: the names, the days, who takes part in each step, and each time on the clocks that the report shows times on. The page itself reads no FILE, and works out no time.
- Everything that the page is sent names the revision it is about. The page shows no answer on a state of the FILE until the COMPILER has answered on that state. While a check runs, the page marks what it still shows of the report on the FILE as it was before.
- A FILE with no report gets the reason instead. The page shows the problems that the format names, or says that the FILE cannot be read, or that a check stopped before its report came. It says each of these in its own words, and never as an answer.
- The command serves the person's own machine only, and the page asks no other host for anything.
- The view lives in [`src/agloe/view/`](../../src/agloe/view/), so it is installed with Agloe: the program that serves, and the page as files beside it. The page is plain HTML, CSS and JavaScript, with nothing to build.
- The view has its own part of the [roadmap](../ROADMAP.md). It is built alongside the releases and does not delay them.

## Consequences

- A person needs Agloe on their machine to use the view. The view is checked on Linux and on macOS, as the rest of Agloe is. A view for people without it needs the first or the second option, by a decision of its own.
- The view shows what a report holds. A report shows an ITINERARY that the travelers can use only for a FEASIBLE TRIP.
- The page draws a calendar of the TRIP: a column for each day, and in it a column for each PERSON. The days run from the first step, or from when the TRIP starts, to the last step, or to when the TRIP ends. For a FEASIBLE TRIP the calendar holds the ITINERARY of the report, and it marks each PERSON whom no LOCK names for an OPTION. For any other TRIP it holds only the OPTIONs that a LOCK names, at the times the FILE states, and it says so. OPTIONs that one PERSON is in at the same time stand side by side.
- The calendar marks what a report names. Each step that the view sends names the FACTs and DECISIONs of the FILE that are about it. A report on a TRIP that cannot work names the FACTs, WANTs and DECISIONs that rule out every plan. So a red edge is on each step that those are about, and on the start or the end of the TRIP. The page judges nothing: it finds the same ids in both.
- The page ties each line of the report in words to the step that it shows, or to the record that it names. A report shows a plan one step to a line, puts what it warns of under the step, and starts the line of a record with its id. So pointing at a step lights up what the report says of it, and pointing at a line lights up what it is about. The calendar puts a yellow edge on each step at which the report warns of something, with the report's own words. This is in [`src/agloe/view/static/lines.js`](../../src/agloe/view/static/lines.js), which a test runs on every example.
- Above the calendar, a strip shows all the days of the calendar at once: a row for each PERSON, and time from left to right. The strip is the calendar on its side. [`src/agloe/view/static/strip.js`](../../src/agloe/view/static/strip.js) takes the calendar as it is laid out and puts its days one after another in the pixels that the page has, so the strip holds the same marks with the same edges, and no others. Where the calendar does not show some hours between two days, the strip leaves them out, and it says so. A strip is narrow: steps that are too close together to show apart at its width are one mark, which says how many they are and names each. Pointing at a step on the strip lights up the same step in the calendar and in the report, and a click brings it into view in the calendar. A calendar that shows one day has no strip.
- The command works out which day a step is on, and which part of it lies on each day, by the time-zone database pinned with Agloe. A day on which the clocks change is two columns, one before the change and one after, and each names its offset from UTC. So two moments that the clocks show as one time of day are never drawn as one. A time gives its offset from UTC wherever the report gives its times with theirs, and it is written the same way.
- The answer and the report show without the calendar. A calendar that fails to load or to draw leaves both on the page. A report reaches the page whatever becomes of its calendar: where what the calendar draws cannot be made, or is not what a page can draw, the report comes without it.
- The calendar is laid out in [`src/agloe/view/static/calendar.js`](../../src/agloe/view/static/calendar.js), which has no page in it. A test runs it with Node on every example, and checks its words against the report.
- A check that takes long shows its answer first, and the page says that the report is on its way.
- The words the page shows for each state are worked out in [`src/agloe/view/static/state.js`](../../src/agloe/view/static/state.js), which has no page in it. A test runs it with Node on what the command sends for the examples.
- The tests start the view on an example, change the FILE, and read what a page is sent. They also stop the command while a page listens, and put a program that never ends in the place of a check.
- The view serves a port from 1024 to 65535 that browsers open. Where no port is given, it takes a free one of those. It refuses a request that names another host, or that says it comes from another site, and it tells the browser to show the page in no other page.
- Each view has a name of its own and says it with each new state of the FILE. A page that listened to one view lets its report go when another view answers at the same address.
