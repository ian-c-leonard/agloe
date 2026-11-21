// The calendar of a TRIP: a column for each day, and in it a column for each PERSON. There is no
// page in here, so the tests run this as it is.
//
// The view sends the TRIP with each report: the PERSONs and the PLACEs by name, and the steps.
// Each step has who takes part, where it is, and its times on the clocks that the report shows
// times on. For a FEASIBLE TRIP the steps are the ITINERARY of the report. For any other TRIP
// the report shows no ITINERARY, and the steps are the OPTIONs that a LOCK names.
//
// Nothing here judges a TRIP, and nothing here reads a FILE. This lays out what it is sent: which
// day a step is on, how far down the day it starts, how tall it is, and whose columns it spans.

const DAY = 24 * 60 * 60; // seconds
const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
/** The most days that the calendar shows. It says how many days it leaves out. */
export const MOST_DAYS = 62;
const ROOM = 20 * 60; // seconds of room above the first step of a day and below the last
const NO_END = 30 * 60; // seconds drawn for a step whose end nobody knows
const NAMED = 20 * 60; // seconds that a WAY takes before its name has room beside it

/** The number of the day, counted from 1 January 1970, in the calendar that a FILE writes dates in. */
function dayNumber(year, month, day) {
  const y = month <= 2 ? year - 1 : year;
  const era = Math.floor(y / 400);
  const inEra = y - era * 400;
  const inYear = Math.floor((153 * (month + (month > 2 ? -3 : 9)) + 2) / 5) + day - 1;
  return era * 146097 + inEra * 365 + Math.floor(inEra / 4) - Math.floor(inEra / 100) + inYear - 719468;
}

/** The date of a day by its number. */
function dateOf(number) {
  const z = number + 719468;
  const era = Math.floor(z / 146097);
  const inEra = z - era * 146097;
  const y = Math.floor((inEra - Math.floor(inEra / 1460) + Math.floor(inEra / 36524) - Math.floor(inEra / 146096)) / 365);
  const inYear = inEra - (365 * y + Math.floor(y / 4) - Math.floor(y / 100));
  const m = Math.floor((5 * inYear + 2) / 153);
  const month = m < 10 ? m + 3 : m - 9;
  return { year: y + era * 400 + (month <= 2 ? 1 : 0), month, day: inYear - Math.floor((153 * m + 2) / 5) + 1 };
}

/** A time such as 2027-05-15T14:00:00, as seconds on its clock, counted from 1 January 1970. */
function secondsOf(written) {
  const [year, month, day, hour, minute, second] = written.match(/\d+/g).map(Number);
  return dayNumber(year, month, day) * DAY + hour * 3600 + minute * 60 + second;
}

const dayOf = (seconds) => Math.floor(seconds / DAY);

/** A day as the report names it: Saturday 15 May 2027. */
export function dayName(number) {
  const { year, month, day } = dateOf(number);
  return `${DAYS[(((number + 3) % 7) + 7) % 7]} ${day} ${MONTHS[month - 1]} ${year}`;
}

/** A time of day as the report writes it: 2:00 pm. The date is added when it is not on this day. */
export function clock(seconds, day = null) {
  const inDay = seconds - dayOf(seconds) * DAY;
  const hour = Math.floor(inDay / 3600);
  const minute = Math.floor(inDay / 60) % 60;
  const second = inDay % 60;
  const time = `${hour % 12 || 12}:${String(minute).padStart(2, "0")}${second ? `:${String(second).padStart(2, "0")}` : ""} ${hour < 12 ? "am" : "pm"}`;
  if (day === null || dayOf(seconds) === day) return time;
  const there = dateOf(dayOf(seconds));
  return `${time} on ${there.day} ${MONTHS[there.month - 1]}${there.year === dateOf(day).year ? "" : ` ${there.year}`}`;
}

/** Names as a sentence joins them: Alex, Sam and Jo. */
export function listed(names) {
  return names.length < 2 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/** The PERSON columns of a step, as runs of columns that are side by side and marked alike. */
function runs(columns, stateOf) {
  const found = [];
  for (const column of [...columns].sort((a, b) => a - b)) {
    const last = found[found.length - 1];
    if (last && last.last === column - 1 && last.state === stateOf(column)) last.last = column;
    else found.push({ first: column, last: column, state: stateOf(column) });
  }
  return found;
}

/** What the calendar holds, in words. */
function saysOf(trip, timed, days, more) {
  const clocks = ` Times are on the clocks of ${trip.zone}.`;
  const cut = more ? ` The calendar shows the first ${days} days. The steps go on for ${more} more.` : "";
  if (trip.itinerary) {
    if (!trip.steps.length) return "The ITINERARY of the report is empty: nobody has to do anything.";
    return `The ITINERARY of the report.${clocks}${cut}`;
  }
  if (!trip.steps.length) return "The report shows no ITINERARY, and no LOCK names an OPTION. So the calendar is empty.";
  if (!timed) return "The report shows no ITINERARY, and the FILE gives no time to the OPTIONs that a LOCK names. So the calendar is empty.";
  return `The report shows no ITINERARY. The calendar holds only the OPTIONs that a LOCK names, at the times the FILE states.${clocks}${cut}`;
}

/**
 * The calendar of a TRIP as the view sends it, or of no TRIP where the view sends none.
 *
 * `hours` is the part of the clock that every day shows, in minutes. Each day has its name and
 * its marks. A mark is the part of one step that one day shows, for PERSONs whose columns are
 * side by side: `top` and `height` are minutes from the top of the day, `first` and `last` are
 * columns. `begins` and `ends` say whether the part holds the start and the end of its step.
 * `untimed` names the steps that have no time. `itinerary` says whether the steps are the
 * ITINERARY of the report.
 */
export function calendar(trip) {
  const none = { says: "", zone: null, itinerary: false, persons: [], hours: { from: 9 * 60, to: 17 * 60 }, days: [], untimed: [] };
  if (trip === null) return { ...none, says: "This TRIP holds a time outside the years 0001 to 9999, so it has no calendar." };
  const column = new Map(trip.persons.map((person, n) => [person.id, n]));
  const nameOf = new Map(trip.persons.map((person) => [person.id, person.name]));
  const place = new Map(trip.places.map((each) => [each.id, each.name]));

  // ---- each step in words, and where it lies in time
  const steps = trip.steps.map((step, n) => {
    const start = step.start === null ? null : secondsOf(step.start);
    const end = step.end === null ? null : secondsOf(step.end);
    return {
      n, start, end,
      kind: step.option === null ? "way" : "option",
      name: step.name ?? "another WAY",
      who: listed(step.persons.map((id) => nameOf.get(id))),
      where: step.from === step.to ? place.get(step.from) : `${place.get(step.from)} to ${place.get(step.to)}`,
      when: start === null ? null : `${clock(start)} to ${end === null ? "an unknown time" : clock(end, dayOf(start))}`,
      // Where the clocks go back, a step can end at an earlier time of day than it starts at.
      until: start === null ? null : Math.max(start, end ?? start + NO_END),
      runs: runs(step.persons.map((id) => column.get(id)), (at) => (step.option === null ? "way" : step.locked.includes(trip.persons[at].id) ? "locked" : "planned")),
    };
  });
  const timed = steps.filter((step) => step.start !== null);
  const untimed = steps.filter((step) => step.start === null).map((step) => ({ name: step.name, who: step.who }));
  if (!timed.length) return { ...none, says: saysOf(trip, 0, 0, 0), zone: trip.zone, itinerary: trip.itinerary, persons: trip.persons, untimed };

  // ---- the hours that every day shows. A step that runs past midnight counts to midnight on
  // its own day. The day after shows it from the first hour that the calendar shows.
  // The days run from the first that a step starts on to the last that a step reaches.
  let low = DAY, high = 0, first = Infinity, last = -Infinity;
  for (const step of timed) {
    low = Math.min(low, step.start - dayOf(step.start) * DAY);
    high = Math.max(high, dayOf(step.until) > dayOf(step.start) ? DAY : step.until - dayOf(step.start) * DAY);
    first = Math.min(first, dayOf(step.start));
    last = Math.max(last, step.until > step.start ? dayOf(step.until - 1) : dayOf(step.start));
  }
  const from = Math.max(0, Math.floor((low - ROOM) / 3600) * 3600);
  const to = Math.min(DAY, Math.ceil((high + ROOM) / 3600) * 3600);
  const shown = Math.min(last - first + 1, MOST_DAYS);
  const days = [];
  for (let day = first; day < first + shown; day += 1) {
    const marks = [];
    for (const step of timed) {
      const top = Math.max(step.start, day * DAY + from);
      const bottom = Math.min(step.until, day * DAY + to);
      // The day shows the step from `top` to `bottom`, if it shows any of it. A step with no
      // length at all is still a mark, on the day and at the time it happens.
      if (bottom < top || (bottom === top && step.until > step.start) || dayOf(top) !== day) continue;
      for (const run of step.runs) {
        marks.push({
          step: step.n, kind: step.kind, name: step.name, when: step.when, where: step.where, who: step.who,
          state: run.state, first: run.first, last: run.last,
          top: (top - day * DAY - from) / 60, height: (bottom - top) / 60,
          begins: top === step.start, ends: step.end !== null && bottom === step.until,
          named: step.kind === "option" || bottom - top >= NAMED,
        });
      }
    }
    days.push({ name: dayName(day), marks });
  }
  return {
    says: saysOf(trip, timed.length, shown, last - first + 1 - shown),
    zone: trip.zone, itinerary: trip.itinerary, persons: trip.persons, hours: { from: from / 60, to: to / 60 }, days, untimed,
  };
}
