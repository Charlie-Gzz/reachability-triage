from pathlib import Path

from reachability_triage.scan.osv import _first_fix_above, _primary_id
from reachability_triage.scan.poetry_export import export
from reachability_triage.scan.workspace import failing_tests, parse_test_summary


def test_primary_id_prefers_ghsa_then_pysec():
    assert _primary_id(["PYSEC-2022-1", "CVE-2022-9", "GHSA-aaaa-bbbb-cccc"]) == "GHSA-aaaa-bbbb-cccc"
    assert _primary_id(["CVE-2022-9", "PYSEC-2022-1"]) == "PYSEC-2022-1"


def test_first_fix_picks_lowest_fix_above_installed():
    # Django-style: one fix per supported branch; installed 4.0.1 -> 4.0.2 is the upgrade target.
    assert _first_fix_above(["3.2.12", "4.0.2", "4.1"], "4.0.1") == "4.0.2"
    assert _first_fix_above(["1.0"], "2.0") is None


def test_parse_django_summary():
    out = "....\nRan 1061 tests in 7.388s\n\nFAILED (failures=2, errors=1)\n"
    assert parse_test_summary(out) == {"runner": "django", "total": 1061, "failed": 3, "passed": 1058}


def test_parse_pytest_summary():
    out = "FAILED tests/x.py::t\n== 2 failed, 480 passed, 3 skipped, 1 error in 9.1s =="
    r = parse_test_summary(out)
    assert (r["passed"], r["failed"], r["skipped"]) == (480, 3, 3)


def test_poetry_export_excludes_dev_and_foreign_markers(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("""
[tool.poetry.dependencies]
python = "^3.11"
web = {version = "*", extras = ["fast"]}
[tool.poetry.group.dev.dependencies]
pytest = "*"
""")
    (tmp_path / "poetry.lock").write_text("""
[[package]]
name = "web"
version = "1.0"
[package.dependencies]
core = "*"
wincolor = {version = "*", markers = "sys_platform == 'win32'"}
[package.extras]
fast = ["speedups (>=2)"]

[[package]]
name = "core"
version = "2.0"

[[package]]
name = "wincolor"
version = "0.1"

[[package]]
name = "speedups"
version = "2.1"

[[package]]
name = "pytest"
version = "8.0"
[package.dependencies]
pluggy = "*"

[[package]]
name = "pluggy"
version = "1.5"
""")
    assert export(tmp_path, "main", "3.11") == ["core==2.0", "speedups==2.1", "web==1.0"]
    assert "pytest==8.0" in export(tmp_path, "all", "3.11")


def test_failing_tests_parses_pytest_and_django():
    out = "FAILED tests/a.py::test_x - assert 0\nERROR: test_y (hc.api.tests.test_z.ZTestCase)\n"
    assert failing_tests(out) == ["hc.api.tests.test_z.ZTestCase.test_y", "tests/a.py::test_x"]
