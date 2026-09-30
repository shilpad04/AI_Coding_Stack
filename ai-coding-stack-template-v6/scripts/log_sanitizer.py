#!/usr/bin/env python3
"""
scripts/log_sanitizer.py — Log Truncator & Error Output Sanitizer

Sanitizes verbose test runner and compiler logs. Retains the essential Head and Tail
of the output to preserve error root causes while preventing token explosion in LLM prompts.

Usage:
    python scripts/log_sanitizer.py <logfile>
    echo "long log" | python scripts/log_sanitizer.py
"""

import sys
import re
import argparse
from typing import Optional

ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def sanitize_log(
    log_text: str,
    max_chars: int = 1500,
    head_ratio: float = 0.5
) -> str:
    """
    Sanitize and truncate log output to fit within a tight token budget.

    Args:
        log_text: Raw compiler or test runner output string.
        max_chars: Total character budget for the returned string (default: 1500 chars ~350 tokens).
        head_ratio: Fraction of max_chars allocated to the beginning of the log (default 0.5).

    Returns:
        Sanitized and truncated log string.
    """
    if not log_text:
        return ""

    # Strip ANSI terminal colors/escape codes
    clean_text = ANSI_ESCAPE.sub("", log_text).strip()

    if len(clean_text) <= max_chars:
        return clean_text

    head_chars = int(max_chars * head_ratio)
    tail_chars = max_chars - head_chars
    omitted_chars = len(clean_text) - head_chars - tail_chars

    head = clean_text[:head_chars].rstrip()
    tail = clean_text[-tail_chars:].lstrip()

    truncation_marker = f"\n\n[... Truncated {omitted_chars:,} characters of intermediate log output ...]\n\n"
    return head + truncation_marker + tail


def extract_error_summary(log_text: str) -> str:
    """Extract standard failure summary lines (e.g. pytest '=== FAILURES ===' or 1 failed)."""
    clean_text = ANSI_ESCAPE.sub("", log_text)
    summary_lines = []
    for line in clean_text.splitlines():
        line_s = line.strip()
        if any(kw in line_s for kw in ("FAILED", "FAILURES", "Error:", "Exception:", "passed", "failed")):
            if len(line_s) < 120 and not any(ign in line_s.lower() for ign in ("warning", "deprecation")):
                summary_lines.append(line_s)
    return "\n".join(summary_lines[:8]) if summary_lines else "Test or build failure detected"


def main():
    parser = argparse.ArgumentParser(description="Log Sanitizer and Truncator")
    parser.add_argument("file", nargs="?", default=None, help="Path to log file (or stdin if omitted)")
    parser.add_argument("--max-chars", "-m", type=int, default=1500, help="Max character length (default: 1500)")
    args = parser.parse_args()

    if args.file:
        try:
            with open(args.file, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception as e:
            print(f"Error reading file: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        if not sys.stdin.isatty():
            content = sys.stdin.read()
        else:
            parser.print_help()
            sys.exit(0)

    print(sanitize_log(content, max_chars=args.max_chars))


if __name__ == "__main__":
    main()
