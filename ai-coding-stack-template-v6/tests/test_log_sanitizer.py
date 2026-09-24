from scripts.log_sanitizer import sanitize_log, extract_error_summary


def test_sanitize_short_log():
    short_log = "All 10 tests passed in 0.5s"
    res = sanitize_log(short_log, max_chars=1000)
    assert res == short_log


def test_sanitize_long_log():
    # Generate 5,000 characters of simulated log output
    long_log = "START OF TEST RUN\n" + ("line output with debug details\n" * 200) + "FAILED tests/test_auth.py::test_login"

    res = sanitize_log(long_log, max_chars=500)
    assert len(res) <= 600  # including truncation message
    assert "START OF TEST RUN" in res
    assert "FAILED tests/test_auth.py::test_login" in res
    assert "[... Truncated" in res


def test_extract_error_summary():
    log = """
============================= test session starts =============================
rootdir: /app
FAILED tests/test_auth.py::test_login - AssertionError: expected 200 got 401
=========================== 1 failed, 9 passed ===========================
"""
    summary = extract_error_summary(log)
    assert "FAILED tests/test_auth.py::test_login" in summary
