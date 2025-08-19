"""Работа с SQLite: создание схемы, базовая статистика и операции с pHash.

Класс `Database` инкапсулирует подключение к SQLite, создаёт таблицы `images` и `hashes`,
предоставляет методы для вставки/проверки хэшей и получения простой статистики.
"""
from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import Dict


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.path, check_same_thread=False)
            # WAL режим ускоряет параллельный доступ и уменьшает блокировки
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
        return self._conn

    def init(self) -> None:
        c = self.conn.cursor()
        # Таблица с метаданными изображений
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT,
                source TEXT,
                width INTEGER,
                height INTEGER,
                ext TEXT,
                saved_path TEXT,
                score REAL,
                phash TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        # Таблица с уникальными перцептуальными хэшами (для дедупликации)
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS hashes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phash TEXT UNIQUE
            );
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_hashes_phash ON hashes(phash);")
        self.conn.commit()

    def get_basic_stats(self) -> Dict[str, int]:
        c = self.conn.cursor()
        c.execute("SELECT COUNT(*) FROM images;")
        images = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM hashes;")
        hashes = c.fetchone()[0]
        return {"images": images, "hashes": hashes}

    # --- Поддержка пост-фильтра ---
    def iter_images(self, limit: int = 0):
        """Итератор по изображениям: (id, saved_path, phash). Если limit>0 — ограничить."""
        c = self.conn.cursor()
        if limit and limit > 0:
            c.execute("SELECT id, saved_path, phash FROM images ORDER BY id DESC LIMIT ?;", (int(limit),))
        else:
            c.execute("SELECT id, saved_path, phash FROM images ORDER BY id DESC;")
        for row in c.fetchall():
            yield row

    def delete_image_by_id(self, image_id: int) -> None:
        c = self.conn.cursor()
        c.execute("DELETE FROM images WHERE id = ?;", (int(image_id),))
        self.conn.commit()

    def delete_orphan_hash(self, phash: str) -> None:
        """Удаляет хэш из таблицы hashes, если его больше не ссылаются в images."""
        c = self.conn.cursor()
        c.execute("SELECT 1 FROM images WHERE phash = ? LIMIT 1;", (phash,))
        if c.fetchone() is None:
            c.execute("DELETE FROM hashes WHERE phash = ?;", (phash,))
            self.conn.commit()

    def has_exact_hash(self, phash: str) -> bool:
        c = self.conn.cursor()
        c.execute("SELECT 1 FROM hashes WHERE phash = ? LIMIT 1;", (phash,))
        return c.fetchone() is not None

    def insert_hash(self, phash: str) -> bool:
        try:
            c = self.conn.cursor()
            c.execute("INSERT OR IGNORE INTO hashes (phash) VALUES (?);", (phash,))
            self.conn.commit()
            return c.rowcount > 0
        except Exception:
            return False

    def iter_hashes(self) -> list[str]:
        c = self.conn.cursor()
        c.execute("SELECT phash FROM hashes;")
        rows = c.fetchall()
        return [r[0] for r in rows]

    def get_stats_by_domain(self, limit: int = 20) -> list[tuple[str, int]]:
        """Количество изображений по источнику (домену), по убыванию."""
        c = self.conn.cursor()
        c.execute(
            """
            SELECT COALESCE(source, ''), COUNT(*) as cnt
            FROM images
            GROUP BY source
            ORDER BY cnt DESC
            LIMIT ?;
            """,
            (int(limit),),
        )
        return [(str(r[0]), int(r[1])) for r in c.fetchall()]

    def get_stats_by_date(self, limit: int = 30) -> list[tuple[str, int]]:
        """Количество изображений по датам (YYYY-MM-DD), начиная с последних дат."""
        c = self.conn.cursor()
        c.execute(
            """
            SELECT strftime('%Y-%m-%d', created_at) as d, COUNT(*) as cnt
            FROM images
            GROUP BY d
            ORDER BY d DESC
            LIMIT ?;
            """,
            (int(limit),),
        )
        return [(str(r[0]), int(r[1])) for r in c.fetchall()]

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
