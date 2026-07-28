# 📚 llmhq-promptops Examples

This directory contains practical examples demonstrating how to use llmhq-promptops in various scenarios.

## Pick an example

| Example | Answers | Runnable |
| --- | --- | --- |
| [`incident-archaeology-demo/`](incident-archaeology-demo/) | "What prompt was running when this incident started?" | `./setup.sh` |
| [`docker-snapshot/`](docker-snapshot/) | "How do I resolve prompts in a container with no `.git/`?" | `./build.sh` |
| [`github-actions/`](github-actions/) | "How do I see a prompt's blast radius on every PR?" | copy the workflow |
| [`hooks-lifecycle/`](hooks-lifecycle/) | "What do the git hooks do, and how do I turn them off?" | `./run.sh` |
| [`error-handling/`](error-handling/) | "What should I catch, and how do I branch on error codes?" | `python main.py` |
| [`fastapi-service/`](fastapi-service/) | "How do I wire this into a long-lived web service?" | own `requirements.txt` |
| [`basic_usage.py`](basic_usage.py) | "What does the SDK surface look like?" | `python basic_usage.py` |

Everything except `fastapi-service/` runs with only `llmhq-promptops`
installed. `fastapi-service/` carries its own `requirements.txt` so the
package itself stays lean.

## 🚀 Quick Start

1. **Install llmhq-promptops**
   ```bash
   pip install llmhq-promptops
   ```

2. **Initialize a test project**
   ```bash
   mkdir promptops-examples
   cd promptops-examples
   git init
   promptops init repo
   ```

3. **Create sample prompts**
   ```bash
   promptops create prompt welcome-message
   promptops create prompt user-onboarding
   ```

4. **Run the examples**

   `basic_usage.py` lives in the cloned repo, so run it from there (its
   template-rendering and error-handling sections work in any directory;
   the resolution sections expect a `welcome-message` prompt like the one
   you just created):
   ```bash
   git clone https://github.com/llmhq-hub/promptops.git
   python promptops/examples/basic_usage.py
   ```

## 📋 Example Files

### [`basic_usage.py`](basic_usage.py)
**Core SDK functionality examples**
- Basic prompt resolution with version references
- PromptManager advanced usage
- Version management and status checking
- Template rendering with variable validation
- Error handling patterns

**Key demonstrations:**
```python
# Version references
get_prompt("prompt:working")     # Latest committed
get_prompt("prompt:unstaged")    # Uncommitted changes
get_prompt("prompt:v1.2.3")     # Specific version

# Status checking
manager.has_uncommitted_changes("prompt")
manager.get_prompt_diff("prompt", "working", "unstaged")
```


## 🛠️ Running Examples

### Prerequisites
```bash
# Core examples
pip install llmhq-promptops
```

### Setup Test Environment
```bash
# Create test directory
mkdir test-promptops && cd test-promptops

# Initialize git and promptops
git init
git config user.name "Test User"
git config user.email "test@example.com"
promptops init repo

# Create sample prompts
promptops create prompt welcome-message
promptops create prompt user-onboarding

# Edit the created prompts in .promptops/prompts/ as needed
```

### Example Prompt Content

**`.promptops/prompts/welcome-message.yaml`** — `promptops create prompt
welcome-message` scaffolds a starter using `{{ user_input }}`; edit it to
taste. (`basic_usage.py` resolves this prompt with a `user_input`
variable.)
```yaml
prompt:
  id: welcome-message
  description: "Welcome message for new users"
  model: gpt-4-turbo
  template: |
    You are a helpful assistant.

    {{ user_input }}
variables:
  user_input: {type: string, required: true}
```

**`.promptops/prompts/user-onboarding.yaml`**
```yaml
metadata:
  id: user-onboarding
  version: "1.0.0"
  description: "User onboarding flow"

template: |
  Welcome {{ user_name }}!
  {% if plan %}
  You are subscribed to the {{ plan }} plan.
  {% endif %}
  
  Available features:
  {% for feature in features %}
  - {{ feature }}
  {% endfor %}

variables:
  user_name: {type: string, required: true}
  plan: {type: string, required: false}
  features: {type: list, default: ["Basic Feature"]}
```

## 🔧 Advanced Examples

### Version Testing Workflow
```python
from llmhq_promptops import PromptManager

manager = PromptManager()

# Test development workflow
print("Testing development changes...")
unstaged = manager.get_prompt("prompt:unstaged", {"user": "Alice"})

# Commit and test
# git add . && git commit -m "Update prompt"
working = manager.get_prompt("prompt:working", {"user": "Alice"})

# Compare versions
diff = manager.get_prompt_diff("prompt", "working", "unstaged")
```

### Production Integration
```python
import os
from llmhq_promptops import get_prompt

# Environment-aware prompt selection
env = os.getenv("ENVIRONMENT", "development")
version_map = {
    "development": "unstaged",  # Test latest changes
    "staging": "working",       # Use committed version
    "production": "latest"      # Use stable version
}

prompt = get_prompt(f"prompt:{version_map[env]}", variables)
```

## 🐛 Troubleshooting

### Common Issues

**"PromptOps not initialized"**
```bash
# Ensure you're in a git repo with .promptops/
git init
promptops init repo
```

**"Prompt not found"**
```bash
# Check available prompts
promptops test status
ls .promptops/prompts/
```

**"Required variable not provided"**
```python
# Check which variables a prompt requires. Note: get_template takes the
# id and version as SEPARATE arguments (it does not parse "id:version"
# like get_prompt does), and required vars come from the .variables dict.
from llmhq_promptops import get_template
template = get_template("welcome-message", "working")
required = [name for name, v in template.variables.items() if v.required]
print("Required:", required)
```


### Debug Mode

Enable verbose logging for troubleshooting:
```python
import logging
logging.basicConfig(level=logging.DEBUG)

from llmhq_promptops import get_prompt
# Now shows detailed resolution steps
```

## 🚀 Next Steps

1. **Create your own prompts**: Use `promptops create prompt` to add prompts for your use case
2. **Set up git hooks**: Use `promptops hooks install` for automatic versioning
3. **Integrate with your code**: Use the SDK for prompt resolution in your applications
4. **Deploy to production**: Use version references for environment-specific deployments

## 📖 More Resources

- **Main Documentation**: [README.md](../README.md)
- **Contributing**: [CONTRIBUTING.md](../CONTRIBUTING.md)
- **Changelog**: [CHANGELOG.md](../CHANGELOG.md)
- **CLI Reference**: Run `promptops --help` for all commands

---

**Happy prompting! 🎯**