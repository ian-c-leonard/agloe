// The page of the view: it listens to the view and shows what state.js says.
import { calendar } from "./calendar.js";
import { after, says, start } from "./state.js";

const PER_MINUTE = 0.8; // pixels down the calendar for each minute
const HUES = 6; // the colours that tell the PERSONs apart, in view.css
const SAID_OF = {
  locked: "A LOCK names it.",
  planned: "In the plan of the report. No LOCK names it.",
  way: "A WAY in the plan of the report.",
};

const part = (id) => document.getElementById(id);
let state = start();
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
 * One mark of the calendar: a block for an OPTION, or a line down each PERSON's column for a WAY.
 * The name of a WAY stands beside the line of the first PERSON who takes it, as far as its day has room.
 */
function markOf(mark, people) {
  const box = made("div", `mark ${mark.state}${mark.begins ? "" : " goes-on"}${mark.ends ? "" : " no-end"}`);
  const columns = mark.last - mark.first + 1;
  box.style.left = `${(mark.first / people) * 100}%`;
  box.style.width = `${(columns / people) * 100}%`;
  box.style.top = `${mark.top * PER_MINUTE}px`;
  box.style.height = `${Math.max(mark.height * PER_MINUTE, 3)}px`;
  box.title = [mark.name, mark.when, mark.where, mark.who, SAID_OF[mark.state]].join("\n");
  const block = made("div", "block");
  const stripes = made("div", "stripes");
  for (let column = mark.first; column <= mark.last; column += 1) stripes.append(made("i", `stripe p${column % HUES}`));
  block.append(stripes);
  if (mark.named && mark.kind === "option") block.append(made("b", "mark-name", mark.name), made("span", "mark-more", `${mark.when} · ${mark.where}`));
  box.append(block);
  if (!mark.named || mark.kind === "option") return [box];
  const name = made("span", "way-name", mark.name);
  name.style.left = `calc(${((mark.first + 0.5) / people) * 100}% + 6px)`;
  name.style.top = `${(mark.top + mark.height / 2) * PER_MINUTE}px`;
  return [box, name];
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
    column.style.setProperty("--people", people);
    const heads = made("div", "people");
    laid.persons.forEach((person, n) => heads.append(Object.assign(made("span", `person p${n % HUES}`, person.name), { title: person.name })));
    const body = made("div", "day-body");
    body.style.height = `${tall}px`;
    body.append(...day.marks.flatMap((mark) => markOf(mark, people)));
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
  part("calendar-part").hidden = said.calendar === null;
  part("calendar-part").classList.toggle("old", said.old);
  if (said.calendar === null || said.calendar.trip === drawn) return;
  drawn = said.calendar.trip;
  try {
    draw(calendar(drawn));
  } catch (problem) {
    // Half a calendar is no calendar. The report below is whole, and says the same in words.
    part("calendar").hidden = part("calendar-key").hidden = part("calendar-untimed").hidden = true;
    part("calendar-says").textContent = "The page could not draw the calendar of this TRIP.";
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
