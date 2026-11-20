// The page of the view: it listens to the view and shows what state.js says.
import { after, says, start } from "./state.js";

const part = (id) => document.getElementById(id);
let state = start();

function show() {
  const said = says(state);
  document.title = said.name ? `${said.name}: Agloe` : "Agloe";
  part("name").textContent = said.name || "";
  part("answer").className = `answer ${said.mark}`;
  part("line").textContent = said.line;
  part("note").textContent = said.note;
  part("problems").replaceChildren(...(said.problems || []).map((problem) => Object.assign(document.createElement("li"), { textContent: problem })));
  part("problems").hidden = !said.problems;
  part("report").textContent = said.report || "";
  part("report-part").hidden = said.report === null;
  part("report-part").classList.toggle("old", said.old);
}

const view = new EventSource("events");
view.onmessage = (message) => {
  state = after(state, JSON.parse(message.data));
  show();
};
// The command that serves the view has ended, or has started again.
view.onerror = () => (part("stopped").hidden = false);
view.onopen = () => (part("stopped").hidden = true);
show();
