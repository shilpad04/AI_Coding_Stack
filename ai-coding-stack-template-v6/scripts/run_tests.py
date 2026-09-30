#!/usr/bin/env python3
"""
scripts/run_tests.py — AGENTS.md Step 4, as one command.

Runs the project's test command (config/config.yaml -> tests.command) and,
if configured, its lint/type-check command (context.md's Build/Run Commands
table -> "Lint / type-check" row), so non-Python code gets checked too, not
just Python tests. Both commands are set by a human in files that already
require explicit approval to edit (context.md is protected, RULE-GOV-001),
so running them here is not a Gate 1 concern the way an AI-proposed command
would be.

Usage:
    python scripts/run_tests.py [--root PATH] [--config PATH] [--context PATH]

Exit codes: 0 if the test command (and lint command, if configured) both
pass; 1 if either fails, or if tests.command is not set.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import yaml

_LINT_ROW_RE = re.compile(r"-\s*\*\*Lint\s*/\s*type-check\*\*:\s*`([^`]*)`")

# Summary lines from pytest ("1 failed, 40 passed in 1.2s"), Jest ("Tests: 1 failed,
# 40 passed") and Vitest ("Tests  1 failed | 40 passed"). Other runners: counts unknown.
_PASSED_RE = re.compile(r"(\d+) passed")
_FAILED_RE = re.compile(r"(\d+) (?:failed|errors?)\b")
_SUITES_LINE_RE = re.compile(r"^\s*(?:Test Suites:|Test Files\s)")


def load_tests_command(config_path: Path) -> str | None:
    """config/config.yaml's tests.command, or None if missing/not set."""
    if not config_path.is_file():
        return None
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    command = (data.get("tests") or {}).get("command")
    return command if isinstance(command, str) and command.strip() else None


def load_lint_command(context_path: Path) -> str | None:
    """context.md's "Lint / type-check" row, or None if missing/unfilled."""
    if not context_path.is_file():
        return None
    match = _LINT_ROW_RE.search(context_path.read_text(encoding="utf-8"))
    if not match:
        return None
    command = match.group(1).strip()
    if not command or "FILL IN" in command:
        return None
    return command


def _count(line: str) -> dict[str, int]:
    return {"passed": sum(int(n) for n in _PASSED_RE.findall(line)),
            "failed": sum(int(n) for n in _FAILED_RE.findall(line))}


def parse_counts(output: str) -> dict | None:
    """Passed/failed test counts (and suite counts, if reported) from the
    runner's summary, or None if no summary line was recognised."""
    suites_line = tests_line = None
    for line in output.splitlines():
        if _SUITES_LINE_RE.match(line):
            suites_line = line
        elif _PASSED_RE.search(line) or _FAILED_RE.search(line):
            tests_line = line
    if tests_line is None:
        return None
    counts: dict = _count(tests_line)
    counts["suites"] = _count(suites_line) if suites_line else None
    return counts


def format_counts(counts: dict | None) -> str:
    if counts is None:
        return " (counts not reported by this runner)"
    text = f"{counts['passed']} passed, {counts['failed']} failed"
    suites = counts["suites"]
    if suites:
        text += f"; suites: {suites['passed']} passed, {suites['failed']} failed"
    return f" ({text})"


def run_command(cmd: str, cwd: Path) -> tuple[int, str]:
    """Run cmd, echoing its output live, and return (exit code, output)."""
    print(f"$ {cmd}", flush=True)
    proc = subprocess.Popen(cmd, shell=True, cwd=cwd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, errors="replace")
    lines = []
    for line in proc.stdout:
        print(line, end="", flush=True)
        lines.append(line)
    return proc.wait(), "".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the project's test command, then its lint/type-check command.")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="project root (default: current folder)")
    parser.add_argument("--config", type=Path, default=None, help="path to config.yaml (default: <root>/config/config.yaml)")
    parser.add_argument("--context", type=Path, default=None, help="path to context.md (default: <root>/context.md)")
    args = parser.parse_args(argv)

    config_path = args.config or (args.root / "config" / "config.yaml")
    context_path = args.context or (args.root / "context.md")

    tests_command = load_tests_command(config_path)
    if not tests_command:
        print(f"ERROR: no tests.command set in {config_path}", file=sys.stderr)
        return 1

    print("[QA Agent] Running the tests.")
    tests_code, tests_output = run_command(tests_command, args.root)
    tests_ok = tests_code == 0
    print(f"tests: {'PASS' if tests_ok else 'FAIL'}{format_counts(parse_counts(tests_output))}")

    lint_command = load_lint_command(context_path)
    if lint_command:
        print("[QA Agent] Running lint / type-check.")
        lint_ok = run_command(lint_command, args.root)[0] == 0
        print(f"lint: {'PASS' if lint_ok else 'FAIL'}")
    else:
        lint_ok = True
        print("lint: SKIPPED (no Lint / type-check command set in context.md)")

    return 0 if tests_ok and lint_ok else 1


if __name__ == "__main__":
    sys.exit(main())
