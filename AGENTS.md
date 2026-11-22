# Working on Agloe

This file is for the AI agents and people who build Agloe. Read it before changing anything.

## Where the truth lives

- [docs/VISION.md](docs/VISION.md): what Agloe is and what it must be.
- [spec/foundation.md](spec/foundation.md) and [spec/vocabulary.md](spec/vocabulary.md): what a TRIP means. A term in capitals means exactly what the vocabulary says.
- [spec/rules.md](spec/rules.md): exactly what the COMPILER checks. The reference checker in `src/agloe/reference.py` applies these rules directly, and it defines the right answer. The COMPILER in `src/agloe/compiler.py` finds the same answers with a solver. Both hand their search to `src/agloe/answers.py`, which works out the three answers and the evidence.
- [docs/PRINCIPLES.md](docs/PRINCIPLES.md): how Agloe is built. Follow all eight principles.
- [docs/decisions/](docs/decisions/): why things are the way they are. When a decision changes, its record is rewritten to the new decision.
- [docs/ROADMAP.md](docs/ROADMAP.md): what each release contains.
- [src/agloe/view/](src/agloe/view/): the view, a page for a person. The command `agloe view FILE` serves it on the person's own machine, checks the FILE each time its content changes, and sends the page the answer and the report, each with the number of the state of the FILE that it is about. Nothing in the page judges a TRIP: every mark comes from the FILE or from the COMPILER's report on it. The page reads no FILE: with each report, `src/agloe/view/trip.py` gives it the TRIP as a drawing needs it. `src/agloe/view/static/state.js` works out what the page says in each state, `src/agloe/view/static/calendar.js` lays out the calendar, `src/agloe/view/static/strip.js` puts the days of that calendar one after another on a strip, `src/agloe/view/static/persons.js`, `src/agloe/view/static/wants.js`, `src/agloe/view/static/options.js`, `src/agloe/view/static/rights.js`, `src/agloe/view/static/budgets.js`, `src/agloe/view/static/ways.js`, `src/agloe/view/static/capabilities.js` and `src/agloe/view/static/objects.js` put the PERSONs, the WANTs, the OPTIONs, the rights to them, the BUDGETs, the WAYs, the CAPABILITIES and the OBJECTs of the FILE in words, `src/agloe/view/static/who.js` says who is in an OPTION and whether they need a right to be, `src/agloe/view/static/times.js` writes a day, a time and a length of time as the report does, `src/agloe/view/static/money.js` writes an amount of money and a payment as the report does, `src/agloe/view/static/lines.js` ties each line of the report to what it is about, and `src/agloe/view/static/named.js` reads what a report names for the parts that mark it. The tests run all of these with Node, and `tests/test_view_browser.py` drives the page itself in a real browser. [Decision 0006](docs/decisions/0006-the-view-is-a-page-that-a-local-command-serves.md) says why it is built this way.
- [pages/](pages/): the home page, [agloe.ai](https://agloe.ai). It quotes the documents and shows reports from the examples, and it marks each passage with the file it comes from. It also draws the first story as a day that a reader can change. The day is drawn from the FILE. When the reader changes it, the reference checker of this repository checks the new FILE in the reader's browser, through `pages/checker.py`. A test fails when a passage no longer matches its source, when that program and the examples disagree, or when the page's own code for changing a FILE (`pages/trip-file.js`, which the tests run with Node) writes a FILE that the format refuses. So change the page in the same pull request as the source. A merge to main that changes the page or the checker publishes the page. `tools/build_site_checker.py` fills `pages/vendor/`, which the page needs when it is served from a copy of the repository.

## Roles

- Ian Leonard owns the product. Product and architecture decisions are his. Present the options, the trade-offs and a recommendation, one decision at a time, and wait for his answer.
- Claude Code builds, and merges its own pull requests once the checks pass. Codex reviews each release, and any decision Ian asks it to check.
- Never file a GitHub issue or post an issue comment without Ian's approval of that specific text. The repository is public.

## How to work

1. Work in thin slices. Each slice runs from FILE to report, with its tests, before the next begins.
2. Write the specification text, the examples and the tests before the implementation. A new rule goes into `spec/rules.md` and the reference checker first. Anything faster must then give the same answers as the reference checker.
3. Every change goes through a small pull request, and merges only after the automated checks pass on Linux and macOS. Branch protection enforces this; nothing is pushed to main directly. Never claim that something works or is fixed without showing the evidence.
4. Use established methods and libraries first. Write a decision record before building anything genuinely new.
5. Never special-case a rule to make one example pass. Fix the example's data, or change the model by decision.

## Writing

- Plain English, short sentences, and natural paragraphs without hard line breaks.
- Vocabulary terms in capitals. Lead with the plain statement; put the source after it.
- Every document describes the current state only. It never records corrections, earlier versions, past mistakes or what changed; git history holds all of that. When something changes, rewrite the document so it reads as if it had always been this way.
- No issue numbers or dated rulings in product prose.
- Describe what a rule does instead of giving it a coined name.

## Privacy

- Example trips are fictional. Never commit real trip data, personal details, local file paths or secrets.
- Payment card numbers never appear anywhere.
