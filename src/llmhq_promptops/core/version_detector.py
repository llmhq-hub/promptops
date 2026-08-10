"""Deprecated. Use :mod:`llmhq_promptops.core.impact` instead.

This module used to carry its own 300-line implementation of "what does this
change break", separate from the one in ``core/impact.py`` that powers
``promptops test diff``. Two graders is not a redundancy, it is a guarantee of
drift, and they had drifted: this one graded adding a *required* variable as
MINOR and changing a variable's type as PATCH, where ``test diff`` graded both
MAJOR. A repository running the git hooks alongside the ``test diff
--exit-code`` CI gate therefore got its pull request blocked as breaking while
the pre-commit hook stamped a non-breaking version onto the same commit.

The grading logic is gone. What remains delegates to
:func:`llmhq_promptops.core.impact.next_version`, so the deprecated path cannot
drift back out of agreement while it lives. The class, the dataclass and the
enum stay importable through the 0.6.x line and are removed in 0.7.0.

Migration::

    from llmhq_promptops.core.impact import compute_impact, next_version
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from .impact import ImpactReport, SemverImpact, next_version


class ChangeType(Enum):
    """Types of changes for semantic versioning.

    ``NONE`` was added in 0.6.0. The old detector had no way to say "this
    change alters nothing a caller depends on", so it graded a description
    edit as PATCH and minted a version for it. Version churn on prose teaches
    people to ignore version numbers.
    """

    NONE = "none"        # x.y.z    - nothing a caller depends on moved
    PATCH = "patch"      # x.y.Z+1  - Content changes, bug fixes
    MINOR = "minor"      # x.Y+1.0  - New features, backward compatible
    MAJOR = "major"      # X+1.0.0  - Breaking changes


_IMPACT_TO_CHANGE_TYPE = {
    SemverImpact.NONE: ChangeType.NONE,
    SemverImpact.PATCH: ChangeType.PATCH,
    SemverImpact.MINOR: ChangeType.MINOR,
    SemverImpact.MAJOR: ChangeType.MAJOR,
}


@dataclass
class VersionChange:
    """Represents a version change with reasoning."""

    change_type: ChangeType
    old_version: str
    new_version: str
    reasons: List[str]
    file_changes: Dict[str, Any]


class SemanticVersionDetector:
    """Deprecated shim over :func:`llmhq_promptops.core.impact.next_version`."""

    def __init__(self) -> None:
        warnings.warn(
            "SemanticVersionDetector is deprecated and will be removed in "
            "0.7.0. Use llmhq_promptops.core.impact.compute_impact or "
            "next_version, which is the one grader the CLI and the git hooks "
            "both use.",
            DeprecationWarning,
            stacklevel=2,
        )

    def analyze_prompt_changes(
        self,
        old_content: Optional[str],
        new_content: str,
        current_version: str = "1.0.0",
    ) -> VersionChange:
        """Analyze changes between two prompt versions.

        ``file_changes`` now carries :meth:`ImpactReport.to_dict`, not the old
        ``metadata_changes`` / ``template_changes`` / ``variable_changes`` /
        ``model_changes`` / ``breaking_changes`` / ``new_features`` keys. Those
        described the old grader's internals, which no longer exist.
        """
        version, report = next_version(current_version, old_content, new_content)
        return VersionChange(
            change_type=_IMPACT_TO_CHANGE_TYPE[report.impact],
            old_version=current_version,
            new_version=version,
            reasons=[change.detail for change in report.changes],
            file_changes=report.to_dict(),
        )

    def get_next_version(
        self, current_version: str, old_content: Optional[str], new_content: str
    ) -> str:
        """Get the next version number for given changes."""
        return next_version(current_version, old_content, new_content)[0]
