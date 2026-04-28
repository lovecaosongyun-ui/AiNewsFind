from __future__ import annotations

import logging
from pathlib import Path


def setup_logger(log_dir: str | Path) -> tuple[logging.Logger, Path]:
    log_path = Path(log_dir) / "ai_news_agent.log"
    logger = logging.getLogger("ai_news_agent")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger, log_path
