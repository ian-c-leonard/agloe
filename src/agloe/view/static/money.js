// How the page writes an amount of money and a payment: as the report does. There is no page
// in here, so the tests run this as it is.
//
// The view sends each amount as the FILE writes it, with its currency. Nothing here adds up
// money or changes a currency: it puts in words what it is sent.

/** An amount of money as the report writes it: 32.00 USD. */
export function amountOf(money) {
  return `${money.amount} ${money.currency}`;
}

/**
 * What a BOOKING paid, as the report writes it: the amount, then who paid and the BUDGET that
 * the money came from, where the BOOKING names them. A payment of nothing says "nothing".
 * `person` and `budget` give the name to show for an id. Leave `budget` out where the words
 * stand under their BUDGET.
 */
export function paidOf(paid, person, budget = null) {
  const parts = [Number(paid.amount) === 0 ? "nothing" : amountOf(paid)];
  if (paid.by !== null) parts.push(`paid by ${person(paid.by)}`);
  if (paid.budget !== null && budget !== null) parts.push(`from ${budget(paid.budget)}`);
  return parts.join(", ");
}
