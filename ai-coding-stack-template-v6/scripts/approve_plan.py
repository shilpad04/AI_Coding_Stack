#!/usr/bin/env python3
"""
scripts/approve_plan.py — Human sign-off on a task's file scope.

The AI writes .ai/plan.json, so a human has to approve it. Until this script
has recorded a task's allowed_files, validate_proposal.py returns ASK
(RULE-PLAN-001) and writes nothing for that task. The same happens if the
list later grows past what was approved. Narrowing it needs no step — that
only restricts what the AI may touch.

This is a command a human runs directly, never the AI: command-policy.yaml
does not allow it, and .ai/plan-approval.json itself is a protected
governance file a proposal cannot write to.

Usage:
    python scripts/approve_plan.py TASK-001     one task (also for a widened scope)
    python scripts/approve_plan.py --all        every task with no approval yet
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import traceability as trace  # noqa: E402

PLAN_APPROVAL_PATH = Path(".ai") / "plan-approval.json"


def _load_plan(root: Path) -> dict:
    path = root / ".ai" / "plan.json"
    if not path.is_file():
        raise ValueError(f".ai/plan.json does not exist under {root}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f".ai/plan.json could not be read: {exc}") from exc
    return data if isinstance(data, dict) else {}


def _find_allowed_files(plan: dict, task_id: str) -> list[str]:
    for phase in plan.get("phases", []):
        for task in phase.get("tasks", []) if isinstance(phase, dict) else []:
            if isinstance(task, dict) and task.get("task_id") == task_id:
                allowed = task.get("allowed_files", [])
                return allowed if isinstance(allowed, list) else []
    raise ValueError(f"task '{task_id}' was not found in .ai/plan.json")


def _load_approval(root: Path) -> dict:
    path = root / PLAN_APPROVAL_PATH
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def approve(root: Path, task_id: str) -> list[str]:
    """Record the task's CURRENT allowed_files as the approved baseline.

    Args:
        root: Project root.
        task_id: The task in .ai/plan.json to approve.

    Returns:
        The allowed_files list that was recorded.

    Raises:
        ValueError: plan.json is missing, unreadable, or has no such task.
        OSError: The approval file or audit log could not be written.
    """
    plan = _load_plan(root)
    allowed_files = sorted(_find_allowed_files(plan, task_id))

    approval = _load_approval(root)
    approval[task_id] = {
        "allowed_files": allowed_files,
        "approved_at": datetime.now().isoformat(timespec="milliseconds"),
    }
    path = root / PLAN_APPROVAL_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(approval, indent=2), encoding="utf-8")

    trace.append(root, {
        "event": "plan_approval",
        "time": datetime.now().isoformat(timespec="milliseconds"),
        "task_id": task_id,
        "allowed_files": allowed_files,
    })
    return allowed_files


def approve_all(root: Path) -> tuple[list[str], list[str]]:
    """Approve every task in plan.json that has no approved baseline yet.

    A task that already has a baseline is skipped, never re-approved, so this
    cannot be used to accept a widened scope without looking at it — that
    still needs `approve <TASK_ID>` for that task.

    Args:
        root: Project root.

    Returns:
        (approved, skipped) task IDs, in plan order.

    Raises:
        ValueError: plan.json is missing or unreadable.
        OSError: The approval file or audit log could not be written.
    """
    plan = _load_plan(root)
    approved: list[str] = []
    skipped: list[str] = []
    for phase in plan.get("phases", []):
        for task in phase.get("tasks", []) if isinstance(phase, dict) else []:
            task_id = task.get("task_id") if isinstance(task, dict) else None
            if not isinstance(task_id, str) or not task_id:
                continue
            if task_id in _load_approval(root):
                skipped.append(task_id)
            else:
                approve(root, task_id)
                approved.append(task_id)
    return approved, skipped


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Approve a task's current allowed_files as the baseline "
                    "validate_proposal.py measures against.")
    parser.add_argument("task_id", nargs="?", default=None,
                        help="The task_id in .ai/plan.json to approve, e.g. TASK-001")
    parser.add_argument("--all", action="store_true",
                        help="Approve every task that has no approval yet. Never re-approves "
                             "a task that already has one.")
    parser.add_argument("--root", type=Path, default=None,
                        help="Project root (default: current directory)")
    args = parser.parse_args()
    if bool(args.task_id) == args.all:
        parser.error("give exactly one of: a task_id, or --all")
    root = args.root or Path.cwd()

    try:
        if args.all:
            approved, skipped = approve_all(root)
        else:
            allowed_files = approve(root, args.task_id)
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.all:
        print(f"[APPROVE] {len(approved)} task(s) approved: {', '.join(approved) or '(none)'}")
        if skipped:
            print(f"[APPROVE] Already approved, left alone: {', '.join(skipped)}. "
                  "If one of them needs a wider scope, run approve_plan.py <TASK_ID> to review it.")
        return

    print(f"[APPROVE] {args.task_id} approved with {len(allowed_files)} file(s):")
    for f in allowed_files:
        print(f"  - {f}")


if __name__ == "__main__":
    main()
