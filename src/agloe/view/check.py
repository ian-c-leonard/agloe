"""What the COMPILER says about one state of a FILE, one event after another.

A state of a FILE is its content at one moment. ``checked`` takes that content, so every event
is about exactly those bytes, whatever happens to the FILE on disk in the meantime.

The events: ``answer`` as soon as the answer is proved, then ``report`` with the report in words
and as JSON. A FILE that does not follow the format has no report, and gets ``refused`` with
the problems. A report that cannot be written gets ``unwritable``, after its answer.

``python -m agloe.view.check`` reads the content from its input and prints each event as one
line of JSON, in UTF-8. The view runs that in a process of its own, because a check can only
be stopped by ending its process.
"""

import json
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

from agloe import compiler, report
from agloe.answers import Answer
from agloe.file import FileError, Unwritable, read

type Event = dict[str, object]


def checked(content: bytes) -> Iterator[Event]:
    """The events for a FILE with this content: ``refused``, or ``answer`` and what follows it."""
    # The FILE is read as the command ``agloe check`` reads it, from a copy that nothing changes.
    with tempfile.TemporaryDirectory() as folder:
        copy = Path(folder) / "FILE.json"
        copy.write_bytes(content)
        try:
            file = read(copy)
        except FileError as refused:
            yield {"kind": "refused", "problems": list(refused.problems)}
            return
    started = time.perf_counter()
    for found in compiler.reports(file):
        seconds = round(time.perf_counter() - started, 3)
        if isinstance(found, Answer):
            yield {"kind": "answer", "answer": found.value, "seconds": seconds}
            continue
        try:
            shown: Event = {
                "kind": "report",
                "answer": found.answer.value,
                "json": report.as_json(file, found),
                "text": report.as_text(file, found),
                "seconds": seconds,
            }
        except Unwritable:
            yield {"kind": "unwritable"}
            return
        yield shown


if __name__ == "__main__":
    for event in checked(sys.stdin.buffer.read()):
        sys.stdout.buffer.write(json.dumps(event, ensure_ascii=False).encode() + b"\n")
        sys.stdout.buffer.flush()
