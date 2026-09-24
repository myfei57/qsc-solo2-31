"""交付卫生门禁：没有死代码、没有空壳实现、没有来历叙述与构建残留。"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "bwms"

RUNTIME_HOOKS = {
    "__init__",
    "__post_init__",
    "__enter__",
    "__exit__",
    "__repr__",
    "__eq__",
    "__hash__",
    "do_GET",
    "do_POST",
    "do_PUT",
    "do_DELETE",
    "log_message",
    "main",
}

# 由片段拼出来，避免把待禁字样本身写进仓库。
FORBIDDEN_TOKENS = (
    "".join(("本", "项目")),
    "".join(("本", "仓库")),
    "".join(("本", "设计")),
    "".join(("设计", "文档")),
    "".join(("题", "库")),
    "".join(("评", "测")),
    "".join(("控制", "服务")),
    "control" + " " + "service",
    "zxy" + "-",
    "".join(("ben", "zhi")),
)

SCANNED_SUFFIXES = {".py", ".toml", ".json", ".md", ".txt", ".cfg", ".yaml", ".yml"}
SKIPPED_DIRS = {".git", "__pycache__", ".pytest_cache", "var", ".venv", ".idea"}


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _sources() -> dict[str, ast.AST]:
    parsed: dict[str, ast.AST] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        parsed[_module_name(path)] = ast.parse(path.read_text(encoding="utf-8"), str(path))
    return parsed


def _definitions(tree: ast.AST, module: str) -> list[dict]:
    found: list[dict] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.append({"name": node.name, "module": module, "line": node.lineno})
        elif isinstance(node, ast.ClassDef):
            found.append({"name": node.name, "module": module, "line": node.lineno})
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    found.append({"name": item.name, "module": module, "line": item.lineno})
    return found


def _usages(tree: ast.AST) -> list[str]:
    used: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.append(node.id)
        elif isinstance(node, ast.Attribute):
            used.append(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            used.extend(
                part
                for part in node.value.replace("/", ".").split(".")
                if part.isidentifier()
            )
    return used


def _resolve_import(module: str, node: ast.ImportFrom, is_package: bool) -> list[str]:
    base = node.module or ""
    if node.level:
        parts = module.split(".")
        parent = parts if is_package else parts[:-1]
        keep = max(0, len(parent) - (node.level - 1))
        base = ".".join(parent[:keep] + ([base] if base else []))
    resolved = [base] if base else []
    for alias in node.names:
        if alias.name != "*":
            resolved.append(f"{base}.{alias.name}" if base else alias.name)
    return [item for item in resolved if item]


def _import_graph(modules: dict[str, ast.AST]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {name: set() for name in modules}
    for name, tree in modules.items():
        is_package = (ROOT / name.replace(".", "/") / "__init__.py").is_file()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                graph[name].update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                graph[name].update(_resolve_import(name, node, is_package))
    return graph


def test_package_has_no_unreferenced_symbols():
    modules = _sources()
    usages: dict[str, int] = {}
    definitions: list[dict] = []
    for module, tree in modules.items():
        definitions.extend(_definitions(tree, module))
        for name in _usages(tree):
            usages[name] = usages.get(name, 0) + 1
    orphans = [
        item
        for item in definitions
        if usages.get(item["name"], 0) == 0
        and item["name"] not in RUNTIME_HOOKS
        and not item["module"].endswith("__main__")
    ]
    assert orphans == [], f"存在生成了但没人调用的符号: {orphans}"


def test_every_module_is_reachable_from_the_entrypoint():
    modules = _sources()
    graph = _import_graph(modules)
    pending = [name for name in modules if name.endswith("__main__")]
    assert pending, "缺少 __main__ 入口"
    reachable: set[str] = set()
    while pending:
        current = pending.pop()
        if current in reachable:
            continue
        reachable.add(current)
        for target in graph.get(current, set()):
            candidates = [target]
            parts = target.split(".")
            for cut in range(len(parts) - 1, 0, -1):
                candidates.append(".".join(parts[:cut]))
            for candidate in candidates:
                if candidate in modules and candidate not in reachable:
                    pending.append(candidate)
    unreachable = sorted(
        name for name in modules if name not in reachable and not name.endswith("__main__")
    )
    assert unreachable == [], f"存在没人引用的模块: {unreachable}"


def test_package_has_no_placeholder_function_bodies():
    places: list[str] = []
    for module, tree in _sources().items():
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = [
                item
                for item in node.body
                if not (isinstance(item, ast.Expr) and isinstance(item.value, ast.Constant))
            ]
            if len(body) != 1:
                continue
            only = body[0]
            if isinstance(only, ast.Pass):
                places.append(f"{module}:{node.lineno} {node.name} 只有 pass")
            elif isinstance(only, ast.Return) and only.value is None:
                places.append(f"{module}:{node.lineno} {node.name} 只有空 return")
            elif (
                isinstance(only, ast.Expr)
                and isinstance(only.value, ast.Constant)
                and only.value.value is Ellipsis
            ):
                places.append(f"{module}:{node.lineno} {node.name} 只有省略号")
    assert places == [], f"存在占位实现: {places}"


def test_delivered_tree_has_no_introductory_document():
    names = {path.name.lower() for path in ROOT.iterdir() if path.is_file()}
    assert not any(name.startswith("readme") for name in names)


def test_project_metadata_is_neutral():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "description" not in text
    for token in FORBIDDEN_TOKENS:
        assert token not in text
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "LABEL" not in dockerfile


def test_sources_contain_no_forbidden_narration():
    offenders: list[str] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if set(relative.parts) & SKIPPED_DIRS:
            continue
        if path.suffix not in SCANNED_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for token in FORBIDDEN_TOKENS:
            if token in text:
                offenders.append(f"{relative}: {token}")
    assert offenders == [], f"交付树混入了来历叙述或构建残留: {offenders}"


def test_no_shell_helper_scripts_are_shipped():
    scripts = [
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*")
        if path.is_file()
        and path.suffix.lower() in {".sh", ".bat", ".cmd", ".ps1"}
        and ".git" not in path.parts
    ]
    assert scripts == [], f"交付树不应带构建助手脚本: {scripts}"


def test_deadcode_tool_reports_a_clean_tree():
    result = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tools", "deadcode.py"), os.path.join(ROOT, "bwms")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["unused_symbols"] == []
    assert report["unreachable_modules"] == []
