// The rights to the OPTIONs of a FILE, as the page shows them. There is no page in here, so
// the tests run this as it is.
//
// The view sends what the FILE says of the rights to each OPTION: whether a PERSON needs a
// right to take part, each BOOKING with the PERSONs it covers, each OFFER with its places and
// the price of one, and the FACT that the FILE lists every right to the OPTION. This puts
// them in words, as the report words them. Where the report shows a plan, it says who uses
// each BOOKING and who takes a place of each OFFER in that plan, as the report states it. It
// marks what the report names: the records that rule out every plan, and the cases in which a
// trip that depends on something works.
//
// Nothing here judges a TRIP. Whether everybody who takes part has a right is for the
// COMPILER to say: the page names who uses a right only where the report does.

import { listed, marksBy, optionsOf, usesIn } from "./named.js";
import { needsARight } from "./who.js";

/** What a case of a report can need that is about the rights to an OPTION. */
const ABOUT_RIGHTS = new Set(["another right", "needs no right", "price", "funding", "charged"]);

/** An OFFER, as the report words it: its places, and what one costs. */
function offerOf(offer) {
  const places = offer.places === 1 ? "1 place" : `${offer.places} places`;
  const price = offer.price === null ? "; nobody knows the price" : `, for ${offer.price.amount} ${offer.price.currency}${offer.places > 1 ? " each" : ""}`;
  return `an OFFER with ${places} that can still be bought${price}`;
}

/** Whether the BOOKINGs and the OFFERs under an OPTION are all the rights to it, as the report words it. */
function wholeOf(complete) {
  if (complete === null) return "Another right to it may exist: the FILE does not say that these are all.";
  return `The FILE lists every right to it: nobody on the trip holds another or can get one${complete.offers.length ? `, except from ${listed(complete.offers)}` : ""}.`;
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
 * report shows no plan).
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
  // Those who use one right for one OPTION in the plan, in the FILE's order of PERSONs.
  const usersOf = (option, by) => trip.persons.filter(({ id }) => uses.some((use) => use.option === option && use.by === by && use.person === id)).map(({ name }) => name);
  const shown = trip.rights
    .filter((each) => each.needs?.needed === true || each.bookings.length || each.offers.length || each.complete !== null)
    .map((each) => ({
      option: each.option,
      name: each.name,
      needs: needs(each.option).says,
      bookings: each.bookings.map((booking) => {
        const users = usersOf(each.option, booking.id);
        return {
          id: booking.id,
          name: booking.id,
          says: `a BOOKING that covers ${listed(booking.covers.map((id) => person.get(id)))}`,
          uses: !trip.itinerary ? null : users.length ? `In the plan: ${listed(users)} ${users.length === 1 ? "uses" : "use"} it.` : "In the plan: nobody uses it.",
          ...marked([booking.id], (need) => need.booking === booking.id, "The report names this BOOKING in what the FILE does not say."),
        };
      }),
      offers: each.offers.map((offer) => {
        const users = usersOf(each.option, offer.id);
        const buys = (need) => Array.isArray(need.buys) && need.buys.some((buy) => buy !== null && typeof buy === "object" && buy.offer === offer.id);
        return {
          id: offer.id,
          name: offer.id,
          says: offerOf(offer),
          uses: !trip.itinerary ? null : users.length ? `In the plan: ${listed(users)} ${users.length === 1 ? "takes" : "each take"} a place of it.` : "In the plan: nobody takes a place of it.",
          ...marked([offer.id], (need) => need.offer === offer.id || buys(need), "The report names this OFFER in what the FILE does not say."),
        };
      }),
      whole: wholeOf(each.complete),
      // Its own records: the FACT about whether people need a right, and the FACT that the
      // FILE lists every right.
      ...marked(
        [...(each.needs === null ? [] : [each.needs.record]), ...(each.complete === null ? [] : [each.complete.record])],
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
