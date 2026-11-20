// The trip on the home page: a day the reader can change, the FILE it is drawn from, and the
// reference checker's answer.
//
// The day is always drawn from a FILE. At first that FILE is one of the examples the page
// carries, shown with the report the example expects. When the reader moves, stretches or adds
// something, the FILE changes, and the reference checker of this repository checks the new FILE
// in the reader's browser (see checker-worker.js). Nothing here decides whether a trip works.
// After a change, the page shows no answer at all until the checker has answered on the new FILE.
//
// trip-file.js holds everything that reads or changes a FILE. This file puts it on the page.
import { FIRST, LAST, STEP, answerOf, bare, change, clock, gesture, holds, said, scene, span, text } from "./trip-file.js";

const SVG = "http://www.w3.org/2000/svg";
const LOADING_LIMIT = 45000; // how long the checker may take to load, in milliseconds
const CHECK_LIMIT = 30000; // how long one check may take
const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
const trip = document.getElementById("trip");

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
  const answers = trip.querySelector(".answers-now");
  const playing = trip.querySelector("#playing");

  let pieces = {}; // what a reader can add, from trip/additions.json
  // What the page shows: a FILE and the report on that very FILE. The report is missing from the
  // moment the reader changes the FILE until the checker answers. A report with a `kind` is the
  // page's own words: the checker stopped, or could not load.
  let now = { version: versions[0], file: structuredClone(stories[versions[0]].file), report: stories[versions[0]].report };
  let drawn = null; // what the day last showed, for moving smoothly to the next thing
  let scrolledTo = ""; // the changed line that the FILE last scrolled to
  let moving = 0; // counts the drawings, so that a movement in progress gives way to a newer drawing

  // ------------------------------------------------------------ the checker

  const checker = { worker: null, ready: false, woke: 0, asked: 0, running: null, waiting: null, serial: 0, broken: false, timer: 0 };

  function wake() {
    if (checker.worker || checker.broken) return;
    try {
      checker.worker = new Worker(new URL("checker-worker.js", import.meta.url), { type: "module" });
    } catch {
      return give_up();
    }
    checker.woke = performance.now();
    checker.worker.onmessage = ({ data }) => {
      if (data.ready) {
        checker.ready = true;
      } else if (checker.running && data.id === checker.running.id) {
        checker.running = null;
        // The answer counts only if the FILE it is about is still the FILE on the page.
        if (checker.waiting === null && now.version === null) settle(data);
      } else if (data.failed && data.id === undefined) {
        return give_up();
      }
      pump();
    };
    checker.worker.onerror = give_up;
  }

  /** Stop the worker. The next FILE gets a new one. */
  function rest() {
    if (checker.worker) checker.worker.terminate();
    Object.assign(checker, { worker: null, ready: false, running: null });
  }

  /** The checker cannot run in this browser. Say so, in the page's own words. */
  function give_up() {
    rest();
    Object.assign(checker, { broken: true, waiting: null });
    sorry();
  }

  function sorry() {
    say("No answer.\nThe reference checker could not load in this browser. The four versions of the story still show their reports.");
  }

  /** Put the page's own words where an answer would go. They never look like an answer. */
  function say(words) {
    if (now.version !== null) return;
    now.report = { kind: "stopped", text: words, json: {} };
    show();
  }

  /**
   * Send the newest FILE when the checker is free. A check that runs long gives way to a newer
   * FILE. Loading and checking each have a limit, so the page never waits for ever.
   */
  function pump() {
    clearTimeout(checker.timer);
    if (checker.broken) return note();
    wake();
    if (checker.broken) return;
    const time = performance.now();
    if (!checker.ready && time - checker.woke > LOADING_LIMIT) return give_up();
    if (checker.running && time - checker.running.started > CHECK_LIMIT) {
      rest();
      if (checker.waiting === null) {
        say(`No answer.\nThe reference checker was stopped after ${CHECK_LIMIT / 1000} s. It tries every order, and this day is too busy for it in a browser. Take something away and it checks again.`);
      }
      wake();
    } else if (checker.running && checker.waiting !== null && time - checker.running.started > 1500) {
      rest();
      wake();
    }
    if (checker.ready && !checker.running && checker.waiting !== null) {
      checker.running = { id: ++checker.serial, started: time };
      checker.worker.postMessage({ id: checker.running.id, file: checker.waiting });
      checker.waiting = null;
    }
    if (checker.running || checker.waiting !== null) checker.timer = setTimeout(pump, 250);
    note();
  }

  function ask() {
    if (checker.broken) return sorry();
    if (!checker.running && checker.waiting === null) checker.asked = performance.now();
    checker.waiting = JSON.stringify(now.file);
    pump();
  }

  function settle(data) {
    if (data.refused) now.report = { kind: "refused", text: `This FILE does not follow the format.\n${data.refused.join(" ")}`, json: {} };
    else if (data.failed) now.report = { kind: "stopped", text: `No answer.\nThe reference checker stopped: ${data.failed}`, json: {} };
    else now.report = { text: data.text, json: data.json, seconds: data.seconds };
    show();
  }

  /** The line over the report that says where the answer came from, or that it is on its way. */
  function note() {
    if (now.version !== null) return;
    const waiting = !checker.broken && Boolean(checker.running || checker.waiting !== null);
    const since = waiting ? performance.now() - checker.asked : 0;
    trip.classList.toggle("checking", waiting);
    trip.classList.toggle("slow", waiting && since > 250);
    reportNote.textContent = checker.broken
      ? "The reference checker could not load here."
      : waiting
        ? !checker.ready
          ? "Loading the reference checker. It is the real one, so it takes a moment the first time."
          : since > 1200
            ? `Still checking after ${Math.round(since / 1000)} s. The reference checker tries every order, so a busy day takes it long. Change anything and it starts afresh.`
            : since > 250
              ? "Checking."
              : ""
        : now.report && now.report.seconds !== undefined
          ? `Checked in your browser by the reference checker, in ${Math.max(1, Math.round(now.report.seconds * 1000))} ms.`
          : "";
  }

  // ------------------------------------------------------------ showing a FILE and its report

  /** The report on the FILE that the page shows, if the checker has given one. */
  const reported = () => (now.report && !now.report.kind ? now.report : null);

  /** Put the current FILE, its report and the day on the page. */
  function show(smooth = false) {
    const own = now.version === null;
    const report = reported();
    const answer = now.report ? now.report.kind || answerOf(now.report) : "waiting";
    trip.classList.toggle("own", own);
    trip.dataset.answer = answer;
    // The FILE, with the lines that differ from the first version marked, and the lines that clash.
    const clash = new Set(report ? report.json.conflict || [] : []);
    const words = own ? text(now.file) : stories[now.version].words;
    const target = own ? fileLive : trip.querySelector(`pre.file-text[data-version="${now.version}"]`);
    target.replaceChildren(
      ...words.replace(/\n$/, "").split("\n").map((each) => {
        const row = document.createElement("span");
        row.textContent = each;
        const id = (each.match(/"id": "([^"]+)"/) || [])[1];
        if (id && clash.has(id)) row.className = "clash";
        else if (!firstLines.has(bare(each))) row.className = "new";
        return row;
      }),
    );
    const changed = target.querySelector(".clash, .new");
    const which = changed ? changed.textContent.slice(0, 40) + target.id : "";
    if (changed && which !== scrolledTo) target.scrollTop = Math.max(0, changed.getBoundingClientRect().top - target.getBoundingClientRect().top + target.scrollTop - 70);
    scrolledTo = which;
    if (own) {
      // The answer, and under it every line of the report that says what the answer turns on.
      const lines = now.report ? said(now.report, answer) : [];
      answerLive.className = `answer live ${now.report ? answer : "pending"}`;
      answerLive.replaceChildren(...lines.map((line) => Object.assign(document.createElement("p"), { textContent: line.words, className: line.inset ? "inset" : "" })));
      reportText.textContent = report ? report.text : "";
      reportLive.className = `report live ${report ? answer : ""}`;
    }
    note();
    for (const button of tools.querySelectorAll("[data-add]")) {
      const piece = pieces[button.dataset.add];
      if (piece) button.setAttribute("aria-pressed", String(holds(now.file, piece)));
    }
    const complete = tools.querySelector("#complete");
    if (complete && pieces.complete) complete.checked = holds(now.file, pieces.complete);
    const next = scene(now.file, report);
    if (smooth && drawn && !still) glide(drawn, next);
    else draw(next);
  }

  /** Move the day from what it shows to the next thing over a short time. */
  function glide(from, to) {
    const began = performance.now();
    const run = ++moving;
    const old = new Map(from.items.map((item) => [item.id, item]));
    const frame = (time) => {
      if (run !== moving) return; // a newer drawing has taken over
      const part = Math.min(1, (time - began) / 650);
      const eased = 1 - (1 - part) ** 3;
      const between = to.items.map((item) => {
        const was = old.get(item.id);
        if (!was || was.kind !== item.kind) return { ...item, faint: eased };
        const mixed = { ...item };
        for (const key of ["start", "length", "longest", "leaves", "cutoff", "shown"]) {
          if (typeof item[key] === "number" && typeof was[key] === "number") mixed[key] = was[key] + (item[key] - was[key]) * eased;
        }
        return mixed;
      });
      if (part < 1) {
        draw({ ...to, items: between, late: [] }, true);
        requestAnimationFrame(frame);
      } else {
        draw(to);
      }
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

  /** Draw the day. `passing` marks one step of a movement; any other drawing ends a movement in progress. */
  function draw(view, passing = false) {
    drawn = view;
    if (!passing) moving += 1;
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
        // A short block has room for the start alone. On a phone the hours at the side say am or pm.
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
          mark.append(make("circle", { class: "cutoff-ring", cx: x2, cy: y2, r: 8 }));
          mark.append(make("circle", { class: "cutoff-hit", cx: x2, cy: y2, r: 16 }));
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
        const known = !ghost && item.length !== null;
        const [x1, y1] = point(item.leaves, fromEdge);
        const [x2, y2] = point(item.leaves + item.shown, toEdge);
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
        // An unknown length is marked "?". Where the report asks for a length, the road shows that length.
        const asked = item.atMost !== null && item.atMost !== undefined ? ` ${span(item.atMost)} or less` : "";
        const name = ghost ? "Another way" : item.name.replace(/ to .*/, "");
        label.textContent = known
          ? `${name} · ${item.longest ? `${span(item.length)} to ${span(item.longest)}` : span(item.length)}`
          : ghost
            ? `${name}?${asked}`
            : `${name} · ?${asked || " nobody knows how long"}`;
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
      }
    }
    // How late people would be at worst, where the report says so: marked along the edge of the lane.
    for (const late of view.late || []) {
      under.append(make("rect", { class: "late-at-worst", ...box(late.from, laneAt(late.place) - 5, late.minutes, 9), rx: 2 }));
    }
    day.classList.toggle("tall", tall);
    // The day is drawn afresh each time, so whatever had the keyboard's focus is given it back.
    const focused = day.contains(document.activeElement) ? document.activeElement.dataset : null;
    day.replaceChildren(svg);
    if (focused && focused.act) day.querySelector(`[data-act="${focused.act}"][data-id="${focused.id}"]`)?.focus();
    day.style.minHeight = `${size[1]}px`;
  }

  // ------------------------------------------------------------ changing the day

  /**
   * The reader changes the trip. It is their own version from then on. The old answer goes at
   * once, and the checker checks the new FILE. A change that changes nothing is left alone.
   */
  function mine(edit) {
    const file = structuredClone(now.file);
    if (edit(file) === false || JSON.stringify(file) === JSON.stringify(now.file)) return;
    if (now.version !== null) {
      stop();
      for (const story of Object.values(stories)) story.input.checked = false;
    }
    now = { version: null, file, report: null };
    show();
    ask();
  }

  /** The thing on the day with this id, as the day shows it now. */
  function itemOf(id) {
    return scene(now.file, reported()).items.find((item) => item.id === id);
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
    const steps = Math.round(by / STEP);
    if (steps !== held.steps) {
      held.steps = steps;
      mine((file) => gesture(file, held.act, held.from, by));
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
    if (!from) return;
    // With shift, the arrow keys stretch a block, and say how late a ride may run.
    const act = !event.shiftKey ? target.dataset.act : from.kind === "event" ? "stretch" : from.kind === "ride" ? "late" : target.dataset.act;
    mine((file) => gesture(file, act, from, way));
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
  // The story waits while the pointer is over the day, and while the day is out of sight.
  const story = { timer: 0, spent: 0, near: false, seen: true };
  function tell(version, smooth = true) {
    stories[version].input.checked = true;
    checker.waiting = null; // a FILE that waits to be checked is the reader's, and the reader has left it
    trip.classList.remove("checking", "slow");
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
  new ResizeObserver(() => draw(scene(now.file, reported()))).observe(day);
  show();
  if (!still) play();
}

if (trip) start();
