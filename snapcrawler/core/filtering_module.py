"""
Модуль фильтрации (Filtering Module) — отвечает за скачивание и фильтрацию изображений
Часть параллельной архитектуры, определённой в ТЗ
"""
import multiprocessing
import queue
import time
import logging
import os
import requests
from PIL import Image
import imagehash
import cv2
import numpy as np
import yaml
from typing import Set, Dict, List
from urllib.parse import urlparse
import re

class FilteringModule:
    """
    Независимый модуль, который скачивает и фильтрует изображения
    Запускается параллельно с CrawlingModule через multiprocessing
    """
    
    def __init__(self, config_path: str, shared_queue: multiprocessing.Queue,
                 stats_queue: multiprocessing.Queue):
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)
        
        self.filtering_config = self.config['images']
        self.limits = self.config['limits']
        self.output_dir = self.config['general']['output_dir']
        
        self.shared_queue = shared_queue  # Очередь изображений от модуля обхода
        self.stats_queue = stats_queue    # Очередь статистики
        
        self.session = requests.Session()
        # Настройка User-Agent для обхода блокировок
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'image',
            'Sec-Fetch-Mode': 'no-cors',
            'Sec-Fetch-Site': 'cross-site'
        })
        self.image_hashes = set()  # Для обнаружения дубликатов
        
        # Подготовка директорий
        self.raw_dir = os.path.join(self.output_dir, 'raw')
        self.processed_dir = os.path.join(self.output_dir, 'processed')
        os.makedirs(self.raw_dir, exist_ok=True)
        os.makedirs(self.processed_dir, exist_ok=True)
        
        # Учёт ресурсов
        self.max_folder_size_bytes = self.limits.get('max_folder_size_mb', 0) * 1024 * 1024
        self.max_images = self.limits.get('max_images', 0)
        self.current_folder_size = self.get_folder_size(self.processed_dir)
        self.processed_count = 0
        self.downloaded_count = 0
        self.filtered_count = 0
        
        self.logger = logging.getLogger('filtering_module')
    
    def get_folder_size(self, folder_path: str) -> int:
        """Подсчёт общего размера папки в байтах"""
        total_size = 0
        try:
            for dirpath, dirnames, filenames in os.walk(folder_path):
                for filename in filenames:
                    filepath = os.path.join(dirpath, filename)
                    if os.path.isfile(filepath):
                        total_size += os.path.getsize(filepath)
        except OSError:
            pass
        return total_size
    
    def run(self):
        """Основной цикл фильтрации — обрабатывает изображения из модуля обхода"""
        self.logger.info("Запуск модуля фильтрации")
        
        while True:
            try:
                # Получаем элемент из очереди (блокирующе, с таймаутом)
                try:
                    item = self.shared_queue.get(timeout=30)
                except queue.Empty:
                    continue
                
                if item.get('type') == 'crawling_complete':
                    self.logger.info("Получен сигнал завершения обхода")
                    break
                
                if item.get('type') == 'image_url':
                    self.process_image(item)
                
                # Проверяем лимиты
                if self.max_images > 0 and self.processed_count >= self.max_images:
                    self.logger.info(f"Достигнут лимит по количеству изображений: {self.max_images}")
                    break
                
                if (self.max_folder_size_bytes > 0 and 
                    self.current_folder_size >= self.max_folder_size_bytes):
                    self.logger.info(f"Достигнут лимит размера папки: {self.max_folder_size_bytes/1024/1024:.1f}MB")
                    break
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.logger.error(f"Ошибка в цикле фильтрации: {e}")
                continue
        
        self.logger.info(f"Фильтрация завершена. Скачано: {self.downloaded_count}, "
                        f"Обработано: {self.processed_count}, Отфильтровано: {self.filtered_count}")
    
    def process_image(self, item: Dict):
        """Скачивание и фильтрация одного изображения"""
        image_url = item['url']
        source_page = item.get('source_page', '')
        
        try:
            # Скачиваем изображение
            raw_path = self.download_image(image_url)
            if not raw_path:
                return
            
            self.downloaded_count += 1
            
            # Применяем все фильтры
            if self.apply_filters(raw_path):
                # Перемещаем в папку processed
                filename = os.path.basename(raw_path)
                processed_path = os.path.join(self.processed_dir, filename)
                os.rename(raw_path, processed_path)
                
                # Обновляем статистику
                file_size = os.path.getsize(processed_path)
                self.current_folder_size += file_size
                self.processed_count += 1
                
                self.logger.info(f"Изображение обработано: {filename}")
                
                # Отправляем статистику
                self.stats_queue.put({
                    'type': 'filtering_stats',
                    'downloaded': self.downloaded_count,
                    'processed': self.processed_count,
                    'filtered_out': self.filtered_count,
                    'folder_size_mb': self.current_folder_size / 1024 / 1024
                })
            else:
                # Удаляем не прошедшее изображение
                self.safe_remove_file(raw_path)
                self.filtered_count += 1
                
        except Exception as e:
            self.logger.error(f"Ошибка при обработке изображения {image_url}: {e}")
    
    def download_image(self, url: str) -> str:
        """Скачивание изображения в папку raw"""
        try:
            response = self.session.get(url, timeout=30, stream=True)
            response.raise_for_status()
            # Проверяем, что получаем именно изображение
            content_type = response.headers.get('Content-Type', '')
            if 'image' not in content_type.lower():
                self.logger.debug(f"Пропущено (не image Content-Type): {url} -> {content_type}")
                return None
            
            # Формируем имя файла по URL
            parsed = urlparse(url)
            filename = os.path.basename(parsed.path)
            if not filename or '.' not in filename:
                filename = f"image_{hash(url) % 1000000}.jpg"
            # Санитизируем имя файла для совместимости с ОС (Windows и др.)
            filename = self._sanitize_filename(filename)

            raw_path = os.path.join(self.raw_dir, filename)
            
            # Обработка коллизий имён файлов
            counter = 1
            base_name, ext = os.path.splitext(raw_path)
            while os.path.exists(raw_path):
                raw_path = f"{base_name}_{counter}{ext}"
                counter += 1
            
            # Скачиваем файл
            with open(raw_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            return raw_path
            
        except Exception as e:
            self.logger.error(f"Не удалось скачать {url}: {e}")
            return None

    def _sanitize_filename(self, name: str) -> str:
        """Заменяет недопустимые символы в имени файла безопасными подчеркиваниями"""
        # Недопустимые для Windows: < > : " / \ | ? * и управляющие
        name = re.sub(r'[<>:"/\\|?*\x00-\x1F]', '_', name)
        # Ограничим длину до разумной (например, 200 символов)
        return name[:200]
    
    def apply_filters(self, image_path: str) -> bool:
        """Применяет все фильтры. Возвращает True, если изображение прошло все проверки"""
        try:
            # Проверка на SVG и конвертация при необходимости
            if image_path.lower().endswith('.svg'):
                try:
                    from ..utils.svg_processor import convert_svg_to_png
                    png_path = convert_svg_to_png(image_path)
                    if png_path:
                        # Заменяем SVG на PNG
                        os.remove(image_path)
                        os.rename(png_path, image_path.replace('.svg', '.png'))
                        image_path = image_path.replace('.svg', '.png')
                    else:
                        return False  # SVG не удалось конвертировать
                except ImportError:
                    return False  # SVG процессор недоступен
            
            img = Image.open(image_path)
            
            filename = os.path.basename(image_path)
            
            # Фильтр размера
            if not self.is_valid_size(img):
                min_side = self.filtering_config.get('min_side_size', 0)
                self.logger.debug(f"❌ [{filename}] Размер {img.size}, требуется мин. сторона {min_side}px")
                return False
            
            # Фильтр формата
            if not self.is_valid_format(image_path):
                allowed = self.filtering_config.get('formats', [])
                ext = os.path.splitext(image_path)[1]
                self.logger.info(f"❌ [{filename}] Формат {ext}, разрешены: {allowed}")
                return False
            
            # Фильтр DPI
            if not self.is_valid_dpi(img):
                min_dpi = self.filtering_config.get('min_dpi', 0)
                actual_dpi = img.info.get('dpi', 'неизвестно')
                self.logger.info(f"❌ [{filename}] DPI {actual_dpi}, требуется мин. {min_dpi}")
                return False
            
            # Фильтр цветового режима
            if not self.is_valid_color_mode(img):
                color_mode = self.filtering_config.get('color_mode', 'all')
                self.logger.info(f"❌ [{filename}] Режим {img.mode}, требуется: {color_mode}")
                return False
            
            # Фильтр ориентации
            if not self.is_valid_orientation(img):
                orientation = self.filtering_config.get('orientation', 'all')
                self.logger.info(f"❌ [{filename}] Размер {img.size}, требуется: {orientation}")
                return False
            
            # Фильтр диапазона соотношения сторон
            if not self.is_valid_aspect_ratio_range(img):
                ratio = img.size[0]/img.size[1] if img.size[1] > 0 else 1
                min_r = self.filtering_config.get('aspect_ratio_min', 0)
                max_r = self.filtering_config.get('aspect_ratio_max', 0)
                self.logger.info(f"❌ [{filename}] Соотношение {ratio:.2f}, диапазон: {min_r}-{max_r}")
                return False
            
            # Фильтр дубликатов
            if self.is_duplicate(img):
                self.logger.info(f"❌ [{filename}] Дубликат по perceptual hash")
                return False
            
            # Фильтр водяных знаков
            if self.has_watermark(image_path):
                sensitivity = self.filtering_config.get('watermark_sensitivity', 50)
                self.logger.info(f"❌ [{filename}] Водяной знак (чувствительность: {sensitivity})")
                return False
            
            # Фильтр баннеров/логотипов
            if not self.is_valid_aspect_ratio(img):
                ratio = img.size[0]/img.size[1] if img.size[1] > 0 else 1
                self.logger.info(f"❌ [{filename}] Баннер/логотип, соотношение: {ratio:.2f}")
                return False
            
            self.logger.info(f"✅ [{filename}] Прошел все фильтры: {img.size}, {img.mode}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Ошибка при применении фильтров к {image_path}: {e}")
            return False
    
    def is_valid_size(self, img: Image.Image) -> bool:
        """Проверка минимального размера"""
        min_side = self.filtering_config.get('min_side_size', 0)
        if min_side <= 0:
            return True
        width, height = img.size
        return min(width, height) >= min_side
    
    def is_valid_format(self, image_path: str) -> bool:
        """Проверка допустимого формата изображения"""
        allowed_formats = self.filtering_config.get('formats', [])
        if not allowed_formats:
            return True
        file_ext = os.path.splitext(image_path)[1].lower().lstrip('.')
        return file_ext in [fmt.lower() for fmt in allowed_formats]
    
    def is_valid_dpi(self, img: Image.Image) -> bool:
        """Проверка минимального DPI"""
        min_dpi = self.filtering_config.get('min_dpi', 0)
        if min_dpi <= 0:
            return True
        try:
            dpi = img.info.get('dpi')
            if dpi:
                actual_dpi = min(dpi) if isinstance(dpi, tuple) else dpi
                return actual_dpi >= min_dpi
        except:
            pass
        return True
    
    def is_valid_color_mode(self, img: Image.Image) -> bool:
        """Проверка цветового режима"""
        color_mode = self.filtering_config.get('color_mode', 'all')
        if color_mode == 'all':
            return True
        is_grayscale = img.mode == 'L'
        if color_mode == 'color' and is_grayscale:
            return False
        if color_mode == 'bw' and not is_grayscale:
            return False
        return True
    
    def is_valid_orientation(self, img: Image.Image) -> bool:
        """Проверка ориентации"""
        orientation = self.filtering_config.get('orientation', 'all')
        if orientation == 'all':
            return True
        width, height = img.size
        if orientation == 'landscape' and width < height:
            return False
        if orientation == 'portrait' and height < width:
            return False
        if orientation == 'square' and width != height:
            return False
        return True
    
    def is_valid_aspect_ratio_range(self, img: Image.Image) -> bool:
        """Проверка диапазона соотношения сторон"""
        min_ratio = self.filtering_config.get('aspect_ratio_min', 0.0)
        max_ratio = self.filtering_config.get('aspect_ratio_max', 0.0)
        if min_ratio <= 0 and max_ratio <= 0:
            return True
        width, height = img.size
        aspect_ratio = width / height if height > 0 else 1
        if min_ratio > 0 and aspect_ratio < min_ratio:
            return False
        if max_ratio > 0 and aspect_ratio > max_ratio:
            return False
        return True
    
    def is_duplicate(self, img: Image.Image) -> bool:
        """Проверка дубликатов с использованием перцептивного хеша"""
        if not self.filtering_config.get('deduplication', True):
            return False
        img_hash = imagehash.phash(img)
        if img_hash in self.image_hashes:
            return True
        self.image_hashes.add(img_hash)
        return False
    
    def has_watermark(self, image_path: str) -> bool:
        """Детектирование водяных знаков с помощью OpenCV"""
        if self.filtering_config.get('allow_watermarks', True):
            return False
        try:
            cv_img = cv2.imread(image_path)
            if cv_img is None:
                return False
            gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
            mser = cv2.MSER_create()
            regions, _ = mser.detectRegions(gray)
            sensitivity = self.filtering_config.get('watermark_sensitivity', 50)
            return len(regions) > sensitivity
        except:
            return False
    
    def is_valid_aspect_ratio(self, img: Image.Image) -> bool:
        """Проверка баннеров/логотипов по экстремальным соотношениям сторон"""
        if self.filtering_config.get('allow_logos_banners', True):
            return True
        width, height = img.size
        aspect_ratio = width / height if height > 0 else 1
        # Отсекаем экстремальные соотношения (баннеры/логотипы)
        return not (aspect_ratio > 10 or aspect_ratio < 0.1)
    
    def safe_remove_file(self, file_path: str):
        """Безопасное удаление файла с обработкой ошибок"""
        try:
            if os.path.exists(file_path):
                os.chmod(file_path, 0o777)
                os.remove(file_path)
        except (OSError, PermissionError):
            pass


def run_filtering_module(config, image_queue, stats_queue, shutdown_event=None):
    """Точка входа для процесса модуля фильтрации"""
    # Настройка логирования с UTF-8 для filtering_module
    import sys
    import contextlib
    
    with contextlib.suppress(Exception):
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    
    module = FilteringModule(config, image_queue, stats_queue)
    module.run()
