#!/usr/bin/env python3
"""
PromptOps pre-commit hook for automatic versioning.

This hook:
1. Detects changes to .promptops/prompts/*.yaml files
2. Analyzes changes for semantic versioning
3. Auto-updates version numbers in YAML metadata
4. Validates prompt syntax and variables
5. Optionally runs tests before commit
"""

import os
import re
import sys
import yaml
import subprocess
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from llmhq_promptops.core.version_detector import SemanticVersionDetector, ChangeType
from llmhq_promptops.core.template import PromptTemplate


# A ``version:`` entry nested under a top-level key. The trailing group keeps
# any end-of-line comment, so ``version: v1.0.0  # pinned`` stays pinned.
_VERSION_LINE_RE = re.compile(
    r"^(?P<indent>[ \t]+)version:(?P<sep>[ \t]+)"
    r"(?P<value>[^#\n]*?)(?P<trail>[ \t]*(?:#.*)?)$"
)

# A key at column zero, which is what changes "which section am I in".
_TOP_LEVEL_KEY_RE = re.compile(r"^(?P<key>[A-Za-z_][\w.-]*)[ \t]*:")

# Sections that may carry the version, in precedence order: the current schema
# first, then the legacy one.
_VERSION_SECTIONS = ("metadata", "prompt")


class PreCommitHook:
    """PromptOps pre-commit hook handler."""
    
    def __init__(self, repo_path: str = "."):
        """Initialize the pre-commit hook."""
        self.repo_path = Path(repo_path).resolve()
        self.promptops_dir = self.repo_path / ".promptops"

        # Configuration
        self.config = self._load_config()
        self.verbose = self.config.get("verbose", False)
        self.run_tests = self.config.get("pre_commit_tests", False)
        self.block_on_test_failure = self.config.get("block_on_test_failure", True)

        # ``SemanticVersionDetector`` is heavyweight (regex compilation, diff
        # tooling). Defer instantiation to the lazy ``self.detector`` property
        # so commits that don't touch prompt files (e.g. ``[deploy]`` commits
        # that only append to ``.promptops/deploys.jsonl``, or ordinary
        # source-code commits) exit fast without paying that cost. M4
        # explicitly targets this optimization to keep the deploy-event
        # commit loop snappy.
        self._detector: Optional[SemanticVersionDetector] = None

    @property
    def detector(self) -> SemanticVersionDetector:
        if self._detector is None:
            self._detector = SemanticVersionDetector()
        return self._detector

    def run(self) -> int:
        """Run the pre-commit hook.

        Returns:
            0 if successful, non-zero if commit should be blocked
        """
        # Get staged prompt files BEFORE logging or any heavy setup, so
        # the early-exit path for non-prompt commits stays silent and
        # cheap. Most commits in a real repo don't touch prompts.
        try:
            staged_prompt_files = self._get_staged_prompt_files()
        except Exception as exc:
            self._log(f"💥 Pre-commit hook failed early: {exc}")
            return 1

        if not staged_prompt_files:
            # Stay quiet on the no-op path. Verbose users still see the
            # skip line; everyone else gets a clean commit.
            if self.verbose:
                self._log("No prompt files changed, skipping.")
            return 0

        self._log("🔍 PromptOps pre-commit hook starting...")

        try:
            self._log(f"📝 Found {len(staged_prompt_files)} changed prompt files")
            
            # Process each changed file
            updated_files = []
            for prompt_file in staged_prompt_files:
                success = self._process_prompt_file(prompt_file)
                if success:
                    updated_files.append(prompt_file)
                elif self.block_on_test_failure:
                    self._log(f"❌ Failed to process {prompt_file}, blocking commit")
                    return 1
            
            # Re-stage updated files
            if updated_files:
                self._restage_files(updated_files)
                self._log(f"✅ Auto-versioned {len(updated_files)} prompt files")
            
            # Run tests if enabled
            if self.run_tests and updated_files:
                test_success = self._run_prompt_tests(updated_files)
                if not test_success and self.block_on_test_failure:
                    self._log("❌ Tests failed, blocking commit")
                    return 1
            
            self._log("🎉 Pre-commit hook completed successfully")
            return 0
            
        except Exception as e:
            self._log(f"💥 Pre-commit hook failed: {e}")
            if self.verbose:
                import traceback
                self._log(traceback.format_exc())
            return 1
    
    def _get_staged_prompt_files(self) -> List[str]:
        """Get list of staged prompt files."""
        try:
            # Get staged files. "--diff-filter=d" (lowercase, meaning
            # *exclude*) drops staged deletions: a deleted prompt has no
            # staged content, so `git show :path` fails, the working-directory
            # fallback finds nothing, and _process_prompt_file returns False,
            # which blocks the commit. Removing a prompt is ordinary work and
            # must not be blocked, and there is nothing to version anyway.
            result = subprocess.run(
                ["git", "diff", "--cached", "--name-only", "--diff-filter=d"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            
            # Filter for prompt files
            all_staged = result.stdout.strip().split('\n') if result.stdout.strip() else []
            prompt_files = [
                f for f in all_staged
                if f.startswith('.promptops/prompts/') and f.endswith('.yaml')
                and not Path(f).name.startswith('-')
            ]
            
            return prompt_files
            
        except subprocess.CalledProcessError as e:
            self._log(f"Failed to get staged files: {e}")
            return []
    
    def _process_prompt_file(self, prompt_file: str) -> bool:
        """Process a single prompt file for versioning.
        
        Args:
            prompt_file: Relative path to prompt file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            self._log(f"🔄 Processing {prompt_file}...")
            
            # Get old and new content
            old_content = self._get_committed_content(prompt_file)
            new_content = self._get_staged_content(prompt_file)
            
            if new_content is None:
                self._log(f"⚠️  Could not read staged content for {prompt_file}")
                return False
            
            # Parse current version
            current_version = self._extract_current_version(new_content)
            
            # Analyze changes
            change = self.detector.analyze_prompt_changes(
                old_content or "", 
                new_content, 
                current_version
            )
            
            # Log change analysis
            self._log(f"📊 Change analysis for {prompt_file}:")
            self._log(f"   Type: {change.change_type.value.upper()}")
            self._log(f"   Version: {change.old_version} → {change.new_version}")
            if change.reasons:
                for reason in change.reasons[:3]:  # Show first 3 reasons
                    self._log(f"   • {reason}")
            
            # Update version in file if changed
            if change.old_version != change.new_version:
                updated_content = self._update_version_in_yaml(new_content, change.new_version)
                if updated_content:
                    self._write_file(prompt_file, updated_content)
                    self._log(f"✅ Updated version to {change.new_version}")
                else:
                    self._log(f"⚠️  Failed to update version in {prompt_file}")
            else:
                self._log(f"ℹ️  No version change needed for {prompt_file}")
            
            # Validate prompt syntax
            if not self._validate_prompt_syntax(new_content):
                self._log(f"❌ Invalid prompt syntax in {prompt_file}")
                return False
            
            return True
            
        except Exception as e:
            self._log(f"Failed to process {prompt_file}: {e}")
            return False
    
    def _get_committed_content(self, file_path: str) -> Optional[str]:
        """Get file content from HEAD commit."""
        try:
            result = subprocess.run(
                # No "--" separator here. It marks everything after it as a
                # PATHSPEC, so "HEAD:path" stops being parsed as a revision
                # and git exits 0 with empty output. The revision itself is
                # not attacker-controlled: file_path comes from
                # `git diff --cached --name-only`, i.e. from git.
                ["git", "show", f"HEAD:{file_path}"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout
        except subprocess.CalledProcessError:
            # File doesn't exist in HEAD (new file)
            return None

    def _get_staged_content(self, file_path: str) -> Optional[str]:
        """Get file content from git index (staged)."""
        try:
            result = subprocess.run(
                # See the note above: ":path" is a revision (the index), not
                # a pathspec, so it must not sit behind a "--".
                ["git", "show", f":{file_path}"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout
        except subprocess.CalledProcessError:
            # Fallback to working directory
            full_path = self.repo_path / file_path
            if full_path.exists():
                return full_path.read_text()
            return None
    
    def _extract_current_version(self, content: str) -> str:
        """Extract current version from YAML content."""
        try:
            data = yaml.safe_load(content)

            # yaml.safe_load returns None for empty or comment-only input, and
            # a scalar for a bare value. "metadata" in None raises TypeError,
            # which `except yaml.YAMLError` below does not catch, so it
            # escaped to the caller and blocked the commit.
            if not isinstance(data, dict):
                return "v1.0.0"

            # Try new format first
            if "metadata" in data and "version" in data["metadata"]:
                return data["metadata"]["version"]
            
            # Try legacy format
            if "prompt" in data and "version" in data["prompt"]:
                return data["prompt"]["version"]
            
            # Default version
            return "v1.0.0"
            
        except yaml.YAMLError:
            return "v1.0.0"
    
    def _update_version_in_yaml(self, content: str, new_version: str) -> Optional[str]:
        """Rewrite the version field, and nothing else.

        This used to round-trip the document through ``yaml.safe_load`` and
        ``yaml.dump`` to change one field. That silently deleted every comment
        in the file and reserialized ``template: |`` block scalars into quoted
        strings, on every commit, to every prompt. The comment naming a
        prompt's owner is frequently the most valuable line in it, and a tool
        that deletes it while claiming to bump a version number has not earned
        the right to run on someone's commits.

        So the edit is textual and targeted: find the version *line*, replace
        its value, leave every other byte alone. When the file's shape makes
        that impossible (a flow mapping, say), return None so the caller warns
        and leaves the file untouched. Refusing is the correct failure mode;
        falling back to a reserialization would be the original bug wearing a
        disguise.
        """
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            self._log(f"Failed to parse YAML: {e}")
            return None

        if not isinstance(data, dict):
            self._log("Prompt is not a YAML mapping, leaving it untouched")
            return None

        lines = content.splitlines()
        updated = self._rewrite_version_line(lines, new_version)

        if updated is None:
            if self._declares_a_version(data):
                # It has a version, but not as a line we can safely edit.
                self._log(
                    "Could not locate an editable version line, "
                    "leaving the file untouched"
                )
                return None
            updated = self._insert_version_line(lines, new_version)

        if updated is None:
            return None

        # Preserve the original trailing newline, since rewriting a file
        # without one is its own small act of vandalism.
        result = "\n".join(updated)
        if content.endswith("\n"):
            result += "\n"

        # The edit must both parse and mean what was intended. Reusing the
        # reader as the check keeps the two definitions of "the version" from
        # drifting apart.
        if self._extract_current_version(result) != new_version:
            self._log("Version rewrite did not take effect, leaving the file untouched")
            return None

        return result

    @staticmethod
    def _declares_a_version(data: Dict) -> bool:
        """Does this document already carry a version anywhere we look for one?"""
        for section in _VERSION_SECTIONS:
            block = data.get(section)
            if isinstance(block, dict) and "version" in block:
                return True
        return False

    @staticmethod
    def _rewrite_version_line(
        lines: List[str], new_version: str
    ) -> Optional[List[str]]:
        """Replace the value on an existing version line, preserving comments."""
        for wanted in _VERSION_SECTIONS:
            section = None
            for index, line in enumerate(lines):
                top_level = _TOP_LEVEL_KEY_RE.match(line)
                if top_level:
                    section = top_level.group("key")
                    continue
                if section != wanted:
                    continue
                match = _VERSION_LINE_RE.match(line)
                if match:
                    out = list(lines)
                    out[index] = (
                        f"{match.group('indent')}version:"
                        f"{match.group('sep')}{new_version}"
                        f"{match.group('trail')}"
                    )
                    return out
        return None

    @staticmethod
    def _insert_version_line(
        lines: List[str], new_version: str
    ) -> Optional[List[str]]:
        """Add a version to a prompt that has none, without moving anything."""
        for wanted in _VERSION_SECTIONS:
            for index, line in enumerate(lines):
                top_level = _TOP_LEVEL_KEY_RE.match(line)
                if not top_level or top_level.group("key") != wanted:
                    continue
                # Match the indentation the section already uses, so the
                # insert is invisible in review apart from the new line.
                indent = "  "
                for following in lines[index + 1:]:
                    if not following.strip():
                        continue
                    leading = following[: len(following) - len(following.lstrip())]
                    if leading:
                        indent = leading
                    break
                out = list(lines)
                out.insert(index + 1, f"{indent}version: {new_version}")
                return out

        # No section to put it in: append one rather than reordering the file.
        return list(lines) + ["metadata:", f"  version: {new_version}"]
    
    def _write_file(self, file_path: str, content: str):
        """Write content to file atomically."""
        import tempfile
        full_path = self.repo_path / file_path
        # Write to temp file then atomically replace
        fd, tmp_path = tempfile.mkstemp(
            dir=full_path.parent, suffix='.tmp', prefix='.promptops_'
        )
        try:
            with os.fdopen(fd, 'w') as tmp_f:
                tmp_f.write(content)
                tmp_f.flush()
                os.fsync(tmp_f.fileno())
            os.replace(tmp_path, full_path)
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    
    def _validate_prompt_syntax(self, content: str) -> bool:
        """Validate prompt YAML syntax and structure.

        Constructing a ``PromptTemplate`` parses the YAML but does *not*
        compile the Jinja source: ``PromptTemplate.template`` is a lazy
        property. So this method claimed to validate syntax while letting an
        unclosed ``{% if %}`` straight through to production, where it fails
        at render time. Touching the property compiles it, which is the whole
        point of a pre-commit check on a guaranteed-broken template.
        """
        try:
            # Basic YAML validation
            data = yaml.safe_load(content)

            # Try to create PromptTemplate (this validates structure)
            template = PromptTemplate(content)

            # Compile the Jinja source. Syntax errors raise here.
            template.template

            return True

        except Exception as e:
            self._log(f"Validation failed: {e}")
            return False
    
    def _restage_files(self, files: List[str]):
        """Re-stage files after modification."""
        try:
            subprocess.run(
                ["git", "add"] + files,
                cwd=self.repo_path,
                check=True
            )
        except subprocess.CalledProcessError as e:
            self._log(f"Failed to re-stage files: {e}")
    
    def _run_prompt_tests(self, prompt_files: List[str]) -> bool:
        """Run tests for changed prompts."""
        try:
            self._log("🧪 Running prompt tests...")
            
            # Extract prompt IDs from file paths
            prompt_ids = []
            for file_path in prompt_files:
                # .promptops/prompts/user-onboarding.yaml -> user-onboarding
                file_name = Path(file_path).stem
                prompt_ids.append(file_name)
            
            # Run basic validation tests
            all_passed = True
            for prompt_id in prompt_ids:
                try:
                    # Basic template rendering test
                    template = PromptTemplate(
                        (self.repo_path / f".promptops/prompts/{prompt_id}.yaml").read_text()
                    )
                    
                    # Try rendering with empty variables
                    template.render({})
                    self._log(f"✅ {prompt_id}: Basic validation passed")
                    
                except Exception as e:
                    self._log(f"❌ {prompt_id}: Test failed - {e}")
                    all_passed = False
            
            return all_passed
            
        except Exception as e:
            self._log(f"Test execution failed: {e}")
            return False
    
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
            "pre_commit_tests": False,
            "block_on_test_failure": True
        }
    
    def _log(self, message: str):
        """Log message to stderr."""
        print(f"[promptops] {message}", file=sys.stderr)


def main():
    """Entry point for pre-commit hook."""
    hook = PreCommitHook()
    exit_code = hook.run()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()