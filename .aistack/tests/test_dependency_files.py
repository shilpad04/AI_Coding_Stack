"""
tests/test_dependency_files.py
==============================
Tests for validators.validate_dependency_files(): a manifest file
(package.json, requirements.txt, pyproject.toml, pom.xml, build.gradle,
.csproj, packages.config, pubspec.yaml) is checked the same way as an
import statement — every dependency must be on the approved list for its
ecosystem, or the run is blocked. There are no exceptions: an unlisted
dependency is a FAIL, not a warning.
"""
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from validators import PASS, FAIL, ASK, validate_dependency_files  # noqa: E402


APPROVED = [
    {"name": "requests", "ecosystem": "pypi", "status": "approved"},
    {"name": "boto3", "ecosystem": "pypi", "status": "needs_approval"},
    {"name": "express", "ecosystem": "npm", "status": "approved"},
    {"name": "axios", "ecosystem": "npm", "status": "needs_approval"},
    {"name": "org.springframework:spring-core", "ecosystem": "maven", "status": "approved"},
    {"name": "com.google.guava:guava", "ecosystem": "maven", "status": "needs_approval"},
    {"name": "Newtonsoft.Json", "ecosystem": "nuget", "status": "approved"},
    {"name": "http", "ecosystem": "pub", "status": "approved"},
]


def _proposal(files):
    return types.SimpleNamespace(files=files)


def _file(path, content, action="create"):
    return {"path": path, "action": action, "content": content}


class TestNpm:
    def test_pass_approved_dependency(self):
        p = _proposal([_file("package.json", '{"dependencies": {"express": "^4.18.0"}}')])
        assert validate_dependency_files(p, APPROVED).status == PASS

    def test_fail_unapproved_dependency(self):
        p = _proposal([_file("package.json", '{"dependencies": {"left-pad": "1.0.0"}}')])
        r = validate_dependency_files(p, APPROVED)
        assert r.status == FAIL
        assert "left-pad" in r.findings[0]["message"]

    def test_ask_needs_approval_dependency(self):
        p = _proposal([_file("package.json", '{"dependencies": {"axios": "^1.6.0"}}')])
        assert validate_dependency_files(p, APPROVED).status == ASK

    def test_dev_dependencies_are_checked_too(self):
        p = _proposal([_file("package.json", '{"devDependencies": {"left-pad": "1.0.0"}}')])
        assert validate_dependency_files(p, APPROVED).status == FAIL

    def test_fail_on_invalid_json(self):
        p = _proposal([_file("package.json", "{not json")])
        r = validate_dependency_files(p, APPROVED)
        assert r.status == FAIL
        assert r.findings[0]["rule"] == "RULE-CODE-001"

    def test_deleted_file_is_not_checked(self):
        p = _proposal([_file("package.json", "", action="delete")])
        assert validate_dependency_files(p, APPROVED).status == PASS


class TestPip:
    def test_requirements_txt_checks_every_line(self):
        content = "requests==2.31.0\nleft-pad>=1.0\n# a comment\n\n-e .\n"
        p = _proposal([_file("requirements.txt", content)])
        r = validate_dependency_files(p, APPROVED)
        assert r.status == FAIL
        assert "left-pad" in r.findings[0]["message"]
        assert not any("requests" in f["message"] for f in r.findings)

    def test_requirements_txt_with_extras_and_markers(self):
        p = _proposal([_file("requirements.txt", "requests[socks]>=2.31; python_version>='3.8'\n")])
        assert validate_dependency_files(p, APPROVED).status == PASS

    def test_pyproject_poetry_table(self):
        content = (
            "[tool.poetry.dependencies]\n"
            "python = \"^3.11\"\n"
            "requests = \"^2.31\"\n"
            "left-pad = \"^1.0\"\n"
            "\n[tool.poetry.dev-dependencies]\n"
            "pytest = \"^8.0\"\n"
        )
        p = _proposal([_file("pyproject.toml", content)])
        r = validate_dependency_files(p, APPROVED)
        assert r.status == FAIL
        assert "left-pad" in r.findings[0]["message"]

    def test_pyproject_pep621_array(self):
        content = (
            "[project]\n"
            "name = \"demo\"\n"
            "dependencies = [\n"
            "    \"requests>=2.31\",\n"
            "    \"left-pad\",\n"
            "]\n"
        )
        p = _proposal([_file("pyproject.toml", content)])
        r = validate_dependency_files(p, APPROVED)
        assert r.status == FAIL
        assert "left-pad" in r.findings[0]["message"]


class TestMaven:
    def test_pom_xml_group_and_artifact(self):
        content = (
            "<project><dependencies>\n"
            "  <dependency>\n"
            "    <groupId>org.springframework</groupId>\n"
            "    <artifactId>spring-core</artifactId>\n"
            "  </dependency>\n"
            "  <dependency>\n"
            "    <groupId>com.badlib</groupId>\n"
            "    <artifactId>badlib</artifactId>\n"
            "  </dependency>\n"
            "</dependencies></project>\n"
        )
        p = _proposal([_file("pom.xml", content)])
        r = validate_dependency_files(p, APPROVED)
        assert r.status == FAIL
        assert "com.badlib:badlib" in r.findings[0]["message"]

    def test_pom_xml_needs_approval(self):
        content = (
            "<project><dependencies>\n"
            "  <dependency><groupId>com.google.guava</groupId><artifactId>guava</artifactId></dependency>\n"
            "</dependencies></project>\n"
        )
        p = _proposal([_file("pom.xml", content)])
        assert validate_dependency_files(p, APPROVED).status == ASK

    def test_gradle_short_form(self):
        content = "dependencies {\n    implementation 'org.springframework:spring-core:6.1.0'\n    implementation \"com.badlib:badlib:1.0\"\n}\n"
        p = _proposal([_file("build.gradle", content)])
        r = validate_dependency_files(p, APPROVED)
        assert r.status == FAIL
        assert "com.badlib:badlib" in r.findings[0]["message"]

    def test_gradle_map_form(self):
        content = "dependencies {\n    api group: 'com.badlib', name: 'badlib', version: '1.0'\n}\n"
        p = _proposal([_file("build.gradle.kts", content)])
        assert validate_dependency_files(p, APPROVED).status == FAIL


class TestNuget:
    def test_csproj_package_reference(self):
        content = (
            "<Project><ItemGroup>\n"
            "  <PackageReference Include=\"Newtonsoft.Json\" Version=\"13.0.1\" />\n"
            "  <PackageReference Include=\"BadLib\" Version=\"1.0.0\" />\n"
            "</ItemGroup></Project>\n"
        )
        p = _proposal([_file("backend/App.csproj", content)])
        r = validate_dependency_files(p, APPROVED)
        assert r.status == FAIL
        assert "BadLib" in r.findings[0]["message"]

    def test_packages_config(self):
        content = (
            "<packages>\n"
            "  <package id=\"Newtonsoft.Json\" version=\"13.0.1\" targetFramework=\"net48\" />\n"
            "  <package id=\"BadLib\" version=\"1.0.0\" targetFramework=\"net48\" />\n"
            "</packages>\n"
        )
        p = _proposal([_file("packages.config", content)])
        r = validate_dependency_files(p, APPROVED)
        assert r.status == FAIL
        assert "BadLib" in r.findings[0]["message"]


class TestPub:
    def test_pubspec_dependencies_checked(self):
        content = (
            "name: demo\n"
            "dependencies:\n"
            "  flutter:\n"
            "    sdk: flutter\n"
            "  http: ^0.13.0\n"
            "  bad_pkg: ^1.0.0\n"
            "\n"
            "dev_dependencies:\n"
            "  flutter_test:\n"
            "    sdk: flutter\n"
        )
        p = _proposal([_file("pubspec.yaml", content)])
        r = validate_dependency_files(p, APPROVED)
        assert r.status == FAIL
        messages = " ".join(f["message"] for f in r.findings)
        assert "bad_pkg" in messages and "flutter_test" in messages
        assert "http" not in [f.get("package") for f in r.findings]

    def test_pubspec_unrelated_top_level_keys_are_ignored(self):
        content = "name: demo\nenvironment:\n  sdk: '>=3.0.0 <4.0.0'\n"
        p = _proposal([_file("pubspec.yaml", content)])
        assert validate_dependency_files(p, APPROVED).status == PASS


class TestNonDependencyFiles:
    def test_unrelated_files_are_ignored(self):
        p = _proposal([_file("src/main.py", "import os\n")])
        assert validate_dependency_files(p, APPROVED).status == PASS

    def test_every_bad_dependency_is_reported_not_just_the_first(self):
        content = '{"dependencies": {"left-pad": "1.0.0", "is-odd": "1.0.0"}}'
        p = _proposal([_file("package.json", content)])
        assert len(validate_dependency_files(p, APPROVED).findings) == 2
