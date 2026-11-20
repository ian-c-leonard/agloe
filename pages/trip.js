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
// What the page says under an INFEASIBLE answer. The marks come from the report's list of records.
const MARKED = "The records marked in red rule out every plan together.";
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
  const reportJson = trip.querySelector("#report-json");
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
  let scrolledTo = ""; // the marked line that a version of the story last scrolled to
  let edited = null; // the FILE in words as it was before the reader's last change, until it is shown
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

  /** The checker could not load, or broke. Say so, in the page's own words. The next change tries again. */
  function give_up() {
    rest();
    Object.assign(checker, { broken: true, waiting: null });
    say("No answer.\nThe reference checker could not load. Change anything and it tries again. The four versions of the story still show their reports.");
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
        say(`No answer.\nThe reference checker gave no answer in ${CHECK_LIMIT / 1000} s, so the page stopped it. It tries every order, and a busy day can take it too long in a browser. Take something away and it checks again.`);
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
    checker.broken = false; // a checker that could not load is tried again
    checker.asked = performance.now(); // the wait is counted from the newest FILE
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
    answerLive.dataset.wait = checker.ready ? "Checking." : "Loading the reference checker.";
    reportNote.textContent = checker.broken
      ? "The reference checker could not load. Change anything and it tries again."
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
    // The FILE, with the records that differ from the first version marked, and the records that clash.
    // A record may run over several lines, and each of its lines takes the record's mark.
    const clash = new Set(report ? report.json.conflict || [] : []);
    const words = own ? text(now.file) : stories[now.version].words;
    const target = own ? fileLive : trip.querySelector(`pre.file-text[data-version="${now.version}"]`);
    const lines = words.replace(/\n$/, "").split("\n");
    const markOf = lines.map((each) => (firstLines.has(bare(each)) ? "" : "new"));
    for (let at = 0; at < lines.length; at += 1) {
      if (!/^ {4}\{/.test(lines[at])) continue;
      const closes = /\},?$/.test(lines[at]) ? at : lines.findIndex((each, index) => index > at && /^ {4}\}/.test(each));
      const last = closes < 0 ? at : closes;
      const record = lines.slice(at, last + 1);
      const id = (record.join("\n").match(/"id": "([^"]+)"/) || [])[1];
      markOf.fill(id && clash.has(id) ? "clash" : record.some((each) => !firstLines.has(bare(each))) ? "new" : "", at, last + 1);
      at = last;
    }
    target.replaceChildren(...lines.map((each, at) => Object.assign(document.createElement("span"), { textContent: each, className: markOf[at] })));
    const reach = (row) => target.scrollTo(0, Math.max(0, row.getBoundingClientRect().top - target.getBoundingClientRect().top + target.scrollTop - 70));
    if (own && edited !== null) {
      // The reader's own FILE scrolls to the line that the reader has just changed.
      const before = edited.replace(/\n$/, "").split("\n");
      const at = lines.findIndex((each, index) => each !== before[index]);
      reach(target.children[at < 0 ? lines.length - 1 : at]);
      edited = null;
    } else if (!own) {
      // A version of the story scrolls to its first marked line.
      const changed = target.querySelector(".clash, .new");
      const which = changed ? changed.textContent.slice(0, 40) + now.version : "";
      if (changed && which !== scrolledTo) reach(changed);
      scrolledTo = which;
    }
    if (own) {
      // The answer, and under it every line of the report that says what the answer turns on.
      const under = now.report ? said(now.report, answer) : [];
      answerLive.className = `answer live ${now.report ? answer : "pending"}`;
      answerLive.replaceChildren(...under.map((line) => Object.assign(document.createElement("p"), { textContent: line.words, className: line.inset ? "inset" : "" })));
      // An INFEASIBLE report lists records. The page marks them, and says so in its own words.
      if (answer === "infeasible") answerLive.append(Object.assign(document.createElement("p"), { textContent: MARKED, className: "page-words" }));
      // The report, or the page's own words where the checker gave none. A new one starts at its top.
      const inWords = now.report ? now.report.text : "";
      if (reportText.textContent !== inWords) reportLive.scrollTo(0, 0);
      reportText.textContent = inWords;
      reportJson.textContent = report ? JSON.stringify(report.json, null, 2) : inWords;
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

  // How wide words are when drawn, so that nothing is cut off and nothing lies on top of something else.
  const ruler = document.createElement("canvas").getContext("2d");
  const root = getComputedStyle(document.documentElement);
  const rem = parseFloat(root.fontSize) || 16;
  const faces = { text: root.getPropertyValue("--text").trim() || "sans-serif", mono: root.getPropertyValue("--mono").trim() || "monospace" };
  function widthOf(words, weight, size, face = "text") {
    if (!ruler) return words.length * size * rem * 0.58;
    ruler.font = `${weight} ${size * rem}px ${faces[face]}`;
    return ruler.measureText(words).width;
  }

  /**
   * Draw the day. `passing` marks one step of a movement; any other drawing ends a movement in progress.
   *
   * Words never lie on top of each other. A block too small for its name has the name beside it.
   * Blocks at the same time in one lane share the lane. A ride that is alone between two PLACEs is
   * named along its road. Several rides between the same PLACEs are named in a short list beside
   * them. On a phone every ride is named in a list under the day, and the time to be there is
   * written up the side. The ends that a reader can pull are drawn last, on top of everything.
   */
  function draw(view, passing = false) {
    drawn = view;
    if (!passing) moving += 1;
    const wide = day.clientWidth;
    const tall = wide < 620; // on a narrow screen time runs down the page
    const lanes = view.places.map((place) => place.id);
    const rides = view.items.filter((item) => item.kind === "ride" || item.kind === "ghost");
    // Along the day: `at(minutes)` in pixels. Across it: each PLACE has a lane.
    const edge = tall ? 30 : 26;
    const gutter = tall ? 50 : 0;
    const margin = tall ? 24 : 0; // on a phone, room at the side for the time to be there
    const length = tall ? Math.round((LAST - FIRST) * 1.75) : wide - 14;
    const perMinute = length / (LAST - FIRST);
    // A time before the day starts or after it ends is drawn at the edge, so nothing leaves the drawing.
    const at = (minutes) => (tall ? edge : 7) + (Math.min(LAST, Math.max(FIRST, minutes)) - FIRST) * perMinute;
    const gap = tall ? 44 : 84;
    const laneSize = tall ? Math.floor((wide - gutter - margin - (lanes.length - 1) * gap) / Math.max(1, lanes.length)) : 50;
    const laneAt = (place) => (tall ? gutter : edge + 22) + lanes.indexOf(place) * (laneSize + gap);
    const across = (tall ? gutter : edge + 22) + lanes.length * laneSize + (lanes.length - 1) * gap;
    // Under the lanes: on a desk, room for the time to be there; on a phone, a line for each ride.
    const size = tall ? [wide, at(LAST) + 28 + Math.max(1, rides.length) * 17] : [wide, across + 26];
    // A point from "minutes along, pixels across".
    const point = (minutes, cross) => (tall ? [cross, at(minutes)] : [at(minutes), cross]);
    const box = (minutes, cross, minutesLong, crossSize) => {
      const [x, y] = point(minutes, cross);
      const along = at(minutes + minutesLong) - at(minutes);
      return tall ? { x, y, width: crossSize, height: along } : { x, y, width: along, height: crossSize };
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
      const [x2, y2] = point(hour, tall ? wide - margin : across);
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

    // From the bottom up: roads, blocks, the times to be there, and the ends that a reader pulls.
    const under = make("g");
    const over = make("g");
    const marks = make("g");
    const ends = make("g");
    svg.append(under, over, marks, ends);

    // Blocks at the same time in one lane share the lane, each in a part of its own.
    const blocks = view.items.filter((item) => item.kind === "event" || item.kind === "departure");
    // What leaves is drawn for as long as it takes, to the end of the day at most.
    const lasts = (item) => (item.kind === "event" ? item.length : Math.min(LAST - item.start, item.length ?? 75));
    const meet = (one, other) => one !== other && one.place === other.place && one.start < other.start + lasts(other) && other.start < one.start + lasts(one);
    const part = new Map(); // for each block: which part of the lane it takes, and of how many
    for (const item of blocks) {
      const taken = new Set(blocks.filter((other) => part.has(other.id) && meet(item, other)).map((other) => part.get(other.id).row));
      let row = 0;
      while (taken.has(row)) row += 1;
      part.set(item.id, { row, rows: 1 });
    }
    for (let settled = false; !settled; ) {
      settled = true;
      for (const item of blocks) {
        const own = part.get(item.id);
        const most = Math.max(own.row + 1, ...blocks.filter((other) => meet(item, other)).map((other) => Math.max(part.get(other.id).rows, part.get(other.id).row + 1)));
        if (most > own.rows) {
          own.rows = most;
          settled = false;
        }
      }
    }
    const shapeOf = (item) => {
      const { row, rows } = part.get(item.id);
      const each = (laneSize - 10) / rows;
      return box(item.start, laneAt(item.place) + 5 + row * each, lasts(item), each - (rows > 1 ? 2 : 0));
    };

    const short = (minutes) => clock(minutes).replace(/ [ap]m$/, "");
    /**
     * The name and the times of a block: inside it where they fit, and beside it where they do not.
     * `times` are ways to say the times, longest first. `grip` is the room that the end to pull takes.
     * Gives back how wide the name is.
     */
    const named = (group, item, shape, times, grip = 0) => {
      const big = tall ? 0.76 : 0.82;
      const name = widthOf(item.name, 600, big);
      const fits = (words) => widthOf(words, 400, 0.66, "mono");
      const title = make("text", { class: "block-name" });
      title.textContent = item.name;
      const inside = () => {
        const clip = `clip-${item.id}`;
        defs.append(make("clipPath", { id: clip }, make("rect", { ...shape })));
        const words = make("g", { "clip-path": `url(#${clip})` });
        words.append(title);
        group.append(words);
        return words;
      };
      const when = (words, x, y) => {
        const line = make("text", { class: "block-time", x, y });
        line.textContent = words;
        return line;
      };
      if (tall) {
        // On a phone a block is narrow and long. Its name goes on one line, or on a line for each
        // word, or down the block.
        const room = shape.width - 14;
        const time = times.find((each) => fits(each) <= room);
        const words = item.name.split(" ");
        const wraps = words.length > 1 && words.every((word) => widthOf(word, 600, big) <= room) && shape.height >= words.length * 15 + 12;
        const turns = name <= shape.height - 14;
        if (name <= room * 1.1 || (!wraps && !turns)) {
          title.setAttribute("x", shape.x + 8);
          title.setAttribute("y", shape.y + Math.min(20, shape.height / 2 + 4.5));
          if (name > room * 1.25) {
            // Far too wide, with no other way to place it: the letters that fit, and a mark for the rest.
            let cut = item.name;
            while (cut.length > 1 && widthOf(`${cut}…`, 600, big) > room) cut = cut.slice(0, -1);
            title.textContent = `${cut}…`;
          } else if (name > room) {
            // A name that is a little too wide is pressed together.
            title.setAttribute("textLength", room);
            title.setAttribute("lengthAdjust", "spacingAndGlyphs");
          }
          const all = inside();
          if (time && shape.height > 40) all.append(when(time, shape.x + 8, shape.y + 36));
        } else if (wraps) {
          title.textContent = "";
          words.forEach((word, row) => title.append(Object.assign(make("tspan", { x: shape.x + 8, y: shape.y + 20 + row * 15 }), { textContent: word })));
          const all = inside();
          if (time && shape.height >= words.length * 15 + 34) all.append(when(time, shape.x + 8, shape.y + 22 + words.length * 15));
        } else {
          const [x, y] = [shape.x + shape.width / 2 - 4, shape.y + 9];
          title.setAttribute("x", x);
          title.setAttribute("y", y);
          title.setAttribute("transform", `rotate(90 ${x} ${y})`);
          inside();
        }
        return name;
      }
      const room = shape.width - 20 - grip;
      if (name <= room) {
        const time = shape.height >= 34 ? times.find((each) => fits(each) <= room) : null;
        title.setAttribute("x", shape.x + 10);
        title.setAttribute("y", shape.y + shape.height / 2 + (time ? -3 : 4.5));
        const all = inside();
        if (time) all.append(when(time, shape.x + 10, shape.y + shape.height / 2 + 13));
      } else {
        // Too narrow for its name: the name and the time stand beside it, on the side with room
        // before the next block or the end of the lane.
        const lane = box(FIRST, laneAt(item.place), LAST - FIRST, laneSize);
        const time = times[times.length - 1];
        const others = blocks.filter((other) => other.id !== item.id && other.place === item.place).map(shapeOf);
        const after = Math.min(lane.x + lane.width, ...others.filter((other) => other.x >= shape.x + shape.width - 1).map((other) => other.x)) - shape.x - shape.width;
        const before = shape.x - Math.max(lane.x, ...others.filter((other) => other.x + other.width <= shape.x + 1).map((other) => other.x + other.width));
        const right = after >= name + fits(time) + 18 || after >= before;
        title.setAttribute("class", "block-name beside");
        title.setAttribute("x", right ? shape.x + shape.width + 8 : shape.x - 8);
        title.setAttribute("y", shape.y + shape.height / 2 + 4.5);
        title.setAttribute("text-anchor", right ? "start" : "end");
        title.append(Object.assign(make("tspan", { class: "block-time beside", dx: 7 }), { textContent: time }));
        group.append(title);
      }
      return name;
    };

    /** What a road says about its ride. An unknown length is marked "?", with the length the report asks for. */
    const several = rides.filter((item) => item.kind === "ghost").length > 1;
    const says = (item, where = false) => {
      const ghost = item.kind === "ghost";
      const goes = where && several ? ` to ${view.places.find((place) => place.id === item.to).name}` : "";
      const name = ghost ? `Another way${goes}` : item.name.replace(/ to .*/, "");
      const asked = item.atMost !== null && item.atMost !== undefined ? ` ${span(item.atMost)} or less` : "";
      if (!ghost && item.length !== null) return `${name} · ${item.longest ? `${span(item.length)} to ${span(item.longest)}` : span(item.length)}`;
      return ghost ? `${name}?${asked}` : `${name} · ?${asked || " nobody knows how long"}`;
    };
    const kindOf = (item) => `ride${item.kind === "ride" && item.length !== null ? "" : " unknown"}${item.kind === "ghost" ? " ghost" : ""}${item.clash ? " clash" : ""}${item.taken === false ? " idle" : ""}`;
    /** One line of a list of rides: a short piece of its road, and what it says. */
    const listed = (item, x, y, anchor) => {
      const row = make("g", { class: `${kindOf(item)} listed` });
      const [from, to, words] = anchor === "end" ? [x - 24, x, x - 32] : [x, x + 24, x + 32];
      row.append(make("line", { class: "road-line", x1: from, y1: y - 4, x2: to, y2: y - 4 }));
      const label = make("text", { class: "road-name", x: words, y, "text-anchor": anchor });
      label.textContent = says(item, true);
      row.append(label);
      under.append(row);
    };
    // The rides between each pair of PLACEs, to see which are alone.
    const pairs = new Map();
    for (const item of rides) pairs.set(`${item.from} ${item.to}`, [...(pairs.get(`${item.from} ${item.to}`) || []), item]);
    // Where the ends of roads are, so that two ends never sit on the same spot.
    const landed = [];

    for (const item of view.items) {
      const faint = item.faint === undefined ? null : item.faint;
      if (item.kind === "event") {
        const shape = shapeOf(item);
        const until = item.start + item.length;
        const group = make("g", { class: `event${item.clash ? " clash" : ""}`, opacity: faint, tabindex: 0, role: "slider", "data-act": "move", "data-id": item.id,
          "aria-label": `${item.name}, ${clock(item.start)} to ${clock(until)}. Arrow keys move it. Shift and the arrow keys make it longer or shorter.`,
          "aria-valuetext": `${clock(item.start)} to ${clock(until)}`, "aria-valuenow": Math.round(item.start), "aria-valuemin": FIRST, "aria-valuemax": Math.round(LAST - item.length) });
        group.append(make("rect", { class: "block", ...shape, rx: Math.min(7, shape.height / 2, shape.width / 2) }));
        // On a phone the hours at the side say am or pm, so the block leaves them out.
        const times = tall ? [`${short(item.start)} to ${short(until)}`, short(item.start)] : [`${clock(item.start)} to ${clock(until)}`, clock(item.start)];
        const name = named(group, item, shape, times, 12);
        // The end that stretches.
        const [gx, gy] = point(until, 0);
        const middle = tall ? shape.x + shape.width - 22 : shape.y + shape.height / 2;
        const reach = tall ? 16 : Math.min(16, shape.height / 2);
        group.append(make("rect", { class: "grip", hint: "Pull to make it longer or shorter", "data-act": "stretch", "data-id": item.id,
          x: tall ? middle - reach : gx - 11, y: tall ? gy - 11 : middle - reach, width: tall ? reach * 2 : 14, height: tall ? 14 : reach * 2, rx: 4 }));
        const half = Math.min(7, shape.height / 2 - 3);
        if (!tall) group.append(make("path", { class: "grip-mark", d: `M${gx - 5} ${middle - half}v${2 * half}` }));
        // On a phone the mark of that end is left out of a block so low that the name would lie on it.
        else if (shape.height > 34 || name + 16 < shape.width - 30) group.append(make("path", { class: "grip-mark", d: `M${middle - 7} ${gy - 5}h14` }));
        over.append(group);
      } else if (item.kind === "departure") {
        const place = laneAt(item.place);
        // What leaves is drawn as the start of a road that fades: the rest of it is somewhere else.
        const shape = shapeOf(item);
        const group = make("g", { class: `departure${item.clash ? " clash" : ""}`, opacity: faint, tabindex: 0, role: "slider", "data-act": "move", "data-id": item.id,
          "aria-label": `${item.name}, leaves at ${clock(item.start)}. Arrow keys move it.`, "aria-valuetext": clock(item.start), "aria-valuenow": Math.round(item.start), "aria-valuemin": Math.round(FIRST + (item.cutoff ?? 0)), "aria-valuemax": LAST - 15 });
        const fade = `fade-${item.id}`;
        defs.append(make("linearGradient", { id: fade, x1: 0, y1: 0, x2: tall ? 0 : 1, y2: tall ? 1 : 0 },
          make("stop", { offset: 0.55, class: "road-stop" }), make("stop", { offset: 1, class: "road-stop", "stop-opacity": 0 })));
        group.append(make("rect", { class: "block road", ...shape, rx: Math.min(7, shape.height / 2, shape.width / 2), style: `fill: url(#${fade})` }));
        named(group, item, shape, tall ? [clock(item.start), short(item.start)] : [clock(item.start)]);
        over.append(group);
        if (item.cutoff !== null) {
          // The time by which people must be there: a line across the gap that rides have to reach.
          const when = item.start - item.cutoff;
          const [x1, y1] = point(when, place - gap + 6);
          const [x2, y2] = point(when, place + laneSize);
          const mark = make("g", { class: `cutoff${item.clashCutoff ? " clash" : ""}`, opacity: faint, tabindex: 0, role: "slider", "data-act": "cutoff", "data-id": item.id,
            "aria-label": `People must be at the place ${span(item.cutoff)} before ${item.name} leaves, by ${clock(when)}. Arrow keys move it.`,
            "aria-valuetext": `${span(item.cutoff)} before, by ${clock(when)}`, "aria-valuenow": Math.round(item.cutoff), "aria-valuemin": 0, "aria-valuemax": Math.round(Math.min(180, item.start - FIRST)) });
          mark.append(make("line", { class: "cutoff-line", x1, y1, x2, y2 }));
          mark.append(make("circle", { class: "cutoff-ring", cx: x2, cy: y2, r: 8 }));
          mark.append(make("circle", { class: "cutoff-hit", cx: x2, cy: y2, r: 16 }));
          // Its words stand clear of the lanes: under them on a desk, up the side on a phone.
          const flip = x2 > wide - 170;
          const words = `Be there by ${clock(when)}`;
          const half = (widthOf(words, 500, 0.68, "mono") + words.length * 0.06 * 0.68 * rem) / 2 + 4;
          const up = Math.min(Math.max(y2, half), at(LAST) + 12 - half);
          const label = tall
            ? make("text", { class: "cutoff-name", x: x2 + 16, y: up, "text-anchor": "middle", transform: `rotate(90 ${x2 + 16} ${up})` })
            : make("text", { class: "cutoff-name", x: flip ? x2 - 14 : x2 + 14, y: y2 + 14, "text-anchor": flip ? "end" : "start" });
          label.textContent = words;
          mark.append(label);
          marks.append(mark);
        }
      } else {
        // A ride, or another way that the report asks about: a road from one PLACE to the next.
        const down = lanes.indexOf(item.to) > lanes.indexOf(item.from);
        const ghost = item.kind === "ghost";
        const known = !ghost && item.length !== null;
        // A road that would end where another has ended goes a little further into the lane.
        let deep = 0;
        if (!ghost) {
          const spot = at(item.leaves + item.shown);
          while (landed.some((other) => other.to === item.to && other.deep === deep && Math.abs(other.spot - spot) < 20)) deep += 1;
          landed.push({ to: item.to, deep, spot });
        }
        const fromEdge = laneAt(item.from) + (down ? laneSize - 4 : 4);
        const toEdge = laneAt(item.to) + (down ? 4 + deep * 17 : laneSize - 4 - deep * 17);
        const [x1, y1] = point(item.leaves, fromEdge);
        const [x2, y2] = point(item.leaves + item.shown, toEdge);
        const group = make("g", { class: kindOf(item), opacity: faint });
        const range = known && item.longest !== null && item.longest > item.length;
        if (range) {
          const [x3, y3] = point(item.leaves + item.longest, toEdge);
          group.append(make("path", { class: "may-run-late", d: `M${x1} ${y1}L${x2} ${y2}L${x3} ${y3}Z` }));
        }
        group.append(make("line", { class: "road-line", x1, y1, x2, y2 }));
        if (!tall && pairs.get(`${item.from} ${item.to}`).length === 1) {
          // Alone between its PLACEs: named along its road, on the side where nothing else is drawn,
          // and clear of the line of a time to be there that crosses the road.
          const far = Math.hypot(x2 - x1, y2 - y1);
          const half = widthOf(says(item), 600, 0.74) / 2;
          let along = far / 2;
          for (const other of view.items) {
            if (other.kind !== "departure" || other.cutoff === null || other.place !== item.to || x2 === x1) continue;
            const crosses = ((at(other.start - other.cutoff) - x1) / (x2 - x1)) * far;
            // The words stand above the road, so they lean towards the line: they keep well away from it.
            if (Math.abs(crosses - along) >= half + 26) continue;
            if (crosses - 2 * half - 32 >= 0) along = crosses - half - 26;
            else if (crosses + 2 * half + 30 <= far) along = crosses + half + 18;
          }
          const [mx, my] = [x1 + ((x2 - x1) * along) / far, y1 + ((y2 - y1) * along) / far];
          const label = make("text", { class: "road-name", x: mx, y: my, dy: range && down ? 20 : -11, "text-anchor": "middle", transform: `rotate(${(Math.atan2(y2 - y1, x2 - x1) * 180) / Math.PI} ${mx} ${my})` });
          label.textContent = says(item);
          group.append(label);
        }
        under.append(group);
        if (!ghost) {
          const lengths = known ? (range ? `${span(item.length)} to ${span(item.longest)}` : span(item.length)) : "not recorded";
          ends.append(make("circle", { class: `road-end${known ? "" : " unknown"}`, cx: x2, cy: y2, r: 9, tabindex: 0, role: "slider", "data-act": "ride", "data-id": item.id,
            "aria-label": known ? `${item.name} takes ${lengths}. Arrow keys change it. Shift and the arrow keys say how late it may run.` : `Nobody has recorded how long ${item.name} takes. Arrow keys set it.`,
            "aria-valuetext": lengths, "aria-valuenow": known ? Math.round(item.length) : 0, "aria-valuemin": 0, "aria-valuemax": 240 }));
          if (known) {
            // The end that says how late the ride may run. Until it is pulled it waits beside the end
            // of the road. Where it would lie on that end, or leave the drawing, it sits further into
            // the lane instead, so each of the two ends can be pulled.
            const [lx, ly] = point(item.leaves + (item.longest ?? item.length), toEdge);
            const inward = down ? 21 : -21;
            const beside = range ? Math.hypot(lx - x2, ly - y2) < 24 : !tall && lx + 26 > at(LAST) + 7;
            const [cx, cy] = beside ? (tall ? [lx + inward, ly] : [lx, ly + inward]) : range ? [lx, ly] : tall ? [lx, ly + 20] : [lx + 20, ly];
            ends.append(make("circle", { class: `late-end${range ? " set" : ""}`, cx, cy, r: 6 }));
            ends.append(make("circle", { class: "late-hit", hint: "Pull to say how late it may run", cx, cy, r: range && !beside ? 14 : 11, "data-act": "late", "data-id": item.id }));
          }
        }
      }
    }
    // The lists of rides. On a phone: every ride, under the day.
    if (tall) {
      rides.forEach((item, row) => listed(item, gutter, at(LAST) + 42 + row * 17, "start"));
    } else {
      // On a desk: where several rides run between the same PLACEs, a list in the gap between the
      // lanes, in the nearest stretch that is clear of roads and of the lines of times to be there.
      for (const group of pairs.values()) {
        if (group.length < 2) continue;
        const [upper, lower] = [group[0].from, group[0].to].sort((one, other) => lanes.indexOf(one) - lanes.indexOf(other));
        const width = 44 + Math.max(...group.map((item) => widthOf(says(item, true), 600, 0.74)));
        const taken = rides
          .filter((item) => [item.from, item.to].includes(upper) && [item.from, item.to].includes(lower))
          .map((item) => [at(item.leaves) - 12, at(item.leaves + Math.max(item.shown, item.longest ?? 0)) + 14]);
        for (const item of view.items) {
          if (item.kind === "departure" && item.cutoff !== null && item.place === lower) taken.push([at(item.start - item.cutoff) - 9, at(item.start - item.cutoff) + 9]);
        }
        taken.sort((one, other) => one[0] - other[0]);
        const clear = [];
        let from = 10;
        for (const [start, end] of taken) {
          if (start > from) clear.push([from, start]);
          from = Math.max(from, end);
        }
        if (wide - 10 > from) clear.push([from, wide - 10]);
        const fan = [at(Math.min(...group.map((item) => item.leaves))), at(Math.max(...group.map((item) => item.leaves + item.shown)))];
        const away = ([start, end]) => (end <= fan[0] ? fan[0] - end : Math.max(0, start - fan[1]));
        const roomy = clear.filter(([start, end]) => end - start >= width);
        // With no stretch wide enough, the widest one.
        const [start, end] = (roomy.length ? roomy.sort((one, other) => away(one) - away(other)) : clear.sort((one, other) => other[1] - other[0] - (one[1] - one[0])))[0] || [10, wide - 10];
        const before = end <= fan[0] + 1;
        const top = laneAt(upper) + laneSize + (gap - group.length * 17) / 2 + 12;
        group.forEach((item, row) => listed(item, before ? end - 6 : start + 6, top + row * 17, before ? "end" : "start"));
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
    if (focused && focused.act) day.querySelector(`[tabindex][data-act="${focused.act}"][data-id="${focused.id}"]`)?.focus();
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
    edited = text(now.file);
    now = { version: null, file, report: null };
    label();
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
    held = { act: target.dataset.act, from, x: event.clientX, y: event.clientY, tall: day.clientWidth < 620, steps: 0 };
    day.setPointerCapture(event.pointerId);
    day.classList.add("holding");
    event.preventDefault();
  });
  day.addEventListener("pointermove", (event) => {
    if (!held) return;
    const length = held.tall ? Math.round((LAST - FIRST) * 1.75) : day.clientWidth - 14;
    const by = ((held.tall ? event.clientY - held.y : event.clientX - held.x) / length) * (LAST - FIRST);
    // Nothing changes until the pull has gone one whole step.
    if (!held.moved && Math.abs(by) < STEP) return;
    held.moved = true;
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
  // The story waits while the pointer is over the day, while the keyboard is in the day, in the
  // versions or in the tools, and while the day is out of sight.
  const story = { timer: 0, spent: 0, near: false, within: false, seen: true };
  /** Each report scrolls by itself. A report that has just come into view starts at its top left. */
  function toTop() {
    for (const pane of trip.querySelectorAll(".terminal > *")) pane.scrollTo(0, 0);
  }
  for (const input of trip.querySelectorAll('input[name="form"]')) input.addEventListener("change", toTop);
  /** What the button says. Playing the story replaces a trip that the reader has changed, so it says that. */
  function label() {
    playing.textContent = story.timer ? "Pause the story" : now.version === null ? "Drop my changes and play the story" : "Play the story";
  }
  function tell(version, smooth = true) {
    stories[version].input.checked = true;
    checker.waiting = null; // a FILE that waits to be checked is the reader's, and the reader has left it
    trip.classList.remove("checking", "slow");
    now = { version, file: structuredClone(stories[version].file), report: stories[version].report };
    toTop();
    label();
    show(smooth);
  }
  function stop() {
    clearInterval(story.timer);
    story.timer = 0;
    trip.classList.remove("playing");
    playing.setAttribute("aria-pressed", "false");
    label();
    answers.setAttribute("aria-live", "polite");
  }
  function play() {
    if (now.version === null) tell(versions[0]);
    story.spent = 0;
    trip.classList.add("playing");
    playing.setAttribute("aria-pressed", "true");
    // A story that plays by itself is not read out at every step.
    answers.setAttribute("aria-live", "off");
    clearInterval(story.timer);
    story.timer = setInterval(() => {
      if (document.hidden || story.near || story.within || !story.seen) return;
      story.spent += 100;
      if (story.spent >= PACE) {
        story.spent = 0;
        tell(versions[(versions.indexOf(now.version) + 1) % versions.length]);
      }
      trip.style.setProperty("--told", String(story.spent / PACE));
    }, 100);
    label();
  }
  day.addEventListener("pointerenter", () => (story.near = true));
  day.addEventListener("pointerleave", () => (story.near = false));
  for (const part of [day, tools, trip.querySelector(".versions")]) {
    part.addEventListener("focusin", () => (story.within = true));
    part.addEventListener("focusout", () => (story.within = false));
  }
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
  if (document.fonts) document.fonts.ready.then(() => draw(scene(now.file, reported())));
  show();
  if (!still) play();
}

if (trip) start();
