// The page of the view: it listens to the view and shows what state.js says.
//
// The answer and the report need nothing but state.js. The calendar is loaded beside them, so
// that a calendar that fails to load or to draw leaves the answer and the report on the page.
import { after, says, start } from "./state.js";

const PER_MINUTE = 0.8; // pixels down the calendar for each minute
const HUES = 6; // the colours that tell the PERSONs apart, in view.css
const EDGE = 14; // pixels that the words at a start or an end of the TRIP need
const SMALLEST = 3; // pixels: the least height of a mark
const TICK = 7; // pixels: the height of the tick for a WAY that takes next to no time

const part = (id) => document.getElementById(id);
let state = start();
let lay = null; // what lays a calendar out, once the page has loaded it: false where it cannot
let drawn; // the TRIP that the calendar on the page is of

function made(tag, className, text = "") {
  return Object.assign(document.createElement(tag), { className, textContent: text });
}

/** The hours down the left of the calendar: 2 pm, noon, midnight. */
function hourName(minute) {
  const hour = (minute / 60) % 24;
  return hour === 0 ? "midnight" : hour === 12 ? "noon" : `${hour % 12} ${hour < 12 ? "am" : "pm"}`;
}

/**
 * One mark of the calendar, put on its day: a block for an OPTION, or a line down each PERSON's
 * column for a WAY. The name of a WAY stands beside the line of the first PERSON who takes it,
 * as far as its day has room.
 */
function put(body, mark, people, open) {
  const box = made("div", `mark ${mark.state}${mark.begins ? "" : " goes-on"}${mark.ends ? "" : " no-end"}${mark.brief ? " brief" : ""}`);
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
  box.title = [mark.name, when, mark.where, mark.who, mark.lock ?? "A WAY in the plan of the report."].join("\n");
  const block = made("div", "block");
  const stripes = made("div", "stripes");
  for (let column = mark.first; column <= mark.last; column += 1) {
    const stripe = made("i", `stripe p${column % HUES}`);
    if (mark.brief) {
      // Only the tick itself answers the pointer, so that what it sits on can be reached too.
      const tick = Object.assign(made("b", "tick"), { title: box.title });
      tick.style.marginLeft = `${mark.beside * 36}px`;
      stripe.append(tick);
    }
    stripes.append(stripe);
  }
  block.append(stripes);
  if (mark.kind === "option") block.append(made("b", "mark-name", mark.name), made("span", "mark-more", `${when} · ${mark.where}`));
  box.append(block);
  body.append(box);
  if (mark.kind === "option" || !mark.named) return;
  const name = made("span", "way-name", mark.name);
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
    for (const mark of day.marks) put(body, mark, people, day.open);
    for (const bound of day.bounds) {
      const line = made("div", "bound");
      const down = bound.top * PER_MINUTE;
      line.style.top = `${down}px`;
      // The words stand outside the TRIP, where no step is, unless the edge of the day is too
      // near. Words for the start and the end at once stand where there is room.
      const above = bound.edge === "ends" ? tall - down < EDGE : down >= EDGE;
      line.append(made("span", above ? "above" : "below", bound.says));
      body.append(line);
    }
    column.append(Object.assign(made("h3", "day-name", day.name), { title: day.name }), heads, body);
    grid.append(column);
  }
  grid.hidden = !laid.days.length;
  part("calendar-key").hidden = !laid.days.length;
  // A calendar of what is LOCKed holds nothing that is only in a plan, and no WAY.
  part("calendar-key").classList.toggle("only-locks", !laid.itinerary);
  part("calendar-says").textContent = laid.says;
  part("calendar-untimed").textContent = `A LOCK names these, and the FILE gives them no time: ${laid.untimed.map((step) => `${step.name} (${step.who})`).join(", ")}.`;
  part("calendar-untimed").hidden = !laid.untimed.length;
}

/** The calendar part says this, and shows no calendar. */
function noCalendar(words) {
  part("calendar").hidden = part("calendar-key").hidden = part("calendar-untimed").hidden = true;
  part("calendar-says").textContent = words;
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
  part("report").textContent = said.report || "";
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
  try {
    draw(lay(drawn));
  } catch (problem) {
    // Half a calendar is no calendar. The report below is whole.
    noCalendar("The page could not draw the calendar of this TRIP.");
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
