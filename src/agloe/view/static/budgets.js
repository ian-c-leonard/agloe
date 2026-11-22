// The BUDGETs of a FILE, as the page shows them. There is no page in here, so the tests run
// this as it is.
//
// The view sends the BUDGETs with each report: the PERSONs who may draw on each, the
// currencies it holds, and each cap on what the TRIP spends from it. It sends what each
// BOOKING paid, with the BUDGET that the money came from, where the BOOKING names one. This
// puts them in words, as the report words them. It marks what the report names: the records
// that rule out every plan.
//
// Nothing here judges a TRIP, and nothing here adds up money. Whether a cap holds is for the
// COMPILER to say.

import { listed, marksBy } from "./named.js";
import { amountOf, paidOf } from "./money.js";

/**
 * What the page shows of the BUDGETs of a TRIP as the view sends it, or of no TRIP where the
 * view sends none.
 *
 * Each BUDGET has its name, who may draw on it and what it holds (`holds`), its `caps`, and
 * the `payments` that BOOKINGs state from it. A cap is named by its id, and a payment by the
 * id of its BOOKING. Each has what the FILE says of it (`says`). `whole` says that the FILE
 * sets no cap on the BUDGET, and is null where it sets one. `unnamed` holds the payments that
 * name no BUDGET.
 *
 * `report` is the report as JSON, where the page has one. `clash` on a cap or on a payment
 * holds its `records` that the report names as ruling out every plan, and `finds` says so.
 * `cases` holds the cases that name the BOOKING of a payment among what the FILE does not
 * say, as their places in `missing` of the report, and `asks` holds what the report says of
 * them. `stated` holds the words of the report for those cases, as lines.js finds them.
 * `clash` and `asked` on the whole say that something here is marked so.
 */
export function budgets(trip, report = null, stated = null) {
  if (trip === null || !trip.budgets.length) return { says: "", clash: false, asked: false, budgets: [], unnamed: [] };
  const people = new Map(trip.persons.map((each) => [each.id, each.name]));
  const person = (id) => people.get(id);
  const marked = marksBy(report, stated);
  const bookings = trip.rights.flatMap((each) => each.bookings).filter((booking) => booking.paid !== null);
  const payment = (booking) => ({
    id: booking.id,
    name: booking.id,
    says: paidOf(booking.paid, person),
    ...marked([booking.id], (need) => need.booking === booking.id, "The report names this BOOKING in what the FILE does not say."),
  });
  const shown = trip.budgets.map((budget) => {
    const who = budget.persons.map(person);
    return {
      id: budget.id,
      name: budget.name,
      // The report says it so: for Alex and Sam; it holds USD.
      holds: `${who.length ? `For ${listed(who)}` : "It lists no PERSON"}. It holds ${listed(budget.currencies)}.`,
      caps: budget.caps.map((cap) => ({
        id: cap.id,
        name: cap.id,
        says: `the TRIP spends at most ${amountOf(cap.limit)} from it`,
        ...marked([cap.id], () => false, ""),
      })),
      payments: bookings.filter((booking) => booking.paid.budget === budget.id).map(payment),
      whole: budget.caps.length ? null : "The FILE sets no cap on what the TRIP spends from it.",
    };
  });
  const unnamed = bookings.filter((booking) => booking.paid.budget === null).map(payment);
  const all = [...shown.flatMap((budget) => [...budget.caps, ...budget.payments]), ...unnamed];
  const clash = all.some((each) => each.clash.length > 0);
  const asked = all.some((each) => each.cases.length > 0);
  const says =
    "The BUDGETs of the FILE, each with who may draw on it, the caps on it, and what the BOOKINGs state that they paid from it." +
    (clash ? " A red edge marks what the report names among what rules out every plan." : "") +
    (asked ? " A yellow edge marks what the report names in what the FILE does not say." : "");
  return { says, clash, asked, budgets: shown, unnamed };
}
