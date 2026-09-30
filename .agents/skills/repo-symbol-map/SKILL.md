---
name: repo-symbol-map
description: >-
  AST Repository Symbol Mapper skill. Use to understand the whole codebase architecture,
  class hierarchies, method signatures, and exported types in under 500 tokens.
---

# Repository Symbol Mapper Skill

Use this skill when you need whole-codebase architectural context without burning thousands of prompt tokens reading raw source files.

---

## How It Works

Instead of running broad directory scans or dumping multiple full source files into context:
1. Run `python .aistack/scripts/symbol_mapper.py`.
2. Inspect the generated **AST Symbol Map** (~2KB).
3. Identify the exact 1–2 files that contain the relevant functions or classes.
4. Read only the specific target lines needed for your edit.

---

## CLI Usage

```bash
# Print symbol map to console
python .aistack/scripts/symbol_mapper.py

# Save symbol map to file
python .aistack/scripts/symbol_mapper.py --output .ai/symbol_map.txt
```

---

## Symbol Map Format

The map indexes Python and TypeScript/JavaScript source files:
```text
📄 src/backend/models.py
  class GameStateModel [@properties: current_turn, winner]
    def __init__(board, mode) -> None
    def execute_move(from_pos, to_pos) -> bool
  def calculate_score(state) -> int

📄 frontend/src/types.ts
  interfaces: UserProfile, AuthSession
  types: MoveCoordinate
  fn validateInput(raw)
```

### Key Rules:
- `@properties` are explicitly marked so you never accidentally invoke them as functions `obj.prop()`.
- Use this map to navigate the repository with 90%+ token reduction compared to full-file ingestion.
