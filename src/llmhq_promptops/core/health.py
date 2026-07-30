"""Repository health checks behind ``promptops doctor`` (v0.5.0, TODO-S4).

Six checks, fixed. Not a plugin registry, not extensible, no auto-fix. The
value of `doctor` is that one command answers "is this setup sane" instead of
making someone remember which six things to inspect by hand; that value comes
from the list being short and curated, not from it being open-ended.

Status semantics matter for the exit code:

- ``OK``   — nothing to say.
- ``WARN`` — a state you may have chosen deliberately. Hooks are opt-in since
  v0.4.0, a repo can legitimately have no snapshot and no deploys yet.
  Warnings do not fail the command.
- ``FAIL`` — actually broken. Fails the command.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class CheckStatus(Enum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True)
class Check:
    """One health check result."""

    name: str
    status: CheckStatus
    message: str
    hint: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "hint": self.hint,
        }


def _check_structure(repo: Path) -> Check:
    promptops_dir = repo / ".promptops"

    if not promptops_dir.is_dir():
        return Check(
            name="structure",
            status=CheckStatus.FAIL,
            message=f"No .promptops/ directory under {repo}.",
            hint="Run 'promptops init repo' to create it.",
        )

    prompts_dir = promptops_dir / "prompts"
    snapshot = promptops_dir / "snapshot.json"
    if not prompts_dir.is_dir() and not snapshot.exists():
        return Check(
            name="structure",
            status=CheckStatus.FAIL,
            message=(
                ".promptops/ exists but has neither a prompts/ directory nor "
                "a snapshot.json, so no prompt can be resolved."
            ),
            hint="Run 'promptops init repo', or ship a snapshot.json.",
        )

    config = promptops_dir / "config.yaml"
    if config.exists():
        try:
            import yaml

            yaml.safe_load(config.read_text(encoding="utf-8"))
        except Exception as exc:
            return Check(
                name="structure",
                status=CheckStatus.FAIL,
                message=f".promptops/config.yaml does not parse: {exc}",
                hint="Fix the YAML syntax, or delete it to use defaults.",
            )

    return Check(
        name="structure",
        status=CheckStatus.OK,
        message=f".promptops/ is present and well-formed at {promptops_dir}.",
    )


def _check_hooks(repo: Path) -> Check:
    hooks_dir = repo / ".git" / "hooks"

    if not hooks_dir.is_dir():
        return Check(
            name="hooks",
            status=CheckStatus.WARN,
            message="No .git/hooks directory: automatic versioning is off.",
            hint="Run 'promptops hooks install' to enable it.",
        )

    installed = []
    for name in ("pre-commit", "post-commit"):
        hook = hooks_dir / name
        if hook.exists():
            try:
                if "promptops" in hook.read_text(encoding="utf-8", errors="ignore"):
                    installed.append(name)
            except OSError:
                continue

    if not installed:
        return Check(
            name="hooks",
            status=CheckStatus.WARN,
            message=(
                "PromptOps git hooks are not installed. Prompt versions will "
                "not bump automatically on commit."
            ),
            hint=(
                "Run 'promptops hooks install'. Hooks are opt-in since "
                "v0.4.0, so this may be deliberate."
            ),
        )

    return Check(
        name="hooks",
        status=CheckStatus.OK,
        message=f"PromptOps hooks installed: {', '.join(sorted(installed))}.",
    )


def _check_snapshot(repo: Path) -> Check:
    from .snapshot import SNAPSHOT_FILENAME

    path = repo / ".promptops" / SNAPSHOT_FILENAME

    if not path.exists():
        return Check(
            name="snapshot",
            status=CheckStatus.WARN,
            message=(
                "No snapshot.json. Production runtimes without .git/ cannot "
                "resolve prompts."
            ),
            hint="Build one in CI with 'promptops snapshot build'.",
        )

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return Check(
            name="snapshot",
            status=CheckStatus.FAIL,
            message=f"snapshot.json exists but does not parse: {exc}",
            hint="Rebuild it with 'promptops snapshot build'.",
        )

    built_from = data.get("generated_from_commit")
    head = _head_sha(repo)

    if head and built_from and built_from != head:
        return Check(
            name="snapshot",
            status=CheckStatus.WARN,
            message=(
                f"snapshot.json is stale: built from {built_from[:12]}, "
                f"HEAD is {head[:12]}."
            ),
            hint="Rebuild with 'promptops snapshot build'.",
        )

    count = len(data.get("prompts", {}))

    if not head:
        # HEAD is unknowable: no git binary, no .git/, or a repo with no
        # commits. The staleness comparison above is guarded on `head` and so
        # silently did not run, and falling through to "is current, at HEAD"
        # asserted freshness that was never checked. Report what is actually
        # known instead. Still OK rather than WARN, because a production image
        # with no git is the intended state and doctor should stay quiet there.
        built = built_from[:12] if built_from else "an unrecorded commit"
        return Check(
            name="snapshot",
            status=CheckStatus.OK,
            message=(
                f"snapshot.json parses ({count} prompt(s)), built from {built}. "
                f"Cannot compare against HEAD from here."
            ),
            hint="Freshness is verifiable where git and .git/ are available.",
        )

    return Check(
        name="snapshot",
        status=CheckStatus.OK,
        message=f"snapshot.json is current ({count} prompt(s), at HEAD).",
    )


def _check_deploy_log(repo: Path) -> Check:
    from .deploys import DeployLog

    log = DeployLog(str(repo))

    if not log.exists():
        return Check(
            name="deploy log",
            status=CheckStatus.WARN,
            message=(
                "No deploys.jsonl. 'promptops blame --at' has nothing to "
                "answer from."
            ),
            hint=(
                "Record deploys in CI with 'promptops deploy event', or seed "
                "history with 'promptops backfill-deploys --from-git-log'."
            ),
        )

    try:
        read = log.read()
    except Exception as exc:
        return Check(
            name="deploy log",
            status=CheckStatus.FAIL,
            message=f"deploys.jsonl could not be read: {exc}",
            hint="Inspect the file; it may be truncated or oversized.",
        )

    if read.skipped:
        return Check(
            name="deploy log",
            status=CheckStatus.FAIL,
            message=(
                f"deploys.jsonl has {read.skipped} malformed line(s) that are "
                f"being skipped. Blame answers may be incomplete."
            ),
            hint="Repair or remove the malformed lines.",
        )

    return Check(
        name="deploy log",
        status=CheckStatus.OK,
        message=f"deploys.jsonl has {len(read.events)} event(s), none malformed.",
    )


def _check_versions(repo: Path) -> Check:
    from .errors import E018_GIT_BINARY_MISSING, PromptOpsError
    from .git_versioning import GitVersioning

    # get_prompt_versions has to be inside this try too. It was outside, so in
    # a container with prompts on disk but no git binary its E018 escaped to
    # run_all_checks' generic handler, which reported FAIL and told the user
    # they had found a PromptOps bug. A snapshot-only runtime is a supported
    # deployment; the absence of git there is expected, not a fault.
    try:
        git = GitVersioning(str(repo))
        prompts = sorted(git.list_available_prompts())

        if not prompts:
            return Check(
                name="versions",
                status=CheckStatus.WARN,
                message="No prompts found under .promptops/prompts/.",
                hint="Create one with 'promptops create prompt <id>'.",
            )

        unversioned = [p for p in prompts if not git.get_prompt_versions(p)]
    except PromptOpsError as exc:
        if exc.code == E018_GIT_BINARY_MISSING:
            return Check(
                name="versions",
                status=CheckStatus.WARN,
                message=(
                    "No git executable on PATH, so committed versions cannot "
                    "be read here."
                ),
                hint=(
                    "Expected in a snapshot-only runtime, where prompts "
                    "resolve from snapshot.json and nothing needs git. "
                    "Install git if you want version history in this "
                    "environment."
                ),
            )
        return Check(
            name="versions",
            status=CheckStatus.WARN,
            message=f"Could not enumerate prompts: {exc}",
            hint="Check that this is a git repository.",
        )
    except Exception as exc:
        return Check(
            name="versions",
            status=CheckStatus.WARN,
            message=f"Could not enumerate prompts: {exc}",
            hint="Check that this is a git repository.",
        )

    if unversioned:
        return Check(
            name="versions",
            status=CheckStatus.WARN,
            message=(
                f"{len(unversioned)} of {len(prompts)} prompt(s) have no "
                f"committed version: {', '.join(unversioned)}."
            ),
            hint=(
                "Commit them. Until then they resolve only via ':unstaged' "
                "and cannot be snapshotted at a commit."
            ),
        )

    return Check(
        name="versions",
        status=CheckStatus.OK,
        message=f"All {len(prompts)} prompt(s) resolve to a committed version.",
    )


def _check_resolver(repo: Path) -> Check:
    from .snapshot import SNAPSHOT_FILENAME

    snapshot = repo / ".promptops" / SNAPSHOT_FILENAME
    is_git = (repo / ".git").exists()

    if snapshot.exists():
        return Check(
            name="resolver",
            status=CheckStatus.OK,
            message=(
                f"AutoResolver will use snapshot mode ({snapshot}). "
                f"Snapshot is preferred over git whenever it is present."
            ),
            hint=(
                "Delete snapshot.json if you meant to resolve from git "
                "history in this working tree."
            ),
        )

    if is_git:
        return Check(
            name="resolver",
            status=CheckStatus.OK,
            message=f"AutoResolver will use git mode ({repo}).",
        )

    return Check(
        name="resolver",
        status=CheckStatus.FAIL,
        message="Neither snapshot.json nor .git/ is present: nothing can resolve.",
        hint="Build a snapshot, or run inside a git repository.",
    )


# Order matters: this is the order doctor prints, and it runs cheapest and
# most fundamental first so a broken structure is reported before checks that
# depend on it produce confusing noise.
_CHECKS = (
    _check_structure,
    _check_hooks,
    _check_snapshot,
    _check_deploy_log,
    _check_versions,
    _check_resolver,
)


def _head_sha(repo: Path) -> Optional[str]:
    try:
        from git import Repo

        return Repo(str(repo)).head.commit.hexsha
    except Exception:
        return None


def run_all_checks(repo_path: str = ".") -> List[Check]:
    """Run every health check against ``repo_path``.

    A check that raises is reported as a FAIL rather than taking down the
    whole command: a broken check must not hide the results of the others.
    """
    repo = Path(repo_path).resolve()

    results: List[Check] = []
    for check in _CHECKS:
        try:
            results.append(check(repo))
        except Exception as exc:  # pragma: no cover - defensive
            results.append(
                Check(
                    name=check.__name__.removeprefix("_check_"),
                    status=CheckStatus.FAIL,
                    message=f"Check raised {type(exc).__name__}: {exc}",
                    hint="This is a PromptOps bug; please report it.",
                )
            )
    return results
