"""
Модуль захвата сетевого трафика для извлечения изображений из API и WebSocket соединений.
Поддерживает перехват Fetch API, JSON ответов и WebSocket сообщений.
"""

import json
import logging
from typing import Dict, List, Any, Optional, Set
from urllib.parse import urljoin, urlparse
import re
from dataclasses import dataclass


@dataclass
class NetworkCaptureConfig:
    """Конфигурация для захвата сетевого трафика"""
    enabled: bool = True
    capture_json: bool = True
    capture_websockets: bool = False
    image_domains: List[str] = None
    max_captured_urls: int = 1000


class NetworkTrafficCapture:
    """Захват сетевого трафика для извлечения URL изображений"""
    
    def __init__(self, config: Dict[str, Any]):
        # Получаем конфигурацию с учетом значений по умолчанию
        network_config = config.get('network_capture', {}) if config else {}
        self.config = NetworkCaptureConfig(
            enabled=network_config.get('enabled', True),
            capture_json=network_config.get('capture_json', True),
            capture_websockets=network_config.get('capture_websockets', False),
            image_domains=network_config.get('image_domains', []),
            max_captured_urls=network_config.get('max_captured_urls', 1000)
        )
        self.captured_urls: Set[str] = set()
        self.logger = logging.getLogger(__name__)
        
        # Паттерны для поиска URL изображений в JSON
        self.image_url_patterns = [
            r'"(?:image|img|photo|picture|thumbnail|avatar|icon)(?:_url|Url|URL)?":\s*"([^"]+)"',
            r'"url":\s*"([^"]+\.(?:jpg|jpeg|png|gif|webp|avif|heic|svg))"',
            r'"src":\s*"([^"]+\.(?:jpg|jpeg|png|gif|webp|avif|heic|svg))"',
            r'"href":\s*"([^"]+\.(?:jpg|jpeg|png|gif|webp|avif|heic|svg))"',
        ]
        
    def get_network_interception_methods(self) -> List:
        """Возвращает методы Playwright для перехвата сетевых запросов"""
        if not self.config.enabled:
            return []
            
        from scrapy_playwright.page import PageMethod
        
        methods = []
        
        # Перехват всех сетевых запросов
        methods.append(PageMethod('route', '**/*', self._handle_route))
        
        # Инъекция JavaScript для перехвата Fetch API
        methods.append(PageMethod('evaluate', self._get_fetch_interception_script()))
        
        # Если включен захват WebSocket
        if self.config.capture_websockets:
            methods.append(PageMethod('evaluate', self._get_websocket_interception_script()))
            
        return methods
    
    def _handle_route(self, route, request):
        """Обработчик перехваченных сетевых запросов"""
        try:
            url = request.url
            
            # Проверяем, является ли запрос изображением
            if self._is_image_request(url):
                self.captured_urls.add(url)
                self.logger.debug(f"Перехвачен запрос изображения: {url}")
            
            # Продолжаем выполнение запроса
            route.continue_()
            
        except Exception as e:
            self.logger.error(f"Ошибка при обработке маршрута: {e}")
            route.continue_()
    
    def _is_image_request(self, url: str) -> bool:
        """Проверяет, является ли URL запросом изображения"""
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.avif', '.heic', '.svg', '.bmp', '.tiff'}
        parsed_url = urlparse(url.lower())
        
        # Проверка по расширению
        for ext in image_extensions:
            if parsed_url.path.endswith(ext):
                return True
                
        # Проверка по MIME типу в заголовках (если доступно)
        return False
    
    def _get_fetch_interception_script(self) -> str:
        """JavaScript для перехвата Fetch API запросов"""
        return '''
        () => {
            const originalFetch = window.fetch;
            window.fetch = function(...args) {
                return originalFetch.apply(this, args).then(response => {
                    try {
                        const url = response.url;
                        const contentType = response.headers.get('content-type') || '';
                        
                        // Сохраняем URL изображений
                        if (contentType.startsWith('image/') || 
                            /\\.(jpg|jpeg|png|gif|webp|avif|heic|svg)$/i.test(url)) {
                            window._capturedImageUrls = window._capturedImageUrls || [];
                            window._capturedImageUrls.push(url);
                        }
                        
                        // Анализируем JSON ответы
                        if (contentType.includes('application/json')) {
                            response.clone().text().then(text => {
                                try {
                                    const data = JSON.parse(text);
                                    window._capturedJsonData = window._capturedJsonData || [];
                                    window._capturedJsonData.push({url: url, data: data});
                                } catch (e) {
                                    // Игнорируем ошибки парсинга JSON
                                }
                            });
                        }
                    } catch (e) {
                        console.error('Ошибка перехвата fetch:', e);
                    }
                    return response;
                });
            };
        }
        '''
    
    def _get_websocket_interception_script(self) -> str:
        """JavaScript для перехвата WebSocket сообщений"""
        return '''
        () => {
            const originalWebSocket = window.WebSocket;
            window.WebSocket = function(url, protocols) {
                const ws = new originalWebSocket(url, protocols);
                
                const originalOnMessage = ws.onmessage;
                ws.onmessage = function(event) {
                    try {
                        const data = JSON.parse(event.data);
                        window._capturedWebSocketData = window._capturedWebSocketData || [];
                        window._capturedWebSocketData.push({url: url, data: data});
                    } catch (e) {
                        // Не JSON данные, игнорируем
                    }
                    
                    if (originalOnMessage) {
                        originalOnMessage.call(this, event);
                    }
                };
                
                return ws;
            };
        }
        '''
    
    def extract_captured_urls(self, page) -> List[str]:
        """Извлекает захваченные URL из страницы"""
        try:
            urls = []
            
            # Получаем URL изображений, захваченных через fetch
            captured_image_urls = page.evaluate('() => window._capturedImageUrls || []')
            if captured_image_urls:
                urls.extend(captured_image_urls)
                self.logger.info(f"Извлечено {len(captured_image_urls)} URL изображений через fetch")
            
            # Анализируем JSON данные
            if self.config.capture_json:
                captured_json_data = page.evaluate('() => window._capturedJsonData || []')
                json_urls = self._extract_urls_from_json_data(captured_json_data)
                urls.extend(json_urls)
                if json_urls:
                    self.logger.info(f"Извлечено {len(json_urls)} URL изображений из JSON")
            
            # Анализируем WebSocket данные
            if self.config.capture_websockets:
                captured_ws_data = page.evaluate('() => window._capturedWebSocketData || []')
                ws_urls = self._extract_urls_from_websocket_data(captured_ws_data)
                urls.extend(ws_urls)
                if ws_urls:
                    self.logger.info(f"Извлечено {len(ws_urls)} URL изображений из WebSocket")
            
            # Добавляем к общему набору захваченных URL
            for url in urls:
                self.captured_urls.add(url)
            
            return list(set(urls))  # Убираем дубликаты
            
        except Exception as e:
            self.logger.error(f"Ошибка извлечения захваченных URL: {e}")
            return []
    
    def _extract_urls_from_json_data(self, json_data_list: List[Dict]) -> List[str]:
        """Извлекает URL изображений из JSON данных"""
        urls = []
        
        for item in json_data_list:
            try:
                json_text = json.dumps(item.get('data', {}))
                base_url = item.get('url', '')
                
                # Применяем регулярные выражения для поиска URL
                for pattern in self.image_url_patterns:
                    matches = re.findall(pattern, json_text, re.IGNORECASE)
                    for match in matches:
                        # Преобразуем относительные URL в абсолютные
                        if match.startswith('http'):
                            urls.append(match)
                        elif base_url:
                            absolute_url = urljoin(base_url, match)
                            urls.append(absolute_url)
                            
            except Exception as e:
                self.logger.debug(f"Ошибка анализа JSON данных: {e}")
                continue
        
        return urls
    
    def _extract_urls_from_websocket_data(self, ws_data_list: List[Dict]) -> List[str]:
        """Извлекает URL изображений из WebSocket данных"""
        urls = []
        
        for item in ws_data_list:
            try:
                data = item.get('data', {})
                base_url = item.get('url', '')
                
                # Рекурсивно ищем URL изображений в данных WebSocket
                found_urls = self._find_image_urls_recursive(data, base_url)
                urls.extend(found_urls)
                
            except Exception as e:
                self.logger.debug(f"Ошибка анализа WebSocket данных: {e}")
                continue
        
        return urls
    
    def _find_image_urls_recursive(self, data: Any, base_url: str = '') -> List[str]:
        """Рекурсивно ищет URL изображений в структуре данных"""
        urls = []
        
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, str) and self._looks_like_image_url(value):
                    if value.startswith('http'):
                        urls.append(value)
                    elif base_url:
                        urls.append(urljoin(base_url, value))
                elif isinstance(value, (dict, list)):
                    urls.extend(self._find_image_urls_recursive(value, base_url))
                    
        elif isinstance(data, list):
            for item in data:
                urls.extend(self._find_image_urls_recursive(item, base_url))
        
        return urls
    
    def _looks_like_image_url(self, text: str) -> bool:
        """Проверяет, похож ли текст на URL изображения"""
        if not isinstance(text, str):
            return False
            
        # Проверка расширений файлов
        image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.avif', '.heic', '.svg', '.bmp']
        text_lower = text.lower()
        
        for ext in image_extensions:
            if ext in text_lower:
                return True
        
        # Проверка ключевых слов в URL
        image_keywords = ['image', 'img', 'photo', 'picture', 'thumbnail', 'avatar', 'icon']
        for keyword in image_keywords:
            if keyword in text_lower:
                return True
                
        return False
    
    def get_captured_urls(self) -> List[str]:
        """Возвращает все захваченные URL изображений"""
        return list(self.captured_urls)
    
    def clear_captured_urls(self):
        """Очищает список захваченных URL"""
        self.captured_urls.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """Возвращает статистику захвата"""
        return {
            'captured_urls_count': len(self.captured_urls),
            'config': {
                'enabled': self.config.enabled,
                'capture_json': self.config.capture_json,
                'capture_websockets': self.config.capture_websockets,
                'max_captured_urls': self.config.max_captured_urls
            }
        }
