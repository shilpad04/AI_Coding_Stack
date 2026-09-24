#!/usr/bin/env python3
"""
scripts/split_prd.py — split an oversized PRD into smaller chunks.

A PRD bigger than config.yaml's context.max_tokens can overwhelm a model
during Step 1 (Phasify). This splits it into files sized to fit that budget,
grouped by top-level "## " section (each chunk keeps everything before the
first "## " as shared context). Phasify each chunk in turn — the existing
append-only plan.json rule already appends each chunk's phase without
overwriting the ones before it, so "one at a time" needs no new code there.

Usage:
    python scripts/split_prd.py input/big_prd.md [--root PATH]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

CHARS_PER_TOKEN = 4  # rough heuristic, no tokenizer dependency
DEFAULT_MAX_TOKENS = 12000

_SECTION_RE = re.compile(r"^## ", re.M)


def _max_chars(root: Path) -> int:
    """Char budget derived from config.yaml's context.max_tokens (or the
    stack's own default if missing/unset)."""
    max_tokens = DEFAULT_MAX_TOKENS
    config_path = root / "config" / "config.yaml"
    if config_path.is_file():
        try:
            data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            value = (data.get("context") or {}).get("max_tokens")
            if isinstance(value, int) and value > 0:
                max_tokens = value
        except Exception:
            pass
    return max_tokens * CHARS_PER_TOKEN


def _split_sections(text: str) -> tuple[str, list[str]]:
    """Everything before the first "## " heading, and each "## " section as
    its own string (heading through the line before the next one)."""
    matches = list(_SECTION_RE.finditer(text))
    if not matches:
        return text, []
    preamble = text[:matches[0].start()]
    sections = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append(text[m.start():end])
    return preamble, sections


def _group_sections(preamble: str, sections: list[str], budget: int) -> list[str]:
    """Group consecutive sections under `budget` chars, preamble repeated in
    each group. A single section over budget on its own is still kept whole
    — never dropped or cut mid-section."""
    chunks: list[str] = []
    current = preamble
    current_has_section = False
    for section in sections:
        candidate = current + section
        if current_has_section and len(candidate) > budget:
            chunks.append(current)
            current = preamble + section
        else:
            current = candidate
        current_has_section = True
    chunks.append(current)
    return chunks


def split_prd(path: Path, root: Path) -> list[Path]:
    """Split `path` into sized chunks if it exceeds the context budget.

    Returns:
        [path] unchanged if it already fits (or has no "## " sections to
        split on); otherwise the list of newly written "<stem>.partN.md"
        files, in order, next to the original.
    """
    text = path.read_text(encoding="utf-8")
    budget = _max_chars(root)
    if len(text) <= budget:
        return [path]

    preamble, sections = _split_sections(text)
    if not sections:
        return [path]

    chunks = _group_sections(preamble, sections, budget)
    if len(chunks) <= 1:
        return [path]

    out_paths = []
    for i, chunk_text in enumerate(chunks, start=1):
        out_path = path.parent / f"{path.stem}.part{i}.md"
        out_path.write_text(chunk_text, encoding="utf-8")
        out_paths.append(out_path)
    return out_paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Split an oversized PRD into chunks sized to fit context.max_tokens.")
    parser.add_argument("prd", type=Path, help="path to the input/*.md PRD file")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="project root (default: current folder)")
    args = parser.parse_args(argv)

    if not args.prd.is_file():
        print(f"ERROR: {args.prd} not found", file=sys.stderr)
        return 1

    chunks = split_prd(args.prd, args.root)
    if len(chunks) == 1 and chunks[0] == args.prd:
        print(f"{args.prd} is within the context budget — no split needed.")
    else:
        print(f"Split into {len(chunks)} chunk(s), phasify them in order:")
        for c in chunks:
            print(f"  {c}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
