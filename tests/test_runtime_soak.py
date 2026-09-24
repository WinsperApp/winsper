from devtools.runtime_soak import RuntimeSoak, SoakTargets, percent_growth


def test_runtime_soak_exercises_all_lifecycle_counts_and_closes_cleanly():
    report = RuntimeSoak(
        SoakTargets(dictations=8, polish=6, cancellations=4, device_changes=3, sleep_resumes=2)
    ).run()

    assert report["ready"] is True
    assert report["evidence_level"] == "application-action-soak"
    assert report["counts_match"] is True
    assert report["completed"] == report["targets"]
    assert report["pipeline"]["recovery_probes"] == 13
    assert report["pipeline"]["expected_recovery_probes"] == 13
    assert report["pipeline"]["selection_rewrites"] == 4
    assert report["pipeline"]["device_start_failures"] == 4
    assert report["warmup"] == {
        "dictations": 5,
        "polish": 2,
        "cancellations": 2,
        "device_changes": 1,
        "sleep_resumes": 1,
    }
    assert report["pipeline"]["insertions"] == report["pipeline"]["successful_actions"]
    assert report["closed_cleanly"] is True
    assert report["final_phase"] == "SHUTTING_DOWN"
    assert "production hotkey start/stop and capture lifecycle" in report["covered"]
    assert "real ASR or LLM inference" in report["not_covered"]


def test_percent_growth_handles_missing_and_declining_samples():
    assert percent_growth(0.0, 10.0) == 0.0
    assert percent_growth(100.0, 95.0) == 0.0
    assert percent_growth(100.0, 104.0) == 4.0
