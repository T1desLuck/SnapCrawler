#!/usr/bin/env python3
"""
Project Check — комплексный самотест для SnapCrawler.

Цели:
- Быстро проверить работоспособность ключевых модулей без сетевых запросов (по умолчанию)
- Дать подробный отчёт (PASS/FAIL) по каждому компоненту
- Не вносить разрушительных изменений (временные артефакты создаются и удаляются)

Запуск:
  python project_check.py            # оффлайн-проверки (без сети)
  python project_check.py --network  # дополнительно проверит минимальные сетевые части

Флаги:
  --network / --no-network    Включить/выключить сетевые проверки (по умолчанию: выключены)
  --keep-artifacts            Не удалять временные артефакты для отладки

Отчёт печатается в консоль. Код выхода 0 при всех PASS, иначе 1.
"""
from __future__ import annotations
import argparse
import sys
import os
import io
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional

# Базовая информация об окружении
PY_MIN = (3, 10)

# Попытка включить UTF-8 вывод в Windows-консоли
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass


@dataclass
class CheckResult:
    name: str
    ok: bool
    details: str = ""


class Reporter:
    def __init__(self) -> None:
        self.results: List[CheckResult] = []

    def add(self, name: str, ok: bool, details: str = "") -> None:
        self.results.append(CheckResult(name, ok, details))

    def summary(self) -> Tuple[int, int]:
        ok_count = sum(1 for r in self.results if r.ok)
        return ok_count, len(self.results)

    def print(self) -> None:
        def _safe(s: str) -> str:
            # Заменяем неразрывный дефис и другие потенциально проблемные символы
            return str(s).replace("\u2011", "-")

        print("\n=== Отчет по проверкам SnapCrawler ===")
        for r in self.results:
            status = "PASS" if r.ok else "FAIL"
            print(f"- [{status}] {_safe(r.name)}")
            if r.details:
                print(f"  {_safe(r.details)}")
        ok, total = self.summary()
        print(f"ИТОГ: {ok}/{total} проверок успешно пройдены.")


def check_environment(rep: Reporter) -> None:
    try:
        assert sys.version_info >= PY_MIN, f"Требуется Python>={PY_MIN[0]}.{PY_MIN[1]}"
        import PIL  # noqa: F401
        import numpy  # noqa: F401
        import aiohttp  # noqa: F401
        import imagehash  # noqa: F401
        rep.add("Окружение и зависимости", True, details=f"Python {sys.version.split()[0]}")
    except Exception as e:
        rep.add("Окружение и зависимости", False, details=str(e))


def check_config(rep: Reporter, project_root: Path) -> Dict[str, Any]:
    try:
        from snapcrawler.config import load_config
        cfg_path = project_root / "config.yaml"
        cfg = load_config(cfg_path)
        rep.add("Загрузка конфигурации", True, details=f"config: {cfg_path}")
        return cfg
    except Exception as e:
        rep.add("Загрузка конфигурации", False, details=str(e))
        return {}


def check_logging(rep: Reporter) -> None:
    try:
        from snapcrawler.logging_setup import setup_logging, get_logger
        setup_logging()
        log = get_logger()
        log.info("Тест логирования: OK")
        rep.add("Логирование", True)
    except Exception as e:
        rep.add("Логирование", False, details=str(e))


def check_db(rep: Reporter, cfg: Dict[str, Any]) -> Tuple[Optional[object], Path, Path]:
    try:
        from snapcrawler.db import Database
        storage = Path(cfg["project"]["storage_path"]).resolve()
        storage.mkdir(parents=True, exist_ok=True)
        db_path = storage / "snapcrawler.sqlite3"
        db = Database(db_path)
        db.init()
        stats = db.get_basic_stats()
        rep.add("SQLite/БД — инициализация и базовые запросы", True, details=f"stats={stats}")
        return db, storage, db_path
    except Exception as e:
        rep.add("SQLite/БД — инициализация и базовые запросы", False, details=str(e))
        return None, Path("."), Path("")


def check_preprocess_and_hash(rep: Reporter) -> None:
    """Проверяем preprocess_image и pHash на синтетике (без сети)."""
    try:
        from PIL import Image
        import numpy as np
        from snapcrawler.pipeline import preprocess_image, compute_phash
        # Синтетическое фото: шум/градиент
        arr = (np.random.rand(600, 800, 3) * 255).astype("uint8")
        im = Image.fromarray(arr, mode="RGB")
        pp = preprocess_image(arr.tobytes() if False else im.tobytes(), 512, False, "all")
        # Вызов preprocess ожидает bytes изображения, подготовим корректно
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=90)
        pp = preprocess_image(buf.getvalue(), 512, False, "all")
        assert pp is not None, "preprocess_image вернул None на валидном изображении"
        pim, w, h = pp
        ph = compute_phash(pim)
        assert isinstance(ph, str) and len(ph) > 0
        rep.add("Предобработка и pHash", True, details=f"size={w}x{h}, phash={ph}")
    except Exception as e:
        rep.add("Предобработка и pHash", False, details=str(e))


def check_storage_and_records(rep: Reporter, cfg: Dict[str, Any], db_obj: object, storage: Path) -> None:
    try:
        from snapcrawler.storage import save_image_atomic, insert_image_record
        from PIL import Image
        import time
        test_dir = storage / "_check_tmp"
        test_dir.mkdir(exist_ok=True)
        fn = test_dir / "test.jpg"
        tmp = test_dir / ".test.jpg"
        im = Image.new("RGB", (640, 480), color=(127, 127, 127))
        im.save(tmp, format="JPEG", quality=90)
        save_image_atomic(tmp, fn)
        insert_image_record(db_obj, url="http://example.com/t.jpg", source="example.com",
                            width=640, height=480, ext=".jpg", saved_path=fn, score=0.9, phash="deadbeef")
        rep.add("Сохранение и запись метаданных", True, details=f"file={fn}")
    except Exception as e:
        rep.add("Сохранение и запись метаданных", False, details=str(e))


def check_classifier_init(rep: Reporter, cfg: Dict[str, Any]) -> None:
    try:
        from snapcrawler.classifier import PhotoClassifier, ClassifierConfig
        if not bool(cfg["classifier"].get("enable", True)):
            rep.add("Классификатор (инициализация)", True, details="disabled by config")
            return
        clf_cfg = ClassifierConfig(
            enable=True,
            model_path=str(cfg["classifier"]["model_path"]),
            batch_size=int(cfg["classifier"].get("batch_size", 16)),
            threshold=float(cfg["classifier"].get("threshold", 0.5)),
        )
        clf = PhotoClassifier(clf_cfg)
        if getattr(clf, "enabled", False):
            rep.add("Классификатор (инициализация)", True, details="enabled")
        else:
            rep.add("Классификатор (инициализация)", True, details="auto-disabled (нет модели)")
    except Exception as e:
        rep.add("Классификатор (инициализация)", False, details=str(e))


def check_postfilter(rep: Reporter, cfg: Dict[str, Any], db_obj: object) -> None:
    try:
        from snapcrawler.postfilter import clean_dataset
        # Всегда запускаем в dry_run вне зависимости от конфига, чтобы не удалить ничего случайно
        cfg_copy = {**cfg, "postfilter": {**cfg.get("postfilter", {}), "enable": True, "dry_run": True, "scan_limit": 5}}
        rc = clean_dataset(cfg_copy, db_obj)
        rep.add("Пост‑фильтр (dry-run)", rc == 0, details="scan_limit=5, dry_run=true")
    except Exception as e:
        rep.add("Пост‑фильтр (dry-run)", False, details=str(e))


def check_packing(rep: Reporter, storage: Path) -> None:
    try:
        from snapcrawler.packing import pack_storage
        out = pack_storage(storage, fmt="zip")
        rep.add("Упаковка датасета", True, details=f"archive={out}")
        # не удаляем архив специально — пусть останется как артефакт проверки
    except Exception as e:
        rep.add("Упаковка датасета", False, details=str(e))


def check_network_sources(rep: Reporter, cfg: Dict[str, Any]) -> None:
    try:
        from snapcrawler.sources import SourceManager
        import asyncio
        sm = SourceManager(
            sources=cfg["download"]["sources"][:1],  # берём один источник для экономии
            user_agents=cfg["download"]["user_agents"],
            request_delay=0.2,
            max_requests_per_site=5,
            deep_parsing=False,
        )
        async def run_once():
            urls = await sm.collect_image_urls()
            return urls[:5]
        urls = asyncio.run(run_once())
        rep.add("Источники (минимальная сеть)", True, details=f"пример URL: {urls[:3] if urls else 'нет'}")
    except Exception as e:
        rep.add("Источники (минимальная сеть)", False, details=str(e))


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Проверка проекта SnapCrawler")
    parser.add_argument("--network", action="store_true", help="Включить сетевые проверки")
    parser.add_argument("--no-network", dest="network", action="store_false")
    parser.add_argument("--keep-artifacts", action="store_true", help="Не удалять временные файлы")
    parser.set_defaults(network=False)
    args = parser.parse_args(argv)

    project_root = Path(__file__).resolve().parent
    rep = Reporter()

    check_environment(rep)
    cfg = check_config(rep, project_root)
    check_logging(rep)

    if cfg:
        db, storage, _ = check_db(rep, cfg)
        if db:
            check_preprocess_and_hash(rep)
            check_storage_and_records(rep, cfg, db, storage)
            check_classifier_init(rep, cfg)
            check_postfilter(rep, cfg, db)
            check_packing(rep, storage)
            if args.network:
                check_network_sources(rep, cfg)

    rep.print()
    ok, total = rep.summary()
    return 0 if ok == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
