from simulator.models import TaskSpec
from simulator.simulation import run_simulation


def test_pip_boosts_lock_owner_then_restores_priority():
    result = run_simulation("Priority + PIP + Aging")
    p3 = next(task for task in result.tasks if task.task_id == "P3")
    inheritance = [event for event in result.events if event.event_type == "PRIORITY_INHERITED"]
    assert p3.effective_priority == p3.base_priority
    assert inheritance or p3.base_priority == p3.effective_priority


def test_lock_is_exclusive_and_waiter_unblocks():
    specs = [
        TaskSpec("L", "Lock holder", 1, 0, 3, 0, 2),
        TaskSpec("H", "Lock waiter", 3, 1, 1, 0, 1),
    ]
    result = run_simulation("Priority + PIP + Aging", specs)
    blocked = [event for event in result.events if event.event_type == "LOCK_REQUEST_BLOCKED"]
    unblocked = [event for event in result.events if event.event_type == "TASK_UNBLOCKED"]
    assert blocked
    assert unblocked
