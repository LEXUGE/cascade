"""
Contains the second pass AST which has all deadline, dependencies, tags etc. propagated.

The tree will only contain "step" tasks.
"""

from __future__ import annotations
import math
from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta, datetime
from typing import Dict, List, Set, Optional, Self

from ics import Calendar, Event

from cascade.compiler import DURATION_UNIT
from cascade.compiler.ast import (
    BackgroundCalendar,
    BackgroundTask,
    CascadeConfig,
    Status,
    TaskAST,
)


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
    bg: Dict[str, BackgroundTask | Calendar]
    config: CascadeConfig

    # Non-overlapping background block intervals
    def get_background_blocks(self, start: datetime, end: datetime) -> List[Event]:
        collected: List[Event] = []
        for bg_item in self.bg.values():
            if isinstance(bg_item, BackgroundTask):
                sessions = bg_item.get_sessions(start, end)
                collected += [
                    Event(begin=session_start, end=session_start + bg_item.duration)
                    for session_start in sessions
                ]
            elif isinstance(bg_item, Calendar):
                collected += bg_item.events
            else:
                raise NotImplementedError("Impossible")

        # merge blocks
        collected.sort(key=lambda x: x.begin)

        final = []

        prev_block = None
        for block in collected:
            # check if current block intersects with the previous block
            if prev_block is None:
                prev_block = block
                continue

            if prev_block.intersects(block):
                prev_block = prev_block.join(block)
            else:
                final.append(prev_block)
                prev_block = block

        final.append(prev_block)

        return final

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

        bg = {
            id: x.get_calendar() if isinstance(x, BackgroundCalendar) else x
            for id, x in raw_ast.get_background_tasks().items()
        }

        return cls(result, bg, raw_ast.config)
