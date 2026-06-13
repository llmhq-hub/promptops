import os
import logging
from typing import Dict, Any, Optional, List, Union
from pathlib import Path
from functools import lru_cache

import yaml
from jinja2 import TemplateError

from .core.errors import (
    E001_NOT_INITIALIZED,
    E002_NO_PROMPT_SOURCE,
    E003_PROMPT_NOT_FOUND,
    E014_RENDER_FAILED,
    E015_PARSE_FAILED,
    PromptOpsError,
)
from .core.git_versioning import GitVersioning
from .core.resolver import GitResolver, ResolvedPrompt, Resolver
from .core.template import PromptTemplate
from .core.validation import validate_prompt_id


class PromptManager:
    """Core prompt management system with git-based versioning."""

    def __init__(
        self,
        repo_path: str = ".",
        cache_size: int = 128,
        resolver: Optional[Resolver] = None,
    ):
        """Initialize PromptManager.

        Args:
            repo_path: Path to git repository containing .promptops directory
            cache_size: Size of LRU cache for prompt templates
            resolver: Optional pluggable Resolver. Defaults to GitResolver(repo_path).
                Phase 1.5a M3 will add SnapshotResolver / AutoResolver for production
                runtime use (Docker images without `.git/`).
        """
        self.repo_path = Path(repo_path).resolve()
        self.promptops_dir = self.repo_path / ".promptops"

        # Backwards-compat: keep `git_versioning` attribute so callers that
        # access manager.git_versioning.has_uncommitted_changes(...) etc.
        # continue to work unchanged.
        self.git_versioning = GitVersioning(repo_path)

        # Pluggable resolver. When None (the default), construct GitResolver —
        # this preserves v0.2.0 behavior (git required) for callers who don't
        # pass `resolver=`. To opt into the new behavior, pass an explicit
        # resolver (e.g., a SnapshotResolver in production).
        self._resolver: Resolver = resolver if resolver is not None else GitResolver(repo_path)

        # Setup caching
        self._get_template_cached = lru_cache(maxsize=cache_size)(self._get_template_uncached)

        # Setup logging
        self.logger = logging.getLogger(__name__)

        # Validate setup (directory layout only; resolver validates its own backend)
        self._validate_setup()

    def _validate_setup(self):
        """Validate directory layout. Backend validation lives in the Resolver.

        Two valid layouts:
          - Dev / source-of-truth: ``.promptops/prompts/`` exists (YAML source).
          - Production runtime: ``.promptops/snapshot.json`` exists (frozen
            artifact in a Docker image, no ``prompts/`` directory needed).
        At least one must be present.
        """
        if not self.promptops_dir.exists():
            raise PromptOpsError(
                code=E001_NOT_INITIALIZED,
                message=f"PromptOps not initialized at {self.repo_path}.",
                hint="Run 'promptops init repo' first.",
            )

        prompts_dir = self.promptops_dir / "prompts"
        snapshot_path = self.promptops_dir / "snapshot.json"
        if not prompts_dir.exists() and not snapshot_path.exists():
            raise PromptOpsError(
                code=E002_NO_PROMPT_SOURCE,
                message=(
                    f"PromptOps directory at {self.promptops_dir} has neither "
                    f"a 'prompts/' directory (dev source) nor a 'snapshot.json' "
                    f"(production artifact)."
                ),
                hint=(
                    "Initialize prompts with 'promptops init repo' or build a "
                    "snapshot with 'promptops snapshot build'."
                ),
            )
    
    def get_prompt(self, prompt_reference: str, variables: Dict[str, Any] = None) -> str:
        """Get and render a prompt by reference.
        
        Args:
            prompt_reference: Either 'prompt_id' or 'prompt_id:version'
            variables: Variables to substitute in template
            
        Returns:
            Rendered prompt string
            
        Example:
            manager.get_prompt("user-onboarding")  # Latest version
            manager.get_prompt("user-onboarding:v1.2.1")  # Specific version
        """
        prompt_id, version = self._parse_prompt_reference(prompt_reference)
        template = self.get_template(prompt_id, version)
        
        if variables is None:
            variables = {}
        
        # Narrow catch (v0.4.0): only template-shaped failures become
        # E014 — Jinja2's TemplateError family (syntax, undefined vars,
        # sandbox violations) and the template's own ValueError for
        # missing required variables. Anything else (a broken __str__ on
        # a passed object, KeyboardInterrupt, ...) propagates raw with
        # its real type and traceback.
        try:
            return template.render(variables)
        except (TemplateError, ValueError) as e:
            self.logger.error(f"Failed to render prompt {prompt_reference}: {e}")
            raise PromptOpsError(
                code=E014_RENDER_FAILED,
                message=f"Failed to render prompt {prompt_reference}: {e}",
                hint=(
                    "Check that all required variables are provided and the "
                    "Jinja2 template syntax is valid. "
                    "'promptops test runtest --prompt <id>' validates a "
                    "prompt locally."
                ),
            )
    
    # Versions that read mutable working-tree state. Caching these made
    # dev edit-then-rerun return stale text until refresh() — the classic
    # first-session WTF. Immutable refs (semver tags, commit SHAs) and
    # HEAD aliases stay cached; refresh() remains the escape hatch after
    # a commit.
    _UNCACHEABLE_VERSIONS = frozenset({None, "unstaged", "working-dir", "staged"})

    def get_template(self, prompt_id: str, version: Optional[str] = None) -> PromptTemplate:
        """Get PromptTemplate object for a prompt.

        Args:
            prompt_id: Unique prompt identifier
            version: Version string (None for latest)

        Returns:
            PromptTemplate instance

        Note (v0.4.0): when the resolver reads mutable working-tree state
        (git mode in dev), working-tree versions (``None``, ``unstaged``,
        ``working-dir``, ``staged``) bypass the template cache so edits on
        disk are visible immediately. Snapshot-backed resolvers are frozen
        artifacts, so everything stays cached there; pinned versions are
        cached everywhere.
        """
        cache_key = f"{prompt_id}:{version or 'latest'}"
        if (
            version in self._UNCACHEABLE_VERSIONS
            # Resolvers declare mutability via `reads_working_tree`
            # (GitResolver: True, SnapshotResolver: False, AutoResolver:
            # delegates). Unknown custom resolvers default to True —
            # favor correctness over cache hits.
            and getattr(self._resolver, "reads_working_tree", True)
        ):
            return self._get_template_uncached(cache_key, prompt_id, version)
        return self._get_template_cached(cache_key, prompt_id, version)
    
    def _get_template_uncached(self, cache_key: str, prompt_id: str, version: Optional[str]) -> PromptTemplate:
        """Internal method to get template without caching.

        Routes through the configured Resolver. The resolver itself raises
        ValueError if the prompt is not found, so the not-found path is
        handled there with the most accurate context.
        """
        resolved = self._resolver.resolve(prompt_id, version)
        yaml_content = resolved.text

        # Narrow catch (v0.4.0): YAML syntax errors, schema problems
        # (missing template key → ValueError), and not-a-mapping shapes
        # (scalar/list YAML → AttributeError/TypeError on .get). Real
        # bugs propagate with their own type.
        try:
            return PromptTemplate(yaml_content)
        except (yaml.YAMLError, ValueError, KeyError, TypeError, AttributeError) as e:
            self.logger.error(f"Failed to parse prompt {prompt_id}: {e}")
            raise PromptOpsError(
                code=E015_PARSE_FAILED,
                message=f"Failed to parse prompt {prompt_id}: {e}",
                hint=(
                    "The prompt YAML is malformed or missing required keys "
                    "(prompt.id, prompt.template). Validate the file under "
                    ".promptops/prompts/ against the schema in the README."
                ),
            )

    def resolve(self, prompt_reference: str) -> ResolvedPrompt:
        """Resolve a prompt to its raw content + provenance metadata.

        Returns a `ResolvedPrompt` with `text` (raw YAML, not rendered),
        plus `version`, `commit`, `resolved_at`, `source`, `prompt_id`.

        Use this when you need provenance (e.g., logging which prompt
        version was used at a given time). For a rendered string only,
        keep using `get_prompt(reference, variables)`.

        Example:
            manager = PromptManager()
            resolved = manager.resolve("user-onboarding:v1.2.0")
            print(resolved.version, resolved.commit, resolved.source)
        """
        prompt_id, version = self._parse_prompt_reference(prompt_reference)
        return self._resolver.resolve(prompt_id, version)
    
    def _parse_prompt_reference(self, reference: str) -> tuple[str, Optional[str]]:
        """Parse prompt reference into ID and version.

        Args:
            reference: Either 'prompt_id' or 'prompt_id:version'

        Returns:
            Tuple of (prompt_id, version)
        """
        if ":" in reference:
            prompt_id, version = reference.split(":", 1)
            prompt_id = prompt_id.strip()
            version = version.strip()
        else:
            prompt_id = reference.strip()
            version = None
        validate_prompt_id(prompt_id)
        return prompt_id, version
    
    def list_prompts(self) -> List[str]:
        """List all available prompt IDs."""
        return self.git_versioning.list_available_prompts()
    
    def list_versions(self, prompt_id: str) -> List[Dict]:
        """List all versions of a specific prompt.
        
        Args:
            prompt_id: Prompt identifier
            
        Returns:
            List of version info dictionaries
        """
        return self.git_versioning.get_prompt_versions(prompt_id)
    
    def get_latest_version(self, prompt_id: str) -> Optional[str]:
        """Get latest version string for a prompt."""
        return self.git_versioning.get_latest_version(prompt_id)
    
    def validate_prompt(self, prompt_id: str, version: Optional[str] = None, 
                       variables: Dict[str, Any] = None) -> List[str]:
        """Validate a prompt and its variables.
        
        Args:
            prompt_id: Prompt identifier
            version: Version string
            variables: Variables to validate
            
        Returns:
            List of validation errors (empty if valid)
        """
        try:
            template = self.get_template(prompt_id, version)
            
            if variables is not None:
                return template.validate_variables(variables)
            else:
                # Check for required variables
                errors = []
                for var_name, var_def in template.variables.items():
                    if var_def.required and var_def.default is None:
                        errors.append(f"Required variable '{var_name}' must be provided")
                return errors
                
        except Exception as e:
            return [str(e)]
    
    def get_prompt_info(self, prompt_id: str, version: Optional[str] = None) -> Dict[str, Any]:
        """Get detailed information about a prompt.
        
        Args:
            prompt_id: Prompt identifier  
            version: Version string
            
        Returns:
            Dictionary with prompt information
        """
        template = self.get_template(prompt_id, version)
        versions = self.list_versions(prompt_id)
        file_status = self.git_versioning.get_file_status(prompt_id)
        
        current_version = version or (versions[0]["version"] if versions else "unknown")
        
        return {
            "id": prompt_id,
            "version": current_version,
            "metadata": template.metadata.__dict__,
            "variables": {name: var.__dict__ for name, var in template.variables.items()},
            "supported_models": template.get_supported_models(),
            "default_model": template.get_default_model(),
            "available_versions": [v["version"] for v in versions],
            "tests": template.tests,
            "file_status": file_status
        }
    
    def clear_cache(self):
        """Clear the template cache."""
        self._get_template_cached.cache_clear()
    
    def refresh(self):
        """Refresh git state and clear cache."""
        self.git_versioning._version_cache.clear()
        self.clear_cache()
    
    def has_uncommitted_changes(self, prompt_id: str) -> bool:
        """Check if prompt has uncommitted changes."""
        return self.git_versioning.has_uncommitted_changes(prompt_id)
    
    def get_file_status(self, prompt_id: str) -> Dict[str, bool]:
        """Get detailed file status information."""
        return self.git_versioning.get_file_status(prompt_id)
    
    def get_prompt_diff(self, prompt_id: str, version1: str, version2: str) -> Dict[str, Any]:
        """Compare two versions of a prompt.

        Args:
            prompt_id: Prompt identifier
            version1: First version to compare
            version2: Second version to compare

        Returns:
            Dictionary with diff information

        Raises:
            PromptOpsError: (E003) when either version's content can't be
                retrieved. Pre-v0.4.0 this returned an ``{"error": ...}``
                dict instead — callers no longer need to remember to check
                for that key.
        """
        content1 = self.git_versioning.get_prompt_at_version(prompt_id, version1)
        content2 = self.git_versioning.get_prompt_at_version(prompt_id, version2)

        if content1 is None or content2 is None:
            missing = [
                v for v, c in ((version1, content1), (version2, content2))
                if c is None
            ]
            raise PromptOpsError(
                code=E003_PROMPT_NOT_FOUND,
                message=(
                    f"Cannot diff prompt '{prompt_id}': version(s) "
                    f"{', '.join(repr(m) for m in missing)} not found."
                ),
                hint=(
                    "See each prompt's latest version with "
                    "'promptops test status', or use a working-tree ref "
                    "like ':unstaged' / ':working'."
                ),
            )

        # Simple line-by-line diff
        lines1 = content1.split('\n')
        lines2 = content2.split('\n')

        return {
            "version1": version1,
            "version2": version2,
            "content1": content1,
            "content2": content2,
            "lines_added": len(lines2) - len(lines1),
            "identical": content1.strip() == content2.strip(),
            "summary": f"Comparing {version1} vs {version2}"
        }
    
    def list_prompt_statuses(self) -> Dict[str, Dict[str, Any]]:
        """Get status information for all prompts."""
        prompts = self.list_prompts()
        statuses = {}
        
        for prompt_id in prompts:
            try:
                file_status = self.get_file_status(prompt_id)
                latest_version = self.get_latest_version(prompt_id)
                
                statuses[prompt_id] = {
                    "latest_version": latest_version,
                    "has_uncommitted_changes": file_status["has_uncommitted_changes"],
                    "has_staged_changes": file_status["has_staged_changes"],
                    "status": self._get_status_summary(file_status)
                }
            except Exception as e:
                statuses[prompt_id] = {
                    "error": str(e),
                    "status": "error"
                }
        
        return statuses
    
    def _get_status_summary(self, file_status: Dict[str, bool]) -> str:
        """Get human-readable status summary."""
        if file_status["has_uncommitted_changes"]:
            return "modified"
        elif file_status["has_staged_changes"]:
            return "staged"
        elif file_status["exists_committed"]:
            return "clean"
        elif file_status["exists_working"]:
            return "untracked"
        else:
            return "missing"


# Global instance for easy access
_default_manager = None


def get_prompt_manager(repo_path: str = ".") -> PromptManager:
    """Get or create the default PromptManager instance.

    The default manager is constructed with ``AutoResolver`` so the same
    code works in dev (with ``.git/``) and prod (with
    ``.promptops/snapshot.json``). To use a specific resolver, construct
    ``PromptManager(resolver=...)`` directly instead of going through this
    convenience helper.
    """
    global _default_manager
    resolved_path = Path(repo_path).resolve()
    if _default_manager is None or _default_manager.repo_path != resolved_path:
        # Lazy import: callers who construct PromptManager(resolver=...)
        # directly never need to pay the snapshot module import cost.
        from .core.snapshot import AutoResolver

        _default_manager = PromptManager(
            repo_path, resolver=AutoResolver(repo_path=str(resolved_path))
        )
    return _default_manager


def get_prompt(prompt_reference: str, variables: Dict[str, Any] = None, 
               repo_path: str = ".") -> str:
    """Convenience function to get and render a prompt.
    
    Args:
        prompt_reference: Either 'prompt_id' or 'prompt_id:version'
        variables: Variables to substitute in template
        repo_path: Path to git repository (default: current directory)
        
    Returns:
        Rendered prompt string
        
    Example:
        from llmhq_promptops import get_prompt
        
        prompt = get_prompt("user-onboarding")
        prompt = get_prompt("user-onboarding:v1.2.1", {"user_name": "John"})
    """
    manager = get_prompt_manager(repo_path)
    return manager.get_prompt(prompt_reference, variables)


def get_template(prompt_id: str, version: Optional[str] = None, 
                repo_path: str = ".") -> PromptTemplate:
    """Convenience function to get a PromptTemplate.
    
    Args:
        prompt_id: Prompt identifier
        version: Version string (None for latest)
        repo_path: Path to git repository
        
    Returns:
        PromptTemplate instance
    """
    manager = get_prompt_manager(repo_path)
    return manager.get_template(prompt_id, version)