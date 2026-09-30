---
name: owasp-security-guard
description: >-
  Security audit and OWASP Top 10 hardening skill. Enforces secure coding practices:
  SQL injection prevention, input validation, secret detection, path traversal guards,
  XSS sanitation, secure authentication flows, and automated security scans.
---

# OWASP Security Guard & Hardening Skill

Use this skill when implementing authentication, handling user inputs, designing database queries, reviewing PRs for security vulnerabilities, or when asked to *"run a security check"*.

---

## 🛡️ The Complete OWASP Top 10 for AI Code Generation

### A01: Broken Access Control
- **Server-Side Authorization**: Never rely on client-side role checks. Always verify user permissions on the server before mutating or reading data.
- **IDOR Protection**: Verify that the authenticated `user_id` in the token matches the requested resource owner:
  ```python
  if document.owner_id != current_user.id and not current_user.is_admin:
      raise HTTPException(status_code=403, detail="Forbidden")
  ```
- **Deny by Default**: Lock down endpoints unless explicitly marked public. Disallow wildcard CORS (`*`) when credentials/cookies are enabled.

---

### A02: Cryptographic Failures
- **Zero Hardcoded Secrets**: Never commit API keys, database credentials, AWS keys, or JWT secrets in source code.
- **Environment Variables**: Load all secrets via `.env` (using `.env.example` as a template).
- **Password Hashing**: Use adaptive hashing algorithms (`bcrypt`, `argon2id`). Never use plain MD5 or SHA256 for passwords.
- **Enforce TLS**: Reject plain HTTP connections for sensitive endpoints.

---

### A03: Injection (SQL, Command, Template, Path)
- **SQL Injection**: **Always** use parameterized queries or ORMs (SQLAlchemy, Prisma, Django ORM). **Never** string-interpolate or format user input directly into queries (`f"SELECT * FROM users WHERE id = {user_id}"` is strictly forbidden).
- **Command Injection**: Never use `os.system()` or `subprocess.run(cmd, shell=True)` with user input. Always pass commands as argument lists: `subprocess.run(["ls", "-la", sanitized_dir], shell=False)`.
- **Path Traversal Guard**: Validate and resolve paths using `Path.resolve()`. Ensure the target stays inside the base directory:
  ```python
  base_dir = Path("/safe/upload/dir").resolve()
  target = (base_dir / user_filename).resolve()
  if not target.is_relative_to(base_dir):
      raise PermissionError("Path traversal attempt detected")
  ```

---

### A04: Insecure Design
- **Rate Limiting**: Apply rate limiting to all public authentication, password reset, and registration endpoints.
- **Account Lockout**: Implement temporary lockouts after repeated failed login attempts to prevent brute-force attacks.
- **Defense in Depth**: Validate inputs at the boundary (schema) and again at the domain/database layer.

---

### A05: Security Misconfiguration
- **Disable Debug in Production**: Ensure `DEBUG = False` in production environments.
- **Standard Security HTTP Headers**: Always configure defensive headers:
  ```
  Content-Security-Policy: default-src 'self'
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
  Strict-Transport-Security: max-age=31536000; includeSubDomains
  ```
- **Secure Cookies**: Always set `HttpOnly; Secure; SameSite=Strict` on session cookies.

---

### A06: Vulnerable and Outdated Components
- **Dependency Whitelist**: Verify all third-party dependencies against `.aistack/config/approved-packages.yaml`.
- **Pin Versions**: Pin dependencies to specific version ranges; remove unused dependencies to reduce attack surface.

---

### A07: Identification & Authentication Failures
- **Token Expiration**: Always enforce explicit expiration (`exp`) on JWT tokens and validate issuer/audience claims.
- **Session Invalidation**: Invalidate sessions and tokens server-side upon logout or password changes.
- **Prevent Session Fixation**: Issue a fresh session token upon successful authentication.

---

### A08: Software & Data Integrity Failures
- **Strict Payload Validation**: Validate incoming JSON payloads against strict schemas (Pydantic / Zod / TypeScript interfaces) with bounds on string length and value ranges.
- **No Unsafe Deserialization**: Never use `pickle.loads()` on untrusted input; use `yaml.safe_load()` instead of `yaml.load()`.
- **Webhook Signature Verification**: Verify HMAC signatures (e.g., Stripe, GitHub) using raw request bytes before processing webhooks.

---

### A09: Security Logging & Monitoring Failures
- **Log Security Events**: Log failed logins, authorization denials, and input validation failures using scoped loggers (`logger.warning`).
- **No PII or Secret Logging**: Never write passwords, credit card numbers, authorization headers, or private user data to logs.

---

### A10: Server-Side Request Forgery (SSRF)
- **Outgoing Request Restrictions**: If your backend fetches URLs provided by users, validate the scheme (`https://` only).
- **Block Private/Loopback IP Ranges**: Disallow requests resolving to `127.0.0.1`, `localhost`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, or cloud metadata endpoints (`169.254.169.254`).

---

## 🔍 Automated Local Security Scan

Run the static security scanner at any time:

```bash
python .aistack/scripts/security_check.py
```
*Checks the workspace for exposed secrets, raw SQL format strings, insecure `shell=True` subprocess calls, `eval()` usage, and dangerous innerHTML assignments.*
