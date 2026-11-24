"""Pure-Python, 100% in-RAM cross-repo AST call-edge scanner (CD-W19 + CD-W07)."""

from __future__ import annotations

import ast
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

IGNORED_DIRS: frozenset[str] = frozenset(
    {".git", "__pycache__", ".pytest_cache", ".worktrees", "node_modules", "Archive"}
)


@dataclass(frozen=True)
class _ModuleInfo:
    module_name: str
    rel_path: str
    is_package: bool
    tree: ast.Module


@dataclass
class _Scope:
    symbol_imports: dict[str, tuple[str, str]]
    module_aliases: dict[str, str]
    pkg_prefixes: set[str]

    def copy(self) -> _Scope:
        return _Scope(
            symbol_imports=dict(self.symbol_imports),
            module_aliases=dict(self.module_aliases),
            pkg_prefixes=set(self.pkg_prefixes),
        )

    def shadow(self, name: str) -> None:
        self.symbol_imports.pop(name, None)
        self.module_aliases.pop(name, None)
        self.pkg_prefixes.discard(name)


def _discover_python_files(repo_root: Path) -> list[Path]:
    """Walk repo_root excluding IGNORED_DIRS strictly relative to repo_root."""
    py_files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS)
        for filename in sorted(filenames):
            if filename.endswith(".py"):
                py_files.append(Path(dirpath) / filename)
    return py_files


def _resolve_module_name(
    file_path: Path,
    repo_root: Path,
    import_base: Path | None,
) -> tuple[str, bool]:
    """Compute dotted module name and package flag relative to import_base or repo_root."""
    if import_base is not None and file_path.is_relative_to(import_base):
        rel = file_path.relative_to(import_base)
    else:
        rel = file_path.relative_to(repo_root)

    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__" and len(parts) > 1:
        return ".".join(parts[:-1]), True
    return ".".join(parts), False


def _resolve_import_from_module(
    current_module: str,
    is_package: bool,
    imp_module: str | None,
    level: int,
) -> str | None:
    """Resolve absolute or relative `from ... import ...` module path."""
    if level == 0:
        return imp_module or ""

    pkg_parts = current_module.split(".") if is_package else current_module.split(".")[:-1]
    up = level - 1
    if up > len(pkg_parts):
        return None
    anchor = pkg_parts[: len(pkg_parts) - up]
    if imp_module:
        return ".".join(anchor + imp_module.split("."))
    return ".".join(anchor)


def _extract_units(mod: _ModuleInfo) -> tuple[list[dict[str, Any]], set[str]]:
    """Extract top-level functions, classes, and class methods from a parsed module."""
    units: list[dict[str, Any]] = []
    top_defs: set[str] = set()

    for node in mod.tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            top_defs.add(node.name)
            units.append(
                {
                    "module": mod.module_name,
                    "file": mod.rel_path,
                    "name": node.name,
                    "qualname": f"{mod.module_name}.{node.name}",
                    "kind": "function",
                    "line": node.lineno,
                    "end_line": getattr(node, "end_lineno", node.lineno),
                }
            )
        elif isinstance(node, ast.ClassDef):
            top_defs.add(node.name)
            units.append(
                {
                    "module": mod.module_name,
                    "file": mod.rel_path,
                    "name": node.name,
                    "qualname": f"{mod.module_name}.{node.name}",
                    "kind": "class",
                    "line": node.lineno,
                    "end_line": getattr(node, "end_lineno", node.lineno),
                }
            )
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    units.append(
                        {
                            "module": mod.module_name,
                            "file": mod.rel_path,
                            "name": f"{node.name}.{item.name}",
                            "qualname": f"{mod.module_name}.{node.name}.{item.name}",
                            "kind": "method",
                            "line": item.lineno,
                            "end_line": getattr(item, "end_lineno", item.lineno),
                        }
                    )

    return units, top_defs


def _collect_raw_reexports(
    modules: dict[str, _ModuleInfo],
    top_defs: dict[str, set[str]],
) -> dict[tuple[str, str], tuple[str, str]]:
    """Build bounded re-export lookup `(module, symbol) -> (defining_module, symbol)`."""
    direct: dict[tuple[str, str], tuple[str, str]] = {}
    for mod_name, mod in modules.items():
        for node in mod.tree.body:
            if isinstance(node, ast.ImportFrom):
                base_mod = _resolve_import_from_module(
                    mod_name, mod.is_package, node.module, node.level
                )
                if not base_mod or base_mod not in modules:
                    continue
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    local_name = alias.asname or alias.name
                    if local_name not in top_defs.get(mod_name, set()):
                        direct[(mod_name, local_name)] = (base_mod, alias.name)

    resolved: dict[tuple[str, str], tuple[str, str]] = {}
    for key in direct:
        cur = key
        seen: set[tuple[str, str]] = set()
        while cur in direct and cur not in seen:
            seen.add(cur)
            nxt = direct[cur]
            if nxt[1] in top_defs.get(nxt[0], set()):
                resolved[key] = nxt
                break
            cur = nxt
    return resolved


def _attr_chain(expr: ast.expr) -> list[str] | None:
    """Return dotted attribute chain `[root, ..., attr]` if pure Attribute/Name."""
    parts: list[str] = []
    cur: ast.expr = expr
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        parts.reverse()
        return parts
    return None


def _target_names(target: ast.expr) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        names: list[str] = []
        for elt in target.elts:
            names.extend(_target_names(elt))
        return names
    return []


def _param_names(args: ast.arguments) -> list[str]:
    names = [a.arg for a in args.posonlyargs]
    names.extend(a.arg for a in args.args)
    names.extend(a.arg for a in args.kwonlyargs)
    if args.vararg:
        names.append(args.vararg.arg)
    if args.kwarg:
        names.append(args.kwarg.arg)
    return names


def _resolve_symbol_target(
    target_mod: str,
    symbol_name: str,
    top_defs: dict[str, set[str]],
    reexports: dict[tuple[str, str], tuple[str, str]],
) -> tuple[str, str] | None:
    if symbol_name in top_defs.get(target_mod, set()):
        return (target_mod, symbol_name)
    return reexports.get((target_mod, symbol_name))


def _bind_import_stmt(
    stmt: ast.Import | ast.ImportFrom,
    mod: _ModuleInfo,
    scope: _Scope,
    modules: dict[str, _ModuleInfo],
    top_defs: dict[str, set[str]],
    reexports: dict[tuple[str, str], tuple[str, str]],
) -> None:
    if isinstance(stmt, ast.Import):
        for alias in stmt.names:
            mod_name = alias.name
            if alias.asname:
                if mod_name in modules:
                    scope.shadow(alias.asname)
                    scope.module_aliases[alias.asname] = mod_name
            else:
                root_pkg = mod_name.split(".")[0]
                if "." in mod_name:
                    if mod_name in modules:
                        scope.pkg_prefixes.add(root_pkg)
                elif mod_name in modules:
                    scope.shadow(mod_name)
                    scope.module_aliases[mod_name] = mod_name
        return

    base_mod = _resolve_import_from_module(
        mod.module_name, mod.is_package, stmt.module, stmt.level
    )
    if not base_mod:
        return

    for alias in stmt.names:
        if alias.name == "*":
            continue
        local_name = alias.asname or alias.name
        submod_candidate = f"{base_mod}.{alias.name}"
        if submod_candidate in modules:
            scope.shadow(local_name)
            scope.module_aliases[local_name] = submod_candidate
            continue
        if base_mod in modules:
            resolved = _resolve_symbol_target(base_mod, alias.name, top_defs, reexports)
            if resolved is not None:
                scope.shadow(local_name)
                scope.symbol_imports[local_name] = resolved


def _scan_expr_calls(
    node: ast.AST,
    mod: _ModuleInfo,
    caller_qualname: str,
    scope: _Scope,
    modules: dict[str, _ModuleInfo],
    top_defs: dict[str, set[str]],
    reexports: dict[tuple[str, str], tuple[str, str]],
    edges: list[dict[str, Any]],
) -> None:
    """Inspect expressions within a statement for exact direct-import or module-qualified calls."""
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        target: tuple[str, str] | None = None
        call_kind = ""

        if isinstance(func, ast.Name):
            target = scope.symbol_imports.get(func.id)
            call_kind = "direct_import"
        elif isinstance(func, ast.Attribute):
            chain = _attr_chain(func)
            if chain and len(chain) == 2:
                alias_name, sym_name = chain
                target_mod = scope.module_aliases.get(alias_name)
                if target_mod is not None:
                    target = _resolve_symbol_target(target_mod, sym_name, top_defs, reexports)
                    call_kind = "module_attr"
            elif chain and len(chain) > 2:
                root_pkg = chain[0]
                candidate_mod = ".".join(chain[:-1])
                if root_pkg in scope.pkg_prefixes and candidate_mod in modules:
                    target = _resolve_symbol_target(candidate_mod, chain[-1], top_defs, reexports)
                    call_kind = "module_attr"

        if target is None:
            continue
        target_mod, target_sym = target
        if target_mod == mod.module_name:
            continue
        target_info = modules.get(target_mod)
        if target_info is None:
            continue

        edges.append(
            {
                "source_module": mod.module_name,
                "source_file": mod.rel_path,
                "source_unit": caller_qualname,
                "target_module": target_mod,
                "target_file": target_info.rel_path,
                "target_unit": f"{target_mod}.{target_sym}",
                "target_symbol": target_sym,
                "call_kind": call_kind,
                "line": child.lineno,
            }
        )


def _walk_stmt_block(
    stmts: list[ast.stmt],
    mod: _ModuleInfo,
    caller_qualname: str,
    scope: _Scope,
    modules: dict[str, _ModuleInfo],
    top_defs: dict[str, set[str]],
    reexports: dict[tuple[str, str], tuple[str, str]],
    edges: list[dict[str, Any]],
    class_prefix: str = "",
) -> None:
    """Walk a statement block sequentially with lexical import and shadow tracking."""
    for stmt in stmts:
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            _bind_import_stmt(stmt, mod, scope, modules, top_defs, reexports)
            continue

        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in stmt.decorator_list:
                _scan_expr_calls(dec, mod, caller_qualname, scope, modules, top_defs, reexports, edges)
            for default_expr in stmt.args.defaults + [d for d in stmt.args.kw_defaults if d is not None]:
                _scan_expr_calls(default_expr, mod, caller_qualname, scope, modules, top_defs, reexports, edges)

            scope.shadow(stmt.name)
            fn_scope = scope.copy()
            for pname in _param_names(stmt.args):
                fn_scope.shadow(pname)

            if class_prefix:
                unit_qual = f"{mod.module_name}.{class_prefix}.{stmt.name}"
            elif caller_qualname == mod.module_name:
                unit_qual = f"{mod.module_name}.{stmt.name}"
            else:
                unit_qual = caller_qualname

            _walk_stmt_block(
                stmt.body, mod, unit_qual, fn_scope, modules, top_defs, reexports, edges
            )
            continue

        if isinstance(stmt, ast.ClassDef):
            for dec in stmt.decorator_list:
                _scan_expr_calls(dec, mod, caller_qualname, scope, modules, top_defs, reexports, edges)
            for base in stmt.bases:
                _scan_expr_calls(base, mod, caller_qualname, scope, modules, top_defs, reexports, edges)
            for kw in stmt.keywords:
                _scan_expr_calls(kw.value, mod, caller_qualname, scope, modules, top_defs, reexports, edges)

            scope.shadow(stmt.name)
            cls_scope = scope.copy()
            cls_qual = f"{mod.module_name}.{stmt.name}" if caller_qualname == mod.module_name else caller_qualname
            sub_prefix = stmt.name if caller_qualname == mod.module_name else ""
            _walk_stmt_block(
                stmt.body,
                mod,
                cls_qual,
                cls_scope,
                modules,
                top_defs,
                reexports,
                edges,
                class_prefix=sub_prefix,
            )
            continue

        if isinstance(stmt, ast.Assign):
            _scan_expr_calls(stmt.value, mod, caller_qualname, scope, modules, top_defs, reexports, edges)
            for tgt in stmt.targets:
                for name in _target_names(tgt):
                    scope.shadow(name)
            continue

        if isinstance(stmt, ast.AnnAssign):
            if stmt.value is not None:
                _scan_expr_calls(stmt.value, mod, caller_qualname, scope, modules, top_defs, reexports, edges)
            for name in _target_names(stmt.target):
                scope.shadow(name)
            continue

        if isinstance(stmt, ast.If):
            _scan_expr_calls(stmt.test, mod, caller_qualname, scope, modules, top_defs, reexports, edges)
            _walk_stmt_block(stmt.body, mod, caller_qualname, scope, modules, top_defs, reexports, edges, class_prefix)
            _walk_stmt_block(stmt.orelse, mod, caller_qualname, scope, modules, top_defs, reexports, edges, class_prefix)
            continue

        if isinstance(stmt, (ast.For, ast.AsyncFor)):
            _scan_expr_calls(stmt.iter, mod, caller_qualname, scope, modules, top_defs, reexports, edges)
            for name in _target_names(stmt.target):
                scope.shadow(name)
            _walk_stmt_block(stmt.body, mod, caller_qualname, scope, modules, top_defs, reexports, edges, class_prefix)
            _walk_stmt_block(stmt.orelse, mod, caller_qualname, scope, modules, top_defs, reexports, edges, class_prefix)
            continue

        if isinstance(stmt, ast.While):
            _scan_expr_calls(stmt.test, mod, caller_qualname, scope, modules, top_defs, reexports, edges)
            _walk_stmt_block(stmt.body, mod, caller_qualname, scope, modules, top_defs, reexports, edges, class_prefix)
            _walk_stmt_block(stmt.orelse, mod, caller_qualname, scope, modules, top_defs, reexports, edges, class_prefix)
            continue

        if isinstance(stmt, (ast.With, ast.AsyncWith)):
            for item in stmt.items:
                _scan_expr_calls(item.context_expr, mod, caller_qualname, scope, modules, top_defs, reexports, edges)
                if item.optional_vars is not None:
                    for name in _target_names(item.optional_vars):
                        scope.shadow(name)
            _walk_stmt_block(stmt.body, mod, caller_qualname, scope, modules, top_defs, reexports, edges, class_prefix)
            continue

        if isinstance(stmt, ast.Try):
            _walk_stmt_block(stmt.body, mod, caller_qualname, scope, modules, top_defs, reexports, edges, class_prefix)
            for handler in stmt.handlers:
                h_scope = scope.copy()
                if handler.name:
                    h_scope.shadow(handler.name)
                _walk_stmt_block(handler.body, mod, caller_qualname, h_scope, modules, top_defs, reexports, edges, class_prefix)
            _walk_stmt_block(stmt.orelse, mod, caller_qualname, scope, modules, top_defs, reexports, edges, class_prefix)
            _walk_stmt_block(stmt.finalbody, mod, caller_qualname, scope, modules, top_defs, reexports, edges, class_prefix)
            continue

        _scan_expr_calls(stmt, mod, caller_qualname, scope, modules, top_defs, reexports, edges)


def scan_repo_edges(repo_root: Path, import_root: str = "") -> dict[str, Any]:
    """Scan Python files in repo_root in RAM and return units and exact cross-file call edges."""
    t0 = time.perf_counter()
    root_path = Path(repo_root)
    if not root_path.is_dir():
        raise FileNotFoundError(
            f"Repository root directory does not exist: '{root_path}'. "
            "Pass an existing repository root directory."
        )

    repo_root_resolved = root_path.resolve()
    import_base: Path | None = None
    if import_root:
        candidate = (repo_root_resolved / import_root).resolve()
        if candidate.is_dir() and (
            candidate == repo_root_resolved or candidate.is_relative_to(repo_root_resolved)
        ):
            import_base = candidate

    py_files = _discover_python_files(repo_root_resolved)
    modules: dict[str, _ModuleInfo] = {}
    units: list[dict[str, Any]] = []
    top_defs: dict[str, set[str]] = {}

    for file_path in py_files:
        try:
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(file_path))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue

        module_name, is_package = _resolve_module_name(file_path, repo_root_resolved, import_base)
        rel_path = file_path.relative_to(repo_root_resolved).as_posix()
        mod_info = _ModuleInfo(
            module_name=module_name,
            rel_path=rel_path,
            is_package=is_package,
            tree=tree,
        )
        modules[module_name] = mod_info
        mod_units, mod_defs = _extract_units(mod_info)
        units.extend(mod_units)
        top_defs[module_name] = mod_defs

    reexports = _collect_raw_reexports(modules, top_defs)

    edges: list[dict[str, Any]] = []
    for module_name in sorted(modules):
        mod_info = modules[module_name]
        root_scope = _Scope(symbol_imports={}, module_aliases={}, pkg_prefixes=set())
        _walk_stmt_block(
            mod_info.tree.body,
            mod_info,
            module_name,
            root_scope,
            modules,
            top_defs,
            reexports,
            edges,
        )

    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    return {
        "repo_root": str(root_path),
        "import_root": import_root,
        "elapsed_ms": elapsed_ms,
        "unit_count": len(units),
        "edge_count": len(edges),
        "units": units,
        "edges": edges,
    }
