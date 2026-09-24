#!/usr/bin/env python3
"""
scripts/symbol_mapper.py — AST Repository Symbol Mapper

Generates a compact (~2KB / <500 tokens) architectural overview of the repository
by extracting classes, methods, @property attributes, functions, and exported types.

Usage:
    python scripts/symbol_mapper.py
    python scripts/symbol_mapper.py --output .ai/symbol_map.txt
"""

import os
import sys
import ast
import re
import argparse
from pathlib import Path
from typing import Dict, List, Any

IGNORE_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "node_modules",
    "dist", "build", ".pytest_cache", ".ai", ".agents",
    "coverage", ".mypy_cache", ".ruff_cache"
}


def _extract_python_symbols(content: str) -> Dict[str, Any]:
    """Parse Python source code and extract classes, properties, methods, and functions."""
    symbols = {"classes": {}, "functions": []}
    try:
        tree = ast.parse(content)
    except Exception:
        return symbols

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            cls_name = node.name
            cls_info = {"methods": [], "properties": []}
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    # Check if @property decorator is present
                    is_property = any(
                        isinstance(d, ast.Name) and d.id == "property"
                        for d in item.decorator_list
                    )
                    args = [a.arg for a in item.args.args if a.arg != "self"]
                    ret_type = ast.unparse(item.returns) if item.returns else None
                    ret_str = f" -> {ret_type}" if ret_type else ""
                    sig = f"{item.name}({', '.join(args)}){ret_str}"

                    if is_property:
                        cls_info["properties"].append(item.name)
                    else:
                        cls_info["methods"].append(sig)
            symbols["classes"][cls_name] = cls_info

        elif isinstance(node, ast.FunctionDef):
            args = [a.arg for a in node.args.args]
            ret_type = ast.unparse(node.returns) if node.returns else None
            ret_str = f" -> {ret_type}" if ret_type else ""
            sig = f"{node.name}({', '.join(args)}){ret_str}"
            symbols["functions"].append(sig)

    return symbols


def _extract_ts_js_symbols(content: str) -> Dict[str, Any]:
    """Extract classes, interfaces, types, and exported functions from TS/JS code using regex."""
    symbols = {"interfaces": [], "types": [], "classes": {}, "functions": []}

    # Extract interfaces
    for m in re.finditer(r"(?:export\s+)?interface\s+([A-Za-z0-9_]+)", content):
        symbols["interfaces"].append(m.group(1))

    # Extract types
    for m in re.finditer(r"(?:export\s+)?type\s+([A-Za-z0-9_]+)\s*=", content):
        symbols["types"].append(m.group(1))

    # Extract classes
    for m in re.finditer(r"(?:export\s+)?class\s+([A-Za-z0-9_]+)", content):
        cls_name = m.group(1)
        symbols["classes"][cls_name] = {"methods": []}

    # Extract functions
    for m in re.finditer(r"(?:export\s+)?(?:async\s+)?function\s+([A-Za-z0-9_]+)\s*\(([^)]*)\)", content):
        fn_name = m.group(1)
        args = [a.strip().split(":")[0].strip() for a in m.group(2).split(",") if a.strip()]
        symbols["functions"].append(f"{fn_name}({', '.join(args)})")

    # Extract arrow functions / const exports
    for m in re.finditer(r"export\s+const\s+([A-Za-z0-9_]+)\s*=\s*(?:async\s*)?\(([^)]*)\)", content):
        fn_name = m.group(1)
        args = [a.strip().split(":")[0].strip() for a in m.group(2).split(",") if a.strip()]
        symbols["functions"].append(f"{fn_name}({', '.join(args)})")

    return symbols


def generate_symbol_map(root: Path) -> str:
    """Scan workspace and generate a concise textual symbol map."""
    lines = ["# Repository Symbol Map (AST Overview)", ""]
    file_count = 0

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in sorted(dirnames)
            if d not in IGNORE_DIRS and not d.startswith(".")
        ]
        for f in sorted(filenames):
            fpath = Path(dirpath, f)
            rel_p = fpath.relative_to(root).as_posix()
            ext = fpath.suffix.lower()

            if ext not in (".py", ".ts", ".tsx", ".js", ".jsx"):
                continue

            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            if not content.strip():
                continue

            if ext == ".py":
                syms = _extract_python_symbols(content)
                has_syms = bool(syms["classes"] or syms["functions"])
                if has_syms:
                    file_count += 1
                    lines.append(f"File: {rel_p}")
                    for cls_name, info in syms["classes"].items():
                        props = f" [@properties: {', '.join(info['properties'])}]" if info["properties"] else ""
                        lines.append(f"  class {cls_name}{props}")
                        for meth in info["methods"][:6]:
                            lines.append(f"    def {meth}")
                        if len(info["methods"]) > 6:
                            lines.append(f"    ... and {len(info['methods']) - 6} more methods")
                    for fn in syms["functions"][:8]:
                        lines.append(f"  def {fn}")
                    if len(syms["functions"]) > 8:
                        lines.append(f"  ... and {len(syms['functions']) - 8} more functions")
                    lines.append("")

            elif ext in (".ts", ".tsx", ".js", ".jsx"):
                syms = _extract_ts_js_symbols(content)
                has_syms = bool(syms["interfaces"] or syms["types"] or syms["classes"] or syms["functions"])
                if has_syms:
                    file_count += 1
                    lines.append(f"File: {rel_p}")
                    if syms["interfaces"]:
                        lines.append(f"  interfaces: {', '.join(syms['interfaces'])}")
                    if syms["types"]:
                        lines.append(f"  types: {', '.join(syms['types'])}")
                    for cls_name, info in syms["classes"].items():
                        lines.append(f"  class {cls_name}")
                    for fn in syms["functions"][:8]:
                        lines.append(f"  fn {fn}")
                    if len(syms["functions"]) > 8:
                        lines.append(f"  ... and {len(syms['functions']) - 8} more functions")
                    lines.append("")

    lines.insert(1, f"Total source modules indexed: {file_count}\n")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="AST Repository Symbol Mapper")
    parser.add_argument("--output", "-o", type=str, default=None, help="Save symbol map to specified file path")
    args = parser.parse_args()

    root = Path.cwd()
    symbol_map = generate_symbol_map(root)

    if args.output:
        out_p = Path(args.output)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(symbol_map, encoding="utf-8")
        print(f"[SYMBOL-MAP] Saved symbol map to {args.output} ({len(symbol_map)} bytes)")
    else:
        if sys.platform == "win32":
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
        print(symbol_map)


if __name__ == "__main__":
    main()
