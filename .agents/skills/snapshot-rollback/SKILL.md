---
name: snapshot-rollback
description: >-
  Git-free local snapshot and rollback engine. Use to create file checkpoints before
  complex edits, inspect diffs, and restore workspace state on demand without Git.
---

# Snapshot & Rollback Skill (Git-Free Checkpointing)

Use this skill when you are about to make significant or risky code modifications, or when the user asks to revert changes, undo edits, or save a checkpoint.

---

## When to Save a Checkpoint
- Before multi-file refactoring.
- Before running unfamiliar build scripts or major dependency upgrades.
- When the user explicitly requests: *"save a checkpoint"* or *"take a snapshot"*.

---

## Commands Reference

### 1. Save a Snapshot
```bash
python .aistack/scripts/snapshot.py save "feature-auth-start"
```
*Creates a timestamped snapshot under `.ai/snapshots/<timestamp>_<label>/` with all tracked files and metadata hashes.*

### 2. List Checkpoints
```bash
python .aistack/scripts/snapshot.py list
```

### 3. View Diffs Against Snapshot
```bash
python .aistack/scripts/snapshot.py diff
```
*Shows added (`+`), modified (`*`), and deleted (`-`) files since the latest snapshot.*

### 4. Rollback to Snapshot
```bash
# Rollback to the latest snapshot:
python .aistack/scripts/snapshot.py rollback

# Rollback to a specific snapshot ID:
python .aistack/scripts/snapshot.py rollback 20260828_103000_feature-auth-start
```
*Deletes any newly created orphan files, restores modified and deleted files, and cleans up empty directories.*
