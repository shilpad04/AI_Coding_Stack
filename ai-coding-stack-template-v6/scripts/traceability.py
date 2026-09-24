#!/usr/bin/env python3
"""
scripts/traceability.py — who changed what.

Every proposal the validator applies adds ONE line to `.ai/traceability.ndjson`:
the task, the time, and for each file the exact lines and the functions changed.

  "added"    line numbers in the NEW file      [[first, last], ...]
  "removed"  line numbers in the OLD file      [[first, last], ...]
  "functions"  Python: exact (parsed), change is added / modified / removed.
               TS/JS/Java/Go: a best guess (nearest declaration above the
               changed line), change is "touched". Other files: none.

Ask the log:
    python scripts/traceability.py --task TASK-001
    python scripts/traceability.py --file backend/app/main.py
    python scripts/traceability.py --function create_order
    python scripts/traceability.py            (everything)
"""
from __future__ import annotations

import argparse
import ast
import difflib
import getpass
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

LOG_PATH = Path(".ai") / "traceability.ndjson"
OUTSIDE = "(outside functions)"

# ---------------------------------------------------------------------------
# Function declarations for the languages we cannot parse. Each pattern must
# capture the function name in a group called "name".
# ---------------------------------------------------------------------------

_JS_PATTERNS = [
    re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*(?P<name>\w+)"),
    re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+(?P<name>\w+)\s*(?::[^=]+)?=\s*"
               r"(?:async\s*)?(?:function\b|\([^)]*\)\s*(?::[^=]+)?=>|\w+\s*=>)"),
    re.compile(r"^\s+(?:(?:public|private|protected|static|async|readonly|override|get|set)\s+)*"
               r"(?P<name>\w+)\s*(?:<[^>]*>)?\([^)]*\)\s*(?::\s*[^{]+)?\{\s*$"),
]
_JAVA_PATTERNS = [
    re.compile(r"^\s*(?:(?:public|private|protected|static|final|abstract|synchronized|native|default)\s+)+"
               r"(?:<[^>]+>\s+)?[\w<>\[\],.?\s]+?\s+(?P<name>\w+)\s*\([^;]*$"),
]
_GO_PATTERNS = [re.compile(r"^func\s+(?:\([^)]*\)\s*)?(?P<name>\w+)")]

_DECLARATIONS = {
    ".ts": _JS_PATTERNS, ".tsx": _JS_PATTERNS, ".js": _JS_PATTERNS, ".jsx": _JS_PATTERNS,
    ".mjs": _JS_PATTERNS, ".cjs": _JS_PATTERNS,
    ".java": _JAVA_PATTERNS,
    ".go": _GO_PATTERNS,
}
# Words that look like a method name to the pattern but are statements.
_NOT_FUNCTION_NAMES = {"if", "for", "while", "switch", "catch", "function", "return",
                       "with", "else", "do", "try", "finally"}


# ---------------------------------------------------------------------------
# Which lines changed
# ---------------------------------------------------------------------------

def changed_ranges(old: str, new: str) -> tuple[list[list[int]], list[list[int]]]:
    """Return (removed, added) as 1-based inclusive [first, last] line ranges.

    Args:
        old: File text before the change ("" for a new file).
        new: File text after the change ("" for a deleted file).

    Returns:
        removed: ranges in the OLD file. added: ranges in the NEW file.
    """
    removed: list[list[int]] = []
    added: list[list[int]] = []
    matcher = difflib.SequenceMatcher(None, old.splitlines(), new.splitlines(), autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            removed.append([i1 + 1, i2])
        if tag in ("replace", "insert"):
            added.append([j1 + 1, j2])
    return removed, added


def _count(ranges: list[list[int]]) -> int:
    return sum(last - first + 1 for first, last in ranges)


def _overlaps(start: int, end: int, ranges: list[list[int]]) -> bool:
    return any(first <= end and last >= start for first, last in ranges)


# ---------------------------------------------------------------------------
# Which functions changed
# ---------------------------------------------------------------------------

def _python_functions(text: str) -> dict[str, tuple[int, int]] | None:
    """Map qualified function name -> (first line, last line); None if unparseable."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    found: dict[str, tuple[int, int]] = {}

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = prefix + child.name
                start = min([child.lineno] + [d.lineno for d in child.decorator_list])
                found[name] = (start, child.end_lineno or child.lineno)
                walk(child, name + ".")
            elif isinstance(child, ast.ClassDef):
                walk(child, prefix + child.name + ".")
            else:
                walk(child, prefix)

    walk(tree, "")
    return found


def _outside(ranges: list[list[int]], spans: dict[str, tuple[int, int]], text: str) -> bool:
    """True if any non-blank changed line lies outside every function."""
    lines = text.splitlines()
    inside = {n for start, end in spans.values() for n in range(start, end + 1)}
    for first, last in ranges:
        for n in range(first, last + 1):
            if n not in inside and n <= len(lines) and lines[n - 1].strip():
                return True
    return False


def _python_changes(old: str, new: str, removed: list[list[int]],
                    added: list[list[int]]) -> list[dict] | None:
    old_fns, new_fns = _python_functions(old), _python_functions(new)
    if old_fns is None or new_fns is None:
        return None
    out = []
    for name, (start, end) in new_fns.items():
        if name not in old_fns:
            out.append({"name": name, "change": "added"})
        elif _overlaps(start, end, added) or _overlaps(*old_fns[name], removed):
            out.append({"name": name, "change": "modified"})
    out += [{"name": n, "change": "removed"} for n in old_fns if n not in new_fns]
    if _outside(added, new_fns, new) or _outside(removed, old_fns, old):
        out.append({"name": OUTSIDE, "change": "modified"})
    return out


def _nearest_declaration(lines: list[str], line_no: int, patterns: list[re.Pattern]) -> str | None:
    """Name of the closest function declaration on or above line_no (1-based)."""
    for i in range(min(line_no, len(lines)) - 1, -1, -1):
        for pattern in patterns:
            match = pattern.match(lines[i])
            if match and match.group("name") not in _NOT_FUNCTION_NAMES:
                return match.group("name")
    return None


def _guess_functions(patterns: list[re.Pattern], old: str, new: str,
                     removed: list[list[int]], added: list[list[int]]) -> list[dict]:
    names: dict[str, bool] = {}
    for text, ranges in ((old, removed), (new, added)):
        lines = text.splitlines()
        for first, last in ranges:
            for n in range(first, last + 1):
                names[_nearest_declaration(lines, n, patterns) or OUTSIDE] = True
    return [{"name": name, "change": "touched"} for name in names]


def file_entry(path: str, action: str, old: str, new: str) -> dict:
    """Describe one file's change: lines and functions.

    Args:
        path: File path as written in the proposal.
        action: create, modify or delete.
        old: Text before the change ("" if the file did not exist).
        new: Text after the change ("" if the file was deleted).

    Returns:
        Dict with path, action, lines_added, lines_removed, added, removed,
        functions, function_detection ("exact", "approximate" or "none").
    """
    removed, added = changed_ranges(old, new)
    functions: list[dict] = []
    detection = "none"
    ext = Path(path).suffix.lower()
    if ext == ".py":
        changes = _python_changes(old, new, removed, added)
        if changes is not None:
            functions, detection = changes, "exact"
    elif ext in _DECLARATIONS:
        functions = _guess_functions(_DECLARATIONS[ext], old, new, removed, added)
        detection = "approximate"
    return {
        "path": path, "action": action,
        "lines_added": _count(added), "lines_removed": _count(removed),
        "added": added, "removed": removed,
        "functions": functions, "function_detection": detection,
        "content_hash": None if action == "delete" else _content_hash(new),
    }


def _content_hash(text: str) -> str:
    """Full sha256 hex of a file's UTF-8 bytes.

    Matches scripts/snapshot.py's _file_hash() (also full sha256 hex of the
    file's bytes), so a logged content_hash can be compared directly against
    a workspace scan without a format mismatch.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Tamper-evident chain: every line's "hash" covers its own content plus the
# previous line's hash, so editing or deleting an old line breaks the link
# to whatever comes after it. GENESIS_HASH is the "previous hash" for the
# very first entry.
# ---------------------------------------------------------------------------

GENESIS_HASH = "0" * 64


def _chain_hash(prev_hash: str, event: dict) -> str:
    """This entry's hash: sha256(prev_hash + this entry's own JSON).

    Excludes "hash"/"prev_hash" themselves, so the same function computes a
    line's hash both when it is written and when it is re-verified later.
    """
    payload = {k: v for k, v in event.items() if k not in ("hash", "prev_hash")}
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256((prev_hash + canonical).encode("utf-8")).hexdigest()


def _last_chain_hash(path: Path) -> str:
    """The log's last line's own hash, or GENESIS_HASH if there is no log yet
    or the last line predates chaining (no "hash" field to continue from)."""
    if not path.is_file():
        return GENESIS_HASH
    last_line = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            last_line = line
    if last_line is None:
        return GENESIS_HASH
    try:
        data = json.loads(last_line)
    except ValueError:
        return GENESIS_HASH
    return data.get("hash", GENESIS_HASH)


def verify_chain(events: list[dict]) -> list[dict]:
    """Check the log's hash chain link by link.

    Args:
        events: The log, in order (e.g. from read_log()).

    Returns:
        [] if every chained line matches; otherwise one
        {"line": <1-based line number>, "reason": <str>} per line where the
        chain first breaks. A line with no "hash"/"prev_hash" fields at all
        (logged before chaining existed) is treated as a legacy line, not a
        break — chaining simply restarts after it, matching what append()
        does when writing the next entry.

        This proves a line hasn't been edited or removed IN ISOLATION. It
        cannot catch a rewrite that also recomputes every hash after the
        tampered line, and it cannot catch the *last* line being deleted,
        since nothing after it exists to notice — both require an attacker
        with full, careful write access to the log file itself.
    """
    breaks = []
    prev_hash = GENESIS_HASH
    for i, event in enumerate(events, start=1):
        if "hash" not in event and "prev_hash" not in event:
            prev_hash = GENESIS_HASH  # legacy line — chain restarts after it
            continue
        if event.get("prev_hash") != prev_hash:
            breaks.append({"line": i, "reason": "prev_hash does not match the previous line's hash"})
        elif event.get("hash") != _chain_hash(prev_hash, event):
            breaks.append({"line": i, "reason": "hash does not match this line's own content"})
        prev_hash = event.get("hash", GENESIS_HASH)
    return breaks


# ---------------------------------------------------------------------------
# The log file
# ---------------------------------------------------------------------------

def _now() -> str:
    # Local time, same style as the snapshot manifests, so the two can be compared.
    return datetime.now().isoformat(timespec="milliseconds")


def _current_user() -> str:
    """OS username of whoever is running this process; "unknown" if the
    platform can't report one (e.g. no login name in the environment)."""
    try:
        return getpass.getuser()
    except OSError:
        return "unknown"


def append(root: Path, event: dict) -> None:
    """Add one event as one line to the log (creates .ai/ if needed).

    Each line is chained to the one before it (see verify_chain()) and
    stamped with the OS user running this process, so the log records who
    made each change alongside what changed.

    Raises:
        OSError: If the log cannot be written.
    """
    path = root / LOG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    prev_hash = _last_chain_hash(path)
    stamped = {**event, "user": _current_user()}
    chained = {**stamped, "prev_hash": prev_hash, "hash": _chain_hash(prev_hash, stamped)}
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(chained, ensure_ascii=False) + "\n")


def read_log(root: Path) -> list[dict]:
    """Return every event in order; [] if there is no log.

    Raises:
        ValueError: If a line is not valid JSON (a damaged log must not be skipped).
    """
    path = root / LOG_PATH
    if not path.is_file():
        return []
    events = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except ValueError as exc:
            raise ValueError(f"{LOG_PATH.as_posix()} line {number} is not valid JSON: {exc}") from exc
    return events


def read_texts(root: Path, paths: list[str]) -> dict[str, str]:
    """Current text of each file, "" for files that do not exist yet.

    Call this BEFORE applying a proposal, so the old text is still there.
    """
    texts = {}
    for rel in paths:
        target = root / rel
        texts[rel] = target.read_bytes().decode("utf-8", errors="replace") if target.is_file() else ""
    return texts


def record_apply(root: Path, task_id: str, proposal: str, files: list[dict],
                 old_texts: dict[str, str], reconcile: str, model: str | None = None) -> None:
    """Log one applied proposal.

    Args:
        root: Project root.
        task_id: The task the proposal belongs to.
        proposal: Path of the proposal file, as given to the validator.
        files: The proposal's file entries (path, action, content).
        old_texts: read_texts() taken before the files were written.
        reconcile: PASS, FAIL or SKIPPED (the post-write disk check).
        model: The AI model name the proposal declared, if any (the "user"
            field, stamped by append(), already covers the OS account).

    Raises:
        OSError: If the log cannot be written.
    """
    entries = []
    for f in files:
        new = "" if f["action"] == "delete" else f.get("content", "")
        entries.append(file_entry(f["path"], f["action"], old_texts.get(f["path"], ""), new))
    append(root, {"event": "apply", "time": _now(), "task_id": task_id,
                  "proposal": proposal, "reconcile": reconcile, "model": model, "files": entries})


# ---------------------------------------------------------------------------
# Drift detection: files changed on disk with no matching log entry, i.e.
# someone edited the workspace without going through validate_proposal.py.
# ---------------------------------------------------------------------------

def _read_snapshot_manifest(root: Path, snapshot_id: str) -> dict | None:
    """The named snapshot's manifest.json, or None if missing/unreadable."""
    if not snapshot_id:
        return None
    path = root / ".ai" / "snapshots" / snapshot_id / "manifest.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def known_state(root: Path, events: list[dict]) -> dict[str, str | None]:
    """Replay the log to get each path's last logged content hash.

    None means the log's last word on that path was "deleted". A path the
    log never mentions is absent from the result entirely — detect_drift()
    reads that as "no matching entry".

    A rollback restores files from its snapshot without re-logging each
    one's content (the snapshot manifest already has that), so its restored
    paths are read from `.ai/snapshots/<id>/manifest.json` instead of the
    event itself. A snapshot that no longer exists on disk is skipped rather
    than guessed at.
    """
    state: dict[str, str | None] = {}
    for event in events:
        if event.get("event") == "apply":
            for entry in event.get("files", []):
                state[entry["path"]] = entry.get("content_hash")
        elif event.get("event") == "rollback":
            manifest = _read_snapshot_manifest(root, event.get("snapshot_id", ""))
            for path, digest in (manifest or {}).get("files", {}).items():
                state[path] = digest
            for path in event.get("files_deleted", []):
                state[path] = None
    return state


def detect_drift(root: Path, events: list[dict], current_files: dict[str, str]) -> list[dict]:
    """Files on disk whose content the audit log does not account for.

    Args:
        root: Project root (for reading rollback snapshot manifests).
        events: The log, in order (e.g. from read_log()).
        current_files: {relative path: sha256 hex of current bytes} for the
            live workspace, e.g. from scripts.snapshot._collect_workspace_files().

    Returns:
        One dict per drifted path, sorted by path:
        {"path": ..., "reason": "untracked" | "diverged", "logged_hash": str|None}.
        "untracked": the log never mentions this path at all.
        "diverged": the log's last known hash for this path does not match
        what's on disk now (edited again after being logged, or logged as
        deleted but still present).
    """
    state = known_state(root, events)
    findings = []
    for path in sorted(current_files):
        digest = current_files[path]
        if path not in state:
            findings.append({"path": path, "reason": "untracked", "logged_hash": None})
        elif state[path] != digest:
            findings.append({"path": path, "reason": "diverged", "logged_hash": state[path]})
    return findings


def _print_drift(findings: list[dict]) -> None:
    if not findings:
        print("[DRIFT] No files changed outside the proposal flow.")
        return
    print(f"[DRIFT] {len(findings)} file(s) changed on disk with no matching entry "
          f"in {LOG_PATH.as_posix()}:")
    for f in findings:
        note = ("never recorded in the audit log" if f["reason"] == "untracked"
                else "differs from the log's last recorded change")
        print(f"  ! {f['path']}  ({note})")


# ---------------------------------------------------------------------------
# Asking the log
# ---------------------------------------------------------------------------

def _span(ranges: list[list[int]]) -> str:
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in ranges) or "-"


def _describe(event: dict, entry: dict) -> str:
    fns = ", ".join(f"{f['name']} ({f['change']})" for f in entry["functions"]) or "-"
    guess = " ~" if entry["function_detection"] == "approximate" else ""
    return (f"{event['time']}  {event['task_id']}  {entry['action']:<6} {entry['path']}  "
            f"+{entry['lines_added']} -{entry['lines_removed']}  "
            f"added: {_span(entry['added'])} | removed: {_span(entry['removed'])}  "
            f"functions{guess}: {fns}")


def format_matches(events: list[dict], task: str | None, file: str | None,
                   function: str | None) -> list[str]:
    """One text line per matching (event, file); rollbacks that undid a task."""
    lines = []
    for event in events:
        if event.get("event") == "rollback":
            if not (file or function) and (not task or task in event.get("tasks_undone", [])):
                undone = ", ".join(event.get("tasks_undone", [])) or "none"
                lines.append(f"{event['time']}  ROLLBACK to {event['snapshot_id']}  tasks undone: {undone}")
            continue
        if task and event.get("task_id") != task:
            continue
        for entry in event.get("files", []):
            if file and file.replace("\\", "/") not in entry["path"]:
                continue
            if function and not any(function in f["name"] for f in entry["functions"]):
                continue
            lines.append(_describe(event, entry))
    return lines


def main(argv: list[str] | None = None) -> int:
    """CLI: print who changed what. Returns a process exit code."""
    parser = argparse.ArgumentParser(description="Show which task changed which file, lines and functions.")
    parser.add_argument("--task", help="only this task, e.g. TASK-001")
    parser.add_argument("--file", help="only files whose path contains this text")
    parser.add_argument("--function", help="only changes touching a function whose name contains this text")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="project root (default: current folder)")
    parser.add_argument("--check-drift", action="store_true",
                        help="report workspace files the audit log does not account for "
                             "(changed outside the proposal flow); exit 1 if any are found")
    parser.add_argument("--verify-chain", action="store_true",
                        help="check the log's tamper-evident hash chain for broken links; "
                             "exit 1 if any are found")
    args = parser.parse_args(argv)
    try:
        events = read_log(args.root)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.verify_chain:
        breaks = verify_chain(events)
        if not breaks:
            print(f"[CHAIN] {LOG_PATH.as_posix()} is intact — {len(events)} entr"
                  f"{'y' if len(events) == 1 else 'ies'} checked, no broken links.")
        else:
            print(f"[CHAIN] {len(breaks)} broken link(s) in {LOG_PATH.as_posix()}:")
            for b in breaks:
                print(f"  ! line {b['line']}: {b['reason']}")
        return 1 if breaks else 0

    if args.check_drift:
        from snapshot import _collect_workspace_files  # local: only --check-drift needs it
        current = _collect_workspace_files(args.root)
        findings = detect_drift(args.root, events, current)
        _print_drift(findings)
        return 1 if findings else 0

    for line in format_matches(events, args.task, args.file, args.function):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
