"""
llmhq-promptops: Git-native prompt management and testing framework for production LLM workflows.

This package provides:
- Git-based prompt versioning and management
- Automated semantic versioning with git hooks
- Version-aware testing with :unstaged, :working, :latest references
- Framework-agnostic design (works with OpenAI, Anthropic, etc.)
- CLI tools for prompt management and testing
"""

__version__ = "0.1.0"
__author__ = "jision"
__email__ = "jisionpc@gmail.com"

# Core SDK exports
from .prompt_manager import (
    PromptManager,
    get_prompt,
    get_template,
    get_prompt_manager
)

from .core.template import (
    PromptTemplate,
    PromptMetadata,
    VariableDefinition
)

from .core.git_versioning import GitVersioning

# Future: Framework adapters will be added in later releases
LANGCHAIN_AVAILABLE = False

# Public API
__all__ = [
    # Core functionality
    "PromptManager",
    "get_prompt", 
    "get_template",
    "get_prompt_manager",
    
    # Template classes
    "PromptTemplate",
    "PromptMetadata", 
    "VariableDefinition",
    
    # Git integration
    "GitVersioning",
    
    # Constants
    "LANGCHAIN_AVAILABLE",
]


def get_version() -> str:
    """Get package version."""
    return __version__


def check_dependencies() -> dict:
    """Check availability of optional dependencies."""
    dependencies = {
        "git": True,  # GitPython is required dependency
    }
    
    # Future: Will include framework adapter dependencies
    
    return dependencies


# Setup logging
import logging
logging.getLogger(__name__).addHandler(logging.NullHandler())