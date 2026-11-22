// How the page writes a day, a time of day and a length of time: as the report does. There is
// no page in here, so the tests run this as it is.
//
// The view sends each time as the clocks of the FILE's time zone show it, such as
// 2027-05-15T14:00:00, with its offset from UTC where the report gives offsets. Nothing here
// works out a time: it puts in words what it is sent.

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

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

/** Whose clocks the times on the page are on. A part that shows a time says so. */
export function clocksOf(zone) {
  return ` Times are on the clocks of ${zone}.`;
}

/** A length of time as the report writes it: 45 min, 1 h, 2 h 30 min. */
export function span(seconds) {
  const parts = [[Math.floor(seconds / 3600), "h"], [Math.floor(seconds / 60) % 60, "min"], [seconds % 60, "s"]];
  return parts.filter(([amount]) => amount).map(([amount, unit]) => `${amount} ${unit}`).join(" ") || "no time";
}
