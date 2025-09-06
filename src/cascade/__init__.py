from cascade.compiler import TaskAST, ProcessedAST
from cascade.cmd import repl
from typing import Optional

from cascade.optimizer import Schedule


class AppState:
    src: Optional[TaskAST]
    processed: Optional[ProcessedAST]
    path: Optional[str]
    schedule: Optional[Schedule]

    def __init__(self):
        self.src = None
        self.path = None


def main() -> None:
    state = AppState()
    repl(state)
