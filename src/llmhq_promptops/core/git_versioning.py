import logging
import os
import re
from typing import Optional, List, Dict, Tuple
from pathlib import Path
from git import Repo, InvalidGitRepositoryError
from datetime import datetime

from .validation import validate_prompt_id, check_file_size


logger = logging.getLogger(__name__)


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
        validate_prompt_id(prompt_id)
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
                # Generate version number (prompt-aware: per-prompt tags take priority over global)
                version = self._generate_version(commit, i, len(commits), prompt_id=prompt_id)
                
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
            # An empty list is the correct answer for a prompt with no commits
            # yet (a newly created, uncommitted prompt), and callers such as
            # get_latest_version and list_prompt_statuses depend on that. But a
            # genuine git failure must not be indistinguishable from "no
            # history": log it so it is diagnosable rather than silent.
            logger.warning(
                "Could not read git history for prompt '%s': %s: %s",
                prompt_id,
                type(e).__name__,
                e,
            )
            versions = []

        return versions
    
    def get_prompt_at_version(self, prompt_id: str, version: Optional[str] = None) -> Optional[str]:
        """Get prompt file content at specific version."""
        validate_prompt_id(prompt_id)
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
        commit_sha = self.commit_for_version(prompt_id, version)
        if not commit_sha:
            return None
        
        try:
            # Get file content at specific commit
            commit = self.repo.commit(commit_sha)
            return commit.tree[prompt_file].data_stream.read().decode('utf-8')
        except (KeyError, Exception):
            return None
    
    def version_at_commit(self, prompt_id: str, commit_sha: str) -> Optional[str]:
        """Which version of ``prompt_id`` was in effect at ``commit_sha``.

        This is the counterpart to :meth:`commit_for_version`, but not its
        exact inverse, and the difference matters. A deploy commit usually
        did not touch the prompt being asked about, so "which version is
        tagged AT this commit" would answer ``None`` for almost every real
        query. The useful question, and the one this answers, is "which
        version was live at that point": the newest prompt-modifying commit
        that is an ancestor of (or equal to) ``commit_sha``.

        Args:
            prompt_id: Prompt to look up.
            commit_sha: Any ref ``Repo.commit`` accepts (full SHA, short
                SHA, tag, ``HEAD~2``).

        Returns:
            The version label ``get_prompt_versions`` would report for that
            point in history: a semver tag (``v1.2.3``) when one exists, the
            ``commit-<sha8>`` fallback otherwise. ``None`` if the prompt did
            not exist yet at that commit, or the ref cannot be resolved.
        """
        validate_prompt_id(prompt_id)

        try:
            target = self.repo.commit(commit_sha)
        except Exception:
            # An unresolvable ref is a caller error, not a crash: blame passes
            # commits straight from the deploy log, which may reference
            # history this checkout does not have (e.g. a shallow clone).
            return None

        # get_prompt_versions is newest-first, so the first ancestor found is
        # the version that was live.
        for entry in self.get_prompt_versions(prompt_id):
            try:
                candidate = self.repo.commit(entry["commit"])
            except Exception:
                continue
            if candidate == target or self.repo.is_ancestor(candidate, target):
                return entry["version"]

        return None

    def commit_for_version(self, prompt_id: str, version: str) -> Optional[str]:
        """Resolve a version string to a full git commit hash.

        Accepts any of:
        - The version label returned by ``get_prompt_versions`` — a real
          semver tag (``v1.2.3``) or the ``commit-<sha>`` fallback.
        - The 8-char short SHA exposed as ``commit_short`` in that list.
        - A full 40-char SHA, an abbreviated prefix, or any other ref that
          ``Repo.commit(...)`` would accept (tag name, ``HEAD~N``, etc.).

        The first three forms hit the prompt's own commit history. The last
        form falls back to a repo-wide ``Repo.commit(version)`` lookup so
        callers can resolve a prompt at *any* point in repo history, not
        only at commits that happened to touch this prompt's file. This is
        what makes ``promptops blame --at <ts>`` work for prompts that
        weren't directly modified by the deploy commit — they still
        existed at that commit, just weren't changed by it.
        """
        versions = self.get_prompt_versions(prompt_id)

        for v in versions:
            if (
                v["version"] == version
                or v["commit_short"] == version
                or v["commit"] == version
            ):
                return v["commit"]

        # Fallback: ask git to resolve ``version`` as any ref the repo knows.
        # This covers full SHAs, prefixes (>=4 chars), tag names, and symbolic
        # refs that aren't in the prompt's own history. If git can't resolve
        # it, we silently return None — the caller will raise a not-found
        # error with the available prompts listed.
        try:
            return self.repo.commit(version).hexsha
        except Exception:
            return None

    def _resolve_version_to_commit(self, prompt_id: str, version: str) -> Optional[str]:
        """Deprecated private alias for :meth:`commit_for_version`.

        Kept for backwards compatibility — external code observed in the
        wild (and our own v0.3.x resolver) reached into the private name.
        New code should call ``commit_for_version``.
        """
        return self.commit_for_version(prompt_id, version)

    def _generate_version(self, commit, index: int, total: int, prompt_id: Optional[str] = None) -> str:
        """Resolve a commit to its version identifier.

        Returns the git tag (e.g. ``v1.2.3``) when the commit is tagged.
        Otherwise returns a commit reference (e.g. ``commit-abc12345``).

        The commit reference is an immutable identifier — the same commit
        always returns the same string regardless of how many commits land
        afterwards. This replaces an earlier position-based fallback
        (``v{major}.{minor}.{patch}`` derived from index/total) that
        violated immutability: a commit's "version" would shift every
        time a new commit was added, which made historical references
        unreliable for ``promptops blame``-style use cases.

        When ``prompt_id`` is provided, per-prompt tags scoped to that
        prompt (created by ``promptops migrate tag-history``) take
        priority over legacy global ``v1.2.3`` tags.

        ``index`` and ``total`` are kept in the signature for backwards
        compatibility with the call site, but are no longer used.
        """
        tag_version = self._get_tag_version(commit, prompt_id=prompt_id)
        if tag_version:
            return tag_version

        return f"commit-{commit.hexsha[:8]}"

    def _get_tag_version(self, commit, prompt_id: Optional[str] = None) -> Optional[str]:
        """Try to get version from git tags.

        Recognizes two tag formats:
        - Per-prompt: ``prompt-<prompt_id>-v1.2.3`` (created by
          ``promptops migrate tag-history``). Scoped to a specific prompt;
          tags for other prompts are ignored.
        - Legacy global: ``v1.2.3`` or ``1.2.3``. Returned when no
          per-prompt tag exists on this commit.

        Per-prompt tags take priority — if both forms tag the same commit,
        the per-prompt tag wins.
        """
        try:
            tags_for_commit = [tag for tag in self.repo.tags if tag.commit == commit]

            # Per-prompt tag has priority when prompt_id is known
            if prompt_id:
                per_prompt_pattern = rf'^prompt-{re.escape(prompt_id)}-v?(\d+\.\d+\.\d+)$'
                for tag in tags_for_commit:
                    match = re.match(per_prompt_pattern, tag.name)
                    if match:
                        return f"v{match.group(1)}"

            # Legacy global tag — anchored end-of-string so per-prompt tags
            # (e.g. ``prompt-foo-v1.0.0``) don't accidentally match here.
            for tag in tags_for_commit:
                match = re.match(r'^v?(\d+\.\d+\.\d+)$', tag.name)
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
            check_file_size(file_path)
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
        validate_prompt_id(prompt_id)
        unstaged_content = self._get_unstaged_prompt(prompt_id)
        latest_content = self._get_latest_commit_prompt(prompt_id)
        
        if unstaged_content is None and latest_content is None:
            return False
        
        if unstaged_content is None or latest_content is None:
            return True
        
        return unstaged_content.strip() != latest_content.strip()
    
    def get_file_status(self, prompt_id: str) -> Dict[str, bool]:
        """Get detailed file status information."""
        validate_prompt_id(prompt_id)
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