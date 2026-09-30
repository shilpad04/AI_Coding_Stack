#!/usr/bin/env python3
"""
scripts/snapshot.py — Git-Free Local Snapshot & Rollback Engine

Enables instant, lossless file checkpoints and rollbacks without Git.
Snapshots are stored in `.ai/snapshots/<timestamp>_<label>/` with a metadata manifest.

Usage:
    python scripts/snapshot.py save [label]
    python scripts/snapshot.py list
    python scripts/snapshot.py rollback [snapshot_id]
    python scripts/snapshot.py diff [snapshot_id]
"""

import os
import sys
import json
import shutil
import hashlib
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Tuple

sys.path.insert(0, str(Path(__file__).parent))
import traceability as trace  # noqa: E402

IGNORE_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "node_modules",
    "dist", "build", ".pytest_cache", ".ai/snapshots", ".ai/backups",
    ".mypy_cache", ".ruff_cache", "coverage"
}

IGNORE_EXTS = {
    ".pyc", ".pyo", ".pyd", ".so", ".dll", ".dylib", ".exe"
}

# Hidden names are skipped by default (.git, .env, caches). These are project
# files, not caches: the stack's own folders and each AI tool's rule files
# (Cursor, Cline/Roo, Windsurf, GitHub Copilot, Claude Code), so an undo
# covers them too.
KEEP_HIDDEN = {
    ".ai", ".agents",
    ".cursorrules", ".cursor",
    ".clinerules", ".roomodes", ".roo",
    ".windsurfrules", ".windsurf",
    ".github", ".claude",
}

# The audit log (scripts/traceability.py). Never snapshotted, so an undo can
# neither rewind nor delete it; an undo adds its own entry to it instead.
TRACE_LOG = ".ai/traceability.ndjson"

PLAN_FILE = ".ai/plan.json"

# The stack's own control state, not project files: never snapshotted, so a
# rollback can neither overwrite nor delete them.
#   - TRACE_LOG / task-state.json keep their own history across rollbacks.
#   - PLAN_FILE is instead patched by _reopen_undone_tasks() below, so an
#     approved requirement change since the snapshot is never lost.
#   - plan-approval.json is a human sign-off record (scripts/approve_plan.py)
#     and must survive a source-code rollback just as much as the log does.
#   - .ai/proposals/ is a historical record; rollback must not delete one.
CONTROL_FILES = {TRACE_LOG, PLAN_FILE, ".ai/task-state.json", ".ai/plan-approval.json"}
CONTROL_DIRS = (".ai/proposals",)


def _file_hash(path: Path) -> str:
    """Calculate SHA-256 hash of a file."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _load_snapshot_exclude(root: Path) -> Dict[str, Set[str]]:
    """Read snapshot.exclude from config/config.yaml, split into name/ext/path
    buckets for _is_ignored(). Missing or unreadable config yields empty
    buckets — the hardcoded IGNORE_DIRS/IGNORE_EXTS/KEEP_HIDDEN still apply.
    """
    extra: Dict[str, Set[str]] = {"names": set(), "exts": set(), "paths": set()}
    config_path = root / "config" / "config.yaml"
    if not config_path.is_file():
        return extra
    try:
        import yaml
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return extra
    if not isinstance(data, dict):
        return extra
    for entry in (data.get("snapshot") or {}).get("exclude") or []:
        entry = str(entry)
        if entry.startswith("*."):
            extra["exts"].add(entry[1:].lower())       # "*.pyc" -> ".pyc"
        elif entry.startswith("**/"):
            extra["names"].add(entry[3:])
        elif "/" in entry:
            extra["paths"].add(entry)
        else:
            extra["names"].add(entry)
    return extra


def _is_ignored(rel_path: str, extra: Dict[str, Set[str]] = None) -> bool:
    """Check if a relative path should be ignored from snapshots.

    `extra` (from _load_snapshot_exclude) adds config-driven exclusions on
    top of the hardcoded defaults below — it never replaces them.
    """
    extra = extra or {"names": set(), "exts": set(), "paths": set()}
    path_obj = Path(rel_path)
    for part in path_obj.parts:
        if part in IGNORE_DIRS or part in extra["names"]:
            return True
        if part.startswith(".") and part not in KEEP_HIDDEN:
            return True
    if path_obj.suffix.lower() in IGNORE_EXTS or path_obj.suffix.lower() in extra["exts"]:
        return True
    if rel_path.startswith(".ai/snapshots") or rel_path.startswith(".ai/backups"):
        return True
    if rel_path in CONTROL_FILES:
        return True
    if any(rel_path == d or rel_path.startswith(d + "/") for d in CONTROL_DIRS):
        return True
    if any(rel_path == p or rel_path.startswith(p + "/") for p in extra["paths"]):
        return True
    return False


def _collect_workspace_files(root: Path) -> Dict[str, str]:
    """Scan workspace and return a dict of {rel_path: file_hash}."""
    extra = _load_snapshot_exclude(root)
    files_map = {}
    for dirpath, dirnames, filenames in os.walk(root):
        # Filter directories in-place
        dirnames[:] = [
            d for d in dirnames
            if not _is_ignored((Path(dirpath, d).relative_to(root)).as_posix(), extra)
        ]
        for f in filenames:
            file_p = Path(dirpath, f)
            rel_p = file_p.relative_to(root).as_posix()
            if not _is_ignored(rel_p, extra):
                files_map[rel_p] = _file_hash(file_p)
    return files_map


def save_snapshot(root: Path, label: str = "checkpoint") -> str:
    """Create a new snapshot of the current workspace."""
    clean_label = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in label).strip("_") or "checkpoint"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_id = f"{timestamp}_{clean_label}"
    snapshot_dir = root / ".ai" / "snapshots" / snapshot_id
    files_dir = snapshot_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)

    files_map = _collect_workspace_files(root)
    for rel_path in files_map:
        src_path = root / rel_path
        dst_path = files_dir / rel_path
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dst_path)

    manifest = {
        "snapshot_id": snapshot_id,
        "label": label,
        "created_at": datetime.now().isoformat(),
        "file_count": len(files_map),
        "files": files_map
    }

    manifest_path = snapshot_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"[SNAPSHOT] Checkpoint saved successfully: {snapshot_id}")
    print(f"[SNAPSHOT] Total files tracked: {len(files_map)}")
    return snapshot_id


def list_snapshots(root: Path) -> List[Dict]:
    """List all available snapshots."""
    snapshots_dir = root / ".ai" / "snapshots"
    if not snapshots_dir.exists():
        print("[SNAPSHOT] No snapshots found in .ai/snapshots/.")
        return []

    snapshots = []
    for sdir in sorted(snapshots_dir.iterdir(), reverse=True):
        if sdir.is_dir():
            mf = sdir / "manifest.json"
            if mf.exists():
                try:
                    data = json.loads(mf.read_text(encoding="utf-8"))
                    snapshots.append(data)
                except Exception:
                    pass

    if not snapshots:
        print("[SNAPSHOT] No snapshots found in .ai/snapshots/.")
        return []

    print("\n" + "=" * 65)
    print(f"{'SNAPSHOT ID':<35} {'CREATED AT':<20} {'FILES':<6} {'LABEL'}")
    print("=" * 65)
    for s in snapshots:
        created = s.get("created_at", "")[:19].replace("T", " ")
        print(f"{s.get('snapshot_id', ''):<35} {created:<20} {s.get('file_count', 0):<6} {s.get('label', '')}")
    print("=" * 65 + "\n")
    return snapshots


def diff_snapshot(root: Path, snapshot_id: str = None) -> Tuple[List[str], List[str], List[str]]:
    """Compare the current workspace against a snapshot."""
    snapshots_dir = root / ".ai" / "snapshots"
    if not snapshot_id:
        # Pick latest snapshot
        available = list_snapshots(root)
        if not available:
            print("[SNAPSHOT] No snapshots available to diff against.")
            return [], [], []
        snapshot_id = available[0]["snapshot_id"]

    target_dir = snapshots_dir / snapshot_id
    manifest_path = target_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"[SNAPSHOT] Error: Snapshot '{snapshot_id}' not found.")
        return [], [], []

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    snap_files: Dict[str, str] = manifest.get("files", {})
    current_files = _collect_workspace_files(root)

    added = sorted(set(current_files.keys()) - set(snap_files.keys()))
    deleted = sorted(set(snap_files.keys()) - set(current_files.keys()))
    modified = sorted([
        f for f in (set(current_files.keys()) & set(snap_files.keys()))
        if current_files[f] != snap_files[f]
    ])

    print(f"\n[SNAPSHOT] Diff vs checkpoint [{snapshot_id}]:")
    if not (added or modified or deleted):
        print("  (Workspace is identical to snapshot — no changes)")
    else:
        for f in added:
            print(f"  + Added:    {f}")
        for f in modified:
            print(f"  * Modified: {f}")
        for f in deleted:
            print(f"  - Deleted:  {f}")
    print()
    return added, modified, deleted


def _tasks_applied_after(root: Path, created_at: str) -> List[str]:
    """Task IDs the audit log shows as applied after the snapshot was taken."""
    log = root / TRACE_LOG
    if not log.is_file():
        return []
    cutoff = datetime.fromisoformat(created_at)
    tasks: List[str] = []
    for number, line in enumerate(log.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
            applied_at = datetime.fromisoformat(event["time"])
        except (ValueError, KeyError):
            print(f"[ROLLBACK] Warning: {TRACE_LOG} line {number} is unreadable; it was skipped.")
            continue
        if event.get("event") == "apply" and applied_at > cutoff and event.get("task_id") not in tasks:
            tasks.append(event.get("task_id"))
    return tasks


def _reopen_undone_tasks(root: Path, task_ids: List[str]) -> Tuple[List[str], List[str]]:
    """Set each undone task's status back to PLANNED in the CURRENT plan.json.

    plan.json is never restored from the snapshot (see CONTROL_FILES) — this
    is the only way its content changes during a rollback, and it touches
    only the tasks task_ids names. Every other task, phase, and any edit to
    allowed_files approved since the snapshot is left exactly as it was.

    Args:
        root: Project root.
        task_ids: Task IDs the audit log shows as applied after the snapshot.

    Returns:
        (found, changed) — found are the task_ids that exist in the current
        plan; changed are the ones whose status actually moved to PLANNED
        (a subset of found: one already PLANNED is found but not changed).
        Both are empty if there is no plan.json or it cannot be read.
    """
    if not task_ids:
        return [], []
    plan_path = root / PLAN_FILE
    if not plan_path.is_file():
        return [], []
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print(f"[ROLLBACK] Warning: {PLAN_FILE} could not be read; task statuses were not reset.")
        return [], []
    if not isinstance(plan, dict):
        return [], []

    found: List[str] = []
    changed: List[str] = []
    for phase in plan.get("phases", []):
        if not isinstance(phase, dict):
            continue
        for task in phase.get("tasks", []):
            if isinstance(task, dict) and task.get("task_id") in task_ids:
                found.append(task["task_id"])
                if task.get("status") != "PLANNED":
                    task["status"] = "PLANNED"
                    changed.append(task["task_id"])
    if changed:
        plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return found, changed


def _log_rollback(root: Path, snapshot_id: str, tasks_undone: List[str],
                  tasks_reopened: List[str], files_deleted: List[str]) -> None:
    """Add the undo itself to the audit log, so the code change is never unrecorded.

    Goes through traceability.append() (not a raw write) so this entry joins
    the same tamper-evident hash chain as every proposal apply — otherwise a
    rollback would be an unchained gap in the log.
    """
    trace.append(root, {
        "event": "rollback",
        "time": datetime.now().isoformat(timespec="milliseconds"),
        "snapshot_id": snapshot_id,
        "tasks_undone": tasks_undone,
        "tasks_reopened": tasks_reopened,
        "files_deleted": sorted(files_deleted),
    })


def rollback_snapshot(root: Path, snapshot_id: str = None) -> bool:
    """Restore the workspace to the exact state of the specified snapshot."""
    snapshots_dir = root / ".ai" / "snapshots"
    if not snapshot_id:
        available = [s.name for s in sorted(snapshots_dir.iterdir(), reverse=True) if s.is_dir() and (s / "manifest.json").exists()]
        if not available:
            print("[SNAPSHOT] Error: No snapshots available to rollback to.")
            return False
        snapshot_id = available[0]

    target_dir = snapshots_dir / snapshot_id
    files_dir = target_dir / "files"
    manifest_path = target_dir / "manifest.json"
    if not manifest_path.exists() or not files_dir.exists():
        print(f"[SNAPSHOT] Error: Snapshot '{snapshot_id}' is corrupt or missing files.")
        return False

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    snap_files: Dict[str, str] = manifest.get("files", {})
    current_files = _collect_workspace_files(root)
    extra = _load_snapshot_exclude(root)

    # 1. Delete newly created files that did not exist in snapshot
    deleted: List[str] = []
    for rel_path in current_files:
        if rel_path not in snap_files:
            file_to_del = root / rel_path
            try:
                if file_to_del.exists():
                    file_to_del.unlink()
                    deleted.append(rel_path)
                    print(f"[ROLLBACK] Deleted created file: {rel_path}")
            except Exception as e:
                print(f"[ROLLBACK] Warning: Could not delete {rel_path}: {e}")

    # 2. Restore modified and deleted files from snapshot
    for rel_path in snap_files:
        if _is_ignored(rel_path, extra):
            continue  # a snapshot saved before a control file was excluded
        src_path = files_dir / rel_path
        dst_path = root / rel_path
        if src_path.exists():
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dst_path)

    # 3. Clean up empty parent directories
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        if dirpath != str(root) and not filenames and not dirnames:
            rel_d = Path(dirpath).relative_to(root).as_posix()
            if not _is_ignored(rel_d, extra):
                try:
                    os.rmdir(dirpath)
                except Exception:
                    pass

    print(f"\n[ROLLBACK] Workspace successfully restored to snapshot [{snapshot_id}] ({len(snap_files)} files restored).\n")

    tasks_undone = _tasks_applied_after(root, manifest.get("created_at", ""))
    found, reopened = _reopen_undone_tasks(root, tasks_undone)
    _log_rollback(root, snapshot_id, tasks_undone, reopened, deleted)
    if tasks_undone:
        print(f"[ROLLBACK] Tasks applied after this snapshot are now undone: {', '.join(tasks_undone)}.")
        if reopened:
            print(f"[ROLLBACK] Reset to PLANNED in .ai/plan.json: {', '.join(reopened)}.")
        missing = [t for t in tasks_undone if t not in found]
        if missing:
            print(f"[ROLLBACK] Not found in .ai/plan.json, so their status could not be reset: "
                  f"{', '.join(missing)}. Check them manually.")
        print()
    return True


def main():
    parser = argparse.ArgumentParser(description="Git-Free Local Snapshot & Rollback Engine")
    subparsers = parser.add_subparsers(dest="command", help="Snapshot command to run")

    # Save
    p_save = subparsers.add_parser("save", help="Create a new snapshot")
    p_save.add_argument("label", nargs="?", default="checkpoint", help="Label/description for snapshot")

    # List
    subparsers.add_parser("list", help="List all snapshots")

    # Diff
    p_diff = subparsers.add_parser("diff", help="Diff workspace against a snapshot")
    p_diff.add_argument("snapshot_id", nargs="?", default=None, help="Snapshot ID (defaults to latest)")

    # Rollback
    p_roll = subparsers.add_parser("rollback", help="Rollback workspace to a snapshot")
    p_roll.add_argument("snapshot_id", nargs="?", default=None, help="Snapshot ID (defaults to latest)")

    args = parser.parse_args()
    root = Path.cwd()

    if args.command == "save":
        save_snapshot(root, args.label)
    elif args.command == "list":
        list_snapshots(root)
    elif args.command == "diff":
        diff_snapshot(root, args.snapshot_id)
    elif args.command == "rollback":
        rollback_snapshot(root, args.snapshot_id)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
