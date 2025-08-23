"""
Модуль для эмуляции человеческого поведения при парсинге
"""
import asyncio
import random
import time
import json
from typing import List, Dict, Any, Optional
from scrapy_playwright.page import PageMethod


class HumanEmulator:
    """Эмулятор человеческого поведения для глубокого извлечения изображений"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config.get('human_emulation', {})
        self.enabled = self.config.get('enabled', False)
        self.scroll_speed = self.config.get('scroll_speed', 1000)  # пикселей в секунду
        self.click_delay = self.config.get('click_delay', (1.0, 3.0))  # диапазон задержек
        self.max_interactions = self.config.get('max_interactions', 50)
        self.scroll_pause_time = self.config.get('scroll_pause_time', 2.0)
        self.max_scroll_attempts = self.config.get('max_scroll_attempts', 10)
        
    def get_human_emulation_methods(self) -> List[PageMethod]:
        """Возвращает методы для эмуляции человеческого поведения"""
        if not self.enabled:
            return []
        
        return [
            # Инициализация эмуляции
            PageMethod('evaluate', self._get_emulation_script()),
            
            # Эмуляция скролла и взаимодействий
            PageMethod('evaluate', self._get_interaction_script()),
            
            # Ожидание стабилизации DOM
            PageMethod('wait_for_timeout', self.config.get('crawling', {}).get('timeouts', {}).get('dom_stabilization_timeout', 3000)),
            
            # Финальный сбор данных
            PageMethod('evaluate', self._get_collection_script()),
        ]
    
    def _get_emulation_script(self) -> str:
        """JavaScript для инициализации эмуляции человеческого поведения"""
        return f"""
        () => {{
            // Глобальные переменные для эмуляции
            window.humanEmulation = {{
                discoveredImages: new Set(),
                interactions: 0,
                maxInteractions: {self.max_interactions},
                scrollAttempts: 0,
                maxScrollAttempts: {self.max_scroll_attempts},
                lastScrollHeight: 0,
                isScrolling: false
            }};
            
            // Функция для случайной задержки
            window.randomDelay = (min, max) => {{
                return new Promise(resolve => {{
                    const delay = Math.random() * (max - min) + min;
                    setTimeout(resolve, delay * 1000);
                }});
            }};
            
            // Функция для эмуляции движения мыши
            window.simulateMouseMovement = () => {{
                const event = new MouseEvent('mousemove', {{
                    clientX: Math.random() * window.innerWidth,
                    clientY: Math.random() * window.innerHeight,
                    bubbles: true
                }});
                document.dispatchEvent(event);
            }};
            
            // Мониторинг мутаций DOM для обнаружения новых изображений
            const observer = new MutationObserver(mutations => {{
                mutations.forEach(mutation => {{
                    if (mutation.type === 'childList') {{
                        mutation.addedNodes.forEach(node => {{
                            if (node.nodeType === Node.ELEMENT_NODE) {{
                                // Проверяем img теги
                                const images = node.tagName === 'IMG' ? [node] : node.querySelectorAll('img');
                                images.forEach(img => {{
                                    const src = img.src || img.dataset.src || 
                                              (img.style.backgroundImage && img.style.backgroundImage.match(/url\\(["']?([^"')]+)["']?\\)/)?.[1]);
                                    if (src) window.humanEmulation.discoveredImages.add(src);
                                }});
                            }}
                        }});
                    }});
                }});
            }});
            
            observer.observe(document.body, {{
                childList: true,
                subtree: true,
                attributes: true,
                attributeFilter: ['src', 'data-src', 'style']
            }});
            
            console.log('Human emulation initialized');
        }}
        """
    
    def _get_interaction_script(self) -> str:
        """JavaScript для выполнения человеческих взаимодействий"""
        return f"""
        async () => {{
            const emulation = window.humanEmulation;
            
            // Функция для плавного скролла
            const smoothScroll = async (distance) => {{
                const startY = window.pageYOffset;
                const targetY = startY + distance;
                const duration = Math.abs(distance) / {self.scroll_speed} * 1000;
                const startTime = performance.now();
                
                return new Promise(resolve => {{
                    const scroll = (currentTime) => {{
                        const elapsed = currentTime - startTime;
                        const progress = Math.min(elapsed / duration, 1);
                        
                        // Easing function для естественного скролла
                        const easeProgress = progress < 0.5 
                            ? 2 * progress * progress 
                            : 1 - Math.pow(-2 * progress + 2, 3) / 2;
                        
                        window.scrollTo(0, startY + (targetY - startY) * easeProgress);
                        
                        if (progress < 1) {{
                            requestAnimationFrame(scroll);
                        }} else {{
                            resolve();
                        }}
                    }};
                    requestAnimationFrame(scroll);
                }});
            }};
            
            // Основной цикл взаимодействий
            while (emulation.interactions < emulation.maxInteractions && 
                   emulation.scrollAttempts < emulation.maxScrollAttempts) {{
                
                const currentHeight = document.documentElement.scrollHeight;
                
                // Если высота не изменилась несколько раз подряд - прекращаем
                if (currentHeight === emulation.lastScrollHeight) {{
                    emulation.scrollAttempts++;
                }} else {{
                    emulation.scrollAttempts = 0;
                    emulation.lastScrollHeight = currentHeight;
                }}
                
                // Случайное движение мыши
                window.simulateMouseMovement();
                
                // Поиск и клик по кнопкам "Load More"
                const loadMoreButtons = document.querySelectorAll(
                    'button:contains("Load"), button:contains("More"), ' +
                    'a:contains("Next"), [data-load], [data-more], ' +
                    '.load-more, .show-more, .pagination-next'
                );
                
                if (loadMoreButtons.length > 0 && Math.random() < 0.3) {{
                    const button = loadMoreButtons[Math.floor(Math.random() * loadMoreButtons.length)];
                    if (button.offsetParent !== null) {{ // видимая кнопка
                        // Скролл к кнопке
                        button.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
                        await window.randomDelay(1, 2);
                        
                        // Hover эффект
                        button.dispatchEvent(new MouseEvent('mouseenter', {{ bubbles: true }}));
                        await window.randomDelay(0.5, 1);
                        
                        // Клик
                        button.click();
                        await window.randomDelay({self.click_delay[0]}, {self.click_delay[1]});
                        
                        emulation.interactions++;
                        continue;
                    }}
                }}
                
                // Скролл вниз
                const scrollDistance = Math.random() * 800 + 400; // 400-1200px
                await smoothScroll(scrollDistance);
                
                // Пауза для загрузки контента
                await window.randomDelay({self.scroll_pause_time * 0.5}, {self.scroll_pause_time * 1.5});
                
                // Проверка на infinite scroll
                const isNearBottom = (window.innerHeight + window.pageYOffset) >= 
                                   document.documentElement.scrollHeight - 1000;
                
                if (isNearBottom) {{
                    // Дополнительная пауза для lazy loading
                    await window.randomDelay(2, 4);
                }}
                
                emulation.interactions++;
            }}
            
            // Финальный скролл вверх для активации lazy loading
            await smoothScroll(-window.pageYOffset / 2);
            await window.randomDelay(1, 2);
            
            console.log('Human emulation completed: ' + emulation.interactions + ' interactions, ' + emulation.discoveredImages.size + ' images discovered');
        }}
        """
    
    def _get_collection_script(self) -> str:
        """JavaScript для сбора обнаруженных изображений"""
        return """
        () => {
            // Собираем все обнаруженные изображения
            const discoveredImages = Array.from(window.humanEmulation.discoveredImages);
            
            // Дополнительный поиск в shadow DOM
            const shadowImages = [];
            const walkShadowDOM = (element) => {
                if (element.shadowRoot) {
                    const shadowImgs = element.shadowRoot.querySelectorAll('img, [data-src], [style*="background-image"]');
                    shadowImgs.forEach(img => {
                        const src = img.src || img.dataset.src || 
                                  (img.style.backgroundImage && img.style.backgroundImage.match(/url\\(["']?([^"')]+)["']?\\)/)?.[1]);
                        if (src) shadowImages.push(src);
                    });
                }
                
                Array.from(element.children).forEach(walkShadowDOM);
            };
            walkShadowDOM(document.body);
            
            // Поиск canvas элементов
            const canvasImages = [];
            document.querySelectorAll('canvas').forEach(canvas => {
                try {
                    const dataURL = canvas.toDataURL('image/png');
                    if (dataURL && dataURL !== 'data:,') {
                        canvasImages.push(dataURL);
                    }
                } catch (e) {
                    // Игнорируем CORS ошибки
                }
            });
            
            return {
                discoveredImages: discoveredImages,
                shadowImages: shadowImages,
                canvasImages: canvasImages,
                totalInteractions: window.humanEmulation.interactions,
                stats: {
                    discovered: discoveredImages.length,
                    shadow: shadowImages.length,
                    canvas: canvasImages.length
                }
            };
        }
        """


class NetworkTrafficCapture:
    """Захват сетевого трафика для извлечения URL изображений"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config.get('network_capture', {})
        self.enabled = self.config.get('enabled', False)
        self.capture_json = self.config.get('capture_json', True)
        self.capture_websockets = self.config.get('capture_websockets', False)
        self.image_domains = self.config.get('image_domains', [])
        
    def get_network_capture_methods(self) -> List[PageMethod]:
        """Возвращает методы для захвата сетевого трафика"""
        if not self.enabled:
            return []
        
        return [
            PageMethod('evaluate', self._get_network_setup_script()),
        ]
    
    def _get_network_setup_script(self) -> str:
        """JavaScript для настройки захвата сетевого трафика"""
        return f"""
        () => {{
            window.networkCapture = {{
                imageUrls: new Set(),
                apiResponses: [],
                websocketMessages: []
            }};
            
            // Перехват fetch запросов
            const originalFetch = window.fetch;
            window.fetch = async function(...args) {{
                const response = await originalFetch.apply(this, args);
                
                // Клонируем response для анализа
                const clonedResponse = response.clone();
                
                try {{
                    const contentType = response.headers.get('content-type') || '';
                    
                    // Если это изображение
                    if (contentType.startsWith('image/')) {{
                        window.networkCapture.imageUrls.add(response.url);
                    }}
                    
                    // Если это JSON - ищем URL изображений
                    if (contentType.includes('application/json') && {str(self.capture_json).lower()}) {{
                        const jsonData = await clonedResponse.json();
                        const imageUrls = extractImageUrlsFromJson(jsonData);
                        imageUrls.forEach(url => window.networkCapture.imageUrls.add(url));
                        
                        window.networkCapture.apiResponses.push({{
                            url: response.url,
                            data: jsonData,
                            imageUrls: imageUrls
                        }});
                    }}
                }} catch (e) {{
                    console.debug('Network capture error:', e);
                }}
                
                return response;
            }};
            
            // Функция для извлечения URL из JSON
            function extractImageUrlsFromJson(obj, urls = []) {{
                if (typeof obj === 'string') {{
                    // Проверяем на URL изображения
                    if (/\\.(jpg|jpeg|png|gif|webp|avif|svg|bmp|tiff)($|\\?)/i.test(obj) ||
                        /^https?:\\/\\/.*\\/(image|img|photo|picture)/i.test(obj)) {{
                        urls.push(obj);
                    }}
                }} else if (Array.isArray(obj)) {{
                    obj.forEach(item => extractImageUrlsFromJson(item, urls));
                }} else if (obj && typeof obj === 'object') {{
                    Object.keys(obj).forEach(key => {{
                        // Ключи, которые часто содержат изображения
                        if (/^(image|img|photo|picture|thumbnail|avatar|banner|background)$/i.test(key)) {{
                            if (typeof obj[key] === 'string') {{
                                urls.push(obj[key]);
                            }}
                        }}
                        extractImageUrlsFromJson(obj[key], urls);
                    }});
                }}
                return urls;
            }}
            
            // WebSocket перехват (если включен)
            if ({str(self.capture_websockets).lower()}) {{
                const originalWebSocket = window.WebSocket;
                window.WebSocket = function(url, protocols) {{
                    const ws = new originalWebSocket(url, protocols);
                    
                    const originalOnMessage = ws.onmessage;
                    ws.onmessage = function(event) {{
                        try {{
                            const data = JSON.parse(event.data);
                            const imageUrls = extractImageUrlsFromJson(data);
                            imageUrls.forEach(url => window.networkCapture.imageUrls.add(url));
                            
                            if (imageUrls.length > 0) {{
                                window.networkCapture.websocketMessages.push({{
                                    url: url,
                                    data: data,
                                    imageUrls: imageUrls
                                }});
                            }}
                        }} catch (e) {{
                            // Не JSON данные, игнорируем
                        }}
                        
                        if (originalOnMessage) {{
                            originalOnMessage.call(this, event);
                        }}
                    }};
                    
                    return ws;
                }};
            }}
            
            console.log('Network traffic capture initialized');
        }}
        """


class HiddenImageExtractor:
    """Извлечение скрытых изображений из различных источников"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config.get('hidden_images', {})
        self.enabled = self.config.get('enabled', False)
        self.extract_base64 = self.config.get('extract_base64', True)
        self.extract_canvas = self.config.get('extract_canvas', True)
        self.extract_webgl = self.config.get('extract_webgl', False)
        self.extract_shadow_dom = self.config.get('extract_shadow_dom', True)
        
    def get_hidden_extraction_methods(self) -> List[PageMethod]:
        """Возвращает методы для извлечения скрытых изображений"""
        if not self.enabled:
            return []
        
        return [
            PageMethod('evaluate', self._get_hidden_extraction_script()),
        ]
    
    def _get_hidden_extraction_script(self) -> str:
        """JavaScript для извлечения скрытых изображений"""
        return f"""
        () => {{
            const hiddenImages = {{
                base64Images: [],
                canvasImages: [],
                webglImages: [],
                shadowDomImages: []
            }};
            
            // Извлечение base64 изображений
            if ({str(self.extract_base64).lower()}) {{
                // Из data-URI в HTML
                document.querySelectorAll('[src^="data:image"], [data-src^="data:image"]').forEach(img => {{
                    const src = img.src || img.dataset.src;
                    if (src && src.startsWith('data:image')) {{
                        hiddenImages.base64Images.push(src);
                    }}
                }});
                
                // Из CSS background-image
                document.querySelectorAll('*').forEach(el => {{
                    const style = window.getComputedStyle(el);
                    const bgImage = style.backgroundImage;
                    if (bgImage && bgImage.includes('data:image')) {{
                        const match = bgImage.match(/url\\(["']?(data:image[^"')]+)["']?\\)/);
                        if (match) {{
                            hiddenImages.base64Images.push(match[1]);
                        }}
                    }}
                }});
            }}
            
            // Извлечение из Canvas
            if ({str(self.extract_canvas).lower()}) {{
                document.querySelectorAll('canvas').forEach(canvas => {{
                    try {{
                        // Проверяем, есть ли что-то нарисованное
                        const ctx = canvas.getContext('2d');
                        const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
                        const data = imageData.data;
                        
                        // Проверяем, не пустой ли canvas
                        let hasContent = false;
                        for (let i = 0; i < data.length; i += 4) {{
                            if (data[i] !== 0 || data[i+1] !== 0 || data[i+2] !== 0 || data[i+3] !== 0) {{
                                hasContent = true;
                                break;
                            }}
                        }}
                        
                        if (hasContent) {{
                            const dataURL = canvas.toDataURL('image/png');
                            hiddenImages.canvasImages.push({{
                                dataURL: dataURL,
                                width: canvas.width,
                                height: canvas.height,
                                element: canvas.outerHTML.substring(0, 100) + '...'
                            }});
                        }}
                    }} catch (e) {{
                        console.debug('Canvas extraction error:', e);
                    }}
                }});
            }}
            
            // Извлечение из WebGL (базовая поддержка)
            if ({str(self.extract_webgl).lower()}) {{
                document.querySelectorAll('canvas').forEach(canvas => {{
                    try {{
                        const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
                        if (gl) {{
                            // Создаем offscreen canvas для рендеринга
                            const offscreen = document.createElement('canvas');
                            offscreen.width = canvas.width;
                            offscreen.height = canvas.height;
                            const ctx = offscreen.getContext('2d');
                            
                            // Копируем WebGL контент (упрощенный подход)
                            ctx.drawImage(canvas, 0, 0);
                            const dataURL = offscreen.toDataURL('image/png');
                            
                            hiddenImages.webglImages.push({{
                                dataURL: dataURL,
                                width: canvas.width,
                                height: canvas.height
                            }});
                        }}
                    }} catch (e) {{
                        console.debug('WebGL extraction error:', e);
                    }}
                }});
            }}
            
            // Извлечение из Shadow DOM
            if ({str(self.extract_shadow_dom).lower()}) {{
                const walkShadowDOM = (element) => {{
                    if (element.shadowRoot) {{
                        // Поиск изображений в shadow root
                        element.shadowRoot.querySelectorAll('img, [data-src], [style*="background-image"]').forEach(img => {{
                            const src = img.src || img.dataset.src;
                            if (src) {{
                                hiddenImages.shadowDomImages.push(src);
                            }}
                            
                            // CSS background images
                            const style = window.getComputedStyle(img);
                            const bgImage = style.backgroundImage;
                            if (bgImage && bgImage !== 'none') {{
                                const match = bgImage.match(/url\\(["']?([^"')]+)["']?\\)/);
                                if (match) {{
                                    hiddenImages.shadowDomImages.push(match[1]);
                                }}
                            }}
                        }});
                    }}
                    
                    // Рекурсивно обходим дочерние элементы
                    Array.from(element.children).forEach(walkShadowDOM);
                }};
                
                walkShadowDOM(document.body);
            }}
            
            return hiddenImages;
        }}
        """
