# Code Quality Standards

Read this before writing or changing any code.

- **Standards Apply to Changed Lines**: The standards below apply to lines you
  change, not to whole files you open. Pre-existing code that does not meet them
  is logged, not fixed.

> These principles apply to every language supported by the pipeline.

## Type Safety

- All functions and methods must declare parameter types and return types explicitly.
- Avoid `any` / untyped / dynamic types unless explicitly justified in a comment.
- No implicit null/None returns — be explicit about every return path.

## Logging & Debugging

- Every module must set up a named logger scoped to that module (e.g. `logger = logging.getLogger(__name__)`).
- Log levels: `INFO` for state changes, `DEBUG` for data values, `ERROR` for exceptions only.
- Every log must include relevant context (e.g. entity IDs, operation names).
- Never fail silently — always log or raise exceptions.

## Error Handling

- Catch specific exceptions — never catch-all bare `except:` or `catch (e)`.
- Document what each exception handling branch means in a comment.
- Re-raise with context if the error cannot be handled locally.

## Dependencies & Imports

- All imports must be at the top of the file — no lazy or conditional imports.
- No wildcard imports (`from module import *`).
- Every dependency must be pinned to a version range with a comment explaining why it is needed.
- Check `.aistack/config/approved-packages.yaml` before adding any new dependency.

## Configuration

- All config must be loaded via environment variables or externalized YAML/JSON configs.
- Use `.env.example` to document every variable, type, and default value.
- No hardcoded URLs, API keys, or absolute file paths in source code.
- Fail fast at startup if a required configuration variable is missing.

## Testing & Coverage

- Every public function needs at least one unit test.
- Tests must cover: happy path, at least one error case, and edge cases (empty input, null, max value).
- **PRD Traceability**: When implementing or changing PRD-driven functionality, derive
  tests from the task's requirements and acceptance criteria in `.ai/plan.json` — each
  acceptance criterion needs at least one test proving it. A test that does not trace to
  a requirement or a real edge/failure case does not count toward coverage; do not write
  one just to raise the number. The validator enforces the minimum: a proposal that changes
  source files without any test file fails (`RULE-TEST-001`), and a plan task with no
  acceptance criterion fails (`RULE-PLAN-002`).
- Test behavior, not implementation details — avoid mocking internal private helpers.
- **Coverage Requirement**:
  - Files you create or change in a task must reach **80% coverage**.
  - Repo-wide coverage must not go **down** compared to before the task.
  - Inherited files you did not touch are exempt. Do not write tests for them
    to lift the number.
- Test file naming must mirror source file naming (e.g., `user_service.py` -> `test_user_service.py`).
- Machine-generated code (any `**/generated/` folder) is excluded from the
  coverage denominator and must never be hand-edited or unit-tested directly.
  Test the wrapper around it instead. See `context.md` for where these folders
  live.

### Turning on the 80% coverage requirement

Nothing in this stack measures coverage for you — it is enforced by running
your project's own test command with coverage turned on, per `context.md`'s
Build/Run Commands table, and reading the report it prints. Use whichever of
these matches your stack; none of them are new dependencies to approve:

- **Python (pytest)**: `pytest-cov` is already on `.aistack/config/approved-packages.yaml`.
  Run `pytest --cov=<package> --cov-report=term-missing --cov-fail-under=80`.
- **Node (Jest)**: coverage is built into Jest. Run `jest --coverage` and add
  `coverageThreshold: { global: { lines: 80 } }` to `jest.config.js`.
- **Node (Vitest)**: coverage is built into Vitest. Run `vitest run --coverage`
  and set `test.coverage.thresholds.lines: 80` in `vite.config.ts`.
- **Java (Maven/Gradle)**: add the JaCoCo plugin (the standard Java coverage
  tool) to `pom.xml` or `build.gradle` with a `<rule>`/`violationRules` line
  requiring 80% line coverage, then run `mvn verify` or `gradle check`.
- **.NET**: `dotnet test --collect:"XPlat Code Coverage"` using the
  `coverlet.collector` package most `dotnet new` test projects already include;
  check the result with `reportgenerator` or your CI's coverage gate.
- **Flutter**: `flutter test --coverage` writes `coverage/lcov.info`; check it
  against 80% with `lcov --summary coverage/lcov.info` or an equivalent CI step.
