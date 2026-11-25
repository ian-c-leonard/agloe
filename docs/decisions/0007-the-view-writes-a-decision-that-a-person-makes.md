# 0007. The view writes a DECISION that a person makes on the page

- **Status:** Proposed
- **Date:** 2026-11-25
- **Decided by:** Ian Leonard

## Context

The view is a companion to an agent that plans a TRIP. The agent writes the FILE, and a person watches the page, often in a narrow window beside the agent. The page lists what has to be done or decided.

Some of that only a person can settle. Whether the group really takes the train that the COMPILER chose is not a FACT that an agent can look up. In Agloe such a choice is a DECISION, and the first kind is a LOCK: the TRIP includes this OPTION, and these PERSONs take part.

The view writes nothing. To settle anything, the person tells the agent, and the agent writes the FILE.

A FACT is another matter. It says how the world is, and an agent finds it out.

## Options considered

1. **The page only shows.** The person tells the agent each DECISION in words. Every one costs a turn of the agent, for something that the person has already made up their mind about.
2. **The page writes any record: an editor.** A person could then state every FACT by hand. That is the agent's work, and every kind of record that the page can write has to follow the format as it changes.
3. **The page passes the person's wish to the agent, and the agent writes the FILE.** The FILE keeps one writer. There is no such channel, and the FILE is already the place that the person and the agent share.
4. **The page writes DECISIONs, and nothing else.** One click settles what only the person can settle, and the agent finds it in the FILE.

## Decision

The view writes a DECISION that a person makes on the page, and writes nothing else.

- The first DECISION is a LOCK. Where a plan holds an OPTION with PERSONs in it whom no LOCK names, the page offers to decide it. One click adds one LOCK to the FILE: that OPTION, with those PERSONs.
- A write adds a record. It changes no record and removes none. The vocabulary says that a DECISION is never edited, and that changing your mind is a new DECISION that names the one it undoes. The format has no such DECISION yet. So the page cannot take a LOCK back, and it does not remove one to make it seem so.
- The page offers a click only for what the FILE can hold. It never writes a FACT.
- The page opens as a viewer. A switch at the top of the page says "Viewing" or "Editing", and it says "Viewing" each time the page opens. Only the person moves it. The page offers a click only while it says "Editing". So a page that somebody opened to look changes nothing, and nobody has to start the view again to decide something.
- A write goes through the view. The page sends the DECISION with the number of the state of the FILE that it shows. The view writes only if the FILE is still in that state. It makes the new FILE, checks it with the reader that the COMPILER uses, writes it beside the FILE, and moves it into place in one step. Then it sees the change as it sees every change, and the COMPILER checks the new FILE. Where the FILE has changed in the meantime, the view writes nothing and says so, and the page shows the FILE as it is now.
- The view writes the whole FILE again as JSON, with its records in the order they had. A FILE that was written another way looks different afterwards, and says the same.
- The view takes a request to write only from its own page. Such a request says which site it comes from, and the view refuses it where that is not the view's own site, or where it does not say.
- Nothing in the page judges a TRIP. The page offers the click from the FILE and from the report, and the COMPILER answers on the FILE that the click made.

## Consequences

- A person settles a DECISION with one click, and the agent sees it in the FILE the next time it reads the FILE.
- Two writers share one FILE. An agent that writes the FILE from a copy it read earlier can write over a DECISION that a person has made since. An agent has to read the FILE before it writes it. The view cannot keep an agent from doing otherwise.
- A click cannot be taken back on the page until the format has a DECISION that undoes another. Until then the agent takes a LOCK out of the FILE, or a person does by hand.
- The FILE does not say who made a DECISION, or when. The vocabulary calls a DECISION a dated choice by a PERSON, and the format has no place for either yet. A LOCK that the page writes looks like one that an agent wrote.
- The command needs the right to write in the folder of the FILE.
- Whoever can open the page can write a DECISION. The view has no sign-in. Where it answers under a name of its owner's, the gateway before it decides who that is.
- Each further kind of DECISION that the page can write is a small step of its own: the time at which the TRIP starts or ends, a cap, and a DISMISSAL once the format has one.
