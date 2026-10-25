"""Enforce the dependency rule and detect cycles within architectural layers."""

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "ghost_audit"
FORBIDDEN_DOMAIN_IMPORTS = {
    "argparse",
    "csv",
    "os",
    "pathlib",
    "pypdf",
    "sqlite3",
    "subprocess",
    "tempfile",
}


def dependency_graph():
    sources = {
        "ghost_audit." + ".".join(path.relative_to(PACKAGE).with_suffix("").parts): path
        for path in PACKAGE.rglob("*.py")
        if path.name != "__init__.py"
    }
    graph = {module: set() for module in sources}
    for module, path in sources.items():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module in sources:
                graph[module].add(node.module)
            elif isinstance(node, ast.Import):
                graph[module].update(alias.name for alias in node.names if alias.name in sources)
    return graph


def test_package_imports_are_acyclic():
    graph = dependency_graph()
    complete = set()

    def visit(module, stack):
        assert module not in stack, "Import cycle: " + " -> ".join([*stack, module])
        if module in complete:
            return
        for dependency in sorted(graph[module]):
            visit(dependency, [*stack, module])
        complete.add(module)

    for module in sorted(graph):
        visit(module, [])


def test_domain_has_no_io_or_outer_layer_dependencies():
    for path in (PACKAGE / "domain").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
            elif isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
        assert not {name.split(".")[0] for name in imports} & FORBIDDEN_DOMAIN_IMPORTS, path
        assert not any(
            name.startswith(
                (
                    "ghost_audit.application",
                    "ghost_audit.infrastructure",
                    "ghost_audit.interfaces",
                    "evaluation",
                )
            )
            for name in imports
        ), path


def test_application_never_imports_file_adapters_or_cli():
    graph = dependency_graph()
    for module, dependencies in graph.items():
        if module.startswith("ghost_audit.application."):
            assert not any(
                name.startswith(("ghost_audit.infrastructure.", "ghost_audit.interfaces."))
                for name in dependencies
            ), module
