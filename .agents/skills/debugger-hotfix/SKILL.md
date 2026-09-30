---
name: debugger-hotfix
description: >-
  Systematic debugging and hotfix skill. Follows the 3-Tier Diagnostic Protocol
  (Structure -> Config -> Logic), reproduces bugs with targeted tests, and fixes root causes.
---

# Debugger & Hotfix Skill

Use this skill when diagnosing errors, compiler warnings, stack traces, or unexpected test failures.

---

## The 3-Tier Diagnostic Protocol

Always diagnose bugs in this strict order to avoid rewriting working code prematurely:

```
┌────────────────────────────────────────────────────────┐
│ Tier A — Structural Audit                              │
│ Are files, imports, or entrypoints missing or misplaced│
└───────────────────────────┬────────────────────────────┘
                            │ (If structure is valid)
                            ▼
┌────────────────────────────────────────────────────────┐
│ Tier B — Configuration Audit                           │
│ Are dependencies, env vars, or configs missing?        │
└───────────────────────────┬────────────────────────────┘
                            │ (If config is valid)
                            ▼
┌────────────────────────────────────────────────────────┐
│ Tier C — Code Logic Audit                              │
│ Inspect internal algorithm, data types, or conditions  │
└────────────────────────────────────────────────────────┘
```

---

## Step-by-Step Hotfix Workflow

1. **Sanitize the Error Trace**:
   If the terminal output is massive, sanitize it to keep prompt tokens low:
   ```bash
   python .aistack/scripts/log_sanitizer.py error.log
   ```
2. **Reproduce with a Failing Test**:
   Write a minimal unit test that triggers the exact bug before touching production code.
3. **Execute the Fix**:
   Make surgical changes only to the files responsible for the failure.
4. **Verify Green**:
   Run the test runner to confirm the bug is resolved and no regressions occurred.
