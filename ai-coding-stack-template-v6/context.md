# Project Context & Infrastructure Configuration

---

## Tech Stack

- **Languages**: [Fill In]
- **Frameworks / libraries**: [Fill In]
- **Databases / storage**: [Fill In]
- **Infra / deployment targets**: [Fill In]
- **Domain focus**: [Fill In]

---

### Build / Run Commands

- **Setup**: [Fill In]
- **Run locally**: [Fill In] 
- **Tests**: [Fill In]
- **Lint / type-check**: [Fill In]

Pick the row for each side and join the two with `&&`. Drop the side that is `none`.
The stack ships `python -m pytest -q`, which runs its **own** tests — change it.

| Frontend  | Tests                        | Lint                                                         |
| --------- | ---------------------------- | ------------------------------------------------------------ |
| `react`   | `npm test --prefix frontend` | `npm run lint --prefix frontend && tsc --noEmit -p frontend` |
| `angular` | `npm test --prefix frontend` | `npm run lint --prefix frontend && tsc --noEmit -p frontend` |

| Backend   | Tests                         | Lint                                                       |
| --------- | ----------------------------- | ---------------------------------------------------------- |
| `express` | `npm test --prefix backend`   | `npm run lint --prefix backend && tsc --noEmit -p backend` |
| `fastapi` | `python -m pytest -q backend` | `mypy --strict backend/app`                                |

---

## Repo / Folder Conventions

Set these before Step 1. The plan locks file paths, so the layout is decided first.

- **Frontend**: [Fill In]
- **Backend**: [Fill In]
- **Capabilities**: [Fill In]
- **Language**: [Fill In]

If a side is `none`, its folder does not exist. The other side keeps its folder
name — a backend-only project still puts code in `backend/`, not at the root.

**Reserved at root:** `scripts/ tests/ config/ specs/` belong to the stack.
Project scripts go in `ops/`. Project tests go inside `frontend/` and `backend/`.

**Root:** `frontend/  backend/  docs/  ops/  infrastructure/`

**frontend/ — React** — entry `src/main.tsx`, tests alongside as `*.test.tsx`

```
src/  assets components pages layouts features hooks services store routes types utils styles
```

**frontend/ — Angular** — entry `src/main.ts`, tests alongside as `*.spec.ts`

```
src/  app/{core shared features layouts store}  assets environments styles
```

**backend/ — Express** — entry `src/index.ts`

```
src/  config middleware routes controllers services repositories models validators modules utils
      migrations/  tests/{unit,integration}
```

**backend/ — FastAPI** — entry `app/main.py`

```
app/  core api/v1/endpoints models schemas services repositories middleware db modules utils
      alembic/  tests/{unit,integration}
```

### Notes

- Include only what your capabilities need. `db` → Express: models, repositories, migrations. FastAPI: models, repositories, db/, alembic/. `rest` → routes/controllers (Express) or api/ (FastAPI).
- Routes live under `/api/v1/`. One error shape, set once in middleware.
- Default to the flat folders. Use `modules/<name>/` only for a self-contained feature nothing outside it imports from.
- A shared `types/` package across frontend and backend is only possible when both sides are TypeScript. With a FastAPI backend the contract lives in OpenAPI instead.

- **Config / env files**: All secrets and environment values must be externalized. Use `.env.example` to document every variable and its default.
- **Shared docs**: `docs/` and `specs/` for project guidance and task planning. Keep repo-root files limited to team-level instructions and entry points.

---

### infrastructure/

Deployment files live here. Written by the agent, run by a human.

```
infrastructure/
  Containerfile              # one per deployable service
  compose.yaml               # local development only
  helm/
    Chart.yaml
    values.yaml              # defaults, no secrets
    values.<env>.yaml        # per-environment overrides
    templates/               # deployment.yaml, service.yaml, configmap.yaml
```

Rules:

- No secret values in any file here. Reference environment variables or a
  Kubernetes secret by name only.
- `values.yaml` holds defaults. Anything that differs per environment goes in a
  `values.<env>.yaml` override, never hardcoded in a template.
- One chart for the whole app. Do not create a separate chart per service unless
  the services deploy independently.

---

## Scope Discipline & Governance Locks

> **Locked Rules — Do Not Modify Without Approval**

1. **Spec Lock**: If it is not in `specs/spec.md`, it is out of scope.
2. **Protected Governance (`RULE-GOV-001`)**: see the exact file list in
   `rules.md`. `context.md` is on that list.
3. **Ambiguity Policy**: Clarify missing requirements rather than making silent assumptions.
