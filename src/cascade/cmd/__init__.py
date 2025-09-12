from datetime import datetime, timedelta
import traceback
import shlex
import arrow
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import NestedCompleter, PathCompleter
import pytimeparse
from cascade.compiler import TaskAST
from prompt_toolkit import HTML, PromptSession, print_formatted_text as pprint
from pprint import pp
import yaml

from typing import TYPE_CHECKING

from cascade.optimizer import schedule
from cascade.compiler.processed_ast import ProcessedAST

if TYPE_CHECKING:
    from cascade import AppState

# TODO: Move to object oriented command dispatch when we grow enough complication.


def import_tasks(file_path: str):
    """
    Imports tasks from a YAML file and validates them against the Tasks model. Doesn't alter state
    """
    with open(file_path, "r") as file:
        raw_data = yaml.safe_load(file)
        tasks = TaskAST.model_validate(raw_data)
        print(f"Successfully imported tasks from {file_path}")
        return tasks


def handle_cmd(raw_cmd: str, state: "AppState"):
    parts = shlex.split(raw_cmd.strip())
    if not parts:
        return None

    verb = parts[0].lower()
    args = parts[1:]

    match verb:
        case "import":
            match args:
                case []:
                    if state.path is not None:
                        new = import_tasks(state.path)
                        if new == state.src:
                            print(f"No changes detected from {state.path}")
                        else:
                            state.src = new
                    else:
                        print("No previous path set. Doing nothing")
                case [path]:
                    state.src = import_tasks(path)
                    state.path = path
                case _:
                    print("Usage: import [file path]")

        case "print":
            print(repr(state.src))

        case "schedule":
            if state.src is None:
                raise RuntimeError("No tasks loaded. Please import tasks first.")
            now = arrow.now(tz=state.src.config.default_tz)
            match args:
                case ["export", "ics"]:
                    if state.schedule is None:
                        raise RuntimeError(
                            "No schedule compiled. Please compile first."
                        )
                    else:
                        pprint(HTML(f"<grey>{state.schedule.to_ics()}</grey>"))
                case ["next_day", end_str]:
                    start = now.shift(days=+1).floor("day").datetime
                    end_delta = pytimeparse.parse(end_str)
                    if not end_delta:
                        raise ValueError(f"Failed to parse duration: {end_str}")

                    end = start + timedelta(seconds=end_delta)
                    sol = schedule(state.src, start, end)
                    sol.print_schedule()
                    state.schedule = sol

                case [start_str, end_str]:
                    start_delta, end_delta = pytimeparse.parse(
                        start_str
                    ), pytimeparse.parse(end_str)
                    if not start_delta:
                        raise ValueError(f"Failed to parse duration: {start_str}")
                    if not end_delta:
                        raise ValueError(f"Failed to parse duration: {end_str}")

                    start = now + timedelta(seconds=start_delta)
                    end = start + timedelta(seconds=end_delta)
                    sol = schedule(state.src, start.datetime, end.datetime)
                    sol.print_schedule()
                    state.schedule = sol
                case _:
                    pprint(
                        "Usage: schedule <start_time relative to now> <end_time relative to start_time>"
                    )

        case "dev":
            if state.src is None:
                raise RuntimeError("No tasks loaded. Please import tasks first.")
            match args:
                case ["normalize_deps"]:
                    pp(state.src.normalize_dependencies())
                case ["propagate"]:
                    pp(state.src.propogate_properties())
                case ["processed_ast"]:
                    state.processed = ProcessedAST.from_raw_ast(state.src)
                    pp(state.processed)
                case _:
                    pprint(
                        "Usage: dev [normalize_deps | propagate_ddl | processed_ast]"
                    )

        case _:
            raise RuntimeWarning(f"Unknown command: {verb}")


def repl(state: "AppState") -> None:
    pprint(HTML("<b>Hello from cascade!</b>"))

    completer = NestedCompleter.from_nested_dict(
        {
            "import": PathCompleter(),
            "print": None,
            "schedule": {
                "export": {
                    "ics": None,
                },
            },
            "dev": {
                "normalize_deps": None,
                "propagate": None,
                "processed_ast": None,
            },
        }
    )

    session = PromptSession(completer=completer, auto_suggest=AutoSuggestFromHistory())
    while True:
        try:
            raw_cmd = session.prompt(HTML("<b>> </b>"))
            handle_cmd(raw_cmd, state)
        # Ctrl-C used to quickly cancel command
        except KeyboardInterrupt:
            continue
        # Ctrl-D used to exit
        except EOFError:
            break
        except Exception as e:
            pprint(HTML(f"<ansired>{e}</ansired>\n{traceback.format_exc()}"))

    pprint("Good bye!")
