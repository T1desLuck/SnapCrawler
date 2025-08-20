"""Настройка логирования: консоль и ротация файла `snapcrawler.log`.

Используется единый логгер модуля с именем `snapcrawler`. Формат включает время, уровень,
имя логгера и сообщение. Ротация файла — до ~2 МБ и 3 резервные копии.
"""
from __future__ import annotations
import logging
from logging.handlers import RotatingFileHandler
import sys
from pathlib import Path

_LOGGER_NAME = "snapcrawler"
_logger: logging.Logger | None = None


def setup_logging(log_dir: Path | None = None) -> None:
    global _logger
    if _logger is not None:
        return

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Попробуем принудительно включить UTF-8 в консоли (актуально для Windows)
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    # Консольный обработчик логов
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # Файловый обработчик с ротацией (если доступна запись на диск)
    try:
        log_path = Path("snapcrawler.log") if log_dir is None else Path(log_dir) / "snapcrawler.log"
        fh = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    except Exception:
        # Если файловая система недоступна для записи — просто пропускаем файловый логгер
        pass

    _logger = logger


def get_logger() -> logging.Logger:
    global _logger
    if _logger is None:
        setup_logging()
    assert _logger is not None
    return _logger
