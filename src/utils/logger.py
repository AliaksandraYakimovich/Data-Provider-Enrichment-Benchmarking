import logging
from pathlib import Path

from config.config import Config

# Neutralized log file name
LOG_FILE = Config.LOG_DIR / "pipeline_execution.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

DEFAULT_LOG_LEVEL = logging.INFO

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s - %(message)s"


def configure_logging(level: int = DEFAULT_LOG_LEVEL) -> None:
    root_logger = logging.getLogger()
    if root_logger.handlers:
        return

    root_logger.setLevel(level)

    formatter = logging.Formatter(LOG_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
