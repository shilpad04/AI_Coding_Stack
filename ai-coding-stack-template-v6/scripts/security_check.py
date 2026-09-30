#!/usr/bin/env python3
"""
scripts/security_check.py — Static Security & OWASP Pre-Commit Scanner

Scans workspace files for common OWASP vulnerabilities, hardcoded secrets,
unsafe subprocess calls, raw SQL formatting, and injection vectors.

Usage:
    python scripts/security_check.py
    python scripts/security_check.py --path src/
"""

import os
import re
import sys
import argparse
from pathlib import Path
from typing import List, Dict, Any

IGNORE_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "node_modules",
    "dist", "build", ".pytest_cache", ".ai/snapshots", ".ai/backups",
    "coverage", ".mypy_cache", ".ruff_cache", ".gemini"
}

# ─── Secret & Vulnerability Detection Patterns ───
SECURITY_RULES = [
    {
        "id": "SEC-001",
        "name": "Hardcoded AWS Access Key",
        "pattern": re.compile(r"\b(AKIA[0-9A-Z]{16})\b"),
        "severity": "CRITICAL"
    },
    {
        "id": "SEC-002",
        "name": "Hardcoded Private Key Header",
        "pattern": re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
        "severity": "CRITICAL"
    },
    {
        "id": "SEC-003",
        "name": "Hardcoded API / Secret Token",
        "pattern": re.compile(r"""(?i)(?:api_key|apikey|secret_key|auth_token|client_secret)\s*[:=]\s*["'](?![$_A-Z0-9_]{2,})(?![<\[])[A-Za-z0-9_\-./+=]{16,}["']"""),
        "severity": "HIGH"
    },
    {
        "id": "SEC-004",
        "name": "Raw SQL Format / Concatenation",
        "pattern": re.compile(r"""(?:f["']SELECT\s+.*\{|f["']INSERT\s+.*\{|f["']UPDATE\s+.*\{|f["']DELETE\s+.*\{)""", re.I),
        "severity": "CRITICAL"
    },
    {
        "id": "SEC-005",
        "name": "Dangerous eval() or exec() Call",
        "pattern": re.compile(r"""\b(?:eval|exec)\s*\([^)]+\)"""),
        "severity": "HIGH"
    },
    {
        "id": "SEC-006",
        "name": "Insecure shell=True in subprocess",
        "pattern": re.compile(r"""subprocess\.(?:run|Popen|call|check_output)\s*\([^)]*shell\s*=\s*True[^)]*\)"""),
        "severity": "MEDIUM"
    },
    {
        "id": "SEC-007",
        "name": "Unsafe dangerouslySetInnerHTML in Frontend",
        "pattern": re.compile(r"""dangerouslySetInnerHTML\s*="""),
        "severity": "MEDIUM"
    }
]


def scan_file_security(file_path: Path, root: Path) -> List[Dict[str, Any]]:
    """Scan a single file against security rules."""
    findings = []
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return findings

    rel_path = file_path.relative_to(root).as_posix() if file_path.is_absolute() else str(file_path)

    for rule in SECURITY_RULES:
        for idx, line in enumerate(content.splitlines(), start=1):
            # Skip test mock data and comments if marked as safe
            if "# test-mock" in line.lower() or "# nosec" in line.lower():
                continue

            if rule["pattern"].search(line):
                # Ignore rule definition itself
                if "re.compile" in line:
                    continue
                findings.append({
                    "rule_id": rule["id"],
                    "rule_name": rule["name"],
                    "severity": rule["severity"],
                    "file": rel_path,
                    "line": idx,
                    "snippet": line.strip()[:100]
                })

    return findings


def scan_workspace_security(root: Path, target_dir: Path = None) -> List[Dict[str, Any]]:
    """Recursively scan all source files in workspace."""
    all_findings = []
    scan_root = target_dir if (target_dir and target_dir.exists()) else root

    for dirpath, dirnames, filenames in os.walk(scan_root):
        dirnames[:] = [
            d for d in sorted(dirnames)
            if d not in IGNORE_DIRS and not d.startswith(".")
        ]
        for f in sorted(filenames):
            # Skip tests containing mock security test data
            if "test_security_check" in f or "test_validators" in f or "validate_proposal.py" in f:
                continue
            ext = Path(f).suffix.lower()
            if ext in (".py", ".ts", ".tsx", ".js", ".jsx", ".yaml", ".yml", ".json", ".env"):
                fpath = Path(dirpath, f)
                all_findings.extend(scan_file_security(fpath, root))

    return all_findings


def main():
    parser = argparse.ArgumentParser(description="Static Security & OWASP Vulnerability Scanner")
    parser.add_argument("--path", "-p", type=str, default=None, help="Target directory or file to scan")
    args = parser.parse_args()

    root = Path.cwd()
    target = (root / args.path) if args.path else root

    print(f"\n[SECURITY] Scanning workspace for OWASP vulnerabilities and secrets...")
    findings = scan_workspace_security(root, target)

    if findings:
        print(f"\n[SECURITY] ❌ Found {len(findings)} potential security issue(s):\n")
        print(f"{'SEVERITY':<10} {'RULE ID':<10} {'LOCATION':<35} {'DETAILS'}")
        print("=" * 80)
        for f in findings:
            loc = f"{f['file']}:{f['line']}"
            print(f"{f['severity']:<10} {f['rule_id']:<10} {loc:<35} {f['rule_name']}")
            print(f"  Snippet: {f['snippet']}")
        print("=" * 80 + "\n")
        sys.exit(1)
    else:
        print("[SECURITY] ✅ Clean! No hardcoded secrets, SQL injections, or unsafe calls detected.\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
