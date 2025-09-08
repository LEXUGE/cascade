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

from cascade.optimizer import BasicModel, Schedule
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


def compile(src: TaskAST, start: datetime, end: datetime) -> Schedule:
    ast = ProcessedAST.from_raw_ast(src)
    sol = (
        BasicModel.from_processed_ast(ast, start, end)
        .to_total_utility_model()
        .to_cuf_model()
        .to_interval_model()
        .to_schedule()
    )
    sol.print_schedule()
    return sol


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
                case ["compile", "next", duration]:
                    parsed = pytimeparse.parse(duration)
                    if not parsed:
                        raise ValueError(f"Failed to parse duration: {duration}")
                    duration = timedelta(seconds=int(parsed))
                    start = datetime.combine(
                        arrow.now().shift(days=+1).date(), datetime.min.time()
                    )
                    end = start + duration
                    state.schedule = compile(state.src, start, end)
                case ["compile", start_str, end_str]:
                    start: datetime = arrow.get(start_str).datetime
                    end: datetime = arrow.get(end_str).datetime
                    state.schedule = compile(state.src, start, end)
                case ["export", "ics"]:
                    if state.schedule is None:
                        raise RuntimeError(
                            "No schedule compiled. Please compile first."
                        )
                    else:
                        pprint(HTML(f"<grey>{state.schedule.to_ics()}</grey>"))
                case _:
                    pprint(
                        "Usage: dev [normalize_deps | propagate_ddl | processed_ast | compile <start_date> <end_date> | compile next <duration>]"
                    )

        case _:
            raise RuntimeWarning(f"Unknown command: {verb}")


def repl(state: "AppState") -> None:
    pprint(HTML("<b>Hello from cascade!</b>"))

    completer = NestedCompleter.from_nested_dict(
        {
            "import": PathCompleter(),
            "print": None,
            "dev": {
                "normalize_deps": None,
                "propagate": None,
                "processed_ast": None,
                "compile": {
                    "next": None,
                },
                "export": {
                    "ics": None,
                },
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
