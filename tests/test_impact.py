"""Tests for ``core/impact.py`` — semver impact of a prompt change (v0.5.0).

Impact is derived from the prompt's *variable signature* plus its declared
models, never from prose. That is the only part of a prompt with a
caller-facing contract, so it is the only part that can be graded without
guessing at intent.

Note on auto-detected variables: ``PromptTemplate.variables`` merges variables
referenced in the template body but never declared in YAML, defaulting them to
required (see ``core/template.py``). That merged set is the effective contract
PromptOps itself enforces in ``validate_variables``, so it is what we grade.
"""

from __future__ import annotations

import pytest

from llmhq_promptops.core.impact import (
    ImpactReport,
    SemverImpact,
    compute_impact,
)
from llmhq_promptops.core.template import PromptTemplate


def _tpl(
    body: str = "Hello, {{ name }}!",
    variables: str = "  name:\n    type: string\n    required: true\n",
    models: str = "    default: gpt-4-turbo\n",
) -> PromptTemplate:
    """Build a PromptTemplate from parts, using the metadata: schema."""
    yaml_text = (
        "metadata:\n"
        "  id: hello\n"
        "  description: Prompt under test\n"
        "  models:\n" + models + "template: |\n"
        + "".join(f"  {line}\n" for line in body.splitlines())
        + "variables:\n" + variables
    )
    return PromptTemplate(yaml_text)


REQUIRED_NAME = "  name:\n    type: string\n    required: true\n"


# ── ordering ────────────────────────────────────────────────────────


class TestSemverImpactOrdering:
    def test_severity_is_ordered(self):
        assert (
            SemverImpact.NONE
            < SemverImpact.PATCH
            < SemverImpact.MINOR
            < SemverImpact.MAJOR
        )

    def test_max_picks_the_most_severe(self):
        assert max(SemverImpact.PATCH, SemverImpact.MAJOR) is SemverImpact.MAJOR


# ── NONE and PATCH ──────────────────────────────────────────────────


class TestNoChangeAndProse:
    def test_identical_templates_are_none(self):
        report = compute_impact(_tpl(), _tpl())
        assert report.impact is SemverImpact.NONE
        assert report.changes == ()

    def test_prose_only_change_is_patch(self):
        report = compute_impact(
            _tpl(body="Hello, {{ name }}!"),
            _tpl(body="Hi there, {{ name }}!"),
        )
        assert report.impact is SemverImpact.PATCH

    def test_whitespace_only_change_is_patch(self):
        report = compute_impact(
            _tpl(body="Hello, {{ name }}!"),
            _tpl(body="Hello,  {{ name }}!"),
        )
        assert report.impact is SemverImpact.PATCH


# ── MAJOR ───────────────────────────────────────────────────────────


class TestMajorChanges:
    def test_required_variable_added(self):
        report = compute_impact(
            _tpl(),
            _tpl(
                body="Hello, {{ name }} of {{ tier }}!",
                variables=REQUIRED_NAME
                + "  tier:\n    type: string\n    required: true\n",
            ),
        )
        assert report.impact is SemverImpact.MAJOR
        assert any("tier" in c.detail for c in report.changes)

    def test_required_variable_removed(self):
        report = compute_impact(
            _tpl(
                body="Hello, {{ name }} of {{ tier }}!",
                variables=REQUIRED_NAME
                + "  tier:\n    type: string\n    required: true\n",
            ),
            _tpl(),
        )
        assert report.impact is SemverImpact.MAJOR

    def test_variable_type_changed(self):
        report = compute_impact(
            _tpl(variables="  name:\n    type: string\n    required: true\n"),
            _tpl(variables="  name:\n    type: dict\n    required: true\n"),
        )
        assert report.impact is SemverImpact.MAJOR
        assert any(
            "string" in c.detail and "dict" in c.detail for c in report.changes
        )

    def test_optional_promoted_to_required(self):
        optional = "  name:\n    type: string\n    required: false\n"
        report = compute_impact(_tpl(variables=optional), _tpl())
        assert report.impact is SemverImpact.MAJOR

    def test_declared_model_removed(self):
        two = "    default: gpt-4-turbo\n    supported:\n      - gpt-4-turbo\n      - claude-3\n"
        one = "    default: gpt-4-turbo\n    supported:\n      - gpt-4-turbo\n"
        report = compute_impact(_tpl(models=two), _tpl(models=one))
        assert report.impact is SemverImpact.MAJOR
        assert any("claude-3" in c.detail for c in report.changes)

    def test_renaming_a_required_variable_is_major(self):
        report = compute_impact(
            _tpl(body="Hi {{ name }}", variables=REQUIRED_NAME),
            _tpl(
                body="Hi {{ username }}",
                variables="  username:\n    type: string\n    required: true\n",
            ),
        )
        assert report.impact is SemverImpact.MAJOR

    def test_undeclared_variable_added_to_body_is_major(self):
        """PromptTemplate treats body-only variables as required, so adding one
        changes the effective contract and must be graded, not ignored."""
        report = compute_impact(
            _tpl(body="Hi {{ name }}"),
            _tpl(body="Hi {{ name }}, tier {{ tier }}"),
        )
        assert report.impact is SemverImpact.MAJOR


# ── MINOR ───────────────────────────────────────────────────────────


class TestMinorChanges:
    def test_optional_variable_added(self):
        report = compute_impact(
            _tpl(),
            _tpl(
                variables=REQUIRED_NAME
                + "  nickname:\n    type: string\n    required: false\n"
            ),
        )
        assert report.impact is SemverImpact.MINOR

    def test_optional_variable_removed(self):
        report = compute_impact(
            _tpl(
                variables=REQUIRED_NAME
                + "  nickname:\n    type: string\n    required: false\n"
            ),
            _tpl(),
        )
        assert report.impact is SemverImpact.MINOR

    def test_required_relaxed_to_optional(self):
        optional = "  name:\n    type: string\n    required: false\n"
        report = compute_impact(_tpl(), _tpl(variables=optional))
        assert report.impact is SemverImpact.MINOR

    def test_model_added(self):
        one = "    default: gpt-4-turbo\n    supported:\n      - gpt-4-turbo\n"
        two = "    default: gpt-4-turbo\n    supported:\n      - gpt-4-turbo\n      - claude-3\n"
        report = compute_impact(_tpl(models=one), _tpl(models=two))
        assert report.impact is SemverImpact.MINOR

    def test_optional_default_changed(self):
        before = "  name:\n    type: string\n    required: false\n    default: there\n"
        after = "  name:\n    type: string\n    required: false\n    default: friend\n"
        report = compute_impact(_tpl(variables=before), _tpl(variables=after))
        assert report.impact is SemverImpact.MINOR


# ── aggregation ─────────────────────────────────────────────────────


class TestAggregation:
    def test_highest_severity_wins(self):
        report = compute_impact(
            _tpl(),
            _tpl(
                body="Rewritten prose entirely, {{ name }} and {{ tier }}.",
                variables=REQUIRED_NAME
                + "  tier:\n    type: string\n    required: true\n",
            ),
        )
        assert report.impact is SemverImpact.MAJOR

    def test_all_changes_are_reported_not_only_the_winner(self):
        report = compute_impact(
            _tpl(),
            _tpl(
                body="Hi {{ name }} {{ tier }} {{ nickname }}",
                variables=REQUIRED_NAME
                + "  tier:\n    type: string\n    required: true\n"
                + "  nickname:\n    type: string\n    required: false\n",
            ),
        )
        assert report.impact is SemverImpact.MAJOR
        assert len(report.changes) >= 2
        kinds = {c.impact for c in report.changes}
        assert SemverImpact.MAJOR in kinds
        assert SemverImpact.MINOR in kinds


# ── serialization ───────────────────────────────────────────────────


class TestImpactReportSerialization:
    def test_to_dict_shape(self):
        report = compute_impact(
            _tpl(),
            _tpl(
                body="Hi {{ name }} {{ tier }}",
                variables=REQUIRED_NAME
                + "  tier:\n    type: string\n    required: true\n",
            ),
        )
        data = report.to_dict()
        assert data["impact"] == "major"
        assert isinstance(data["changes"], list)
        assert {"kind", "impact", "detail"} <= set(data["changes"][0].keys())

    def test_report_is_frozen(self):
        report = compute_impact(_tpl(), _tpl())
        with pytest.raises(Exception):
            report.impact = SemverImpact.MAJOR  # type: ignore[misc]

    def test_none_report_serializes_cleanly(self):
        assert compute_impact(_tpl(), _tpl()).to_dict() == {
            "impact": "none",
            "changes": [],
        }
