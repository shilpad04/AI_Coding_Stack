#!/usr/bin/env python3
"""
scripts/package_template.py — Clean Distribution Zipper

Packages this repository into a clean `ai-coding-stack-template.zip` for sharing with
coworkers via shared network drive, SharePoint, or email.

Excludes caches, snapshots, and temporary files.

Usage:
    python scripts/package_template.py
    python scripts/package_template.py --output "D:/SharedDrive/ai-coding-stack.zip"
"""

import os
import sys
import zipfile
import argparse
from pathlib import Path

EXCLUDE_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "node_modules",
    "dist", "build", ".pytest_cache", ".ai/snapshots", ".ai/backups",
    ".mypy_cache", ".ruff_cache", "coverage", ".gemini"
}

EXCLUDE_FILES = {
    ".DS_Store", "Thumbs.db", "ai-coding-stack-template.zip", "*.pyc", "*.pyo",
    "spec.md", "plan.json", "traceability.ndjson", "task-state.json", "plan-approval.json"
}


def create_clean_zip(root: Path, output_zip_path: Path) -> Path:
    """Pack workspace into a clean zip archive."""
    output_zip_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0

    with zipfile.ZipFile(output_zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for dirpath, dirnames, filenames in os.walk(root):
            # Prune excluded directories
            rel_dir = Path(dirpath).relative_to(root).as_posix()
            dirnames[:] = [
                d for d in sorted(dirnames)
                if not any(
                    part in EXCLUDE_DIRS or (part.startswith(".") and part not in (".agents", ".ai"))
                    for part in Path(dirpath, d).relative_to(root).parts
                ) and not (Path(dirpath, d).relative_to(root).as_posix().startswith((".ai/snapshots", ".ai/backups")))
            ]

            for f in sorted(filenames):
                file_p = Path(dirpath, f)
                rel_p = file_p.relative_to(root).as_posix()

                if f in EXCLUDE_FILES or f.endswith((".pyc", ".zip")) or f.startswith("proposal_"):
                    continue
                if any(part in EXCLUDE_DIRS for part in Path(rel_p).parts):
                    continue
                if rel_p.startswith((".ai/snapshots", ".ai/backups")):
                    continue

                zipf.write(file_p, arcname=rel_p)
                count += 1

    size_kb = output_zip_path.stat().st_size / 1024
    print(f"[PACKAGE] Successfully created clean distribution zip:")
    print(f"  Archive: {output_zip_path}")
    print(f"  Files:   {count} files ({size_kb:.1f} KB)")
    return output_zip_path


def main():
    parser = argparse.ArgumentParser(description="Package AI Coding Stack into a clean zip")
    parser.add_argument("--output", "-o", type=str, default="ai-coding-stack-template.zip", help="Destination zip path")
    args = parser.parse_args()

    root = Path.cwd()
    out_p = Path(args.output) if Path(args.output).is_absolute() else root / args.output
    create_clean_zip(root, out_p)


if __name__ == "__main__":
    main()
