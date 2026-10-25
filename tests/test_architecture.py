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


def _classes_with_a_client_attribute():
    """Every class that keeps a client of its own, and where it keeps it."""
    for path in _modules("**", "*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Assign):
                    continue
                for target in sub.targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                        and target.attr in {"client", "_client"}
                    ):
                        yield path, node.name, target.attr


def test_nothing_holds_a_client_that_the_agent_may_replace():
    """The lead's client can be replaced - switching the model or the thinking
    level gives it a new one. Anything that kept hold of the old one would be
    asking through it while reading the answer from somewhere else, and the
    numbers on the message would be the ones of a call nobody made.

    Two are allowed to hold one: the agent itself, and the caller that asks
    the model - the agent tells the caller when the client changes. A third
    may hold the client a host brought, because that one is never replaced.
    """
    allowed = {"Agent", "ModelCaller", "ModelChoice"}
    offenders = {
        f"{path.relative_to(PACKAGE)}:{name}.{attr}"
        for path, name, attr in _classes_with_a_client_attribute()
        if name not in allowed
    }
    assert not offenders, offenders


def test_the_agent_tells_the_caller_when_its_client_changes():
    """The caller that asks the model is given the new client, so the two
    always agree on which client they are talking through."""
    source = (PACKAGE / "runtime" / "agent.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    setters = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "client"
        and any(isinstance(dec, ast.Attribute) and dec.attr == "setter" for dec in node.decorator_list)
    ]
    assert setters, "the agent has no client setter"
    for setter in setters:
        names = {
            node.attr
            for node in ast.walk(setter)
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self"
        }
        if "caller" in names:
            return
    raise AssertionError("the agent's client setter does not tell the caller")
