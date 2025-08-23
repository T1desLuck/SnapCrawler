import scrapy
import hashlib
import re
from urllib.parse import urlparse
from scrapy_playwright.page import PageMethod
from snapcrawler.utils.log_formatter import format_process_status, format_url_short, format_stats_compact
from snapcrawler.core.human_emulation import HumanEmulationModule, HiddenImageExtractor, NetworkTrafficCapture
from snapcrawler.core.navigation_module import AutoNavigationManager
from snapcrawler.core.advanced_formats import SmartImageProcessor
from snapcrawler.items import SnapcrawlerItem

class ImageSpider(scrapy.Spider):
    """
    Расширенный паук для изображений, реализующий стратегию обхода «рост дерева»
    Совместим с асинхронной архитектурой Scrapy 2.13+
    """
    name = 'image_spider'

    def __init__(self, *args, **kwargs):
        super(ImageSpider, self).__init__(*args, **kwargs)
        self.visited_urls = set()
        self.urls_by_depth = {0: set(), 1: set(), 2: set(), 3: set(), 4: set(), 5: set()}
        self.page_hashes = set()  # Для дедупликации страниц по MD5
        self.new_urls_found = True  # Флаг завершения «роста дерева»
        self.intercepted_images = set()  # Для хранения перехваченных изображений
        
        # Модули будут инициализированы в from_crawler
        self.human_emulation = None
        self.network_capture = None
        self.hidden_extractor = None
        self.auto_navigation = None
        self.image_processor = None

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super(ImageSpider, cls).from_crawler(crawler, *args, **kwargs)
        
        # Инициализируем модули для продвинутого извлечения
        config = spider.settings.get('SNAPCRAWLER_CONFIG', {})
        spider.human_emulation = HumanEmulationModule(config)
        spider.network_capture = NetworkTrafficCapture(config)
        spider.hidden_extractor = HiddenImageExtractor(config)
        
        # Инициализируем автоматическую навигацию
        spider.auto_navigation = AutoNavigationManager(config.get('crawling', {}))
        
        # Инициализируем процессор продвинутых форматов
        spider.image_processor = SmartImageProcessor(config.get('images', {}))
        
        return spider

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
        # Feature flags from config
        crawling_cfg = self.config.get('crawling', {})
        general_cfg = self.config.get('general', {})
        self.extract_responsive_images = crawling_cfg.get('extract_responsive_images', True)
        self.extract_lazy_loaded = crawling_cfg.get('extract_lazy_loaded', True)
        self.intercept_network_requests = crawling_cfg.get('intercept_network_requests', True)
        self.enhanced_css_parsing = crawling_cfg.get('enhanced_css_parsing', True)
        self.lazy_load_wait_time = float(crawling_cfg.get('lazy_load_wait_time', 0))
        self.detailed_tree_stats = bool(general_cfg.get('detailed_tree_stats', False))
        
        self.logger.info(f"{format_process_status('crawl_start')} {len(start_urls)} источников, глубина={self.max_depth}")
        
        for url in start_urls:
            self.visited_urls.add(url)
            # Base Playwright methods
            page_methods = []
            if self.js_enabled:
                page_methods.append(PageMethod('wait_for_load_state', 'networkidle'))
                # If we plan to rely on lazy loading, wait a bit for images to populate
                if self.extract_lazy_loaded and self.lazy_load_wait_time > 0:
                    page_methods.append(PageMethod('wait_for_timeout', int(self.lazy_load_wait_time * 1000)))

            meta = {
                'playwright': bool(page_methods),
                'playwright_page_methods': page_methods,
                'depth': 0
            }
            yield scrapy.Request(url, callback=self.parse, meta=meta)

    def parse(self, response):
        depth = response.meta.get('depth', 0)
        
        # --- Дедупликация страниц ---
        page_content = response.text
        page_hash = hashlib.md5(page_content.encode('utf-8')).hexdigest()
        if page_hash in self.page_hashes:
            self.logger.info(f"{format_process_status('duplicate')} {format_url_short(response.url)}")
            return
        self.page_hashes.add(page_hash)

        # --- Расширённый сбор ссылок на изображения ---
        img_urls = self._extract_all_images(response)
        
        self.logger.info(f"Найдено {len(img_urls)} изображений на {response.url}")
        
        if img_urls:
            item = SnapcrawlerItem()
            item['image_urls'] = img_urls
            self.logger.info(f"Создан item с {len(img_urls)} изображениями")
            yield item
        else:
            self.logger.warning(f"Не найдено изображений на {response.url}")

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
                    
                    # Создаем запрос с Playwright методами если нужно
                    page_methods = []
                    if self.config['crawling'].get('js_enabled', False):
                        if self.intercept_network_requests:
                            page_methods.extend(self._get_network_interception_methods())
                        page_methods.extend(self._get_human_emulation_methods())
                        page_methods.extend(self._get_hidden_extraction_methods())
                        if self.extract_lazy_loaded and self.lazy_load_wait_time > 0:
                            page_methods.append(PageMethod('wait_for_timeout', int(self.lazy_load_wait_time * 1000)))
                    
                    meta = {
                        'playwright': bool(page_methods),
                        'playwright_page_methods': page_methods,
                        'depth': depth + 1
                    }
                    yield scrapy.Request(absolute_link, callback=self.parse, meta=meta)
        
        # Генерируем запросы автоматической навигации
        if depth < self.config['crawling']['max_depth']:
            navigation_requests = self.auto_navigation.generate_navigation_requests(response)
            for nav_request in navigation_requests:
                yield nav_request
        
        # Логика завершения «роста дерева»
        if new_links_this_depth == 0 and depth > 0 and self.detailed_tree_stats:
            self.logger.info(f"{format_process_status('depth_complete')} уровень {depth}")
            
    def _extract_all_images(self, response):
        """Расширённый сбор изображений из разных источников"""
        img_urls = []
        
        # 1. Стандартные теги <img>
        img_urls.extend(response.css('img::attr(src)').getall())
        
        # 2. Lazy loading атрибуты
        if self.extract_lazy_loaded:
            img_urls.extend(self._extract_lazy_loaded_images(response))
        
        # 3. Responsive images (picture, srcset)
        if self.extract_responsive_images:
            img_urls.extend(self._extract_responsive_images(response))
        
        # 4. Перехваченные сетевые запросы
        if self.intercept_network_requests:
            img_urls.extend(self._extract_intercepted_images(response))
        
        # 5. Фоновые изображения из CSS (расширенный парсинг)
        if self.enhanced_css_parsing:
            img_urls.extend(self._extract_css_images_enhanced(response))
        
        # 6. Данные из эмуляции человеческого поведения
        img_urls.extend(self._extract_human_emulation_data(response))
        
        # 7. Сетевой трафик (JSON/API/WebSockets)
        img_urls.extend(self._extract_network_traffic_data(response))
        
        # 8. Скрытые изображения (base64, canvas, WebGL, shadow DOM)
        img_urls.extend(self._extract_hidden_images_data(response))
        
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
    
    def _extract_lazy_loaded_images(self, response):
        """Извлекает изображения с lazy loading атрибутами"""
        img_urls = []
        
        # Стандартные lazy loading атрибуты
        lazy_attrs = [
            'data-src', 'data-lazy-src', 'data-original', 'data-lazy',
            'data-srcset', 'data-background-image', 'data-bg',
            'data-image', 'data-thumb', 'data-full-src'
        ]
        
        for attr in lazy_attrs:
            img_urls.extend(response.css(f'img::attr({attr})').getall())
            img_urls.extend(response.css(f'[{attr}]::attr({attr})').getall())
        
        # Изображения с loading="lazy"
        img_urls.extend(response.css('img[loading="lazy"]::attr(src)').getall())
        
        # Элементы с data-background-image
        bg_images = response.css('[data-background-image]::attr(data-background-image)').getall()
        img_urls.extend(bg_images)
        
        return [url for url in img_urls if url and self._is_image_url(url)]
    
    def _extract_responsive_images(self, response):
        """Извлекает изображения из responsive элементов (picture, srcset)"""
        img_urls = []
        
        # Извлечение из <picture> элементов
        for picture in response.css('picture'):
            # Источники из <source> элементов
            sources = picture.css('source')
            for source in sources:
                srcset = source.attrib.get('srcset', '')
                if srcset:
                    img_urls.extend(self._parse_srcset(srcset))
                
                # Также проверяем data-srcset
                data_srcset = source.attrib.get('data-srcset', '')
                if data_srcset:
                    img_urls.extend(self._parse_srcset(data_srcset))
            
            # Fallback img внутри picture
            fallback_imgs = picture.css('img::attr(src)').getall()
            img_urls.extend(fallback_imgs)
        
        # Извлечение из srcset атрибутов обычных img
        for img in response.css('img[srcset]'):
            srcset = img.attrib.get('srcset', '')
            if srcset:
                img_urls.extend(self._parse_srcset(srcset))
        
        # Извлечение из data-srcset атрибутов
        for img in response.css('img[data-srcset]'):
            data_srcset = img.attrib.get('data-srcset', '')
            if data_srcset:
                img_urls.extend(self._parse_srcset(data_srcset))
        
        return [url for url in img_urls if url and self._is_image_url(url)]
    
    def _is_image_url(self, url):
        """Проверяет, является ли URL изображением по расширению"""
        if not url:
            return False
        
        # Получаем поддерживаемые форматы из процессора
        supported_formats = set(self.image_processor.get_supported_formats())
        
        # Добавляем дополнительные современные форматы
        supported_formats.update({
            'jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'tif',
            'webp', 'avif', 'heic', 'heif', 'svg', 'ico', 'cur',
            'jxl', 'avifs', 'webp2', 'ai', 'neural'  # Новые форматы 2025
        })
        
        # Извлекаем расширение из URL
        parsed = urlparse(url.lower())
        path = parsed.path
        
        # Убираем query параметры и якоря
        if '?' in path:
            path = path.split('?')[0]
        if '#' in path:
            path = path.split('#')[0]
        
        # Проверяем расширение
        if '.' in path:
            extension = path.split('.')[-1]
            return extension in supported_formats
        
        return False

    def _extract_css_images_enhanced(self, response):
        """Расширенное извлечение изображений из CSS с поддержкой современных техник"""
        img_urls = []
        
        # Получаем все CSS контент
        style_tags = response.css('style::text').getall()
        inline_styles = response.css('*::attr(style)').getall()
        all_styles = " ".join(style_tags + inline_styles)
        
        # Паттерны для извлечения изображений из CSS
        css_patterns = [
            # Стандартные background-image
            r'background-image:\s*url\([\'\"]?([^\'\"]+)[\'\"]?\)',
            r'background:\s*[^;]*url\([\'\"]?([^\'\"]+)[\'\"]?\)',
            
            # CSS image-set() функция
            r'image-set\(\s*[\'\"]?([^\'\"]+)[\'\"]?',
            r'-webkit-image-set\(\s*[\'\"]?([^\'\"]+)[\'\"]?',
            
            # CSS custom properties (переменные)
            r'--[\w-]+:\s*url\([\'\"]?([^\'\"]+)[\'\"]?\)',
            
            # CSS content property
            r'content:\s*url\([\'\"]?([^\'\"]+)[\'\"]?\)',
            
            # CSS mask и clip-path
            r'mask-image:\s*url\([\'\"]?([^\'\"]+)[\'\"]?\)',
            r'clip-path:\s*url\([\'\"]?([^\'\"]+)[\'\"]?\)',
            
            # CSS border-image
            r'border-image-source:\s*url\([\'\"]?([^\'\"]+)[\'\"]?\)',
            r'border-image:\s*url\([\'\"]?([^\'\"]+)[\'\"]?\)',
        ]
        
        for pattern in css_patterns:
            matches = re.findall(pattern, all_styles, re.IGNORECASE)
            img_urls.extend(matches)
        
        # Обработка CSS переменных - ищем их использование
        css_vars = re.findall(r'var\((--[\w-]+)\)', all_styles)
        for var_name in css_vars:
            var_pattern = f'{re.escape(var_name)}:\\s*url\\([\\\'\\"]?([^\\\'\\"]+)[\\\'\\"]?\\)'
            var_matches = re.findall(var_pattern, all_styles, re.IGNORECASE)
            img_urls.extend(var_matches)
        
        return [url for url in img_urls if url and self._is_image_url(url)]
    
    def _extract_human_emulation_data(self, response):
        """Извлекает данные, собранные эмуляцией человеческого поведения"""
        img_urls = []
        
        try:
            if response.meta.get('playwright_page') and self.hidden_extractor:
                page = response.meta['playwright_page']
                
                # Получаем данные эмуляции человеческого поведения
                emulation_data = page.evaluate('() => window.humanEmulation || {}')
                if 'discoveredImages' in emulation_data:
                    discovered_images = emulation_data['discoveredImages']
                    if isinstance(discovered_images, list):
                        img_urls.extend(discovered_images)
                
                # Получаем данные скрытых изображений
                hidden_data = page.evaluate('() => window.hiddenImageExtraction || {}')
                for key in ['base64Images', 'canvasImages', 'webglImages', 'shadowDomImages']:
                    if key in hidden_data and isinstance(hidden_data[key], list):
                        img_urls.extend(hidden_data[key])
                
                if img_urls:
                    self.logger.debug(f"Эмуляция человека обнаружила {len(img_urls)} изображений")
                
        except Exception as e:
            self.logger.debug(f"Ошибка извлечения данных эмуляции: {e}")
        
        return [url for url in img_urls if url and self._is_image_url(url)]
    
    def _extract_network_traffic_data(self, response):
        """Извлекает изображения из перехваченного сетевого трафика"""
        img_urls = []
        
        try:
            if response.meta.get('playwright_page'):
                page = response.meta['playwright_page']
                network_data = page.evaluate('() => window.networkCapture || {}')
                
                # Изображения из прямых запросов
                if 'imageUrls' in network_data:
                    image_urls = network_data['imageUrls']
                    if isinstance(image_urls, list):
                        img_urls.extend(image_urls)
                
                # Изображения из API responses
                if 'apiResponses' in network_data:
                    for api_response in network_data['apiResponses']:
                        if 'imageUrls' in api_response:
                            img_urls.extend(api_response['imageUrls'])
                
                # Изображения из WebSocket messages
                if 'websocketMessages' in network_data:
                    for ws_message in network_data['websocketMessages']:
                        if 'imageUrls' in ws_message:
                            img_urls.extend(ws_message['imageUrls'])
                
                if img_urls:
                    self.logger.debug(f"Захват сети обнаружил {len(img_urls)} изображений")
                
        except Exception as e:
            self.logger.debug(f"Ошибка извлечения данных сетевого трафика: {e}")
        
        return [url for url in img_urls if url and self._is_image_url(url)]
    
    def _extract_hidden_images_data(self, response):
        """Извлекает скрытые изображения из различных источников"""
        img_urls = []
        
        try:
            if response.meta.get('playwright_page'):
                page = response.meta['playwright_page']
                hidden_data = page.evaluate('() => window.hiddenImages || {}')
                
                # Base64 изображения
                if 'base64Images' in hidden_data:
                    base64_images = hidden_data['base64Images']
                    if isinstance(base64_images, list):
                        img_urls.extend(base64_images)
                
                # Canvas изображения
                if 'canvasImages' in hidden_data:
                    canvas_images = hidden_data['canvasImages']
                    if isinstance(canvas_images, list):
                        for canvas_img in canvas_images:
                            if isinstance(canvas_img, dict) and 'dataURL' in canvas_img:
                                img_urls.append(canvas_img['dataURL'])
                            elif isinstance(canvas_img, str):
                                img_urls.append(canvas_img)
                
                # WebGL изображения
                if 'webglImages' in hidden_data:
                    webgl_images = hidden_data['webglImages']
                    if isinstance(webgl_images, list):
                        for webgl_img in webgl_images:
                            if isinstance(webgl_img, dict) and 'dataURL' in webgl_img:
                                img_urls.append(webgl_img['dataURL'])
                
                # Shadow DOM изображения
                if 'shadowDomImages' in hidden_data:
                    shadow_images = hidden_data['shadowDomImages']
                    if isinstance(shadow_images, list):
                        img_urls.extend(shadow_images)
                
                if img_urls:
                    self.logger.debug(f"Извлечение скрытых изображений нашло {len(img_urls)} изображений")
                
        except Exception as e:
            self.logger.debug(f"Ошибка извлечения данных скрытых изображений: {e}")
        
        return img_urls  # Не фильтруем base64, они валидны
    
    def _get_network_interception_methods(self):
        """Возвращает методы для перехвата сетевых запросов Playwright"""
        from scrapy_playwright.page import PageMethod
        
        return [
            PageMethod('route', '**/*.{jpg,jpeg,png,gif,webp,avif,svg,bmp,tiff}', self._intercept_image_request),
            PageMethod('evaluate', '''
                () => {
                    window.interceptedImages = [];
                    const originalFetch = window.fetch;
                    window.fetch = function(...args) {
                        const url = args[0];
                        if (typeof url === 'string' && /\\.(jpg|jpeg|png|gif|webp|avif|svg|bmp|tiff)$/i.test(url)) {
                            window.interceptedImages.push(url);
                        }
                        return originalFetch.apply(this, args);
                    };
                }
            '''),
            PageMethod('wait_for_timeout', self.config.get('crawling', {}).get('timeouts', {}).get('page_load_timeout', 2000)),
        ]
    
    def _intercept_image_request(self, route):
        """Перехватывает запросы изображений для анализа"""
        request = route.request
        
        # Сохраняем URL перехваченного изображения
        self.intercepted_images.add(request.url)
        self.logger.debug(f"Перехвачено изображение: {request.url}")
        
        # Продолжаем запрос
        route.continue_()
    
    def _extract_intercepted_images(self, response):
        """Извлекает изображения, перехваченные через network monitoring"""
        img_urls = []
        
        # Получаем перехваченные изображения из Playwright
        if hasattr(self, 'intercepted_images') and self.intercepted_images:
            img_urls.extend(list(self.intercepted_images))
            self.logger.info(f"Найдено {len(self.intercepted_images)} перехваченных изображений")
            # НЕ очищаем сразу, оставляем для следующих страниц
        
        # Получаем изображения из JavaScript fetch перехвата
        try:
            if response.meta.get('playwright_page'):
                page = response.meta['playwright_page']
                js_images = page.evaluate('() => window.interceptedImages || []')
                if js_images:
                    img_urls.extend(js_images)
                    self.logger.info(f"Найдено {len(js_images)} JS перехваченных изображений")
                    # Очищаем массив
                    page.evaluate('() => window.interceptedImages = []')
        except Exception as e:
            self.logger.debug(f"Ошибка извлечения JS изображений: {e}")
        
        # Фильтруем и возвращаем только валидные URL изображений
        valid_urls = [url for url in img_urls if url and self._is_image_url(url)]
        if valid_urls:
            self.logger.info(f"Отфильтровано {len(valid_urls)} валидных URL изображений")
        
        return valid_urls
    
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
        image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.avif', '.svg', '.bmp', '.tiff', '.ico', '.heic', '.heif']
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
            self.logger.info(f"{format_process_status('processing')} скролл на {format_url_short(response.url)}")
            
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
                        self.logger.debug(f"{format_process_status('new_links')} AJAX: {format_url_short(ajax_url)}")
                        # В полной реализации сюда добавили бы запросы к таким эндпоинтам
        
        return scroll_images
        
    def closed(self, reason):
        """
        Завершение паука и финальный вывод статистики
        Совместим с жизненным циклом Scrapy 2.13+
        """
        total_pages = len(self.visited_urls)
        total_unique_pages = len(self.page_hashes)
        
        self.logger.info(f"{format_process_status('crawl_complete')} {reason}")
        self.logger.info(format_stats_compact(total_pages, 0, total_unique_pages, total_pages - total_unique_pages))
        
        # Логируем структуру по уровням для анализа (только если включено)
        if self.detailed_tree_stats:
            for depth, urls in self.urls_by_depth.items():
                self.logger.info(f"{format_process_status('depth_complete')} ур.{depth}: {len(urls)} ссылок")
    
    def _parse_srcset(self, srcset):
        """Парсит srcset атрибут и извлекает URL изображений"""
        urls = []
        try:
            # srcset формат: "url1 1x, url2 2x" или "url1 100w, url2 200w"
            entries = srcset.split(',')
            for entry in entries:
                entry = entry.strip()
                if entry:
                    # Берем первую часть до пробела как URL
                    url = entry.split()[0]
                    if url:
                        urls.append(url)
        except Exception as e:
            self.logger.debug(f"Ошибка парсинга srcset: {e}")
        return urls
    
    def _get_human_emulation_methods(self):
        """Возвращает методы эмуляции человеческого поведения для Playwright"""
        if self.human_emulation:
            return self.human_emulation.get_page_methods()
        return []
    
    def _get_network_interception_methods(self):
        """Возвращает методы перехвата сетевых запросов"""
        if self.network_capture:
            return self.network_capture.get_page_methods()
        return []
    
    def _get_hidden_extraction_methods(self):
        """Возвращает методы извлечения скрытых изображений"""
        if self.hidden_extractor:
            return self.hidden_extractor.get_page_methods()
        return []
