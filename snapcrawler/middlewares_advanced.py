"""
Продвинутые middleware для обхода современных анти-скрапинг защит
"""
import random
import time
import json
import hashlib
from typing import Dict, List, Any, Optional
from scrapy.downloadermiddlewares.useragent import UserAgentMiddleware
from scrapy.exceptions import NotConfigured
from scrapy_playwright.page import PageMethod


class AdvancedFingerprintSpoofingMiddleware:
    """Продвинутый спуфинг браузерных отпечатков для обхода AI-детекции"""
    
    def __init__(self, settings):
        self.settings = settings
        self.fingerprint_level = settings.get('FINGERPRINT_SPOOF_LEVEL', 'high')
        self.canvas_noise = settings.get('CANVAS_NOISE_ENABLED', True)
        self.webgl_spoofing = settings.get('WEBGL_SPOOFING_ENABLED', True)
        self.audio_spoofing = settings.get('AUDIO_SPOOFING_ENABLED', False)
        
        # Реалистичные конфигурации браузеров
        self.browser_configs = [
            {
                'platform': 'Win32',
                'hardwareConcurrency': 8,
                'deviceMemory': 8,
                'languages': ['en-US', 'en'],
                'timezone': 'America/New_York',
                'webgl_vendor': 'Google Inc. (NVIDIA)',
                'webgl_renderer': 'ANGLE (NVIDIA, NVIDIA GeForce RTX 3070 Direct3D11 vs_5_0 ps_5_0, D3D11)',
                'screen': {'width': 1920, 'height': 1080, 'colorDepth': 24}
            },
            {
                'platform': 'MacIntel',
                'hardwareConcurrency': 10,
                'deviceMemory': 16,
                'languages': ['en-US', 'en'],
                'timezone': 'America/Los_Angeles',
                'webgl_vendor': 'Apple Inc.',
                'webgl_renderer': 'Apple M1 Pro',
                'screen': {'width': 3024, 'height': 1964, 'colorDepth': 30}
            },
            {
                'platform': 'Linux x86_64',
                'hardwareConcurrency': 12,
                'deviceMemory': 32,
                'languages': ['en-US', 'en'],
                'timezone': 'Europe/London',
                'webgl_vendor': 'Mesa',
                'webgl_renderer': 'Mesa Intel(R) UHD Graphics 630 (CFL GT2)',
                'screen': {'width': 2560, 'height': 1440, 'colorDepth': 24}
            }
        ]
        
    @classmethod
    def from_crawler(cls, crawler):
        settings = crawler.settings
        if not settings.getbool('ADVANCED_FINGERPRINT_SPOOFING', False):
            raise NotConfigured('AdvancedFingerprintSpoofingMiddleware disabled')
        return cls(settings)
    
    def process_request(self, request, spider):
        """Применяет продвинутый спуфинг отпечатков"""
        if request.meta.get('playwright'):
            self._configure_advanced_spoofing(request)
        return None
    
    def _configure_advanced_spoofing(self, request):
        """Настраивает продвинутый спуфинг для Playwright"""
        config = random.choice(self.browser_configs)
        page_methods = request.meta.get('playwright_page_methods', [])
        
        # Базовая конфигурация браузера
        page_methods.extend([
            # Спуфинг navigator properties
            PageMethod('evaluate', f'''
                () => {{
                    // Переопределяем navigator properties
                    Object.defineProperty(navigator, 'platform', {{
                        get: () => '{config["platform"]}'
                    }});
                    
                    Object.defineProperty(navigator, 'hardwareConcurrency', {{
                        get: () => {config["hardwareConcurrency"]}
                    }});
                    
                    Object.defineProperty(navigator, 'deviceMemory', {{
                        get: () => {config["deviceMemory"]}
                    }});
                    
                    Object.defineProperty(navigator, 'languages', {{
                        get: () => {json.dumps(config["languages"])}
                    }});
                    
                    // Убираем webdriver флаг
                    Object.defineProperty(navigator, 'webdriver', {{
                        get: () => undefined
                    }});
                    
                    // Добавляем реалистичные плагины
                    Object.defineProperty(navigator, 'plugins', {{
                        get: () => [
                            {{name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer'}},
                            {{name: 'Chromium PDF Plugin', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai'}},
                            {{name: 'Microsoft Edge PDF Plugin', filename: 'pdf.js'}},
                            {{name: 'WebKit built-in PDF', filename: 'WebKit built-in PDF'}}
                        ]
                    }});
                }}
            '''),
            
            # Установка timezone
            PageMethod('emulate_timezone', config['timezone']),
            
            # Установка viewport
            PageMethod('set_viewport_size', {
                'width': config['screen']['width'],
                'height': config['screen']['height']
            }),
        ])
        
        # Canvas fingerprint spoofing
        if self.canvas_noise and self.fingerprint_level == 'high':
            page_methods.append(PageMethod('evaluate', self._get_canvas_spoofing_script()))
        
        # WebGL fingerprint spoofing
        if self.webgl_spoofing:
            page_methods.append(PageMethod('evaluate', self._get_webgl_spoofing_script(config)))
        
        # Audio context spoofing
        if self.audio_spoofing and self.fingerprint_level == 'high':
            page_methods.append(PageMethod('evaluate', self._get_audio_spoofing_script()))
        
        # Общие анти-детекция меры
        page_methods.append(PageMethod('evaluate', self._get_anti_detection_script()))
        
        request.meta['playwright_page_methods'] = page_methods
    
    def _get_canvas_spoofing_script(self) -> str:
        """JavaScript для спуфинга Canvas fingerprint"""
        return f'''
        () => {{
            const originalGetContext = HTMLCanvasElement.prototype.getContext;
            const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
            const originalGetImageData = CanvasRenderingContext2D.prototype.getImageData;
            
            // Генерируем уникальный шум для сессии
            const noise = {random.random() * 0.1};
            
            HTMLCanvasElement.prototype.getContext = function(type, ...args) {{
                const context = originalGetContext.apply(this, [type, ...args]);
                
                if (type === '2d') {{
                    const originalFillText = context.fillText;
                    context.fillText = function(text, x, y, ...args) {{
                        // Добавляем минимальный шум к координатам
                        const noisyX = x + (Math.random() - 0.5) * noise;
                        const noisyY = y + (Math.random() - 0.5) * noise;
                        return originalFillText.apply(this, [text, noisyX, noisyY, ...args]);
                    }};
                }}
                
                return context;
            }};
            
            CanvasRenderingContext2D.prototype.getImageData = function(x, y, width, height) {{
                const imageData = originalGetImageData.apply(this, arguments);
                
                // Добавляем минимальный шум к пикселям
                for (let i = 0; i < imageData.data.length; i += 4) {{
                    if (Math.random() < 0.001) {{ // 0.1% пикселей
                        imageData.data[i] = Math.min(255, imageData.data[i] + Math.floor((Math.random() - 0.5) * 2));
                    }}
                }}
                
                return imageData;
            }};
        }}
        '''
    
    def _get_webgl_spoofing_script(self, config: Dict[str, Any]) -> str:
        """JavaScript для спуфинга WebGL fingerprint"""
        return f'''
        () => {{
            const originalGetContext = HTMLCanvasElement.prototype.getContext;
            
            HTMLCanvasElement.prototype.getContext = function(type, ...args) {{
                const context = originalGetContext.apply(this, arguments);
                
                if (type === 'webgl' || type === 'experimental-webgl') {{
                    const originalGetParameter = context.getParameter;
                    
                    context.getParameter = function(parameter) {{
                        // Спуфим основные WebGL параметры
                        switch (parameter) {{
                            case context.VENDOR:
                                return '{config["webgl_vendor"]}';
                            case context.RENDERER:
                                return '{config["webgl_renderer"]}';
                            case context.VERSION:
                                return 'WebGL 1.0 (OpenGL ES 2.0 Chromium)';
                            case context.SHADING_LANGUAGE_VERSION:
                                return 'WebGL GLSL ES 1.0 (OpenGL ES GLSL ES 1.0 Chromium)';
                            default:
                                return originalGetParameter.apply(this, arguments);
                        }}
                    }};
                    
                    // Спуфим расширения
                    const originalGetSupportedExtensions = context.getSupportedExtensions;
                    context.getSupportedExtensions = function() {{
                        const extensions = originalGetSupportedExtensions.apply(this, arguments);
                        // Возвращаем стандартный набор расширений
                        return [
                            'ANGLE_instanced_arrays',
                            'EXT_blend_minmax',
                            'EXT_color_buffer_half_float',
                            'EXT_disjoint_timer_query',
                            'EXT_float_blend',
                            'EXT_frag_depth',
                            'EXT_shader_texture_lod',
                            'EXT_texture_compression_rgtc',
                            'EXT_texture_filter_anisotropic',
                            'WEBKIT_EXT_texture_filter_anisotropic',
                            'EXT_sRGB',
                            'OES_element_index_uint',
                            'OES_fbo_render_mipmap',
                            'OES_standard_derivatives',
                            'OES_texture_float',
                            'OES_texture_float_linear',
                            'OES_texture_half_float',
                            'OES_texture_half_float_linear',
                            'OES_vertex_array_object',
                            'WEBGL_color_buffer_float',
                            'WEBGL_compressed_texture_s3tc',
                            'WEBKIT_WEBGL_compressed_texture_s3tc',
                            'WEBGL_compressed_texture_s3tc_srgb',
                            'WEBGL_debug_renderer_info',
                            'WEBGL_debug_shaders',
                            'WEBGL_depth_texture',
                            'WEBKIT_WEBGL_depth_texture',
                            'WEBGL_draw_buffers',
                            'WEBGL_lose_context',
                            'WEBKIT_WEBGL_lose_context'
                        ];
                    }};
                }}
                
                return context;
            }};
        }}
        '''
    
    def _get_audio_spoofing_script(self) -> str:
        """JavaScript для спуфинга Audio Context fingerprint"""
        return f'''
        () => {{
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            
            if (AudioContext) {{
                const originalCreateAnalyser = AudioContext.prototype.createAnalyser;
                const noise = {random.random() * 0.0001};
                
                AudioContext.prototype.createAnalyser = function() {{
                    const analyser = originalCreateAnalyser.apply(this, arguments);
                    const originalGetFloatFrequencyData = analyser.getFloatFrequencyData;
                    
                    analyser.getFloatFrequencyData = function(array) {{
                        originalGetFloatFrequencyData.apply(this, arguments);
                        
                        // Добавляем минимальный шум к аудио данным
                        for (let i = 0; i < array.length; i++) {{
                            array[i] += (Math.random() - 0.5) * noise;
                        }}
                    }};
                    
                    return analyser;
                }};
            }}
        }}
        '''
    
    def _get_anti_detection_script(self) -> str:
        """JavaScript для общих мер против детекции автоматизации"""
        return '''
        () => {
            // Убираем следы автоматизации
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
            
            // Маскируем Playwright/Puppeteer
            Object.defineProperty(window, 'chrome', {
                get: () => ({
                    runtime: {},
                    loadTimes: function() {},
                    csi: function() {},
                    app: {}
                })
            });
            
            // Эмулируем нормальное поведение браузера
            Object.defineProperty(navigator, 'permissions', {
                get: () => ({
                    query: () => Promise.resolve({ state: 'granted' })
                })
            });
            
            // Добавляем реалистичные события
            ['mousedown', 'mouseup', 'mousemove'].forEach(eventType => {
                document.addEventListener(eventType, () => {}, { passive: true });
            });
            
            // Эмулируем активность пользователя
            let lastActivity = Date.now();
            const updateActivity = () => {
                lastActivity = Date.now();
            };
            
            ['click', 'scroll', 'keydown', 'mousemove', 'touchstart'].forEach(event => {
                document.addEventListener(event, updateActivity, { passive: true });
            });
            
            // Переопределяем Date для стабильности
            const originalDate = Date;
            const timeOffset = Math.floor(Math.random() * 1000);
            
            window.Date = class extends originalDate {
                constructor(...args) {
                    if (args.length === 0) {
                        super(originalDate.now() + timeOffset);
                    } else {
                        super(...args);
                    }
                }
                
                static now() {
                    return originalDate.now() + timeOffset;
                }
            };
        }
        '''


class SmartThrottlingMiddleware:
    """Умное троттлинг с адаптацией к нагрузке сервера"""
    
    def __init__(self, settings):
        self.settings = settings
        self.base_delay = settings.getfloat('SMART_THROTTLE_BASE_DELAY', 1.0)
        self.max_delay = settings.getfloat('SMART_THROTTLE_MAX_DELAY', 30.0)
        self.backoff_factor = settings.getfloat('SMART_THROTTLE_BACKOFF_FACTOR', 2.0)
        self.success_reduction = settings.getfloat('SMART_THROTTLE_SUCCESS_REDUCTION', 0.9)
        
        self.domain_delays = {}  # Задержки по доменам
        self.domain_stats = {}   # Статистика по доменам
        
    @classmethod
    def from_crawler(cls, crawler):
        settings = crawler.settings
        if not settings.getbool('SMART_THROTTLING_ENABLED', False):
            raise NotConfigured('SmartThrottlingMiddleware disabled')
        return cls(settings)
    
    def process_request(self, request, spider):
        """Применяет умную задержку перед запросом"""
        domain = self._get_domain(request.url)
        base_delay = self.settings.get('SNAPCRAWLER_CONFIG', {}).get('crawling', {}).get('delays', {}).get('base_delay', self.base_delay)
        delay = self.domain_delays.get(domain, base_delay)
        
        if delay > 0:
            time.sleep(delay)
        
        return None
    
    def process_response(self, request, response, spider):
        """Адаптирует задержки на основе ответа сервера"""
        domain = self._get_domain(request.url)
        current_delay = self.domain_delays.get(domain, self.base_delay)
        
        # Инициализируем статистику домена
        if domain not in self.domain_stats:
            self.domain_stats[domain] = {
                'success_count': 0,
                'error_count': 0,
                'last_status': None
            }
        
        stats = self.domain_stats[domain]
        
        if response.status == 200:
            # Успешный запрос - уменьшаем задержку
            stats['success_count'] += 1
            new_delay = max(self.base_delay, current_delay * self.success_reduction)
            
        elif response.status == 429:  # Too Many Requests
            # Слишком много запросов - увеличиваем задержку
            stats['error_count'] += 1
            new_delay = min(self.max_delay, current_delay * self.backoff_factor)
            spider.logger.warning(f"Ограничение частоты на {domain}, увеличиваем задержку до {new_delay:.2f}с")
            
        elif response.status >= 500:  # Server errors
            # Ошибка сервера - умеренное увеличение задержки
            stats['error_count'] += 1
            new_delay = min(self.max_delay, current_delay * 1.5)
            
        else:
            # Другие статусы - сохраняем текущую задержку
            new_delay = current_delay
        
        self.domain_delays[domain] = new_delay
        stats['last_status'] = response.status
        
        return response
    
    def _get_domain(self, url: str) -> str:
        """Извлекает домен из URL"""
        from urllib.parse import urlparse
        return urlparse(url).netloc


class CaptchaSolverMiddleware:
    """Middleware для автоматического решения CAPTCHA"""
    
    def __init__(self, settings):
        self.settings = settings
        self.api_key = settings.get('CAPTCHA_API_KEY', '')
        self.service = settings.get('CAPTCHA_SERVICE', '2captcha')  # 2captcha, anticaptcha
        self.enabled = bool(self.api_key)
        
    @classmethod
    def from_crawler(cls, crawler):
        settings = crawler.settings
        if not settings.get('CAPTCHA_API_KEY'):
            raise NotConfigured('CaptchaSolverMiddleware disabled - no API key')
        return cls(settings)
    
    def process_response(self, request, response, spider):
        """Обрабатывает ответы с CAPTCHA"""
        if self._is_captcha_response(response):
            spider.logger.info(f"CAPTCHA обнаружена на {request.url}")
            
            if self.enabled:
                try:
                    solution = self._solve_captcha(response, spider)
                    if solution:
                        # Создаем новый запрос с решением CAPTCHA
                        return self._create_captcha_solution_request(request, solution)
                except Exception as e:
                    spider.logger.error(f"Ошибка решения CAPTCHA: {e}")
        
        return response
    
    def _is_captcha_response(self, response) -> bool:
        """Определяет, содержит ли ответ CAPTCHA"""
        captcha_indicators = [
            'captcha', 'recaptcha', 'hcaptcha', 'cloudflare',
            'challenge', 'verification', 'robot'
        ]
        
        content_lower = response.text.lower()
        return any(indicator in content_lower for indicator in captcha_indicators)
    
    def _solve_captcha(self, response, spider) -> Optional[str]:
        """Решает CAPTCHA через внешний сервис"""
        # Базовая реализация - можно расширить для конкретных сервисов
        spider.logger.info("Решение CAPTCHA не реализовано - пропускаем")
        return None
    
    def _create_captcha_solution_request(self, original_request, solution: str):
        """Создает запрос с решением CAPTCHA"""
        # Базовая реализация - нужно адаптировать под конкретные типы CAPTCHA
        return original_request.replace(
            meta={**original_request.meta, 'captcha_solution': solution}
        )
