#!/usr/bin/env python3
"""
Точка входа CLI для SnapCrawler.
Команды:
  - start  : запустить сбор изображений (асинхронный пайплайн)
  - status : показать базовую статистику из SQLite
  - pack   : упаковать папку датасета в zip/tar согласно конфигу
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
import asyncio

from snapcrawler.config import load_config
from snapcrawler.logging_setup import setup_logging, get_logger
from snapcrawler.db import Database
from snapcrawler.packing import pack_storage
from snapcrawler import pipeline
from snapcrawler.postfilter import clean_dataset


def cmd_status(db: Database) -> int:
    stats = db.get_basic_stats()
    log = get_logger()
    log.info("Сохранённых изображений: %d", stats.get("images", 0))
    log.info("Уникальных хэшей: %d", stats.get("hashes", 0))
    # Топ доменов
    domains = db.get_stats_by_domain(limit=10)
    if domains:
        log.info("ТОП доменов (по количеству изображений):")
        for dom, cnt in domains:
            log.info("  %s — %d", dom or "(неизвестно)", cnt)
    # По датам (последние N)
    dates = db.get_stats_by_date(limit=7)
    if dates:
        log.info("По датам (последние дни):")
        for d, cnt in dates:
            log.info("  %s — %d", d, cnt)
    return 0


def cmd_pack(cfg: dict) -> int:
    storage_path = Path(cfg["project"]["storage_path"]).resolve()
    fmt = cfg["packing"]["format"].lower()
    out = pack_storage(storage_path, fmt)
    print(f"Архив создан: {out}")
    return 0


def cmd_start(cfg: dict, db: Database) -> int:
    # Run the async pipeline: URL collection -> download -> preprocess -> dedup -> storage
    asyncio.run(pipeline.run(cfg, db))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="snapcrawler", description="CLI-интерфейс SnapCrawler")
    parser.add_argument("command", choices=["start", "status", "pack", "clean", "check"], help="Команда для выполнения")
    parser.add_argument("--config", "-c", default="config.yaml", help="Путь к YAML-конфигу")
    args = parser.parse_args(argv)

    cfg = load_config(Path(args.config))
    setup_logging()

    # Храним БД в корне проекта, чтобы папка загрузок оставалась чисто с изображениями
    db_path = Path("snapcrawler.sqlite3").resolve()
    db = Database(db_path)
    db.init()

    if args.command == "status":
        return cmd_status(db)
    if args.command == "pack":
        return cmd_pack(cfg)
    if args.command == "start":
        return cmd_start(cfg, db)
    if args.command == "clean":
        return clean_dataset(cfg, db)
    if args.command == "check":
        # Запускаем встроенный проектный self-check
        try:
            import project_check  # локальный файл в корне проекта
            return int(project_check.main([]))
        except Exception as e:
            get_logger().error("Не удалось запустить project_check: %s", e)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
