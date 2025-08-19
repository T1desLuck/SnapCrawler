"""Сохранение изображений и контроль размера папки хранения.

Функции:
- `save_image_atomic` — атомарное перемещение временного файла в целевой путь.
- `auto_pack_if_needed` — сигнализирует о необходимости упаковки при превышении лимита.
- `insert_image_record` — запись метаданных изображения в SQLite.
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional
import shutil
import os

from .db import Database


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def save_image_atomic(tmp_path: Path, dest_path: Path) -> None:
    ensure_dir(dest_path.parent)
    # По возможности используем атомарную замену/перемещение
    shutil.move(str(tmp_path), str(dest_path))


def auto_pack_if_needed(storage_root: Path, max_folder_size_mb: int) -> Optional[Path]:
    if max_folder_size_mb <= 0:
        return None
    total_bytes = 0
    for root, _, files in os.walk(storage_root):
        for f in files:
            fp = Path(root) / f
            try:
                total_bytes += fp.stat().st_size
            except OSError:
                pass
    if total_bytes >= max_folder_size_mb * 1024 * 1024:
        # Передаём сигнал CLI-команде 'pack' (архивирование выполнит пользователь)
        return storage_root
    return None


def insert_image_record(db: Database, url: str, source: str, width: int, height: int, ext: str,
                        saved_path: Path, score: float | None, phash: str | None) -> None:
    # Вставка записи об изображении и его атрибутах
    c = db.conn.cursor()
    c.execute(
        """
        INSERT INTO images (url, source, width, height, ext, saved_path, score, phash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (url, source, width, height, ext, str(saved_path), score, phash),
    )
    db.conn.commit()
