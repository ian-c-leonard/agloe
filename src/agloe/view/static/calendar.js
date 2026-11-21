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
// Each step names the FACTs and DECISIONs of the FILE that are about it. A report on a TRIP that
// cannot work names the FACTs, WANTs and DECISIONs that rule out every plan. So the calendar
// marks the steps that the report is about, and the start and the end of the TRIP likewise.
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

/** What the calendar says of the records that a report names as ruling out every plan. */
function rulesOut(named, marked) {
  if (!named) return "";
  const names = ` The report names ${named === 1 ? "1 record that rules" : `${named} records that rule`} out every plan.`;
  if (!marked) return `${names} ${named === 1 ? "It is not" : "None of them is"} about what the calendar shows.`;
  if (named === 1) return `${names} A red edge marks what it is about.`;
  return `${names} A red edge marks what ${marked} of them ${marked === 1 ? "is" : "are"} about.`;
}

/** What the calendar holds, in words. */
function saysOf(trip, timed) {
  const clocks = ` Times are on the clocks of ${trip.zone}.`;
  const changes = trip.days.some((day) => day.offset !== null) ? " A column that names its offset from UTC starts or ends with a change of those clocks." : "";
  const cut = trip.until === null ? "" : ` The calendar shows the first ${trip.days.length} columns. It leaves out what comes after them, up to ${dateName(trip.until)}.`;
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
 *
 * `report` is the report as JSON, where the page has one. `clash` on a mark holds the records
 * that are about its step and that the report names as ruling out every plan. `clash` on a
 * bound says that the report names the DECISION about it. `clash` on the calendar says that
 * something on it is marked so.
 *
 * `warnings` holds, at the place of each step, what the report in words warns of there.
 * `warns` on a mark holds those words, and `warned` on the calendar says that a mark has some.
 * Each mark also holds the `records` that are about its step, and each bound its `record`.
 */
export function calendar(trip, report = null, warnings = []) {
  const none = { says: "", zone: null, itinerary: false, clash: false, warned: false, persons: [], hours: { from: 9 * 60, to: 17 * 60 }, days: [], untimed: [] };
  if (trip === null) return { ...none, says: "There is no calendar of this TRIP: the view could not make one." };
  const column = new Map(trip.persons.map((person, n) => [person.id, n]));
  const place = new Map(trip.places.map((each) => [each.id, each.name]));
  const names = (columns) => listed(columns.map((n) => trip.persons[n].name));
  // The FACTs, WANTs and DECISIONs that the report names as ruling out every plan.
  const ruled = new Set(report !== null && report.answer === "INFEASIBLE" && Array.isArray(report.conflict) ? report.conflict.filter((id) => typeof id === "string") : []);

  // ---- each step in words
  const steps = trip.steps.map((step, n) => {
    const columns = step.persons.map((id) => column.get(id)).sort((a, b) => a - b);
    const locked = new Set(step.locked.map((id) => column.get(id)));
    return {
      n, columns, parts: step.parts, end: step.end,
      records: step.records,
      warns: Array.isArray(warnings[n]) ? warnings[n].filter((words) => typeof words === "string") : [],
      clash: step.records.filter((id) => ruled.has(id)),
      get finds() {
        return this.clash.length ? `The report names ${listed(this.clash)} among what rules out every plan.` : null;
      },
      kind: step.option === null ? "way" : "option",
      name: step.name ?? "another WAY",
      who: names(columns),
      where: step.from === step.to ? place.get(step.from) : `${place.get(step.from)} to ${place.get(step.to)}`,
      when: step.start === null ? null : `${clock(step.start)} to ${step.end === null ? "an unknown time" : clock(step.end, step.start)}`,
      late: step.latest === null ? null : `or as late as ${clock(step.latest, step.start)}`,
      stateOf: (at) => (step.option === null ? "way" : locked.has(at) ? "locked" : "planned"),
    };
  });
  const untimed = steps.filter((step) => step.when === null).map((step) => ({ name: step.name, who: step.who, records: step.records, clash: step.clash, finds: step.finds }));
  // What the report names, and how much of it is about what the calendar shows: the steps
  // on its days, the steps with no time that it names beside them, and the times of the TRIP.
  const marked = new Set(steps.filter((step) => step.parts.length || step.when === null).flatMap((step) => step.clash));
  for (const bound of [trip.starts, trip.ends]) if (bound !== null && bound.day !== null && ruled.has(bound.record)) marked.add(bound.record);
  // A step that the report warns about is marked where the calendar shows it. A step after
  // the days shown has no mark, and the calendar says how many of those the report warns about.
  const warned = steps.some((step) => step.warns.length && step.parts.length);
  const after = steps.filter((step) => step.warns.length && !step.parts.length).length;
  const warns = (warned ? " A yellow edge marks each step shown at which the report warns of something." : "") + (after ? ` The report also warns of something at ${after === 1 ? "1 step" : `${after} steps`} after the days shown.` : "");
  const says = saysOf(trip, steps.length - untimed.length) + rulesOut(ruled.size, marked.size) + warns;
  if (!trip.days.length) return { ...none, says, zone: trip.zone, itinerary: trip.itinerary, persons: trip.persons, untimed };

  // ---- the hours that every day shows: from the earliest start of a step on any day to the
  // latest end of a part of one. A step that runs past midnight counts to midnight on the day
  // it starts on. The day after shows it from the first hour that the calendar shows. A part
  // that goes on in a column which opens later than midnight, after a change of the clocks,
  // counts from where it goes on. A step with no known end is drawn half an hour long, and no
  // longer than its day has left.
  const reach = (step, part) => (step.end === null ? Math.min(part.from + NO_END, trip.days[part.day].closes) : part.to);
  const bounds = [[trip.starts, "starts"], [trip.ends, "ends"]].filter(([bound]) => bound !== null && bound.day !== null);
  let low = DAY, high = 0;
  for (const step of steps) {
    for (const part of step.parts) {
      if (part.begins || part.from > 0) low = Math.min(low, part.from);
      high = Math.max(high, reach(step, part));
    }
  }
  if (low > high) {
    // No step is on any day. The hours are those that the TRIP itself covers: from its start
    // to its end where both are in one column, and whole days where they are not, or where
    // one of them is on none of the days shown. A TRIP that says only one of the two shows
    // the hour of that one. With neither, the hours are those of a working day.
    const one = trip.starts ?? trip.ends;
    if (trip.starts && trip.ends) [low, high] = trip.starts.day !== null && trip.starts.day === trip.ends.day ? [Math.min(trip.starts.second, trip.ends.second), Math.max(trip.starts.second, trip.ends.second)] : [0, DAY];
    else [low, high] = one && one.day !== null ? [one.second, one.second] : [9 * 3600 + ROOM, 17 * 3600 - ROOM];
  }
  const from = Math.max(0, Math.floor((low - ROOM) / 3600) * 3600);
  const to = Math.min(DAY, Math.ceil((high + ROOM) / 3600) * 3600);
  const down = (seconds) => (Math.min(Math.max(seconds, from), to) - from) / 60;

  // ---- what each day shows of each step
  const days = trip.days.map((day) => ({
    name: `${dateName(day.date)}${day.offset === null ? "" : ` (${day.offset})`}`,
    marks: [], bounds: [], shown: [],
    // The part of the hours shown in which this column's clocks run: no mark is outside it.
    // `first` and `last` say that it holds the first moment of the column, and its last.
    open: { top: down(day.opens), bottom: down(day.closes), first: day.opens >= from && day.opens < to, last: day.closes <= to && day.closes > from },
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
          // One LOCK can name several PERSONs, and several LOCKs one each: the words fit both.
          lock: run.state === "way" ? null : run.state === "locked" ? `${these} ${run.first === run.last ? "is" : "are each"} named by a LOCK.` : `No LOCK names ${these}.`,
          state: run.state, first: run.first, last: run.last, lane: run.lane, lanes: run.lanes,
          top: (top - from) / 60, height: (bottom - top) / 60,
          begins: part.begins && top === part.from,
          ends: part.ends && bottom === part.to && step.late === null,
          named: step.kind === "option" || bottom - top >= NAMED,
          // A WAY that takes next to no time is a tick on top of what is beside it, so that it shows.
          brief: step.kind === "way" && bottom - top < SMALLEST,
          clash: step.clash,
          finds: step.finds,
          records: step.records,
          warns: step.warns,
        });
      }
    }
    delete day.shown;
  }
  // ---- when the TRIP starts and ends: a line for each, with its words. A time outside the
  // hours shown is at their edge. A time says its date where that is not the date of its
  // column. Each is marked where the report names the DECISION about it, and only there.
  for (const [bound, word] of bounds) {
    const time = clock(bound, { at: trip.days[bound.day].date });
    days[bound.day].bounds.push({ says: `The TRIP ${word} at ${time}`, edge: word, top: down(bound.second), clash: ruled.has(bound.record), record: bound.record });
  }
  return { says, zone: trip.zone, itinerary: trip.itinerary, clash: marked.size > 0, warned, persons: trip.persons, hours: { from: from / 60, to: to / 60 }, days, untimed };
}
