#!/usr/bin/env python3
"""
Единый тестовый раннер для SnapCrawler (неинвазивный):
- Не модифицирует файлы проекта
- Использует только стандартную библиотеку
- Даёт быстрые smoke-тесты и утилиты из одной точки входа

Примеры (Windows PowerShell):
  # Список доступных команд
  py test_runner.py list

  # Проверка окружения (структура, Python, модули)
  py test_runner.py env:check

  # Краткая сводка по config.yaml
  py test_runner.py config:print --config config.yaml

  # Псевдоюнит-проверка extract_images/links на примере HTML
  py test_runner.py unit:crawling_module

  # Smoke-запуск Scrapy (лимит 1 элемент, минимальная глубина, нужна сеть)
  py test_runner.py smoke:spider --timeout 60 --log INFO --item-limit 1 --depth 1

  # Smoke-запуск параллельной архитектуры через run_parallel.py (с таймаутом)
  py test_runner.py smoke:parallel --timeout 60 --config config.yaml

Заметки:
- Сетевые тесты могут падать за фаерволом; используйте --offline для пропуска.
- По умолчанию тесты безопасны: низкие лимиты и короткие таймауты.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
import subprocess
import textwrap
from pathlib import Path

# Прагматичная попытка печатать в UTF-8 на Windows-консолях, чтобы избежать кракозябр
with contextlib.suppress(Exception):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Корень проекта (этот файл в корне)
ROOT = Path(__file__).resolve().parent


# -----------------------------
# Вспомогательные функции
# -----------------------------

def _print_header(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def _check_exists(path: Path, kind: str = "file") -> tuple[bool, str]:
    if kind == "file":
        ok = path.is_file()
    elif kind == "dir":
        ok = path.is_dir()
    else:
        ok = path.exists()
    label = "ФАЙЛ" if kind == "file" else ("ПАПКА" if kind == "dir" else kind.upper())
    return ok, f"{label}: {path} -> {'OK' if ok else 'ОТСУТСТВУЕТ'}"


# -----------------------------
# Команды
# -----------------------------

def cmd_list(args: argparse.Namespace) -> int:
    print("Доступные команды:")
    for name, _ in COMMANDS.items():
        desc = COMMAND_HELP.get(name, "")
        usage = COMMAND_USAGE.get(name, "")
        print(f"\n- {name}")
        if desc:
            print(f"  Описание: {desc}")
        if usage:
            print(f"  Пример:  {usage}")
    print("\nПодробную помощь по опциям: py test_runner.py <команда> -h")
    return 0


def cmd_env_check(args: argparse.Namespace) -> int:
    _print_header("Проверка окружения и структуры")

    # Базовая структура
    expectations = [
        (ROOT / "scrapy.cfg", "file"),
        (ROOT / "requirements.txt", "file"),
        (ROOT / "config.yaml", "file"),
        (ROOT / "run_parallel.py", "file"),
        (ROOT / "snapcrawler", "dir"),
        (ROOT / "snapcrawler" / "spiders" / "image_spider.py", "file"),
        (ROOT / "snapcrawler" / "core", "dir"),
        (ROOT / "downloads", "dir"),
        (ROOT / "downloads" / "raw", "dir"),
        (ROOT / "downloads" / "processed", "dir"),
    ]
    ok_all = True
    for path, kind in expectations:
        ok, msg = _check_exists(path, kind)
        ok_all = ok_all and ok
        print(msg)

    # Версия Python
    print(f"Python: {sys.version.split()[0]} (exe: {sys.executable})")

    # Проверка импортов (без установки зависимостей)
    missing = []
    with contextlib.suppress(Exception):
        import yaml  # type: ignore
    try:
        import yaml  # noqa: F401
    except Exception:
        missing.append("pyyaml (yaml)")

    try:
        import scrapy  # noqa: F401
    except Exception:
        missing.append("scrapy")

    # Необязательно
    try:
        import playwright  # noqa: F401
    except Exception:
        pass

    if missing:
        print("Отсутствуют пакеты Python:")
        for m in missing:
            print("  -", m)
        print("Установите командой: pip install -r requirements.txt")

    return 0 if ok_all else 1


def cmd_config_print(args: argparse.Namespace) -> int:
    _print_header("Сводка config.yaml")
    cfg_path = ROOT / args.config
    if not cfg_path.exists():
        print(f"Конфиг не найден: {cfg_path}")
        return 1
    try:
        import yaml
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    except Exception as e:
        print("Не удалось прочитать конфиг:", e)
        return 1

    # Краткая сводка
    crawling = data.get("crawling", {})
    limits = data.get("limits", {})
    general = data.get("general", {})

    summary = {
        "start_urls": crawling.get("start_urls", [])[:3],
        "js_enabled": crawling.get("js_enabled"),
        "max_depth": crawling.get("max_depth"),
        "request_delay": crawling.get("request_delay"),
        "output_dir": general.get("output_dir"),
        "max_images": limits.get("max_images"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def cmd_unit_crawling_module(args: argparse.Namespace) -> int:
    _print_header("Псевдоюнит: CrawlingModule extract_images/links на примере HTML")
    # Минимальный встроенный HTML
    sample_html = textwrap.dedent(
        """
        <html>
          <head>
            <style>
              .banner { background-image: url('/img/banner.jpg'); }
            </style>
          </head>
          <body>
            <img src="/img/a.png" />
            <a href="/next">Next</a>
          </body>
        </html>
        """
    )

    # Базовый URL для абсолютных путей
    base = "https://example.com/page"

    # Создаём soup и вызываем методы без сети
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(sample_html, "html.parser")

    # Минимальная конфигурация
    config = {
        "crawling": {
            "start_urls": ["https://example.com"],
            "max_depth": 1,
        },
        "limits": {},
    }

    from snapcrawler.core.crawling_module import CrawlingModule
    import multiprocessing as mp

    img_q = mp.Queue()
    stats_q = mp.Queue()
    cm = CrawlingModule(config=config, image_queue=img_q, stats_queue=stats_q,
                        visited_urls={}, page_hashes=set(), urls_by_depth={})

    imgs = cm.extract_images(soup, base)
    links = cm.extract_links(soup, base)

    print("Изображения:", imgs)
    print("Ссылки:", links)
    # Простейшие проверки
    ok = any(u.endswith("a.png") for u in imgs) and any(l.endswith("/next") for l in links)
    print("Итог:", "УСПЕХ" if ok else "ОШИБКА")
    return 0 if ok else 1


def _run_subprocess(cmd: list[str], timeout: int) -> int:
    print("Запуск:", " ".join(cmd))
    try:
        proc = subprocess.Popen(cmd, cwd=str(ROOT))
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            print(f"Превышен таймаут ({timeout}с). Завершаю...")
            with contextlib.suppress(Exception):
                proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(Exception):
                    proc.kill()
        return proc.returncode or 0
    except FileNotFoundError as e:
        print("Команда не найдена:", e)
        return 1


def cmd_smoke_spider(args: argparse.Namespace) -> int:
    _print_header("Smoke-запуск Scrapy (с ограничениями)")
    if args.offline:
        print("Оффлайн-режим: пропускаю сетевой smoke-тест паука.")
        return 0

    # Windows-дружественный запуск через модуль
    cmd = [
        sys.executable, "-m", "scrapy", "crawl", "image_spider",
        "-s", f"LOG_LEVEL={args.log}",
        "-s", f"CLOSESPIDER_ITEMCOUNT={args.item_limit}",
        "-s", f"DEPTH_LIMIT={args.depth}",
    ]
    rc = _run_subprocess(cmd, timeout=args.timeout)
    print("Код выхода:", rc)
    return 0 if rc == 0 else rc


def cmd_smoke_parallel(args: argparse.Namespace) -> int:
    _print_header("Smoke-запуск параллельной архитектуры (с таймером)")
    if args.offline:
        print("Оффлайн-режим: пропускаю сетевой smoke-тест параллельного режима.")
        return 0
    cmd = [sys.executable, str(ROOT / "run_parallel.py"), args.config]
    rc = _run_subprocess(cmd, timeout=args.timeout)
    print("Код выхода:", rc)
    return 0 if rc == 0 else rc


# -----------------------------
# CLI
# -----------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Единый тестовый раннер SnapCrawler")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="Список команд с кратким описанием и примерами")

    sub.add_parser("env:check", help="Проверка структуры проекта и базовых зависимостей")

    p_cfg = sub.add_parser("config:print", help="Печать краткой сводки config.yaml")
    p_cfg.add_argument("--config", default="config.yaml", help="Путь к config.yaml")

    sub.add_parser("unit:crawling_module", help="Псевдоюнит: проверка extract_images/links на HTML-примере")

    p_sp = sub.add_parser("smoke:spider", help="Короткий запуск Scrapy с лимитами и таймаутом")
    p_sp.add_argument("--timeout", type=int, default=60)
    p_sp.add_argument("--log", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Уровень логов Scrapy")
    p_sp.add_argument("--item-limit", type=int, default=1, help="Ограничение по числу элементов (CLOSESPIDER_ITEMCOUNT)")
    p_sp.add_argument("--depth", type=int, default=1, help="Ограничение глубины (DEPTH_LIMIT)")
    p_sp.add_argument("--offline", action="store_true", help="Пропустить сетевой тест")

    p_par = sub.add_parser("smoke:parallel", help="Короткий запуск параллельной архитектуры (run_parallel.py)")
    p_par.add_argument("--timeout", type=int, default=60)
    p_par.add_argument("--config", default="config.yaml", help="Путь к конфигу для run_parallel.py")
    p_par.add_argument("--offline", action="store_true", help="Пропустить сетевой тест")

    return p


COMMANDS = {
    "list": cmd_list,
    "env:check": cmd_env_check,
    "config:print": cmd_config_print,
    "unit:crawling_module": cmd_unit_crawling_module,
    "smoke:spider": cmd_smoke_spider,
    "smoke:parallel": cmd_smoke_parallel,
}

# Описания и примеры для вывода команды `list`
COMMAND_HELP = {
    "list": "Список команд с описанием и примерами использования.",
    "env:check": "Проверка наличия ключевых файлов/папок и базовых Python-пакетов.",
    "config:print": "Краткая сводка значимых параметров из config.yaml.",
    "unit:crawling_module": "Локальная проверка извлечения изображений и ссылок без сети.",
    "smoke:spider": "Короткий сетевой запуск паука Scrapy с лимитами (item/depth).",
    "smoke:parallel": "Короткий сетевой запуск параллельной архитектуры через run_parallel.py.",
}

COMMAND_USAGE = {
    "list": "py test_runner.py list",
    "env:check": "py test_runner.py env:check",
    "config:print": "py test_runner.py config:print --config config.yaml",
    "unit:crawling_module": "py test_runner.py unit:crawling_module",
    "smoke:spider": "py test_runner.py smoke:spider --timeout 60 --log INFO --item-limit 1 --depth 1",
    "smoke:parallel": "py test_runner.py smoke:parallel --timeout 60 --config config.yaml",
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = COMMANDS.get(args.command)
    if not func:
        print("Неизвестная команда:", args.command)
        return 1
    return func(args)


if __name__ == "__main__":
    raise SystemExit(main())
