"""What the home page runs in the visitor's browser: the reference checker, on one FILE.

The page loads this file into Pyodide, which is Python for browsers, and calls ``check`` each time
the visitor changes the trip. The answer comes from the reference checker of this repository.

A browser has no build of the solver that the COMPILER uses. The reference checker never calls
the solver, but ``import agloe`` does import it. So where the solver is missing, a stand-in takes
its name. Nothing calls the stand-in.
"""

import json
import sys
import time
import types

try:
    import ortools.sat.python.cp_model  # noqa: F401
except ImportError:

    class _Absent:
        """Takes the place of anything the solver's library would provide."""

        def __getattr__(self, name: str) -> _Absent:
            return _Absent()

        def __call__(self, *given: object, **named: object) -> _Absent:
            return _Absent()

    def _nothing(name: str) -> _Absent:
        return _Absent()

    for _name in ("ortools", "ortools.sat", "ortools.sat.python", "ortools.sat.python.cp_model"):
        _module = types.ModuleType(_name)
        _module.__getattr__ = _nothing  # type: ignore[method-assign]
        sys.modules[_name] = _module

from agloe import answers, report
from agloe.file import FileError, load


def check(text: str) -> str:
    """The report for one FILE, as JSON: the answer, the report in words and as data, and the time.

    A FILE that does not follow the format gives ``refused``, with each problem in words.
    """
    started = time.perf_counter()
    try:
        file = load(json.loads(text))
    except FileError as refused:
        return json.dumps({"refused": list(refused.problems)})
    found = answers.check(file)
    return json.dumps(
        {
            "answer": found.answer.value,
            "text": report.as_text(file, found),
            "json": report.as_json(file, found),
            "seconds": time.perf_counter() - started,
        }
    )
