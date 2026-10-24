"""The layering rules the tool split depends on, checked instead of remembered.

chatchat is the runtime: it knows nothing about the product built on top of it,
and its own tool modules are leaves - they import the abstractions they need and
never the team object that will call them, so the facade can change without them.
"""

import ast
import pathlib

PACKAGE = pathlib.Path(__file__).resolve().parent.parent / "chatchat"


def _imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module)
    return found


def _modules(*parts):
    return sorted(PACKAGE.glob("/".join(parts)))


def test_the_runtime_knows_nothing_about_the_product_built_on_it():
    offenders = {
        str(path.relative_to(PACKAGE)): sorted(names)
        for path in _modules("**", "*.py")
        if (names := {name for name in _imports(path) if name.split(".")[0] in {"pyclaw", "textual"}})
    }
    assert offenders == {}


def test_a_builtin_tool_never_imports_the_team_that_will_call_it():
    offenders = {}
    for path in _modules("tools", "builtin", "*.py"):
        found = {name for name in _imports(path) if name in {"chatchat.team.team", "chatchat.tools"}}
        if found:
            offenders[path.name] = sorted(found)
    assert offenders == {}
