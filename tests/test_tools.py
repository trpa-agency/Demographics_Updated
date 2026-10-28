"""Checks for the double-click scripts in tools/.

Each script must explain itself at the top of the file. The shared launcher
must import only the standard library, because it runs before the script knows
whether pandas is available.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = sorted((ROOT / "tools").glob("*.py"))
SECTIONS = ("What it does", "What it reads", "What it writes", "How to run it")
STANDARD_LIBRARY = {"__future__", "os", "subprocess", "sys", "traceback", "pathlib", "typing",
                    "functools", "http", "json", "threading", "webbrowser"}


def _imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.col_offset == 0:
            yield node.module.split(".")[0]


def test_there_are_scripts_and_no_batch_files():
    assert TOOLS
    assert not list((ROOT / "tools").glob("*.bat"))


def test_every_script_explains_itself():
    for path in TOOLS:
        doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or ""
        missing = [s for s in SECTIONS if s not in doc]
        assert not missing, f"{path.name} is missing {missing} in its description"


def test_launcher_imports_standard_library_only():
    launcher = ROOT / "src" / "trpa_demographics" / "launcher.py"
    assert set(_imports(launcher)) <= STANDARD_LIBRARY


def test_explorer_script_imports_standard_library_only():
    assert set(_imports(ROOT / "tools" / "6_open_explorer.py")) <= STANDARD_LIBRARY
