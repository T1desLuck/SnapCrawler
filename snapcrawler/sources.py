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
                 skip_watermarked_urls: bool = True, watermark_keywords: List[str] | None = None) -> None:
        self.sources = list(sources)
        self.user_agents = user_agents
        self.request_delay = request_delay
        self.max_requests_per_site = max_requests_per_site
        self.deep_parsing = deep_parsing
        self.deep_max_depth = max(0, int(deep_max_depth))
        self.extensions = [e.lower() for e in (extensions or [])]
        self.skip_watermarked_urls = skip_watermarked_urls
        self.watermark_keywords = [w.lower() for w in (watermark_keywords or [])]
        self._seen_pages: Set[str] = set()
        self._per_site_count: dict[str, int] = {}
        self.log = get_logger()

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
        if self._is_watermarked_url(full):
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
            # BFS очередь по страницам: (url, depth)
            q: deque[Tuple[str, int]] = deque()
            for src in self.sources:
                q.append((src, 0))

            while q:
                page, depth = q.popleft()
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
                if self.deep_parsing and depth < self.deep_max_depth:
                    for npg in next_pages:
                        if npg not in self._seen_pages:
                            q.append((npg, depth + 1))

        # Фильтр-страховка по ключевым словам (если попали из вне)
        if self.skip_watermarked_urls and self.watermark_keywords:
            urls = [u for u in urls if not self._is_watermarked_url(u)]

        # Удаляем дубликаты URL
        deduped = list(dict.fromkeys(urls))
        self.log.info("Собрано %d ссылок на изображения (после дедупликации).", len(deduped))
        return deduped
