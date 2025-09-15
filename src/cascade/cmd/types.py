from enum import Enum
from cascade.compiler import TaskAST, ProcessedAST
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


class OutputFormat(str, Enum):
    Ics = "ics"
    Rendered = "rendered"
    NoOutput = "no"
