"""The view: ``agloe view FILE`` serves a page on this machine and keeps it up to date.

The command watches the FILE. Each time the FILE changes, it runs the COMPILER on it in a
process of its own. It tells the page that there is a FILE to check, then sends the answer as
soon as it is proved, then the report in words and as JSON. A FILE that does not follow the
format gets no report: the page is sent the problems that the format names.

Nothing in the page judges a TRIP, and the page shows no answer on a FILE until the COMPILER has
answered on that FILE. ``src/agloe/view/static/state.js`` works out what the page says in each
state. It has no page in it, so Node runs it here, through ``view_page.mjs``.
"""

import http.client
import json
import os
import re
import select
import shutil
import subprocess
import sys
import threading
import urllib.request
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from agloe.cli import main
from agloe.file import FileError, read
from agloe.view import View
from agloe.view.check import events
from tests.stories import EXAMPLES

STORY = EXAMPLES / "flight-home"
STATIC = Path(__file__).parent.parent / "src" / "agloe" / "view" / "static"
FILES = sorted(
    path for path in EXAMPLES.rglob("*.json") if not path.name.endswith(".expected.json")
)
ANSWERS = ("FEASIBLE", "INFEASIBLE", "UNDETERMINED")


def beside(path: Path, ending: str) -> Path:
    return path.with_name(path.stem + ending)


@contextmanager
def serving(path: Path, python: str = sys.executable) -> Generator[View]:
    """The view of one FILE, served on a free port of this machine until the test is done."""
    view = View(path, port=0, python=python)
    thread = threading.Thread(target=view.serve, daemon=True)
    thread.start()
    try:
        yield view
    finally:
        view.close()
        thread.join(timeout=20)
        assert not thread.is_alive(), "the view did not stop"


class Sent:
    """What the view sends a page, read one event at a time."""

    def __init__(self, view: View) -> None:
        self.reply = urllib.request.urlopen(f"{view.address}events", timeout=60)

    def next(self) -> dict[str, Any]:
        for raw in self.reply:
            line = raw.decode().rstrip("\n")
            if line.startswith("data: "):
                event: dict[str, Any] = json.loads(line.removeprefix("data: "))
                return event
        raise AssertionError("the view stopped sending")

    def until(self, kind: str) -> list[dict[str, Any]]:
        """Every event up to the first of this kind."""
        seen = [self.next()]
        while seen[-1]["kind"] != kind:
            seen.append(self.next())
        return seen


def asked(view: View, path: str, host: str | None = None) -> tuple[int, str, bytes]:
    """The status, the kind of content and the content that the view gives for one path."""
    port = int(view.address.rstrip("/").rsplit(":", 1)[1])
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    try:
        connection.request("GET", path, headers={"Host": host or f"127.0.0.1:{port}"})
        reply = connection.getresponse()
        return reply.status, reply.headers.get("Content-Type", ""), reply.read()
    finally:
        connection.close()


@pytest.mark.parametrize("name", ["works", "works-but-risky", "cannot-work", "depends-on-the-cab"])
def test_a_page_is_sent_the_file_then_the_answer_then_the_report(name: str, tmp_path: Path) -> None:
    path = tmp_path / "trip.json"
    shutil.copy(STORY / f"{name}.json", path)
    expected = json.loads((STORY / f"{name}.expected.json").read_text())
    with serving(path) as view:
        file, answer, report = Sent(view).until("report")
    assert file == {"kind": "file", "name": "trip.json"}
    assert answer["kind"] == "answer"
    assert answer["answer"] == expected["answer"]
    assert report["answer"] == expected["answer"]
    assert report["json"] == expected
    assert report["text"] == (STORY / f"{name}.expected.txt").read_text()
    assert 0 <= answer["seconds"] <= report["seconds"]


def test_a_file_that_changes_is_checked_again(tmp_path: Path) -> None:
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    with serving(path) as view:
        sent = Sent(view)
        assert sent.until("report")[-1]["answer"] == "FEASIBLE"
        shutil.copy(STORY / "cannot-work.json", path)
        again = sent.until("report")
    assert [event["kind"] for event in again] == ["file", "answer", "report"]
    assert again[-1]["json"] == json.loads((STORY / "cannot-work.expected.json").read_text())


def test_a_file_that_breaks_the_format_has_no_report(tmp_path: Path) -> None:
    """The page is sent the problems that the format names, and the view goes on."""
    path = tmp_path / "trip.json"
    broken = json.loads((STORY / "works.json").read_text())
    broken["facts"][0]["starts_at"] = "half past two"
    path.write_text(json.dumps(broken))
    with pytest.raises(FileError) as refused:
        read(path)
    with serving(path) as view:
        sent = Sent(view)
        first = sent.until("refused")
        assert [event["kind"] for event in first] == ["file", "refused"]
        assert first[-1]["problems"] == list(refused.value.problems)
        path.write_text("{ this is not JSON")
        unreadable = sent.until("refused")
        assert [event["kind"] for event in unreadable] == ["file", "refused"]
        assert unreadable[-1]["problems"][0].startswith("not readable as JSON")
        shutil.copy(STORY / "works.json", path)
        mended = sent.until("report")
    assert [event["kind"] for event in mended] == ["file", "answer", "report"]


def test_a_page_that_comes_late_is_sent_the_same(tmp_path: Path) -> None:
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    with serving(path) as view:
        first = Sent(view).until("report")
        late = Sent(view).until("report")
    assert late == first


def test_a_file_that_is_taken_away_has_no_report(tmp_path: Path) -> None:
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    with serving(path) as view:
        sent = Sent(view)
        sent.until("report")
        path.unlink()
        gone = sent.until("refused")
    assert [event["kind"] for event in gone] == ["file", "refused"]
    assert len(gone[-1]["problems"]) == 1


def test_a_check_that_ends_without_a_report_has_stopped(tmp_path: Path) -> None:
    """The page is told, so it never waits for a report that will not come."""
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    broken = tmp_path / "python"
    broken.write_text("#!/bin/sh\nexit 3\n")
    broken.chmod(0o755)
    with serving(path, python=str(broken)) as view:
        assert Sent(view).until("stopped") == [{"kind": "stopped"}]
    with serving(path, python=str(tmp_path / "nothing")) as view:
        assert Sent(view).until("stopped") == [{"kind": "stopped"}]


def test_the_view_serves_its_page_and_nothing_else(tmp_path: Path) -> None:
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    with serving(path) as view:
        status, kind, page = asked(view, "/")
        assert status == 200
        assert kind.startswith("text/html")
        # Every file that the page names is served, with a kind of content a browser accepts.
        named = re.findall(r'(?:src|href)="([^"]+)"', page.decode())
        assert named, "the page names no script and no style sheet"
        for name in named:
            status, kind, _ = asked(view, f"/{name}")
            assert status == 200, name
            assert kind.split(";")[0] in {"text/javascript", "text/css"}, name
        # Nothing else is: not the FILE, not a file beside the page, not a file above it.
        for other in ["/trip.json", "/serve.py", "/../cli.py", "/static/view.js", "/nothing"]:
            assert asked(view, other)[0] == 404, other


def test_the_view_serves_this_machine_only(tmp_path: Path) -> None:
    """A page on another site cannot reach the view under a name of its own."""
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    with serving(path) as view:
        assert view.address.startswith("http://127.0.0.1:")
        port = view.address.rstrip("/").rsplit(":", 1)[1]
        assert asked(view, "/", host=f"localhost:{port}")[0] == 200
        for host in ["example.com", f"example.com:{port}", "127.0.0.1:1"]:
            assert asked(view, "/", host=host)[0] == 403, host
            assert asked(view, "/events", host=host)[0] == 403, host


def test_the_page_asks_no_other_host_for_anything() -> None:
    for part in sorted(STATIC.iterdir()):
        assert part.suffix in {".html", ".css", ".js"}, part.name
        assert not re.search(r"https?://|//[a-z]", part.read_text()), part.name


def test_the_command_serves_the_view(tmp_path: Path) -> None:
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    command = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys; from agloe.cli import main; sys.exit(main())",
            "view",
            str(path),
            "--port",
            "0",
            "--no-browser",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert command.stdout is not None
        ready, _, _ = select.select([command.stdout], [], [], 60)
        assert ready, "the command said nothing"
        address = command.stdout.readline().split()[-1]
        assert address.startswith("http://127.0.0.1:")
        with urllib.request.urlopen(address, timeout=20) as reply:
            assert reply.status == 200
        with urllib.request.urlopen(f"{address}events", timeout=60) as reply:
            for raw in reply:
                if raw.startswith(b"data: ") and json.loads(raw[6:])["kind"] == "report":
                    break
    finally:
        command.terminate()
        command.wait(timeout=20)
    # The check ran in a process of its own, and neither process had anything to complain of.
    assert command.stderr is not None
    assert command.stderr.read() == ""


def test_the_command_needs_a_file_that_is_there(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["view", str(tmp_path / "nothing.json"), "--no-browser"]) == 2
    assert "nothing.json" in capsys.readouterr().err


def page_says(trips: list[list[dict[str, Any]]]) -> list[list[dict[str, Any]]]:
    """What the page says after each event of each series, worked out by the page's own code."""
    node = shutil.which("node")
    if node is None:
        if os.environ.get("CI"):
            pytest.fail("the tests of the view need Node")
        pytest.skip("needs Node")
    done = subprocess.run(
        [node, str(Path(__file__).parent / "view_page.mjs")],
        input=json.dumps(trips),
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    said: list[list[dict[str, Any]]] = json.loads(done.stdout)
    return said


def kind_of(report: dict[str, Any]) -> str:
    """How the page marks a report: the answer, or a warning where the plan has one."""
    if report["answer"] != "FEASIBLE":
        return report["answer"].lower()
    return "warning" if report["robust"] is False or "to_buy" in report else "feasible"


def test_the_page_says_what_the_report_says() -> None:
    """For every example: the page's first line is the report's, and its mark is the answer's."""
    series = [list(events(path)) for path in FILES]
    for path, sent, said in zip(FILES, series, page_says(series), strict=True):
        name = f"{path.parent.name}/{path.stem}"
        assert [event["kind"] for event in sent] == ["file", "answer", "report"], name
        at_first, on_file, on_answer, on_report = said
        assert at_first["mark"] == "waiting", name
        expected = json.loads(beside(path, ".expected.json").read_text())
        words = beside(path, ".expected.txt").read_text()
        # The FILE is there, and the COMPILER has not answered: the page shows no answer.
        assert on_file["mark"] == "checking", name
        assert not any(answer in on_file["line"] for answer in ANSWERS), name
        assert on_file["report"] is None, name
        # The answer comes ahead of the report, and the page says that the report is on its way.
        assert on_answer["mark"] == expected["answer"].lower(), name
        assert on_answer["line"].startswith(expected["answer"]), name
        assert on_answer["report"] is None, name
        assert on_report["mark"] == kind_of(expected), name
        assert on_report["line"] == words.split("\n")[0], name
        assert on_report["report"] == words, name
        assert on_report["old"] is False, name


def test_the_page_marks_a_report_on_the_file_as_it_was() -> None:
    """After a change the page shows no answer on the new FILE until the COMPILER gives one."""
    first = list(events(STORY / "works.json"))
    second = list(events(STORY / "cannot-work.json"))
    refused = [{"kind": "refused", "problems": ["/facts/0: fits no known shape"]}]
    (said,) = page_says([[*first, *second, *refused, *first]])
    words = (STORY / "works.expected.txt").read_text()
    changed, answered, reported = said[4:7]
    # The FILE changed: the report on the page is on the FILE as it was, and the page says so.
    assert changed["mark"] == "checking"
    assert not any(answer in changed["line"] for answer in ANSWERS)
    assert (changed["report"], changed["old"]) == (words, True)
    assert answered["line"].startswith("INFEASIBLE")
    assert (answered["report"], answered["old"]) == (words, True)
    assert reported["line"] == "INFEASIBLE: this trip cannot work."
    assert reported["old"] is False
    # A FILE that breaks the format has no report: the page shows the problems, and no answer.
    broken = said[7]
    assert broken["mark"] == "refused"
    assert broken["problems"] == ["/facts/0: fits no known shape"]
    assert not any(answer in broken["line"] for answer in ANSWERS)
    assert broken["old"] is True
    assert said[-1]["line"] == "FEASIBLE: this trip works."
    assert said[-1]["problems"] is None


def test_the_page_says_when_a_check_has_stopped() -> None:
    """An answer that came before the check stopped was proved, so it stays on the page."""
    file, answer, report = events(STORY / "cannot-work.json")
    stopped = {"kind": "stopped"}
    early, late, again = page_says(
        [[file, stopped], [file, answer, stopped], [file, stopped, file, answer, report]]
    )
    assert early[-1]["mark"] == "stopped"
    assert not any(word in early[-1]["line"] for word in ANSWERS)
    assert late[-1]["mark"] == "stopped"
    assert late[-1]["line"].startswith("INFEASIBLE")
    assert late[-1]["report"] is None
    assert again[-1]["line"] == "INFEASIBLE: this trip cannot work."


def test_the_page_knows_every_event_it_is_sent() -> None:
    """An event that the page's code does not know is an error, and never passed over."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs Node")
    done = subprocess.run(
        [node, str(Path(__file__).parent / "view_page.mjs")],
        input=json.dumps([[{"kind": "something else"}]]),
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode != 0
    assert "something else" in done.stderr
