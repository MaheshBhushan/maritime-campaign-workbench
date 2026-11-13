from datetime import UTC, datetime, timedelta

import pytest

from mcw.scheduler import PlanTask, PlanVessel, ScheduleError, build_schedule

T0 = datetime(2026, 3, 2, 6, tzinfo=UTC)


def by_task(slots):
    return {s.task_id: s for s in slots}


def test_dependencies_and_vessel_exclusivity():
    vessels = [PlanVessel(1), PlanVessel(2)]
    tasks = [
        PlanTask(10, 1, 4),
        PlanTask(11, 1, 2),
        PlanTask(12, 2, 3, depends_on=(10,)),
    ]
    s = by_task(build_schedule(T0, vessels, tasks))
    assert s[10].start == T0 and s[10].end == T0 + timedelta(hours=4)
    # vessel 1 is busy until +4h, so task 11 follows task 10
    assert s[11].start == T0 + timedelta(hours=4)
    # vessel 2 is idle but must wait for its dependency
    assert s[12].start == s[10].end


def test_turnaround_gap_between_consecutive_tasks():
    s = by_task(build_schedule(T0, [PlanVessel(1, turnaround_hours=2)], [PlanTask(1, 1, 1), PlanTask(2, 1, 1)]))
    assert s[2].start == s[1].end + timedelta(hours=2)


def test_earliest_start_is_chosen_not_input_order():
    # task 2 depends on a long task; task 3 is free. Task 3 must not wait behind task 2.
    vessels = [PlanVessel(1), PlanVessel(2)]
    tasks = [PlanTask(1, 1, 10), PlanTask(2, 2, 1, depends_on=(1,)), PlanTask(3, 2, 1)]
    s = by_task(build_schedule(T0, vessels, tasks))
    assert s[3].start == T0
    assert s[2].start == T0 + timedelta(hours=10)


def test_fixture_shaped_plan():
    # Same structure as fixtures/campaign.json: survey(1) tender(2) tug(3)
    vessels = [PlanVessel(1, 2), PlanVessel(2, 1), PlanVessel(3, 0.5)]
    tasks = [
        PlanTask(1, 1, 4),
        PlanTask(2, 1, 10, (1,)),
        PlanTask(3, 2, 3),
        PlanTask(4, 2, 6, (3, 2)),
        PlanTask(5, 3, 5),
        PlanTask(6, 1, 3, (4,)),
    ]
    s = by_task(build_schedule(T0, vessels, tasks))
    h = lambda n: T0 + timedelta(hours=n)  # noqa: E731
    assert s[2].start == h(6)  # 4h transit + 2h turnaround
    assert s[4].start == h(16)  # after survey ends
    assert s[6].start == h(22)  # after lay ends; survey vessel free at 16+2
    assert s[6].end == h(25)


@pytest.mark.parametrize(
    "tasks,msg",
    [
        ([PlanTask(1, 9, 1)], "unknown vessel"),
        ([PlanTask(1, 1, 0)], "non-positive"),
        ([PlanTask(1, 1, 1, (7,))], "unknown tasks"),
        ([PlanTask(1, 1, 1, (2,)), PlanTask(2, 1, 1, (1,))], "cycle"),
    ],
)
def test_invalid_plans_rejected(tasks, msg):
    with pytest.raises(ScheduleError, match=msg):
        build_schedule(T0, [PlanVessel(1)], tasks)
