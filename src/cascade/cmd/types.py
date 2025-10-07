from __future__ import annotations
from enum import Enum
from cascade.compiler import TaskAST, ProcessedAST
from cascade.optimizer import schedule
from typing import Dict, Optional
import yaml
from datetime import datetime, timedelta
import arrow
import pytimeparse

from cascade.optimizer import Schedule


def _import_tasks(file_path: str) -> tuple[str, TaskAST]:
    """
    Imports tasks from a YAML file and validates them against the Tasks model. Doesn't alter state
    """
    with open(file_path, "r") as file:
        text = file.read()
        raw_data = yaml.safe_load(text)
        tasks = TaskAST.model_validate(raw_data)
        return (text, tasks)


class AppState:
    path: Optional[str] = None
    src: Optional[str] = None
    ast: Optional[TaskAST] = None
    processed: Optional[ProcessedAST] = None
    schedule: Optional[Schedule] = None
    cache: Dict[tuple[str, datetime, datetime], Schedule] = {}

    def import_tasks(self, path: Optional[str]):
        # merge two paths, with the provided path taking precedence
        self.path = path or self.path

        if not self.path:
            raise RuntimeError("No path set, doing nothing")

        new_src, new_ast = _import_tasks(self.path)
        new_processed = ProcessedAST.from_raw_ast(new_ast)
        if new_processed == self.processed:
            print(f"No changes detected from {self.path}")
        else:
            self.src, self.ast, self.processed = new_src, new_ast, new_processed
            # clean up schedule
            self.schedule = None
            print(f"Successfully imported tasks from {self.path}")

    def handle_schedule(self, start_str: str, end_str: str):
        if not self.src or not self.processed:
            raise RuntimeError("Missing tasks to schedule")

        now = arrow.now(tz=self.processed.config.default_tz)

        match start_str:
            case "next_day":
                start = now.shift(days=+1).floor("day").datetime
            case "next_hour":
                start = now.shift(hours=+1).floor("hour").datetime
            case _:
                start_delta = pytimeparse.parse(start_str)
                if not start_delta:
                    raise ValueError(f"Failed to parse duration: {start_str}")
                start = (now + timedelta(seconds=start_delta)).datetime

        end_delta = pytimeparse.parse(end_str)
        if not end_delta:
            raise ValueError(f"Failed to parse duration: {end_str}")

        end = start + timedelta(seconds=end_delta)

        # explicit checking necessary for lazy evaluation.
        if (self.src, start, end) in self.cache:
            self.schedule = self.cache[(self.src, start, end)]
        else:
            self.schedule = self.cache[(self.src, start, end)] = schedule(
                self.processed, start, end
            )

    def print_schedule(self, format: OutputFormat):
        if not self.schedule:
            raise RuntimeError("No schedule to print")
        match format:
            case OutputFormat.Rendered:
                self.schedule.print_schedule()
            case OutputFormat.Ics:
                print(f"{self.schedule.to_ics()}")
            case OutputFormat.NoOutput:
                pass


class OutputFormat(str, Enum):
    Ics = "ics"
    Rendered = "rendered"
    NoOutput = "no"
