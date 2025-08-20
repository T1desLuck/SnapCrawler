from __future__ import annotations
import asyncio
from typing import Iterable, Set, List, Tuple
from urllib.parse import urljoin
from collections import deque

from bs4 import BeautifulSoup
import aiohttp

from .logging_setup import get_logger
from .utils import domain_of, pick_user_agent, jitter_delay


class SourceManager:
    """Управляет исходными страницами и извлекает ссылки на изображения (<img>),
    с опциональным ограниченным глубоким обходом (BFS) по домену."""
    def __init__(self, sources: Iterable[str], user_agents: List[str], request_delay: float = 1.0,
                 max_requests_per_site: int = 100, deep_parsing: bool = False,
                 deep_max_depth: int = 2, extensions: List[str] | None = None,
                 skip_watermarked_urls: bool = True, watermark_keywords: List[str] | None = None,
                 url_collect_limit: int = 0,
                 skip_screenshot_urls: bool = False, screenshot_keywords: List[str] | None = None,
                 skip_logo_urls: bool = False, logo_keywords: List[str] | None = None) -> None:
        # Инициализация параметров до нормализации (используются ниже)
        self.user_agents = user_agents
        self.request_delay = request_delay
        self.max_requests_per_site = max_requests_per_site
        self.deep_parsing = bool(deep_parsing)
        self.deep_max_depth = max(0, int(deep_max_depth))
        self.extensions = [e.lower() for e in (extensions or [])]
        self.skip_watermarked_urls = bool(skip_watermarked_urls)
        self.watermark_keywords = [w.lower() for w in (watermark_keywords or [])]
        self.skip_screenshot_urls = bool(skip_screenshot_urls)
        self.screenshot_keywords = [w.lower() for w in (screenshot_keywords or [])]
        self.skip_logo_urls = bool(skip_logo_urls)
        self.logo_keywords = [w.lower() for w in (logo_keywords or [])]
        self.url_collect_limit = max(0, int(url_collect_limit))
        self._seen_pages: Set[str] = set()
        self._per_site_count: dict[str, int] = {}
        self.log = get_logger()

        # Нормализуем источники: поддерживаем как строки, так и dict с полями {url, deep, max_depth}
        norm: List[Tuple[str, int]] = []  # (url, per-source max_depth)
        for s in sources:
            if isinstance(s, dict):
                url = s.get("url") or s.get("link") or s.get("href")
                if not isinstance(url, str):
                    continue
                if bool(s.get("deep", False)):
                    md = int(s.get("max_depth", self.deep_max_depth))
                else:
                    md = 0
                norm.append((url, max(0, md)))
            elif isinstance(s, str):
                # Используем глобальные настройки deep_parsing/deep_max_depth
                md = self.deep_max_depth if self.deep_parsing else 0
                norm.append((s, max(0, md)))
        self.sources: List[Tuple[str, int]] = norm

    def _allowed(self, url: str) -> bool:
        d = domain_of(url)
        cnt = self._per_site_count.get(d, 0)
        if cnt >= self.max_requests_per_site:
            return False
        self._per_site_count[d] = cnt + 1
        return True

    async def _fetch(self, session: aiohttp.ClientSession, url: str) -> str:
        headers = {"User-Agent": pick_user_agent(self.user_agents)}
        await asyncio.sleep(jitter_delay(self.request_delay))
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status} при загрузке страницы")
            return await resp.text(errors="ignore")

    def _is_watermarked_url(self, url: str) -> bool:
        if not self.skip_watermarked_urls or not self.watermark_keywords:
            return False
        low = url.lower()
        return any(k in low for k in self.watermark_keywords)

    def _is_screenshot_url(self, url: str) -> bool:
        if not self.skip_screenshot_urls or not self.screenshot_keywords:
            return False
        low = url.lower()
        return any(k in low for k in self.screenshot_keywords)

    def _is_logo_url(self, url: str) -> bool:
        if not self.skip_logo_urls or not self.logo_keywords:
            return False
        low = url.lower()
        return any(k in low for k in self.logo_keywords)

    def _passes_ext_filter(self, url: str) -> bool:
        if not self.extensions:
            return True
        low = url.lower()
        return any(low.endswith(ext) for ext in self.extensions)

    def _best_img_src(self, base_url: str, tag) -> List[str]:
        # Возвращает кандидатов URL для картинки, отдавая приоритет наибольшему из srcset
        urls: List[str] = []
        def add(u: str):
            if not u:
                return
            full = urljoin(base_url, u)
            if self._is_watermarked_url(full):
                return
            if self._is_logo_url(full):
                return
            if self._is_screenshot_url(full):
                return
            if not self._passes_ext_filter(full):
                return
            urls.append(full)

        srcset = tag.get("srcset") or tag.get("data-srcset")
        if srcset:
            # format: "url1 320w, url2 640w, url3 1280w"
            pairs: List[Tuple[int, str]] = []
            for part in srcset.split(","):
                p = part.strip().split()
                if not p:
                    continue
                u = p[0]
                w = 0
                if len(p) > 1 and p[1].endswith("w"):
                    try:
                        w = int(p[1][:-1])
                    except Exception:
                        w = 0
                pairs.append((w, u))
            for _, u in sorted(pairs, key=lambda t: t[0], reverse=True):
                add(u)

        # Fallbacks: data-original, data-src, src
        for attr in ("data-original", "data-src", "src"):
            val = tag.get(attr)
            if val:
                add(val)
        return urls

    def _candidate_image_from_link(self, base_url: str, href: str) -> str | None:
        full = urljoin(base_url, href)
        if self._is_watermarked_url(full) or self._is_screenshot_url(full) or self._is_logo_url(full):
            return None
        low = full.lower()
        # 1) Явные расширения картинки
        if self._passes_ext_filter(low):
            return full
        # 2) Сильные ключевые слова намекающие на оригинал/загрузку
        strong_kw = ("download", "original", "orig", "full", "hires", "max", "raw")
        if any(k in low for k in strong_kw):
            # даже без расширения разрешим; pipeline проверит Content-Type
            return full
        return None

    async def _parse_page(self, session: aiohttp.ClientSession, url: str) -> Tuple[List[str], List[str]]:
        try:
            html = await self._fetch(session, url)
        except Exception as e:
            self.log.debug("Не удалось загрузить страницу %s: %s", url, e)
            return [], []
        soup = BeautifulSoup(html, "lxml")
        imgs: List[str] = []
        for tag in soup.find_all("img"):
            for candidate in self._best_img_src(url, tag):
                imgs.append(candidate)
        next_pages: List[str] = []
        if self.deep_parsing:
            base_domain = domain_of(url)
            for a in soup.find_all("a"):
                href = a.get("href")
                if not href:
                    continue
                full = urljoin(url, href)
                if full in self._seen_pages:
                    continue
                if domain_of(full) != base_domain:
                    # ссылка в другой домен — пропускаем как страницу, но если это прямая картинка — добавим
                    cand = self._candidate_image_from_link(url, href)
                    if cand:
                        imgs.append(cand)
                    continue
                # внутри домена — и как страница, и как потенциальная картинка
                cand = self._candidate_image_from_link(url, href)
                if cand:
                    imgs.append(cand)
                next_pages.append(full)
        return imgs, next_pages

    async def collect_image_urls(self) -> List[str]:
        urls: List[str] = []
        conn = aiohttp.TCPConnector(limit=8)
        async with aiohttp.ClientSession(connector=conn) as session:
            # BFS очередь по страницам: (url, depth, max_depth)
            q: deque[Tuple[str, int, int]] = deque()
            for url, md in self.sources:
                q.append((url, 0, md))

            self.log.info("Старт сбора URL: стартовых страниц=%d, глубина по умолчанию=%d, лимит URL=%s",
                         len(self.sources), self.deep_max_depth, (self.url_collect_limit or "∞"))
            processed_pages = 0
            last_beat = 0

            while q:
                page, depth, max_depth = q.popleft()
                if page in self._seen_pages:
                    continue
                self._seen_pages.add(page)
                if not self._allowed(page):
                    continue
                try:
                    imgs, next_pages = await self._parse_page(session, page)
                except Exception:
                    continue
                urls.extend(imgs)
                processed_pages += 1
                # Heartbeat каждые ~25 страниц
                if processed_pages - last_beat >= 25:
                    self.log.info("URL-сбор: страниц обработано=%d, собрано ссылок=%d, в очереди=%d",
                                   processed_pages, len(urls), len(q))
                    last_beat = processed_pages
                # Лимит на общее кол-во собранных URL (если задан)
                if self.url_collect_limit > 0 and len(urls) >= self.url_collect_limit:
                    self.log.info("Достигнут лимит сбора URL: %d. Останавливаем парсинг.", self.url_collect_limit)
                    break
                # Используем per-source max_depth; если 0 — обход только стартовой страницы
                if depth < max_depth:
                    for npg in next_pages:
                        if npg not in self._seen_pages:
                            q.append((npg, depth + 1, max_depth))

        # Фильтр-страховка по ключевым словам (если попали из вне)
        if self.skip_watermarked_urls and self.watermark_keywords:
            urls = [u for u in urls if not self._is_watermarked_url(u)]
        if self.skip_screenshot_urls and self.screenshot_keywords:
            urls = [u for u in urls if not self._is_screenshot_url(u)]
        if self.skip_logo_urls and self.logo_keywords:
            urls = [u for u in urls if not self._is_logo_url(u)]

        # Удаляем дубликаты URL
        deduped = list(dict.fromkeys(urls))
        self.log.info("Собрано %d ссылок на изображения (после дедупликации).", len(deduped))
        return deduped

    async def iter_image_urls(self):
        """Потоковый сбор URL изображений.
        Вместо возврата полного списка, отдаёт URL по мере нахождения (BFS),
        применяя те же фильтры и ограничения. Позволяет запускать загрузку параллельно со сбором.
        """
        conn = aiohttp.TCPConnector(limit=8)
        async with aiohttp.ClientSession(connector=conn) as session:
            q: deque[Tuple[str, int, int]] = deque()
            for url, md in self.sources:
                q.append((url, 0, md))

            self.log.info(
                "Старт сбора URL (stream): стартовых страниц=%d, глубина по умолчанию=%d, лимит URL=%s",
                len(self.sources), self.deep_max_depth, (self.url_collect_limit or "∞"),
            )

            processed_pages = 0
            last_beat_pages = 0
            yielded = 0
            yielded_set: Set[str] = set()

            while q:
                page, depth, max_depth = q.popleft()
                if page in self._seen_pages:
                    continue
                self._seen_pages.add(page)
                if not self._allowed(page):
                    continue
                try:
                    imgs, next_pages = await self._parse_page(session, page)
                except Exception:
                    continue

                # Отдаём URL по мере нахождения, с локальной дедупликацией
                for u in imgs:
                    if u in yielded_set:
                        continue
                    if self.skip_watermarked_urls and self.watermark_keywords and self._is_watermarked_url(u):
                        continue
                    if self.skip_screenshot_urls and self.screenshot_keywords and self._is_screenshot_url(u):
                        continue
                    if self.skip_logo_urls and self.logo_keywords and self._is_logo_url(u):
                        continue
                    yielded_set.add(u)
                    yield u
                    yielded += 1
                    if self.url_collect_limit > 0 and yielded >= self.url_collect_limit:
                        self.log.info("Достигнут лимит сбора URL (stream): %d. Останавливаем парсинг.", self.url_collect_limit)
                        return

                processed_pages += 1
                if processed_pages - last_beat_pages >= 25:
                    self.log.info(
                        "URL-сбор: страниц обработано=%d, выдано ссылок=%d, в очереди=%d",
                        processed_pages, yielded, len(q),
                    )
                    last_beat_pages = processed_pages

                if depth < max_depth:
                    for npg in next_pages:
                        if npg not in self._seen_pages:
                            q.append((npg, depth + 1, max_depth))

            self.log.info("URL-сбор завершён (stream): всего выдано ссылок=%d", yielded)
