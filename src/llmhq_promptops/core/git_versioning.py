import os
import re
from typing import Optional, List, Dict, Tuple
from pathlib import Path
from git import Repo, InvalidGitRepositoryError
from datetime import datetime


class GitVersioning:
    """Handles git-based versioning for prompt files."""
    
    def __init__(self, repo_path: str = "."):
        """Initialize GitVersioning with repository path."""
        self.repo_path = Path(repo_path).resolve()
        self.promptops_dir = self.repo_path / ".promptops"
        self._repo = None
        self._version_cache = {}
    
    @property
    def repo(self) -> Repo:
        """Get git repository instance."""
        if self._repo is None:
            try:
                self._repo = Repo(self.repo_path)
            except InvalidGitRepositoryError:
                raise ValueError(f"Not a git repository: {self.repo_path}")
        return self._repo
    
    def get_prompt_versions(self, prompt_id: str) -> List[Dict]:
        """Get all versions of a prompt from git history."""
        prompt_file = f".promptops/prompts/{prompt_id}.yaml"
        
        # Check cache first
        cache_key = f"{prompt_id}:{self.repo.head.commit.hexsha[:8]}"
        if cache_key in self._version_cache:
            return self._version_cache[cache_key]
        
        versions = []
        
        try:
            # Get commits that modified this file
            commits = list(self.repo.iter_commits(paths=prompt_file))
            
            for i, commit in enumerate(commits):
                # Generate version number
                version = self._generate_version(commit, i, len(commits))
                
                versions.append({
                    "version": version,
                    "commit": commit.hexsha,
                    "commit_short": commit.hexsha[:8],
                    "author": str(commit.author),
                    "date": datetime.fromtimestamp(commit.committed_date),
                    "message": commit.message.strip(),
                    "is_latest": i == 0
                })
            
            # Cache the result
            self._version_cache[cache_key] = versions
            
        except Exception as e:
            # If file doesn't exist in git history, return empty list
            versions = []
        
        return versions
    
    def get_prompt_at_version(self, prompt_id: str, version: Optional[str] = None) -> Optional[str]:
        """Get prompt file content at specific version."""
        prompt_file = f".promptops/prompts/{prompt_id}.yaml"
        
        # Handle special version references
        if version is None:
            # Smart default: unstaged if exists and different, else working (latest commit)
            return self._get_smart_default_version(prompt_id)
        elif version in ["unstaged", "working-dir"]:
            # Return current working directory version (uncommitted changes)
            return self._get_unstaged_prompt(prompt_id)
        elif version == "staged":
            # Return staged version (git index)
            return self._get_staged_prompt(prompt_id)
        elif version in ["working", "latest", "head"]:
            # Return latest committed version (HEAD)
            return self._get_latest_commit_prompt(prompt_id)
        
        # Handle specific version tags (v1.2.3 format)
        commit_sha = self._resolve_version_to_commit(prompt_id, version)
        if not commit_sha:
            return None
        
        try:
            # Get file content at specific commit
            commit = self.repo.commit(commit_sha)
            return commit.tree[prompt_file].data_stream.read().decode('utf-8')
        except (KeyError, Exception):
            return None
    
    def _resolve_version_to_commit(self, prompt_id: str, version: str) -> Optional[str]:
        """Resolve version string to git commit hash."""
        versions = self.get_prompt_versions(prompt_id)
        
        for v in versions:
            if v["version"] == version or v["commit_short"] == version:
                return v["commit"]
        
        return None
    
    def _generate_version(self, commit, index: int, total: int) -> str:
        """Generate semantic version number for a commit."""
        # Try to extract version from commit message or tags
        tag_version = self._get_tag_version(commit)
        if tag_version:
            return tag_version
        
        # Auto-generate semantic version based on position
        # Latest commit gets highest version
        major = 1 + (total - index - 1) // 100  # Increment major every 100 commits
        minor = ((total - index - 1) % 100) // 10  # Increment minor every 10 commits  
        patch = (total - index - 1) % 10  # Increment patch every commit
        
        return f"v{major}.{minor}.{patch}"
    
    def _get_tag_version(self, commit) -> Optional[str]:
        """Try to get version from git tags."""
        try:
            # Check if commit has a version tag
            for tag in self.repo.tags:
                if tag.commit == commit:
                    # Extract version from tag name
                    match = re.match(r'v?(\d+\.\d+\.\d+)', tag.name)
                    if match:
                        return f"v{match.group(1)}"
        except Exception:
            pass
        
        return None
    
    def list_available_prompts(self) -> List[str]:
        """List all available prompt IDs in the repository."""
        prompts_dir = self.promptops_dir / "prompts"
        if not prompts_dir.exists():
            return []
        
        prompt_files = prompts_dir.glob("*.yaml")
        return [f.stem for f in prompt_files if f.is_file()]
    
    def get_latest_version(self, prompt_id: str) -> Optional[str]:
        """Get the latest version of a prompt."""
        versions = self.get_prompt_versions(prompt_id)
        if versions:
            return versions[0]["version"]
        return None
    
    def is_git_repo(self) -> bool:
        """Check if current directory is a git repository."""
        try:
            self.repo
            return True
        except ValueError:
            return False
    
    def _get_unstaged_prompt(self, prompt_id: str) -> Optional[str]:
        """Get prompt content from working directory (uncommitted changes)."""
        prompt_file = f".promptops/prompts/{prompt_id}.yaml"
        file_path = self.repo_path / prompt_file
        
        if file_path.exists():
            return file_path.read_text()
        return None
    
    def _get_staged_prompt(self, prompt_id: str) -> Optional[str]:
        """Get prompt content from git index (staged changes)."""
        prompt_file = f".promptops/prompts/{prompt_id}.yaml"
        
        try:
            # Get content from git index
            staged_content = self.repo.git.show(f":{prompt_file}")
            return staged_content
        except Exception:
            # File not in index, fallback to working directory
            return self._get_unstaged_prompt(prompt_id)
    
    def _get_latest_commit_prompt(self, prompt_id: str) -> Optional[str]:
        """Get prompt content from latest commit (HEAD)."""
        prompt_file = f".promptops/prompts/{prompt_id}.yaml"
        
        try:
            # Get content from HEAD commit
            head_content = self.repo.git.show(f"HEAD:{prompt_file}")
            return head_content
        except Exception:
            # File doesn't exist in HEAD, return None
            return None
    
    def _get_smart_default_version(self, prompt_id: str) -> Optional[str]:
        """Smart default: unstaged if different from committed, else latest commit."""
        unstaged_content = self._get_unstaged_prompt(prompt_id)
        latest_content = self._get_latest_commit_prompt(prompt_id)
        
        # If no working directory file, use latest commit
        if unstaged_content is None:
            return latest_content
        
        # If no committed version, use working directory
        if latest_content is None:
            return unstaged_content
        
        # If files are different, prefer working directory (developer is editing)
        if unstaged_content.strip() != latest_content.strip():
            return unstaged_content
        
        # Files are same, use committed version for consistency
        return latest_content
    
    def has_uncommitted_changes(self, prompt_id: str) -> bool:
        """Check if prompt has uncommitted changes."""
        unstaged_content = self._get_unstaged_prompt(prompt_id)
        latest_content = self._get_latest_commit_prompt(prompt_id)
        
        if unstaged_content is None and latest_content is None:
            return False
        
        if unstaged_content is None or latest_content is None:
            return True
        
        return unstaged_content.strip() != latest_content.strip()
    
    def get_file_status(self, prompt_id: str) -> Dict[str, bool]:
        """Get detailed file status information."""
        prompt_file = f".promptops/prompts/{prompt_id}.yaml"
        
        status = {
            "exists_working": False,
            "exists_staged": False, 
            "exists_committed": False,
            "has_uncommitted_changes": False,
            "has_staged_changes": False
        }
        
        # Check working directory
        file_path = self.repo_path / prompt_file
        status["exists_working"] = file_path.exists()
        
        # Check if file is staged
        try:
            self.repo.git.show(f":{prompt_file}")
            status["exists_staged"] = True
        except Exception:
            status["exists_staged"] = False
        
        # Check if file exists in HEAD
        try:
            self.repo.git.show(f"HEAD:{prompt_file}")
            status["exists_committed"] = True
        except Exception:
            status["exists_committed"] = False
        
        # Check for changes
        status["has_uncommitted_changes"] = self.has_uncommitted_changes(prompt_id)
        
        # Check for staged changes
        if status["exists_staged"] and status["exists_committed"]:
            try:
                staged_content = self.repo.git.show(f":{prompt_file}")
                committed_content = self.repo.git.show(f"HEAD:{prompt_file}")
                status["has_staged_changes"] = staged_content.strip() != committed_content.strip()
            except Exception:
                status["has_staged_changes"] = False
        elif status["exists_staged"] and not status["exists_committed"]:
            status["has_staged_changes"] = True
        
        return status