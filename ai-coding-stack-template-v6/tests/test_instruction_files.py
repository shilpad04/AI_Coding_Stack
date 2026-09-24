"""
tests/test_instruction_files.py
===============================
The four tool entry files (CLAUDE.md, .cursorrules, .clinerules, .windsurfrules)
carry the same short "starter card". These tests keep them identical, small,
and pointing at files that exist.
"""
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
CARD_FILES = ["CLAUDE.md", ".cursorrules", ".clinerules", ".windsurfrules"]
MAX_CARD_BYTES = 4000  # the card is read on every request; keep it small


def _card(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_all_four_cards_are_identical() -> None:
    reference = _card(CARD_FILES[0])
    for name in CARD_FILES[1:]:
        assert _card(name) == reference, f"{name} has drifted from CLAUDE.md"


def test_card_stays_small() -> None:
    assert len(_card("CLAUDE.md").encode("utf-8")) <= MAX_CARD_BYTES


def test_card_names_every_skill() -> None:
    card = _card("CLAUDE.md")
    for skill_dir in (ROOT / ".agents" / "skills").iterdir():
        assert skill_dir.name in card, f"card does not point to skill {skill_dir.name}"


def test_every_path_the_card_points_to_exists() -> None:
    card = _card("CLAUDE.md")
    paths = set(re.findall(
        r"(?<![\w/])((?:\.agents|\.ai|config|scripts)/[\w./-]+|"
        r"(?:AGENTS|STACK_GUIDE|rules|context)\.md)", card))
    assert paths, "expected the card to reference files"
    for rel in paths:
        target = rel.rstrip("/")
        # <proposal>/<name> style placeholders and output dirs are not real files
        if "<" in target or target in {".ai/plan.json", ".ai/proposals"}:
            continue
        assert (ROOT / target).exists(), f"card points to missing file: {rel}"


def test_code_standards_file_exists_and_rules_md_points_to_it() -> None:
    assert (ROOT / ".agents" / "rules" / "code-standards.md").is_file()
    assert ".agents/rules/code-standards.md" in (ROOT / "rules.md").read_text(encoding="utf-8")
