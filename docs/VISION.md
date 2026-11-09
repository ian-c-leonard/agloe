# Agloe

Agloe is a standard format for trips, a compiler that checks them, and an optimizer that finds the best version.

## Why now

AI agents are starting to plan trips. An agent can seat eight friends at dinner in its head. Seating 800 is different: it needs the guest list written down, the rules codified, and something that checks every seat against every rule. A real trip is the 800 case: many people, legs, bookings and times, all affecting each other.

So agents need three things:

1. **A place to keep the plan.** Agents can read and write far more detail than people, but they forget. Conversations get compressed, sessions end, and people switch agents. The plan must live somewhere lasting that any agent or person can pick up.
2. **Codified rules, and a checker that applies them.** The same answer every time, with the reason for every problem it finds.
3. **A way to say what you want, not just what is possible.** A plan can work and still be wrong for the people on it. Travelers need to state their priorities, so the best version can be found and its trade-offs shown.

People planning without AI benefit in the same way.

## What Agloe is

1. **A standard format** that represents a trip and all its nuances, readable by people and machines. It is the lasting record.
2. **A compiler** that checks the whole plan and explains every conflict.
3. **An optimizer** that finds the best version for the priorities people set.

## What it must be

- **Trustworthy.** Anyone, person or agent, can check any trip, including one an AI drafted, and rely on the answer.
- **Flexible.** It works for any kind of trip.
- **Whole-lifecycle.** It covers the first idea, planning, booking, the live trip, recovery when things go wrong, and the record afterwards. The file keeps the agreed plan, the current forecast and what actually happened.
- **Intuitive.** It is easy to read and understand.
- **Multiplayer.** Several people and their agents share one plan. They propose changes, the file records what the group decided and why, and the trip stays fair to everyone.
- **Open.** It imports what travelers already have, publishes to the tools they already use, and hands purchases to the services that sell them.
- **Durable.** The file outlives any app, the way a calendar file does.
- **Agent-ready.** AI agents write the file and use it as shared memory across sessions and tools.
- **Self-explaining.** Every finding shows its evidence, and what is still missing.
- **Deterministic.** The same file gives the same answer on any machine, on any day.

## Where it stands

Each part exists somewhere in narrow form: trip formats, plan checkers in research, route optimizers, group planning apps. Nobody joins them. Agloe's contribution is the combination and its rigor: precise rules, clear explanations, and a format that always ships with its checker.
