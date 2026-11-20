# Roadmap

Agloe grows in releases, each built on one that already works. Before 1.0, anything may still change.

## 0.1: the COMPILER

- The format, defined by a published JSON Schema and an executable specification whose examples are its tests.
- The COMPILER: for any TRIP it answers FEASIBLE, INFEASIBLE or UNDETERMINED, and reports every FINDING with its evidence, including DEADLINEs and BETs.
- A command line, a Python library and an MCP tool, so an AI agent can use the COMPILER from the start.

0.1 is built in steps along one fictional trip to Chicago: one connection, a full day, a group, several days, musts and must-nots, tickets and money, cars and drivers, DEADLINEs and BETs, and the tools for an AI agent.

0.1 is done when the COMPILER gives the right answer at every step of that trip, and an AI agent plans the trip with it. The agent gets a one-page description of the trip and of Agloe. It writes the FILE, reads the COMPILER's reports, and ends with a FEASIBLE TRIP, with no other help.

## 0.2: the OPTIMIZER

- The OPTIMIZER: ranking FEASIBLE ITINERARIES by SCORE, with each PERSON's SCORE shown beside the total.
- Comparing VARIANTs side by side, fairness reporting, and repair when the agreed ITINERARY stops working.

Later releases are planned once 0.2 works.

## The view

The view is a page for a person. It shows a TRIP from its FILE and from the COMPILER's report, and it follows the FILE as the FILE changes. The command `agloe view FILE` serves it on the person's own machine.

The view is built beside the releases, in steps of its own, and it holds no release up. Its first step shows the COMPILER's answer and report, and keeps them up to date. Each later step adds one drawing of the TRIP, or one way to change the TRIP by hand.
