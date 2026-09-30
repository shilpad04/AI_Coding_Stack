"""
tests/test_init_project.py
==========================
Tests for .aistack/scripts/init_project.py: Step 0 decided from the files on disk.
A repo with source files is "existing" and its layout is recorded as found;
an empty one is "new" and gets the context.md template rows.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import init_project as ip  # noqa: E402

CONTEXT = """- **Languages**: [Fill In]
- **Tests**: [Fill In]
- **Lint / type-check**: [Fill In]
- **Repo**: [Fill In]
- **Source folders**: [Fill In]
- **Frontend**: [Fill In]
- **Backend**: [Fill In]
- **Capabilities**: [Fill In]
- **Language**: [Fill In]
"""
CONFIG = """governance:
  max_repair_attempts: 2

tests:
  # CHANGE THIS.
  command: "python -m pytest -q"

snapshot:
  exclude: []
"""


def _write(root: Path, rel: str, text: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _stack(root: Path) -> None:
    _write(root, ip.CONTEXT_FILE, CONTEXT)
    _write(root, ip.CONFIG_FILE, CONFIG)


class TestDetect:
    def test_only_stack_files_is_a_new_project(self, tmp_path):
        _stack(tmp_path)
        _write(tmp_path, ".aistack/scripts/validate_proposal.py", "x = 1\n")
        _write(tmp_path, ".aistack/tests/test_x.py", "def test_x(): pass\n")
        _write(tmp_path, "input/prd.md", "# PRD\n")
        _write(tmp_path, ".agents/tool.py", "x = 1\n")
        assert ip.detect(tmp_path)["existing"] is False

    def test_python_backend_folder(self, tmp_path):
        _write(tmp_path, "server/app/main.py", "x = 1\n")
        _write(tmp_path, "server/pyproject.toml", "[project]\n")
        info = ip.detect(tmp_path)
        assert info["existing"] is True
        assert info["source_folders"] == ["server/"]
        assert info["languages"] == ["Python"]
        assert info["test_command"] == "python -m pytest -q server"

    def test_root_level_code_and_npm_test_script(self, tmp_path):
        _write(tmp_path, "index.js", "")
        _write(tmp_path, "package.json", '{"scripts": {"test": "jest"}}')
        info = ip.detect(tmp_path)
        assert info["source_folders"] == ["."]
        assert info["test_command"] == "npm test"

    def test_monorepo_joins_commands(self, tmp_path):
        _write(tmp_path, "apps/web/src/main.tsx", "")
        _write(tmp_path, "apps/web/package.json", '{"scripts": {"test": "vitest"}}')
        _write(tmp_path, "api/main.go", "")
        _write(tmp_path, "api/go.mod", "module api\n")
        info = ip.detect(tmp_path)
        assert info["source_folders"] == ["api/", "apps/"]
        assert info["test_command"] == "cd api && go test ./... && npm test --prefix apps/web"

    def test_npm_placeholder_test_script_is_ignored(self, tmp_path):
        _write(tmp_path, "web/a.js", "")
        _write(tmp_path, "web/package.json",
               '{"scripts": {"test": "echo \\"Error: no test specified\\" && exit 1"}}')
        assert ip.detect(tmp_path)["test_command"] is None

    def test_dependency_and_build_folders_are_skipped(self, tmp_path):
        _write(tmp_path, "node_modules/lib/index.js", "")
        _write(tmp_path, "dist/bundle.js", "")
        _write(tmp_path, "README.md", "# hi\n")
        assert ip.detect(tmp_path)["existing"] is False


class TestPlanNew:
    def test_react_and_fastapi_with_db(self):
        info = ip.plan_new("react", "fastapi", db=True)
        assert info["source_folders"] == ["frontend/", "backend/"]
        assert info["capabilities"] == "rest, db"
        assert info["test_command"] == "npm test --prefix frontend && python -m pytest -q backend"
        assert info["lint_command"].endswith("mypy --strict backend/app")

    def test_backend_only(self):
        info = ip.plan_new("none", "express", db=False)
        assert info["source_folders"] == ["backend/"]
        assert info["test_command"] == "npm test --prefix backend"

    def test_nothing_to_build_is_an_error(self):
        with pytest.raises(ValueError):
            ip.plan_new("none", "none", db=False)


class TestWriters:
    def test_update_context_fills_fields_and_keeps_the_rest(self):
        info = {"existing": True, "source_folders": ["server/"], "languages": ["Python"],
                "test_command": "python -m pytest -q server"}
        text = ip.update_context(CONTEXT, info)
        assert "- **Repo**: existing" in text
        assert "- **Source folders**: `server/`" in text
        assert "- **Tests**: `python -m pytest -q server`" in text
        assert "- **Language**: [Fill In]" in text  # a different label, untouched
        assert "- **Frontend**: [Fill In]" in text  # existing repos leave the template rows alone

    def test_update_config_replaces_only_tests_command(self):
        text = ip.update_config(CONFIG, "npm test --prefix web")
        assert 'command: "npm test --prefix web"' in text
        assert "# CHANGE THIS." in text and "max_repair_attempts: 2" in text


class TestMain:
    def test_new_project_with_flags_writes_both_files(self, tmp_path, capsys):
        _stack(tmp_path)
        code = ip.main(["--root", str(tmp_path), "--yes",
                        "--frontend", "react", "--backend", "fastapi", "--db", "no"])
        assert code == 0
        context = (tmp_path / ip.CONTEXT_FILE).read_text(encoding="utf-8")
        assert "- **Repo**: new" in context and "- **Backend**: fastapi" in context
        assert "- **Lint / type-check**: `npm run lint" in context
        config = (tmp_path / ip.CONFIG_FILE).read_text(encoding="utf-8")
        assert 'command: "npm test --prefix frontend && python -m pytest -q backend"' in config

    def test_declining_writes_nothing(self, tmp_path, monkeypatch):
        _stack(tmp_path)
        _write(tmp_path, "src/a.py", "x = 1\n")
        monkeypatch.setattr("builtins.input", lambda _: "n")
        assert ip.main(["--root", str(tmp_path)]) == 1
        assert (tmp_path / ip.CONTEXT_FILE).read_text(encoding="utf-8") == CONTEXT

    def test_no_test_runner_leaves_config_alone(self, tmp_path, capsys):
        _stack(tmp_path)
        _write(tmp_path, "src/a.py", "x = 1\n")
        assert ip.main(["--root", str(tmp_path), "--yes"]) == 0
        assert (tmp_path / ip.CONFIG_FILE).read_text(encoding="utf-8") == CONFIG
        assert "no test runner" in capsys.readouterr().out

    def test_no_answer_on_a_new_project_is_an_error(self, tmp_path, monkeypatch):
        _stack(tmp_path)

        def _eof(_):
            raise EOFError
        monkeypatch.setattr("builtins.input", _eof)
        assert ip.main(["--root", str(tmp_path)]) == 3
