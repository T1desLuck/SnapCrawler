"""Загрузка и валидация конфигурации YAML.

Функции:
- `load_config(path)` — читает YAML, накладывает значения по умолчанию и проводит минимальную проверку,
  нормализует пути. Ключи и структура соответствуют файлу `config.yaml`.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any, Dict
import yaml

_DEFAULTS: Dict[str, Any] = {
    "project": {
        "name": "SnapCrawler",
        "storage_path": "./dataset",
        "max_folder_size_mb": 1024,
        "target_images": 100000,
        "statistics_enabled": True,
    },
    "image": {
        "min_side": 512,
        "accept_bw": False,
        "extensions": [".jpg", ".jpeg", ".png"],
        "orientation": "all",
        # Новые поля управления сохранением и фильтрами URL
        "save_format": "jpeg",        # "jpeg" | "original"
        "jpeg_quality": 95,            # Качество JPEG при save_format="jpeg"
        "skip_watermarked_urls": True, # Пропускать URL с признаками водяных знаков
        "watermark_keywords": [        # Ключевые слова в URL, указывающие на водянку/превью
            "watermark",
            "wm",
            "overlay",
            "preview",
            "thumb",
        ],
        "watermark_pixel_filter": {    # Простейший пиксельный детектор водяных знаков (по полосам)
            "enable": False,
            "band_ratio": 0.15,       # Доля высоты сверху/снизу для анализа полос
            "edge_threshold": 25,     # Порог градиента для детекции "текста"
            "edge_density": 0.08      # Доля сильных границ, при которой считаем как водяной знак
        },
    },
    "classifier": {
        "enable": True,
        "model_path": "./models/photo_filter.onnx",
        "batch_size": 16,
        "threshold": 0.5,
        "parallel": True,
        "enable_ssim": False,
    },
    "deduplication": {"enable": True, "hamming_threshold": 5},
    "download": {
        "threads": 4,
        "deep_parsing": False,
        "deep_max_depth": 2,  # Максимальная глубина обхода при deep_parsing
        "per_site_concurrency": 2,  # Параллельных запросов на один домен одновременно
        "enable_auto_discovery": False,
        "request_delay": 1.0,
        "max_requests_per_site": 100,
        "circuit_breaker_enabled": True,
        "user_agents": [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Safari/605.1.15",
        ],
        "proxies": [],
        "sources": [],
    },
    "packing": {"format": "zip", "auto_pack": True},
    "postfilter": {
        "enable": False,          # Включить пост-фильтр уже скачанных изображений
        "use_classifier": True,   # Пытаться использовать ONNX‑модель, если доступна
        "threshold": 0.6,         # Порог комбинированного скора (0..1)
        "dry_run": True,          # Сухой прогон: только лог, без удаления
        "scan_limit": 0,          # 0 = без ограничений; иначе ограничить число проверок
        "batch_size": 16,         # Батч для модели (если используется)
    },
}


def _deep_update(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    # Рекурсивное объединение словарей: значения из `updates` перекрывают значения `base`
    for k, v in updates.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = _deep_update(dict(base[k]), v)
        else:
            base[k] = v
    return base


def load_config(path: Path) -> Dict[str, Any]:
    # Чтение файла конфига и применение значений по умолчанию
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        user_cfg = yaml.safe_load(f) or {}
    cfg = _deep_update(dict(_DEFAULTS), user_cfg)

    # Normalize paths
    storage = Path(cfg["project"]["storage_path"]).expanduser()
    cfg["project"]["storage_path"] = str(storage)

    # Validate minimal fields
    fmt = cfg["packing"]["format"].lower()
    if fmt not in {"zip", "tar"}:
        raise ValueError("Некорректное значение packing.format — ожидается 'zip' или 'tar'")

    return cfg
