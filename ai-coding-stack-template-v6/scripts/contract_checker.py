#!/usr/bin/env python3
"""
scripts/contract_checker.py — AST Contract Extractor & Drift Validator

Records and validates class signatures, properties, and methods across modules
to prevent contract drift (such as calling a @property as a function `obj.prop()`).
Contracts are persisted in `.ai/contracts.json`.

Usage:
    python scripts/contract_checker.py --extract
    python scripts/contract_checker.py --check [file_path]
"""

import os
import sys
import ast
import json
import argparse
from pathlib import Path
from typing import Dict, List, Any, Set, Tuple

IGNORE_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "node_modules",
    "dist", "build", ".pytest_cache", ".ai", ".agents",
    "coverage", ".mypy_cache", ".ruff_cache"
}


def extract_file_contracts(content: str, rel_path: str) -> Dict[str, Any]:
    """Extract AST classes, fields, properties, and methods from Python source."""
    result = {"classes": {}}
    try:
        tree = ast.parse(content)
    except Exception:
        return result

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            cls_name = node.name
            properties = []
            methods = []
            fields = []

            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    is_property = any(
                        isinstance(d, ast.Name) and d.id == "property"
                        for d in item.decorator_list
                    )
                    if is_property:
                        properties.append(item.name)
                    else:
                        methods.append(item.name)
                elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    fields.append(item.target.id)
                elif isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name):
                            fields.append(target.id)

            result["classes"][cls_name] = {
                "properties": sorted(set(properties)),
                "methods": sorted(set(methods)),
                "fields": sorted(set(fields))
            }

    return result


def extract_workspace_contracts(root: Path) -> Dict[str, Any]:
    """Scan workspace and write `.ai/contracts.json`."""
    contracts = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in sorted(dirnames) if d not in IGNORE_DIRS and not d.startswith(".")]
        for f in sorted(filenames):
            if f.endswith(".py"):
                fpath = Path(dirpath, f)
                rel_p = fpath.relative_to(root).as_posix()
                try:
                    content = fpath.read_text(encoding="utf-8", errors="ignore")
                    file_c = extract_file_contracts(content, rel_p)
                    if file_c.get("classes"):
                        contracts[rel_p] = file_c
                except Exception:
                    pass

    out_file = root / ".ai" / "contracts.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(contracts, indent=2), encoding="utf-8")
    return contracts


def check_contract_violations(root: Path, target_path: Path = None) -> List[Dict[str, str]]:
    """
    Check if code calls any @property as a function (e.g. `obj.prop()`).
    Returns a list of violation dicts with file, line, and message.
    """
    contracts_path = root / ".ai" / "contracts.json"
    if not contracts_path.exists():
        extract_workspace_contracts(root)

    try:
        contracts_data = json.loads(contracts_path.read_text(encoding="utf-8"))
    except Exception:
        contracts_data = {}

    all_properties: Set[str] = set()
    for file_key, file_info in contracts_data.items():
        if isinstance(file_info, dict):
            for cls_name, cls_info in file_info.get("classes", {}).items():
                for prop in cls_info.get("properties", []):
                    all_properties.add(prop)

    if not all_properties:
        return []

    violations = []
    files_to_check = [target_path] if target_path else [
        Path(dp, f) for dp, dirs, files in os.walk(root)
        for f in files if f.endswith(".py")
        if not any(ign in dp for ign in IGNORE_DIRS)
    ]

    for fpath in files_to_check:
        if not fpath.exists() or not fpath.is_file():
            continue
        rel_p = fpath.relative_to(root).as_posix() if fpath.is_absolute() else str(fpath)
        try:
            content = fpath.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Attribute):
                        called_name = node.func.attr
                        if called_name in all_properties:
                            violations.append({
                                "file": rel_p,
                                "line": getattr(node, "lineno", 0),
                                "property": called_name,
                                "message": f"Contract Violation: '{called_name}' is defined as a @property and must be accessed without parentheses '()'."
                            })
        except Exception:
            pass

    return violations


def main():
    parser = argparse.ArgumentParser(description="AST Contract Extractor & Validator")
    parser.add_argument("--extract", action="store_true", help="Extract and save contracts to .ai/contracts.json")
    parser.add_argument("--check", type=str, nargs="?", const="all", default=None, help="Check file or workspace for contract violations")
    args = parser.parse_args()

    root = Path.cwd()
    if args.extract:
        contracts = extract_workspace_contracts(root)
        print(f"[CONTRACTS] Extracted contracts for {len(contracts)} modules to .ai/contracts.json")

    if args.check:
        target = None if args.check == "all" else Path(args.check)
        violations = check_contract_violations(root, target)
        if violations:
            print(f"\n[CONTRACTS] Found {len(violations)} contract violation(s):")
            for v in violations:
                print(f"  [FAIL] {v['file']}:{v['line']} — {v['message']}")
            print()
            sys.exit(1)
        else:
            print("[CONTRACTS] All @property contract checks passed.")


if __name__ == "__main__":
    main()
