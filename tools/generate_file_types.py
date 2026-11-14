"""Generate ``src/agloe/file_types.py`` from the FILE schema.

The schema is the source of truth for a FILE's shape. Run this after changing it:

    uv run python tools/generate_file_types.py

With ``--check`` it changes nothing and fails if the committed types differ from the schema.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "src" / "agloe" / "schema" / "file.schema.json"
TYPES = ROOT / "src" / "agloe" / "file_types.py"
HEADER = (
    '"""The shape of a FILE as Python types.\n\n'
    'Generated from schema/file.schema.json by tools/generate_file_types.py. Do not edit.\n"""\n\n'
)
GENERATOR = [
    "--input-file-type=jsonschema",
    "--output-model-type=typing.TypedDict",
    "--target-python-version=3.14",
    "--use-standard-collections",
    "--use-union-operator",
    "--use-title-as-name",
    "--no-use-closed-typed-dict",
    "--disable-timestamp",
    "--no-formatters",
]


def run(*command: str) -> None:
    subprocess.run([sys.executable, "-m", *command], check=True, capture_output=True)


def generate() -> str:
    with tempfile.TemporaryDirectory() as folder:
        out = Path(folder) / "file_types.py"
        run("datamodel_code_generator", "--input", str(SCHEMA), "--output", str(out), *GENERATOR)
        lines = [line for line in out.read_text().splitlines() if not line.startswith("#")]
        out.write_text(HEADER + "\n".join(lines).lstrip("\n") + "\n")
        config = str(ROOT / "pyproject.toml")
        run("ruff", "check", "--quiet", "--fix", "--select", "I", "--config", config, str(out))
        run("ruff", "format", "--quiet", "--config", config, str(out))
        return out.read_text()


if __name__ == "__main__":
    wanted = generate()
    if "--check" in sys.argv:
        if TYPES.read_text() != wanted:
            sys.exit(f"{TYPES.relative_to(ROOT)} does not match the schema. Run {sys.argv[0]}.")
    else:
        TYPES.write_text(wanted)
