// The rights to the OPTIONs of a FILE, as the page shows them. There is no page in here, so
// the tests run this as it is.
//
// The view sends what the FILE says of the rights to each OPTION: whether a PERSON needs a
// right to take part, each BOOKING with the PERSONs and the OBJECTs it covers, the name to
// show for each of them in one list, what it paid, and its terms for cancelling and for
// changing, each OFFER
// with its places, the OBJECTs that it names and the price of one place, and the FACT that
// the FILE lists every right to the OPTION. It also sends the time now, where a FACT states
// it. This puts
// them in words, as the report words them. Where the report says what cancelling or changing
// a BOOKING costs at the time now, the BOOKING says that too. Where the report shows a plan, it says who uses
// each BOOKING and who takes a place of each OFFER in that plan, as the report states it. It
// marks what the report names: the records that rule out every plan, and the cases in which a
// trip that depends on something works.
//
// Nothing here judges a TRIP. Whether everybody who takes part has a right is for the
// COMPILER to say: the page names who uses a right only where the report does.

import { KINDS_OF_TERMS, carriedIn, costsNowIn, expiredIn, listed, marksBy, optionsOf, toBuyIn, usesIn, withExpired } from "./named.js";
import { amountOf, paidOf } from "./money.js";
import { needsARight } from "./who.js";

/** What a case of a report can need that is about the rights to an OPTION, for a PERSON or for an OBJECT. */
const ABOUT_RIGHTS = new Set(["another right", "needs no right", "price", "funding", "charged", "another right for", "needs no right for"]);

/**
 * An OFFER, as the report words it: its places, until when they can be bought, where it
 * states that, the OBJECTs that a place can cover, where it names any, and what one place
 * costs. An OFFER that has expired by the time now of the FILE had its places.
 */
function offerOf(offer) {
  const places = offer.places === 1 ? "1 place" : `${offer.places} places`;
  const price = offer.price === null ? "; nobody knows the price" : `, for ${offer.price.amount} ${offer.price.currency}${offer.places > 1 ? " each" : ""}`;
  const covers = offer.objects.length ? ` to cover ${listed(offer.objects.map((id) => offer.names[id]), "or")}` : "";
  const until = typeof offer.until === "string" ? ` until ${offer.until}` : "";
  if (offer.expired === true) return `an OFFER that had ${places} that could be bought${until}${covers}${price}`;
  // Where the FILE states no time now, nobody knows whether that time has passed.
  const still = offer.expired === null ? "" : " still";
  return `an OFFER with ${places} that can${still} be bought${until}${covers}${price}`;
}

/**
 * Whether the BOOKINGs and the OFFERs under an OPTION are all the rights for a PERSON to take
 * part in it, as the report words it. A right for an OBJECT is another matter.
 */
function wholeOf(complete, expired) {
  if (complete === null) return "Another right for a PERSON to take part in it may exist: the FILE does not say that these are all.";
  // The set names an OFFER as long as the FILE holds it: one that has expired is marked.
  const except = complete.offers.length ? `, except from ${listed(withExpired(complete.offers, expired))}` : "";
  return `The FILE lists every right for a PERSON to take part in it: nobody on the trip holds another or can get one${except}.`;
}

/**
 * What the page shows of the rights to the OPTIONs of a TRIP as the view sends it, or of no
 * TRIP where the view sends none.
 *
 * There is one for each OPTION that needs a right, or that the FILE has a BOOKING, an OFFER or
 * a FACT that its rights are all listed for. Each has the name of its OPTION, whether people
 * need a right (`needs`), its `bookings` and its `offers`, and whether those are all the
 * rights to it (`whole`). A BOOKING and an OFFER are named by their ids. Each has what the
 * FILE says of it (`says`), and who uses it in the plan of the report (`uses`, null where the
 * report shows no plan). Where the plan buys a place only if the OPTION turns out to need a
 * right, the OFFER says so, as the report does.
 *
 * `report` is the report as JSON, where the page has one. `clash` on the rights to an OPTION,
 * on a BOOKING or on an OFFER holds its `records` that the report names as ruling out every
 * plan, and `finds` says so. `cases` holds the cases that name it among what the FILE does not
 * say, as their places in `missing` of the report, and `asks` holds what the report says of
 * them. `stated` holds the words of the report for those cases, as lines.js finds them.
 * `clash` and `asked` on the whole say that something here is marked so.
 */
/** What the terms of each kind state, as a report heads it, and what a term says where the seller accepts none. */
const COSTS = { cancelling: "What cancelling costs", changing: "The fee for a change" };
const APART = { cancelling: "", changing: ", apart from any difference in price" };
const NONE_ACCEPTED = { cancelling: "the seller accepts no cancellation", changing: "the seller accepts no change" };

/**
 * What a BOOKING states for cancelling it and for changing it: one sentence for each kind of
 * terms that it states, with its terms in the order of time. A term holds from its time
 * until the next one starts. The first can hold from when the BOOKING was made: where it is
 * the only one, it holds at any time. A term states a cost, or states none, or says that the
 * seller accepts none. A cost is one amount for each currency, and nothing is added up.
 */
function termsOf(booking) {
  return KINDS_OF_TERMS.flatMap((kind) => {
    const terms = booking.terms[kind];
    if (!terms.length) return [];
    const always = terms.length === 1 && terms[0].since === null;
    const says = (term) => (term.refused ? NONE_ACCEPTED[kind] : term.costs === null ? "the FILE does not say" : term.costs.length ? listed(term.costs.map(amountOf)) : "nothing");
    const parts = terms.map((term) => (always ? says(term) : `${term.since === null ? "at first" : `from ${term.since}`}, ${says(term)}`));
    return [`${COSTS[kind]}${always ? " at any time" : ""}${APART[kind]}: ${parts.join("; ")}.`];
  });
}

/** What the report says holds at the time now, for each kind of terms: a cost, that the FILE states none, or that the seller accepts none. */
const NOW = {
  cancelling: { costs: (cost) => `cancelling costs ${cost} now`, unsaid: "the FILE does not say what cancelling costs now" },
  changing: { costs: (cost) => `the fee for a change is ${cost} now, apart from any difference in price`, unsaid: "the FILE does not state the fee for a change now" },
};

/**
 * What the report says that cancelling a BOOKING and changing it cost at the time now, for
 * each kind of terms that the BOOKING dates. Which term holds now is for the COMPILER to
 * say, so the card says it only where the report does. One term that holds at any time says
 * its cost already.
 */
function nowOf(booking, held) {
  return KINDS_OF_TERMS.flatMap((kind) => {
    const terms = booking.terms[kind];
    const row = held[kind].get(booking.id);
    if (!terms.length || (terms.length === 1 && terms[0].since === null) || row === undefined) return [];
    const says = row.refused ? `${NONE_ACCEPTED[kind]} now` : row.costs === null ? NOW[kind].unsaid : NOW[kind].costs(row.costs.length ? listed(row.costs.map(amountOf)) : "nothing");
    return [`The report says that ${says}.`];
  });
}

export function rights(trip, report = null, stated = null) {
  const none = { says: "", clash: false, asked: false, rights: [] };
  if (trip === null) return none;
  const person = new Map(trip.persons.map((each) => [each.id, each.name]));
  const needs = needsARight(trip);
  const marked = marksBy(report, stated);
  const uses = usesIn(report);
  const pots = new Map(trip.budgets.map((each) => [each.id, each.name]));
  const capped = trip.budgets.some((budget) => budget.caps.length > 0);
  // What a BOOKING paid, as the report words it. Where the FILE has a cap, a BOOKING that
  // states no payment says so: then no cap can be shown to hold.
  const paymentOf = (booking) => {
    if (booking.paid === null) return capped ? "; it states no payment" : "";
    return `; its payment: ${paidOf(
      booking.paid,
      (id) => person.get(id),
      (id) => pots.get(id),
    )}`;
  };
  // A place that the plan buys only if its OPTION turns out to need a right.
  const ifNeeded = (option, offer) => toBuyIn(report).some((buy) => buy.option === option && buy.offer === offer && buy.only_if_needed === true);
  // Those who use one right for one OPTION in the plan, in the FILE's order of PERSONs.
  const usersOf = (option, by) => trip.persons.filter(({ id }) => uses.some((use) => use.option === option && use.by === by && use.person === id)).map(({ id }) => id);
  // The OBJECTs that one BOOKING covers for one OPTION in the plan, in the FILE's order.
  const carried = carriedIn(report);
  const thing = new Map(trip.objects.map((each) => [each.id, each.name]));
  const coveredBy = (option, by) => trip.objects.filter(({ id }) => carried.some((each) => each.object === id && each.covers.some((use) => use.option === option && use.booking === by))).map(({ id }) => id);
  // The OBJECTs that a FACT says an OPTION needs a right for, each with that FACT.
  const needing = (option) => trip.objects.flatMap((each) => each.rights.filter((right) => right.option === option && right.needed).map((right) => ({ id: each.id, name: each.name, record: right.record })));
  // The OFFERs that have expired by the time now that the FILE states.
  const expired = expiredIn(trip);
  // What the report says that cancelling and changing cost at the time now.
  const held = costsNowIn(report);
  // The OBJECTs of which a FACT says that the FILE lists every right to an OPTION that
  // covers them, each with that FACT and the OFFERs that it names.
  const closedFor = (option) => trip.objects.flatMap((each) => each.rights_closed.filter((closed) => closed.option === option).map((closed) => ({ name: closed.called, record: closed.record, offers: closed.offers })));
  // The OBJECTs that take a place of one OFFER for one OPTION in the plan, in the FILE's
  // order: those whose right is needed, and those whose right might be needed. Nobody
  // knows whether the OPTION needs one, or whether the OBJECT is in it.
  const placedBy = (option, offer, ifNeeded) => {
    const taken = toBuyIn(report).filter((buy) => buy.option === option && buy.offer === offer && Array.isArray(buy.objects) && (buy.only_if_needed === true) === ifNeeded);
    return trip.objects.filter(({ id }) => taken.some((buy) => buy.objects.includes(id))).map(({ id }) => id);
  };
  const shown = trip.rights
    .filter((each) => each.needs?.needed === true || each.bookings.length || each.offers.length || each.complete !== null || needing(each.option).length || closedFor(each.option).length)
    .map((each) => ({
      option: each.option,
      name: each.name,
      needs: needs(each.option).says,
      // The OBJECTs that it needs a right for, where a FACT says so.
      things: needing(each.option).length ? `It needs a right for ${listed(needing(each.option).map((thing) => thing.name))}.` : null,
      bookings: each.bookings.map((booking) => {
        const users = [...usersOf(each.option, booking.id), ...coveredBy(each.option, booking.id)];
        // PERSONs and OBJECTs in one list, each by the name that the view sends for that
        // list. A report can name somebody whom the BOOKING does not cover: they have their
        // own name.
        const called = (ids) => listed(ids.map((id) => booking.names[id] ?? person.get(id) ?? thing.get(id)));
        return {
          id: booking.id,
          name: booking.id,
          says: `a BOOKING that covers ${called([...booking.covers, ...booking.objects])}${paymentOf(booking)}`,
          // What it states for cancelling it and for changing it, as far as the FILE says.
          terms: termsOf(booking),
          // What the report says holds of those at the time now.
          now: nowOf(booking, held),
          uses: !trip.itinerary ? null : users.length ? `In the plan: ${called(users)} ${users.length === 1 ? "uses" : "use"} it.` : "In the plan: nobody uses it.",
          ...marked([booking.id], (need) => need.booking === booking.id, "The report names this BOOKING in what the FILE does not say."),
        };
      }),
      offers: each.offers.map((offer) => {
        const users = usersOf(each.option, offer.id).map((id) => person.get(id));
        const takes = `In the plan: ${listed(users)} ${users.length === 1 ? "takes" : "each take"} a place of it${ifNeeded(each.option, offer.id) ? ", if the OPTION needs a right" : ""}.`;
        const buys = (need) => Array.isArray(need.buys) && need.buys.some((buy) => buy !== null && typeof buy === "object" && buy.offer === offer.id);
        // A place for an OBJECT: nobody takes it, so the page names the OBJECT that it
        // covers. A name can be of one thing or of several, so no verb follows it.
        const covering = (ids) => `a place of it covers ${ids.length === 1 ? "" : "each of "}${listed(ids.map((id) => offer.names[id] ?? thing.get(id)))}`;
        const sure = placedBy(each.option, offer.id, false);
        const maybe = placedBy(each.option, offer.id, true);
        const covers = [...(sure.length ? [`In the plan: ${covering(sure)}.`] : []), ...(maybe.length ? [`In the plan: ${covering(maybe)}, if a right is needed there.`] : [])].join(" ");
        const nobody = offer.objects.length ? "In the plan: no place of it is taken." : "In the plan: nobody takes a place of it.";
        return {
          id: offer.id,
          name: offer.id,
          says: offerOf(offer),
          uses: !trip.itinerary ? null : offer.objects.length && covers ? covers : users.length ? takes : nobody,
          ...marked([offer.id], (need) => need.offer === offer.id || buys(need), "The report names this OFFER in what the FILE does not say."),
        };
      }),
      whole: wholeOf(each.complete, expired),
      // What the FILE says of the rights to it for an OBJECT, as the report words it.
      closed: closedFor(each.option).map((thing) => `The FILE lists every right to it that covers ${thing.name}: nobody on the trip holds another or can get one${thing.offers.length ? `, except from ${listed(withExpired(thing.offers, expired))}` : ""}.`),
      // Its own records: the FACT about whether people need a right, the FACT that the
      // FILE lists every right for a PERSON, each FACT that it needs a right for an OBJECT,
      // and each FACT that the FILE lists every right for an OBJECT.
      ...marked(
        [
          ...(each.needs === null ? [] : [each.needs.record]),
          ...(each.complete === null ? [] : [each.complete.record]),
          ...needing(each.option).map((thing) => thing.record),
          ...closedFor(each.option).map((thing) => thing.record),
        ],
        (need) => ABOUT_RIGHTS.has(need.what) && optionsOf(need).includes(each.option),
        "The report names the rights to this OPTION in what the FILE does not say.",
      ),
    }));
  if (!shown.length) return none;
  const all = shown.flatMap((each) => [each, ...each.bookings, ...each.offers]);
  const clash = all.some((each) => each.clash.length > 0);
  const asked = all.some((each) => each.cases.length > 0);
  // Which term of a BOOKING holds, and whether an OFFER has expired, turns on the time now.
  // So the part says which time the FILE states, and says so where it states none.
  const dated = trip.rights.some((each) => each.bookings.some((booking) => KINDS_OF_TERMS.some((kind) => booking.terms[kind].length)) || each.offers.some((offer) => offer.until !== null));
  const now = trip.now !== null ? ` The FILE states the time now: ${trip.now.at}.` : dated ? " The FILE does not state the time now." : "";
  const says =
    "The BOOKINGs and the OFFERs of the FILE, each under the OPTION that it is for." +
    now +
    (clash ? " A red edge marks what the report names among what rules out every plan." : "") +
    (asked ? " A yellow edge marks what the report names in what the FILE does not say." : "");
  return { says, clash, asked, rights: shown };
}
