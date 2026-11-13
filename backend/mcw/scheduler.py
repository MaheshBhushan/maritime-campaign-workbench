"""Deterministic campaign scheduler.

NeuroPlan turned a list of goals and tasks into time blocks by asking an LLM.
Here the same idea (tasks in, a timeline out) is made deterministic and
constraint-aware for a multi-vessel campaign:

* a task starts no earlier than the campaign start,
* a task starts only after every task it depends on has finished,
* a vessel performs one task at a time,
* a vessel idles for its turnaround time between consecutive tasks.

It is greedy list scheduling: among tasks whose dependencies are scheduled,
place the one that can start earliest (ties broken by task id), repeat.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


class ScheduleError(ValueError):
    pass


@dataclass(frozen=True)
class PlanTask:
    id: int
    vessel_id: int
    duration_hours: float
    depends_on: tuple[int, ...] = ()


@dataclass(frozen=True)
class PlanVessel:
    id: int
    turnaround_hours: float = 0.0


@dataclass(frozen=True)
class Slot:
    task_id: int
    vessel_id: int
    start: datetime
    end: datetime


def build_schedule(start: datetime, vessels: list[PlanVessel], tasks: list[PlanTask]) -> list[Slot]:
    vessel_ids = {v.id for v in vessels}
    task_ids = {t.id for t in tasks}
    for t in tasks:
        if t.vessel_id not in vessel_ids:
            raise ScheduleError(f"task {t.id} is assigned to unknown vessel {t.vessel_id}")
        if t.duration_hours <= 0:
            raise ScheduleError(f"task {t.id} has non-positive duration")
        missing = set(t.depends_on) - task_ids
        if missing:
            raise ScheduleError(f"task {t.id} depends on unknown tasks {sorted(missing)}")

    turnaround = {v.id: timedelta(hours=v.turnaround_hours) for v in vessels}
    vessel_free: dict[int, datetime] = {v.id: start for v in vessels}
    finished: dict[int, datetime] = {}
    pending = {t.id: t for t in tasks}
    slots: list[Slot] = []

    while pending:
        candidates: list[tuple[datetime, int]] = []
        for t in pending.values():
            if all(d in finished for d in t.depends_on):
                earliest = max([start, vessel_free[t.vessel_id], *(finished[d] for d in t.depends_on)])
                candidates.append((earliest, t.id))
        if not candidates:
            raise ScheduleError(f"dependency cycle among tasks {sorted(pending)}")
        begin, task_id = min(candidates)
        task = pending.pop(task_id)
        end = begin + timedelta(hours=task.duration_hours)
        slots.append(Slot(task_id=task_id, vessel_id=task.vessel_id, start=begin, end=end))
        finished[task_id] = end
        vessel_free[task.vessel_id] = end + turnaround[task.vessel_id]

    return slots

