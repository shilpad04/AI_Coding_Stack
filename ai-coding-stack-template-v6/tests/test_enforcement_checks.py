"""
tests/test_enforcement_checks.py
=================================
Two Gate 1 checks that turn written rules into blocks:

  RULE-TEST-001  A proposal that changes source files must also change at
                 least one test file (PRD-driven testing). FAIL.
  RULE-PLAN-002  A task in .ai/plan.json must have at least one acceptance
                 criterion, or no test can be derived from the PRD. FAIL.

(The third check — a human must approve a task before its first apply,
RULE-PLAN-001 — is covered in tests/test_plan_approval.py.)
"""
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import validators as v  # noqa: E402
from validate_proposal import run_validation  # noqa: E402

REAL_CONFIG = ROOT / "config" / "config.yaml"


def _proposal(*entries: tuple[str, str]) -> types.SimpleNamespace:
    return types.SimpleNamespace(files=[
        {"path": path, "action": action, "content": "x = 1\n"} for path, action in entries])


# RULE-TEST-001: validate_tests_present

class TestTestsPresent:
    def test_source_without_a_test_fails(self) -> None:
        result = v.validate_tests_present(_proposal(("src/a.py", "create")))

        assert result.status == v.FAIL
        assert result.findings[0]["rule"] == "RULE-TEST-001"
        assert "src/a.py" in result.findings[0]["message"]

    @pytest.mark.parametrize("source, test", [
        ("src/a.py", "tests/test_a.py"),
        ("src/a.py", "src/test_a.py"),
        ("src/a.py", "src/a_test.py"),
        ("src/a.ts", "src/a.spec.ts"),
        ("src/A.tsx", "src/A.test.tsx"),
        ("src/a.js", "src/__tests__/a.js"),
        ("src/main/java/A.java", "src/test/java/ATest.java"),
        ("Svc/A.cs", "Svc.Tests/ATests.cs"),
        ("lib/a.dart", "test/a_test.dart"),
    ])
    def test_source_with_a_test_passes(self, source: str, test: str) -> None:
        assert v.validate_tests_present(_proposal((source, "create"), (test, "create"))).ok

    def test_modifying_an_existing_test_counts(self) -> None:
        assert v.validate_tests_present(_proposal(("src/a.py", "modify"), ("tests/test_a.py", "modify"))).ok

    def test_a_test_only_proposal_passes(self) -> None:
        assert v.validate_tests_present(_proposal(("tests/test_a.py", "create"))).ok

    def test_windows_style_paths_are_understood(self) -> None:
        assert v.validate_tests_present(_proposal(("src\\a.py", "create"), ("tests\\test_a.py", "create"))).ok
        assert v.validate_tests_present(_proposal(("src\\a.py", "create"))).status == v.FAIL

    @pytest.mark.parametrize("path", [
        "README.md", "package.json", "requirements.txt", "specs/spec.md",
        "vite.config.ts", "jest.config.js", "src/types.d.ts",
        "app/__init__.py", "conftest.py",
        "backend/alembic/versions/001_init.py", "db/migrations/001.py",
        "src/generated/client.ts", "infrastructure/Containerfile",
    ])
    def test_files_that_are_not_source_need_no_test(self, path: str) -> None:
        assert v.validate_tests_present(_proposal((path, "create"))).ok

    def test_deleting_source_needs_no_test(self) -> None:
        assert v.validate_tests_present(_proposal(("src/a.py", "delete"))).ok

    def test_deleting_a_test_does_not_count_as_adding_one(self) -> None:
        result = v.validate_tests_present(_proposal(("src/a.py", "modify"), ("tests/test_a.py", "delete")))

        assert result.status == v.FAIL

    @pytest.mark.parametrize("path", ["src/latest/a.py", "src/contest/a.py", "src/attest.py"])
    def test_a_name_that_merely_ends_in_test_is_still_source(self, path: str) -> None:
        assert v.validate_tests_present(_proposal((path, "create"))).status == v.FAIL

    def test_an_empty_proposal_passes(self) -> None:
        assert v.validate_tests_present(_proposal()).ok


# RULE-PLAN-002: validate_acceptance_criteria

class TestAcceptanceCriteria:
    def test_a_task_with_a_criterion_passes(self) -> None:
        assert v.validate_acceptance_criteria(
            {"task_id": "T", "acceptance_criteria": ["returns 400 when id is missing"]}).ok

    def test_one_real_criterion_among_blanks_passes(self) -> None:
        assert v.validate_acceptance_criteria({"task_id": "T", "acceptance_criteria": ["", "  ", "real"]}).ok

    @pytest.mark.parametrize("criteria", [None, [], [""], ["   "], "returns 400", [None], [42]])
    def test_missing_or_empty_criteria_fail(self, criteria) -> None:
        result = v.validate_acceptance_criteria({"task_id": "TASK-007", "acceptance_criteria": criteria})

        assert result.status == v.FAIL
        assert result.findings[0]["rule"] == "RULE-PLAN-002"
        assert "TASK-007" in result.findings[0]["message"]

    def test_a_task_with_no_criteria_key_at_all_fails(self) -> None:
        assert v.validate_acceptance_criteria({"task_id": "T"}).status == v.FAIL


# Both checks wired into run_validation

def _write_plan(root: Path, criteria, allowed: list[str]) -> None:
    task = {"task_id": "TASK-001", "allowed_files": allowed}
    if criteria is not None:
        task["acceptance_criteria"] = criteria
    (root / ".ai").mkdir(parents=True, exist_ok=True)
    (root / ".ai" / "plan.json").write_text(
        json.dumps({"phases": [{"id": "P", "tasks": [task]}]}), encoding="utf-8")
    (root / ".ai" / "plan-approval.json").write_text(
        json.dumps({"TASK-001": {"allowed_files": sorted(allowed)}}), encoding="utf-8")


def _run(root: Path, files: list[tuple[str, str]], config: Path = REAL_CONFIG) -> int:
    proposal = root / "p.json"
    proposal.write_text(json.dumps({
        "task_id": "TASK-001", "status": "PROPOSAL",
        "files": [{"path": p, "action": "create", "content": c} for p, c in files]}), encoding="utf-8")
    return run_validation(
        proposal_path=proposal, config_path=config,
        packages_path=ROOT / "config" / "approved-packages.yaml",
        commands_path=ROOT / "config" / "command-policy.yaml",
        task={}, allowed_files=[], skip_reconcile=True, quiet=True,
        apply_files=True, project_root=root)


class TestWiredIntoTheValidator:
    def test_source_without_a_test_is_blocked_by_default(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, ["it works"], ["src/a.py", "tests/test_a.py"])

        assert _run(tmp_path, [("src/a.py", "x = 1\n")]) == 1
        assert not (tmp_path / "src" / "a.py").exists()

    def test_source_with_its_test_is_applied(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, ["it works"], ["src/a.py", "tests/test_a.py"])

        code = _run(tmp_path, [("src/a.py", "x = 1\n"), ("tests/test_a.py", "def test_x():\n    assert 1\n")])

        assert code == 0
        assert (tmp_path / "src" / "a.py").exists() and (tmp_path / "tests" / "test_a.py").exists()

    def test_a_docs_only_proposal_needs_no_test(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, ["it works"], ["docs/notes.md"])

        assert _run(tmp_path, [("docs/notes.md", "# notes\n")]) == 0

    def test_the_check_can_be_turned_off_in_config(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, ["it works"], ["src/a.py"])
        config = tmp_path / "config.yaml"
        config.write_text("governance:\n  require_tests_with_code: false\n", encoding="utf-8")

        assert _run(tmp_path, [("src/a.py", "x = 1\n")], config=config) == 0

    @pytest.mark.parametrize("value, expected_code", [
        ("false", 0),    # YAML boolean false: really off
        ('"false"', 1),  # text, not a boolean: stays on
        ("0", 1),
        ("null", 1),
    ])
    def test_only_a_real_boolean_false_turns_it_off(self, tmp_path: Path, value: str, expected_code: int) -> None:
        # A typo'd or oddly-typed setting must never silently disable the check.
        _write_plan(tmp_path, ["it works"], ["src/a.py"])
        config = tmp_path / "config.yaml"
        config.write_text(f"governance:\n  require_tests_with_code: {value}\n", encoding="utf-8")

        assert _run(tmp_path, [("src/a.py", "x = 1\n")], config=config) == expected_code

    def test_a_task_without_criteria_is_blocked(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, None, ["docs/notes.md"])

        assert _run(tmp_path, [("docs/notes.md", "# notes\n")]) == 1
        assert not (tmp_path / "docs" / "notes.md").exists()

    def test_a_task_with_only_blank_criteria_is_blocked(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, ["  "], ["docs/notes.md"])

        assert _run(tmp_path, [("docs/notes.md", "# notes\n")]) == 1

    def test_no_plan_file_means_no_criteria_check(self, tmp_path: Path) -> None:
        # Stand-alone use (no plan.json) keeps working; the scope check
        # still needs an explicit list, so this is asserted on the plan check only.
        proposal = tmp_path / "p.json"
        proposal.write_text(json.dumps({"task_id": "T", "status": "PROPOSAL", "files": []}), encoding="utf-8")

        code = run_validation(
            proposal_path=proposal, config_path=REAL_CONFIG,
            packages_path=ROOT / "config" / "approved-packages.yaml",
            commands_path=ROOT / "config" / "command-policy.yaml",
            task={}, allowed_files=[], skip_reconcile=True, quiet=True,
            apply_files=False, project_root=tmp_path)

        assert code == 0
