"""Catching PromptOpsError and acting on error codes.

Every user-facing PromptOps error carries four fields: a stable
``PROMPTOPS_E0XX`` code, a message, a hint naming the next action, and a doc
URL. The code is the part worth building on: message text can be reworded in
any release, codes cannot.

``PromptOpsError`` subclasses ``ValueError`` deliberately, so pre-v0.4.0 code
that wrote ``except ValueError`` keeps working. New code should catch
``PromptOpsError`` and branch on ``.code``.

Run: python main.py   (needs no network and no API key; creates its own
throwaway git repo in a temp directory, since PromptManager resolves from git
by default)
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from llmhq_promptops import PromptManager, PromptOpsError
from llmhq_promptops.core import errors


PROMPT = """\
metadata:
  id: greeting
  description: Greeting
template: |
  Hello {{ name }}, your tier is {{ tier }}.
variables:
  name:
    type: string
    required: true
  tier:
    type: string
    required: true
"""


def demo_structured_fields(manager: PromptManager) -> None:
    """Every field on the error, and why each exists."""
    print("=" * 60)
    print("1. The four fields")
    print("=" * 60)

    try:
        manager.get_prompt("no-such-prompt")
    except PromptOpsError as exc:
        print(f"code:    {exc.code}")
        print(f"message: {exc.message}")
        print(f"hint:    {exc.hint}")
        print(f"docs:    {exc.doc_url}")
        print()
        print("to_dict() for structured logging:")
        print(f"  {exc.to_dict()}")
    print()


def demo_branching_on_code(manager: PromptManager) -> None:
    """Branch on the code, never on the message text."""
    print("=" * 60)
    print("2. Branching on .code")
    print("=" * 60)

    try:
        # Missing a required variable: renders, but not the way you meant.
        manager.get_prompt("greeting", {"name": "Ada"})
        print("rendered without 'tier' (undefined renders empty)")
    except PromptOpsError as exc:
        if exc.code == errors.E014_RENDER_FAILED:
            print("render failed; check the variables you passed")
        elif exc.code == errors.E003_PROMPT_NOT_FOUND:
            print("prompt id is wrong")
        else:
            raise
    print()

    # Validate up front rather than discovering it at render time.
    template = manager.get_template("greeting")
    problems = template.validate_variables({"name": "Ada"})
    print(f"validate_variables({{'name': 'Ada'}}) -> {problems}")
    print()


def demo_valueerror_compatibility(manager: PromptManager) -> None:
    """Old handlers keep working: PromptOpsError IS a ValueError."""
    print("=" * 60)
    print("3. Backwards compatibility")
    print("=" * 60)

    try:
        manager.get_prompt("no-such-prompt")
    except ValueError as exc:
        print(f"caught as ValueError: {type(exc).__name__}")
        print(f"isinstance PromptOpsError: {isinstance(exc, PromptOpsError)}")
    print()


def demo_e012(tmp: Path) -> None:
    """E012: a template that could never render, caught at build time."""
    print("=" * 60)
    print("4. E012, caught before it reaches production")
    print("=" * 60)

    from llmhq_promptops.core.snapshot import find_unsupported_includes

    bad = 'Hello {{ name }}.\n{% include "footer.txt" %}\n'
    findings = find_unsupported_includes(bad)
    print(f"find_unsupported_includes -> {findings}")
    print(
        "snapshot build would refuse this: the sandbox has no template loader,"
    )
    print("so the include can never resolve at runtime.")
    print()


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        prompts = tmp / ".promptops" / "prompts"
        prompts.mkdir(parents=True)
        (prompts / "greeting.yaml").write_text(PROMPT)

        # PromptManager defaults to GitResolver, which needs a repository.
        # In production you would pass resolver=AutoResolver(...) instead and
        # ship a snapshot.json; see examples/docker-snapshot/.
        for args in (
            ["init", "--quiet"],
            ["config", "user.email", "example@promptops.dev"],
            ["config", "user.name", "PromptOps Example"],
            ["config", "commit.gpgsign", "false"],
            ["add", "."],
            ["commit", "--quiet", "-m", "feat: greeting"],
        ):
            subprocess.run(["git", *args], cwd=tmp, check=True, capture_output=True)

        manager = PromptManager(str(tmp))

        demo_structured_fields(manager)
        demo_branching_on_code(manager)
        demo_valueerror_compatibility(manager)
        demo_e012(tmp)

        print("Full registry: docs/error-codes.md (E001 through E017).")


if __name__ == "__main__":
    main()
