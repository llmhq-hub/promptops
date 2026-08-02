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
- **🔄 Automated git versioning** *(opt-in)* — after `promptops hooks install`, a pre-commit hook detects prompt changes, bumps semver in YAML metadata, and re-stages. `promptops init repo` never touches `.git/hooks/` on its own.
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

> Full walkthrough + screencast script: [`examples/incident-archaeology-demo/README.md`](https://github.com/llmhq-hub/promptops/blob/main/examples/incident-archaeology-demo/README.md)

### Path B — Try it on your own repo

For when you want to add this to a real project.

```bash
pip install llmhq-promptops

cd <your-project>                # any git repo
promptops init repo              # creates .promptops/ (does NOT touch git hooks)

# Scaffold your first prompt → .promptops/prompts/user-onboarding.yaml
promptops create prompt user-onboarding

# Render it (the starter template uses {{ user_input }}; :unstaged reads
# your uncommitted working-tree edits)
python -c "from llmhq_promptops import get_prompt; print(get_prompt('user-onboarding:unstaged', {'user_input': 'World'}))"

# Record a deploy and look it up later
promptops deploy event --env prod -m release=v0.1.0
promptops blame --at now

# Optional: enable auto-versioning on commit (opt-in since v0.4.0)
promptops hooks install
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
| `promptops history <id>` | Every version a prompt has been, and what shipped each one |
| `promptops doctor` | Health check: hooks, snapshot freshness, deploy log, versions, resolver |
| `promptops backfill-deploys --from-git-log` | Seed the deploy log from existing git history |
| `promptops migrate tag-history` | Create per-prompt git tags for historical commits |

Full help: `promptops --help` or `promptops <command> --help`.

## 📗 Guides

| Guide | Read it when |
|---|---|
| [Day 0 Incident Playbook](https://github.com/llmhq-hub/promptops/blob/main/docs/day-0-playbook.md) | Something went wrong in production and you need to know which prompt did it |
| [Production Deployment](https://github.com/llmhq-hub/promptops/blob/main/docs/production-deployment.md) | You are wiring the snapshot pipeline, Docker, and CI |
| [Migrating from Hardcoded Prompts](https://github.com/llmhq-hub/promptops/blob/main/docs/migration-from-hardcoded-prompts.md) | You have prompts in string literals today |
| [Error Codes](https://github.com/llmhq-hub/promptops/blob/main/docs/error-codes.md) | You hit a `PROMPTOPS_E0XX` and want the fix |
| [Migration v0.5 to v0.6](https://github.com/llmhq-hub/promptops/blob/main/docs/migration-v0.5-to-v0.6.md) | You are upgrading to v0.6.0 (the git hooks were broken from v0.2.0 to v0.5.0) |
| [Migration v0.4 to v0.5](https://github.com/llmhq-hub/promptops/blob/main/docs/migration-v0.4-to-v0.5.md) | You are upgrading to v0.5.0 (one break fails silently) |
| [Migration v0.3 to v0.4](https://github.com/llmhq-hub/promptops/blob/main/docs/migration-v0.3-to-v0.4.md) | You are upgrading across the breaking release |

Runnable examples live in [`examples/`](https://github.com/llmhq-hub/promptops/tree/main/examples/), including Docker,
GitHub Actions, hook lifecycle, error handling, and FastAPI.

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

PromptOps reads two interchangeable layouts. `promptops create prompt`
scaffolds the compact `prompt:` form; the richer `metadata:` form below
adds tags, multiple models, and inline tests. Both are parsed the same way.

**Extended (`metadata:`) format:**

```yaml
# .promptops/prompts/user-onboarding.yaml
metadata:
  id: user-onboarding
  version: "1.2.0"            # auto-incremented once you run `promptops hooks install`
  description: "User onboarding welcome message"
  tags: ["onboarding", "welcome"]
  models:                    # NOTE: nested under metadata
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

**Compact (`prompt:`) format** — what `promptops create prompt` generates:

```yaml
# .promptops/prompts/user-onboarding.yaml
prompt:
  id: user-onboarding
  description: "User onboarding welcome message"
  model: gpt-4-turbo
  template: "Welcome {{ user_name }}!"
variables:
  user_name: {type: string, required: true}
```

## 🔄 Automated Versioning

Automated versioning is **opt-in** — enable it once per repo with
`promptops hooks install`. (Since v0.4.0, `promptops init repo` never
modifies `.git/hooks/` on its own.)

The pre-commit hook grades a change from its **variable signature** and declared
models, never from prose. It uses the same engine as `promptops test diff`, so
a change graded MAJOR in review is versioned MAJOR on commit:

| Change | Impact |
|---|---|
| Required variable added, removed, renamed, or retyped | **MAJOR** (1.2.0 → 2.0.0) |
| Optional variable promoted to required | **MAJOR** |
| Declared model removed | **MAJOR** |
| Optional variable added or removed | **MINOR** (1.2.0 → 1.3.0) |
| Required variable relaxed to optional | **MINOR** |
| Model added, or an optional variable's default changed | **MINOR** |
| Prose changed, signature identical | **PATCH** (1.2.0 → 1.2.1) |
| Nothing a caller depends on moved | **no bump** |

A brand-new prompt keeps the version you declared: there is nothing for a first
commit to be backward incompatible with.

**Workflow** (after `promptops hooks install`):

1. Edit a prompt → changes in working tree
2. `promptops test diff name` (see the impact before you commit)
3. `git add` + `git commit` → pre-commit hook bumps the version line and re-stages
4. Post-commit hook tags it `prompt-<id>-v<version>` and validates it

The bump rewrites the version line and nothing else, so comments and
`template: |` formatting survive. `promptops doctor` verifies the hooks can
actually run, not merely that they are installed.

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

- Python 3.10+
- Git (for versioning at dev time — **not** required at production runtime if you ship `snapshot.json`)
- YAML + Jinja2 (auto-installed)

## 📚 Dependencies

- **Core:** Typer (CLI), Jinja2 (templates), PyYAML (parsing), GitPython (git access)

## 🤝 Contributing

See [CONTRIBUTING.md](https://github.com/llmhq-hub/promptops/blob/main/CONTRIBUTING.md).

```bash
git clone https://github.com/llmhq-hub/promptops.git
cd promptops
python -m venv venv
source venv/bin/activate
pip install -e .
pip install pytest
pytest tests/
```

## 📄 License

MIT — see [LICENSE](https://github.com/llmhq-hub/promptops/blob/main/LICENSE).

## 📞 Support

- **Issues:** [github.com/llmhq-hub/promptops/issues](https://github.com/llmhq-hub/promptops/issues)
- **Discussions:** [github.com/llmhq-hub/promptops/discussions](https://github.com/llmhq-hub/promptops/discussions)
- **Releases & changelog:** [github.com/llmhq-hub/promptops/releases](https://github.com/llmhq-hub/promptops/releases)

---

**Made with ❤️ for teams shipping LLMs in production.**
