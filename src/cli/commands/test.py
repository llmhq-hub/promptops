import os
import json
import time
import datetime
import difflib
import yaml
import typer
import sys
from pathlib import Path
from jinja2.sandbox import SandboxedEnvironment
from typing import List, Optional
from io import StringIO

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from llmhq_promptops import get_prompt, PromptManager
from llmhq_promptops.core.impact import SemverImpact, compute_impact
from llmhq_promptops.core.template import PromptTemplate

app = typer.Typer()

@app.command()
def runtest(
    prompt: str = typer.Option(..., "--prompt", help="Prompt reference (name or name:version)"),
    dataset: str = typer.Option(None, "--dataset", help="Path to JSON test dataset (optional for basic tests)"),
    variables: str = typer.Option(None, "--variables", help="JSON string with test variables")
):
    """
    Run tests for a prompt with enhanced version support.

    Supports version references:
    - prompt_name (smart default: unstaged if different, else working)
    - prompt_name:unstaged (uncommitted changes)
    - prompt_name:working (latest committed version)
    - prompt_name:v1.2.3 (specific version)
    
    Examples:
    promptops test --prompt user-onboarding:unstaged --variables '{"user_name":"Alice"}'
    promptops test --prompt user-onboarding:working --dataset test-data.json
    """
    
    try:
        manager = PromptManager()
        
        # Parse prompt reference
        if ":" in prompt:
            prompt_id, version = prompt.split(":", 1)
        else:
            prompt_id, version = prompt, None
            
        # Store original for user feedback
        original_prompt_ref = prompt
        
        # Provide helpful feedback about version selection
        if version is None:
            # Check if there are uncommitted changes
            has_changes = manager.has_uncommitted_changes(prompt_id)
            if has_changes:
                typer.echo(f"🔍 Detected uncommitted changes in {prompt_id}")
                typer.echo(f"📝 Testing :unstaged version (to test committed version, use {prompt_id}:working)")
                version = "unstaged"
            else:
                typer.echo(f"✅ No uncommitted changes, testing :working version")
                version = "working"
        
        full_prompt_ref = f"{prompt_id}:{version}" if version else prompt_id
        typer.echo(f"🧪 Testing prompt: {full_prompt_ref}")
        
        # Show prompt status
        file_status = manager.get_file_status(prompt_id)
        if file_status["has_uncommitted_changes"]:
            typer.echo("📝 Note: Prompt has uncommitted changes")
        
        # Basic validation test if no dataset provided
        if not dataset:
            return _run_basic_validation(manager, prompt_id, version, variables)
        
        # Run dataset-based tests
        return _run_dataset_tests(manager, prompt_id, version, dataset)
        
    except Exception as e:
        typer.echo(f"❌ Test failed: {e}", err=True)
        raise typer.Exit(1)


def _run_basic_validation(manager: PromptManager, prompt_id: str, version: Optional[str], variables: Optional[str]):
    """Run basic validation tests without a dataset."""
    try:
        typer.echo("🔍 Running basic validation tests...")
        
        # Get template info
        template = manager.get_template(prompt_id, version)
        info = manager.get_prompt_info(prompt_id, version)
        
        typer.echo(f"✅ Prompt loaded successfully")
        typer.echo(f"📋 ID: {info['id']}")
        typer.echo(f"📊 Version: {info['version']}")
        typer.echo(f"🎯 Variables: {len(info['variables'])}")
        
        # Parse test variables
        test_vars = {}
        if variables:
            try:
                test_vars = json.loads(variables)
                typer.echo(f"📥 Using provided variables: {list(test_vars.keys())}")
            except json.JSONDecodeError:
                typer.echo("⚠️  Invalid JSON in variables, using defaults")
        
        # Add default values for missing required variables
        for var_name, var_def in template.variables.items():
            if var_name not in test_vars:
                if var_def.default is not None:
                    test_vars[var_name] = var_def.default
                elif var_def.required:
                    # Generate sample value
                    test_vars[var_name] = _generate_sample_value(var_def.type, var_name)
                    typer.echo(f"🔧 Generated sample value for '{var_name}': {test_vars[var_name]}")
        
        # Test rendering
        start_time = time.time()
        rendered = manager.get_prompt(f"{prompt_id}:{version}" if version else prompt_id, test_vars)
        render_time = time.time() - start_time
        
        typer.echo(f"⚡ Render time: {render_time:.3f} seconds")
        typer.echo(f"📏 Output length: {len(rendered)} characters")
        
        # Show preview
        typer.echo("\n📖 Rendered Prompt Preview:")
        typer.echo("=" * 50)
        preview_lines = rendered.split('\n')[:10]
        for line in preview_lines:
            typer.echo(line)
        if len(rendered.split('\n')) > 10:
            typer.echo("... (truncated)")
        typer.echo("=" * 50)
        
        typer.echo("✅ All basic validation tests passed!")
        
    except Exception as e:
        typer.echo(f"❌ Validation failed: {e}", err=True)
        raise typer.Exit(1)


def _run_dataset_tests(manager: PromptManager, prompt_id: str, version: Optional[str], dataset: str):
    """Run tests using a dataset file."""
    typer.echo(f"📁 Loading test dataset: {dataset}")
    
    # Load test cases (using original logic)
    test_cases = load_json_test_cases(dataset)
    results = []
    total_latency = 0.0
    success_count = 0
    total_tests = len(test_cases)

    for idx, test_case in enumerate(test_cases):
        if not isinstance(test_case, dict):
            typer.echo(f"Error: Test case {idx} is not a valid object.")
            continue

        test_input = test_case.get("input")
        expected_output = test_case.get("expected_output")

        if test_input is None or expected_output is None:
            typer.echo(f"Error: Test case {idx} is missing 'input' or 'expected_output' keys.")
            continue

        start_time = time.time()
        try:
            # Use new prompt manager instead of old logic
            prompt_ref = f"{prompt_id}:{version}" if version else prompt_id
            actual_output = manager.get_prompt(prompt_ref, test_input)
        except Exception as e:
            typer.echo(f"Test case {idx} failed with error: {e}")
            continue
            
        latency = time.time() - start_time
        total_latency += latency
        passed = accuracy_match(actual_output, expected_output)
        if passed:
            success_count += 1
        
        results.append({
            "test_index": idx,
            "input": test_input,
            "expected_output": expected_output,
            "actual_output": actual_output,
            "latency": latency,
            "passed": passed
        })

    # Generate report (keeping original logic)
    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    report_lines = [
        f"# Test Report for Prompt '{prompt}' - {date_str}",
        f"- Total tests run: {total_tests}",
        f"- Success count: {success_count}",
        f"- Average latency: {total_latency / total_tests:.2f} seconds" if total_tests > 0 else "",
        "",
        "## Detailed Test Results:",
        ""
    ]
    
    for res in results:
        report_lines.append(f"### Test {res['test_index']}")
        report_lines.append(f"- **Input:** {res['input']}")
        report_lines.append(f"- **Expected Output:** {res['expected_output']}")
        report_lines.append(f"- **Actual Output:** {res['actual_output']}")
        report_lines.append(f"- **Latency:** {res['latency']:.2f} seconds")
        report_lines.append(f"- **Passed:** {res['passed']}")
        report_lines.append("")
    
    report_content = "\n".join(report_lines)
    
    # Save the report under .promptops/results/
    results_dir = os.path.join(os.getcwd(), ".promptops", "results")
    os.makedirs(results_dir, exist_ok=True)
    report_file = os.path.join(results_dir, f"{date_str}-{prompt_id}-test-report.md")
    try:
        with open(report_file, "w") as f:
            f.write(report_content)
        typer.echo(f"Test report saved to {report_file}")
    except Exception as e:
        typer.echo(f"Error saving test report: {e}")
    
    typer.echo("\n" + report_content)


def _generate_sample_value(var_type: str, var_name: str):
    """Generate a sample value for a variable type."""
    if var_type == "string":
        return f"sample_{var_name}"
    elif var_type == "list":
        return ["item1", "item2"]
    elif var_type == "dict":
        return {"key": "value"}
    elif var_type in ["int", "integer"]:
        return 42
    elif var_type in ["float", "number"]:
        return 3.14
    elif var_type == "boolean":
        return True
    else:
        return "sample_value"


@app.command()
def status():
    """Show status of all prompts (working/staged/committed states)."""
    try:
        manager = PromptManager()
        statuses = manager.list_prompt_statuses()
        
        typer.echo("📊 Prompt Status Overview")
        typer.echo("=" * 50)
        
        for prompt_id, status in statuses.items():
            if "error" in status:
                typer.echo(f"❌ {prompt_id}: {status['error']}")
            else:
                status_icon = {
                    "clean": "✅",
                    "modified": "📝", 
                    "staged": "📋",
                    "untracked": "❓",
                    "missing": "❌"
                }.get(status["status"], "❓")
                
                typer.echo(f"{status_icon} {prompt_id} ({status['latest_version']}) - {status['status']}")
        
    except Exception as e:
        typer.echo(f"❌ Failed to get status: {e}", err=True)
        raise typer.Exit(1)


# Exit codes for --exit-code. This borrows git's --exit-code *flag* but not
# git's *numbers*: `git diff --exit-code` returns 1 for "differences found",
# whereas we must encode three severities and still leave a code free to mean
# "the command itself failed". 1 stays reserved for failure.
_IMPACT_EXIT_CODES = {
    SemverImpact.NONE: 0,
    SemverImpact.PATCH: 0,
    SemverImpact.MINOR: 2,
    SemverImpact.MAJOR: 3,
}


def _color_enabled(as_json: bool) -> bool:
    """Colour only when a human on a terminal will actually read it."""
    if as_json or os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


def _render_unified_diff(
    content1: str, content2: str, version1: str, version2: str, color: bool
) -> str:
    lines = difflib.unified_diff(
        content1.splitlines(),
        content2.splitlines(),
        fromfile=version1,
        tofile=version2,
        lineterm="",
    )

    out = []
    for line in lines:
        if not color:
            out.append(line)
        elif line.startswith("+++") or line.startswith("---"):
            out.append(typer.style(line, bold=True))
        elif line.startswith("@@"):
            out.append(typer.style(line, fg=typer.colors.CYAN))
        elif line.startswith("+"):
            out.append(typer.style(line, fg=typer.colors.GREEN))
        elif line.startswith("-"):
            out.append(typer.style(line, fg=typer.colors.RED))
        else:
            out.append(line)
    return "\n".join(out)


_IMPACT_COLORS = {
    SemverImpact.MAJOR: typer.colors.RED,
    SemverImpact.MINOR: typer.colors.YELLOW,
    SemverImpact.PATCH: typer.colors.GREEN,
    SemverImpact.NONE: typer.colors.GREEN,
}


@app.command()
def diff(
    prompt: str = typer.Argument(..., help="Prompt name"),
    version1: str = typer.Option("working", help="First version to compare"),
    version2: str = typer.Option("unstaged", help="Second version to compare"),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON (for CI, PR comments, tooling).",
    ),
    exit_code: bool = typer.Option(
        False,
        "--exit-code",
        help=(
            "Exit with the semver impact: 0 none/patch, 2 minor, 3 major "
            "(1 still means the command failed). Without this flag the "
            "command always exits 0 on success, like 'git diff'."
        ),
    ),
):
    """Compare two versions of a prompt, with semver impact.

    Impact is derived from the prompt's variable signature and declared
    models, never from prose. Adding a required variable is MAJOR because
    every caller must now supply it; rewording the template is PATCH.

    Examples:

      promptops test diff greeting                      # working vs unstaged
      promptops test diff greeting --version1 v1.0.0    # against a tag
      promptops test diff greeting --exit-code          # gate CI on impact
      promptops test diff greeting --json               # for tooling
    """
    try:
        manager = PromptManager()

        # Raises PromptOpsError E003 on a missing version since v0.4.0;
        # the outer except renders it and exits 1.
        diff_result = manager.get_prompt_diff(prompt, version1, version2)

        content1 = diff_result["content1"]
        content2 = diff_result["content2"]
        identical = diff_result["identical"]

        report = compute_impact(
            PromptTemplate(content1), PromptTemplate(content2)
        )
    except Exception as e:
        typer.echo(f"❌ Diff failed: {e}", err=True)
        raise typer.Exit(1)

    color = _color_enabled(as_json)
    unified = _render_unified_diff(content1, content2, version1, version2, color=False)

    if as_json:
        payload = {
            "prompt": prompt,
            "version1": version1,
            "version2": version2,
            "identical": identical,
            "diff": unified,
            **report.to_dict(),
        }
        typer.echo(json.dumps(payload, indent=2))
    else:
        typer.echo(f"🔍 Comparing {prompt}: {version1} vs {version2}")
        typer.echo("=" * 60)

        label = f"IMPACT: {report.impact.value.upper()}"
        typer.echo(
            typer.style(label, fg=_IMPACT_COLORS[report.impact], bold=True)
            if color
            else label
        )
        for change in report.changes:
            typer.echo(f"  {change.impact.value.upper():<5} {change.detail}")

        if identical and not report.changes:
            typer.echo("✅ Versions are identical")
        else:
            typer.echo("")
            typer.echo(
                _render_unified_diff(
                    content1, content2, version1, version2, color=color
                )
            )

        # Anyone who hand-rolls a CI step and forgets --exit-code would
        # otherwise get a silently green build on a breaking change. Say so
        # at the moment it matters, in the output they are already reading.
        if not exit_code and report.impact >= SemverImpact.MINOR:
            typer.echo("")
            typer.echo(
                f"note: exiting 0, pass --exit-code to make this "
                f"{report.impact.value} fail CI"
            )

    if exit_code:
        raise typer.Exit(_IMPACT_EXIT_CODES[report.impact])


def load_json_test_cases(json_file: str):
    """
    Load test cases from a JSON file.
    Expected JSON format is a list of objects,
    each with "input" and "expected_output" keys.
    """
    if not os.path.exists(json_file):
        typer.echo(f"Error: Test dataset file '{json_file}' not found.")
        raise typer.Exit(code=1)
    try:
        with open(json_file, "r") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        typer.echo(f"Error parsing JSON file '{json_file}': {e}")
        raise typer.Exit(code=1)
    if not isinstance(data, list):
        typer.echo("Error: JSON test dataset should be a list of test cases.")
        raise typer.Exit(code=1)
    return data

def run_prompt_test(prompt_file: str, test_input: dict) -> str:
    """
    Load a prompt from a YAML file and render it using test_input.
    Returns the rendered prompt.
    """
    if not os.path.exists(prompt_file):
        typer.echo(f"Error: Prompt file '{prompt_file}' not found.")
        raise typer.Exit(code=1)
    try:
        with open(prompt_file, "r") as f:
            prompt_data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        typer.echo(f"Error parsing YAML file '{prompt_file}': {e}")
        raise typer.Exit(code=1)

    if not isinstance(prompt_data, dict):
        typer.echo(f"Error: Prompt file '{prompt_file}' does not contain valid YAML data.")
        raise typer.Exit(code=1)
    
    # Make sure the 'template' key exists.
    template_str = prompt_data.get("template")
    if not template_str:
        typer.echo(f"Error: No 'template' found in prompt file '{prompt_file}'.")
        raise typer.Exit(code=1)
    
    try:
        template = SandboxedEnvironment().from_string(template_str)
    except Exception as e:
        typer.echo(f"Error creating Jinja2 template from prompt: {e}")
        raise typer.Exit(code=1)
    
    try:
        rendered_output = template.render(**test_input)
    except Exception as e:
        typer.echo(f"Error rendering template with input {test_input}: {e}")
        raise typer.Exit(code=1)
    
    return rendered_output

def accuracy_match(actual: str, expected: str) -> bool:
    """
    Perform a basic string comparison for matching.
    """
    return actual.strip() == expected.strip()

if __name__ == "__main__":
    app()
