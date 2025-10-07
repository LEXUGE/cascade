import traceback
from prompt_toolkit import HTML, print_formatted_text as pprint
from cascade.cmd.repl import repl
from cascade.cmd.parser import parser
from cascade.cmd.types import AppState


def cmd():
    try:
        args = parser.parse_args()
        match args.command:
            case "schedule":
                state = AppState()
                state.import_tasks(args.path)
                state.handle_schedule(args.start_str, args.end_str)
                state.print_schedule(args.output)
            case "repl":
                repl()
    except Exception as e:
        pprint(HTML(f"<ansired>{e}</ansired>\n{traceback.format_exc()}"))


__all__ = ["cmd"]
