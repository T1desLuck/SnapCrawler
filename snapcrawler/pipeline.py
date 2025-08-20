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
from .clip_zeroshot import ClipZeroShot, ClipConfig


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
            ctype = (resp.headers.get("Content-Type") or "").lower()
            data = await resp.read()
            # Принимаем, если явно image/*
            if "image" in ctype:
                return data, 200
            # Если это точно не картинка (html/json/xml/js) — помечаем как 415 (unsupported media type)
            if any(t in ctype for t in ("text/", "html", "json", "xml", "javascript")):
                return None, 415
            # Разрешаем generic типы — многие CDN отдают octet-stream/без заголовка
            if (not ctype) or ("octet-stream" in ctype):
                return data, 200
            # Fallback: если URL выглядит как картинка по расширению — примем и попробуем открыть далее
            url_low = url.lower().split("?", 1)[0]
            if any(url_low.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff")):
                return data, 200
            # Иначе — не поддерживаемый тип
            return None, 415
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


def _screenshot_pixel_heuristic(im: Image.Image, cfg: Dict[str, Any]) -> bool:
    """Простая эвристика для UI-скриншотов:
    - Ровная верхняя полоса (титл-бар) с низкой дисперсией
    - Повышенная плотность «текстовых» краёв в центральной области
    Возвращает True, если похоже на скриншот."""
    try:
        arr = np.asarray(im.convert("RGB"))
        h, w, _ = arr.shape
        top_ratio = float(cfg.get("top_band_ratio", 0.06))
        top_h = max(1, int(h * top_ratio))
        top = arr[:top_h, :, :]
        # Дисперсия по яркости
        gray_top = np.dot(top[..., :3], [0.299, 0.587, 0.114]).astype(np.float32)
        var_top = float(np.var(gray_top))
        var_thr = float(cfg.get("top_band_var_max", 12.0))

        # Центральная область (исключим края 10%)
        y0, y1 = int(h * 0.15), int(h * 0.85)
        x0, x1 = int(w * 0.10), int(w * 0.90)
        center = gray_top  # reuse variable for typing; will overwrite
        center = np.dot(arr[y0:y1, x0:x1, :3], [0.299, 0.587, 0.114]).astype(np.int16)
        gx = np.abs(np.diff(center, axis=1))
        gy = np.abs(np.diff(center, axis=0))
        edge_thr = int(cfg.get("edge_threshold", 28))
        edges = (gx > edge_thr).sum() + (gy > edge_thr).sum()
        total = gx.size + gy.size
        dens = edges / max(1, total)
        dens_thr = float(cfg.get("edge_density_center", 0.18))

        if var_top <= var_thr and dens >= dens_thr:
            return True
        return False
    except Exception:
        return False


def _logo_alpha_heuristic(im: Image.Image, cfg: Dict[str, Any]) -> bool:
    """Эвристика для логотипов: высокий процент прозрачных пикселей.
    Возвращает True, если вероятно логотип (прозрачный фон/иконки)."""
    try:
        if im.mode not in ("RGBA", "LA"):
            return False
        alpha = im.split()[-1]
        a = np.asarray(alpha, dtype=np.uint8)
        thr = int(cfg.get("alpha_threshold", 24))
        frac = float(cfg.get("transparent_fraction", 0.30))
        transparent = (a <= thr).sum()
        total = a.size
        return (transparent / max(1, total)) >= frac
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


async def worker(url: str, referer: Optional[str], cfg: Dict[str, Any], db: Database, session: aiohttp.ClientSession,
                 cb: CircuitBreaker, storage_root: Path, known_hashes: List[str],
                 log_rate: Dict[str, int], clf: Optional[PhotoClassifier],
                 clip_inline: Optional[ClipZeroShot]) -> Optional[Path]:
    log = get_logger()
    if not cb.allow(url):
        return None

    # Формируем заголовки для скачивания изображений
    # Многие сайты требуют Referer (иначе 403/отказ)
    # Если известна страница-источник — используем её, иначе реферер по домену картинки
    from urllib.parse import urlparse
    pu = urlparse(url)
    fallback_referer = f"{pu.scheme}://{pu.netloc}/" if pu.scheme and pu.netloc else None
    headers = {
        "User-Agent": pick_user_agent(cfg["download"]["user_agents"]),
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        # Доп. заголовки как у браузера, чтобы изображения охотнее отдавались
        "Sec-Fetch-Dest": "image",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "cross-site",
        "Pragma": "no-cache",
        "Cache-Control": "no-cache",
    }
    headers_ref = referer or fallback_referer
    if headers_ref:
        headers["Referer"] = headers_ref
    # Кол-во повторов и экспоненциальный бэкофф берём из конфига
    retries = int(cfg["download"].get("image_retries", 3))
    backoff_base = float(cfg["download"].get("backoff_base", 2.0))
    last_status: Optional[int] = None
    for attempt in range(retries):
        await asyncio.sleep(jitter_delay(cfg["download"]["request_delay"]))
        # Таймаут загрузки изображения управляется download.image_timeout
        data, status = await fetch_bytes(session, url, headers, timeout=int(cfg["download"].get("image_timeout", 25)))
        last_status = status
        if data is not None:
            cb.report(url, ok=True)
            break
        # backoff
        cb.report(url, ok=False, code=status)
        try:
            # Диагностика: первые несколько неудач логируем с реферером
            if attempt == 0:
                log.debug("Загрузка не удалась: %s status=%s referer=%s", url, status, headers.get("Referer"))
        except Exception:
            pass
        await asyncio.sleep(backoff_base ** attempt)
    else:
        if last_status == 429:
            log.debug("Получен 429, цепь для домена %s временно разомкнута", domain_of(url))
        # Учёт финальной неудачи HTTP
        key = f"http_{last_status if last_status is not None else 'err'}"
        log_rate[key] = log_rate.get(key, 0) + 1
        try:
            # Финальная диагностика неудачи скачивания
            log.info("Провал скачивания: %s status=%s referer=%s", url, last_status, headers.get("Referer"))
        except Exception:
            pass
        return None

    pp = preprocess_image(
        data,
        min_side=cfg["image"]["min_side"],
        accept_bw=cfg["image"]["accept_bw"],
        orientation=cfg["image"]["orientation"],
        wm_cfg=cfg["image"].get("watermark_pixel_filter"),
    )
    if pp is None:
        # Причину точно не знаем (капсулировано в preprocess), помечаем как общий отсеев
        log_rate["preprocess_drop"] = log_rate.get("preprocess_drop", 0) + 1
        return None
    im, w, h = pp

    # Optional classifier filter
    score: Optional[float] = None
    if clf is not None and clf.enabled:
        score = clf.is_photo(im)
        if score is not None and score < float(cfg["classifier"]["threshold"]):
            log_rate["classifier_reject"] = log_rate.get("classifier_reject", 0) + 1
            return None

    # Optional pixel screenshot heuristic
    ss_cfg = cfg["image"].get("screenshot_pixel_filter") or {}
    if bool(ss_cfg.get("enable", False)):
        try:
            if _screenshot_pixel_heuristic(im, ss_cfg):
                log_rate["screenshot_pixel"] = log_rate.get("screenshot_pixel", 0) + 1
                return None
        except Exception:
            pass

    # Optional logo alpha heuristic
    la_cfg = cfg["image"].get("logo_alpha_filter") or {}
    if bool(la_cfg.get("enable", False)):
        if _logo_alpha_heuristic(im, la_cfg):
            log_rate["logo_alpha"] = log_rate.get("logo_alpha", 0) + 1
            return None

    # Optional inline CLIP zero-shot filter
    if clip_inline is not None and clip_inline.enabled and bool(cfg["clip"].get("enable_filter", False)):
        clip_score = float(clip_inline.photo_score(im))
        if clip_score < float(cfg["clip"].get("threshold", 0.60)):
            log_rate["clip_reject"] = log_rate.get("clip_reject", 0) + 1
            return None

    # Compute pHash and deduplicate
    ph = compute_phash(im)
    thr = int(cfg["deduplication"]["hamming_threshold"]) if cfg["deduplication"]["enable"] else 0
    if cfg["deduplication"]["enable"]:
        # quick exact check
        if db.has_exact_hash(ph):
            log_rate["dup"] = log_rate.get("dup", 0) + 1
            return None
        # near-duplicate check via BK-tree
        bk: Optional[BKTree] = known_hashes  # type: ignore[assignment]
        if isinstance(bk, BKTree):
            matches = bk.search(ph, thr)
            if matches:
                log_rate["near_dup"] = log_rate.get("near_dup", 0) + 1
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
    final_path = out_dir / filename
    # Use project-level temp dir to avoid cluttering storage with dotfiles
    project_root = Path(__file__).resolve().parents[1]
    temp_dir = (project_root / ".tmp").resolve()
    temp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = temp_dir / (filename + ".part")
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
    # Cleanup stale temp files in project temp dir
    project_root = Path(__file__).resolve().parents[1]
    temp_dir = (project_root / ".tmp").resolve()
    try:
        temp_dir.mkdir(parents=True, exist_ok=True)
        for p in temp_dir.glob("*.part"):
            try:
                # Remove files older than ~48h
                if time.time() - p.stat().st_mtime > 48 * 3600:
                    p.unlink(missing_ok=True)
            except Exception:
                pass
    except Exception:
        pass
    # Стартовые параметры
    log.info(
        "Старт пайплайна: storage=%s, threads=%s, per_site=%s, deep_parsing=%s(depth=%s), target=%s",
        str(storage_root),
        cfg["download"]["threads"],
        cfg["download"].get("per_site_concurrency", 2),
        cfg["download"]["deep_parsing"],
        cfg["download"].get("deep_max_depth", 2),
        cfg["project"].get("target_images", 0),
    )

    # Инициализируем менеджер источников (streaming)
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
        url_collect_limit=int(cfg["download"].get("url_collect_limit", 0)),
        skip_screenshot_urls=bool(cfg["image"].get("skip_screenshot_urls", False)),
        screenshot_keywords=[w for w in cfg["image"].get("screenshot_keywords", [])],
        skip_logo_urls=bool(cfg["image"].get("skip_logo_urls", False)),
        logo_keywords=[w for w in cfg["image"].get("logo_keywords", [])],
        allow_subdomains=bool(cfg["download"].get("allow_subdomains", True)),
        # Новые параметры коллектора страниц: лимит соединений и таймаут
        collector_conn_limit=int(cfg["download"].get("collector_conn_limit", 8)),
        page_timeout=int(cfg["download"].get("page_timeout", 20)),
    )

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
            auto_download=bool(cfg["classifier"].get("auto_download", False)),
            download_url=str(cfg["classifier"].get("download_url", "")),
        )
        clf = PhotoClassifier(clf_cfg)
    except Exception:
        clf = None

    # Initialize CLIP inline filter (optional)
    clip_inline: Optional[ClipZeroShot] = None
    try:
        if bool(cfg["clip"].get("enable_filter", False)):
            clip_cfg = ClipConfig(
                repo_id=str(cfg["clip"]["repo_id"]),
                model_filename=str(cfg["clip"]["model_filename"]),
                tokenizer_filename=str(cfg["clip"]["tokenizer_filename"]),
                cache_dir=str(cfg["clip"]["cache_dir"]),
                revision=str(cfg["clip"].get("revision", "")) or None,
                prompts=[p for p in cfg["clip"].get("prompts", [])],
                positive_index=int(cfg["clip"].get("positive_index", 0)),
            )
            clip_inline = ClipZeroShot(clip_cfg)
    except Exception:
        clip_inline = None

    log_rate: Dict[str, int] = {}

    async with aiohttp.ClientSession(connector=conn) as session:
        threads = int(cfg["download"]["threads"])
        sem = asyncio.Semaphore(threads)
        per_site = int(cfg["download"].get("per_site_concurrency", 2))
        domain_sems: Dict[str, asyncio.Semaphore] = {}
        target = int(cfg["project"].get("target_images", 0) or 0)
        saved_count_box = {"n": db.get_basic_stats().get("images", 0)}
        stop_event = asyncio.Event()

        # Общая очередь URL с backpressure
        # Очередь пар (url, referer)
        q: asyncio.Queue[Optional[Tuple[str, Optional[str]]]] = asyncio.Queue(maxsize=max(threads * 20, 100))

        # Таймер авто-остановки для диагностики (если задан run_seconds)
        run_seconds = int(cfg["download"].get("run_seconds", 0) or 0)
        timer_task: Optional[asyncio.Task] = None
        if run_seconds > 0:
            async def stop_after():
                try:
                    await asyncio.sleep(run_seconds)
                    stop_event.set()
                except asyncio.CancelledError:
                    pass
            timer_task = asyncio.create_task(stop_after())

        async def guarded(item: Tuple[str, Optional[str]]):
            async with sem:
                u, ref = item
                d = domain_of(u)
                if d not in domain_sems:
                    domain_sems[d] = asyncio.Semaphore(per_site)
                async with domain_sems[d]:
                    return await worker(u, ref, cfg, db, session, cb, storage_root, known_hashes, log_rate, clf, clip_inline)

        async def producer():
            try:
                async for item in sm.iter_image_urls():  # item: (url, referer)
                    if stop_event.is_set():
                        break
                    await q.put(item)
            finally:
                # Сигнализируем завершение
                for _ in range(threads):
                    await q.put(None)

        async def consumer(idx: int):
            last_beat = time.time()
            while True:
                if stop_event.is_set() and q.empty():
                    break
                item = await q.get()
                if item is None:
                    q.task_done()
                    break
                try:
                    res = await guarded(item)
                    if res is not None:
                        saved_count_box["n"] += 1
                finally:
                    q.task_done()

                # Целевая остановка
                if target > 0 and saved_count_box["n"] >= target:
                    stop_event.set()

                # Heartbeat каждые ~10 сек с оценкой очереди
                now = time.time()
                if now - last_beat >= 10:
                    in_queue = q.qsize()
                    # Короткая сводка по причинам отсевов (топ-4 счётчиков)
                    counters = {k: v for k, v in log_rate.items() if not k.startswith("ok")}
                    top = sorted(counters.items(), key=lambda kv: kv[1], reverse=True)[:4]
                    drops = ", ".join(f"{k}={v}" for k, v in top) if top else ""
                    log.info(
                        "Прогресс: сохранено=%d, цель=%s, в очереди=%d%s",
                        saved_count_box["n"], target or "∞", in_queue,
                        ("; отсеяно: " + drops) if drops else "",
                    )
                    last_beat = now

        # Запускаем producer и несколько consumers
        prod_task = asyncio.create_task(producer())
        cons_tasks = [asyncio.create_task(consumer(i)) for i in range(threads)]

        # Ждём завершения
        await prod_task
        await q.join()
        stop_event.set()
        for t in cons_tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        if timer_task:
            try:
                timer_task.cancel()
            except Exception:
                pass

    if cfg["project"]["max_folder_size_mb"] > 0:
        trigger = auto_pack_if_needed(storage_root, int(cfg["project"]["max_folder_size_mb"]))
        if trigger is not None and cfg["packing"]["auto_pack"]:
            log.info("Размер папки превышен; выполните 'python spider.py pack' для архивации датасета.")

    # Финальная краткая сводка отсевов (топ-6)
    # Примечание: log_rate локален в worker/consumer, поэтому дополнительно не доступен здесь.
    # Хартбит уже печатал топ причин каждые ~10 сек.
    log.info("Пайплайн завершён. Статистика: %s", db.get_basic_stats())
