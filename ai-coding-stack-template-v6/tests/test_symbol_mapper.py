import os
from pathlib import Path
from scripts.symbol_mapper import (
    _extract_python_symbols,
    _extract_ts_js_symbols,
    generate_symbol_map
)


def test_extract_python_symbols():
    py_code = """
class UserModel:
    def __init__(self, name: str) -> None:
        self.name = name

    @property
    def is_active(self) -> bool:
        return True

    def save(self) -> bool:
        return True

def create_user(name: str) -> UserModel:
    return UserModel(name)
"""
    syms = _extract_python_symbols(py_code)
    assert "UserModel" in syms["classes"]
    user_cls = syms["classes"]["UserModel"]
    assert "is_active" in user_cls["properties"]
    assert any("save" in m for m in user_cls["methods"])
    assert any("create_user" in f for f in syms["functions"])


def test_extract_ts_symbols():
    ts_code = """
export interface UserProfile {
    id: string;
    email: string;
}

export type RoleType = "admin" | "user";

export class AuthService {
    login(): boolean {
        return true;
    }
}

export async function fetchUser(id: string): Promise<UserProfile> {
    return { id, email: "test@example.com" };
}
"""
    syms = _extract_ts_js_symbols(ts_code)
    assert "UserProfile" in syms["interfaces"]
    assert "RoleType" in syms["types"]
    assert "AuthService" in syms["classes"]
    assert any("fetchUser" in fn for fn in syms["functions"])


def test_generate_symbol_map_workspace(tmp_path):
    py_file = tmp_path / "app.py"
    py_file.write_text("class App: pass\ndef run(): pass", encoding="utf-8")

    ts_file = tmp_path / "index.ts"
    ts_file.write_text("export interface Config {}\nexport function start() {}", encoding="utf-8")

    smap = generate_symbol_map(tmp_path)
    assert "app.py" in smap
    assert "class App" in smap
    assert "index.ts" in smap
    assert "interfaces: Config" in smap
