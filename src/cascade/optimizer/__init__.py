"""
Converted from ProcessedAST to CompiledModel which can be solved by CP-SAT solver.
- all dates and durations are resolved using DURATION_UNIT
- all constraints populated
- all variables populated
"""

from __future__ import annotations
from itertools import chain
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple
from prompt_toolkit import HTML, print_formatted_text
from typing_extensions import Self, Dict
from ortools.sat.python import cp_model

from cascade.compiler import DURATION_UNIT
from cascade.compiler.ast import Status
from .helpers import piecewise_linear_objective
from .piecewise_functions.piecewise_linear_function import (
    PiecewiseLinearConstraint,
)
from cascade.compiler.processed_ast import AtomicTask, ProcessedAST

# Scale on the CDF's value
YSCALE = 100


def datetime_to_slot(dt: datetime, schedule_start: datetime) -> int:
    return (dt - schedule_start) // DURATION_UNIT


def get_total_slots(schedule_start: datetime, schedule_end: datetime) -> int:
    return datetime_to_slot(schedule_end, schedule_start)


def get_nodes(ast: ProcessedAST) -> Dict[str, AtomicTask]:
    return {id: node for id, node in ast.nodes.items() if node.status == Status.todo}


def get_converted_ddl(
    nodes: Dict[str, AtomicTask], schedule_start: datetime
) -> Dict[str, int]:
    """
    Converts deadlines from timestamp to integers
    """
    return {
        id: datetime_to_slot(node.deadline, schedule_start)
        for id, node in nodes.items()
        if node.deadline
    }


def from_slot_to_datetime(n: int, schedule_start: datetime) -> datetime:
    return schedule_start + n * DURATION_UNIT


@dataclass
class ScheduleDetail:
    name: str
    start: datetime
    end: datetime
    task_length: int
    task_score: float


@dataclass
class Schedule:
    schedule: Dict[str, ScheduleDetail]

    def get_total_score(self) -> float:
        return sum(detail.task_score for detail in self.schedule.values())

    def get_total_length_slots(self) -> int:
        return sum(detail.task_length for detail in self.schedule.values())

    def print_schedule(self):
        print_formatted_text(
            HTML(f"<b>Total utility:</b> {self.get_total_score() / YSCALE}")
        )
        print_formatted_text(
            HTML(
                f"<b>Total length:</b> {self.get_total_length_slots() * DURATION_UNIT}"
            )
        )
        sorted_schedule = sorted(
            self.schedule.items(), key=lambda kv: self.schedule[kv[0]].start
        )
        for id, detail in sorted_schedule:
            if detail.task_length == 0:
                print_formatted_text(
                    HTML(
                        f'<b>Task <ansimagenta>"{detail.name}"<grey>({id})</grey></ansimagenta> is <red>not scheduled</red></b>'
                    )
                )
            else:
                formatted_output = HTML(
                    f'<b>Task <ansimagenta>"{detail.name}"</ansimagenta></b> scheduled at '
                    f"<skyblue>{detail.start}</skyblue> → <skyblue>{detail.end}</skyblue>. "
                    f"Length: <b><ansigreen>{detail.task_length * DURATION_UNIT}</ansigreen></b>, "
                    f"Utility: <ansiyellow>{detail.task_score/YSCALE}</ansiyellow>"
                )
                print_formatted_text(formatted_output)


@dataclass
class BasicModel:
    """
    Enforcing dependencies only
    """

    ast: ProcessedAST
    model: cp_model.CpModel
    intervals: Dict[str, cp_model.IntervalVar]
    schedule_start: datetime
    schedule_end: datetime

    def to_utility_model(self) -> UtilityModel:
        return UtilityModel.from_basic_model(self)

    def get_nodes(self) -> Dict[str, AtomicTask]:
        return get_nodes(self.ast)

    def get_total_slots(self) -> int:
        return get_total_slots(self.schedule_start, self.schedule_end)

    @classmethod
    def from_processed_ast(
        cls, ast: ProcessedAST, schedule_start: datetime, schedule_end: datetime
    ) -> Self:
        nodes = get_nodes(ast)
        total_slots = get_total_slots(schedule_start, schedule_end)

        model = cp_model.CpModel()

        # populates start_time_vars
        start_time_vars: Dict[str, cp_model.IntVar] = {
            id: model.new_int_var(0, total_slots - node.duration, f"start_time_{id}")
            for id, node in nodes.items()
        }

        end_time_vars: Dict[str, cp_model.IntVar] = {
            id: model.new_int_var(node.duration, total_slots, f"end_time_{id}")
            for id, node in nodes.items()
        }

        # NOTE: Here optional scheduling is actually built-in by saying length == 0
        length_vars: Dict[str, cp_model.IntVar] = {
            id: model.new_int_var(0, 2 * nodes[id].duration, f"end_time_{id}")
            for id in nodes.keys()
        }

        interval_vars: Dict[str, cp_model.IntervalVar] = {
            id: model.new_interval_var(
                start=start_time_vars[id],
                size=length_vars[id],
                end=end_time_vars[id],
                name=f"interval_var_{id}",
            )
            for id in nodes.keys()
        }

        # Add sleep intervals
        bg_intervals = []
        for bg_task in ast.bg.values():
            starts = [
                datetime_to_slot(start, schedule_start)
                for start in bg_task.get_sessions(schedule_start, schedule_end)
            ]
            bg_duration = bg_task.duration // DURATION_UNIT
            bg_intervals += [
                # If no overlapping then name will not clash as well
                model.new_fixed_size_interval_var(
                    start, bg_duration, f"bg_task_start_{start}"
                )
                for start in starts
            ]

        # No parallel tasks
        model.add_no_overlap(chain(interval_vars.values(), bg_intervals))

        # Enforce dependencies
        for id, node in nodes.items():
            for prereq in node.deps:
                model.add(
                    interval_vars[prereq].end_expr() <= interval_vars[id].start_expr()
                )

        return cls(ast, model, interval_vars, schedule_start, schedule_end)


@dataclass
class UtilityModel(BasicModel):
    scores: Dict[str, PiecewiseLinearConstraint]
    # Only used for printing
    before_ddls: Dict[str, cp_model.IntVar]
    after_ddls: Dict[str, cp_model.IntVar]
    clippeds: Dict[str, cp_model.IntVar]

    def to_interval_len_model(self) -> IntervalLenModel:
        return IntervalLenModel.from_utility_model(self)

    # NOTE: This will be inherited for all the rest models
    def solve(self) -> Schedule:
        solver = cp_model.CpSolver()
        # solver.parameters.log_search_progress = True
        status = solver.solve(self.model)

        sol = Schedule(
            {
                id: ScheduleDetail(
                    self.ast.nodes[id].name,
                    from_slot_to_datetime(
                        solver.value(var.start_expr()), self.schedule_start
                    ),
                    from_slot_to_datetime(
                        solver.value(var.end_expr()), self.schedule_start
                    ),
                    solver.value(var.size_expr()),
                    solver.value(self.scores[id].y),
                )
                for id, var in self.intervals.items()
            }
        )

        match status:
            case cp_model.OPTIMAL | cp_model.FEASIBLE:
                pass
            case cp_model.INFEASIBLE:
                raise Exception("No solution found.")
            case cp_model.UNKNOWN:
                raise Exception("Limit reached")

        return sol

    @classmethod
    def from_basic_model(cls, basic_model: BasicModel) -> Self:
        nodes = basic_model.get_nodes()
        total_slots = basic_model.get_total_slots()
        converted_ddl = get_converted_ddl(nodes, basic_model.schedule_start)

        model = basic_model.model
        interval_vars = basic_model.intervals

        # Use variables to represent per-task score
        scores = {}

        # Calculate the available time to complete the task
        available_times: Dict[str, cp_model.IntVar] = {
            id: model.new_int_var(
                0,
                total_slots,
                f"available_time_{id}",
            )
            for id in nodes.keys()
        }

        before_ddls = {}
        after_ddls = {}
        clippeds = {}
        for id, node in nodes.items():
            if node.deadline:
                # Basically a pattern matching case here
                before_ddl = model.new_bool_var(f"before_ddl_{id}")
                clipped = model.new_bool_var(f"clipped_{id}")
                after_ddl = model.new_bool_var(f"after_ddl_{id}")

                model.add_exactly_one([before_ddl, clipped, after_ddl])
                # Before
                model.add(
                    interval_vars[id].end_expr() <= converted_ddl[id]
                ).only_enforce_if(before_ddl)
                # After
                model.add(
                    converted_ddl[id] < interval_vars[id].start_expr()
                ).only_enforce_if(after_ddl)
                # In between
                model.add(
                    interval_vars[id].start_expr() <= converted_ddl[id]
                ).only_enforce_if(clipped)
                model.add(
                    converted_ddl[id] < interval_vars[id].end_expr()
                ).only_enforce_if(clipped)

                model.add(
                    available_times[id] == interval_vars[id].size_expr()
                ).only_enforce_if(before_ddl)
                model.add(
                    available_times[id]
                    == converted_ddl[id] - interval_vars[id].start_expr()
                ).only_enforce_if(clipped)
                model.add(available_times[id] == 0).only_enforce_if(after_ddl)

                before_ddls[id] = before_ddl
                after_ddls[id] = after_ddl
                clippeds[id] = clipped
            else:
                model.add(available_times[id] == interval_vars[id].size_expr())

        # set the objective function for each task
        for id, node in nodes.items():
            f_objective = piecewise_linear_objective(
                node.duration,
                # TODO: we need to come up with a more sensible way of specifying confidence
                node.duration // (node.confidence + 3),
                node.priority,
                total_slots,
                stepsize=1,
                yscale=YSCALE,
            )
            scores[id] = PiecewiseLinearConstraint(
                model,
                available_times[id],
                f_objective,
                upper_bound=True,
            )

        objective = sum([score.y for score in scores.values()])

        model.maximize(objective)

        return cls(
            scores=scores,
            before_ddls=before_ddls,
            after_ddls=after_ddls,
            clippeds=clippeds,
            **vars(basic_model),
        )


@dataclass
class IntervalLenModel(UtilityModel):
    @classmethod
    def from_utility_model(cls, utility_model: UtilityModel) -> Self:
        # Get the optimal goal from utility_model
        utility_score = utility_model.solve().get_total_score()
        model = utility_model.model
        scores = utility_model.scores
        model.clear_objective()

        model.add(sum([score.y for score in scores.values()]) >= utility_score)
        model.minimize(
            sum([interval.size_expr() for interval in utility_model.intervals.values()])
        )

        return cls(**vars(utility_model))
