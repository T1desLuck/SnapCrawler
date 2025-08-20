from __future__ import annotations
import asyncio
from typing import Iterable, Set, List, Tuple
from urllib.parse import urljoin, urlsplit, urlunsplit
from collections import deque

from bs4 import BeautifulSoup
import json
import aiohttp
import random

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
                 skip_logo_urls: bool = False, logo_keywords: List[str] | None = None,
                 allow_subdomains: bool = True,
                 collector_conn_limit: int = 8,
                 page_timeout: int = 20) -> None:
        # Инициализация параметров до нормализации (используются ниже)
        self.user_agents = user_agents
        self.request_delay = request_delay
        self.max_requests_per_site = max_requests_per_site
        self.deep_parsing = bool(deep_parsing)
        self.deep_max_depth = max(0, int(deep_max_depth))
        # Нормализуем расширения: приводим к нижнему регистру и добавляем ведущую точку
        ex: List[str] = []
        for e in (extensions or []):
            try:
                el = str(e).lower().strip()
            except Exception:
                continue
            if not el:
                continue
            if not el.startswith("."):
                el = "." + el
            ex.append(el)
        self.extensions = ex
        self.skip_watermarked_urls = bool(skip_watermarked_urls)
        self.watermark_keywords = [w.lower() for w in (watermark_keywords or [])]
        self.skip_screenshot_urls = bool(skip_screenshot_urls)
        self.screenshot_keywords = [w.lower() for w in (screenshot_keywords or [])]
        self.skip_logo_urls = bool(skip_logo_urls)
        self.logo_keywords = [w.lower() for w in (logo_keywords or [])]
        self.url_collect_limit = max(0, int(url_collect_limit))
        self.allow_subdomains = bool(allow_subdomains)
        # Лимит одновременных соединений коллектора страниц (BFS) — берём из конфига
        self.collector_conn_limit = int(collector_conn_limit)
        # Таймаут загрузки HTML-страницы (секунды) — берём из конфига
        self.page_timeout = int(page_timeout)
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

    # Нормализуем URL страницы: убираем фрагменты, унифицируем слеши
    def _normalize_page_url(self, url: str) -> str:
        try:
            sp = urlsplit(url)
            # Убираем #fragment
            fragless = sp._replace(fragment="")
            # Убираем повторные слеши в path и нормализуем хвост (без лишнего "/")
            path = fragless.path or "/"
            if path != "/" and path.endswith("/"):
                path = path[:-1]
            fragless = fragless._replace(path=path)
            return urlunsplit(fragless)
        except Exception:
            return url

    def _is_pagination_link(self, a_tag, full_url: str) -> bool:
        try:
            rel = a_tag.get("rel") or []
            if isinstance(rel, (list, tuple)) and any(r.lower() == "next" for r in rel):
                return True
        except Exception:
            pass
        low = full_url.lower()
        # Простые шаблоны пагинации
        if "?page=" in low or "/page/" in low or "&page=" in low or "start=" in low or "offset=" in low:
            return True
        return False

    def _allowed(self, url: str) -> bool:
        d = domain_of(url)
        cnt = self._per_site_count.get(d, 0)
        if cnt >= self.max_requests_per_site:
            return False
        self._per_site_count[d] = cnt + 1
        return True

    async def _fetch(self, session: aiohttp.ClientSession, url: str) -> str:
        from urllib.parse import urlparse
        # Браузерные заголовки + реферер на корень сайта
        pu = urlparse(url)
        fallback_ref = f"{pu.scheme}://{pu.netloc}/" if pu.scheme and pu.netloc else None

        async def do_get(ua: str):
            headers = {
                "User-Agent": ua,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
                "Pragma": "no-cache",
                "Cache-Control": "no-cache",
            }
            if fallback_ref:
                headers["Referer"] = fallback_ref
            # Задержка между запросами для стелса (с джиттером)
            await asyncio.sleep(jitter_delay(self.request_delay))
            # Таймаут страницы управляется self.page_timeout из конфига
            return await session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=self.page_timeout))

        ua1 = pick_user_agent(self.user_agents)
        async with (await do_get(ua1)) as resp:
            try:
                ctype = resp.headers.get("Content-Type", "")
                self.log.debug("FETCH %s: status=%s ctype=%s", url, resp.status, ctype)
            except Exception:
                pass
            if resp.status == 200:
                text = await resp.text(errors="ignore")
                try:
                    self.log.debug("FETCH OK %s: text_len=%d", url, len(text))
                except Exception:
                    pass
                return text
            # Если блок по 403 — одна попытка с новым User-Agent
            if resp.status == 403:
                try:
                    ua2 = pick_user_agent(self.user_agents)
                    if ua2 == ua1 and len(self.user_agents) > 1:
                        ua2 = random.choice(self.user_agents)  # type: ignore[name-defined]
                except Exception:
                    ua2 = ua1
                async with (await do_get(ua2)) as resp2:
                    try:
                        ctype2 = resp2.headers.get("Content-Type", "")
                        self.log.debug("FETCH RETRY %s: status=%s ctype=%s (ua changed)", url, resp2.status, ctype2)
                    except Exception:
                        pass
                    if resp2.status == 200:
                        text2 = await resp2.text(errors="ignore")
                        try:
                            self.log.debug("FETCH OK (retry) %s: text_len=%d", url, len(text2))
                        except Exception:
                            pass
                        return text2
                    raise RuntimeError(f"HTTP {resp2.status} при загрузке страницы (повтор после 403)")
            raise RuntimeError(f"HTTP {resp.status} при загрузке страницы")

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
        base = low.split("?", 1)[0]
        # Явное совпадение по расширению
        if any(base.endswith(ext) for ext in self.extensions):
            return True
        # Разрешаем URL без расширения в последнем сегменте пути — CDN часто скрывают расширение
        last = base.rsplit("/", 1)[-1]
        if "." not in last:
            return True
        return False

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

        # Поддержка <source> внутри <picture>: используем атрибуты srcset/type
        if tag.name == "source":
            srcset = tag.get("srcset") or tag.get("data-srcset")
            if srcset:
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

        # Fallbacks: распространённые ленивые атрибуты и обычный src
        for attr in ("data-original", "data-src", "data-lazy-src", "data-llsrc", "data-image", "data-url", "src"):
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

    async def _parse_page(self, session: aiohttp.ClientSession, url: str) -> Tuple[List[Tuple[str, str]], List[str]]:
        try:
            html = await self._fetch(session, url)
        except Exception as e:
            self.log.debug("Не удалось загрузить страницу %s: %s", url, e)
            return [], []
        soup = BeautifulSoup(html, "lxml")
        imgs: List[Tuple[str, str]] = []
        samples: List[str] = []
        # Диагностика: базовые счётчики по тегам
        try:
            counts = {
                "img": len(soup.find_all("img")),
                "picture": len(soup.find_all("picture")),
                "meta": len(soup.find_all("meta")),
                "video": len(soup.find_all("video")),
                "link": len(soup.find_all("link")),
                "a": len(soup.find_all("a")),
                "script_ld": len(soup.find_all("script", {"type": "application/ld+json"})),
                "noscript": len(soup.find_all("noscript")),
            }
            self.log.debug("PARSE %s: tags=%s html_prefix=%s", url, counts, (html[:120] if isinstance(html, str) else ""))
        except Exception:
            pass

        # 1) <img> и <picture><source>
        for tag in soup.find_all("img"):
            for candidate in self._best_img_src(url, tag):
                imgs.append((candidate, url))
                if len(samples) < 5:
                    samples.append(candidate)
        for pict in soup.find_all("picture"):
            for src in pict.find_all("source"):
                for candidate in self._best_img_src(url, src):
                    imgs.append((candidate, url))
                    if len(samples) < 5:
                        samples.append(candidate)

        # 2) <noscript> fallback
        for ns in soup.find_all("noscript"):
            try:
                ns_soup = BeautifulSoup(ns.get_text() or "", "lxml")
                for tag in ns_soup.find_all("img"):
                    for candidate in self._best_img_src(url, tag):
                        imgs.append((candidate, url))
                        if len(samples) < 5:
                            samples.append(candidate)
            except Exception:
                pass

        # 3) Мета OG/Twitter — сильные сигналы, не фильтруем по расширению
        for meta in soup.find_all("meta"):
            prop = (meta.get("property") or meta.get("name") or "").lower()
            if prop in ("og:image", "og:image:url", "og:image:secure_url", "twitter:image", "twitter:image:src"):
                content = meta.get("content")
                if content:
                    cand = urljoin(url, content)
                    if not (self._is_watermarked_url(cand) or self._is_logo_url(cand) or self._is_screenshot_url(cand)):
                        imgs.append((cand, url))
                        if len(samples) < 5:
                            samples.append(cand)

        # 4) data-* атрибуты и JSON внутри них
        data_attr_candidates = (
            "data-src", "data-srcset", "data-original", "data-original-src", "data-lazy", "data-lazy-src",
            "data-image", "data-img", "data-full", "data-large", "data-url", "data-file", "data-thumb",
        )
        for el in soup.find_all(True):
            for attr, val in (el.attrs or {}).items():
                if not isinstance(val, str):
                    continue
                low_attr = str(attr).lower()
                if low_attr in data_attr_candidates or (low_attr.startswith("data-") and any(k in low_attr for k in ("img", "image", "photo", "thumb"))):
                    v = val.strip()
                    if not v:
                        continue
                    cand = urljoin(url, v)
                    strong = any(k in low_attr for k in ("img", "image", "photo", "thumb"))
                    if strong:
                        if not (self._is_watermarked_url(cand) or self._is_logo_url(cand) or self._is_screenshot_url(cand)):
                            imgs.append((cand, url))
                            if len(samples) < 5:
                                samples.append(cand)
                    else:
                        if self._passes_ext_filter(cand) and not (self._is_watermarked_url(cand) or self._is_logo_url(cand) or self._is_screenshot_url(cand)):
                            imgs.append((cand, url))
                            if len(samples) < 5:
                                samples.append(cand)
                    # JSON в значении data-* (вытаскиваем image-like ключи)
                    try:
                        if (v.startswith("{") and v.endswith("}")) or (v.startswith("[") and v.endswith("]")):
                            j = json.loads(v)
                            def _from_json(obj):
                                if isinstance(obj, dict):
                                    for k in ("image", "imageUrl", "image_url", "thumbnail", "thumbnailUrl", "contentUrl", "src", "url"):
                                        if k in obj and isinstance(obj[k], str):
                                            cc = urljoin(url, obj[k])
                                            if not (self._is_watermarked_url(cc) or self._is_logo_url(cc) or self._is_screenshot_url(cc)):
                                                imgs.append((cc, url))
                                                if len(samples) < 5:
                                                    samples.append(cc)
                                    for v2 in obj.values():
                                        _from_json(v2)
                                elif isinstance(obj, list):
                                    for it in obj:
                                        _from_json(it)
                            _from_json(j)
                    except Exception:
                        pass

        # 5) <video poster>
        for v in soup.find_all("video"):
            try:
                poster = v.get("poster")
                if poster:
                    cand = urljoin(url, poster)
                    if not (self._is_watermarked_url(cand) or self._is_logo_url(cand) or self._is_screenshot_url(cand)):
                        imgs.append((cand, url))
            except Exception:
                pass

        # 6) JSON-LD
        for sc in soup.find_all("script", {"type": "application/ld+json"}):
            try:
                data = json.loads(sc.string or sc.get_text() or "{}")
            except Exception:
                continue
            def _add_img(val):
                if isinstance(val, str):
                    cand = urljoin(url, val)
                    if not (self._is_watermarked_url(cand) or self._is_logo_url(cand) or self._is_screenshot_url(cand)):
                        imgs.append((cand, url))
                elif isinstance(val, list):
                    for v in val:
                        _add_img(v)
                elif isinstance(val, dict):
                    _add_img(val.get("url") or val.get("contentUrl") or val.get("thumbnailUrl"))
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        for key in ("image", "imageUrl", "image_url", "thumbnailUrl", "contentUrl"):
                            if key in item:
                                _add_img(item[key])
            elif isinstance(data, dict):
                for key in ("image", "imageUrl", "image_url", "thumbnailUrl", "contentUrl"):
                    if key in data:
                        _add_img(data[key])

        # 7) link rel=image_src, preload as=image
        for link in soup.find_all("link"):
            rel = (link.get("rel") or [])
            rel = [str(r).lower() for r in rel] if isinstance(rel, list) else [str(rel).lower()]
            if "image_src" in rel or link.get("rel", "").lower() == "image_src":
                href = link.get("href")
                if href:
                    cand = urljoin(url, href)
                    if not (self._is_watermarked_url(cand) or self._is_logo_url(cand) or self._is_screenshot_url(cand)):
                        imgs.append((cand, url))
            asv = (link.get("as") or link.get("as_"))
            if ("preload" in rel) and (str(asv).lower() == "image"):
                href = link.get("href")
                if href:
                    cand = urljoin(url, href)
                    if not (self._is_watermarked_url(cand) or self._is_logo_url(cand) or self._is_screenshot_url(cand)):
                        imgs.append((cand, url))

        # 8) Ссылки <a>: добавляем прямые картинки и продолжаем BFS по страницам
        next_pages: List[str] = []
        if self.deep_parsing:
            base_domain = domain_of(url)
            for a in soup.find_all("a"):
                href = a.get("href")
                if not href:
                    continue
                full = self._normalize_page_url(urljoin(url, href))
                if full in self._seen_pages:
                    continue
                target_domain = domain_of(full)
                same_site = (
                    target_domain == base_domain or
                    (self.allow_subdomains and (
                        target_domain.endswith("." + base_domain) or base_domain.endswith("." + target_domain)
                    ))
                )
                if not same_site:
                    cand = self._candidate_image_from_link(url, href)
                    if cand:
                        imgs.append((cand, url))
                        if len(samples) < 5:
                            samples.append(cand)
                    continue
                # Wikimedia Commons: прямое преобразование ссылок вида /wiki/File:... в Special:FilePath
                try:
                    if "commons.wikimedia.org" in target_domain and "/wiki/File:" in full:
                        from urllib.parse import quote
                        file_title = full.split("/wiki/File:", 1)[1]
                        # Не включаем параметры запроса/фрагменты
                        file_title = file_title.split("?", 1)[0].split("#", 1)[0]
                        special = f"https://commons.wikimedia.org/wiki/Special:FilePath/{quote(file_title, safe='/:()[]%') }"
                        imgs.append((special, url))
                        if len(samples) < 5:
                            samples.append(special)
                except Exception:
                    pass
                cand = self._candidate_image_from_link(url, href)
                if cand:
                    imgs.append((cand, url))
                    if len(samples) < 5:
                        samples.append(cand)
                if self._is_pagination_link(a, full):
                    next_pages.insert(0, full)
                else:
                    next_pages.append(full)

        # Диагностика: краткая сводка по странице
        try:
            if imgs:
                self.log.debug("Страница %s: найдено изображений=%d, переходов=%d", url, len(imgs), len(next_pages))
            else:
                self.log.debug("Страница %s: изображений не найдено, переходов=%d", url, len(next_pages))
        except Exception:
            pass
        # ASCII-диагностика для терминалов с проблемами кодировки
        try:
            self.log.debug("PAGE IMG COUNT %s -> imgs=%d next_pages=%d", url, len(imgs), len(next_pages))
            if samples:
                for s in samples:
                    self.log.debug("SAMPLE IMG URL %s -> %s", url, s)
        except Exception:
            pass
        return imgs, next_pages

    async def collect_image_urls(self) -> List[str]:
        urls: List[str] = []
        # Лимит соединений коллектора управляется download.collector_conn_limit
        conn = aiohttp.TCPConnector(limit=self.collector_conn_limit)
        async with aiohttp.ClientSession(connector=conn) as session:
            # BFS очередь по страницам: (url, depth, max_depth)
            q: deque[Tuple[str, int, int]] = deque()
            for url, md in self.sources:
                q.append((self._normalize_page_url(url), 0, md))

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
                # ASCII-диагностика количества кандидатов после парсинга
                try:
                    self.log.debug("PAGE PARSED %s: candidates=%d depth=%d queue=%d", page, len(imgs), depth, len(q))
                except Exception:
                    pass
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
                            # Пагинацию ставим в начало очереди
                            if self._is_pagination_link(None, npg):
                                q.appendleft((npg, depth + 1, max_depth))
                            else:
                                q.append((npg, depth + 1, max_depth))
                    if depth < max_depth:
                        for npg in next_pages:
                            if npg not in self._seen_pages:
                                # Пагинацию ставим в начало очереди
                                if self._is_pagination_link(None, npg):
                                    q.appendleft((npg, depth + 1, max_depth))
                                else:
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
        # Лимит соединений коллектора управляется download.collector_conn_limit
        conn = aiohttp.TCPConnector(limit=self.collector_conn_limit)
        async with aiohttp.ClientSession(connector=conn) as session:
            q: deque[Tuple[str, int, int]] = deque()
            for url, md in self.sources:
                q.append((self._normalize_page_url(url), 0, md))

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
                # Диагностика: количество кандидатов и первые несколько URL
                try:
                    self.log.debug("STREAM PAGE PARSED %s: candidates=%d depth=%d queue=%d", page, len(imgs), depth, len(q))
                    for i, (uu, rr) in enumerate(imgs[:5]):
                        self.log.debug("CANDIDATE %d on %s: %s (ref=%s)", i+1, page, uu, rr)
                except Exception:
                    pass

                # Отдаём URL по мере нахождения, с локальной дедупликацией по строке URL
                for (u, ref) in imgs:
                    if u in yielded_set:
                        continue
                    if self.skip_watermarked_urls and self.watermark_keywords and self._is_watermarked_url(u):
                        try:
                            if yielded < 5:
                                self.log.debug("SKIP watermarked %s", u)
                        except Exception:
                            pass
                        continue
                    if self.skip_screenshot_urls and self.screenshot_keywords and self._is_screenshot_url(u):
                        try:
                            if yielded < 5:
                                self.log.debug("SKIP screenshot %s", u)
                        except Exception:
                            pass
                        continue
                    if self.skip_logo_urls and self.logo_keywords and self._is_logo_url(u):
                        try:
                            if yielded < 5:
                                self.log.debug("SKIP logo %s", u)
                        except Exception:
                            pass
                        continue
                    yielded_set.add(u)
                    # Диагностика: лог первых нескольких URL с реферером
                    if yielded < 5:
                        try:
                            self.log.debug("YIELD URL: %s | referer=%s", u, ref)
                        except Exception:
                            pass
                    yield (u, ref)
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
                            if self._is_pagination_link(None, npg):
                                q.appendleft((npg, depth + 1, max_depth))
                            else:
                                q.append((npg, depth + 1, max_depth))

            self.log.info("URL-сбор завершён (stream): всего выдано ссылок=%d", yielded)
