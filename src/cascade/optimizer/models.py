"""
Converted from ProcessedAST to CompiledModel which can be solved by CP-SAT solver.
- all dates and durations are resolved using DURATION_UNIT
- all constraints populated
- all variables populated
"""

from __future__ import annotations
from itertools import chain
import html
from ics import Calendar, Event
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
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
    """
    Convert slot back to datetime, respecting the DURATION_UNIT gridding
    """
    return schedule_start + n * DURATION_UNIT


def schedule(ast: ProcessedAST, start: datetime, end: datetime) -> Schedule:
    sol = (
        BasicModel.from_processed_ast(ast, start, end)
        .to_total_utility_model()
        .to_cuf_model()
        .to_interval_model()
        .to_schedule()
    )
    return sol


@dataclass
class ScheduleDetail:
    name: str
    start: datetime
    end: datetime
    task_length: int
    task_utility: float
    max_utility: int


@dataclass
class Schedule:
    objective: int
    schedule: Dict[str, ScheduleDetail]
    schedule_start: datetime
    schedule_end: datetime

    def get_objective(self) -> int:
        return self.objective

    def get_total_utility(self) -> float:
        return sum([detail.task_utility for detail in self.schedule.values()])

    def get_total_length_slots(self) -> int:
        return sum(detail.task_length for detail in self.schedule.values())

    def to_ics(self) -> str:
        c = Calendar()
        for id, detail in self.schedule.items():
            if detail.task_length != 0:
                e = Event()
                e.name = detail.name
                e.begin = detail.start
                e.end = detail.end
                e.description = f"Task ID: {id}, Score: {detail.task_utility / YSCALE}"
                c.events.add(e)

        return c.serialize()

    def print_schedule(self):
        print_formatted_text(
            HTML(
                f"Schedule for <skyblue>{self.schedule_start}</skyblue> → <skyblue>{self.schedule_end}</skyblue>"
            )
        )
        print_formatted_text(
            HTML(f"<b>Total utility:</b> {self.get_total_utility() / YSCALE}")
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
                        f'<b>Task <ansimagenta>"{html.escape(detail.name)}"<grey>({id})</grey></ansimagenta> is <red>not scheduled</red></b>'
                    )
                )
            else:
                formatted_output = HTML(
                    f'<b>Task <ansimagenta>"{html.escape(detail.name)}"</ansimagenta></b> scheduled at '
                    f"<skyblue>{detail.start}</skyblue> → <skyblue>{detail.end}</skyblue>. "
                    f"Length: <b><ansigreen>{detail.task_length * DURATION_UNIT}</ansigreen></b>, "
                    f"Utility: <ansiyellow>{detail.task_utility/YSCALE}/{detail.max_utility}</ansiyellow>"
                )
                print_formatted_text(formatted_output)


def add_hints(model: cp_model.CpModel, solver: cp_model.CpSolver):
    model.clear_hints()
    for i, _ in enumerate(model.proto.variables):
        v_ = model.get_int_var_from_proto_index(i)
        model.add_hint(v_, solver.value(v_))


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

    def to_total_utility_model(self) -> TotalUtilityModel:
        return TotalUtilityModel.from_basic_model(self)

    def get_nodes(self) -> Dict[str, AtomicTask]:
        return get_nodes(self.ast)

    def get_total_slots(self) -> int:
        return get_total_slots(self.schedule_start, self.schedule_end)

    def solve(self) -> cp_model.CpSolver:
        solver = cp_model.CpSolver()
        solver.parameters.log_search_progress = True
        # stop when we are within 2% of the upper bound of optimum (provable) cause making it drop can take a long time.
        solver.parameters.relative_gap_limit = 0.02
        # since we are adding hints, models are no longer suffering from cold start issues, we might just add a time limit to solve plateau problem
        solver.parameters.max_time_in_seconds = 120
        status = solver.solve(self.model)

        match status:
            case cp_model.OPTIMAL | cp_model.FEASIBLE:
                pass
            case cp_model.INFEASIBLE:
                raise Exception("No solution found.")
            case cp_model.UNKNOWN:
                raise Exception("Limit reached")

        return solver

    # NOTE: `schedule_start` and `schedule_end` should be timezone aware when passed in
    @classmethod
    def from_processed_ast(
        cls, ast: ProcessedAST, schedule_start: datetime, schedule_end: datetime
    ) -> Self:
        # bring the start to the nearest next 5 mins mark (e.g. 10:06 -> 10:10)
        start_of_day = schedule_start.replace(hour=0, minute=0, second=0, microsecond=0)
        schedule_start = (
            start_of_day
            + (
                (schedule_start - start_of_day)
                + (DURATION_UNIT - timedelta(microseconds=1))
            )
            // DURATION_UNIT
            * DURATION_UNIT
        )

        if get_total_slots(schedule_start, schedule_end) < 0:
            raise RuntimeError(
                f"Schedule start time {schedule_start} is too close to/later than {schedule_end}"
            )

        nodes = get_nodes(ast)
        total_slots = get_total_slots(schedule_start, schedule_end)

        model = cp_model.CpModel()

        # populates start_time_vars
        start_time_vars: Dict[str, cp_model.IntVar] = {
            id: model.new_int_var(0, total_slots, f"start_time_{id}")
            for id, node in nodes.items()
        }

        end_time_vars: Dict[str, cp_model.IntVar] = {
            id: model.new_int_var(0, total_slots, f"end_time_{id}")
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

        # add background blocks over which we shouldn't schedule
        bg_blocks = []
        for block in ast.get_background_blocks(schedule_start, schedule_end):
            if block.duration:
                start = datetime_to_slot(block.begin.datetime, schedule_start)
                duration = block.duration // DURATION_UNIT
                bg_blocks.append(
                    # If no overlapping then name will not clash as well
                    model.new_fixed_size_interval_var(
                        start, duration, f"bg_task_start_{start}"
                    )
                )

        # No parallel tasks
        model.add_no_overlap(chain(interval_vars.values(), bg_blocks))

        # Enforce dependencies
        for id, node in nodes.items():
            for prereq in node.deps:
                model.add(
                    interval_vars[prereq].end_expr() <= interval_vars[id].start_expr()
                )

        return cls(ast, model, interval_vars, schedule_start, schedule_end)


@dataclass
class TotalUtilityModel(BasicModel):
    """
    Maximizes total utility of the schedule
    """

    utilities: Dict[str, PiecewiseLinearConstraint]
    # NOTE: These are not used in this model but we set them up in one place for convenience.
    cuf_int: Dict[str, PiecewiseLinearConstraint]
    cuf_prod: Dict[str, cp_model.IntVar]
    cuf: Dict[str, cp_model.IntVar]
    # Only used for printing
    before_ddls: Dict[str, cp_model.IntVar]
    after_ddls: Dict[str, cp_model.IntVar]
    clippeds: Dict[str, cp_model.IntVar]

    # It makes sense as basic layer cannot solve/print, and all subsequent layers can.
    def to_schedule(self) -> Schedule:
        solver = self.solve()
        nodes = self.get_nodes()

        return Schedule(
            int(solver.objective_value),
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
                    solver.value(self.utilities[id].y),
                    nodes[id].priority,
                )
                for id, var in self.intervals.items()
            },
            schedule_start=self.schedule_start,
            schedule_end=self.schedule_end,
        )

    def to_cuf_model(self) -> CUFModel:
        return CUFModel.from_total_utility_model(self)

    def set_objective_constraint(self):
        sol = self.solve()
        optimal = int(sol.objective_value)
        self.model.clear_objective()
        add_hints(self.model, sol)
        self.model.add(sum(utility.y for utility in self.utilities.values()) >= optimal)

    @classmethod
    def from_basic_model(cls, basic_model: BasicModel) -> Self:
        nodes = basic_model.get_nodes()
        total_slots = basic_model.get_total_slots()
        converted_ddl = get_converted_ddl(nodes, basic_model.schedule_start)

        model = basic_model.model
        interval_vars = basic_model.intervals

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

        # Use variables to represent per-task utility
        utilities = {}
        # integrated first part
        cuf_int = {}
        # trailing part multiplied
        cuf_prod = {}
        # cumulative-utility-function
        cuf = {}

        # set the objective function for each task
        for id, node in nodes.items():
            base_opts: Dict[str, Any] = {
                "mu_X": node.duration,
                # TODO: we need to come up with a more sensible way of specifying confidence
                "sigma_X": node.duration // (node.confidence + 3),
                "priority": node.priority,
                "total_slots": total_slots,
                "stepsize": 1,
                "yscale": YSCALE,
            }
            f_objective = piecewise_linear_objective(**base_opts)
            int_f_objective = piecewise_linear_objective(
                **(base_opts | {"integrated": True})
            )
            utilities[id] = PiecewiseLinearConstraint(
                model,
                available_times[id],
                f_objective,
                upper_bound=True,
            )
            cuf_int[id] = PiecewiseLinearConstraint(
                model,
                available_times[id],
                int_f_objective,
                upper_bound=True,
            )
            cuf_prod[id] = model.new_int_var(
                0, node.priority * total_slots * YSCALE, f"cuf_prod_{id}"
            )
            model.add_multiplication_equality(
                cuf_prod[id],
                [utilities[id].y, total_slots - interval_vars[id].end_expr()],
            )
            cuf[id] = model.new_int_var(
                0, node.priority * total_slots * YSCALE, f"cuf_{id}"
            )
            model.add(cuf[id] == cuf_int[id].y + cuf_prod[id])

        objective = sum(utility.y for utility in utilities.values())

        model.maximize(objective)

        return cls(
            utilities=utilities,
            cuf=cuf,
            cuf_int=cuf_int,
            cuf_prod=cuf_prod,
            before_ddls=before_ddls,
            after_ddls=after_ddls,
            clippeds=clippeds,
            **vars(basic_model),
        )


@dataclass
class CUFModel(TotalUtilityModel):
    """
    A model that maximizes CUF integral

    Integral is done in a Leibniz fashion
    """

    def to_interval_model(self) -> IntervalLenModel:
        return IntervalLenModel.from_cuf_model(self)

    @classmethod
    def from_total_utility_model(cls, tu_model: TotalUtilityModel) -> Self:
        tu_model.set_objective_constraint()

        tu_model.model.maximize(sum(tu_model.cuf.values()))

        return cls(**vars(tu_model))

    def set_objective_constraint(self):
        sol = self.solve()
        optimal = int(sol.objective_value)
        self.model.clear_objective()
        add_hints(self.model, sol)
        self.model.add(sum(self.cuf.values()) >= optimal)


@dataclass
class IntervalLenModel(CUFModel):
    """
    A model that reduces interval length when utilities of the tasks saturate
    """

    @classmethod
    def from_cuf_model(cls, cuf_model: CUFModel) -> Self:
        # Get the optimal goal from utility_model
        cuf_model.set_objective_constraint()
        model = cuf_model.model
        model.minimize(
            sum([interval.size_expr() for interval in cuf_model.intervals.values()])
        )

        return cls(**vars(cuf_model))
