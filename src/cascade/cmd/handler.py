import arrow
import pytimeparse
from datetime import timedelta
from cascade.cmd.types import OutputFormat
from cascade.optimizer import schedule
from cascade.compiler.ast import TaskAST
from cascade.optimizer.models import Schedule
import yaml


def import_tasks(file_path: str):
    """
    Imports tasks from a YAML file and validates them against the Tasks model. Doesn't alter state
    """
    with open(file_path, "r") as file:
        raw_data = yaml.safe_load(file)
        tasks = TaskAST.model_validate(raw_data)
        return tasks


def handle_schedule(
    start_str: str, end_str: str, src: TaskAST, format: OutputFormat
) -> Schedule:
    now = arrow.now(tz=src.config.default_tz)

    match start_str:
        case "next_day":
            start = now.shift(days=+1).floor("day").datetime
        case _:
            start_delta = pytimeparse.parse(start_str)
            if not start_delta:
                raise ValueError(f"Failed to parse duration: {start_str}")
            start = (now + timedelta(seconds=start_delta)).datetime

    end_delta = pytimeparse.parse(end_str)
    if not end_delta:
        raise ValueError(f"Failed to parse duration: {end_str}")

    end = start + timedelta(seconds=end_delta)
    sol = schedule(src, start, end)

    match format:
        case OutputFormat.Rendered:
            sol.print_schedule()
        case OutputFormat.Ics:
            print(f"<grey>{sol.to_ics()}</grey>")
        case OutputFormat.NoOutput:
            pass

    return sol
