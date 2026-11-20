"""The program behind ``agloe view FILE``: it serves the page and checks the FILE as it changes.

It serves this machine only: the page, the page's own files, and what the page is to show. It
writes nothing. Each time the FILE changes, the COMPILER checks it in a process of its own, and
a check that is still running by then is ended.
"""

import json
import subprocess
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Only the name of the type is needed here. The check itself runs in a process of its own.
    from agloe.view.check import Event

KINDS = {".html": "text/html", ".css": "text/css", ".js": "text/javascript"}
LOOK = 0.1  # seconds between two looks at the FILE
QUIET = 15.0  # seconds after which a page with nothing new is told that the view is still there


def _static() -> dict[str, tuple[str, bytes]]:
    """The page and its files, each by the path a browser asks for: its kind and its content."""
    parts: dict[str, tuple[str, bytes]] = {}
    for part in resources.files("agloe.view").joinpath("static").iterdir():
        kind = KINDS[Path(part.name).suffix]
        parts[f"/{part.name}"] = (f"{kind}; charset=utf-8", part.read_bytes())
    parts["/"] = parts.pop("/index.html")
    return parts


class View:
    """The view of one FILE. ``serve`` runs it until ``close``. ``address`` is where the page is."""

    def __init__(self, path: Path, port: int = 0, python: str = sys.executable) -> None:
        self.path = path
        self.python = python  # the Python that runs each check
        self._server = _Server(("127.0.0.1", port), _Asked)
        self._server.view = self
        self._port = int(self._server.server_address[1])
        self.address = f"http://127.0.0.1:{self._port}/"
        self.static = _static()
        self.changed = threading.Condition()
        self.round = 0  # counts the states of the FILE that have been seen
        self.events: list[Event] = []  # what a page is told about the FILE as it is now
        self.closed = False
        self._check: subprocess.Popen[str] | None = None

    def hosts(self) -> set[str]:
        """The names by which a browser on this machine reaches the view."""
        return {f"127.0.0.1:{self._port}", f"localhost:{self._port}"}

    def news(self, round: int, sent: int) -> tuple[int, int, list[Event]] | None:
        """What to send next to a page that has had ``sent`` events of the FILE's state ``round``.

        Waits until there is something, or until it is time to say that the view is still
        there. Gives the state of the FILE now, how many of its events the page will then have
        had, and the events to send. Gives None once the view is closed.
        """
        with self.changed:
            self.changed.wait_for(
                lambda: self.closed or self.round != round or len(self.events) > sent, QUIET
            )
            if self.closed:
                return None
            if self.round != round:
                sent = 0
            fresh = self.events[sent:]
            return self.round, sent + len(fresh), fresh

    def serve(self) -> None:
        """Serve the page and watch the FILE, until ``close``."""
        watching = threading.Thread(target=self._watch, daemon=True)
        watching.start()
        try:
            self._server.serve_forever(poll_interval=LOOK)
        finally:
            self._server.server_close()
            watching.join()

    def close(self) -> None:
        with self.changed:
            self.closed = True
            self._end_the_check()
            self.changed.notify_all()
        self._server.shutdown()

    def _watch(self) -> None:
        """Check the FILE now, and again each time it is another FILE than at the last look."""
        seen: object = self
        while True:
            try:
                found = self.path.stat()
                now: object = (found.st_mtime_ns, found.st_size, found.st_ino)
            except OSError:
                now = None
            with self.changed:
                if self.closed:
                    return
                if now != seen:
                    seen = now
                    self.round += 1
                    self.events = []
                    self._end_the_check()
                    threading.Thread(target=self._run, args=(self.round,), daemon=True).start()
                    self.changed.notify_all()
                self.changed.wait(LOOK)

    def _run(self, round: int) -> None:
        """One check, in a process of its own. What it says counts while the FILE stays as it is.

        A check ends with a report, or with the problems of a FILE that has none. A check that
        ends any other way has stopped, and the page is told so.
        """
        with self.changed:
            if round != self.round or self.closed:
                return
            try:
                check = subprocess.Popen(
                    [self.python, "-m", "agloe.view.check", str(self.path)],
                    stdout=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                )
            except OSError:
                self.events.append({"kind": "stopped"})
                self.changed.notify_all()
                return
            self._check = check
        assert check.stdout is not None
        last = ""
        for line in check.stdout:
            event: Event = json.loads(line)
            with self.changed:
                if round != self.round or self.closed:
                    break
                self.events.append(event)
                self.changed.notify_all()
            last = str(event["kind"])
        check.kill()
        check.wait()
        with self.changed:
            if round == self.round and not self.closed and last not in {"report", "refused"}:
                self.events.append({"kind": "stopped"})
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

    def log_message(self, format: str, *args: object) -> None:
        """Nothing is logged: a FILE can hold what its PERSONs would rather keep to themselves."""

    def do_GET(self) -> None:
        view = self.server.view
        if self.headers.get("Host") not in view.hosts():
            # A page from elsewhere reaches this machine under a name of its own. It is refused.
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

    def _begin(self, kind: str, length: int | None = None) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", kind)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        # The page loads nothing from any other host, and sends nothing to one.
        self.send_header("Content-Security-Policy", "default-src 'self'")
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.end_headers()

    def _tell(self, view: View) -> None:
        """Send the events of the FILE as it is now, and then each new one as it comes."""
        self._begin("text/event-stream")
        round, sent = 0, 0
        try:
            while True:
                news = view.news(round, sent)
                if news is None:
                    return
                round, sent, fresh = news
                for event in fresh:
                    self.wfile.write(f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode())
                if not fresh:
                    self.wfile.write(b": the view is still here\n\n")
                self.wfile.flush()
        except OSError:
            return  # the page has gone
