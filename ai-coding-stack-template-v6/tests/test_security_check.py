from pathlib import Path
from scripts.security_check import scan_file_security, scan_workspace_security


def test_detect_aws_key(tmp_path):
    bad_file = tmp_path / "config.py"
    bad_file.write_text("AWS_KEY = 'AKIAIOSFODNN7EXAMPLE'", encoding="utf-8")
    findings = scan_file_security(bad_file, tmp_path)
    assert len(findings) == 1
    assert findings[0]["rule_id"] == "SEC-001"


def test_detect_raw_sql_injection(tmp_path):
    bad_file = tmp_path / "db.py"
    bad_file.write_text('query = f"SELECT * FROM users WHERE username = \'{user}\'"', encoding="utf-8")
    findings = scan_file_security(bad_file, tmp_path)
    assert len(findings) == 1
    assert findings[0]["rule_id"] == "SEC-004"


def test_detect_insecure_subprocess(tmp_path):
    bad_file = tmp_path / "runner.py"
    bad_file.write_text("subprocess.run('ls ' + user_dir, shell=True)", encoding="utf-8")
    findings = scan_file_security(bad_file, tmp_path)
    assert len(findings) == 1
    assert findings[0]["rule_id"] == "SEC-006"


def test_clean_file_passes(tmp_path):
    good_file = tmp_path / "service.py"
    good_file.write_text("""
import os
from pydantic import BaseModel

api_key = os.getenv("API_KEY")

def get_user(db, user_id: int):
    return db.query(User).filter(User.id == user_id).first()
""", encoding="utf-8")
    findings = scan_file_security(good_file, tmp_path)
    assert len(findings) == 0
