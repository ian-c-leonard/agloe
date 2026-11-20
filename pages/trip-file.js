// The trip on the home page, without the page: reading a FILE and a report, and changing a FILE.
//
// Nothing here touches the page, so the tests run it as it is. Nothing here judges a trip:
// what clashes, what is missing, how late people would be and what the plan is all come from
// the report that the reference checker gives.

export const FIRST = 12 * 60 + 30; // the day as drawn runs from 12:30 pm
export const LAST = 18 * 60; // to 6:00 pm
export const STEP = 5; // things move in steps of five minutes

// ---------------------------------------------------------------- times as the FILE writes them

/** Minutes after midnight in a time such as 2027-05-15T14:00:00-05:00[America/Chicago]. */
export function minutesOf(stamp) {
  const [, hours, minutes] = stamp.match(/T(\d\d):(\d\d)/);
  return Number(hours) * 60 + Number(minutes);
}

/** The same day and zone as `like`, at this many minutes after midnight. */
export function stampAt(like, minutes) {
  const two = (number) => String(number).padStart(2, "0");
  return like.replace(/T\d\d:\d\d/, `T${two(Math.floor(minutes / 60))}:${two(minutes % 60)}`);
}

/** Minutes in a length such as PT1H20M. Nothing, where the report gives no length. */
export function lengthOf(written) {
  const found = typeof written === "string" ? written.match(/^PT(?:(\d+)H)?(?:(\d+)M)?(?:0S)?$/) : null;
  return found ? Number(found[1] || 0) * 60 + Number(found[2] || 0) : null;
}

/** A length of this many minutes, as the FILE writes it. */
export function written(minutes) {
  if (minutes === 0) return "PT0S";
  const hours = Math.floor(minutes / 60);
  return `PT${hours ? hours + "H" : ""}${minutes % 60 ? (minutes % 60) + "M" : ""}`;
}

/** 870 as "2:30 pm". */
export function clock(minutes) {
  const whole = Math.round(minutes);
  const hour = Math.floor(whole / 60);
  return `${((hour + 11) % 12) + 1}:${String(whole % 60).padStart(2, "0")} ${hour < 12 ? "am" : "pm"}`;
}

/** 80 as "1 h 20 min". */
export function span(minutes) {
  const whole = Math.round(minutes);
  const hours = Math.floor(whole / 60);
  return [hours ? `${hours} h` : "", whole % 60 ? `${whole % 60} min` : ""].filter(Boolean).join(" ") || "0 min";
}

const snap = (minutes) => Math.round(minutes / STEP) * STEP;
const within = (low, value, high) => Math.min(high, Math.max(low, value));

// ---------------------------------------------------------------- reading a FILE and a report

const factOf = (file, option, key) => file.facts.find((fact) => fact.option === option && key in fact);

/** Which of the answers a report gives, from its data: feasible, risky, infeasible or undetermined. */
export function answerOf(report) {
  const found = report && report.json ? report.json : {};
  if (found.answer === "FEASIBLE") return found.robust === false ? "risky" : "feasible";
  if (found.answer === "INFEASIBLE") return "infeasible";
  if (found.answer === "UNDETERMINED") return "undetermined";
  return "refused";
}

/**
 * The lines of a report that go under the day: the answer, and every line that says what the
 * answer turns on. Each is a whole line of the report. `inset` marks a line that hangs from the
 * line above it: one case of several, or what would go wrong at a step.
 *
 * - UNDETERMINED: the whole report. It says what the FILE would have to say, as one condition or
 *   as every case of several, and then what else has to be true for that to help.
 * - FEASIBLE with a WARNING: each step that may go wrong, and what would go wrong at it.
 * - INFEASIBLE: the answer alone. The day and the FILE mark the records that the report lists.
 * - Words of the page's own, where the checker gave no answer: all of them.
 */
export function said(report, answer = answerOf(report)) {
  const lines = report.text.split("\n");
  const under = [];
  if (answer === "risky") {
    lines.forEach((line, at) => {
      if (!line.trim().startsWith("!")) return;
      // A line marked "!" is about the step above it, so the step is shown with it.
      const step = lines.slice(0, at).reverse().find((before) => before.trim() && !before.trim().startsWith("!"));
      if (step && !under.includes(step)) under.push(step);
      under.push(line);
    });
  } else if (answer !== "feasible" && answer !== "infeasible") {
    under.push(...lines.slice(1).filter((line) => line.trim()));
  }
  // A line that hangs from the one above it: a case of several, or what would go wrong at a step.
  const hangs = (line) => (answer === "risky" ? line.trim().startsWith("!") : /^\s/.test(line));
  return [lines[0], ...under].map((line) => ({ words: line.trim(), inset: line !== lines[0] && hangs(line) }));
}

/**
 * What the day shows, read from a FILE and, where there is one, the report on that FILE.
 * Every number is in minutes.
 *
 * From the FILE: what happens where and when, how long each ride takes, and when people must be
 * there. From the report: the records that clash, the plan, how late people would be at worst,
 * and the lengths the report asks for.
 */
export function scene(file, report) {
  const found = report && report.json ? report.json : {};
  const clash = new Set(found.conflict || []);
  const clashes = (...facts) => facts.some((fact) => fact && clash.has(fact.id));
  const lock = (option) => file.decisions.find((decision) => decision.lock === option);
  const planned = new Map((found.itinerary || []).filter((step) => step.option).map((step) => [step.option, step]));
  const items = [];
  const events = [];
  for (const option of file.options) {
    const time = factOf(file, option.id, "starts_at");
    const length = factOf(file, option.id, "duration");
    const range = factOf(file, option.id, "contingent_duration");
    const cutoff = factOf(file, option.id, "arrive_before_start");
    if (option.place) {
      const event = {
        kind: "event", id: option.id, name: option.name, place: option.place,
        start: minutesOf(time.starts_at), length: lengthOf(length.duration),
        cutoff: cutoff ? lengthOf(cutoff.arrive_before_start) : null,
        clash: clashes(time, length, lock(option.id)),
      };
      events.push(event);
      items.push(event);
    } else if (time) {
      items.push({
        kind: "departure", id: option.id, name: option.name, place: option.from, lands: option.to,
        start: minutesOf(time.starts_at), length: length ? lengthOf(length.duration) : null,
        cutoff: cutoff ? lengthOf(cutoff.arrive_before_start) : null,
        clash: clashes(time, lock(option.id)), clashCutoff: clashes(cutoff),
      });
    } else {
      items.push({
        kind: "ride", id: option.id, name: option.name, from: option.from, to: option.to,
        length: length ? lengthOf(length.duration) : range ? lengthOf(range.contingent_duration.shortest) : null,
        longest: range ? lengthOf(range.contingent_duration.longest) : null,
        clash: clashes(length, range),
      });
    }
  }
  // A ride that can start at any time is drawn where the plan puts it. Without a plan it is drawn
  // leaving when the last thing at its PLACE ends, or when the last thing that lands there lands.
  // That is a place to draw it, and no claim.
  const leaving = (place) => {
    const ends = [
      ...events.filter((event) => event.place === place).map((event) => event.start + event.length),
      ...items.filter((item) => item.kind === "departure" && item.lands === place && item.length !== null).map((item) => item.start + item.length),
    ];
    return ends.length ? Math.max(...ends) : FIRST + 30;
  };
  // When people must next be at a PLACE: the earliest start there, less the time to be there before it.
  const due = (place, after) => {
    const times = items.filter((item) => item.place === place).map((item) => item.start - (item.cutoff ?? 0)).filter((time) => time >= after);
    return times.length ? Math.min(...times) : null;
  };
  // A length to draw a ride with when nobody gives one: as far as the next thing at the PLACE it goes to.
  const asFarAs = (place, leaves) => {
    const by = due(place, leaves);
    return by === null ? 45 : Math.max(STEP, by - leaves);
  };
  // What the report asks for. It may ask for several things together, or offer several cases, so
  // the day shows a length it asks for and leaves the rest to the report's own words.
  const missing = (found.missing || []).flat();
  for (const ride of items.filter((item) => item.kind === "ride")) {
    const step = planned.get(ride.id);
    ride.leaves = step ? minutesOf(step.start) : leaving(ride.from);
    ride.taken = !found.itinerary || Boolean(step);
    const asked = missing.find((need) => need.what === "duration" && need.option === ride.id);
    ride.atMost = asked ? lengthOf(asked.at_most) : null;
    // The length the ride is drawn with: its own, or the one the report asks for.
    ride.shown = ride.length ?? ride.atMost ?? asFarAs(ride.to, ride.leaves);
  }
  // The gaps in the day that travel has to fill: something ends at one PLACE, and the next thing
  // is at another. Each has the time people can leave and the time by which they must be there.
  const timed = items.filter((item) => item.kind !== "ride").sort((one, other) => one.start - other.start);
  const gaps = [];
  timed.slice(0, -1).forEach((first, at) => {
    const next = timed[at + 1];
    if (first.length === null) return;
    gaps.push({ from: first.kind === "departure" ? first.lands : first.place, to: next.place, leaves: first.start + first.length, by: next.start - (next.cutoff ?? 0) });
  });
  // Each other way that the report asks about, once for each pair of PLACEs. It is drawn in the
  // tightest gap between those PLACEs, because that is where another way is needed most. That is
  // a place to draw it, and no claim.
  for (const other of missing.filter((need) => need.what === "other ways" && need.from && need.to)) {
    const id = `another-way-${other.from}-${other.to}`;
    if (items.some((item) => item.id === id)) continue;
    const atMost = lengthOf(other.at_most);
    const gap = gaps.filter((each) => each.from === other.from && each.to === other.to).sort((one, two) => one.by - one.leaves - (two.by - two.leaves))[0];
    const leaves = gap ? gap.leaves : leaving(other.from);
    const room = gap ? Math.max(STEP, gap.by - gap.leaves) : asFarAs(other.to, leaves);
    items.push({ kind: "ghost", id, from: other.from, to: other.to, leaves, atMost, shown: atMost ?? room });
  }
  // How late people would be at worst, where the report on a trip that may not hold says so.
  // Too late to arrive is counted from the time to be there. Still busy is counted from the start.
  const late = [];
  for (const worst of found.at_worst || []) {
    const item = items.find((each) => each.id === worst.option && each.place);
    const minutes = lengthOf(worst.late);
    if (!item || !minutes) continue;
    if (worst.constraint === "Each PERSON arrives in time") late.push({ place: item.place, from: item.start - (item.cutoff ?? 0), minutes });
    else if (worst.constraint === "Each PERSON is in one place at a time") late.push({ place: item.place, from: item.start, minutes });
  }
  // A lane for each PLACE where something on the day happens, leaves or lands.
  const places = file.places.filter((place) => items.some((item) => [item.place, item.from, item.to].includes(place.id)));
  return { items, places, late };
}

// ---------------------------------------------------------------- changing a FILE

/** The changes a reader can make. Each one edits records of the FILE and nothing else. */
export const change = {
  move(file, option, start) {
    const time = factOf(file, option, "starts_at");
    time.starts_at = stampAt(time.starts_at, start);
  },
  stretch(file, option, length) {
    factOf(file, option, "duration").duration = written(length);
  },
  /** How long a ride takes: one length, or a shortest and a longest when it may run late. */
  ride(file, option, length, longest) {
    const at = file.facts.findIndex((fact) => fact.option === option && ("duration" in fact || "contingent_duration" in fact));
    const id = at < 0 ? `${option}-length` : file.facts[at].id;
    const fact = longest > length
      ? { id, option, contingent_duration: { shortest: written(length), longest: written(longest) } }
      : { id, option, duration: written(length) };
    if (at < 0) file.facts.push(fact);
    else file.facts[at] = fact;
  },
  cutoff(file, option, before) {
    factOf(file, option, "arrive_before_start").arrive_before_start = written(before);
  },
  add(file, piece) {
    for (const list of ["places", "options", "ways", "wants", "facts", "decisions"]) {
      for (const record of piece[list] || []) file[list].push(structuredClone(record));
    }
  },
  remove(file, piece) {
    const options = new Set((piece.options || []).map((option) => option.id));
    for (const list of ["places", "options", "ways", "wants", "decisions"]) {
      const ids = new Set((piece[list] || []).map((record) => record.id));
      file[list] = file[list].filter((record) => !ids.has(record.id));
    }
    const facts = new Set((piece.facts || []).map((fact) => fact.id));
    file.facts = file.facts.filter((fact) => !facts.has(fact.id) && !options.has(fact.option));
  },
};

/** Whether the FILE holds what this piece adds. */
export const holds = (file, piece) =>
  (piece.options || []).every((option) => file.options.some((other) => other.id === option.id)) &&
  (piece.options ? true : (piece.facts || []).every((fact) => file.facts.some((other) => other.id === fact.id)));

/**
 * Apply one gesture to the FILE. `item` is the thing on the day as it was when the gesture began,
 * and `by` is how far the gesture has gone, in minutes. Says whether the FILE changed.
 */
export function gesture(file, act, item, by) {
  // Everything stays inside the day as drawn: 12:30 pm to 6:00 pm.
  if (act === "move" && item.kind === "departure") {
    // What leaves keeps the time to be there inside the day too.
    change.move(file, item.id, within(FIRST + (item.cutoff ?? 0), snap(item.start + by), LAST - 15));
  } else if (act === "move") {
    change.move(file, item.id, within(FIRST, snap(item.start + by), LAST - item.length));
  } else if (act === "stretch" && item.kind === "event") {
    change.stretch(file, item.id, within(15, snap(item.length + by), Math.min(240, LAST - item.start)));
  } else if (act === "cutoff" && item.cutoff !== null) {
    change.cutoff(file, item.id, within(0, snap(item.cutoff - by), Math.min(180, item.start - FIRST)));
  } else if (act === "ride" && item.kind === "ride") {
    // A ride of unknown length starts from the length it is drawn with.
    const length = within(0, snap(item.shown + by), 240);
    const range = item.length !== null && item.longest !== null ? item.longest - item.length : 0;
    change.ride(file, item.id, length, length + range);
  } else if (act === "late" && item.kind === "ride" && item.length !== null) {
    // How late a ride may run can be said only once its length is known.
    change.ride(file, item.id, item.length, within(item.length, snap((item.longest ?? item.length) + by), item.length + 120));
  } else {
    return false;
  }
  return true;
}

// ---------------------------------------------------------------- the FILE in words

/** A record on one line, spaced as the examples space theirs. */
function line(value) {
  if (Array.isArray(value)) return `[${value.map(line).join(", ")}]`;
  if (value && typeof value === "object") {
    return `{ ${Object.entries(value).map(([key, inner]) => `${JSON.stringify(key)}: ${line(inner)}`).join(", ")} }`;
  }
  return JSON.stringify(value);
}

/** The whole FILE as text, one record to a line. */
export function text(file) {
  const lists = Object.entries(file).map(([key, records]) =>
    records.length
      ? `  ${JSON.stringify(key)}: [\n${records.map((record) => `    ${line(record)}`).join(",\n")}\n  ]`
      : `  ${JSON.stringify(key)}: []`,
  );
  return `{\n${lists.join(",\n")}\n}\n`;
}

/** A line of the FILE without its indent or its closing comma, for comparing two FILEs. */
export function bare(each) {
  return each.trim().replace(/,$/, "");
}
