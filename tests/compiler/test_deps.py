from cascade.compiler import *
from cascade.compiler.ast import CascadeConfig, Dependencies, Status
from typing import List
from zoneinfo import ZoneInfo

DEFAULT_TZ = ZoneInfo("Europe/London")


def test_implicit_deps():
    tasks: List[Step | Goal] = [
        Step(name="Task A", status=Status.todo, duration=DURATION_UNIT),
        Step(
            name="Task B",
            status=Status.todo,
            deps=Dependencies(after={"task-c"}),
            duration=DURATION_UNIT,
        ),
        Step(name="Task C", status=Status.todo, duration=DURATION_UNIT),
        Goal(
            name="Goal A",
            subtasks=["goal-b", "task-a"],
            implicit_deps_by_order=True,
        ),
        Goal(name="Goal B", subtasks=["task-b"]),
    ]
    ast = TaskAST(config=CascadeConfig(default_tz=DEFAULT_TZ), tasks=tasks)
    processed = ProcessedAST.from_raw_ast(ast)

    assert len(processed.nodes) == 3
    assert processed.nodes["task-a"].deps == {"task-b"}
    assert processed.nodes["task-b"].deps == {"task-c"}
    assert processed.nodes["task-c"].deps == set()
