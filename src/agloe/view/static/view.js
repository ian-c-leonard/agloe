// The page of the view: it listens to the view and shows what state.js says.
//
// The answer and the report need nothing but state.js. The calendar is loaded beside them, so
// that a calendar that fails to load or to draw leaves the answer and the report on the page.
// So is what ties each line of the report to the step or the record that it is about, and so
// are the strip above the calendar, and each part of the page that shows what the FILE holds:
// its WANTs and its OPTIONs.
import { after, says, start } from "./state.js";

const PER_MINUTE = 0.8; // pixels down the calendar for each minute
const HUES = 6; // the colours that tell the PERSONs apart, in view.css
const SMALLEST = 3; // pixels: the least height of a mark
const TICK = 7; // pixels: the height of the tick for a WAY that takes next to no time
const BESIDE = 18; // pixels from one tick to the next where several are at one place
const EDGES = 80; // pixels of the strip that are not its rows: the names, the padding and the edge
const NARROWEST = 40; // pixels: the least room for the rows of a strip

const part = (id) => document.getElementById(id);
let state = start();
let lay = null; // what lays a calendar out, once the page has loaded it: false where it cannot
let tie = null; // what ties the lines of a report to steps and records, once the page has loaded it
let turn = null; // what turns a calendar into the strip above it, once the page has loaded it
let onStrip = null; // the calendar that the strip on the page is of
let stripRoom = 0; // pixels: how wide the page was when the strip was laid out
let drawn; // the TRIP that the calendar on the page is of
let written = []; // what the report on the page was written from: its words, and what its lines are tied to
let revealedFor = null; // the drawing that the pointer is on, by what it is of and tied to: the report has moved for it

function made(tag, className, text = "") {
  return Object.assign(document.createElement(tag), { className, textContent: text });
}

/** The hours down the left of the calendar: 2 pm, noon, midnight. */
function hourName(minute) {
  const hour = (minute / 60) % 24;
  return hour === 0 ? "midnight" : hour === 12 ? "noon" : `${hour % 12} ${hour < 12 ? "am" : "pm"}`;
}

/** What a mark says to a pointer that rests on it. */
function wordsOf(mark) {
  const when = mark.late ? `${mark.when}, ${mark.late}` : mark.when;
  return [mark.name, when, mark.where, mark.who, mark.lock ?? "A WAY in the plan of the report.", ...(mark.finds ? [mark.finds] : []), ...mark.warns, ...mark.asks].join("\n");
}

/** The edges of a thing that the report names: red, or yellow. */
function edges(each) {
  return `${each.clash.length ? " clash" : ""}${each.cases.length ? " asked" : ""}`;
}

/** What the report says of a thing that it names, for the pointer that rests on it. */
function marks(each) {
  return [...(each.finds ? [each.finds] : []), ...each.asks];
}

/** How a mark looks, on the calendar and on the strip: by what the view and the report say of its step. */
function looksOf(mark) {
  return `${mark.state}${mark.begins ? "" : " goes-on"}${mark.ends ? "" : " no-end"}${mark.brief ? " brief" : ""}${mark.clash.length ? " clash" : ""}${mark.warns.length ? " warned" : ""}${mark.asks.length ? " asked" : ""}`;
}

/**
 * What a step is tied to in the report: the records that are about it, and the cases in which
 * the report says the trip works that name it. A case is tied like a record, under a name that
 * no record can have.
 */
function tiesOf(step) {
  return [...step.records, ...step.cases.map((at) => `case:${at}`)];
}

/**
 * What a row for an OPTION is a drawing of: the step of the TRIP that the OPTION is, by its
 * number, or the OPTION itself where the calendar holds no step for it. A name with a colon is
 * the name of no step.
 */
function drawingOf(option, id) {
  return option.step !== null ? String(option.step) : `option:${id}`;
}

/**
 * The name of a PERSON over their column of the calendar, or beside their row of the strip,
 * in the colour of that PERSON. It is a drawing of the PERSON, like their row among the
 * PERSONs, so pointing at one lights up the others.
 */
function nameOf(person, n, kind) {
  const name = Object.assign(made("span", `${kind}p${n % HUES}`, person.name), { title: person.name });
  name.dataset.of = `person:${person.id}`;
  return name;
}

/**
 * What a row or an entry for a WAY is a drawing of: each step of the TRIP in which somebody
 * takes it, by its number, or the WAY itself, by its id, where nobody takes it.
 */
function drawingOfAWay(steps, id) {
  return steps.length ? steps.join(" ") : `way:${id}`;
}

/**
 * One mark of the calendar, put on its day: a block for an OPTION, or a line down each PERSON's
 * column for a WAY. The name of a WAY stands beside the line of the first PERSON who takes it,
 * as far as its day has room.
 */
function put(body, mark, index, people, open, ticks) {
  const box = made("div", `mark ${looksOf(mark)}`);
  Object.assign(box.dataset, { of: mark.step, records: tiesOf(mark).join(" "), mark: index });
  const columns = mark.last - mark.first + 1;
  const when = mark.late ? `${mark.when}, ${mark.late}` : mark.when;
  // A mark is never smaller than the eye can find, and never outside the hours of its column.
  // The tick of a WAY that takes next to no time sits across the moment it happens at.
  const room = Math.max((open.bottom - open.top) * PER_MINUTE, 1);
  const height = Math.min(mark.brief ? TICK : Math.max(mark.height * PER_MINUTE, SMALLEST), room);
  const least = open.top * PER_MINUTE;
  const top = Math.min(Math.max(mark.top * PER_MINUTE - (mark.brief ? TICK / 2 : 0), least), least + room - height);
  box.style.left = `${((mark.first + mark.lane / mark.lanes) / people) * 100}%`;
  box.style.width = `${(columns / mark.lanes / people) * 100}%`;
  box.style.top = `${top}px`;
  box.style.height = `${height}px`;
  box.title = wordsOf(mark);
  const block = made("div", "block");
  const stripes = made("div", "stripes");
  for (let column = mark.first; column <= mark.last; column += 1) {
    const stripe = made("i", `stripe p${column % HUES}`);
    if (mark.brief) {
      // Only the tick itself answers the pointer, so that what it sits on can be reached too.
      // Ticks that would lie on each other in one PERSON's column stand beside each other,
      // as far as the column has room.
      const there = ticks.get(column) ?? ticks.set(column, []).get(column);
      const taken = new Set(there.filter((other) => Math.abs(other.top - top) < TICK).map((other) => other.place));
      let place = 0;
      while (taken.has(place)) place += 1;
      there.push({ top, place });
      const tick = Object.assign(made("b", "tick"), { title: box.title });
      tick.style.marginLeft = `${4 + Math.min(place, 2) * BESIDE}px`;
      stripe.append(tick);
    }
    stripes.append(stripe);
  }
  block.append(stripes);
  if (mark.kind === "option") block.append(made("b", "mark-name", mark.name), made("span", "mark-more", `${when} · ${mark.where}`));
  box.append(block);
  body.append(box);
  if (mark.kind === "option" || !mark.named) return;
  // The name is part of the mark: pointing at it is pointing at the WAY.
  const name = Object.assign(made("span", "way-name", mark.name), { title: box.title });
  Object.assign(name.dataset, box.dataset);
  name.style.left = `calc(${((mark.first + 0.5) / people) * 100}% + 6px)`;
  name.style.top = `${(mark.top + mark.height / 2) * PER_MINUTE}px`;
  body.append(name);
}

function draw(laid) {
  const people = laid.persons.length;
  const tall = (laid.hours.to - laid.hours.from) * PER_MINUTE;
  const grid = part("calendar");
  grid.style.setProperty("--hour", `${60 * PER_MINUTE}px`);
  grid.replaceChildren();
  if (laid.days.length) {
    const hours = made("div", "hours");
    hours.style.height = `${tall}px`;
    for (let minute = laid.hours.from; minute <= laid.hours.to; minute += 60) {
      const name = made("span", "", hourName(minute));
      name.style.top = `${(minute - laid.hours.from) * PER_MINUTE}px`;
      hours.append(name);
    }
    grid.append(hours);
  }
  // The days are level with each other: where one has words above or below it, all have room.
  const above = laid.days.some((day) => day.bounds.some((bound) => bound.edge === "starts"));
  const below = laid.days.some((day) => day.bounds.some((bound) => bound.edge === "ends"));
  grid.classList.toggle("with-starts", above);
  for (const day of laid.days) {
    const column = made("div", "day");
    column.style.setProperty("--people", Math.max(people, 1));
    const heads = made("div", "people");
    laid.persons.forEach((person, n) => heads.append(nameOf(person, n, "person ")));
    const body = made("div", "day-body");
    body.style.height = `${tall}px`;
    for (const shut of day.shut) {
      // The hours of this column that its clocks do not show.
      const band = Object.assign(made("div", "shut"), { title: "The clocks do not show these hours in this column." });
      band.style.top = `${shut.top * PER_MINUTE}px`;
      band.style.height = `${shut.height * PER_MINUTE}px`;
      body.append(band);
    }
    const ticks = new Map();
    day.marks.forEach((mark, index) => put(body, mark, index, people, day.open, ticks));
    // Where the TRIP starts and where it ends: a line across the day. Its words stand above
    // the day for the start and below it for the end, so that they cover no step.
    const words = { starts: made("div", "bound-says"), ends: made("div", "bound-says") };
    for (const bound of day.bounds) {
      const line = made("div", bound.clash ? "bound clash" : "bound");
      line.style.top = `${bound.top * PER_MINUTE}px`;
      line.dataset.record = words[bound.edge].dataset.record = bound.record;
      body.append(line);
      Object.assign(words[bound.edge], { textContent: bound.says, title: bound.says });
      words[bound.edge].classList.toggle("clash", bound.clash);
    }
    column.append(Object.assign(made("h3", "day-name", day.name), { title: day.name }), heads);
    if (above) column.append(words.starts);
    column.append(body);
    if (below) column.append(words.ends);
    grid.append(column);
  }
  grid.hidden = !laid.days.length;
  part("calendar-key").hidden = !laid.days.length;
  // A calendar of what is LOCKed holds nothing that is only in a plan, and no WAY.
  part("calendar-key").classList.toggle("only-locks", !laid.itinerary);
  part("calendar-key").classList.toggle("with-clash", laid.clash);
  part("calendar-key").classList.toggle("with-warnings", laid.warned);
  part("calendar-key").classList.toggle("with-asks", laid.asked);
  part("calendar-says").textContent = laid.says;
  // The steps with no time, each marked where the report names what is about it.
  const untimed = laid.untimed.flatMap((step, n) => {
    const name = Object.assign(made("span", `${step.clash.length ? "clash" : ""}${step.asks.length ? " asked" : ""}`, `${step.name} (${step.who})`), { title: [...(step.finds ? [step.finds] : []), ...step.asks].join("\n") });
    // It is a step of the TRIP: pointing at it lights up that step, and no other.
    Object.assign(name.dataset, { of: step.step, records: tiesOf(step).join(" ") });
    return n ? [", ", name] : [name];
  });
  part("calendar-untimed").replaceChildren("The FILE gives no time for these LOCKed OPTIONs: ", ...untimed, ".");
  part("calendar-untimed").hidden = !laid.untimed.length;
}

/**
 * One mark of the strip. It stands for one mark of the calendar, or for several that are too
 * close together to show apart at this width, and then it says so.
 */
function bar(mark, people) {
  const [one] = mark.of;
  const several = mark.of.length > 1;
  // A mark for several has the edges of each of them: it is dashed where one of them does not
  // start there, and fades where one of them may not end there.
  const any = (holds) => mark.of.some(holds);
  const looks = several ? `several${any((each) => !each.begins) ? " goes-on" : ""}${any((each) => !each.ends) ? " no-end" : ""}${any((each) => each.clash.length) ? " clash" : ""}${any((each) => each.warns.length) ? " warned" : ""}${any((each) => each.asks.length) ? " asked" : ""}` : looksOf(one);
  const box = made("div", `bar ${looks}${mark.small ? " small" : ""}`);
  // It names each of them, with its times and with what the report says of it.
  const said = (each) => [`${each.name}, ${each.late ? `${each.when}, ${each.late}` : each.when}`, ...[...(each.finds ? [each.finds] : []), ...each.warns, ...each.asks].map((words) => `    ${words}`)];
  box.title = several ? [`${mark.of.length} steps too close together to show apart at this width:`, ...mark.of.flatMap(said)].join("\n") : wordsOf(one);
  // A click goes to the first of the marks that it stands for.
  Object.assign(box.dataset, {
    of: [...new Set(mark.of.map((each) => each.step))].join(" "),
    records: [...new Set(mark.of.flatMap(tiesOf))].join(" "),
    day: one.day,
    mark: one.index,
  });
  box.style.left = `${mark.x}px`;
  box.style.width = `${mark.w}px`;
  box.style.top = `${((mark.first + mark.lane / mark.lanes) / people) * 100}%`;
  box.style.height = `${((mark.last - mark.first + 1) / mark.lanes / people) * 100}%`;
  // A block for an OPTION, with its name where there is room. A line along each PERSON's row
  // for a WAY, or a tick for a WAY that is too short to draw. Two ticks, one above the other,
  // for several marks. Only a tick itself answers the pointer, so that what it sits on can be
  // reached too.
  if (several) box.append(Object.assign(made("i", `bar-several p${mark.first % HUES}`), { title: box.title }));
  else if (one.kind === "option") box.append(made("i", "bar-block"), made("b", "bar-name", one.name));
  else if (mark.small) box.append(Object.assign(made("i", `bar-tick p${mark.first % HUES}`), { title: box.title }));
  else for (let row = mark.first; row <= mark.last; row += 1) box.append(made("i", `bar-line p${row % HUES}`));
  return box;
}

/**
 * The strip above the calendar: all its days, with a row for each PERSON and time from left to
 * right. It holds the marks of the calendar. So pointing at a step on it lights up the same
 * step below, and what the report says of it. A calendar of one day has no strip.
 */
function drawStrip(laid) {
  onStrip = laid;
  const box = part("strip");
  box.replaceChildren();
  box.hidden = part("strip-says").hidden = true;
  // The strip is laid out in the pixels that the page has for its rows. A page with next to
  // none has no strip.
  stripRoom = part("calendar-part").clientWidth;
  const strip = turn && laid && stripRoom - EDGES >= NARROWEST ? turn(laid, stripRoom - EDGES) : null;
  if (strip === null) return;
  box.hidden = part("strip-says").hidden = false;
  const people = Math.max(strip.persons.length, 1);
  box.style.setProperty("--people", people);
  box.style.setProperty("--row", `${strip.row}px`);
  const names = made("div", "strip-people");
  strip.persons.forEach((person, n) => names.append(nameOf(person, n, "")));
  const days = made("div", "strip-days");
  const rows = made("div", "strip-rows");
  days.style.width = rows.style.width = `${strip.wide}px`;
  for (const day of strip.days) {
    if (!day.w) continue;
    const name = Object.assign(made("span", "strip-day", day.short), { title: day.name });
    name.style.left = `${day.x}px`;
    name.style.width = `${day.w}px`;
    days.append(name);
    if (!day.x) continue;
    // Where the strip leaves hours out before a day, the line between the days is double.
    const edge = made("i", day.gap ? "strip-edge gap" : "strip-edge");
    edge.style.left = `${day.x}px`;
    rows.append(edge);
  }
  for (const mark of strip.marks) rows.append(bar(mark, people));
  for (const bound of strip.bounds) {
    const line = Object.assign(made("i", bound.clash ? "strip-bound clash" : "strip-bound"), { title: bound.says });
    line.style.left = `${bound.x}px`;
    line.dataset.record = bound.record;
    rows.append(line);
  }
  box.append(made("span", ""), days, names, rows);
  part("strip-says").textContent = strip.says;
}

/**
 * An entry on a card: an OPTION on the card of a WANT or of a CAPABILITY, or a BOOKING or an
 * OFFER on the card of the rights to an OPTION. It has its name, what the FILE says of it, and
 * who is in it or uses it, where the page says so. `of` says what the entry is a drawing of,
 * and it is tied to its one FACT. `plain` says that the entry is drawn full: the OPTION
 * SATISFIES the WANT or requires the CAPABILITY, or the BOOKING secures a right. `more` holds
 * what the page says under that: who takes part, and what the report says of a plan.
 */
function entry(thing, of, plain, ...more) {
  const under = more.filter(Boolean);
  const item = made("li", `entry${plain ? "" : " not"}${edges(thing)}`);
  item.title = [thing.name, thing.says, ...under, ...marks(thing)].join("\n");
  Object.assign(item.dataset, { of, records: tiesOf(thing).join(" ") });
  item.append(made("b", "entry-name", thing.name), made("span", "entry-says", thing.says));
  for (const words of under) item.append(made("span", "entry-takes", words));
  return item;
}

/**
 * The WANTs of the FILE: each with for whom it is a must or a must-not, and under it the
 * OPTIONs that the FILE says SATISFY it or do not, with who takes part in each. An OPTION that
 * the calendar holds is tied to its step, so pointing at it lights up that step.
 */
function drawWants(shown) {
  const box = part("wants");
  box.replaceChildren();
  part("wants-part").hidden = !shown.wants.length;
  part("wants-says").textContent = shown.says;
  for (const want of shown.wants) {
    const card = Object.assign(made("article", `card${edges(want)}`), { title: marks(want).join("\n") });
    Object.assign(card.dataset, { of: `want:${want.id}`, records: tiesOf(want).join(" ") });
    card.append(made("h3", "card-name", want.name));
    for (const words of [want.holds, want.ends]) if (words) card.append(made("p", "card-holds", words));
    const options = made("ul", "card-options");
    for (const option of want.options) options.append(entry(option, drawingOf(option, option.option), option.degree > 0, option.takes));
    if (want.options.length) card.append(options);
    if (want.whole) card.append(made("p", "card-whole", want.whole));
    box.append(card);
  }
}

/**
 * A row for a PERSON, an OPTION or a WAY of the FILE: its name and where it is, and then what
 * the page says of it, in columns. `of` says what the row is a drawing of.
 */
function item(thing, of, columns) {
  const row = Object.assign(made("article", `item${edges(thing)}`), { title: marks(thing).join("\n") });
  Object.assign(row.dataset, { of, records: tiesOf(thing).join(" ") });
  const head = made("div", "item-head");
  head.append(made("h3", "item-name", thing.name), made("p", "item-where", thing.where));
  row.append(head);
  for (const column of columns) {
    const said = made("div", "item-said");
    for (const words of column) if (words) said.append(made("p", "", words));
    row.append(said);
  }
  return row;
}

/**
 * Every PERSON of the FILE, a row for each: where the FILE says they start from, where a WANT
 * has them end the TRIP, and which BUDGETs they may draw on. The row has the colour of the
 * PERSON's column in the calendar.
 */
function drawPersons(shown) {
  const box = part("persons");
  box.replaceChildren();
  part("persons-part").hidden = !shown.persons.length;
  part("persons-says").textContent = shown.says;
  shown.persons.forEach((person, n) => {
    const row = item(person, `person:${person.id}`, [person.ends, person.pays]);
    row.classList.add("of-a-person", `p${n % HUES}`);
    box.append(row);
  });
}

/**
 * Every PLACE of the FILE, a card for each: who starts from it, which OBJECTs are there when
 * the TRIP starts, and who must end the TRIP there, and under that the OPTIONs and the WAYs
 * that are at it or go from it or to it. An OPTION that the calendar holds is tied to its
 * step, and a WAY to each step in which somebody takes it, so pointing at one lights up those
 * steps.
 */
function drawPlaces(shown) {
  const box = part("places");
  box.replaceChildren();
  part("places-part").hidden = !shown.places.length;
  part("places-says").textContent = shown.says;
  for (const place of shown.places) {
    const card = Object.assign(made("article", `card${edges(place)}`), { title: marks(place).join("\n") });
    Object.assign(card.dataset, { of: `place:${place.id}`, records: tiesOf(place).join(" ") });
    card.append(made("h3", "card-name", place.name));
    for (const words of place.holds) card.append(made("p", "card-holds", words));
    const entries = made("ul", "card-options");
    for (const option of place.options) entries.append(entry(option, drawingOf(option, option.option), true, option.takes));
    for (const way of place.ways) entries.append(entry(way, drawingOfAWay(way.steps, way.way), true, way.takes));
    if (entries.children.length) card.append(entries);
    box.append(card);
  }
}

/**
 * Every OPTION of the FILE, a row for each: where it is, what the FILE says of its start and
 * its length, and who is in it. An OPTION that the calendar holds is tied to its step, so
 * pointing at it lights up that step.
 */
function drawOptions(shown) {
  const box = part("options");
  box.replaceChildren();
  part("options-part").hidden = !shown.options.length;
  part("options-says").textContent = shown.says;
  for (const option of shown.options) box.append(item(option, drawingOf(option, option.id), [[option.when, option.takes, option.arrive, option.right], [option.lock, option.plan]]));
}

/**
 * The rights to the OPTIONs of the FILE: a card for each OPTION that needs a right or has one
 * in the FILE, with its BOOKINGs and its OFFERs. A BOOKING secures a right, and is drawn full.
 * An OFFER is a place that can still be bought. Each is a thing of its own, tied to its FACT.
 */
function drawRights(shown) {
  const box = part("rights");
  box.replaceChildren();
  part("rights-part").hidden = !shown.rights.length;
  part("rights-says").textContent = shown.says;
  for (const rights of shown.rights) {
    const card = Object.assign(made("article", `card${edges(rights)}`), { title: marks(rights).join("\n") });
    Object.assign(card.dataset, { of: `rights:${rights.option}`, records: tiesOf(rights).join(" ") });
    card.append(made("h3", "card-name", rights.name), made("p", "card-holds", rights.needs));
    const entries = made("ul", "card-options");
    for (const booking of rights.bookings) entries.append(entry(booking, `booking:${booking.id}`, true, booking.uses));
    for (const offer of rights.offers) entries.append(entry(offer, `offer:${offer.id}`, false, offer.uses));
    if (entries.children.length) card.append(entries);
    card.append(made("p", "card-whole", rights.whole));
    box.append(card);
  }
}

/**
 * The BUDGETs of the FILE: a card for each, with the caps on it and what the BOOKINGs state
 * that they paid from it. A cap is a thing of its own. A payment is a drawing of its BOOKING.
 * The payments that name no BUDGET come last, on a card of their own.
 */
function drawBudgets(shown) {
  const box = part("budgets");
  box.replaceChildren();
  part("budgets-part").hidden = !shown.budgets.length;
  part("budgets-says").textContent = shown.says;
  const paid = (booking) => entry(booking, `booking:${booking.id}`, true, null);
  for (const budget of shown.budgets) {
    const card = made("article", "card");
    card.dataset.of = `budget:${budget.id}`;
    card.append(made("h3", "card-name", budget.name), made("p", "card-holds", budget.holds));
    const entries = made("ul", "card-options");
    for (const cap of budget.caps) entries.append(entry(cap, `cap:${cap.id}`, true, cap.plan));
    for (const booking of budget.payments) entries.append(paid(booking));
    if (entries.children.length) card.append(entries);
    if (budget.whole) card.append(made("p", "card-whole", budget.whole));
    box.append(card);
  }
  if (shown.unnamed.length) {
    const card = made("article", "card");
    card.append(made("h3", "card-name", "No BUDGET named"), made("p", "card-holds", "These BOOKINGs state a payment, and not which BUDGET the money came from."));
    const entries = made("ul", "card-options");
    for (const booking of shown.unnamed) entries.append(paid(booking));
    card.append(entries);
    box.append(card);
  }
}

/**
 * Every WAY of the FILE, a row for each: where it goes, how long it takes, and who takes it in
 * the plan. A WAY is tied to each step in which somebody takes it, so pointing at it lights up
 * those steps. Under the WAYs comes each FACT that the FILE lists every way of some travel: a
 * thing of its own.
 */
function drawWays(shown) {
  const box = part("ways");
  const travel = part("travel");
  box.replaceChildren();
  travel.replaceChildren();
  part("ways-part").hidden = !shown.ways.length && !shown.travel.length;
  part("ways-says").textContent = shown.says;
  box.hidden = !shown.ways.length;
  travel.hidden = !shown.travel.length;
  for (const way of shown.ways) box.append(item(way, drawingOfAWay(way.steps, way.id), [[way.takes], way.plan]));
  for (const fact of shown.travel) {
    const line = Object.assign(made("li", `in-full${fact.clash.length ? " clash" : ""}`, fact.says), { title: fact.finds ?? "" });
    Object.assign(line.dataset, { of: `travel:${fact.record}`, records: fact.records.join(" ") });
    travel.append(line);
  }
}

/**
 * The CAPABILITIES of the FILE: each with every PERSON and what the FILE says of them, and
 * under it the OPTIONs that the FILE says require it or do not, with who takes part in each
 * and who meets what it requires. An OPTION that the calendar holds is tied to its step, so
 * pointing at it lights up that step.
 */
function drawCapabilities(shown) {
  const box = part("capabilities");
  box.replaceChildren();
  part("capabilities-part").hidden = !shown.capabilities.length;
  part("capabilities-says").textContent = shown.says;
  for (const capability of shown.capabilities) {
    const card = Object.assign(made("article", `card${edges(capability)}`), { title: marks(capability).join("\n") });
    Object.assign(card.dataset, { of: `capability:${capability.id}`, records: tiesOf(capability).join(" ") });
    card.append(made("h3", "card-name", capability.name));
    const people = made("ul", "able");
    for (const person of capability.people) {
      const item = made("li", `has${person.has === true ? " yes" : person.has === false ? " no" : " unsaid"}${edges(person)}`);
      item.title = [`${person.name}: ${person.says}`, ...marks(person)].join("\n");
      // What the FILE says of one PERSON and one CAPABILITY is a thing of its own.
      Object.assign(item.dataset, { of: `capability:${capability.id}:${person.person}`, records: tiesOf(person).join(" ") });
      item.append(made("b", "has-name", `${person.name}:`), made("span", "has-says", person.says));
      people.append(item);
    }
    card.append(people);
    const options = made("ul", "card-options");
    for (const option of capability.options) options.append(entry(option, drawingOf(option, option.option), option.of !== "none", option.meets ? `${option.takes} ${option.meets}` : option.takes));
    if (capability.options.length) card.append(options);
    if (capability.whole) card.append(made("p", "card-whole", capability.whole));
    box.append(card);
  }
}

/**
 * The OBJECTs of the FILE: a card for each, with where it is when the TRIP starts, and under
 * it the OPTIONs that the FILE says require it or do not, and those that it says hand it
 * over, keep it or leave it alone. An OPTION that the calendar holds is tied to its step.
 */
function drawObjects(shown) {
  const box = part("objects");
  box.replaceChildren();
  part("objects-part").hidden = !shown.objects.length;
  part("objects-says").textContent = shown.says;
  for (const thing of shown.objects) {
    const card = Object.assign(made("article", `card${edges(thing)}`), { title: marks(thing).join("\n") });
    Object.assign(card.dataset, { of: `object:${thing.id}`, records: tiesOf(thing).join(" ") });
    card.append(made("h3", "card-name", thing.name), made("p", "card-holds", thing.starts));
    if (thing.plan) card.append(made("p", "card-plan", thing.plan));
    const options = made("ul", "card-options");
    for (const option of [...thing.requires, ...thing.might, ...thing.transfers]) options.append(entry(option, drawingOf(option, option.option), option.does, option.takes, option.plan));
    if (options.children.length) card.append(options);
    for (const words of thing.whole) card.append(made("p", "card-whole", words));
    box.append(card);
  }
}

/**
 * The parts of the page that show what the FILE holds, beside its calendar. Each is loaded by
 * itself and put on the page once for each TRIP. `words` is what puts the part in words, once
 * the page has loaded it, and `of` is the TRIP that the part on the page is of.
 */
const held = [
  { id: "persons-part", load: () => import("./persons.js"), name: "persons", draw: drawPersons, words: null, of: undefined },
  { id: "places-part", load: () => import("./places.js"), name: "places", draw: drawPlaces, words: null, of: undefined },
  { id: "wants-part", load: () => import("./wants.js"), name: "wants", draw: drawWants, words: null, of: undefined },
  { id: "options-part", load: () => import("./options.js"), name: "options", draw: drawOptions, words: null, of: undefined },
  { id: "rights-part", load: () => import("./rights.js"), name: "rights", draw: drawRights, words: null, of: undefined },
  { id: "budgets-part", load: () => import("./budgets.js"), name: "budgets", draw: drawBudgets, words: null, of: undefined },
  { id: "ways-part", load: () => import("./ways.js"), name: "ways", draw: drawWays, words: null, of: undefined },
  { id: "capabilities-part", load: () => import("./capabilities.js"), name: "capabilities", draw: drawCapabilities, words: null, of: undefined },
  { id: "objects-part", load: () => import("./objects.js"), name: "objects", draw: drawObjects, words: null, of: undefined },
];

/** The calendar part says this, and shows no calendar. */
function noCalendar(words) {
  drawStrip(null);
  part("calendar").hidden = part("calendar-key").hidden = part("calendar-untimed").hidden = true;
  part("calendar-says").textContent = words;
  // Nothing in this part is marked now, whatever an earlier calendar held.
  noted("calendar-part", null, false, false);
}

/** The report in words on the page: line by line where its lines are tied, and whole where not. */
function write(text, tied) {
  const report = part("report");
  if (tied === null) {
    report.textContent = text || "";
    return;
  }
  report.replaceChildren();
  tied.forEach((line, n) => {
    const words = made("span", line.warns ? "row warns" : "row", line.text);
    // A line is about the step that it shows or warns of, and about each OFFER that it says
    // somebody buys a place of, or the BUDGET that it states.
    const about = [...(line.step === null ? [] : [line.step]), ...line.about];
    if (about.length) words.dataset.of = about.join(" ");
    if (line.record !== null) words.dataset.record = line.record;
    if (line.case !== null) words.dataset.record = `case:${line.case}`;
    report.append(words, n + 1 < tied.length ? "\n" : "");
  });
}

/**
 * Pointing at a drawing lights up every drawing of the same thing, and the lines of the report
 * that the drawing pointed at is tied to: the line of its step in the plan, what the report
 * warns of there, and the lines of its own records and cases. A drawing has the records of
 * what it shows. A mark and a row have every record about their OPTION. An OPTION under a WANT
 * has the one FACT about the two, so pointing at it picks out that FACT. Pointing lights up no
 * drawing of another thing, though a record or a case may be about both. `data-of` says what a
 * drawing is of: a step of the TRIP, an OPTION or a WAY that is no step, a PERSON, a PLACE, a WANT, a
 * CAPABILITY, what the FILE says of one PERSON and one CAPABILITY, the rights to an OPTION, a
 * BOOKING, an OFFER, a BUDGET, a cap, an OBJECT, or a FACT that the FILE lists every way of
 * some travel. A WAY that somebody takes several times is a drawing of each
 * of those steps.
 *
 * The line of a record or of a case, and a time of the TRIP, are of no thing. Pointing at one
 * lights up everything that is tied to it. A drawing that is tied to it is a drawing of what
 * the line is about, so every other drawing of that thing lights up too.
 */
function light(target) {
  const tied = "[data-of], [data-record], [data-records]";
  const from = target instanceof Element ? target.closest(tied) : null;
  const all = [...document.querySelectorAll(tied)];
  const ids = (each) => [each.dataset.record, ...(each.dataset.records ?? "").split(" ")].filter(Boolean);
  // A mark of the strip can stand for several steps.
  const thingsOf = (each) => (each.dataset.of ?? "").split(" ").filter(Boolean);
  const isLine = (each) => each.classList.contains("row");
  const records = new Set(from ? ids(from) : []);
  const shares = (each) => ids(each).some((id) => records.has(id));
  const things = new Set(from ? thingsOf(from) : []);
  const ofAThing = things.size > 0;
  // What a line is about: each thing with a drawing of its own that is tied to the line.
  if (from !== null && !ofAThing) {
    for (const each of all) if (!isLine(each) && thingsOf(each).length === 1 && shares(each)) things.add(thingsOf(each)[0]);
  }
  for (const each of all) {
    const theirs = thingsOf(each);
    const ofThese = theirs.some((thing) => things.has(thing));
    const same = ofAThing ? (theirs.length ? ofThese : shares(each)) : shares(each) || (ofThese && !isLine(each));
    each.classList.toggle("lit", from !== null && same);
  }
  reveal(from);
}

/**
 * Where the report scrolls by itself beside the drawings, pointing at a drawing brings the
 * first of its lines into view there, unless one of them is in view already.
 *
 * Only the report scrolls, so the drawing stays under the pointer. And the report moves once
 * for a drawing: while the pointer stays on that drawing, the reader's own scrolling stands.
 * A drawing is known by what it is of and what it is tied to, so the line of a WAY and its
 * name beside it are one drawing.
 */
function reveal(from) {
  const drawing = from === null ? null : [from.dataset.of, from.dataset.record, from.dataset.records].join("|");
  const entered = drawing !== revealedFor;
  revealedFor = drawing;
  const report = part("report");
  if (!entered || from === null || report.contains(from) || report.scrollHeight <= report.clientHeight) return;
  // What the reader sees of the report: the part of it that is in the window. A window too
  // short for the panes shows the upper part only.
  const pane = report.getBoundingClientRect();
  const box = { top: Math.max(pane.top, 0), bottom: Math.min(pane.bottom, innerHeight) };
  const lines = [...report.querySelectorAll(".row.lit")].map((line) => line.getBoundingClientRect());
  if (!lines.length || box.bottom <= box.top || lines.some((at) => at.top >= box.top && at.bottom <= box.bottom)) return;
  // The middle of the first line goes to the middle of what the reader sees of the report.
  report.scrollTop += (lines[0].top + lines[0].bottom) / 2 - (box.top + box.bottom) / 2;
}

/** What is under the pointer is lit again, after the page has written or drawn anew. */
function lightAgain() {
  requestAnimationFrame(() => light([...document.querySelectorAll(":hover")].pop() ?? null));
}

/**
 * What the row of links says of one part of the page: how many things the part holds, where
 * that is a number worth saying, and whether something in it has the red edge or the yellow
 * edge. The part is drawn, and this is noted on it.
 */
function noted(id, count, clash, asked) {
  Object.assign(part(id).dataset, { count: count === null ? "" : String(count), clash: clash ? "yes" : "", asked: asked ? "yes" : "" });
}

/**
 * The row of links to the parts that the page shows now, in the order of the page: the
 * calendar, each part that shows what the FILE holds, and the report. A link has the heading
 * of its part, how many things the part holds, and the red or the yellow edge where something
 * in the part has it. So a reader of a long page sees where the report names something, and
 * gets there with one click or from the keyboard. A page with one part has no such row.
 */
function drawContents() {
  const parts = [...document.querySelectorAll("#drawings > section, #report-part")].filter((each) => !each.hidden);
  const row = part("contents");
  row.hidden = parts.length < 2;
  // A link stays where it is while its part is on the page, so the keyboard keeps its place
  // on it when the page says more. The parts and the links are both in the order of the page.
  const have = new Map([...row.children].map((link) => [link.getAttribute("href"), link]));
  let last = null;
  for (const each of parts) {
    const href = `#${each.id}`;
    let link = have.get(href);
    if (link === undefined) {
      link = Object.assign(made("a", "to"), { href });
      link.append(made("span", "", ""), made("span", "count", ""));
      row.insertBefore(link, last === null ? row.firstChild : last.nextSibling);
    }
    have.delete(href);
    last = link;
    const clash = each.dataset.clash === "yes";
    const asked = each.dataset.asked === "yes";
    // A part that is pale shows what is not of the FILE as it is now, and so does its link.
    const old = each.classList.contains("old");
    link.className = `to${clash ? " clash" : ""}${asked ? " asked" : ""}${old ? " old" : ""}`;
    link.firstChild.textContent = each.querySelector("h2").textContent;
    link.lastChild.textContent = each.dataset.count ?? "";
    link.title = [
      ...(clash ? ["The report names something here among what rules out every plan."] : []),
      ...(asked ? ["The report names something here that the reader should look at: a yellow edge marks it."] : []),
      ...(old ? ["What this part shows is not of the FILE as it is now."] : []),
    ].join("\n");
  }
  for (const gone of have.values()) gone.remove();
}

// A part comes to rest under the row of links, however many lines the row takes.
new ResizeObserver(() => document.documentElement.style.setProperty("--row-of-links", `${part("contents").offsetHeight}px`)).observe(part("contents"));

/** What the page shows now, with the row of links to its parts. */
function show() {
  try {
    showParts();
  } finally {
    drawContents();
  }
}

function showParts() {
  const said = says(state);
  document.title = said.name ? `${said.name}: Agloe` : "Agloe";
  part("name").textContent = said.name || "";
  part("answer").className = `answer ${said.mark}`;
  part("line").textContent = said.line;
  part("note").textContent = said.note;
  part("problems").replaceChildren(...(said.problems || []).map((problem) => Object.assign(document.createElement("li"), { textContent: problem })));
  part("problems").hidden = !said.problems;
  // The lines of the report, each tied to the step or the record that it is about, once the
  // page can tie them. Until then, and where it cannot, the report is on the page as it is.
  // Where the page draws the FILE ahead of any report on it, a report that is still on the
  // page is on the FILE as it was: its lines are tied to nothing that the page draws.
  const tied = tie && said.report !== null && !said.ahead ? tie.lines(said.report, said.calendar.report, said.calendar.trip) : null;
  const drawnOld = said.past;
  const from = [said.report, said.calendar?.report, said.calendar?.trip, tie];
  if (from.some((each, n) => each !== written[n])) {
    written = from;
    write(said.report, tied);
    lightAgain();
  }
  part("report-part").hidden = said.report === null;
  part("report-part").classList.toggle("old", said.old);
  // Each part that shows what the FILE holds is put on the page once for each TRIP, like the
  // calendar. It needs no calendar, and a fault in it leaves the rest of the page as it is.
  for (const each of held) {
    part(each.id).classList.toggle("old", drawnOld);
    if (said.calendar === null || each.words === null) part(each.id).hidden = true;
    else if (said.calendar.trip !== each.of) {
      each.of = said.calendar.trip;
      try {
        const shown = each.words(each.of, said.calendar.report, tied ? tie.statedIn(tied) : null);
        each.draw(shown);
        noted(each.id, Array.isArray(shown[each.name]) ? shown[each.name].length : null, shown.clash, shown.asked);
        lightAgain();
      } catch (problem) {
        part(each.id).hidden = true;
        queueMicrotask(() => {
          throw problem;
        });
      }
    }
  }
  // The answer and the report are on the page before the calendar is drawn. The calendar is
  // drawn once for each TRIP, so it stays as the reader left it while the page says more.
  part("calendar-part").hidden = said.calendar === null || lay === null;
  part("calendar-part").classList.toggle("old", drawnOld);
  if (said.calendar === null || lay === null) return;
  if (lay === false) return noCalendar("The page could not load its calendar.");
  if (said.calendar.trip === drawn) return;
  drawn = said.calendar.trip;
  let laid;
  try {
    laid = lay(drawn, said.calendar.report, tied ? tie.warningsOf(tied) : [], tied ? tie.statedIn(tied) : []);
    draw(laid);
    noted("calendar-part", null, laid.clash, laid.warned || laid.asked);
    lightAgain();
  } catch (problem) {
    // Half a calendar is no calendar. The report below is whole.
    noCalendar("The page could not draw the calendar of this TRIP.");
    throw problem;
  }
  try {
    drawStrip(laid);
  } catch (problem) {
    // Half a strip is no strip. The calendar below is whole.
    drawStrip(null);
    throw problem;
  }
}

function hear(event) {
  state = after(state, event);
  show();
}

const view = new EventSource("events");
view.onmessage = (message) => hear(JSON.parse(message.data));
// The page no longer hears the view. What it shows stays, marked, until the view speaks again.
view.onerror = () => hear({ kind: "lost" });
document.querySelector("main").addEventListener("mouseover", (event) => light(event.target));
document.querySelector("main").addEventListener("mouseleave", () => light(null));
// A click on a mark of the strip brings the same mark of the calendar into view: that part
// of the step, in the columns of those PERSONs.
part("strip").addEventListener("click", (event) => {
  const bar = event.target instanceof Element ? event.target.closest(".bar") : null;
  if (bar === null) return;
  const day = part("calendar").querySelectorAll(".day")[bar.dataset.day];
  day?.querySelector(`.mark[data-mark="${bar.dataset.mark}"]`)?.scrollIntoView({ block: "nearest", inline: "center" });
});
show();
import("./calendar.js").then(
  (loaded) => {
    lay = loaded.calendar;
    show();
  },
  () => {
    // The page goes on without a calendar, and says so where the calendar would be.
    lay = false;
    show();
  },
);
import("./lines.js").then(
  (loaded) => {
    // The report is written again with its lines tied, and the calendar and the parts of the
    // FILE are drawn with what the report says of them.
    tie = loaded;
    drawn = undefined;
    for (const each of held) each.of = undefined;
    show();
  },
  () => {}, // The report stays on the page as it is, and nothing lights up.
);
for (const each of held) {
  each.load().then(
    (loaded) => {
      each.words = loaded[each.name];
      show();
    },
    () => {}, // The page goes on without this part.
  );
}
// The strip is laid out again when the page has more room for it, or less.
if (typeof ResizeObserver === "function") {
  new ResizeObserver(() => {
    if (onStrip === null || part("calendar-part").clientWidth === stripRoom) return;
    drawStrip(onStrip);
    lightAgain();
  }).observe(part("calendar-part"));
}
import("./strip.js").then(
  (loaded) => {
    // The calendar is drawn again, with the strip above it.
    turn = loaded.strip;
    drawn = undefined;
    show();
  },
  () => {}, // The calendar stays on the page as it is, with no strip above it.
);
