import traceback
from prompt_toolkit import HTML, print_formatted_text as pprint
from cascade.cmd.repl import repl
from cascade.cmd.handler import handle_schedule, import_tasks
from cascade.cmd.parser import parser


def cmd():
    try:
        args = parser.parse_args()
        match args.command:
            case "schedule":
                src = import_tasks(args.path)
                handle_schedule(
                    args.start_str,
                    args.end_str,
                    src,
                    args.output,
                )
            case "repl":
                repl()
    except Exception as e:
        pprint(HTML(f"<ansired>{e}</ansired>\n{traceback.format_exc()}"))


__all__ = ["cmd"]
