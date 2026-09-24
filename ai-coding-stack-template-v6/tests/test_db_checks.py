"""
tests/test_db_checks.py
=======================
The database rules from rules.md that the validator enforces:

  RULE-DB-001  A migration is never bundled with feature code. FAIL.
  RULE-DB-002  No ORM auto-create/sync; schema comes from migrations. FAIL.

Plus the migration commands in config/command-policy.yaml that need a human.
"""
import json
import sys
import types
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import validators as v  # noqa: E402
from validate_proposal import run_validation  # noqa: E402


def _proposal(*files: tuple[str, str], action: str = "create") -> types.SimpleNamespace:
    return types.SimpleNamespace(files=[
        {"path": path, "action": action, "content": content} for path, content in files])


def _rules(result: v.Result) -> list[str]:
    return [f["rule"] for f in result.findings]


# RULE-DB-002: no ORM auto-create / auto-sync

class TestAutoSchema:
    @pytest.mark.parametrize("path, content", [
        ("app/db/session.py", "Base.metadata.create_all(bind=engine)\n"),
        ("backend/src/data-source.ts", "export default new DataSource({ synchronize: true })\n"),
        ("backend/ormconfig.json", '{"synchronize": true}\n'),
        ("backend/src/db.js", "await sequelize.sync({ alter: true });\n"),
        ("backend/package.json", '{"scripts": {"db": "prisma db push"}}\n'),
    ])
    def test_auto_create_or_sync_fails(self, path: str, content: str) -> None:
        result = v.validate_database(_proposal((path, content)))

        assert result.status == v.FAIL
        assert _rules(result) == ["RULE-DB-002"]
        assert path in result.findings[0]["message"]

    @pytest.mark.parametrize("content", [
        "synchronize: false\n",
        "fs.writeFileSync(path, data)\n",
        "npx prisma migrate deploy\n",
    ])
    def test_safe_lookalikes_pass(self, content: str) -> None:
        assert v.validate_database(_proposal(("backend/src/db.ts", content))).ok

    def test_markdown_may_name_the_forbidden_calls(self) -> None:
        assert v.validate_database(_proposal(("docs/db.md", "Never call create_all().\n"))).ok

    def test_deleting_a_file_that_used_it_passes(self) -> None:
        assert v.validate_database(_proposal(("app/db.py", "create_all()\n"), action="delete")).ok


# RULE-DB-001: a migration is its own task

class TestMigrationIsItsOwnTask:
    def test_migration_with_feature_code_fails(self) -> None:
        result = v.validate_database(_proposal(
            ("alembic/versions/001_add_email.py", "def upgrade(): pass\n"),
            ("app/services/user_service.py", "x = 1\n")))

        assert result.status == v.FAIL
        assert _rules(result) == ["RULE-DB-001"]
        assert "app/services/user_service.py" in result.findings[0]["message"]

    @pytest.mark.parametrize("companion", [
        "app/models/user.py",
        "app/models.py",
        "backend/src/entities/User.ts",
        "backend/src/user.entity.ts",
        "backend/src/user.model.js",
        "tests/test_migration_001.py",
        "prisma/schema.prisma",
    ])
    def test_migration_with_its_model_or_test_passes(self, companion: str) -> None:
        assert v.validate_database(_proposal(
            ("backend/migrations/001_add_email.js", "x = 1\n"), (companion, "x = 1\n"))).ok

    def test_migration_alone_passes(self) -> None:
        assert v.validate_database(_proposal(("migrations/001.sql", "ALTER TABLE t ADD c int;\n"))).ok

    def test_feature_alone_passes(self) -> None:
        assert v.validate_database(_proposal(("app/services/a.py", "x = 1\n"))).ok

    def test_windows_style_paths_are_understood(self) -> None:
        result = v.validate_database(_proposal(
            ("alembic\\versions\\001.py", "x = 1\n"), ("app\\api\\users.py", "x = 1\n")))
        assert _rules(result) == ["RULE-DB-001"]


# Wired into the validator: nothing is written

def test_validator_blocks_auto_create_and_writes_nothing(tmp_path: Path) -> None:
    allowed = ["app/db.py", "tests/test_db.py"]
    (tmp_path / ".ai").mkdir()
    (tmp_path / ".ai" / "plan.json").write_text(json.dumps({"phases": [{"id": "P", "tasks": [
        {"task_id": "TASK-001", "allowed_files": allowed, "acceptance_criteria": ["ok"]}]}]}),
        encoding="utf-8")
    (tmp_path / ".ai" / "plan-approval.json").write_text(
        json.dumps({"TASK-001": {"allowed_files": sorted(allowed)}}), encoding="utf-8")
    proposal = tmp_path / "p.json"
    proposal.write_text(json.dumps({"task_id": "TASK-001", "status": "PROPOSAL", "files": [
        {"path": "app/db.py", "action": "create", "content": "Base.metadata.create_all(engine)\n"},
        {"path": "tests/test_db.py", "action": "create", "content": "def test_x():\n    assert 1\n"},
    ]}), encoding="utf-8")

    code = run_validation(
        proposal_path=proposal, config_path=ROOT / "config" / "config.yaml",
        packages_path=ROOT / "config" / "approved-packages.yaml",
        commands_path=ROOT / "config" / "command-policy.yaml",
        task={}, allowed_files=[], skip_reconcile=True, quiet=True,
        apply_files=True, project_root=tmp_path)

    assert code == 1
    assert not (tmp_path / "app" / "db.py").exists()


# Migration commands in the real command policy need a human (RULE-EXEC-002)

@pytest.mark.parametrize("command", [
    "alembic upgrade head",
    "npx prisma migrate deploy",
    "npx prisma db push",
    "npx sequelize db:migrate",
    "npx sequelize-cli db:migrate",
    "npx knex migrate:latest",
    "npx typeorm migration:run -d src/data-source.ts",
    "npx typeorm migration:revert -d src/data-source.ts",
])
def test_migration_commands_ask_a_human(command: str) -> None:
    policy_cfg = yaml.safe_load((ROOT / "config" / "command-policy.yaml").read_text(encoding="utf-8"))

    assert v.classify_command(command, policy_cfg) == ("ASK", "RULE-EXEC-002")
