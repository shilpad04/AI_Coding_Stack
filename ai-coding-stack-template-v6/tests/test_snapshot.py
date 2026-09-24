import os
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
import pytest
from scripts.snapshot import (
    save_snapshot,
    list_snapshots,
    diff_snapshot,
    rollback_snapshot,
    _collect_workspace_files
)

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import traceability as trace  # noqa: E402


def test_snapshot_save_and_list(tmp_path):
    # Setup test workspace
    src_file = tmp_path / "src" / "main.py"
    src_file.parent.mkdir(parents=True, exist_ok=True)
    src_file.write_text("print('hello world')", encoding="utf-8")

    # Save snapshot
    snap_id = save_snapshot(tmp_path, "initial_commit")
    assert snap_id is not None
    assert "initial_commit" in snap_id

    # Verify manifest exists
    snap_manifest = tmp_path / ".ai" / "snapshots" / snap_id / "manifest.json"
    assert snap_manifest.exists()
    manifest_data = json.loads(snap_manifest.read_text(encoding="utf-8"))
    assert manifest_data["label"] == "initial_commit"
    assert "src/main.py" in manifest_data["files"]

    # Verify list
    snapshots = list_snapshots(tmp_path)
    assert len(snapshots) == 1
    assert snapshots[0]["snapshot_id"] == snap_id


def test_snapshot_diff(tmp_path):
    src_file = tmp_path / "src" / "main.py"
    src_file.parent.mkdir(parents=True, exist_ok=True)
    src_file.write_text("print('version 1')", encoding="utf-8")

    save_snapshot(tmp_path, "base")

    # Modify existing file and create new file
    src_file.write_text("print('version 2')", encoding="utf-8")
    new_file = tmp_path / "src" / "utils.py"
    new_file.write_text("def helper(): pass", encoding="utf-8")

    added, modified, deleted = diff_snapshot(tmp_path)
    assert "src/utils.py" in added
    assert "src/main.py" in modified
    assert len(deleted) == 0


def test_snapshot_rollback(tmp_path):
    # Setup base state
    src_file = tmp_path / "src" / "main.py"
    src_file.parent.mkdir(parents=True, exist_ok=True)
    src_file.write_text("print('original')", encoding="utf-8")

    save_snapshot(tmp_path, "good_state")

    # Make disruptive changes
    src_file.write_text("print('broken modifications')", encoding="utf-8")
    extra_file = tmp_path / "src" / "unwanted.py"
    extra_file.write_text("# trash code", encoding="utf-8")

    assert extra_file.exists()

    # Rollback to good_state
    success = rollback_snapshot(tmp_path)
    assert success is True

    # Verify original file restored and extra file removed
    assert src_file.read_text(encoding="utf-8") == "print('original')"
    assert not extra_file.exists()


# AI-tool rule files are project files: they must be snapshotted and restored.

TOOL_FILES = [
    ".cursorrules", ".clinerules", ".windsurfrules", ".roomodes",
    ".cursor/rules/team.mdc", ".roo/rules/team.md", ".windsurf/rules/team.md",
    ".github/copilot-instructions.md", ".claude/settings.json",
]


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_ai_tool_rule_files_are_snapshotted(tmp_path):
    for rel in TOOL_FILES:
        _write(tmp_path, rel, "rules")

    tracked = _collect_workspace_files(tmp_path)

    for rel in TOOL_FILES:
        assert rel in tracked, f"{rel} was skipped"


# Batch 5, item 7: snapshot.exclude in config/config.yaml is consulted too,
# not just the hardcoded IGNORE_DIRS/IGNORE_EXTS.

def test_snapshot_exclude_from_config_is_respected(tmp_path):
    _write(tmp_path, "config/config.yaml",
           "snapshot:\n  exclude:\n    - my_custom_cache\n    - \"*.custom\"\n    - notes/private.md\n")
    _write(tmp_path, "my_custom_cache/data.txt", "x")
    _write(tmp_path, "report.custom", "x")
    _write(tmp_path, "notes/private.md", "x")
    _write(tmp_path, "notes/public.md", "x")
    _write(tmp_path, "src/main.py", "x")

    tracked = set(_collect_workspace_files(tmp_path))

    assert tracked == {"config/config.yaml", "notes/public.md", "src/main.py"}


def test_missing_config_yaml_still_uses_hardcoded_defaults(tmp_path):
    _write(tmp_path, ".venv/lib.py", "x")
    _write(tmp_path, "src/main.py", "x")

    assert set(_collect_workspace_files(tmp_path)) == {"src/main.py"}


def test_unreadable_config_yaml_does_not_crash_the_scan(tmp_path):
    _write(tmp_path, "config/config.yaml", "not: valid: yaml: [")
    _write(tmp_path, "src/main.py", "x")

    assert "src/main.py" in set(_collect_workspace_files(tmp_path))


def test_caches_and_secrets_are_still_skipped(tmp_path):
    for rel in [".git/config", ".venv/lib.py", ".env", ".pytest_cache/v", ".mypy_cache/m",
                ".ai/snapshots/old/manifest.json", "node_modules/pkg/index.js"]:
        _write(tmp_path, rel, "x")
    _write(tmp_path, "src/main.py", "x")

    assert set(_collect_workspace_files(tmp_path)) == {"src/main.py"}


def test_rollback_restores_tool_files_and_removes_new_ones(tmp_path):
    _write(tmp_path, ".cursorrules", "original card")
    _write(tmp_path, ".cursor/rules/team.mdc", "original rule")
    save_snapshot(tmp_path, "before")

    _write(tmp_path, ".cursorrules", "rewritten card")
    _write(tmp_path, ".cursor/rules/new.mdc", "added later")

    assert rollback_snapshot(tmp_path) is True

    assert (tmp_path / ".cursorrules").read_text(encoding="utf-8") == "original card"
    assert (tmp_path / ".cursor/rules/team.mdc").read_text(encoding="utf-8") == "original rule"
    assert not (tmp_path / ".cursor/rules/new.mdc").exists()


# The traceability log is an audit trail: undo must never rewind or delete it.

def _log_event(root: Path, **event) -> Path:
    log = root / ".ai" / "traceability.ndjson"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event) + "\n")
    return log


def _stamp(delta_seconds: int) -> str:
    return (datetime.now() + timedelta(seconds=delta_seconds)).isoformat(timespec="milliseconds")


def test_traceability_log_is_not_snapshotted(tmp_path):
    _write(tmp_path, "src/a.py", "x")
    _log_event(tmp_path, event="apply", task_id="TASK-001", time=_stamp(0))

    assert set(_collect_workspace_files(tmp_path)) == {"src/a.py"}


def test_rollback_keeps_the_log_and_records_which_tasks_were_undone(tmp_path):
    _write(tmp_path, "src/a.py", "x")
    _log_event(tmp_path, event="apply", task_id="TASK-001", time=_stamp(-3600), files=[])
    snap_id = save_snapshot(tmp_path, "before")
    _log_event(tmp_path, event="apply", task_id="TASK-007", time=_stamp(5), files=[])
    _log_event(tmp_path, event="apply", task_id="TASK-008", time=_stamp(6), files=[])
    _write(tmp_path, "src/b.py", "y")

    assert rollback_snapshot(tmp_path) is True

    text = (tmp_path / ".ai" / "traceability.ndjson").read_text(encoding="utf-8")
    events = [json.loads(x) for x in text.splitlines()]
    assert [e.get("task_id") for e in events[:3]] == ["TASK-001", "TASK-007", "TASK-008"]  # nothing lost
    rollback = events[-1]
    assert rollback["event"] == "rollback"
    assert rollback["snapshot_id"] == snap_id
    assert rollback["tasks_undone"] == ["TASK-007", "TASK-008"]  # TASK-001 came before the snapshot
    assert rollback["files_deleted"] == ["src/b.py"]


def test_rollback_without_an_earlier_log_still_records_itself(tmp_path):
    _write(tmp_path, "src/a.py", "x")
    save_snapshot(tmp_path, "before")
    _write(tmp_path, "src/a.py", "changed")

    assert rollback_snapshot(tmp_path) is True

    assert (tmp_path / "src" / "a.py").read_text(encoding="utf-8") == "x"
    text = (tmp_path / ".ai" / "traceability.ndjson").read_text(encoding="utf-8")
    (event,) = [json.loads(x) for x in text.splitlines()]
    assert event["event"] == "rollback" and event["tasks_undone"] == []


def test_rollback_reports_undone_tasks_on_screen(tmp_path, capsys):
    _write(tmp_path, "src/a.py", "x")
    save_snapshot(tmp_path, "before")
    _log_event(tmp_path, event="apply", task_id="TASK-007", time=_stamp(5), files=[])

    rollback_snapshot(tmp_path)

    assert "TASK-007" in capsys.readouterr().out


# The rollback's own log entry must go through the same tamper-evident chain
# as every proposal apply — otherwise a rollback would be a silent gap an
# attacker could hide inside.

def test_rollback_log_entry_is_chained(tmp_path):
    _write(tmp_path, "src/a.py", "x")
    save_snapshot(tmp_path, "before")
    _write(tmp_path, "src/a.py", "changed")

    assert rollback_snapshot(tmp_path) is True

    (event,) = trace.read_log(tmp_path)
    assert event["event"] == "rollback"
    assert event["prev_hash"] == trace.GENESIS_HASH
    assert event["hash"]


def test_rollback_chains_from_the_previous_real_entry(tmp_path):
    _write(tmp_path, "src/a.py", "x")
    trace.append(tmp_path, {"event": "apply", "task_id": "TASK-001", "time": _stamp(-3600), "files": []})
    save_snapshot(tmp_path, "before")
    _write(tmp_path, "src/a.py", "changed")

    assert rollback_snapshot(tmp_path) is True

    apply_event, rollback_event = trace.read_log(tmp_path)
    assert rollback_event["prev_hash"] == apply_event["hash"]
    assert trace.verify_chain(trace.read_log(tmp_path)) == []


# Batch 2: plan.json and .ai/proposals/ are the stack's own control state,
# not project files — never snapshotted, so rollback can neither rewind nor
# delete them. plan.json is instead patched directly: only the tasks the
# audit log shows as undone go back to PLANNED; everything else in the plan
# (other tasks, phases, edits since the snapshot) is left exactly as it was.

def _write_plan(root: Path, phases: list) -> Path:
    path = root / ".ai" / "plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"project": "p", "phases": phases}), encoding="utf-8")
    return path


def test_task_state_json_is_not_snapshotted(tmp_path):
    _write(tmp_path, "src/a.py", "x")
    _write(tmp_path, ".ai/task-state.json", '{"TASK-001": {"repair_attempts": 1}}')

    assert set(_collect_workspace_files(tmp_path)) == {"src/a.py"}


def test_plan_json_is_not_snapshotted(tmp_path):
    _write(tmp_path, "src/a.py", "x")
    _write_plan(tmp_path, [{"id": "P", "tasks": [{"task_id": "TASK-001", "status": "PLANNED"}]}])

    assert set(_collect_workspace_files(tmp_path)) == {"src/a.py"}


def test_plan_approval_json_is_not_snapshotted(tmp_path):
    _write(tmp_path, "src/a.py", "x")
    _write(tmp_path, ".ai/plan-approval.json", '{"TASK-001": {"allowed_files": ["src/a.py"]}}')

    assert set(_collect_workspace_files(tmp_path)) == {"src/a.py"}


def test_proposals_directory_is_not_snapshotted(tmp_path):
    _write(tmp_path, "src/a.py", "x")
    _write(tmp_path, ".ai/proposals/proposal_TASK-001.json", "{}")

    assert set(_collect_workspace_files(tmp_path)) == {"src/a.py"}


def test_rollback_does_not_delete_proposal_files_created_after_snapshot(tmp_path):
    _write(tmp_path, "src/a.py", "x")
    save_snapshot(tmp_path, "before")
    _write(tmp_path, ".ai/proposals/proposal_TASK-002.json", "{}")

    assert rollback_snapshot(tmp_path) is True
    assert (tmp_path / ".ai" / "proposals" / "proposal_TASK-002.json").exists()


def test_rollback_leaves_plan_json_untouched_when_nothing_was_undone(tmp_path):
    _write(tmp_path, "src/a.py", "x")
    save_snapshot(tmp_path, "before")
    plan_path = _write_plan(tmp_path, [{"id": "P", "tasks": [
        {"task_id": "TASK-001", "status": "PLANNED"},
        {"task_id": "TASK-002", "status": "PLANNED", "note": "added after the snapshot"},
    ]}])
    before_content = plan_path.read_text(encoding="utf-8")

    assert rollback_snapshot(tmp_path) is True

    assert plan_path.read_text(encoding="utf-8") == before_content


def test_rollback_reopens_only_the_tasks_the_log_says_were_undone(tmp_path):
    _write(tmp_path, "src/a.py", "x")
    save_snapshot(tmp_path, "before")
    _log_event(tmp_path, event="apply", task_id="TASK-001", time=_stamp(5), files=[])
    plan_path = _write_plan(tmp_path, [{"id": "P", "tasks": [
        {"task_id": "TASK-001", "status": "COMPLETED"},
        {"task_id": "TASK-002", "status": "COMPLETED"},
    ]}])

    assert rollback_snapshot(tmp_path) is True

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    tasks = {t["task_id"]: t["status"] for t in plan["phases"][0]["tasks"]}
    assert tasks["TASK-001"] == "PLANNED"     # undone since the snapshot — reopened
    assert tasks["TASK-002"] == "COMPLETED"   # never logged as applied after it — untouched


def test_rollback_reports_reopened_tasks_on_screen(tmp_path, capsys):
    _write(tmp_path, "src/a.py", "x")
    save_snapshot(tmp_path, "before")
    _log_event(tmp_path, event="apply", task_id="TASK-001", time=_stamp(5), files=[])
    _write_plan(tmp_path, [{"id": "P", "tasks": [{"task_id": "TASK-001", "status": "COMPLETED"}]}])

    rollback_snapshot(tmp_path)

    out = capsys.readouterr().out
    assert "TASK-001" in out and "PLANNED" in out


def test_rollback_notes_a_task_missing_from_the_current_plan(tmp_path, capsys):
    _write(tmp_path, "src/a.py", "x")
    save_snapshot(tmp_path, "before")
    _log_event(tmp_path, event="apply", task_id="TASK-999", time=_stamp(5), files=[])
    _write_plan(tmp_path, [{"id": "P", "tasks": [{"task_id": "TASK-001", "status": "PLANNED"}]}])

    rollback_snapshot(tmp_path)

    assert "TASK-999" in capsys.readouterr().out


def test_corrupt_plan_json_does_not_crash_the_rollback(tmp_path):
    _write(tmp_path, "src/a.py", "x")
    save_snapshot(tmp_path, "before")
    _log_event(tmp_path, event="apply", task_id="TASK-001", time=_stamp(5), files=[])
    (tmp_path / ".ai" / "plan.json").write_text("not json", encoding="utf-8")

    assert rollback_snapshot(tmp_path) is True  # source files are still restored


def test_rollback_does_not_overwrite_current_plan_even_from_a_legacy_snapshot(tmp_path):
    # A snapshot saved before plan.json was excluded still lists it in its
    # manifest. Rollback must not use that copy to overwrite today's plan.
    _write(tmp_path, "src/a.py", "x")
    plan_path = _write_plan(tmp_path, [{"id": "P", "tasks": [{"task_id": "TASK-001", "status": "PLANNED"}]}])
    snap_id = save_snapshot(tmp_path, "legacy")
    snap_dir = tmp_path / ".ai" / "snapshots" / snap_id
    (snap_dir / "files" / ".ai").mkdir(parents=True, exist_ok=True)
    (snap_dir / "files" / ".ai" / "plan.json").write_bytes(plan_path.read_bytes())
    manifest_path = snap_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][".ai/plan.json"] = "legacy-hash"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    plan_path.write_text(json.dumps({"project": "p", "phases": [{"id": "P", "tasks": [
        {"task_id": "TASK-001", "status": "COMPLETED"},
        {"task_id": "TASK-002", "status": "PLANNED"},
    ]}]}), encoding="utf-8")
    current_content = plan_path.read_text(encoding="utf-8")

    assert rollback_snapshot(tmp_path, snap_id) is True

    assert plan_path.read_text(encoding="utf-8") == current_content
