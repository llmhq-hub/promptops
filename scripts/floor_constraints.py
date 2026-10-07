#!/usr/bin/env python3
"""Print the declared dependency floors as a pip constraints file.

    python scripts/floor_constraints.py > floors.txt
    pip install -c floors.txt -e .

CI installs the package this way in its "floors" leg, so the suite runs at
exactly the minimum versions pyproject.toml promises, not only at whatever
pip resolves today. Nothing had ever installed the floors before 0.6.1, and
the declared combination turned out not to work (typer 0.15.2 with any
click >= 8.3 silently drops required options). Deriving the set from
pyproject.toml, rather than keeping a second list, means the two cannot
drift apart.

Only ``>=`` lower bounds are turned into ``==`` pins. Anything else in a
specifier (markers, extras, upper bounds) is passed through unchanged.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"

# name, optional extras, then a specifier that begins with >=
_FLOOR_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(?P<extras>\[[^\]]*\])?\s*>=\s*(?P<version>[^,;\s]+)"
)


def _dependencies_from_toml(text: str) -> list[str]:
    """The [project].dependencies list, via tomllib (Python 3.11+)."""
    import tomllib  # noqa: PLC0415

    return list(tomllib.loads(text)["project"]["dependencies"])


def _dependencies_by_regex(text: str) -> list[str]:
    """Fallback for 3.10, which has no tomllib: read the literal list.

    Deliberately narrow. It expects ``dependencies = [`` followed by one
    quoted requirement per line, which is how this file is written.
    """
    match = re.search(r"^dependencies\s*=\s*\[(?P<body>.*?)^\]", text, re.M | re.S)
    if not match:
        raise SystemExit("floor_constraints: could not find [project].dependencies")
    return re.findall(r'"([^"]+)"', match.group("body"))


def floors(text: str) -> list[str]:
    try:
        deps = _dependencies_from_toml(text)
    except ModuleNotFoundError:
        deps = _dependencies_by_regex(text)

    out = []
    for dep in deps:
        m = _FLOOR_RE.match(dep)
        if m:
            out.append(f"{m.group('name')}=={m.group('version')}")
        else:
            out.append(dep)
    return out


def main() -> int:
    for line in floors(_PYPROJECT.read_text(encoding="utf-8")):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
