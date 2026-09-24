"""
tests/test_plan_approval.py
============================
Human plan approval (RULE-PLAN-001).

The AI writes .ai/plan.json, so the plan alone proves nothing. A task's FIRST
apply pauses (ASK) until a human has run `scripts/approve_plan.py`
(one task, or `--all` for every task with no approval yet). After that,
allowed_files may narrow freely (that only restricts it further), but
widening it — the AI adding a file to its own plan.json — pauses for a human
again.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from validate_proposal import run_validation  # noqa: E402
import approve_plan  # noqa: E402

LENIENT = ROOT / "tests" / "data" / "lenient_config.yaml"  # RULE-TEST-001 off; not under test here


def _write_plan_tasks(root: Path, tasks: dict[str, list[str]], approve: bool = False) -> None:
    plan = {"phases": [{"id": "P", "tasks": [
        {"task_id": tid, "allowed_files": allowed, "acceptance_criteria": ["it works"]}
        for tid, allowed in tasks.items()]}]}
    (root / ".ai").mkdir(parents=True, exist_ok=True)
    (root / ".ai" / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    if approve:
        for tid in tasks:
            approve_plan.approve(root, tid)


def _write_plan(root: Path, task_id: str, allowed: list[str], approve: bool = False) -> None:
    _write_plan_tasks(root, {task_id: allowed}, approve=approve)


def _write_proposal(root: Path, files: list[dict], task_id: str = "TASK-001") -> Path:
    data = {"task_id": task_id, "status": "PROPOSAL", "files": files}
    path = root / "p.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _run(proposal_path: Path, root: Path) -> int:
    return run_validation(
        proposal_path  = proposal_path,
        config_path    = LENIENT,
        packages_path  = ROOT / "config" / "approved-packages.yaml",
        commands_path  = ROOT / "config" / "command-policy.yaml",
        task           = {},
        allowed_files  = [],
        skip_reconcile = True,
        quiet          = True,
        apply_files    = True,
        project_root   = root,
    )


def _approval(root: Path) -> dict:
    path = root / ".ai" / "plan-approval.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


class TestFirstApplyNeedsApproval:
    def test_an_unapproved_task_asks_and_writes_nothing(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, "TASK-001", ["src/a.py"])
        proposal = _write_proposal(tmp_path, [{"path": "src/a.py", "action": "create", "content": "x = 1\n"}])

        assert _run(proposal, tmp_path) == 2
        assert not (tmp_path / "src" / "a.py").exists()

    def test_the_validator_never_approves_a_task_itself(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, "TASK-001", ["src/a.py"])
        proposal = _write_proposal(tmp_path, [{"path": "src/a.py", "action": "create", "content": "x = 1\n"}])

        _run(proposal, tmp_path)

        assert _approval(tmp_path) == {}

    def test_the_ask_names_the_command_a_human_must_run(self, tmp_path: Path, capsys) -> None:
        _write_plan(tmp_path, "TASK-001", ["src/a.py"])
        proposal = _write_proposal(tmp_path, [{"path": "src/a.py", "action": "create", "content": "x = 1\n"}])

        _run(proposal, tmp_path)

        out = capsys.readouterr().out
        assert "RULE-PLAN-001" in out
        assert "approve_plan.py TASK-001" in out

    def test_after_approve_plan_the_first_apply_passes(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, "TASK-001", ["src/a.py"], approve=True)
        proposal = _write_proposal(tmp_path, [{"path": "src/a.py", "action": "create", "content": "x = 1\n"}])

        assert _run(proposal, tmp_path) == 0
        assert (tmp_path / "src" / "a.py").exists()

    def test_the_same_list_again_is_fine(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, "TASK-001", ["src/a.py"], approve=True)
        _run(_write_proposal(tmp_path, [{"path": "src/a.py", "action": "create", "content": "x=1\n"}]), tmp_path)

        code = _run(_write_proposal(tmp_path, [{"path": "src/a.py", "action": "modify", "content": "x=2\n"}]), tmp_path)

        assert code == 0

    def test_a_narrower_list_updates_the_baseline_with_no_ask(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, "TASK-001", ["src/a.py", "src/b.py"], approve=True)

        _write_plan(tmp_path, "TASK-001", ["src/a.py"])  # b.py dropped
        code = _run(_write_proposal(tmp_path, [{"path": "src/a.py", "action": "modify", "content": "x=2\n"}]), tmp_path)

        assert code == 0
        assert _approval(tmp_path)["TASK-001"]["allowed_files"] == ["src/a.py"]

    def test_approving_one_task_does_not_approve_another(self, tmp_path: Path) -> None:
        _write_plan_tasks(tmp_path, {"TASK-001": ["src/a.py"], "TASK-002": ["src/b.py"]})
        approve_plan.approve(tmp_path, "TASK-001")

        code = _run(_write_proposal(
            tmp_path, [{"path": "src/b.py", "action": "create", "content": "y = 1\n"}], task_id="TASK-002"), tmp_path)

        assert code == 2
        assert not (tmp_path / "src" / "b.py").exists()


class TestWideningNeedsApproval:
    def test_a_wider_list_asks_instead_of_writing(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, "TASK-001", ["src/a.py"], approve=True)

        _write_plan(tmp_path, "TASK-001", ["src/a.py", "src/b.py"])  # b.py added by the AI itself
        proposal = _write_proposal(tmp_path, [{"path": "src/b.py", "action": "create", "content": "y=1\n"}])

        code = _run(proposal, tmp_path)

        assert code == 2
        assert not (tmp_path / "src" / "b.py").exists()

    def test_baseline_is_not_updated_while_pending(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, "TASK-001", ["src/a.py"], approve=True)

        _write_plan(tmp_path, "TASK-001", ["src/a.py", "src/b.py"])
        _run(_write_proposal(tmp_path, [{"path": "src/b.py", "action": "create", "content": "y=1\n"}]), tmp_path)

        assert _approval(tmp_path)["TASK-001"]["allowed_files"] == ["src/a.py"]

    def test_after_approve_plan_the_same_widen_is_accepted(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, "TASK-001", ["src/a.py"], approve=True)

        _write_plan(tmp_path, "TASK-001", ["src/a.py", "src/b.py"])
        approve_plan.approve(tmp_path, "TASK-001")
        code = _run(_write_proposal(tmp_path, [{"path": "src/b.py", "action": "create", "content": "y=1\n"}]), tmp_path)

        assert code == 0
        assert (tmp_path / "src" / "b.py").exists()

    def test_proposal_cannot_write_the_approval_file_directly(self, tmp_path: Path) -> None:
        # Even naming the approval file in a task's own allowed_files does
        # not let a proposal control its content: RULE-GOV-001 fires first.
        _write_plan(tmp_path, "TASK-001", [".ai/plan-approval.json"])
        proposal = _write_proposal(tmp_path, [
            {"path": ".ai/plan-approval.json", "action": "create",
             "content": '{"TASK-001": {"allowed_files": ["src/a.py", "src/secret.py"]}}'},
        ])

        code = _run(proposal, tmp_path)

        assert code == 2
        assert "src/secret.py" not in json.dumps(_approval(tmp_path))


class TestApprovePlanScript:
    def test_approve_records_the_current_plan_allowed_files(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, "TASK-001", ["src/a.py", "src/b.py"])

        result = approve_plan.approve(tmp_path, "TASK-001")

        assert result == ["src/a.py", "src/b.py"]
        assert _approval(tmp_path)["TASK-001"]["allowed_files"] == ["src/a.py", "src/b.py"]

    def test_approve_logs_an_event(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, "TASK-001", ["src/a.py"])

        approve_plan.approve(tmp_path, "TASK-001")

        log = (tmp_path / ".ai" / "traceability.ndjson").read_text(encoding="utf-8").splitlines()
        event = json.loads(log[-1])
        assert event["event"] == "plan_approval"
        assert event["task_id"] == "TASK-001"
        assert event["allowed_files"] == ["src/a.py"]

    def test_approve_unknown_task_raises_a_clear_error(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, "TASK-001", ["src/a.py"])

        with pytest.raises(ValueError, match="TASK-999"):
            approve_plan.approve(tmp_path, "TASK-999")

    def test_approve_with_no_plan_file_raises_a_clear_error(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="plan.json"):
            approve_plan.approve(tmp_path, "TASK-001")


class TestApproveAll:
    def test_approves_every_task_that_has_no_approval_yet(self, tmp_path: Path) -> None:
        _write_plan_tasks(tmp_path, {"TASK-001": ["src/a.py"], "TASK-002": ["src/b.py"]})

        approved, skipped = approve_plan.approve_all(tmp_path)

        assert approved == ["TASK-001", "TASK-002"] and skipped == []
        assert set(_approval(tmp_path)) == {"TASK-001", "TASK-002"}

    def test_never_re_approves_a_task_that_already_has_a_baseline(self, tmp_path: Path) -> None:
        # --all must not become a way to accept a widened scope without looking.
        _write_plan_tasks(tmp_path, {"TASK-001": ["src/a.py"]}, approve=True)
        _write_plan_tasks(tmp_path, {"TASK-001": ["src/a.py", "src/evil.py"], "TASK-002": ["src/b.py"]})

        approved, skipped = approve_plan.approve_all(tmp_path)

        assert approved == ["TASK-002"] and skipped == ["TASK-001"]
        assert _approval(tmp_path)["TASK-001"]["allowed_files"] == ["src/a.py"]

    def test_a_second_run_approves_nothing_new(self, tmp_path: Path) -> None:
        _write_plan_tasks(tmp_path, {"TASK-001": ["src/a.py"]})
        approve_plan.approve_all(tmp_path)

        approved, skipped = approve_plan.approve_all(tmp_path)

        assert approved == [] and skipped == ["TASK-001"]

    def test_with_no_plan_file_raises_a_clear_error(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="plan.json"):
            approve_plan.approve_all(tmp_path)


class TestApprovePlanCommandLine:
    def _main(self, monkeypatch, *args: str) -> None:
        monkeypatch.setattr(sys, "argv", ["approve_plan.py", *args])
        approve_plan.main()

    def test_all_flag_approves_and_reports(self, tmp_path: Path, monkeypatch, capsys) -> None:
        _write_plan_tasks(tmp_path, {"TASK-001": ["src/a.py"]})

        self._main(monkeypatch, "--all", "--root", str(tmp_path))

        assert "TASK-001" in capsys.readouterr().out
        assert "TASK-001" in _approval(tmp_path)

    def test_a_task_id_still_works(self, tmp_path: Path, monkeypatch, capsys) -> None:
        _write_plan(tmp_path, "TASK-001", ["src/a.py"])

        self._main(monkeypatch, "TASK-001", "--root", str(tmp_path))

        assert "TASK-001" in _approval(tmp_path)

    def test_neither_a_task_id_nor_all_is_an_error(self, tmp_path: Path, monkeypatch, capsys) -> None:
        _write_plan(tmp_path, "TASK-001", ["src/a.py"])

        with pytest.raises(SystemExit) as exc:
            self._main(monkeypatch, "--root", str(tmp_path))

        assert exc.value.code != 0
        assert _approval(tmp_path) == {}

    def test_both_a_task_id_and_all_is_an_error(self, tmp_path: Path, monkeypatch, capsys) -> None:
        _write_plan(tmp_path, "TASK-001", ["src/a.py"])

        with pytest.raises(SystemExit) as exc:
            self._main(monkeypatch, "TASK-001", "--all", "--root", str(tmp_path))

        assert exc.value.code != 0
        assert _approval(tmp_path) == {}
