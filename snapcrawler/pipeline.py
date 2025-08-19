"""Асинхронный пайплайн: сбор URL → загрузка → предобработка → (классификация) → дедупликация → сохранение."""
from __future__ import annotations
import asyncio
import io
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List
from urllib.parse import urlparse

import aiohttp
from PIL import Image, ImageOps
import numpy as np
import imagehash

from .logging_setup import get_logger
from .sources import SourceManager
from .utils import pick_user_agent, jitter_delay, domain_of
from .storage import save_image_atomic, insert_image_record, auto_pack_if_needed
from .db import Database
from .classifier import PhotoClassifier, ClassifierConfig
from .bktree import BKTree


@dataclass
class CircuitBreaker:
    enabled: bool = True
    threshold: int = 3
    cooldown_sec: int = 60
    failures: Dict[str, int] = None
    blocked_until: Dict[str, float] = None

    def __post_init__(self) -> None:
        self.failures = {}
        self.blocked_until = {}

    def allow(self, url: str) -> bool:
        if not self.enabled:
            return True
        d = domain_of(url)
        until = self.blocked_until.get(d, 0)
        if until and time.time() < until:
            return False
        return True

    def report(self, url: str, ok: bool, code: Optional[int] = None) -> None:
        if not self.enabled:
            return
        d = domain_of(url)
        if ok:
            self.failures[d] = 0
            return
        if code == 429:
            # immediate trip
            self.blocked_until[d] = time.time() + self.cooldown_sec
            return
        self.failures[d] = self.failures.get(d, 0) + 1
        if self.failures[d] >= self.threshold:
            self.blocked_until[d] = time.time() + self.cooldown_sec
            self.failures[d] = 0


async def fetch_bytes(session: aiohttp.ClientSession, url: str, headers: Dict[str, str], timeout: int = 25) -> Tuple[Optional[bytes], Optional[int]]:
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            if resp.status != 200:
                return None, resp.status
            ctype = resp.headers.get("Content-Type", "").lower()
            if "image" not in ctype:
                return None, resp.status
            data = await resp.read()
            return data, 200
    except aiohttp.ClientResponseError as e:
        return None, e.status
    except Exception:
        return None, None


def _watermark_pixel_heuristic(im: Image.Image, cfg: Dict[str, Any]) -> bool:
    """Возвращает True, если вероятен водяной знак (по пиксельной эвристике в верх/низ полосах)."""
    try:
        band_ratio = float(cfg.get("band_ratio", 0.15))
        edge_threshold = int(cfg.get("edge_threshold", 25))
        edge_density = float(cfg.get("edge_density", 0.08))
        arr = np.asarray(im.convert("L"))
        h, w = arr.shape
        bh = max(1, int(h * band_ratio))
        top = arr[:bh, :]
        bot = arr[-bh:, :]
        def density(a: np.ndarray) -> float:
            # простая оценка "текстовых" краев
            gx = np.abs(np.diff(a.astype(np.int16), axis=1))
            gy = np.abs(np.diff(a.astype(np.int16), axis=0))
            edges = (gx > edge_threshold).sum() + (gy > edge_threshold).sum()
            total = gx.size + gy.size
            return edges / max(1, total)
        dens = max(density(top), density(bot))
        return dens >= edge_density
    except Exception:
        return False


def preprocess_image(data: bytes, min_side: int, accept_bw: bool, orientation: str,
                     wm_cfg: Optional[Dict[str, Any]] = None) -> Optional[Tuple[Image.Image, int, int]]:
    try:
        im = Image.open(io.BytesIO(data))
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        elif im.mode == "L":
            # grayscale
            if not accept_bw:
                return None
            im = im.convert("RGB")
        w, h = im.size
        if min(w, h) < min_side:
            return None
        # orientation filter
        ratio = w / h
        if orientation == "square" and not (0.9 <= ratio <= 1.1):
            return None
        if orientation == "portrait" and not (ratio < 0.9):
            return None
        if orientation == "landscape" and not (ratio > 1.1):
            return None
        # optional pixel watermark heuristic on bands
        if wm_cfg and bool(wm_cfg.get("enable", False)):
            if _watermark_pixel_heuristic(im, wm_cfg):
                return None
        return im, w, h
    except Exception:
        return None


def compute_phash(im: Image.Image) -> str:
    return str(imagehash.phash(im))


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


async def worker(url: str, cfg: Dict[str, Any], db: Database, session: aiohttp.ClientSession,
                 cb: CircuitBreaker, storage_root: Path, known_hashes: List[str],
                 log_rate: Dict[str, int], clf: Optional[PhotoClassifier]) -> Optional[Path]:
    log = get_logger()
    if not cb.allow(url):
        return None

    headers = {"User-Agent": pick_user_agent(cfg["download"]["user_agents"])}
    retries = 3
    last_status: Optional[int] = None
    for attempt in range(retries):
        await asyncio.sleep(jitter_delay(cfg["download"]["request_delay"]))
        data, status = await fetch_bytes(session, url, headers)
        last_status = status
        if data is not None:
            cb.report(url, ok=True)
            break
        # backoff
        cb.report(url, ok=False, code=status)
        await asyncio.sleep(2 ** attempt)
    else:
        if last_status == 429:
            log.debug("Получен 429, цепь для домена %s временно разомкнута", domain_of(url))
        return None

    pp = preprocess_image(
        data,
        min_side=cfg["image"]["min_side"],
        accept_bw=cfg["image"]["accept_bw"],
        orientation=cfg["image"]["orientation"],
        wm_cfg=cfg["image"].get("watermark_pixel_filter"),
    )
    if pp is None:
        return None
    im, w, h = pp

    # Optional classifier filter
    score: Optional[float] = None
    if clf is not None and clf.enabled:
        score = clf.is_photo(im)
        if score is not None and score < float(cfg["classifier"]["threshold"]):
            return None

    # Compute pHash and deduplicate
    ph = compute_phash(im)
    thr = int(cfg["deduplication"]["hamming_threshold"]) if cfg["deduplication"]["enable"] else 0
    if cfg["deduplication"]["enable"]:
        # quick exact check
        if db.has_exact_hash(ph):
            return None
        # near-duplicate check via BK-tree
        bk: Optional[BKTree] = known_hashes  # type: ignore[assignment]
        if isinstance(bk, BKTree):
            matches = bk.search(ph, thr)
            if matches:
                return None
        # insert new hash
        db.insert_hash(ph)
        if isinstance(bk, BKTree):
            bk.add(ph)

    # Decide save format/extension
    date_folder = time.strftime("%Y-%m-%d")
    source_domain = urlparse(url).netloc.replace(":", "_")
    out_dir = storage_root / date_folder / source_domain
    out_dir.mkdir(parents=True, exist_ok=True)
    save_format_pref = str(cfg["image"].get("save_format", "jpeg")).lower()
    jpeg_quality = int(cfg["image"].get("jpeg_quality", 95))

    # infer extension from URL
    parsed = urlparse(url)
    path = parsed.path.lower()
    ext = ".jpg"
    for cand in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"):
        if path.endswith(cand):
            ext = cand
            break

    allowed_exts = [e.lower() for e in cfg["image"].get("extensions", [])]

    def pil_format_for(extension: str) -> str:
        mapping = {
            ".jpg": "JPEG",
            ".jpeg": "JPEG",
            ".png": "PNG",
            ".webp": "WEBP",
            ".bmp": "BMP",
            ".tiff": "TIFF",
        }
        return mapping.get(extension.lower(), "JPEG")

    if save_format_pref == "original" and (not allowed_exts or ext in allowed_exts):
        out_ext = ext
        out_format = pil_format_for(ext)
    else:
        out_ext = ".jpg"
        out_format = "JPEG"

    filename = f"img_{int(time.time()*1000)}_{random.randint(1000,9999)}{out_ext}"
    tmp_path = out_dir / ("." + filename)
    final_path = out_dir / filename
    try:
        save_kwargs: Dict[str, Any] = {}
        if out_format == "JPEG":
            save_kwargs.update({"quality": jpeg_quality, "optimize": False})
            if im.mode != "RGB":
                im = im.convert("RGB")
        im.save(tmp_path, format=out_format, **save_kwargs)
        save_image_atomic(tmp_path, final_path)
    except Exception:
        try:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        return None

    insert_image_record(db, url=url, source=source_domain, width=w, height=h, ext=out_ext,
                        saved_path=final_path, score=score, phash=ph)

    # Лёгкое логирование прогресса
    log_rate["ok"] = log_rate.get("ok", 0) + 1
    if log_rate["ok"] % 50 == 0:
        get_logger().info("Сохранено %d изображений", log_rate["ok"])

    return final_path


async def run(cfg: Dict[str, Any], db: Database) -> None:
    log = get_logger()
    storage_root = Path(cfg["project"]["storage_path"]).resolve()
    storage_root.mkdir(parents=True, exist_ok=True)

    # Collect URLs
    sm = SourceManager(
        sources=cfg["download"]["sources"],
        user_agents=cfg["download"]["user_agents"],
        request_delay=float(cfg["download"]["request_delay"]),
        max_requests_per_site=int(cfg["download"]["max_requests_per_site"]),
        deep_parsing=bool(cfg["download"]["deep_parsing"]),
        deep_max_depth=int(cfg["download"].get("deep_max_depth", 2)),
        extensions=[e.lower() for e in cfg["image"].get("extensions", [])],
        skip_watermarked_urls=bool(cfg["image"].get("skip_watermarked_urls", True)),
        watermark_keywords=[w for w in cfg["image"].get("watermark_keywords", [])],
    )
    urls = await sm.collect_image_urls()
    if not urls:
        log.warning("Не найдено ни одной ссылки на изображения из заданных источников.")
        return

    # Prepare HTTP session
    conn = aiohttp.TCPConnector(limit=int(cfg["download"]["threads"]))
    cb = CircuitBreaker(enabled=bool(cfg["download"]["circuit_breaker_enabled"]))

    if cfg["deduplication"]["enable"]:
        existing = db.iter_hashes()
        known_hashes: Any = BKTree(hamming)
        known_hashes.build(existing)
    else:
        known_hashes = []

    # Initialize classifier (in-process). If model missing or disabled, it will auto-disable.
    clf: Optional[PhotoClassifier] = None
    try:
        clf_cfg = ClassifierConfig(
            enable=bool(cfg["classifier"]["enable"]),
            model_path=str(cfg["classifier"]["model_path"]),
            batch_size=int(cfg["classifier"]["batch_size"]),
            threshold=float(cfg["classifier"]["threshold"]),
        )
        clf = PhotoClassifier(clf_cfg)
    except Exception:
        clf = None

    log_rate: Dict[str, int] = {}

    async with aiohttp.ClientSession(connector=conn) as session:
        sem = asyncio.Semaphore(int(cfg["download"]["threads"]))
        per_site = int(cfg["download"].get("per_site_concurrency", 2))
        domain_sems: Dict[str, asyncio.Semaphore] = {}
        target = int(cfg["project"].get("target_images", 0) or 0)
        saved_count = db.get_basic_stats().get("images", 0)

        async def guarded(u: str):
            async with sem:
                d = domain_of(u)
                if d not in domain_sems:
                    domain_sems[d] = asyncio.Semaphore(per_site)
                async with domain_sems[d]:
                    return await worker(u, cfg, db, session, cb, storage_root, known_hashes, log_rate, clf)

        tasks = []
        for u in urls:
            # Check cap before scheduling
            if target > 0 and saved_count >= target:
                break
            t = asyncio.create_task(guarded(u))
            tasks.append(t)
        for fut in asyncio.as_completed(tasks):
            try:
                res = await fut
                if res is not None:
                    saved_count += 1
                if target > 0 and saved_count >= target:
                    # Cancel remaining tasks politely
                    for t in tasks:
                        if not t.done():
                            t.cancel()
                    break
            except Exception:
                continue

    if cfg["project"]["max_folder_size_mb"] > 0:
        trigger = auto_pack_if_needed(storage_root, int(cfg["project"]["max_folder_size_mb"]))
        if trigger is not None and cfg["packing"]["auto_pack"]:
            log.info("Размер папки превышен; выполните 'python spider.py pack' для архивации датасета.")

    log.info("Пайплайн завершён. Статистика: %s", db.get_basic_stats())
