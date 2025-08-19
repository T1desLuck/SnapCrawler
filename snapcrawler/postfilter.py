"""Лёгкий пост-фильтр для уже скачанных изображений.

Цель: с минимальной нагрузкой на CPU/GPU просканировать датасет и удалить
нереалистичные изображения (арт/абстракция/ИИ), используя:
- при наличии — лёгкий ONNX-классификатор `PhotoClassifier` (photo vs non-photo)
- всегда — консервативную эвристику (градиенты/насыщенность), чтобы
  не удалить реальные фото по ошибке

Управление через конфиг `postfilter.*`.
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

import numpy as np
from PIL import Image, ImageFilter

from .logging_setup import get_logger
from .classifier import PhotoClassifier, ClassifierConfig


def _heuristic_photo_score(im: Image.Image) -> float:
    """Консервативная эвристика "настоящего фото" в [0..1].

    Признаки:
    - средняя дисперсия по каналам HSV (рисунки часто имеют плоские заливки)
    - плотность границ (реальные фото содержат больше мелких деталей)

    Нагрузка мала: resize→градиент Sobel→вариация, все на CPU.
    """
    try:
        im_small = im.convert("RGB")
        im_small.thumbnail((224, 224), Image.BILINEAR)
        arr = np.asarray(im_small, dtype=np.float32) / 255.0  # (H,W,3)

        # Градиенты (через фильтры, приближённо)
        gx = im_small.filter(ImageFilter.FIND_EDGES)
        gx_arr = np.asarray(gx, dtype=np.float32) / 255.0
        edge_mean = float(gx_arr.mean())  # [0..1]

        # Вариативность цвета
        var_rgb = float(arr.var())  # [0..~0.1]

        # Нормализация показателей в [0..1]
        v_edge = max(0.0, min(1.0, edge_mean))
        v_var = max(0.0, min(1.0, var_rgb * 10.0))  # масштабируем дисперсию

        # Комбинация (консервативно): если оба высокие — ближе к фото
        score = 0.6 * v_edge + 0.4 * v_var
        return float(max(0.0, min(1.0, score)))
    except Exception:
        return 0.5  # нейтрально


def _load_classifier(cfg: Dict[str, Any]) -> Optional[PhotoClassifier]:
    if not bool(cfg["postfilter"].get("use_classifier", True)):
        return None
    try:
        clf_cfg = ClassifierConfig(
            enable=True,
            model_path=str(cfg["classifier"]["model_path"]),
            batch_size=int(cfg["postfilter"].get("batch_size", cfg["classifier"].get("batch_size", 16))),
            threshold=float(cfg["classifier"].get("threshold", 0.5)),
        )
        clf = PhotoClassifier(clf_cfg)
        return clf
    except Exception:
        return None


def _combined_score(im: Image.Image, clf: Optional[PhotoClassifier]) -> float:
    h = _heuristic_photo_score(im)
    if clf is None or not getattr(clf, "enabled", False):
        return h
    s = clf.is_photo(im) or 0.5
    # Комбинация: больше вес модели, но эвристика сглаживает ошибки
    return 0.7 * float(s) + 0.3 * float(h)


def clean_dataset(cfg: Dict[str, Any], db) -> int:
    """Сканирует сохранённые изображения и удаляет не-фото (ИИ/арт), если включено.

    Поведение:
    - уважает `postfilter.enable`
    - если `dry_run: true`, только логирует, не удаляя
    - порог `postfilter.threshold` применяется к комбинированному скору
    - удаление: файл + запись из `images`; orphan-хэш очищаем по возможности
    """
    log = get_logger()
    if not bool(cfg.get("postfilter", {}).get("enable", False)):
        log.info("Пост-фильтр отключён (postfilter.enable = false)")
        return 0

    storage = Path(cfg["project"]["storage_path"]).resolve()
    threshold = float(cfg["postfilter"].get("threshold", 0.6))
    dry_run = bool(cfg["postfilter"].get("dry_run", True))
    scan_limit = int(cfg["postfilter"].get("scan_limit", 0) or 0)

    clf = _load_classifier(cfg)
    if clf is None:
        log.info("Классификатор не используется — работаем по консервативной эвристике")
    else:
        log.info("Классификатор активен: порог %.2f", float(cfg["classifier"].get("threshold", 0.5)))

    count_total = 0
    count_removed = 0

    for rec in db.iter_images(limit=scan_limit):
        img_id, path, phash = rec[0], rec[1], rec[2] if len(rec) > 2 else None
        p = Path(path)
        if not p.is_file():
            continue
        try:
            with Image.open(p) as im:
                im = im.convert("RGB")
                score = _combined_score(im, clf)
        except Exception as e:
            log.debug("Не удалось открыть %s: %s", p, e)
            score = 0.0  # считать подозрительным

        count_total += 1
        if score < threshold:
            action = "[DRY-RUN] Удалил бы" if dry_run else "Удаляю"
            log.info("%s как не-фото (score=%.2f<th=%.2f): %s", action, score, threshold, p)
            if not dry_run:
                try:
                    p.unlink(missing_ok=True)
                except Exception as e:
                    log.debug("Не удалось удалить файл %s: %s", p, e)
                # Удаляем запись из БД
                try:
                    db.delete_image_by_id(img_id)
                except Exception as e:
                    log.debug("Не удалось удалить запись images[%s]: %s", img_id, e)
                # Попробуем подчистить orphan-хэш
                if phash:
                    try:
                        db.delete_orphan_hash(phash)
                    except Exception:
                        pass
                count_removed += 1

    log.info("Пост-фильтр завершён: проверено %d, удалено %d (порог %.2f, dry_run=%s)",
             count_total, count_removed, threshold, dry_run)
    return 0
