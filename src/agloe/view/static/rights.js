// The rights to the OPTIONs of a FILE, as the page shows them. There is no page in here, so
// the tests run this as it is.
//
// The view sends what the FILE says of the rights to each OPTION: whether a PERSON needs a
// right to take part, each BOOKING with the PERSONs and the OBJECTs it covers, the name to
// show for each of them in one list, and what it paid, each OFFER
// with its places and the price of one, and the FACT that the FILE lists every right to the
// OPTION. This puts
// them in words, as the report words them. Where the report shows a plan, it says who uses
// each BOOKING and who takes a place of each OFFER in that plan, as the report states it. It
// marks what the report names: the records that rule out every plan, and the cases in which a
// trip that depends on something works.
//
// Nothing here judges a TRIP. Whether everybody who takes part has a right is for the
// COMPILER to say: the page names who uses a right only where the report does.

import { carriedIn, either, listed, marksBy, optionsOf, toBuyIn, usesIn } from "./named.js";
import { paidOf } from "./money.js";
import { needsARight } from "./who.js";

/** What a case of a report can need that is about the rights to an OPTION, for a PERSON or for an OBJECT. */
const ABOUT_RIGHTS = new Set(["another right", "needs no right", "price", "funding", "charged", "another right for", "needs no right for"]);

/** An OFFER, as the report words it: its places, and what one costs. */
function offerOf(offer) {
  const places = offer.places === 1 ? "1 place" : `${offer.places} places`;
  const price = offer.price === null ? "; nobody knows the price" : `, for ${offer.price.amount} ${offer.price.currency}${offer.places > 1 ? " each" : ""}`;
  return `an OFFER with ${places} that can still be bought${price}`;
}

/** Whether the BOOKINGs and the OFFERs under an OPTION are all the rights to it, as the report words it. */
function wholeOf(complete, things) {
  if (complete === null) return "Another right to it may exist: the FILE does not say that these are all.";
  const except = complete.offers.length ? `, except from ${listed(complete.offers)}` : "";
  // That FACT is about the PERSONs who take part. A right for an OBJECT is another matter.
  const scope = things.length ? `; that is about the PERSONs who take part, and it says nothing of a right for ${listed(things.map(either), "or")}` : "";
  return `The FILE lists every right to it: nobody on the trip holds another or can get one${except}${scope}.`;
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
  // The OBJECTs that an OPTION needs a right for, or might: a FACT says that it does, or no
  // FACT says, and none says that the FILE states every OPTION that does.
  const mightNeed = (option) => trip.objects.filter((each) => each.rights.find((right) => right.option === option)?.needed ?? each.rights_complete === null).map((each) => each.name);
  const shown = trip.rights
    .filter((each) => each.needs?.needed === true || each.bookings.length || each.offers.length || each.complete !== null || needing(each.option).length)
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
          uses: !trip.itinerary ? null : users.length ? `In the plan: ${called(users)} ${users.length === 1 ? "uses" : "use"} it.` : "In the plan: nobody uses it.",
          ...marked([booking.id], (need) => need.booking === booking.id, "The report names this BOOKING in what the FILE does not say."),
        };
      }),
      offers: each.offers.map((offer) => {
        const users = usersOf(each.option, offer.id).map((id) => person.get(id));
        const takes = `In the plan: ${listed(users)} ${users.length === 1 ? "takes" : "each take"} a place of it${ifNeeded(each.option, offer.id) ? ", if the OPTION needs a right" : ""}.`;
        const buys = (need) => Array.isArray(need.buys) && need.buys.some((buy) => buy !== null && typeof buy === "object" && buy.offer === offer.id);
        return {
          id: offer.id,
          name: offer.id,
          says: offerOf(offer),
          uses: !trip.itinerary ? null : users.length ? takes : "In the plan: nobody takes a place of it.",
          ...marked([offer.id], (need) => need.offer === offer.id || buys(need), "The report names this OFFER in what the FILE does not say."),
        };
      }),
      whole: wholeOf(each.complete, mightNeed(each.option)),
      // Its own records: the FACT about whether people need a right, the FACT that the
      // FILE lists every right, and each FACT that it needs a right for an OBJECT.
      ...marked(
        [...(each.needs === null ? [] : [each.needs.record]), ...(each.complete === null ? [] : [each.complete.record]), ...needing(each.option).map((thing) => thing.record)],
        (need) => ABOUT_RIGHTS.has(need.what) && optionsOf(need).includes(each.option),
        "The report names the rights to this OPTION in what the FILE does not say.",
      ),
    }));
  if (!shown.length) return none;
  const all = shown.flatMap((each) => [each, ...each.bookings, ...each.offers]);
  const clash = all.some((each) => each.clash.length > 0);
  const asked = all.some((each) => each.cases.length > 0);
  const says =
    "The BOOKINGs and the OFFERs of the FILE, each under the OPTION that it gives a right to." +
    (clash ? " A red edge marks what the report names among what rules out every plan." : "") +
    (asked ? " A yellow edge marks what the report names in what the FILE does not say." : "");
  return { says, clash, asked, rights: shown };
}
