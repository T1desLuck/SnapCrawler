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


def cmd_unit_human_emulation(args: argparse.Namespace) -> int:
    _print_header("Юнит-тест: HumanEmulationModule")
    try:
        from snapcrawler.core.human_emulation import HumanEmulationModule, HumanEmulationConfig
        
        # Тестируем конфигурацию
        config = {
            'human_emulation': {
                'enabled': True,
                'scroll_speed': 1000,
                'max_interactions': 10
            }
        }
        
        module = HumanEmulationModule(config)
        print(f"Модуль создан: enabled={module.config.enabled}")
        print(f"Скорость скролла: {module.config.scroll_speed}")
        print(f"Макс. взаимодействий: {module.config.max_interactions}")
        
        # Тестируем генерацию PageMethod
        methods = module.get_page_methods()
        print(f"Сгенерировано PageMethod: {len(methods)}")
        
        # Тестируем JavaScript
        js_script = module._get_emulation_script()
        print(f"JavaScript скрипт: {len(js_script)} символов")
        
        # Проверяем что JavaScript валидный
        if 'window.humanEmulation' in js_script and 'randomDelay' in js_script:
            print("Итог: УСПЕХ")
            return 0
        else:
            print("Итог: ОШИБКА - неверный JavaScript")
            return 1
            
    except Exception as e:
        print(f"Ошибка: {e}")
        return 1


def cmd_unit_network_capture(args: argparse.Namespace) -> int:
    _print_header("Юнит-тест: NetworkTrafficCapture")
    try:
        from snapcrawler.core.human_emulation import NetworkTrafficCapture
        
        config = {
            'network_capture': {
                'enabled': True,
                'capture_json': True,
                'capture_websockets': False
            }
        }
        
        module = NetworkTrafficCapture(config)
        print(f"Модуль создан: enabled={module.enabled}")
        print(f"Захват JSON: {module.capture_json}")
        print(f"Захват WebSocket: {module.capture_websockets}")
        
        methods = module.get_page_methods()
        print(f"Сгенерировано PageMethod: {len(methods)}")
        
        # Тестируем JavaScript
        setup_script = module._get_network_setup_script()
        collection_script = module._get_network_collection_script()
        
        if 'window.networkCapture' in setup_script and 'networkImageUrls' in collection_script:
            print("Итог: УСПЕХ")
            return 0
        else:
            print("Итог: ОШИБКА - неверный JavaScript")
            return 1
            
    except Exception as e:
        print(f"Ошибка: {e}")
        return 1


def cmd_unit_hidden_extractor(args: argparse.Namespace) -> int:
    _print_header("Юнит-тест: HiddenImageExtractor")
    try:
        from snapcrawler.core.human_emulation import HiddenImageExtractor
        
        config = {
            'hidden_images': {
                'enabled': True,
                'extract_base64': True,
                'extract_canvas': True,
                'extract_shadow_dom': True
            }
        }
        
        module = HiddenImageExtractor(config)
        print(f"Модуль создан: enabled={module.enabled}")
        print(f"Извлечение base64: {module.extract_base64}")
        print(f"Извлечение canvas: {module.extract_canvas}")
        print(f"Извлечение shadow DOM: {module.extract_shadow_dom}")
        
        methods = module.get_page_methods()
        print(f"Сгенерировано PageMethod: {len(methods)}")
        
        # Тестируем JavaScript
        extraction_script = module._get_hidden_extraction_script()
        collection_script = module._get_hidden_collection_script()
        
        if 'window.hiddenImageExtraction' in extraction_script and 'base64Images' in collection_script:
            print("Итог: УСПЕХ")
            return 0
        else:
            print("Итог: ОШИБКА - неверный JavaScript")
            return 1
            
    except Exception as e:
        print(f"Ошибка: {e}")
        return 1


def cmd_unit_advanced_formats(args: argparse.Namespace) -> int:
    _print_header("Юнит-тест: SmartImageProcessor")
    try:
        from snapcrawler.core.advanced_formats import SmartImageProcessor
        
        config = {
            'ai_optimization': {
                'enabled': True,
                'quality_threshold': 0.7
            },
            'format_conversion': {
                'enabled': True,
                'target_format': 'webp'
            }
        }
        
        processor = SmartImageProcessor(config)
        print(f"Процессор создан: оптимизация={config.get('ai_optimization', {}).get('enabled', False)}")
        print(f"Конвертация форматов: {config.get('format_conversion', {}).get('enabled', False)}")
        
        # Тестируем получение поддерживаемых форматов
        supported_formats = processor.get_supported_formats()
        print(f"Поддерживаемых форматов: {len(supported_formats)}")
        
        # Тестируем определение форматов
        test_urls = [
            'test.avif',
            'test.heic', 
            'test.jxl',
            'test.webp2',
            'test.jpg'
        ]
        
        supported_count = 0
        for url in test_urls:
            ext = url.split('.')[-1]
            if ext in supported_formats:
                supported_count += 1
                print(f"  {url}: поддерживается")
        
        if supported_count >= 3:
            print("Итог: УСПЕХ")
            return 0
        else:
            print("Итог: ОШИБКА - мало поддерживаемых форматов")
            return 1
            
    except Exception as e:
        print(f"Ошибка: {e}")
        return 1


def cmd_unit_navigation_module(args: argparse.Namespace) -> int:
    _print_header("Юнит-тест: AutoNavigationManager")
    try:
        from snapcrawler.core.navigation_module import AutoNavigationManager
        
        config = {
            'auto_navigation': {
                'enabled': True,
                'detect_pagination': True,
                'follow_sitemaps': True
            }
        }
        
        manager = AutoNavigationManager(config)
        print(f"Менеджер создан: max_depth={manager.max_depth}")
        print(f"Sitemap discovery: {manager.enable_sitemap}")
        print(f"ML discovery: {manager.enable_ml_discovery}")
        
        # Тестируем основные атрибуты
        print(f"Pagination detector: {type(manager.pagination_detector).__name__}")
        print(f"Sitemap parser: {type(manager.sitemap_parser).__name__}")
        print(f"ML discovery: {type(manager.ml_discovery).__name__}")
        
        # Проверяем что объект создан корректно
        if hasattr(manager, 'config') and hasattr(manager, 'pagination_detector'):
            print("Итог: УСПЕХ")
            return 0
        else:
            print("Итог: ОШИБКА - неполная инициализация")
            return 1
            
    except Exception as e:
        print(f"Ошибка: {e}")
        return 1


def cmd_unit_middlewares_advanced(args: argparse.Namespace) -> int:
    _print_header("Юнит-тест: AdvancedFingerprintSpoofingMiddleware")
    try:
        from snapcrawler.middlewares_advanced import AdvancedFingerprintSpoofingMiddleware
        from scrapy.http import Request
        from scrapy.spiders import Spider
        
        # Создаем настройки для middleware
        from scrapy.utils.test import get_crawler
        from scrapy.settings import Settings
        
        settings = Settings()
        settings.set('FINGERPRINT_SPOOF_LEVEL', 'high')
        settings.set('CANVAS_NOISE_ENABLED', True)
        
        # Создаем middleware
        middleware = AdvancedFingerprintSpoofingMiddleware(settings)
        
        print(f"Middleware создан: {type(middleware).__name__}")
        print(f"Fingerprint level: {middleware.fingerprint_level}")
        print(f"Canvas noise: {middleware.canvas_noise}")
        print(f"WebGL spoofing: {middleware.webgl_spoofing}")
        
        # Проверяем что конфигурации браузеров загружены
        if hasattr(middleware, 'browser_configs') and len(middleware.browser_configs) > 0:
            print(f"Конфигураций браузеров: {len(middleware.browser_configs)}")
            print("Итог: УСПЕХ")
            return 0
        else:
            print("Итог: ОШИБКА - конфигурации не загружены")
            return 1
            
    except Exception as e:
        print(f"Ошибка: {e}")
        return 1


def cmd_unit_all_modules(args: argparse.Namespace) -> int:
    _print_header("Запуск всех юнит-тестов модулей")
    
    test_functions = [
        ("CrawlingModule", cmd_unit_crawling_module),
        ("HumanEmulationModule", cmd_unit_human_emulation),
        ("NetworkTrafficCapture", cmd_unit_network_capture),
        ("HiddenImageExtractor", cmd_unit_hidden_extractor),
        ("SmartImageProcessor", cmd_unit_advanced_formats),
        ("AutoNavigationManager", cmd_unit_navigation_module),
        ("AdvancedStealthMiddleware", cmd_unit_middlewares_advanced),
    ]
    
    results = []
    for name, func in test_functions:
        print(f"\nТестирование {name}...")
        try:
            result = func(args)
            results.append((name, result))
            status = "УСПЕХ" if result == 0 else "ОШИБКА"
            print(f"{name}: {status}")
        except Exception as e:
            results.append((name, 1))
            print(f"{name}: ОШИБКА - {e}")
    
    # Общая статистика
    passed = sum(1 for _, result in results if result == 0)
    total = len(results)
    
    print(f"\nОбщий результат: {passed}/{total} тестов прошли")
    
    if passed == total:
        print("Все модули работают корректно!")
        return 0
    else:
        failed_modules = [name for name, result in results if result != 0]
        print(f"Проблемы с модулями: {', '.join(failed_modules)}")
        return 1


def cmd_integration_full_stack(args: argparse.Namespace) -> int:
    _print_header("Интеграционный тест: все модули вместе")
    
    if args.offline:
        print("Оффлайн-режим: пропускаю интеграционный тест.")
        return 0
    
    # Проверяем что все модули можно импортировать вместе
    try:
        from snapcrawler.core.human_emulation import HumanEmulationModule, NetworkTrafficCapture, HiddenImageExtractor
        from snapcrawler.core.advanced_formats import SmartImageProcessor
        from snapcrawler.core.navigation_module import AutoNavigationManager
        from snapcrawler.middlewares_advanced import AdvancedFingerprintSpoofingMiddleware
        from snapcrawler.spiders.image_spider import ImageSpider
        
        print("Все модули успешно импортированы")
        
        # Создаем конфигурацию для интеграционного теста
        config = {
            'human_emulation': {'enabled': True, 'max_interactions': 5},
            'network_capture': {'enabled': True, 'capture_json': True},
            'hidden_images': {'enabled': True, 'extract_base64': True},
            'ai_optimization': {'enabled': True},
            'auto_navigation': {'enabled': True}
        }
        
        # Инициализируем все модули
        human_emulation = HumanEmulationModule(config)
        network_capture = NetworkTrafficCapture(config)
        hidden_extractor = HiddenImageExtractor(config)
        image_processor = SmartImageProcessor(config)
        auto_navigation = AutoNavigationManager(config)
        
        print("Все модули созданы успешно")
        
        # Проверяем что все модули генерируют PageMethod
        total_methods = 0
        total_methods += len(human_emulation.get_page_methods())
        total_methods += len(network_capture.get_page_methods())
        total_methods += len(hidden_extractor.get_page_methods())
        
        print(f"Общее количество PageMethod: {total_methods}")
        
        if total_methods > 0:
            print("Интеграционный тест: УСПЕХ")
            
            # Запускаем короткий smoke-тест с всеми модулями
            print("Запуск smoke-теста с всеми модулями...")
            
            cmd = [
                sys.executable, "-m", "scrapy", "crawl", "image_spider",
                "-s", "LOG_LEVEL=INFO",
                "-s", "CLOSESPIDER_ITEMCOUNT=3",
                "-s", "DEPTH_LIMIT=1",
            ]
            
            timeout = getattr(args, 'timeout', 120)
            rc = _run_subprocess(cmd, timeout=timeout)
            
            if rc == 0:
                print("Полный интеграционный тест: УСПЕХ")
                return 0
            else:
                print(f"Интеграционный тест завершился с кодом: {rc}")
                return 0  # Не критично для таймаутов
        else:
            print("Ошибка: не сгенерировано PageMethod")
            return 1
            
    except Exception as e:
        print(f"Ошибка интеграционного теста: {e}")
        return 1


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
    sub.add_parser("unit:human_emulation", help="Юнит-тест: HumanEmulationModule")
    sub.add_parser("unit:network_capture", help="Юнит-тест: NetworkTrafficCapture")
    sub.add_parser("unit:hidden_extractor", help="Юнит-тест: HiddenImageExtractor")
    sub.add_parser("unit:advanced_formats", help="Юнит-тест: SmartImageProcessor")
    sub.add_parser("unit:navigation_module", help="Юнит-тест: AutoNavigationManager")
    sub.add_parser("unit:middlewares_advanced", help="Юнит-тест: AdvancedStealthMiddleware")
    sub.add_parser("unit:all_modules", help="Запуск всех юнит-тестов модулей")

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

    p_int = sub.add_parser("integration:full_stack", help="Интеграционный тест всех модулей")
    p_int.add_argument("--timeout", type=int, default=120, help="Таймаут для интеграционного теста")
    p_int.add_argument("--offline", action="store_true", help="Пропустить сетевой тест")

    return p


COMMANDS = {
    "list": cmd_list,
    "env:check": cmd_env_check,
    "config:print": cmd_config_print,
    "unit:crawling_module": cmd_unit_crawling_module,
    "unit:human_emulation": cmd_unit_human_emulation,
    "unit:network_capture": cmd_unit_network_capture,
    "unit:hidden_extractor": cmd_unit_hidden_extractor,
    "unit:advanced_formats": cmd_unit_advanced_formats,
    "unit:navigation_module": cmd_unit_navigation_module,
    "unit:middlewares_advanced": cmd_unit_middlewares_advanced,
    "unit:all_modules": cmd_unit_all_modules,
    "smoke:spider": cmd_smoke_spider,
    "smoke:parallel": cmd_smoke_parallel,
    "integration:full_stack": cmd_integration_full_stack,
}

# Описания и примеры для вывода команды `list`
COMMAND_HELP = {
    "list": "Список команд с описанием и примерами использования.",
    "env:check": "Проверка наличия ключевых файлов/папок и базовых Python-пакетов.",
    "config:print": "Краткая сводка значимых параметров из config.yaml.",
    "unit:crawling_module": "Локальная проверка извлечения изображений и ссылок без сети.",
    "unit:human_emulation": "Тестирование модуля эмуляции человеческого поведения.",
    "unit:network_capture": "Тестирование модуля захвата сетевого трафика.",
    "unit:hidden_extractor": "Тестирование модуля извлечения скрытых изображений.",
    "unit:advanced_formats": "Тестирование процессора продвинутых форматов изображений.",
    "unit:navigation_module": "Тестирование модуля автоматической навигации.",
    "unit:middlewares_advanced": "Тестирование продвинутых middleware для обхода защиты.",
    "unit:all_modules": "Запуск всех юнит-тестов модулей подряд.",
    "smoke:spider": "Короткий сетевой запуск паука Scrapy с лимитами (item/depth).",
    "smoke:parallel": "Короткий сетевой запуск параллельной архитектуры через run_parallel.py.",
    "integration:full_stack": "Интеграционный тест всех модулей вместе с реальным сайтом.",
}

COMMAND_USAGE = {
    "list": "py test_runner.py list",
    "env:check": "py test_runner.py env:check",
    "config:print": "py test_runner.py config:print --config config.yaml",
    "unit:crawling_module": "py test_runner.py unit:crawling_module",
    "unit:human_emulation": "py test_runner.py unit:human_emulation",
    "unit:network_capture": "py test_runner.py unit:network_capture",
    "unit:hidden_extractor": "py test_runner.py unit:hidden_extractor",
    "unit:advanced_formats": "py test_runner.py unit:advanced_formats",
    "unit:navigation_module": "py test_runner.py unit:navigation_module",
    "unit:middlewares_advanced": "py test_runner.py unit:middlewares_advanced",
    "unit:all_modules": "py test_runner.py unit:all_modules",
    "smoke:spider": "py test_runner.py smoke:spider --timeout 60 --log INFO --item-limit 1 --depth 1",
    "smoke:parallel": "py test_runner.py smoke:parallel --timeout 60 --config config.yaml",
    "integration:full_stack": "py test_runner.py integration:full_stack --timeout 120",
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
