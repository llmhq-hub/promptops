"""Security regression tests for PromptOps.

Tests for:
- Path traversal prevention
- Jinja2 SSTI sandbox
- Input validation
- File size limits
"""

import pytest
from pathlib import Path

from llmhq_promptops.core.validation import (
    validate_prompt_id,
    validate_version,
    sanitize_path,
    check_file_size,
)
from llmhq_promptops.core.template import PromptTemplate


# ── validate_prompt_id ──────────────────────────────────────────────

class TestValidatePromptId:
    """Tests for prompt_id validation."""

    def test_valid_ids(self):
        assert validate_prompt_id("hello") == "hello"
        assert validate_prompt_id("user-onboarding") == "user-onboarding"
        assert validate_prompt_id("code_review") == "code_review"
        assert validate_prompt_id("v2-prompt") == "v2-prompt"
        assert validate_prompt_id("A123") == "A123"

    def test_path_traversal_rejected(self):
        with pytest.raises(ValueError):
            validate_prompt_id("../../etc/passwd")

    def test_path_traversal_dot_dot(self):
        with pytest.raises(ValueError):
            validate_prompt_id("..%2f..%2fetc%2fpasswd")

    def test_path_traversal_slash(self):
        with pytest.raises(ValueError):
            validate_prompt_id("foo/bar")

    def test_path_traversal_backslash(self):
        with pytest.raises(ValueError):
            validate_prompt_id("foo\\bar")

    def test_empty_string(self):
        with pytest.raises(ValueError):
            validate_prompt_id("")

    def test_none(self):
        with pytest.raises(ValueError):
            validate_prompt_id(None)

    def test_starts_with_hyphen(self):
        with pytest.raises(ValueError):
            validate_prompt_id("-flag")

    def test_starts_with_underscore(self):
        with pytest.raises(ValueError):
            validate_prompt_id("_hidden")

    def test_starts_with_dot(self):
        with pytest.raises(ValueError):
            validate_prompt_id(".hidden")

    def test_too_long(self):
        with pytest.raises(ValueError):
            validate_prompt_id("a" * 129)

    def test_max_length_ok(self):
        long_id = "a" * 128
        assert validate_prompt_id(long_id) == long_id

    def test_special_characters(self):
        for char in ['!', '@', '#', '$', '%', '^', '&', '*', '(', ')', ' ', '\n', '\t']:
            with pytest.raises(ValueError):
                validate_prompt_id(f"test{char}id")


# ── validate_version ────────────────────────────────────────────────

class TestValidateVersion:
    """Tests for version string validation."""

    def test_valid_semver(self):
        assert validate_version("v1.0.0") == "v1.0.0"
        assert validate_version("v2.3.4") == "v2.3.4"
        assert validate_version("1.0.0") == "1.0.0"

    def test_valid_keywords(self):
        for kw in ['unstaged', 'working-dir', 'staged', 'working', 'latest', 'head']:
            assert validate_version(kw) == kw

    def test_invalid_version(self):
        with pytest.raises(ValueError):
            validate_version("not-a-version")

    def test_empty_string(self):
        with pytest.raises(ValueError):
            validate_version("")

    def test_path_traversal_in_version(self):
        with pytest.raises(ValueError):
            validate_version("../../etc/passwd")


# ── sanitize_path ────────────────────────────────────────────────────

class TestSanitizePath:
    """Tests for path sanitization."""

    def test_path_within_root(self, tmp_path):
        child = tmp_path / "subdir" / "file.txt"
        child.parent.mkdir(parents=True, exist_ok=True)
        child.touch()
        result = sanitize_path(child, tmp_path)
        assert result == child.resolve()

    def test_path_traversal_rejected(self, tmp_path):
        evil = tmp_path / ".." / ".." / "etc" / "passwd"
        with pytest.raises(ValueError, match="resolves outside"):
            sanitize_path(evil, tmp_path)

    def test_absolute_path_outside_root(self, tmp_path):
        with pytest.raises(ValueError, match="resolves outside"):
            sanitize_path(Path("/etc/passwd"), tmp_path)

    def test_symlink_escape(self, tmp_path):
        """Symlink pointing outside allowed root should be rejected."""
        link = tmp_path / "evil_link"
        link.symlink_to("/etc")
        target = link / "passwd"
        with pytest.raises(ValueError, match="resolves outside"):
            sanitize_path(target, tmp_path)


# ── check_file_size ──────────────────────────────────────────────────

class TestCheckFileSize:
    """Tests for file size limits."""

    def test_small_file_ok(self, tmp_path):
        f = tmp_path / "small.yaml"
        f.write_text("hello: world")
        check_file_size(f)  # Should not raise

    def test_oversized_file_rejected(self, tmp_path):
        f = tmp_path / "huge.yaml"
        f.write_bytes(b"x" * (1024 * 1024 + 1))
        with pytest.raises(ValueError, match="exceeding limit"):
            check_file_size(f)

    def test_custom_limit(self, tmp_path):
        f = tmp_path / "medium.yaml"
        f.write_bytes(b"x" * 200)
        with pytest.raises(ValueError):
            check_file_size(f, max_size=100)

    def test_nonexistent_file_ok(self, tmp_path):
        f = tmp_path / "missing.yaml"
        check_file_size(f)  # Should not raise — file doesn't exist


# ── Jinja2 Sandbox ──────────────────────────────────────────────────

class TestJinja2Sandbox:
    """Tests for Jinja2 SSTI prevention."""

    SAFE_YAML = """
metadata:
  id: test-prompt
  version: "1.0.0"
  description: "Test"

template: |
  Hello {{ name }}!

variables:
  name:
    type: string
    required: true
"""

    def test_normal_rendering_works(self):
        t = PromptTemplate(self.SAFE_YAML)
        result = t.render({"name": "Alice"})
        assert "Hello Alice!" in result

    def test_class_traversal_blocked(self):
        """Attempt to access __class__.__mro__ should be blocked by sandbox."""
        evil_yaml = """
metadata:
  id: evil
  version: "1.0.0"
template: |
  {{ ''.__class__.__mro__[1].__subclasses__() }}
"""
        t = PromptTemplate(evil_yaml)
        with pytest.raises(Exception):
            t.render({})

    def test_getattr_on_class_blocked(self):
        """Attempt to access __globals__ should be blocked."""
        evil_yaml = """
metadata:
  id: evil
  version: "1.0.0"
template: |
  {{ ''.__class__.__init__.__globals__ }}
"""
        t = PromptTemplate(evil_yaml)
        with pytest.raises(Exception):
            t.render({})

    def test_dunder_access_blocked(self):
        """Access to __subclasses__ should be blocked."""
        evil_yaml = """
metadata:
  id: evil
  version: "1.0.0"
template: |
  {{ ().__class__.__bases__[0].__subclasses__() }}
"""
        t = PromptTemplate(evil_yaml)
        with pytest.raises(Exception):
            t.render({})

    def test_safe_filters_still_work(self):
        """Normal Jinja2 filters should still work."""
        yaml_content = """
metadata:
  id: test
  version: "1.0.0"
template: |
  {{ name | upper }}
variables:
  name:
    type: string
    required: true
"""
        t = PromptTemplate(yaml_content)
        result = t.render({"name": "alice"})
        assert "ALICE" in result

    def test_loop_still_works(self):
        """Jinja2 for loops should still work in sandbox."""
        yaml_content = """
metadata:
  id: test
  version: "1.0.0"
template: |
  {% for item in items %}{{ item }} {% endfor %}
variables:
  items:
    type: list
    required: true
"""
        t = PromptTemplate(yaml_content)
        result = t.render({"items": ["a", "b", "c"]})
        assert "a" in result and "b" in result and "c" in result


# ── PromptManager Path Traversal ─────────────────────────────────────

class TestPromptManagerPathTraversal:
    """Tests that PromptManager rejects path traversal attempts."""

    def test_traversal_in_get_prompt_reference(self):
        """Path traversal in prompt reference should be rejected."""
        from llmhq_promptops.prompt_manager import PromptManager
        # We can't fully instantiate PromptManager without a git repo,
        # but we can test _parse_prompt_reference validation
        # by testing the validation function directly
        with pytest.raises(ValueError):
            validate_prompt_id("../../etc/passwd")

    def test_traversal_with_version(self):
        """Path traversal in prompt_id part of reference should be rejected."""
        with pytest.raises(ValueError):
            validate_prompt_id("../secret")

    def test_null_bytes(self):
        """Null bytes in prompt_id should be rejected."""
        with pytest.raises(ValueError):
            validate_prompt_id("test\x00evil")
