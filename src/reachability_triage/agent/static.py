"""Static evidence: imports of the vulnerable package, call sites of named vulnerable symbols, and a
call path from an entry point (view / route / CLI) where one can be found. Pure `ast`, no LLM.

Deliberately simple and explainable: name-based call graph inside the project, import-alias
resolution per file, string-literal references (Django MIDDLEWARE etc.), template filter use.
"""
from __future__ import annotations

import ast
import re
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

ROUTE_DECORATORS = {"route", "get", "post", "put", "patch", "delete", "websocket", "api_route", "command",
                    "group", "task", "receiver", "before_request", "after_request", "errorhandler",
                    "app_template_filter", "template_filter", "on_event", "middleware", "exception_handler"}
VIEW_BASES = {"View", "TemplateView", "FormView", "APIView", "MethodView", "Resource", "ListView", "DetailView",
              "CreateView", "UpdateView", "DeleteView", "RedirectView", "Command", "BaseCommand", "Form", "ModelForm",
              "Middleware", "MiddlewareMixin", "BaseHTTPMiddleware", "Namespace", "Model", "Admin", "ModelAdmin"}
REGISTER_CALLS = {"path", "re_path", "url", "add_url_rule", "add_api_route", "add_route", "add_get", "add_post",
                  "add_put", "add_delete", "add_patch", "add_view", "register", "add_middleware", "connect",
                  "add_api_websocket_route", "add_resource", "add_command", "add_task"}
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "migrations", "site-packages", "frontend",
             "docs", "dist", "build"}


@dataclass
class Func:
    qualname: str          # module:Class.func
    name: str
    file: str
    line: int
    end_line: int
    is_entry: bool = False
    entry_kind: str = ""
    in_test: bool = False
    calls: set[str] = field(default_factory=set)       # bare names this function calls


@dataclass
class CallSite:
    file: str
    line: int
    code: str
    resolved: str          # dotted name after alias resolution, e.g. yaml.full_load
    function: str          # enclosing qualname, or <module>
    in_test: bool
    weak: bool = False     # matched only by attribute name on an unresolved object


@dataclass
class Evidence:
    package: str
    import_names: list[str]
    symbols: list[str]
    imported: bool
    import_locations: list[str]
    imported_in_tests_only: bool
    package_call_sites: int
    vulnerable_call_sites: list[dict]
    config_references: list[dict]
    template_references: list[dict]
    package_usages: list[dict]
    searched: dict
    entry_points: int
    paths: list[list[str]]
    summary: str

    def to_dict(self) -> dict:
        return asdict(self)


def _is_test_path(rel: str, test_dirs: list[str]) -> bool:
    parts = rel.replace("\\", "/").split("/")
    name = parts[-1]
    return (any(rel.replace("\\", "/").startswith(d.rstrip("/") + "/") for d in test_dirs)
            or "tests" in parts or "test" in parts or name.startswith("test_") or name.endswith("_test.py")
            or name == "conftest.py")


def iter_py(root: Path, dirs: list[str] | None) -> list[Path]:
    bases = [root / d for d in dirs] if dirs else [root]
    out = []
    for b in bases:
        if b.is_file():
            out.append(b)
            continue
        for p in b.rglob("*.py"):
            if not SKIP_DIRS.intersection(p.relative_to(root).parts):
                out.append(p)
    return sorted(set(out))


class _FileVisitor(ast.NodeVisitor):
    def __init__(self, rel: str, module: str, lines: list[str], in_test: bool):
        self.rel, self.module, self.lines, self.in_test = rel, module, lines, in_test
        self.aliases: dict[str, str] = {}          # local name -> dotted origin
        self.imports: list[tuple[str, int]] = []   # (dotted module, line)
        self.funcs: list[Func] = []
        self.calls: list[tuple[str, int, str, str]] = []   # (resolved, line, enclosing, attr)
        self.kwargs: list[tuple[str, int, str, str, str]] = []  # (resolved callee, line, enclosing, kw, value src)
        self.registered: set[str] = set()                   # function names handed to route/url registration
        self.strings: list[tuple[str, int]] = []
        self.stack: list[Func] = []
        self.class_stack: list[str] = []
        self.main_guard = False

    # imports
    def visit_Import(self, node: ast.Import):
        for a in node.names:
            self.imports.append((a.name, node.lineno))
            if a.asname:
                self.aliases[a.asname] = a.name
            else:
                self.aliases[a.name.split(".")[0]] = a.name.split(".")[0]

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.level:          # relative import: first-party
            mod = node.module or ""
            for a in node.names:
                self.aliases[a.asname or a.name] = f".{mod}.{a.name}" if mod else f".{a.name}"
            return
        mod = node.module or ""
        self.imports.append((mod, node.lineno))
        for a in node.names:
            self.aliases[a.asname or a.name] = f"{mod}.{a.name}"

    # definitions
    def _enter_func(self, node):
        owner = ".".join(self.class_stack)
        qual = f"{self.module}:{owner + '.' if owner else ''}{node.name}"
        f = Func(qual, node.name, self.rel, node.lineno, getattr(node, "end_lineno", node.lineno), in_test=self.in_test)
        for d in node.decorator_list:
            target = d.func if isinstance(d, ast.Call) else d
            nm = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
            if nm in ROUTE_DECORATORS:
                f.is_entry, f.entry_kind = True, f"@{nm}"
        if self.class_stack and getattr(self, "_class_is_view", [False])[-1]:
            f.is_entry, f.entry_kind = True, f.entry_kind or "view method"
        self.funcs.append(f)
        self.stack.append(f)
        self.generic_visit(node)
        self.stack.pop()

    visit_FunctionDef = _enter_func
    visit_AsyncFunctionDef = _enter_func

    def visit_ClassDef(self, node: ast.ClassDef):
        bases = {b.attr if isinstance(b, ast.Attribute) else getattr(b, "id", "") for b in node.bases}
        self.class_stack.append(node.name)
        self._class_is_view = getattr(self, "_class_is_view", []) + [bool(bases & VIEW_BASES)]
        if self.stack:
            self.stack[-1].calls.add(node.name)
        self.generic_visit(node)
        self._class_is_view.pop()
        self.class_stack.pop()

    def visit_If(self, node: ast.If):
        t = node.test
        if (isinstance(t, ast.Compare) and isinstance(t.left, ast.Name) and t.left.id == "__name__"
                and any(isinstance(c, ast.Constant) and c.value == "__main__" for c in t.comparators)):
            main = Func(f"{self.module}:<main>", "<main>", self.rel, node.lineno, getattr(node, "end_lineno", node.lineno),
                        is_entry=True, entry_kind="__main__", in_test=self.in_test)
            self.funcs.append(main)
            self.stack.append(main)
            self.generic_visit(node)
            self.stack.pop()
            return
        self.generic_visit(node)

    # uses
    def _dotted(self, node) -> str | None:
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Call):
            inner = self._dotted(node.func)
            return f"{inner}()." + ".".join(reversed(parts)) if inner and parts else None
        if isinstance(node, ast.Name):
            parts.append(node.id)
            return ".".join(reversed(parts))
        return None

    def _resolve(self, dotted: str) -> str:
        head, _, rest = dotted.partition(".")
        if head in self.aliases:
            base = self.aliases[head]
            return f"{base}.{rest}" if rest else base
        return dotted

    def visit_Assign(self, node: ast.Assign):
        # Module-level containers that reference functions (dispatch tables, urlpatterns) become graph nodes,
        # so `OPS[name](...)` inside a function still links to every function listed in OPS.
        if not self.stack and not self.class_stack:
            names = {n.id for n in ast.walk(node.value) if isinstance(n, ast.Name)} | {
                n.attr for n in ast.walk(node.value) if isinstance(n, ast.Attribute)}
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and names and isinstance(node.value, ast.Dict | ast.List | ast.Tuple | ast.Set):
                    f = Func(f"{self.module}:{tgt.id}", tgt.id, self.rel, node.lineno,
                             getattr(node, "end_lineno", node.lineno), in_test=self.in_test, calls=set(names))
                    if tgt.id in ("urlpatterns", "MIDDLEWARE", "routes"):
                        f.is_entry, f.entry_kind = True, tgt.id
                    self.funcs.append(f)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        d = self._dotted(node.func)
        enclosing = self.stack[-1].qualname if self.stack else f"{self.module}:<module>"
        if d and d.rsplit(".", 1)[-1] in REGISTER_CALLS:
            for a in [*node.args, *(k.value for k in node.keywords)]:
                if isinstance(a, ast.Name):
                    self.registered.add(a.id)
                elif isinstance(a, ast.Attribute):
                    self.registered.add(a.attr)
        if d:
            resolved = self._resolve(d)
            for kw in node.keywords:
                if kw.arg:
                    try:
                        val = ast.unparse(kw.value)[:80]
                    except Exception:
                        val = "?"
                    self.kwargs.append((resolved, node.lineno, enclosing, kw.arg, val))
            attr = d.rsplit(".", 1)[-1]
            self.calls.append((resolved, node.lineno, enclosing, attr))
            if self.stack:
                self.stack[-1].calls.add(attr)
                self.stack[-1].calls.add(resolved.lstrip(".").rsplit(".", 1)[-1])
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        # references without a call (e.g. Loader=yaml.FullLoader, MIDDLEWARE class refs)
        d = self._dotted(node)
        if d and isinstance(node.ctx, ast.Load):
            resolved = self._resolve(d)
            enclosing = self.stack[-1].qualname if self.stack else f"{self.module}:<module>"
            self.calls.append((resolved, node.lineno, enclosing, "@ref"))
            if self.stack:
                self.stack[-1].calls.add(node.attr)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name):
        if isinstance(node.ctx, ast.Load) and self.stack:
            self.stack[-1].calls.add(node.id)       # functions passed as callbacks still count as edges
            if node.id in self.aliases and not self.aliases[node.id].startswith("."):
                self.calls.append((self.aliases[node.id], node.lineno, self.stack[-1].qualname, "@ref"))

    def visit_Constant(self, node: ast.Constant):
        if isinstance(node.value, str) and 2 < len(node.value) < 200:
            self.strings.append((node.value, node.lineno))


@dataclass
class ProjectIndex:
    root: Path
    funcs: dict[str, Func]
    by_name: dict[str, list[str]]
    files: dict[str, _FileVisitor]
    callers: dict[str, set[str]]


def build_index(root: Path, app_dirs: list[str] | None, test_dirs: list[str] | None = None) -> ProjectIndex:
    return _build_index(str(root), tuple(app_dirs or ()), tuple(test_dirs or ()))


@lru_cache(maxsize=16)
def _build_index(root_s: str, app_dirs: tuple, test_dirs: tuple) -> ProjectIndex:
    root = Path(root_s)
    funcs: dict[str, Func] = {}
    files: dict[str, _FileVisitor] = {}
    for p in iter_py(root, list(app_dirs) or None):
        rel = p.relative_to(root).as_posix()
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src)
        except (SyntaxError, ValueError):
            continue
        module = rel[:-3].replace("/", ".").removesuffix(".__init__")
        v = _FileVisitor(rel, module, src.splitlines(), _is_test_path(rel, list(test_dirs)))
        v.visit(tree)
        files[rel] = v
        for f in v.funcs:
            funcs[f.qualname] = f
    registered = set().union(*(v.registered for v in files.values())) if files else set()
    for f in funcs.values():
        if not f.is_entry and f.name in registered and not f.in_test:
            f.is_entry, f.entry_kind = True, "registered handler"
    by_name: dict[str, list[str]] = defaultdict(list)
    for q, f in funcs.items():
        by_name[f.name].append(q)
        if ":" in q and "." in q.split(":", 1)[1]:
            by_name[q.split(":", 1)[1].split(".")[0]].append(q)    # class name -> its methods
    callers: dict[str, set[str]] = defaultdict(set)
    for q, f in funcs.items():
        for name in f.calls:
            for callee in by_name.get(name, []):
                if callee != q:
                    callers[callee].add(q)
    return ProjectIndex(root, funcs, dict(by_name), files, callers)


def _path_from_entry(idx: ProjectIndex, start: str, max_depth: int = 8) -> list[str] | None:
    """BFS backwards through callers to the nearest non-test entry point."""
    if start.endswith(":<module>"):
        return [start]                       # module-level code runs on import
    seen = {start}
    q = deque([[start]])
    while q:
        path = q.popleft()
        f = idx.funcs.get(path[-1])
        if f and f.is_entry and not f.in_test:
            return list(reversed(path))
        if len(path) > max_depth:
            continue
        for c in sorted(idx.callers.get(path[-1], ())):
            if c not in seen and not idx.funcs[c].in_test:
                seen.add(c)
                q.append(path + [c])
    return None


def _matches(resolved: str, symbol: str, roots: list[str]) -> bool:
    r = resolved.replace("().", ".")
    root = r.split(".")[0]
    if root not in roots:
        return False
    sym = symbol.strip("`()")
    if "." in sym:
        parts = sym.split(".")
        if parts[0] in roots:
            return r == sym or r.startswith(sym + ".") or (r.endswith("." + parts[-1]) and parts[-2] in r.split("."))
        return r.endswith("." + sym) or ("." + sym + ".") in r
    return r.split(".")[-1] == sym or ("." + sym + ".") in (r + ".")


def gather(root: Path, app_dirs: list[str] | None, test_dirs: list[str] | None, package: str,
           import_names: list[str], symbols: list[str], template_dirs: list[str] | None = None) -> Evidence:
    idx = build_index(root, app_dirs, test_dirs)
    roots = sorted(set(import_names))
    imports, import_tests = [], []
    pkg_calls = 0
    sites: list[CallSite] = []
    config_refs, tmpl_refs = [], []
    usages: list[dict] = []
    for rel, v in idx.files.items():
        for mod, line in v.imports:
            if mod.split(".")[0] in roots:
                (import_tests if v.in_test else imports).append(f"{rel}:{line}")
        uses_pkg = any(mod.split(".")[0] in roots for mod, _ in v.imports)
        seen_lines = set()
        usage_lines = set()
        for resolved, line, enclosing, attr in v.calls:
            rr = resolved.replace("().", ".")
            if rr.split(".")[0] in roots:
                pkg_calls += 1
                if line not in usage_lines and len(usages) < 40:
                    usage_lines.add(line)
                    code = v.lines[line - 1].strip() if 0 < line <= len(v.lines) else ""
                    usages.append({"location": f"{rel}:{line}", "code": code[:200], "function": enclosing,
                                   "in_test": v.in_test})
            for sym in symbols:
                strong = _matches(resolved, sym, roots)
                weak = (not strong and uses_pkg and attr not in ("@ref",) and "." not in sym.strip("`()")
                        and attr == sym.strip("`()") and rr.split(".")[0] not in roots and len(attr) > 4)
                if (strong or weak) and line not in seen_lines:
                    seen_lines.add(line)
                    code = v.lines[line - 1].strip() if 0 < line <= len(v.lines) else ""
                    sites.append(CallSite(rel, line, code[:200], rr, enclosing, v.in_test, weak=weak))
        for resolved, line, enclosing, kw, val in v.kwargs:
            rr = resolved.replace("().", ".")
            if rr.split(".")[0] not in roots and not uses_pkg:
                continue
            for sym in symbols:
                if kw == sym.strip("`()").split(".")[-1] and line not in seen_lines:
                    seen_lines.add(line)
                    code = v.lines[line - 1].strip() if 0 < line <= len(v.lines) else ""
                    sites.append(CallSite(rel, line, f"{code[:170]}  [{kw}={val}]", rr, enclosing, v.in_test,
                                          weak=rr.split(".")[0] not in roots))
        for s, line in v.strings:
            for sym in symbols:
                bare = sym.strip("`()")
                if len(bare) > 5 and (s == bare or s.endswith("." + bare.split(".")[-1]) and "." in s
                                      and s.split(".")[0] in roots):
                    config_refs.append({"location": f"{rel}:{line}", "value": s, "symbol": sym, "in_test": v.in_test})
    # template filters/tags ({{ x|urlize }}, {% load ... %})
    n_templates = 0
    for d in template_dirs or []:
        for p in (root / d).rglob("*.html") if (root / d).exists() else []:
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            n_templates += 1
            for sym in symbols:
                bare = sym.strip("`()").split(".")[-1]
                if len(bare) < 4:
                    continue
                for m in re.finditer(r"\|\s*" + re.escape(bare) + r"\b", text):
                    line = text.count("\n", 0, m.start()) + 1
                    tmpl_refs.append({"location": f"{p.relative_to(root).as_posix()}:{line}", "symbol": sym})
                    if len(tmpl_refs) > 20:
                        break
    vulnerable = []
    paths = []
    for s in sorted(sites, key=lambda s: (s.in_test, s.weak, s.file, s.line))[:25]:
        path = None if s.in_test else _path_from_entry(idx, s.function)
        d = asdict(s)
        d["reachable_from_entry"] = path is not None
        d["path"] = path or []
        d["callers"] = len(idx.callers.get(s.function, ())) if not s.function.endswith(":<module>") else None
        if path:
            paths.append(path)
        vulnerable.append(d)
    entries = sum(1 for f in idx.funcs.values() if f.is_entry and not f.in_test)
    prod_sites = [s for s in vulnerable if not s["in_test"]]
    strong_prod = [s for s in prod_sites if not s["weak"]]
    summary = (f"{package}: imported in {len(imports)} non-test location(s)"
               + (f" and {len(import_tests)} test location(s)" if import_tests else "")
               + f"; {pkg_calls} package call/reference site(s); named vulnerable symbols {symbols or 'none found'}; "
               + f"{len(strong_prod)} production call site(s) of those symbols"
               + (f" (+{len(prod_sites) - len(strong_prod)} weak name-only)" if len(prod_sites) > len(strong_prod) else "")
               + f", {sum(1 for s in prod_sites if s['reachable_from_entry'])} with a path from an entry point"
               + (f"; {len(vulnerable) - len(prod_sites)} only in tests" if len(vulnerable) > len(prod_sites) else "")
               + (f"; {len(config_refs)} config/string reference(s)" if config_refs else "")
               + (f"; {len(tmpl_refs)} template use(s)" if tmpl_refs else ""))
    usages.sort(key=lambda u: u["in_test"])
    return Evidence(package, roots, symbols, bool(imports), imports[:20], bool(import_tests) and not imports, pkg_calls,
                    vulnerable, config_refs[:10], tmpl_refs[:10], usages[:15],
                    {"python_files": len(idx.files), "template_dirs": list(template_dirs or []),
                     "template_files": n_templates}, entries, paths[:5], summary)


def function_source(root: Path, rel: str, line: int, context: int = 3) -> str:
    lines = (root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
    lo, hi = max(0, line - 1 - context), min(len(lines), line + context)
    return "\n".join(f"{i + 1:>5}  {lines[i]}" for i in range(lo, hi))
