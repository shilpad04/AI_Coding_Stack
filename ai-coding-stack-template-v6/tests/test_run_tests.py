"""
tests/test_run_tests.py
========================
Tests for scripts/run_tests.py: runs the project's test command (from
config/config.yaml) and its lint/type-check command (from context.md's
Build/Run Commands table) as one QA step, so non-Python code gets checked
too, not just Python tests.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import run_tests as rt  # noqa: E402


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class TestLoadTestsCommand:
    def test_reads_the_command_from_config_yaml(self, tmp_path):
        config = tmp_path / "config.yaml"
        _write(config, "tests:\n  command: \"npm test --prefix frontend\"\n")
        assert rt.load_tests_command(config) == "npm test --prefix frontend"

    def test_missing_config_returns_none(self, tmp_path):
        assert rt.load_tests_command(tmp_path / "no-such.yaml") is None

    def test_missing_tests_key_returns_none(self, tmp_path):
        config = tmp_path / "config.yaml"
        _write(config, "governance:\n  block_unapproved_packages: true\n")
        assert rt.load_tests_command(config) is None


class TestLoadLintCommand:
    def test_reads_the_command_from_context_md(self, tmp_path):
        ctx = tmp_path / "context.md"
        _write(ctx, "- **Lint / type-check**: `npm run lint --prefix frontend`\n")
        assert rt.load_lint_command(ctx) == "npm run lint --prefix frontend"

    def test_placeholder_is_not_configured(self, tmp_path):
        ctx = tmp_path / "context.md"
        _write(ctx, "- **Lint / type-check**: `[FILL IN]`\n")
        assert rt.load_lint_command(ctx) is None

    def test_missing_file_returns_none(self, tmp_path):
        assert rt.load_lint_command(tmp_path / "no-such.md") is None

    def test_missing_row_returns_none(self, tmp_path):
        ctx = tmp_path / "context.md"
        _write(ctx, "- **Tests**: `pytest -q`\n")
        assert rt.load_lint_command(ctx) is None


class TestParseCounts:
    def test_pytest_summary_line(self):
        out = "tests/a.py ..F\n==== 1 failed, 40 passed, 2 skipped in 1.2s ====\n"
        assert rt.parse_counts(out) == {"passed": 40, "failed": 1, "suites": None}

    def test_pytest_errors_count_as_failed(self):
        out = "==== 2 failed, 5 passed, 1 error in 0.5s ====\n"
        assert rt.parse_counts(out)["failed"] == 3

    def test_jest_reads_tests_and_suites(self):
        out = ("Test Suites: 1 failed, 5 passed, 6 total\n"
               "Tests:       2 failed, 40 passed, 42 total\n"
               "Snapshots:   0 total\nTime:        3.1 s\n")
        assert rt.parse_counts(out) == {
            "passed": 40, "failed": 2, "suites": {"passed": 5, "failed": 1}}

    def test_vitest_reads_tests_and_suites(self):
        out = (" Test Files  1 failed | 3 passed (4)\n"
               "      Tests  1 failed | 12 passed (13)\n")
        assert rt.parse_counts(out) == {
            "passed": 12, "failed": 1, "suites": {"passed": 3, "failed": 1}}

    def test_all_passing_reports_zero_failed(self):
        assert rt.parse_counts("==== 7 passed in 0.1s ====")["failed"] == 0

    def test_unrecognised_output_returns_none(self):
        assert rt.parse_counts("BUILD SUCCESS") is None


class TestMain:
    def _setup(self, tmp_path, tests_cmd='"echo tests"', lint_cmd="`echo lint`"):
        _write(tmp_path / "config" / "config.yaml", f"tests:\n  command: {tests_cmd}\n")
        _write(tmp_path / "context.md", f"- **Lint / type-check**: {lint_cmd}\n")

    def test_runs_tests_then_lint_and_reports_both_passing(self, tmp_path, monkeypatch, capsys):
        self._setup(tmp_path)
        calls = []

        def fake_run(cmd, cwd):
            calls.append(cmd)
            return 0, ""

        monkeypatch.setattr(rt, "run_command", fake_run)
        code = rt.main(["--root", str(tmp_path)])

        assert code == 0
        assert calls == ["echo tests", "echo lint"]
        out = capsys.readouterr().out
        assert "tests: PASS" in out and "lint: PASS" in out

    def test_prints_passed_and_failed_counts(self, tmp_path, monkeypatch, capsys):
        self._setup(tmp_path)
        output = {"echo tests": (1, "==== 2 failed, 40 passed in 1.0s ===="),
                  "echo lint": (0, "")}
        monkeypatch.setattr(rt, "run_command", lambda cmd, cwd: output[cmd])

        rt.main(["--root", str(tmp_path)])

        out = capsys.readouterr().out
        assert "tests: FAIL (40 passed, 2 failed)" in out
        assert "lint: PASS" in out

    def test_prints_suite_counts_when_runner_reports_them(self, tmp_path, monkeypatch, capsys):
        self._setup(tmp_path)
        jest = "Test Suites: 6 passed, 6 total\nTests:       42 passed, 42 total\n"
        monkeypatch.setattr(rt, "run_command",
                            lambda cmd, cwd: (0, jest if cmd == "echo tests" else ""))

        rt.main(["--root", str(tmp_path)])

        assert "tests: PASS (42 passed, 0 failed; suites: 6 passed, 0 failed)" in capsys.readouterr().out

    def test_says_counts_unavailable_for_unknown_runner(self, tmp_path, monkeypatch, capsys):
        self._setup(tmp_path)
        monkeypatch.setattr(rt, "run_command", lambda cmd, cwd: (0, "BUILD SUCCESS"))

        rt.main(["--root", str(tmp_path)])

        assert "tests: PASS (counts not reported by this runner)" in capsys.readouterr().out

    def test_prints_a_status_line_before_each_step(self, tmp_path, monkeypatch, capsys):
        self._setup(tmp_path)
        monkeypatch.setattr(rt, "run_command", lambda cmd, cwd: (0, ""))

        rt.main(["--root", str(tmp_path)])

        out = capsys.readouterr().out
        assert "[QA Agent] Running the tests." in out
        assert "[QA Agent] Running lint / type-check." in out

    def test_lint_not_configured_is_skipped_not_failed(self, tmp_path, monkeypatch, capsys):
        _write(tmp_path / "config" / "config.yaml", "tests:\n  command: \"echo tests\"\n")
        _write(tmp_path / "context.md", "- **Lint / type-check**: `[FILL IN]`\n")
        monkeypatch.setattr(rt, "run_command", lambda cmd, cwd: (0, ""))

        code = rt.main(["--root", str(tmp_path)])

        assert code == 0
        assert "lint: SKIPPED" in capsys.readouterr().out

    def test_failing_test_command_fails_the_run(self, tmp_path, monkeypatch, capsys):
        self._setup(tmp_path)
        monkeypatch.setattr(rt, "run_command", lambda cmd, cwd: (1 if cmd == "echo tests" else 0, ""))

        code = rt.main(["--root", str(tmp_path)])

        assert code == 1
        assert "tests: FAIL" in capsys.readouterr().out

    def test_failing_lint_command_fails_the_run_even_if_tests_pass(self, tmp_path, monkeypatch, capsys):
        self._setup(tmp_path)
        monkeypatch.setattr(rt, "run_command", lambda cmd, cwd: (1 if cmd == "echo lint" else 0, ""))

        code = rt.main(["--root", str(tmp_path)])

        assert code == 1
        out = capsys.readouterr().out
        assert "tests: PASS" in out and "lint: FAIL" in out

    def test_missing_tests_command_is_an_error(self, tmp_path, monkeypatch, capsys):
        _write(tmp_path / "context.md", "- **Lint / type-check**: `[FILL IN]`\n")
        monkeypatch.setattr(rt, "run_command", lambda cmd, cwd: (0, ""))

        code = rt.main(["--root", str(tmp_path)])

        assert code == 1
        assert "tests.command" in capsys.readouterr().err
