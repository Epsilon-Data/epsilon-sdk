"""
Static checks that run before a job is submitted.

These are the cheap, deterministic half of the submission gate, run locally so
a researcher sees a file and a line number while they can still act on it,
rather than a rejection verdict after the job has been queued.

Nothing here calls a model. Every rule is an AST or regex check with a fixed
answer, which means it is fast enough to run on every build and identical
between the researcher's machine and the server.
"""
from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass
from typing import List, Optional, Set

BLOCK = "BLOCK"
WARN = "WARN"

# Directories that never contain researcher-authored analysis code.
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".idea",
             ".epsilon", "build", "dist", "node_modules", ".mypy_cache"}

# Modules that would let an analysis reach off the machine. Inside an enclave
# there is nowhere legitimate to reach.
NETWORK_MODULES = {"socket", "requests", "urllib", "urllib2", "urllib3", "http",
                   "httplib", "httpx", "aiohttp", "ftplib", "smtplib",
                   "telnetlib", "paramiko", "boto3", "botocore", "pycurl"}

# Modules that execute other programs or arbitrary code.
EXEC_MODULES = {"subprocess", "pty", "multiprocessing"}
EXEC_BUILTINS = {"eval", "exec", "compile", "__import__"}

MAX_SCAN_BYTES = 2 * 1024 * 1024

# Specific, high-confidence credential shapes. A hit here is a hard stop:
# `epsilon build` packages the tree and ships it to the coordinator.
SECRET_PATTERNS = [
    ("anthropic-key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9]{32,}")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("private-key", re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----")),
]

# Looser shape, reported as a warning because it false-positives on examples.
ASSIGNED_SECRET = re.compile(
    r"""(?i)\b(api[_-]?key|secret|token|password|passwd)\b\s*[:=]\s*['"][^'"]{16,}['"]""")

SECRET_SCAN_EXTENSIONS = {".py", ".yml", ".yaml", ".json", ".ini", ".cfg", ".toml",
                          ".env", ".txt", ".md", ".sh", ".ipynb"}

# Dotfiles defeat an extension allowlist: os.path.splitext(".env") returns
# (".env", "") and ".env.local" yields ".local". These are exactly the files
# credentials live in, so they are matched by name.
SECRET_SCAN_FILENAMES = {".env", ".envrc", ".netrc", ".npmrc", ".pypirc",
                         ".pgpass", ".htpasswd", "credentials", ".credentials",
                         "secrets", ".secrets"}

# Files that hold environment configuration are worth flagging on sight: they
# are where a key goes, and they have no business in a package that is shipped
# to the coordinator even when this scan recognises nothing inside.
ENV_FILE_PREFIX = ".env"


@dataclass
class Finding:
    rule: str
    level: str
    path: str
    line: int
    message: str
    fix: Optional[str] = None

    @property
    def blocking(self) -> bool:
        return self.level == BLOCK

    def format(self) -> str:
        location = "{0}:{1}".format(self.path, self.line) if self.line else self.path
        out = "{0}  {1}  {2}".format(self.level, location, self.message)
        if self.fix:
            out += "\n      -> " + self.fix
        return out


class _SourceVisitor(ast.NodeVisitor):
    """Walk one module, collecting disclosure and safety findings."""

    def __init__(self, path: str):
        self.path = path
        self.findings: List[Finding] = []
        # Names bound to a record while iterating the dataset. Printing one of
        # these emits raw rows, which is the single most common reason an
        # output is held at release review.
        self.record_names: Set[str] = set()
        self.dataset_names: Set[str] = set()

    # -- imports ---------------------------------------------------------

    def visit_Import(self, node):
        for alias in node.names:
            self._check_module(alias.name, node.lineno)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.module:
            self._check_module(node.module, node.lineno)
        self.generic_visit(node)

    def _check_module(self, name: str, lineno: int) -> None:
        root = name.split(".")[0]
        if root in NETWORK_MODULES:
            self.findings.append(Finding(
                "no-network", BLOCK, self.path, lineno,
                "imports '{0}': analyses run with no network and any egress "
                "attempt is a policy violation".format(name),
                "remove the import; fetch what you need before submitting"))
        elif root in EXEC_MODULES:
            self.findings.append(Finding(
                "no-subprocess", BLOCK, self.path, lineno,
                "imports '{0}': running other programs inside the enclave is "
                "not permitted".format(name),
                "express the work in Python"))

    # -- dataset tracking ------------------------------------------------

    def visit_Assign(self, node):
        if self._is_dataset_call(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.dataset_names.add(target.id)
        self.generic_visit(node)

    def _is_dataset_call(self, node) -> bool:
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        if isinstance(func, ast.Name):
            return func.id == "create_dataset"
        if isinstance(func, ast.Attribute):
            return func.attr == "create_dataset"
        return False

    def visit_For(self, node):
        iterating_records = (
            (isinstance(node.iter, ast.Name) and node.iter.id in self.dataset_names)
            or self._is_dataset_call(node.iter)
        )
        if iterating_records and isinstance(node.target, ast.Name):
            self.record_names.add(node.target.id)
        self.generic_visit(node)

    # -- calls -----------------------------------------------------------

    def visit_Call(self, node):
        func = node.func
        if isinstance(func, ast.Name):
            if func.id == "print":
                self._check_print(node)
            elif func.id in EXEC_BUILTINS and func.id != "compile":
                self.findings.append(Finding(
                    "no-dynamic-exec", BLOCK, self.path, node.lineno,
                    "calls {0}(): dynamic execution cannot be reviewed".format(func.id),
                    "write the operation directly"))
        elif isinstance(func, ast.Attribute):
            if func.attr in ("system", "popen") and isinstance(func.value, ast.Name) \
                    and func.value.id == "os":
                self.findings.append(Finding(
                    "no-subprocess", BLOCK, self.path, node.lineno,
                    "calls os.{0}(): running other programs inside the enclave "
                    "is not permitted".format(func.attr), None))
            if func.attr in ("to_csv", "to_json", "to_pickle", "to_parquet"):
                self.findings.append(Finding(
                    "check-output-shape", WARN, self.path, node.lineno,
                    "writes a dataframe with .{0}(): make sure it holds "
                    "aggregates, not rows".format(func.attr),
                    "aggregate and apply the suppression threshold first"))
        self.generic_visit(node)

    def _check_print(self, node) -> None:
        for arg in node.args:
            name = self._root_name(arg)
            if name and name in self.record_names:
                shown = self._expression(arg) or name
                self.findings.append(Finding(
                    "no-record-output", BLOCK, self.path, node.lineno,
                    "prints '{0}', which is per-record: one line is released "
                    "per row".format(shown),
                    "accumulate into a counter and print the aggregate"))
                return
            if name and name in self.dataset_names:
                self.findings.append(Finding(
                    "no-record-output", BLOCK, self.path, node.lineno,
                    "prints the dataset itself: this releases raw rows",
                    "print len(dataset) or an aggregate"))
                return

    def _expression(self, node) -> Optional[str]:
        """Reconstruct a dotted expression for the message, e.g. record.patient.age."""
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if not isinstance(node, ast.Name):
            return None
        parts.append(node.id)
        return ".".join(reversed(parts))

    def _root_name(self, node) -> Optional[str]:
        """The base name of an expression: record.patient.age -> 'record'."""
        while isinstance(node, (ast.Attribute, ast.Subscript)):
            node = node.value
        if isinstance(node, ast.Name):
            return node.id
        return None


def check_source(path: str, source: str) -> List[Finding]:
    """Run the AST rules over one Python module."""
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return [Finding("parse-error", BLOCK, path, exc.lineno or 0,
                        "cannot be parsed: {0}".format(exc.msg),
                        "fix the syntax error; unparseable files cannot be reviewed")]
    visitor = _SourceVisitor(path)
    visitor.visit(tree)
    # A second pass catches prints that appear before the loop is visited,
    # which happens when helpers are defined above main().
    if visitor.record_names or visitor.dataset_names:
        again = _SourceVisitor(path)
        again.record_names = set(visitor.record_names)
        again.dataset_names = set(visitor.dataset_names)
        again.visit(tree)
        seen = set((f.rule, f.line) for f in visitor.findings)
        for finding in again.findings:
            if (finding.rule, finding.line) not in seen:
                visitor.findings.append(finding)
    return visitor.findings


def check_requirements(path: str, display_path: Optional[str] = None) -> List[Finding]:
    """Every dependency must be pinned, or the enclave build is not reproducible.

    `path` is read; `display_path` is what findings are reported against, so a
    scan rooted anywhere still reports project-relative locations.
    """
    findings = []
    display_path = display_path or path
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return findings
    for i, raw in enumerate(lines, start=1):
        line = raw.split("#")[0].strip()
        if not line or line.startswith("-"):
            continue
        if "==" in line or line.startswith(("http://", "https://", "git+")):
            continue
        findings.append(Finding(
            "pin-dependencies", WARN, display_path, i,
            "'{0}' is not pinned to an exact version".format(line),
            "pin it, e.g. {0}==1.2.3, so the enclave build is reproducible".format(
                re.split(r"[<>=!~\[]", line)[0])))
    return findings


def should_scan_secrets(path: str) -> bool:
    """Whether a file is worth reading for credentials."""
    name = os.path.basename(path).lower()
    if name in SECRET_SCAN_FILENAMES or name.startswith(ENV_FILE_PREFIX):
        return True
    return os.path.splitext(name)[1] in SECRET_SCAN_EXTENSIONS


def scan_secrets(path: str, text: str) -> List[Finding]:
    """Look for credentials in anything that would be packaged and shipped."""
    findings = []
    name = os.path.basename(path).lower()
    if name.startswith(ENV_FILE_PREFIX) or name in SECRET_SCAN_FILENAMES:
        findings.append(Finding(
            "no-secrets", WARN, path, 0,
            "an environment file is inside the project: 'epsilon build' "
            "packages this tree and ships it to the coordinator",
            "keep configuration out of the project directory, and add it to "
            ".gitignore"))
    for i, line in enumerate(text.splitlines(), start=1):
        for name, pattern in SECRET_PATTERNS:
            if pattern.search(line):
                findings.append(Finding(
                    "no-secrets", BLOCK, path, i,
                    "looks like a credential ({0}): 'epsilon build' packages "
                    "this tree and ships it to the coordinator".format(name),
                    "remove it; configure keys with 'epsilon ai login' or an "
                    "environment variable, never in the project directory"))
                break
        else:
            if ASSIGNED_SECRET.search(line):
                findings.append(Finding(
                    "no-secrets", WARN, path, i,
                    "assigns a long literal to a secret-looking name",
                    "if it is a credential, move it out of the project tree"))
    return findings


def local_modules(project_dir: str) -> Set[str]:
    """Top-level importable names the project itself defines."""
    names = set()
    try:
        entries = os.listdir(project_dir)
    except OSError:
        return names
    for entry in entries:
        if entry in SKIP_DIRS or entry.startswith("."):
            continue
        path = os.path.join(project_dir, entry)
        if os.path.isdir(path) and os.path.exists(os.path.join(path, "__init__.py")):
            names.add(entry)
        elif entry.endswith(".py"):
            names.add(entry[:-3])
    return names


def _imported_names(source: str) -> Set[str]:
    names = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return names
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names


def check_packaging(project_dir: str, entry_point: str,
                    packaged: Set[str]) -> List[Finding]:
    """Catch local imports that would not survive being packaged.

    `epsilon build` ships a subset of the project. A helper module the
    researcher wrote and imported, but which is not in that subset, fails at
    import time inside the enclave -- after the queue, after the middleware
    hand-off, with a traceback the researcher cannot see the data behind. It is
    a cheap thing to catch here.
    """
    findings: List[Finding] = []
    available = local_modules(project_dir)
    entry_name = os.path.splitext(os.path.basename(entry_point))[0]
    shipped = set(packaged) | {entry_name}

    to_scan = [entry_point]
    for name in sorted(packaged):
        directory = os.path.join(project_dir, name)
        if os.path.isdir(directory):
            for root, dirs, files in os.walk(directory):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                to_scan.extend(os.path.join(root, f)
                               for f in files if f.endswith(".py"))

    seen = set()
    for relative in to_scan:
        path = os.path.join(project_dir, relative) \
            if not os.path.isabs(relative) else relative
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                source = fh.read()
        except (OSError, UnicodeDecodeError):
            continue
        for name in _imported_names(source):
            if name in available and name not in shipped and name not in seen:
                seen.add(name)
                findings.append(Finding(
                    "unpackaged-import", BLOCK,
                    os.path.relpath(path, project_dir), 0,
                    "imports local module '{0}', which 'epsilon build' does "
                    "not package: it would fail at import time in the "
                    "enclave".format(name),
                    "move the code into {0}/, or into the entry point".format(
                        sorted(packaged)[0] if packaged else "the entry point")))
    return findings


def _iter_files(project_dir: str):
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            yield os.path.join(root, name)


def check_project(project_dir: str = ".",
                  skip_generated: bool = True) -> List[Finding]:
    """Run every static rule over a project directory.

    Generated code is excluded from the AST rules -- the researcher did not
    write it -- but never from the secret scan, because it is packaged too.
    """
    findings: List[Finding] = []
    for path in _iter_files(project_dir):
        rel = os.path.relpath(path, project_dir)
        parts = rel.split(os.sep)
        in_generated = parts and parts[0] == "generated"
        ext = os.path.splitext(path)[1].lower()

        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        if size > MAX_SCAN_BYTES:
            continue

        if ext == ".py" and not (skip_generated and in_generated):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    source = fh.read()
            except (OSError, UnicodeDecodeError):
                continue
            findings.extend(check_source(rel, source))

        if os.path.basename(path) in ("requirements.txt", "requirements-dev.txt"):
            findings.extend(check_requirements(path, rel))

        if should_scan_secrets(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    text = fh.read()
            except (OSError, UnicodeDecodeError):
                continue
            findings.extend(scan_secrets(rel, text))

    findings.sort(key=lambda f: (0 if f.blocking else 1, f.path, f.line))
    return findings


def summarise(findings: List[Finding]) -> str:
    blocking = [f for f in findings if f.blocking]
    warnings = [f for f in findings if not f.blocking]
    if not findings:
        return "All checks passed."
    parts = []
    if blocking:
        parts.append("{0} blocking issue{1}".format(
            len(blocking), "" if len(blocking) == 1 else "s"))
    if warnings:
        parts.append("{0} warning{1}".format(
            len(warnings), "" if len(warnings) == 1 else "s"))
    return ", ".join(parts) + "."
