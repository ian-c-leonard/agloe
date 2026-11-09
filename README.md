# Agloe

Agloe is a standard format for trips, a compiler that checks them, and an optimizer that finds the best version.

AI agents are starting to plan trips. They need three things: a lasting place to keep the plan, codified rules that check their work, and a way to say what people want rather than only what is possible. Agloe provides all three. People planning without AI benefit in the same way.

## Status

Agloe is being built in public, and there is nothing to install yet.

- **0.1, the COMPILER:** says whether a trip is FEASIBLE, INFEASIBLE or UNDETERMINED, and explains every finding with its evidence.
- **0.2, the OPTIMIZER:** finds the best version of a trip for the priorities people set.

See the [roadmap](docs/ROADMAP.md) for what each release contains.

## Documents

- [Vision](docs/VISION.md): the problem, the product and what it must be.
- [Foundation](spec/foundation.md): what a trip file means and what the compiler answers.
- [Vocabulary](spec/vocabulary.md): the protected terms, written in capitals throughout.
- [Engineering principles](docs/PRINCIPLES.md): how Agloe is built.
- [Decisions](docs/decisions/): why it is built this way.

## How it is built

Ian Leonard designs Agloe and makes its product decisions. AI agents do much of the building: Claude Code writes the code, and Codex reviews each release. The principles and decisions are public, so anyone can see why Agloe works the way it does.

## The name

Agloe was a town that appeared on maps of New York State but did not exist. Mapmakers invented it in the 1930s to catch anyone copying their maps. Agloe the compiler catches the parts of a plan that are not really there.

## License

Apache License 2.0. See [LICENSE](LICENSE).
