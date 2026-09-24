"""
tests/test_repair_attempts.py
=============================
A model can be told to fix a proposal and keep failing the same task forever.
run_validation() counts consecutive Gate-1 FAILs per task in
.ai/task-state.json; once the count reaches governance.max_repair_attempts
(config.yaml), it stops returning FAIL (1) and returns ASK (2) instead, so a
human has to look. A PASS or an ordinary ASK resets the count.

These tests run against tests/data/lenient_config.yaml (max_repair_attempts 2,
RULE-TEST-001 off since it is not under test here). MAX_ATTEMPTS below must
match both that file and the real config/config.yaml — the last test in this
file checks the real one.
"""
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent.parent
MAX_ATTEMPTS = 2  # must match config/config.yaml -> governance.max_repair_attempts
LENIENT = ROOT / "tests" / "data" / "lenient_config.yaml"

import sys
sys.path.insert(0, str(ROOT / "scripts"))
from validate_proposal import run_validation  # noqa: E402


def _write_plan_tasks(root: Path, tasks: dict[str, list[str]]) -> None:
    """A plan a human has approved: every task has acceptance criteria and a baseline."""
    plan = {"phases": [{"id": "P", "tasks": [
        {"task_id": tid, "allowed_files": allowed, "acceptance_criteria": ["it works"]}
        for tid, allowed in tasks.items()]}]}
    (root / ".ai").mkdir(parents=True, exist_ok=True)
    (root / ".ai" / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    approval = {tid: {"allowed_files": sorted(allowed)} for tid, allowed in tasks.items()}
    (root / ".ai" / "plan-approval.json").write_text(json.dumps(approval), encoding="utf-8")


def _write_plan(root: Path, task_id: str, allowed: list[str]) -> None:
    _write_plan_tasks(root, {task_id: allowed})


def _write_proposal(root: Path, files: list[dict], task_id: str = "TASK-001") -> Path:
    data = {"task_id": task_id, "status": "PROPOSAL", "files": files}
    path = root / "p.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _run(proposal_path: Path, root: Path, task_id: str = "TASK-001",
         config_path: Path | None = None) -> int:
    return run_validation(
        proposal_path  = proposal_path,
        config_path    = config_path or LENIENT,
        packages_path  = ROOT / "config" / "approved-packages.yaml",
        commands_path  = ROOT / "config" / "command-policy.yaml",
        task           = {},
        allowed_files  = [],
        skip_reconcile = True,
        quiet          = True,
        apply_files    = False,
        project_root   = root,
    )


def _state(root: Path) -> dict:
    return json.loads((root / ".ai" / "task-state.json").read_text(encoding="utf-8"))


BAD = [{"path": "src/other.py", "action": "create", "content": "x = 1\n"}]  # not in allowed_files
GOOD_FILES = ["src/a.py"]


class TestRepairAttemptEscalation:
    def test_failures_below_the_threshold_are_plain_fail(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, "TASK-001", GOOD_FILES)

        for _ in range(MAX_ATTEMPTS - 1):
            code = _run(_write_proposal(tmp_path, BAD), tmp_path)
            assert code == 1

        assert _state(tmp_path)["TASK-001"]["repair_attempts"] == MAX_ATTEMPTS - 1

    def test_the_threshold_th_consecutive_failure_escalates_to_ask(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, "TASK-001", GOOD_FILES)

        for _ in range(MAX_ATTEMPTS - 1):
            _run(_write_proposal(tmp_path, BAD), tmp_path)
        code = _run(_write_proposal(tmp_path, BAD), tmp_path)

        assert code == 2
        assert _state(tmp_path)["TASK-001"]["repair_attempts"] == MAX_ATTEMPTS

    def test_malformed_proposal_failures_count_too(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, "TASK-001", GOOD_FILES)
        broken = [{"path": "src/a.py", "content": "x = 1\n"}]  # missing "action"

        for _ in range(MAX_ATTEMPTS):
            code = _run(_write_proposal(tmp_path, broken), tmp_path)

        assert code == 2
        assert _state(tmp_path)["TASK-001"]["repair_attempts"] == MAX_ATTEMPTS

    def test_a_pass_resets_the_counter(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, "TASK-001", GOOD_FILES)
        for _ in range(MAX_ATTEMPTS):
            _run(_write_proposal(tmp_path, BAD), tmp_path)

        good = [{"path": "src/a.py", "action": "create", "content": "x = 1\n"}]
        code = _run(_write_proposal(tmp_path, good), tmp_path)

        assert code == 0
        assert _state(tmp_path)["TASK-001"]["repair_attempts"] == 0

    def test_after_a_reset_it_takes_the_full_threshold_again_to_escalate(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, "TASK-001", GOOD_FILES)
        _run(_write_proposal(tmp_path, BAD), tmp_path)
        good = [{"path": "src/a.py", "action": "create", "content": "x = 1\n"}]
        _run(_write_proposal(tmp_path, good), tmp_path)  # resets to 0

        code1 = _run(_write_proposal(tmp_path, BAD), tmp_path)
        assert code1 == 1  # attempt 1 of a fresh streak, not a continuation of the old one

    def test_an_ordinary_ask_resets_the_counter(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, "TASK-001", ["rules.md"])
        _run(_write_proposal(tmp_path, BAD, task_id="TASK-001"), tmp_path)  # a FAIL first

        protected = [{"path": "rules.md", "action": "modify", "content": "# x\n"}]
        code = _run(_write_proposal(tmp_path, protected), tmp_path)  # ordinary ASK

        assert code == 2
        assert _state(tmp_path)["TASK-001"]["repair_attempts"] == 0

    def test_counters_are_kept_separately_per_task(self, tmp_path: Path) -> None:
        _write_plan_tasks(tmp_path, {"TASK-001": ["src/a.py"], "TASK-002": ["src/b.py"]})

        _run(_write_proposal(tmp_path, BAD, task_id="TASK-001"), tmp_path, task_id="TASK-001")
        _run(_write_proposal(tmp_path, BAD, task_id="TASK-001"), tmp_path, task_id="TASK-001")
        _run(_write_proposal(tmp_path, BAD, task_id="TASK-002"), tmp_path, task_id="TASK-002")

        state = _state(tmp_path)
        assert state["TASK-001"]["repair_attempts"] == 2
        assert state["TASK-002"]["repair_attempts"] == 1

    def test_state_file_is_created_fresh_when_missing(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, "TASK-001", GOOD_FILES)
        assert not (tmp_path / ".ai" / "task-state.json").exists()

        _run(_write_proposal(tmp_path, BAD), tmp_path)

        assert (tmp_path / ".ai" / "task-state.json").exists()

    def test_corrupt_state_file_does_not_crash_the_run(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, "TASK-001", GOOD_FILES)
        (tmp_path / ".ai" / "task-state.json").write_text("not json", encoding="utf-8")

        code = _run(_write_proposal(tmp_path, BAD), tmp_path)

        assert code == 1  # treated as a fresh count of 1, not a crash


class TestMaxAttemptsComesFromConfig:
    """The threshold is read from governance.max_repair_attempts, not hardcoded."""

    def test_the_real_config_matches_the_value_these_tests_assume(self) -> None:
        real = yaml.safe_load((ROOT / "config" / "config.yaml").read_text(encoding="utf-8"))
        assert real["governance"]["max_repair_attempts"] == MAX_ATTEMPTS

    def test_a_lower_config_value_escalates_sooner(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, "TASK-001", GOOD_FILES)
        custom_config = tmp_path / "custom_config.yaml"
        custom_config.write_text("governance:\n  max_repair_attempts: 1\n", encoding="utf-8")

        code = _run(_write_proposal(tmp_path, BAD), tmp_path, config_path=custom_config)

        assert code == 2  # already the 1st-of-1 allowed failure

    def test_an_invalid_config_value_falls_back_to_the_default(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, "TASK-001", GOOD_FILES)
        custom_config = tmp_path / "custom_config.yaml"
        custom_config.write_text("governance:\n  max_repair_attempts: 0\n", encoding="utf-8")

        code = _run(_write_proposal(tmp_path, BAD), tmp_path, config_path=custom_config)

        assert code == 1  # 0 is invalid; the built-in default (2) applies instead

    def test_a_missing_governance_section_falls_back_to_the_default(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, "TASK-001", GOOD_FILES)
        custom_config = tmp_path / "custom_config.yaml"
        custom_config.write_text("tests:\n  command: pytest\n", encoding="utf-8")

        code = _run(_write_proposal(tmp_path, BAD), tmp_path, config_path=custom_config)

        assert code == 1
