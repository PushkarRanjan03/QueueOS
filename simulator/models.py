from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class State(str, Enum):
    NEW = "NEW"
    READY = "READY"
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    name: str
    base_priority: int
    arrival_time: int
    cpu_burst: int
    lock_request_at: int | None = None
    lock_duration: int = 0

    def __post_init__(self) -> None:
        if self.base_priority < 1:
            raise ValueError("Priority must be at least 1.")
        if self.arrival_time < 0:
            raise ValueError("Arrival time cannot be negative.")
        if self.cpu_burst < 1:
            raise ValueError("CPU burst must be positive.")
        if self.lock_request_at is not None and not 0 <= self.lock_request_at < self.cpu_burst:
            raise ValueError("Lock request must occur during the CPU burst.")
        if self.lock_duration < 0:
            raise ValueError("Lock duration cannot be negative.")


@dataclass
class TaskRuntime:
    spec: TaskSpec
    state: State = State.NEW
    effective_priority: int = 0
    remaining_cpu: int = 0
    executed_cpu: int = 0
    ready_wait: int = 0
    blocked_time: int = 0
    start_time: int | None = None
    completion_time: int | None = None
    lock_acquired_at: int | None = None
    lock_released_at: int | None = None
    execution_history: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.effective_priority = self.spec.base_priority
        self.remaining_cpu = self.spec.cpu_burst

    @property
    def task_id(self) -> str:
        return self.spec.task_id

    @property
    def base_priority(self) -> int:
        return self.spec.base_priority

    def requests_lock(self) -> bool:
        return self.spec.lock_request_at is not None and self.executed_cpu >= self.spec.lock_request_at


@dataclass(frozen=True)
class Event:
    time: int
    event_type: str
    task_id: str | None
    resource_id: str | None
    explanation: str


@dataclass
class Resource:
    resource_id: str
    owner: str | None = None
    waiting_tasks: list[str] = field(default_factory=list)

    @property
    def locked(self) -> bool:
        return self.owner is not None
