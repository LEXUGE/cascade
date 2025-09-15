import argparse
from cascade.cmd.types import OutputFormat


parser = argparse.ArgumentParser(
    description="Cascade turns your TODO list into a well-scheduled calendar"
)


subparsers = parser.add_subparsers(
    dest="command", required=True, help="Available commands"
)

parser_repl = subparsers.add_parser(
    "repl", help="Starts an interactive Cascade session."
)


def build_schedule_parser(parser, require_path: bool = False):
    parser.add_argument(
        "start_str",
        type=str,
        help="The start time for the schedule relative to now (e.g. `1hr 30 mins`).",
    )
    parser.add_argument(
        "end_str",
        type=str,
        help="The end time for the schedule relative to the start time (e.g., `1day`).",
    )

    parser.add_argument(
        "--output",
        type=OutputFormat,
        default=OutputFormat.Rendered,
        choices=list(OutputFormat),
        help="What format to use on output",
    )

    if require_path:
        parser.add_argument(
            "--path", type=str, required=True, help="Path to the cascade task file."
        )


parser_schedule = subparsers.add_parser(
    "schedule", help="Schedules tasks between a start and end time."
)

build_schedule_parser(parser_schedule, require_path=True)
