import scrapy
import hashlib
import re
from urllib.parse import urljoin, urlparse
import yaml
import os
from ..items import SnapcrawlerItem
from ..utils.log_formatter import format_url_short, format_process_status, format_stats_compact
from scrapy_playwright.page import PageMethod

class ImageSpider(scrapy.Spider):
    """
    Расширенный паук для изображений, реализующий стратегию обхода «рост дерева»
    Совместим с асинхронной архитектурой Scrapy 2.13+
    """
    name = 'image_spider'

    def __init__(self, *args, **kwargs):
        super(ImageSpider, self).__init__(*args, **kwargs)
        self.visited_urls = set()
        self.page_hashes = set()  # Для детекции дублирующихся страниц
        self.urls_by_depth = {}  # Учёт ссылок, найденных на каждом уровне
        self.new_urls_found = True  # Флаг завершения «роста дерева»

    async def start(self):
        """
        Современный асинхронный метод старта для Scrapy 2.13+
        Инициализирует конфигурацию паука и отдаёт начальные запросы
        """
        # Инициализация атрибутов из настроек
        self.config = self.settings.get('SNAPCRAWLER_CONFIG')
        start_urls = self.config['crawling']['start_urls']
        self.allowed_domains = [urlparse(url).netloc for url in start_urls]
        self.max_depth = self.config['crawling']['max_depth']
        self.js_enabled = self.config['crawling']['js_enabled']
        
        self.logger.info(format_process_status('crawl_start', f"{len(start_urls)} источников, глубина={self.max_depth}"))
        
        for url in start_urls:
            self.visited_urls.add(url)
            meta = {
                'playwright': self.js_enabled,
                'playwright_page_methods': [
                    PageMethod('wait_for_load_state', 'networkidle'),
                ],
                'depth': 0
            }
            yield scrapy.Request(url, callback=self.parse, meta=meta)

    def parse(self, response):
        depth = response.meta.get('depth', 0)
        
        # --- Дедупликация страниц ---
        page_content = response.text
        page_hash = hashlib.md5(page_content.encode('utf-8')).hexdigest()
        if page_hash in self.page_hashes:
            self.logger.info(format_process_status('duplicate', format_url_short(response.url)))
            return
        self.page_hashes.add(page_hash)

        # --- Расширённый сбор ссылок на изображения ---
        img_urls = self._extract_all_images(response)
        
        if img_urls:
            item = SnapcrawlerItem()
            item['image_urls'] = img_urls
            yield item

        # --- Извлечение ссылок по принципу «роста дерева» ---
        new_links_this_depth = 0
        if self.max_depth == 0 or depth < self.max_depth:
            links = self._extract_all_links(response)
            
            # Инициализируем учёт ссылок по уровню глубины
            if depth not in self.urls_by_depth:
                self.urls_by_depth[depth] = set()
            
            for link in links:
                absolute_link = response.urljoin(link)
                parsed_link = urlparse(absolute_link)
                
                # Фильтр: тот же домен, не посещали ранее, корректный URL
                if (parsed_link.netloc in self.allowed_domains and 
                    absolute_link not in self.visited_urls and
                    self._is_valid_url(absolute_link)):
                    
                    self.visited_urls.add(absolute_link)
                    self.urls_by_depth[depth].add(absolute_link)
                    new_links_this_depth += 1
                    
                    meta = {
                        'playwright': self.js_enabled,
                        'playwright_page_methods': [
                            PageMethod('wait_for_load_state', 'networkidle'),
                        ],
                        'depth': depth + 1
                    }
                    yield scrapy.Request(absolute_link, callback=self.parse, meta=meta)
        
        # Логика завершения «роста дерева»
        if new_links_this_depth == 0 and depth > 0:
            self.logger.info(format_process_status('depth_complete', f"уровень {depth}"))
            
    def _extract_all_images(self, response):
        """Расширённый сбор изображений из разных источников"""
        img_urls = []
        
        # 1. Стандартные теги <img>
        img_urls.extend(response.css('img::attr(src)').getall())
        img_urls.extend(response.css('img::attr(data-src)').getall())
        img_urls.extend(response.css('img::attr(data-lazy-src)').getall())
        img_urls.extend(response.css('img::attr(data-original)').getall())
        
        # 2. Фоновые изображения из CSS
        style_tags = response.css('style::text').getall()
        inline_styles = response.css('*::attr(style)').getall()
        all_styles = " ".join(style_tags + inline_styles)
        css_img_urls = re.findall(r'url\([\'\"]?(.*?)[\'\"]?\)', all_styles)
        img_urls.extend(css_img_urls)
        
        # 3. Изображения из JavaScript (по типовым паттернам)
        script_tags = response.css('script::text').getall()
        all_scripts = " ".join(script_tags)
        # Ищем распространённые паттерны URL изображений в JS
        js_img_patterns = [
            r'["\']([^"\']*/[^"\']*.(?:jpg|jpeg|png|gif|webp|svg))["\']',
            r'src["\']?\s*[:=]\s*["\']([^"\']*.(?:jpg|jpeg|png|gif|webp|svg))["\']',
            r'image["\']?\s*[:=]\s*["\']([^"\']*.(?:jpg|jpeg|png|gif|webp|svg))["\']'
        ]
        for pattern in js_img_patterns:
            js_imgs = re.findall(pattern, all_scripts, re.IGNORECASE)
            img_urls.extend(js_imgs)
        
        # 4. Структурированные данные JSON-LD
        json_ld = response.css('script[type="application/ld+json"]::text').getall()
        for json_text in json_ld:
            try:
                import json
                data = json.loads(json_text)
                # Извлекаем изображения из структурированных данных
                img_urls.extend(self._extract_from_json(data))
            except:
                pass
        
        # 5. Бесконечная прокрутка и динамический контент (если включён JS)
        if self.js_enabled and self.config['crawling'].get('infinite_scroll', False):
            # Активируем скролл для подгрузки дополнительного контента
            scroll_images = self._handle_infinite_scroll(response)
            img_urls.extend(scroll_images)
        
        # Чистим и приводим URL к абсолютному виду
        cleaned_urls = []
        for url in img_urls:
            if url and isinstance(url, str):
                absolute_url = response.urljoin(url.strip())
                if self._is_image_url(absolute_url):
                    cleaned_urls.append(absolute_url)
        
        return list(set(cleaned_urls))  # Удаляем дубликаты
    
    def _extract_all_links(self, response):
        """Извлекает все потенциальные навигационные ссылки"""
        links = []
        
        # Стандартные теги <a>
        links.extend(response.css('a::attr(href)').getall())
        
        # Ссылки навигации и меню
        links.extend(response.css('nav a::attr(href)').getall())
        links.extend(response.css('.menu a::attr(href)').getall())
        links.extend(response.css('.navigation a::attr(href)').getall())
        
        # Ссылки пагинации
        links.extend(response.css('.pagination a::attr(href)').getall())
        links.extend(response.css('.pager a::attr(href)').getall())
        
        # Ссылки категорий и тегов
        links.extend(response.css('.category a::attr(href)').getall())
        links.extend(response.css('.tag a::attr(href)').getall())
        
        return [link for link in links if link]
    
    def _extract_from_json(self, data):
        """Рекурсивно извлекает URL изображений из JSON-данных"""
        images = []
        if isinstance(data, dict):
            for key, value in data.items():
                if key.lower() in ['image', 'thumbnail', 'photo', 'picture'] and isinstance(value, str):
                    if self._is_image_url(value):
                        images.append(value)
                elif isinstance(value, (dict, list)):
                    images.extend(self._extract_from_json(value))
        elif isinstance(data, list):
            for item in data:
                images.extend(self._extract_from_json(item))
        return images
    
    def _is_valid_url(self, url):
        """Проверяет, подходит ли URL для обхода"""
        parsed = urlparse(url)
        # Пропускаем фрагменты, mailto, javascript и пр.
        if parsed.scheme not in ['http', 'https']:
            return False
        if '#' in url and url.split('#')[0] in self.visited_urls:
            return False  # Пропускаем варианты, отличающиеся только фрагментом
        return True
    
    def _is_image_url(self, url):
        """Проверяет, что URL, вероятно, указывает на изображение"""
        image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp', '.tiff']
        url_lower = url.lower()
        return any(url_lower.endswith(ext) for ext in image_extensions)
    
    def _handle_infinite_scroll(self, response):
        """Обрабатывает страницы с бесконечной прокруткой для подгрузки контента"""
        scroll_images = []
        
        # Проверяем признаки бесконечной прокрутки
        scroll_indicators = [
            '.infinite-scroll', '.lazy-load', '.load-more',
            '[data-infinite]', '[data-scroll]', '.pagination-next'
        ]
        
        has_scroll = any(response.css(indicator) for indicator in scroll_indicators)
        
        if has_scroll:
            # В реальной реализации это обрабатывается Playwright
            # Пока что просто логируем, что обнаружен скролл
            self.logger.info(format_process_status('processing', f"скролл на {format_url_short(response.url)}"))
            
            # Ищем AJAX-эндпоинты, подгружающие дополнительный контент
            ajax_patterns = [
                r'["\']([^"\']*/?(?:api|ajax|load|more|next)[^"\']*)["\']',
                r'data-url=["\']([^"\']*)["\']',
                r'data-src=["\']([^"\']*)["\']',
            ]
            
            import re
            for pattern in ajax_patterns:
                matches = re.findall(pattern, response.text)
                for match in matches:
                    if 'json' in match.lower() or 'api' in match.lower():
                        ajax_url = response.urljoin(match)
                        self.logger.debug(format_process_status('new_links', f"AJAX: {format_url_short(ajax_url)}"))
                        # В полной реализации сюда добавили бы запросы к таким эндпоинтам
        
        return scroll_images
        
    def closed(self, reason):
        """
        Завершение паука и финальный вывод статистики
        Совместим с жизненным циклом Scrapy 2.13+
        """
        total_pages = len(self.visited_urls)
        total_unique_pages = len(self.page_hashes)
        
        self.logger.info(format_process_status('crawl_complete', reason))
        self.logger.info(format_stats_compact(total_pages, 0, total_unique_pages, total_pages - total_unique_pages))
        
        # Логируем структуру по уровням для анализа
        for depth, urls in self.urls_by_depth.items():
            self.logger.info(format_process_status('depth_complete', f"ур.{depth}: {len(urls)} ссылок"))
