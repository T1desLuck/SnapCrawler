import random
import time
from scrapy.downloadermiddlewares.retry import RetryMiddleware
from scrapy.exceptions import IgnoreRequest
import random
import time
import logging
from .utils.log_formatter import format_url_short, format_process_status

class RotateUserAgentMiddleware:
    """
    Промежуточный слой (middleware) для ротации заголовка User-Agent на каждый запрос.
    """

    def __init__(self, user_agents):
        self.user_agents = user_agents

    @classmethod
    def from_crawler(cls, crawler):
        # Получаем список User-Agent из конфигурации
        config = crawler.settings.get('SNAPCRAWLER_CONFIG', {})
        user_agents = config.get('crawling', {}).get('user_agents', [])
        if not user_agents:
            return None
        return cls(user_agents)

    def process_request(self, request, spider):
        if self.user_agents:
            request.headers.setdefault('User-Agent', random.choice(self.user_agents))


class ProxyMiddleware:
    """
    Промежуточный слой (middleware) для назначения прокси каждому запросу.
    """

    def __init__(self, proxies):
        self.proxies = proxies

    @classmethod
    def from_crawler(cls, crawler):
        # Включается только если в конфигурации задан список прокси
        proxies = crawler.settings.get('SNAPCRAWLER_CONFIG', {}).get('crawling', {}).get('proxies')
        if not proxies:
            return None
        return cls(proxies)

    def process_request(self, request, spider):
        if self.proxies:
            proxy = random.choice(self.proxies)
            request.meta['proxy'] = proxy


class AdaptiveDelayMiddleware:
    """
    Промежуточный слой, динамически регулирующий задержки между запросами в зависимости от ответов сервера.
    """
    
    def __init__(self, initial_delay=1.0, max_delay=30.0, backoff_factor=2.0):
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.current_delay = initial_delay
        self.consecutive_errors = 0
        self.last_request_time = 0
    
    @classmethod
    def from_crawler(cls, crawler):
        config = crawler.settings.get('SNAPCRAWLER_CONFIG', {})
        crawling_config = config.get('crawling', {})
        
        return cls(
            initial_delay=crawling_config.get('request_delay', 1.0),
            max_delay=crawling_config.get('max_delay', 30.0),
            backoff_factor=crawling_config.get('backoff_factor', 2.0)
        )
    
    def process_request(self, request, spider):
        # Реализуем адаптивную задержку между запросами
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        if time_since_last < self.current_delay:
            time.sleep(self.current_delay - time_since_last)
        
        self.last_request_time = time.time()
    
    def process_response(self, request, response, spider):
        # Корректируем задержку на основе ответа сервера
        if response.status == 200:
            # Успех — постепенно уменьшаем задержку
            self.consecutive_errors = 0
            self.current_delay = max(self.initial_delay, self.current_delay * 0.9)
        elif response.status in [429, 503, 502, 504]:  # Лимитирование или ошибки сервера
            # Увеличиваем задержку экспоненциально
            self.consecutive_errors += 1
            self.current_delay = min(self.max_delay, self.current_delay * self.backoff_factor)
            spider.logger.warning(format_process_status('throttle', f"{format_url_short(response.url)} задержка {self.current_delay:.1f}с"))
        
        return response
    
    def process_exception(self, request, exception, spider):
        # Обработка ошибок соединения
        self.consecutive_errors += 1
        self.current_delay = min(self.max_delay, self.current_delay * self.backoff_factor)
        spider.logger.warning(format_process_status('connection_error', f"задержка {self.current_delay:.1f}с"))


class CaptchaDetectionMiddleware:
    """
    Промежуточный слой для детектирования и обработки вызовов CAPTCHA.
    """
    
    def __init__(self, captcha_service_api_key=None):
        self.captcha_service_api_key = captcha_service_api_key
        self.captcha_indicators = [
            'captcha', 'recaptcha', 'hcaptcha', 'cloudflare',
            'please verify', 'human verification', 'robot check'
        ]
    
    @classmethod
    def from_crawler(cls, crawler):
        config = crawler.settings.get('SNAPCRAWLER_CONFIG', {})
        api_key = config.get('crawling', {}).get('captcha_api_key')
        return cls(captcha_service_api_key=api_key)
    
    def process_response(self, request, response, spider):
        # Проверяем, содержит ли ответ страницу с CAPTCHA
        if self.is_captcha_response(response):
            spider.logger.warning(format_process_status('captcha', format_url_short(request.url)))
            
            if self.captcha_service_api_key:
                # Пытаемся решить CAPTCHA (базовая заглушка)
                solved_response = self.solve_captcha(request, response, spider)
                if solved_response:
                    return solved_response
            
            # Если решить не удалось — пропускаем/повторим позже с увеличенной задержкой
            spider.logger.warning(format_process_status('skip', f"CAPTCHA {format_url_short(request.url)}"))
            raise IgnoreRequest(f"Требование CAPTCHA на {request.url}")
        
        return response
    
    def is_captcha_response(self, response):
        """Определяет, содержит ли ответ требование прохождения CAPTCHA"""
        if response.status == 403:
            return True
        
        content_lower = response.text.lower()
        return any(indicator in content_lower for indicator in self.captcha_indicators)
    
    def solve_captcha(self, request, response, spider):
        """Базовая заглушка для решения CAPTCHA через внешний сервис"""
        # Это заглушка под интеграцию решения CAPTCHA
        # Реальная реализация интегрируется с 2captcha, AntiCaptcha и т.п.
        spider.logger.info(format_process_status('processing', "CAPTCHA сервис не настроен"))
        return None


class AjaxInterceptorMiddleware:
    """
    Промежуточный слой для перехвата и извлечения изображений из ответов Ajax/API.
    """
    
    def __init__(self):
        self.ajax_patterns = [
            '/api/', '/ajax/', '/json/', '/load', '/fetch',
            'xhr', 'async', 'infinite', 'scroll', 'more'
        ]
    
    @classmethod
    def from_crawler(cls, crawler):
        return cls()
    
    def process_response(self, request, response, spider):
        # Проверяем, является ли ответом Ajax/API
        if self.is_ajax_response(request, response):
            # Извлекаем ссылки на изображения из JSON/Ajax-ответа
            images = self.extract_images_from_ajax(response, spider)
            if images:
                spider.logger.info(format_process_status('success', f"{len(images)} изображений из Ajax {format_url_short(request.url)}"))
                # Создаём Item для найденных изображений
                from ..items import SnapcrawlerItem
                item = SnapcrawlerItem()
                item['image_urls'] = images
                # Примечание: дальше нужно отдавать через колбэк паука (yield)
        
        return response
    
    def is_ajax_response(self, request, response):
        """Проверяет, относится ли ответ к запросу Ajax/API"""
        url_lower = request.url.lower()
        if any(pattern in url_lower for pattern in self.ajax_patterns):
            return True
        
        # Проверяем тип содержимого (Content-Type)
        content_type = response.headers.get('content-type', b'').decode().lower()
        if 'application/json' in content_type:
            return True
        
        # Проверяем заголовок X-Requested-With
        if request.headers.get('X-Requested-With') == b'XMLHttpRequest':
            return True
        
        return False
    
    def extract_images_from_ajax(self, response, spider):
        """Извлекает URL изображений из Ajax/JSON-ответа"""
        images = []
        
        try:
            import json
            import re
            
            # Пробуем распарсить как JSON
            try:
                data = json.loads(response.text)
                images.extend(self.extract_from_json_recursive(data))
            except json.JSONDecodeError:
                # Если это не JSON, ищем URL изображений в тексте
                image_pattern = r'https?://[^\s"\'>]+\.(?:jpg|jpeg|png|gif|webp|svg)(?:\?[^\s"\'>]*)?'
                found_urls = re.findall(image_pattern, response.text, re.IGNORECASE)
                images.extend(found_urls)
        
        except Exception as e:
            spider.logger.error(format_process_status('error', f"Ajax: {str(e)[:30]}"))
        
        return list(set(images))  # Убираем дубликаты
    
    def extract_from_json_recursive(self, data):
        """Рекурсивно извлекает URL изображений из JSON-структуры"""
        images = []
        
        if isinstance(data, dict):
            for key, value in data.items():
                key_lower = key.lower()
                if key_lower in ['image', 'img', 'photo', 'picture', 'thumbnail', 'src', 'url']:
                    if isinstance(value, str) and self.is_image_url(value):
                        images.append(value)
                elif isinstance(value, (dict, list)):
                    images.extend(self.extract_from_json_recursive(value))
        elif isinstance(data, list):
            for item in data:
                images.extend(self.extract_from_json_recursive(item))
        elif isinstance(data, str) and self.is_image_url(data):
            images.append(data)
        
        return images
    
    def is_image_url(self, url):
        """Проверяет, похожа ли строка на URL изображения"""
        if not isinstance(url, str) or not url.startswith(('http://', 'https://')):
            return False
        
        image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp']
        url_lower = url.lower()
        return any(ext in url_lower for ext in image_extensions)
