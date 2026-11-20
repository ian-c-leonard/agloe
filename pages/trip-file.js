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
  const hour = Math.floor(minutes / 60);
  return `${((hour + 11) % 12) + 1}:${String(minutes % 60).padStart(2, "0")} ${hour < 12 ? "am" : "pm"}`;
}

/** 80 as "1 h 20 min". */
export function span(minutes) {
  const hours = Math.floor(minutes / 60);
  return [hours ? `${hours} h` : "", minutes % 60 ? `${minutes % 60} min` : ""].filter(Boolean).join(" ") || "0 min";
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
        kind: "departure", id: option.id, name: option.name, place: option.from,
        start: minutesOf(time.starts_at), cutoff: cutoff ? lengthOf(cutoff.arrive_before_start) : null,
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
  // The time by which people must be at each PLACE: the earliest cutoff of what leaves from it.
  const deadline = {};
  for (const item of items) {
    if (item.kind !== "departure" || item.cutoff === null) continue;
    deadline[item.place] = Math.min(deadline[item.place] ?? Infinity, item.start - item.cutoff);
  }
  // A ride that can start at any time is drawn where the plan puts it. Without a plan it is drawn
  // leaving when the last thing at its PLACE ends. That is a place to draw it, and no claim.
  const leaving = (place) => {
    const ends = events.filter((event) => event.place === place).map((event) => event.start + event.length);
    return ends.length ? Math.max(...ends) : FIRST + 30;
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
    // The length the ride is drawn with: its own, or the one the report asks for, or as far as the cutoff.
    const by = deadline[ride.to] ?? null;
    ride.shown = ride.length ?? ride.atMost ?? (by !== null ? Math.max(15, by - ride.leaves) : 45);
  }
  const other = missing.find((need) => need.what === "other ways" && need.from && need.to);
  if (other) {
    const atMost = lengthOf(other.at_most);
    items.push({ kind: "ghost", id: "another-way", from: other.from, to: other.to, leaves: leaving(other.from), atMost, shown: atMost ?? 45 });
  }
  // How late people would be at worst, where the report on a trip that may not hold says so.
  const late = [];
  for (const worst of found.at_worst || []) {
    const item = items.find((each) => each.id === worst.option && each.place);
    const minutes = lengthOf(worst.late);
    if (item && minutes) late.push({ place: item.place, from: item.start - (item.cutoff ?? 0), minutes });
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
  if (act === "move") {
    change.move(file, item.id, within(FIRST, snap(item.start + by), LAST - (item.length || 15)));
  } else if (act === "stretch" && item.kind === "event") {
    change.stretch(file, item.id, within(15, snap(item.length + by), 240));
  } else if (act === "cutoff" && item.cutoff !== null) {
    change.cutoff(file, item.id, within(0, snap(item.cutoff - by), 180));
  } else if (act === "ride" && item.kind === "ride") {
    // A ride of unknown length starts from the length it is drawn with.
    const length = within(10, snap(item.shown + by), 240);
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
