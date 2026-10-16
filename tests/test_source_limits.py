import ast
from pathlib import Path

import pytest

MAX_FILE_LINES = 300
MAX_FUNCTION_LINES = 30
MAX_PARAMETERS = 4
ALLOWED_SIGNATURES: dict[str, str] = {}
SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "wimm"


def analyze_source(source: str) -> list[str]:
    violations = []
    if len(source.splitlines()) > MAX_FILE_LINES:
        violations.append(f"file exceeds {MAX_FILE_LINES} lines")
    for node in ast.walk(node=ast.parse(source=source)):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        start_line = min([node.lineno, *(item.lineno for item in node.decorator_list)])
        if node.end_lineno is not None and node.end_lineno - start_line + 1 > MAX_FUNCTION_LINES:
            violations.append(f"{node.name}: function exceeds {MAX_FUNCTION_LINES} lines")
        # Receivers are implicit; variadics do not impose a fixed callback arity.
        parameters = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        count = sum(parameter.arg not in {"self", "cls"} for parameter in parameters)
        if count > MAX_PARAMETERS and node.name not in ALLOWED_SIGNATURES:
            violations.append(f"{node.name}: signature exceeds {MAX_PARAMETERS} parameters")
    return violations


def test_source_limits_project_sources() -> None:
    sources = sorted(SOURCE_ROOT.rglob(pattern="*.py"))
    assert sources
    for path in sources:
        assert analyze_source(source=path.read_text(encoding="utf-8")) == [], str(path)


@pytest.mark.parametrize("is_async", [False, True])
def test_analyze_source_function_length_boundary(is_async: bool) -> None:
    prefix = "async " if is_async else ""
    valid = f"{prefix}def sample():\n" + "    pass\n" * (MAX_FUNCTION_LINES - 1)
    assert analyze_source(source=valid) == []
    assert analyze_source(source=valid + "    pass\n") == ["sample: function exceeds 30 lines"]


def test_analyze_source_parameter_boundary() -> None:
    assert analyze_source(source="def sample(a, b, /, *, c, d): pass") == []
    assert analyze_source(source="def sample(a, b, /, *, c, d, e): pass") == [
        "sample: signature exceeds 4 parameters"
    ]


def test_analyze_source_file_length_boundary() -> None:
    valid = "pass\n" * MAX_FILE_LINES
    assert analyze_source(source=valid) == []
    assert analyze_source(source=valid + "pass\n") == ["file exceeds 300 lines"]


def test_analyze_source_excludes_receivers_and_variadics() -> None:
    source = "class Sample:\n    def method(self, a, b, c, d, *args, **kwargs): pass"
    assert analyze_source(source=source) == []


def test_analyze_source_callback_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    source = "def callback(a, b, c, d, e): pass"
    assert analyze_source(source=source) == ["callback: signature exceeds 4 parameters"]
    monkeypatch.setitem(dic=ALLOWED_SIGNATURES, name="callback", value="Gio callback contract")
    assert analyze_source(source=source) == []


def test_analyze_source_invalid_python_raises() -> None:
    with pytest.raises(SyntaxError):
        analyze_source(source="def invalid(")
