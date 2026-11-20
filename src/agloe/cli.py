"""The command line: ``agloe check FILE`` prints the COMPILER's report for one FILE."""

import argparse
import json
import os
import sys
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
    chosen = parser.parse_args(arguments)

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
