"""Static evidence (pure `ast`) and rule-based vulnerable-symbol extraction. No LLM, no network."""
from pathlib import Path

import pytest

from reachability_triage.agent import static
from reachability_triage.agent.advisory import extract_symbols, symbols_for
from reachability_triage.config import BENCH

YAML_SYMS = ["yaml.full_load", "FullLoader", "yaml.load"]


def _gather(root: Path, syms=YAML_SYMS, **kw):
    return static.gather(root, None, None, "pyyaml", ["yaml"], syms, **kw)


def _sites(ev):
    return [(s["file"], s["line"], s["in_test"], s["weak"], s["reachable_from_entry"]) for s in ev.vulnerable_call_sites]


# --------------------------------------------------------------------------- committed bench cases

@pytest.mark.parametrize("case, site, path", [
    ("recipe-importer", ("recipes/importer.py", 8), ["app:import_recipe", "recipes.importer:parse_recipe"]),
    ("ops-runbook", ("runbook/serialization.py", 6),
     ["runbook.__main__:<main>", "runbook.engine:run_book", "runbook.serialization:load_document"]),
])
def test_bench_reachable_cases_have_entry_path(case, site, path):
    ev = _gather(BENCH / "cases" / case)
    assert ev.imported
    assert [s[:2] for s in _sites(ev)] == [site]
    assert ev.vulnerable_call_sites[0]["reachable_from_entry"]
    assert ev.paths[0] == path


def test_bench_safe_api_only_has_no_vulnerable_sites():
    ev = _gather(BENCH / "cases" / "deploy-config")
    assert ev.imported and ev.package_call_sites > 0
    assert ev.vulnerable_call_sites == [] and ev.paths == []


def test_bench_dead_code_site_has_no_entry_path():
    ev = _gather(BENCH / "cases" / "billing-sync")
    assert _sites(ev) == [("billing/legacy.py", 7, False, False, False)]
    assert ev.paths == []


# --------------------------------------------------------------------------- synthetic projects

def _write(root: Path, files: dict[str, str]) -> Path:
    for rel, src in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(src, encoding="utf-8")
    return root


def test_import_alias_and_registered_handler(tmp_path):
    static._build_index.cache_clear()
    root = _write(tmp_path, {
        "app/loader.py": "from yaml import full_load as fl\n\ndef parse(s):\n    return fl(s)\n",
        "app/views.py": "from app.loader import parse\n\ndef upload(req):\n    return parse(req.body)\n",
        "app/urls.py": "from app.views import upload\nurlpatterns = [path('u/', upload)]\n",
    })
    ev = _gather(root)
    assert _sites(ev) == [("app/loader.py", 4, False, False, True)]
    assert ev.vulnerable_call_sites[0]["resolved"] == "yaml.full_load"
    assert ev.paths[0][0] in ("app.urls:urlpatterns", "app.views:upload")
    assert ev.paths[0][-1] == "app.loader:parse"


def test_keyword_argument_reference_counts_as_site(tmp_path):
    static._build_index.cache_clear()
    root = _write(tmp_path, {"cli.py": "import yaml\n\nif __name__ == '__main__':\n"
                                       "    yaml.load(open('x'), Loader=yaml.FullLoader)\n"})
    ev = _gather(root)
    assert [s[:2] for s in _sites(ev)] == [("cli.py", 4)]
    assert ev.paths == [["cli:<main>"]]


def test_test_only_usage_is_flagged_and_not_reachable(tmp_path):
    static._build_index.cache_clear()
    root = _write(tmp_path, {
        "pkg/core.py": "def add(a, b):\n    return a + b\n",
        "tests/test_core.py": "import yaml\n\ndef test_x():\n    yaml.full_load('a: 1')\n",
    })
    ev = _gather(root)
    assert not ev.imported and ev.imported_in_tests_only
    assert _sites(ev) == [("tests/test_core.py", 4, True, False, False)]
    assert ev.paths == []


def test_not_imported_at_all(tmp_path):
    static._build_index.cache_clear()
    root = _write(tmp_path, {"main.py": "import json\n\ndef load(s):\n    return json.loads(s)\n"})
    ev = _gather(root)
    assert not ev.imported and ev.package_call_sites == 0 and ev.vulnerable_call_sites == []


def test_template_filter_reference(tmp_path):
    static._build_index.cache_clear()
    root = _write(tmp_path, {"views.py": "import jinja2\n",
                             "templates/post.html": "<p>\n{{ body|urlize }}\n</p>\n"})
    ev = static.gather(root, None, None, "jinja2", ["jinja2"], ["urlize"], template_dirs=["templates"])
    assert ev.template_references == [{"location": "templates/post.html:2", "symbol": "urlize"}]


def test_function_source_numbers_lines(tmp_path):
    (tmp_path / "m.py").write_text("a = 1\nb = 2\nc = 3\nd = 4\n", encoding="utf-8")
    out = static.function_source(tmp_path, "m.py", 2, context=1)
    assert out.splitlines() == ["    1  a = 1", "    2  b = 2", "    3  c = 3"]


# --------------------------------------------------------------------------- symbol extraction

def test_extract_symbols_ranks_dotted_package_names_first_and_drops_urls():
    text = ("Arbitrary code execution when processing untrusted YAML through the `full_load` method or the "
            "FullLoader loader. See https://github.com/yaml/pyyaml/issues/420 and yaml.full_load().")
    syms = extract_symbols(text, ["yaml"], "pyyaml")
    assert syms[0] == "yaml.full_load"
    assert {"full_load", "FullLoader"} <= set(syms)
    assert not any("github" in s or "issues" in s for s in syms)


def test_extract_symbols_skips_acronyms_versions_and_package_name():
    syms = extract_symbols("CVE HTML YAML pyyaml yaml v5.4 5.3.1 Fixed in `safe_load`.", ["yaml"], "pyyaml")
    assert syms == ["safe_load"]


def test_symbols_for_prefers_structured_osv_hints():
    rec = {"details": "Something in `helper()`.", "affected": [{"ecosystem_specific": {
        "imports": [{"path": "pkg.mod", "symbols": ["bad"]}], "affected_functions": ["pkg.f"]}}]}
    syms = symbols_for({"package": "pkg", "summary": "s"}, [rec], ["pkg"])
    assert syms[:2] == ["pkg.f", "pkg.mod.bad"]
    assert "helper" in syms
