"""What the COMPILER says about one state of a FILE, one event after another.

A state of a FILE is its content at one moment. ``checked`` takes that content, so every event
is about exactly those bytes, whatever happens to the FILE on disk in the meantime. Nothing is
written anywhere.

The events: ``read`` as soon as the FILE is read, with the TRIP as the page draws it from the
FILE alone. Then ``answer`` as soon as the answer is proved, then ``report`` with the report in
words and as JSON, and with the TRIP as the page draws it with that report. A FILE that does not
follow the format has no report, and gets ``refused`` with the problems. A report that cannot be
written gets ``unwritable``, after its answer.

``python -m agloe.view.check`` reads the content from its input and prints each event as one
line of JSON. The view runs that in a process of its own, because a check can only be stopped
by ending its process.
"""

import io
import json
import sys
import time
from collections.abc import Iterator

from agloe import compiler, report
from agloe.answers import Answer, Report
from agloe.file import File, FileError, Unwritable, parse
from agloe.view import trip

type Event = dict[str, object]


def checked(content: bytes) -> Iterator[Event]:
    """The events for a FILE with this content: ``refused``, or ``read`` and what follows it."""
    try:
        # The text is read as ``agloe check`` reads it from disk, with every kind of line ending
        # taken for one, so that both name the same line of a FILE that is no JSON.
        file = parse(io.TextIOWrapper(io.BytesIO(content), encoding="utf-8").read())
    except UnicodeDecodeError as problem:
        yield {"kind": "refused", "problems": [f"not readable as JSON: {problem}"]}
        return
    except FileError as refused:
        yield {"kind": "refused", "problems": list(refused.problems)}
        return
    # A page can draw the FILE while the COMPILER works: what the FILE holds needs no report.
    yield {"kind": "read", "trip": _to_draw(file, None)}
    started = time.perf_counter()
    for found in compiler.reports(file):
        seconds = round(time.perf_counter() - started, 3)
        if isinstance(found, Answer):
            yield {"kind": "answer", "answer": found.value, "seconds": seconds}
            continue
        try:
            event: Event = {
                "kind": "report",
                "answer": found.answer.value,
                "json": report.as_json(file, found),
                "text": report.as_text(file, found),
                "seconds": seconds,
            }
        except Unwritable:
            yield {"kind": "unwritable"}
            return
        yield {**event, "trip": _to_draw(file, found)}


def _to_draw(file: File, found: Report | None) -> object:
    """The TRIP as the page draws it, or None where there is none to send.

    ``found`` is the report on it, or None before there is one. The report is whole without
    the TRIP. So a fault in what makes the drawing costs the reader the calendar, and never
    the report.
    """
    try:
        sent = trip.shown(file, found)
        json.dumps(sent)  # what cannot be printed is no TRIP to send
    except Exception:  # whatever goes wrong in making the drawing, the report goes out
        return None
    return sent


if __name__ == "__main__":
    for event in checked(sys.stdin.buffer.read()):
        # Plain ASCII on the wire: whatever a name in the FILE holds, the line can be written.
        sys.stdout.buffer.write(json.dumps(event).encode("ascii") + b"\n")
        sys.stdout.buffer.flush()
