import yaml
import re
from typing import Dict, List, Tuple, Optional, Any
from enum import Enum
from dataclasses import dataclass

from .template import PromptTemplate


class ChangeType(Enum):
    """Types of changes for semantic versioning."""
    PATCH = "patch"      # x.y.Z+1 - Content changes, bug fixes
    MINOR = "minor"      # x.Y+1.0 - New features, backward compatible
    MAJOR = "major"      # X+1.0.0 - Breaking changes


@dataclass
class VersionChange:
    """Represents a version change with reasoning."""
    change_type: ChangeType
    old_version: str
    new_version: str
    reasons: List[str]
    file_changes: Dict[str, Any]


class SemanticVersionDetector:
    """Detects semantic version changes in prompt files."""
    
    def __init__(self):
        """Initialize the semantic version detector."""
        pass
    
    def analyze_prompt_changes(self, old_content: str, new_content: str, 
                             current_version: str = "1.0.0") -> VersionChange:
        """Analyze changes between two prompt versions.
        
        Args:
            old_content: Previous YAML content
            new_content: New YAML content  
            current_version: Current version string
            
        Returns:
            VersionChange object with analysis
        """
        try:
            old_data = yaml.safe_load(old_content) if old_content else {}
            new_data = yaml.safe_load(new_content) if new_content else {}
        except yaml.YAMLError as e:
            # If YAML is invalid, consider it a patch fix
            return VersionChange(
                change_type=ChangeType.PATCH,
                old_version=current_version,
                new_version=self._increment_version(current_version, ChangeType.PATCH),
                reasons=[f"YAML syntax fix: {e}"],
                file_changes={"yaml_error": str(e)}
            )
        
        changes = self._detect_changes(old_data, new_data)
        change_type = self._determine_change_type(changes)
        
        return VersionChange(
            change_type=change_type,
            old_version=current_version,
            new_version=self._increment_version(current_version, change_type),
            reasons=changes["reasons"],
            file_changes=changes
        )
    
    def _detect_changes(self, old_data: Dict, new_data: Dict) -> Dict[str, Any]:
        """Detect specific changes between YAML data."""
        changes = {
            "reasons": [],
            "metadata_changes": [],
            "template_changes": [],
            "variable_changes": [],
            "model_changes": [],
            "breaking_changes": [],
            "new_features": []
        }
        
        # Check metadata changes
        old_metadata = old_data.get("metadata", {})
        new_metadata = new_data.get("metadata", {})
        
        if old_metadata != new_metadata:
            changes["metadata_changes"] = self._diff_metadata(old_metadata, new_metadata)
            if changes["metadata_changes"]:
                changes["reasons"].extend([f"Metadata: {change}" for change in changes["metadata_changes"]])
        
        # Check template content changes
        old_template = self._extract_template_content(old_data)
        new_template = self._extract_template_content(new_data)
        
        if old_template != new_template:
            changes["template_changes"] = self._analyze_template_changes(old_template, new_template)
            changes["reasons"].append("Template content modified")
        
        # Check variable changes
        old_vars = self._extract_variables(old_data)
        new_vars = self._extract_variables(new_data)
        
        var_changes = self._analyze_variable_changes(old_vars, new_vars)
        changes["variable_changes"] = var_changes
        changes["breaking_changes"].extend(var_changes.get("breaking", []))
        changes["new_features"].extend(var_changes.get("new_features", []))
        
        if var_changes.get("reasons"):
            changes["reasons"].extend(var_changes["reasons"])
        
        # Check model support changes
        old_models = self._extract_models(old_data)
        new_models = self._extract_models(new_data)
        
        if old_models != new_models:
            model_changes = self._analyze_model_changes(old_models, new_models)
            changes["model_changes"] = model_changes
            changes["reasons"].extend(model_changes.get("reasons", []))
            
            if model_changes.get("removed_models"):
                changes["breaking_changes"].append("Removed model support")
            if model_changes.get("added_models"):
                changes["new_features"].append("Added model support")
        
        return changes
    
    def _determine_change_type(self, changes: Dict[str, Any]) -> ChangeType:
        """Determine the semantic version change type."""
        # MAJOR: Breaking changes
        if changes["breaking_changes"]:
            return ChangeType.MAJOR
        
        # MINOR: New features, backward compatible additions
        if (changes["new_features"] or 
            changes["model_changes"] or 
            any("new" in reason.lower() for reason in changes["reasons"])):
            return ChangeType.MINOR
        
        # PATCH: Everything else (content changes, fixes, etc.)
        return ChangeType.PATCH
    
    def _diff_metadata(self, old_meta: Dict, new_meta: Dict) -> List[str]:
        """Compare metadata sections."""
        changes = []
        
        for key in set(old_meta.keys()) | set(new_meta.keys()):
            old_val = old_meta.get(key)
            new_val = new_meta.get(key)
            
            if old_val != new_val:
                if old_val is None:
                    changes.append(f"Added {key}")
                elif new_val is None:
                    changes.append(f"Removed {key}")
                else:
                    changes.append(f"Modified {key}")
        
        return changes
    
    def _extract_template_content(self, data: Dict) -> str:
        """Extract template content from YAML data."""
        if "template" in data:
            return data["template"]
        elif "prompt" in data and "template" in data["prompt"]:
            return data["prompt"]["template"]
        return ""
    
    def _analyze_template_changes(self, old_template: str, new_template: str) -> Dict[str, Any]:
        """Analyze changes in template content."""
        old_lines = old_template.split('\n')
        new_lines = new_template.split('\n')
        
        return {
            "lines_added": len(new_lines) - len(old_lines),
            "significant_change": abs(len(new_lines) - len(old_lines)) > 5,
            "old_length": len(old_template),
            "new_length": len(new_template)
        }
    
    def _extract_variables(self, data: Dict) -> Dict[str, Any]:
        """Extract variable definitions from YAML data."""
        if "variables" in data:
            return data["variables"]
        elif "prompt" in data and "variables" in data["prompt"]:
            return data["prompt"]["variables"]
        return {}
    
    def _analyze_variable_changes(self, old_vars: Dict, new_vars: Dict) -> Dict[str, Any]:
        """Analyze changes in variable definitions."""
        changes = {
            "breaking": [],
            "new_features": [],
            "reasons": []
        }
        
        # Check for removed variables (breaking change)
        removed_vars = set(old_vars.keys()) - set(new_vars.keys())
        for var in removed_vars:
            # Only breaking if it was required
            if isinstance(old_vars[var], dict) and old_vars[var].get("required", True):
                changes["breaking"].append(f"Removed required variable: {var}")
                changes["reasons"].append(f"BREAKING: Removed required variable '{var}'")
            else:
                changes["reasons"].append(f"Removed optional variable '{var}'")
        
        # Check for added variables (new feature)
        added_vars = set(new_vars.keys()) - set(old_vars.keys())
        for var in added_vars:
            changes["new_features"].append(f"Added variable: {var}")
            changes["reasons"].append(f"Added new variable '{var}'")
        
        # Check for modified variables
        for var in set(old_vars.keys()) & set(new_vars.keys()):
            old_def = old_vars[var]
            new_def = new_vars[var]
            
            if old_def != new_def:
                # Check if required status changed
                old_required = old_def.get("required", True) if isinstance(old_def, dict) else True
                new_required = new_def.get("required", True) if isinstance(new_def, dict) else True
                
                if old_required and not new_required:
                    changes["new_features"].append(f"Made variable optional: {var}")
                    changes["reasons"].append(f"Made variable '{var}' optional")
                elif not old_required and new_required:
                    changes["breaking"].append(f"Made variable required: {var}")
                    changes["reasons"].append(f"BREAKING: Made variable '{var}' required")
                else:
                    changes["reasons"].append(f"Modified variable definition: {var}")
        
        return changes
    
    def _extract_models(self, data: Dict) -> List[str]:
        """Extract supported models from YAML data."""
        models = []
        
        if "models" in data:
            model_data = data["models"]
            if isinstance(model_data, dict):
                if "supported" in model_data:
                    models = model_data["supported"]
                elif "default" in model_data:
                    models = [model_data["default"]]
            elif isinstance(model_data, list):
                models = model_data
            elif isinstance(model_data, str):
                models = [model_data]
        elif "prompt" in data and "model" in data["prompt"]:
            models = [data["prompt"]["model"]]
        
        return models if isinstance(models, list) else []
    
    def _analyze_model_changes(self, old_models: List[str], new_models: List[str]) -> Dict[str, Any]:
        """Analyze changes in model support."""
        added = set(new_models) - set(old_models)
        removed = set(old_models) - set(new_models)
        
        changes = {
            "added_models": list(added),
            "removed_models": list(removed),
            "reasons": []
        }
        
        if added:
            changes["reasons"].append(f"Added model support: {', '.join(added)}")
        if removed:
            changes["reasons"].append(f"Removed model support: {', '.join(removed)}")
        
        return changes
    
    def _increment_version(self, current_version: str, change_type: ChangeType) -> str:
        """Increment version based on change type."""
        # Remove 'v' prefix if present
        version = current_version.lstrip('v')
        
        try:
            parts = [int(x) for x in version.split('.')]
            
            # Ensure we have at least 3 parts
            while len(parts) < 3:
                parts.append(0)
            
            major, minor, patch = parts[0], parts[1], parts[2]
            
            if change_type == ChangeType.MAJOR:
                major += 1
                minor = 0
                patch = 0
            elif change_type == ChangeType.MINOR:
                minor += 1
                patch = 0
            else:  # PATCH
                patch += 1
            
            return f"v{major}.{minor}.{patch}"
            
        except (ValueError, IndexError):
            # If version parsing fails, default to patch increment
            return "v1.0.1"
    
    def get_next_version(self, current_version: str, old_content: str, new_content: str) -> str:
        """Get the next version number for given changes."""
        change = self.analyze_prompt_changes(old_content, new_content, current_version)
        return change.new_version