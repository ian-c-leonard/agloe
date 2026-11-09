# Roadmap

Agloe grows in releases, each built on one that already works. Before 1.0, anything may still change.

## 0.1: the COMPILER

- The format, defined by a published JSON Schema and an executable specification whose examples are its tests.
- The COMPILER: for any TRIP it answers FEASIBLE, INFEASIBLE or UNDETERMINED, and reports every FINDING with its evidence, including DEADLINEs and BETs.
- A command line, a Python library and an MCP tool, so an AI agent can use the COMPILER from the start.

0.1 is done when the COMPILER catches the unreachable ferry in a real trip to Scotland and is used to plan one real upcoming trip.

## 0.2: the OPTIMIZER

- The OPTIMIZER: ranking FEASIBLE ITINERARIES by SCORE, with each PERSON's SCORE shown beside the total.
- Comparing VARIANTs side by side, fairness reporting, and repair when the agreed ITINERARY stops working.

Later releases are planned once 0.2 works.
