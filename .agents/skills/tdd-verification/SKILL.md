---
name: tdd-verification
description: >-
  Test-Driven Development and verification skill. Enforces co-located unit tests,
  explicit typing, scoped loggers, >=80% coverage, and automated test suite execution.
---

# TDD Verification Skill

Use this skill when implementing new features, modifying business logic, or writing unit tests.

---

## 1. Co-Located Test Pairing

Every new or modified source file must have a corresponding test file:

- Python: `src/services/auth_service.py` ↔ `tests/test_auth_service.py`
- TypeScript: `src/components/Button.tsx` ↔ `src/components/Button.test.tsx`

---

## 2. Test Coverage Rules (The 3 Scenarios)

Derive these scenarios from the task's requirements and acceptance criteria in
`.ai/plan.json`, not from guessing — each acceptance criterion needs at least one test
that proves it. Every public function or endpoint must test at least three scenarios:

1. **Happy Path**: Expected input returns expected output.
2. **Error / Exception Path**: Invalid input raises the expected error (e.g. `pytest.raises(ValueError)`).
3. **Edge Case**: Boundary conditions (empty list, `None`, 0, maximum string length).

Do not add a test that doesn't trace to a requirement or a real failure mode just to pad
the coverage number.

---

## 3. Code Standards Checklist

Before declaring code complete, check `.agents/rules/code-standards.md`
(explicit types, scoped logger and never raw `print`, specific exceptions and no
silent returns, imports, config, coverage) and:

- [ ] **Anti-Stub**: No `pass`, `// TODO`, or dummy placeholder functions.

---

## 4. Immediate Automated Verification

Run the `tests.command` value from `.aistack/config/config.yaml`. Do not substitute
your own test command.

_Never declare a task done without verifying that tests pass._
