# Vocabulary

These are Agloe's protected terms. In every Agloe document a protected term is written in capitals and means exactly what this page says. A word in lower case has its ordinary meaning.

Each entry gives a definition, the protected terms it uses, and notes where a boundary needs stating. Terms are defined before they are used wherever possible; a forward reference is marked with an arrow (→).

Two usage rules apply throughout:

- An OPTION or an ITINERARY **SATISFIES** a WANT. An ITINERARY **meets** a CONSTRAINT. The two verbs are never swapped.

---

## 1. The TRIP and its FILE

### TRIP

The trip being planned, lived and recorded: the PERSONs it concerns, their WANTs, the PLACEs, OBJECTs and BUDGETs involved, the OPTIONs that could make it up, the OFFERs and BOOKINGs for them, and the DECISIONs taken. A TRIP is not one fixed plan. It describes a space of possible ITINERARIES, and the COMPILER reports whether that space contains one that works.

*Uses:* → PERSON, → WANT, → PLACE, → OBJECT, → BUDGET, → OPTION, → OFFER, → BOOKING, → DECISION, → ITINERARY, → COMPILER.

### SCOPE

The TRIP's frame: its dates, the PLACE each traveling PERSON starts from and returns to, what the TRIP is for, and anything explicitly out of bounds. The COMPILER uses the SCOPE to know which days and nights to check.

*Uses:* TRIP, PLACE, PERSON, COMPILER.

### FILE

The document that records one TRIP in the Agloe format, valid against the published schema. Each saved state of a FILE is a revision. Several copies of a FILE may exist and be merged; they record the same TRIP. The COMPILER reads only the FILE.

*Uses:* TRIP, → COMPILER.

---

## 2. What the FILE records

A FILE changes only by adding records of three kinds: FACTs, WANTs and DECISIONs. Each record is dated and carries its author, its source where it has one, and an optional reason.

### FACT

A dated record about the world, with its source: an OPTION's time, a price, a travel time, an OPTION being UNAVAILABLE, a set of OPTIONs being COMPLETE. The current FACTs describe the world as currently understood; earlier values survive only where the FILE records them.

*Uses:* FILE, → OPTION, → UNAVAILABLE, → COMPLETE.

### STALE

Describes a FACT older than its stated or default freshness limit. A STALE FACT may still be true; the COMPILER flags it and keeps using it.

*Uses:* FACT, → COMPILER.

### DRIFT

A newer FACT that contradicts an older one about the same thing: the 15:55 sailing now leaves at 16:10. The newer FACT wins, and the change is recorded.

*Uses:* FACT.

### COMPLETE

Describes a set of OPTIONs that a FACT states the FILE holds in full: every OPTION between two PLACEs starting within a stated time span. A COMPLETE set that is empty means "we looked, and there is nothing". A FACT that one set is COMPLETE says nothing about any other set.

*Uses:* OPTION, FACT, FILE, → PLACE.

### DECISION

A dated choice by a PERSON: a LOCK, a PIN or a DISMISSAL, or the undoing of one. A DECISION is never edited; changing your mind is a new DECISION that names the one it undoes.

*Uses:* → PERSON, → LOCK, → PIN, → DISMISSAL.

---

## 3. Things that exist over time

### PERSON

A human the TRIP concerns, whether or not they travel. A PERSON may hold WANTs, have CAPABILITIES, draw on BUDGETs and take part in OPTIONs. In any ITINERARY, a PERSON who travels is at exactly one PLACE or in exactly one OPTION at every moment.

*Uses:* TRIP, → WANT, → CAPABILITY, → BUDGET, → OPTION, → ITINERARY, → PLACE.

### CAPABILITY

Something a PERSON can do: drive a manual car, climb stairs, dive. An OPTION can require a CAPABILITY; an ITINERARY meets that requirement only if a PERSON with the CAPABILITY takes part in the OPTION.

*Uses:* PERSON, → OPTION, → ITINERARY.

### PLACE

A location where OPTIONs happen, or between which they move: a city, a harbor, a hotel, a museum. A PLACE may sit within a larger PLACE: a museum within central Kyoto, within Kyoto. A PLACE exists over time; it does not happen. The Louvre is a PLACE; a visit to the Louvre on Thursday morning is an OPTION.

*Uses:* → OPTION.

### OBJECT

A physical thing with a position that OPTIONs may require or move: a rental car, a bag, diving gear. In any ITINERARY, an OBJECT is at one PLACE, with one PERSON, or in one OPTION at every moment, and it changes position only through OPTIONs.

*Uses:* PLACE, PERSON, → OPTION, → ITINERARY.
*Notes:* holding an OBJECT is not being somewhere. Renting a car gives a PERSON the car; it does not keep the PERSON at the rental desk.

### BUDGET

A store of one or more currencies that OPTIONs, OFFERs and BOOKINGs draw on: money, loyalty points, energy. A BUDGET belongs to one PERSON or is shared by several, and states which PERSONs may draw on it. Each currency either has a limit or is unlimited. Limits never mix currencies: no conversion ever decides whether a limit is kept. A currency may refill on a stated event, as energy does with a night's sleep; money never refills.

*Uses:* PERSON, → OPTION, → OFFER, → BOOKING.

---

## 4. Time

### CONTROLLABLE

Describes a duration whose exact value, within its stated range, the TRIP's planners choose: how long to stay at the museum.

*Uses:* TRIP.

### CONTINGENT

Describes a duration whose exact value, within its stated range, the world decides: how long traffic makes the drive. A FEASIBLE ITINERARY may rely on any value in the range; a ROBUST ITINERARY must work for every value.

*Uses:* → FEASIBLE, → ROBUST, → ITINERARY.

---

## 5. Things that happen

### OPTION

Something that happens at a time and that a TRIP may include: this ferry sailing, this room on this night, dinner at eight on Thursday. An OPTION has:

- a time: a fixed time, an allowed time window, or left to be scheduled;
- a duration: an exact value, a CONTROLLABLE range or a CONTINGENT range;
- a PLACE, or a pair of PLACEs for a movement;
- the PERSONs and OBJECTs it involves, and any CAPABILITIES and OBJECTs it requires;
- anything it draws from a BUDGET for its own sake, such as energy or fuel, separately from any price.

Every time carries a date and a time zone. An OPTION is never deleted from the FILE.

*Uses:* TRIP, PLACE, PERSON, OBJECT, CAPABILITY, CONTROLLABLE, CONTINGENT, FILE.

### UNAVAILABLE

Describes an OPTION that a FACT says can no longer happen for this TRIP: sold out, cancelled, missed. An UNAVAILABLE OPTION stays in the FILE but is in no ITINERARY. Only a FACT makes an OPTION UNAVAILABLE; no DECISION does, and becoming UNAVAILABLE undoes no DECISION.

*Uses:* OPTION, FACT, TRIP, FILE, DECISION, → ITINERARY.

---

## 6. WANTs

### WANT

Something PERSONs want, or want to avoid, from the TRIP: a bed each night, seeing Iona, no starts before 7. A WANT has one or more holders, each a PERSON with their own DEGREE OF WANT for it. A holder who has not been asked has no DEGREE OF WANT yet; that is unelicited, never zero.

A WANT is about one of two things:

- something an OPTION can deliver, such as dinner, a bed or a visit; or
- a property of the whole ITINERARY, such as "at most two hotel changes", written with a fixed set of operators (always, never, at most n times, at most a total amount per day or per TRIP, after, within).

Each PERSON's ranking of their WANTs is recorded as a full snapshot; the latest applies. A negative WANT never adds an OPTION to a TRIP. Every traveling PERSON starts with a published set of starter WANTs for basic needs (a bed each night, getting home, meals, rest, staying together); they are stored like any other WANT and can be re-ranked or dropped.

*Uses:* PERSON, TRIP, OPTION, → DEGREE OF WANT, → ITINERARY.

### DEGREE OF WANT

How strongly one holder feels about one WANT: a whole number from −10 to +10.

- **+10** is a must: a CONSTRAINT that the ITINERARY SATISFIES the WANT.
- **−10** is a must-not: a CONSTRAINT that the ITINERARY does not SATISFY the WANT.
- **0** is indifference.
- **1 to 9 and −1 to −9** are preferences. They are not typed in: each PERSON ranks their own WANTs, and a fixed rule converts the ranking into DEGREEs OF WANT. Adding a WANT to a ranking shifts the others, and the report shows the shift.

*Uses:* WANT, PERSON, → CONSTRAINT, → ITINERARY, → SATISFIES.
*Notes:* a DEGREE OF WANT belongs to one holder and one WANT. Two holders of the same WANT may differ.

### DECOMPOSED

Describes a WANT too big for one OPTION, split into pieces along its natural units: "dinner each night" becomes one piece per night. Each piece is SATISFIED at most once, so nothing is counted twice.

*Uses:* WANT, OPTION, → SATISFIES.

### SATISFIES

The relation between a WANT and what delivers it. An OPTION SATISFIES a WANT when it delivers the thing the WANT describes; for a WANT about the whole ITINERARY, the ITINERARY SATISFIES it when the property holds. Each SATISFIES relation from an OPTION carries a DEGREE OF SATISFACTION.

Whether delivery is good or bad comes from the DEGREE OF WANT, not from SATISFIES. An overnight bus SATISFIES a WANT about overnight travel; for a holder at −7, that counts against the ITINERARY, and it always counts when the bus is in the ITINERARY for any reason.

No stated relation means unknown, never "does not satisfy". A relation may be stated directly, or derived from an OPTION's FACTs: a WANT about departures before 06:00 applies to every OPTION that departs earlier.

*Uses:* WANT, OPTION, DEGREE OF WANT, FACT, → ITINERARY, → DEGREE OF SATISFACTION.

### DEGREE OF SATISFACTION

On a SATISFIES relation from an OPTION, a whole number from 0 to 10: how fully the OPTION delivers the thing the WANT describes. Zero states explicitly that it does not. Any value above zero means it does, and the number says how well.

*Uses:* SATISFIES, OPTION, WANT.
*Notes:* the same kebab shop is a 2 for "a nice dinner" and an 8 for "quick food before a train".

---

## 7. Commerce

### OFFER

A seller's proposal, recorded as a FACT: the right to use certain OPTIONs, for certain PERSONs or OBJECTs, in a stated quantity, at a stated price and on stated terms, including the date it expires. An OFFER may list alternative prices, such as "£420, or 35,000 points". An OFFER grants nothing. Missing price or terms are unknown, never free. An OFFER that can still be bought may support a FEASIBLE ITINERARY, with a WARNING that the purchase is not secured.

*Uses:* FACT, OPTION, PERSON, OBJECT, → FEASIBLE, → ITINERARY, → WARNING.

### BOOKING

An accepted agreement with a seller, recorded as a FACT, that secures the right to use certain OPTIONs: a seat on the 11:15 ferry, a room for two nights. A BOOKING records its dated terms, such as what cancelling or changing costs on each date. It states separately how many units it secures, how many uses each unit allows, and which PERSONs or OBJECTs each covers. The PERSONs a BOOKING names hold its rights; they are not necessarily the PERSONs who take part. A BOOKING gives a right over a period; it never places anyone anywhere, and it does not put an OPTION into an ITINERARY; a LOCK does. Cancelling a BOOKING ends its right and leaves any LOCK in place.

*Uses:* FACT, OPTION, PERSON, OBJECT, → ITINERARY, → LOCK.

---

## 8. DECISIONs

### LOCK

A DECISION that the TRIP includes an OPTION, or at least one OPTION from a stated list or matching a stated description ("a hotel in central Kyoto, nights of the 10th to the 14th"). A LOCK may also fix part of a choice, such as only the date, and names the PERSONs taking part. Detail arrives as new, more specific LOCKs; an existing LOCK is never edited. Every ITINERARY must honor every active LOCK. A LOCK stays until a later DECISION undoes it; no FACT undoes it. If a LOCKed OPTION becomes UNAVAILABLE, the LOCK stays and the COMPILER reports the conflict.

*Uses:* DECISION, TRIP, OPTION, PERSON, FACT, UNAVAILABLE, → ITINERARY, → COMPILER.

### VARIANT

A named what-if version of the TRIP, defined by its PINs. The COMPILER checks each VARIANT separately: its ITINERARIES must honor every active LOCK and every PIN in that VARIANT. One VARIANT never affects another, or the TRIP's own result. For comparison, a VARIANT is represented by its highest-SCORE ITINERARY.

*Uses:* TRIP, LOCK, → PIN, → ITINERARY, → COMPILER.

### PIN

A LOCK that applies only inside one VARIANT: "suppose we did this".

*Uses:* LOCK, VARIANT.

### DISMISSAL

A DECISION that silences one ERROR, WARNING or NOTE as it stood. It identifies the FINDING by its rule and the stable ids involved, never by position in the FILE. The FINDING returns if it gets worse than when it was dismissed. An UNDETERMINED FINDING, and an ERROR meaning the FILE cannot be read, cannot be dismissed. A DISMISSAL changes the report, never the FACTs or the checks.

*Uses:* DECISION, FILE, FACT, → FINDING, → ERROR, → WARNING, → NOTE, → UNDETERMINED.

---

## 9. The COMPILER and its results

### COMPILER

The program that reads one FILE and reports, for the TRIP and for each VARIANT, whether it is FEASIBLE, INFEASIBLE or UNDETERMINED, together with every FINDING. It reads nothing but the FILE, its own pinned rules and SETTINGs: the same FILE gives the same report on any machine, on any day, and each report names the FILE revision, the COMPILER version and the time it treated as now.

*Uses:* FILE, TRIP, VARIANT, → FEASIBLE, → INFEASIBLE, → UNDETERMINED, → FINDING, → SETTING.

### ITINERARY

One complete way the TRIP could go: which OPTIONs happen, the exact start and end of each, the value chosen or assumed for each duration, which PERSONs and OBJECTs take part in each, and, for each OPTION that needs a right, the BOOKING or OFFER that covers it, which price is paid and from which BUDGET. In constraint-solving terms, an ITINERARY is a complete assignment of the TRIP's choices. An ITINERARY is derived by the COMPILER; it is never stored in the FILE.

*Uses:* TRIP, OPTION, PERSON, OBJECT, BOOKING, OFFER, BUDGET, COMPILER, FILE.

### CONSTRAINT

A requirement every ITINERARY must meet. The CONSTRAINTs include: every traveling PERSON and every OBJECT has one unbroken path; every +10 WANT is SATISFIED and no −10 WANT is; no limited BUDGET currency is overdrawn; every active LOCK is honored; every OPTION's time rules and access cutoffs are kept; every required CAPABILITY and OBJECT is present; and every OPTION that requires a right is covered by a BOOKING or an OFFER. The specification holds the complete list.

*Uses:* ITINERARY, PERSON, OBJECT, WANT, BUDGET, LOCK, OPTION, CAPABILITY, BOOKING, OFFER.

### FEASIBLE

A TRIP or VARIANT is FEASIBLE when at least one ITINERARY meets every CONSTRAINT, however the unknown FACTs turn out.

*Uses:* TRIP, VARIANT, ITINERARY, CONSTRAINT, FACT.
*Notes:* "unknown FACTs" means FACTs the FILE does not state. A CONTINGENT duration is not unknown; it has a stated range, and FEASIBLE may rely on any value in it.

### INFEASIBLE

A TRIP or VARIANT is INFEASIBLE when no ITINERARY meets every CONSTRAINT, however the unknown FACTs turn out. A conclusion that no OPTION exists to do something needs a FACT that the relevant set of OPTIONs is COMPLETE.

*Uses:* TRIP, VARIANT, ITINERARY, CONSTRAINT, FACT, OPTION, COMPLETE.

### UNDETERMINED

A TRIP, VARIANT or individual check is UNDETERMINED when it is neither FEASIBLE nor INFEASIBLE: the answer depends on FACTs the FILE does not hold, or the search stopped at its stated limit. The report names the missing FACTs and the conditions under which it would be FEASIBLE.

*Uses:* TRIP, VARIANT, FEASIBLE, INFEASIBLE, FACT, FILE.
*Notes:* an undecided choice never makes a TRIP UNDETERMINED. Choices are what the COMPILER searches over; only missing FACTs or a search limit do.

### FINDING

Anything the COMPILER reports about a TRIP. Every FINDING is an ERROR, a WARNING, a NOTE or UNDETERMINED, and shows its evidence: the FACTs and DECISIONs it rests on.

*Uses:* COMPILER, TRIP, FACT, DECISION, → ERROR, → WARNING, → NOTE, UNDETERMINED.

### ERROR

A FINDING that something is broken: the FILE does not follow the format, or a CONSTRAINT cannot be met under the current FACTs and DECISIONs.

*Uses:* FINDING, FILE, CONSTRAINT, FACT, DECISION.

### WARNING

A FINDING that something is risky or unpleasant without being broken: a BET, an ITINERARY that is not ROBUST or RECOVERABLE, an OFFER not yet booked, a tight connection.

*Uses:* FINDING, → BET, → ROBUST, → RECOVERABLE, OFFER.

### NOTE

A FINDING worth knowing that needs no action: a WANT nobody has been asked about, an empty day, a STALE FACT.

*Uses:* FINDING, WANT, STALE, FACT.

### SETTING

A threshold the COMPILER uses, such as the minimum connection time or the slack that triggers a WARNING. Each SETTING has a default pinned in the COMPILER version. A FILE may override it, and every report names each override, so a tuned result never reads like an untuned one.

*Uses:* COMPILER, WARNING, FILE.

---

## 10. The OPTIMIZER

### SCORE

A number for one FEASIBLE ITINERARY: for every PERSON and every WANT they hold, the DEGREE OF WANT times the DEGREE OF SATISFACTION the ITINERARY delivers, all added up. A WANT the ITINERARY does not SATISFY adds nothing; a negative WANT it SATISFIES subtracts. Each PERSON also has their own SCORE, the same sum over only their WANTs, and every ranking shows it beside the total.

*Uses:* FEASIBLE, ITINERARY, PERSON, WANT, DEGREE OF WANT, DEGREE OF SATISFACTION, SATISFIES.

### OPTIMIZER

The program that orders the FEASIBLE ITINERARIES of a TRIP by SCORE, and proposes repairs when the agreed ITINERARY stops working. It uses the COMPILER to check everything it proposes.

*Uses:* FEASIBLE, ITINERARY, TRIP, SCORE, COMPILER.

---

## 11. Risk

### DEADLINE

A dated point at which something about the TRIP changes unless a DECISION comes first: an OFFER expires, a BOOKING's cancellation cost rises, a price changes, or a DECISION a PERSON has set a date for falls due. DEADLINEs come from OFFER and BOOKING terms, from BETs, and from PERSONs. The COMPILER lists every upcoming DEADLINE with its STAKE, earliest first.

*Uses:* TRIP, DECISION, OFFER, BOOKING, PERSON, COMPILER, → BET, → STAKE.

### ROBUST

An ITINERARY is ROBUST when one fixed set of clock times meets every CONSTRAINT for every value of every CONTINGENT duration.

*Uses:* ITINERARY, CONSTRAINT, CONTINGENT.

### RECOVERABLE

An ITINERARY is RECOVERABLE when, for each BOOKING it relies on, a FEASIBLE ITINERARY would still exist within a stated number of changes if that BOOKING were cancelled.

*Uses:* ITINERARY, BOOKING, FEASIBLE.

### BET

An OPTION that must be committed, by LOCK or BOOKING, before a deadline that falls earlier than the time at which a FACT deciding whether it works becomes known. A BET never makes a TRIP INFEASIBLE. If the FACT becomes known before the deadline, there is no BET.

*Uses:* OPTION, LOCK, BOOKING, FACT, TRIP, INFEASIBLE.

### STAKE

What is lost when a DEADLINE passes, or when a BET's FACT goes against it, priced from the OFFER or BOOKING terms. If those terms are missing, the STAKE is unknown; only an explicit zero makes it free.

*Uses:* DEADLINE, BET, FACT, OFFER, BOOKING.
