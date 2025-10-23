"""
Contains first pass AST, which upon construction, ensures syntax and semantics are correct
"""

from __future__ import annotations
import re
from ics import Calendar
from zoneinfo import ZoneInfo
import requests
from enum import Enum
from croniter import croniter, croniter_range
import pytimeparse
from copy import copy, deepcopy
from typing import (
    ClassVar,
    Dict,
    Optional,
    Pattern,
    Union,
    Any,
    Annotated,
    Set,
    override,
)
from typing_extensions import Self
from datetime import datetime, time, timedelta
from slugify import slugify
from prompt_toolkit import HTML, print_formatted_text
from urllib.request import url2pathname
from pydantic import (
    AfterValidator,
    BeforeValidator,
    FileUrl,
    HttpUrl,
    NaiveDatetime,
    Tag,
    BaseModel,
    Discriminator,
    field_validator,
    model_validator,
    Field,
    Discriminator,
)


class Status(str, Enum):
    todo = "todo"
    done = "done"


class Dependencies(BaseModel):
    before: Set[str] = Field(default_factory=set)
    after: Set[str] = Field(default_factory=set)


def parse_time(value: Any) -> time:
    if isinstance(value, str):
        try:
            return datetime.strptime(value, "%H:%M").time()
        except ValueError:
            raise ValueError("Time must be in HH:mm format")
    else:
        return value


def parse_cron(value: Any) -> str:
    if isinstance(value, str):
        if croniter.is_valid(value):
            return value
        else:
            raise ValueError(f"Invalid cron expression: {value}")
    else:
        return value


def parse_duration(value: Any) -> timedelta:
    if isinstance(value, str):
        parsed = pytimeparse.parse(value)
        if not parsed:
            raise ValueError(f"Invalid duration format: {value}")
        return timedelta(seconds=int(parsed))
    else:
        return value


def parse_timezone(value: Any) -> ZoneInfo:
    if isinstance(value, str):
        try:
            parsed = ZoneInfo(value)
        except:
            raise ValueError(f"Invalid timezone: {value}")
        return parsed
    else:
        return value


class BaseTask(BaseModel):
    name: str
    # NOTE: order matters as we access name in the default factory
    id: str = Field(default_factory=lambda data: slugify(data["name"]))
    desc: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    deadline: Optional[NaiveDatetime] = None
    timezone: Optional[Annotated[ZoneInfo, BeforeValidator(parse_timezone)]] = None
    # 1 is the lowest, higher number means higher priority
    priority: int = 1
    deps: Dependencies = Field(default_factory=Dependencies)

    def update_timezone(self, default: Optional[ZoneInfo]):
        tz = self.timezone or default
        if self.deadline:
            self.deadline = self.deadline.replace(tzinfo=tz)

    def update_ddl(self, ddl: datetime):
        """
        Update the deadline of the task if the ddl provided is earlier than the existing one.
        """
        match self.deadline:
            case None:
                self.deadline = ddl
            case x if x > ddl:
                self.deadline = ddl
            case _:
                pass

    def check_refs(self, ast: TaskAST) -> Set[str]:
        defined_ids = ast.get_ids()
        refs = set()
        refs.update(self.deps.before)
        refs.update(self.deps.after)

        return set(x for x in refs if x not in defined_ids)

    def check_deadlines(self, ast: TaskAST):
        # we are guaranteed that dependencies are inverted so we only need to check the after branch:
        if not self.deadline:
            return

        conflicting_ddls: Set[str] = set()
        tasks = ast.get_tasks_in_dict()

        for t in self.deps.after:
            # Just to quiet pyright
            subtask = tasks[t]
            if subtask.deadline:
                if subtask.deadline > self.deadline:
                    conflicting_ddls.add(t)

        if len(conflicting_ddls) > 0:
            raise ValueError(
                f'Tasks {conflicting_ddls} have deadlines later than "{self.name}", contradicting with the dependency relation'
            )

    def check_deps_graph(self, ast: TaskAST, safe: list[str], stack: list[str]):
        if self.id in safe:
            return
        if self.id in stack:
            raise ValueError(
                f"Dependency cycle detected: {' -> '.join(stack + [self.id])}"
            )
        stack.append(self.id)
        for dep in self.deps.after:
            ts = ast.get_tasks_in_dict()
            ts[dep].check_deps_graph(ast, safe, stack)
        safe.append(self.id)
        stack.pop()

    def propogate_ddl(self, ast: TaskAST):
        pass

    def propogate_priority(self, ast: TaskAST):
        pass


class Step(BaseTask):
    """
    A step task
    """

    type: ClassVar[str] = "step"
    status: Status
    duration: Annotated[timedelta, BeforeValidator(parse_duration)]
    confidence: int = 1

    @model_validator(mode="after")
    def validate_step(self) -> Self:
        return self


class Goal(BaseTask):
    """
    A goal task
    """

    type: ClassVar[str] = "goal"

    subtasks: list[str]
    implicit_deps_by_order: Optional[bool] = False

    @model_validator(mode="after")
    def validate_goal(self) -> Self:
        return self

    @override
    def check_refs(self, ast: TaskAST) -> Set[str]:
        defined_ids = ast.get_ids()
        refs = self.subtasks

        super_undefined_ids = super().check_refs(ast)

        return set(x for x in refs if x not in defined_ids).union(super_undefined_ids)

    def collect_leaf_tasks(self, ast: TaskAST) -> Set[str]:
        """
        Collects all leaf tasks (steps) under this goal.
        """
        leaf_tasks = set()
        tasks_dict = ast.get_tasks_in_dict()
        for subtask_id in self.subtasks:
            subtask = tasks_dict[subtask_id]
            if isinstance(subtask, Step):
                leaf_tasks.add(subtask_id)
            elif isinstance(subtask, Goal):
                leaf_tasks.update(subtask.collect_leaf_tasks(ast))
        return leaf_tasks

    @override
    def propogate_ddl(self, ast: TaskAST):
        if not self.deadline:
            return
        tasks_dict = ast.get_tasks_in_dict()
        for t in self.subtasks:
            tasks_dict[t].update_ddl(self.deadline)

    @override
    def propogate_priority(self, ast: TaskAST):
        """
        Propagate priorities by multiplying the priorities of its dependent tasks

        This is good because priorities are then relative between tasks at the same level, you don't have to assign a global priority to every task.
        """
        tasks_dict = ast.get_tasks_in_dict()
        for t in self.subtasks:
            tasks_dict[t].priority *= self.priority

    def inject_implicit_deps(self, ast: TaskAST):
        """
        Inject implicit dependencies specified by subtask ordering. This should be done before dependency graph checking
        """
        if self.implicit_deps_by_order:
            for i in range(1, len(self.subtasks)):
                ast.get_tasks_in_dict()[self.subtasks[i]].deps.after.update(
                    self.subtasks[:i]
                )


def get_task_type(v: Any) -> str:
    if isinstance(v, dict):
        if "subtasks" in v:
            return "goal"
        else:
            return "step"
    else:
        if hasattr(v, "subtasks"):
            return "goal"
        else:
            return "step"


# NOTE: We interpret these cron schedule as local time because they are mainly for sleep schedule etc. For timezone specific events use BackgroundCalendar
class BackgroundTask(BaseModel):
    schedule: Annotated[str, BeforeValidator(parse_cron)]
    duration: Annotated[timedelta, BeforeValidator(parse_duration)]

    def get_sessions(
        self, schedule_start: datetime, schedule_end: datetime
    ) -> list[datetime]:
        """
        Returns a list of background task session start time given schedule range.

        This doesn't check whether session start/end are within the schedule. It just ensures we don't miss any session, including fractional ones
        """
        return list(
            croniter_range(
                schedule_start - timedelta(days=1), schedule_end, self.schedule
            )
        )


class BackgroundCalendar(BaseModel):
    url: Union[HttpUrl, FileUrl]
    # on default allows all events
    filter: Set[str] = set()
    # use filter as a whitelist or blacklist
    whitelist: bool = False

    def matches(self, name: str):
        name = name.casefold()
        if self.whitelist:
            return any(s.casefold() in name for s in self.filter)
        else:
            return not any(s.casefold() in name for s in self.filter)

    def get_calendar(self) -> Calendar:
        cal = Calendar(self.get_raw())
        return Calendar(events=[e for e in cal.events if self.matches(e.name)])

    def get_raw(self) -> str:
        path = self.url
        raw_url = str(path)

        if isinstance(path, HttpUrl):
            response = requests.get(raw_url, timeout=10)
            print_formatted_text(
                HTML(f"<grey>Downloading calendar from {path} ...</grey>")
            )
            # Raise an exception for bad status codes (4xx or 5xx)
            response.raise_for_status()
            return response.text
        else:
            # Convert the file URI's path to a system-specific file path.
            # This correctly handles different OS path formats.
            file_path = url2pathname(path.path or "")

            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()


class CascadeConfig(BaseModel):
    default_tz: Annotated[ZoneInfo, AfterValidator(parse_timezone)]
    log: bool = False
    solver_timeout: int = 120


class TaskAST(BaseModel):
    """
    An AST describing tasks.

    Upon construction, it ensures:
    - dependency graph (implied by `deps` and `subtasks`) is a DAG
    - deadlines of subtasks are compatible with the parent task
    """

    config: CascadeConfig
    bg: Dict[str, Union[BackgroundTask, BackgroundCalendar]] = {}
    tasks: list[
        Annotated[
            Union[Annotated[Step, Tag("step")], Annotated[Goal, Tag("goal")]],
            Discriminator(get_task_type),
        ]
    ]

    def get_tasks(self) -> list[Union[Step, Goal]]:
        """
        Returns the list of tasks in the file.
        """
        return self.tasks

    def get_background_tasks(
        self,
    ) -> Dict[str, Union[BackgroundTask, BackgroundCalendar]]:
        return self.bg

    def get_tasks_in_dict(self) -> dict[str, Union[Step, Goal]]:
        return dict((x.id, x) for x in self.get_tasks())

    def get_steps(self) -> list[Step]:
        return [x for x in self.get_tasks() if isinstance(x, Step)]

    def get_goals(self) -> list[Goal]:
        return [x for x in self.get_tasks() if isinstance(x, Goal)]

    def _invert_dependencies(self):
        tasks = self.get_tasks_in_dict()
        for task in self.get_tasks():
            # invert dependencies
            for t in task.deps.before:
                tasks[t].deps.after.add(task.id)
            task.deps.before.clear()

    def _convert_goal_to_deps(self):
        for task in self.get_tasks():
            if isinstance(task, Goal):
                # convert goal to deps
                task.deps.after.update(task.subtasks)

    def normalize_dependencies(self) -> list[Step]:
        """
        Normalize dependencies:
        - express all dependencies through `after`
        - propagate transitive dependencies if src/target is goal instead of step

        The result is that a set of steps where each step only has an `after` tag of other steps
        """
        self_copy = deepcopy(self)
        self_copy._invert_dependencies()
        tasks = self_copy.get_tasks_in_dict()
        for task in self_copy.get_tasks():
            result = copy(task.deps.after)
            for t in task.deps.after:
                # Just to quiet pyright
                subtask = tasks[t]
                if isinstance(subtask, Goal):
                    # propagate dependencies from goal to its subtasks
                    result.update(subtask.collect_leaf_tasks(self_copy))
                    # remove goal
                    result.remove(t)
            task.deps.after = result

        return self_copy.get_steps()

    @model_validator(mode="after")
    def check(self) -> Self:
        self.check_refs()
        self.check_deadlines()
        # NOTE: Implicit dependency injection should be done before deps checking
        for goal in self.get_goals():
            goal.inject_implicit_deps(self)
        self.check_deps_graph()
        return self

    def get_ids(self):
        return {task.id for task in self.get_tasks()}

    def check_refs(self):
        undefined_ids = set()
        for task in self.get_tasks():
            undefined_ids.update(task.check_refs(self))

        if len(undefined_ids) > 0:
            raise ValueError(f"Reference to undefined task ID: {undefined_ids}")

    def check_deps_graph(self):
        self_copy = deepcopy(self)
        # NOTE: _invert_dependencies and _convert_goal_to_deps are enough for graph check, we don't need to propagate transitive dependencies
        self_copy._invert_dependencies()
        # make dependencies relation implied in "subtasks" explicit.
        self_copy._convert_goal_to_deps()

        safe: list[str] = []

        for task in self_copy.get_tasks():
            task.check_deps_graph(self_copy, safe, [])

    def check_deadlines(self):
        """
        Check deadlines are consistent with `after` semantics

        Note that we don't need to propogate dependencies for this.
        """
        self_copy = deepcopy(self)
        self_copy._invert_dependencies()
        # make dependencies relation implied in "subtasks" explicit.
        self_copy._convert_goal_to_deps()
        for task in self_copy.get_tasks():
            task.check_deadlines(self)

    def topo_sort(self) -> list[str]:
        self_copy = deepcopy(self)
        self_copy._invert_dependencies()
        self_copy._convert_goal_to_deps()

        topo_sorted: list[str] = []

        tasks = self_copy.get_tasks_in_dict()
        # IDs with no inbound
        ids_with_no_inbound = set(tasks.keys())

        # populate it first
        for task in tasks.values():
            if len(task.deps.after) > 0:
                ids_with_no_inbound.remove(task.id)

        while len(ids_with_no_inbound) > 0:
            # propagate the deadline
            for id in ids_with_no_inbound:
                topo_sorted.append(id)
                tasks.pop(id)

            # update dependency graph
            for task in tasks.values():
                task.deps.after = task.deps.after - ids_with_no_inbound

            ids_with_no_inbound = set(tasks.keys())

            for task in tasks.values():
                if len(task.deps.after) > 0:
                    ids_with_no_inbound.remove(task.id)

        if len(tasks) > 0:
            # our graph is not a DAG, this is not supposed to happen because we are supposed to check our graph on construction
            raise Exception("The graph is not a DAG, failed to propagate deadlines")

        return topo_sorted

    def propogate_properties(self) -> Self:
        result_copy = deepcopy(self)

        # TODO: It's probably more efficient if we reverse the edges used in topological sort. However, our stored format is not very favorable for this.
        for id in reversed(self.topo_sort()):
            result_copy.get_tasks_in_dict()[id].update_timezone(self.config.default_tz)
            result_copy.get_tasks_in_dict()[id].propogate_ddl(result_copy)
            result_copy.get_tasks_in_dict()[id].propogate_priority(result_copy)

        return result_copy
