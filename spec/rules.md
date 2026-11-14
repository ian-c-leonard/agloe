# Rules

This document says exactly what the COMPILER checks. It turns the principles of the [foundation](foundation.md) into CONSTRAINTs, each stated as one sentence about a finished ITINERARY. Terms in capitals are defined in the [vocabulary](vocabulary.md).

The rules exist twice: here in words, and in the reference checker, [`src/agloe/reference.py`](../src/agloe/reference.py). The reference checker is a small program that applies these rules directly and uses no solver. It defines the right answer for small TRIPs, and anything faster must give the same answers. Every FILE under [`examples/`](../examples/) is one of its tests.

## What a FILE holds

A FILE lists PERSONs, PLACEs, OPTIONs, FACTs and DECISIONs. Its shape is fixed by the [schema](../src/agloe/schema/file.schema.json). Every record has an id that is unique in the FILE.

An OPTION happens at one PLACE, or moves from one PLACE to another. It happens at most once, and everyone who takes part in it starts and ends together.

A FACT states one thing:

| A FACT states | Meaning |
|---|---|
| a fixed start | The OPTION can start only at that time. |
| a start at any time | The planners choose when the OPTION starts. |
| a duration | The OPTION takes exactly that long. |
| a CONTINGENT duration | The world decides how long the OPTION takes, between a shortest and a longest value. |
| an access cutoff | Each PERSON must reach the OPTION's PLACE at least that long before it starts. |
| a COMPLETE set | The FILE lists every OPTION a PERSON could use to get from one PLACE to another, directly or through other PLACEs, leaving within a stated span of time. |

A LOCK names an OPTION and the PERSONs who take part in it.

## What is unknown

A FACT that the FILE does not state is unknown. The COMPILER never fills one in.

- With no stated start, an OPTION might start only at some time nobody has recorded.
- With no stated duration, an OPTION might take any length of time.
- With no stated access cutoff, an OPTION might need any margin.
- OPTIONs that the FILE does not list might exist, except where a COMPLETE FACT says the list is full.

A possible world is one way that all the unknown FACTs could turn out.

## The CONSTRAINTs

An ITINERARY says which OPTIONs happen, which PERSONs take part in each, and when each starts and ends. It works in a possible world when it meets every CONSTRAINT below.

1. **LOCKs are honored.** Every LOCKed OPTION happens, and the PERSONs its LOCK names take part.
2. **Each OPTION starts when it can.** An OPTION with a fixed start starts at that time.
3. **Each OPTION takes as long as it takes.** Its end is its start plus its duration. For a CONTINGENT duration, that is any value in the range.
4. **Each PERSON is in one place at a time.** A PERSON's OPTIONs do not overlap, and each one starts at the PLACE where the one before it ended. A PERSON's path begins at the PLACE of their first OPTION. OPTIONs that take no time and share an instant can happen in any order.
5. **Each PERSON arrives in time.** A PERSON who travels to an OPTION's PLACE gets there at least its access cutoff before it starts. A PERSON who was there all along is in time.
6. **A COMPLETE set is the whole set.** An unlisted OPTION can be used only in a possible world that has it. Where a FACT says the ways from one PLACE to another are COMPLETE, a PERSON who leaves the first PLACE within the stated span uses only listed OPTIONs until they reach the second.
7. **Nothing happens without need.** Taking out any OPTIONs, or any PERSONs from an OPTION, that no LOCK requires would break one of the CONSTRAINTs above.

## The three answers

- **FEASIBLE:** some ITINERARY works in every possible world.
- **INFEASIBLE:** no ITINERARY works in any possible world.
- **UNDETERMINED:** some ITINERARY works in some possible world, but none works in all of them.

A CONTINGENT duration has a stated range, so it is not unknown. An ITINERARY may rely on any value in the range and still support FEASIBLE.

Two cases settle the answer. Every CONSTRAINT is at least as easy to meet when an OPTION can start more freely, takes less time or needs less margin, and when more OPTIONs exist.

- **The best case.** Every unknown start is free, every unknown duration and access cutoff is zero, and an unlisted OPTION joins any two PLACEs in no time. If no ITINERARY works here, none works in any possible world, and the TRIP is INFEASIBLE.
- **The worst case.** An OPTION with an unknown start cannot be used. An unknown duration has no limit, so nothing can follow that OPTION. An unknown access cutoff has no limit, so only a PERSON who was at the PLACE all along is in time. No unlisted OPTION exists. An ITINERARY that works here works in every possible world, and the TRIP is FEASIBLE.

## ROBUST

An ITINERARY is ROBUST when its OPTIONs and start times work for every value of every CONTINGENT duration. A longer duration is never easier, so it is enough to check the longest value of each.

A FEASIBLE TRIP with no ROBUST ITINERARY gets a WARNING. The WARNING names the CONSTRAINT that the ITINERARY shown would break if every CONTINGENT duration ran longest, and by how much.

## Which ITINERARY is shown

When several ITINERARIES work, the report shows one, chosen by a fixed rule:

1. a ROBUST one, if there is any;
2. then one with the fewest PERSONs taking part in OPTIONs;
3. then one with the fewest OPTIONs;
4. then one that uses the OPTIONs listed first in the FILE.

Each OPTION starts as early as the CONSTRAINTs allow. An OPTION with nothing before it starts as late as they allow. A ROBUST ITINERARY shows each CONTINGENT duration at its longest value, and any other ITINERARY shows it at its shortest.

## Evidence

- **FEASIBLE:** the ITINERARY, and the FACTs and DECISIONs it relies on. These are every FACT about an OPTION in the ITINERARY, and every LOCK.
- **INFEASIBLE:** a set of FACTs and DECISIONs that make the TRIP INFEASIBLE by themselves, and from which none can be removed. Removing a FACT makes what it stated unknown. The COMPILER goes through the records in the FILE's order, FACTs before DECISIONs, and removes each one that the TRIP stays INFEASIBLE without.
- **UNDETERMINED:** the fewest unknown FACTs that would have to turn out well for the TRIP to be FEASIBLE. When there is exactly one and it is a length of time, the report gives its limit: "only if the cab takes 45 minutes or less".

## Examples

Alex and Sam spend their last afternoon in Chicago at the Art Institute, then fly home from O'Hare. The flight leaves at 5:00 pm, and bag drop closes 45 minutes earlier. The Blue Line takes an hour from the museum to the terminal.

| FILE | What it says | Answer |
|---|---|---|
| [works](../examples/flight-home/works.json) | They leave the museum at 3:00 pm. | FEASIBLE. They reach O'Hare at 4:00 pm. |
| [cannot work](../examples/flight-home/cannot-work.json) | They leave at 3:30 pm, and a FACT says the Blue Line is the only way to O'Hare. | INFEASIBLE. Eight FACTs and DECISIONs conflict. |
| [depends on another way](../examples/flight-home/depends-on-another-way.json) | They leave at 3:30 pm, and no FACT says the Blue Line is the only way. | UNDETERMINED. It works only if another way from the Art Institute to O'Hare takes 45 minutes or less. |
| [depends on the cab](../examples/flight-home/depends-on-the-cab.json) | They leave at 3:30 pm. A cab is listed, but nobody has recorded how long it takes. | UNDETERMINED. It works only if the cab takes 45 minutes or less. |
| [works, but risky](../examples/flight-home/works-but-risky.json) | They leave at 3:00 pm, and the Blue Line can take up to 80 minutes. | FEASIBLE, with a WARNING that no ITINERARY is ROBUST. At 80 minutes they reach O'Hare five minutes after bag drop closes. |

Each FILE has its expected result beside it, and the tests compare the reference checker's answer with it.
