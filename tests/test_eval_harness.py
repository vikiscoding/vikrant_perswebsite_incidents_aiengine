from eval_harness import run_harness


def test_harness_scores_ten_fixtures_without_self_grade(tmp_path):
    summary = run_harness(tmp_path / "evaluations", live=False)
    assert summary["n"] == 10
    assert summary["mode"] == "scripted"
    assert (tmp_path / "evaluations" / "summary.json").is_file()
    assert summary["logging_all_pass"] is True
    assert summary["high_medium_gaps_total"] >= 5
    assert summary["triage_correct_or_better_pct"] >= 70
    dup = next(row for row in summary["results"] if row["fixture_id"] == "eval-02-website-5xx-dup")
    first = next(row for row in summary["results"] if row["fixture_id"] == "eval-01-website-5xx")
    assert dup["proposal"]["duplicate_of"] == first["incident_id"]
    assert dup["duplicate_ok"] is True
    assert "self-eval" not in dup["notes"].lower() or "not model self-eval" in dup["notes"].lower()
    for row in summary["results"]:
        assert row["scores"]["logging_completeness"]["trace_count"] >= 1
