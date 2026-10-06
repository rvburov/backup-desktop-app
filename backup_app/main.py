"""Точка сборки приложения: создаёт бэкенд и интерфейс и связывает их."""
import sys
from typing import Dict, List, Optional

from .backend import MINIMIZED_FLAG, close_logging, create_service
from .frontend.app import QtFrontend

HIDDEN_FLAGS = (MINIMIZED_FLAG, "--hidden", "-m")


def parse_args(argv: List[str]) -> Dict[str, bool]:
    return {"minimized": any(arg in HIDDEN_FLAGS for arg in argv[1:])}


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    options = parse_args(argv)

    frontend = QtFrontend(argv)
    if not frontend.acquire_single_instance():
        # Приложение уже запущено: ему отправлен запрос показать окно.
        return 0

    service = create_service()
    try:
        return frontend.run(service, minimized=options["minimized"])
    finally:
        service.shutdown()
        close_logging()
        frontend.release()
