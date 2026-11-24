// The page on how a rule is built: two figures that a reader can try.
//
// Without this script both figures are whole and still. With it, the reader can set the variables
// of the second figure and see which statements hold, and the first figure can show its plans
// being checked one after another.
import { holds } from "./statements.js";

const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
const COUNT = ["No", "One", "Two", "Three", "Four", "Five"];

// ---------------------------------------------------------------- the variables and their statements

for (const board of document.querySelectorAll(".board")) {
  const switches = [...board.querySelectorAll("[data-switch]")];
  const statements = [...board.querySelectorAll("[data-says]")];
  const outcome = board.querySelector(".outcome");
  const solver = board.querySelector(".solver");
  const tried = board.querySelector(".tried");
  const answer = (board.dataset.solver || "").split(" ").filter(Boolean);
  const seen = new Set();

  const yes = () => new Set(switches.filter((each) => each.getAttribute("aria-checked") === "true").map((each) => each.dataset.switch));
  const set = (each, on) => {
    each.setAttribute("aria-checked", String(on));
    each.querySelector("b").textContent = on ? "yes" : "no";
  };

  /** Say which statements hold with the variables as they are. */
  function show() {
    const now = yes();
    let wrong = 0;
    for (const statement of statements) {
      const true_ = holds(statement.dataset.says, now);
      wrong += !true_;
      statement.classList.toggle("false", !true_);
      statement.querySelector(".lamp").textContent = true_ ? "true" : "false";
    }
    outcome.classList.toggle("no", wrong > 0);
    outcome.textContent = wrong
      ? `${COUNT[wrong] || wrong} statement${wrong === 1 ? " is" : "s are"} false. This setting is not a plan.`
      : "Every statement is true. This setting is a plan.";
    if (tried) {
      seen.add([...now].sort().join(" "));
      const all = 2 ** switches.length;
      tried.textContent = seen.size < all ? `You have tried ${seen.size} of the ${all} settings.` : `You have tried all ${all} settings. None makes every statement true.`;
    }
  }

  for (const each of switches) {
    each.addEventListener("click", () => {
      set(each, each.getAttribute("aria-checked") !== "true");
      show();
    });
  }
  if (solver && answer.length) {
    solver.hidden = false;
    solver.addEventListener("click", () => {
      for (const each of switches) set(each, answer.includes(each.dataset.switch));
      show();
    });
  }
  if (tried) tried.hidden = false;
  show();
}
for (const figure of document.querySelectorAll("#switchboard")) figure.classList.add("alive");

// ---------------------------------------------------------------- every plan, one after another

const plans = document.querySelector(".plans");
if (plans && !still) {
  const cards = [...plans.querySelectorAll(".plan")];
  const again = Object.assign(document.createElement("button"), { type: "button", className: "button quiet again", textContent: "Check the plans again" });
  let run = 0;
  /** Show the result of each plan in turn, as the slow checker reaches it. */
  const check = () => {
    const mine = ++run;
    for (const card of cards) card.classList.remove("checked", "now");
    plans.classList.add("checking");
    cards.forEach((card, at) => {
      setTimeout(() => {
        if (mine !== run) return;
        for (const other of cards) other.classList.remove("now");
        card.classList.add("checked", "now");
        if (at === cards.length - 1) {
          setTimeout(() => {
            if (mine !== run) return;
            card.classList.remove("now");
            plans.classList.remove("checking");
          }, 700);
        }
      }, 450 * (at + 1));
    });
  };
  plans.after(again);
  again.addEventListener("click", check);
  // The first time the plans come into view, they are checked once.
  if ("IntersectionObserver" in window) {
    new IntersectionObserver((seen, watcher) => {
      if (seen.some((entry) => entry.isIntersecting)) {
        watcher.disconnect();
        check();
      }
    }, { threshold: 0.6 }).observe(plans);
  }
}
