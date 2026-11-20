"""The command line: ``agloe check FILE`` prints the COMPILER's report for one FILE."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from agloe import compiler, report
from agloe.answers import Answer
from agloe.file import FileError, Unwritable, read


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
            "and 2 when the FILE could not be read or its report could not be written."
        ),
    )
    check.add_argument("file", type=Path, help="the trip, as a JSON FILE")
    check.add_argument("--json", action="store_true", help="print the report as JSON")
    check.add_argument(
        "--answer-first",
        action="store_true",
        help=(
            "print the answer as soon as it is proved, and then the report; "
            "with --json, each of the two is one line of JSON"
        ),
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
            if chosen.json:
                indent = None if chosen.answer_first else 2
                shape = report.as_json(file, found)
                printed = json.dumps(shape, indent=indent, ensure_ascii=False) + "\n"
            else:
                printed = report.as_text(file, found)
        except Unwritable:
            print(
                f"{chosen.file}: the report holds a time outside the years 0001 to 9999, "
                "so it cannot be written",
                file=sys.stderr,
            )
            return 2
        if found.unfinished and not chosen.json:
            printed += "\n"
        print(printed, end="", flush=True)
        answer = found.answer
    return 0 if answer is Answer.FEASIBLE else 1
