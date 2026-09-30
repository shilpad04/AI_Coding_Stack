"""
tests/test_split_prd.py
========================
Tests for scripts/split_prd.py: splits an oversized PRD into smaller
markdown files (by top-level "## " section) sized to fit config.yaml's
context.max_tokens, so Step 1 (Phasify) can process one chunk at a time and
append each chunk's phase to the same plan.json (the existing append-only
rule already handles the "one at a time" part).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import split_prd as sp  # noqa: E402


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class TestSplitPrd:
    def test_small_prd_is_not_split(self, tmp_path):
        prd = tmp_path / "input" / "small.md"
        _write(prd, "# Small PRD\n\n## Overview\nJust a little text.\n")

        assert sp.split_prd(prd, tmp_path) == [prd]

    def test_default_budget_is_used_when_config_missing(self, tmp_path):
        prd = tmp_path / "input" / "small.md"
        _write(prd, "# Small\n\n## One\nshort\n")

        assert sp.split_prd(prd, tmp_path) == [prd]

    def test_large_prd_is_split_by_top_level_headings(self, tmp_path):
        _write(tmp_path / "config" / "config.yaml", "context:\n  max_tokens: 10\n")  # 40-char budget
        prd = tmp_path / "input" / "big.md"
        preamble = "# Big PRD\n\n"
        sections = [f"## Section {i}\n{'x' * 20}\n" for i in range(1, 5)]
        _write(prd, preamble + "".join(sections))

        chunks = sp.split_prd(prd, tmp_path)

        assert len(chunks) > 1
        for c in chunks:
            assert c.parent == prd.parent
            assert c.name.startswith("big.part")
            assert c.read_text(encoding="utf-8").startswith(preamble)
        combined = "".join(c.read_text(encoding="utf-8") for c in chunks)
        for i in range(1, 5):
            assert f"## Section {i}" in combined

    def test_a_single_oversized_section_is_kept_whole_not_dropped(self, tmp_path):
        _write(tmp_path / "config" / "config.yaml", "context:\n  max_tokens: 5\n")  # 20-char budget
        prd = tmp_path / "input" / "one_big_section.md"
        _write(prd, "# T\n\n## Section 1\n" + ("y" * 100) + "\n")

        chunks = sp.split_prd(prd, tmp_path)

        assert len(chunks) == 1
        assert "y" * 100 in chunks[0].read_text(encoding="utf-8")

    def test_no_headings_at_all_is_left_unsplit(self, tmp_path):
        _write(tmp_path / "config" / "config.yaml", "context:\n  max_tokens: 5\n")
        prd = tmp_path / "input" / "flat.md"
        _write(prd, "just a wall of text with no ## headings " * 5)

        assert sp.split_prd(prd, tmp_path) == [prd]


class TestCLI:
    def test_prints_split_chunks(self, tmp_path, capsys):
        _write(tmp_path / "config" / "config.yaml", "context:\n  max_tokens: 10\n")
        prd = tmp_path / "input" / "big.md"
        _write(prd, "# Big\n\n" + "".join(f"## S{i}\n{'x' * 20}\n" for i in range(1, 4)))

        code = sp.main(["--root", str(tmp_path), str(prd)])

        assert code == 0
        assert "Split into" in capsys.readouterr().out

    def test_small_prd_reports_no_split_needed(self, tmp_path, capsys):
        prd = tmp_path / "input" / "small.md"
        _write(prd, "# Small\n\n## One\nshort\n")

        code = sp.main(["--root", str(tmp_path), str(prd)])

        assert code == 0
        assert "no split needed" in capsys.readouterr().out

    def test_missing_file_is_an_error(self, tmp_path, capsys):
        code = sp.main(["--root", str(tmp_path), str(tmp_path / "input" / "nope.md")])
        assert code == 1
        assert "not found" in capsys.readouterr().err
