"""The command line: ``agloe check FILE`` prints the COMPILER's report for one FILE.

``agloe view FILE`` serves a page that shows the report and follows the FILE as it changes.
"""

import argparse
import json
import os
import signal
import sys
import threading
import webbrowser
from collections.abc import Sequence
from pathlib import Path

from agloe import compiler, report
from agloe.answers import Answer, Report
from agloe.file import File, FileError, Unwritable, read


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the command. Returns 0 for FEASIBLE, 1 for another answer, 2 when there is no report."""
    parser = argparse.ArgumentParser(
        prog="agloe",
        description="Check a trip: does it work, can it not work, or can nobody tell yet?",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser(
        "check",
        help="say whether a trip is FEASIBLE, INFEASIBLE or UNDETERMINED, with the evidence",
        description=(
            "Reads one FILE and prints the COMPILER's report. "
            "Ends with 0 for FEASIBLE, 1 for INFEASIBLE or UNDETERMINED, "
            "and 2 when the FILE could not be read or its report could not be written. "
            "With --answer-first, the answer is printed as soon as it is proved, and the "
            "report follows when the check is done. With --json as well, the answer is the "
            'line {"answer": ..., "unfinished": true}, and the report is one line after it. '
            "To stop a check, end the command: closing its output does not stop the search."
        ),
    )
    check.add_argument("file", type=Path, help="the trip, as a JSON FILE")
    check.add_argument("--json", action="store_true", help="print the report as JSON")
    check.add_argument(
        "--answer-first",
        action="store_true",
        help="print the answer as soon as it is proved, ahead of the report",
    )
    view = commands.add_parser(
        "view",
        help="show a trip on a page that follows the FILE as it changes",
        description=(
            "Serves a page on this machine that shows the COMPILER's answer and report on one "
            "FILE, with a calendar of the trip. Each time the FILE changes, the COMPILER checks "
            "it again and the page shows the new answer. Ends with 2 when the FILE is not there. "
            "Stop it with Ctrl-C. The view listens on this machine only, and it has no sign-in."
        ),
    )
    view.add_argument("file", type=Path, help="the trip, as a JSON FILE")
    view.add_argument(
        "--port",
        type=int,
        default=0,
        help=(
            "the port to serve on: one from 1024 to 65535 that browsers open, "
            "or a free port if not given"
        ),
    )
    view.add_argument("--no-browser", action="store_true", help="do not open the page in a browser")
    view.add_argument(
        "--allowed-host",
        metavar="NAME",
        help=(
            "one more name that the view answers under, such as view.example.org: the name of "
            "a gateway of your own that passes requests on to the view. It is the name of a "
            "host, or an address of four numbers, with the port after a colon where the gateway "
            "has one. The gateway has to pass each request on with the name that the browser "
            "asked for, in its Host line. Give the view a --port for the gateway to pass "
            "requests to. The view has no sign-in, so the gateway needs one"
        ),
    )
    chosen = parser.parse_args(arguments)
    if chosen.command == "view":
        return _view(chosen.file, chosen.port, not chosen.no_browser, chosen.allowed_host)

    try:
        file = read(chosen.file)
    except OSError as problem:
        print(f"{chosen.file}: {problem.strerror or problem}", file=sys.stderr)
        return 2
    except FileError as refused:
        print(f"{chosen.file} does not follow the format:", file=sys.stderr)
        for problem in refused.problems:
            print(f"  {problem}", file=sys.stderr)
        return 2
    # The answer comes ahead of the report where it is asked for. Each is written out at once,
    # so whoever reads the answer has it while the search for the evidence goes on.
    series = compiler.reports(file) if chosen.answer_first else iter([compiler.check(file)])
    answer = None
    for found in series:
        try:
            printed = _in_print(file, found, chosen.json, chosen.answer_first)
        except Unwritable:
            print(
                f"{chosen.file}: the report holds a time outside the years 0001 to 9999, "
                "so it cannot be written",
                file=sys.stderr,
            )
            return 2
        try:
            print(printed, end="", flush=True)
        except BrokenPipeError:
            _leave_the_output()
            return 2
        except (OSError, UnicodeError) as problem:
            print(f"{chosen.file}: the output could not be written: {problem}", file=sys.stderr)
            return 2
        answer = found if isinstance(found, Answer) else found.answer
    return 0 if answer is Answer.FEASIBLE else 1


def _view(path: Path, port: int, in_a_browser: bool, allowed_host: str | None = None) -> int:
    """Serve the view of one FILE on this machine until the command is stopped.

    ``allowed_host`` is one more name that the view answers under, where the person gives one.
    """
    if not path.is_file():
        print(f"{path}: there is no such FILE", file=sys.stderr)
        return 2
    # The view needs sockets and processes, so it is loaded only where it is asked for.
    from agloe.view import View
    from agloe.view.serve import NotAHost

    try:
        view = View(path, port, allowed_host=allowed_host)
    except NotAHost as problem:
        print(f"{problem}.", file=sys.stderr)
        return 2
    except ValueError as problem:
        print(f"{problem}. Leave --port out, and the view takes a free port.", file=sys.stderr)
        return 2
    except OSError as problem:
        print(f"the view cannot be served on port {port}: {problem.strerror}", file=sys.stderr)
        return 2
    # However the command is stopped, and whenever, the check that is running is ended with it.
    signal.signal(signal.SIGTERM, _stopped)
    try:
        print(f"The view of {path} is at {view.address}", flush=True)
        if view.allowed_host is not None:
            print(
                f"It also answers under the name {view.allowed_host}, for a gateway of your own "
                "that passes requests on to it with the name that the browser asked for. "
                "The view has no sign-in: the gateway needs one.",
                flush=True,
            )
        if in_a_browser:
            # A browser can take its time, and some wait until they are closed. The view
            # serves meanwhile, or the browser would wait for a page that nobody sends.
            threading.Thread(target=webbrowser.open, args=(view.address,), daemon=True).start()
        view.serve()
    except KeyboardInterrupt:
        pass
    finally:
        view.close()
    return 0


def _stopped(signal_number: int, frame: object) -> None:
    """The command was told to end. It ends the way Ctrl-C ends it."""
    raise KeyboardInterrupt


def _in_print(file: File, found: Answer | Report, as_json: bool, on_one_line: bool) -> str:
    """What the command prints for an answer given ahead of its Report, or for a Report."""
    if as_json:
        ahead = isinstance(found, Answer)
        shape = report.answer_as_json(found) if ahead else report.as_json(file, found)
        return json.dumps(shape, indent=None if on_one_line else 2, ensure_ascii=False) + "\n"
    if isinstance(found, Answer):
        # An empty line parts the answer from the report that follows.
        return report.answer_as_text(found) + "\n"
    return report.as_text(file, found)


def _leave_the_output() -> None:
    """Whoever read the output has stopped reading. Nothing more is written to it.

    Python writes out what is left when it ends, and would report the same failure again. So
    the output is pointed at nothing first.
    """
    try:
        nothing = os.open(os.devnull, os.O_WRONLY)
        os.dup2(nothing, sys.stdout.fileno())
        os.close(nothing)
    except OSError, ValueError:
        pass
