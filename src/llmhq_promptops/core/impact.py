"""Semver impact of a prompt change (v0.6.0).

``promptops test diff`` answers "what changed", but the question a reviewer
actually has is "will this break my callers". This module answers that.

Impact is derived from the prompt's **variable signature** plus its declared
models, and from nothing else. Prose is never graded. That restraint is
deliberate: the variable interface is the only part of a prompt with a real
caller-facing contract, so it is the only part that can be graded
mechanically without guessing at authorial intent. A rule that guessed would
produce annotations nobody trusts, and an untrusted CI gate gets disabled.

A note on auto-detected variables. ``PromptTemplate.variables`` merges
variables referenced in the template body but never declared in YAML,
defaulting them to required (see ``core/template.py``). This module grades
that merged set, because it is the same effective contract
``PromptTemplate.validate_variables`` enforces at render time. Adding
``{{ tier }}`` to a body therefore reads as MAJOR even with no YAML edit,
which is correct: every caller must now supply it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Tuple

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .template import PromptTemplate, VariableDefinition


class SemverImpact(Enum):
    """Severity of a prompt change, ordered NONE < PATCH < MINOR < MAJOR."""

    NONE = "none"
    PATCH = "patch"
    MINOR = "minor"
    MAJOR = "major"

    @property
    def _rank(self) -> int:
        return _RANKS[self]

    def __lt__(self, other: "SemverImpact") -> bool:
        if not isinstance(other, SemverImpact):
            return NotImplemented
        return self._rank < other._rank

    def __le__(self, other: "SemverImpact") -> bool:
        if not isinstance(other, SemverImpact):
            return NotImplemented
        return self._rank <= other._rank

    def __gt__(self, other: "SemverImpact") -> bool:
        if not isinstance(other, SemverImpact):
            return NotImplemented
        return self._rank > other._rank

    def __ge__(self, other: "SemverImpact") -> bool:
        if not isinstance(other, SemverImpact):
            return NotImplemented
        return self._rank >= other._rank


_RANKS: Dict[SemverImpact, int] = {
    SemverImpact.NONE: 0,
    SemverImpact.PATCH: 1,
    SemverImpact.MINOR: 2,
    SemverImpact.MAJOR: 3,
}


@dataclass(frozen=True)
class SignatureChange:
    """One graded delta between two versions of a prompt."""

    kind: str
    impact: SemverImpact
    detail: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "kind": self.kind,
            "impact": self.impact.value,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ImpactReport:
    """The overall verdict plus every individual change behind it."""

    impact: SemverImpact
    changes: Tuple[SignatureChange, ...] = field(default=())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "impact": self.impact.value,
            "changes": [c.to_dict() for c in self.changes],
        }

    @property
    def is_breaking(self) -> bool:
        return self.impact is SemverImpact.MAJOR


def _models(template: "PromptTemplate") -> List[str]:
    try:
        return list(template.get_supported_models())
    except Exception:
        # A malformed models block must not take down the whole diff; the
        # signature comparison below is still worth reporting.
        return []


def _compare_variable(
    name: str, old: "VariableDefinition", new: "VariableDefinition"
) -> List[SignatureChange]:
    """Grade a variable present in both versions."""
    changes: List[SignatureChange] = []

    if old.type != new.type:
        changes.append(
            SignatureChange(
                kind="variable_type_changed",
                impact=SemverImpact.MAJOR,
                detail=(
                    f"variable '{name}' type changed: "
                    f"{old.type} -> {new.type}"
                ),
            )
        )

    if not old.required and new.required:
        changes.append(
            SignatureChange(
                kind="variable_now_required",
                impact=SemverImpact.MAJOR,
                detail=f"optional variable '{name}' is now required",
            )
        )
    elif old.required and not new.required:
        changes.append(
            SignatureChange(
                kind="variable_now_optional",
                impact=SemverImpact.MINOR,
                detail=f"required variable '{name}' is now optional",
            )
        )

    # A default only takes effect when the caller omits the variable, so it
    # can only change behavior for optional ones.
    if not new.required and old.default != new.default:
        changes.append(
            SignatureChange(
                kind="variable_default_changed",
                impact=SemverImpact.MINOR,
                detail=(
                    f"variable '{name}' default changed: "
                    f"{old.default!r} -> {new.default!r}"
                ),
            )
        )

    return changes


def compute_impact(
    old: "PromptTemplate", new: "PromptTemplate"
) -> ImpactReport:
    """Grade the change from ``old`` to ``new``.

    Returns an :class:`ImpactReport` whose ``impact`` is the most severe of
    the individual changes, and whose ``changes`` lists every one of them so
    a reviewer sees the full picture rather than only the winner.
    """
    changes: List[SignatureChange] = []

    old_vars = old.variables
    new_vars = new.variables

    for name in sorted(set(new_vars) - set(old_vars)):
        var = new_vars[name]
        changes.append(
            SignatureChange(
                kind="required_variable_added" if var.required else "optional_variable_added",
                impact=SemverImpact.MAJOR if var.required else SemverImpact.MINOR,
                detail=(
                    f"{'required' if var.required else 'optional'} variable "
                    f"'{name}' added"
                ),
            )
        )

    for name in sorted(set(old_vars) - set(new_vars)):
        var = old_vars[name]
        changes.append(
            SignatureChange(
                kind="required_variable_removed" if var.required else "optional_variable_removed",
                impact=SemverImpact.MAJOR if var.required else SemverImpact.MINOR,
                detail=(
                    f"{'required' if var.required else 'optional'} variable "
                    f"'{name}' removed"
                ),
            )
        )

    for name in sorted(set(old_vars) & set(new_vars)):
        changes.extend(_compare_variable(name, old_vars[name], new_vars[name]))

    old_models = _models(old)
    new_models = _models(new)

    for model in sorted(set(new_models) - set(old_models)):
        changes.append(
            SignatureChange(
                kind="model_added",
                impact=SemverImpact.MINOR,
                detail=f"model '{model}' added to supported list",
            )
        )

    for model in sorted(set(old_models) - set(new_models)):
        changes.append(
            SignatureChange(
                kind="model_removed",
                impact=SemverImpact.MAJOR,
                detail=f"model '{model}' removed from supported list",
            )
        )

    if changes:
        return ImpactReport(
            impact=max(c.impact for c in changes),
            changes=tuple(changes),
        )

    # Signature is identical: the only question left is whether the prose moved.
    if old.template_str != new.template_str:
        return ImpactReport(impact=SemverImpact.PATCH)

    return ImpactReport(impact=SemverImpact.NONE)
