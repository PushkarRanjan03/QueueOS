from simulator.simulation import run_simulation


def test_default_scenario_detects_inversion_under_strict_priority():
    result = run_simulation("Strict Priority")
    inversion_events = [event for event in result.events if event.event_type == "PRIORITY_INVERSION_DETECTED"]
    assert inversion_events
    assert result.metrics["inversion_duration"] > 0
    assert result.resource.owner is None


def test_pip_mitigates_default_inversion():
    strict = run_simulation("Strict Priority")
    pip = run_simulation("Priority + PIP + Aging")
    assert pip.metrics["inversion_duration"] < strict.metrics["inversion_duration"]
    assert pip.tasks[0].effective_priority == pip.tasks[0].base_priority
    assert any(event.event_type == "LOCK_RELEASED" for event in pip.events)
