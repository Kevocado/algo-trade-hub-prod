import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("compare_junit", REPO / "tools" / "compare_junit.py")
compare_junit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compare_junit)


def _write(tmp_path, name, cases):
    body = "".join(
        f'<testcase classname="{cls}" name="{test}">{inner}</testcase>' for cls, test, inner in cases
    )
    path = tmp_path / name
    path.write_text(f'<?xml version="1.0"?><testsuites><testsuite>{body}</testsuite></testsuites>')
    return path


def test_key_normalizes_old_and_new_locations():
    assert compare_junit.test_key("SP500 Predictor.tests.test_x", "test_a") == "test_x::test_a"
    assert compare_junit.test_key("tests.test_x", "test_a") == "test_x::test_a"
    assert compare_junit.test_key("tests.test_x.TestY", "test_b") == "test_x.TestY::test_b"


def test_load_results_reads_statuses(tmp_path):
    path = _write(tmp_path, "r.xml", [
        ("tests.test_x", "test_ok", ""),
        ("tests.test_x", "test_bad", "<failure/>"),
        ("tests.test_x", "test_err", "<error/>"),
        ("tests.test_x", "test_skip", "<skipped/>"),
    ])
    assert compare_junit.load_results(path) == {
        "test_x::test_ok": "passed",
        "test_x::test_bad": "failed",
        "test_x::test_err": "failed",
        "test_x::test_skip": "skipped",
    }


def test_regressions_flags_lost_passes_but_allows_listed_removals():
    baseline = {"test_x::a": "passed", "test_x::b": "passed", "test_dixon_coles::c": "passed", "test_x::d": "failed"}
    current = {"test_x::a": "passed", "test_x::b": "failed"}
    assert compare_junit.regressions(baseline, current, ["test_dixon_coles*"]) == ["test_x::b: passed -> failed"]


def test_regressions_reports_missing_tests():
    assert compare_junit.regressions({"test_x::a": "passed"}, {}, []) == ["test_x::a: passed -> missing"]


def test_main_exit_codes(tmp_path):
    base = _write(tmp_path, "b.xml", [("tests.test_x", "test_a", "")])
    good = _write(tmp_path, "g.xml", [("tests.test_x", "test_a", "")])
    bad = _write(tmp_path, "x.xml", [("tests.test_x", "test_a", "<failure/>")])
    assert compare_junit.main([str(base), str(good)]) == 0
    assert compare_junit.main([str(base), str(bad)]) == 1
