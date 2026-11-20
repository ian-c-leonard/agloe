<p align="center">
  <a href="https://agloe.ai"><img src=".github/assets/banner.jpg" alt="Agloe: check whether a trip works" width="100%"></a>
</p>

Agloe is a standard format for trips, a compiler that checks them, and an optimizer that finds the best version.

AI agents are starting to plan trips. They need three things: a lasting place to keep the plan, codified rules that check their work, and a way to say what people want rather than only what is possible. Agloe provides all three. People planning without AI benefit in the same way.

The home page is [agloe.ai](https://agloe.ai).

## Status

Agloe is being built in public, and nothing is published to install yet. The first release, the COMPILER, is being built in steps.

Today the COMPILER reads a trip file and gives one of three answers, each with its evidence:

- **FEASIBLE:** the trip works. The report shows a plan, and warns when the plan holds only if uncertain durations stay short.
- **INFEASIBLE:** the trip cannot work. The report names the FACTs, WANTs and DECISIONs that clash.
- **UNDETERMINED:** the file does not say enough to tell. The report names what it would have to say for the trip to work.

It checks times and places for one traveler or a group, over one day or several. It checks what each person must have and must not have. It also checks that the trip fits between its start and its end, and that each person ends it where they have to. The [rules](spec/rules.md) say exactly what it checks, and every trip under [`examples/`](examples/) is one of its tests.

From a copy of this repository:

```
uv run agloe check examples/flight-home/works.json
uv run agloe check examples/a-must/cannot-work.json
```

The releases:

- **0.1, the COMPILER:** says whether a trip is FEASIBLE, INFEASIBLE or UNDETERMINED, and explains every finding with its evidence.
- **0.2, the OPTIMIZER:** finds the best version of a trip for the priorities people set.

See the [roadmap](docs/ROADMAP.md) for what each release contains.

## Documents

- [Vision](docs/VISION.md): the problem, the product and what it must be.
- [Foundation](spec/foundation.md): what a trip file means and what the compiler answers.
- [Vocabulary](spec/vocabulary.md): the protected terms, written in capitals throughout.
- [Rules](spec/rules.md): exactly what the compiler checks, with examples that run as tests.
- [Engineering principles](docs/PRINCIPLES.md): how Agloe is built.
- [Decisions](docs/decisions/): why it is built this way.

## How it is built

Ian Leonard designs Agloe and makes its product decisions. AI agents do much of the building: Claude Code writes the code, and Codex reviews each step and each release. The principles and decisions are public, so anyone can see why Agloe works the way it does.

## The name

Agloe was a town that appeared on maps of New York State but did not exist. Mapmakers invented it in the 1930s to catch anyone copying their maps. Agloe the compiler catches the parts of a plan that are not really there.

## License

Apache License 2.0. See [LICENSE](LICENSE).
