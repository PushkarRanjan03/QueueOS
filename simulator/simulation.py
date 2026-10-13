from __future__ import annotations

from dataclasses import dataclass

from .metrics import calculate_metrics, state_distribution
from .models import Event, Resource, State, TaskRuntime, TaskSpec
from .scheduler import recompute_inheritance, select_task


DEFAULT_TASKS = [
    TaskSpec("P3", "Low resource holder", 1, 0, 7, 0, 3),
    TaskSpec("P1", "High resource waiter", 3, 1, 1, 0, 1),
    TaskSpec("P2", "Medium CPU workload", 2, 2, 4),
]


@dataclass
class SimulationResult:
    policy: str
    tasks: list[TaskRuntime]
    events: list[Event]
    timeline: list[dict]
    metrics: dict[str, float]
    elapsed_ticks: int
    resource: Resource


def _event(events: list[Event], time: int, event_type: str, task_id: str | None, resource_id: str | None, explanation: str) -> None:
    events.append(Event(time, event_type, task_id, resource_id, explanation))


def run_simulation(policy: str, specs: list[TaskSpec] | None = None, max_ticks: int = 100) -> SimulationResult:
    if policy not in {"FCFS", "Strict Priority", "Priority + PIP + Aging"}:
        raise ValueError("Unknown scheduling policy.")
    tasks = [TaskRuntime(spec) for spec in (specs or DEFAULT_TASKS)]
    task_map = {task.task_id: task for task in tasks}
    resource = Resource("R1")
    blocked_on: dict[str, str] = {}
    events: list[Event] = []
    timeline: list[dict] = []
    inversion_active = False
    inversion_start: int | None = None
    inversion_durations: list[int] = []

    for clock in range(max_ticks):
        for task in tasks:
            if task.state == State.NEW and task.spec.arrival_time == clock:
                task.state = State.READY
                _event(events, clock, "TASK_ARRIVED", task.task_id, None, f"{task.task_id} entered READY at arrival time.")
                _event(events, clock, "TASK_READY", task.task_id, None, "Task is eligible for scheduling.")

        for task in tasks:
            if task.state != State.READY or task.spec.lock_request_at is None or task.lock_acquired_at is not None or task.lock_released_at is not None:
                continue
            if task.executed_cpu < task.spec.lock_request_at:
                continue
            if resource.owner is None:
                resource.owner = task.task_id
                task.lock_acquired_at = clock
                _event(events, clock, "LOCK_ACQUIRED", task.task_id, resource.resource_id, f"{task.task_id} acquired exclusive resource {resource.resource_id}.")
            elif resource.owner != task.task_id:
                task.state = State.BLOCKED
                blocked_on[task.task_id] = resource.resource_id
                if task.task_id not in resource.waiting_tasks:
                    resource.waiting_tasks.append(task.task_id)
                _event(events, clock, "LOCK_REQUEST_BLOCKED", task.task_id, resource.resource_id, f"{task.task_id} blocked because {resource.owner} owns {resource.resource_id}.")

        owner_by_resource = {resource.resource_id: resource.owner}
        priorities_before = {task.task_id: task.effective_priority for task in tasks}
        if policy == "Priority + PIP + Aging":
            recompute_inheritance(tasks, blocked_on, owner_by_resource)
        else:
            for task in tasks:
                task.effective_priority = task.base_priority
        for task in tasks:
            if task.effective_priority != priorities_before[task.task_id]:
                event_type = "PRIORITY_INHERITED" if task.effective_priority > priorities_before[task.task_id] else "PRIORITY_RESTORED"
                _event(events, clock, event_type, task.task_id, resource.resource_id, f"Effective priority changed from {priorities_before[task.task_id]} to {task.effective_priority}.")
        running = select_task(tasks, policy)
        if running:
            running.state = State.RUNNING
            if running.start_time is None:
                running.start_time = clock
            running.execution_history.append(clock)
            _event(events, clock, "TASK_RUNNING", running.task_id, resource.resource_id if resource.owner == running.task_id else None, "Selected by the active scheduling policy.")
        elif not all(task.state == State.COMPLETED for task in tasks):
            _event(events, clock, "SCHEDULER_IDLE", None, None, "No READY task can execute at this tick.")

        inversion_now = bool(
            resource.owner
            and any(task.state == State.BLOCKED and task.spec.base_priority == 3 and blocked_on.get(task.task_id) == resource.resource_id for task in tasks)
            and running is not None
            and running.spec.base_priority == 2
        )
        if inversion_now and not inversion_active:
            inversion_active = True
            inversion_start = clock
            _event(events, clock, "PRIORITY_INVERSION_DETECTED", running.task_id if running else None, resource.resource_id, "A high-priority task is blocked while medium-priority work runs and a lower-priority owner is delayed.")
        if not inversion_now and inversion_active:
            inversion_active = False
            inversion_durations.append(clock - (inversion_start or clock))

        for task in tasks:
            if task.state == State.BLOCKED:
                task.blocked_time += 1
            elif task.state == State.READY and task is not running:
                task.ready_wait += 1

        if running:
            running.executed_cpu += 1
            running.remaining_cpu -= 1
            if running.spec.lock_request_at is not None and resource.owner == running.task_id and running.lock_acquired_at is not None:
                held_ticks = clock - running.lock_acquired_at + 1
                if held_ticks >= running.spec.lock_duration:
                    resource.owner = None
                    running.lock_released_at = clock + 1
                    _event(events, clock + 1, "LOCK_RELEASED", running.task_id, resource.resource_id, f"{running.task_id} released {resource.resource_id} after its critical section.")
                    for waiting_id in list(resource.waiting_tasks):
                        waiting = task_map[waiting_id]
                        waiting.state = State.READY
                        blocked_on.pop(waiting_id, None)
                        _event(events, clock + 1, "TASK_UNBLOCKED", waiting_id, resource.resource_id, f"{waiting_id} returned to READY after {resource.resource_id} was released.")
                    resource.waiting_tasks.clear()
            if running.remaining_cpu == 0:
                running.state = State.COMPLETED
                running.completion_time = clock + 1
                _event(events, clock + 1, "TASK_COMPLETED", running.task_id, None, "CPU burst completed.")
            else:
                running.state = State.READY

        for task in tasks:
            timeline.append({
                "Tick": clock,
                "Task": task.task_id,
                "State": "RUNNING" if task is running else task.state.value,
                "Base priority": task.base_priority,
                "Effective priority": task.effective_priority,
                "Resource": resource.resource_id if resource.owner == task.task_id else (resource.resource_id if task.state == State.BLOCKED else ""),
            })

        if all(task.state == State.COMPLETED for task in tasks):
            elapsed = clock + 1
            if inversion_active:
                inversion_durations.append(elapsed - (inversion_start or elapsed))
            metrics = calculate_metrics(tasks, events, elapsed)
            metrics["inversion_duration"] = float(sum(inversion_durations))
            return SimulationResult(policy, tasks, events, timeline, metrics, elapsed, resource)

    raise RuntimeError(f"Simulation did not complete within {max_ticks} ticks.")


def default_state_distribution(policy: str) -> dict[str, int]:
    return state_distribution(run_simulation(policy).tasks)
