import os
import json
import time
import datetime
import yaml
import typer
import sys
from pathlib import Path
from jinja2 import Template
from typing import List, Optional
from io import StringIO

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from llmhq_promptops import get_prompt, PromptManager

app = typer.Typer()

@app.command()
def status():
    """
    Show status of all prompts and their versions.
    
    Displays which prompts have uncommitted changes, current versions,
    and helpful guidance on which version references to use.
    """
    try:
        manager = PromptManager()
        
        # Get all prompt files
        prompts_dir = Path(".promptops/prompts")
        if not prompts_dir.exists():
            typer.echo("❌ No .promptops/prompts directory found. Run 'promptops init repo' first.", err=True)
            raise typer.Exit(1)
        
        prompt_files = list(prompts_dir.glob("*.yaml"))
        
        if not prompt_files:
            typer.echo("ℹ️  No prompt files found in .promptops/prompts/")
            return
        
        typer.echo("🔍 PromptOps Status Overview:")
        typer.echo("=" * 50)
        
        for prompt_file in sorted(prompt_files):
            prompt_id = prompt_file.stem
            _show_prompt_status(manager, prompt_id)
        
        typer.echo("\n💡 Usage Tips:")
        typer.echo("   • Use :unstaged to test uncommitted changes")
        typer.echo("   • Use :working for latest committed version")
        typer.echo("   • Use :v1.2.3 for specific versions")
        typer.echo("   • No version suffix uses smart default")
        
    except Exception as e:
        typer.echo(f"❌ Failed to get status: {e}", err=True)
        raise typer.Exit(1)


def _show_prompt_status(manager: PromptManager, prompt_id: str):
    """Show status for a single prompt."""
    try:
        # Check if there are uncommitted changes
        has_changes = manager.has_uncommitted_changes(prompt_id)
        
        # Get current version from working directory
        try:
            working_version = manager._get_template_cached(f"{prompt_id}:working").metadata.get('version', 'unknown')
        except:
            working_version = 'unknown'
        
        # Get unstaged version if different
        unstaged_version = None
        if has_changes:
            try:
                unstaged_version = manager._get_template_cached(f"{prompt_id}:unstaged").metadata.get('version', 'unknown')
            except:
                unstaged_version = 'unknown'
        
        # Display status
        if has_changes:
            if unstaged_version and unstaged_version != working_version:
                typer.echo(f"📝 {prompt_id}: 🔄 Uncommitted changes ({working_version} → {unstaged_version})")
                typer.echo(f"   💡 Test with: --prompt {prompt_id}:unstaged")
            else:
                typer.echo(f"📝 {prompt_id}: 🔄 Uncommitted changes (content modified)")
                typer.echo(f"   💡 Test with: --prompt {prompt_id}:unstaged")
        else:
            typer.echo(f"📝 {prompt_id}: ✅ Up to date (v{working_version})")
            typer.echo(f"   💡 Test with: --prompt {prompt_id}:working")
        
        # Show available tags
        _show_available_versions(prompt_id)
        
    except Exception as e:
        typer.echo(f"📝 {prompt_id}: ⚠️  Error checking status - {e}")


def _show_available_versions(prompt_id: str):
    """Show available git tags for a prompt."""
    try:
        import subprocess
        result = subprocess.run(
            ["git", "tag", "-l", f"{prompt_id}-*"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0 and result.stdout.strip():
            tags = result.stdout.strip().split('\n')
            versions = [tag.replace(f"{prompt_id}-", "") for tag in tags[-3:]]  # Show last 3
            typer.echo(f"   🏷️  Recent versions: {', '.join(versions)}")
        
    except Exception:
        pass  # Silently fail for git tag lookup

# Register 'test' as a subcommand (not as a callback)
@app.command()
def diff(
    prompt_id: str = typer.Argument(..., help="Prompt ID to compare"),
    version1: str = typer.Option("working", "--version1", help="First version to compare"),
    version2: str = typer.Option("unstaged", "--version2", help="Second version to compare")
):
    """
    Compare two versions of a prompt.
    
    Shows the differences between two versions of a prompt.
    Common comparisons:
    - working vs unstaged (default): See uncommitted changes
    - v1.2.0 vs v1.3.0: Compare specific versions
    - working vs v1.2.0: See changes since a version
    """
    try:
        manager = PromptManager()
        
        typer.echo(f"🔍 Comparing {prompt_id}: {version1} vs {version2}")
        typer.echo("=" * 50)
        
        # Get both versions
        try:
            diff_result = manager.get_prompt_diff(prompt_id, version1, version2)
            
            if not diff_result.strip():
                typer.echo("✅ No differences found between versions")
            else:
                typer.echo("📊 Differences:")
                typer.echo(diff_result)
                
        except Exception as e:
            typer.echo(f"❌ Failed to generate diff: {e}", err=True)
            
    except Exception as e:
        typer.echo(f"❌ Diff failed: {e}", err=True)
        raise typer.Exit(1)


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


@app.command()
def diff(
    prompt: str = typer.Argument(..., help="Prompt name"),
    version1: str = typer.Option("working", help="First version to compare"),
    version2: str = typer.Option("unstaged", help="Second version to compare")
):
    """Compare two versions of a prompt."""
    try:
        manager = PromptManager()
        
        diff_result = manager.get_prompt_diff(prompt, version1, version2)
        
        if "error" in diff_result:
            typer.echo(f"❌ {diff_result['error']}", err=True)
            raise typer.Exit(1)
        
        typer.echo(f"🔍 Comparing {prompt}: {version1} vs {version2}")
        typer.echo("=" * 60)
        
        if diff_result["identical"]:
            typer.echo("✅ Versions are identical")
        else:
            typer.echo(f"📊 Lines difference: {diff_result['lines_added']}")
            typer.echo("\n📝 Content differences:")
            typer.echo(f"\n--- {version1} ---")
            typer.echo(diff_result["content1"][:500] + "..." if len(diff_result["content1"]) > 500 else diff_result["content1"])
            typer.echo(f"\n+++ {version2} +++")
            typer.echo(diff_result["content2"][:500] + "..." if len(diff_result["content2"]) > 500 else diff_result["content2"])
        
    except Exception as e:
        typer.echo(f"❌ Diff failed: {e}", err=True)
        raise typer.Exit(1)
    
    # Load the test cases from the JSON dataset.
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
            actual_output = run_prompt_test(prompt_file, test_input)
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

    # Generate a Markdown test report
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
    report_file = os.path.join(results_dir, f"{date_str}-{prompt}-test-report.md")
    try:
        with open(report_file, "w") as f:
            f.write(report_content)
        typer.echo(f"Test report saved to {report_file}")
    except Exception as e:
        typer.echo(f"Error saving test report: {e}")
    
    typer.echo("\n" + report_content)

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
        template = Template(template_str)
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
