"""
Модуль для эмуляции человеческого поведения в браузере
"""

from typing import Dict, Any, List
from dataclasses import dataclass
from scrapy_playwright.page import PageMethod


@dataclass
class HumanEmulationConfig:
    """Конфигурация эмуляции человеческого поведения"""
    enabled: bool = True
    scroll_speed: int = 1000  # пикселей в секунду
    click_delay: List[float] = None  # диапазон задержек для кликов
    max_interactions: int = 100
    scroll_pause_time: float = 3.0
    max_scroll_attempts: int = 15
    
    def __post_init__(self):
        if self.click_delay is None:
            self.click_delay = [1.0, 3.0]


class HumanEmulationModule:
    """Модуль для эмуляции человеческого поведения в браузере"""
    
    def __init__(self, config: Dict[str, Any]):
        # Получаем конфигурацию с учетом полной структуры
        full_config = config if config else {}
        human_config = config.get('human_emulation', {}) if config else {}
        
        self.config = HumanEmulationConfig(
            enabled=human_config.get('enabled', True),
            scroll_speed=human_config.get('scroll_speed', 1000),
            click_delay=human_config.get('click_delay', [1.0, 3.0]),
            max_interactions=human_config.get('max_interactions', 50),
            scroll_pause_time=human_config.get('scroll_pause_time', 2.0),
            max_scroll_attempts=human_config.get('max_scroll_attempts', 10)
        )
        
        # Сохраняем полную конфигурацию для доступа к таймаутам
        self.full_config = full_config
    
    def get_page_methods(self) -> List[PageMethod]:
        """Возвращает список PageMethod для Playwright"""
        if not self.config.enabled:
            return []
        
        return [
            # Инициализация эмуляции
            PageMethod('evaluate', self._get_emulation_script()),
            
            # Ожидание загрузки страницы
            PageMethod('wait_for_timeout', self.full_config.get('crawling', {}).get('timeouts', {}).get('page_load_timeout', 2000)),
            
            # Выполнение человеческих взаимодействий
            PageMethod('evaluate', self._get_interaction_script()),
            
            # Ожидание стабилизации DOM
            PageMethod('wait_for_timeout', self.full_config.get('crawling', {}).get('timeouts', {}).get('dom_stabilization_timeout', 3000)),
            
            # Финальный сбор данных
            PageMethod('evaluate', self._get_collection_script()),
        ]
    
    def _get_emulation_script(self) -> str:
        """JavaScript для инициализации эмуляции человеческого поведения"""
        return """
        () => {
            window.humanEmulation = {
                enabled: true,
                scrollSpeed: 1000,
                maxInteractions: 50,
                scrollPauseTime: 2000,
                interactions: 0,
                discoveredImages: new Set()
            };
            
            window.randomDelay = (min, max) => {
                return new Promise(resolve => {
                    const delay = Math.random() * (max - min) + min;
                    setTimeout(resolve, delay * 1000);
                });
            };
            
            console.log('Human emulation initialized');
        }
        """
    
    def _get_interaction_script(self) -> str:
        """JavaScript для выполнения человеческих взаимодействий"""
        return """
        async () => {
            const emulation = window.humanEmulation;
            
            // Простой скролл вниз
            for (let i = 0; i < 3 && emulation.interactions < emulation.maxInteractions; i++) {
                window.scrollBy(0, 400);
                await window.randomDelay(1, 2);
                emulation.interactions++;
            }
            
            console.log('Human interactions completed:', emulation.interactions);
        }
        """
    
    def _get_collection_script(self) -> str:
        """JavaScript для сбора обнаруженных изображений"""
        return """
        () => {
            const discoveredImages = Array.from(window.humanEmulation.discoveredImages || []);
            
            return {
                humanEmulationImages: discoveredImages,
                shadowDomImages: [],
                canvasImages: [],
                totalInteractions: window.humanEmulation.interactions
            };
        }
        """


class NetworkTrafficCapture:
    """Модуль для захвата сетевого трафика и извлечения URL изображений"""
    
    def __init__(self, config: Dict[str, Any]):
        network_config = config.get('network_capture', {}) if config else {}
        
        self.enabled = network_config.get('enabled', True)
        self.capture_json = network_config.get('capture_json', True)
        self.capture_websockets = network_config.get('capture_websockets', False)
        self.image_domains = network_config.get('image_domains', [])
        
        # Сохраняем полную конфигурацию для доступа к таймаутам
        self.full_config = config if config else {}
    
    def get_page_methods(self) -> List[PageMethod]:
        """Возвращает список PageMethod для Playwright"""
        if not self.enabled:
            return []
        
        return [
            # Настройка захвата трафика
            PageMethod('evaluate', self._get_network_setup_script()),
            
            # Ожидание активности
            PageMethod('wait_for_timeout', self.full_config.get('crawling', {}).get('timeouts', {}).get('network_activity_timeout', 5000)),
            
            # Сбор данных трафика
            PageMethod('evaluate', self._get_network_collection_script()),
        ]
    
    def _get_network_setup_script(self) -> str:
        """JavaScript для настройки захвата сетевого трафика"""
        return """
        () => {
            window.networkCapture = {
                imageUrls: new Set(),
                apiResponses: [],
                websocketMessages: []
            };
            
            console.log('Network capture initialized');
        }
        """
    
    def _get_network_collection_script(self) -> str:
        """JavaScript для сбора данных сетевого трафика"""
        return """
        () => {
            const capturedData = window.networkCapture || {
                imageUrls: new Set(),
                apiResponses: [],
                websocketMessages: []
            };
            
            return {
                networkImageUrls: Array.from(capturedData.imageUrls),
                apiImageUrls: capturedData.apiResponses.flatMap(response => response.imageUrls || []),
                websocketImageUrls: capturedData.websocketMessages.flatMap(msg => msg.imageUrls || []),
                totalApiResponses: capturedData.apiResponses.length,
                totalWebsocketMessages: capturedData.websocketMessages.length
            };
        }
        """


class HiddenImageExtractor:
    """Модуль для извлечения скрытых изображений"""
    
    def __init__(self, config: Dict[str, Any]):
        # Получаем конфигурацию для скрытых изображений
        hidden_config = config.get('hidden_images', {}) if config else {}
        
        self.enabled = hidden_config.get('enabled', True)
        self.extract_base64 = hidden_config.get('extract_base64', True)
        self.extract_canvas = hidden_config.get('extract_canvas', True)
        self.extract_webgl = hidden_config.get('extract_webgl', False)
        self.extract_shadow_dom = hidden_config.get('extract_shadow_dom', True)
        
        # Сохраняем полную конфигурацию для доступа к таймаутам
        self.full_config = config if config else {}

    def get_page_methods(self) -> List[PageMethod]:
        """Возвращает список PageMethod для Playwright"""
        if not self.enabled:
            return []
        
        return [
            # Извлечение скрытых изображений
            PageMethod('evaluate', self._get_hidden_extraction_script()),
            
            # Ожидание обработки
            PageMethod('wait_for_timeout', self.full_config.get('crawling', {}).get('timeouts', {}).get('hidden_processing_timeout', 2000)),
            
            # Сбор результатов
            PageMethod('evaluate', self._get_hidden_collection_script()),
        ]
    
    def _get_hidden_extraction_script(self) -> str:
        """JavaScript для извлечения скрытых изображений"""
        return """
        () => {
            window.hiddenImageExtraction = {
                base64Images: [],
                canvasImages: [],
                webglImages: [],
                shadowDomImages: []
            };
            
            // Простое извлечение base64 изображений
            const dataUriElements = document.querySelectorAll('[src^="data:image"]');
            dataUriElements.forEach(el => {
                if (el.src) {
                    window.hiddenImageExtraction.base64Images.push(el.src);
                }
            });
            
            // Простое извлечение из canvas
            const canvases = document.querySelectorAll('canvas');
            canvases.forEach(canvas => {
                try {
                    const dataUrl = canvas.toDataURL('image/png');
                    if (dataUrl && dataUrl !== 'data:,') {
                        window.hiddenImageExtraction.canvasImages.push(dataUrl);
                    }
                } catch (e) {
                    // Canvas может быть tainted
                }
            });
            
            console.log('Hidden image extraction completed');
        }
        """
    
    def _get_hidden_collection_script(self) -> str:
        """JavaScript для сбора скрытых изображений"""
        return """
        () => {
            const hiddenData = window.hiddenImageExtraction || {
                base64Images: [],
                canvasImages: [],
                webglImages: [],
                shadowDomImages: []
            };
            
            return {
                base64Images: hiddenData.base64Images,
                canvasImages: hiddenData.canvasImages,
                webglImages: hiddenData.webglImages,
                shadowDomImages: hiddenData.shadowDomImages,
                totalHiddenImages: hiddenData.base64Images.length + 
                                 hiddenData.canvasImages.length + 
                                 hiddenData.webglImages.length + 
                                 hiddenData.shadowDomImages.length
            };
        }
        """
