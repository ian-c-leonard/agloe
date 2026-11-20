// The trip on the home page: a day the reader can change, the FILE it is drawn from, and the
// reference checker's answer.
//
// The day is always drawn from a FILE. At first that FILE is one of the examples the page
// carries, shown with the report the example expects. When the reader moves, stretches or adds
// something, the FILE changes, and the reference checker of this repository checks the new FILE
// in the reader's browser (see checker-worker.js). Nothing here decides whether a trip works.

const SVG = "http://www.w3.org/2000/svg";
const FIRST = 12 * 60 + 30; // the day as drawn runs from 12:30 pm
const LAST = 18 * 60; // to 6:00 pm
const STEP = 5; // things move in steps of five minutes
const still = matchMedia("(prefers-reduced-motion: reduce)").matches;

const trip = document.getElementById("trip");

// ---------------------------------------------------------------- times as the FILE writes them

/** Minutes after midnight in a time such as 2027-05-15T14:00:00-05:00[America/Chicago]. */
function minutesOf(stamp) {
  const [, hours, minutes] = stamp.match(/T(\d\d):(\d\d)/);
  return Number(hours) * 60 + Number(minutes);
}

/** The same day and zone as `like`, at this many minutes after midnight. */
function stampAt(like, minutes) {
  const two = (number) => String(number).padStart(2, "0");
  return like.replace(/T\d\d:\d\d/, `T${two(Math.floor(minutes / 60))}:${two(minutes % 60)}`);
}

/** Minutes in a length such as PT1H20M. */
function lengthOf(written) {
  const [, hours, minutes] = written.match(/^PT(?:(\d+)H)?(?:(\d+)M)?(?:0S)?$/);
  return Number(hours || 0) * 60 + Number(minutes || 0);
}

/** A length of this many minutes, as the FILE writes it. */
function written(minutes) {
  if (minutes === 0) return "PT0S";
  const hours = Math.floor(minutes / 60);
  return `PT${hours ? hours + "H" : ""}${minutes % 60 ? (minutes % 60) + "M" : ""}`;
}

/** 870 as "2:30 pm". */
function clock(minutes) {
  const hour = Math.floor(minutes / 60);
  return `${((hour + 11) % 12) + 1}:${String(minutes % 60).padStart(2, "0")} ${hour < 12 ? "am" : "pm"}`;
}

/** 80 as "1 h 20 min". */
function span(minutes) {
  const hours = Math.floor(minutes / 60);
  return [hours ? `${hours} h` : "", minutes % 60 ? `${minutes % 60} min` : ""].filter(Boolean).join(" ") || "0 min";
}

const snap = (minutes) => Math.round(minutes / STEP) * STEP;
const within = (low, value, high) => Math.min(high, Math.max(low, value));

// ---------------------------------------------------------------- reading and changing a FILE

const factOf = (file, option, key) => file.facts.find((fact) => fact.option === option && key in fact);

/**
 * What the day shows, read from a FILE and, where there is one, the report on it.
 * Every number is in minutes. Nothing here judges the trip: what clashes, what is missing and
 * what the plan is all come from the report.
 */
function scene(file, report) {
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
  const missing = (found.missing || []).flat();
  for (const ride of items.filter((item) => item.kind === "ride")) {
    // A ride that can start at any time is drawn where the plan puts it. Without a plan it is
    // drawn leaving when the last thing at its PLACE ends.
    const step = planned.get(ride.id);
    const before = events.filter((event) => event.place === ride.from).map((event) => event.start + event.length);
    ride.leaves = step ? minutesOf(step.start) : before.length ? Math.max(...before) : FIRST + 30;
    ride.taken = !found.itinerary || Boolean(step);
    const asked = missing.find((need) => need.what === "duration" && need.option === ride.id);
    ride.atMost = asked ? lengthOf(asked.at_most) : null;
    ride.by = deadline[ride.to] ?? null;
  }
  const other = missing.find((need) => need.what === "other ways");
  if (other) {
    const before = events.filter((event) => event.place === other.from).map((event) => event.start + event.length);
    const leaves = before.length ? Math.max(...before) : FIRST + 30;
    items.push({ kind: "ghost", id: "another-way", from: other.from, to: other.to, leaves, atMost: lengthOf(other.at_most) });
  }
  const worst = (found.at_worst || []).find((late) => late.late);
  // A lane for each PLACE where something on the day happens, leaves or lands.
  const places = file.places.filter((place) => items.some((item) => [item.place, item.from, item.to].includes(place.id)));
  return {
    items, places, deadline,
    complete: file.facts.some((fact) => fact.complete),
    completeClash: file.facts.some((fact) => fact.complete && clash.has(fact.id)),
    lateAtWorst: worst ? { option: worst.option, minutes: lengthOf(worst.late) } : null,
  };
}

/** The changes a reader can make. Each one edits records of the FILE and nothing else. */
const change = {
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

const holds = (file, piece) =>
  (piece.options || []).every((option) => file.options.some((other) => other.id === option.id)) &&
  (piece.options ? true : (piece.facts || []).every((fact) => file.facts.some((other) => other.id === fact.id)));

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
function text(file) {
  const lists = Object.entries(file).map(([key, records]) =>
    records.length
      ? `  ${JSON.stringify(key)}: [\n${records.map((record) => `    ${line(record)}`).join(",\n")}\n  ]`
      : `  ${JSON.stringify(key)}: []`,
  );
  return `{\n${lists.join(",\n")}\n}\n`;
}

// ---------------------------------------------------------------- the page

function start() {
  const stories = {};
  for (const input of trip.querySelectorAll('input[name="version"]')) {
    const version = input.value;
    const words = trip.querySelector(`pre.file-text[data-version="${version}"]`).textContent;
    stories[version] = {
      input, words, file: JSON.parse(words),
      report: {
        text: trip.querySelector(`.report[data-version="${version}"] pre`).textContent,
        json: JSON.parse(trip.querySelector(`pre.report-data[data-version="${version}"]`).textContent),
      },
    };
  }
  const versions = Object.keys(stories);
  const firstLines = new Set(stories[versions[0]].words.split("\n").map(bare));
  const day = trip.querySelector("#day");
  const tools = trip.querySelector("#tools");
  const fileLive = trip.querySelector("#file-live");
  const reportLive = trip.querySelector("#report-live");
  const reportText = trip.querySelector("#report-text");
  const reportNote = trip.querySelector("#report-note");
  const answerLive = trip.querySelector("#answer-live");
  const playing = trip.querySelector("#playing");

  let pieces = {}; // what a reader can add, from trip/additions.json
  let now = { version: versions[0], file: structuredClone(stories[versions[0]].file), report: stories[versions[0]].report };
  let drawn = null; // the scene on the page, for moving smoothly to the next one
  let scrolledTo = ""; // the changed line that the FILE last scrolled to
  let moving = 0;

  // ------------------------------------------------------------ the checker

  const checker = { worker: null, ready: false, running: null, waiting: null, serial: 0, broken: "", slow: 0 };

  function wake() {
    if (checker.worker || checker.broken) return;
    try {
      checker.worker = new Worker(new URL("checker-worker.js", import.meta.url), { type: "module" });
    } catch (problem) {
      checker.broken = String(problem);
      return;
    }
    checker.worker.onmessage = ({ data }) => {
      if (data.ready) {
        checker.ready = true;
      } else if (checker.running && data.id === checker.running.id) {
        const asked = checker.running;
        checker.running = null;
        if (checker.waiting === null && now.version === null) settle(asked, data);
      } else if (data.failed && data.id === undefined) {
        checker.broken = data.failed;
      }
      pump();
    };
    checker.worker.onerror = (event) => {
      checker.broken = event.message || "the checker could not start";
      note();
    };
  }

  /** Send the newest FILE when the checker is free. A check that runs long gives way to a newer FILE. */
  function pump() {
    if (checker.broken) return note();
    wake();
    if (checker.running && checker.waiting !== null && performance.now() - checker.running.started > 1500) {
      checker.worker.terminate();
      Object.assign(checker, { worker: null, ready: false, running: null });
      wake();
    }
    if (checker.ready && !checker.running && checker.waiting !== null) {
      checker.running = { id: ++checker.serial, started: performance.now() };
      checker.worker.postMessage({ id: checker.running.id, file: checker.waiting });
      checker.waiting = null;
    }
    clearTimeout(checker.slow);
    if (checker.running || checker.waiting !== null) checker.slow = setTimeout(pump, 400);
    note();
  }

  function ask() {
    checker.waiting = JSON.stringify(now.file);
    pump();
  }

  function settle(asked, data) {
    if (data.refused || data.failed) {
      now.report = { text: data.refused ? `This FILE does not follow the format:\n  ${data.refused.join("\n  ")}` : `The checker stopped: ${data.failed}`, json: {} };
    } else {
      now.report = { text: data.text, json: data.json, seconds: data.seconds };
    }
    show();
  }

  /** The line under the report that says where the answer came from. */
  function note() {
    if (now.version !== null) return;
    const waiting = checker.running || checker.waiting !== null;
    const long = checker.running && performance.now() - checker.running.started > 1200;
    trip.classList.toggle("checking", Boolean(waiting));
    reportNote.textContent = checker.broken
      ? "The checker could not load here. The four versions above still show their reports."
      : !checker.ready
        ? "Loading the reference checker. It is the real one, so it takes a moment the first time."
        : long
          ? "Still checking. The reference checker tries every order, so a busier day takes it longer."
          : waiting
            ? "Checking."
            : now.report && now.report.seconds !== undefined
              ? `Checked in your browser by the reference checker, in ${Math.max(1, Math.round(now.report.seconds * 1000))} ms.`
              : "";
  }

  // ------------------------------------------------------------ showing a FILE and its report

  function answerOf(report) {
    const first = report.text.split("\n")[0];
    if (first.startsWith("FEASIBLE, with a WARNING")) return "risky";
    if (first.startsWith("FEASIBLE")) return "feasible";
    if (first.startsWith("INFEASIBLE")) return "infeasible";
    if (first.startsWith("UNDETERMINED")) return "undetermined";
    return "refused";
  }

  /** Put the current FILE, its report and the day on the page. */
  function show(smooth = false) {
    const own = now.version === null;
    trip.classList.toggle("own", own);
    trip.dataset.answer = now.report ? answerOf(now.report) : "waiting";
    const found = now.report && now.report.json ? now.report.json : {};
    const marked = new Set([...(found.conflict || [])]);
    // The FILE, with the lines that differ from the first version marked, and the lines that clash.
    const words = own ? text(now.file) : stories[now.version].words;
    const target = own ? fileLive : trip.querySelector(`pre.file-text[data-version="${now.version}"]`);
    target.replaceChildren(
      ...words.replace(/\n$/, "").split("\n").map((each) => {
        const row = document.createElement("span");
        row.textContent = each;
        const id = (each.match(/"id": "([^"]+)"/) || [])[1];
        if (id && marked.has(id)) row.className = "clash";
        else if (!firstLines.has(bare(each))) row.className = "new";
        return row;
      }),
    );
    const changed = target.querySelector(".clash, .new");
    const which = changed ? changed.textContent.slice(0, 40) + target.id : "";
    if (changed && which !== scrolledTo) target.scrollTop = Math.max(0, changed.getBoundingClientRect().top - target.getBoundingClientRect().top + target.scrollTop - 70);
    scrolledTo = which;
    if (own && now.report) {
      const lines = now.report.text.split("\n");
      const answer = answerOf(now.report);
      // Under the answer goes the line of the report that says what it turns on.
      const next = answer === "undetermined" ? lines.slice(1).find((each) => each.trim()) : answer === "risky" ? lines.find((each) => each.trim().startsWith("!")) : "";
      answerLive.className = `answer live ${answer}`;
      answerLive.replaceChildren(...[lines[0], (next || "").trim()].filter(Boolean).map((each) => Object.assign(document.createElement("p"), { textContent: each })));
      reportText.textContent = now.report.text;
      reportLive.className = `report live ${answer}`;
    }
    note();
    for (const button of tools.querySelectorAll("[data-add]")) {
      const piece = pieces[button.dataset.add];
      if (piece) button.setAttribute("aria-pressed", String(holds(now.file, piece)));
    }
    const complete = tools.querySelector("#complete");
    if (complete && pieces.complete) complete.checked = holds(now.file, pieces.complete);
    const next = scene(now.file, now.report);
    if (smooth && drawn && !still) glide(drawn, next);
    else draw(next);
  }

  /** Move the day from one scene to the next over a short time. */
  function glide(from, to) {
    const began = performance.now();
    const run = ++moving;
    const old = new Map(from.items.map((item) => [item.id, item]));
    const frame = (time) => {
      if (run !== moving) return;
      const part = Math.min(1, (time - began) / 650);
      const eased = 1 - (1 - part) ** 3;
      const between = to.items.map((item) => {
        const was = old.get(item.id);
        if (!was || was.kind !== item.kind) return { ...item, faint: eased };
        const mixed = { ...item };
        for (const key of ["start", "length", "longest", "leaves", "cutoff"]) {
          if (typeof item[key] === "number" && typeof was[key] === "number") mixed[key] = was[key] + (item[key] - was[key]) * eased;
        }
        return mixed;
      });
      draw({ ...to, items: between }, part < 1);
      if (part < 1) requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
  }

  // ------------------------------------------------------------ drawing the day

  function make(name, attributes = {}, ...children) {
    const element = document.createElementNS(SVG, name);
    for (const [key, value] of Object.entries(attributes)) {
      if (value === null || value === undefined) continue;
      if (key === "hint") element.append(Object.assign(document.createElementNS(SVG, "title"), { textContent: value }));
      else element.setAttribute(key, value);
    }
    element.append(...children);
    return element;
  }

  function draw(view, passing = false) {
    if (!passing) drawn = view;
    const wide = day.clientWidth;
    const tall = wide < 620; // on a narrow screen time runs down the page
    const lanes = view.places.map((place) => place.id);
    // Along the day: `at(minutes)` in pixels. Across it: each PLACE has a lane.
    const edge = tall ? 30 : 26;
    const gutter = tall ? 50 : 0;
    const length = tall ? Math.round((LAST - FIRST) * 1.75) : wide - 14;
    const perMinute = length / (LAST - FIRST);
    const at = (minutes) => (tall ? edge : 7) + (minutes - FIRST) * perMinute;
    const laneSize = tall ? Math.floor((wide - gutter - 44) / Math.max(1, lanes.length)) : 50;
    const gap = tall ? 44 : 84;
    const laneAt = (place) => (tall ? gutter : edge + 22) + lanes.indexOf(place) * (laneSize + gap);
    const across = (tall ? gutter : edge + 22) + lanes.length * laneSize + (lanes.length - 1) * gap + (tall ? 0 : 14);
    const size = tall ? [wide, at(LAST) + 16] : [wide, across];
    // A point from "minutes along, pixels across".
    const point = (minutes, cross) => (tall ? [cross, at(minutes)] : [at(minutes), cross]);
    const box = (minutes, cross, minutesLong, crossSize) => {
      const [x, y] = point(minutes, cross);
      return tall ? { x, y, width: crossSize, height: minutesLong * perMinute } : { x, y, width: minutesLong * perMinute, height: crossSize };
    };

    const svg = make("svg", { viewBox: `0 0 ${size[0]} ${size[1]}`, width: size[0], height: size[1], role: "group", "aria-label": "The day, drawn from the FILE" });
    const defs = make("defs");
    defs.append(
      make("pattern", { id: "may-run-late", width: 8, height: 8, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" }, make("rect", { width: 4, height: 8, class: "hatch-brass" })),
      make("pattern", { id: "too-late", width: 8, height: 8, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" }, make("rect", { width: 4, height: 8, class: "hatch-stop" })),
    );
    svg.append(defs);

    // The hours, and a lane for each PLACE.
    for (let hour = Math.ceil(FIRST / 60) * 60; hour <= LAST; hour += 60) {
      const [x1, y1] = point(hour, tall ? gutter - 6 : edge);
      const [x2, y2] = point(hour, tall ? wide : across);
      svg.append(make("line", { class: "hour", x1, y1, x2, y2 }));
      const label = make("text", { class: "hour-name", x: tall ? gutter - 12 : x1, y: tall ? y1 + 4 : edge - 9, "text-anchor": tall ? "end" : "middle" });
      label.textContent = clock(hour).replace(":00", "");
      svg.append(label);
    }
    for (const place of view.places) {
      const lane = box(FIRST, laneAt(place.id), LAST - FIRST, laneSize);
      svg.append(make("rect", { class: "lane", ...lane, rx: 9 }));
      const name = make("text", { class: "lane-name", x: tall ? lane.x + laneSize / 2 : lane.x + 12, y: tall ? edge - 12 : lane.y - 8, "text-anchor": tall ? "middle" : "start" });
      name.textContent = place.name.replace(/^the /, "");
      svg.append(name);
    }

    const under = make("g");
    const over = make("g");
    svg.append(under, over);
    const roads = {}; // how many roads already run between each pair of PLACEs

    for (const item of view.items) {
      const faint = item.faint === undefined ? null : item.faint;
      if (item.kind === "event") {
        const shape = box(item.start, laneAt(item.place) + 5, item.length, laneSize - 10);
        const group = make("g", { class: `event${item.clash ? " clash" : ""}`, opacity: faint, tabindex: 0, role: "slider", "data-act": "move", "data-id": item.id,
          "aria-label": `${item.name}, ${clock(item.start)} to ${clock(item.start + item.length)}. Arrow keys move it. Shift and the arrow keys make it longer or shorter.`,
          "aria-valuetext": `${clock(item.start)} to ${clock(item.start + item.length)}`, "aria-valuenow": item.start, "aria-valuemin": FIRST, "aria-valuemax": LAST });
        group.append(make("rect", { class: "block", ...shape, rx: 7 }));
        const clip = `clip-${item.id}`;
        defs.append(make("clipPath", { id: clip }, make("rect", { ...shape })));
        const words = make("g", { "clip-path": `url(#${clip})` });
        const title = make("text", { class: "block-name", x: shape.x + 10, y: shape.y + (tall ? 20 : laneSize / 2 - 8) });
        title.textContent = item.name;
        const times = make("text", { class: "block-time", x: shape.x + 10, y: shape.y + (tall ? 36 : laneSize / 2 + 8) });
        // A short block has room for the start alone.
        times.textContent = tall
          ? shape.height > 40 ? `${clock(item.start).replace(/ [ap]m$/, "")} to ${clock(item.start + item.length).replace(/ [ap]m$/, "")}` : ""
          : shape.width > 128 ? `${clock(item.start)} to ${clock(item.start + item.length)}` : clock(item.start);
        words.append(title, times);
        group.append(words);
        // The end that stretches.
        const [gx, gy] = point(item.start + item.length, laneAt(item.place) + laneSize / 2);
        group.append(make("rect", { class: "grip", hint: "Pull to make it longer or shorter", "data-act": "stretch", "data-id": item.id, x: tall ? shape.x + shape.width / 2 - 16 : gx - 11, y: tall ? gy - 11 : shape.y + shape.height / 2 - 16, width: tall ? 32 : 14, height: tall ? 14 : 32, rx: 4 }));
        group.append(make("path", { class: "grip-mark", d: tall ? `M${shape.x + shape.width / 2 - 7} ${gy - 5}h14` : `M${gx - 5} ${shape.y + shape.height / 2 - 7}v14` }));
        over.append(group);
      } else if (item.kind === "departure") {
        const lane = laneAt(item.place);
        const shape = box(item.start, lane + 5, LAST - item.start, laneSize - 10);
        const group = make("g", { class: `departure${item.clash ? " clash" : ""}`, opacity: faint, tabindex: 0, role: "slider", "data-act": "move", "data-id": item.id,
          "aria-label": `${item.name}, leaves at ${clock(item.start)}. Arrow keys move it.`, "aria-valuetext": clock(item.start), "aria-valuenow": item.start, "aria-valuemin": FIRST, "aria-valuemax": LAST });
        const fade = `fade-${item.id}`;
        defs.append(make("linearGradient", { id: fade, x1: 0, y1: 0, x2: tall ? 0 : 1, y2: tall ? 1 : 0 },
          make("stop", { offset: 0.55, class: "road-stop" }), make("stop", { offset: 1, class: "road-stop", "stop-opacity": 0 })));
        group.append(make("rect", { class: "block road", ...shape, rx: 7, style: `fill: url(#${fade})` }));
        const title = make("text", { class: "block-name", x: shape.x + 10, y: shape.y + (tall ? 20 : laneSize / 2 - 8) });
        title.textContent = item.name;
        const times = make("text", { class: "block-time", x: shape.x + 10, y: shape.y + (tall ? 36 : laneSize / 2 + 8) });
        times.textContent = clock(item.start);
        group.append(title, times);
        over.append(group);
        if (item.cutoff !== null) {
          // The time by which people must be there: a line across the gap that rides have to reach.
          const when = item.start - item.cutoff;
          const [x1, y1] = point(when, lane - gap + 6);
          const [x2, y2] = point(when, lane + laneSize);
          const mark = make("g", { class: `cutoff${item.clashCutoff ? " clash" : ""}`, opacity: faint, tabindex: 0, role: "slider", "data-act": "cutoff", "data-id": item.id,
            "aria-label": `People must be at the place ${span(item.cutoff)} before ${item.name} leaves, by ${clock(when)}. Arrow keys move it.`, "aria-valuetext": clock(when), "aria-valuenow": when, "aria-valuemin": FIRST, "aria-valuemax": LAST });
          mark.append(make("line", { class: "cutoff-line", x1, y1, x2, y2 }));
          const [rx, ry] = point(when, lane + laneSize);
          mark.append(make("circle", { class: "cutoff-ring", cx: rx, cy: ry, r: 8 }));
          mark.append(make("circle", { class: "cutoff-hit", cx: rx, cy: ry, r: 16 }));
          const label = make("text", { class: "cutoff-name", x: tall ? x2 - 14 : x1 + 9, y: tall ? y2 + 15 : y1 + 12, "text-anchor": tall ? "end" : "start" });
          label.textContent = `Be there by ${clock(when)}`;
          mark.append(label);
          over.append(mark);
        }
      } else {
        // A ride, or the other way that the report asks about: a road from one PLACE to the next.
        const down = lanes.indexOf(item.to) > lanes.indexOf(item.from);
        const fromEdge = laneAt(item.from) + (down ? laneSize - 4 : 4);
        const toEdge = laneAt(item.to) + (down ? 4 : laneSize - 4);
        const ghost = item.kind === "ghost";
        const known = item.length !== null && !ghost;
        const takes = known ? item.length : item.atMost ?? (item.by !== null && item.by !== undefined ? Math.max(15, item.by - item.leaves) : 45);
        const [x1, y1] = point(item.leaves, fromEdge);
        const [x2, y2] = point(item.leaves + takes, toEdge);
        const group = make("g", { class: `ride${known ? "" : " unknown"}${ghost ? " ghost" : ""}${item.clash ? " clash" : ""}${item.taken === false ? " idle" : ""}`, opacity: faint });
        if (known && item.longest !== null && item.longest > item.length) {
          const [x3, y3] = point(item.leaves + item.longest, toEdge);
          group.append(make("path", { class: "may-run-late", d: `M${x1} ${y1}L${x2} ${y2}L${x3} ${y3}Z` }));
        }
        group.append(make("line", { class: "road-line", x1, y1, x2, y2 }));
        const angle = tall ? 0 : (Math.atan2(y2 - y1, x2 - x1) * 180) / Math.PI;
        const [mx, my] = [(x1 + x2) / 2, (y1 + y2) / 2];
        const nth = (roads[`${item.from} ${item.to}`] = (roads[`${item.from} ${item.to}`] ?? -1) + 1);
        const label = make("text", { class: "road-name", x: mx, y: my, dy: tall ? nth * 15 : nth % 2 ? 22 : -11, dx: tall ? 12 : 0, "text-anchor": tall ? "start" : "middle", transform: tall ? null : `rotate(${angle} ${mx} ${my})` });
        label.textContent = ghost
          ? `Another way? ${span(item.atMost)} or less`
          : known
            ? `${item.name.replace(/ to .*/, "")} · ${item.longest ? `${span(item.length)} to ${span(item.longest)}` : span(item.length)}`
            : `${item.name.replace(/ to .*/, "")} · ${item.atMost ? `? works if ${span(item.atMost)} or less` : "nobody knows how long"}`;
        group.append(label);
        under.append(group);
        if (!ghost) {
          const end = make("circle", { class: "road-end", cx: x2, cy: y2, r: 9, tabindex: 0, role: "slider", "data-act": "ride", "data-id": item.id,
            "aria-label": known ? `${item.name} takes ${span(item.length)}. Arrow keys change it. Shift and the arrow keys say how late it may run.` : `Nobody has recorded how long ${item.name} takes. Arrow keys set it.`,
            "aria-valuetext": known ? span(item.length) : "not recorded", "aria-valuenow": known ? item.length : 0, "aria-valuemin": 0, "aria-valuemax": 240 });
          over.append(end);
          if (known) {
            const late = item.longest ?? item.length;
            const [lx, ly] = point(item.leaves + late, toEdge);
            over.append(make("circle", { class: `late-end${late > item.length ? " set" : ""}`, hint: "Pull to say how late it may run", cx: tall ? lx : lx + (late > item.length ? 0 : 20), cy: tall ? ly + (late > item.length ? 0 : 20) : ly, r: 6, "data-act": "late", "data-id": item.id }));
          }
        }
        // Where the ride lands after the time people must be there, the lateness is marked.
        if (known && item.by !== null && item.by !== undefined && item.taken !== false) {
          const lands = item.leaves + (item.longest ?? item.length);
          if (lands > item.by) {
            const late = box(item.by, toEdge - (down ? 9 : 0), lands - item.by, 9);
            under.append(make("rect", { class: item.leaves + item.length > item.by ? "too-late" : "late-at-worst", ...late, rx: 2 }));
          }
        }
      }
    }
    day.classList.toggle("tall", tall);
    // The day is drawn afresh each time, so whatever had the keyboard's focus is given it back.
    const focused = day.contains(document.activeElement) ? document.activeElement.dataset : null;
    day.replaceChildren(svg);
    if (focused && focused.act) day.querySelector(`[data-act="${focused.act}"][data-id="${focused.id}"]`)?.focus();
    day.style.minHeight = `${size[1]}px`;
  }

  // ------------------------------------------------------------ changing the day

  /** The reader has changed the trip: it is their own version now, and the checker checks it. */
  function mine(edit) {
    if (now.version !== null) {
      now = { version: null, file: structuredClone(now.file), report: now.report };
      stop();
      for (const story of Object.values(stories)) story.input.checked = false;
    }
    edit(now.file);
    now.report = now.report ? { ...now.report, seconds: undefined } : null;
    show();
    ask();
  }

  function itemOf(id) {
    return scene(now.file, now.report).items.find((item) => item.id === id);
  }

  /** Apply one gesture: `by` is how far it has gone, in minutes. `from` is the item as it was. */
  function gesture(act, from, by) {
    mine((file) => {
      if (act === "move") change.move(file, from.id, within(FIRST, snap(from.start + by), LAST - (from.length || 15)));
      if (act === "stretch") change.stretch(file, from.id, within(15, snap(from.length + by), 240));
      if (act === "cutoff") change.cutoff(file, from.id, within(0, snap(from.cutoff - by), 180));
      if (act === "ride") {
        const length = within(10, snap((from.length ?? from.atMost ?? 45) + by), 240);
        change.ride(file, from.id, length, from.longest ? Math.max(length, from.longest + (length - (from.length ?? length))) : length);
      }
      if (act === "late") change.ride(file, from.id, from.length, within(from.length, snap((from.longest ?? from.length) + by), from.length + 120));
    });
  }

  let held = null;
  day.addEventListener("pointerdown", (event) => {
    const target = event.target.closest("[data-act]");
    if (!target) return;
    const from = itemOf(target.dataset.id);
    if (!from) return;
    held = { act: target.dataset.act, from, x: event.clientX, y: event.clientY, tall: day.clientWidth < 620 };
    day.setPointerCapture(event.pointerId);
    day.classList.add("holding");
    event.preventDefault();
  });
  day.addEventListener("pointermove", (event) => {
    if (!held) return;
    const length = held.tall ? Math.round((LAST - FIRST) * 1.75) : day.clientWidth - 14;
    const by = ((held.tall ? event.clientY - held.y : event.clientX - held.x) / length) * (LAST - FIRST);
    if (snap(by) !== held.last) {
      held.last = snap(by);
      gesture(held.act, held.from, by);
    }
  });
  const release = () => {
    held = null;
    day.classList.remove("holding");
  };
  // A finger that lands on something that moves drags it. Without this the page would scroll instead.
  day.addEventListener("touchstart", (event) => event.target.closest("[data-act]") && event.preventDefault(), { passive: false });
  day.addEventListener("pointerup", release);
  day.addEventListener("pointercancel", release);
  day.addEventListener("keydown", (event) => {
    const target = event.target.closest("[data-act]");
    const way = { ArrowLeft: -STEP, ArrowUp: -STEP, ArrowRight: STEP, ArrowDown: STEP }[event.key];
    if (!target || !way) return;
    event.preventDefault();
    const from = itemOf(target.dataset.id);
    const act = target.dataset.act;
    gesture(event.shiftKey ? (act === "move" && from.kind === "event" ? "stretch" : act === "ride" ? "late" : act) : act, from, way);
  });

  tools.addEventListener("click", (event) => {
    const button = event.target.closest("[data-add]");
    if (!button) return;
    const piece = pieces[button.dataset.add];
    mine((file) => (holds(file, piece) ? change.remove(file, piece) : change.add(file, piece)));
  });
  tools.querySelector("#complete").addEventListener("change", (event) => {
    mine((file) => (event.target.checked ? change.add(file, pieces.complete) : change.remove(file, pieces.complete)));
  });

  // ------------------------------------------------------------ the story that plays by itself

  const PACE = 5600; // how long each version of the story stays, in milliseconds
  const answers = trip.querySelector(".answers-now");
  // The story waits while the pointer is over the day, and while the day is out of sight.
  const story = { timer: 0, spent: 0, near: false, seen: true };
  function tell(version, smooth = true) {
    stories[version].input.checked = true;
    now = { version, file: structuredClone(stories[version].file), report: stories[version].report };
    show(smooth);
  }
  function stop() {
    clearInterval(story.timer);
    story.timer = 0;
    trip.classList.remove("playing");
    playing.setAttribute("aria-pressed", "false");
    playing.textContent = "Play the story";
    answers.setAttribute("aria-live", "polite");
  }
  function play() {
    if (now.version === null) tell(versions[0]);
    story.spent = 0;
    trip.classList.add("playing");
    playing.setAttribute("aria-pressed", "true");
    playing.textContent = "Pause the story";
    // A story that plays by itself is not read out at every step.
    answers.setAttribute("aria-live", "off");
    clearInterval(story.timer);
    story.timer = setInterval(() => {
      if (document.hidden || story.near || !story.seen) return;
      story.spent += 100;
      if (story.spent >= PACE) {
        story.spent = 0;
        tell(versions[(versions.indexOf(now.version) + 1) % versions.length]);
      }
      trip.style.setProperty("--told", String(story.spent / PACE));
    }, 100);
  }
  day.addEventListener("pointerenter", () => (story.near = true));
  day.addEventListener("pointerleave", () => (story.near = false));
  new IntersectionObserver((seen) => (story.seen = seen.some((entry) => entry.isIntersecting)), { threshold: 0.25 }).observe(day);
  playing.addEventListener("click", () => (story.timer ? stop() : play()));
  for (const version of versions) {
    stories[version].input.addEventListener("change", () => {
      stop();
      tell(version);
    });
  }
  // The checker starts to load when the reader shows interest, so it is ready by the first change.
  for (const kind of ["pointerenter", "focusin", "touchstart"]) trip.addEventListener(kind, wake, { once: true, passive: true });
  day.addEventListener("pointerdown", stop);

  fetch(new URL("trip/additions.json", import.meta.url))
    .then((reply) => reply.json())
    .then((found) => {
      pieces = found;
      tools.hidden = false;
      show();
    })
    .catch(() => {});

  trip.classList.add("alive");
  new ResizeObserver(() => draw(scene(now.file, now.report))).observe(day);
  show();
  if (!still) play();
}

/** A line of the FILE without its indent or its closing comma, for comparing two FILEs. */
function bare(each) {
  return each.trim().replace(/,$/, "");
}

if (trip) start();
