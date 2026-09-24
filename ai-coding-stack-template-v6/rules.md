# AI Coding Governance Rules & Engineering Standards

## Scope Discipline (All Tasks)

- **Change Trace and Simplicity**: see principles 2 and 3 in
  `.agents/rules/principles.md`. Whether the coding standards apply to changed
  lines only is in `.agents/rules/code-standards.md`.
- **Spec Lock**: If it is not in `specs/spec.md`, it is out of scope. Do not add
  features, refactor, or fix unrelated bugs.
- **Red Flags** (pause and ask):
  - Touching multiple unrelated directories.
  - Refactoring code unrelated to the task.
  - Creating new files/folders not in `specs/spec.md` or `.ai/plan.json`.
  - "While I'm here" modifications.
- **Unrelated Bugs**: Log as a separate issue; do NOT fix inline.
- **Scope Creep Detector**: If changes exceed 2x estimated lines in `spec.md`, stop and ask before continuing.

---

## Enforced Rules (what the validator actually blocks)

These are checked by `scripts/validate_proposal.py`. Nothing else in this file
is machine-checked.

| Rule                     | Fires when                                                                        | Result      |
| ------------------------ | --------------------------------------------------------------------------------- | ----------- |
| `RULE-SCOPE-001`         | A file in the proposal is not in the task's `allowed_files`                       | FAIL        |
| `RULE-SCOPE-002`         | What landed on disk does not match the approved proposal                          | FAIL        |
| `RULE-GOV-001`           | The proposal touches a protected governance file                                  | ASK         |
| `RULE-DEP-001`           | A package, import, or a dependency declared in a manifest file (`package.json`, `requirements.txt`, `pyproject.toml`, `pom.xml`, `build.gradle`, `.csproj`, `packages.config`, `pubspec.yaml`) is not on the approved list | FAIL |
| `RULE-DEP-002`           | Same, but the dependency is approved and flagged as needing human sign-off        | ASK         |
| `RULE-SEC-001`           | A file looks like it contains a hardcoded secret, a connection string with embedded credentials, or a cloud/Slack/JWT token | FAIL |
| `RULE-CODE-001`          | A file has placeholder text, is not valid Python, an entry is malformed or empty, or a manifest file could not be parsed | FAIL |
| `RULE-ASSUME-001`        | A required decision was never stated, or the proposal asks for clarification      | ASK         |
| `RULE-EXEC-001` to `004` | A command matches a blocked or approval-required pattern in `command-policy.yaml`, contains `$( )`/backticks, or contains a redirect (`>` or `<`) | FAIL or ASK |
| `RULE-PLAN-001`          | A task has no human-approved baseline in `.ai/plan-approval.json` yet, or its `allowed_files` in `.ai/plan.json` grew past it | ASK — a human runs `python scripts/approve_plan.py <TASK_ID>` (or `--all`) |
| `RULE-PLAN-002`          | A task in `.ai/plan.json` has no non-blank acceptance criterion                   | FAIL        |
| `RULE-TEST-001`          | A proposal changes source files (`.py .ts .tsx .js .jsx .java .cs .dart`, not config/types/migrations/generated) but includes no test file. On by default; `governance.require_tests_with_code: false` in `config.yaml` turns it off | FAIL |
| `RULE-DB-001`            | One proposal has both a migration file (under `migrations/` or `alembic/`) and feature source code. ORM model files (`models/`, `entities/`, `models.py`, `*.model.ts`, `*.entity.ts`) and tests may go with the migration | FAIL |
| `RULE-DB-002`            | A non-Markdown file uses ORM auto-create/sync: `create_all(`, `synchronize: true`, `sequelize.sync(`, or `prisma db push` | FAIL |
| *(no rule ID — orchestration, not a validator)* | The same task fails Gate 1 `governance.max_repair_attempts` times in a row (`config.yaml`, currently 2) | ASK instead of FAIL, so a human looks before another attempt |

FAIL means fix it and re-run. ASK means stop and wait for a human.

Everything else below is a standard you are expected to follow. It is not
checked automatically, so following it is on you.

---

### Protected Governance Rule (RULE-GOV-001)

These exact files are protected. Touching any of them returns ASK (exit 2) and
halts until a human approves:

- `config/approved-packages.yaml`
- `config/command-policy.yaml`
- `config/config.yaml`
- `scripts/validate_proposal.py`
- `scripts/validators/__init__.py`
- `scripts/approve_plan.py`
- `.ai/plan-approval.json`
- `AGENTS.md`
- `rules.md`
- `context.md`
- `CLAUDE.md`

The list is exact filenames, not folders. A new file added under `config/` or
`scripts/` is **not** protected until it is added to
`PROTECTED_GOVERNANCE_FILES` in `scripts/validators/__init__.py`.

Never modify a protected file inside a normal task proposal. Only when the
human explicitly asks for a governance change.

---

## Ambiguity Policy (All Tasks)

- **Missing Elements Trigger Clarification**:
  - No error case specified.
  - No test cases provided.
  - Unclear expected behavior.
  - Missing success/failure criteria.
- **Assumption Veto** — Ask before proceeding on:
  - Framework/library default behavior.
  - Authentication/authorization flows.
  - Data validation rules.
  - Error recovery (retry? fail? fallback?).
  - Edge cases (empty input, null/None, max values).
- **Clarification Format**: Provide 2-3 interpretations of unclear requirements and ask which applies.
- **No Silent Assumptions**: Every assumption must be documented in a code comment or in `specs/spec.md`.

---

## Forbidden Actions

- **Deployment files are written, never executed.** The agent may create or edit
  `Containerfile`, compose files, Kubernetes manifests and Helm charts when a
  task asks for it. They live in `infrastructure/`.
- **The agent never runs a deployment or build command.** No `docker build`,
  `podman build`, `docker compose up`, `kubectl`, `helm`, or `terraform`. Write
  the file, then hand the exact command to the human to run. Do not run it and
  do not offer to.
- After writing deployment files, state plainly what the human should run and in
  what order. Stop there.
- Production secrets are never written into any file. Deployment files reference
  environment variables and nothing else.
- Do not install new dependencies without checking `config/approved-packages.yaml`.
- Do not generate code that cannot be explained.
- Do not silently expand scope.
- Do not fabricate unverified APIs, imports, endpoints, package names, or behavior.
- Do not hide uncertainty behind confident wording.
- Do not fix unrelated bugs or refactor code outside task scope.
- Do not make "optimizations" or "improvements" without explicit approval.

---

## Code Quality Standards

These are binding and live in `.agents/rules/code-standards.md`: typing, logging,
error handling, imports, configuration, testing, and the 80% coverage
requirement. Read that file before writing or changing code.

---

## Project Structure & Layering

> Folder layout is defined in `context.md` and is binding.

### RULE-STRUCT-001 — One-way layering

`route/endpoint → service → repository → database`.
An endpoint never queries the database. A repository never holds business logic.
A service never touches the HTTP request or response.

### RULE-STRUCT-002 — Never return a database model over HTTP

Endpoints return a schema or DTO, never a SQLAlchemy model or Mongoose/TypeORM
document. Returning the model leaks password hashes, audit columns and PII to
the client. This is a security failure, not a style preference.

---

## Database & Schema

### RULE-DB-001 — A schema change is its own task

Adding, altering or dropping a column, table or index is a separate task with
its own migration file. Never bundle a schema change into a feature task. If a
feature needs a schema change, that is two tasks, and the migration goes first.

### RULE-DB-002 — Never auto-create schema

No ORM auto-create or auto-sync in any environment. Not
`Base.metadata.create_all`, not `synchronize: true`, not `sync()`. Schema comes
from migration files only, so every change is reviewable and repeatable.

### RULE-DB-003 — Migrations are not covered by rollback

`scripts/snapshot.py` restores files. It cannot undo a migration that has
already run. Once a migration is applied, rolling back is manual. Treat any
migration task as one-way and get human approval before running it.
