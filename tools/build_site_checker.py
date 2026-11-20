"""Put the reference checker where the home page can load it: ``pages/vendor/``.

The home page runs the reference checker in the visitor's browser, on the trip the visitor has
changed. It is the checker of this repository, not a copy of its rules. Three things make that
possible, and this script gathers them:

- Agloe itself, built as a wheel from ``src/``.
- Pyodide, which is Python for browsers, and the packages Agloe needs to read a FILE. Each
  download is checked against a recorded checksum.
- The time zone data that ``uv.lock`` names, so that the page and the command line agree.

The folder is not committed. The pages workflow runs this before it publishes agloe.ai:

    uv run python tools/build_site_checker.py
"""

import hashlib
import json
import shutil
import subprocess
import sys
import tomllib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "pages" / "vendor"
PYODIDE = "https://cdn.jsdelivr.net/pyodide/v314.0.8/full/"
# The files of Pyodide itself, with the SHA-256 of each.
CORE = {
    "pyodide.mjs": "1bb8cc14f9405aaa7cd4e00c12edd0a8539de9cc026618d6ee5a9663f367dc70",
    "pyodide.asm.mjs": "22514b8be6980e28a02c8b1d6387ce8dfe666fc4edf8d547cff5dce29ff4d972",
    "pyodide.asm.wasm": "e14d49ceca9b4a0e274ea918f3a898de2d3880b6e5573a6cfe1a2267ecc70329",
    "python_stdlib.zip": "2bd3394a145bfbbe5bbc9d9d6ab9136abbb986c6fef6c142b3a2962227aa5c28",
    "pyodide-lock.json": "5dc2fc119108bc148c7457dc86e7675b5c87e1cafd420b9c34c1eaef7b36c010",
}
# What Agloe needs from Pyodide's own packages. Pyodide's lock file names what these need in turn.
FROM_PYODIDE = ["jsonschema"]
# What Agloe needs exactly as uv.lock pins it, because it changes answers.
FROM_THE_LOCK = ["tzdata"]


def fetched(url: str, sha256: str, to: Path) -> Path:
    """Download one file, unless it is already here, and stop if it is not the file expected."""
    if not to.exists() or hashlib.sha256(to.read_bytes()).hexdigest() != sha256:
        with urllib.request.urlopen(url) as response:
            to.write_bytes(response.read())
    found = hashlib.sha256(to.read_bytes()).hexdigest()
    if found != sha256:
        to.unlink()
        sys.exit(f"{url} is not the file expected: its SHA-256 is {found}, not {sha256}")
    return to


def needed(packages: dict[str, dict[str, object]], names: list[str]) -> list[str]:
    """These packages and everything they depend on, by Pyodide's lock file."""
    found: list[str] = []
    waiting = list(names)
    while waiting:
        name = waiting.pop(0)
        if name not in found:
            found.append(name)
            depends = packages[name]["depends"]
            assert isinstance(depends, list)
            waiting += [str(other).lower().replace("_", "-") for other in depends]
    return found


def main() -> None:
    pyodide = VENDOR / "pyodide"
    wheels = VENDOR / "wheels"
    pyodide.mkdir(parents=True, exist_ok=True)
    if wheels.exists():
        shutil.rmtree(wheels)
    wheels.mkdir()

    for name, sha256 in CORE.items():
        fetched(PYODIDE + name, sha256, pyodide / name)
    packages = json.loads((pyodide / "pyodide-lock.json").read_text())["packages"]
    for name in needed(packages, FROM_PYODIDE):
        file = str(packages[name]["file_name"])
        fetched(PYODIDE + file, str(packages[name]["sha256"]), pyodide / file)

    unpacked: list[str] = []
    locked = tomllib.loads((ROOT / "uv.lock").read_text())["package"]
    for name in FROM_THE_LOCK:
        (wheel,) = next(package["wheels"] for package in locked if package["name"] == name)
        file = wheel["url"].rsplit("/", 1)[1]
        fetched(wheel["url"], wheel["hash"].removeprefix("sha256:"), wheels / file)
        unpacked.append(f"wheels/{file}")

    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(wheels)], cwd=ROOT, check=True)
    (wheels / ".gitignore").unlink(missing_ok=True)
    (agloe,) = wheels.glob("agloe-*.whl")
    unpacked.append(f"wheels/{agloe.name}")

    # The page reads this to know what to load, so no name is written twice.
    (VENDOR / "checker.json").write_text(
        json.dumps({"packages": FROM_PYODIDE, "wheels": unpacked}, indent=2) + "\n"
    )
    size = sum(file.stat().st_size for file in VENDOR.rglob("*") if file.is_file())
    print(f"pages/vendor/ holds the checker: {size / 1e6:.1f} MB in all")


if __name__ == "__main__":
    main()
