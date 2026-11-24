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
from agloe.view.trip import holds, shown
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
def serving(
    path: Path, python: str = sys.executable, allowed_host: str | None = None
) -> Generator[View]:
    """The view of one FILE, served on a free port of this machine until the test is done.

    ``allowed_host`` is one more name that the view answers under.
    """
    view = View(path, port=0, python=python, allowed_host=allowed_host)
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
        file, first, answer, report = Sent(view).until("report")
    assert file == {"kind": "file", "name": "trip.json", "revision": 1, "view": view.id}
    # Before any answer comes the TRIP as the page draws it from the FILE alone. It says that
    # it has no report, and its steps are the OPTIONs that a LOCK names.
    assert first == {"kind": "read", "revision": 1, "trip": shown(read(path))}
    assert first["trip"]["itinerary"] is None
    assert holds(first["trip"])
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
    assert kinds(again) == ["file", "read", "answer", "report"]
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
    assert kinds(done) == ["file", "read", "answer", "report"]
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
    assert kinds(mended) == ["file", "read", "answer", "report"]


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
    assert kinds(back) == ["file", "read", "answer", "report"]


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
    '"ways": [], "complete_travel": [], "rights": [], "budgets": [], "capabilities": [], '
    '"objects": []}'
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


@pytest.mark.parametrize(
    ("trip", "reaches"),
    [
        (f', "trip": {EMPTY.replace("true", "null")}', True),
        # No TRIP, one that a page cannot draw, and one that says it came with a report.
        (', "trip": null', False),
        ("", False),
        (', "trip": {}', False),
        (f', "trip": {EMPTY}', False),
        (f', "trip": {EMPTY.replace("true", "false")}', False),
        (
            f', "trip": {EMPTY.replace("true", "null").replace('"days": []', '"days": [1e400]')}',
            False,
        ),
    ],
    ids=[
        "a TRIP",
        "none",
        "missing",
        "empty",
        "with a plan",
        "with a report",
        "too large a number",
    ],
)
def test_what_a_check_read_reaches_a_page_whatever_its_trip_is(
    trip: str, reaches: bool, tmp_path: Path
) -> None:
    """Before any answer, a check sends the TRIP as a page draws it from the FILE alone.

    A page is sent that TRIP where it is one it can draw and says that it has no report, and
    none where it is not. The answer and the report follow all the same.
    """
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    read_it = f'{{"kind": "read"{trip}}}'
    report = (
        '{"kind": "report", "answer": "FEASIBLE", "json": {"answer": "FEASIBLE"}, '
        '"text": "FEASIBLE: this trip works.", "seconds": 1}'
    )
    does = f"echo '{read_it}'\necho '{report}'"
    with serving(path, python=stand_in(tmp_path, does)) as view:
        sent = Sent(view).until("report", within=20)
    assert kinds(sent) == ["file", "read", "report"]
    expected = json.loads(EMPTY.replace("true", "null")) if reaches else None
    assert sent[1] == {"kind": "read", "revision": 1, "trip": expected}
    assert sent[-1]["text"] == "FEASIBLE: this trip works."


def test_what_a_check_read_holds_nothing_but_its_trip(tmp_path: Path) -> None:
    """An event with one thing more is no event, and the check that printed it has stopped."""
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    does = """echo '{"kind": "read", "trip": null, "answer": "FEASIBLE"}'"""
    with serving(path, python=stand_in(tmp_path, does)) as view:
        sent = Sent(view).until("stopped", within=20)
    assert kinds(sent) == ["file", "stopped"]


def test_a_fault_in_what_makes_the_drawing_costs_the_calendar_and_not_the_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fails(*given: object) -> None:
        raise RuntimeError("a fault in the drawing")

    monkeypatch.setattr("agloe.view.trip.shown", fails)
    file, first, answer, report = sent_for((STORY / "works.json").read_bytes())
    assert kinds([file, first, answer, report]) == ["file", "read", "answer", "report"]
    assert report["text"] == (STORY / "works.expected.txt").read_text()
    assert report["json"] == json.loads((STORY / "works.expected.json").read_text())
    assert (first["trip"], report["trip"]) == (None, None)
    # The page shows the answer and the report, and has no TRIP for the calendar.
    (said,) = page_says([[file, first, answer, report]])
    assert said[2]["calendar"] is None
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
    assert kinds(sent) == ["file", "read", "answer", "report"]
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
            # A page that opened the view from another site keeps no hold on its window.
            assert headers["Cross-Origin-Opener-Policy"] == "same-origin", part


def status_of(view: View, *lines: str) -> int:
    """The status that the view gives for a request with these lines after its first, sent
    as they are: a line can be there twice, and can end in blanks."""
    request = "\r\n".join(["GET / HTTP/1.1", *lines, "Connection: close", "", ""])
    with socket.create_connection(("127.0.0.1", port_of(view)), timeout=20) as line:
        line.sendall(request.encode("latin-1"))
        reply = line.makefile("rb").readline().decode("latin-1")
    return int(reply.split()[1])


def test_a_request_says_each_thing_about_itself_once(tmp_path: Path) -> None:
    """A request that names two hosts, or says twice where it comes from, is no request: the
    view looks at one of each, and the other could say anything."""
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    with serving(path, allowed_host="view.example.org") as view:
        own = f"127.0.0.1:{port_of(view)}"
        assert status_of(view, f"Host: {own}") == 200
        assert status_of(view, "Host: view.example.org", "Origin: https://view.example.org") == 200
        for twice in [
            [f"Host: {own}", "Host: evil.example"],
            ["Host: evil.example", f"Host: {own}"],
            [f"Host: {own}", f"Host: {own}"],
            [f"Host: {own}", f"Origin: http://{own}", "Origin: https://evil.example"],
            [f"Host: {own}", "Sec-Fetch-Site: same-origin", "Sec-Fetch-Site: cross-site"],
            [f"Host: {own}", "Sec-Fetch-Mode: navigate", "Sec-Fetch-Mode: cors"],
            [f"Host: {own}", "Sec-Fetch-Dest: document", "Sec-Fetch-Dest: iframe"],
            # Two words on where a request comes from are no request, with or without a host.
            ["Origin: https://evil.example", "Origin: https://evil.example"],
        ]:
            assert status_of(view, *twice) == 400, twice
        # A request that names no host is refused like one that names another.
        assert status_of(view) == 403
        # Blanks around what a line says are no part of it.
        assert status_of(view, "Host:   view.example.org \t") == 200
        assert status_of(view, f"Host: {own}", "Sec-Fetch-Site:  same-origin ") == 200
        assert status_of(view, "Host: view.example.org", "Origin: https://view.example.org ") == 200
        # A blank inside a name makes it another name.
        assert status_of(view, "Host: view.example .org") == 403


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
        links_from_elsewhere(view)


def links_from_elsewhere(view: View, **named: str) -> None:
    """Checks that a link on another site can open the page itself, and nothing else of the
    view. A sign-in on another site sends its reader back to the page that way. ``named`` is
    the Host line of the request, where it is not the view's own address."""
    link = {"Sec_Fetch_Mode": "navigate", "Sec_Fetch_Dest": "document"}
    for site in ["cross-site", "same-site"]:
        assert asked(view, "/", Sec_Fetch_Site=site, **link, **named)[0] == 200, site
        assert asked(view, "/?from=elsewhere", Sec_Fetch_Site=site, **link, **named)[0] == 200
        # What the page is to show, and the page's own files, are for the page alone.
        for part in ["/events", "/view.js", "/view.css"]:
            assert asked(view, part, Sec_Fetch_Site=site, **link, **named)[0] == 403, part
        # The page is shown in no other page, and it is no part of another page.
        for mode, kind in [
            ("navigate", "iframe"),
            ("navigate", "frame"),
            ("navigate", "embed"),
            ("navigate", "object"),
            ("no-cors", "document"),
            ("cors", "empty"),
            ("no-cors", "script"),
        ]:
            got = asked(
                view, "/", Sec_Fetch_Site=site, Sec_Fetch_Mode=mode, Sec_Fetch_Dest=kind, **named
            )
            assert got[0] == 403, (mode, kind)
        # A request that says which other site it comes from is still refused.
        got = asked(view, "/", Sec_Fetch_Site=site, Origin="https://evil.example", **link, **named)
        assert got[0] == 403


def test_the_view_answers_under_one_more_name_that_its_owner_gives(tmp_path: Path) -> None:
    """The owner runs a gateway that passes requests on to the view under the gateway's name.
    The view answers under that name, and under no other."""
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    name = "view.example.org"
    with serving(path, allowed_host="View.Example.org") as view:
        # The view still listens on this machine only, and still answers under its own names.
        assert view.address.startswith("http://127.0.0.1:")
        port = port_of(view)
        for part in ["/", "/events"]:
            assert asked(view, part)[0] == 200
            assert asked(view, part, Host=f"localhost:{port}")[0] == 200
            # The name of a host counts whatever the case of its letters.
            for host in [name, "VIEW.example.ORG"]:
                assert asked(view, part, Host=host)[0] == 200, host
            # A page that came through the gateway is the view's own page, whether or not the
            # gateway speaks to the browser over a secured line.
            for origin in [f"https://{name}", f"http://{name}", "HTTPS://View.Example.Org"]:
                got = asked(view, part, Host=name, Origin=origin, Sec_Fetch_Site="same-origin")
                assert got[0] == 200, origin
            # No other name is the view's.
            others = ["example.org", f"{name}:8443", f"{name}.evil.example", f"evil.{name}"]
            for host in others:
                assert asked(view, part, Host=host)[0] == 403, host
            # A page of another site is not the view's page, also not one of a site beside it.
            for origin in ["https://evil.example", f"https://www.{name}", "null", f"ftp://{name}"]:
                assert asked(view, part, Host=name, Origin=origin)[0] == 403, origin
            for site in ["cross-site", "same-site"]:
                assert asked(view, part, Host=name, Sec_Fetch_Site=site)[0] == 403, site
            # The view's own address is no site of the gateway, and the other way round.
            own = f"http://127.0.0.1:{port}"
            assert asked(view, part, Host=name, Origin=own)[0] == 403
            assert asked(view, part, Origin=f"https://{name}")[0] == 403
        # A sign-in at the gateway sends its reader back to the page from another site.
        links_from_elsewhere(view, Host=name)
    # A name with a port is that name with that port, written as a browser writes it.
    for given in [f"{name}:8443", f"{name}:08443", f"{name}:{'0' * 40}8443"]:
        with serving(path, allowed_host=given) as view:
            assert view.allowed_host == f"{name}:8443"
            assert asked(view, "/", Host=f"{name}:8443")[0] == 200
            for how in ["http", "https"]:
                origin = f"{how}://{name}:8443"
                assert asked(view, "/", Host=f"{name}:8443", Origin=origin)[0] == 200
            assert asked(view, "/", Host=name)[0] == 403
            assert asked(view, "/", Host=f"{name}:8443", Origin=f"https://{name}")[0] == 403
    # A browser leaves the usual port of a secured line out of what it sends, and so the
    # view answers the address that a person opens: https://view.example.org:443/.
    with serving(path, allowed_host=f"{name}:443") as view:
        assert asked(view, "/", Host=name)[0] == 200
        assert asked(view, "/", Host=name, Origin=f"https://{name}")[0] == 200
        assert asked(view, "/", Host=name, Origin=f"http://{name}")[0] == 403
        # Over a line that is not secured, port 443 is not the usual one, and is sent.
        assert asked(view, "/", Host=f"{name}:443", Origin=f"http://{name}:443")[0] == 200
        assert asked(view, "/", Host=f"{name}:443", Origin=f"https://{name}:443")[0] == 403
        assert asked(view, "/", Host=f"{name}:443", Origin=f"https://{name}")[0] == 403
    # The same for port 80 and a line that is not secured.
    with serving(path, allowed_host=f"{name}:80") as view:
        assert asked(view, "/", Host=name, Origin=f"http://{name}")[0] == 200
        assert asked(view, "/", Host=name, Origin=f"https://{name}")[0] == 403
        assert asked(view, "/", Host=f"{name}:80", Origin=f"https://{name}:80")[0] == 200
        assert asked(view, "/", Host=f"{name}:80", Origin=f"http://{name}:80")[0] == 403
    # A name that ends in a dot is the name that a browser sends with the dot, and no other.
    with serving(path, allowed_host=f"{name}.") as view:
        assert asked(view, "/", Host=f"{name}.", Origin=f"https://{name}.")[0] == 200
        assert asked(view, "/", Host=name)[0] == 403
        assert asked(view, "/", Host=f"{name}.", Origin=f"https://{name}")[0] == 403
    with serving(path, allowed_host=name) as view:
        assert asked(view, "/", Host=f"{name}.")[0] == 403
    # Without such a name, the view answers under its own names only.
    with serving(path) as view:
        assert asked(view, "/", Host=name)[0] == 403


@pytest.mark.parametrize(
    "name",
    [
        "",
        " ",
        "https://view.example.org",
        "view.example.org/",
        "view.example.org/trip",
        "view example.org",
        "view.example.org:port",
        "view.example.org:0",
        "view.example.org:65536",
        "view.example.org:",
        "-view.example.org",
        "view-.example.org",
        "view..example.org",
        ".example.org",
        "*.example.org",
        "view_1.example.org",
        f"{'a' * 64}.example.org",
        ".".join(["a" * 63] * 4) + ".org",
        "user@view.example.org",
        "[::1]",
        "view.example.org..",
        ".",
        "view.example.org.:8443x",
        # What a browser would take for an address made of numbers, and would rewrite or refuse.
        "999.999.999.999",
        "127.1",
        "1.2.3",
        "1.2.3.4.5",
        "010.0.0.5",
        "10.0.0.5.",
        "0x7f.0.0.1",
        "host.123",
        "example.0x10",
        "2130706433",
        "view.example.org:000000",
        "view.example.org:0065536",
        "vi\u00e9w.example.org",
        # The sign for kelvin is no letter of a name, though its small form is the letter k.
        "\u212aiew.example.org",
        "view.example.org\n",
    ],
)
def test_one_more_name_for_the_view_is_the_name_of_a_host(name: str, tmp_path: Path) -> None:
    """Whatever is no name of a host, with or without a port, is refused before the view serves."""
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    with pytest.raises(ValueError, match="no name that the view can answer under"):
        View(path, allowed_host=name)


@pytest.mark.parametrize("port", [1, 21, 22, 25, 110, 143, 993, 6000, 6667, 10080])
def test_one_more_name_for_the_view_has_a_port_that_browsers_open(
    port: int, tmp_path: Path
) -> None:
    """A browser refuses to open a page on some ports, whatever answers there."""
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    for given in [f"view.example.org:{port}", f"10.0.0.5:0{port}"]:
        with pytest.raises(ValueError, match=f"browsers refuse to open a page on port {port}"):
            View(path, allowed_host=given)


@pytest.mark.parametrize(
    "name",
    [
        "view.example.org",
        "localhost",
        "trips",
        "10.0.0.5",
        "10.0.0.5:8080",
        "a-b.c-d.example",
        "x1.example.org:8443",
        "xn--vie-dma.example.org",
        "view.example.org.",
        "view.example.org:010443",
        "view.example.org:80",
        "view.example.org:8080",
        "view.example.org:65535",
        "1a.example",
        "0x.example",
    ],
)
def test_the_name_of_a_host_is_taken_as_one_more_name_for_the_view(
    name: str, tmp_path: Path
) -> None:
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    with serving(path, allowed_host=name) as view:
        # The view answers under the name as a browser sends it: with its port as a plain
        # number, and without the usual port of a line that is not secured.
        host, _, port = name.partition(":")
        sent = host if port in ("", "80") else f"{host}:{int(port)}"
        assert asked(view, "/", Host=sent)[0] == 200


def test_the_command_takes_one_more_name_for_the_view(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The command says under which name the view answers too, and that the view has no sign-in."""
    path = tmp_path / "trip.json"
    shutil.copy(STORY / "works.json", path)
    # What is no name of a host is refused, and the command says which name it was given.
    assert main(["view", str(path), "--no-browser", "--allowed-host=https://example.org"]) == 2
    assert "https://example.org" in capsys.readouterr().err
    started, address = command(path, allowed_host="view.example.org")
    try:
        assert started.stdout is not None
        also = started.stdout.readline()
        assert also == (
            "It also answers under the name view.example.org, for a gateway of your own that"
            " passes requests on to it with the name that the browser asked for. The view has no"
            " sign-in: the gateway needs one.\n"
        )
        request = urllib.request.Request(address, headers={"Host": "view.example.org"})
        with urllib.request.urlopen(request, timeout=20) as reply:
            assert reply.status == 200
    finally:
        started.kill()
        started.wait(timeout=20)


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
        assert kinds(Sent(view).until("report")) == ["file", "read", "answer", "report"]
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


def command(
    path: Path, python: str | None = None, allowed_host: str | None = None
) -> tuple[subprocess.Popen[str], str]:
    """The command as a process of its own, and the address of the view that it prints.

    With ``python``, the command takes that program for the Python that runs its checks. With
    ``allowed_host``, the view answers under that name too.
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
            *([] if allowed_host is None else [f"--allowed-host={allowed_host}"]),
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
        assert kinds(Sent(address).until("report")) == ["file", "read", "answer", "report"]
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


# What the page says while it no longer hears the view.
START = "If agloe view has stopped, start it again and open the address that it prints."
SAID = "When the page last heard the view, it said:"
OLD = "What the page shows below is on the FILE as it was before."
LAST = (
    "What the page shows below is the last that the view sent. The FILE may have changed since"
    " then."
)


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
        assert kinds(sent) == ["file", "read", "answer", "report"], name
        at_first, on_file, on_read, on_answer, on_report = said
        assert at_first["mark"] == "waiting", name
        expected = json.loads(beside(path, ".expected.json").read_text())
        words = beside(path, ".expected.txt").read_text()
        # There is a FILE, and the COMPILER has not answered: the page shows no answer.
        assert on_file["mark"] == "checking", name
        # The page says what it knows. The check may have ended before this page was opened.
        assert on_file["line"] == "Waiting for the COMPILER's answer on this FILE.", name
        assert not any(answer in on_file["line"] for answer in ANSWERS), name
        assert on_file["report"] is None, name
        assert on_file["calendar"] is None, name
        # The view has read the FILE: the page draws it, with no report, and still no answer.
        ahead = {"trip": sent[1]["trip"], "report": None}
        assert sent[1]["trip"]["itinerary"] is None, name
        assert (on_read["mark"], on_read["line"]) == (on_file["mark"], on_file["line"]), name
        assert (on_read["calendar"], on_read["ahead"], on_read["report"]) == (ahead, True, None), (
            name
        )
        # The answer comes ahead of the report, and the page says that the report is on its way.
        assert on_answer["mark"] == expected["answer"].lower(), name
        assert on_answer["line"].startswith(expected["answer"]), name
        assert on_answer["report"] is None, name
        assert (on_answer["calendar"], on_answer["ahead"]) == (ahead, True), name
        assert on_report["mark"] == kind_of(expected), name
        assert on_report["line"] == words.split("\n")[0], name
        assert on_report["report"] == words, name
        assert (on_report["old"], on_report["ahead"], on_report["past"]) == (False, False, False), (
            name
        )
        assert (on_read["past"], on_answer["past"]) == (False, False), name
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
    changed, read_again, answered, reported = said[5:9]
    # The FILE changed: the report on the page is on the FILE as it was, and the page says so.
    assert changed["mark"] == "checking"
    assert not any(answer in changed["line"] for answer in ANSWERS)
    assert (changed["report"], changed["old"], changed["ahead"]) == (words, True, False)
    assert changed["past"] is True
    # Until the view has read the FILE as it is now, the page draws the TRIP of that report,
    # and it is marked with it.
    kept = {"trip": first[-1]["trip"], "report": first[-1]["json"]}
    assert changed["calendar"] == kept
    # The page says so of all that it still shows of that FILE, and names no part of it.
    assert changed["note"].endswith("What the page shows below is on the FILE as it was before.")
    # The view has read the FILE as it is now: the page draws that FILE, with no report. The
    # report in words is still the one on the FILE as it was, and the page says which is which.
    ahead = {"trip": second[1]["trip"], "report": None}
    assert (read_again["calendar"], read_again["ahead"], read_again["past"]) == (ahead, True, False)
    assert (read_again["report"], read_again["old"]) == (words, True)
    assert read_again["note"].endswith("The report below is on the FILE as it was before.")
    assert answered["line"].startswith("INFEASIBLE")
    assert (answered["report"], answered["old"]) == (words, True)
    assert (answered["calendar"], answered["ahead"]) == (ahead, True)
    assert reported["line"] == "INFEASIBLE: this trip cannot work."
    assert (reported["old"], reported["ahead"]) == (False, False)
    assert reported["calendar"] == {"trip": second[-1]["trip"], "report": second[-1]["json"]}
    assert reported["calendar"] != changed["calendar"]
    # A FILE that breaks the format has no report: the page shows the problems, and no answer.
    # The view could not read it, so the page still draws the TRIP of the last report.
    broken = said[10]
    assert broken["mark"] == "refused"
    assert broken["problems"] == ["/facts/0: fits no known shape"]
    assert not any(answer in broken["line"] for answer in ANSWERS)
    assert (broken["old"], broken["ahead"], broken["past"]) == (True, False, True)
    assert broken["calendar"] == reported["calendar"]
    assert said[-1]["line"] == "FEASIBLE: this trip works."
    assert said[-1]["problems"] is None


def test_the_page_keeps_the_last_file_that_the_view_read() -> None:
    """A FILE with no report yet changes. What the page draws of it stays until the view has
    read the FILE again, marked as on the FILE as it was."""
    file, read_it, answer, _ = sent_for((STORY / "works.json").read_bytes(), 1)
    away: Events = [
        {"kind": "file", "name": "trip.json", "revision": 2, "view": "one"},
        {"kind": "unreadable", "problem": "No such file or directory", "revision": 2},
    ]
    back = sent_for((STORY / "cannot-work.json").read_bytes(), 3)
    (said,) = page_says([[file, read_it, answer, *away, *back]])
    answered, changed, unreadable, again, read_again = said[3:8]
    drawn = {"trip": read_it["trip"], "report": None}
    assert (answered["calendar"], answered["past"]) == (drawn, False)
    # The FILE changed, and the page has no report to fall back on: the drawing stays.
    assert (changed["mark"], changed["calendar"], changed["past"]) == ("checking", drawn, True)
    assert changed["note"] == "What the page shows below is on the FILE as it was before."
    assert (unreadable["mark"], unreadable["calendar"], unreadable["past"]) == (
        "unreadable",
        drawn,
        True,
    )
    assert unreadable["note"].endswith("What the page shows below is on the FILE as it was before.")
    assert (again["calendar"], again["past"]) == (drawn, True)
    # The view has read the FILE as it is now: the page draws that one.
    assert read_again["calendar"] == {"trip": back[1]["trip"], "report": None}
    assert (read_again["past"], read_again["note"]) == (False, "")
    # A state of which the view has no TRIP to send leaves the last one on the page.
    none_to_send = {**back[1], "trip": None}
    (said,) = page_says([[file, read_it, answer, back[0], none_to_send]])
    assert (said[-1]["calendar"], said[-1]["past"]) == (drawn, True)
    # What the view says twice of one state is taken once.
    (said,) = page_says([[file, read_it, {**read_it, "trip": None}, read_it]])
    assert said[2] == said[3] == said[4]


def test_the_page_takes_no_answer_for_another_state_of_the_file() -> None:
    """An event that names another revision than the page was last told of is passed over."""
    file, first, answer, report = sent_for((STORY / "cannot-work.json").read_bytes(), 1)
    newer: dict[str, Any] = {"kind": "file", "name": "trip.json", "revision": 2, "view": "one"}
    late = [first, answer, report, {"kind": "stopped", "revision": 1}]
    (said,) = page_says([[file, newer, *late]])
    for after_it in said[2:]:
        assert after_it["mark"] == "checking"
        assert after_it["report"] is None
        # The page draws nothing of the FILE as it was either.
        assert after_it["calendar"] is None
        assert not any(word in after_it["line"] for word in ANSWERS)


def test_the_page_says_when_a_check_has_stopped() -> None:
    """An answer that came before the check stopped was proved, so it stays on the page."""
    file, first, answer, report = sent_for((STORY / "cannot-work.json").read_bytes(), 1)
    stopped = {"kind": "stopped", "revision": 1}
    early, late = page_says([[file, stopped], [file, first, answer, stopped]])
    assert early[-1]["mark"] == "stopped"
    assert not any(word in early[-1]["line"] for word in ANSWERS)
    assert early[-1]["calendar"] is None
    assert late[-1]["mark"] == "stopped"
    assert late[-1]["line"].startswith("INFEASIBLE")
    assert late[-1]["report"] is None
    # What the view read of the FILE stays on the page: the check stopped, and the FILE is there.
    assert late[-1]["calendar"] == {"trip": first["trip"], "report": None}
    # The next state of the FILE starts afresh.
    again = sent_for((STORY / "cannot-work.json").read_bytes(), 2)
    (said,) = page_says([[file, first, answer, stopped, *again]])
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
    # The TRIP holds a time that cannot be written, so the view has none to send before the
    # report either.
    assert kinds(sent) == ["file", "read", "answer", "unwritable"]
    assert sent[1]["trip"] is None
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
    reported, lost = said[4:6]
    assert lost["mark"] == "lost"
    assert not any(word in lost["line"] for word in ANSWERS)
    assert lost["old"] is True
    assert lost["report"] == (STORY / "works.expected.txt").read_text()
    # What the page draws stays too: the TRIP of that report, marked with it.
    assert lost["calendar"] == {"trip": first[-1]["trip"], "report": first[-1]["json"]}
    assert (lost["ahead"], lost["past"]) == (False, True)
    # The page does not know of a change, so it says of none: only that this is the last
    # that it was sent.
    assert lost["note"] == f"{START} {LAST}"
    # The view speaks again, of the same state of the FILE: all that the page was told of it
    # stands. The page never says that a report which it shows is on its way.
    for after_it in said[6:]:
        assert after_it == reported
    # The page lost the view after the view had read the FILE, and before the report. What it
    # draws is the last that it saw of the FILE, and it is marked so.
    file, read_it, answer, report = first
    (said,) = page_says([[file, read_it, answer, {"kind": "lost"}, file, read_it, answer, report]])
    answered, lost, found, *_ = said[3:]
    assert (answered["ahead"], answered["past"]) == (True, False)
    assert lost["calendar"] == answered["calendar"] == {"trip": read_it["trip"], "report": None}
    assert (lost["ahead"], lost["past"], lost["old"]) == (True, True, False)
    # The answer was proved, and the page has no report that shows it: the page still says it.
    assert lost["line"] == "The view is not answering."
    # The page still says what it said last: the answer that was proved, and that the report
    # was on its way.
    assert lost["note"] == (
        f"{START} {SAID} FEASIBLE. The report is on its way. {answered['note']} {LAST}"
    )
    # The view speaks again: the check goes on, and the answer that was proved stands.
    assert found == answered
    assert said[-1] == reported
    # The view speaks again of another state of the FILE: the page starts afresh on that one,
    # and marks what it still shows.
    newer = sent_for((STORY / "works.json").read_bytes(), 2)
    (said,) = page_says([[*first, {"kind": "lost"}, *newer]])
    assert (said[6]["mark"], said[6]["old"], said[6]["past"]) == ("checking", True, True)
    assert said[-1]["line"] == "FEASIBLE: this trip works."
    assert (said[-1]["old"], said[-1]["past"]) == (False, False)


def test_a_page_that_no_longer_hears_the_view_says_what_is_the_last_it_was_sent() -> None:
    """The report on the page is on one state of the FILE, and the view was lost on a later one."""
    first = sent_for((STORY / "cannot-work.json").read_bytes(), 1)
    file, read_it, answer, _ = sent_for((STORY / "works.json").read_bytes(), 2)
    lost = {"kind": "lost"}
    start, last = START, LAST
    earlier = "The report is on an earlier state of the FILE than what the page draws."
    checking = f"{SAID} Waiting for the COMPILER's answer on this FILE."
    # Lost after the view had read the newer state and proved its answer. The only answer in
    # a report on the page is the one on the FILE as it was, so the page says the newer one.
    (said,) = page_says([[*first, file, read_it, answer, lost]])
    assert said[-1]["report"].startswith("INFEASIBLE")
    assert (said[-1]["old"], said[-1]["ahead"], said[-1]["past"]) == (True, True, True)
    assert said[-1]["line"] == "The view is not answering."
    on_its_way = f"{SAID} FEASIBLE. The report is on its way. The answer came after"
    assert said[-1]["note"].startswith(f"{start} {on_its_way} ")
    assert said[-1]["note"].endswith(f" s. {last} {earlier}")
    # Lost before that answer: the page names none.
    (said,) = page_says([[*first, file, read_it, lost]])
    assert said[-1]["note"] == f"{start} {checking} {last} {earlier}"
    # Lost after the view had said that there is a newer state, and before it had read it.
    # The page knows that the FILE changed, and says so of what it shows.
    (said,) = page_says([[*first, file, lost]])
    assert said[-1]["note"] == f"{start} {checking} {OLD}"
    # Lost with nothing on the page.
    (said,) = page_says([[file, lost]])
    assert said[-1]["note"] == f"{start} {checking}"
    # Lost with the report on the page: its first line is there to read, so the page does not
    # say it twice.
    (said,) = page_says([[*first, lost]])
    assert said[-1]["note"] == f"{start} {last}"
    # Lost after a check that stopped, and after a FILE that could not be read: the page
    # still says why it has no report.
    stopped = {"kind": "stopped", "revision": 2}
    (said,) = page_says([[file, read_it, answer, stopped, lost]])
    assert said[-1]["note"] == (
        f"{start} {SAID} FEASIBLE. The check stopped before its report came."
        f" It runs again when the FILE changes. {last}"
    )
    away: Events = [
        {**file, "revision": 3},
        {"kind": "unreadable", "problem": "No such file or directory", "revision": 3},
    ]
    (said,) = page_says([[file, read_it, answer, *away, lost]])
    assert said[-1]["note"] == (
        f"{start} {SAID} The FILE cannot be read, so it has no report."
        f" No such file or directory. {OLD}"
    )
    # The view is there, a still newer state is announced, and the page has not been sent its
    # TRIP: the report and what the page draws are of two earlier states.
    newest = {**file, "revision": 3}
    (said,) = page_says([[*first, file, read_it, answer, newest]])
    assert (said[-1]["old"], said[-1]["ahead"], said[-1]["past"]) == (True, True, True)
    assert said[-1]["note"] == f"{OLD} {earlier}"
    # A FILE that the format refused, and then the view was lost: the problems are those of
    # the last check, and the page says so above them.
    refused: Events = [
        {"kind": "file", "name": "trip.json", "revision": 1, "view": "one"},
        {"kind": "refused", "problems": ["/facts/0: fits no known shape"], "revision": 1},
    ]
    (said,) = page_says([[*refused, lost]])
    assert said[-1]["problems"] == ["/facts/0: fits no known shape"]
    assert said[-1]["line"] == (
        "The view is not answering. The problems below are from the last check that it sent."
    )
    assert said[-1]["note"] == start


def test_the_page_keeps_no_report_from_another_view() -> None:
    """A view was stopped, and another one now serves another FILE at the same address."""
    first = sent_for((STORY / "works.json").read_bytes(), 3, view="one")
    other: Events = [
        {"kind": "file", "name": "other.json", "revision": 1, "view": "two"},
        {"kind": "refused", "problems": ["not readable as JSON"], "revision": 1},
    ]
    (said,) = page_says([[*first, {"kind": "lost"}, *other]])
    assert said[5]["report"] == (STORY / "works.expected.txt").read_text()
    assert said[5]["calendar"] == {"trip": first[-1]["trip"], "report": first[-1]["json"]}
    for after_it in said[6:]:
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
