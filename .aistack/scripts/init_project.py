#!/usr/bin/env python3
"""
.aistack/scripts/init_project.py — AGENTS.md Step 0, as one command. A human runs this once.

Decides from the files on disk, not by asking the AI, whether this is a new
project or an existing repo:
  - existing repo: records the source folders, languages and a suggested test
    command it finds. The layout on disk wins; nothing is moved.
  - new project:   asks for frontend / backend / database and fills in the
    matching rows from context.md's templates.

It prints what it found and writes context.md and config.yaml's tests.command
only after the human confirms. Both are protected files (RULE-GOV-001), which
is why a human runs this, not the AI.

Usage:
    python .aistack/scripts/init_project.py [--yes] [--frontend react|angular|none]
                                   [--backend express|fastapi|none] [--db yes|no]
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

CONTEXT_FILE = "context.md"
CONFIG_FILE = ".aistack/config/config.yaml"

# The stack's own folders besides hidden ones (.aistack, .ai, .agents): never project code.
STACK_DIRS = {"input"}
IGNORE_DIRS = {
    "node_modules", "venv", "env", "dist", "build", "coverage", "target",
    "bin", "obj", "__pycache__", "vendor",
}
LANGUAGES = {
    ".py": "Python", ".ts": "TypeScript", ".tsx": "TypeScript",
    ".js": "JavaScript", ".jsx": "JavaScript", ".java": "Java", ".kt": "Kotlin",
    ".cs": "C#", ".dart": "Dart", ".go": "Go", ".rb": "Ruby", ".php": "PHP",
    ".rs": "Rust",
}
# manifest -> test command run from that manifest's folder
TEST_COMMANDS = {
    "pom.xml": "mvn test",
    "build.gradle": "gradle test",
    "build.gradle.kts": "gradle test",
    "go.mod": "go test ./...",
    "Cargo.toml": "cargo test",
    "pubspec.yaml": "dart test",
}
PYTHON_MANIFESTS = {"pyproject.toml", "requirements.txt", "setup.py", "pytest.ini"}
MANIFEST_DEPTH = 2  # root, apps/, apps/web/

# context.md templates for a new project (same rows as its Build / Run table)
FRONTENDS = {
    "react": ("TypeScript", "npm test --prefix frontend",
              "npm run lint --prefix frontend && tsc --noEmit -p frontend"),
    "angular": ("TypeScript", "npm test --prefix frontend",
                "npm run lint --prefix frontend && tsc --noEmit -p frontend"),
}
BACKENDS = {
    "express": ("TypeScript", "npm test --prefix backend",
                "npm run lint --prefix backend && tsc --noEmit -p backend"),
    "fastapi": ("Python", "python -m pytest -q backend", "mypy --strict backend/app"),
}


def _project_dirs(root: Path):
    """os.walk over the project's own files: skips hidden, stack and build folders."""
    for dirpath, dirnames, filenames in os.walk(root):
        rel = Path(dirpath).relative_to(root)
        dirnames[:] = sorted(
            d for d in dirnames
            if not d.startswith(".") and d not in IGNORE_DIRS
            and not (rel == Path(".") and d in STACK_DIRS)
        )
        yield rel, filenames


def _test_command(manifest: str, folder: Path, root: Path) -> str | None:
    """Suggested test command for one manifest, or None if it defines no tests."""
    where = folder.as_posix()
    at_root = where == "."
    if manifest == "package.json":
        try:
            scripts = json.loads((root / folder / manifest).read_text(encoding="utf-8")).get("scripts") or {}
        except (OSError, ValueError, AttributeError):
            return None
        test = scripts.get("test", "")
        if not test or "no test specified" in test:
            return None
        return "npm test" if at_root else f"npm test --prefix {where}"
    if manifest in PYTHON_MANIFESTS:
        return "python -m pytest -q" if at_root else f"python -m pytest -q {where}"
    if manifest in TEST_COMMANDS or manifest.endswith(".csproj"):
        cmd = TEST_COMMANDS.get(manifest, "dotnet test")
        return cmd if at_root else f"cd {where} && {cmd}"
    return None


def detect(root: Path) -> dict:
    """What is on disk: {"existing", "source_folders", "languages", "test_command"}."""
    folders: list[str] = []
    counts: dict[str, int] = {}
    commands: list[str] = []
    for rel, filenames in _project_dirs(root):
        for name in filenames:
            lang = LANGUAGES.get(Path(name).suffix.lower())
            if lang:
                counts[lang] = counts.get(lang, 0) + 1
                top = "." if rel == Path(".") else rel.parts[0] + "/"
                if top not in folders:
                    folders.append(top)
        if len(rel.parts) <= MANIFEST_DEPTH:
            for name in sorted(filenames):
                cmd = _test_command(name, rel, root)
                if cmd and cmd not in commands:
                    commands.append(cmd)
    return {
        "existing": bool(counts),
        "source_folders": sorted(folders),
        "languages": sorted(counts, key=lambda k: -counts[k]),
        "test_command": " && ".join(commands) or None,
    }


def plan_new(frontend: str, backend: str, db: bool) -> dict:
    """context.md values for a new project from the template rows."""
    if frontend == "none" and backend == "none":
        raise ValueError("frontend and backend cannot both be 'none'")
    picks = [FRONTENDS[frontend]] if frontend != "none" else []
    picks += [BACKENDS[backend]] if backend != "none" else []
    capabilities = (["rest"] if backend != "none" else []) + (["db"] if db else [])
    return {
        "frontend": frontend,
        "backend": backend,
        "capabilities": ", ".join(capabilities) or "none",
        "source_folders": [f"{side}/" for side, pick in (("frontend", frontend), ("backend", backend))
                           if pick != "none"],
        "languages": sorted({p[0] for p in picks}),
        "test_command": " && ".join(p[1] for p in picks),
        "lint_command": " && ".join(p[2] for p in picks),
    }


def _set_field(text: str, label: str, value: str) -> str:
    """Replace the value of a `- **Label**: ...` line; unchanged if the line is missing."""
    pattern = re.compile(rf"^(-\s*\*\*{re.escape(label)}\*\*:).*$", re.M)
    return pattern.sub(lambda m: f"{m.group(1)} {value}", text, count=1)


def update_context(text: str, info: dict) -> str:
    """context.md with the detected (or chosen) values filled in."""
    text = _set_field(text, "Repo", "existing" if info.get("existing") else "new")
    text = _set_field(text, "Source folders", ", ".join(f"`{f}`" for f in info["source_folders"]))
    text = _set_field(text, "Languages", ", ".join(info["languages"]) or "[Fill In]")
    if info.get("test_command"):
        text = _set_field(text, "Tests", f"`{info['test_command']}`")
    if info.get("lint_command"):
        text = _set_field(text, "Lint / type-check", f"`{info['lint_command']}`")
    for label in ("Frontend", "Backend", "Capabilities"):
        if label.lower() in info:
            text = _set_field(text, label, info[label.lower()])
    return text


def update_config(text: str, test_command: str) -> str:
    """config.yaml with tests.command replaced; comments and other keys kept."""
    pattern = re.compile(r"^(tests:\s*\n(?:[ \t]*#.*\n)*[ \t]+command:[ \t]*).*$", re.M)
    return pattern.sub(lambda m: m.group(1) + json.dumps(test_command), text, count=1)


def _ask(question: str, choices: list[str]) -> str:
    while True:
        answer = input(f"{question} [{'/'.join(choices)}]: ").strip().lower()
        if answer in choices:
            return answer


def _report(info: dict) -> None:
    rows = [
        ("Repo", "existing" if info.get("existing") else "new"),
        ("Source folders", ", ".join(info["source_folders"]) or "(none)"),
        ("Languages", ", ".join(info["languages"]) or "(none)"),
        ("Test command", info.get("test_command") or "[FILL IN] — no test runner found"),
    ]
    if info.get("lint_command"):
        rows.append(("Lint command", info["lint_command"]))
    for label, value in rows:
        print(f"  {label:<15}: {value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Detect a new or existing repo and fill in context.md.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--yes", action="store_true", help="write without asking for confirmation")
    parser.add_argument("--frontend", choices=["react", "angular", "none"])
    parser.add_argument("--backend", choices=["express", "fastapi", "none"])
    parser.add_argument("--db", choices=["yes", "no"])
    args = parser.parse_args(argv)
    root = args.root

    info = detect(root)
    try:
        if info["existing"]:
            print("Existing repo detected. The layout on disk is kept as is.")
        else:
            print("New project (no source files found).")
            info = plan_new(
                args.frontend or _ask("Frontend?", ["react", "angular", "none"]),
                args.backend or _ask("Backend?", ["express", "fastapi", "none"]),
                (args.db or _ask("Database?", ["yes", "no"])) == "yes",
            )
        _report(info)
        if not args.yes and _ask(f"Write this to {CONTEXT_FILE} and {CONFIG_FILE}?", ["y", "n"]) != "y":
            print("Nothing written.")
            return 1
    except EOFError:
        print("\nERROR: no answer given. Re-run with --yes (and --frontend/--backend/--db for a new project).",
              file=sys.stderr)
        return 3
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3

    context_path, config_path = root / CONTEXT_FILE, root / CONFIG_FILE
    context_path.write_text(update_context(context_path.read_text(encoding="utf-8"), info), encoding="utf-8")
    if info.get("test_command"):
        config_path.write_text(update_config(config_path.read_text(encoding="utf-8"), info["test_command"]),
                               encoding="utf-8")
    else:
        print(f"Set tests.command in {CONFIG_FILE} yourself: no test runner was found.")
    print(f"Written. Review {CONTEXT_FILE}, then give your AI a request or a PRD.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
