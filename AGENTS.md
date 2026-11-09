# Working on Agloe

This file is for the AI agents and people who build Agloe. Read it before changing anything.

## Where the truth lives

- [docs/VISION.md](docs/VISION.md): what Agloe is and what it must be.
- [spec/foundation.md](spec/foundation.md) and [spec/vocabulary.md](spec/vocabulary.md): what a TRIP means. A term in capitals means exactly what the vocabulary says.
- [docs/PRINCIPLES.md](docs/PRINCIPLES.md): how Agloe is built. Follow all eight principles.
- [docs/decisions/](docs/decisions/): why things are the way they are. When a decision changes, its record is rewritten to the new decision.
- [docs/ROADMAP.md](docs/ROADMAP.md): what each release contains.

## Roles

- Ian Leonard owns the product. Product and architecture decisions are his. Present the options, the trade-offs and a recommendation, one decision at a time, and wait for his answer.
- Claude Code builds, and merges its own pull requests once the checks pass. Codex reviews each release, and any decision Ian asks it to check.
- Never file a GitHub issue or post an issue comment without Ian's approval of that specific text. The repository is public.

## How to work

1. Work in thin slices. Each slice runs from FILE to report, with its tests, before the next begins.
2. Write the specification text, the examples and the tests before the implementation.
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
