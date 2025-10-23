from zoneinfo import ZoneInfo

import arrow
from cascade.compiler.ast import CascadeConfig, Dependencies, Status
from cascade.optimizer import *
from cascade.compiler import *
from datetime import timedelta

from typing import List

DEFAULT_TZ = ZoneInfo("Europe/London")

START = arrow.get("1970-01-01").datetime


def ast_to_sol(src: TaskAST, total_dur: timedelta) -> Schedule:
    ast = ProcessedAST.from_raw_ast(src)
    return schedule(ast, START, START + total_dur)


def test_cuf_model():
    """
    This test tests the cumulative-utility-function layer of our optimization model which compares the CUF of two schedules with the same maximum end utility
    """
    # setting up the tasks
    tasks: List[Step | Goal] = [
        Step(name="Task A", status=Status.todo, duration=DURATION_UNIT),
        Step(name="Task B", status=Status.todo, duration=4 * DURATION_UNIT),
        Step(name="Task C", priority=2, status=Status.todo, duration=DURATION_UNIT),
    ]
    ast = TaskAST(config=CascadeConfig(default_tz=DEFAULT_TZ, log=True), tasks=tasks)

    sol = ast_to_sol(ast, 20 * DURATION_UNIT)
    sol.print_schedule()

    assert sol.get_total_utility() == 4 * YSCALE
    assert sol.get_total_length_slots() == 10
    sorted_id = list(
        map(lambda kv: kv[0], sorted(sol.schedule.items(), key=lambda kv: kv[1].start))
    )
    assert sorted_id == ["task-c", "task-a", "task-b"]


def test_prereq_enforcement():
    """
    This test tests whether "length zero" scheduling is properly understood as "not scheduled" by the model.
    """
    # Tune up confidence so each task's utility saturates by the expected duration specified
    c = 4
    # setting up the tasks
    tasks: List[Step | Goal] = [
        Step(
            name="A",
            status=Status.todo,
            duration=DURATION_UNIT,
            confidence=c,
            deps=Dependencies(before=set(["b", "c", "d", "e", "f"])),
        ),
        Step(
            name="B",
            status=Status.todo,
            duration=DURATION_UNIT,
            confidence=c,
            deps=Dependencies(before=set(["c", "d", "e", "f"])),
        ),
        Step(
            name="C",
            status=Status.todo,
            duration=DURATION_UNIT,
            confidence=c,
            deps=Dependencies(before=set(["d", "e", "f"])),
        ),
        Step(
            name="D",
            status=Status.todo,
            duration=DURATION_UNIT,
            confidence=c,
            deps=Dependencies(before=set(["e", "f"])),
        ),
        Step(
            name="E",
            status=Status.todo,
            duration=DURATION_UNIT,
            confidence=c,
            deps=Dependencies(before=set(["f"])),
        ),
        Step(name="F", status=Status.todo, duration=DURATION_UNIT),
    ]
    ast = TaskAST(config=CascadeConfig(default_tz=DEFAULT_TZ, log=True), tasks=tasks)

    # we squeeze the scheduler so it can only schedule 3 tasks. Due to dependencies the only viable solution is a, b, c
    sol = ast_to_sol(ast, 3 * DURATION_UNIT)
    sol.print_schedule()
    assert sol.get_total_utility() == 3 * YSCALE
    # sorted and filtered
    sorted_id = list(
        map(
            lambda kv: kv[0],
            filter(
                lambda x: x[1].task_length != 0,
                sorted(sol.schedule.items(), key=lambda kv: kv[1].start),
            ),
        )
    )
    assert sorted_id == ["a", "b", "c"]
