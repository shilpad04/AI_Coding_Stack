# Agent Instructions & Workflow Protocol

## 🏛️ Pipeline Architecture & Agent Roles

This repository uses a four-role workflow with separate responsibilities. One AI plays the roles in order; the Step 3 checks are done by code, not by the AI:

1. **Planner Agent (Phase 1):**
   - Ingests PRDs from `input/*.md`.
   - Generates `.ai/plan.json` breaking the PRD into phases, tasks, acceptance criteria, and locked file boundaries (`allowed_files`) — do not echo the full file.
   - Waits for human approval before execution.

2. **Developer Agent (Phase 2 & 3):**
   - Reads locked tasks from `.ai/plan.json`.
   - Writes feature specs in `specs/spec.md`.
   - Outlines unit tests and drafts code into JSON proposal envelopes stored in `.ai/proposals/proposal_<TASK_ID>.json`.

3. **Policy & Governance Agent (Phase 3 Gatekeeper):**
   - Executes `python scripts/validate_proposal.py .ai/proposals/proposal_<TASK_ID>.json --apply`.
   - First checks the proposal format, and reads the task's `allowed_files` from the approved `.ai/plan.json`.
   - Runs 6 deterministic checks: Rules, Scope bounds, Hardcoded Secrets, Package Whitelists (`config/approved-packages.yaml`), Command Policies (`config/command-policy.yaml`), and Protected Infrastructure Files (`RULE-GOV-001`).
   - Handles Exit Codes:
     - `0 (PASS)` -> Apply changes & reconcile disk.
     - `1 (FAIL)` -> Auto-fix feedback loop back to Developer Agent.
     - `2 (ASK)` -> Pause execution for Human Governance Approval.

4. **QA & Code Reviewer Agent (Phase 4):**
   - Executes the automated test command defined in `config/config.yaml` (`python -m pytest -q`, `npm test`, etc.).
   - Enforces `.agents/rules/code-standards.md`: parameter/return typing, scoped logger setup, explicit exception handling, and its coverage requirement.
   - Prepares change summary and test logs for final Human Approval.

**Status lines.** So a human can see who is doing what, every step starts with one
short line naming the role and the action, e.g. `[Planner Agent] Turning the PRD into a plan.`
or `[Developer Agent] Writing the TASK-001 proposal.` The AI prints the Planner and Developer
lines itself. `scripts/validate_proposal.py` prints the `[Policy Agent]` lines and
`scripts/run_tests.py` prints the `[QA Agent]` lines, including the passed/failed test counts
and lint PASS/FAIL.

---

## 🔄 Session Workflow

### Step 0 — Confirm Project Structure (blocking)

First ask: **is this a new project or an existing repo?**

**New project**
Read `context.md` → **Repo / Folder Conventions**. If **Frontend** or **Backend**
is still `[FILL IN]`, propose them from the PRD and stop for confirmation.
Never assume. Restate the chosen layout, then continue.

**Existing repo**
Do not propose a layout. Run:

```bash
python scripts/symbol_mapper.py
```

Read the output and write the folder layout you actually found into
`context.md` → **Repo / Folder Conventions**. Restate it and stop for
confirmation.

The layout on disk wins. Never propose moving or renaming existing folders as
part of a task.

`context.md` is a protected file (`RULE-GOV-001`). Write the layout into it only
after the human has confirmed it.

> Step 1 locks `allowed_files` for the whole project. Settle the layout first.

---

### Step 1 — Phasify (Planner Agent)

When a PRD is placed in `input/` or the user says "phasify":

1. Read the PRD fully.
2. **If `.ai/plan.json` already has phases in it, this PRD is an addition, not
   a replacement.** Append a new phase for it. Never overwrite an existing
   phase or task, never renumber, and never reuse a `task_id` — not even one
   marked `COMPLETED` or `FAILED`. A requirement change to a task already
   `COMPLETED` is a new task, not an edit to the old one; the old task's
   record stays as history. This is what makes `.ai/traceability.ndjson`
   trustworthy: a `task_id` always means the same task.
3. Break the PRD into phases and tasks using the schema below.
4. Every path in `allowed_files` must sit inside the folders defined in
   `context.md` → **Repo / Folder Conventions**. A path outside them is a
   planning error — fix the plan, not the layout.
5. One task, one layer (`RULE-STRUCT-001`). Endpoint and repository are two tasks.
6. Write `.ai/plan.json` and present a high-level phase summary. Wait for human approval before proceeding.
7. **No task is applied until a human approves it.** After the human reviews
   `.ai/plan.json`, they run `python scripts/approve_plan.py --all` (or
   `<TASK_ID>` for one task); until then `validate_proposal.py` returns ASK
   (`RULE-PLAN-001`) for that task. Never run `approve_plan.py` yourself. A
   task's `allowed_files` may be narrowed later with no extra step, but
   widening it needs the human to approve that task again. Say this plainly
   if a task needs more files than first planned; don't treat the ASK as a bug.
8. **Every task needs at least one acceptance criterion** (`RULE-PLAN-002`,
   FAIL otherwise), and a proposal that changes source files must include a
   test file (`RULE-TEST-001`, FAIL otherwise).

**`plan.json` schema:**

```json
{
  "project": "project name",
  "current_phase": "PHASE-1",
  "phases": [
    {
      "id": "PHASE-1",
      "name": "descriptive name",
      "status": "PLANNED",
      "tasks": [
        {
          "task_id": "TASK-001",
          "description": "what to build",
          "allowed_files": [
            "backend/app/repositories/order_repository.py",
            "backend/tests/unit/test_order_repository.py"
          ],
          "acceptance_criteria": [
            "get_order(id) returns an Order for an existing id",
            "get_order(id) raises OrderNotFound for a missing id"
          ],
          "depends_on": [],
          "status": "PLANNED"
        }
      ]
    }
  ]
}
```

Status values: `PLANNED` -> `IN_PROGRESS` -> `COMPLETED` or `FAILED`.

6. Every `acceptance_criteria` entry must be checkable by a test. Write the
   check, not the intention.
   - Not: "handles bad input properly"
   - Yes: "returns 400 with an error body when `order_id` is missing"
   - Not: "fixes the duplicate charge bug"
   - Yes: "a test reproducing the duplicate charge fails before the change and
     passes after"

   If a criterion cannot be turned into a test, it is too vague. Ask before
   planning it.

> ⚠️ Shape only — never copy these values. A proposal whose files don't match
> its task's `allowed_files` is invalid.

---

### Step 2 — Start a Task (Developer Agent)

1. Read `.ai/plan.json` — confirm active task ID and locked `allowed_files`.
2. State the task ID and acceptance criteria.
3. Check `config/approved-packages.yaml` for every package planned for use.
   - If not listed, stop and ask the user for approval. Do NOT auto-edit `approved-packages.yaml`.
4. Outline feature design in `specs/spec.md` and list target unit tests, one per
   acceptance criterion for this task — see `.agents/rules/code-standards.md` (PRD Traceability).
   **`specs/spec.md` is one file for the whole project, kept forever.** Add a
   `## TASK_ID` section for this task at the end of the file; never overwrite
   or delete an earlier task's section. The file reads as a running history
   of every task's design, in task order.

---

### Step 3 — Implement (Developer & Policy Agents)

1. Write only what the task requires into proposal envelope `.ai/proposals/proposal_<TASK_ID>.json`.
   Every file needs `path`, `action` and the FULL `content` (a delete needs no content).
   Shape only — never copy these values:
   ```json
   {"task_id": "TASK-001", "status": "PROPOSAL", "summary": "one line",
    "files": [{"path": "<a path in allowed_files>", "action": "create|modify|delete", "content": "<full file text>"}],
    "packages": [{"name": "<name>", "version": "<version>", "ecosystem": "pypi", "reason": "<why>"}],
    "commands": [{"command": "<one command>", "reason": "<why>"}],
    "clarifications": [{"question": "<question>", "why_needed": "<why>"}], "observations": []}
   ```
   If something is unclear, set `"status": "CLARIFICATION_REQUIRED"` and fill `clarifications` instead of guessing.
2. Execute proposal validation. It reads this task's `allowed_files` from the approved `.ai/plan.json`, and writes nothing unless every check passes (exit 0):
   ```bash
   python scripts/validate_proposal.py .ai/proposals/proposal_<TASK_ID>.json --apply
   ```
   Every applied proposal is logged to `.ai/traceability.ndjson` (task, file, changed lines, functions). Never edit that log.
   Ask it with `python scripts/traceability.py --task <TASK_ID>` (or `--file`, `--function`).
3. Evaluate Exit Code:
   - **Exit 0 (PASS):** Files applied & reconciled on disk. Proceed to Step 4.
   - **Exit 1 (FAIL):** Hard policy violation. Auto-fix violation and re-validate.
     - _CRITICAL:_ If FAIL is caused by an unapproved package or dependency-manifest entry (`RULE-DEP-001`) — this covers `package.json`, `requirements.txt`, `pyproject.toml`, `pom.xml`, `build.gradle`, `.csproj`, `packages.config` and `pubspec.yaml`, not just imports — do NOT edit `approved-packages.yaml` to bypass the failure. Pause and ask the user for permission.
     - After `governance.max_repair_attempts` consecutive FAILs on the same task (`config.yaml`, currently 2), the validator returns exit 2 (ASK) instead of 1. Stop and wait for a human instead of retrying again.
   - **Exit 2 (ASK):** Protected file (`RULE-GOV-001`), unapproved command touched, the task not yet approved by a human (`RULE-PLAN-001`), or the repair-attempt limit reached on this task. Pause for human approval.

---

### Step 4 — Run Tests (QA & Code Reviewer Agent)

1. Execute test command from `config/config.yaml` (`tests.command`).
2. Verify:
   - All tests pass.
   - Every acceptance criterion for this task has at least one test proving it — no
     untested criteria, and no meaningless tests added just to pad the count.
   - Coverage meets the requirement in `.agents/rules/code-standards.md` (changed files at 80%,
     repo-wide not lower than before).
   - Standards in `.agents/rules/code-standards.md` (typing, scoped logger, no silent exceptions) are met.
3. If tests fail, send failure logs back to Step 3 for repair.

---

### Step 5 — Final Approval (Human Gate)

Present to the user:

- Summary of modified files.
- Test execution results and coverage logs.
- Observations outside scope (logged, NOT modified inline).

Ask: _"Approve, or do you have remarks?"_

- **Approved:** Mark task `COMPLETED` in `.ai/plan.json`, move to next task.
- **Remark:** Address feedback and return to Step 3.
- **Phase Complete:** Mark phase `COMPLETED` in `.ai/plan.json`.
