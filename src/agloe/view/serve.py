"""The program behind ``agloe view FILE``: it serves the page and checks the FILE as it changes.

It serves this machine only: the page, the page's own files, and what the page is to show. It
writes nothing.

A state of the FILE is its content at one look. Each new state gets a number, its revision, and
every event that a page is sent names the revision it is about. So a page can never take an
answer on one state of the FILE for an answer on another. The COMPILER checks each state in a
process of its own, from the content that was seen, and a check that is still running when the
FILE changes is ended.
"""

import contextlib
import json
import math
import os
import secrets
import socket
import stat
import subprocess
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    # Only the name of the type is needed here. The check itself runs in a process of its own.
    from agloe.view.check import Event

PAGE = ("index.html", "view.css", "view.js", "state.js")  # the page and its files
KINDS = {".html": "text/html", ".css": "text/css", ".js": "text/javascript"}
LOOK = 0.1  # seconds between two looks at the FILE, and at whether the view is closed
QUIET = 15.0  # seconds after which a page with nothing new is told that the view is still there
LONGEST = 1e9  # seconds: no check takes this long, and a page can still write the number
ANSWERS = {"FEASIBLE", "INFEASIBLE", "UNDETERMINED"}
# What a check can say, and what each of its events must hold. A check ends with one of ENDS.
SHAPES: dict[str, dict[str, type | tuple[type, ...]]] = {
    "answer": {"answer": str, "seconds": (int, float)},
    "report": {"answer": str, "json": dict, "text": str, "seconds": (int, float)},
    "refused": {"problems": list},
    "unwritable": {},
}
ENDS = {"report", "refused", "unwritable"}
# The page loads nothing from any other host, sends nothing to one, and sits in no other page.
POLICY = "default-src 'self'; frame-ancestors 'none'"


def _static() -> dict[str, tuple[str, bytes]]:
    """The page and its files, each by the path a browser asks for: its kind and its content."""
    parts: dict[str, tuple[str, bytes]] = {}
    folder = resources.files("agloe.view").joinpath("static")
    for name in PAGE:
        content = folder.joinpath(name).read_bytes()
        parts[f"/{name}"] = (f"{KINDS[Path(name).suffix]}; charset=utf-8", content)
    parts["/"] = parts.pop("/index.html")
    return parts


def _no_number(name: str) -> object:
    raise ValueError(f"{name} is not a JSON value")


def _finite(written: str) -> float:
    """A number as JSON writes it. One too large to hold is no number that a page can read."""
    number = float(written)
    if not math.isfinite(number):
        raise ValueError(f"{written} is too large a number")
    return number


def _said(line: bytes) -> Event:
    """One line that a check printed, as the event it is. Raises ValueError where it is none.

    An event is passed on only if it holds all that a page reads from it, so that no page is
    ever left with half an event.
    """
    said: object = json.loads(line.decode(), parse_constant=_no_number, parse_float=_finite)
    if not isinstance(said, dict):
        raise ValueError("a check printed something that is no event")
    event = cast("Event", said)
    kind = event.get("kind")
    shape = SHAPES.get(kind) if isinstance(kind, str) else None
    if shape is None or set(event) != {"kind", *shape}:
        raise ValueError("a check printed something that is no event")
    for name, kinds in shape.items():
        if isinstance(event[name], bool) or not isinstance(event[name], kinds):
            raise ValueError("a check printed an event that does not hold what it must")
    if "answer" in event and event["answer"] not in ANSWERS:
        raise ValueError("a check printed an answer that is none of the three")
    seconds = event.get("seconds")
    if isinstance(seconds, int | float) and not 0 <= seconds < LONGEST:
        raise ValueError("a check printed a length of time that is none")
    if "json" in event and cast("Event", event["json"]).get("answer") != event["answer"]:
        raise ValueError("a check printed a report with another answer than its own")
    if "problems" in event and not all(
        isinstance(problem, str) for problem in cast("list[object]", event["problems"])
    ):
        raise ValueError("a check printed a problem that is no text")
    return event


class View:
    """The view of one FILE. ``serve`` runs it until ``close``. ``address`` is where the page is.

    ``python`` is the Python that runs each check.
    """

    def __init__(self, path: Path, port: int = 0, python: str = sys.executable) -> None:
        self.path = path
        self.python = python
        self._server = _Server(("127.0.0.1", port), _Asked)
        self._server.view = self
        self._server.timeout = LOOK
        self._port = int(self._server.server_address[1])
        self.address = f"http://127.0.0.1:{self._port}/"
        # A name of its own, so that a page can tell this view from one that served the same
        # address before it. The page keeps nothing that another view told it.
        self.id = secrets.token_hex(8)
        self.static = _static()
        self.changed = threading.Condition()
        self.revision = 0  # counts the states of the FILE that have been seen
        self.events: list[Event] = []  # what a page is told about the FILE as it is now
        self.pages: set[socket.socket] = set()  # the connections that are open
        self.closed = False
        self._serving = False
        self._check: subprocess.Popen[bytes] | None = None

    def hosts(self) -> set[str]:
        """The names by which a browser on this machine reaches the view."""
        return {f"127.0.0.1:{self._port}", f"localhost:{self._port}"}

    def serve(self) -> None:
        """Serve the page and watch the FILE, until ``close`` or until the command is stopped.

        However it ends, it ends the check that is running, lets every page go, and gives the
        port back, before it returns.
        """
        watching: threading.Thread | None = None
        try:
            self._serving = True
            watching = threading.Thread(target=self._watch, daemon=True)
            watching.start()
            # One request at a time is taken up, so that the view sees soon that it is closed.
            while not self.closed:
                self._server.handle_request()
        finally:
            self._stop()
            self._server.server_close()
            if watching is not None and watching.is_alive():
                watching.join()

    def close(self) -> None:
        """Stop the view. ``serve`` returns soon after, from whichever thread it runs in."""
        self._stop()
        if not self._serving:
            self._server.server_close()

    def _stop(self) -> None:
        with self.changed:
            self.closed = True
            self._end_the_check()
            pages = list(self.pages)
            self.changed.notify_all()
        for page in pages:
            # A page that is slow to read, or that has sent half a request, holds a thread.
            with contextlib.suppress(OSError):
                page.shutdown(socket.SHUT_RDWR)

    def news(self, revision: int, sent: int) -> tuple[int, int, list[Event]] | None:
        """What to send next to a page that has had ``sent`` events of the state ``revision``.

        Waits until there is something, or until it is time to say that the view is still
        there. Gives the revision of the FILE now, how many of its events the page will then
        have had, and the events to send. Gives None once the view is closed.
        """
        with self.changed:
            self.changed.wait_for(
                lambda: self.closed or self.revision != revision or len(self.events) > sent, QUIET
            )
            if self.closed:
                return None
            if self.revision != revision:
                sent = 0
            fresh = self.events[sent:]
            return self.revision, sent + len(fresh), fresh

    def _look(self) -> bytes | str:
        """The content of the FILE now, or the reason why it cannot be read.

        Only a regular file is read. Whatever else has the FILE's name is opened without
        waiting for it, so a pipe with nobody writing to it cannot hold the view up.
        """
        try:
            opened = os.open(self.path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError as problem:
            return problem.strerror or str(problem)
        try:
            if not stat.S_ISREG(os.fstat(opened).st_mode):
                return "It is not a regular file"
            with open(opened, "rb", closefd=False) as file:
                return file.read()
        except OSError as problem:
            return problem.strerror or str(problem)
        finally:
            os.close(opened)

    def _watch(self) -> None:
        """Check the FILE now, and again each time its content is another than at the last look.

        A new state is announced to the pages in the same step that makes it the current one,
        so no page is ever told of a state with nothing said about which FILE it is.
        """
        seen: bytes | str | None = None
        while True:
            now = self._look()
            with self.changed:
                if self.closed:
                    return
                if now != seen:
                    seen = now
                    self.revision += 1
                    self._end_the_check()
                    self.events = [self._about("file", name=self.path.name, view=self.id)]
                    if isinstance(now, str):
                        self.events.append(self._about("unreadable", problem=now))
                    else:
                        check = threading.Thread(target=self._run, args=(self.revision, now))
                        check.daemon = True
                        check.start()
                    self.changed.notify_all()
                self.changed.wait(LOOK)

    def _about(self, kind: str, **said: object) -> Event:
        """An event about the state of the FILE that is the current one."""
        return {"kind": kind, "revision": self.revision, **said}

    def _run(self, revision: int, content: bytes) -> None:
        """One check of one state of the FILE, in a process of its own.

        What the check says is passed on while that state is the current one. A check ends with
        a report, with the problems of a FILE that has none, or with a report that cannot be
        written. A check that ends any other way has stopped, and the pages are told so.
        """
        with self.changed:
            if revision != self.revision or self.closed:
                return
            try:
                check = subprocess.Popen(
                    [self.python, "-m", "agloe.view.check"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                )
            except OSError:
                self.events.append(self._about("stopped"))
                self.changed.notify_all()
                return
            self._check = check
        assert check.stdin is not None
        assert check.stdout is not None
        ended = False
        try:
            check.stdin.write(content)
            check.stdin.close()
            for line in check.stdout:
                event = _said(line)
                with self.changed:
                    if revision != self.revision or self.closed:
                        return
                    self.events.append({**event, "revision": revision})
                    self.changed.notify_all()
                    ended = event["kind"] in ENDS
        except OSError, ValueError:
            # The check was ended while it wrote, or it printed something that is no event.
            ended = False
        finally:
            check.kill()
            check.stdout.close()
            check.wait()
            with self.changed:
                if revision == self.revision and not self.closed and not ended:
                    self.events.append(self._about("stopped"))
                    self.changed.notify_all()

    def _end_the_check(self) -> None:
        if self._check is not None:
            self._check.kill()
            self._check = None


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    view: View


class _Asked(BaseHTTPRequestHandler):
    """One request of a browser: the page, one of its files, or what the page is to show."""

    server: _Server  # pyright: ignore[reportIncompatibleVariableOverride]

    def setup(self) -> None:
        super().setup()
        view = self.server.view
        with view.changed:
            if view.closed:
                # The view closed while this connection was on its way in. It is let go at once.
                with contextlib.suppress(OSError):
                    self.connection.shutdown(socket.SHUT_RDWR)
            else:
                view.pages.add(self.connection)

    def finish(self) -> None:
        view = self.server.view
        with view.changed:
            view.pages.discard(self.connection)
        super().finish()

    def log_message(self, format: str, *args: object) -> None:
        """Nothing is logged: a FILE can hold what its PERSONs would rather keep to themselves."""

    def do_GET(self) -> None:
        view = self.server.view
        if not self._from_this_machine(view):
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        path = self.path.split("?", 1)[0]
        if path == "/events":
            self._tell(view)
        elif path in view.static:
            kind, content = view.static[path]
            self._begin(kind, len(content))
            self.wfile.write(content)
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def _from_this_machine(self, view: View) -> bool:
        """Whether the request is made to the view under its own name, and by its own page.

        A page from elsewhere reaches this machine under a name of its own, or says in the
        request that it comes from another site. Both are refused.
        """
        if self.headers.get("Host") not in view.hosts():
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin not in {f"http://{host}" for host in view.hosts()}:
            return False
        return self.headers.get("Sec-Fetch-Site") in {None, "same-origin", "none"}

    def _begin(self, kind: str, length: int | None = None) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", kind)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", POLICY)
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.end_headers()

    def _tell(self, view: View) -> None:
        """Send the events of the FILE as it is now, and then each new one as it comes."""
        self._begin("text/event-stream")
        revision, sent = 0, 0
        try:
            while True:
                news = view.news(revision, sent)
                if news is None:
                    return
                revision, sent, fresh = news
                for event in fresh:
                    # Plain ASCII, so that whatever the FILE's name holds can be sent.
                    self.wfile.write(f"data: {json.dumps(event)}\n\n".encode("ascii"))
                if not fresh:
                    self.wfile.write(b": the view is still here\n\n")
                self.wfile.flush()
        except OSError:
            return  # the page has gone
