#!/usr/bin/env python3
"""
PromptOps post-commit hook for automation.

This hook:
1. Creates git tags for new prompt versions
2. Generates markdown reports
3. Runs comprehensive test suites
4. Updates logs and analytics
"""

import os
import sys
import subprocess
import json
import yaml
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from llmhq_promptops.core.git_versioning import GitVersioning
from llmhq_promptops.core.template import PromptTemplate
from llmhq_promptops.prompt_manager import PromptManager


# Stand-in values used to exercise the render path. The point is to reach the
# renderer at all, not to produce meaningful text, so anything type-plausible
# will do.
_PLACEHOLDERS = {
    "string": "example",
    "str": "example",
    "text": "example",
    "number": 1,
    "integer": 1,
    "int": 1,
    "float": 1.0,
    "boolean": True,
    "bool": True,
    "list": [],
    "array": [],
    "dict": {},
    "object": {},
}


class PostCommitHook:
    """PromptOps post-commit hook handler."""
    
    def __init__(self, repo_path: str = "."):
        """Initialize the post-commit hook."""
        self.repo_path = Path(repo_path).resolve()
        self.promptops_dir = self.repo_path / ".promptops"
        self.git_versioning = GitVersioning(repo_path)
        
        # Load configuration
        self.config = self._load_config()
        self.verbose = self.config.get("verbose", False)
        self.auto_tag = self.config.get("auto_tag_versions", True)
        self.run_tests = self.config.get("post_commit_tests", True)
        # Off by default: writing files into someone's repository after every
        # commit is opt-in behavior, not a sensible default.
        self.generate_reports = self.config.get("generate_reports", False)
    
    def run(self) -> int:
        """Run the post-commit hook.
        
        Returns:
            0 if successful, non-zero if there were issues
        """
        self._log("🚀 PromptOps post-commit hook starting...")
        
        try:
            # Get prompt files changed in this commit
            changed_prompt_files = self._get_changed_prompt_files()
            
            if not changed_prompt_files:
                self._log("ℹ️  No prompt files changed, skipping post-commit actions")
                return 0
            
            self._log(f"📝 Processing {len(changed_prompt_files)} changed prompt files")
            
            # Create git tags for new versions
            if self.auto_tag:
                self._create_version_tags(changed_prompt_files)
            
            # Generate markdown reports
            if self.generate_reports:
                self._generate_and_store_reports(changed_prompt_files)
            
            # Run tests if enabled
            if self.run_tests:
                self._run_post_commit_tests(changed_prompt_files)
            
            self._log("✅ Post-commit hook completed successfully")
            return 0
            
        except Exception as e:
            self._log(f"💥 Post-commit hook failed: {e}")
            if self.verbose:
                import traceback
                self._log(traceback.format_exc())
            return 1
    
    def _get_changed_prompt_files(self) -> List[str]:
        """Get list of prompt files changed in the current commit."""
        try:
            # Get files changed in HEAD commit.
            #
            # "--root" is what makes this work on the *first* commit in a
            # repository. A root commit has no parent, so without it git
            # prints nothing and exits 0, and that silence read as "no prompt
            # files changed" and skipped versioning altogether. The first
            # commit of a new repo is exactly the path a first-time user
            # takes. On any other commit the flag is a no-op.
            result = subprocess.run(
                ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", "HEAD"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            
            # Filter for prompt files
            all_changed = result.stdout.strip().split('\n') if result.stdout.strip() else []
            prompt_files = [
                f for f in all_changed
                if f.startswith('.promptops/prompts/') and f.endswith('.yaml')
                and not Path(f).name.startswith('-')
            ]
            
            return prompt_files
            
        except subprocess.CalledProcessError as e:
            self._log(f"Failed to get changed files: {e}")
            return []
    
    def _create_version_tags(self, prompt_files: List[str]):
        """Create git tags for new prompt versions."""
        try:
            for prompt_file in prompt_files:
                prompt_id = Path(prompt_file).stem
                version = self._get_prompt_version(prompt_file)
                
                if version:
                    # "prompt-<id>-v1.2.3" is the one per-prompt format the
                    # SDK reads (GitVersioning._get_tag_version), and the one
                    # `promptops migrate tag-history` writes. The hook used to
                    # emit "<id>-v1.2.3", which matches neither, so every tag
                    # auto-versioning ever created was invisible to history,
                    # blame, and version resolution.
                    tag_name = f"prompt-{prompt_id}-{version}"
                    
                    # Check if tag already exists ('--' so a crafted
                    # tag_name can't inject a git option; the write path
                    # below already uses it)
                    tag_exists = subprocess.run(
                        ["git", "tag", "-l", "--", tag_name],
                        capture_output=True,
                        text=True
                    ).stdout.strip()
                    
                    if not tag_exists:
                        subprocess.run(
                            ["git", "tag", "-m", f"Version {version} of {prompt_id}", "--", tag_name],
                            cwd=self.repo_path,
                            check=True
                        )
                        self._log(f"🏷️  Created tag: {tag_name}")
                    else:
                        self._log(f"ℹ️  Tag {tag_name} already exists")
                        
        except subprocess.CalledProcessError as e:
            self._log(f"Failed to create tags: {e}")
    
    def _generate_and_store_reports(self, prompt_files: List[str]):
        """Generate markdown reports and store them in git."""
        try:
            # Create reports directory structure
            reports_dir = self.promptops_dir / "reports"
            reports_dir.mkdir(exist_ok=True)
            
            # Create monthly subdirectory
            current_month = datetime.now().strftime("%Y-%m")
            month_dir = reports_dir / current_month
            month_dir.mkdir(exist_ok=True)
            
            # Generate version change report
            commit_hash = self._get_current_commit_hash()
            report_file = month_dir / f"commit-{commit_hash[:7]}-version-changes.md"
            
            report_content = self._generate_version_report(prompt_files, commit_hash)
            report_file.write_text(report_content)
            
            # Update index file
            self._update_reports_index(reports_dir, report_file, prompt_files)

            # Deliberately NOT `git add`-ed. Staging files the user never
            # touched meant their *next* commit silently carried report files
            # they had not asked for. What to do with these is their call.
            self._log(f"📊 Generated report: {report_file.relative_to(self.repo_path)}")
            
        except Exception as e:
            self._log(f"Failed to generate reports: {e}")
    
    def _generate_version_report(self, prompt_files: List[str], commit_hash: str) -> str:
        """Generate markdown report for version changes."""
        report_lines = [
            "# Prompt Version Report",
            f"Generated: {datetime.now().isoformat()}",
            f"Commit: {commit_hash}",
            "",
            "## Changed Prompts",
            ""
        ]
        
        for prompt_file in prompt_files:
            prompt_id = Path(prompt_file).stem
            current_version = self._get_prompt_version(prompt_file)
            change_type = self._detect_change_type(prompt_file)
            
            report_lines.extend([
                f"### {prompt_id}",
                f"- **Current Version:** {current_version}",
                f"- **Change Type:** {change_type}",
                f"- **File:** `{prompt_file}`",
                f"- **Commit:** {commit_hash}",
                ""
            ])
        
        # Add git diff summary
        report_lines.extend([
            "## Changes Summary",
            "```diff"
        ])
        
        try:
            diff_result = subprocess.run(
                ["git", "show", "--stat", commit_hash],
                capture_output=True,
                text=True,
                cwd=self.repo_path
            )
            report_lines.append(diff_result.stdout)
        except subprocess.CalledProcessError:
            report_lines.append("Could not generate diff summary")
        
        report_lines.append("```")
        
        return "\n".join(report_lines)
    
    def _update_reports_index(self, reports_dir: Path, new_report: Path, prompt_files: List[str]):
        """Update the reports index file."""
        index_file = reports_dir / "index.md"
        
        # Read existing index or create new
        if index_file.exists():
            content = index_file.read_text()
        else:
            content = "# PromptOps Reports Index\n\nGenerated reports for prompt version changes:\n\n"
        
        # Add new entry
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        prompt_list = ", ".join([Path(f).stem for f in prompt_files])
        relative_path = new_report.relative_to(reports_dir)
        
        new_entry = f"- [{timestamp}]({relative_path}) - {prompt_list}\n"
        
        # Insert at the beginning of the list (after header)
        lines = content.split('\n')
        header_end = next((i for i, line in enumerate(lines) if line.startswith('- ')), len(lines))
        lines.insert(header_end, new_entry.strip())
        
        index_file.write_text('\n'.join(lines))
    
    def _get_prompt_version(self, prompt_file: str) -> Optional[str]:
        """Get version from prompt file."""
        try:
            full_path = self.repo_path / prompt_file
            if not full_path.exists():
                return None
                
            data = yaml.safe_load(full_path.read_text())

            # None for an empty or comment-only file; "metadata" in None
            # raises TypeError, which the bare except below would turn into a
            # silent None rather than surfacing the real problem.
            if not isinstance(data, dict):
                return None

            # Try new format first
            if "metadata" in data and "version" in data["metadata"]:
                return data["metadata"]["version"]
            
            # Try legacy format
            if "prompt" in data and "version" in data["prompt"]:
                return data["prompt"]["version"]
            
            return None
            
        except Exception:
            return None
    
    def _detect_change_type(self, prompt_file: str) -> str:
        """Detect the type of change made to the prompt."""
        try:
            # A prompt removed in this commit has no file left to read. Say so
            # rather than letting the read below raise FileNotFoundError into
            # the handler at the bottom, which reported "UNKNOWN" and lost the
            # one fact worth reporting.
            if not (self.repo_path / prompt_file).exists():
                return "DELETED"

            # Get previous version of file
            prev_content = subprocess.run(
                # No "--": "HEAD~1:path" is a revision, and behind a "--" git
                # reads it as a pathspec and exits 0 with empty output. That
                # silence is why this returned "UNKNOWN" for every change.
                ["git", "show", f"HEAD~1:{prompt_file}"],
                capture_output=True,
                text=True,
                cwd=self.repo_path
            )
            
            if prev_content.returncode != 0:
                return "NEW"
            
            # Simple change detection
            current_content = (self.repo_path / prompt_file).read_text()
            
            try:
                prev_data = yaml.safe_load(prev_content.stdout)
                curr_data = yaml.safe_load(current_content)

                # An unparseable or empty previous revision means there is
                # nothing to compare against, which is what "NEW" means.
                # Calling .get() on None here raised AttributeError and the
                # outer handler reported "UNKNOWN" instead.
                if not isinstance(prev_data, dict):
                    return "NEW"
                if not isinstance(curr_data, dict):
                    return "PATCH"

                # Check for variable changes
                prev_vars = prev_data.get('variables', {})
                curr_vars = curr_data.get('variables', {})
                
                if set(prev_vars.keys()) != set(curr_vars.keys()):
                    return "MINOR" if len(curr_vars) > len(prev_vars) else "MAJOR"
                
                # Check template changes
                if prev_data.get('template') != curr_data.get('template'):
                    return "PATCH"
                
                return "PATCH"
                
            except yaml.YAMLError:
                return "PATCH"
                
        except Exception:
            return "UNKNOWN"
    
    def _get_current_commit_hash(self) -> str:
        """Get current commit hash."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
                cwd=self.repo_path
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return "unknown"
    
    def _validate_prompt(self, prompt_file: str) -> Tuple[bool, str]:
        """Is this prompt usable? Returns (ok, detail).

        Deliberately **not** ``render({})``. That is what this check used to
        do, and rendering with no variables fails by construction for any
        prompt declaring a required one:

            PROMPTOPS_E014: Required variable 'name' not provided

        Since ``post_commit_tests`` defaults to on, every user saw that red
        mark on every commit. A check that cannot pass teaches people to
        ignore everything the tool prints, which is worse than no check.

        What it was reaching for is three things that can genuinely be wrong:
        the YAML parses into a prompt, the Jinja source compiles (the
        ``.template`` property is what triggers that; constructing a
        ``PromptTemplate`` alone does not), and the template renders when
        given values for the variables it declares.
        """
        try:
            full_path = self.repo_path / prompt_file
            template = PromptTemplate(full_path.read_text())
            template.template  # compiles the Jinja source; raises on bad syntax
            template.render(self._sample_variables(template))
            return True, ""
        except Exception as e:
            return False, str(e)

    @staticmethod
    def _sample_variables(template: PromptTemplate) -> Dict[str, Any]:
        """A plausible value for every declared variable."""
        sample: Dict[str, Any] = {}
        for name, var in template.variables.items():
            if var.default is not None:
                sample[name] = var.default
            else:
                sample[name] = _PLACEHOLDERS.get(str(var.type).lower(), "example")
        return sample

    def _run_post_commit_tests(self, prompt_files: List[str]):
        """Validate each changed prompt after the commit."""
        try:
            self._log("🧪 Running post-commit tests...")

            for prompt_file in prompt_files:
                prompt_id = Path(prompt_file).stem
                if not (self.repo_path / prompt_file).exists():
                    # Removed in this commit; nothing left to validate.
                    continue
                ok, detail = self._validate_prompt(prompt_file)
                if ok:
                    self._log(f"✅ {prompt_id}: Post-commit validation passed")
                else:
                    self._log(f"❌ {prompt_id}: Post-commit test failed - {detail}")

        except Exception as e:
            self._log(f"Post-commit tests failed: {e}")
    
    def _load_config(self) -> Dict:
        """Load PromptOps configuration."""
        config_file = self.promptops_dir / "config.yaml"
        
        if config_file.exists():
            try:
                with open(config_file) as f:
                    return yaml.safe_load(f) or {}
            except Exception:
                pass
        
        # Default configuration
        return {
            "verbose": False,
            "auto_tag_versions": True,
            "post_commit_tests": True,
            "generate_reports": False
        }
    
    def _log(self, message: str):
        """Log message to stderr."""
        print(f"[promptops] {message}", file=sys.stderr)


def main():
    """Entry point for post-commit hook."""
    hook = PostCommitHook()
    exit_code = hook.run()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()