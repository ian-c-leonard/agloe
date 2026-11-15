"""The command line: ``agloe check FILE`` prints the COMPILER's report for one FILE."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from agloe import compiler, report
from agloe.file import FileError, read
from agloe.reference import Answer


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the command. Returns 0 for FEASIBLE, 1 for another answer, 2 when nothing was checked."""
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
            "and 2 when the FILE could not be read."
        ),
    )
    check.add_argument("file", type=Path, help="the trip, as a JSON FILE")
    check.add_argument("--json", action="store_true", help="print the report as JSON")
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
    found = compiler.check(file)
    if chosen.json:
        print(json.dumps(report.as_json(file, found), indent=2, ensure_ascii=False))
    else:
        print(report.as_text(file, found), end="")
    return 0 if found.answer is Answer.FEASIBLE else 1
