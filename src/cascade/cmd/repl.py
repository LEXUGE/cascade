import argparse
import traceback
import shlex
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import NestedCompleter, PathCompleter
from prompt_toolkit import HTML, PromptSession, print_formatted_text as pprint
from pprint import pp
from cascade.cmd.parser import build_schedule_parser
from cascade.compiler.processed_ast import ProcessedAST
from cascade.cmd.types import AppState


# TODO: Move to object oriented command dispatch when we grow enough complication.


def handle_cmd(raw_cmd: str, state: AppState):
    parts = shlex.split(raw_cmd.strip())
    if not parts:
        return None

    verb = parts[0].lower()
    args = parts[1:]

    match verb:
        case "import":
            match args:
                case []:
                    state.import_tasks(None)
                case [path]:
                    state.import_tasks(path)
                case _:
                    print("Usage: import [file path]")

        case "schedule":
            parser = argparse.ArgumentParser(exit_on_error=False)
            build_schedule_parser(parser)
            parsed = parser.parse_args(args)
            state.handle_schedule(
                parsed.start_str,
                parsed.end_str,
            )
            state.print_schedule(parsed.output)

        case "dev":
            if state.ast is None:
                raise RuntimeError("No tasks loaded. Please import tasks first.")
            match args:
                case ["normalize_deps"]:
                    pp(state.ast.normalize_dependencies())
                case ["propagate"]:
                    pp(state.ast.propogate_properties())
                case ["processed_ast"]:
                    pp(state.processed)
                case _:
                    pprint(
                        "Usage: dev [normalize_deps | propagate_ddl | processed_ast]"
                    )

        case _:
            raise RuntimeWarning(f"Unknown command: {verb}")


def repl() -> None:
    state = AppState()
    pprint(HTML("<b>Hello from cascade!</b>"))

    completer = NestedCompleter.from_nested_dict(
        {
            "import": PathCompleter(),
            "schedule": None,
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
