---
name: context-hygiene
description: >-
  Context compaction and session hygiene skill. Use to distill conversation state into
  a concise session snapshot (.ai/session_summary.md), preventing token bloat and attention loss.
---

# Context Hygiene & Compaction Skill

Use this skill during extended vibe-coding sessions (15+ turns) to preserve token budget, eliminate prompt bloat, and maintain sharp focus.

---

## When to Compact Context
- When the chat conversation history is getting long and tool outputs are cluttering context.
- Before switching to a new major feature or phase.
- When the user asks to *"summarize context"* or *"compact state"*.

---

## How to Compact

Run the compactor script to generate a distilled `.ai/session_summary.md` (<500 tokens):
```bash
# Basic compaction
python .aistack/scripts/context_compact.py

# Compaction with explicit active goal
python .aistack/scripts/context_compact.py --goal "Implementing JWT auth endpoints and tests"
```

---

## What the Session Summary Captures:
1. **Active Goal & Scope**: The feature currently in flight.
2. **Workspace Architecture Map**: The key source and test modules currently in the repository.
3. **Latest Checkpoint**: The active snapshot ID in `.ai/snapshots/`.
4. **Active Constraints**: The Four Principles & testing requirements.

*Starting a fresh chat session and reading `.ai/session_summary.md` gives the agent 100% of needed context for only ~400 tokens.*
