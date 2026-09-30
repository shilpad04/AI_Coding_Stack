# Universal Multi-Agent AI Coding Stack & Vibe-Coding Guardrails

> A high-performance, container-native AI pair-programming repository template equipped with **The Four Principles**, **progressive on-demand skills**, **Git-free local snapshots**, **AST codebase symbol mapping**, and **deterministic safety verification**.

---

## 🌐 100% Model & IDE Agnostic

This repository is built with **zero proprietary lock-in**. It works seamlessly across any AI model and any developer environment:

- **Any AI Model**: Claude 3.5/3.7 Sonnet, Gemini 2.5/1.5 Pro, GPT-4o, DeepSeek-V3/R1, Qwen2.5-Coder, local Ollama, or Amazon Bedrock.
- **Any AI IDE / Agent Interface**: 
  - **Antigravity IDE** (`.agents/skills/`, `.agents/rules/`)
  - **Cursor** (`.cursor/rules/`, `.cursorrules`, `.mdc`)
  - **Windsurf / Cascade** (`rules.md`, `STACK_GUIDE.md`)
  - **Claude Code** (`CLAUDE.md`, CLI tools)
  - **Roo-Code / Cline** (`.clinerules`, `.roomodes`)
  - **Aider / OpenHands** (pure Python CLI & repo tools)
  - **Standard VS Code / JetBrains / Terminal**

---

## 🏛️ System Architecture

```
                                  ┌──────────────────────────────────────────────┐
                                  │      DEVELOPER (Natural Language Vibe Chat)  │
                                  └──────────────────────┬───────────────────────┘
                                                         │
                                                         ▼
                                  ┌──────────────────────────────────────────────┐
                                  │      AI CODING AGENT / IDE                   │
                                  │  (Cursor, Antigravity, Windsurf, Claude, etc.)│
                                  │  - Guided by The Four Principles             │
                                  │  - Zero CLI friction: auto-runs tools        │
                                  └──────────────────────┬───────────────────────┘
                                                         │ (On-Demand Progressive Activation)
         ┌──────────────────────────────┬────────────────┴──────────────┬──────────────────────────────┐
         ▼                              ▼                               ▼                              ▼
┌─────────────────┐           ┌───────────────────┐           ┌──────────────────┐           ┌──────────────────┐
│  VERIFICATION   │           │    ARCHITECTURE   │           │     CONTAINER    │           │    REVERSIBILITY │
│    & QUALITY    │           │   & CONTEXT MAP   │           │   & ENVIRONMENT  │           │   & EXPERIMENT   │
├─────────────────┤           ├───────────────────┤           ├──────────────────┤           ├──────────────────┤
│• tdd-verification│          │• repo-symbol-map  │           │• podman-k8s-devops│          │• snapshot-rollback│
│• debugger-hotfix│           │• api-contracts    │           │• ui-design-system│           │• context-hygiene │
└─────────────────┘           └───────────────────┘           └──────────────────┘           └──────────────────┘
```

---

## 📖 Key Documentation

- 📘 **[STACK_GUIDE.md](STACK_GUIDE.md)**: The **Natural Language Playbook** for developers (how to prompt the AI, when each skill activates, and zero CLI friction guidelines).
- 📜 **[principles.md](.agents/rules/principles.md)**: **The Four Principles** (*Think Before Coding*, *Simplicity First*, *Surgical Changes*, *Goal-Driven Execution*).
- 🔒 **[rules.md](rules.md)**: Scope boundaries, the rules the validator enforces, and the structure and database rules.
- 🧱 **[code-standards.md](.agents/rules/code-standards.md)**: Typing, scoped logging, error handling, imports, config, testing, and coverage.
- 📋 **[AGENTS.md](AGENTS.md)**: Phase protocol and agent role boundaries.

---

## 🧰 Progressive Skills Suite (`.agents/skills/`)

Skills use standard markdown with YAML frontmatter, loading into the AI's working memory **only when needed** to keep token costs low:

1. **`snapshot-rollback`**: Git-free local snapshots and 1-command rollback in `.ai/snapshots/`.
2. **`podman-k8s-devops`**: Rootless Podman local dev (`Containerfile`, `:Z` mounts) + minimal multi-stage builds (`USER 10001`) + production Kubernetes manifests.
3. **`repo-symbol-map`**: AST-based symbol map providing whole-repo architectural context in ~2KB (<500 tokens).
4. **`context-hygiene`**: Distills state into `.ai/session_summary.md` (<500 tokens) to reset cluttered conversation memory without lost progress.
5. **`tdd-verification`**: Co-located unit testing (`src/` ↔ `tests/`), strict typing, scoped logging, and automated test execution.
6. **`debugger-hotfix`**: 3-Tier diagnostic protocol (Structure → Config → Logic) and reproducing bugs with failing tests.
7. **`api-contracts`**: Schema-first modeling (Pydantic / TypeScript) and AST `@property` consistency checks.
8. **`ui-design-system`**: Vibrant dark mode, glassmorphism, responsive CSS (Flex/Grid), and micro-animations.
9. **`owasp-security-guard`**: OWASP Top 10 hardening (parameterized queries, IDOR checks, bcrypt password hashing) and static secret scanning.

---

## ⚙️ Core Utilities (`scripts/`)

Plain Python scripts with no heavy dependencies (`validate_proposal.py` needs PyYAML):

| Script | Command | Purpose |
| :--- | :--- | :--- |
| **`snapshot.py`** | `python scripts/snapshot.py [save\|rollback\|list\|diff]` | Git-free local checkpoint and rollback manager. |
| **`symbol_mapper.py`** | `python scripts/symbol_mapper.py` | AST repository symbol extractor emitting ~2KB map. |
| **`log_sanitizer.py`** | `python scripts/log_sanitizer.py <log>` | Head/Tail log trimmer to prevent prompt token explosion. |
| **`contract_checker.py`** | `python scripts/contract_checker.py [--extract\|--check]` | AST model contract extractor and `@property` call checker. |
| **`context_compact.py`** | `python scripts/context_compact.py [--goal <goal>]` | Session state compactor emitting `.ai/session_summary.md`. |
| **`security_check.py`** | `python scripts/security_check.py [--path <dir>]` | Static secret and OWASP vulnerability scanner. |
| **`validate_proposal.py`**| `python scripts/validate_proposal.py <proposal>` | 0-token deterministic policy gatekeeper. |
| **`traceability.py`** | `python scripts/traceability.py [--task\|--file\|--function]` | Audit log: which task changed which file, lines and functions. |
| **`approve_plan.py`** | `python scripts/approve_plan.py <TASK_ID>` | Human sign-off when a task's `allowed_files` widens past its approved baseline. |

---

## 📁 Repository Structure

```
.
├── .agents/
│   ├── rules/
│   │   ├── principles.md         # The Four Principles core rule
│   │   └── code-standards.md     # Typing, logging, errors, imports, config, testing
│   └── skills/                   # Progressive skills suite (universal markdown)
│       ├── api-contracts/
│       ├── context-hygiene/
│       ├── debugger-hotfix/
│       ├── owasp-security-guard/
│       ├── podman-k8s-devops/
│       ├── repo-symbol-map/
│       ├── snapshot-rollback/
│       ├── tdd-verification/
│       └── ui-design-system/
├── .ai/                          # Plan state, contracts.json, snapshots
├── config/                       # Package & command whitelists
├── scripts/                      # Core Python tooling suite
├── specs/                        # Feature specifications
├── tests/                        # Automated unit & governance test suite
├── AGENTS.md                     # Agent roles & workflow protocol
├── rules.md                      # Engineering standards & scope discipline
├── context.md                    # Project context & conventions
├── STACK_GUIDE.md                # Natural Language Playbook & user guide
└── README.md                     # Repository overview
```

---

## 🧪 Running the Test Suite

```bash
# Run all unit and governance tests
python -m pytest tests/ -v
```
