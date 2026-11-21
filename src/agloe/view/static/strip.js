// All the days of the calendar on one strip: a row for each PERSON, and time from left to right.
// There is no page in here, so the tests run this as it is.
//
// The strip is the calendar on its side. It takes the calendar as calendar.js lays it out, and
// puts its days one after another. Each day takes the room of the hours that it shows on the
// calendar, less the hours that its clocks never show. So the strip holds the marks of the
// calendar and no others, each with the words, the lane and the edges that it has there.
//
// Nothing here judges a TRIP, and nothing here works out a time.

const ROOM = 20; // minutes of room before the first thing on the strip, and after the last
const NEAR = 1 / 30; // of the strip: two ticks that are nearer than this would lie on each other
const PLACES = 3; // the places for a tick in the row of one PERSON

/** A day as the strip names it: Sat 15, for Saturday 15 May 2027. Its offset from UTC follows. */
function shortName(name) {
  const [weekday, day, , , offset] = name.split(" ");
  return `${weekday.slice(0, 3)} ${day}${offset ? ` ${offset}` : ""}`;
}

/**
 * The strip of a calendar, or null where the calendar needs none: where fewer than two of its
 * days have room, or where it holds no step.
 *
 * `length` is how long the strip is, in minutes. Each day has its `left` and its `width` on the
 * strip. So has each mark, which is otherwise the mark of the calendar: `day` and `index` say
 * which mark of which day it is there. A bound is where the TRIP starts or ends, with its `left`.
 *
 * `gap` on a day says that the strip leaves hours out before it: hours that the calendar does
 * not show. `cut` says that it does so before some day.
 *
 * A WAY that takes next to no time is a tick. Ticks that would lie on each other in the row of
 * one PERSON each have a `place` of their own in that row, as far as the row has places.
 */
export function strip(laid) {
  const open = laid.days.map((day) => ({ from: day.open.top, to: Math.max(day.open.bottom, day.open.top) }));
  const withRoom = open.flatMap((each, n) => (each.to > each.from ? [n] : []));
  if (withRoom.length < 2 || !laid.days.some((day) => day.marks.length)) return null;
  // The strip starts a little before the first thing on its first day, and ends a little
  // after the last thing on its last day. A day at an end with nothing on it is there whole.
  const first = withRoom[0], last = withRoom[withRoom.length - 1];
  const starts = [...laid.days[first].marks, ...laid.days[first].bounds].map((each) => each.top);
  const ends = [...laid.days[last].marks.map((mark) => mark.top + mark.height), ...laid.days[last].bounds.map((bound) => bound.top)];
  if (starts.length) open[first].from = Math.max(open[first].from, starts.reduce((least, top) => Math.min(least, top)) - ROOM);
  if (ends.length) open[last].to = Math.min(open[last].to, ends.reduce((most, bottom) => Math.max(most, bottom)) + ROOM);
  let length = 0, before = null;
  const days = laid.days.map((day, n) => {
    const width = Math.max(open[n].to - open[n].from, 0);
    // No time is left out between two days where the calendar shows the first to its last
    // moment and the next from its first. A day with no room between them is time left out.
    const gap = width > 0 && before !== null && !(before === n - 1 && laid.days[before].open.last && day.open.first);
    const made = { name: day.name, short: shortName(day.name), left: length, width, gap };
    length += width;
    if (width > 0) before = n;
    return made;
  });
  // How far along the strip a time of a day is: never outside the room of its day.
  const along = (n, top) => days[n].left + Math.min(Math.max(top - open[n].from, 0), days[n].width);
  const marks = laid.days.flatMap((day, n) =>
    day.marks.map(({ top, height, ...mark }, index) => {
      // A mark inside the room of its day is as long as it is tall on the calendar.
      const inside = top >= open[n].from && top + height <= open[n].to;
      return { ...mark, day: n, index, left: along(n, top), width: inside ? height : along(n, top + height) - along(n, top) };
    }),
  );
  // Each tick takes the first place that no tick near it in the same rows has taken.
  const ticks = [];
  for (const mark of marks.filter((each) => each.brief).sort((a, b) => a.left - b.left)) {
    while (ticks.length && mark.left - ticks[0].left >= length * NEAR) ticks.shift();
    const taken = new Set(ticks.filter((other) => other.first <= mark.last && mark.first <= other.last).map((other) => other.place));
    mark.place = 0;
    while (taken.has(mark.place) && mark.place < PLACES - 1) mark.place += 1;
    ticks.push(mark);
  }
  const bounds = laid.days.flatMap((day, n) => day.bounds.map(({ top, ...bound }) => ({ ...bound, day: n, left: along(n, top) })));
  const cut = days.some((day) => day.gap);
  const says = `All the days of the calendar on one strip, a row for each PERSON.${cut ? " It leaves out the hours that the calendar does not show." : ""} Click a step to see it in the calendar.`;
  return { says, persons: laid.persons, length, cut, days, marks, bounds };
}
