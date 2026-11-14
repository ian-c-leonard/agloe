"""The words, the examples, the schema and the code say the same thing."""

import re
import subprocess
import sys
from pathlib import Path

from agloe.reference import Constraint
from tests.stories import EXAMPLES

ROOT = Path(__file__).parent.parent
RULES = (ROOT / "spec" / "rules.md").read_text()


def test_the_rules_page_and_the_checker_name_the_same_constraints() -> None:
    section = RULES.split("## The CONSTRAINTs")[1].split("\n## ")[0]
    headings = re.findall(r"^\d+\. \*\*(.+?)\.\*\*", section, flags=re.MULTILINE)
    assert headings == [constraint.value for constraint in Constraint]


def test_the_rules_page_lists_every_example() -> None:
    for path in EXAMPLES.rglob("*.json"):
        if not path.name.endswith(".expected.json"):
            assert f"(../{path.relative_to(ROOT).as_posix()})" in RULES


def test_every_link_on_the_rules_page_leads_somewhere() -> None:
    for target in re.findall(r"\]\(([^)#]+)\)", RULES):
        assert (ROOT / "spec" / target).resolve().exists(), target


def test_the_python_types_match_the_schema() -> None:
    tool = ROOT / "tools" / "generate_file_types.py"
    done = subprocess.run([sys.executable, str(tool), "--check"], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
