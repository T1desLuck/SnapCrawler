"""
Модуль обхода (Crawling Module) — отвечает за обнаружение URL и обход страниц
Часть параллельной архитектуры, определённой в ТЗ
"""
import asyncio
import multiprocessing
import queue
import time
import logging
import hashlib
from dataclasses import dataclass, field
from urllib.parse import urlparse, urljoin
from typing import Set, Dict, List, Optional
import requests
from bs4 import BeautifulSoup
import yaml
import os

@dataclass
class CrawlingModule:
    """Модуль обхода сайтов для параллельной архитектуры"""
    config: dict
    image_queue: multiprocessing.Queue
    stats_queue: multiprocessing.Queue
    visited_urls: dict = field(default_factory=dict)
    page_hashes: set = field(default_factory=set)
    urls_by_depth: dict = field(default_factory=dict)

    def __post_init__(self):
        if isinstance(self.config, str):
            with open(self.config, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f)
        
        self.crawling_config = self.config['crawling']
        self.limits = self.config['limits']
        
        self.shared_queue = self.image_queue  # Очередь для найденных изображений
        # visited_urls, page_hashes, urls_by_depth уже переданы как параметры
        self.stats_queue = self.stats_queue    # Очередь для статистики
        
        self.session = requests.Session()
        self.setup_session()
        
        self.logger = logging.getLogger('crawling_module')
        self.pages_crawled = 0
        self.images_found = 0
        
    def setup_session(self):
        """Настройка сессии requests с базовыми анти-скрейпинг заголовками"""
        if self.crawling_config.get('stealth_mode'):
            user_agents = self.crawling_config.get('user_agents', [])
            if user_agents:
                import random
                self.session.headers.update({
                    'User-Agent': random.choice(user_agents)
                })
        
        # Устанавливаем типичные заголовки браузера
        default_user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        
        self.session.headers.update({
            'User-Agent': self.session.headers.get('User-Agent', default_user_agent),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,ru;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0'
        })
    
    def run(self):
        """Основной цикл обхода — реализация стратегии «роста дерева»"""
        start_urls = self.crawling_config['start_urls']
        max_depth = self.crawling_config.get('max_depth', 0)
        max_requests = self.crawling_config.get('max_requests', 0)
        
        self.logger.info(f"Запуск модуля обхода, стартовых URL: {len(start_urls)}")
        
        # Инициализируем очередь URL стартовыми адресами
        url_queue = []
        for url in start_urls:
            url_queue.append((url, 0))  # (url, глубина)
            self.visited_urls[url] = True
        
        request_count = 0
        
        while url_queue and (max_requests == 0 or request_count < max_requests):
            current_url, depth = url_queue.pop(0)
            
            if max_depth > 0 and depth >= max_depth:
                continue
            
            try:
                # Устанавливаем текущую глубину для add_image_page_to_queue
                self.current_depth = depth
                
                # Обходим страницу и извлекаем изображения/ссылки
                images, new_links = self.crawl_page(current_url)
                
                # Отправляем найденные изображения в модуль фильтрации
                for img_url in images:
                    self.image_queue.put({
                        'type': 'image_url',
                        'url': img_url,
                        'source_page': current_url,
                        'depth': depth
                    })
                    self.images_found += 1
                
                # Встраиваем отложенные страницы изображений для этой глубины
                try:
                    cascade_links = list(self.urls_by_depth.get(depth, []))
                except Exception:
                    cascade_links = []
                if cascade_links:
                    self.logger.debug(
                        f"Вставляю {len(cascade_links)} каскадных страниц изображений на глубине {depth}"
                    )
                    # Немедленно поставить их в очередь на той же глубине
                    for link in cascade_links:
                        if link not in self.visited_urls:
                            url_queue.insert(0, (link, depth))
                            self.visited_urls[link] = True
                    # Очистить использованные записи, чтобы избежать повторов
                    try:
                        self.urls_by_depth[depth] = []
                    except Exception:
                        pass
                
                # Добавляем новые ссылки в очередь для «роста дерева»
                new_links_added = 0
                for link in new_links:
                    if link not in self.visited_urls:
                        url_queue.append((link, depth + 1))
                        self.visited_urls[link] = True
                        new_links_added += 1
                
                self.pages_crawled += 1
                request_count += 1
                
                # Отправляем статистику
                self.stats_queue.put({
                    'type': 'crawling_stats',
                    'pages_crawled': self.pages_crawled,
                    'images_found': self.images_found,
                    'depth': depth,
                    'new_links_added': new_links_added,
                    'queue_size': len(url_queue)
                })
                
                # Условие завершения «роста дерева»: на этой глубине нет новых ссылок
                if new_links_added == 0 and depth > 0:
                    self.logger.info(f"Новых ссылок на глубине {depth} не найдено — вероятно, рост дерева завершён")
                
                # Соблюдаем задержку между запросами
                delay = self.crawling_config.get('request_delay', 1.0)
                time.sleep(delay)
                
            except Exception as e:
                self.logger.error(f"Ошибка при обходе {current_url}: {e}")
                continue
        
        # Сигнализируем о завершении
        self.image_queue.put({'type': 'crawling_complete'})
        self.logger.info(f"Обход завершён. Страниц: {self.pages_crawled}, Изображений: {self.images_found}")
    
    def crawl_page(self, url: str) -> tuple[List[str], List[str]]:
        """
        Обходит одну страницу и извлекает изображения и ссылки
        Возвращает: (список URL изображений, список ссылок страницы)
        """
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Проверяем страницу на дубликаты
            page_hash = hashlib.md5(response.text.encode('utf-8')).hexdigest()
            if page_hash in self.page_hashes:
                self.logger.info(f"Обнаружен дубликат страницы, пропускаем: {url}")
                return [], []
            
            # Поддержка как list-прокси Manager, так и обычного set в юнитах
            try:
                adder = self.page_hashes.add  # type: ignore[attr-defined]
            except Exception:
                adder = None
            if adder:
                adder(page_hash)
            else:
                # fallback для list-прокси
                try:
                    self.page_hashes.append(page_hash)
                except Exception:
                    pass
            
            images = self.extract_images(soup, url)
            
            # Извлекаем ссылки для «роста дерева»
            links = self.extract_links(soup, url)
            
            return images, links
            
        except Exception as e:
            self.logger.error(f"Не удалось обойти {url}: {e}")
            return [], []
    
    def extract_images(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        """Извлекает все URL изображений со страницы"""
        images = []
        
        # Стандартные теги <img>
        for img in soup.find_all('img'):
            # Прямые ссылки на изображения
            src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
            if src:
                absolute_url = urljoin(base_url, src)
                if self.is_valid_image_url(absolute_url):
                    images.append(absolute_url)
            
            # Поиск ссылок на полноразмерные версии
            parent_a = img.find_parent('a')
            if parent_a and parent_a.get('href'):
                href = parent_a.get('href')
                absolute_href = urljoin(base_url, href)
                
                # Если ссылка ведет на изображение - добавляем
                if self.is_valid_image_url(absolute_href):
                    images.append(absolute_href)
                # Если ссылка ведет на страницу изображения - добавляем в очередь обхода
                elif self.is_image_page_url(absolute_href, base_url):
                    self.add_image_page_to_queue(absolute_href)
        
        # Wikimedia Commons специальные атрибуты
        for element in soup.find_all(attrs={'data-file-url': True}):
            file_url = element.get('data-file-url')
            if file_url:
                absolute_url = urljoin(base_url, file_url)
                if self.is_valid_image_url(absolute_url):
                    images.append(absolute_url)
        
        # Фоновые изображения из CSS
        for element in soup.find_all(style=True):
            style = element.get('style', '')
            import re
            urls = re.findall(r'url\(["\']?([^"\']+)["\']?\)', style)
            for url in urls:
                absolute_url = urljoin(base_url, url)
                if self.is_valid_image_url(absolute_url):
                    images.append(absolute_url)
        
        # Теги <style>
        for style_tag in soup.find_all('style'):
            if style_tag.string:
                import re
                urls = re.findall(r'url\(["\']?([^"\']+)["\']?\)', style_tag.string)
                for url in urls:
                    absolute_url = urljoin(base_url, url)
                    if self.is_valid_image_url(absolute_url):
                        images.append(absolute_url)
        
        return list(set(images))  # Удаляем дубликаты
    
    def is_image_page_url(self, url: str, base_url: str) -> bool:
        """Определяет, является ли URL страницей изображения"""
        # Wikimedia Commons паттерны
        if 'commons.wikimedia.org' in base_url:
            return ('/wiki/File:' in url or '/wiki/Category:' in url)
        
        # Общие паттерны страниц изображений
        image_page_patterns = [
            '/image/', '/photo/', '/picture/', '/img/', '/gallery/',
            'image_id=', 'photo_id=', 'picture_id='
        ]
        return any(pattern in url.lower() for pattern in image_page_patterns)
    
    def add_image_page_to_queue(self, url: str):
        """Добавляет страницу изображения в очередь для дальнейшего обхода"""
        if url not in self.visited_urls:
            # Добавляем в текущую глубину для немедленной обработки
            current_depth = getattr(self, 'current_depth', 0)
            if current_depth not in self.urls_by_depth:
                self.urls_by_depth[current_depth] = []
            self.urls_by_depth[current_depth].append(url)
            self.logger.debug(f"Добавлена страница изображения в очередь: {url}")
    
    def extract_links(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        """Извлекает все навигационные ссылки для «роста дерева»"""
        links = []
        allowed_domains = [urlparse(url).netloc for url in self.crawling_config['start_urls']]
        
        for a_tag in soup.find_all('a', href=True):
            href = a_tag.get('href')
            if href:
                absolute_url = urljoin(base_url, href)
                parsed = urlparse(absolute_url)
                
                # Фильтр: тот же домен и подходящая схема
                if (parsed.netloc in allowed_domains and 
                    parsed.scheme in ['http', 'https'] and
                    absolute_url not in self.visited_urls):
                    links.append(absolute_url)
        
        return links
    
    def is_valid_image_url(self, url: str) -> bool:
        """Проверяет, указывает ли URL на изображение"""
        image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp', '.tiff', '.ico']
        url_lower = url.lower()
        
        # Прямые расширения
        if any(url_lower.endswith(ext) for ext in image_extensions):
            return True
            
        # Wikimedia Commons специальные URL
        if 'commons.wikimedia.org' in url and '/thumb/' in url:
            return True
            
        # Исключаем явно не-изображения
        exclude_patterns = ['.css', '.js', '.html', '.php', '.xml', '.json']
        if any(pattern in url_lower for pattern in exclude_patterns):
            return False
            
        return False


def run_crawling_module(config, image_queue, stats_queue, shutdown_event=None):
    """Точка входа для процесса обхода"""
    # Создаем shared objects внутри процесса
    manager = multiprocessing.Manager()
    
    module = CrawlingModule(
        config=config,
        image_queue=image_queue,
        stats_queue=stats_queue,
        visited_urls=manager.dict(),
        page_hashes=manager.list(),  # Используем list вместо set
        urls_by_depth=manager.dict()
    )
    module.run()
