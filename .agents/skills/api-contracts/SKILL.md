---
name: api-contracts
description: >-
  API contract design and AST interface integrity skill. Enforces schema-first types
  (Pydantic/TypeScript), records contracts to .ai/contracts.json, and prevents signature drift.
---

# API Contracts & Interface Integrity Skill

Use this skill when designing data models, backend API routes, or frontend request/response types.

---

## 1. Schema-First Modeling

Always define explicit request/response schemas before writing business logic or route handlers:

- **Python**: Use Pydantic `BaseModel` or dataclasses with strict types:
  ```python
  from pydantic import BaseModel, Field

  class UserCreateRequest(BaseModel):
      username: str = Field(..., min_length=3, max_length=50)
      email: str = Field(..., pattern=r"^[\w\.-]+@[\w\.-]+\.\w+$")
  ```
- **TypeScript**: Use strict interfaces with exact optionality:
  ```typescript
  export interface UserCreateRequest {
    username: string;
    email: string;
  }
  ```

---

## 2. Preventing Contract & @property Drift

- **The `@property` Rule**: In Python models, never invoke `@property` attributes with parentheses `()`. Always access them as attributes `model.is_active` (NOT `model.is_active()`).
- **Contract Verification Tool**:
  ```bash
  # Extract current workspace model contracts
  python .aistack/scripts/contract_checker.py --extract

  # Check for contract violations in codebase
  python .aistack/scripts/contract_checker.py --check
  ```
