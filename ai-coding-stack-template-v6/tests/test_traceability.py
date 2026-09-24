"""
tests/test_traceability.py
=========================
Tests for scripts/traceability.py: the audit log of which task changed which
file, which lines and which functions.

Covers:
- changed_ranges     exact line numbers, old-side and new-side
- file_entry         function detection (exact for Python, best guess for TS/Java/Go)
- append / read_log  the .ai/traceability.ndjson file
- main               the "who changed what" query command
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import traceability as t  # noqa: E402


# changed_ranges

class TestChangedRanges:
    def test_identical_text_has_no_changes(self):
        assert t.changed_ranges("a\nb\n", "a\nb\n") == ([], [])

    def test_replaced_line(self):
        removed, added = t.changed_ranges("a\nb\nc\n", "a\nB\nc\n")
        assert removed == [[2, 2]]
        assert added == [[2, 2]]

    def test_inserted_lines(self):
        removed, added = t.changed_ranges("a\nc\n", "a\nb1\nb2\nc\n")
        assert removed == []
        assert added == [[2, 3]]

    def test_deleted_lines(self):
        removed, added = t.changed_ranges("a\nb\nc\nd\n", "a\nd\n")
        assert removed == [[2, 3]]
        assert added == []

    def test_new_file_is_all_added(self):
        removed, added = t.changed_ranges("", "x\ny\nz\n")
        assert removed == []
        assert added == [[1, 3]]

    def test_deleted_file_is_all_removed(self):
        removed, added = t.changed_ranges("x\ny\n", "")
        assert removed == [[1, 2]]
        assert added == []

    def test_line_endings_alone_are_not_a_change(self):
        assert t.changed_ranges("a\r\nb\r\n", "a\nb\n") == ([], [])


# file_entry: Python (exact)

PY_OLD = """import os

def a():
    return 1

def b():
    return 2
"""


def _names(entry):
    return {(f["name"], f["change"]) for f in entry["functions"]}


class TestPythonFunctions:
    def test_changed_body_marks_only_that_function(self):
        new = PY_OLD.replace("return 1", "return 10")
        e = t.file_entry("src/m.py", "modify", PY_OLD, new)
        assert e["function_detection"] == "exact"
        assert e["added"] == [[4, 4]] and e["removed"] == [[4, 4]]
        assert (e["lines_added"], e["lines_removed"]) == (1, 1)
        assert _names(e) == {("a", "modified")}

    def test_new_function_is_added_and_blank_line_is_not_noise(self):
        new = PY_OLD + "\ndef c():\n    return 3\n"
        e = t.file_entry("src/m.py", "modify", PY_OLD, new)
        assert _names(e) == {("c", "added")}

    def test_deleted_function_is_removed(self):
        new = "import os\n\ndef a():\n    return 1\n"
        e = t.file_entry("src/m.py", "modify", PY_OLD, new)
        assert ("b", "removed") in _names(e)

    def test_method_gets_its_class_name(self):
        old = "class K:\n    def m(self):\n        return 1\n"
        new = "class K:\n    def m(self):\n        return 2\n"
        e = t.file_entry("src/k.py", "modify", old, new)
        assert _names(e) == {("K.m", "modified")}

    def test_change_outside_functions_is_reported(self):
        new = PY_OLD.replace("import os", "import os\nimport sys")
        e = t.file_entry("src/m.py", "modify", PY_OLD, new)
        assert _names(e) == {(t.OUTSIDE, "modified")}

    def test_decorator_line_belongs_to_its_function(self):
        old = "@cache\ndef a():\n    return 1\n"
        new = "@cache(1)\ndef a():\n    return 1\n"
        e = t.file_entry("src/m.py", "modify", old, new)
        assert _names(e) == {("a", "modified")}

    def test_deleting_a_file_removes_all_its_functions(self):
        e = t.file_entry("src/m.py", "delete", PY_OLD, "")
        assert {("a", "removed"), ("b", "removed")} <= _names(e)
        assert e["lines_added"] == 0 and e["lines_removed"] == 7

    def test_new_file_adds_all_its_functions(self):
        e = t.file_entry("src/m.py", "create", "", PY_OLD)
        assert {("a", "added"), ("b", "added")} <= _names(e)

    def test_unparseable_old_file_gives_no_function_names(self):
        e = t.file_entry("src/m.py", "modify", "def broken(\n", PY_OLD)
        assert e["functions"] == [] and e["function_detection"] == "none"


# file_entry: other languages (best guess: nearest declaration above the change)

class TestOtherLanguages:
    TS = (
        "export function total(items: number[]): number {\n"
        "  let sum = 0;\n"
        "  return sum;\n"
        "}\n"
        "\n"
        "export const price = (x: number) => {\n"
        "  return x;\n"
        "};\n"
    )

    def test_typescript_function(self):
        e = t.file_entry("src/a.ts", "modify", self.TS, self.TS.replace("return sum;", "return sum + 1;"))
        assert e["function_detection"] == "approximate"
        assert _names(e) == {("total", "touched")}

    def test_typescript_arrow_function(self):
        e = t.file_entry("src/a.ts", "modify", self.TS, self.TS.replace("return x;", "return x * 2;"))
        assert _names(e) == {("price", "touched")}

    def test_typescript_method_skips_if_blocks(self):
        old = (
            "export class Svc {\n"
            "  private cache = {};\n"
            "\n"
            "  async load(id: string): Promise<void> {\n"
            "    if (id) {\n"
            "      this.cache = {};\n"
            "    }\n"
            "  }\n"
            "}\n"
        )
        e = t.file_entry("src/svc.ts", "modify", old, old.replace("this.cache = {};", "this.cache = { id };"))
        assert _names(e) == {("load", "touched")}

    def test_java_method(self):
        old = "public class A {\n    public int total(int x) {\n        return x;\n    }\n}\n"
        e = t.file_entry("src/A.java", "modify", old, old.replace("return x;", "return x + 1;"))
        assert _names(e) == {("total", "touched")}

    def test_go_method(self):
        old = "package main\n\nfunc (s *Svc) Load(id string) error {\n\treturn nil\n}\n"
        e = t.file_entry("svc.go", "modify", old, old.replace("return nil", "return err"))
        assert _names(e) == {("Load", "touched")}

    def test_other_file_types_have_lines_but_no_functions(self):
        e = t.file_entry("README.md", "modify", "a\nb\n", "a\nB\n")
        assert e["functions"] == [] and e["function_detection"] == "none"
        assert e["added"] == [[2, 2]]


# The log file

class TestLogFile:
    def test_append_creates_folder_and_writes_one_line_per_event(self, tmp_path):
        t.append(tmp_path, {"event": "apply", "task_id": "TASK-001"})
        t.append(tmp_path, {"event": "apply", "task_id": "TASK-002"})

        lines = (tmp_path / ".ai" / "traceability.ndjson").read_text(encoding="utf-8").splitlines()
        assert [json.loads(x)["task_id"] for x in lines] == ["TASK-001", "TASK-002"]

    def test_read_log_returns_events_in_order(self, tmp_path):
        t.append(tmp_path, {"event": "apply", "task_id": "TASK-001"})
        (event,) = t.read_log(tmp_path)
        assert event["event"] == "apply" and event["task_id"] == "TASK-001"

    def test_read_log_without_a_log_is_empty(self, tmp_path):
        assert t.read_log(tmp_path) == []

    def test_read_log_refuses_a_corrupt_line(self, tmp_path):
        log = tmp_path / ".ai" / "traceability.ndjson"
        log.parent.mkdir()
        log.write_text('{"event": "apply"}\nnot json\n', encoding="utf-8")
        with pytest.raises(ValueError, match="line 2"):
            t.read_log(tmp_path)

    def test_read_texts_gives_empty_string_for_new_files(self, tmp_path):
        (tmp_path / "a.py").write_bytes(b"x = 1\n")
        assert t.read_texts(tmp_path, ["a.py", "new.py"]) == {"a.py": "x = 1\n", "new.py": ""}

    def test_record_apply_builds_a_complete_entry(self, tmp_path):
        files = [{"path": "src/m.py", "action": "create", "content": "def a():\n    return 1\n"}]
        t.record_apply(tmp_path, "TASK-001", "p.json", files, {"src/m.py": ""}, "PASS")

        (event,) = t.read_log(tmp_path)
        assert event["event"] == "apply" and event["task_id"] == "TASK-001"
        assert event["proposal"] == "p.json" and event["reconcile"] == "PASS"
        assert event["time"]
        (entry,) = event["files"]
        assert entry["path"] == "src/m.py" and entry["added"] == [[1, 2]]
        assert _names(entry) == {("a", "added")}
        assert entry["content_hash"] == t._content_hash("def a():\n    return 1\n")

    def test_deleted_file_has_no_content_hash(self, tmp_path):
        files = [{"path": "src/m.py", "action": "delete"}]
        t.record_apply(tmp_path, "TASK-001", "p.json", files, {"src/m.py": "x = 1\n"}, "PASS")
        (event,) = t.read_log(tmp_path)
        (entry,) = event["files"]
        assert entry["content_hash"] is None


# Drift detection: files changed on disk with no matching log entry
# (i.e. someone bypassed the proposal flow).

class TestDriftDetection:
    def test_file_never_logged_is_untracked(self, tmp_path):
        findings = t.detect_drift(tmp_path, [], {"src/a.py": "hash1"})
        assert findings == [{"path": "src/a.py", "reason": "untracked", "logged_hash": None}]

    def test_file_matching_its_last_logged_apply_is_clean(self, tmp_path):
        digest = t._content_hash("x = 1\n")
        events = [{"event": "apply", "files": [
            {"path": "src/a.py", "content_hash": digest}]}]
        assert t.detect_drift(tmp_path, events, {"src/a.py": digest}) == []

    def test_file_edited_after_being_logged_is_flagged_as_diverged(self, tmp_path):
        logged = t._content_hash("x = 1\n")
        on_disk = t._content_hash("x = 2\n")
        events = [{"event": "apply", "files": [
            {"path": "src/a.py", "content_hash": logged}]}]
        findings = t.detect_drift(tmp_path, events, {"src/a.py": on_disk})
        assert findings == [{"path": "src/a.py", "reason": "diverged", "logged_hash": logged}]

    def test_later_apply_overrides_an_earlier_one_for_the_same_path(self, tmp_path):
        first = t._content_hash("x = 1\n")
        second = t._content_hash("x = 2\n")
        events = [
            {"event": "apply", "files": [{"path": "src/a.py", "content_hash": first}]},
            {"event": "apply", "files": [{"path": "src/a.py", "content_hash": second}]},
        ]
        assert t.detect_drift(tmp_path, events, {"src/a.py": second}) == []

    def test_file_logged_as_deleted_but_still_present_is_flagged(self, tmp_path):
        events = [{"event": "apply", "files": [
            {"path": "src/a.py", "content_hash": None}]}]
        recreated = t._content_hash("back again\n")
        findings = t.detect_drift(tmp_path, events, {"src/a.py": recreated})
        assert findings == [{"path": "src/a.py", "reason": "diverged", "logged_hash": None}]

    def test_files_untouched_by_any_apply_are_not_reported(self, tmp_path):
        events = [{"event": "apply", "files": [{"path": "src/a.py", "content_hash": "h"}]}]
        assert t.detect_drift(tmp_path, events, {"src/a.py": "h"}) == []

    def test_rollback_restored_file_matches_the_snapshot_manifest(self, tmp_path):
        snap = tmp_path / ".ai" / "snapshots" / "snap1"
        snap.mkdir(parents=True)
        restored_hash = t._content_hash("original\n")
        (snap / "manifest.json").write_text(
            json.dumps({"files": {"src/a.py": restored_hash}}), encoding="utf-8")
        events = [
            {"event": "apply", "files": [{"path": "src/a.py", "content_hash": t._content_hash("changed\n")}]},
            {"event": "rollback", "snapshot_id": "snap1", "files_deleted": []},
        ]
        assert t.detect_drift(tmp_path, events, {"src/a.py": restored_hash}) == []

    def test_rollback_deleted_file_still_on_disk_is_flagged(self, tmp_path):
        snap = tmp_path / ".ai" / "snapshots" / "snap1"
        snap.mkdir(parents=True)
        (snap / "manifest.json").write_text(json.dumps({"files": {}}), encoding="utf-8")
        events = [{"event": "rollback", "snapshot_id": "snap1", "files_deleted": ["src/new.py"]}]
        recreated = t._content_hash("back\n")
        findings = t.detect_drift(tmp_path, events, {"src/new.py": recreated})
        assert findings == [{"path": "src/new.py", "reason": "diverged", "logged_hash": None}]

    def test_missing_snapshot_manifest_does_not_crash(self, tmp_path):
        events = [{"event": "rollback", "snapshot_id": "does-not-exist", "files_deleted": []}]
        assert t.detect_drift(tmp_path, events, {}) == []

    def test_multiple_findings_are_sorted_by_path(self, tmp_path):
        findings = t.detect_drift(tmp_path, [], {"z.py": "h1", "a.py": "h2"})
        assert [f["path"] for f in findings] == ["a.py", "z.py"]


# Tamper-evident log: each line chains to the one before it, so an edited
# or deleted line becomes detectable.

class TestHashChain:
    def test_first_entry_chains_from_genesis(self, tmp_path, monkeypatch):
        monkeypatch.setattr(t.getpass, "getuser", lambda: "prasad")
        t.append(tmp_path, {"event": "apply", "task_id": "TASK-001"})
        (event,) = t.read_log(tmp_path)
        assert event["prev_hash"] == t.GENESIS_HASH
        assert event["hash"] == t._chain_hash(
            t.GENESIS_HASH, {"event": "apply", "task_id": "TASK-001", "user": "prasad"})

    def test_second_entry_chains_from_the_first(self, tmp_path):
        t.append(tmp_path, {"event": "apply", "task_id": "TASK-001"})
        t.append(tmp_path, {"event": "apply", "task_id": "TASK-002"})
        first, second = t.read_log(tmp_path)
        assert second["prev_hash"] == first["hash"]
        assert first["hash"] != second["hash"]

    def test_clean_chain_has_no_breaks(self, tmp_path):
        t.append(tmp_path, {"event": "apply", "task_id": "TASK-001"})
        t.append(tmp_path, {"event": "apply", "task_id": "TASK-002"})
        t.append(tmp_path, {"event": "apply", "task_id": "TASK-003"})
        assert t.verify_chain(t.read_log(tmp_path)) == []

    def test_empty_log_has_no_breaks(self):
        assert t.verify_chain([]) == []

    def test_editing_a_line_in_place_is_caught(self, tmp_path):
        t.append(tmp_path, {"event": "apply", "task_id": "TASK-001"})
        t.append(tmp_path, {"event": "apply", "task_id": "TASK-002"})
        t.append(tmp_path, {"event": "apply", "task_id": "TASK-003"})

        log = tmp_path / ".ai" / "traceability.ndjson"
        lines = log.read_text(encoding="utf-8").splitlines()
        tampered = json.loads(lines[1])
        tampered["task_id"] = "TASK-999"  # content changed, hash left stale
        lines[1] = json.dumps(tampered)
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")

        breaks = t.verify_chain(t.read_log(tmp_path))
        assert len(breaks) == 1 and breaks[0]["line"] == 2

    def test_deleting_a_line_is_caught(self, tmp_path):
        t.append(tmp_path, {"event": "apply", "task_id": "TASK-001"})
        t.append(tmp_path, {"event": "apply", "task_id": "TASK-002"})
        t.append(tmp_path, {"event": "apply", "task_id": "TASK-003"})

        log = tmp_path / ".ai" / "traceability.ndjson"
        lines = log.read_text(encoding="utf-8").splitlines()
        del lines[1]  # TASK-002's line removed outright
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")

        breaks = t.verify_chain(t.read_log(tmp_path))
        assert len(breaks) == 1 and breaks[0]["line"] == 2  # TASK-003's line, now second

    def test_truncating_the_last_line_is_a_documented_blind_spot(self, tmp_path):
        # Nothing comes after the last line to notice it's gone — a hash
        # chain alone can't catch a trailing deletion. Documented, not a bug.
        t.append(tmp_path, {"event": "apply", "task_id": "TASK-001"})
        t.append(tmp_path, {"event": "apply", "task_id": "TASK-002"})

        log = tmp_path / ".ai" / "traceability.ndjson"
        first_line = log.read_text(encoding="utf-8").splitlines()[0]
        log.write_text(first_line + "\n", encoding="utf-8")

        assert t.verify_chain(t.read_log(tmp_path)) == []

    def test_pre_chaining_legacy_lines_are_not_reported_as_broken(self, tmp_path):
        log = tmp_path / ".ai" / "traceability.ndjson"
        log.parent.mkdir(parents=True)
        log.write_text(json.dumps({"event": "apply", "task_id": "LEGACY-1"}) + "\n", encoding="utf-8")

        t.append(tmp_path, {"event": "apply", "task_id": "TASK-002"})

        events = t.read_log(tmp_path)
        assert t.verify_chain(events) == []
        assert events[1]["prev_hash"] == t.GENESIS_HASH  # chaining restarts after a legacy line


# Who made each change: OS username on every entry, AI model name on applies
# that declare one.

class TestAuthorship:
    def test_append_stamps_the_current_os_user(self, tmp_path, monkeypatch):
        monkeypatch.setattr(t.getpass, "getuser", lambda: "prasad")
        t.append(tmp_path, {"event": "apply", "task_id": "TASK-001"})
        (event,) = t.read_log(tmp_path)
        assert event["user"] == "prasad"

    def test_record_apply_includes_the_model_when_given(self, tmp_path):
        files = [{"path": "src/m.py", "action": "create", "content": "x = 1\n"}]
        t.record_apply(tmp_path, "TASK-001", "p.json", files, {"src/m.py": ""}, "PASS",
                       model="claude-sonnet-5")
        (event,) = t.read_log(tmp_path)
        assert event["model"] == "claude-sonnet-5"

    def test_record_apply_model_defaults_to_none(self, tmp_path):
        files = [{"path": "src/m.py", "action": "create", "content": "x = 1\n"}]
        t.record_apply(tmp_path, "TASK-001", "p.json", files, {"src/m.py": ""}, "PASS")
        (event,) = t.read_log(tmp_path)
        assert event["model"] is None


class TestVerifyChainCLI:
    def test_clean_log_exits_zero(self, tmp_path, capsys):
        t.append(tmp_path, {"event": "apply", "task_id": "TASK-001"})
        code = t.main(["--root", str(tmp_path), "--verify-chain"])
        assert code == 0
        assert "intact" in capsys.readouterr().out.lower()

    def test_no_log_at_all_is_clean(self, tmp_path, capsys):
        code = t.main(["--root", str(tmp_path), "--verify-chain"])
        assert code == 0

    def test_tampered_log_exits_nonzero_and_names_the_line(self, tmp_path, capsys):
        t.append(tmp_path, {"event": "apply", "task_id": "TASK-001"})
        t.append(tmp_path, {"event": "apply", "task_id": "TASK-002"})
        log = tmp_path / ".ai" / "traceability.ndjson"
        lines = log.read_text(encoding="utf-8").splitlines()
        tampered = json.loads(lines[0])
        tampered["task_id"] = "HACKED"
        lines[0] = json.dumps(tampered)
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")

        code = t.main(["--root", str(tmp_path), "--verify-chain"])
        out = capsys.readouterr().out
        assert code == 1
        assert "line 1" in out


class TestCheckDriftCLI:
    def test_reports_untracked_file_and_exits_nonzero(self, tmp_path, capsys):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")

        code = t.main(["--root", str(tmp_path), "--check-drift"])

        out = capsys.readouterr().out
        assert code == 1
        assert "src/a.py" in out

    def test_clean_workspace_exits_zero(self, tmp_path, capsys):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "a.py").write_bytes(b"x = 1\n")  # write_text would translate \n on Windows
        t.record_apply(tmp_path, "TASK-001", "p.json",
                       [{"path": "src/a.py", "action": "create", "content": "x = 1\n"}],
                       {"src/a.py": ""}, "PASS")

        code = t.main(["--root", str(tmp_path), "--check-drift"])

        out = capsys.readouterr().out
        assert code == 0
        assert "No files changed" in out

    def test_corrupt_log_still_errors_with_check_drift(self, tmp_path, capsys):
        log = tmp_path / ".ai" / "traceability.ndjson"
        log.parent.mkdir()
        log.write_text("garbage\n", encoding="utf-8")

        code = t.main(["--root", str(tmp_path), "--check-drift"])

        assert code == 1
        assert "line 1" in capsys.readouterr().err


# The query command

class TestQueryCommand:
    @pytest.fixture()
    def root(self, tmp_path):
        t.record_apply(tmp_path, "TASK-001", "p1.json",
                       [{"path": "src/m.py", "action": "create", "content": "def a():\n    return 1\n"}],
                       {"src/m.py": ""}, "PASS")
        t.record_apply(tmp_path, "TASK-002", "p2.json",
                       [{"path": "src/m.py", "action": "modify", "content": "def a():\n    return 2\n"},
                        {"path": "src/n.py", "action": "create", "content": "def z():\n    pass\n"}],
                       {"src/m.py": "def a():\n    return 1\n", "src/n.py": ""}, "PASS")
        t.append(tmp_path, {"event": "rollback", "time": "2026-01-01T00:00:00.000",
                            "snapshot_id": "snap1", "tasks_undone": ["TASK-002"]})
        return tmp_path

    def _run(self, root, capsys, *args):
        code = t.main(["--root", str(root), *args])
        return code, capsys.readouterr().out

    def test_by_file_shows_every_task_that_touched_it(self, root, capsys):
        code, out = self._run(root, capsys, "--file", "src/m.py")
        assert code == 0
        assert "TASK-001" in out and "TASK-002" in out
        assert "src/n.py" not in out
        assert "a (added)" in out and "a (modified)" in out

    def test_by_task_shows_its_files_and_line_numbers(self, root, capsys):
        _, out = self._run(root, capsys, "--task", "TASK-002")
        assert "src/m.py" in out and "src/n.py" in out
        assert "+1 -1" in out and "2" in out
        assert "TASK-001" not in out.replace("TASK-002", "")

    def test_by_function_finds_the_tasks(self, root, capsys):
        _, out = self._run(root, capsys, "--function", "z")
        assert "TASK-002" in out and "src/n.py" in out and "src/m.py" not in out

    def test_task_query_also_shows_that_it_was_rolled_back(self, root, capsys):
        _, out = self._run(root, capsys, "--task", "TASK-002")
        assert "ROLLBACK" in out and "snap1" in out

    def test_no_filter_shows_everything(self, root, capsys):
        _, out = self._run(root, capsys)
        assert out.count("TASK-00") >= 4 and "ROLLBACK" in out

    def test_corrupt_log_is_an_error_not_silence(self, tmp_path, capsys):
        log = tmp_path / ".ai" / "traceability.ndjson"
        log.parent.mkdir()
        log.write_text("garbage\n", encoding="utf-8")
        code = t.main(["--root", str(tmp_path)])
        assert code == 1
        assert "line 1" in capsys.readouterr().err
