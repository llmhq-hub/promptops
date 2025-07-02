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
import sys
import yaml
import subprocess
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from llmhq_promptops.core.version_detector import SemanticVersionDetector, ChangeType
from llmhq_promptops.core.template import PromptTemplate


class PreCommitHook:
    """PromptOps pre-commit hook handler."""
    
    def __init__(self, repo_path: str = "."):
        """Initialize the pre-commit hook."""
        self.repo_path = Path(repo_path).resolve()
        self.detector = SemanticVersionDetector()
        self.promptops_dir = self.repo_path / ".promptops"
        
        # Configuration
        self.config = self._load_config()
        self.verbose = self.config.get("verbose", False)
        self.run_tests = self.config.get("pre_commit_tests", False)
        self.block_on_test_failure = self.config.get("block_on_test_failure", True)
    
    def run(self) -> int:
        """Run the pre-commit hook.
        
        Returns:
            0 if successful, non-zero if commit should be blocked
        """
        self._log("🔍 PromptOps pre-commit hook starting...")
        
        try:
            # Get staged prompt files
            staged_prompt_files = self._get_staged_prompt_files()
            
            if not staged_prompt_files:
                self._log("✅ No prompt files changed, skipping.")
                return 0
            
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
            # Get staged files
            result = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
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
        """Update version in YAML content."""
        try:
            data = yaml.safe_load(content)
            
            # Update version in metadata (preferred)
            if "metadata" in data:
                data["metadata"]["version"] = new_version
            elif "prompt" in data:
                # Legacy format
                data["prompt"]["version"] = new_version
            else:
                # Add metadata section
                data["metadata"] = data.get("metadata", {})
                data["metadata"]["version"] = new_version
            
            # Convert back to YAML with formatting
            return yaml.dump(data, default_flow_style=False, sort_keys=False, indent=2)
            
        except yaml.YAMLError as e:
            self._log(f"Failed to update YAML: {e}")
            return None
    
    def _write_file(self, file_path: str, content: str):
        """Write content to file."""
        full_path = self.repo_path / file_path
        full_path.write_text(content)
    
    def _validate_prompt_syntax(self, content: str) -> bool:
        """Validate prompt YAML syntax and structure."""
        try:
            # Basic YAML validation
            data = yaml.safe_load(content)
            
            # Try to create PromptTemplate (this validates structure)
            template = PromptTemplate(content)
            
            # Basic validation passed
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