#!/usr/bin/env python3
"""
Basic Usage Examples for llmhq-promptops

Demonstrates the core SDK: prompt resolution with version references,
the PromptManager API, template rendering, and the v0.4.0 PROMPTOPS_E0XX
error system.

Run inside a git repo that has been set up with:
    promptops init repo
    promptops create prompt welcome-message
The template-rendering and error-handling sections are self-contained and
run anywhere.
"""

from pathlib import Path

from llmhq_promptops import get_prompt, PromptManager, PromptOpsError
from llmhq_promptops.core.template import PromptTemplate


def _required_vars(template: PromptTemplate):
    """Public way to list a template's required variables."""
    return [name for name, v in template.variables.items() if v.required]


def example_basic_prompt_resolution():
    """Basic prompt resolution with different version references."""
    print("🔍 Basic Prompt Resolution Examples")
    print("=" * 50)

    try:
        # Smart default — resolves :unstaged if it differs from working,
        # else working. The starter template scaffolded by
        # `promptops create prompt` uses {{ user_input }}.
        prompt1 = get_prompt("welcome-message:unstaged", {"user_input": "Alice"})
        print(f"Smart default: {prompt1[:100]}")

        # Latest committed (HEAD)
        prompt2 = get_prompt("welcome-message:working", {"user_input": "Bob"})
        print(f"Working (HEAD) version: {prompt2[:100]}")

    except PromptOpsError as e:
        print(f"⚠️  Example needs a prompt named 'welcome-message' [{e.code}]")
        print("💡 Run: promptops init repo && promptops create prompt welcome-message")


def example_prompt_manager():
    """PromptManager API: status, metadata, and diffs (public methods only)."""
    print("\n🔧 PromptManager Usage")
    print("=" * 50)

    prompt_id = "welcome-message"
    try:
        manager = PromptManager()

        # Uncommitted-change check
        has_changes = manager.has_uncommitted_changes(prompt_id)
        print(f"📝 {prompt_id} has uncommitted changes: {has_changes}")

        # Metadata without rendering — use the PUBLIC get_template(id, version)
        template = manager.get_template(prompt_id, "working")
        print(f"📋 Template id: {template.metadata.id}")
        print(f"🔧 Required variables: {_required_vars(template)}")

        # Diff two versions. In v0.4.0 this returns a dict and raises
        # PromptOpsError (E003) if a version can't be resolved.
        try:
            diff = manager.get_prompt_diff(prompt_id, "working", "unstaged")
            if diff["identical"]:
                print("✅ working and unstaged are identical")
            else:
                print(f"📊 {diff['lines_added']} line(s) changed between versions")
        except PromptOpsError as e:
            print(f"ℹ️  Could not diff [{e.code}]: {e.message}")

    except PromptOpsError as e:
        print(f"⚠️  [{e.code}] {e.message}")


def example_version_management():
    """List prompts and their working-tree status."""
    print("\n📋 Version Management Examples")
    print("=" * 50)

    prompts_dir = Path(".promptops/prompts")
    if not prompts_dir.exists():
        print("📁 No .promptops/prompts directory — run 'promptops init repo' first")
        return

    try:
        manager = PromptManager()
        prompt_files = sorted(prompts_dir.glob("*.yaml"))
        print(f"📁 Found {len(prompt_files)} prompt file(s):")
        for prompt_file in prompt_files[:5]:
            prompt_id = prompt_file.stem
            try:
                changed = manager.has_uncommitted_changes(prompt_id)
                print(f"   {prompt_id}: {'🔄 modified' if changed else '✅ up to date'}")
            except PromptOpsError as e:
                print(f"   {prompt_id}: ❓ {e.code}")
    except PromptOpsError as e:
        print(f"⚠️  [{e.code}] {e.message}")


def example_template_rendering():
    """Template rendering with variable validation (self-contained)."""
    print("\n🎨 Template Rendering Examples")
    print("=" * 50)

    yaml_content = """
metadata:
  id: example-prompt
  version: "1.0.0"
  description: "Example prompt for demonstration"

template: |
  Hello {{ user_name }}!
  {% if plan %}You are on the {{ plan }} plan.{% endif %}
  Features:
  {% for feature in features %}
  - {{ feature }}
  {% endfor %}

variables:
  user_name: {type: string, required: true}
  plan: {type: string, required: false}
  features: {type: list, default: ["Basic Feature"]}
"""

    # PromptTemplate parses both the metadata: and legacy prompt: schemas
    # and renders inside a Jinja2 sandbox.
    template = PromptTemplate(yaml_content)
    print(f"📋 Template id: {template.metadata.id}")
    print(f"🔧 Required variables: {_required_vars(template)}")

    rendered = template.render({
        "user_name": "Bob",
        "plan": "Enterprise",
        "features": ["Analytics", "Integrations", "Priority Support"],
    })
    print(f"🎨 Rendered:\n{rendered}")

    # Validation: a missing required variable raises.
    try:
        template.render({})
    except ValueError as e:
        print(f"✅ Validation works: {e}")


def example_error_handling():
    """The v0.4.0 PROMPTOPS_E0XX error system: catch by code, read the hint."""
    print("\n⚠️  Error Handling (PROMPTOPS_E0XX)")
    print("=" * 50)

    # Every user-facing error is a PromptOpsError (a ValueError subclass)
    # carrying .code, .message, .hint, and .doc_url.
    try:
        get_prompt("does-not-exist")
    except PromptOpsError as e:
        print(f"✅ caught {e.code}")
        print(f"   message: {e.message}")
        print(f"   hint:    {e.hint}")
        print(f"   docs:    {e.doc_url}")

    # Branch on the stable code, not the message text.
    try:
        get_prompt("welcome-message", {})  # likely missing a required var
    except PromptOpsError as e:
        if e.code == "PROMPTOPS_E014":
            print("✅ render failure handled by code (E014)")
        else:
            print(f"ℹ️  got {e.code}")


def main():
    print("🚀 llmhq-promptops SDK Examples")
    print("=" * 50)
    print("For the resolution sections, run in a repo set up with:")
    print("  promptops init repo && promptops create prompt welcome-message\n")

    example_basic_prompt_resolution()
    example_prompt_manager()
    example_version_management()
    example_template_rendering()
    example_error_handling()

    print("\n✨ Examples completed!")
    print("💡 Create prompts with: promptops create prompt your-prompt-name")
    print("📚 See README.md and docs/error-codes.md for more.")


if __name__ == "__main__":
    main()
