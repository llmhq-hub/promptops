"""One semver grader, used by both the hook and the CLI (v0.6.0).

Two implementations of "what does this change break" existed:

- ``core/version_detector.py``, written for v0.1.0, 303 lines, referenced by
  **zero** test files, driving the version number the pre-commit hook stamps
  into every prompt.
- ``core/impact.py``, written for v0.5.0, 22 tests, driving
  ``promptops test diff`` and its ``--exit-code`` CI gate.

They disagreed on 2 of 7 change types, and both disagreements were the older
one *under*-grading a breaking change:

    change                     hook    test diff
    add REQUIRED variable      MINOR   MAJOR
    change variable type       PATCH   MAJOR

So a repo running both got its PR blocked as breaking by CI while the hook
stamped a non-breaking version onto the same commit. Version numbers are only
useful if they mean one thing.

``core/impact.py`` is now the only grader. The important test in this file is
:class:`TestTheHookAndTheCliCannotDisagree`, which asserts the two paths return
the same grade for the same change. It is a property, not a list of cases, so
it keeps holding as the rules evolve.
"""

from __future__ import annotations

import pytest

from llmhq_promptops.core.impact import (
    SemverImpact,
    compute_impact,
    next_version,
)
from llmhq_promptops.core.template import PromptTemplate


def _prompt(
    body: str = "Hello, {{ name }}!",
    variables: str = "  name:\n    type: string\n    required: true\n",
    models: str = "    default: gpt-4-turbo\n",
    description: str = "Prompt under test",
    version: str = "v1.2.0",
) -> str:
    return (
        "metadata:\n"
        "  id: hello\n"
        f"  version: {version}\n"
        f"  description: {description}\n"
        "  models:\n" + models + "template: |\n"
        + "".join(f"  {line}\n" for line in body.splitlines())
        + "variables:\n" + variables
    )


REQUIRED_NAME = "  name:\n    type: string\n    required: true\n"
OPTIONAL_NAME = "  name:\n    type: string\n    required: false\n"

BASE = _prompt()

# (label, new prompt text, expected impact, expected version from v1.2.0)
CASES = [
    (
        "add a required variable",
        _prompt(
            body="Hello, {{ name }}! Tier {{ tier }}.",
            variables=REQUIRED_NAME + "  tier:\n    type: string\n    required: true\n",
        ),
        SemverImpact.MAJOR,
        "v2.0.0",
    ),
    (
        "add an optional variable",
        _prompt(
            variables=REQUIRED_NAME
            + "  tier:\n    type: string\n    required: false\n"
        ),
        SemverImpact.MINOR,
        "v1.3.0",
    ),
    (
        "remove a required variable",
        _prompt(body="Hello there!", variables="  {}\n"),
        SemverImpact.MAJOR,
        "v2.0.0",
    ),
    (
        "relax a required variable to optional",
        _prompt(variables=OPTIONAL_NAME),
        SemverImpact.MINOR,
        "v1.3.0",
    ),
    (
        "change a variable's type",
        _prompt(variables="  name:\n    type: number\n    required: true\n"),
        SemverImpact.MAJOR,
        "v2.0.0",
    ),
    (
        # BASE declares only `default: gpt-4-turbo`, which
        # get_supported_models() resolves to ["gpt-4-turbo"], so listing that
        # same model under `supported` alongside a new one is purely additive.
        "add a declared model",
        _prompt(
            models=(
                "    default: gpt-4-turbo\n"
                "    supported:\n      - gpt-4-turbo\n      - claude-sonnet-4-5\n"
            ),
        ),
        SemverImpact.MINOR,
        "v1.3.0",
    ),
    (
        "drop a declared model",
        _prompt(
            models=(
                "    default: claude-sonnet-4-5\n"
                "    supported:\n      - claude-sonnet-4-5\n"
            ),
        ),
        SemverImpact.MAJOR,  # gpt-4-turbo is gone; removal outranks the addition
        "v2.0.0",
    ),
    (
        "reword prose only",
        _prompt(body="Hi there, {{ name }}!"),
        SemverImpact.PATCH,
        "v1.2.1",
    ),
    (
        "edit only the description",
        _prompt(description="Reworded description, same contract"),
        SemverImpact.NONE,
        "v1.2.0",
    ),
    (
        "change nothing",
        BASE,
        SemverImpact.NONE,
        "v1.2.0",
    ),
]

IDS = [c[0] for c in CASES]


# ── the property that matters ───────────────────────────────────────


class TestTheHookAndTheCliCannotDisagree:
    """The whole point of the refactor, asserted directly."""

    @pytest.mark.parametrize("_, new_text, expected, __", CASES, ids=IDS)
    def test_both_paths_return_the_same_grade(self, _, new_text, expected, __):
        cli_verdict = compute_impact(PromptTemplate(BASE), PromptTemplate(new_text))
        _, hook_report = next_version("v1.2.0", BASE, new_text)

        assert hook_report.impact is cli_verdict.impact, (
            f"the hook graded {hook_report.impact.value} where "
            f"test diff graded {cli_verdict.impact.value}"
        )
        assert hook_report.impact is expected


# ── the version the hook writes ─────────────────────────────────────


class TestNextVersion:
    @pytest.mark.parametrize("_, new_text, __, expected", CASES, ids=IDS)
    def test_it_bumps_to_the_expected_version(self, _, new_text, __, expected):
        assert next_version("v1.2.0", BASE, new_text)[0] == expected

    def test_a_brand_new_prompt_keeps_its_declared_version(self):
        """There is nothing for a first commit to be incompatible *with*.

        The old grader compared a new prompt against an empty document,
        read every variable as an addition, graded MINOR, and overwrote the
        author's declared v1.0.0 with v1.1.0. A tool whose first act is to
        overwrite the version you just wrote has not earned trust on any
        later version either.
        """
        version, report = next_version("v1.0.0", None, _prompt(version="v1.0.0"))

        assert version == "v1.0.0"
        assert report.impact is SemverImpact.NONE

    def test_an_empty_previous_revision_counts_as_new(self):
        assert next_version("v1.0.0", "", BASE)[0] == "v1.0.0"
        assert next_version("v1.0.0", "   \n", BASE)[0] == "v1.0.0"

    def test_a_version_with_no_v_prefix_still_bumps(self):
        assert next_version("1.2.0", BASE, _prompt(body="Hi, {{ name }}!"))[0] == "v1.2.1"

    def test_an_unparseable_version_is_left_alone(self):
        """Better to leave a strange version in place than invent a number."""
        assert next_version("not-a-version", BASE, _prompt(body="Hi!"))[0] == (
            "not-a-version"
        )

    def test_an_unparseable_previous_revision_does_not_bump(self):
        version, report = next_version("v1.2.0", "{{{ not yaml", BASE)

        assert version == "v1.2.0"
        assert report.impact is SemverImpact.NONE

    def test_a_short_version_is_padded_not_rejected(self):
        assert next_version("v1", BASE, _prompt(body="Hi, {{ name }}!"))[0] == "v1.0.1"


# ── the deprecated grader still works, and agrees ───────────────────


class TestSemanticVersionDetectorIsDeprecated:
    def test_constructing_it_warns(self):
        from llmhq_promptops.core.version_detector import SemanticVersionDetector

        with pytest.warns(DeprecationWarning, match="0.7.0"):
            SemanticVersionDetector()

    @pytest.mark.parametrize("_, new_text, expected, expected_version", CASES, ids=IDS)
    def test_it_agrees_with_the_one_grader(
        self, _, new_text, expected, expected_version
    ):
        """Delegating rather than deleting gives importers a working release.

        Delegating rather than keeping its own logic is what makes it
        impossible for the deprecated path to drift back out of agreement.
        """
        from llmhq_promptops.core.version_detector import SemanticVersionDetector

        with pytest.warns(DeprecationWarning):
            detector = SemanticVersionDetector()

        change = detector.analyze_prompt_changes(BASE, new_text, "v1.2.0")

        assert change.new_version == expected_version
        assert change.change_type.value == expected.value
