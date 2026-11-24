"""The program behind ``agloe view FILE``: it serves the page and checks the FILE as it changes.

It listens on this machine only, and serves the page, the page's own files, and what the page
is to show. It writes nothing. It answers a browser that asks for this machine by its own
address. Its owner can give it one more name to answer under: the name of a gateway of their
own, which passes requests on to it. The view has no sign-in, so such a gateway needs one.

A state of the FILE is its content at one look. Each new state gets a number, its revision, and
every event that a page is sent names the revision it is about. So a page can never take an
answer on one state of the FILE for an answer on another. The COMPILER checks each state in a
process of its own, from the content that was seen, and a check that is still running when the
FILE changes is ended.
"""

import contextlib
import ipaddress
import json
import math
import os
import re
import secrets
import socket
import socketserver
import stat
import subprocess
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, cast

from agloe.view.trip import holds

if TYPE_CHECKING:
    # Only the name of the type is needed here. The check itself runs in a process of its own.
    from agloe.view.check import Event

PAGE = (
    "index.html",
    "view.css",
    "view.js",
    "state.js",
    "calendar.js",
    "lines.js",
    "strip.js",
    "named.js",
    "wants.js",
    "times.js",
    "options.js",
    "who.js",
    "capabilities.js",
    "ways.js",
    "persons.js",
    "rights.js",
    "money.js",
    "budgets.js",
    "objects.js",
    "places.js",
)  # the page and its files
NEEDED = PAGE[:4]  # those that the answer and the report need: the page shows them without the rest
KINDS = {".html": "text/html", ".css": "text/css", ".js": "text/javascript"}
LOOK = 0.1  # seconds between two looks at the FILE, and at whether the view is closed
QUIET = 15.0  # seconds after which a page with nothing new is told that the view is still there
LONGEST = 1e9  # seconds: no check takes this long, and a page can still write the number
# The name of a host, with a port or without, as a browser sends it: parts of letters, digits
# and hyphens with dots between them, and no part that starts or ends with a hyphen. A name
# can end in a dot, and a browser then sends it with the dot.
_PART = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_HOST = re.compile(rf"({_PART}(?:\.{_PART})*)(\.?)(?::([0-9]{{1,5}}))?")
_LONGEST_NAME = 253  # letters and dots: the names of the internet are no longer
# A name whose last part is a number is an address made of numbers to a browser. It rewrites
# such an address, or refuses it. So the view takes one only as a browser writes it.
_A_NUMBER = re.compile(r"[0-9]+|0x[0-9a-f]*")
# The port that a browser leaves out of what it sends, for each way of reaching a gateway.
_USUAL = {"http": 80, "https": 443}
# The ports from 1024 up that browsers refuse to open a page on: the bad ports of the Fetch
# Standard.
REFUSED_BY_BROWSERS = frozenset(
    {1719, 1720, 1723, 2049, 3659, 4045, 4190, 5060, 5061, 6000, 6566}
    | {6665, 6666, 6667, 6668, 6669, 6679, 6697, 10080}
)
ANSWERS = {"FEASIBLE", "INFEASIBLE", "UNDETERMINED"}
# What a check can say, and what each of its events must hold. A check ends with one of ENDS.
SHAPES: dict[str, dict[str, type | tuple[type, ...]]] = {
    "read": {},
    "answer": {"answer": str, "seconds": (int, float)},
    "report": {"answer": str, "json": dict, "text": str, "seconds": (int, float)},
    "refused": {"problems": list},
    "unwritable": {},
}
ENDS = {"report", "refused", "unwritable"}
WITH_A_TRIP = {"read", "report"}  # the events that come with the TRIP as a page draws it
# The page loads nothing from any other host, sends nothing to one, and sits in no other page.
POLICY = "default-src 'self'; frame-ancestors 'none'"


def _static() -> dict[str, tuple[str, bytes]]:
    """The page and its files, each by the path a browser asks for: its kind and its content.

    A file that the answer and the report do not need is left out where it cannot be read. The
    page then shows them without the calendar, or with no line tied, and says so.
    """
    parts: dict[str, tuple[str, bytes]] = {}
    folder = resources.files("agloe.view").joinpath("static")
    for name in PAGE:
        try:
            content = folder.joinpath(name).read_bytes()
        except OSError:
            if name in NEEDED:
                raise
            continue
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


def _without_its_trip(line: bytes) -> object:
    """What a check printed, without the TRIP, where the line is no event as it stands.

    What is wrong may be in the TRIP alone: a number that no page can read. The rest is then
    read again as strictly as any event. Raises ValueError where the rest is no event either.
    """
    loose: object = json.loads(line.decode())
    if not isinstance(loose, dict) or cast("Event", loose).get("kind") not in WITH_A_TRIP:
        raise ValueError("a check printed something that is no event")
    rest = {name: held for name, held in cast("Event", loose).items() if name != "trip"}
    again = json.dumps(rest, allow_nan=False)
    return json.loads(again, parse_constant=_no_number, parse_float=_finite)


def _said(line: bytes) -> Event:
    """One line that a check printed, as the event it is. Raises ValueError where it is none.

    An event is passed on only if it holds all that a page reads from it, so that no page is
    ever left with half an event.

    A report is whole without the TRIP that the calendar draws. So a report comes with its TRIP
    where that is one a page can draw, and with none where it is not: what is wrong with a
    calendar never costs the reader the report. So it is with the TRIP that the check sends as
    soon as it has read the FILE: that one says that it has no report.
    """
    try:
        said: object = json.loads(line.decode(), parse_constant=_no_number, parse_float=_finite)
    except ValueError:
        said = _without_its_trip(line)
    if not isinstance(said, dict):
        raise ValueError("a check printed something that is no event")
    event = cast("Event", said)
    kind = event.get("kind")
    trip = event.pop("trip", None) if kind in WITH_A_TRIP else None
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
    if kind == "report":
        planned = cast("Event", trip).get("itinerary") if holds(trip) else None
        event["trip"] = trip if planned is (event["answer"] == "FEASIBLE") else None
    if kind == "read":
        # The TRIP of a FILE that has no report yet says so.
        event["trip"] = trip if holds(trip) and cast("Event", trip)["itinerary"] is None else None
    return event


class NotAHost(ValueError):
    """What was given as one more name for the view is no name of a host."""


def _named(name: str) -> tuple[str, int | None]:
    """One more name for the view, as a browser sends it: in small letters, and its port
    where it has one.

    Raises NotAHost for anything but the name of a host, with a port or without. So nothing
    that is given as a name can match a request that it was not meant for, and nothing is
    taken that no browser would send.
    """
    found = _HOST.fullmatch(name.lower()) if name.isascii() else None
    if found is not None and len(found[1]) <= _LONGEST_NAME:
        host, port = found[1] + found[2], None if found[3] is None else int(found[3])
        if _A_NUMBER.fullmatch(found[1].rsplit(".", 1)[-1]):
            # An address made of numbers: four numbers up to 255, with no dot after them.
            with contextlib.suppress(ValueError):
                if str(ipaddress.IPv4Address(host)) == host and (
                    port is None or 1 <= port <= 65535
                ):
                    return host, port
        elif port is None or 1 <= port <= 65535:
            return host, port
    raise NotAHost(
        f"{name!r} is no name of a host: give one like view.example.org, "
        "with the port after a colon where the gateway has one"
    )


class View:
    """The view of one FILE. ``serve`` runs it until ``close``. ``address`` is where the page is.

    ``python`` is the Python that runs each check. ``allowed_host`` is one more name that the
    view answers under: the name of a gateway that passes requests on to it.
    """

    def __init__(
        self,
        path: Path,
        port: int = 0,
        python: str = sys.executable,
        allowed_host: str | None = None,
    ) -> None:
        self.path = path
        self.python = python
        # The name is looked at before the view takes a port, so a bad one holds nothing.
        self._gateway = None if allowed_host is None else _named(allowed_host)
        self.allowed_host: str | None = None
        if self._gateway is not None:
            name, at = self._gateway
            self.allowed_host = name if at is None else f"{name}:{at}"
        self._server = _listening(port)
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

    def sites(self) -> dict[str, set[str]]:
        """Each name by which a browser reaches the view, with the sites that its page can say
        it comes from.

        A browser on this machine reaches the view by the address of this machine. Where the
        owner has given one more name, a browser reaches it by that name too, through the
        gateway that has the name. The gateway may speak to the browser over a secured line,
        or over one that is not. A browser leaves the usual port of each out of what it
        sends: 443 for a secured line, and 80 for the other. So a name with one of those
        ports is the bare name for that line, and the name with the port for the other.
        """
        own = (f"127.0.0.1:{self._port}", f"localhost:{self._port}")
        sites = {host: {f"http://{host}"} for host in own}
        if self._gateway is not None:
            name, port = self._gateway
            for how, usual in _USUAL.items():
                sent = name if port is None or port == usual else f"{name}:{port}"
                sites.setdefault(sent, set()).add(f"{how}://{sent}")
        return sites

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
            # Where the system has no way to open without waiting, it has no such pipes either.
            how = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
            opened = os.open(self.path, how)
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

    def server_bind(self) -> None:
        """Take the port, and ask the system for no name.

        Python's server looks up a name for its address as it starts. The view never uses that
        name, and on some machines the answer takes seconds.
        """
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]


def _listening(port: int) -> _Server:
    """A server on this port of this machine, or on a free port where the port is 0.

    Raises ValueError for a port that the view does not serve, and OSError where the port
    cannot be had. A free port is one that browsers open: one that they refuse is held until
    another is found, so that the system does not offer it again.
    """
    if port != 0 and not 1024 <= port <= 65535:
        raise ValueError(f"{port} is no port for the view: give one from 1024 to 65535")
    if port in REFUSED_BY_BROWSERS:
        raise ValueError(f"browsers refuse to open a page on port {port}")
    refused: list[_Server] = []
    try:
        for _ in range(len(REFUSED_BY_BROWSERS) + 1):
            server = _Server(("127.0.0.1", port), _Asked)
            if server.server_address[1] not in REFUSED_BY_BROWSERS:
                return server
            refused.append(server)
        raise OSError("the system offers no free port that browsers open")
    finally:
        for server in refused:
            server.server_close()


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
        # A request that names two hosts, or says twice where it comes from, is no request.
        said = {
            name: self.headers.get_all(name) or [] for name in ("Host", "Origin", "Sec-Fetch-Site")
        }
        if any(len(values) > 1 for values in said.values()):
            self.send_error(HTTPStatus.BAD_REQUEST)
            return
        if not self._for_the_view(view):
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

    def _for_the_view(self, view: View) -> bool:
        """Whether the request is made to the view under one of its names, and by its own page.

        A page from elsewhere reaches this machine under a name of its own, or says in the
        request that it comes from another site. Both are refused. The names of hosts count
        whatever the case of their letters, and blanks around what a line says are no part
        of it.
        """

        def said(name: str) -> str | None:
            value = self.headers.get(name)
            return None if value is None else value.strip(" \t")

        sites = view.sites().get((said("Host") or "").lower())
        if sites is None:
            return False
        origin = said("Origin")
        if origin is not None and origin.lower() not in sites:
            return False
        return said("Sec-Fetch-Site") in {None, "same-origin", "none"}

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
