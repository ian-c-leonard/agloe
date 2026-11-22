"""The view: ``agloe view FILE`` serves a page on this machine and keeps it up to date.

The command watches the FILE. A state of the FILE is its content at one look, and each new
state gets a number, its revision. For each state the view tells the page that there is a FILE
to check, runs the COMPILER on that content in a process of its own, and sends the answer as
soon as it is proved, then the report in words and as JSON. Every event names the revision it
is about. A FILE with no report gets the reason instead: the problems that the format names,
or why it cannot be read.

Nothing in the page judges a TRIP, and the page shows no answer on a state of the FILE until
the COMPILER has answered on that state. ``src/agloe/view/static/state.js`` works out what the
page says in each state. It has no page in it, so Node runs it here, through ``view_page.mjs``.
"""

import http.client
import json
import os
import queue
import re
import select
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from collections.abc import Generator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, cast

import pytest

from agloe import compiler
from agloe.cli import main
from agloe.file import FileError, read
from agloe.view import View
from agloe.view.check import checked
from agloe.view.serve import PAGE, REFUSED_BY_BROWSERS
from agloe.view.trip import shown
from tests.stories import EXAMPLES, lasts, lock, needs_no_right, stays

STORY = EXAMPLES / "flight-home"
STATIC = Path(__file__).parent.parent / "src" / "agloe" / "view" / "static"
FILES = sorted(
    path for path in EXAMPLES.rglob("*.json") if not path.name.endswith(".expected.json")
)
ANSWERS = ("FEASIBLE", "INFEASIBLE", "UNDETERMINED")

type Events = list[dict[str, Any]]


def beside(path: Path, ending: str) -> Path:
    return path.with_name(path.stem + ending)


def kinds(events: Events) -> list[str]:
    return [event["kind"] for event in events]


def put(path: Path, content: bytes | Path) -> None:
    """Put a FILE in the place of the old one in one step, so that no half of it is ever seen."""
    new = path.with_name(f"{path.name}.new")
    new.write_bytes(content if isinstance(content, bytes) else content.read_bytes())
    os.replace(new, path)


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
    """What the view sends a page, read one event at a time, each within a time limit.

    The events are read in a thread of their own, and each is noted with the time it came at.
    So a limit holds whatever the view sends, and an event that came after it does not count.
    """

    def __init__(self, view: View | str) -> None:
        address = view if isinstance(view, str) else view.address
        self.reply = urllib.request.urlopen(f"{address}events", timeout=120)
        self.read: queue.Queue[tuple[float, dict[str, Any] | Exception | None]] = queue.Queue()
        threading.Thread(target=self._listen, daemon=True).start()

    def _listen(self) -> None:
        try:
            for raw in self.reply:
                # The view says now and then that it is still there. That is no event.
                if raw.startswith(b"data: "):
                    event = json.loads(raw.removeprefix(b"data: "))
                    if not isinstance(event, dict):
                        raise ValueError(f"{event!r} is no event")
                    self.read.put((time.monotonic(), cast("dict[str, Any]", event)))
        except OSError:
            pass
        except ValueError as problem:
            self.read.put((time.monotonic(), problem))
        self.read.put((time.monotonic(), None))

    def _next(self, late: float) -> dict[str, Any] | None:
        """The next event that came before this time, or None where the view stopped sending."""
        try:
            came, event = self.read.get(timeout=max(0.0, late - time.monotonic()))
        except queue.Empty:
            raise AssertionError("the view sent no event in time") from None
        assert came <= late, "the view sent no event in time"
        assert not isinstance(event, Exception), f"the view sent a line that is no event: {event}"
        return event

    def next(self, within: float = 60) -> dict[str, Any]:
        event = self._next(time.monotonic() + within)
        assert event is not None, "the view stopped sending"
        return event

    def until(self, kind: str, within: float = 60) -> Events:
        """Every event up to the first of this kind, all of them within the time."""
        late = time.monotonic() + within
        seen: Events = []
        while not seen or seen[-1]["kind"] != kind:
            event = self._next(late)
            assert event is not None, "the view stopped sending"
            seen.append(event)
        return seen

    def ended(self, within: float = 20) -> bool:
        """Whether the view stops sending within the time, with no further event."""
        return self._next(time.monotonic() + within) is None


def stand_in(folder: Path, does: str) -> str:
    """A program that runs in the place of the Python that checks, and does this instead."""
    program = folder / "python"
    program.write_text(f"#!/bin/sh\ncat > /dev/null\n{does}\n")
    program.chmod(0o755)
    return str(program)


def running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def gone(pid: int, within: float = 10) -> bool:
    """Whether this process ends within the time."""
    late = time.monotonic() + within
    while running(pid) and time.monotonic() < late:
        time.sleep(0.05)
    return not running(pid)


def port_of(view: View) -> int:
    return int(view.address.rstrip("/").rsplit(":", 1)[1])


def asked(view: View, path: str, **headers: str) -> tuple[int, http.client.HTTPMessage, bytes]:
    """The status, the headers and the content that the view gives for one path.

    The content of the events is left unread: it never ends.
    """
    named = {"Host": f"127.0.0.1:{port_of(view)}"}
    named.update({name.replace("_", "-"): value for name, value in headers.items()})
    connection = http.client.HTTPConnection("127.0.0.1", port_of(view), timeout=20)
    try:
        connection.request("GET", path, headers=named)
        reply = connection.getresponse()
        content = b"" if path == "/events" and reply.status == 200 else reply.read()
        return reply.status, reply.headers, content
    finally:
        connection.close()


@pytest.mark.parametrize("name", ["works", "works-but-risky", "cannot-work", "depends-on-the-cab"])
def test_a_page_is_sent_the_file_then_the_answer_then_the_report(name: str, tmp_path: Path) -> None:
    path = tmp_path / "trip.json"
    shutil.copy(STORY / f"{name}.json", path)
    expected = json.loads((STORY / f"{name}.expected.json").read_text())
    with serving(path) as view:
        file, answer, report = Sent(view).until("report")
    assert file == {"kind": "file", "name": "trip.json", "revision": 1, "view": view.id}
    assert (answer["kind"], answer["answer"]) == ("answer", expected["answer"])
    assert report["answer"] == expected["answer"]
    assert report["json"] == expected
    assert report["text"] == (STORY / f"{name}.expected.txt").read_text()
    # With the report comes the TRIP as the page draws it.
    checked_file = read(path)
    assert report["trip"] == shown(checked_file, compiler.check(checked_file))
    assert report["trip"]["itinerary"] is (expected["answer"] == "FEASIBLE")
    assert 0 <= answer["seconds"] <= report["seconds"]
    # Each event names the state of the FILE that it is about.
    assert answer["revision"] == report["revision"] == 1


def test_a_file_that_changes_is_checked_again(tmp_path: Path) -> None:
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    with serving(path) as view:
        sent = Sent(view)
        assert sent.until("report")[-1]["answer"] == "FEASIBLE"
        put(path, STORY / "cannot-work.json")
        again = sent.until("report")
    assert kinds(again) == ["file", "answer", "report"]
    assert {event["revision"] for event in again} == {2}
    assert again[-1]["json"] == json.loads((STORY / "cannot-work.expected.json").read_text())


def test_a_change_that_keeps_the_size_and_the_time_of_the_file_is_seen(tmp_path: Path) -> None:
    """The view tells one state of the FILE from another by its content."""
    path = tmp_path / "trip.json"
    before = (STORY / "works.json").read_bytes()
    after = before.replace(b'"duration": "PT1H"', b'"duration": "PT3H"', 1)
    assert len(after) == len(before)
    assert after != before
    path.write_bytes(before)
    written = path.stat()
    with serving(path) as view:
        sent = Sent(view)
        assert sent.until("report")[-1]["answer"] == "FEASIBLE"
        with path.open("r+b") as file:
            file.write(after)
        os.utime(path, ns=(written.st_atime_ns, written.st_mtime_ns))
        again = sent.until("report")
    assert again[0]["kind"] == "file"
    assert again[-1]["answer"] != "FEASIBLE"


def test_a_file_that_is_written_in_two_steps_is_checked_at_each(tmp_path: Path) -> None:
    """Half a FILE has no report. The whole FILE gets one, and the page is told which is which."""
    path = tmp_path / "trip.json"
    whole = (STORY / "works.json").read_bytes()
    path.write_bytes(whole[: len(whole) // 2])
    with serving(path) as view:
        sent = Sent(view)
        half = sent.until("refused")
        put(path, whole)
        done = sent.until("report")
    assert kinds(half) == ["file", "refused"]
    assert half[-1]["problems"][0].startswith("not readable as JSON")
    assert kinds(done) == ["file", "answer", "report"]
    assert done[0]["revision"] > half[0]["revision"]


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
        put(path, STORY / "works.json")
        mended = sent.until("report")
    assert kinds(first) == ["file", "refused"]
    assert first[-1]["problems"] == list(refused.value.problems)
    assert kinds(mended) == ["file", "answer", "report"]


def test_a_file_that_cannot_be_read_has_no_report(tmp_path: Path) -> None:
    """A FILE that is taken away is no FILE that breaks the format: the page is told why."""
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    with serving(path) as view:
        sent = Sent(view)
        sent.until("report")
        path.unlink()
        away = sent.until("unreadable")
        put(path, STORY / "works.json")
        back = sent.until("report")
    assert kinds(away) == ["file", "unreadable"]
    assert away[-1]["problem"] == "No such file or directory"
    assert kinds(back) == ["file", "answer", "report"]


@pytest.mark.parametrize("ending", [b"\n", b"\r\n", b"\r"], ids=["LF", "CRLF", "CR"])
def test_a_file_that_is_no_json_is_refused_in_the_words_of_the_command(
    ending: bytes, tmp_path: Path
) -> None:
    """The view and ``agloe check`` name the same line of the FILE, whatever ends its lines."""
    path = tmp_path / "trip.json"
    path.write_bytes(b"{" + ending + b'  "persons": [' + ending + b"?}")
    with pytest.raises(FileError) as refused:
        read(path)
    assert "line 3" in refused.value.problems[0]
    with serving(path) as view:
        sent = Sent(view).until("refused")
    assert sent[-1]["problems"] == list(refused.value.problems)


def test_each_view_has_a_name_of_its_own(tmp_path: Path) -> None:
    """A page that listened to one view can tell when another one answers at the same address."""
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    with serving(path) as one, serving(path) as other:
        assert one.id != other.id
        assert Sent(one).next()["view"] == one.id
        assert Sent(other).next()["view"] == other.id


def test_a_page_that_comes_late_is_sent_the_same(tmp_path: Path) -> None:
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    with serving(path) as view:
        first = Sent(view).until("report")
        late = Sent(view).until("report")
    assert late == first


def test_the_answer_reaches_a_page_while_the_check_goes_on(tmp_path: Path) -> None:
    """And a check that the FILE has moved on from is ended, as is the last one at the end."""
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    says = '{"kind": "answer", "answer": "FEASIBLE", "seconds": 0.1}'
    # The stand-in notes which process it is, gives an answer, and then never ends by itself.
    held = stand_in(tmp_path, f"echo $$ > \"$0.$$\"\nprintf '%s\\n' '{says}'\nexec sleep 600")

    def checks() -> list[int]:
        return sorted(int(noted.suffix[1:]) for noted in tmp_path.glob("python.*"))

    with serving(path, python=held) as view:
        sent = Sent(view)
        early = sent.until("answer", within=20)
        (first,) = checks()
        assert running(first)
        put(path, STORY / "cannot-work.json")
        again = sent.until("answer", within=20)
        assert gone(first), "the check of the FILE as it was is still running"
        (second,) = [check for check in checks() if check != first]
        assert running(second)
    assert kinds(early) == kinds(again) == ["file", "answer"]
    assert again[0]["revision"] > early[0]["revision"]
    assert gone(second), "a check is still running after the view has stopped"


@pytest.mark.parametrize(
    "does",
    [
        "exit 3",
        "echo this is no event",
        "echo '[1, 2]'",
        "printf '\\377\\376\\n'",
        """echo '{"kind": "report"}'""",
        """echo '{"kind": "answer", "answer": "PERHAPS", "seconds": 1}'""",
        """echo '{"kind": "refused", "problems": [1]}'""",
        """echo '{"kind": "file", "name": "another.json"}'""",
        (
            """echo '{"kind": "report", "answer": "FEASIBLE", "json": {}, "text": "", """
            """"trip": null, "seconds": 1}'"""
        ),
        # An answer with a TRIP, which only a report has, and one that is no number at that.
        """echo '{"kind": "answer", "answer": "FEASIBLE", "seconds": 1, "trip": NaN}'""",
        """echo '{"kind": "answer", "answer": "FEASIBLE", "seconds": 1, "trip": null}'""",
        # A report with one thing more than a report holds.
        (
            """echo '{"kind": "report", "answer": "FEASIBLE", "json": {"answer": "FEASIBLE"}, """
            """"text": "", "trip": null, "more": 1, "seconds": 1}'"""
        ),
        """echo '{"kind": "answer", "answer": "FEASIBLE", "seconds": true}'""",
        """echo '{"kind": "answer", "answer": "FEASIBLE", "seconds": NaN}'""",
        """echo '{"kind": "answer", "answer": "FEASIBLE", "seconds": -1}'""",
        """echo '{"kind": "answer", "answer": "FEASIBLE", "seconds": 1e400}'""",
        f"""echo '{{"kind": "answer", "answer": "FEASIBLE", "seconds": 1{"0" * 400}}}'""",
        (
            """echo '{"kind": "report", "answer": "FEASIBLE", "text": "", "seconds": 1, """
            """"trip": null, "json": {"answer": "FEASIBLE", "robust": 1e400}}'"""
        ),
        None,
    ],
)
def test_a_check_that_ends_without_a_report_has_stopped(does: str | None, tmp_path: Path) -> None:
    """The page is told, so it never waits for a report that will not come.

    The check fails, or says something that is no event, or there is nothing to run it with.
    """
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    python = str(tmp_path / "nothing") if does is None else stand_in(tmp_path, does)
    with serving(path, python=python) as view:
        stopped = Sent(view).until("stopped", within=20)
    assert stopped == [
        {"kind": "file", "name": "trip.json", "revision": 1, "view": view.id},
        {"kind": "stopped", "revision": 1},
    ]


EMPTY = (
    '{"zone": "UTC", "persons": [], "places": [], "starts_from": [], '
    '"itinerary": true, "days": [], '
    '"until": null, "starts": null, "ends": null, "steps": [], "wants": [], "options": [], '
    '"ways": [], "complete_travel": [], "rights": [], "capabilities": []}'
)


@pytest.mark.parametrize(
    ("trip", "reaches"),
    [
        (f', "trip": {EMPTY}', True),
        # No TRIP, one that a page cannot draw, and one for another answer than the report's.
        (', "trip": null', False),
        ("", False),
        (', "trip": {}', False),
        (', "trip": []', False),
        (', "trip": "none"', False),
        (', "trip": true', False),
        (f', "trip": {EMPTY.replace("true", "false")}', False),
        (f', "trip": {EMPTY.replace('"steps": []', '"steps": [{}]')}', False),
        # One with a number that no page can read, and one with a number that is none.
        (f', "trip": {EMPTY.replace('"days": []', '"days": [1e400]')}', False),
        (f', "trip": {EMPTY.replace("null", "NaN", 1)}', False),
    ],
    ids=[
        "a TRIP",
        "none",
        "missing",
        "empty",
        "a list",
        "words",
        "a yes",
        "another answer",
        "half",
        "too large a number",
        "no number",
    ],
)
def test_a_report_reaches_a_page_whatever_its_trip_is(
    trip: str, reaches: bool, tmp_path: Path
) -> None:
    """A report is whole without the TRIP that the calendar draws.

    So a page is sent the report with its TRIP where that is one it can draw, and with none
    where it is not. What is wrong with a calendar never costs the reader the report.
    """
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    report = (
        '{"kind": "report", "answer": "FEASIBLE", "json": {"answer": "FEASIBLE"}, '
        f'"text": "FEASIBLE: this trip works.", "seconds": 1{trip}}}'
    )
    with serving(path, python=stand_in(tmp_path, f"echo '{report}'")) as view:
        sent = Sent(view).until("report", within=20)
    assert kinds(sent) == ["file", "report"]
    assert sent[-1]["text"] == "FEASIBLE: this trip works."
    assert sent[-1]["trip"] == (json.loads(EMPTY) if reaches else None)


def test_a_fault_in_what_makes_the_drawing_costs_the_calendar_and_not_the_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fails(*given: object) -> None:
        raise RuntimeError("a fault in the drawing")

    monkeypatch.setattr("agloe.view.trip.shown", fails)
    file, answer, report = sent_for((STORY / "works.json").read_bytes())
    assert kinds([file, answer, report]) == ["file", "answer", "report"]
    assert report["text"] == (STORY / "works.expected.txt").read_text()
    assert report["json"] == json.loads((STORY / "works.expected.json").read_text())
    assert report["trip"] is None
    # The page shows the answer and the report, and has no TRIP for the calendar.
    (said,) = page_says([[file, answer, report]])
    assert said[-1]["line"] == "FEASIBLE: this trip works."
    assert said[-1]["calendar"] == {"trip": None, "report": report["json"]}

    # So it is where what is made cannot be printed.
    def unprintable(*given: object) -> dict[str, date]:
        return {"day": date(2027, 5, 15)}

    monkeypatch.setattr("agloe.view.trip.shown", unprintable)
    *_, report = sent_for((STORY / "works.json").read_bytes())
    assert (report["kind"], report["trip"]) == ("report", None)
    assert report["text"] == (STORY / "works.expected.txt").read_text()


def test_a_pipe_in_the_place_of_the_file_cannot_hold_the_view_up(tmp_path: Path) -> None:
    """Only a regular file is read. A pipe with nobody writing to it would never give its end."""
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    with serving(path) as view:
        sent = Sent(view)
        sent.until("report")
        os.mkfifo(tmp_path / "pipe")
        os.replace(tmp_path / "pipe", path)
        pipe = sent.until("unreadable")
    assert kinds(pipe) == ["file", "unreadable"]
    assert pipe[-1]["problem"] == "It is not a regular file"


def test_a_file_with_a_name_that_is_no_text_is_checked_like_any_other(tmp_path: Path) -> None:
    """A name on disk is bytes. The page is still sent every event."""
    path = tmp_path / os.fsdecode(b"trip-\xff.json")
    try:
        shutil.copy(STORY / "works.json", path)
    except OSError:
        pytest.skip("this file system takes no such name")
    with serving(path) as view:
        sent = Sent(view).until("report")
    assert kinds(sent) == ["file", "answer", "report"]
    assert sent[0]["name"] == path.name


def test_a_view_that_is_closed_before_it_serves_does_not_serve(tmp_path: Path) -> None:
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    view = View(path)
    view.close()
    view.serve()
    with pytest.raises(OSError):
        asked(view, "/")


def test_the_view_stops_while_a_page_listens(tmp_path: Path) -> None:
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    with serving(path) as view:
        sent = Sent(view)
        sent.until("report")
    # The view has stopped, and it has let the page go: the page reads the end of what the view
    # sends, and no further event.
    assert sent.ended()
    # And nothing answers at the address any more.
    with pytest.raises(OSError):
        asked(view, "/")


def test_the_view_serves_its_page_and_nothing_else(tmp_path: Path) -> None:
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    with serving(path) as view:
        status, headers, page = asked(view, "/")
        assert status == 200
        assert headers.get_content_type() == "text/html"
        # Every file that the page names is served, with a kind of content a browser accepts.
        named = re.findall(r'(?:src|href)="([^"]+)"', page.decode())
        assert named, "the page names no script and no style sheet"
        # So is every file that one of the page's scripts loads, at once or later.
        loaded = {
            name
            for script in STATIC.glob("*.js")
            for name in re.findall(r'(?:from |import\()"\./([^"]+)"', script.read_text())
        }
        loaded_later = {"calendar.js", "lines.js", "strip.js", "wants.js", "options.js"}
        assert {"state.js", "named.js", "times.js"} | loaded_later <= loaded
        assert {*named, *loaded} == set(PAGE) - {"index.html"}
        for name in [*named, *sorted(loaded)]:
            status, headers, _ = asked(view, f"/{name}")
            assert status == 200, name
            assert headers.get_content_type() in {"text/javascript", "text/css"}, name
        # Nothing else is: not the FILE, not a file beside the page, not a file above it.
        for other in ["/trip.json", "/serve.py", "/../cli.py", "/static/view.js", "/nothing"]:
            assert asked(view, other)[0] == 404, other


def test_the_view_tells_a_browser_to_keep_the_page_to_itself(tmp_path: Path) -> None:
    """The page loads from no other host, sits in no other page, and is kept nowhere."""
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    with serving(path) as view:
        for part in ["/", "/view.js", "/events"]:
            status, headers, _ = asked(view, part)
            assert status == 200, part
            policy = headers["Content-Security-Policy"]
            assert "default-src 'self'" in policy, part
            assert "frame-ancestors 'none'" in policy, part
            assert headers["Cache-Control"] == "no-store", part
            assert headers["X-Content-Type-Options"] == "nosniff", part
            assert headers["Cross-Origin-Resource-Policy"] == "same-origin", part


def test_the_view_serves_this_machine_only(tmp_path: Path) -> None:
    """A page on another site cannot reach the view under a name of its own, or as itself."""
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    with serving(path) as view:
        assert view.address.startswith("http://127.0.0.1:")
        port = port_of(view)
        own = f"http://127.0.0.1:{port}"
        for part in ["/", "/events"]:
            assert asked(view, part, Host=f"localhost:{port}")[0] == 200
            assert asked(view, part, Origin=own, Sec_Fetch_Site="same-origin")[0] == 200
            for host in ["example.com", f"example.com:{port}", "127.0.0.1:1", "127.0.0.1"]:
                assert asked(view, part, Host=host)[0] == 403, host
            assert asked(view, part, Origin="http://example.com")[0] == 403
            assert asked(view, part, Origin="null")[0] == 403
            for site in ["cross-site", "same-site"]:
                assert asked(view, part, Sec_Fetch_Site=site)[0] == 403, site


def test_the_page_asks_no_other_host_for_anything() -> None:
    for name in PAGE:
        assert not re.search(r"https?://|//[a-z]", (STATIC / name).read_text()), name


def test_the_page_has_every_part_that_its_code_fills() -> None:
    """The page's code finds each part of the page by its name."""
    filled = set(re.findall(r'part\("([^"]+)"\)', (STATIC / "view.js").read_text()))
    there = set(re.findall(r'id="([^"]+)"', (STATIC / "index.html").read_text()))
    assert {"line", "report", "calendar", "calendar-says"} <= filled
    assert filled <= there


def test_the_view_serves_the_answer_and_the_report_without_what_they_do_not_need(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file of the page that only the calendar needs cannot be read. The view still starts."""
    shutil.copytree(STATIC, tmp_path / "static")
    optional = [
        "lines.js",
        "calendar.js",
        "strip.js",
        "wants.js",
        "named.js",
        "times.js",
        "options.js",
    ]
    for name in optional:
        (tmp_path / "static" / name).unlink()

    def beside(package: str) -> Path:
        return tmp_path

    monkeypatch.setattr("agloe.view.serve.resources.files", beside)
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    with serving(path) as view:
        assert asked(view, "/")[0] == 200
        assert asked(view, "/state.js")[0] == 200
        for name in optional:
            assert asked(view, f"/{name}")[0] == 404
        assert kinds(Sent(view).until("report")) == ["file", "answer", "report"]
    # Without a file that the answer and the report need, there is no view.
    (tmp_path / "static" / "state.js").unlink()
    with pytest.raises(OSError, match=r"state\.js"):
        View(path)


def test_the_answer_and_the_report_need_no_calendar() -> None:
    """The page's code loads the calendar beside them, so that they show without it."""
    code = (STATIC / "view.js").read_text()
    assert re.findall(r'^import .* from "\./([^"]+)";$', code, re.MULTILINE) == ["state.js"]
    assert 'import("./calendar.js")' in code
    assert 'import("./lines.js")' in code
    assert 'import("./strip.js")' in code
    assert 'import("./wants.js")' in code
    assert 'import("./options.js")' in code
    # What the page says in each state needs nothing else at all.
    assert "import" not in (STATIC / "state.js").read_text()


def test_the_page_puts_each_mark_on_the_calendar_by_itself() -> None:
    """However many marks a day has, no call to the browser takes them all at once."""
    assert "...day.marks" not in (STATIC / "view.js").read_text()


def test_what_the_page_hides_stays_hidden() -> None:
    """A rule that lays a part out must not bring it back once the page has hidden it."""
    assert "[hidden] { display: none !important; }" in (STATIC / "view.css").read_text()


def command(path: Path, python: str | None = None) -> tuple[subprocess.Popen[str], str]:
    """The command as a process of its own, and the address of the view that it prints.

    With ``python``, the command takes that program for the Python that runs its checks.
    """
    stand_in = f"sys.executable = {python!r}; " if python else ""
    started = subprocess.Popen(
        [
            sys.executable,
            "-c",
            f"import sys; {stand_in}from agloe.cli import main; sys.exit(main())",
            "view",
            str(path),
            "--no-browser",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert started.stdout is not None
    ready, _, _ = select.select([started.stdout], [], [], 60)
    assert ready, "the command said nothing"
    address = started.stdout.readline().split()[-1]
    assert address.startswith("http://127.0.0.1:")
    return started, address


@pytest.mark.parametrize("stop", [signal.SIGINT, signal.SIGTERM], ids=["Ctrl-C", "ended"])
def test_the_command_serves_the_view_until_it_is_stopped(
    stop: signal.Signals, tmp_path: Path
) -> None:
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    started, address = command(path)
    try:
        with urllib.request.urlopen(address, timeout=20) as reply:
            assert reply.status == 200
        assert kinds(Sent(address).until("report")) == ["file", "answer", "report"]
        started.send_signal(stop)
        assert started.wait(timeout=20) == 0
    finally:
        started.kill()
        started.wait(timeout=20)
    # The check ran in a process of its own, and neither process had anything to complain of.
    assert started.stderr is not None
    assert started.stderr.read() == ""


def test_the_command_serves_a_browser_that_it_opens_and_that_waits(tmp_path: Path) -> None:
    """A browser that runs until it is closed gets its page, and does not hold the view up."""
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    got = tmp_path / "got"
    # The stand-in for a browser asks for the page, notes what it got, and then stays open.
    browser = tmp_path / "a browser.py"
    browser.write_text(
        "import os, sys, time, urllib.request\n"
        "with urllib.request.urlopen(sys.argv[1], timeout=20) as reply:\n"
        f"    open({str(got) + '.new'!r}, 'w').write(str(reply.status))\n"
        f"os.replace({str(got) + '.new'!r}, {str(got)!r})\n"
        "time.sleep(3)\n"
    )
    opens = f"{shlex.quote(sys.executable)} {shlex.quote(str(browser))} %s"
    started = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys; from agloe.cli import main; sys.exit(main())",
            "view",
            str(path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "BROWSER": opens},
    )
    try:
        late = time.monotonic() + 30
        while not got.exists() and time.monotonic() < late:
            time.sleep(0.05)
        assert got.exists(), "the browser that the command opened got no page"
        assert got.read_text() == "200"
        started.send_signal(signal.SIGINT)
        assert started.wait(timeout=20) == 0
    finally:
        started.kill()
        started.wait(timeout=20)


@pytest.mark.parametrize("stop", [signal.SIGINT, signal.SIGTERM], ids=["Ctrl-C", "ended"])
def test_stopping_the_command_ends_the_check_that_is_running(
    stop: signal.Signals, tmp_path: Path
) -> None:
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    says = '{"kind": "answer", "answer": "FEASIBLE", "seconds": 0.1}'
    # The stand-in notes which process it is, gives an answer, and then never ends by itself.
    held = stand_in(tmp_path, f"echo $$ > \"$0.$$\"\nprintf '%s\\n' '{says}'\nexec sleep 600")
    started, address = command(path, python=held)
    try:
        assert kinds(Sent(address).until("answer", within=20)) == ["file", "answer"]
        (check,) = [int(noted.suffix[1:]) for noted in tmp_path.glob("python.*")]
        assert running(check)
        started.send_signal(stop)
        assert started.wait(timeout=20) == 0
        assert gone(check), "the check is still running after the command has ended"
    finally:
        started.kill()
        started.wait(timeout=20)


@pytest.mark.parametrize("port", [80, 1023, 65536, -1, 6000, 10080])
def test_the_view_serves_only_a_port_that_browsers_open(port: int, tmp_path: Path) -> None:
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    with pytest.raises(ValueError, match=str(port)):
        View(path, port=port)


def test_the_view_takes_a_free_port_that_browsers_open(tmp_path: Path) -> None:
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    views = [View(path) for _ in range(5)]
    try:
        ports = [port_of(view) for view in views]
        assert len(set(ports)) == len(ports)
        assert not set(ports) & REFUSED_BY_BROWSERS
        assert all(1024 <= port <= 65535 for port in ports)
    finally:
        for view in views:
            view.close()


def test_the_view_looks_no_name_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A view starts at once on a machine that is slow to answer for a name: it asks for none."""

    def looked_up(*asked: object) -> str:
        raise AssertionError(f"the view looked a name up: {asked}")

    monkeypatch.setattr(socket, "getfqdn", looked_up)
    monkeypatch.setattr(socket, "gethostbyaddr", looked_up)
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    View(path).close()


def test_the_command_needs_a_file_that_is_there(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["view", str(tmp_path / "nothing.json"), "--no-browser"]) == 2
    assert "nothing.json" in capsys.readouterr().err


@pytest.mark.parametrize("port", ["80", "1023", "65536", "-1", "6000", "10080"])
def test_the_command_needs_a_port_that_it_can_serve_on(
    port: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    assert main(["view", str(path), "--no-browser", f"--port={port}"]) == 2
    assert port in capsys.readouterr().err


def page_says(trips: list[Events]) -> list[Events]:
    """What the page says before any event and after each one, by the page's own code."""
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
    said: list[Events] = json.loads(done.stdout)
    return said


def sent_for(
    content: bytes, revision: int = 1, name: str = "trip.json", view: str = "one"
) -> Events:
    """What the view sends a page about one state of a FILE, as ``serve`` puts it together."""
    file: dict[str, Any] = {"kind": "file", "name": name, "revision": revision, "view": view}
    return [file, *({**event, "revision": revision} for event in checked(content))]


def kind_of(report: dict[str, Any]) -> str:
    """How the page marks a report: the answer, or a warning where the plan has one."""
    if report["answer"] != "FEASIBLE":
        return str(report["answer"]).lower()
    return "warning" if report["robust"] is False or "to_buy" in report else "feasible"


def test_the_page_says_what_the_report_says() -> None:
    """For every example: the page's first line is the report's, and its mark is the answer's."""
    series = [sent_for(path.read_bytes()) for path in FILES]
    for path, sent, said in zip(FILES, series, page_says(series), strict=True):
        name = f"{path.parent.name}/{path.stem}"
        assert kinds(sent) == ["file", "answer", "report"], name
        at_first, on_file, on_answer, on_report = said
        assert at_first["mark"] == "waiting", name
        expected = json.loads(beside(path, ".expected.json").read_text())
        words = beside(path, ".expected.txt").read_text()
        # There is a FILE, and the COMPILER has not answered: the page shows no answer.
        assert on_file["mark"] == "checking", name
        assert not any(answer in on_file["line"] for answer in ANSWERS), name
        assert on_file["report"] is None, name
        assert on_file["calendar"] is None, name
        # The answer comes ahead of the report, and the page says that the report is on its way.
        assert on_answer["mark"] == expected["answer"].lower(), name
        assert on_answer["line"].startswith(expected["answer"]), name
        assert on_answer["report"] is None, name
        assert on_answer["calendar"] is None, name
        assert on_report["mark"] == kind_of(expected), name
        assert on_report["line"] == words.split("\n")[0], name
        assert on_report["report"] == words, name
        assert on_report["old"] is False, name
        # The calendar is of the TRIP that came with the report.
        assert on_report["calendar"] == {"trip": sent[-1]["trip"], "report": expected}, name
        assert sent[-1]["trip"]["itinerary"] is (expected["answer"] == "FEASIBLE"), name


def test_the_page_marks_a_report_on_the_file_as_it_was() -> None:
    """After a change the page shows no answer on the new FILE until the COMPILER gives one."""
    first = sent_for((STORY / "works.json").read_bytes(), 1)
    second = sent_for((STORY / "cannot-work.json").read_bytes(), 2)
    refused: Events = [
        {"kind": "file", "name": "trip.json", "revision": 3, "view": "one"},
        {"kind": "refused", "problems": ["/facts/0: fits no known shape"], "revision": 3},
    ]
    last = sent_for((STORY / "works.json").read_bytes(), 4)
    (said,) = page_says([[*first, *second, *refused, *last]])
    words = (STORY / "works.expected.txt").read_text()
    changed, answered, reported = said[4:7]
    # The FILE changed: the report on the page is on the FILE as it was, and the page says so.
    assert changed["mark"] == "checking"
    assert not any(answer in changed["line"] for answer in ANSWERS)
    assert (changed["report"], changed["old"]) == (words, True)
    assert answered["line"].startswith("INFEASIBLE")
    assert (answered["report"], answered["old"]) == (words, True)
    # The calendar on the page is the one of that report, and it is marked with it.
    kept = {"trip": first[-1]["trip"], "report": first[-1]["json"]}
    assert changed["calendar"] == answered["calendar"] == kept
    # The page says so of all that it still shows of that FILE, and names no part of it.
    assert changed["note"].endswith("What the page shows below is on the FILE as it was before.")
    assert reported["line"] == "INFEASIBLE: this trip cannot work."
    assert reported["old"] is False
    assert reported["calendar"] == {"trip": second[-1]["trip"], "report": second[-1]["json"]}
    assert reported["calendar"] != changed["calendar"]
    # A FILE that breaks the format has no report: the page shows the problems, and no answer.
    broken = said[8]
    assert broken["mark"] == "refused"
    assert broken["problems"] == ["/facts/0: fits no known shape"]
    assert not any(answer in broken["line"] for answer in ANSWERS)
    assert broken["old"] is True
    assert broken["calendar"] == reported["calendar"]
    assert said[-1]["line"] == "FEASIBLE: this trip works."
    assert said[-1]["problems"] is None


def test_the_page_takes_no_answer_for_another_state_of_the_file() -> None:
    """An event that names another revision than the page was last told of is passed over."""
    file, answer, report = sent_for((STORY / "cannot-work.json").read_bytes(), 1)
    newer: dict[str, Any] = {"kind": "file", "name": "trip.json", "revision": 2, "view": "one"}
    (said,) = page_says([[file, newer, answer, report, {"kind": "stopped", "revision": 1}]])
    for after_it in said[2:]:
        assert after_it["mark"] == "checking"
        assert after_it["report"] is None
        assert not any(word in after_it["line"] for word in ANSWERS)


def test_the_page_says_when_a_check_has_stopped() -> None:
    """An answer that came before the check stopped was proved, so it stays on the page."""
    file, answer, report = sent_for((STORY / "cannot-work.json").read_bytes(), 1)
    stopped = {"kind": "stopped", "revision": 1}
    early, late = page_says([[file, stopped], [file, answer, stopped]])
    assert early[-1]["mark"] == "stopped"
    assert not any(word in early[-1]["line"] for word in ANSWERS)
    assert late[-1]["mark"] == "stopped"
    assert late[-1]["line"].startswith("INFEASIBLE")
    assert late[-1]["report"] is None
    # The next state of the FILE starts afresh.
    again = sent_for((STORY / "cannot-work.json").read_bytes(), 2)
    (said,) = page_says([[file, answer, stopped, *again]])
    assert said[-1]["line"] == report["text"].split("\n")[0]


def test_the_page_says_why_a_file_has_no_report() -> None:
    """A FILE that cannot be read is not said to break the format."""
    file: dict[str, Any] = {"kind": "file", "name": "trip.json", "revision": 1, "view": "one"}
    unreadable = {"kind": "unreadable", "problem": "No such file or directory", "revision": 1}
    ((_, _, away),) = page_says([[file, unreadable]])
    assert away["mark"] == "unreadable"
    assert "format" not in away["line"]
    assert "No such file or directory" in away["note"]
    assert away["problems"] is None


def test_the_page_keeps_the_answer_of_a_report_that_cannot_be_written() -> None:
    """The stay starts in the last second of the year 9999 and ends one second later."""
    document = {
        "persons": [{"id": "alex", "name": "Alex"}],
        "places": [{"id": "pier", "name": "Navy Pier"}],
        "options": [stays("fireworks", "pier")],
        "ways": [],
        "wants": [],
        "facts": [
            {
                "id": "fireworks-time",
                "option": "fireworks",
                "starts_at": "9999-12-31T23:59:59+00:00[UTC]",
            },
            lasts("fireworks", "PT1S"),
            needs_no_right("fireworks"),
        ],
        "decisions": [lock("fireworks", "alex")],
    }
    sent = sent_for(json.dumps(document).encode())
    assert kinds(sent) == ["file", "answer", "unwritable"]
    (said,) = page_says([sent])
    assert said[-1]["mark"] == "feasible"
    assert said[-1]["line"].startswith("FEASIBLE")
    assert "format" not in said[-1]["line"]
    assert "0001 to 9999" in said[-1]["note"]
    assert said[-1]["problems"] is None


def test_the_page_says_when_it_no_longer_hears_the_view() -> None:
    """What it shows stays, marked as on the FILE as it was, until the view speaks again."""
    first = sent_for((STORY / "works.json").read_bytes(), 1)
    again = sent_for((STORY / "works.json").read_bytes(), 1)
    (said,) = page_says([[*first, {"kind": "lost"}, *again]])
    lost = said[4]
    assert lost["mark"] == "lost"
    assert not any(word in lost["line"] for word in ANSWERS)
    assert lost["old"] is True
    assert lost["report"] == (STORY / "works.expected.txt").read_text()
    # The view speaks again: the page starts afresh on the FILE that the view tells it of.
    assert said[5]["mark"] == "checking"
    assert said[5]["old"] is True
    assert said[-1]["line"] == "FEASIBLE: this trip works."
    assert said[-1]["old"] is False


def test_the_page_keeps_no_report_from_another_view() -> None:
    """A view was stopped, and another one now serves another FILE at the same address."""
    first = sent_for((STORY / "works.json").read_bytes(), 3, view="one")
    other: Events = [
        {"kind": "file", "name": "other.json", "revision": 1, "view": "two"},
        {"kind": "refused", "problems": ["not readable as JSON"], "revision": 1},
    ]
    (said,) = page_says([[*first, {"kind": "lost"}, *other]])
    assert said[4]["report"] == (STORY / "works.expected.txt").read_text()
    assert said[4]["calendar"] == {"trip": first[-1]["trip"], "report": first[-1]["json"]}
    for after_it in said[5:]:
        assert after_it["name"] == "other.json"
        assert after_it["report"] is None
        assert after_it["calendar"] is None
        assert after_it["old"] is False
    assert said[-1]["mark"] == "refused"


def test_the_page_knows_every_event_it_is_sent() -> None:
    """An event that the page's code does not know is an error, and never passed over."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs Node")
    file = {"kind": "file", "name": "trip.json", "revision": 1, "view": "one"}
    done = subprocess.run(
        [node, str(Path(__file__).parent / "view_page.mjs")],
        input=json.dumps([[file, {"kind": "something else", "revision": 1}]]),
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode != 0
    assert "something else" in done.stderr
