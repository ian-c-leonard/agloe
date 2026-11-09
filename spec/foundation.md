# Foundation

This document states what a TRIP means and what the COMPILER and the OPTIMIZER answer. Terms in capitals are defined in the [vocabulary](vocabulary.md). Each principle names the qualities from the [vision](../docs/VISION.md) it serves, and cites the original source of the idea where one exists; "to be verified" marks a source still being checked against the original. Later sections of the specification turn these principles into rules with runnable examples.

## The foundation

**A TRIP is a decision problem that unfolds over time.**

1. **The FILE** records it: the OPTIONs, FACTs, WANTs and DECISIONs that define its possible ITINERARIES.
2. **The COMPILER** decides whether any ITINERARY meets every CONSTRAINT.
3. **The OPTIMIZER** ranks the FEASIBLE ITINERARIES by SCORE.
4. **Over the TRIP's life,** each new FACT or DECISION re-runs both on what remains.

*Source:* decision theory's split into alternatives, constraints and preferences, which recurs in constrained optimization (Boyd and Vandenberghe, 2004), economic choice (Mas-Colell, Whinston and Green, 1995) and constraint satisfaction (Russell and Norvig). Re-running on what remains follows model predictive control (Rawlings, Mayne and Diehl). Savage's decision theory is deliberately not cited: it has no constraints and no time.

## A. The FILE

**A1. Single source of truth.** One FILE holds the whole TRIP: its PERSONs, WANTs, OPTIONs, FACTs, DECISIONs and BOOKINGs, and what happened. It is JSON, valid against a published JSON Schema, and readable by people as well as machines.
*Serves:* format, durable, intuitive. *Source:* JSON (RFC 8259); JSON Schema 2020-12.

**A2. Progressive elaboration.** A FILE can start nearly empty, such as a date range, four PERSONs and one must-have WANT, and still be valid. Detail is added as planning goes on. Missing detail produces FINDINGs, never schema errors.
*Serves:* whole-lifecycle, intuitive, agent-ready. *Source:* the PMBOK Guide (Project Management Institute, 1996, section 1.2.2), where the term first appears.

**A3. Minimal core ontology.** A few general concepts, the ones in the vocabulary, cover every kind of trip. Specific kinds such as ferry, hotel or concert are data values, not schema types. Each FACT is stated once.
*Serves:* flexible, intuitive. *Source:* minimal ontological commitment (Gruber, 1995); kinds as data, the Type Object pattern (Johnson and Woolf, 1997, after Coad's Item Description, 1992); normalization (Codd, 1972; to be verified).

**A4. Hermetic, reproducible evaluation.** The COMPILER reads only the FILE, its own pinned rules and its SETTINGs: no network, no hidden state. Outside information enters as FACTs with their source and date. Every report names the FILE revision, the COMPILER version and the time it treated as now.
*Serves:* deterministic, trustworthy. *Source:* Bazel's definition of hermeticity; the Reproducible Builds definition; W3C PROV-DM (2013) for provenance; referential transparency (Strachey, 1967).

**A5. Stable identifiers.** Every record has an id assigned once that never changes, rather than one computed from its content. References, DECISIONs and DISMISSALs keep pointing at the right thing through edits.
*Serves:* durable, multiplayer. *Source:* surrogate keys (Hall, Owlett and Todd, 1976; adopted by Codd, 1979).

**A6. Machine-readable contract.** The schema is published, every FINDING has a stable code, and the COMPILER is available to agents as an MCP tool. The same library and tool also answer plain questions about the FILE, such as which OPTIONs are LOCKed, who is taking part in this ferry, or what a VARIANT PINs, so agents never have to read and interpret the raw FILE themselves.
*Serves:* agent-ready. *Source:* SARIF 2.1.0 (OASIS) for findings; the Model Context Protocol specification.

**A7. Interoperability.** The FILE can import from existing standards, such as calendar files, booking confirmations and airline records, and export one-way views such as a calendar feed or a map. Purchases are handed to the sellers' own booking services, and the resulting BOOKING comes back as a FACT.
*Serves:* open. *Source:* the definition of interoperability (IEEE Std 610.12-1990); iCalendar (RFC 5545) and JSCalendar (RFC 8984); schema.org Reservation; the iCalendar PUBLISH method for one-way views (RFC 5546).

**A8. Sensitive details are welcome, and protected.** The FILE is where agents keep everything a trip needs, including passport details, dates of birth, loyalty numbers and health needs. The schema marks those fields as sensitive. The COMPILER never sends them anywhere, never writes them into logs, and never repeats their values in a FINDING; it names the field instead ("Alex's passport expires before the return flight"). Any FILE can be exported with sensitive fields removed, for a bug report, a co-traveler or an agent that does not need them. Payment card numbers never go in the FILE: purchases are handed to the sellers' payment services (A7), which keep cards as tokens. Example trips in the public repository are fictional.
*Serves:* trustworthy, agent-ready, multiplayer. *Source:* data protection by design and by default (GDPR, Article 25); health data as a special category (GDPR, Article 9); the Payment Card Industry Data Security Standard for card numbers.

## B. Changes and people

**B1. Every change is a dated record.** A FILE changes only by adding a FACT, a WANT or a DECISION. Each record carries its author, its time, its source where it has one, and a reason. The current records describe the TRIP now; earlier ones are its history.
*Serves:* multiplayer, whole-lifecycle, trustworthy. *Source:* modeled on the belief-desire-intention model (Bratman, 1987; Rao and Georgeff, 1991): FACTs are beliefs, WANTs desires and DECISIONs intentions. W3C PROV-DM for author, time and source; the reason is our addition.

**B2. One owner per record; everyone else proposes.** Each record has one owner. Other PERSONs and agents propose changes, and the owner accepts or declines. The FILE keeps who proposed what and who agreed.
*Serves:* multiplayer, agent-ready. *Source:* iCalendar scheduling, where "only the Organizer is allowed to update" (RFC 5546, section 3.7.2; first defined in RFC 2446, 1998).

**B3. The past is fixed; booked plans change only with a reason.** Anything before now changes only through a correcting FACT. A LOCKed or booked OPTION changes only through a DECISION that states why. Everything else changes freely.
*Serves:* whole-lifecycle, trustworthy.

**B4. Optimistic concurrency, checked after every merge.** People and agents edit their own copies of the FILE, and the copies are merged. Two edits can each be valid and still break the TRIP together, such as two purchases that each fit the BUDGET but exceed it combined. The COMPILER checks after every merge and flags exactly these.
*Serves:* multiplayer, trustworthy. *Source:* optimistic concurrency control (Kung and Robinson, 1981); invariant confluence (Bailis et al., 2014); merge-then-check in Bayou (Terry et al., 1995).

**B5. OPTIONs are never deleted.** A FACT can make an OPTION UNAVAILABLE, but the OPTION stays in the FILE, so the alternatives are still there when plans change.
*Serves:* durable, whole-lifecycle.

**B6. STALE is not DRIFT.** A STALE FACT is old and may still be true: it is flagged and still used. DRIFT is a newer FACT contradicting an older one: the newer one wins, and the change is recorded.
*Serves:* trustworthy.

**B7. The plan narrows as LOCKs accumulate and time passes.** Each LOCK is final for what it says, and detail arrives as new, more specific LOCKs that fit inside earlier ones, never as edits to old ones: "stay in central Kyoto those nights", then "Hotel Granvia", then its BOOKING. Time narrows the plan for good; a LOCK can be undone, but only deliberately, with a reason (B3). Every new LOCK reports what it rules out: OPTIONs no longer reachable, and WANTs that can no longer be SATISFIED.
*Serves:* whole-lifecycle, self-explaining, intuitive. *Source:* the remaining prism (Hägerstrand, 1970), the set of still-reachable plans that shrinks with every commitment (to be verified).

## C. WANTs

**C1. One scale for every WANT.** Each holder gives each WANT a DEGREE OF WANT from −10 to +10. +10 makes it a CONSTRAINT that the ITINERARY SATISFIES the WANT; −10 a CONSTRAINT that it does not. Zero means indifferent. Everything between is a preference that adds to or subtracts from the SCORE.
*Serves:* optimizer, multiplayer. *Source:* hard and soft constraints on one scale (Schiex, Fargier and Verfaillie, 1995); a signed scale with a neutral point (Bistarelli, Pini, Rossi and Venable, 2006).

**C2. Ranked, not scored.** PERSONs rank their own WANTs instead of inventing numbers, and a fixed rule turns each ranking into DEGREEs OF WANT. Adding a WANT shifts the others, and the report shows the shift: adding a second-ranked WANT drops the top weight from 0.61 to 0.52.
*Serves:* optimizer, multiplayer, intuitive. *Source:* rank-order centroid weights (Barron, 1992; earlier, Solymosi and Dombi, 1986). A 2023 study found the rule performs poorly on some real-world data.

**C3. Fit belongs to the pair.** How well an OPTION delivers a WANT is the DEGREE OF SATISFACTION on the SATISFIES link between them. No link means unknown, never zero.
*Serves:* optimizer, self-explaining. *Source:* contribution links between tasks and goals (Mylopoulos, Chung and Nixon, 1992); numeric value scoring (Edwards, 1977); the open-world assumption (Reiter, 1978).

**C4. Big WANTs are DECOMPOSED.** "Dinner each night" becomes one piece per night, and each piece is SATISFIED at most once.
*Serves:* compiler, optimizer. *Source:* PDDL3's per-unit quantified preferences (Gerevini and Long, 2005); a reward collected at most once per place in the orienteering problem (Tsiligirides, 1984; Golden, Levy and Vohra, 1987).

**C5. Not asked is not indifferent.** A holder who has not stated a DEGREE OF WANT is unelicited. That produces a NOTE, and is never treated as zero.
*Serves:* multiplayer, self-explaining. *Source:* missing-but-applicable versus inapplicable values (Codd, 1986); unknown preferences in incremental elicitation (Wang and Boutilier, 2003).

**C6. WANTs about the whole ITINERARY.** A WANT can be a property of the whole ITINERARY: never starting before 7, at most two hotel changes, a rest day after a long drive. These use the same scale, so each can be a CONSTRAINT or a preference. They are written with a fixed set of operators the COMPILER can check and explain: always, never, at most n times, at most a total amount per day or per TRIP ("at most 4 hours of driving a day"), after, within.
*Serves:* flexible, optimizer, self-explaining. *Source:* based on PDDL3's trajectory constraints (Gerevini and Long, 2005), extended with "at most n times" and totals; temporal logic (Pnueli, 1977) as the deeper root.

**C7. A dislike cannot be dodged.** A negative WANT never adds an OPTION to the TRIP. But when an OPTION in the ITINERARY SATISFIES it, because someone else wants that OPTION or as a side effect, it always counts against the SCORE.
*Serves:* optimizer, multiplayer.

**C8. Starter WANTs.** Each traveling PERSON starts with a small published set of WANTs for basic needs, each DECOMPOSED by its natural rhythm and stored as an ordinary visible WANT that anyone can re-rank or drop:

- a bed each night, +10: a night without one is an ERROR;
- getting home at the end of the TRIP, +10;
- breakfast, lunch and dinner each day, as preferences;
- rest, with no day overfull, as a preference;
- staying together: a weak dislike of splitting up from the group, ranked lowest.

Starter WANTs are never hidden rules; they sit in the FILE like any other WANT. They use the TRIP's SCOPE to know which nights and days to cover and where home is.
*Serves:* compiler, multiplayer, intuitive. *Source:* Hägerstrand (1970, pages 19 to 20) sketched a list of basic needs, each with its own rhythm (to be verified).

## D. The world

**D1. Things versus events.** PERSONs, PLACEs, OBJECTs and BUDGETs exist over time. OPTIONs happen at a time: a ferry sailing, a night in a room, dinner at eight. The Louvre is a PLACE; a Louvre visit on Thursday morning is an OPTION.
*Serves:* format, flexible, intuitive. *Source:* the continuant and occurrent distinction of formal ontology (to be verified).

**D2. Four kinds of time, and durations we do not control.** A fixed time, an allowed window, a duration range and the scheduled time are separate facts. A CONTROLLABLE duration is ours to choose; a CONTINGENT one the world chooses. The COMPILER may pick a CONTROLLABLE value; for a CONTINGENT one it checks whether the ITINERARY is ROBUST, and warns if not. Every time carries its date and time zone.
*Serves:* compiler, deterministic. *Source:* simple temporal networks (Dechter, Meiri and Pearl, 1991); controllable and contingent durations (Vidal and Fargier, 1999); zoned timestamps (RFC 9557).

**D3. One place at a time.** Each traveling PERSON and each OBJECT has one unbroken path through the ITINERARY, is in one place at a time, and is moved or placed only by OPTIONs. A car left in Oban stays there until an OPTION moves it. A BOOKING gives a right over a period, such as a room for two nights, a car for three days or a rail pass for a week; it never places anyone anywhere. The bed WANT is SATISFIED by whatever OPTION has a PERSON sleeping somewhere: a hotel night, a sleeper train, a tent.
*Serves:* compiler. *Source:* the space-time path (Hägerstrand, 1970), which covers people; giving OBJECTs paths is our extension.

**D4. DECISIONs and FACTs do not change each other.** A LOCK says "we are doing this"; a PIN says "suppose we did this" inside a VARIANT. Only a FACT makes an OPTION UNAVAILABLE. If a LOCKed OPTION becomes UNAVAILABLE, the LOCK stays and the COMPILER reports an ERROR; it never quietly swaps in something else.
*Serves:* whole-lifecycle, trustworthy.

**D5. A quote is not a BOOKING, and a BOOKING is not attendance.** An OFFER promises nothing. A BOOKING secures a right. Who holds the right, who is planned to take part and who actually went are recorded separately: my BOOKING might be used by my brother.
*Serves:* compiler, open. *Source:* ODRL 2.2, where an Offer "does not grant any Rules" (W3C, 2018); Hohfeld (1913) for an offer as a power to accept; keeping beneficiaries apart from participants follows practice (ODRL's assignee; schema.org's underName).

**D6. Some OPTIONs need a CAPABILITY or an OBJECT.** The manual hire car needs a driver who can drive manual, and the drive needs the car. An ITINERARY meets this only if a PERSON with the CAPABILITY takes part and the OBJECT is there.
*Serves:* compiler.

**D7. BUDGET limits are CONSTRAINTs, and currencies never mix.** An ITINERARY that overdraws a limited currency is not FEASIBLE; unlimited currencies only report what is spent. A £2,000 limit counts only pounds and a 100,000-point limit only points: no conversion ever decides FEASIBLE. Every cost is paid from a named BUDGET. A BOOKING already paid records its payer and BUDGET as a FACT; for an OFFER not yet bought, a DECISION can fix the paying BUDGET, and otherwise the COMPILER picks among the BUDGETs allowed to pay, within their limits, and reports its pick. An OFFER may list alternative prices ("£420, or 35,000 points"), and which one is paid is a choice like any other. Prices come from OFFERs and BOOKINGs; a missing price is unknown, never zero. An OPTION may also state what it draws from a BUDGET for its own sake, such as energy or fuel, separately from any price. Energy can refill with a night's sleep; money never refills.
*Serves:* compiler, optimizer, trustworthy. *Source:* the Money pattern, an amount always carried with its currency (Fowler, 2002; to be verified).

**D8. Access cutoffs.** A PERSON or OBJECT may have to arrive a stated time before an OPTION starts: boarding closes 30 minutes before departure. Each cutoff applies to its own path; a car's earlier check-in is not the passenger's.
*Serves:* compiler. *Source:* a difference constraint in a simple temporal network (Dechter, Meiri and Pearl, 1991).

**D9. A BOOKING counts three things separately:** units bought, uses per unit, and who or what each covers. Two one-person tickets, one family ticket for four and one room for two are different FACTs. A BOOKING also records who paid, and from which BUDGET.
*Serves:* compiler, open.

**D10. A LOCK can fix part of a choice, or name a list or a description.** It can fix only the date of an OPTION; say "at least one of these ferries"; or name a description, such as "a hotel in central Kyoto, nights of the 10th to the 14th". Any OPTION matching the description can fill it. If the FILE holds matching OPTIONs, the COMPILER chooses among them like any other choice. If none are listed, or the matching set is not COMPLETE, the TRIP is UNDETERMINED with the condition named ("FEASIBLE if a hotel in central Kyoto is found for those nights"), and everything else is still planned around it. A description is a filter on an OPTION's own fields (kind, PLACE, time, and measurable attributes such as price), written in the same schema-defined form as COMPLETE FACTs and derived SATISFIES links; free-text descriptions are not allowed.
*Serves:* whole-lifecycle, intuitive, flexible. *Source:* stepwise refinement (Wirth, 1971); abstract tasks in hierarchical planning (Erol, Hendler and Nau, 1994) (to be verified).

**D11. An OFFER that can still be bought can make a TRIP FEASIBLE,** with a WARNING that the purchase is not secured. Only a BOOKING removes the WARNING.
*Serves:* whole-lifecycle, trustworthy.

## E. What the COMPILER answers

**E1. A TRIP is FEASIBLE if at least one ITINERARY meets every CONSTRAINT.** Checking pieces separately is not enough: the drive and the ferry can each be possible and still not fit together.
*Serves:* compiler, trustworthy. *Source:* the constraint satisfaction problem (Montanari, 1974; Mackworth, 1977): an ITINERARY is a complete assignment, and a FEASIBLE one is a solution.

**E2. Every check returns FEASIBLE, INFEASIBLE or UNDETERMINED.** FEASIBLE: an ITINERARY works however the unknown FACTs turn out. INFEASIBLE: no ITINERARY works however they turn out. UNDETERMINED: the answer depends on FACTs the FILE does not hold, and the report names them ("FEASIBLE only if a route under 2 h 15 min exists"). An undecided choice never makes a TRIP UNDETERMINED; only missing FACTs or a search limit do.
*Serves:* trustworthy, self-explaining. *Source:* solver result statuses (SMT-LIB; CP-SAT); certain answers over incomplete information (Imieliński and Lipski, 1984; Libkin, 2016).

**E3. INFEASIBLE needs a COMPLETE set.** An INFEASIBLE result that rests on an OPTION not existing ("no OPTION gets you from Craignure to Fionnphort before 17:50") needs a FACT saying that set of OPTIONs is COMPLETE. Not finding an OPTION is no proof that none exists.
*Serves:* trustworthy. *Source:* the closed-world assumption (Reiter, 1978), applied to a stated scope (Etzioni, Golden and Weld, 1997).

**E4. SETTINGs, never assumed FACTs.** Thresholds such as the minimum connection time are SETTINGs with defaults pinned in the COMPILER, and every report names any override. The COMPILER never assumes a FACT it is not given; it returns UNDETERMINED and states the condition instead ("FEASIBLE if the walk needs no BOOKING"). An assumed ferry time is exactly how a real trip goes wrong.
*Serves:* trustworthy, deterministic.

**E5. Every result shows its evidence.** FEASIBLE: the ITINERARY and the FACTs and DECISIONs it relies on. INFEASIBLE: the smallest set of FACTs and DECISIONs that conflict. UNDETERMINED: the missing FACTs. A fixed rule picks among equal explanations, so the same FILE always gives the same one.
*Serves:* self-explaining, deterministic. *Source:* QuickXplain (Junker, 2004); why-provenance (Buneman, Khanna and Tan, 2001).

**E6. Every FINDING is visible.** A DISMISSAL silences an ERROR, WARNING or NOTE as it stood, and the FINDING returns if it gets worse. UNDETERMINED FINDINGs, and ERRORs meaning the FILE cannot be read, cannot be dismissed.
*Serves:* trustworthy, self-explaining.

**E7. An OPTION belongs only if something needs it.** An ITINERARY includes an OPTION only if a WANT or a LOCK needs it, directly or through a chain: the drive to reach the ferry, the ferry to reach Iona. Detours and loops cannot justify themselves.
*Serves:* optimizer, self-explaining.

**E8. Every DEADLINE is listed.** OFFERs and BOOKINGs record their dated terms: when an OFFER expires, and what cancelling or changing costs on each date. Before and during the trip, the COMPILER lists every upcoming DEADLINE at which cost or availability changes, or by which a DECISION is due, with its STAKE, earliest first: "Hotel C becomes non-refundable Friday: £420 at STAKE."
*Serves:* whole-lifecycle, self-explaining, trustworthy.

**E9. What still fits.** Between any two fixed points in an ITINERARY, such as the museum at 10:00 and the ferry at 17:50, the COMPILER lists which OPTIONs still fit, for each PERSON. It answers "what can we do this afternoon?" while planning and during the trip.
*Serves:* whole-lifecycle, self-explaining. *Source:* the space-time prism (Hägerstrand, 1970); computing reachable areas (Lenntorp, 1976; Miller, 1991) (to be verified).

## F. Risk, the live trip and recovery

Each rule below is followed by a formal sketch, a first step toward codifying it.

**F1. BET.** An OPTION is a BET when it must be committed before the FACT that decides whether it works becomes known. The report names the DEADLINE, the missing FACT and the STAKE. A BET never makes a TRIP INFEASIBLE. If the FACT becomes known before the DEADLINE, there is no BET: wait.
*Serves:* self-explaining, whole-lifecycle. *Source:* value of information (Howard, 1966), for further reading only: it assumes probabilities the FILE does not hold.

```
BET exists when:
  an OPTION must be committed by DEADLINE
  AND a FACT deciding whether it works becomes known at ARRIVAL
  AND ARRIVAL > DEADLINE
STAKE = what is lost if the FACT goes badly
        (from the OFFER or BOOKING terms; unknown if unstated)
A BET never makes the TRIP INFEASIBLE.
If ARRIVAL <= DEADLINE: no BET. Advice: wait.
```

**F2. ROBUST and RECOVERABLE.** An ITINERARY is ROBUST if every clock time can be fixed now and it still works however long the CONTINGENT durations, such as traffic, turn out. It is RECOVERABLE if, when any one BOOKING it relies on fails, a FEASIBLE ITINERARY exists within a stated number of changes, set by a SETTING. The report warns when a FEASIBLE TRIP is not ROBUST or not RECOVERABLE.
*Serves:* trustworthy, whole-lifecycle. *Source:* strong controllability (Vidal and Fargier, 1999); supermodels (Ginsberg, Parkes and Roy, 1998), adapted as super solutions by Hebrard, Hnich and Walsh (2004).

```
ROBUST(ITINERARY) iff
  one set of clock times meets every CONSTRAINT
  for every value of every CONTINGENT duration
RECOVERABLE(ITINERARY) iff
  for each BOOKING it relies on:
    if cancelled -> a FEASIBLE ITINERARY exists within k changes
WARNING if FEASIBLE but not ROBUST, or not RECOVERABLE.
```

**F3. Agreed versus current.** The agreed ITINERARY is the one fixed by the current LOCKs. Every new FACT re-checks it, and the report lists each step now late and each BOOKING now at risk. A LOCKed step whose time has passed counts as done unless a FACT says otherwise. What actually happened is recorded as FACTs: actual times, who took part, and spending outside BOOKINGs. The agreed ITINERARY at any moment can be recomputed from the FILE's revision at that moment, so it is never stored separately.
*Serves:* whole-lifecycle. *Source:* valid time versus transaction time in bitemporal databases (Snodgrass and Ahn, 1985); baseline versus actual in schedule management (US GAO Schedule Assessment Guide) as established practice.

```
Agreed ITINERARY = the one fixed by the current LOCKs
On every new FACT:
  re-check the agreed ITINERARY against the current FACTs
  report each step now late and each BOOKING now at risk
Past steps are fixed (B3).
A LOCKed step whose time has passed is done, unless a FACT says otherwise.
```

**F4. Repair before replanning.** When the agreed ITINERARY becomes INFEASIBLE, the OPTIMIZER first proposes fixes that change the fewest LOCKs and BOOKINGs and affect the fewest PERSONs, and only then ranks by SCORE. Owners accept or decline (B2).
*Serves:* whole-lifecycle, multiplayer. *Source:* plan repair that protects bookings and commitments to others (Babli, Sapena and Onaindia, 2023); plan stability (Fox, Gerevini, Long and Serina, 2006).

```
When a new FACT makes the agreed ITINERARY INFEASIBLE:
  rank FEASIBLE ITINERARIES by:
    1. fewest changes to LOCKs and BOOKINGs
    2. fewest PERSONs affected
    3. then SCORE
  propose the top few to their owners (B2)
```

**F5. Live dispatch.** During the trip, every upcoming step has an earliest start, a latest start and its slack, and a list of what breaks downstream if it slips. Every new FACT recomputes them. The COMPILER warns when slack runs low or negative, and states each DEADLINE for a DECISION.
*Serves:* whole-lifecycle, self-explaining. *Source:* dispatchable temporal plans (Muscettola, Morris and Tsamardinos, 1998).

```
During the trip, for every upcoming step:
  earliest start, latest start, slack = latest - earliest
  everything downstream that breaks if it slips
On every new FACT (a delay, an early arrival):
  recompute all of the above
  WARNING when any slack drops below its SETTING or below zero
  state each DEADLINE for a DECISION ("decide on the bus by 14:10")
```

**F6. Contingency branches.** An ITINERARY can branch on something learned during the trip: "if the boat is cancelled, take the bus". It is FEASIBLE only if every branch is FEASIBLE and each observation comes before the steps that depend on it.
*Serves:* whole-lifecycle, flexible. *Source:* conditional temporal plans (Tsamardinos, Vidal and Pollack, 2003).

```
IF observation O by time t THEN OPTIONS A ELSE OPTIONS B
FEASIBLE requires every branch to be FEASIBLE
O must be knowable by t, before any step that depends on it
```

## G. Ranking and fairness

**G1. Rank by SCORE, and show every PERSON's SCORE.** The OPTIMIZER orders FEASIBLE ITINERARIES by total SCORE. Every ranking shows each PERSON's own SCORE beside the total, so nobody's loss hides in a sum.
*Serves:* optimizer, multiplayer, self-explaining. *Source:* group recommender systems (Jameson and Smyth, 2007); PolyLens (O'Connor et al., 2001).

**G2. Money, time and risk are WANTs too.** If you care about cost, you say so the way you would say anything else you want: "keep the trip cheap", ranked alongside seeing Iona or a good dinner. You also say what cheap means: under £1,500 is perfect, over £3,000 is no good. A £2,000 ITINERARY then counts partway, and how much that matters depends on where you ranked it. Driving time and risk work the same way. Hard limits on spending stay CONSTRAINTs. A cost WANT names its currency; other currencies convert at an exchange rate recorded as a dated FACT, never a live lookup, and points convert at the value their holder states ("I value a point at 1.2p"), because what a point is worth is personal. Conversions affect SCORE only, never FEASIBLE.
*Serves:* optimizer, intuitive, trustworthy. *Source:* the additive value model (Keeney and Raiffa, 1976).

**G3. Fairness is reported across the whole TRIP.** The ranking flags any ITINERARY in which one PERSON's SCORE trails far behind the others, or in which the same PERSON loses every choice. Shared rooms and costs are split so that nobody would rather swap.
*Serves:* multiplayer. *Source:* perpetual voting (Lackner, 2020); rental harmony (Su, 1999; Alkan, Demange and Gale, 1991).

**G4. Change has a cost.** Once an ITINERARY is agreed, the OPTIMIZER proposes a different one only if its SCORE beats the agreed one by more than a SETTING. Small gains do not justify reshuffling BOOKINGs.
*Serves:* whole-lifecycle, multiplayer. *Source:* rescheduling with a stability penalty (Wu, Storer and Chang, 1993).

**G5. VARIANTs are compared side by side.** For comparison, each VARIANT is represented by its best ITINERARY: the highest SCORE, with ties broken by the fixed rule (E5). The report shows the VARIANTs side by side: FEASIBLE or not, total and per-PERSON SCORE, spend per currency, and what differs from the agreed ITINERARY.
*Serves:* optimizer, multiplayer, self-explaining.
