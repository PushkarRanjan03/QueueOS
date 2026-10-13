from simulator.simulation import run_simulation


def test_metrics_are_deterministic_and_completed():
    first = run_simulation("Strict Priority")
    second = run_simulation("Strict Priority")
    assert first.metrics == second.metrics
    assert all(task.completion_time is not None for task in first.tasks)
    assert first.metrics["total_blocked_time"] >= 0
    assert first.metrics["resource_utilisation"] > 0
