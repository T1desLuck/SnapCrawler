"""
Модуль автоматизированной навигации для SnapCrawler
Обрабатывает пагинацию, sitemaps, и ML-based discovery
"""
import re
import json
import asyncio
import xml.etree.ElementTree as ET
from typing import List, Dict, Set, Optional, Tuple, Any
from urllib.parse import urljoin, urlparse, parse_qs
from dataclasses import dataclass
from scrapy.http import Request
from scrapy_playwright.page import PageMethod
import logging

logger = logging.getLogger(__name__)


@dataclass
class NavigationPattern:
    """Паттерн навигации для автоматического обнаружения"""
    pattern_type: str  # 'pagination', 'infinite_scroll', 'load_more', 'sitemap'
    selectors: List[str]
    url_patterns: List[str]
    confidence: float
    metadata: Dict[str, Any]


class PaginationDetector:
    """Детектор различных типов пагинации"""
    
    def __init__(self):
        self.pagination_patterns = [
            # Классическая пагинация
            NavigationPattern(
                pattern_type='pagination',
                selectors=[
                    'a[href*="page="]',
                    'a[href*="p="]',
                    'a[href*="/page/"]',
                    '.pagination a',
                    '.pager a',
                    'nav[aria-label*="pagination"] a',
                    'a:contains("Next")',
                    'a:contains("Следующая")',
                    'a:contains(">")',
                    'a[rel="next"]'
                ],
                url_patterns=[
                    r'page=(\d+)',
                    r'p=(\d+)',
                    r'/page/(\d+)',
                    r'offset=(\d+)',
                    r'start=(\d+)'
                ],
                confidence=0.9,
                metadata={'max_pages': 100}
            ),
            
            # Infinite scroll
            NavigationPattern(
                pattern_type='infinite_scroll',
                selectors=[
                    '[data-infinite-scroll]',
                    '[data-lazy-load]',
                    '.infinite-scroll',
                    '.lazy-load-container'
                ],
                url_patterns=[
                    r'api/.*load.*more',
                    r'ajax.*page',
                    r'load.*next'
                ],
                confidence=0.8,
                metadata={'scroll_trigger': 0.8}
            ),
            
            # Load more button
            NavigationPattern(
                pattern_type='load_more',
                selectors=[
                    'button:contains("Load more")',
                    'button:contains("Show more")',
                    'button:contains("Загрузить еще")',
                    'a:contains("Load more")',
                    '.load-more',
                    '[data-load-more]'
                ],
                url_patterns=[
                    r'load.*more',
                    r'show.*more',
                    r'next.*batch'
                ],
                confidence=0.85,
                metadata={'max_clicks': 50}
            )
        ]
    
    def detect_navigation_patterns(self, response) -> List[NavigationPattern]:
        """Обнаруживает паттерны навигации на странице"""
        detected_patterns = []
        
        for pattern in self.pagination_patterns:
            confidence = self._calculate_pattern_confidence(response, pattern)
            if confidence > 0.5:
                detected_pattern = NavigationPattern(
                    pattern_type=pattern.pattern_type,
                    selectors=pattern.selectors,
                    url_patterns=pattern.url_patterns,
                    confidence=confidence,
                    metadata=pattern.metadata
                )
                detected_patterns.append(detected_pattern)
        
        return sorted(detected_patterns, key=lambda x: x.confidence, reverse=True)
    
    def _calculate_pattern_confidence(self, response, pattern: NavigationPattern) -> float:
        """Вычисляет уверенность в паттерне навигации"""
        confidence = 0.0
        
        # Проверяем селекторы
        selector_matches = 0
        for selector in pattern.selectors:
            try:
                elements = response.css(selector)
                if elements:
                    selector_matches += 1
            except:
                continue
        
        if selector_matches > 0:
            confidence += (selector_matches / len(pattern.selectors)) * 0.6
        
        # Проверяем URL паттерны
        url_matches = 0
        page_text = response.text.lower()
        for url_pattern in pattern.url_patterns:
            if re.search(url_pattern, page_text, re.IGNORECASE):
                url_matches += 1
        
        if url_matches > 0:
            confidence += (url_matches / len(pattern.url_patterns)) * 0.4
        
        return min(confidence, 1.0)


class SitemapParser:
    """Парсер XML sitemaps"""
    
    def __init__(self):
        self.sitemap_urls = [
            '/sitemap.xml',
            '/sitemap_index.xml',
            '/sitemaps.xml',
            '/sitemap/sitemap.xml',
            '/robots.txt'  # Для поиска ссылок на sitemap
        ]
    
    def discover_sitemaps(self, base_url: str) -> List[str]:
        """Обнаруживает sitemap URLs"""
        discovered_sitemaps = []
        
        for sitemap_path in self.sitemap_urls:
            sitemap_url = urljoin(base_url, sitemap_path)
            discovered_sitemaps.append(sitemap_url)
        
        return discovered_sitemaps
    
    def parse_sitemap(self, response) -> List[Dict[str, Any]]:
        """Парсит XML sitemap"""
        urls = []
        
        try:
            # Пытаемся парсить как XML
            root = ET.fromstring(response.body)
            
            # Обрабатываем sitemap index
            if 'sitemapindex' in root.tag:
                for sitemap in root.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}sitemap'):
                    loc = sitemap.find('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')
                    if loc is not None:
                        urls.append({
                            'url': loc.text,
                            'type': 'sitemap',
                            'priority': 1.0
                        })
            
            # Обрабатываем обычный sitemap
            elif 'urlset' in root.tag:
                for url_elem in root.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}url'):
                    loc = url_elem.find('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')
                    priority = url_elem.find('{http://www.sitemaps.org/schemas/sitemap/0.9}priority')
                    changefreq = url_elem.find('{http://www.sitemaps.org/schemas/sitemap/0.9}changefreq')
                    
                    if loc is not None:
                        url_data = {
                            'url': loc.text,
                            'type': 'page',
                            'priority': float(priority.text) if priority is not None else 0.5,
                            'changefreq': changefreq.text if changefreq is not None else 'unknown'
                        }
                        urls.append(url_data)
        
        except ET.ParseError:
            # Если не XML, проверяем robots.txt
            if 'robots.txt' in response.url:
                urls.extend(self._parse_robots_txt(response.text))
        
        return urls
    
    def _parse_robots_txt(self, robots_content: str) -> List[Dict[str, Any]]:
        """Извлекает sitemap URLs из robots.txt"""
        urls = []
        
        for line in robots_content.split('\n'):
            line = line.strip()
            if line.lower().startswith('sitemap:'):
                sitemap_url = line.split(':', 1)[1].strip()
                urls.append({
                    'url': sitemap_url,
                    'type': 'sitemap',
                    'priority': 1.0
                })
        
        return urls


class MLNavigationDiscovery:
    """ML-based обнаружение навигационных паттернов"""
    
    def __init__(self):
        self.link_patterns = {
            'gallery': [
                r'gallery', r'photos', r'images', r'pictures',
                r'галерея', r'фото', r'изображения'
            ],
            'category': [
                r'category', r'section', r'topic', r'tag',
                r'категория', r'раздел', r'тема', r'тег'
            ],
            'archive': [
                r'archive', r'history', r'past', r'old',
                r'архив', r'история', r'прошлое'
            ],
            'media': [
                r'media', r'multimedia', r'content',
                r'медиа', r'контент'
            ]
        }
        
        self.image_indicators = [
            r'jpg', r'jpeg', r'png', r'gif', r'webp', r'svg',
            r'photo', r'image', r'pic', r'picture',
            r'фото', r'изображение', r'картинка'
        ]
    
    def analyze_page_structure(self, response) -> Dict[str, Any]:
        """Анализирует структуру страницы для поиска навигационных паттернов"""
        analysis = {
            'navigation_links': [],
            'content_areas': [],
            'image_containers': [],
            'pagination_hints': [],
            'confidence_score': 0.0
        }
        
        # Анализируем ссылки
        links = response.css('a[href]')
        for link in links:
            href = link.attrib.get('href', '')
            text = link.css('::text').get('').strip().lower()
            
            link_analysis = self._analyze_link(href, text)
            if link_analysis['relevance'] > 0.5:
                analysis['navigation_links'].append(link_analysis)
        
        # Анализируем контейнеры изображений
        image_containers = response.css('div, section, article').getall()
        for container in image_containers[:50]:  # Ограничиваем количество
            container_analysis = self._analyze_container(container)
            if container_analysis['image_density'] > 0.3:
                analysis['image_containers'].append(container_analysis)
        
        # Вычисляем общую оценку уверенности
        analysis['confidence_score'] = self._calculate_page_confidence(analysis)
        
        return analysis
    
    def _analyze_link(self, href: str, text: str) -> Dict[str, Any]:
        """Анализирует отдельную ссылку"""
        relevance = 0.0
        link_type = 'unknown'
        
        # Проверяем паттерны в URL
        for pattern_type, patterns in self.link_patterns.items():
            for pattern in patterns:
                if re.search(pattern, href, re.IGNORECASE):
                    relevance += 0.3
                    link_type = pattern_type
                    break
        
        # Проверяем паттерны в тексте ссылки
        for pattern_type, patterns in self.link_patterns.items():
            for pattern in patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    relevance += 0.4
                    if link_type == 'unknown':
                        link_type = pattern_type
                    break
        
        # Проверяем индикаторы изображений
        for indicator in self.image_indicators:
            if re.search(indicator, href + ' ' + text, re.IGNORECASE):
                relevance += 0.3
                break
        
        return {
            'href': href,
            'text': text,
            'type': link_type,
            'relevance': min(relevance, 1.0)
        }
    
    def _analyze_container(self, container_html: str) -> Dict[str, Any]:
        """Анализирует контейнер на предмет содержания изображений"""
        # Подсчитываем изображения и ссылки
        img_count = container_html.count('<img')
        link_count = container_html.count('<a')
        total_tags = container_html.count('<')
        
        image_density = img_count / max(total_tags, 1)
        link_density = link_count / max(total_tags, 1)
        
        return {
            'image_count': img_count,
            'link_count': link_count,
            'image_density': image_density,
            'link_density': link_density,
            'relevance': image_density * 0.7 + link_density * 0.3
        }
    
    def _calculate_page_confidence(self, analysis: Dict[str, Any]) -> float:
        """Вычисляет общую уверенность в навигационной ценности страницы"""
        confidence = 0.0
        
        # Учитываем количество релевантных ссылок
        relevant_links = [link for link in analysis['navigation_links'] if link['relevance'] > 0.5]
        confidence += min(len(relevant_links) * 0.1, 0.4)
        
        # Учитываем контейнеры с изображениями
        image_containers = [c for c in analysis['image_containers'] if c['relevance'] > 0.3]
        confidence += min(len(image_containers) * 0.15, 0.6)
        
        return min(confidence, 1.0)


class AutoNavigationManager:
    """Главный менеджер автоматической навигации"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.pagination_detector = PaginationDetector()
        self.sitemap_parser = SitemapParser()
        self.ml_discovery = MLNavigationDiscovery()
        
        self.visited_urls: Set[str] = set()
        self.discovered_patterns: Dict[str, NavigationPattern] = {}
        
        # Настройки из конфига
        self.max_depth = config.get('max_depth', 5)
        self.max_pages_per_site = config.get('limits', {}).get('max_images', 1000)
        self.enable_sitemap = config.get('enable_sitemap_discovery', True)
        self.enable_ml_discovery = config.get('enable_ml_discovery', True)
    
    def generate_navigation_requests(self, response) -> List[Request]:
        """Генерирует запросы для автоматической навигации"""
        requests = []
        
        # 1. Обнаруживаем паттерны пагинации
        pagination_patterns = self.pagination_detector.detect_navigation_patterns(response)
        for pattern in pagination_patterns[:2]:  # Берем топ-2 паттерна
            pattern_requests = self._generate_pagination_requests(response, pattern)
            requests.extend(pattern_requests)
        
        # 2. Обрабатываем sitemaps
        if self.enable_sitemap and response.meta.get('depth', 0) == 0:
            sitemap_requests = self._generate_sitemap_requests(response)
            requests.extend(sitemap_requests)
        
        # 3. ML-based discovery
        if self.enable_ml_discovery:
            ml_requests = self._generate_ml_discovery_requests(response)
            requests.extend(ml_requests[:10])  # Ограничиваем количество
        
        # Фильтруем дубликаты
        unique_requests = []
        seen_urls = set()
        
        for request in requests:
            if request.url not in seen_urls and request.url not in self.visited_urls:
                unique_requests.append(request)
                seen_urls.add(request.url)
        
        return unique_requests[:20]  # Ограничиваем общее количество
    
    def _generate_pagination_requests(self, response, pattern: NavigationPattern) -> List[Request]:
        """Генерирует запросы для пагинации"""
        requests = []
        
        if pattern.pattern_type == 'pagination':
            # Классическая пагинация
            for selector in pattern.selectors:
                try:
                    links = response.css(selector)
                    for link in links[:5]:  # Ограничиваем количество
                        href = link.attrib.get('href')
                        if href:
                            url = urljoin(response.url, href)
                            request = Request(
                                url=url,
                                meta={
                                    'navigation_type': 'pagination',
                                    'depth': response.meta.get('depth', 0) + 1
                                }
                            )
                            requests.append(request)
                except:
                    continue
        
        elif pattern.pattern_type == 'infinite_scroll':
            # Infinite scroll - добавляем Playwright методы
            request = Request(
                url=response.url,
                meta={
                    'playwright': True,
                    'playwright_page_methods': self._get_infinite_scroll_methods(),
                    'navigation_type': 'infinite_scroll',
                    'depth': response.meta.get('depth', 0)
                }
            )
            requests.append(request)
        
        elif pattern.pattern_type == 'load_more':
            # Load more button
            request = Request(
                url=response.url,
                meta={
                    'playwright': True,
                    'playwright_page_methods': self._get_load_more_methods(pattern),
                    'navigation_type': 'load_more',
                    'depth': response.meta.get('depth', 0)
                }
            )
            requests.append(request)
        
        return requests
    
    def _generate_sitemap_requests(self, response) -> List[Request]:
        """Генерирует запросы для sitemaps"""
        requests = []
        
        base_url = f"{urlparse(response.url).scheme}://{urlparse(response.url).netloc}"
        sitemap_urls = self.sitemap_parser.discover_sitemaps(base_url)
        
        for sitemap_url in sitemap_urls:
            request = Request(
                url=sitemap_url,
                callback=self._parse_sitemap_response,
                meta={
                    'navigation_type': 'sitemap',
                    'depth': 0
                }
            )
            requests.append(request)
        
        return requests
    
    def _generate_ml_discovery_requests(self, response) -> List[Request]:
        """Генерирует запросы на основе ML анализа"""
        requests = []
        
        analysis = self.ml_discovery.analyze_page_structure(response)
        
        # Генерируем запросы для релевантных ссылок
        for link_data in analysis['navigation_links']:
            if link_data['relevance'] > 0.6:
                url = urljoin(response.url, link_data['href'])
                request = Request(
                    url=url,
                    meta={
                        'navigation_type': 'ml_discovery',
                        'link_type': link_data['type'],
                        'confidence': link_data['relevance'],
                        'depth': response.meta.get('depth', 0) + 1
                    }
                )
                requests.append(request)
        
        return requests
    
    def _get_infinite_scroll_methods(self) -> List[PageMethod]:
        """Playwright методы для infinite scroll"""
        return [
            PageMethod('evaluate', '''
                async () => {
                    let totalHeight = 0;
                    const distance = 100;
                    const maxScrolls = 20;
                    let scrollCount = 0;
                    
                    while (scrollCount < maxScrolls) {
                        const scrollHeight = document.body.scrollHeight;
                        window.scrollBy(0, distance);
                        totalHeight += distance;
                        
                        if (totalHeight >= scrollHeight) {
                            break;
                        }
                        
                        await new Promise(resolve => setTimeout(resolve, 500));
                        scrollCount++;
                    }
                }
            '''),
            PageMethod('wait_for_timeout', self.config.get('crawling', {}).get('timeouts', {}).get('navigation_timeout', 2000)),
        ]
    
    def _get_load_more_methods(self, pattern: NavigationPattern) -> List[PageMethod]:
        """Playwright методы для load more buttons"""
        methods = []
        
        for selector in pattern.selectors:
            methods.append(PageMethod('evaluate', f'''
                async () => {{
                    const buttons = document.querySelectorAll('{selector}');
                    const maxClicks = {pattern.metadata.get('max_clicks', 10)};
                    let clickCount = 0;
                    
                    for (const button of buttons) {{
                        if (clickCount >= maxClicks) break;
                        
                        if (button && button.offsetParent !== null) {{
                            button.scrollIntoView();
                            const waitTime = {self.config.get('crawling', {}).get('delays', {}).get('load_more_wait', 1000)};
                            await new Promise(resolve => setTimeout(resolve, waitTime));
                            button.click();
                            const pauseTime = {self.config.get('crawling', {}).get('delays', {}).get('load_more_pause', 2000)};
                            await new Promise(resolve => setTimeout(resolve, pauseTime));
                            clickCount++;
                        }}
                    }}
                }}
            '''))
        
        methods.append(PageMethod('wait_for_timeout', self.config.get('crawling', {}).get('timeouts', {}).get('load_more_timeout', 3000)))
        return methods
    
    def _parse_sitemap_response(self, response):
        """Обрабатывает ответ sitemap"""
        urls = self.sitemap_parser.parse_sitemap(response)
        
        for url_data in urls:
            if url_data['type'] == 'page' and url_data['priority'] > 0.3:
                yield Request(
                    url=url_data['url'],
                    meta={
                        'navigation_type': 'sitemap_page',
                        'priority': url_data['priority'],
                        'depth': 1
                    }
                )
            elif url_data['type'] == 'sitemap':
                yield Request(
                    url=url_data['url'],
                    callback=self._parse_sitemap_response,
                    meta={
                        'navigation_type': 'sitemap',
                        'depth': 0
                    }
                )
