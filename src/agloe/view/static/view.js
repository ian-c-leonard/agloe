// The page of the view: it listens to the view and shows what state.js says.
//
// The answer and the report need nothing but state.js. The calendar is loaded beside them, so
// that a calendar that fails to load or to draw leaves the answer and the report on the page.
// So is what ties each line of the report to the step or the record that it is about, and so
// is the strip above the calendar.
import { after, says, start } from "./state.js";

const PER_MINUTE = 0.8; // pixels down the calendar for each minute
const HUES = 6; // the colours that tell the PERSONs apart, in view.css
const SMALLEST = 3; // pixels: the least height of a mark
const TICK = 7; // pixels: the height of the tick for a WAY that takes next to no time
const BESIDE = 18; // pixels from one tick to the next where several are at one place
const ROW = 20; // pixels: the height of the row of one PERSON on the strip
const LEAST = 3; // pixels: the least width of a mark on the strip
const TICK_WIDE = 5; // pixels: the width of the tick on the strip for a WAY that takes next to no time

const part = (id) => document.getElementById(id);
let state = start();
let lay = null; // what lays a calendar out, once the page has loaded it: false where it cannot
let tie = null; // what ties the lines of a report to steps and records, once the page has loaded it
let turn = null; // what turns a calendar into the strip of the whole TRIP, once the page has loaded it
let drawn; // the TRIP that the calendar on the page is of
let written = []; // what the report on the page was written from: its words, and what its lines are tied to

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
  return [mark.name, when, mark.where, mark.who, mark.lock ?? "A WAY in the plan of the report.", ...(mark.finds ? [mark.finds] : []), ...mark.warns].join("\n");
}

/** How a mark looks, on the calendar and on the strip: by what the view and the report say of its step. */
function looksOf(mark) {
  return `${mark.state}${mark.begins ? "" : " goes-on"}${mark.ends ? "" : " no-end"}${mark.brief ? " brief" : ""}${mark.clash.length ? " clash" : ""}${mark.warns.length ? " warned" : ""}`;
}

/**
 * One mark of the calendar, put on its day: a block for an OPTION, or a line down each PERSON's
 * column for a WAY. The name of a WAY stands beside the line of the first PERSON who takes it,
 * as far as its day has room.
 */
function put(body, mark, index, people, open, ticks) {
  const box = made("div", `mark ${looksOf(mark)}`);
  Object.assign(box.dataset, { step: mark.step, records: mark.records.join(" "), mark: index });
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
    laid.persons.forEach((person, n) => heads.append(Object.assign(made("span", `person p${n % HUES}`, person.name), { title: person.name })));
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
  part("calendar-says").textContent = laid.says;
  // The steps with no time, each marked where the report names what is about it.
  const untimed = laid.untimed.flatMap((step, n) => {
    const name = Object.assign(made("span", step.clash.length ? "clash" : "", `${step.name} (${step.who})`), { title: step.finds ?? "" });
    name.dataset.records = step.records.join(" ");
    return n ? [", ", name] : [name];
  });
  part("calendar-untimed").replaceChildren("The FILE gives no time for these LOCKed OPTIONs: ", ...untimed, ".");
  part("calendar-untimed").hidden = !laid.untimed.length;
}

/**
 * The strip above the calendar: all its days, with a row for each PERSON and time from left to
 * right. It holds the marks of the calendar. So pointing at a step on it lights up the same
 * step below, and what the report says of it. A calendar of one day has no strip.
 */
function drawStrip(laid) {
  const strip = turn && laid ? turn(laid) : null;
  const box = part("strip");
  box.hidden = part("strip-says").hidden = strip === null;
  box.replaceChildren();
  if (strip === null) return;
  const people = Math.max(strip.persons.length, 1);
  const along = (minutes) => `${(minutes / strip.length) * 100}%`;
  box.style.setProperty("--people", people);
  box.style.setProperty("--row", `${ROW}px`);
  const names = made("div", "strip-people");
  strip.persons.forEach((person, n) => names.append(Object.assign(made("span", `p${n % HUES}`, person.name), { title: person.name })));
  const days = made("div", "strip-days");
  const rows = made("div", "strip-rows");
  for (const day of strip.days) {
    if (!day.width) continue;
    const name = Object.assign(made("span", "strip-day", day.short), { title: day.name });
    name.style.left = along(day.left);
    name.style.width = along(day.width);
    days.append(name);
    if (!day.left) continue;
    // Where the strip leaves hours out before a day, the line between the days is double.
    const edge = made("i", day.gap ? "strip-edge gap" : "strip-edge");
    edge.style.left = along(day.left);
    rows.append(edge);
  }
  for (const mark of strip.marks) {
    const bar = Object.assign(made("div", `bar ${looksOf(mark)}`), { title: wordsOf(mark) });
    Object.assign(bar.dataset, { step: mark.step, records: mark.records.join(" "), day: mark.day, mark: mark.index });
    const day = strip.days[mark.day];
    const ends = along(day.left + day.width);
    if (mark.brief) {
      // A tick sits across the moment of its WAY, and never outside its day.
      bar.style.left = `clamp(${along(day.left)}, calc(${along(mark.left)} - ${TICK_WIDE / 2}px), calc(${ends} - ${TICK_WIDE}px))`;
      bar.style.width = `${TICK_WIDE}px`;
    } else {
      // A mark is never smaller than the eye can find, and never outside its day.
      bar.style.left = `min(${along(mark.left)}, calc(${ends} - ${LEAST}px))`;
      bar.style.width = `max(${along(mark.width)}, ${LEAST}px)`;
    }
    bar.style.top = `${((mark.first + mark.lane / mark.lanes) / people) * 100}%`;
    bar.style.height = `${((mark.last - mark.first + 1) / mark.lanes / people) * 100}%`;
    // A block for an OPTION, with its name where there is room. A line along each PERSON's row
    // for a WAY, or a tick in that row for a WAY that takes next to no time. Only the tick
    // itself answers the pointer, so that ticks at one place can each be reached.
    if (mark.kind === "option") bar.append(made("i", "bar-block"), made("b", "bar-name", mark.name));
    else {
      for (let row = mark.first; row <= mark.last; row += 1) {
        const line = made("i", `bar-line p${row % HUES}`);
        if (mark.brief) line.append(Object.assign(made("b", `strip-tick at${mark.place}`), { title: bar.title }));
        bar.append(line);
      }
    }
    rows.append(bar);
  }
  for (const bound of strip.bounds) {
    const line = Object.assign(made("i", bound.clash ? "strip-bound clash" : "strip-bound"), { title: bound.says });
    line.style.left = `min(${along(bound.left)}, calc(100% - 2px))`;
    line.dataset.record = bound.record;
    rows.append(line);
  }
  box.append(made("span", ""), days, names, rows);
  part("strip-says").textContent = strip.says;
}

/** The calendar part says this, and shows no calendar. */
function noCalendar(words) {
  drawStrip(null);
  part("calendar").hidden = part("calendar-key").hidden = part("calendar-untimed").hidden = true;
  part("calendar-says").textContent = words;
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
    if (line.step !== null) words.dataset.step = line.step;
    if (line.record !== null) words.dataset.record = line.record;
    report.append(words, n + 1 < tied.length ? "\n" : "");
  });
}

/**
 * Pointing at a step lights up that step and what the report says of it: its marks, its line
 * in the plan, what the report warns of there, and the lines of the records that are about it.
 * It lights up no other step, though a record may be about both. Pointing at the line of a
 * record, or at a time of the TRIP, lights up everything that the record is about.
 */
function light(target) {
  const from = target instanceof Element ? target.closest("[data-step], [data-record], [data-records]") : null;
  const ids = (each) => [each.dataset.record, ...(each.dataset.records ?? "").split(" ")].filter(Boolean);
  const records = new Set(from ? ids(from) : []);
  const step = from?.dataset.step;
  for (const each of document.querySelectorAll("[data-step], [data-record], [data-records]")) {
    const shares = ids(each).some((id) => records.has(id));
    const same = from !== null && (step === undefined ? shares : each.dataset.step === step || (each.dataset.step === undefined && shares));
    each.classList.toggle("lit", same);
  }
}

/** What is under the pointer is lit again, after the page has written or drawn anew. */
function lightAgain() {
  requestAnimationFrame(() => light([...document.querySelectorAll(":hover")].pop() ?? null));
}

function show() {
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
  const tied = tie && said.report !== null ? tie.lines(said.report, said.calendar.report, said.calendar.trip) : null;
  const from = [said.report, said.calendar?.report, said.calendar?.trip, tie];
  if (from.some((each, n) => each !== written[n])) {
    written = from;
    write(said.report, tied);
    lightAgain();
  }
  part("report-part").hidden = said.report === null;
  part("report-part").classList.toggle("old", said.old);
  // The answer and the report are on the page before the calendar is drawn. The calendar is
  // drawn once for each TRIP, so it stays as the reader left it while the page says more.
  part("calendar-part").hidden = said.calendar === null || lay === null;
  part("calendar-part").classList.toggle("old", said.old);
  if (said.calendar === null || lay === null) return;
  if (lay === false) return noCalendar("The page could not load its calendar.");
  if (said.calendar.trip === drawn) return;
  drawn = said.calendar.trip;
  let laid;
  try {
    laid = lay(drawn, said.calendar.report, tied ? tie.warningsOf(tied) : []);
    draw(laid);
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
    // The report is written again with its lines tied, and the calendar is drawn with what
    // the report warns of.
    tie = loaded;
    drawn = undefined;
    show();
  },
  () => {}, // The report stays on the page as it is, and nothing lights up.
);
import("./strip.js").then(
  (loaded) => {
    // The calendar is drawn again, with the strip above it.
    turn = loaded.strip;
    drawn = undefined;
    show();
  },
  () => {}, // The calendar stays on the page as it is, with no strip above it.
);
