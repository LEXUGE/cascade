from datetime import datetime
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import NestedCompleter, PathCompleter
from pydantic import ValidationError
from yaml.error import YAMLError
from cascade.compiler import TaskAST
from prompt_toolkit import HTML, PromptSession, print_formatted_text as pprint
from pprint import pp
import yaml

from typing import TYPE_CHECKING

from cascade.optimizer import BasicModel
from cascade.compiler.processed_ast import ProcessedAST

if TYPE_CHECKING:
    from cascade import AppState

# TODO: Move to object oriented command dispatch when we grow enough complication.
# TODO: Render error messages as red, and maybe do styling centrally.


def import_tasks(file_path: str):
    """
    Imports tasks from a YAML file and validates them against the Tasks model. Doesn't alter state
    """
    try:
        with open(file_path, "r") as file:
            raw_data = yaml.safe_load(file)
            tasks = TaskAST.model_validate(raw_data)
            print(f"Successfully imported tasks from {file_path}")
            return tasks

    except FileNotFoundError:
        print(f"File not found: {file_path}")
    except ValidationError as e:
        print(f"Validation error while importing tasks: {e}")
    except YAMLError as e:
        print(f"Error parsing YAML file while importing tasks: {e}")
    except Exception as e:
        print(f"An error occurred while importing tasks: {e}")

    pprint(HTML(f"<ansired>Failed to import {file_path}</ansired>"))


def handle_cmd(raw_cmd: str, state: "AppState"):
    parts = raw_cmd.strip().split()
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
                            # FIXME: You shouldn't catch error in import_tasks
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
                print("No tasks loaded. Please import tasks first.")
                return
            match args:
                case ["normalize_deps"]:
                    pp(state.src.normalize_dependencies())
                case ["propagate"]:
                    pp(state.src.propogate_properties())
                case ["processed_ast"]:
                    state.processed = ProcessedAST.from_raw_ast(state.src)
                    pp(state.processed)
                case ["compile", start_str, end_str]:
                    start: datetime = datetime.strptime(start_str, "%Y-%m-%d")
                    end: datetime = datetime.strptime(end_str, "%Y-%m-%d")
                    ast = ProcessedAST.from_raw_ast(state.src)
                    sol = (
                        BasicModel.from_processed_ast(ast, start, end)
                        .to_utility_model()
                        .to_interval_len_model()
                        .solve()
                    )
                    sol.print_schedule()
                case _:
                    pprint(
                        "Usage: dev [normalize_deps | propagate_ddl | processed_ast | compile <start_date> <end_date>]"
                    )
                    pprint("Dates should be in format YYYY-MM-DD, e.g. 2023-10-01")

        case _:
            print(f"Unknown command: {verb}")


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
                "compile": None,
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

    pprint("Good bye!")
