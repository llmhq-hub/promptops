import yaml
from typing import Dict, Any, Optional, List
from pathlib import Path
from jinja2 import Template, Environment, meta
from dataclasses import dataclass


@dataclass
class VariableDefinition:
    """Variable definition with type and validation."""
    name: str
    type: str
    required: bool = True
    default: Any = None
    description: str = ""


@dataclass
class PromptMetadata:
    """Prompt metadata from YAML file."""
    id: str
    version: Optional[str] = None
    description: str = ""
    tags: List[str] = None
    models: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.models is None:
            self.models = {"default": "gpt-4-turbo"}


class PromptTemplate:
    """Enhanced prompt template with metadata and variable support."""
    
    def __init__(self, yaml_content: str):
        """Initialize PromptTemplate from YAML content."""
        self.raw_content = yaml_content
        self._data = yaml.safe_load(yaml_content)
        self._template = None
        self._jinja_env = Environment()
        
        # Parse the structure
        self.metadata = self._parse_metadata()
        self.template_str = self._extract_template()
        self.variables = self._parse_variables()
        self.tests = self._parse_tests()
    
    def _parse_metadata(self) -> PromptMetadata:
        """Parse metadata from YAML."""
        if "metadata" in self._data:
            # New enhanced format
            meta_data = self._data["metadata"]
            return PromptMetadata(
                id=meta_data.get("id", ""),
                version=meta_data.get("version"),
                description=meta_data.get("description", ""),
                tags=meta_data.get("tags", []),
                models=meta_data.get("models", {"default": "gpt-4-turbo"})
            )
        elif "prompt" in self._data:
            # Legacy format compatibility
            prompt_data = self._data["prompt"]
            return PromptMetadata(
                id=prompt_data.get("id", ""),
                description=prompt_data.get("description", ""),
                models={"default": prompt_data.get("model", "gpt-4-turbo")}
            )
        else:
            # Minimal format - just template
            return PromptMetadata(id="unknown")
    
    def _extract_template(self) -> str:
        """Extract template string from YAML."""
        if "template" in self._data:
            # New format - template at root level
            return self._data["template"]
        elif "prompt" in self._data and "template" in self._data["prompt"]:
            # Legacy format
            return self._data["prompt"]["template"]
        else:
            raise ValueError("No template found in prompt YAML")
    
    def _parse_variables(self) -> Dict[str, VariableDefinition]:
        """Parse variable definitions from YAML."""
        variables = {}
        
        # Parse from YAML definition
        if "variables" in self._data:
            var_data = self._data["variables"]
            
            if isinstance(var_data, list):
                # Legacy format - list of variable names
                for var in var_data:
                    if isinstance(var, str):
                        variables[var] = VariableDefinition(name=var, type="string")
                    elif isinstance(var, dict):
                        name = list(var.keys())[0]
                        config = var[name]
                        variables[name] = VariableDefinition(
                            name=name,
                            type=config.get("type", "string"),
                            required=config.get("required", True),
                            default=config.get("default"),
                            description=config.get("description", "")
                        )
            elif isinstance(var_data, dict):
                # New format - dict of variable definitions
                for name, config in var_data.items():
                    if isinstance(config, dict):
                        variables[name] = VariableDefinition(
                            name=name,
                            type=config.get("type", "string"),
                            required=config.get("required", True),
                            default=config.get("default"),
                            description=config.get("description", "")
                        )
                    else:
                        # Simple format - just type
                        variables[name] = VariableDefinition(name=name, type=str(config))
        
        # Auto-detect variables from template
        template_vars = self._detect_template_variables()
        for var in template_vars:
            if var not in variables:
                variables[var] = VariableDefinition(name=var, type="string")
        
        return variables
    
    def _detect_template_variables(self) -> set:
        """Auto-detect variables used in Jinja2 template."""
        try:
            ast = self._jinja_env.parse(self.template_str)
            return meta.find_undeclared_variables(ast)
        except Exception:
            return set()
    
    def _parse_tests(self) -> List[Dict]:
        """Parse test configurations from YAML."""
        if "tests" in self._data:
            return self._data["tests"]
        return []
    
    @property 
    def template(self) -> Template:
        """Get Jinja2 template instance."""
        if self._template is None:
            self._template = Template(self.template_str)
        return self._template
    
    def render(self, variables: Dict[str, Any] = None) -> str:
        """Render template with provided variables."""
        if variables is None:
            variables = {}
        
        # Add default values for missing variables
        final_vars = {}
        for var_name, var_def in self.variables.items():
            if var_name in variables:
                final_vars[var_name] = variables[var_name]
            elif var_def.default is not None:
                final_vars[var_name] = var_def.default
            elif var_def.required:
                raise ValueError(f"Required variable '{var_name}' not provided")
        
        # Add any extra variables not in definitions
        for key, value in variables.items():
            if key not in final_vars:
                final_vars[key] = value
        
        return self.template.render(**final_vars)
    
    def validate_variables(self, variables: Dict[str, Any]) -> List[str]:
        """Validate provided variables against definitions."""
        errors = []
        
        for var_name, var_def in self.variables.items():
            if var_def.required and var_name not in variables:
                if var_def.default is None:
                    errors.append(f"Required variable '{var_name}' is missing")
            
            if var_name in variables:
                value = variables[var_name]
                
                # Basic type checking
                if var_def.type == "string" and not isinstance(value, str):
                    errors.append(f"Variable '{var_name}' should be string, got {type(value).__name__}")
                elif var_def.type == "list" and not isinstance(value, list):
                    errors.append(f"Variable '{var_name}' should be list, got {type(value).__name__}")
                elif var_def.type == "dict" and not isinstance(value, dict):
                    errors.append(f"Variable '{var_name}' should be dict, got {type(value).__name__}")
                elif var_def.type in ["int", "integer"] and not isinstance(value, int):
                    errors.append(f"Variable '{var_name}' should be integer, got {type(value).__name__}")
                elif var_def.type in ["float", "number"] and not isinstance(value, (int, float)):
                    errors.append(f"Variable '{var_name}' should be number, got {type(value).__name__}")
        
        return errors
    
    def get_supported_models(self) -> List[str]:
        """Get list of supported models for this prompt."""
        if isinstance(self.metadata.models, dict):
            if "supported" in self.metadata.models:
                return self.metadata.models["supported"]
            elif "default" in self.metadata.models:
                return [self.metadata.models["default"]]
        elif isinstance(self.metadata.models, list):
            return self.metadata.models
        elif isinstance(self.metadata.models, str):
            return [self.metadata.models]
        
        return ["gpt-4-turbo"]  # Default fallback
    
    def get_default_model(self) -> str:
        """Get default model for this prompt."""
        if isinstance(self.metadata.models, dict):
            return self.metadata.models.get("default", "gpt-4-turbo")
        elif isinstance(self.metadata.models, list) and self.metadata.models:
            return self.metadata.models[0]
        elif isinstance(self.metadata.models, str):
            return self.metadata.models
        
        return "gpt-4-turbo"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert prompt template to dictionary representation."""
        return {
            "metadata": {
                "id": self.metadata.id,
                "version": self.metadata.version,
                "description": self.metadata.description,
                "tags": self.metadata.tags,
                "models": self.metadata.models
            },
            "template": self.template_str,
            "variables": {
                name: {
                    "type": var.type,
                    "required": var.required,
                    "default": var.default,
                    "description": var.description
                }
                for name, var in self.variables.items()
            },
            "tests": self.tests
        }
    
    @classmethod
    def from_file(cls, file_path: Path) -> 'PromptTemplate':
        """Create PromptTemplate from YAML file."""
        content = file_path.read_text()
        return cls(content)