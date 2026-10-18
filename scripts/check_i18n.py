"""Find user-facing text that bypasses gettext and check the English catalog.

Usage: ``uv run python scripts/check_i18n.py [--no-catalog] [PATH ...]``

Source check: every string literal that reads as natural language must reach the user
through ``_``, ``N_``, ``ngettext`` or ``pgettext``. Docstrings, log calls, dictionary keys
and identifier-like strings are not text. Exception messages are internal English, so
inside a ``raise`` only Italian-looking text is reported.

Catalog check: ``po/en.po`` has no untranslated or fuzzy entry, covers every msgid in the
code, and keeps the shared English terms (container, Docker...) in the translation.
"""

import argparse
import ast
import re
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATHS = (ROOT / "src" / "wimm",)
CATALOG = ROOT / "po" / "en.po"
TEMPLATE = ROOT / "build" / "po" / "wimm.pot"
SKIPPED_FILES = frozenset({"i18n.py"})
# Collectors read the system and return data: by design they never produce interface text.
SKIPPED_DIRS = frozenset({"collectors"})
MARKERS = frozenset({"_", "N_", "ngettext", "pgettext"})
# Calls whose string arguments are names, signals, CSS or log text, never shown as text.
NON_TEXT_CALLS = frozenset(
    {
        "debug",
        "info",
        "warning",
        "error",
        "exception",
        "critical",
        "log",
        "getLogger",
        "require_version",
        "connect",
        "emit",
        "lookup_action",
        "add_css_class",
        "remove_css_class",
        "has_css_class",
        "set_css_classes",
        "Variant",
        "new_tuple",
        "get_property",
        "set_property",
        "lookup",
        "add_action",
        "SimpleAction",
        "set_accels_for_action",
        "new_for_string",
        "parse",
        "strftime",
        "getenv",
        "get",
        "setenv",
        "Path",
        "PurePosixPath",
        "environ",
        "import_module",
        "signal_new",
    }
)
NON_TEXT_KEYWORDS = frozenset(
    {
        "icon_name",
        "css_classes",
        "css_name",
        "name",
        "action_name",
        "detailed_action",
        "application_id",
        "accelerator",
        "orientation",
        "halign",
        "valign",
        "encoding",
        "errors",
        "mode",
        "level",
        "format",
        "datefmt",
        "sep",
        "key",
        "kind",
    }
)
DOTTED_NAME = re.compile(r"[\w*-]+(\.[\w*-]+)+")
PATH_LIKE = re.compile(r"[~.\w-]*/[\w./-]*")
REGEX_MARKS = ("\\", "(?", "[^")
# Class attributes that hold the internal English of an error, never shown (model/errors.py).
INTERNAL_ATTRIBUTES = frozenset({"message", "code"})
# Strings a person never reads, or reads unchanged in every language, with the reason.
EXEMPT = {
    "core/constants.py": {
        # Process names and freedesktop menu categories matched against the system.
        "Xorg",
        "Xwayland",
        "IDE",
        "Development",
        "Office",
        "WordProcessor",
        "Spreadsheet",
        "Presentation",
        "Graphics",
        "Email",
        "Chat",
        "InstantMessaging",
    },
    # Unicode general-category codes matched against unicodedata, never shown.
    "core/planning_restart.py": {"Cc", "Cf", "Zl", "Zp"},
    # Clipboard MIME type that password managers read; fixed by the protocol.
    "ui/toasts.py": {"x-kde-passwordManagerHint"},
    "core/risk_table.py": {
        # Shell commands shown verbatim inside the translated rebuild sentence.
        "npm install",
        "uv sync",
        "gradle build",
        "npm run build",
        "composer install",
        "cargo build",
        "mvn package",
    },
    "collectors/desktop_entries.py": {"Desktop Entry"},  # .desktop file section name
    "redaction.py": {"[REDACTED]"},  # log redaction marker
    "tray/status_notifier.py": {"Active"},  # StatusNotifierItem Status value
    # Endonyms: each language keeps its own name in every interface language.
    "ui/dialogs/preferences_language.py": {"Italiano", "English"},
    # Internal English: D-Bus error text, step messages and log text, never in the UI.
    "service/inspector_dbus.py": {"Snapshot is not ready"},
    "logging_setup.py": {"Cannot open private log; using stderr only: {}"},
    "app.py": {"wimm {}"},  # the --version line: program name and number
    # Step outcome messages: logged and kept in history, never shown by the UI.
    "service/control_protocols.py": {"unexpected error, see the log"},
    "service/controls_disk.py": {
        "Build cache prune timed out after {} s: "
        "the daemon may still be freeing space, the result is unknown",
        "build cache",
    },
    "service/executor_disk_docker.py": {"tags left alone, now on another image: {}"},
    "service/executor_disk_fs.py": {"{} entries left in {} (first: {})", "mount point skipped"},
    "service/executor_docker.py": {
        "container no longer exists",
        "container is {}: stop it before removing",
    },
    "service/executor_process.py": {"still running after {}s: {}"},
    "core/disk_wire.py": {"disk report"},  # path label inside a decoding error
    "ui/window.py": {"max-width: 600px"},  # libadwaita breakpoint condition
    # A shell command the user copies verbatim: the same in every language.
    "ui/dialogs/tray_help.py": {"gnome-extensions enable ubuntu-appindicators@ubuntu.com"},
}
IDENTIFIER = re.compile(r"[a-z0-9_.\-:/%*+@#=<>|\\,;]*")
CONSTANT_NAME = re.compile(r"[A-Z0-9_]+")
CAMEL_CASE = re.compile(r"[A-Z][a-z0-9]*[A-Z][A-Za-z0-9.]*")
PLACEHOLDER = re.compile(r"\{[^{}]*\}")
LETTERS = re.compile(r"[A-Za-zÀ-ÿ]{2,}")
ITALIAN = re.compile(
    r"[àèéìòù]|\bnon\b(?!-)|\b(il|lo|la|gli|le|di|da|del|della|dei|nel|nella|con|che|una|"
    r"sono|più|già|nessun\w*|questo|questa|ancora|quando|perché)\b",
    re.IGNORECASE,
)
# Literal text the user sees that stays the same in every language.
LANGUAGE_NEUTRAL = frozenset({"B", "kB", "MB", "GB", "TB", "B/s", "Where Is My Memory"})
# Terms already English in the Italian interface: the translation keeps them (prefix match).
SHARED_TERMS = (
    "container",
    "Docker",
    "cache",
    "swap",
    "snap",
    "flatpak",
    "registry",
    "CPU",
    "RAM",
    "node_modules",
    ".venv",
    "localhost",
    "Compose",
)


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    text: str

    def __str__(self) -> str:
        return f"{self.path.relative_to(ROOT)}:{self.line}: {self.text!r}"


def call_name(node: ast.Call) -> str:
    """Return the called name for ``f()`` and ``obj.f()``, else an empty string."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def is_text(*, text: str) -> bool:
    """Whether ``text`` reads as words a person would read, not as a name or a format."""
    bare = PLACEHOLDER.sub("", text).strip()
    if bare in LANGUAGE_NEUTRAL or not LETTERS.search(bare) or bare.startswith("<"):
        return False
    if ("{" in text and ";" in text) or any(mark in text for mark in REGEX_MARKS):
        return False  # embedded CSS or a regular expression
    if PLACEHOLDER.search(text) and bare.isalpha():
        return True  # "{n} processi": a word next to a value is a sentence, not a name
    names = (IDENTIFIER, CONSTANT_NAME, CAMEL_CASE, DOTTED_NAME, PATH_LIKE)
    return not any(pattern.fullmatch(bare) for pattern in names)


def literal_text(node: ast.AST) -> str | None:
    """Return the text of a string literal or an f-string, placeholders as ``{}``."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = (v.value if isinstance(v, ast.Constant) else "{}" for v in node.values)
        return "".join(str(part) for part in parts)
    return None


class _Scanner(ast.NodeVisitor):
    def __init__(self, *, path: Path, exempt: frozenset[str] = frozenset()) -> None:
        self.path = path
        self.exempt = exempt
        self.findings: list[Finding] = []
        self.in_raise = False

    def generic_visit(self, node: ast.AST) -> None:
        body: list[ast.stmt] = getattr(node, "body", None) or []
        documented = isinstance(
            node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ) and bool(body and isinstance(body[0], ast.Expr) and literal_text(body[0].value))
        if not documented:
            super().generic_visit(node)
            return
        for statement in body[1:]:
            self.visit(statement)
        for field in ("decorator_list", "args", "returns", "bases", "keywords"):
            for child in _as_list(getattr(node, field, None)):
                self.visit(child)

    def visit_Call(self, node: ast.Call) -> None:
        name = call_name(node)
        if name in MARKERS or name in NON_TEXT_CALLS:
            return
        self.visit(node.func)
        for arg in node.args:
            self.visit(arg)
        for keyword in node.keywords:
            if keyword.arg not in NON_TEXT_KEYWORDS:
                self.visit(keyword.value)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        body = node.body
        if body and isinstance(body[0], ast.Expr) and literal_text(body[0].value):
            body = body[1:]
        for child in (*node.decorator_list, *node.bases, *node.keywords):
            self.visit(child)
        for statement in body:
            internal = isinstance(statement, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in INTERNAL_ATTRIBUTES for t in statement.targets
            )
            if not internal:
                self.visit(statement)

    def visit_Raise(self, node: ast.Raise) -> None:
        self.in_raise = True
        self.generic_visit(node)
        self.in_raise = False

    def visit_Dict(self, node: ast.Dict) -> None:
        for value in node.values:
            self.visit(value)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        self.visit(node.value)

    def visit_Compare(self, node: ast.Compare) -> None:
        # ``kind == "x"`` compares names; text comparisons go through the translated form.
        return

    def visit_Constant(self, node: ast.Constant) -> None:
        self._check(node=node)

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        self._check(node=node)

    def _check(self, *, node: ast.Constant | ast.JoinedStr) -> None:
        text = literal_text(node)
        if text is None or text in self.exempt:
            return
        flagged = ITALIAN.search(text) if self.in_raise else is_text(text=text)
        if flagged:
            self.findings.append(Finding(path=self.path, line=node.lineno, text=text))


def _as_list(value: object) -> list[ast.AST]:
    if isinstance(value, ast.arguments):
        return [*value.defaults, *(d for d in value.kw_defaults if d is not None)]
    if isinstance(value, list):
        return value
    return [value] if isinstance(value, ast.AST) else []


def scan_source(*, path: Path, source: str) -> list[Finding]:
    """Return the string literals in ``source`` that should go through gettext."""
    relative = path.as_posix().split("/src/wimm/")[-1]
    scanner = _Scanner(path=path, exempt=frozenset(EXEMPT.get(relative, ())))
    scanner.visit(ast.parse(source))
    return scanner.findings


def iter_sources(*, paths: tuple[Path, ...]) -> Iterator[Path]:
    for base in paths:
        files = [base] if base.is_file() else sorted(base.rglob("*.py"))
        yield from (
            f for f in files if f.name not in SKIPPED_FILES and not SKIPPED_DIRS & set(f.parts)
        )


def _run(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True, cwd=ROOT).stdout  # noqa: S603


def check_catalog() -> list[str]:
    """Return the problems of po/en.po against the code and the shared terms."""
    _run("make", "--silent", "pot")
    problems = []
    for flag, label in (("--untranslated", "untranslated"), ("--only-fuzzy", "fuzzy")):
        entries = _run("msgattrib", flag, "--no-obsolete", str(CATALOG)).count("\nmsgid ")
        if entries:
            problems.append(f"po/en.po: {entries} {label} entries")
    missing = subprocess.run(  # noqa: S603
        ["msgcmp", "--use-untranslated", str(CATALOG), str(TEMPLATE)],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    if missing.returncode:
        problems.append(f"po/en.po misses strings of the code (make po):\n{missing.stderr}")
    return problems + check_shared_terms()


def lost_terms(*, msgid: str, msgstr: str) -> list[str]:
    """Shared English terms of ``msgid`` that its translation dropped."""
    lost = []
    for term in SHARED_TERMS:
        pattern = re.compile(rf"\b{re.escape(term)}", re.IGNORECASE)
        if pattern.search(msgid) and not pattern.search(msgstr):
            lost.append(term)
    return lost


def check_shared_terms() -> list[str]:
    """Shared English terms in a msgid must survive in its translation."""
    return [
        f"po/en.po: {term!r} lost in {msgid!r} -> {msgstr!r}"
        for msgid, msgstr in _catalog_pairs()
        for term in lost_terms(msgid=msgid, msgstr=msgstr)
    ]


def _catalog_pairs() -> Iterator[tuple[str, str]]:
    import gettext
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        mo = Path(tmp) / "en.mo"
        _run("msgfmt", "-o", str(mo), str(CATALOG))
        with mo.open("rb") as handle:
            catalog = gettext.GNUTranslations(handle)._catalog  # type: ignore[attr-defined]
    for key, msgstr in catalog.items():
        msgid = key[0] if isinstance(key, tuple) else key
        if msgid:
            yield msgid.split("\x04")[-1], msgstr


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", type=Path, default=list(DEFAULT_PATHS))
    parser.add_argument("--no-catalog", action="store_true", help="only scan the sources")
    options = parser.parse_args(argv)
    findings = [
        finding
        for path in iter_sources(paths=tuple(p.resolve() for p in options.paths))
        for finding in scan_source(path=path, source=path.read_text(encoding="utf-8"))
    ]
    problems = [str(f) for f in findings] + ([] if options.no_catalog else check_catalog())
    for problem in problems:
        print(problem)
    print(f"check_i18n: {len(findings)} untranslated literals, {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
