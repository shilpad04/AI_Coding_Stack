import json
from pathlib import Path
from scripts.contract_checker import (
    extract_file_contracts,
    extract_workspace_contracts,
    check_contract_violations
)


def test_extract_file_contracts():
    code = """
class Account:
    id: int
    name: str

    @property
    def is_verified(self) -> bool:
        return True

    def deposit(self, amount: float) -> None:
        pass
"""
    contracts = extract_file_contracts(code, "src/models.py")
    assert "Account" in contracts["classes"]
    acc = contracts["classes"]["Account"]
    assert "is_verified" in acc["properties"]
    assert "deposit" in acc["methods"]
    assert "id" in acc["fields"]


def test_check_property_call_violation(tmp_path):
    # 1. Setup model with @property
    model_file = tmp_path / "models.py"
    model_file.write_text("""
class User:
    @property
    def is_active(self) -> bool:
        return True
""", encoding="utf-8")

    extract_workspace_contracts(tmp_path)

    # 2. Setup caller with invalid @property invocation `user.is_active()`
    caller_file = tmp_path / "handler.py"
    caller_file.write_text("""
def check_user(user):
    if user.is_active():
        return True
    return False
""", encoding="utf-8")

    violations = check_contract_violations(tmp_path, caller_file)
    assert len(violations) == 1
    assert violations[0]["property"] == "is_active"
    assert "is defined as a @property" in violations[0]["message"]
