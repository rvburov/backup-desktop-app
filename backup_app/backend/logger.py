"""Подробный журнал приложения: файл с ротацией. Без Qt.

В журнал пишется все: копирование, служебные сообщения и технические подробности ошибок.
Окно показывает не журнал, а короткую историю копирования (модуль history).
"""
import logging
import logging.handlers
import os

from .constants import LOG_FILE_NAME, LOGGER_NAME

FILE_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_FILE_HANDLER_MARK = "_backup_app_file_handler"


def get_logger() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if logger.level == logging.NOTSET:
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def setup_file_logging(log_directory: str, level: int = logging.INFO) -> str:
    """Подключает файл журнала с ротацией и возвращает путь к нему.

    Повторный вызов заменяет только файловый обработчик, остальные обработчики остаются.
    """
    logger = get_logger()
    logger.setLevel(level)
    logger.propagate = False
    for handler in list(logger.handlers):
        if getattr(handler, _FILE_HANDLER_MARK, False):
            logger.removeHandler(handler)
            handler.close()

    os.makedirs(log_directory, exist_ok=True)
    path = os.path.join(log_directory, LOG_FILE_NAME)
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter(FILE_FORMAT, DATE_FORMAT))
    setattr(handler, _FILE_HANDLER_MARK, True)
    logger.addHandler(handler)
    return path


def close_logging() -> None:
    """Закрывает все обработчики журнала и освобождает файл."""
    logger = get_logger()
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
