"""
tests/test_apply.py
===================
Tests for take_snapshot() and apply_proposal() utilities, and the --apply
Gate 2 wiring in run_validation().

Covers all acceptance criteria from TASK-003:
  - take_snapshot: happy path returns correct hash dict
  - take_snapshot: missing file is skipped gracefully
  - apply_proposal: create (including parent dirs)
  - apply_proposal: modify (overwrite)
  - apply_proposal: delete (existing file removed)
  - apply_proposal: delete on missing file is a no-op
  - Gate 1 FAIL blocks apply (no files written)
"""
from __future__ import annotations

import hashlib
import json
import sys
import types
from pathlib import Path

import pytest

# Make repo root and scripts/ importable for both runtime and IDE static analysis.
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from scripts.validate_proposal import take_snapshot, apply_proposal, run_validation, Proposal  # type: ignore # noqa: E402
except ImportError:
    from validate_proposal import take_snapshot, apply_proposal, run_validation, Proposal  # type: ignore # noqa: E402


# Helpers

def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _make_proposal(files: list[dict]) -> Proposal:
    """Minimal Proposal object with a .files attribute."""
    return Proposal({"files": files})


# take_snapshot

class TestTakeSnapshot:
    def test_happy_path_returns_correct_hash(self, tmp_path: Path) -> None:
        """Hash of a file whose content we know must match our expected value."""
        content = "hello world\n"
        (tmp_path / "src.py").write_text(content, encoding="utf-8")

        snap = take_snapshot(["src.py"], tmp_path)

        assert "src.py" in snap
        assert snap["src.py"]["hash"] == _sha_bytes((tmp_path / "src.py").read_bytes())

    def test_multiple_files(self, tmp_path: Path) -> None:
        """All present files appear in the snapshot."""
        (tmp_path / "a.py").write_text("a", encoding="utf-8")
        (tmp_path / "b.py").write_text("b", encoding="utf-8")

        snap = take_snapshot(["a.py", "b.py"], tmp_path)

        assert set(snap.keys()) == {"a.py", "b.py"}

    def test_missing_file_skipped_gracefully(self, tmp_path: Path) -> None:
        """A path that does not exist must be omitted without raising."""
        snap = take_snapshot(["does_not_exist.py"], tmp_path)

        assert snap == {}

    def test_mix_of_present_and_missing(self, tmp_path: Path) -> None:
        """Only existing files appear; missing ones are silently dropped."""
        (tmp_path / "real.py").write_text("x = 1\n", encoding="utf-8")

        snap = take_snapshot(["real.py", "ghost.py"], tmp_path)

        assert "real.py" in snap
        assert "ghost.py" not in snap


# apply_proposal

class TestApplyProposal:
    def test_create_file_with_content(self, tmp_path: Path) -> None:
        """action:create writes the file with the expected content."""
        proposal = _make_proposal([
            {"path": "src/new_file.py", "action": "create", "content": "x = 42\n"},
        ])

        touched = apply_proposal(proposal, tmp_path)

        assert touched == ["src/new_file.py"]
        assert (tmp_path / "src" / "new_file.py").read_text(encoding="utf-8") == "x = 42\n"

    def test_create_makes_parent_directories(self, tmp_path: Path) -> None:
        """action:create must create missing intermediate directories."""
        proposal = _make_proposal([
            {"path": "a/b/c/deep.py", "action": "create", "content": "pass\n"},
        ])

        apply_proposal(proposal, tmp_path)

        assert (tmp_path / "a" / "b" / "c" / "deep.py").exists()

    def test_modify_overwrites_existing_file(self, tmp_path: Path) -> None:
        """action:modify replaces existing content completely."""
        target = tmp_path / "service.py"
        target.write_text("old content\n", encoding="utf-8")

        proposal = _make_proposal([
            {"path": "service.py", "action": "modify", "content": "new content\n"},
        ])

        touched = apply_proposal(proposal, tmp_path)

        assert touched == ["service.py"]
        assert target.read_text(encoding="utf-8") == "new content\n"

    def test_delete_removes_existing_file(self, tmp_path: Path) -> None:
        """action:delete unlinks a file that exists and records the path."""
        target = tmp_path / "old.py"
        target.write_text("to be removed\n", encoding="utf-8")

        proposal = _make_proposal([
            {"path": "old.py", "action": "delete", "content": ""},
        ])

        touched = apply_proposal(proposal, tmp_path)

        assert touched == ["old.py"]
        assert not target.exists()

    def test_delete_missing_file_is_noop(self, tmp_path: Path) -> None:
        """action:delete on a non-existent file must not raise and must not appear in touched."""
        proposal = _make_proposal([
            {"path": "never_existed.py", "action": "delete", "content": ""},
        ])

        touched = apply_proposal(proposal, tmp_path)

        assert touched == []

    def test_returns_all_touched_paths(self, tmp_path: Path) -> None:
        """Returned list contains every path that was actually written or deleted."""
        (tmp_path / "existing.py").write_text("old\n", encoding="utf-8")

        proposal = _make_proposal([
            {"path": "new.py",      "action": "create", "content": "new\n"},
            {"path": "existing.py", "action": "modify", "content": "updated\n"},
        ])

        touched = apply_proposal(proposal, tmp_path)

        assert set(touched) == {"new.py", "existing.py"}


# Gate 1 FAIL blocks apply

class TestGate1BlocksApply:
    """run_validation with --apply must not write files when Gate 1 returns FAIL."""

    def _write_proposal(self, path: Path, files: list[dict]) -> Path:
        proposal = {
            "task_id": "TASK-TEST",
            "status": "PROPOSAL",
            "summary": "test",
            "clarifications": [],
            "files": files,
            "packages": [],
            "commands": [],
            "observations": [],
        }
        p = path / "proposal.json"
        p.write_text(json.dumps(proposal), encoding="utf-8")
        return p

    def test_file_not_written_when_gate1_fails(self, tmp_path: Path) -> None:
        """A file outside allowed_files causes Gate 1 FAIL; disk must be untouched."""
        proposal_path = self._write_proposal(tmp_path, [
            {"path": "src/sneaky.py", "action": "create", "content": "evil\n"},
        ])

        code = run_validation(
            proposal_path  = proposal_path,
            config_path    = Path("config/config.yaml"),
            packages_path  = Path("config/approved-packages.yaml"),
            commands_path  = Path("config/command-policy.yaml"),
            task           = {},
            allowed_files  = ["src/allowed.py"],  # sneaky.py is NOT in this list
            skip_reconcile = False,
            quiet          = True,
            apply_files    = True,
            project_root   = tmp_path,
        )

        assert code == 1  # Gate 1 FAIL
        assert not (tmp_path / "src" / "sneaky.py").exists()  # nothing written


# Shared helpers for the tests below

ROOT = Path(__file__).parent.parent
LENIENT = ROOT / "tests" / "data" / "lenient_config.yaml"  # RULE-TEST-001 off; not under test here


def _write_plan_tasks(root: Path, tasks: dict[str, list[str]], approve_root: Path | None = None) -> Path:
    """A plan a human has approved: every task has acceptance criteria and a baseline.

    The baseline goes to <approve_root>/.ai/plan-approval.json (the project
    root, defaulting to the folder the plan is written into).
    """
    plan = {"project": "p", "phases": [{"id": "PHASE-1", "tasks": [
        {"task_id": tid, "allowed_files": allowed, "acceptance_criteria": ["it works"]}
        for tid, allowed in tasks.items()]}]}
    path = root / ".ai" / "plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan), encoding="utf-8")
    approval_path = (approve_root or root) / ".ai" / "plan-approval.json"
    approval_path.parent.mkdir(parents=True, exist_ok=True)
    approval_path.write_text(json.dumps(
        {tid: {"allowed_files": sorted(allowed)} for tid, allowed in tasks.items()}), encoding="utf-8")
    return path


def _write_plan(root: Path, task_id: str, allowed: list[str], approve_root: Path | None = None) -> Path:
    return _write_plan_tasks(root, {task_id: allowed}, approve_root=approve_root)


def _write_raw_proposal(root: Path, data: object, task_id: str = "TASK-001") -> Path:
    if isinstance(data, dict):
        data = {"task_id": task_id, "status": "PROPOSAL", **data}
    path = root / "proposal.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _run(proposal_path: Path, root: Path, allowed_files: list[str] | None = None,
         plan_path: Path | None = None, skip_reconcile: bool = False) -> int:
    return run_validation(
        proposal_path  = proposal_path,
        config_path    = LENIENT,
        packages_path  = ROOT / "config" / "approved-packages.yaml",
        commands_path  = ROOT / "config" / "command-policy.yaml",
        task           = {},
        allowed_files  = allowed_files or [],
        skip_reconcile = skip_reconcile,
        quiet          = True,
        apply_files    = True,
        project_root   = root,
        plan_path      = plan_path,
    )


def _one_file(path: str, content: str = "x = 1\n") -> dict:
    return {"files": [{"path": path, "action": "create", "content": content}]}


# The approved plan decides which files a task may touch

class TestPlanDecidesAllowedFiles:
    def test_file_in_plan_is_applied(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, "TASK-001", ["src/a.py"])
        proposal = _write_raw_proposal(tmp_path, _one_file("src/a.py"))

        assert _run(proposal, tmp_path) == 0
        assert (tmp_path / "src" / "a.py").exists()

    def test_file_outside_plan_is_blocked(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, "TASK-001", ["src/a.py"])
        proposal = _write_raw_proposal(tmp_path, _one_file("src/other.py"))

        assert _run(proposal, tmp_path) == 1
        assert not (tmp_path / "src" / "other.py").exists()

    def test_explicit_list_cannot_widen_the_plan(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, "TASK-001", ["src/a.py"])
        proposal = _write_raw_proposal(tmp_path, _one_file("src/b.py"))

        code = _run(proposal, tmp_path, allowed_files=["src/a.py", "src/b.py"])

        assert code == 1
        assert not (tmp_path / "src" / "b.py").exists()

    def test_explicit_list_can_narrow_the_plan(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, "TASK-001", ["src/a.py", "src/b.py"])
        blocked = _write_raw_proposal(tmp_path, _one_file("src/b.py"))
        assert _run(blocked, tmp_path, allowed_files=["src/a.py"]) == 1
        assert not (tmp_path / "src" / "b.py").exists()

        allowed = _write_raw_proposal(tmp_path, _one_file("src/a.py"))
        assert _run(allowed, tmp_path, allowed_files=["src/a.py"]) == 0

    def test_task_missing_from_plan_is_blocked(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, "TASK-001", ["src/a.py"])
        proposal = _write_raw_proposal(tmp_path, _one_file("src/a.py"), task_id="TASK-999")

        assert _run(proposal, tmp_path) == 1
        assert not (tmp_path / "src" / "a.py").exists()

    def test_unreadable_plan_blocks_everything(self, tmp_path: Path) -> None:
        (tmp_path / ".ai").mkdir()
        (tmp_path / ".ai" / "plan.json").write_text("{not json", encoding="utf-8")
        proposal = _write_raw_proposal(tmp_path, _one_file("src/a.py"))

        assert _run(proposal, tmp_path, allowed_files=["src/a.py"]) == 1
        assert not (tmp_path / "src" / "a.py").exists()

    def test_no_plan_file_falls_back_to_explicit_list(self, tmp_path: Path) -> None:
        proposal = _write_raw_proposal(tmp_path, _one_file("src/a.py"))

        assert _run(proposal, tmp_path, allowed_files=["src/a.py"]) == 0

    def test_no_plan_and_no_list_blocks_everything(self, tmp_path: Path) -> None:
        proposal = _write_raw_proposal(tmp_path, _one_file("src/a.py"))

        assert _run(proposal, tmp_path) == 1

    def test_plan_path_can_be_given_explicitly(self, tmp_path: Path) -> None:
        plan = _write_plan(tmp_path / "elsewhere", "TASK-001", ["src/a.py"], approve_root=tmp_path)
        proposal = _write_raw_proposal(tmp_path, _one_file("src/a.py"))

        assert _run(proposal, tmp_path, plan_path=plan) == 0

    def test_plan_cannot_unlock_a_protected_file(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, "TASK-001", ["rules.md"])
        proposal = _write_raw_proposal(tmp_path, _one_file("rules.md", "# changed\n"))

        assert _run(proposal, tmp_path) == 2  # ASK: a human must approve
        assert not (tmp_path / "rules.md").exists()  # and nothing was written

    def test_package_outside_approved_list_is_blocked(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, "TASK-001", ["src/a.py"])
        proposal = _write_raw_proposal(
            tmp_path, _one_file("src/a.py", "import notapprovedpkg\n"))

        assert _run(proposal, tmp_path) == 1
        assert not (tmp_path / "src" / "a.py").exists()


# Nothing is written while a human decision is pending (exit 2)

class TestAskDoesNotWrite:
    def test_protected_file_is_not_written_on_ask(self, tmp_path: Path) -> None:
        proposal = _write_raw_proposal(tmp_path, _one_file("rules.md", "# changed\n"))

        code = _run(proposal, tmp_path, allowed_files=["rules.md"])

        assert code == 2
        assert not (tmp_path / "rules.md").exists()


# Bad model output fails cleanly instead of crashing

class TestMalformedProposals:
    def test_missing_action_fails_and_writes_nothing(self, tmp_path: Path) -> None:
        proposal = _write_raw_proposal(
            tmp_path, {"files": [{"path": "src/a.py", "content": "x = 1\n"}]})

        assert _run(proposal, tmp_path, allowed_files=["src/a.py"]) == 1
        assert not (tmp_path / "src" / "a.py").exists()

    def test_null_content_fails_and_writes_nothing(self, tmp_path: Path) -> None:
        proposal = _write_raw_proposal(
            tmp_path, {"files": [{"path": "src/a.py", "action": "create", "content": None}]})

        assert _run(proposal, tmp_path, allowed_files=["src/a.py"]) == 1
        assert not (tmp_path / "src" / "a.py").exists()

    def test_files_not_a_list_fails(self, tmp_path: Path) -> None:
        proposal = _write_raw_proposal(tmp_path, {"files": "src/a.py"})

        assert _run(proposal, tmp_path, allowed_files=["src/a.py"]) == 1

    def test_packages_as_plain_strings_fails(self, tmp_path: Path) -> None:
        proposal = _write_raw_proposal(tmp_path, {"files": [], "packages": ["requests"]})

        assert _run(proposal, tmp_path) == 1

    def test_proposal_that_is_not_an_object_is_an_error(self, tmp_path: Path) -> None:
        proposal = _write_raw_proposal(tmp_path, ["not", "an", "object"])

        assert _run(proposal, tmp_path) == 3


# Every applied proposal is logged: task, file, lines, functions

def _read_log(root: Path) -> list[dict]:
    text = (root / ".ai" / "traceability.ndjson").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


class TestTraceLog:
    def test_applied_proposal_is_logged_with_lines_and_functions(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, "TASK-001", ["src/a.py"])
        proposal = _write_raw_proposal(tmp_path, _one_file("src/a.py", "def hello():\n    return 1\n"))

        assert _run(proposal, tmp_path) == 0

        (event,) = _read_log(tmp_path)
        assert event["event"] == "apply"
        assert event["task_id"] == "TASK-001"
        assert event["reconcile"] == "PASS"
        assert event["time"]
        (entry,) = event["files"]
        assert entry["path"] == "src/a.py"
        assert entry["added"] == [[1, 2]] and entry["removed"] == []
        assert entry["functions"] == [{"name": "hello", "change": "added"}]

    def test_changing_an_existing_file_logs_only_the_changed_lines(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "a.py").write_bytes(b"def a():\n    return 1\n\ndef b():\n    return 2\n")
        _write_plan(tmp_path, "TASK-001", ["src/a.py"])
        new_text = "def a():\n    return 10\n\ndef b():\n    return 2\n"
        proposal = _write_raw_proposal(tmp_path, {"files": [
            {"path": "src/a.py", "action": "modify", "content": new_text}]})

        assert _run(proposal, tmp_path) == 0

        (entry,) = _read_log(tmp_path)[0]["files"]
        assert entry["added"] == [[2, 2]] and entry["removed"] == [[2, 2]]
        assert entry["functions"] == [{"name": "a", "change": "modified"}]

    def test_deleting_a_file_is_logged_as_removed_lines(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "old.py").write_bytes(b"def gone():\n    pass\n")
        _write_plan(tmp_path, "TASK-001", ["src/old.py"])
        proposal = _write_raw_proposal(tmp_path, {"files": [
            {"path": "src/old.py", "action": "delete", "content": ""}]})

        assert _run(proposal, tmp_path) == 0

        (entry,) = _read_log(tmp_path)[0]["files"]
        assert entry["action"] == "delete"
        assert entry["lines_removed"] == 2 and entry["lines_added"] == 0
        assert entry["functions"] == [{"name": "gone", "change": "removed"}]

    def test_two_tasks_make_two_log_lines(self, tmp_path: Path) -> None:
        _write_plan_tasks(tmp_path, {"TASK-001": ["src/a.py"], "TASK-002": ["src/b.py"]})

        _run(_write_raw_proposal(tmp_path, _one_file("src/a.py"), task_id="TASK-001"), tmp_path)
        _run(_write_raw_proposal(tmp_path, _one_file("src/b.py"), task_id="TASK-002"), tmp_path)

        assert [e["task_id"] for e in _read_log(tmp_path)] == ["TASK-001", "TASK-002"]

    def test_blocked_run_writes_no_log(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, "TASK-001", ["src/a.py"])
        proposal = _write_raw_proposal(tmp_path, _one_file("src/other.py"))

        assert _run(proposal, tmp_path) == 1
        assert not (tmp_path / ".ai" / "traceability.ndjson").exists()

    def test_ask_writes_no_log(self, tmp_path: Path) -> None:
        proposal = _write_raw_proposal(tmp_path, _one_file("rules.md", "# x\n"))

        assert _run(proposal, tmp_path, allowed_files=["rules.md"]) == 2
        assert not (tmp_path / ".ai" / "traceability.ndjson").exists()

    def test_skipped_reconcile_is_recorded_as_such(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, "TASK-001", ["src/a.py"])
        proposal = _write_raw_proposal(tmp_path, _one_file("src/a.py"))

        assert _run(proposal, tmp_path, skip_reconcile=True) == 0
        assert _read_log(tmp_path)[0]["reconcile"] == "SKIPPED"

    def test_log_that_cannot_be_written_fails_the_run(self, tmp_path: Path, capsys) -> None:
        _write_plan(tmp_path, "TASK-001", ["src/a.py"])
        (tmp_path / ".ai" / "traceability.ndjson").mkdir()  # a folder where the log file should be
        proposal = _write_raw_proposal(tmp_path, _one_file("src/a.py"))

        assert _run(proposal, tmp_path) == 1
        assert "traceability" in capsys.readouterr().err.lower()


class TestStatusLines:
    def _run_loud(self, proposal_path: Path, root: Path) -> int:
        return run_validation(
            proposal_path  = proposal_path,
            config_path    = LENIENT,
            packages_path  = ROOT / "config" / "approved-packages.yaml",
            commands_path  = ROOT / "config" / "command-policy.yaml",
            task           = {},
            allowed_files  = [],
            skip_reconcile = False,
            quiet          = False,
            apply_files    = True,
            project_root   = root,
        )

    def test_policy_agent_says_what_it_is_doing(self, tmp_path: Path, capsys) -> None:
        _write_plan(tmp_path, "TASK-001", ["src/a.py"])
        proposal = _write_raw_proposal(tmp_path, _one_file("src/a.py"))

        assert self._run_loud(proposal, tmp_path) == 0
        out = capsys.readouterr().out
        assert "[Policy Agent] Checking the TASK-001 proposal against the rules." in out
        assert "[Policy Agent] Writing the TASK-001 files to disk and checking what landed." in out
        assert "[Policy Agent] Done: TASK-001 is PASS." in out

    def test_blocked_proposal_reports_its_result_without_writing(self, tmp_path: Path, capsys) -> None:
        _write_plan(tmp_path, "TASK-001", ["src/a.py"])
        proposal = _write_raw_proposal(tmp_path, _one_file("src/other.py"))

        assert self._run_loud(proposal, tmp_path) == 1
        out = capsys.readouterr().out
        assert "[Policy Agent] Done: TASK-001 is FAIL." in out
        assert "Writing the TASK-001 files" not in out
