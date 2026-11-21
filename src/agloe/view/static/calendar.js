// The calendar of a TRIP: a column for each day, and in it a column for each PERSON. There is no
// page in here, so the tests run this as it is.
//
// The view sends the TRIP with each report: the PERSONs and the PLACEs by name, the days, and the
// steps. Each step has who takes part, where it is, its times on the clocks that the report shows
// times on, and the part of it that lies on each day. For a FEASIBLE TRIP the steps are the
// ITINERARY of the report. For any other TRIP the report shows no ITINERARY, and the steps are
// the OPTIONs that a LOCK names.
//
// A day is sent as the stretch of it in which the clocks run on without a change. Most days are
// one stretch. A day on which the clocks change is two, each a column of its own.
//
// Nothing here judges a TRIP, nothing here reads a FILE, and nothing here works out which day a
// moment is on: the view says. This lays out what it is sent: how far down its day a part
// starts, how tall it is, whose columns it spans, and what its words are.

const DAY = 24 * 60 * 60; // seconds
const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const ROOM = 20 * 60; // seconds of room above the first step of a day and below the last
const NO_END = 30 * 60; // seconds drawn for a step whose end nobody knows
const NAMED = 20 * 60; // seconds that a WAY takes before its name has room beside it
const SMALLEST = 4 * 60; // seconds that the smallest mark covers on the page

/** The number of a day, counted from 1 January 1970, in the calendar that a FILE writes dates in. */
function dayNumber(year, month, day) {
  const y = month <= 2 ? year - 1 : year;
  const era = Math.floor(y / 400);
  const inEra = y - era * 400;
  const inYear = Math.floor((153 * (month + (month > 2 ? -3 : 9)) + 2) / 5) + day - 1;
  return era * 146097 + inEra * 365 + Math.floor(inEra / 4) - Math.floor(inEra / 100) + inYear - 719468;
}

/** A time such as 2027-05-15T14:00:00, or a date: its year, month and day, and its seconds into the day. */
function read(written) {
  const [year, month, day, hour = 0, minute = 0, second = 0] = written.match(/\d+/g).map(Number);
  return { year, month, day, seconds: hour * 3600 + minute * 60 + second };
}

/** A date as the report names it: Saturday 15 May 2027. */
export function dateName(written) {
  const { year, month, day } = read(written);
  return `${DAYS[(((dayNumber(year, month, day) + 3) % 7) + 7) % 7]} ${day} ${MONTHS[month - 1]} ${year}`;
}

/**
 * A time of day as the report writes it: 2:00 pm. Its offset from UTC follows where the view
 * sends one. The date is added when it is not on the day of `from`.
 */
export function clock(time, from = null) {
  const at = read(time.at);
  const hour = Math.floor(at.seconds / 3600);
  const minute = Math.floor(at.seconds / 60) % 60;
  const second = at.seconds % 60;
  const shown = `${hour % 12 || 12}:${String(minute).padStart(2, "0")}${second ? `:${String(second).padStart(2, "0")}` : ""} ${hour < 12 ? "am" : "pm"}${time.offset === null ? "" : ` (${time.offset})`}`;
  if (from === null) return shown;
  const day = read(from.at);
  if (at.year === day.year && at.month === day.month && at.day === day.day) return shown;
  return `${shown} on ${at.day} ${MONTHS[at.month - 1]}${at.year === day.year ? "" : ` ${at.year}`}`;
}

/** Names as a sentence joins them: Alex, Sam and Jo. */
export function listed(names) {
  return names.length < 2 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/**
 * Where each of these marks goes in one PERSON's column: its lane, and how many lanes there are
 * beside each other where it is. Marks at the same time get a lane each, so that none hides
 * another. `marks` are in the order of their tops.
 */
function lanesOf(marks) {
  const placed = new Map();
  let group = [], ends = [], until = -Infinity; // `ends` is a heap of [end, lane], least end first
  const close = () => {
    for (const mark of group) placed.get(mark).lanes = ends.length;
    group = [];
    ends = [];
  };
  for (const mark of marks) {
    const bottom = Math.max(mark.bottom, mark.top + SMALLEST);
    if (mark.top >= until) close();
    let lane = ends.length;
    if (ends.length && ends[0][0] <= mark.top) {
      // The lane that came free first is taken again.
      lane = ends[0][1];
      ends[0] = ends[ends.length - 1];
      ends.pop();
      for (let at = 0; ; ) {
        const below = [2 * at + 1, 2 * at + 2].filter((each) => each < ends.length).sort((a, b) => ends[a][0] - ends[b][0])[0];
        if (below === undefined || ends[at][0] <= ends[below][0]) break;
        [ends[at], ends[below]] = [ends[below], ends[at]];
        at = below;
      }
    }
    ends.push([bottom, lane]);
    for (let at = ends.length - 1; at > 0; ) {
      const above = Math.floor((at - 1) / 2);
      if (ends[above][0] <= ends[at][0]) break;
      [ends[at], ends[above]] = [ends[above], ends[at]];
      at = above;
    }
    until = Math.max(until, bottom);
    placed.set(mark, { lane, lanes: 1 });
    group.push(mark);
  }
  close();
  return placed;
}

/** What the calendar holds, in words. */
function saysOf(trip, timed) {
  const clocks = ` Times are on the clocks of ${trip.zone}.`;
  const changes = trip.days.some((day) => day.offset !== null) ? " A column that names its offset from UTC is part of a day on which those clocks change." : "";
  const cut = trip.until === null ? "" : ` The calendar shows the first ${trip.days.length} columns. The TRIP goes on until ${dateName(trip.until)}.`;
  const more = clocks + changes + cut;
  if (trip.itinerary) {
    if (!trip.steps.length) return `The ITINERARY of the report is empty: nobody has to do anything.${trip.days.length ? more : ""}`;
    return `The ITINERARY of the report.${more}`;
  }
  const empty = trip.days.length ? more : " So the calendar is empty.";
  if (!trip.steps.length) return `The report shows no ITINERARY, and no LOCK names an OPTION.${empty}`;
  if (!timed) return `The report shows no ITINERARY, and the FILE gives no time to the OPTIONs that a LOCK names.${empty}`;
  return `The report shows no ITINERARY. The calendar holds only the OPTIONs that a LOCK names, at the times the FILE states.${more}`;
}

/**
 * The calendar of a TRIP as the view sends it, or of no TRIP where the view sends none.
 *
 * `hours` is the part of the clock that every day shows, in minutes. Each day has its name, its
 * marks, its bounds, and the parts of those hours that its clocks never show (`shut`). A mark is
 * the part of one step that one day shows, for PERSONs whose columns are side by side: `top` and
 * `height` are minutes from the top of the day, `first` and `last` are columns. Marks of one
 * PERSON at the same time each get a `lane` of the `lanes` in that column. `begins` and `ends`
 * say whether the part holds the start and the end of its step. A bound is where the TRIP starts
 * or ends. `untimed` names the steps that have no time. `itinerary` says whether the steps are
 * the ITINERARY of the report.
 */
export function calendar(trip) {
  const none = { says: "", zone: null, itinerary: false, persons: [], hours: { from: 9 * 60, to: 17 * 60 }, days: [], untimed: [] };
  if (trip === null) return { ...none, says: "There is no calendar of this TRIP: the view could not make one." };
  const column = new Map(trip.persons.map((person, n) => [person.id, n]));
  const place = new Map(trip.places.map((each) => [each.id, each.name]));
  const names = (columns) => listed(columns.map((n) => trip.persons[n].name));

  // ---- each step in words
  const steps = trip.steps.map((step, n) => {
    const columns = step.persons.map((id) => column.get(id)).sort((a, b) => a - b);
    const locked = new Set(step.locked.map((id) => column.get(id)));
    return {
      n, columns, parts: step.parts, end: step.end,
      kind: step.option === null ? "way" : "option",
      name: step.name ?? "another WAY",
      who: names(columns),
      where: step.from === step.to ? place.get(step.from) : `${place.get(step.from)} to ${place.get(step.to)}`,
      when: step.start === null ? null : `${clock(step.start)} to ${step.end === null ? "an unknown time" : clock(step.end, step.start)}`,
      late: step.latest === null ? null : `or as late as ${clock(step.latest, step.start)}`,
      stateOf: (at) => (step.option === null ? "way" : locked.has(at) ? "locked" : "planned"),
    };
  });
  const untimed = steps.filter((step) => step.when === null).map((step) => ({ name: step.name, who: step.who }));
  const says = saysOf(trip, steps.length - untimed.length);
  if (!trip.days.length) return { ...none, says, zone: trip.zone, itinerary: trip.itinerary, persons: trip.persons, untimed };

  // ---- the hours that every day shows: from the earliest start of a step on any day to the
  // latest end. A step that runs past midnight counts to midnight on the day it starts on. The
  // day after shows it from the first hour that the calendar shows. A step with no known end
  // is drawn half an hour long, and no longer than its day has left.
  const reach = (step, part) => (step.end === null ? Math.min(part.from + NO_END, trip.days[part.day].closes) : part.to);
  const bounds = [[trip.starts, "starts"], [trip.ends, "ends"]].filter(([bound]) => bound !== null && bound.day !== null);
  let low = DAY, high = 0;
  for (const step of steps) {
    for (const part of step.parts) {
      if (!part.begins) continue;
      low = Math.min(low, part.from);
      high = Math.max(high, reach(step, part));
    }
  }
  if (low > high) {
    // No step is on any day. The hours are those of the TRIP itself, or of a working day.
    const seconds = bounds.map(([bound]) => bound.second);
    [low, high] = seconds.length ? [Math.min(...seconds), Math.max(...seconds)] : [9 * 3600 + ROOM, 17 * 3600 - ROOM];
  }
  const from = Math.max(0, Math.floor((low - ROOM) / 3600) * 3600);
  const to = Math.min(DAY, Math.ceil((high + ROOM) / 3600) * 3600);
  const down = (seconds) => (Math.min(Math.max(seconds, from), to) - from) / 60;

  // ---- what each day shows of each step
  const days = trip.days.map((day) => ({
    name: `${dateName(day.date)}${day.offset === null ? "" : ` (${day.offset})`}`,
    marks: [], bounds: [], shown: [],
    // The hours of this column that its clocks never show: before it opens, and after it closes.
    shut: [[from, day.opens], [day.closes, to]].filter(([start, end]) => down(end) > down(start)).map(([start, end]) => ({ top: down(start), height: down(end) - down(start) })),
  }));
  for (const step of steps) {
    for (const part of step.parts) {
      const top = Math.max(part.from, from);
      const bottom = Math.min(reach(step, part), to);
      // A part with no length at all is still a mark, at the time it happens.
      if (bottom < top || (bottom === top && reach(step, part) > part.from)) continue;
      days[part.day].shown.push({ step, part, top, bottom });
    }
  }
  for (const day of days) {
    // OPTIONs that one PERSON is in at the same time stand beside each other in that column.
    const lanes = trip.persons.map((_, at) => lanesOf(day.shown.filter((mark) => mark.step.kind === "option" && mark.step.columns.includes(at)).sort((a, b) => a.top - b.top)));
    for (const mark of day.shown) {
      const { step, part, top, bottom } = mark;
      const laneOf = (at) => (step.kind === "option" ? lanes[at].get(mark) : { lane: 0, lanes: 1 });
      // The PERSONs of the step, as runs of columns that are side by side and marked alike.
      const runs = [];
      for (const at of step.columns) {
        const last = runs[runs.length - 1];
        const state = step.stateOf(at);
        const { lane, lanes: beside } = laneOf(at);
        if (last && last.last === at - 1 && last.state === state && last.lanes === 1 && beside === 1) last.last = at;
        else runs.push({ first: at, last: at, state, lane, lanes: beside });
      }
      for (const run of runs) {
        const these = names(step.columns.filter((at) => run.first <= at && at <= run.last));
        day.marks.push({
          step: step.n, kind: step.kind, name: step.name, when: step.when, late: step.late, where: step.where, who: step.who,
          lock: run.state === "way" ? null : run.state === "locked" ? `A LOCK names ${these}.` : `No LOCK names ${these}.`,
          state: run.state, first: run.first, last: run.last, lane: run.lane, lanes: run.lanes,
          top: (top - from) / 60, height: (bottom - top) / 60,
          begins: part.begins && top === part.from,
          ends: part.ends && bottom === part.to && step.late === null,
          named: step.kind === "option" || bottom - top >= NAMED,
          // A WAY that takes next to no time is a tick on top of what is beside it, so that it shows.
          brief: step.kind === "way" && bottom - top < SMALLEST,
        });
      }
    }
    delete day.shown;
  }
  // ---- when the TRIP starts and ends. A time outside the hours shown is at their edge. Where
  // both are at one place on one day, they share their words.
  for (const [bound, word] of bounds) {
    const says = `The TRIP ${word} at ${clock(bound)}`;
    const beside = days[bound.day].bounds.find((other) => other.top === down(bound.second));
    if (beside) Object.assign(beside, { says: `${beside.says}, and ends at ${clock(bound)}`, edge: "both" });
    else days[bound.day].bounds.push({ says, edge: word, top: down(bound.second) });
  }
  return { says, zone: trip.zone, itinerary: trip.itinerary, persons: trip.persons, hours: { from: from / 60, to: to / 60 }, days, untimed };
}
