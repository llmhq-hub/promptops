# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added (Phase 1.5a — M1: Resolver Protocol)
- New `core/resolver.py` module with `Resolver` Protocol (PEP 544 `@runtime_checkable`), `ResolvedPrompt` frozen dataclass (text + version + commit + resolved_at + source + prompt_id), and `GitResolver` implementation.
- `PromptManager.__init__` now accepts an optional `resolver=` keyword argument. Default is `GitResolver(repo_path)`, preserving v0.2.0 behavior.
- `PromptManager.resolve(prompt_reference)` returns a `ResolvedPrompt` with provenance metadata — for callers that need version/commit info (e.g., incident archaeology logging), not just a rendered string.
- Public exports: `Resolver`, `ResolvedPrompt`, `GitResolver`.

### Changed
- `PromptManager._validate_setup` no longer checks for git directly. Git presence validation now lives in `GitResolver.__init__`. This allows future resolvers (e.g., `SnapshotResolver` in M3) to validate their own backends, enabling production usage in Docker images without `.git/`.

### Fixed (Phase 1.5a — M2: Stable version identifiers)
- `GitVersioning._generate_version` no longer fabricates a position-based semver (`v1.0.0`, `v1.0.1`, …) for untagged commits. The previous fallback derived the version from a commit's index in `iter_commits` output, so the same commit's "version" would shift every time a new commit landed — directly breaking incident archaeology (`promptops blame --at <timestamp>`).
- Untagged commits now return a stable, immutable identifier of the form `commit-<8charsha>`. Tagged-commit behavior is unchanged. Lookup by short SHA continues to work, and lookup by the new `commit-<sha>` form also works.

### Added (Phase 1.5a — M2b: Retroactive version tagging)
- New `promptops migrate tag-history` CLI command. Walks each prompt's commit history (oldest first) and creates immutable per-prompt git tags of the form `prompt-<id>-v<X>.<Y>.<Z>`. This is the migration path for users moving off the pre-M2 fake-semver fallback: after tagging, `get_latest_version()` returns the real version instead of `commit-<sha>`. Options: `--prompt <id>` (single-prompt mode), `--dry-run`, `--start-version v0.1.0`. The command is idempotent — existing tags are skipped, not overwritten.
- `GitVersioning._get_tag_version` is now prompt-aware: per-prompt tags scoped to the resolved prompt take priority over legacy global `v1.2.3` tags. Both forms are still recognized.

### Tests
- New `tests/test_resolver.py` with 26 tests covering ResolvedPrompt roundtrip, Resolver Protocol structural typing, GitResolver constructor + all version references, PromptManager resolver injection, and backwards compatibility.
- New `tests/test_git_versioning.py` with 13 tests covering the M2 fix (commit-reference format, immutability across new commits, tagged-commit precedence, roundtrip via `get_prompt_at_version`) and the M2b per-prompt tag recognition (priority over legacy tags, scoping to the correct prompt, the no-`v`-prefix form).
- New `tests/test_migrate_cli.py` with 11 tests covering the `migrate tag-history` CLI: happy path (single prompt, all prompts, custom start version), idempotency, error paths (invalid version, invalid prompt id, non-git directory, empty prompts dir), and end-to-end integration with `GitVersioning.get_latest_version`.

## [0.2.0] - 2026-04-18

### Security
- Fixed Jinja2 Server-Side Template Injection (SSTI) — replaced `Environment` with `SandboxedEnvironment` to block class traversal attacks
- Fixed path traversal via unsanitized `prompt_id` in SDK and CLI — added strict input validation (`[a-zA-Z0-9][a-zA-Z0-9_-]*`)
- Fixed arbitrary code execution via `exec()` in hook test validation — replaced with `ast.parse()` syntax checking
- Fixed git argument injection via filenames starting with `--` — added `--` separators to git subprocess calls
- Fixed non-atomic file writes in pre-commit hook — now uses temp file + `os.replace()`
- Fixed TOCTOU race condition in hook installation backup

### Added
- Input validation module (`core/validation.py`) with `validate_prompt_id`, `validate_version`, `sanitize_path`, `check_file_size`
- 35 security regression tests (`tests/test_security.py`)

### Changed
- CLI `render` and `create` commands now validate file paths are within the working directory
- File reads now enforce a 1MB size limit to prevent memory exhaustion

## [0.1.0] - 2024-07-01

### Added
- 🚀 **Initial Release** - Core prompt management framework
- 🔄 **Automated Git Versioning** - Zero-manual versioning with git hooks
- 📝 **Version References** - Support for `:unstaged`, `:working`, `:latest`, `:v1.2.3` references
- 🐍 **Python SDK** - Complete SDK for prompt resolution and management
- 🔧 **CLI Framework** - Comprehensive command-line interface
- ⚙️ **Git Hooks** - Pre-commit and post-commit automation
- 📊 **Markdown Reports** - Automated version change documentation
- 🧪 **Testing Framework** - Prompt validation and testing capabilities

### Features

#### Core SDK
- `PromptManager` - Central prompt resolution and management
- `GitVersioning` - Git-based version control and file state detection  
- `PromptTemplate` - YAML parsing and Jinja2 template rendering
- `SemanticVersionDetector` - Automated MAJOR/MINOR/PATCH analysis

#### CLI Commands
- `promptops init repo` - Project initialization with automatic hook setup
- `promptops test status` - Show all prompt states and version information
- `promptops test diff` - Compare versions with detailed output
- `promptops test runtest` - Version-aware prompt testing
- `promptops hooks install/status/configure` - Git hook management
- `promptops create prompt` - New prompt template creation

#### Git Integration
- **Pre-commit Hook** - Automatic version detection and updating
- **Post-commit Hook** - Git tagging and report generation
- **Semantic Versioning** - Intelligent change analysis
- **File State Tracking** - Working/staged/committed state detection

#### SDK Features
- **Version-aware Resolution** - Smart default version selection
- **Variable Validation** - Type checking and required field validation
- **Framework Agnostic** - Works with any LLM framework (OpenAI, Anthropic, etc.)

### Technical Details
- **Python Support**: 3.8+
- **Dependencies**: Minimal core dependencies (Typer, Jinja2, PyYAML, GitPython)
- **License**: MIT
- **Package Format**: Modern Python packaging with pyproject.toml

### Documentation
- Comprehensive README with usage examples
- CLI help documentation for all commands
- SDK API documentation with type hints
- Git workflow integration guides

### Known Issues
- Rich formatting disabled in CLI help to ensure compatibility across environments
- Some LLM provider integrations require optional dependencies

---

## Release Notes

### v0.1.0 - Foundation Release
This initial release establishes the core architecture for git-native prompt management. The focus is on reliability, automation, and developer experience.

**Key Achievement**: Zero-manual versioning workflow where developers can commit prompt changes and have versions automatically detected, updated, and tagged without any manual intervention.

**Next Planned Features**:
- Framework adapters (LangChain, LangGraph)
- Multi-LLM testing and comparison
- Advanced analytics and reporting  
- CI/CD pipeline integrations

### Migration Guide
This is the initial release - no migration needed.

### Upgrade Instructions
Install with pip:
```bash
pip install llmhq-promptops
```

For development:
```bash
git clone https://github.com/llmhq-hub/promptops.git
cd llmhq-promptops
pip install -e .
```