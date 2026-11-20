"""What the view tells a page about one FILE as it is now, one event after another.

First that there is a FILE to check. Then the answer as soon as it is proved, and then the
report in words and as JSON. A FILE that cannot be read, or that does not follow the format,
has no report: the page is told the problems instead. The view adds ``stopped`` where a check
ends with neither.

``python -m agloe.view.check FILE`` prints each event as one line of JSON. The view runs that
in a process of its own, because a check can only be stopped by ending its process.
"""

import json
import sys
import time
from collections.abc import Iterator
from pathlib import Path

from agloe import compiler, report
from agloe.answers import Answer
from agloe.file import FileError, Unwritable, read

type Event = dict[str, object]


def events(path: Path) -> Iterator[Event]:
    """The events for this FILE: ``file``, then ``refused``, or ``answer`` and ``report``."""
    yield {"kind": "file", "name": path.name}
    try:
        file = read(path)
    except OSError as problem:
        yield {"kind": "refused", "problems": [f"not readable: {problem.strerror or problem}"]}
        return
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
            problem = "the report holds a time outside the years 0001 to 9999"
            yield {"kind": "refused", "problems": [f"{problem}, so it cannot be written"]}
            return
        yield shown


if __name__ == "__main__":
    for event in events(Path(sys.argv[1])):
        print(json.dumps(event, ensure_ascii=False), flush=True)
