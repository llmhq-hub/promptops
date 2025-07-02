import os
import logging
from typing import Dict, Any, Optional, List, Union
from pathlib import Path
from functools import lru_cache

from .core.git_versioning import GitVersioning
from .core.template import PromptTemplate


class PromptManager:
    """Core prompt management system with git-based versioning."""
    
    def __init__(self, repo_path: str = ".", cache_size: int = 128):
        """Initialize PromptManager.
        
        Args:
            repo_path: Path to git repository containing .promptops directory
            cache_size: Size of LRU cache for prompt templates
        """
        self.repo_path = Path(repo_path).resolve()
        self.promptops_dir = self.repo_path / ".promptops"
        self.git_versioning = GitVersioning(repo_path)
        
        # Setup caching
        self._get_template_cached = lru_cache(maxsize=cache_size)(self._get_template_uncached)
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
        
        # Validate setup
        self._validate_setup()
    
    def _validate_setup(self):
        """Validate that promptops is properly setup."""
        if not self.git_versioning.is_git_repo():
            raise ValueError(f"Directory {self.repo_path} is not a git repository")
        
        if not self.promptops_dir.exists():
            raise ValueError(f"PromptOps not initialized. Run 'promptops init repo' first")
        
        prompts_dir = self.promptops_dir / "prompts"
        if not prompts_dir.exists():
            raise ValueError(f"Prompts directory not found: {prompts_dir}")
    
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
        
        try:
            return template.render(variables)
        except Exception as e:
            self.logger.error(f"Failed to render prompt {prompt_reference}: {e}")
            raise ValueError(f"Failed to render prompt {prompt_reference}: {e}")
    
    def get_template(self, prompt_id: str, version: Optional[str] = None) -> PromptTemplate:
        """Get PromptTemplate object for a prompt.
        
        Args:
            prompt_id: Unique prompt identifier
            version: Version string (None for latest)
            
        Returns:
            PromptTemplate instance
        """
        cache_key = f"{prompt_id}:{version or 'latest'}"
        return self._get_template_cached(cache_key, prompt_id, version)
    
    def _get_template_uncached(self, cache_key: str, prompt_id: str, version: Optional[str]) -> PromptTemplate:
        """Internal method to get template without caching."""
        # Get YAML content from git
        yaml_content = self.git_versioning.get_prompt_at_version(prompt_id, version)
        
        if yaml_content is None:
            available = self.list_prompts()
            raise ValueError(f"Prompt '{prompt_id}' not found. Available prompts: {available}")
        
        try:
            return PromptTemplate(yaml_content)
        except Exception as e:
            self.logger.error(f"Failed to parse prompt {prompt_id}: {e}")
            raise ValueError(f"Failed to parse prompt {prompt_id}: {e}")
    
    def _parse_prompt_reference(self, reference: str) -> tuple[str, Optional[str]]:
        """Parse prompt reference into ID and version.
        
        Args:
            reference: Either 'prompt_id' or 'prompt_id:version'
            
        Returns:
            Tuple of (prompt_id, version)
        """
        if ":" in reference:
            prompt_id, version = reference.split(":", 1)
            return prompt_id.strip(), version.strip()
        else:
            return reference.strip(), None
    
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
        """
        try:
            content1 = self.git_versioning.get_prompt_at_version(prompt_id, version1)
            content2 = self.git_versioning.get_prompt_at_version(prompt_id, version2)
            
            if content1 is None or content2 is None:
                return {
                    "error": f"Could not retrieve content for versions {version1} or {version2}",
                    "version1_exists": content1 is not None,
                    "version2_exists": content2 is not None
                }
            
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
            
        except Exception as e:
            return {
                "error": f"Failed to compare versions: {e}",
                "version1": version1,
                "version2": version2
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
    """Get or create the default PromptManager instance."""
    global _default_manager
    if _default_manager is None or _default_manager.repo_path != Path(repo_path).resolve():
        _default_manager = PromptManager(repo_path)
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