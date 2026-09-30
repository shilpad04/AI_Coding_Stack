"""
scripts/validators/__init__.py  -  All TSG governance validator logic in one place.

Validators are called at two gates during a run:

  Gate 1 (before anything is written to disk)
    validate_structure() RULE-CODE-001    proposal entries well-formed? (runs first)
    preflight()          RULE-ASSUME-001  required decisions present?
    validate_rules()     RULE-ASSUME-001  model asked a clarification?
    validate_scope()     RULE-SCOPE-001   only task-allowed files touched?
    validate_packages()  RULE-DEP-001/2   approved packages + hidden imports
    validate_dependency_files() RULE-DEP-001/2  every manifest file's dependencies
    validate_commands()  RULE-EXEC-*      classify shell commands before run
    validate_secrets()   RULE-SEC-001     no credentials in proposed code
    validate_changes()   RULE-CODE-001    complete + parseable files
    validate_tests_present() RULE-TEST-001 source changes come with a test file
    validate_acceptance_criteria() RULE-PLAN-002 the plan task has acceptance criteria

  Gate 2 (after the system has written the files)
    validate_reconcile() RULE-SCOPE-002   disk must match what was approved

Backward-compatible sub-module shims at the bottom preserve the old import
style so orchestrator and tests need zero changes:
  from validators import scope as v_scope   # still works
  v_scope.validate(proposal, task)          # still works
"""

import ast
import hashlib
import json
import re
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path

PASS, FAIL, ASK = "PASS", "FAIL", "ASK"


@dataclass
class Result:
    """Container for a single validator's outcome."""

    name: str
    status: str = PASS
    findings: list = field(default_factory=list)

    def add(self, status: str, rule: str, message: str, **detail) -> "Result":
        """Add a finding; FAIL beats ASK beats PASS."""
        order = {PASS: 0, ASK: 1, FAIL: 2}
        if order[status] > order[self.status]:
            self.status = status
        self.findings.append({"rule": rule, "status": status,
                               "message": message, **detail})
        return self

    @property
    def ok(self) -> bool:
        return self.status == PASS

    @property
    def blocked(self) -> bool:
        return self.status == FAIL

    def messages(self) -> list:
        return [f"{f['rule']}: {f['message']}" for f in self.findings]


def combine(results: list) -> str:
    """Return the highest-severity status across a list of Results."""
    order = {PASS: 0, ASK: 1, FAIL: 2}
    overall = PASS
    for r in results:
        if order[r.status] > order[overall]:
            overall = r.status
    return overall


# ---------------------------------------------------------------------------
# Gate 1 validators
# ---------------------------------------------------------------------------

def preflight(task: dict, required_decisions: list) -> Result:
    """Run before the model is called.

    Checks that every architectural decision required by the active skills
    is stated somewhere in the task description, acceptance criteria, or
    the project context.

    Args:
        task: The task dict (task_id, description, acceptance_criteria, etc.)
        required_decisions: List of decision token strings that must appear.

    Returns:
        Result with ASK findings for any missing decisions.
    """
    r = Result("preflight")
    haystack = " ".join([
        task.get("description", ""),
        " ".join(task.get("acceptance_criteria", [])),
        " ".join(task.get("known_decisions", {}).keys()) if isinstance(
            task.get("known_decisions"), dict) else "",
        " ".join(task.get("known_decisions", [])) if isinstance(
            task.get("known_decisions"), list) else "",
    ]).lower()
    for decision in required_decisions:
        token = decision.replace("_", " ")
        if token not in haystack and decision.lower() not in haystack:
            r.add(ASK, "RULE-ASSUME-001",
                  f"required decision not stated for this task: {decision}",
                  decision=decision)
    return r


def validate_rules(proposal) -> Result:
    """Run on the returned proposal.

    Checks whether the model flagged missing information via clarifications.

    Args:
        proposal: Proposal object with .needs_clarification and .clarifications.

    Returns:
        Result with ASK findings for each clarification question.
    """
    r = Result("rules")
    if proposal.needs_clarification:
        for c in proposal.clarifications:
            r.add(ASK, "RULE-ASSUME-001",
                  f"clarification required: {c.get('question')}",
                  why_needed=c.get("why_needed"))
    return r


_VALID_ACTIONS = ("create", "modify", "delete")
# Files that are normally empty on purpose; every other file needs real content.
_MAY_BE_EMPTY = {"__init__.py", ".gitkeep"}
_PROPOSAL_SHAPE_HINT = (
    'Each entry in "files" must be {"path": "<file>", "action": "create|modify|delete", '
    '"content": "<full file text>"} (delete needs no content).'
)


def validate_structure(proposal) -> Result:
    """Run first: is the proposal shaped correctly, entry by entry?

    Later validators read entry["path"], entry["action"] and so on directly, so
    a malformed entry (usual with smaller models) would crash them. This check
    turns each such mistake into a plain FAIL message the model can act on.

    Args:
        proposal: Proposal object with .files, .packages, .commands and
            .clarifications.

    Returns:
        Result with a RULE-CODE-001 FAIL for every malformed entry.
    """
    r = Result("structure")

    def bad(message: str) -> None:
        r.add(FAIL, "RULE-CODE-001", f"{message} {_PROPOSAL_SHAPE_HINT}")

    if not isinstance(proposal.files, list):
        bad('"files" must be a list.')
        return r
    for n, f in enumerate(proposal.files, start=1):
        if not isinstance(f, dict):
            bad(f"files entry {n} must be an object, not plain text.")
            continue
        path, action, content = f.get("path"), f.get("action"), f.get("content")
        if not isinstance(path, str) or not path.strip():
            bad(f'files entry {n} has no "path".')
            continue
        if action not in _VALID_ACTIONS:
            bad(f'{path}: "action" is {action!r}; it must be create, modify or delete.')
        elif action != "delete" and not (isinstance(content, str) and (
                content.strip() or Path(path).name in _MAY_BE_EMPTY)):
            bad(f'{path}: "content" is missing or empty; give the full file text.')

    for label, items, key in (("packages", proposal.packages, "name"),
                              ("commands", proposal.commands, "command"),
                              ("clarifications", proposal.clarifications, "question")):
        if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
            bad(f'"{label}" must be a list of objects (each with "{key}").')
    return r


PROTECTED_GOVERNANCE_FILES = {
    "config/approved-packages.yaml",
    "config/command-policy.yaml",
    "config/config.yaml",
    "scripts/validate_proposal.py",
    "scripts/validators/__init__.py",
    "scripts/approve_plan.py",
    ".ai/plan-approval.json",
    "AGENTS.md",
    "rules.md",
    "context.md",
    "CLAUDE.md",

}


def validate_scope(proposal, task: dict) -> Result:
    """Block out-of-scope files and require human approval (ASK) for protected governance files.

    Args:
        proposal: Proposal object with .files list.
        task: The task dict containing 'allowed_files'.

    Returns:
        Result with FAIL findings for out-of-scope paths and ASK findings for protected governance files.
    """
    r = Result("scope")
    allowed = set(task.get("allowed_files", []))

    for f in proposal.files:
        path = f["path"].replace("\\", "/")

        # Guard: Protected governance files require explicit human approval (ASK / Exit 2)
        if path in PROTECTED_GOVERNANCE_FILES:
            r.add(ASK, "RULE-GOV-001",
                  f"attempted to modify protected governance file '{path}'. Human approval required.",
                  path=path)
            continue

        if path not in allowed:
            r.add(FAIL, "RULE-SCOPE-001",
                  f"{path} is not in the task's allowed files",
                  path=path, allowed=sorted(allowed))
    return r


# ---- Package validator helpers ----

# --- Python ---
_PY_IMPORT_RE = re.compile(
    r"^\s*(?:import\s+([A-Za-z0-9_.]+)|from\s+([A-Za-z0-9_.]+)\s+import)",
    re.M,
)
try:
    _PY_STDLIB = set(sys.stdlib_module_names)
except AttributeError:
    _PY_STDLIB = {"os", "sys", "re", "json", "pathlib", "typing", "dataclasses",
                   "ast", "hashlib", "types", "abc", "collections", "functools",
                   "itertools", "logging", "math", "random", "string", "time",
                   "datetime", "uuid", "enum", "copy", "io", "subprocess"}

# --- JavaScript / TypeScript ---
_JS_IMPORT_RE = re.compile(
    r"""
    (?:
        # ES module: import ... from 'pkg'
        \bimport\b.*?\bfrom\s+['"]([A-Za-z0-9_.@/][A-Za-z0-9_.@/-]*)['"]  
        |
        # CommonJS: require('pkg')
        \brequire\s*\(\s*['"]([A-Za-z0-9_.@/][A-Za-z0-9_.@/-]*)['"]  
    )
    """,
    re.M | re.X,
)
_NODE_STDLIB = {
    "assert", "buffer", "child_process", "cluster", "console", "crypto",
    "dgram", "dns", "domain", "events", "fs", "http", "http2", "https",
    "inspector", "module", "net", "os", "path", "perf_hooks", "process",
    "punycode", "querystring", "readline", "repl", "stream", "string_decoder",
    "timers", "tls", "tty", "url", "util", "v8", "vm", "worker_threads", "zlib",
}

# --- Go ---
_GO_IMPORT_RE = re.compile(
    r'import\s+(?:"([^"]+)"|`([^`]+)`|\(([^)]*)\))',
    re.M | re.S,
)
_GO_STDLIB_PREFIXES = {
    "archive", "bufio", "builtin", "bytes", "compress", "container",
    "context", "crypto", "database", "debug", "encoding", "errors",
    "expvar", "flag", "fmt", "go", "hash", "html", "image", "index",
    "io", "log", "math", "mime", "net", "os", "path", "plugin",
    "reflect", "regexp", "runtime", "sort", "strconv", "strings",
    "sync", "syscall", "testing", "text", "time", "unicode", "unsafe",
}

# --- Java ---
_JAVA_IMPORT_RE = re.compile(
    r"^\s*import\s+(?:static\s+)?([A-Za-z0-9_.]+)\s*;",
    re.M,
)
_JAVA_STDLIB_PREFIXES = {"java", "javax", "sun", "com.sun", "org.w3c", "org.xml"}


# Keep the old name as an alias so any external code that imports it directly
# continues to work; new code should use _extract_imports() instead.
_IMPORT_RE = _PY_IMPORT_RE
_STDLIB    = _PY_STDLIB


def _extract_imports(content: str, path: str) -> set:
    """Extract third-party module/package names from source file content.

    Dispatches by file extension.  Returns an empty set for file types that
    are not recognised, rather than raising an error.

    Args:
        content: Full source code text of the file.
        path: Relative file path — extension determines which parser is used.

    Returns:
        Set of top-level module/package names that appear to be third-party.
        Standard-library imports are excluded from the result.
    """
    ext = Path(path).suffix.lower() if path else ""

    if ext == ".py":
        mods: set = set()
        for m in _PY_IMPORT_RE.finditer(content):
            mod = (m.group(1) or m.group(2) or "").split(".")[0]
            if mod and mod not in _PY_STDLIB:
                mods.add(mod)
        return mods

    if ext in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
        mods = set()
        for m in _JS_IMPORT_RE.finditer(content):
            pkg = m.group(1) or m.group(2) or ""
            if not pkg or pkg.startswith("."):
                continue  # skip relative imports
            # Scoped packages: @scope/name  → keep both parts
            top = "/".join(pkg.split("/")[:2]) if pkg.startswith("@") else pkg.split("/")[0]
            if top and top not in _NODE_STDLIB:
                mods.add(top)
        return mods

    if ext == ".go":
        mods = set()
        for m in _GO_IMPORT_RE.finditer(content):
            block = m.group(3) or ""
            singles = [s for s in (m.group(1), m.group(2)) if s]
            all_paths = re.findall(r'"([^"]+)"', block) + singles
            for imp_path in all_paths:
                top = imp_path.split("/")[0]
                if top and top not in _GO_STDLIB_PREFIXES:
                    mods.add(imp_path)  # use full path for Go (e.g. github.com/gin-gonic/gin)
        return mods

    if ext == ".java":
        mods = set()
        for m in _JAVA_IMPORT_RE.finditer(content):
            fqn = m.group(1) or ""
            if fqn and not any(fqn.startswith(p) for p in _JAVA_STDLIB_PREFIXES):
                mods.add(fqn.split(".")[0])
        return mods

    # Unrecognised file type — cannot analyse imports safely.
    return set()


def _pkg_index(approved: list) -> tuple:
    by_name, by_module = {}, {}
    for p in approved:
        by_name[p["name"].lower()] = p
        if p.get("module"):
            by_module[p["module"]] = p
    return by_name, by_module


def _local_modules(task: dict, project_root=None) -> set:
    mods = set()
    for rel in task.get("allowed_files", []):
        parts = rel.replace("\\", "/").split("/")
        mods.add(parts[0])
        if parts[-1].endswith(".py"):
            mods.add(parts[-1][:-3])
    return mods


def validate_packages(proposal, task: dict, approved_packages: list, *,
                      block_unapproved: bool = True,
                      project_root=None) -> Result:
    """Check declared packages and hidden import statements in proposed files.

    Args:
        proposal: Proposal object with .packages and .files.
        task: The task dict (used to derive local module names).
        approved_packages: List of package entries from approved-packages.yaml.
        block_unapproved: If True, unknown packages -> FAIL; else -> ASK.
        project_root: Optional path to project root for local-module detection.

    Returns:
        Result with FAIL/ASK findings for policy violations.
    """
    r = Result("packages")
    by_name, by_module = _pkg_index(approved_packages)
    local = _local_modules(task, project_root)

    for pkg in proposal.packages:
        entry = by_name.get(str(pkg.get("name", "")).lower())
        if entry is None:
            r.add(FAIL if block_unapproved else ASK, "RULE-DEP-001",
                  f"package '{pkg.get('name')}' is not on the approved list",
                  package=pkg.get("name"))
        elif entry.get("status") == "needs_approval":
            r.add(ASK, "RULE-DEP-002",
                  f"package '{entry['name']}' is approved but needs human approval",
                  package=entry["name"], versions=entry.get("versions"))

    declared = {str(p.get("name", "")).lower() for p in proposal.packages}
    for f in proposal.files:
        content = f.get("content") or ""
        for module in _extract_imports(content, f["path"]):
            if module in local:
                continue
            entry = by_module.get(module) or by_name.get(module.lower())
            if entry is None:
                r.add(FAIL if block_unapproved else ASK, "RULE-DEP-001",
                      f"{f['path']} imports '{module}', which is not on the approved list",
                      path=f["path"], module=module)
            elif entry.get("status") == "needs_approval" and entry["name"].lower() not in declared:
                r.add(ASK, "RULE-DEP-002",
                      f"{f['path']} imports '{module}' ({entry['name']}), which needs approval",
                      path=f["path"], module=module)
    return r


# A command line can hold several commands. Split at every chaining character
# so an allowed first word cannot carry a second command through.
_CHAIN_SPLIT_RE = re.compile(r"[;&|\n]")
# $(...) and `...` run a hidden command that cannot be classified by its text.
_SUBSTITUTION_RE = re.compile(r"\$\(|`")
# A redirect can overwrite or feed a file (e.g. `ls > config/config.yaml`),
# bypassing scope and governance checks entirely. No ALLOW pattern uses one.
_REDIRECT_RE = re.compile(r"[<>]")
_POLICY_SEVERITY = {"ALLOW": 0, "ASK": 1, "BLOCK": 2}


def _classify_one(command: str, command_config: dict) -> tuple:
    """Return (policy, rule) for a single command with no chaining."""
    default = command_config.get("default", "BLOCK")
    for entry in command_config.get("commands", []):
        if re.match(entry["pattern"], command.strip()):
            return entry["policy"], entry.get("rule", "RULE-EXEC-001")
    return default, "RULE-EXEC-001"


# ---------------------------------------------------------------------------
# Dependency manifest files (RULE-DEP-001/002 applied to whole files, not
# just import statements). Every parser is best-effort and regex-based, the
# same approach as _extract_imports above: good enough to find declared
# package names, not a full parser for the format.
# ---------------------------------------------------------------------------

def _parse_package_json(content: str) -> set | None:
    """npm/Angular/React: dependencies, devDependencies, peer/optional."""
    try:
        data = json.loads(content)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    names: set = set()
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        deps = data.get(key)
        if isinstance(deps, dict):
            names.update(deps.keys())
    return names


def _parse_requirements_txt(content: str) -> set:
    """pip: one requirement per line; plain text, so nothing counts as unparseable."""
    names: set = set()
    for line in content.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        name = re.split(r"[<>=!~\[;\s]", line, maxsplit=1)[0].strip()
        if name:
            names.add(name)
    return names


_TOML_TABLE_RE = re.compile(r"^\[(?P<table>[^\]]+)\]\s*$")
_TOML_KEY_RE = re.compile(r'^([A-Za-z0-9_.\-]+)\s*=')
_POETRY_TABLES = {"tool.poetry.dependencies", "tool.poetry.dev-dependencies"}


def _parse_pyproject_toml(content: str) -> set:
    """pip: [tool.poetry.dependencies] table, or PEP 621 dependencies = [...]."""
    names: set = set()
    table = None
    in_array = False
    for raw in content.splitlines():
        line = raw.strip()
        match = _TOML_TABLE_RE.match(line)
        if match:
            table = match.group("table")
            in_array = False
            continue
        if table in _POETRY_TABLES or table is not None and table.startswith("tool.poetry.group."):
            key = _TOML_KEY_RE.match(line)
            if key and key.group(1).lower() != "python":
                names.add(key.group(1))
        elif table == "project":
            if line.startswith("dependencies") and "=" in line:
                in_array = "[" in line and "]" not in line
            if in_array or (line.startswith("dependencies") and "[" in line):
                for entry in re.findall(r'"([^"]+)"', line):
                    names.add(re.split(r"[<>=!~\[;\s]", entry, maxsplit=1)[0])
                if "]" in line:
                    in_array = False
    return names


_POM_DEP_RE = re.compile(r"<dependency>(.*?)</dependency>", re.S)
_POM_GROUP_RE = re.compile(r"<groupId>\s*([^<\s]+)\s*</groupId>")
_POM_ARTIFACT_RE = re.compile(r"<artifactId>\s*([^<\s]+)\s*</artifactId>")


def _parse_pom_xml(content: str) -> set:
    """Maven: <dependency><groupId>/<artifactId> as "group:artifact"."""
    names: set = set()
    for block in _POM_DEP_RE.findall(content):
        group = _POM_GROUP_RE.search(block)
        artifact = _POM_ARTIFACT_RE.search(block)
        if artifact:
            names.add(f"{group.group(1)}:{artifact.group(1)}" if group else artifact.group(1))
    return names


_GRADLE_CONFIGS = (r"(?:implementation|api|compile|testImplementation|"
                   r"androidTestImplementation|runtimeOnly|compileOnly)")
_GRADLE_SHORT_RE = re.compile(_GRADLE_CONFIGS + r"[\s(]+['\"]([^:'\"]+):([^:'\"]+):[^'\"]+['\"]")
_GRADLE_MAP_RE = re.compile(
    _GRADLE_CONFIGS + r"[\s(]+group:\s*['\"]([^'\"]+)['\"]\s*,\s*name:\s*['\"]([^'\"]+)['\"]")


def _parse_build_gradle(content: str) -> set:
    """Gradle: `implementation 'group:artifact:version'` or the map form."""
    names = {f"{g}:{a}" for g, a in _GRADLE_SHORT_RE.findall(content)}
    names |= {f"{g}:{a}" for g, a in _GRADLE_MAP_RE.findall(content)}
    return names


_CSPROJ_PKG_RE = re.compile(r'<PackageReference\s+[^>]*\bInclude\s*=\s*"([^"]+)"')
_PACKAGES_CONFIG_RE = re.compile(r'<package\s+[^>]*\bid\s*=\s*"([^"]+)"')


def _parse_csproj(content: str) -> set:
    """.NET (modern): <PackageReference Include="Name" .../>."""
    return set(_CSPROJ_PKG_RE.findall(content))


def _parse_packages_config(content: str) -> set:
    """.NET (legacy): <package id="Name" .../>."""
    return set(_PACKAGES_CONFIG_RE.findall(content))


_YAML_TOP_KEY_RE = re.compile(r"^(\S[^:]*):")
_YAML_NESTED_KEY_RE = re.compile(r"^\s{1,4}(\S[^:]*):")
_PUBSPEC_DEP_SECTIONS = {"dependencies", "dev_dependencies"}


def _parse_pubspec_yaml(content: str) -> set:
    """Flutter/Dart: keys nested under dependencies: / dev_dependencies:."""
    names: set = set()
    in_deps = False
    for line in content.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        if not line[0].isspace():
            top = _YAML_TOP_KEY_RE.match(line)
            in_deps = bool(top) and top.group(1).strip() in _PUBSPEC_DEP_SECTIONS
            continue
        if in_deps:
            nested = _YAML_NESTED_KEY_RE.match(line)
            if nested:
                names.add(nested.group(1).strip())
    return names


# filename -> (ecosystem, parser); .csproj is matched by suffix instead, since
# its basename varies (Api.csproj, Worker.csproj, ...).
_DEP_FILE_PARSERS = {
    "package.json": ("npm", _parse_package_json),
    "requirements.txt": ("pypi", _parse_requirements_txt),
    "pyproject.toml": ("pypi", _parse_pyproject_toml),
    "pom.xml": ("maven", _parse_pom_xml),
    "build.gradle": ("maven", _parse_build_gradle),
    "build.gradle.kts": ("maven", _parse_build_gradle),
    "packages.config": ("nuget", _parse_packages_config),
    "pubspec.yaml": ("pub", _parse_pubspec_yaml),
}
_DEP_FILE_SUFFIX_PARSERS = {".csproj": ("nuget", _parse_csproj)}


def _match_dependency_file(path: str):
    name = Path(path).name
    if name in _DEP_FILE_PARSERS:
        return _DEP_FILE_PARSERS[name]
    return _DEP_FILE_SUFFIX_PARSERS.get(Path(path).suffix.lower())


def _dep_pkg_index(approved: list) -> dict:
    return {(p.get("ecosystem"), p["name"].lower()): p for p in approved}


def validate_dependency_files(proposal, approved_packages: list, *,
                              block_unapproved: bool = True) -> Result:
    """Every dependency declared in a manifest file must be on the approved list.

    Covers package.json (npm/Angular/React), requirements.txt and
    pyproject.toml (pip), pom.xml and build.gradle (Maven/Gradle), .csproj
    and packages.config (.NET), and pubspec.yaml (Flutter). There is no
    partial pass: one unlisted dependency fails the whole file.

    Args:
        proposal: Proposal object with .files.
        approved_packages: List of package entries from approved-packages.yaml.
        block_unapproved: If True, an unlisted dependency is FAIL; else ASK.

    Returns:
        Result with FAIL/ASK findings per unapproved or needs-approval dependency.
    """
    r = Result("dependency_files")
    index = _dep_pkg_index(approved_packages)
    for f in proposal.files:
        if f.get("action") == "delete":
            continue
        match = _match_dependency_file(f.get("path", ""))
        if not match:
            continue
        ecosystem, parser = match
        names = parser(f.get("content") or "")
        if names is None:
            r.add(FAIL, "RULE-CODE-001",
                  f"{f['path']} could not be parsed, so its dependencies cannot be verified")
            continue
        for name in sorted(names):
            entry = index.get((ecosystem, name.lower()))
            if entry is None:
                r.add(FAIL if block_unapproved else ASK, "RULE-DEP-001",
                      f"{f['path']} declares '{name}' ({ecosystem}), which is not on the approved list",
                      path=f["path"], package=name, ecosystem=ecosystem)
            elif entry.get("status") == "needs_approval":
                r.add(ASK, "RULE-DEP-002",
                      f"{f['path']} declares '{name}' ({ecosystem}), which is approved but needs human approval",
                      path=f["path"], package=name, ecosystem=ecosystem)
    return r


def classify_command(command: str, command_config: dict) -> tuple:
    """Return (policy, rule) for a shell command string.

    A chained command (&&, ||, ;, |, &, newline) is split and every piece is
    classified on its own; the strictest result wins. Command substitution
    ($( ) or backticks) is always BLOCK, and so is any redirect (`>` or `<`).

    Args:
        command: The shell command string to classify.
        command_config: The loaded command-policy.yaml dict.

    Returns:
        Tuple of (policy, rule) where policy is ALLOW, ASK, or BLOCK.
    """
    if _SUBSTITUTION_RE.search(command):
        return "BLOCK", "RULE-EXEC-001"
    if _REDIRECT_RE.search(command):
        return "BLOCK", "RULE-EXEC-004"
    pieces = [p for p in _CHAIN_SPLIT_RE.split(command) if p.strip()] or [command]
    worst = None
    for piece in pieces:
        result = _classify_one(piece, command_config)
        if worst is None or (_POLICY_SEVERITY.get(result[0], 2)
                             > _POLICY_SEVERITY.get(worst[0], 2)):
            worst = result
    return worst


def validate_commands(proposal, command_config: dict) -> Result:
    """Classify every shell command in the proposal before anything runs.

    Args:
        proposal: Proposal object with .commands list.
        command_config: The loaded command-policy.yaml dict.

    Returns:
        Result with FAIL/ASK findings for blocked or needs-approval commands.
    """
    r = Result("commands")
    for c in proposal.commands:
        cmd = c.get("command", "")
        policy, rule = classify_command(cmd, command_config)
        if policy == "BLOCK":
            r.add(FAIL, rule, f"command is blocked by policy: {cmd}", command=cmd)
        elif policy == "ASK":
            r.add(ASK, rule, f"command needs human approval: {cmd}", command=cmd)
    return r


_SECRET_PATTERNS = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key id"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
    (re.compile(
        r"(?i)\b(aws_secret_access_key|api[_-]?key|secret[_-]?key|password|passwd)\b\s*[=:]\s*['\"][^'\"]{6,}['\"]"
    ), "hardcoded credential"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-_.]{20,}"), "bearer token"),
    # scheme://user:pass@host — a connection string with the password inline,
    # regardless of what the surrounding variable is called (DATABASE_URL, ...).
    (re.compile(r"[a-zA-Z][a-zA-Z0-9+.\-]*://[^\s:'\"/@]+:[^\s'\"/@]+@"),
     "connection string with embedded credentials"),
    (re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b"), "Google API key"),
    (re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b"), "Slack token"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
     "JSON Web Token"),
]


def validate_secrets(proposal) -> Result:
    """Fail if any proposed file appears to contain credentials.

    Args:
        proposal: Proposal object with .files list.

    Returns:
        Result with FAIL findings for any credential pattern detected.
    """
    r = Result("secrets")
    for f in proposal.files:
        content = f.get("content") or ""
        for pattern, label in _SECRET_PATTERNS:
            if pattern.search(content):
                r.add(FAIL, "RULE-SEC-001",
                      f"{f['path']} appears to contain a {label}", path=f["path"])
                break
    return r


_PLACEHOLDERS = [
    "rest of file unchanged", "... unchanged ...", "<unchanged>",
    "TODO: keep existing", "rest of the file",
]


def validate_changes(proposal) -> Result:
    """Reject truncated content; syntax-check Python files.

    Placeholder detection applies to all file types.
    Syntax validation is currently only performed for .py files using Python's
    built-in AST parser.  Other languages (TypeScript, Go, Java, etc.) require
    external tooling (tsc, go vet, javac) that is not available in this script.

    Args:
        proposal: Proposal object with .files list.

    Returns:
        Result with FAIL findings for placeholder text or Python syntax errors.
    """
    r = Result("changes")
    for f in proposal.files:
        if f["action"] == "delete":
            continue
        content = f.get("content") or ""
        low = content.lower()
        for ph in _PLACEHOLDERS:
            if ph.lower() in low:
                r.add(FAIL, "RULE-CODE-001",
                      f"{f['path']} contains a placeholder instead of full content",
                      path=f["path"])
                break
        if f["path"].endswith(".py"):
            # Syntax check only available for Python files.
            try:
                ast.parse(content)
            except SyntaxError as e:
                r.add(FAIL, "RULE-CODE-001",
                      f"{f['path']} is not valid Python: {e.msg} (line {e.lineno})",
                      path=f["path"])
    return r


# ---------------------------------------------------------------------------
# Tests must come with code (RULE-TEST-001) and tasks must have criteria
# (RULE-PLAN-002). Both turn a written rule into a block: the PRD-driven
# testing guideline in .agents/rules/code-standards.md.
# ---------------------------------------------------------------------------

_SOURCE_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".java", ".cs", ".dart"}
# test_x.py, x_test.py, x_test.dart, x.test.ts / x.spec.ts, XTest.java, XTests.cs
_TEST_NAME_RE = re.compile(
    r"(^test_.+\.py$|_test\.(py|dart)$|\.(test|spec)\.(ts|tsx|js|jsx|mjs|cjs)$|Tests?\.(java|cs)$)")
# tests/, test/, __tests__/, and .NET's Project.Tests/ (but not "latest/")
_TEST_DIR_RE = re.compile(r"(^|\.)(tests?|__tests__)$", re.I)
_NOT_SOURCE_NAMES = {"__init__.py", "conftest.py"}
_NOT_SOURCE_DIRS = {"migrations", "alembic", "generated", "node_modules"}


def _is_test_file(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    return bool(_TEST_NAME_RE.search(parts[-1])) or any(_TEST_DIR_RE.search(p) for p in parts[:-1])


def _is_source_file(path: str) -> bool:
    """A code file a test could reasonably be written for (not config, types,
    migrations or generated output)."""
    parts = path.replace("\\", "/").split("/")
    name = parts[-1]
    if Path(name).suffix.lower() not in _SOURCE_EXTS:
        return False
    if name in _NOT_SOURCE_NAMES or name.endswith(".d.ts") or ".config." in name:
        return False
    if any(p in _NOT_SOURCE_DIRS for p in parts[:-1]):
        return False
    return not _is_test_file(path)


def validate_tests_present(proposal) -> Result:
    """RULE-TEST-001: a proposal that changes source files must also create or
    modify at least one test file.

    Deliberately per proposal, not per file: pairing each source file with a
    named test file would break on every framework's own convention. Deleting
    a test does not count as adding one.

    Args:
        proposal: Proposal object with .files (entries already shape-checked).

    Returns:
        Result with a FAIL when source files change with no test file alongside.
    """
    r = Result("tests_present")
    changed = [f["path"].replace("\\", "/") for f in proposal.files if f.get("action") != "delete"]
    sources = [p for p in changed if _is_source_file(p)]
    if sources and not any(_is_test_file(p) for p in changed):
        shown = ", ".join(sources[:3]) + (" ..." if len(sources) > 3 else "")
        r.add(FAIL, "RULE-TEST-001",
              f"proposal changes source file(s) ({shown}) but includes no test file. Add or update a "
              "test that proves this task's acceptance criteria. If nothing here has behaviour to "
              "test (e.g. a pure refactor), a human must approve it instead.",
              paths=sources)
    return r


# ---------------------------------------------------------------------------
# Database rules (RULE-DB-001, RULE-DB-002 in rules.md)
# ---------------------------------------------------------------------------

_MIGRATION_DIRS = {"migrations", "alembic"}
# The ORM model a schema change edits belongs with its migration, not with a feature.
_MODEL_DIRS = {"models", "entities"}
_MODEL_NAME_RE = re.compile(r"(^models?\.py$|\.(model|entity)\.(ts|js)$)")
_AUTO_SCHEMA_PATTERNS = [
    (re.compile(r"\bcreate_all\s*\("), "create_all()"),
    (re.compile(r"\bsynchronize['\"]?\s*[:=]\s*true\b"), "synchronize: true"),
    (re.compile(r"\bsequelize\.sync\s*\("), "sequelize.sync()"),
    (re.compile(r"\bprisma\s+db\s+push\b"), "prisma db push"),
]


def _is_model_file(path: str) -> bool:
    parts = path.split("/")
    return bool(_MODEL_NAME_RE.search(parts[-1])) or any(p in _MODEL_DIRS for p in parts[:-1])


def validate_database(proposal) -> Result:
    """RULE-DB-001: a migration is never bundled with feature code.
    RULE-DB-002: schema comes from migrations only, never ORM auto-create/sync.

    Args:
        proposal: Proposal object with .files (entries already shape-checked).

    Returns:
        Result with FAIL findings for either rule.
    """
    r = Result("database")
    changed = [f for f in proposal.files if f.get("action") != "delete"]

    for f in changed:
        if f["path"].lower().endswith(".md"):
            continue  # docs may name the forbidden calls
        content = f.get("content") or ""
        for pattern, label in _AUTO_SCHEMA_PATTERNS:
            if pattern.search(content):
                r.add(FAIL, "RULE-DB-002",
                      f"{f['path']} uses {label}. Schema must come from migration files only.",
                      path=f["path"])
                break

    paths = [f["path"].replace("\\", "/") for f in changed]
    migrations = [p for p in paths if any(d in _MIGRATION_DIRS for d in p.split("/")[:-1])]
    features = [p for p in paths if _is_source_file(p) and not _is_model_file(p)]
    if migrations and features:
        shown = ", ".join(features[:3]) + (" ..." if len(features) > 3 else "")
        r.add(FAIL, "RULE-DB-001",
              f"proposal bundles a migration with feature code ({shown}). A schema change is "
              "its own task: split it into two tasks, migration first.",
              paths=features)
    return r


def validate_acceptance_criteria(task: dict) -> Result:
    """RULE-PLAN-002: a plan task needs at least one non-blank acceptance
    criterion, or no test can be derived from the PRD for it.

    Args:
        task: The task dict from .ai/plan.json.

    Returns:
        Result with a FAIL when acceptance_criteria is missing, not a list, or
        holds no non-blank text.
    """
    r = Result("acceptance_criteria")
    criteria = task.get("acceptance_criteria")
    if not (isinstance(criteria, list) and any(isinstance(c, str) and c.strip() for c in criteria)):
        r.add(FAIL, "RULE-PLAN-002",
              f"task '{task.get('task_id')}' has no acceptance criteria in .ai/plan.json. Add at least "
              "one testable criterion (AGENTS.md Step 1) so tests can be derived from it.")
    return r


# ---------------------------------------------------------------------------
# Gate 2 validator
# ---------------------------------------------------------------------------

def _sha256_short(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def validate_reconcile(changes, proposal, after_snapshot: dict) -> Result:
    """Gate 2: what is on disk must be exactly what was approved.

    The system wrote the files itself, so this catches interference:
    a developer editing in the IDE mid-run, a partial write, or anything
    else on the machine touching the project.

    Args:
        changes: Object with .all_paths listing every path that changed on disk.
        proposal: The approved proposal with .files.
        after_snapshot: Dict mapping path -> {hash, ...} taken after writing.

    Returns:
        Result with FAIL findings for any disk/approval mismatches.
    """
    r = Result("reconcile")
    expected_write  = {f["path"] for f in proposal.files if f["action"] != "delete"}
    expected_delete = {f["path"] for f in proposal.files if f["action"] == "delete"}
    expected = expected_write | expected_delete
    actual   = set(changes.all_paths)

    for path in sorted(actual - expected):
        r.add(FAIL, "RULE-SCOPE-002",
              f"{path} changed on disk but was not part of the approved proposal",
              path=path)
    for path in sorted(expected - actual):
        r.add(FAIL, "RULE-SCOPE-002",
              f"{path} was approved but no change was detected on disk", path=path)

    for f in proposal.files:
        if f["action"] == "delete":
            if f["path"] in after_snapshot:
                r.add(FAIL, "RULE-SCOPE-002",
                      f"{f['path']} was approved for deletion but still exists",
                      path=f["path"])
            continue
        meta = after_snapshot.get(f["path"])
        if meta and meta["hash"] != _sha256_short(f["content"]):
            r.add(FAIL, "RULE-SCOPE-002",
                  f"{f['path']} on disk does not match the approved content",
                  path=f["path"])
    return r


# ---------------------------------------------------------------------------
# Backward-compatible sub-module shims
# ---------------------------------------------------------------------------

result    = types.SimpleNamespace(Result=Result, PASS=PASS, FAIL=FAIL, ASK=ASK,
                                   combine=combine)
rules     = types.SimpleNamespace(preflight=preflight, validate=validate_rules)
scope     = types.SimpleNamespace(validate=validate_scope)
packages  = types.SimpleNamespace(validate=validate_packages)
commands  = types.SimpleNamespace(validate=validate_commands,
                                   classify=classify_command)
secrets   = types.SimpleNamespace(validate=validate_secrets)
changes   = types.SimpleNamespace(validate=validate_changes)
reconcile = types.SimpleNamespace(validate=validate_reconcile)
