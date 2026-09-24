"""
scripts/validate_proposal.py
============================
AI Governance Proposal Validator — standalone CLI orchestrator.

The AI coding assistant runs this script BEFORE applying any change.
It validates the JSON proposal envelope against all TSG governance rules
and exits with a non-zero code if the proposal must be blocked.

Usage
-----
  python scripts/validate_proposal.py <proposal.json> [OPTIONS]

Options
-------
  --config PATH            Path to config.yaml   (default: config/config.yaml)
  --packages PATH          Path to approved-packages.yaml
                           (default: config/approved-packages.yaml)
  --commands PATH          Path to command-policy.yaml
                           (default: config/command-policy.yaml)
  --plan PATH              Approved plan (default: <root>/.ai/plan.json). When it
                           exists, the task's allowed_files come from it.
  --allowed-files F [F..] Explicit list of allowed file paths. It can only NARROW
                           the plan's list, never widen it. Used as-is only when
                           there is no plan file. Overrides a --task JSON.
  --task PATH              Path to a task JSON file (has allowed_files, etc.)
  --skip-reconcile         Skip Gate 2 reconcile check (use pre-write only).
  --quiet                  Suppress colour output; print JSON summary to stdout.

Exit codes
----------
  0  PASS — all validators green, safe to apply.
  1  FAIL — at least one hard policy violation; DO NOT apply.
  2  ASK  — human approval needed for at least one item; pause and ask.
  3  Error — could not parse proposal or load config.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import textwrap
from pathlib import Path
from typing import Any

import yaml

# Allow running from repo root: python scripts/validate_proposal.py ...
sys.path.insert(0, str(Path(__file__).parent))

import traceability as trace
import validators as v

# ---------------------------------------------------------------------------
# ANSI colours (disabled on --quiet)
# ---------------------------------------------------------------------------

_COLOURS = {
    "green":  "\033[92m",
    "yellow": "\033[93m",
    "red":    "\033[91m",
    "cyan":   "\033[96m",
    "bold":   "\033[1m",
    "reset":  "\033[0m",
}


def _c(text: str, colour: str, quiet: bool = False) -> str:
    if quiet or not sys.stdout.isatty():
        return text
    return f"{_COLOURS.get(colour, '')}{text}{_COLOURS['reset']}"


def _status(text: str, quiet: bool) -> None:
    """One short line saying what the Policy Agent is doing right now."""
    if not quiet:
        print(_c(f"[Policy Agent] {text}", "cyan", quiet), flush=True)


# ---------------------------------------------------------------------------
# Proposal wrapper  (turns the raw JSON dict into an attribute-accessible obj)
# ---------------------------------------------------------------------------

class Proposal:
    """Thin wrapper over the raw JSON proposal dict."""

    def __init__(self, data: dict) -> None:
        self._data = data

    @property
    def task_id(self) -> str:
        return self._data.get("task_id", "")

    @property
    def status(self) -> str:
        return self._data.get("status", "")

    @property
    def needs_clarification(self) -> bool:
        return self.status == "CLARIFICATION_REQUIRED"

    @property
    def clarifications(self) -> list:
        return self._data.get("clarifications", [])

    @property
    def files(self) -> list:
        return self._data.get("files", [])

    @property
    def packages(self) -> list:
        return self._data.get("packages", [])

    @property
    def commands(self) -> list:
        return self._data.get("commands", [])

    @property
    def model(self) -> str | None:
        """The AI model name the proposal declares, if any (optional field)."""
        return self._data.get("model")


class Changes:
    """Minimal Changes object for reconcile validator."""

    def __init__(self, all_paths: list[str]) -> None:
        self.all_paths = all_paths


# ---------------------------------------------------------------------------
# Config loaders
# ---------------------------------------------------------------------------

def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _load_config(config_path: Path) -> dict:
    return _load_yaml(config_path)


def _load_approved_packages(path: Path) -> list:
    data = _load_yaml(path)
    return data.get("packages", [])


def _load_approved_commands(path: Path) -> dict:
    return _load_yaml(path)


def _load_plan(path: Path) -> dict | None:
    """Load the approved plan.

    Returns:
        None if there is no plan file (stand-alone use). An empty dict if the
        file exists but cannot be read, so every task is then "not in the plan"
        and nothing is allowed.
    """
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _find_task(plan: dict, task_id: object) -> dict | None:
    """Return the task with this task_id from the plan, or None."""
    for phase in plan.get("phases", []):
        tasks = phase.get("tasks", []) if isinstance(phase, dict) else []
        for task in tasks:
            if isinstance(task, dict) and task.get("task_id") == task_id:
                return task
    return None


# ---------------------------------------------------------------------------
# Human plan approval (.ai/plan-approval.json)
#
# The AI writes .ai/plan.json, so the plan alone proves nothing. A task is
# only applied once a human has run `scripts/approve_plan.py <TASK_ID>` (or
# `--all`) for it, which records its allowed_files as the approved baseline.
# After that, a task's allowed_files may narrow freely — that only restricts
# scope further — but growing it (the AI editing its own plan.json) needs the
# human to approve again. The validator never writes a baseline for a task
# that has none.
# ---------------------------------------------------------------------------

PLAN_APPROVAL_PATH = Path(".ai") / "plan-approval.json"


def _load_plan_approval(root: Path) -> dict:
    path = root / PLAN_APPROVAL_PATH
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_plan_approval(root: Path, approval: dict) -> None:
    path = root / PLAN_APPROVAL_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(approval, indent=2), encoding="utf-8")


def _check_plan_widen(root: Path, task_id: str, plan_allowed: list) -> v.Result:
    """ASK unless a human has approved this task's allowed_files (RULE-PLAN-001).

    ASK when the task has no approved baseline yet, or when its allowed_files
    grew past that baseline. Tightens the baseline whenever the plan has
    narrowed since. Neither ASK changes the baseline, so it keeps asking until
    scripts/approve_plan.py records the human's approval.
    """
    r = v.Result("plan_scope")
    if not task_id:
        return r
    approval = _load_plan_approval(root)
    entry = approval.get(task_id)
    baseline = entry.get("allowed_files") if isinstance(entry, dict) else None

    current = sorted(plan_allowed)
    if baseline is None:
        r.add(v.ASK, "RULE-PLAN-001",
              f"task '{task_id}' has not been approved by a human yet. After reviewing "
              f".ai/plan.json, run `python scripts/approve_plan.py {task_id}` "
              "(or `--all` for every unapproved task).", allowed=current)
        return r

    extra = sorted(set(plan_allowed) - set(baseline))
    if extra:
        r.add(v.ASK, "RULE-PLAN-001",
              f"task '{task_id}' allowed_files grew beyond its approved baseline: "
              f"{', '.join(extra)}. Run `python scripts/approve_plan.py {task_id}` "
              "after review to accept the wider scope.", added=extra)
    elif current != sorted(baseline):
        approval[task_id] = {"allowed_files": current}
        _save_plan_approval(root, approval)
    return r


# ---------------------------------------------------------------------------
# Repair-attempt counter (.ai/task-state.json)
#
# A model can be told "fix it" and keep failing the same task forever. After
# governance.max_repair_attempts (config.yaml) consecutive Gate-1 FAILs on one
# task, the run stops returning FAIL and returns ASK instead, so a human has
# to look. DEFAULT_MAX_REPAIR_ATTEMPTS is used only if that setting is missing
# from config.yaml or is not a positive integer.
# ---------------------------------------------------------------------------

DEFAULT_MAX_REPAIR_ATTEMPTS = 2
TASK_STATE_PATH = Path(".ai") / "task-state.json"


def _load_task_state(root: Path) -> dict:
    path = root / TASK_STATE_PATH
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_task_state(root: Path, state: dict) -> None:
    path = root / TASK_STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _record_repair_attempt(root: Path, task_id: str, failed: bool) -> int:
    """Update this task's consecutive-FAIL count and return it.

    A FAIL increments it; a PASS or an ordinary ASK resets it to 0, since the
    model has stopped producing a rule-violating proposal.
    """
    state = _load_task_state(root)
    entry = state.get(task_id) if isinstance(state.get(task_id), dict) else {}
    count = int(entry.get("repair_attempts", 0)) + 1 if failed else 0
    state[task_id] = {"repair_attempts": count}
    _save_task_state(root, state)
    return count


def _exit_for(root: Path, task_id: str, overall: str, quiet: bool,
              max_attempts: int = DEFAULT_MAX_REPAIR_ATTEMPTS) -> int:
    """Apply the repair-attempt counter and return the process exit code.

    Args:
        root: Project root (where .ai/task-state.json lives).
        task_id: The proposal's task_id.
        overall: The true combined validator status (PASS, ASK or FAIL) —
            never altered by this function, only the exit code is.
        quiet: Suppress colour on the escalation notice.
        max_attempts: From config.yaml's governance.max_repair_attempts.

    Returns:
        0 for PASS, 1 for FAIL, 2 for ASK — except a FAIL that is this task's
        max_attempts-th in a row, which returns 2 instead of 1.
    """
    count = _record_repair_attempt(root, task_id, overall == v.FAIL)
    if overall == v.FAIL and count >= max_attempts:
        print(_c(f"  ! {count} consecutive failures on this task — "
                  "escalating to ASK for human review.", "yellow", quiet))
        print()
        return 2
    return {v.PASS: 0, v.ASK: 2, v.FAIL: 1}.get(overall, 1)


# ---------------------------------------------------------------------------
# Snapshot + apply utilities  (Gate 2 support)
# ---------------------------------------------------------------------------

def take_snapshot(paths: list[str], root: Path) -> dict:
    """Hash the current on-disk content of a list of file paths.

    Args:
        paths: Relative file paths to hash (relative to root).
        root: Project root directory used to resolve each path.

    Returns:
        Dict mapping each relative path to {"hash": sha256_short_str}.
        Paths that do not exist or cannot be read are silently skipped.
    """
    snapshot: dict[str, dict] = {}
    for rel in paths:
        abs_path = root / rel
        try:
            raw = abs_path.read_bytes()
            snapshot[rel] = {"hash": hashlib.sha256(raw).hexdigest()[:16]}
        except (OSError, PermissionError):
            pass  # missing or unreadable — skip gracefully
    return snapshot


def apply_proposal(proposal: "Proposal", root: Path) -> list[str]:
    """Write, overwrite, or delete files on disk as described in proposal.files.

    Gate 1 must have passed (exit 0) before calling this function.
    All file content is written as UTF-8, matching how proposals are read.

    Args:
        proposal: Proposal object whose .files list drives the writes.
        root: Project root; all proposal paths are resolved relative to it.

    Returns:
        List of relative paths that were touched (created, modified, or deleted).

    Raises:
        OSError: If a file cannot be written or deleted.
    """
    touched: list[str] = []
    for f in proposal.files:
        abs_path = root / f["path"]
        action   = f["action"]
        if action in ("create", "modify"):
            # Create missing parent directories automatically.
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_bytes(f.get("content", "").encode("utf-8"))
            touched.append(f["path"])
        elif action == "delete":
            if abs_path.exists():
                abs_path.unlink()
                touched.append(f["path"])
            # Missing file on delete is a no-op, not an error.
    return touched


def _log_apply(root: Path, proposal: "Proposal", proposal_path: Path,
               old_texts: dict, reconcile: str) -> str | None:
    """Add an applied proposal to the audit log (.ai/traceability.ndjson).

    Returns:
        None on success, or an error message. The files are already on disk at
        this point, so a log that cannot be written must fail the run.
    """
    try:
        trace.record_apply(root, proposal.task_id, str(proposal_path),
                           proposal.files, old_texts, reconcile, model=proposal.model)
    except OSError as exc:
        return f"files were applied but the traceability log could not be written: {exc}"
    return None


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

_STATUS_COLOUR = {v.PASS: "green", v.ASK: "yellow", v.FAIL: "red"}
_STATUS_ICON   = {v.PASS: "+", v.ASK: "?", v.FAIL: "!"}


def _print_result(result: v.Result, quiet: bool) -> None:
    icon   = _STATUS_ICON[result.status]
    colour = _STATUS_COLOUR[result.status]
    label  = _c(f"[{result.status}]", colour, quiet)
    name   = _c(result.name.upper(), "bold", quiet)
    print(f"  {icon} {name} {label}")
    for finding in result.findings:
        fcolour = _STATUS_COLOUR[finding["status"]]
        ficon   = _STATUS_ICON[finding["status"]]
        rule    = _c(finding["rule"], "cyan", quiet)
        msg     = finding["message"]
        print(f"      {ficon} {rule}: {msg}")


def _print_summary(overall: str, results: list[v.Result], quiet: bool) -> None:
    colour = _STATUS_COLOUR[overall]
    icon   = _STATUS_ICON[overall]
    banner = _c(f" {icon} OVERALL: {overall} ", colour, quiet)
    print()
    print("=" * 60)
    print(banner)
    print("=" * 60)

    if quiet:
        summary = {
            "overall": overall,
            "validators": [
                {"name": r.name, "status": r.status, "findings": r.findings}
                for r in results
            ],
        }
        print(json.dumps(summary, indent=2))


# ---------------------------------------------------------------------------
# Main validation runner
# ---------------------------------------------------------------------------

def run_validation(
    proposal_path: Path,
    config_path: Path,
    packages_path: Path,
    commands_path: Path,
    task: dict,
    allowed_files: list[str],
    skip_reconcile: bool,
    quiet: bool,
    apply_files: bool = False,
    project_root: Path | None = None,
    plan_path: Path | None = None,
) -> int:
    """Run all validators and return an exit code (0=PASS, 1=FAIL, 2=ASK, 3=Error).

    Args:
        proposal_path: Path to the JSON proposal file.
        config_path: Path to config.yaml.
        packages_path: Path to approved-packages.yaml.
        commands_path: Path to command-policy.yaml.
        task: Task dict with allowed_files, description, acceptance_criteria.
        allowed_files: Explicit list of allowed files (overrides task if set).
        skip_reconcile: If True, skip Gate 2 reconcile validator.
        quiet: If True, suppress colour output and emit JSON to stdout.
        apply_files: If True, apply the proposal to disk and run Gate 2.
        project_root: Root directory for resolving file paths (defaults to cwd).
        plan_path: Approved plan.json (defaults to <project_root>/.ai/plan.json).
            When the file exists, allowed_files come from the plan and the
            explicit allowed_files list can only narrow them.

    Returns:
        Exit code integer.
    """
    # ---- Load configs ----
    try:
        cfg            = _load_config(config_path)
        approved_pkgs  = _load_approved_packages(packages_path)
        command_cfg    = _load_approved_commands(commands_path)
    except Exception as exc:
        print(f"ERROR: could not load config: {exc}", file=sys.stderr)
        return 3

    governance = cfg.get("governance", {})
    block_unapproved = governance.get("block_unapproved_packages", True)
    max_repair_attempts = governance.get("max_repair_attempts", DEFAULT_MAX_REPAIR_ATTEMPTS)
    if not isinstance(max_repair_attempts, int) or max_repair_attempts < 1:
        max_repair_attempts = DEFAULT_MAX_REPAIR_ATTEMPTS
    # On unless config says a real boolean false: a typo must never turn a check off.
    require_tests = governance.get("require_tests_with_code", True) is not False

    # ---- Load proposal ----
    try:
        raw = json.loads(proposal_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("the proposal must be a JSON object")
        proposal = Proposal(raw)
    except Exception as exc:
        print(f"ERROR: could not parse proposal JSON: {exc}", file=sys.stderr)
        return 3

    # ---- Resolve task / allowed_files ----
    # An approved plan decides what the task may touch; an explicit list can
    # only narrow it. With no plan file, the explicit list is used as given.
    root = project_root or Path.cwd()
    plan_result = None
    widen_result = None
    criteria_result = None
    plan = _load_plan(plan_path or (root / ".ai" / "plan.json"))
    if plan is not None:
        plan_task = _find_task(plan, proposal.task_id)
        plan_allowed: list = []
        if plan_task is None:
            plan_result = v.Result("plan")
            plan_result.add(v.FAIL, "RULE-SCOPE-001",
                            f"task '{proposal.task_id}' is not in the approved plan, "
                            "or the plan could not be read")
        else:
            if isinstance(plan_task.get("allowed_files"), list):
                plan_allowed = plan_task["allowed_files"]
            widen_result = _check_plan_widen(root, proposal.task_id, plan_allowed)
            criteria_result = v.validate_acceptance_criteria(plan_task)
        narrowed = [f for f in allowed_files if f in plan_allowed]
        task = {**task, "allowed_files": narrowed if allowed_files else plan_allowed}
    elif allowed_files:
        task = {**task, "allowed_files": allowed_files}

    # ---- Print header ----
    if not quiet:
        print()
        print(_c("TSG AI Governance Validator", "bold", quiet))
        print(_c("=" * 60, "cyan", quiet))
        print(f"  Proposal : {proposal_path}")
        print(f"  Task ID  : {proposal.task_id or '(none)'}")
        print(f"  Status   : {proposal.status or '(none)'}")
        print()
        _status(f"Checking the {proposal.task_id or 'unnamed'} proposal against the rules.", quiet)
        print(_c("Gate 1 — Pre-write checks", "bold", quiet))
        print()

    results: list[v.Result] = []

    # 0. structure: the checks below read every entry directly, so a malformed
    #    entry has to stop the run here with a message the model can act on.
    r_structure = v.validate_structure(proposal)
    results.append(r_structure)
    _print_result(r_structure, quiet)
    if r_structure.blocked:
        overall = v.combine(results)
        _print_summary(overall, results, quiet)
        _status(f"Done: {proposal.task_id or 'unnamed'} is {overall}.", quiet)
        return _exit_for(root, proposal.task_id, overall, quiet, max_repair_attempts)

    if plan_result is not None:
        results.append(plan_result)
        _print_result(plan_result, quiet)
    if widen_result is not None and not widen_result.ok:
        results.append(widen_result)
        _print_result(widen_result, quiet)
    if criteria_result is not None:
        results.append(criteria_result)
        _print_result(criteria_result, quiet)

    # 1. rules (clarification check)
    r_rules = v.validate_rules(proposal)
    results.append(r_rules)
    _print_result(r_rules, quiet)

    # 2. scope
    r_scope = v.validate_scope(proposal, task)
    results.append(r_scope)
    _print_result(r_scope, quiet)

    # 3. secrets
    r_secrets = v.validate_secrets(proposal)
    results.append(r_secrets)
    _print_result(r_secrets, quiet)

    # 4. packages
    r_packages = v.validate_packages(
        proposal, task, approved_pkgs,
        block_unapproved=block_unapproved,
    )
    results.append(r_packages)
    _print_result(r_packages, quiet)

    # 4b. dependency manifest files (package.json, requirements.txt, pom.xml, ...)
    r_dep_files = v.validate_dependency_files(
        proposal, approved_pkgs, block_unapproved=block_unapproved,
    )
    results.append(r_dep_files)
    _print_result(r_dep_files, quiet)

    # 5. commands
    r_commands = v.validate_commands(proposal, command_cfg)
    results.append(r_commands)
    _print_result(r_commands, quiet)

    # 6. changes (placeholder + syntax)
    r_changes = v.validate_changes(proposal)
    results.append(r_changes)
    _print_result(r_changes, quiet)

    # 6b. database rules (migration not bundled with features, no ORM auto-create)
    r_database = v.validate_database(proposal)
    results.append(r_database)
    _print_result(r_database, quiet)

    # 7. tests must come with code (governance.require_tests_with_code, default on)
    if require_tests:
        r_tests = v.validate_tests_present(proposal)
        results.append(r_tests)
        _print_result(r_tests, quiet)

    # ---- Gate 2 — post-write reconcile ----
    gate1_overall = v.combine(results)

    trace_error = None
    if apply_files:
        if not quiet:
            print()
            print(_c("Gate 2 — Post-write reconcile", "bold", quiet))
            print()

        if gate1_overall != v.PASS:
            # Write nothing unless Gate 1 fully passed. ASK means a human has
            # to approve first, so it must not touch the disk either.
            if not quiet:
                print(_c(f"  ! Apply skipped — Gate 1 returned {gate1_overall}.",
                         _STATUS_COLOUR[gate1_overall], quiet))
                print()
        elif skip_reconcile:
            # Apply files but skip the reconcile check.
            _status(f"Writing the {proposal.task_id} files to disk.", quiet)
            old_texts = trace.read_texts(root, [f["path"] for f in proposal.files])
            apply_proposal(proposal, root)
            trace_error = _log_apply(root, proposal, proposal_path, old_texts, "SKIPPED")
            if not quiet:
                print(_c("  (reconcile skipped via --skip-reconcile)", "yellow", quiet))
                print()
        else:
            # Full Gate 2: snapshot → apply → snapshot → reconcile.
            _status(f"Writing the {proposal.task_id} files to disk and checking what landed.", quiet)
            proposed_paths = [f["path"] for f in proposal.files]
            old_texts = trace.read_texts(root, proposed_paths)
            pre  = take_snapshot(proposed_paths, root)
            touched = apply_proposal(proposal, root)
            post = take_snapshot(proposed_paths, root)

            changes_obj = Changes(touched)
            r_reconcile = v.validate_reconcile(changes_obj, proposal, post)
            results.append(r_reconcile)
            _print_result(r_reconcile, quiet)
            trace_error = _log_apply(root, proposal, proposal_path, old_texts, r_reconcile.status)
    else:
        if not quiet:
            print()
            print(_c("Gate 2 — Post-write reconcile", "bold", quiet))
            print(_c("  (skipped — run with --apply to write files and enable Gate 2)", "yellow", quiet))
            print()

    overall = v.combine(results)
    _print_summary(overall, results, quiet)
    _status(f"Done: {proposal.task_id or 'unnamed'} is {overall}.", quiet)

    if trace_error:
        print(f"ERROR: {trace_error}", file=sys.stderr)
        return 1

    return _exit_for(root, proposal.task_id, overall, quiet, max_repair_attempts)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="validate_proposal",
        description=textwrap.dedent("""\
            TSG AI Governance Validator.
            Runs the governance validators on a JSON proposal before it
            is applied to the project. Exit 0=PASS, 1=FAIL, 2=ASK, 3=Error.
        """),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("proposal", type=Path,
                   help="Path to the JSON proposal file to validate.")
    p.add_argument("--config", type=Path, default=Path("config/config.yaml"),
                   help="Path to config.yaml (default: config/config.yaml)")
    p.add_argument("--packages", type=Path,
                   default=Path("config/approved-packages.yaml"),
                   help="Path to approved-packages.yaml")
    p.add_argument("--commands", type=Path,
                   default=Path("config/command-policy.yaml"),
                   help="Path to command-policy.yaml")
    p.add_argument("--plan", type=Path, default=None,
                   help="Approved plan.json (default: <root>/.ai/plan.json). "
                        "Its allowed_files for the task decide the scope.")
    p.add_argument("--allowed-files", nargs="+", metavar="FILE",
                   help="Optional list that can only NARROW the plan's allowed files. "
                        "Used as-is only when there is no plan file.")
    p.add_argument("--task", type=Path,
                   help="Path to a task JSON file (provides allowed_files, description, etc.)")
    p.add_argument("--skip-reconcile", action="store_true",
                   help="Skip Gate 2 reconcile check.")
    p.add_argument("--apply", action="store_true",
                   help="Apply proposal files to disk and run Gate 2 reconcile. "
                        "Files are only written when Gate 1 passes.")
    p.add_argument("--root", type=Path, default=None,
                   help="Project root for resolving file paths (default: cwd).")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress colour output; emit JSON summary to stdout.")
    return p


def main() -> None:
    """CLI entry point for the proposal validator."""
    parser = _build_parser()
    args = parser.parse_args()

    # Load task JSON if provided
    task: dict[str, Any] = {}
    if args.task:
        try:
            task = json.loads(args.task.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"ERROR: could not load task file: {exc}", file=sys.stderr)
            sys.exit(3)

    code = run_validation(
        proposal_path  = args.proposal,
        config_path    = args.config,
        packages_path  = args.packages,
        commands_path  = args.commands,
        task           = task,
        allowed_files  = args.allowed_files or [],
        skip_reconcile = args.skip_reconcile,
        quiet          = args.quiet,
        apply_files    = args.apply,
        project_root   = args.root,
        plan_path      = args.plan,
    )
    sys.exit(code)


if __name__ == "__main__":
    main()
