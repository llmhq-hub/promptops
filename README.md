# 🚀 llmhq-promptops

[![PyPI version](https://img.shields.io/pypi/v/llmhq-promptops.svg)](https://pypi.org/project/llmhq-promptops/)
[![Python Support](https://img.shields.io/pypi/pyversions/llmhq-promptops.svg)](https://pypi.org/project/llmhq-promptops/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Downloads](https://img.shields.io/pypi/dm/llmhq-promptops.svg)](https://pypi.org/project/llmhq-promptops/)

**Git blame for prompts.** When prod breaks, know exactly which prompt version was running, in seconds. No SaaS, no vendor lock-in — all in your own git.

`llmhq-promptops` is a prompt management framework that records every deploy, builds an immutable snapshot at CI time, and lets you ask `promptops blame --at <timestamp>` to find out what was running when an incident happened. Built for teams who already use git for everything else.

## ✨ Key Features

- **🔎 Incident archaeology** — `promptops blame --at <ts>` resolves "what prompt was running in prod at that moment" by composing the deploy log with git history.
- **🐳 Production runtime without `.git/`** — `promptops snapshot build` writes a self-contained `.promptops/snapshot.json`. Ship that in your Docker image; `AutoResolver` picks it up automatically.
- **📒 Deploy event log** — append-only `.promptops/deploys.jsonl` records every deploy with provenance (env, commit, actor, metadata). Committed to git alongside your prompts.
- **🔄 Automated git versioning** — Pre-commit hook detects prompt changes, bumps semver in YAML metadata, re-stages.
- **📝 Version-aware testing** — `:unstaged`, `:working`, `:latest`, `commit-<sha>`, or any tag.
- **🐍 Python SDK** — `PromptManager(resolver=AutoResolver())` works the same in dev (uses git) and prod (uses snapshot).

## ⚡ Quick Start

Two paths depending on what you want to do.

### Path A — 60-second demo on a sample repo

Walk through the incident-archaeology flow on a pre-baked repo, no setup of your own.

```bash
pip install llmhq-promptops

git clone https://github.com/llmhq-hub/promptops.git
cd promptops/examples/incident-archaeology-demo
./setup.sh                       # builds a tmp git repo with pre-baked history
cd /tmp/promptops-demo

# 1. Look at what's been deployed
promptops deploy list

# 2. "Production broke at 10:00 UTC. What was running?"
promptops blame --at 2026-05-20T10:00:00Z

# 3. Same question, full text of one prompt
promptops blame --at 2026-05-20T10:00:00Z --prompt summarizer
```

That's the hero use case. Three commands, one provable answer.

> Full walkthrough + screencast script: [`examples/incident-archaeology-demo/README.md`](examples/incident-archaeology-demo/README.md)

### Path B — Try it on your own repo

For when you want to add this to a real project.

```bash
pip install llmhq-promptops

cd <your-project>                # any git repo
promptops init repo              # creates .promptops/ directory
promptops hooks install          # opt-in: auto-version on commit

# Write a prompt
promptops create prompt user-onboarding

# Render it
python -c "from llmhq_promptops import get_prompt; print(get_prompt('user-onboarding', {'name': 'World'}))"

# Record a deploy and look it up later
promptops deploy event --env prod -m release=v0.1.0
promptops blame --at "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
```

## 📖 Usage Examples

### Recommended production setup

```python
from llmhq_promptops import PromptManager, AutoResolver

# Same code in dev (uses .git/) and prod (uses .promptops/snapshot.json)
manager = PromptManager(resolver=AutoResolver(repo_path="."))

prompt = manager.get_prompt("user-onboarding", {"name": "Alice"})
```

### Resolving with full provenance

When you need to know *which* version actually ran (for logging, observability):

```python
resolved = manager.resolve("user-onboarding")
# resolved.text       — raw YAML
# resolved.version    — e.g. "v1.2.3" or "commit-abc12345"
# resolved.commit     — full 40-char SHA
# resolved.source     — "git" or "snapshot"
# resolved.resolved_at — tz-aware UTC datetime

log_to_observability({
    "prompt": resolved.prompt_id,
    "version": resolved.version,
    "commit": resolved.commit,
    "source": resolved.source,
})
```

### Specific versions

```python
from llmhq_promptops import get_prompt

prompt = get_prompt("user-onboarding")                    # smart default
prompt = get_prompt("user-onboarding:v1.2.1")             # tagged version
prompt = get_prompt("user-onboarding:commit-abc12345")    # untagged commit
prompt = get_prompt("user-onboarding:unstaged")           # working tree
prompt = get_prompt("user-onboarding:working")            # HEAD (committed)
```

### Using with LLM frameworks

```python
from llmhq_promptops import get_prompt

prompt = get_prompt("user-onboarding:working", {"name": "John"})

# OpenAI
import openai
openai.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": prompt}],
)

# Anthropic
import anthropic
anthropic.Anthropic().messages.create(
    model="claude-3-sonnet-20240229",
    messages=[{"role": "user", "content": prompt}],
)
```

## 🔧 CLI Commands

| Command group | What it does |
|---|---|
| `promptops init repo` | Create `.promptops/` directory structure |
| `promptops hooks install` | Opt-in auto-versioning hooks (pre-commit + post-commit) |
| `promptops create prompt <id>` | Scaffold a new prompt YAML |
| `promptops render prompt <file>` | Render a prompt with variables |
| `promptops test status` / `test diff` / `test runtest` | Version-aware prompt testing |
| `promptops deploy event --env <e>` | Append a deploy event to `.promptops/deploys.jsonl` |
| `promptops deploy list` | Show recent deploys, newest first |
| `promptops snapshot build` | Write `.promptops/snapshot.json` (production-runtime artifact) |
| `promptops snapshot inspect` | Print contents of a snapshot |
| `promptops blame --at <ts>` | Incident archaeology: what was running when? |
| `promptops backfill-deploys --from-git-log` | Seed the deploy log from existing git history |
| `promptops migrate tag-history` | Create per-prompt git tags for historical commits |

Full help: `promptops --help` or `promptops <command> --help`.

## 📁 Project Structure

```
.promptops/
├── prompts/           # YAML prompt templates (auto-versioned)
├── deploys.jsonl      # Append-only deploy event log (committed to git)
├── snapshot.json      # Production-runtime snapshot (built at CI time)
├── config.yaml        # Hook + tool configuration
├── tests/             # Test datasets
├── results/           # Test reports
├── logs/              # Audit logs
└── reports/           # Auto-generated version change notes
```

## 📋 Prompt Schema

```yaml
# .promptops/prompts/user-onboarding.yaml
metadata:
  id: user-onboarding
  version: "1.2.0"            # Auto-incremented by pre-commit hook
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
  features:  {type: list,   default: ["Browse", "Purchase"]}

tests:
  - dataset: .promptops/tests/onboarding-data.json
    metrics: {max_tokens: 150, min_relevance: 0.8}
```

## 🔄 Automated Versioning

Semantic version rules applied by the pre-commit hook:

- **PATCH** (1.0.0 → 1.0.1) — template content changes only
- **MINOR** (1.0.0 → 1.1.0) — new variables added (backwards compatible)
- **MAJOR** (1.0.0 → 2.0.0) — required variables removed (breaking change)

**Workflow:**

1. Edit a prompt → changes in working tree
2. `promptops test --prompt name:unstaged` (test before commit)
3. `git add` + `git commit` → pre-commit hook bumps version and re-stages
4. Post-commit hook tags the new version and generates a changelog entry

Zero manual version management.

## 🌟 Version References

| Reference | Resolves to | Use case |
|-----------|-------------|----------|
| `prompt-name` | Smart default (unstaged if different, else working) | Development |
| `:unstaged` | Uncommitted working-tree content | Testing changes before commit |
| `:working` / `:latest` / `:head` | Latest committed (HEAD) | Production |
| `:v1.2.3` | Specific semver tag | Reproducible builds |
| `:commit-abc12345` | Immutable commit reference for untagged commits | Incident archaeology |

## 🛠️ Requirements

- Python 3.8+
- Git (for versioning at dev time — **not** required at production runtime if you ship `snapshot.json`)
- YAML + Jinja2 (auto-installed)

## 📚 Dependencies

- **Core:** Typer (CLI), Jinja2 (templates), PyYAML (parsing), GitPython (git access)
- **Compatibility:** typing_extensions (Python 3.8)

## 🤝 Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

```bash
git clone https://github.com/llmhq-hub/promptops.git
cd promptops
python -m venv venv
source venv/bin/activate
pip install -e .
pip install pytest
pytest tests/ --ignore=tests/test_versioning.py --ignore=tests/test_langchain.py
```

## 📄 License

MIT — see [LICENSE](LICENSE).

## 📞 Support

- **Issues:** [github.com/llmhq-hub/promptops/issues](https://github.com/llmhq-hub/promptops/issues)
- **Discussions:** [github.com/llmhq-hub/promptops/discussions](https://github.com/llmhq-hub/promptops/discussions)
- **Releases & changelog:** [github.com/llmhq-hub/promptops/releases](https://github.com/llmhq-hub/promptops/releases)

---

**Made with ❤️ for teams shipping LLMs in production.**
