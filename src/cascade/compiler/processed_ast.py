"""
Contains the second pass AST which has all deadline, dependencies, tags etc. propagated.

The tree will only contain "step" tasks.
"""

import math
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Set, Optional, Self

from cascade.compiler import DURATION_UNIT
from cascade.compiler.ast import BackgroundTask, Status, TaskAST


@dataclass
class AtomicTask:
    name: str
    id: str
    status: Status
    priority: int
    confidence: int
    # In unit of DURATION_UNIT
    duration: int
    # expressed as `after`
    deps: Set[str]
    deadline: Optional[datetime]
    # a positive integer specifying if the task is duplicated.
    dup: int = 1


@dataclass
class ProcessedAST:
    nodes: Dict[str, AtomicTask]
    bg: Dict[str, BackgroundTask]

    @classmethod
    def from_raw_ast(cls, raw_ast: TaskAST) -> Self:
        """
        Convert a raw AST to a processed AST with deadlines and dependencies propagated.

        It also has timestamp and duration converted according to the DURATION_UNIT
        """
        propogated = raw_ast.propogate_properties()
        # normalize dependencies
        normalized_steps = propogated.normalize_dependencies()

        result: Dict[str, AtomicTask] = {}

        # convert to atomic tasks
        for step in normalized_steps:
            result[step.id] = AtomicTask(
                name=step.name,
                id=step.id,
                status=step.status,
                priority=step.priority,
                confidence=step.confidence,
                duration=math.ceil(step.duration / DURATION_UNIT),
                deps=step.deps.after,
                deadline=step.deadline,
                # NOTE: dup is currently unused
            )

        return cls(result, raw_ast.get_background_tasks())
