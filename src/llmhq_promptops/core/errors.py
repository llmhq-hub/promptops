"""Tier 2 error system for PromptOps (M9, v0.4.0).

Every user-facing error carries four fields:

- ``code``    — stable ``PROMPTOPS_E0XX`` identifier, safe to grep / alert on
- ``message`` — what went wrong, with concrete values interpolated
- ``hint``    — the next command or action that most likely fixes it
- ``doc_url`` — deep link into ``docs/error-codes.md`` for the full writeup

``PromptOpsError`` subclasses ``ValueError`` deliberately: every pre-v0.4.0
caller that wrote ``except ValueError`` keeps working unchanged, and every
existing test that does ``pytest.raises(ValueError, match=...)`` still
passes because the original message text is preserved inside ``str(e)``.

Code registry (authoritative copy lives in ``docs/error-codes.md``):

    E001  NOT_INITIALIZED            .promptops/ directory missing
    E002  NO_PROMPT_SOURCE           neither prompts/ nor snapshot.json
    E003  PROMPT_NOT_FOUND           prompt id unknown to the resolver
    E004  VERSION_NOT_FOUND          version not resolvable from this source
    E005  GIT_REQUIRED               operation needs .git/ and it's absent
    E006  SNAPSHOT_MISSING           snapshot.json required but not found
    E007  SNAPSHOT_INVALID           snapshot.json unreadable or malformed
    E008  SNAPSHOT_SCHEMA_MISMATCH   snapshot built by incompatible version
    E009  RESOLVER_UNAVAILABLE       AutoResolver found neither backend
    E010  INVALID_PROMPT_ID          prompt id fails validation rules
    E011  NO_DEPLOY_EVENTS           blame/history with empty deploy log
    E012  TEMPLATE_INCLUDE_UNSUPPORTED  (reserved — jinja include scan)
    E013  INVALID_VERSION_SPEC       version string fails validation rules
    E014  RENDER_FAILED              Jinja2 render raised
    E015  PARSE_FAILED               prompt YAML failed to parse
    E016  INVALID_DEPLOY_EVENT       DeployEvent field validation failed
    E017  NAIVE_TIMESTAMP            timezone-naive datetime where aware required
"""

from __future__ import annotations

from typing import Optional


DOC_BASE_URL = (
    "https://github.com/llmhq-hub/promptops/blob/main/docs/error-codes.md"
)

# Stable error-code constants. Names describe the condition; values are the
# greppable wire format. New codes append — never renumber an existing one.
E001_NOT_INITIALIZED = "PROMPTOPS_E001"
E002_NO_PROMPT_SOURCE = "PROMPTOPS_E002"
E003_PROMPT_NOT_FOUND = "PROMPTOPS_E003"
E004_VERSION_NOT_FOUND = "PROMPTOPS_E004"
E005_GIT_REQUIRED = "PROMPTOPS_E005"
E006_SNAPSHOT_MISSING = "PROMPTOPS_E006"
E007_SNAPSHOT_INVALID = "PROMPTOPS_E007"
E008_SNAPSHOT_SCHEMA_MISMATCH = "PROMPTOPS_E008"
E009_RESOLVER_UNAVAILABLE = "PROMPTOPS_E009"
E010_INVALID_PROMPT_ID = "PROMPTOPS_E010"
E011_NO_DEPLOY_EVENTS = "PROMPTOPS_E011"
E012_TEMPLATE_INCLUDE_UNSUPPORTED = "PROMPTOPS_E012"  # reserved, not raised yet
E013_INVALID_VERSION_SPEC = "PROMPTOPS_E013"
E014_RENDER_FAILED = "PROMPTOPS_E014"
E015_PARSE_FAILED = "PROMPTOPS_E015"
E016_INVALID_DEPLOY_EVENT = "PROMPTOPS_E016"
E017_NAIVE_TIMESTAMP = "PROMPTOPS_E017"


class PromptOpsError(ValueError):
    """Structured PromptOps error: code + message + hint + doc_url.

    Subclasses ``ValueError`` so pre-v0.4.0 ``except ValueError`` handlers
    and ``pytest.raises(ValueError, match=...)`` assertions keep working.

    ``str(e)`` renders all fields::

        [PROMPTOPS_E003] Prompt 'foo' not found at version 'v1.0.0'. ...
        Hint: Run 'promptops test status' to see available prompts.
        Docs: https://github.com/llmhq-hub/promptops/.../error-codes.md#promptops_e003
    """

    def __init__(
        self,
        code: str,
        message: str,
        hint: Optional[str] = None,
        doc_url: Optional[str] = None,
    ):
        self.code = code
        self.message = message
        self.hint = hint
        self.doc_url = (
            doc_url if doc_url is not None else f"{DOC_BASE_URL}#{code.lower()}"
        )
        super().__init__(self._render())

    def _render(self) -> str:
        parts = [f"[{self.code}] {self.message}"]
        if self.hint:
            parts.append(f"Hint: {self.hint}")
        parts.append(f"Docs: {self.doc_url}")
        return "\n".join(parts)

    def to_dict(self) -> dict:
        """Serializable shape, e.g. for ``--json`` CLI output."""
        return {
            "code": self.code,
            "message": self.message,
            "hint": self.hint,
            "doc_url": self.doc_url,
        }
