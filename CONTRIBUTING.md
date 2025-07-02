# Contributing to llmhq-promptops

Thank you for your interest in contributing to llmhq-promptops! This document provides guidelines for contributing to the project.

## 🚀 Getting Started

### Prerequisites
- Python 3.8+
- Git
- Virtual environment (recommended)

### Development Setup

1. **Fork and Clone**
   ```bash
   git clone https://github.com/your-username/llmhq-promptops.git
   cd llmhq-promptops
   ```

2. **Create Virtual Environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # or `venv\Scripts\activate` on Windows
   ```

3. **Install Development Dependencies**
   ```bash
   pip install -r requirements.txt
   pip install -e .[dev]
   ```

4. **Verify Installation**
   ```bash
   promptops --help
   python -c "from llmhq_promptops import get_prompt; print('SDK works!')"
   ```

## 🛠️ Development Workflow

### Making Changes

1. **Create a Feature Branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make Your Changes**
   - Follow the existing code style and patterns
   - Add tests for new functionality
   - Update documentation as needed

3. **Test Your Changes**
   ```bash
   # Run syntax checks
   python -m py_compile src/path/to/changed/file.py
   
   # Test package building
   python -m build
   pip install dist/llmhq_promptops-*.whl --force-reinstall
   
   # Test CLI functionality
   promptops --help
   promptops init repo --help
   ```

4. **Commit Your Changes**
   ```bash
   git add .
   git commit -m "feat: add your feature description"
   ```

### Code Style Guidelines

- **Python Style**: Follow PEP 8
- **Import Order**: Standard library, third-party, local imports
- **Docstrings**: Use Google-style docstrings
- **Type Hints**: Add type hints for public APIs
- **Error Handling**: Provide clear, actionable error messages

### Example Code Style

```python
from typing import Dict, List, Optional
from pathlib import Path

class PromptManager:
    """Central class for prompt resolution and management.
    
    Args:
        repo_path: Path to git repository containing .promptops directory
        cache_size: Size of LRU cache for prompt templates
    """
    
    def __init__(self, repo_path: str = ".", cache_size: int = 128):
        self.repo_path = Path(repo_path).resolve()
        # Implementation...
    
    def get_prompt(self, prompt_reference: str, variables: Optional[Dict[str, Any]] = None) -> str:
        """Get and render a prompt by reference.
        
        Args:
            prompt_reference: Either 'prompt_id' or 'prompt_id:version'
            variables: Optional variables for template rendering
            
        Returns:
            Rendered prompt string
            
        Raises:
            ValueError: If prompt not found or rendering fails
        """
        # Implementation...
```

## 📝 Documentation

### Code Documentation
- All public classes and methods must have docstrings
- Include examples in docstrings for complex functionality
- Document all parameters and return values

### README Updates
- Update usage examples if you add new features
- Add new CLI commands to the command reference
- Update the feature list for significant additions

## 🧪 Testing

### Test Categories

1. **Unit Tests**: Test individual components
2. **Integration Tests**: Test CLI command functionality  
3. **Package Tests**: Test installation and import behavior

### Writing Tests

```python
def test_prompt_resolution():
    """Test basic prompt resolution functionality."""
    manager = PromptManager("./test-data")
    result = manager.get_prompt("test-prompt:working", {"name": "Alice"})
    assert "Hello Alice" in result
```

### Running Tests

```bash
# Quick syntax check
python -m py_compile src/**/*.py

# Package build test
python -m build
pip install dist/llmhq_promptops-*.whl --force-reinstall

# Manual integration test
mkdir test-project && cd test-project
git init
promptops init repo
promptops create prompt test
```

## 🐛 Bug Reports

### Before Submitting
- Check existing issues to avoid duplicates
- Test with the latest version
- Provide minimal reproduction steps

### Bug Report Template

```markdown
**Environment:**
- OS: [e.g., Ubuntu 22.04, Windows 11, macOS 13]
- Python: [e.g., 3.9.7]
- llmhq-promptops: [e.g., 0.1.0]

**Bug Description:**
Clear description of the bug.

**Steps to Reproduce:**
1. Run `promptops init repo`
2. Execute `promptops test status`
3. See error

**Expected Behavior:**
What should have happened.

**Actual Behavior:**
What actually happened.

**Error Output:**
```
[Paste error messages here]
```

**Additional Context:**
Any other relevant information.
```

## 💡 Feature Requests

### Before Submitting
- Check if the feature aligns with project goals
- Consider if it could be implemented as a plugin
- Think about backward compatibility

### Feature Request Template

```markdown
**Feature Description:**
Clear description of the proposed feature.

**Use Case:**
Why is this feature needed? What problem does it solve?

**Proposed Implementation:**
How might this feature work?

**Alternatives Considered:**
Other approaches you've considered.

**Additional Context:**
Screenshots, examples, or references.
```

## 🔄 Pull Request Process

### Before Submitting

1. **Update Documentation**
   - README.md if adding user-facing features
   - CHANGELOG.md with your changes
   - Code comments and docstrings

2. **Test Thoroughly**
   - Verify all existing functionality still works
   - Test your new feature in isolation
   - Test package installation from wheel

3. **Check Dependencies**
   - Minimize new dependencies
   - Use optional dependencies for non-core features
   - Update pyproject.toml if needed

### Pull Request Template

```markdown
## Description
Brief description of changes.

## Type of Change
- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update

## How Has This Been Tested?
- [ ] Unit tests pass
- [ ] Package builds successfully
- [ ] CLI commands work as expected
- [ ] Integration tests pass

## Checklist
- [ ] Code follows the project's style guidelines
- [ ] Self-review of code completed
- [ ] Code is commented, particularly in hard-to-understand areas
- [ ] Corresponding changes to documentation made
- [ ] CHANGELOG.md updated
```

## 📋 Release Process

### Version Numbering
- **MAJOR**: Breaking changes to public API
- **MINOR**: New features, backward compatible
- **PATCH**: Bug fixes, backward compatible

### Release Checklist
1. Update version in pyproject.toml
2. Update CHANGELOG.md
3. Create and test package build
4. Test installation in fresh environment
5. Create Git tag and GitHub release
6. Publish to PyPI

## 🤝 Community Guidelines

### Code of Conduct
- Be respectful and inclusive
- Focus on constructive feedback
- Help others learn and grow
- Maintain a professional tone

### Communication
- **Issues**: Bug reports and feature requests
- **Discussions**: Questions and general discussion
- **Pull Requests**: Code contributions

## 🆘 Getting Help

- **Documentation**: Check README.md and code comments
- **Issues**: Search existing issues before creating new ones
- **Discussions**: Use GitHub Discussions for questions
- **Email**: Contact maintainers for security issues

## 📄 License

By contributing to llmhq-promptops, you agree that your contributions will be licensed under the MIT License.

---

Thank you for contributing to llmhq-promptops! Your help makes this project better for everyone. 🙏