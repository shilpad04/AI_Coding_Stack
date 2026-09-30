# AI Coding Stack Guide: Natural Language Playbook

A practical guide on **when** and **how** to use the skills and tools in this repository with **any AI model** (Claude, Gemini, GPT-4o, DeepSeek, Ollama) and **any AI IDE/Agent** (Cursor, Antigravity, Windsurf, Claude Code, Roo/Cline, VS Code).

> **Zero CLI Friction Principle**: Developers do **not** need to memorize or run CLI commands. Simply speak in natural language to your AI coding agent in the chat bar—the AI automatically activates the right skills and runs the underlying scripts for you.

---

## ⚡ Quick Prompt Cheat Sheet

| You Say (Natural Language)                                   | Skill Activated                         | What the AI Does Under the Hood                                                                                                    |
| :----------------------------------------------------------- | :-------------------------------------- | :--------------------------------------------------------------------------------------------------------------------------------- |
| _"Let's build feature X"_ or _"Add endpoint Y"_              | `repo-symbol-map`<br>`tdd-verification` | Takes a checkpoint, queries the 2KB AST symbol map, writes code + co-located tests, and runs `pytest`.                             |
| _"Save a checkpoint"_ or _"Take a snapshot"_                 | `snapshot-rollback`                     | Automatically runs `snapshot.py save` to freeze the current codebase state.                                                        |
| _"Undo the last change"_ or _"Revert to earlier checkpoint"_ | `snapshot-rollback`                     | Automatically runs `snapshot.py rollback` to restore previous files without Git.                                                   |
| _"Fix this error / stack trace: <paste>"_                    | `debugger-hotfix`                       | Sanitizes log, runs 3-Tier diagnostic (structure → config → code), writes a reproducing test, and fixes it.                        |
| _"Our chat is getting long, compact the state"_              | `context-hygiene`                       | Runs `context_compact.py` to write `.ai/session_summary.md`, letting you start a clean turn with zero lost context.                |
| _"Define the data model / API schema for X"_                 | `api-contracts`                         | Writes Pydantic/TS interfaces and verifies `@property` consistency via `contract_checker.py`.                                      |
| _"Make this UI look modern / polish the design"_             | `ui-design-system`                      | Implements vibrant dark mode, glassmorphism, responsive CSS, and micro-animations.                                                 |
| _"Create container / K8s manifests for this app"_            | `podman-k8s-devops`                     | Writes rootless `Containerfile` (`:Z` mounts), multi-stage builds (`USER 10001`), and K8s manifests with resource limits & probes. |
| _"Run a security check / audit for vulnerabilities"_         | `owasp-security-guard`                  | Audits code for OWASP Top 10 vulnerabilities, raw SQL injections, exposed credentials, and runs `security_check.py`.               |

---

## 📖 Deep Dive: The 8 Skills

---

### 1. `snapshot-rollback` (Git-Free Undo Engine)

#### When to Use:

- **Before the first task on a new project, once Step 0/1 are confirmed and
  before any proposal is applied.** This baseline is what every later rollback
  ultimately falls back to, and it is what you diff against to confirm the AI
  never touched files outside its task.
- Before asking the AI to do a risky or large multi-file refactoring.
- When you want to experiment with an idea and keep a safety net.
- When the AI generates code you don't like and you want an instant undo.

#### Example Prompts:

> _"Take a baseline snapshot before we start the first task."_  
> _"Take a checkpoint before we refactor the database layer."_  
> _"What changed since our last snapshot?"_  
> _"Revert the codebase to the state before we started editing auth."_

#### What Happens Under the Hood:

The AI automatically executes `python scripts/snapshot.py save/diff/rollback`. It tracks all files in `.ai/snapshots/`, removing any unwanted files the AI created and restoring modified files.

---

### 2. `repo-symbol-map` (Low-Token Codebase Discovery)

#### When to Use:

- When starting a task in a large codebase or asking how components connect.
- When you want the AI to understand dependencies without burning thousands of tokens reading every file.

#### Example Prompts:

> _"Give me a quick architectural overview of this repo."_  
> _"Where is the user authentication flow defined and what methods does it expose?"_

#### What Happens Under the Hood:

The AI runs `python scripts/symbol_mapper.py` to inspect a compact **~2KB AST overview** of all classes, `@properties`, method signatures, and exported types across the project for **<500 tokens**.

---

### 3. `tdd-verification` (Test-Driven Quality Guard)

#### When to Use:

- Every time you build a feature, endpoint, or business logic.

#### Example Prompts:

> _"Implement the user registration endpoint with rate limiting."_  
> _"Add the discount calculation logic for annual subscriptions."_

#### What Happens Under the Hood:

1. The AI pairs the source file with a co-located test file (e.g. `src/discount.py` ↔ `tests/test_discount.py`).
2. It tests 3 required scenarios: **Happy path**, **Error path**, and **Edge cases (empty/null/bounds)**.
3. It automatically runs the test runner (`pytest` / `npm test`) to confirm tests pass before telling you it's done.

---

### 4. `debugger-hotfix` (3-Tier Root Cause Diagnosis)

#### When to Use:

- Whenever you hit a bug, test failure, compiler warning, or runtime crash.

#### Example Prompts:

> _"I'm getting this error when running the dev server: <paste error>"_  
> _"The login test is failing with a 401 Unauthorized, figure out why."_

#### What Happens Under the Hood:

1. **Tier A (Structure Audit)**: Checks if files, entrypoints, or assets are in the wrong folder.
2. **Tier B (Config Audit)**: Checks if dependencies, ports, or environment variables are missing.
3. **Tier C (Logic Audit)**: Inspects code algorithms only after Tiers A & B pass.
4. Writes a minimal test reproducing the error, fixes the root cause, and re-runs the test suite.

---

### 5. `context-hygiene` (Context Compaction & Token Saver)

#### When to Use:

- When your chat session has reached 15+ turns and responses feel slower or cluttered.
- Before switching to an entirely different phase or feature.

#### Example Prompts:

> _"Summarize our session context so we can start a fresh chat."_  
> _"Compact our state and list what we finished and what's next."_

#### What Happens Under the Hood:

The AI runs `python scripts/context_compact.py` to produce `.ai/session_summary.md` (<500 tokens). In a fresh conversation tab, the AI reads this single file and instantly has 100% working memory.

---

### 6. `podman-k8s-devops` (Container & Cloud-Native Parity)

#### When to Use:

- When building files under `infrastructure/` — `Containerfile`, `compose.yaml`, or the Helm chart.

#### Example Prompts:

> _"Create a Containerfile and compose.yaml under infrastructure/ for local development."_  
> _"Generate production Kubernetes Deployment and Service manifests for this service."_

#### What Happens Under the Hood:

- **Local Dev (Podman)**: Configures rootless settings, `:Z` volume mounts for live reload, and unprivileged ports.
- **Production (K8s)**: Generates multi-stage minimal images (`USER 10001`), explicit CPU/memory `requests` & `limits`, `livenessProbe` / `readinessProbe`, and non-root security contexts.

---

### 7. `api-contracts` (Schema-First & Interface Integrity)

#### When to Use:

- When creating data models, database schemas, or API routes.

#### Example Prompts:

> _"Design the Pydantic models and request schemas for our billing service."_  
> _"Check the repo to ensure there are no @property function call bugs."_

#### What Happens Under the Hood:

The AI defines strict Pydantic / TypeScript types and runs `scripts/contract_checker.py` to ensure Python `@property` attributes are never called with parentheses `()`.

---

### 8. `ui-design-system` (Production-Grade Modern UI)

#### When to Use:

- When building frontend pages, components, dashboards, or CSS styles.

#### Example Prompts:

> _"Build a modern analytics dashboard page in dark mode."_  
> _"Style this settings form with glassmorphism and smooth hover effects."_

#### What Happens Under the Hood:

The AI applies curated dark themes (`#0B0F19`), translucent card glassmorphism, responsive CSS Grid/Flexbox, and micro-animations instead of basic plain HTML.

---

### 9. `owasp-security-guard` (OWASP Top 10 Hardening & Static Audit)

#### When to Use:

- When implementing authentication, user inputs, database queries, or doing pre-commit security reviews.

#### Example Prompts:

> _"Run a security check on the codebase for OWASP vulnerabilities."_  
> _"Review this auth endpoint for potential SQL injection or broken access control."_

#### What Happens Under the Hood:

The AI reviews code against the OWASP Top 10 (parameterized queries, IDOR checks, bcrypt password hashing, path traversal guards) and executes `python scripts/security_check.py` to detect hardcoded secrets and injection vulnerabilities.

---

## 🏛️ The Four Principles (Always Active)

Regardless of which skill is used, the AI adheres to **The Four Principles**:

1. **Think Before Coding**: State assumptions, push back if overcomplicated, stop when confused.
2. **Simplicity First**: Minimum code that solves the problem. No single-use abstractions.
3. **Surgical Changes**: Touch only what's asked. Clean up own orphans. Match existing style.
4. **Goal-Driven Execution**: Define criteria and loop until automated tests pass.

---

## 🔧 Set Up Your Chat Tool (Do This Once)

The scripts never talk to an AI model. Your chat tool (Claude Code, Cline, Continue, Copilot Chat and so on) does, and it decides what the AI may run. Two settings matter:

1. **Ask before running commands.** The validator only checks the commands the AI writes into its proposal. It cannot see commands the chat tool runs on its own. Turn on "ask before running a command" in your chat tool, and leave automatic approval off for terminal commands.
2. **Give local models enough context space.** Every request starts with a rules card of about 3 KB (roughly 800 tokens), and the AI then reads `AGENTS.md` and skill files as it works. If the model's context window is too small, the start of the prompt (where the rules are) is silently dropped. Many Ollama versions default to a small window, so set it explicitly, for example `PARAMETER num_ctx 16384` in a Modelfile, and check the real limit of your model (including internally hosted ones such as Gemma). Claude on Bedrock needs no change here.

Skills are found through the "Read the file first when..." table on the rules card, so this works even in tools that do not discover `.agents/skills/` on their own.

---

## 🛠️ (Optional) Direct CLI Reference

_For developers or CI scripts that prefer running commands directly in the terminal:_

```bash
# Snapshots (Git-free)
python scripts/snapshot.py save "my-checkpoint"
python scripts/snapshot.py rollback
python scripts/snapshot.py list
python scripts/snapshot.py diff

# Symbol Map
python scripts/symbol_mapper.py

# Context Compaction
python scripts/context_compact.py --goal "Active feature description"

# Contract Verification
python scripts/contract_checker.py --extract
python scripts/contract_checker.py --check

# Security & Secret Scanner
python scripts/security_check.py

# Who changed what (task, file, changed lines, functions)
python scripts/traceability.py --task TASK-001
python scripts/traceability.py --file backend/app/main.py
python scripts/traceability.py --function create_order

# Human approval of the plan (the AI never runs these): once after reviewing
# .ai/plan.json, and again for a task whose allowed_files grew later
python scripts/approve_plan.py --all
python scripts/approve_plan.py TASK-001

# Test Suite
python -m pytest tests/ -v
```
