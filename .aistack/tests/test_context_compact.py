from pathlib import Path
from scripts.context_compact import compact_session_context


def test_compact_session_context(tmp_path):
    src_file = tmp_path / "src" / "app.py"
    src_file.parent.mkdir(parents=True, exist_ok=True)
    src_file.write_text("class App: pass", encoding="utf-8")

    test_file = tmp_path / "tests" / "test_app.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text("def test_app(): pass", encoding="utf-8")

    summary = compact_session_context(tmp_path, active_goal="Adding user profile route")
    assert "Active Goal" in summary
    assert "Adding user profile route" in summary
    assert "src/app.py" in summary
    assert "tests/test_app.py" in summary
    assert "The Four Principles" in summary

    summary_file = tmp_path / ".ai" / "session_summary.md"
    assert summary_file.exists()
