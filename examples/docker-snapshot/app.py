"""Resolve a prompt in production, with no .git/ anywhere on disk.

Run inside the container built by ./Dockerfile, or locally against any
directory containing .promptops/snapshot.json.

The important line is the resolver choice. AutoResolver picks SnapshotResolver
when snapshot.json is present and GitResolver otherwise, so the same code runs
unchanged in a dev checkout (git) and a production image (snapshot). Since
v0.3.3 the module-level get_prompt() does this for you, but constructing it
explicitly is what you want in a service: one manager, reused.
"""

from pathlib import Path

from llmhq_promptops import AutoResolver, PromptManager


def main() -> None:
    repo = Path(__file__).parent

    manager = PromptManager(str(repo), resolver=AutoResolver(repo_path=str(repo)))

    resolved = manager.resolve("greeting")
    print(f"source:  {resolved.source}")
    print(f"version: {resolved.version}")
    print(f"commit:  {resolved.commit}")
    print()

    rendered = manager.get_prompt("greeting", {"name": "Ada", "tier": "gold"})
    print("rendered:")
    print(rendered)

    # The claim this example exists to demonstrate.
    assert not (repo / ".git").exists(), "this example is meant to run without git"
    assert resolved.source == "snapshot", (
        f"expected snapshot resolution, got {resolved.source!r}"
    )
    print()
    print(
        "OK: resolved from snapshot.json with no .git/ directory, and (in the "
        "container) no git binary either."
    )


if __name__ == "__main__":
    main()
