# Rules

This document says exactly what the COMPILER checks. It turns the principles of the [foundation](foundation.md) into CONSTRAINTs, each stated in plain words about a finished ITINERARY. Terms in capitals are defined in the [vocabulary](vocabulary.md).

The rules exist twice: here in words, and in the reference checker, [`src/agloe/reference.py`](../src/agloe/reference.py). The reference checker is a small program that applies these rules directly and uses no solver. It defines the right answer for small TRIPs, and anything faster must give the same answers. The three answers and the evidence are worked out in [`src/agloe/answers.py`](../src/agloe/answers.py), from its search or from a faster one. Every FILE under [`examples/`](../examples/) is one of its tests.

## What a FILE holds

A FILE lists PERSONs, PLACEs, OPTIONs, WAYs, FACTs and DECISIONs. Its shape is fixed by the [schema](../src/agloe/schema/file.schema.json). Every record has an id that is unique in the FILE.

An OPTION happens at one PLACE, or moves from one PLACE to another. It happens at most once, and everyone who takes part in it starts and ends together.

A WAY goes from one PLACE to another, or between two PLACEs in both directions. A PERSON can take a WAY at any time and as often as they need, alone or with others.

A FACT states one thing:

| A FACT states | Meaning |
|---|---|
| a fixed start | The OPTION can start only at that time. |
| a start at any time | The planners choose when the OPTION starts. |
| a duration | The OPTION takes exactly that long. |
| a CONTINGENT duration | The world decides how long the OPTION takes, between a shortest and a longest value. |
| an access cutoff | Each PERSON must reach the PLACE where the OPTION starts at least that long before it starts. |
| how long a WAY takes | Each time a PERSON takes the WAY, it takes that long. The FACT gives an exact value, or a CONTINGENT range from which the world decides each time. |
| a COMPLETE set | The FILE lists every OPTION and WAY that goes straight from one PLACE to another and starts within a stated span of time. So no unlisted WAY does. The span includes both of its ends. The FACT can leave out the first PLACE, the second, or both. A PLACE it leaves out stands for every PLACE. The FACT says nothing about travel through a third PLACE. |

A FILE states each FACT once. An OPTION has at most one start, one duration and one access cutoff. A WAY has at most one duration.

A time states its date and time to the second, its offset from UTC and the name of its time zone. The offset must be the one that time zone has at that moment. Every time lies in the years 0001 to 9999, on its own clock and in UTC, and a report can be written only when every time in it does too. The COMPILER pins one release of the time-zone database, so the same FILE gets the same reading on every machine.

No text in a FILE holds a control character, a line break or half of a character pair. A name holds at least one character that is not a space.

A LOCK names an OPTION and the PERSONs who take part in it.

## What is unknown

A FACT that the FILE does not state is unknown. The COMPILER never fills one in.

- With no stated start, an OPTION might start only at some time nobody has recorded.
- With no stated duration, an OPTION or a WAY might take any length of time.
- With no stated access cutoff, an OPTION might need any margin.
- WAYs that the FILE does not list might exist between any two PLACEs, and take any length of time. A COMPLETE FACT says that none goes straight from its first PLACE to its second within its span.

A possible world is one way that all the unknown FACTs could turn out.

## The CONSTRAINTs

An ITINERARY says which OPTIONs happen, which PERSONs take part in each, which WAYs each PERSON takes, and when each of these starts and ends. At least one PERSON takes part in every OPTION that happens. The OPTIONs, the PERSONs, the WAYs and the start times are choices. Each end follows from the start and the duration, so the same choices can end at different times in different possible worlds.

An ITINERARY works in a possible world when it meets every CONSTRAINT below.

1. **LOCKs are honored.** Every LOCKed OPTION happens, and the PERSONs its LOCK names take part.
2. **Each OPTION starts when it can.** An OPTION with a fixed start starts at that time. A WAY can be taken at any time.
3. **Each OPTION and WAY takes as long as it takes.** It ends at its start plus its duration. A CONTINGENT duration is one value in its range, and for a WAY it can be a different value each time.
4. **Each PERSON is in one place at a time.** A PERSON's OPTIONs and WAYs do not overlap, and each one starts at the PLACE where the one before it ended. A PERSON's path begins at the PLACE where the first of them starts. OPTIONs and WAYs that take no time and share an instant happen one after another, in any order, and that order is the same for every PERSON.
5. **Each PERSON arrives in time.** A PERSON who travels to the PLACE where an OPTION starts gets there at least its access cutoff before it starts. A PERSON whose path has no movement before the OPTION was there all along, and is in time. A WAY has no access cutoff.
6. **A COMPLETE set is the whole set.** A PERSON takes an unlisted WAY only in a possible world that has it. Where a FACT says the ways from one PLACE to another are COMPLETE, no PERSON takes an unlisted WAY that goes straight from the first PLACE to the second and starts within the stated span.

## The three answers

- **FEASIBLE:** one choice of OPTIONs, PERSONs, WAYs and start times works in every possible world.
- **INFEASIBLE:** no choice works in any possible world.
- **UNDETERMINED:** some choice works in some possible world, but none works in all of them.

A CONTINGENT duration has a stated range, so it is not unknown, and a possible world does not settle it. FEASIBLE may rely on any value in the range. A shorter duration is never harder, so the three answers use the shortest value of each.

Two cases settle the answer. For the same OPTIONs, PERSONs, WAYs and start times, every CONSTRAINT is at least as easy to meet when an OPTION can start more freely or needs less margin, when an OPTION or a WAY takes less time, and when more WAYs exist.

- **The best case.** Every unknown start is free, and every unknown duration and access cutoff is zero. An unlisted WAY joins any two PLACEs and takes no time, except where a COMPLETE FACT says there is none. A choice that works in any possible world works here too, so the TRIP is INFEASIBLE when nothing works here.
- **The worst case.** An OPTION with an unknown start cannot be used. An unknown duration has no limit, so no PERSON does anything after that OPTION or WAY. An unknown access cutoff has no limit, so only a PERSON who was at the PLACE all along is in time. No unlisted WAY exists. A choice works here exactly when it works in every possible world, so the TRIP is FEASIBLE when something works here.

## ROBUST

An ITINERARY is ROBUST when its OPTIONs, PERSONs, WAYs and start times work in every possible world, for every value of every CONTINGENT duration. A longer duration is never easier, so it is enough to check the longest value of each.

A FEASIBLE TRIP with no ROBUST ITINERARY gets a WARNING. The WARNING names each CONSTRAINT that the ITINERARY shown would break if every CONTINGENT duration ran longest, with the OPTION, the PERSONs and how late they would be.

## Which ITINERARY is shown

When several ITINERARIES work, the report shows one, chosen by a fixed rule:

1. a ROBUST one, if there is any;
2. then one in which PERSONs take part the fewest times, counting each PERSON once for every OPTION they take part in and once for every time they take a WAY;
3. then one with the fewest OPTIONs;
4. then one that uses the OPTIONs listed first in the FILE;
5. then one in which each PERSON does the OPTIONs listed first, in the FILE's order where they can. Going through the PERSONs in the FILE's order, and through each PERSON's OPTIONs in the order they do them, the ITINERARY with the OPTION listed first comes first. A PERSON with nothing more to do comes before one with more;
6. then one in which each PERSON takes the WAYs listed first. Going through the PERSONs in the FILE's order, and through the WAYs each PERSON takes in the order they take them, the ITINERARY with the WAY listed first comes first. An unlisted WAY comes after every listed one.

The second rule keeps out anything nobody needs. If any OPTION were taken out of the ITINERARY shown, or any PERSON out of one of its OPTIONs, or any WAY a PERSON takes, it would stop working in some possible world, or stop being ROBUST. So no PERSON in it goes round in a circle by WAYs alone: they could wait where they are and take fewer WAYs.

The start times follow a fixed rule too. It treats each time a PERSON takes a WAY as an OPTION of its own. Here one OPTION comes before another when a PERSON does it earlier, or when a chain of such OPTIONs links the two. At first, only the OPTIONs with a fixed start are timed.

1. An OPTION that comes after one already timed starts as early as it can.
2. Then an OPTION that comes before one already timed starts as late as it can.
3. Steps 1 and 2 repeat until they time nothing more.
4. The OPTIONs still without a time are tied to no fixed start. They are timed from the first second of 1970 in UTC, each as early as it can.

A ROBUST ITINERARY shows each CONTINGENT duration at its longest value, and any other ITINERARY shows it at its shortest. An OPTION with an unknown duration shows no end.

## Evidence

- **FEASIBLE:** the ITINERARY, and the FACTs and DECISIONs it relies on. These are every FACT about an OPTION or a WAY in the ITINERARY, and every LOCK.
- **INFEASIBLE:** a set of FACTs and DECISIONs that make the TRIP INFEASIBLE by themselves, and from which none can be removed. Removing a FACT makes what it stated unknown. The COMPILER goes through the records in the FILE's order, FACTs before DECISIONs, and removes each one that the TRIP stays INFEASIBLE without.
- **UNDETERMINED:** the unknown FACTs that would make the TRIP FEASIBLE. A set of unknown FACTs is enough when the TRIP is FEASIBLE with those FACTs as in the best case and every other unknown FACT as in the worst case. The report lists every set that is enough and has the fewest FACTs. When a set holds exactly one unknown FACT, and that FACT is a length of time, the report gives the most it can be: "works if the cab takes 45 minutes or less". When any length of time would do, the report gives no limit, and the FACT only has to be stated.

An unknown FACT is the start, the duration or the access cutoff of a listed OPTION, the duration of a listed WAY, or other WAYs from one PLACE to another. Other WAYs are unlisted WAYs that go straight from the first PLACE to the second. Their length of time is how long each one takes.

The unknown FACTs have a fixed order. First come the OPTIONs in the FILE's order, each with its start, its duration and its access cutoff. Then come the durations of the WAYs, in the FILE's order. Then come the other WAYs, in the FILE's order of their first PLACE and then of their second. A set lists its FACTs in that order, and the sets are listed in that order too, comparing their first FACTs first.

## Examples

Alex and Sam spend their last afternoon in Chicago at the Art Institute, then fly home from O'Hare. The flight leaves at 5:00 pm, and bag drop closes 45 minutes earlier. The Blue Line takes an hour from the museum to the terminal.

| FILE | What it says | Answer |
|---|---|---|
| [works](../examples/flight-home/works.json) | They leave the museum at 3:00 pm. | FEASIBLE. They reach O'Hare at 4:00 pm. |
| [cannot work](../examples/flight-home/cannot-work.json) | They leave at 3:30 pm, and a FACT says the Blue Line is the only way to O'Hare. | INFEASIBLE. Eight FACTs and DECISIONs conflict. |
| [depends on another way](../examples/flight-home/depends-on-another-way.json) | They leave at 3:30 pm, and no FACT says the Blue Line is the only way. | UNDETERMINED. It works if there are other WAYs from the Art Institute to O'Hare that take 45 minutes or less. |
| [depends on the cab](../examples/flight-home/depends-on-the-cab.json) | They leave at 3:30 pm. A cab is listed, but nobody has recorded how long it takes. | UNDETERMINED. It works if the cab takes 45 minutes or less. |
| [works, but risky](../examples/flight-home/works-but-risky.json) | They leave at 3:00 pm, and the Blue Line can take up to 80 minutes. | FEASIBLE, with a WARNING that no ITINERARY is ROBUST. At 80 minutes they reach O'Hare five minutes after bag drop closes. |

Each FILE has its expected result beside it, as JSON and in words, and the tests compare the reference checker's answer with it. The command `agloe check` prints the same result for any FILE.
