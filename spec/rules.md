# Rules

This document says exactly what the COMPILER checks. It turns the principles of the [foundation](foundation.md) into CONSTRAINTs, each stated in plain words about a finished ITINERARY. Terms in capitals are defined in the [vocabulary](vocabulary.md).

The rules exist twice: here in words, and in the reference checker, [`src/agloe/reference.py`](../src/agloe/reference.py). The reference checker is a small program that applies these rules directly and uses no solver. It defines the right answer for small TRIPs, and anything faster must give the same answers. The three answers and the evidence are worked out in [`src/agloe/answers.py`](../src/agloe/answers.py), from its search or from a faster one. Every FILE under [`examples/`](../examples/) is one of its tests.

## What a FILE holds

A FILE lists PERSONs, PLACEs, OPTIONs, WAYs, WANTs, FACTs and DECISIONs. Its shape is fixed by the [schema](../src/agloe/schema/file.schema.json). Every record has an id that is unique in the FILE.

An OPTION happens at one PLACE, or moves from one PLACE to another. It happens at most once, and everyone who takes part in it starts and ends together.

A WAY goes from one PLACE to another, or between two PLACEs in both directions. A PERSON can take a WAY at any time and as often as they need, alone or with others.

A WANT is something PERSONs want, or want to avoid, from the TRIP. It is about something an OPTION can deliver, such as deep-dish pizza or a view from high up, or it is the WANT to end the TRIP at home. That WANT is about the whole ITINERARY, and no OPTION delivers it. A WANT names its holders. Each holder is a PERSON with a DEGREE OF WANT. +10 makes the WANT a must for that PERSON, and −10 makes it a must-not. A WANT names each PERSON at most once. A FILE states the WANT to end the TRIP at home only as a must.

A FACT states one thing:

| A FACT states | Meaning |
|---|---|
| a fixed start | The OPTION can start only at that time. |
| a start at any time | The planners choose when the OPTION starts. |
| a duration | The OPTION takes exactly that long. |
| a CONTINGENT duration | The world decides how long the OPTION takes, between a shortest and a longest value. |
| an access cutoff | Each PERSON must reach the PLACE where the OPTION starts at least that long before it starts. |
| how long a WAY takes | Each time a PERSON takes the WAY, it takes that long. The FACT gives an exact value, or a CONTINGENT range from which the world decides each time. |
| a COMPLETE set of travel | The FILE lists every OPTION and WAY that goes straight from one PLACE to another and starts within a stated span of time. Straight means that it stops at no other PLACE of the FILE on the way. So no unlisted WAY does. The span includes both of its ends. The FACT can leave out the first PLACE, the second, or both. A PLACE it leaves out stands for every PLACE. The FACT says nothing about travel through a third PLACE as a whole. Each leg of such travel is straight travel by itself, and the FACT rules out a leg only where it covers that leg. |
| that an OPTION SATISFIES a WANT | The OPTION delivers what the WANT describes. The FACT gives a DEGREE OF SATISFACTION, a whole number from 0 to 10. Zero says that the OPTION does not deliver it. Any value above zero says that it does. Only an OPTION SATISFIES a WANT. A WAY never does. |
| a COMPLETE set for a WANT | The FILE states every OPTION that SATISFIES the WANT. Each one is listed, with a FACT that it SATISFIES the WANT. So an OPTION with no FACT about the WANT does not SATISFY it, and nothing outside the FILE does. |
| where a PERSON starts from | The PERSON's path begins at that PLACE. |
| where a PERSON returns to | That PLACE is home for the PERSON. |

A FILE states each FACT once. An OPTION has at most one start, one duration and one access cutoff, and one FACT about each WANT. A WAY has at most one duration. A WANT has at most one FACT that its set is COMPLETE. A PERSON has at most one FACT about where they start from and one about where they return to. A FACT that an OPTION SATISFIES a WANT, and a COMPLETE set for a WANT, are about a WANT that an OPTION can deliver.

A time states its date and time to the second, its offset from UTC and the name of its time zone. The offset must be the one that time zone has at that moment. Every time lies in the years 0001 to 9999, on its own clock and in UTC, and a report can be written only when every time in it does too. The COMPILER pins one release of the time-zone database, so the same FILE gets the same reading on every machine.

No text in a FILE holds a control character, a line break or half of a character pair. A name holds at least one character that is not a space.

A DECISION is a LOCK, or it says when the TRIP starts, or when the TRIP ends.

- A LOCK names an OPTION and the PERSONs who take part in it.
- A FILE holds at most one DECISION about when the TRIP starts and one about when it ends, and the TRIP does not end before it starts.

## What is unknown

A FACT that the FILE does not state is unknown, unless a COMPLETE set settles it. The COMPILER never fills one in.

- With no stated start, an OPTION might start only at some time nobody has recorded.
- With no stated duration, an OPTION or a WAY might take any length of time.
- With no stated access cutoff, an OPTION might need any margin.
- Travel that the FILE does not list might exist between any two PLACEs, and take any length of time. The rules call it an unlisted WAY. It stands for a WAY, or for an OPTION that leaves at some time, so it can be there at one time and not at another. Where it stands for an OPTION, nobody knows which WANTs it SATISFIES, except that it SATISFIES no WANT whose set is COMPLETE. A COMPLETE set of travel says that none goes straight from its first PLACE to its second within its span.
- With no FACT about an OPTION and a WANT, nobody knows whether the OPTION SATISFIES the WANT, unless a FACT says that the WANT's set is COMPLETE.
- An OPTION that the FILE does not list might SATISFY any WANT whose set is not COMPLETE. The rules call it another OPTION for the WANT. Nobody knows where it happens, when it starts or how long it takes. So nobody knows which PERSONs can take part in it.
- With no FACT about where a PERSON returns to, nobody knows where home is for them. It might be any PLACE of the FILE, or a PLACE that the FILE does not name.

Where a PERSON starts from is different. With no FACT about it, the ITINERARY chooses where their path begins, as it chooses a start that can be at any time.

A possible world is one way that all the unknown FACTs could turn out. Its travel joins only PLACEs that the FILE names: travel through anywhere else is part of one WAY between two PLACEs of the FILE. Another OPTION for a WANT can happen anywhere.

## The CONSTRAINTs

An ITINERARY says which OPTIONs of the FILE happen, which PERSONs take part in each, which WAYs each PERSON takes, and when each of these starts and ends. A PERSON's path is their OPTIONs and WAYs in the order they do them. Each time a PERSON takes a WAY counts by itself, even when others take the same WAY at the same time. At least one PERSON takes part in every OPTION that happens. The OPTIONs, the PERSONs, the WAYs and the start times are choices. Each end follows from the start and the duration, so the same choices can end at different times in different possible worlds.

An ITINERARY works in a possible world when it meets every CONSTRAINT below.

1. **LOCKs are honored.** Every LOCKed OPTION happens, and the PERSONs its LOCK names take part.
2. **Each OPTION starts when it can.** An OPTION with a fixed start starts at that time. A WAY can be taken at any time.
3. **Each OPTION and WAY takes as long as it takes.** It ends at its start plus its duration. A CONTINGENT duration is one value in its range, and for a WAY it can be a different value each time.
4. **Each PERSON is in one place at a time.** A PERSON's OPTIONs and WAYs do not overlap, and each one starts at the PLACE where the one before it ended. Where a FACT says where the PERSON starts from, their path begins at that PLACE, so the first of them starts there. Otherwise their path begins at the PLACE where the first of them starts. A PERSON who does nothing stays where their path begins, and with no FACT that can be any PLACE. OPTIONs and WAYs that take no time and share an instant happen one after another, in any order, and that order is the same for every PERSON.
5. **Each PERSON arrives in time.** A PERSON who travels to the PLACE where an OPTION starts gets there at least its access cutoff before it starts. A PERSON whose path has no movement before the OPTION was there all along, and is in time. A WAY has no access cutoff.
6. **A COMPLETE set is the whole set.** A PERSON takes an unlisted WAY only in a possible world that has it. Where a FACT says the ways from one PLACE to another are COMPLETE, no PERSON takes an unlisted WAY that goes straight from the first PLACE to the second and starts within the stated span.
7. **Every must is met.** A PERSON for whom a WANT is a must takes part in an OPTION that SATISFIES it. Only the PERSON's own taking part counts: nobody else can meet the must for them. A possible world can also have another OPTION for the WANT that the PERSON can take part in. Then the must is met as well, and the ITINERARY does not show that OPTION. The WANT to end the TRIP at home is met another way: the PERSON's path ends at the PLACE they return to. A path ends where the last of its OPTIONs and WAYs ends, and a path with nothing in it ends where it begins.
8. **Every must-not is kept.** A PERSON for whom a WANT is a must-not takes part in no OPTION that SATISFIES it, and takes no unlisted WAY that does. Only the PERSON's own taking part counts: a must-not stops nobody else.
9. **Everything happens within the TRIP.** No OPTION and no WAY starts before the TRIP starts, and none ends after the TRIP ends. Where no DECISION says when the TRIP starts, or when it ends, there is no such limit.

So a PERSON can take WAYs before their first OPTION and after their last one, and a PERSON can take WAYs without taking part in any OPTION. Where a DECISION says when the TRIP ends, a PERSON who must end the TRIP at home is home by then: the last thing they do is over.

## The three answers

- **FEASIBLE:** one choice of OPTIONs, PERSONs, WAYs and start times works in every possible world.
- **INFEASIBLE:** no choice works in any possible world.
- **UNDETERMINED:** some choice works in some possible world, but none works in all of them.

A CONTINGENT duration has a stated range, so it is not unknown, and a possible world does not settle it. FEASIBLE may rely on any value in the range. A shorter duration is never harder, so the three answers use the shortest value of each.

Two cases settle the answer. For the same OPTIONs, PERSONs, WAYs and start times, every CONSTRAINT is at least as easy to meet when an OPTION can start more freely or needs less margin, when an OPTION or a WAY takes less time, when more WAYs exist, and when more PERSONs can take part in another OPTION for a WANT. Whether an OPTION SATISFIES a WANT is different: it helps a must and hurts a must-not. So each case takes it the way that suits the case. Where a PERSON returns to is different too: each PLACE suits only the choices that end there.

- **The best case.** Every unknown start is free, and every unknown duration and access cutoff is zero. An unlisted WAY joins any two PLACEs, takes no time and SATISFIES no WANT, except where a COMPLETE set of travel says there is none. An OPTION with no FACT about a WANT does not SATISFY it, so it breaks no must-not. For every must on a WANT whose set is not COMPLETE, there is another OPTION that the PERSON can take part in whatever else they do. It SATISFIES nothing else, it takes no time, and it comes before everything else the PERSON does, at the PLACE where they start. A PERSON who does nothing else can take part in it anywhere. So every such must is met here, with no help from a listed OPTION. A PERSON with no FACT about where they return to is home wherever their path ends. That is one possible world for each choice: the one in which home is the PLACE where that choice ends. A choice that works in any possible world works here too, so the TRIP is INFEASIBLE when nothing works here.
- **The worst case.** An OPTION with an unknown start cannot be used. An unknown duration has no limit, so no PERSON does anything after that OPTION or WAY, and it is not over before the TRIP ends where the TRIP has an end. An unknown access cutoff has no limit, so only a PERSON who was at the PLACE all along is in time. No unlisted WAY exists. Where a WANT's set is not COMPLETE, nobody knows whether an OPTION with no FACT about the WANT SATISFIES it. So it meets no must, and no PERSON for whom the WANT is a must-not takes part in it. That is no single possible world, but a choice that relies on such an OPTION either way fails in one. There is no other OPTION for any WANT. A PERSON with no FACT about where they return to is home nowhere: wherever their path ends, home might be another PLACE. A choice works here exactly when it works in every possible world, so the TRIP is FEASIBLE when something works here.

So a must can make a TRIP INFEASIBLE only where a FACT says that the WANT's set is COMPLETE. Otherwise another OPTION might be found, and the must makes the TRIP UNDETERMINED when no OPTION that a FACT says SATISFIES the WANT fits. A must-not can make a TRIP INFEASIBLE: a LOCK names a PERSON in an OPTION that a FACT says SATISFIES what they must not have.

A must to end the TRIP at home makes a TRIP UNDETERMINED where nobody knows where home is, or where no listed OPTION or WAY gets the PERSON there in time: other WAYs might. It makes a TRIP INFEASIBLE only where COMPLETE sets of travel rule those out, on every route home and at every time the PERSON could still leave. Without a DECISION about when the TRIP ends, the PERSON could always wait until a span has passed.

## ROBUST

An ITINERARY is ROBUST when its OPTIONs, PERSONs, WAYs and start times work in every possible world, for every value of every CONTINGENT duration. A longer duration is never easier, so it is enough to check the longest value of each.

A FEASIBLE TRIP with no ROBUST ITINERARY gets a WARNING. The WARNING names each CONSTRAINT that the ITINERARY shown would break, with its steps in the order shown, if every CONTINGENT duration ran longest, with the OPTION or the time a WAY is taken, the PERSONs and how late they would be. No duration changes who takes part in what or where a path ends, so a longer duration never leaves a must unmet or breaks a must-not, and a WARNING names only CONSTRAINTs about time.

## Which ITINERARY is shown

When several ITINERARIES work, the report shows one, chosen by a fixed rule:

1. a ROBUST one, if there is any;
2. then one in which PERSONs take part the fewest times, counting each PERSON once for every OPTION they take part in and once for every time they take a WAY;
3. then one with the fewest OPTIONs;
4. then one that uses the OPTIONs listed first in the FILE;
5. then one in which each PERSON does the OPTIONs listed first, in the FILE's order where they can. Going through the PERSONs in the FILE's order, and through each PERSON's OPTIONs in the order they do them, the ITINERARY with the OPTION listed first comes first. A PERSON with nothing more to do comes before one with more;
6. then one in which each PERSON takes the WAYs listed first. Going through the PERSONs in the FILE's order, and through the WAYs each PERSON takes in the order they take them, the ITINERARY with the WAY listed first comes first. An unlisted WAY comes after every listed one.

Where several OPTIONs could meet a must, the same rules choose among them. The DEGREE OF SATISFACTION plays no part: any value above zero meets a must and breaks a must-not.

The second rule keeps out anything nobody needs. If any OPTION were taken out of the ITINERARY shown, or any PERSON out of one of its OPTIONs, or any WAY a PERSON takes, it would stop working in some possible world, or stop being ROBUST. So no PERSON in it goes round in a circle by WAYs alone: they could wait where they are and take fewer WAYs.

The start times follow a fixed rule too. It treats each time a PERSON takes a WAY as an OPTION of its own. Here one OPTION comes before another when a PERSON does it earlier, or when a chain of such OPTIONs links the two. At first, only the OPTIONs with a fixed start are timed.

1. An OPTION that comes after one already timed starts as early as it can.
2. Then an OPTION that comes before one already timed starts as late as it can.
3. Steps 1 and 2 repeat until they time nothing more.
4. The OPTIONs still without a time are tied to no fixed start. They are timed from the time the TRIP starts, each as early as it can. Where no DECISION says when the TRIP starts, they are timed from the first second of 1970 in UTC, or from earlier where the TRIP ends too soon for that.

The times of the TRIP are limits, and a FILE can hold either, both or neither. They are no fixed starts: steps 1 to 3 time nothing from them. "As early as it can" and "as late as it can" keep to them, for the OPTION itself and for whatever comes before or after it: a start that leaves no room for the rest inside the TRIP is not one the OPTION can take. The opening in which an unlisted WAY leaves, before or after the span of a COMPLETE set of travel, is a limit of the same kind.

A ROBUST ITINERARY shows each CONTINGENT duration at its longest value, and any other ITINERARY shows it at its shortest. An OPTION or a WAY with an unknown duration shows no end.

## Evidence

- **FEASIBLE:** the ITINERARY, and the FACTs, WANTs and DECISIONs it relies on. These are every FACT about an OPTION or a WAY in the ITINERARY, every WANT, and every LOCK. Where the ITINERARY has anything in it, they include the DECISIONs about when the TRIP starts and ends. A FACT about where a PERSON starts from is one of them where the PERSON is in the ITINERARY or must end the TRIP at home. A FACT about where a PERSON returns to is one of them where the PERSON must end the TRIP at home. A FACT that a WANT's set is COMPLETE is one of them where a PERSON for whom the WANT is a must-not takes part in an OPTION with no FACT about the WANT: only the COMPLETE set says that such an OPTION does not SATISFY it.
- **INFEASIBLE:** a set of FACTs, WANTs and DECISIONs that make the TRIP INFEASIBLE by themselves, and from which none can be removed. Removing a FACT makes what it stated unknown. That is more than leaving the FACT out: where a WANT's set is COMPLETE, an OPTION whose FACT about the WANT is removed might SATISFY the WANT or not. So the set is the smallest by this test, and a FILE with only these records can be one that fewer records already rule out. The set is one conflict: a TRIP can have another, so taking a record away need not make the TRIP work. Removing a WANT removes its musts and must-nots. Removing the FACT about where a PERSON starts from leaves that choice to the ITINERARY. The COMPILER goes through the FACTs, then the WANTs, then the DECISIONs, each in the FILE's order, and removes each record that the TRIP stays INFEASIBLE without.
- **UNDETERMINED:** the unknown FACTs that would make the TRIP FEASIBLE. A set of unknown FACTs is enough when the TRIP is FEASIBLE with those FACTs turned out well and every other unknown FACT as in the worst case. A start, a length of time, other WAYs and another OPTION turn out well as in the best case. Whether an OPTION SATISFIES a WANT can help either way, so it gives two unknown FACTs: that it does, and that it does not. A set states which of the two, and that is how it turns out. A set never holds both. Where a PERSON returns to gives one unknown FACT for each PLACE of the FILE: that the PERSON returns to that PLACE. A set holds at most one of them for a PERSON. A FILE that names no PLACE gives one such FACT: that the PERSON returns to a PLACE the FILE has yet to name. The report lists the sets that are enough and have the fewest FACTs. This is a choice about what a report says first: what to find out about the OPTIONs and WAYs that the FILE already lists. "Another OPTION is found for this WANT and this PERSON" is a different kind of condition. It asks for something new, and it stands in for a listed OPTION and every FACT about it. So the report first keeps the sets with the fewest of these conditions, and lists those among them with the fewest FACTs. Other WAYs count as one FACT: they stand in for one listed WAY and its duration, and the report says how long they may take. When a set holds exactly one unknown FACT, and that FACT is a length of time, the report gives the most it can be: "works if the cab takes 45 minutes or less". When any length of time would do, the report gives no limit, and the FACT only has to be stated.

An unknown FACT is the start, the duration or the access cutoff of a listed OPTION, that a listed OPTION SATISFIES a WANT or that it does not, the duration of a listed WAY, other WAYs from one PLACE to another, another OPTION for a WANT and a PERSON, or that a PERSON returns to a PLACE. A report says that an OPTION SATISFIES a WANT only where the WANT is a must for some PERSON, and that it does not only where the WANT is a must-not for some PERSON. It says where a PERSON returns to only where ending the TRIP at home is a must for them.

Other WAYs are unlisted WAYs that go straight from the first PLACE to the second. Their length of time is how long each one takes. They help only if they can be taken when the ITINERARY needs them, and only if they SATISFY nothing that is a must-not for a PERSON who takes them.

Another OPTION for a WANT and a PERSON is an OPTION outside the FILE that SATISFIES the WANT, that SATISFIES nothing that is a must-not for the PERSON, and that the PERSON can take part in. As in the best case, it is one the PERSON can take part in whatever else they do. So it helps only if the PERSON can take part in it and still do everything else the TRIP asks of them. It is one condition for one WANT and one PERSON, and a report names it only for a PERSON for whom the WANT is a must. One OPTION that is found can meet the condition for several PERSONs and for several WANTs, so the conditions are counted, and the OPTIONs are not.

The unknown FACTs have a fixed order. First come the OPTIONs in the FILE's order. Each OPTION has its start, its duration and its access cutoff, and then, for each WANT in the FILE's order, that it SATISFIES the WANT and that it does not. Then come the durations of the WAYs, in the FILE's order. Then come the other WAYs, in the FILE's order of their first PLACE and then of their second. Then come the conditions for another OPTION, in the FILE's order of WANTs and then of PERSONs. Last come the PLACEs that PERSONs return to, in the FILE's order of PERSONs and then of PLACEs. A set lists its FACTs in that order, and the sets are listed in that order too, comparing their first FACTs first.

## Examples

Alex and Sam spend their last afternoon in Chicago at the Art Institute, then fly home from O'Hare. The flight leaves at 5:00 pm, and bag drop closes 45 minutes earlier. The Blue Line takes an hour from the museum to the terminal.

| FILE | What it says | Answer |
|---|---|---|
| [works](../examples/flight-home/works.json) | They leave the museum at 3:00 pm. | FEASIBLE. They reach O'Hare at 4:00 pm. |
| [cannot work](../examples/flight-home/cannot-work.json) | They leave at 3:30 pm, and a FACT says the Blue Line is the only way to O'Hare. | INFEASIBLE. Eight FACTs and DECISIONs conflict. |
| [depends on another way](../examples/flight-home/depends-on-another-way.json) | They leave at 3:30 pm, and no FACT says the Blue Line is the only way. | UNDETERMINED. It works if there are other WAYs from the Art Institute to O'Hare that take 45 minutes or less. |
| [depends on the cab](../examples/flight-home/depends-on-the-cab.json) | They leave at 3:30 pm. A cab is listed, but nobody has recorded how long it takes. | UNDETERMINED. It works if the cab takes 45 minutes or less. |
| [works, but risky](../examples/flight-home/works-but-risky.json) | They leave at 3:00 pm, and the Blue Line can take up to 80 minutes. | FEASIBLE, with a WARNING that no ITINERARY is ROBUST. At 80 minutes they reach O'Hare five minutes after bag drop closes. |

The day before, Alex spends Friday in Chicago alone: breakfast at the hotel at 8:00 am, the Art Institute at 10:00 am, lunch in Millennium Park at 12:30 pm, an architecture boat tour, and dinner in River North at 7:00 pm. Alex walks from each stop to the next, and the FILE lists each walk as a WAY. Lunch takes an hour. The walk from the park to the dock takes 20 minutes, and boarding closes 15 minutes before the boat leaves.

| FILE | What it says | Answer |
|---|---|---|
| [works](../examples/a-day/works.json) | The boat leaves at 3:00 pm. | FEASIBLE. The plan shows each stop and each walk. |
| [cannot work](../examples/a-day/cannot-work.json) | The boat leaves at 2:00 pm, and a FACT says the FILE lists every way. | INFEASIBLE. Alex would reach the dock five minutes after boarding closes. Eight FACTs and DECISIONs conflict. |
| [depends on the walk](../examples/a-day/depends-on-the-walk.json) | The boat leaves at 2:00 pm, and nobody has recorded how long the walk to the dock takes. | UNDETERMINED. It works if that walk takes 15 minutes or less. |
| [works, but risky](../examples/a-day/works-but-risky.json) | The boat leaves at 2:15 pm, and lunch can take up to 90 minutes. | FEASIBLE, with a WARNING that no ITINERARY is ROBUST. At 90 minutes Alex is still at lunch when the walk to the dock should start. |

On Saturday morning Sam has arrived, and so has their friend Jo. Alex and Sam visit the Skydeck at Willis Tower at 10:00 am, while Jo goes to a gallery talk at the Art Institute at 10:30 am. All three meet for lunch in Millennium Park at 12:15 pm. The Skydeck visit takes 90 minutes, and the walk from Willis Tower to the park takes 20 minutes.

| FILE | What it says | Answer |
|---|---|---|
| [works](../examples/a-group/works.json) | The Skydeck visit starts at 10:00 am. | FEASIBLE. The plan shows Alex and Sam at the Skydeck, Jo at the talk, and all three at lunch. |
| [cannot work](../examples/a-group/cannot-work.json) | The Skydeck visit starts at 10:30 am, and a FACT says the FILE lists every way. | INFEASIBLE. Alex and Sam would reach the park five minutes after lunch starts. Seven FACTs and DECISIONs conflict, and none of them is about Jo's talk. |
| [depends on the walk](../examples/a-group/depends-on-the-walk.json) | The Skydeck visit starts at 10:30 am, and nobody has recorded how long the walk from Willis Tower takes. | UNDETERMINED. It works if that walk takes 15 minutes or less. |
| [works, but risky](../examples/a-group/works-but-risky.json) | The Skydeck visit starts at 10:00 am and can take up to two hours. | FEASIBLE, with a WARNING that no ITINERARY is ROBUST. The WARNING names Alex and Sam, who would still be at the Skydeck when their walk should start. |

The trip also runs from one day into the next. On Friday evening Alex has dinner in River North until 8:30 pm and walks 25 minutes to the hotel. The night at the hotel starts at 11:30 pm and lasts eight hours. The FILE lists the night like any other OPTION. On Saturday, breakfast is at 8:00 am, and the Skydeck visit at 10:00 am is a 15 minute walk away.

| FILE | What it says | Answer |
|---|---|---|
| [works](../examples/several-days/works.json) | The night ends at 7:30 am, and breakfast is at 8:00 am. | FEASIBLE. The plan runs over two days. |
| [cannot work](../examples/several-days/cannot-work.json) | Breakfast is at 7:00 am. | INFEASIBLE. The night ends half an hour after breakfast starts. Five FACTs and DECISIONs conflict, from both days. |
| [depends on the night](../examples/several-days/depends-on-the-night.json) | Nobody has recorded how long the night lasts. | UNDETERMINED. It works if the night takes 8 hours 30 minutes or less. |
| [works, but risky](../examples/several-days/works-but-risky.json) | Breakfast can take up to two hours. | FEASIBLE, with a WARNING that no ITINERARY is ROBUST. At two hours Alex is still at breakfast when Saturday's walk to Willis Tower should start. |

Friday evening has one more plan. Alex has a ticket for a blues show at 9:00 pm, and the show is LOCKed. Doors close 10 minutes before it starts, and the club is a 15 minute walk from River North. Deep-dish pizza is a must for Alex. The FILE lists two dinners in River North, one at a deep-dish place and one at a tavern, and no LOCK names either. Dinner at the deep-dish place takes 90 minutes.

| FILE | What it says | Answer |
|---|---|---|
| [works](../examples/a-must/works.json) | The deep-dish place has a table at 7:00 pm. A FACT says that dinner there SATISFIES the WANT. | FEASIBLE. The plan has dinner at the deep-dish place, though no LOCK names it. |
| [cannot work](../examples/a-must/cannot-work.json) | The deep-dish place has no table until 7:45 pm, so Alex would miss the show. A FACT says that the FILE lists every OPTION that SATISFIES the WANT. | INFEASIBLE. Six records conflict: when dinner at the deep-dish place starts, how long it takes, when the show starts, the COMPLETE set, the WANT and the LOCK. |
| [depends on the menu](../examples/a-must/depends-on-the-menu.json) | The deep-dish place has no table until 7:45 pm, so Alex would miss the show. Nobody has recorded whether the tavern serves deep-dish pizza. | UNDETERMINED. It works if dinner at the tavern SATISFIES deep-dish pizza. |
| [depends on another place](../examples/a-must/depends-on-another-place.json) | The deep-dish place has no table until 7:45 pm, and a FACT says that dinner at the tavern does not SATISFY the WANT. | UNDETERMINED. It works if another OPTION that SATISFIES deep-dish pizza is found for Alex. |

The trip home has a frame. The TRIP starts at noon on Saturday and ends at 7:30 pm, when the flight lands. The story is the first one, with those two DECISIONs.

| FILE | What it says | Answer |
|---|---|---|
| [works](../examples/the-times-of-the-trip/works.json) | The flight takes two and a half hours and lands at 7:30 pm. | FEASIBLE. The last second of the TRIP is inside it. |
| [ends too early](../examples/the-times-of-the-trip/ends-too-early.json) | The TRIP ends at 7:00 pm. | INFEASIBLE. Four records conflict: when the flight starts, how long it takes, when the TRIP ends, and the LOCK. |
| [starts too late](../examples/the-times-of-the-trip/starts-too-late.json) | The TRIP starts at 2:30 pm, after the museum visit has begun. | INFEASIBLE. Three records conflict: when the visit starts, when the TRIP starts, and the LOCK. |
| [depends on the flight](../examples/the-times-of-the-trip/depends-on-the-flight.json) | Nobody has recorded how long the flight takes. | UNDETERMINED. It works if the flight takes 2 hours 30 minutes or less. |
| [works, but risky](../examples/the-times-of-the-trip/works-but-risky.json) | The flight can take up to three hours. | FEASIBLE, with a WARNING that no ITINERARY is ROBUST. At three hours the flight would end 30 minutes after the TRIP ends. |

Getting home is a must for Alex and Sam. They start Saturday afternoon at the hotel, a 15 minute walk from the Art Institute, and they return to the PLACE where the flight lands. The TRIP runs from noon to 7:30 pm. Only the museum visit is LOCKed. The walk, the Blue Line and the flight are in the plan because the must needs them.

| FILE | What it says | Answer |
|---|---|---|
| [works](../examples/getting-home/works.json) | The flight leaves at 5:00 pm. | FEASIBLE. The plan has the walk from the hotel at 1:45 pm, the visit, the Blue Line and the flight. |
| [cannot work](../examples/getting-home/cannot-work.json) | The flight leaves at 3:30 pm, and a FACT says the FILE lists every way home that leaves before the TRIP ends. | INFEASIBLE. Nine records conflict. Among them are where Sam returns to, the COMPLETE set, the WANT and when the TRIP ends. |
| [depends on another flight](../examples/getting-home/depends-on-another-flight.json) | The flight leaves at 3:30 pm, and no FACT says the FILE lists every way home. | UNDETERMINED. It works if there are other WAYs home from the hotel, from the Art Institute or from O'Hare that are quick enough. |
| [depends on where home is](../examples/getting-home/depends-on-where-home-is.json) | No FACT says where Sam returns to. | UNDETERMINED. It works if Sam returns to any one of the four PLACEs, and the report names each. |

On Saturday morning a view from high up is a must for Alex and a must-not for Jo, who is afraid of heights. A FACT says that the Skydeck visit at 10:00 am SATISFIES it. All three are LOCKed for lunch at 12:15 pm.

| FILE | What it says | Answer |
|---|---|---|
| [works](../examples/a-must-not/works.json) | Lunch is in the park, and a FACT says that it does not SATISFY the WANT. No LOCK names the Skydeck visit. | FEASIBLE. Alex visits the Skydeck, and Sam and Jo do not. All three have lunch. |
| [cannot work](../examples/a-must-not/cannot-work.json) | A LOCK names all three in the Skydeck visit. | INFEASIBLE. Three records conflict: the FACT about the Skydeck, the WANT and the LOCK. |
| [depends on the lunch](../examples/a-must-not/depends-on-the-lunch.json) | Lunch is on a rooftop, and nobody has recorded whether that SATISFIES the WANT. | UNDETERMINED. It works if lunch on the rooftop does not SATISFY a view from high up. |

Each FILE has its expected result beside it, as JSON and in words, and the tests compare the reference checker's answer with it. The command `agloe check` prints the same result for any FILE.
