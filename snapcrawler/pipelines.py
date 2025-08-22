from itemadapter import ItemAdapter
import os
import hashlib
import requests
from PIL import Image
import imagehash
import cv2
import numpy as np
from scrapy.exceptions import DropItem
from scrapy.pipelines.images import ImagesPipeline
from scrapy import Request
from .utils.log_formatter import format_url_short, format_process_status, format_image_info
from .utils.svg_processor import SVGProcessor, is_svg_file

class ImageFilteringPipeline:
    def __init__(self, settings):
        self.settings = settings
        self.config = settings.get('SNAPCRAWLER_CONFIG')
        self.filtering_config = self.config.get('images', {})
        self.output_dir = self.config.get('general', {}).get('output_dir', 'downloads')
        self.resource_limits = self.config.get('limits', {})
        self.image_hashes = set()
        self.svg_processor = SVGProcessor()

        # --- Настройка лимита размера папки ---
        self.raw_dir = os.path.join(self.output_dir, 'raw')
        self.processed_dir = os.path.join(self.output_dir, 'processed')
        os.makedirs(self.raw_dir, exist_ok=True)
        os.makedirs(self.processed_dir, exist_ok=True)
        self.max_folder_size_bytes = self.resource_limits.get('max_folder_size_mb', 0) * 1024 * 1024
        self.current_folder_size_bytes = sum(
            os.path.getsize(os.path.join(self.processed_dir, f))
            for f in os.listdir(self.processed_dir)
            if os.path.isfile(os.path.join(self.processed_dir, f))
        )

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler.settings)

    def process_item(self, item, spider):
        if not item.get('image_urls'):
            raise DropItem("В элементе не найдено ссылок на изображения")

        processed_images = []
        
        # Скачиваем и обрабатываем каждый URL изображения напрямую
        for image_url in item.get('image_urls', []):
            try:
                # Скачиваем изображение
                image_path = self._download_image(image_url, spider)
                if not image_path:
                    continue
                
                # Обрабатываем загруженное изображение
                if self._process_single_image(image_path, spider):
                    processed_images.append({'url': image_url, 'path': image_path})
                else:
                    self._safe_remove_file(image_path)
                    
            except Exception as e:
                spider.logger.error(format_process_status('error', f"{format_url_short(image_url)}: {str(e)[:30]}"))
                continue

        if not processed_images:
            raise DropItem("Ни одно изображение не прошло фильтры")

        item['images'] = processed_images
        return item
    
    def _download_image(self, url, spider):
        """Загрузить изображение по URL в директорию raw"""
        try:
            import requests
            from urllib.parse import urlparse
            
            timeout = spider.settings.get('SNAPCRAWLER_CONFIG', {}).get('crawling', {}).get('timeouts', {}).get('request_timeout', 30)
            response = requests.get(url, timeout=timeout, stream=True)
            response.raise_for_status()
            
            # Генерируем имя файла из URL
            parsed = urlparse(url)
            filename = os.path.basename(parsed.path)
            if not filename or '.' not in filename:
                filename = f"image_{hash(url) % 1000000}.jpg"
            
            raw_path = os.path.join(self.raw_dir, filename)
            
            # Обрабатываем возможные дубликаты имён файлов
            counter = 1
            base_name, ext = os.path.splitext(raw_path)
            while os.path.exists(raw_path):
                raw_path = f"{base_name}_{counter}{ext}"
                counter += 1
            
            # Загружаем файл поблочно
            with open(raw_path, 'wb') as f:
                chunk_size = spider.settings.get('SNAPCRAWLER_CONFIG', {}).get('crawling', {}).get('timeouts', {}).get('chunk_size', 8192)
                for chunk in response.iter_content(chunk_size=chunk_size):
                    f.write(chunk)
            
            spider.logger.info(format_process_status('download', f"{format_url_short(url)} -> {filename[-10:]}"))
            return raw_path
            
        except Exception as e:
            spider.logger.error(format_process_status('error', f"{format_url_short(url)}: {str(e)[:30]}"))
            return None
    
    def _process_single_image(self, image_path, spider):
        """Обработать одно загруженное изображение через все фильтры"""
        if not os.path.exists(image_path):
            return False

        try:
            # Проверяем, является ли файл SVG
            if is_svg_file(image_path):
                # Конвертируем SVG в PNG для обработки
                png_path = self.svg_processor.convert_svg_to_png(image_path)
                if png_path:
                    try:
                        img = Image.open(png_path)
                        # Заменяем оригинальный SVG на PNG
                        if png_path != image_path:
                            os.replace(png_path, image_path.replace('.svg', '.png'))
                            image_path = image_path.replace('.svg', '.png')
                    except Exception as e:
                        spider.logger.debug(format_process_status('error', f"SVG->PNG {format_url_short(image_path)}: {str(e)[:20]}"))
                        return False
                else:
                    spider.logger.debug(format_process_status('format_fail', f"SVG {format_url_short(image_path)} не конвертирован"))
                    return False
            else:
                img = Image.open(image_path)
            
            # --- Запускаем все фильтры ---
            if not self._is_valid_size(img):
                spider.logger.debug(format_process_status('size_fail', f"{format_url_short(image_path)} {format_image_info(img.size)}"))
                return False
            if not self._is_valid_format(image_path):
                spider.logger.debug(format_process_status('format_fail', f"{format_url_short(image_path)} {os.path.splitext(image_path)[1]}"))
                return False
            if not self._is_valid_dpi(img):
                spider.logger.debug(format_process_status('dpi_fail', format_url_short(image_path)))
                return False
            if not self._is_valid_color_mode(img):
                spider.logger.debug(format_process_status('color_fail', f"{format_url_short(image_path)} {img.mode}"))
                return False
            if not self._is_valid_orientation(img):
                spider.logger.debug(format_process_status('orientation_fail', f"{format_url_short(image_path)} {format_image_info(img.size)}"))
                return False
            if not self._is_valid_aspect_ratio_range(img):
                spider.logger.debug(format_process_status('aspect_fail', f"{format_url_short(image_path)} {img.size[0]/img.size[1]:.2f}"))
                return False
            if self._is_duplicate(img):
                spider.logger.debug(format_process_status('duplicate', format_url_short(image_path)))
                return False
            if self._has_watermark(image_path):
                spider.logger.debug(format_process_status('watermark_fail', format_url_short(image_path)))
                return False
            if not self._is_valid_aspect_ratio(img):
                spider.logger.debug(format_process_status('banner_fail', f"{format_url_short(image_path)} {format_image_info(img.size)}"))
                return False

            # Если все фильтры пройдены, перемещаем файл в папку processed
            self._handle_processed_image(image_path)
            return True

        except Exception as e:
            spider.logger.error(format_process_status('error', f"{format_url_short(image_path)}: {str(e)[:30]}"))
            return False

    def _is_valid_size(self, img):
        """Проверка соответствия изображения минимальным требованиям по размеру"""
        width, height = img.size
        min_side = self.filtering_config.get('min_side_size', 0)
        return min_side <= 0 or (min(width, height) >= min_side)

    def _is_valid_color_mode(self, img):
        """Проверка режима цвета изображения"""
        color_mode = self.filtering_config.get('color_mode', 'any')
        if color_mode == 'any':
            return True
        is_grayscale = img.mode == 'L'
        if color_mode == 'color' and is_grayscale:
            return False
        if color_mode == 'bw' and not is_grayscale:
            return False
        return True

    def _is_valid_orientation(self, img):
        """Проверка ориентации изображения"""
        orientation = self.filtering_config.get('orientation', 'any')
        if orientation == 'any':
            return True
        width, height = img.size
        if orientation == 'landscape' and width < height:
            return False
        if orientation == 'portrait' and height < width:
            return False
        if orientation == 'square' and width != height:
            return False
        return True

    def _is_duplicate(self, img):
        """Проверка дублирования изображения"""
        if not self.filtering_config.get('deduplication', True):
            return False
        img_hash = imagehash.phash(img)
        if img_hash in self.image_hashes:
            return True
        self.image_hashes.add(img_hash)
        return False

    def _has_watermark(self, image_path):
        """Проверка наличия водяного знака"""
        if self.filtering_config.get('allow_watermarks', True):
            return False
        try:
            cv_img = cv2.imread(image_path)
            if cv_img is None:
                return False # Не удалось прочитать файл — пропускаем обработку
            gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
            # Простая эвристика: большое число маленьких контрастных областей может указывать на текст/логотип
            mser = cv2.MSER_create()
            regions, _ = mser.detectRegions(gray)
            # Порог примерный и требует настройки под реальные сайты
            if len(regions) > self.filtering_config.get('watermark_sensitivity', 50):
                return True
        except Exception as e:
            # Если OpenCV завершился с ошибкой — лучше сохранить изображение, чем удалить по ложному срабатыванию
            return False
        return False

    def _is_valid_aspect_ratio(self, img):
        """Проверка соотношения сторон на предмет баннеров/логотипов"""
        if self.filtering_config.get('allow_logos_banners', True):
            return True
        
        width, height = img.size
        aspect_ratio = width / height if height > 0 else 1
        
        # Отфильтровываем экстремальные соотношения сторон, типичные для баннеров/логотипов
        # Баннеры: очень широкие (>10:1) или очень высокие (<1:10)
        if aspect_ratio > 10 or aspect_ratio < 0.1:
            return False
        return True

    def _is_valid_format(self, image_path):
        """Проверка, что формат изображения входит в список разрешённых"""
        allowed_formats = self.filtering_config.get('formats', [])
        if not allowed_formats:
            return True
        
        file_ext = os.path.splitext(image_path)[1].lower().lstrip('.')
        return file_ext in [fmt.lower() for fmt in allowed_formats]

    def _is_valid_dpi(self, img):
        """Проверка, что DPI изображения соответствует минимальному порогу"""
        min_dpi = self.filtering_config.get('min_dpi', 0)
        if min_dpi <= 0:
            return True
        
        try:
            dpi = img.info.get('dpi')
            if dpi:
                # DPI возвращается как кортеж (x_dpi, y_dpi)
                actual_dpi = min(dpi) if isinstance(dpi, tuple) else dpi
                return actual_dpi >= min_dpi
        except:
            pass
        return True  # Если информация о DPI отсутствует, не отбрасываем изображение

    def _is_valid_aspect_ratio_range(self, img):
        """Проверка, что соотношение сторон находится в указанном диапазоне"""
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

    def _handle_processed_image(self, image_path):
        """Переместить валидированное изображение в папку processed и проверить лимиты размера"""
        # Проверяем лимит размера папки перед перемещением
        image_size_bytes = os.path.getsize(image_path)
        if self.max_folder_size_bytes > 0 and (self.current_folder_size_bytes + image_size_bytes) > self.max_folder_size_bytes:
            raise DropItem(f"Будет превышен лимит размера папки ({self.resource_limits.get('max_folder_size_mb', 0)}MB)")

        # Перемещаем файл в папку processed
        file_name = os.path.basename(image_path)
        new_path = os.path.join(self.processed_dir, file_name)
        os.rename(image_path, new_path)
        self.current_folder_size_bytes += image_size_bytes
    
    def _safe_remove_file(self, file_path):
        """Безопасное удаление файла с корректной обработкой ошибок"""
        try:
            if os.path.exists(file_path):
                # Для Windows: убедимся, что файл не только для чтения
                os.chmod(file_path, 0o777)
                os.remove(file_path)
        except (OSError, PermissionError) as e:
            # Логируем проблему, но не падаем — файл будет удалён позже или вручную
            pass
