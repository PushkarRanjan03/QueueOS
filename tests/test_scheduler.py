from simulator.models import TaskSpec
from simulator.simulation import run_simulation


def test_fcfs_uses_arrival_order():
    specs = [TaskSpec("B", "B", 1, 1, 1), TaskSpec("A", "A", 1, 0, 1)]
    result = run_simulation("FCFS", specs)
    running = [event.task_id for event in result.events if event.event_type == "TASK_RUNNING"]
    assert running[:2] == ["A", "B"]


def test_strict_priority_selects_highest_ready_task():
    specs = [TaskSpec("L", "L", 1, 0, 2), TaskSpec("H", "H", 3, 0, 1)]
    result = run_simulation("Strict Priority", specs)
    running = [event.task_id for event in result.events if event.event_type == "TASK_RUNNING"]
    assert running[0] == "H"


def test_invalid_task_spec_is_rejected():
    try:
        TaskSpec("X", "X", 0, 0, 1)
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid priority should be rejected")


def test_aging_increases_ready_task_selection_score():
    specs = [TaskSpec("L", "Low", 1, 0, 2), TaskSpec("H", "High", 3, 0, 2)]
    result = run_simulation("Priority + PIP + Aging", specs)
    running = [event.task_id for event in result.events if event.event_type == "TASK_RUNNING"]
    assert running == ["H", "H", "L", "L"]
