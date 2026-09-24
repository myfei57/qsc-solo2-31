"""交付树的死代码与可达性检查。

两项检查：

1. **符号引用**：扫描包内所有生产模块，任何模块级函数、类或类方法如果在整个
   包里找不到定义之外的引用，即判定为"生成了但没人调用"；
2. **模块可达**：从 ``bwms.__main__`` 出发沿 import 图求传递闭包，任何生产模块
   不在闭包内，说明有没人引用的文件混进了交付树。

用法::

    python tools/deadcode.py bwms

退出码 0 表示通过，1 表示发现问题（问题清单打到 stdout 的 JSON 里）。
"""

from __future__ import annotations

import ast
import json
import os
import sys

HOOK_NAMES = {
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


def _module_name(path: str, root: str) -> str:
    relative = os.path.relpath(path, os.path.dirname(root))
    parts = relative.replace(os.sep, ".").removesuffix(".py").split(".")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _iter_sources(root: str) -> list[str]:
    sources: list[str] = []
    for base, _dirs, files in os.walk(root):
        if "__pycache__" in base:
            continue
        for name in sorted(files):
            if name.endswith(".py"):
                sources.append(os.path.join(base, name))
    return sorted(sources)


def _parse(path: str) -> ast.AST:
    with open(path, "r", encoding="utf-8") as handle:
        return ast.parse(handle.read(), filename=path)


def _collect_definitions(tree: ast.AST, module: str) -> list[dict]:
    found: list[dict] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.append(
                {
                    "name": node.name,
                    "qualname": node.name,
                    "module": module,
                    "line": node.lineno,
                    "kind": "function",
                }
            )
        elif isinstance(node, ast.ClassDef):
            found.append(
                {
                    "name": node.name,
                    "qualname": node.name,
                    "module": module,
                    "line": node.lineno,
                    "kind": "class",
                }
            )
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    found.append(
                        {
                            "name": item.name,
                            "qualname": f"{node.name}.{item.name}",
                            "module": module,
                            "line": item.lineno,
                            "kind": "method",
                        }
                    )
    return found


def _collect_usages(tree: ast.AST) -> list[str]:
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
        if alias.name == "*":
            continue
        resolved.append(f"{base}.{alias.name}" if base else alias.name)
    return [item for item in resolved if item]


def analyze(root: str) -> dict:
    root = os.path.abspath(root)
    sources = _iter_sources(root)
    modules: dict[str, ast.AST] = {}
    packages: set[str] = set()
    for path in sources:
        module = _module_name(path, root)
        modules[module] = _parse(path)
        if os.path.basename(path) == "__init__.py":
            packages.add(module)

    usages: dict[str, int] = {}
    definitions: list[dict] = []
    for module, tree in modules.items():
        definitions.extend(_collect_definitions(tree, module))
        for name in _collect_usages(tree):
            usages[name] = usages.get(name, 0) + 1

    unused = [
        item
        for item in definitions
        if usages.get(item["name"], 0) == 0
        and item["name"] not in HOOK_NAMES
        and not item["module"].endswith("__main__")
    ]

    imports: dict[str, set[str]] = {module: set() for module in modules}
    for module, tree in modules.items():
        is_package = module in packages
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports[module].add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                imports[module].update(_resolve_import(module, node, is_package))

    reachable: set[str] = set()
    pending = [name for name in modules if name.endswith("__main__")]
    if not pending:
        pending = [name for name in modules if name.count(".") == 0]
    while pending:
        current = pending.pop()
        if current in reachable:
            continue
        reachable.add(current)
        for target in imports.get(current, set()):
            candidates = [target]
            parts = target.split(".")
            for cut in range(len(parts) - 1, 0, -1):
                candidates.append(".".join(parts[:cut]))
            for candidate in candidates:
                if candidate in modules and candidate not in reachable:
                    pending.append(candidate)

    unreachable_modules = sorted(
        module
        for module in modules
        if module not in reachable and not module.endswith("__main__")
    )

    return {
        "root": root,
        "files": len(sources),
        "symbols": len(definitions),
        "unused_symbols": sorted(
            unused, key=lambda item: (item["module"], item["line"])
        ),
        "unreachable_modules": unreachable_modules,
        "ok": not unused and not unreachable_modules,
    }


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    root = args[0] if args else "bwms"
    report = analyze(root)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
