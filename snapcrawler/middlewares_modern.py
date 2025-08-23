"""
Современные middleware для обхода анти-скрапинг защит
"""
import random
import time
from scrapy.downloadermiddlewares.useragent import UserAgentMiddleware
from scrapy.exceptions import NotConfigured


class ModernStealthMiddleware:
    """Современный stealth middleware с продвинутыми техниками обхода"""
    
    def __init__(self, settings):
        self.settings = settings
        self.viewport_sizes = [
            (1920, 1080), (1366, 768), (1536, 864), (1440, 900),
            (1280, 720), (1024, 768), (768, 1024), (414, 896)
        ]
        self.languages = [
            'en-US,en;q=0.9', 'ru-RU,ru;q=0.9,en;q=0.8',
            'de-DE,de;q=0.9,en;q=0.8', 'fr-FR,fr;q=0.9,en;q=0.8',
            'es-ES,es;q=0.9,en;q=0.8', 'it-IT,it;q=0.9,en;q=0.8',
            'zh-CN,zh;q=0.9,en;q=0.8', 'ja-JP,ja;q=0.9,en;q=0.8',
            'ko-KR,ko;q=0.9,en;q=0.8'
        ]
        
    @classmethod
    def from_crawler(cls, crawler):
        settings = crawler.settings
        if not settings.getbool('STEALTH_MODE_ENABLED', False):
            raise NotConfigured('ModernStealthMiddleware disabled')
        return cls(settings)
    
    def process_request(self, request, spider):
        """Применяет stealth техники к запросу"""
        
        # Рандомизация заголовков
        self._randomize_headers(request)
        
        # Добавление реалистичных заголовков
        self._add_realistic_headers(request)
        
        # Рандомизация времени запроса
        self._add_timing_variation()
        
        # Playwright-специфичные настройки
        if request.meta.get('playwright'):
            self._configure_playwright_stealth(request)
        
        return None
    
    def _randomize_headers(self, request):
        """Рандомизирует заголовки запроса"""
        headers = request.headers
        
        # Accept-Language
        headers['Accept-Language'] = random.choice(self.languages)
        
        # Accept-Encoding
        headers['Accept-Encoding'] = 'gzip, deflate, br'
        
        # Cache-Control
        if random.random() < 0.3:
            headers['Cache-Control'] = random.choice(['no-cache', 'max-age=0'])
        
        # DNT (Do Not Track)
        if random.random() < 0.5:
            headers['DNT'] = '1'
    
    def _add_realistic_headers(self, request):
        """Добавляет реалистичные заголовки браузера"""
        headers = request.headers
        
        # Sec-Fetch headers (современные браузеры)
        headers['Sec-Fetch-Dest'] = 'document'
        headers['Sec-Fetch-Mode'] = 'navigate'
        headers['Sec-Fetch-Site'] = random.choice(['none', 'same-origin', 'cross-site'])
        headers['Sec-Fetch-User'] = '?1'
        
        # Upgrade-Insecure-Requests
        headers['Upgrade-Insecure-Requests'] = '1'
        
        # Accept
        headers['Accept'] = 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8'
    
    def _add_timing_variation(self):
        """Добавляет вариацию в тайминг запросов"""
        # Небольшая случайная задержка
        config = getattr(self, 'config', {})
        min_delay = config.get('crawling', {}).get('delays', {}).get('min_random_delay', 0.1)
        max_delay = config.get('crawling', {}).get('delays', {}).get('max_random_delay', 0.5)
        delay = random.uniform(min_delay, max_delay)
        time.sleep(delay)
    
    def _configure_playwright_stealth(self, request):
        """Настраивает stealth параметры для Playwright"""
        from scrapy_playwright.page import PageMethod
        
        # Получаем существующие методы или создаем новые
        page_methods = request.meta.get('playwright_page_methods', [])
        
        # Рандомизация viewport
        width, height = random.choice(self.viewport_sizes)
        page_methods.append(
            PageMethod('set_viewport_size', {'width': width, 'height': height})
        )
        
        # Эмуляция геолокации
        if random.random() < 0.3:
            page_methods.append(
                PageMethod('set_geolocation', {
                    'latitude': random.uniform(40.0, 60.0),
                    'longitude': random.uniform(-10.0, 30.0)
                })
            )
        
        # Эмуляция timezone
        timezones = ['Europe/Moscow', 'Europe/London', 'America/New_York', 'Europe/Berlin']
        page_methods.append(
            PageMethod('emulate_timezone', random.choice(timezones))
        )
        
        # Отключение WebRTC для предотвращения утечки IP
        page_methods.append(
            PageMethod('evaluate', '''
                () => {
                    // Отключаем WebRTC
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined,
                    });
                    
                    // Маскируем автоматизацию
                    window.chrome = {
                        runtime: {},
                    };
                    
                    // Эмулируем плагины
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [1, 2, 3, 4, 5],
                    });
                }
            ''')
        )
        
        request.meta['playwright_page_methods'] = page_methods


class EnhancedUserAgentMiddleware(UserAgentMiddleware):
    """Расширенный middleware для ротации User-Agent с современными браузерами"""
    
    def __init__(self, user_agent='Scrapy'):
        self.user_agent = user_agent
        self.user_agent_list = [
            # Chrome (Windows)
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            
            # Firefox (Windows)
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:119.0) Gecko/20100101 Firefox/119.0',
            
            # Edge (Windows)
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
            
            # Chrome (macOS)
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            
            # Safari (macOS)
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
            
            # Chrome (Linux)
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            
            # Mobile Chrome
            'Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
            
            # Mobile Safari
            'Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1',
        ]
    
    def process_request(self, request, spider):
        """Выбирает случайный современный User-Agent"""
        ua = random.choice(self.user_agent_list)
        request.headers['User-Agent'] = ua
        return None


class AntiDetectionMiddleware:
    """Middleware для предотвращения обнаружения автоматизации"""
    
    def __init__(self, settings=None):
        self.request_count = 0
        self.last_request_time = 0
        self.config = settings.get('SNAPCRAWLER_CONFIG', {}) if settings else {}
    
    def process_request(self, request, spider):
        """Применяет техники против обнаружения"""
        self.request_count += 1
        current_time = time.time()
        
        # Адаптивная задержка на основе частоты запросов
        if self.last_request_time > 0:
            time_diff = current_time - self.last_request_time
            if time_diff < 1.0:  # Слишком быстро
                config = getattr(self, 'config', {})
                min_delay = config.get('crawling', {}).get('delays', {}).get('min_request_delay', 1.0)
                max_delay = config.get('crawling', {}).get('delays', {}).get('max_request_delay', 3.0)
                delay = random.uniform(min_delay, max_delay)
                time.sleep(delay)
        
        self.last_request_time = current_time
        
        # Добавляем вариативность в заголовки
        self._add_header_variations(request)
        
        return None
    
    def _add_header_variations(self, request):
        """Добавляет вариативность в заголовки"""
        # Случайный порядок заголовков
        if random.random() < 0.3:
            # Иногда добавляем дополнительные заголовки
            extra_headers = {
                'X-Requested-With': 'XMLHttpRequest',
                'Origin': request.url,
                'Referer': request.url,
            }
            for key, value in extra_headers.items():
                if random.random() < 0.5:
                    request.headers[key] = value
