#!/usr/bin/env python3
"""
scripts/context_compact.py — Session State Compactor

Distills current workspace state, active plan, modified files, and test statuses
into a concise `.ai/session_summary.md` (<500 tokens).

Enables starting clean conversation turns with zero loss of context, preventing
attention dilution and token bloat during extended vibe-coding sessions.

Usage:
    python scripts/context_compact.py
    python scripts/context_compact.py --goal "Build authentication system"
"""

import os
import json
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any

IGNORE_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "node_modules",
    "dist", "build", ".pytest_cache", ".ai/snapshots", ".ai/backups",
    "coverage", ".mypy_cache", ".ruff_cache"
}


def compact_session_context(root: Path, active_goal: str = None) -> str:
    """Generate a compact session summary document (<500 tokens)."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    sections = [
        f"# Session State Snapshot ({now_str})",
        ""
    ]

    # 1. Active Goal
    if active_goal:
        sections.append(f"## Active Goal\n{active_goal.strip()}\n")
    else:
        # Check if plan.json has active task
        plan_p = root / ".ai" / "plan.json"
        if plan_p.exists():
            try:
                p_data = json.loads(plan_p.read_text(encoding="utf-8"))
                proj = p_data.get("project", "Project")
                curr_ph = p_data.get("current_phase", "")
                sections.append(f"## Active Project & Phase\n- **Project:** {proj}\n- **Phase:** {curr_ph}\n")
            except Exception:
                pass

    # 2. Key Recent Files & Modules
    source_files = []
    test_files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")]
        for f in sorted(filenames):
            rel_p = Path(dirpath, f).relative_to(root).as_posix()
            if rel_p.startswith(".agents/"):
                continue
            ext = Path(f).suffix.lower()
            if ext in (".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs"):
                if "test" in f.lower():
                    test_files.append(rel_p)
                else:
                    source_files.append(rel_p)

    sections.append("## Workspace Architecture Map")
    if source_files:
        sections.append(f"- **Source Modules ({len(source_files)}):** " + ", ".join(f"`{f}`" for f in source_files[:12]))
        if len(source_files) > 12:
            sections.append(f"  *(and {len(source_files) - 12} more)*")
    if test_files:
        sections.append(f"- **Test Suites ({len(test_files)}):** " + ", ".join(f"`{f}`" for f in test_files[:8]))
    sections.append("")

    # 3. Latest Snapshot Checkpoint
    snapshots_dir = root / ".ai" / "snapshots"
    if snapshots_dir.exists():
        snaps = sorted([d.name for d in snapshots_dir.iterdir() if d.is_dir() and (d / "manifest.json").exists()], reverse=True)
        if snaps:
            sections.append(f"## Local Checkpoint\n- **Latest Snapshot:** `{snaps[0]}`\n")

    # 4. Working Directives
    sections.append(
        "## Next Steps / Active Constraints\n"
        "- Follow The Four Principles: Think before coding, Simplicity first, Surgical changes, Goal-driven.\n"
        "- Run tests immediately after modifications to verify behavior.\n"
    )

    summary_text = "\n".join(sections)
    out_file = root / ".ai" / "session_summary.md"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(summary_text, encoding="utf-8")

    print(f"[CONTEXT-COMPACT] Distilled session state saved to {out_file} ({len(summary_text)} chars / ~{len(summary_text)//4} tokens)")
    return summary_text


def main():
    parser = argparse.ArgumentParser(description="Session Context Compactor")
    parser.add_argument("--goal", "-g", type=str, default=None, help="Describe current feature goal or working context")
    args = parser.parse_args()

    root = Path.cwd()
    compact_session_context(root, args.goal)


if __name__ == "__main__":
    main()
