from __future__ import annotations

from collections import Counter
from typing import Iterable

from .models import Event, State, TaskRuntime


def calculate_metrics(tasks: Iterable[TaskRuntime], events: Iterable[Event], elapsed_ticks: int) -> dict[str, float]:
    task_list = list(tasks)
    event_list = list(events)
    inversion = [event for event in event_list if event.event_type == "PRIORITY_INVERSION_DETECTED"]
    total_cpu = sum(task.spec.cpu_burst for task in task_list)
    return {
        "total_cpu_time": float(total_cpu),
        "average_ready_wait": sum(task.ready_wait for task in task_list) / len(task_list),
        "total_blocked_time": float(sum(task.blocked_time for task in task_list)),
        "average_turnaround": sum((task.completion_time or elapsed_ticks) - task.spec.arrival_time for task in task_list) / len(task_list),
        "throughput": len(task_list) / max(elapsed_ticks, 1),
        "resource_utilisation": total_cpu / max(elapsed_ticks, 1),
        "inversion_intervals": float(len(inversion)),
        "inversion_duration": float(sum(event.time for event in inversion[1:]) - sum(event.time for event in inversion[:-1])) if len(inversion) > 1 else float(len(inversion)),
        "completed_tasks": float(sum(task.state == State.COMPLETED for task in task_list)),
    }


def state_distribution(tasks: Iterable[TaskRuntime]) -> dict[str, int]:
    return Counter(task.state.value for task in tasks)
