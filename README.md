# 🚀 llmhq-promptops

[![PyPI version](https://badge.fury.io/py/llmhq-promptops.svg)](https://badge.fury.io/py/llmhq-promptops)
[![Python Support](https://img.shields.io/pypi/pyversions/llmhq-promptops.svg)](https://pypi.org/project/llmhq-promptops/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A comprehensive prompt management and testing framework for production LLM workflows. Built for teams who need reliable, version-controlled prompt development with zero-manual versioning.

## ✨ Key Features

- **🔄 Automated Git Versioning** - Zero-manual versioning with git hooks and semantic version detection
- **📝 Uncommitted Change Testing** - Test prompts instantly with `:unstaged`, `:working`, `:latest` references
- **🐍 Python SDK Integration** - `pip install llmhq-promptops` for seamless app integration  
- **🧪 Version-Aware Testing** - Test different prompt versions with comprehensive validation
- **📊 Markdown Reports** - Automatic generation of version change documentation
- **⚙️ Git Hook Automation** - Pre-commit and post-commit hooks for seamless developer workflow

## 🚀 Quick Start

### Installation

```bash
pip install llmhq-promptops
```

### Initialize Your Project

```bash
# Create a new project with git hooks
promptops init repo

# Check installation
promptops --help
```

### Create Your First Prompt

```bash
# Create a new prompt template
promptops create prompt welcome-message

# Test uncommitted changes
promptops test --prompt welcome-message:unstaged

# Check status of all prompts
promptops test status
```

## 📖 Usage Examples

### Basic Prompt Resolution

```python
from llmhq_promptops import get_prompt

# Smart default (unstaged if different, else working)
prompt = get_prompt("user-onboarding") 

# Specific version references
prompt = get_prompt("user-onboarding:v1.2.1")    # Specific version
prompt = get_prompt("user-onboarding:unstaged")  # Test uncommitted changes
prompt = get_prompt("user-onboarding:working")   # Latest committed (HEAD)
prompt = get_prompt("user-onboarding:latest")    # Alias for working

# With variables
rendered = get_prompt("user-onboarding", {"user_name": "Alice", "plan": "Pro"})
print(rendered)
```

### Using with LLM Frameworks

```python
from llmhq_promptops import get_prompt

# Get versioned prompt for any LLM framework
prompt_text = get_prompt(
    "user-onboarding:working", 
    {"user_name": "John", "plan": "Enterprise"}
)

# Use with OpenAI
import openai
response = openai.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": prompt_text}]
)

# Use with Anthropic
import anthropic
client = anthropic.Anthropic()
response = client.messages.create(
    model="claude-3-sonnet-20240229",
    messages=[{"role": "user", "content": prompt_text}]
)

# Use with any other LLM framework
print(f"Prompt ready for LLM: {prompt_text}")
```

### Advanced Usage

```python
from llmhq_promptops import PromptManager

manager = PromptManager()

# Check if prompt has uncommitted changes
if manager.has_uncommitted_changes("user-onboarding"):
    # Test the latest changes
    rendered = manager.get_prompt("user-onboarding:unstaged", {"user_name": "Alice"})
else:
    # Use committed version
    rendered = manager.get_prompt("user-onboarding:working", {"user_name": "Alice"})

# Get prompt differences
diff = manager.get_prompt_diff("user-onboarding", "working", "unstaged")
print(diff)

# List all prompt statuses
statuses = manager.list_prompt_statuses()
for prompt_id, status in statuses.items():
    print(f"{prompt_id}: {status}")
```

## 🔧 CLI Commands

### Initialization & Setup
```bash
# Initialize project with interactive setup
promptops init repo --interactive

# Install git hooks for automatic versioning
promptops hooks install

# Check hook status
promptops hooks status
```

### Testing & Development
```bash
# Show status of all prompts
promptops test status

# Test specific version references
promptops test --prompt user-onboarding:unstaged
promptops test --prompt user-onboarding:working  
promptops test --prompt user-onboarding:v1.2.0

# Compare versions
promptops test diff user-onboarding --version1=working --version2=unstaged

# Test with custom variables
promptops test --prompt user-onboarding --variables '{"name": "Alice", "plan": "Pro"}'
```

### Hook Management
```bash
# Install automated versioning hooks
promptops hooks install

# Configure hook behavior
promptops hooks configure

# Check installation status
promptops hooks status

# Remove hooks
promptops hooks uninstall
```

## 📁 Project Structure

```
.promptops/
├── prompts/          # YAML prompt templates with metadata and auto-versioning
├── configs/          # LLM and environment configurations  
├── templates/        # Jinja2 template files
├── vars/             # Variable definition files
├── tests/            # Test datasets (JSON/YAML)
├── results/          # Generated test reports (markdown)
├── logs/             # LLM call logs and analytics
├── reports/          # Auto-generated version change reports
└── config.yaml       # Git hook configuration
```

## 📋 Prompt Schema

```yaml
# .promptops/prompts/user-onboarding.yaml
# Version automatically managed by git hooks
metadata:
  id: user-onboarding
  version: "1.2.0"  # Auto-incremented by pre-commit hook
  description: "User onboarding welcome message"
  tags: ["onboarding", "welcome"]
  
models:
  default: gpt-4-turbo
  supported: [gpt-4-turbo, claude-3-sonnet, llama2-70b]
  
template: |
  Welcome {{ user_name }}!
  Available features:
  {% for feature in features %}
  - {{ feature }}
  {% endfor %}
  
variables:
  user_name: {type: string, required: true}
  features: {type: list, default: ["Browse", "Purchase"]}
  
tests:
  - dataset: .promptops/tests/onboarding-data.json
    metrics: {max_tokens: 150, min_relevance: 0.8}
```

## 🔄 Automated Versioning

### Semantic Version Rules
- **PATCH** (1.0.0 → 1.0.1): Template content changes only
- **MINOR** (1.0.0 → 1.1.0): New variables added (backward compatible)
- **MAJOR** (1.0.0 → 2.0.0): Required variables removed (breaking change)

### Git Hook Workflow
1. **Developer edits prompt** → Changes saved to working directory
2. **Test uncommitted changes** → `promptops test --prompt name:unstaged`
3. **Git add & commit** → Pre-commit hook automatically:
   - Detects changed prompts
   - Analyzes changes for semantic versioning
   - Updates version numbers in YAML files
   - Re-stages updated files
4. **Commit completes** → Post-commit hook automatically:
   - Creates git tags for new versions
   - Runs validation tests
   - Generates audit logs

**Result**: Zero manual version management with instant testing capabilities.

## 🌟 Version References

| Reference | Description | Use Case |
|-----------|-------------|----------|
| `prompt-name` | Smart default (unstaged if different, else working) | Development |
| `:unstaged` | Uncommitted changes in working directory | Testing changes |
| `:working` | Latest committed version (HEAD) | Production |
| `:latest` | Alias for `:working` | Production |
| `:v1.2.3` | Specific semantic version | Reproducible builds |

## 🛠️ Requirements

- **Python**: 3.8+
- **Git**: Required for versioning
- **YAML**: For prompt template storage
- **Jinja2**: For template rendering

## 📚 Dependencies

- **Core**: Typer (CLI), Jinja2 (templating), PyYAML (parsing)
- **Git Integration**: GitPython (versioning)
- **Typing**: typing_extensions (Python 3.8 compatibility)

## 🤝 Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Development Setup

```bash
# Clone the repository
git clone https://github.com/your-org/llmhq-promptops.git
cd llmhq-promptops

# Install development dependencies
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt
pip install -e .

# Run tests
python -m pytest tests/

# Test CLI commands
promptops --help
```

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Built with [Typer](https://typer.tiangolo.com/) for CLI functionality
- Inspired by modern DevOps practices for infrastructure as code
- Designed for reliable prompt management in production applications

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/your-org/llmhq-promptops/issues)
- **Discussions**: [GitHub Discussions](https://github.com/your-org/llmhq-promptops/discussions)
- **Documentation**: [Full Documentation](https://your-org.github.io/llmhq-promptops/)

---

**Made with ❤️ for the LLM development community**