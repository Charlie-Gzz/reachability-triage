"""Eval metrics, bootstrap CIs and the remediation regression check. Pure functions, no runs/ needed."""
import pytest

from reachability_triage.eval.metrics import _ci, _core, evaluate, resolved_model
from reachability_triage.remediate.pipeline import _regressions

R, N, U = "reachable", "not_reachable", "uncertain"


def test_core_counts_and_rates():
    pairs = [(R, R), (R, R), (R, N), (R, U), (N, N), (N, N), (N, R), (N, U)]
    m = _core(pairs)
    assert (m["n"], m["tp"], m["true_reachable"], m["predicted_reachable"], m["false_suppressions"]) == (8, 2, 4, 3, 1)
    assert m["precision"] == pytest.approx(2 / 3)
    assert m["recall"] == pytest.approx(2 / 4)            # an `uncertain` prediction is not a catch
    assert m["false_suppression_rate"] == pytest.approx(1 / 4)
    assert m["noise_reduction"] == pytest.approx(2 / 8)
    assert m["uncertain_rate"] == pytest.approx(2 / 8)
    assert m["suppressed_rate"] == pytest.approx(3 / 8)
    assert m["accuracy"] == pytest.approx(4 / 8)


def test_core_undefined_rates_are_none_not_zero():
    m = _core([(N, N), (N, U)])
    assert m["precision"] is None and m["recall"] is None and m["false_suppression_rate"] is None
    assert _core([])["noise_reduction"] is None


def test_bootstrap_ci_is_deterministic_and_brackets_the_estimate():
    pairs = [(R, R)] * 12 + [(R, N)] * 3 + [(N, N)] * 10 + [(N, R)] * 5
    a, b = _ci(pairs, "recall"), _ci(pairs, "recall")
    assert a == b                                          # fixed seed
    assert a[0] <= _core(pairs)["recall"] <= a[1]
    assert 0 <= a[0] < a[1] <= 1


def test_bootstrap_ci_degenerate_cases():
    assert _ci([], "recall") is None
    assert _ci([(R, R)] * 5, "recall") == [1.0, 1.0]
    # recall is undefined in every resample when nothing is truly reachable -> no CI
    assert _ci([(N, N)] * 5, "recall") is None


def _rec(fid, verdict, model="claude-sonnet-x"):
    return {"finding_id": fid, "final": {"verdict": verdict},
            "totals": {"llm_calls": 2, "tokens_in": 100, "tokens_out": 20, "cost_usd_est": 0.001, "seconds": 3.0},
            "steps": [{"name": "verdict", "attempts": [{"model": model}]}]}


def test_evaluate_filters_dataset_and_excludes_uncertain_truth():
    gt = {"b1": {"label": R, "status": "final", "dataset": "bench", "split": "test", "category": "direct_call"},
          "b2": {"label": N, "status": "final", "dataset": "bench", "split": "test", "category": "dead_code"},
          "b3": {"label": R, "status": "final", "dataset": "bench", "split": "dev", "category": "direct_call"},
          "r1": {"label": U, "status": "pending_review", "dataset": "real"},
          "r2": {"label": R, "status": "reviewed", "dataset": "real"}}
    recs = [_rec("b1", R), _rec("b2", R), _rec("b3", N), _rec("r1", N), _rec("r2", N)]
    bench = evaluate(recs, gt, "bench-test")
    assert bench["findings_run"] == 2 and bench["n"] == 2          # dev split left out
    assert bench["by_category"] == {"direct_call": {"n": 1, "correct": 1}, "dead_code": {"n": 1, "correct": 0}}
    assert bench["errors"] == [{"finding_id": "b2", "truth": N, "predicted": R}]
    real = evaluate(recs, gt, "real-eval")
    assert real["findings_run"] == 2 and real["n"] == 1 and real["excluded_truth_uncertain"] == 1
    assert real["false_suppression_rate"] == 1.0 and real["provisional"]
    assert evaluate(recs, {}, "real-eval") is None


def test_resolved_model_reads_step_attempts():
    assert resolved_model(_rec("x", R, model="claude-sonnet-5-5")) == "claude-sonnet-5-5"
    assert resolved_model({"steps": [{"name": "load"}, {"name": "verdict", "attempts": [{"error": "x"}]}]}) is None


# --------------------------------------------------------------------------- remediation

def test_regressions_ignores_baseline_and_new_test():
    suite = {"failing": ["a", "b", "new"], "failed": 3}
    assert _regressions(suite, {"a"}, "new") == ["b"]


def test_regressions_none_when_only_baseline_fails():
    assert _regressions({"failing": ["a"], "failed": 1}, {"a"}, "new") == []


def test_regressions_counts_failures_without_ids():
    # 4 failed, only 1 parsed id beyond baseline -> 2 more unexplained
    assert _regressions({"failing": ["a", "b"], "failed": 4}, {"a"}, "new") == [
        "b", "<2 more failures/errors without test ids>"]
