// All the days of the calendar on one strip: a row for each PERSON, and time from left to right.
// There is no page in here, so the tests run this as it is.
//
// The strip is the calendar on its side. It takes the calendar as calendar.js lays it out, and
// puts its days one after another in the pixels that the page has. Each day takes the room of
// the hours that it shows on the calendar, less the hours that its clocks never show. So the
// strip holds the marks of the calendar and no others, each with the words, the lane and the
// edges that it has there.
//
// A strip is narrow, and a mark can be too short to draw at its width. Such a mark is drawn
// across the middle of its time, as small as the eye can find, in the row of each of its
// PERSONs. Where two of those would lie on each other in one row, they are one mark, which
// stands for both. So nothing on the strip hides a step.
//
// Nothing here judges a TRIP, and nothing here works out a time.

const ROOM = 20; // minutes of room before the first thing on the strip, and after the last
const LEAST = 3; // pixels: the least width of the block of an OPTION, and of the line of a WAY
const TICK = 5; // pixels: the width of the tick of a WAY that is too short for a line
const STUB = 24; // pixels: the room of a day that shows no hours and holds a time of the TRIP
const TOUCH = 1e-6; // pixels: two marks that are this close to each other do not lie on each other

/** A day as the strip names it: Sat 15, for Saturday 15 May 2027. Its offset from UTC follows. */
function shortName(name) {
  const [weekday, day, , , offset] = name.split(" ");
  return `${weekday.slice(0, 3)} ${day}${offset ? ` ${offset}` : ""}`;
}

/**
 * The strip of a calendar in `wide` pixels, or null where the calendar needs none: where fewer
 * than two of its days have a place on the strip, or where it holds no step.
 *
 * Each day has its `x` and its `w` on the strip, in pixels. A day that shows no hours has no
 * place, but for one that holds a time of the TRIP. `gap` on a day says that the strip leaves
 * hours out before it: hours that the calendar does not show. `cut` says that it does so
 * before some day. `per` is the pixels that a minute takes.
 *
 * Each mark has its `x` and `w`, the rows `first` to `last` of its PERSONs, and its `lane` of
 * the `lanes` in those rows. `of` holds the marks of the calendar that it stands for, each
 * with the `day` it is on and its `index` among the marks of that day. A mark that can be drawn
 * stands for itself. A mark that is `small` is too short to draw. It is in one row, and it
 * stands for every small mark of that row that would lie on it.
 *
 * A bound is where the TRIP starts or ends, with its `x`.
 */
export function strip(laid, wide = 800) {
  const open = laid.days.map((day) => ({ from: day.open.top, to: Math.max(day.open.bottom, day.open.top) }));
  const withRoom = open.flatMap((each, n) => (each.to > each.from ? [n] : []));
  // A day that shows no hours has a place where it holds a time of the TRIP.
  const stub = laid.days.map((day, n) => open[n].to <= open[n].from && day.bounds.length > 0);
  const places = withRoom.length + stub.filter(Boolean).length;
  if (places < 2 || !withRoom.length || !laid.days.some((day) => day.marks.length)) return null;
  // The strip starts a little before the first thing on the first day that shows hours, and
  // ends a little after the last thing on the last. Such a day with nothing on it is there whole.
  const first = withRoom[0], last = withRoom[withRoom.length - 1];
  const starts = [...laid.days[first].marks, ...laid.days[first].bounds].map((each) => each.top);
  const ends = [...laid.days[last].marks.map((mark) => mark.top + mark.height), ...laid.days[last].bounds.map((bound) => bound.top)];
  if (starts.length) open[first].from = Math.max(open[first].from, starts.reduce((least, top) => Math.min(least, top)) - ROOM);
  if (ends.length) open[last].to = Math.min(open[last].to, ends.reduce((most, bottom) => Math.max(most, bottom)) + ROOM);
  const minutes = withRoom.reduce((sum, n) => sum + open[n].to - open[n].from, 0);
  const per = Math.max(wide - STUB * (places - withRoom.length), wide / 2) / minutes;
  let across = 0, before = null;
  const days = laid.days.map((day, n) => {
    const w = stub[n] ? STUB : Math.max(open[n].to - open[n].from, 0) * per;
    // No time is left out between two days where the calendar shows the first to its last
    // moment and the next from its first.
    const gap = w > 0 && before !== null && !(before === n - 1 && laid.days[before].open.last && day.open.first);
    const made = { name: day.name, short: shortName(day.name), x: across, w, gap };
    across += w;
    if (w > 0) before = n;
    return made;
  });
  // How far along the strip a time of a day is: never outside the room of its day.
  const along = (n, top) => days[n].x + Math.min(Math.max(top - open[n].from, 0), Math.max(open[n].to - open[n].from, 0)) * per;
  const marks = [];
  const small = laid.persons.map(() => []);
  laid.days.forEach((day, n) => {
    day.marks.forEach(({ top, height, ...rest }, index) => {
      const mark = { ...rest, day: n, index };
      const from = along(n, top), to = along(n, top + height);
      if (to - from >= LEAST) {
        marks.push({ x: from, w: to - from, first: mark.first, last: mark.last, lane: mark.lane, lanes: mark.lanes, small: false, of: [mark] });
        return;
      }
      // Too short to draw: across the middle of its time, and inside its day.
      const w = Math.min(mark.kind === "way" ? TICK : LEAST, days[n].w);
      const x = Math.min(Math.max((from + to) / 2 - w / 2, days[n].x), days[n].x + days[n].w - w);
      for (let row = mark.first; row <= mark.last; row += 1) small[row].push({ x, w, mark });
    });
  });
  // In each row, small marks that would lie on each other are one mark.
  small.forEach((pieces, row) => {
    let group = null;
    for (const piece of pieces.sort((a, b) => a.x - b.x)) {
      if (group !== null && piece.x < group.x + group.w - TOUCH) {
        group.w = Math.max(group.x + group.w, piece.x + piece.w) - group.x;
        group.of.push(piece.mark);
      } else {
        group = { x: piece.x, w: piece.w, first: row, last: row, lane: 0, lanes: 1, small: true, of: [piece.mark] };
        marks.push(group);
      }
    }
  });
  const bounds = laid.days.flatMap((day, n) => day.bounds.map(({ top, ...bound }) => ({ ...bound, day: n, x: stub[n] ? days[n].x + STUB / 2 : along(n, top) })));
  const cut = days.some((day) => day.gap);
  const says = `All the days of the calendar on one strip, a row for each PERSON.${cut ? " It leaves out the hours that the calendar does not show." : ""} Click a step to see it in the calendar.`;
  return { says, persons: laid.persons, wide: across, per, cut, days, marks, bounds };
}
