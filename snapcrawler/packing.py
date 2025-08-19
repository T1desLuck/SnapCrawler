"""Упаковка папки с датасетом в архив (zip или tar) без сжатия.

Файл называется `dataset-YYYYMMDD-HHMMSS.<fmt>` и создаётся рядом с папкой хранения.
Используем хранение без сжатия для скорости и минимальной нагрузки на CPU.
"""
from __future__ import annotations
from pathlib import Path
import time
import zipfile
import tarfile


def pack_storage(storage_dir: Path, fmt: str = "zip") -> Path:
    storage_dir = Path(storage_dir)
    storage_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    out_name = f"dataset-{ts}.{fmt}"
    out_path = storage_dir.parent / out_name

    if fmt == "zip":
        # ZIP без сжатия (ZIP_STORED)
        with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_STORED) as zf:
            for p in storage_dir.rglob("*"):
                if p.is_file():
                    zf.write(p, arcname=p.relative_to(storage_dir))
    elif fmt == "tar":
        # TAR без сжатия
        with tarfile.open(out_path, "w") as tf:
            tf.add(storage_dir, arcname=".")
    else:
        raise ValueError("Неподдерживаемый формат упаковки. Используйте 'zip' или 'tar'.")

    return out_path
