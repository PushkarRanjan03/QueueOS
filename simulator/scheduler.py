from __future__ import annotations

from typing import Iterable

from .models import State, TaskRuntime


def select_task(tasks: Iterable[TaskRuntime], policy: str) -> TaskRuntime | None:
    eligible = [task for task in tasks if task.state == State.READY]
    if not eligible:
        return None
    if policy == "FCFS":
        return min(eligible, key=lambda task: (task.spec.arrival_time, task.task_id))
    return min(
        eligible,
        key=lambda task: (
            -(task.effective_priority + (task.ready_wait if policy == "Priority + PIP + Aging" else 0)),
            task.spec.arrival_time,
            task.task_id,
        ),
    )


def recompute_inheritance(tasks: Iterable[TaskRuntime], blocked_on: dict[str, str], owner_by_resource: dict[str, str | None]) -> None:
    task_map = {task.task_id: task for task in tasks}
    for task in task_map.values():
        task.effective_priority = task.base_priority
    changed = True
    while changed:
        changed = False
        for waiter in task_map.values():
            if waiter.state != State.BLOCKED:
                continue
            resource_id = blocked_on.get(waiter.task_id)
            if resource_id is None:
                continue
            owner_id = owner_by_resource.get(resource_id)
            owner = task_map.get(owner_id or "")
            if owner and owner.effective_priority < waiter.effective_priority:
                owner.effective_priority = waiter.effective_priority
                changed = True
