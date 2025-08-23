"""
Модуль поддержки продвинутых форматов изображений с AI-оптимизацией
Поддерживает новые форматы 2025 года и интеллектуальную обработку
"""
import io
import os
import json
import base64
import hashlib
import logging
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass
from PIL import Image, ImageFilter, ImageEnhance
import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ImageMetadata:
    """Метаданные изображения для AI анализа"""
    format: str
    size: Tuple[int, int]
    mode: str
    quality_score: float
    compression_ratio: float
    color_palette: List[str]
    dominant_colors: List[str]
    has_transparency: bool
    estimated_file_size: int
    ai_tags: List[str]
    content_type: str  # 'photo', 'illustration', 'icon', 'logo', 'text'


class NextGenFormatHandler:
    """Обработчик форматов изображений нового поколения"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.supported_formats = {
            # Стандартные форматы
            'jpg': {'mime': 'image/jpeg', 'quality': 'high', 'compression': 'lossy'},
            'jpeg': {'mime': 'image/jpeg', 'quality': 'high', 'compression': 'lossy'},
            'png': {'mime': 'image/png', 'quality': 'high', 'compression': 'lossless'},
            'gif': {'mime': 'image/gif', 'quality': 'medium', 'compression': 'lossless'},
            'bmp': {'mime': 'image/bmp', 'quality': 'high', 'compression': 'none'},
            'tiff': {'mime': 'image/tiff', 'quality': 'high', 'compression': 'lossless'},
            
            # Современные форматы
            'webp': {'mime': 'image/webp', 'quality': 'high', 'compression': 'both'},
            'avif': {'mime': 'image/avif', 'quality': 'very_high', 'compression': 'advanced'},
            'heic': {'mime': 'image/heic', 'quality': 'very_high', 'compression': 'advanced'},
            'heif': {'mime': 'image/heif', 'quality': 'very_high', 'compression': 'advanced'},
            
            # Векторные форматы
            'svg': {'mime': 'image/svg+xml', 'quality': 'vector', 'compression': 'xml'},
            
            # Новые форматы 2025
            'jxl': {'mime': 'image/jxl', 'quality': 'ultra_high', 'compression': 'next_gen'},
            'avifs': {'mime': 'image/avif-sequence', 'quality': 'very_high', 'compression': 'advanced'},
            'webp2': {'mime': 'image/webp2', 'quality': 'ultra_high', 'compression': 'next_gen'},
            
            # AI-генерированные форматы
            'ai': {'mime': 'image/ai-generated', 'quality': 'variable', 'compression': 'smart'},
            'neural': {'mime': 'image/neural-compressed', 'quality': 'adaptive', 'compression': 'ai'},
        }
        
        # Настройки AI оптимизации
        self.ai_optimization = config.get('ai_optimization', {})
        self.enable_quality_enhancement = self.ai_optimization.get('enhance_quality', False)
        self.enable_smart_cropping = self.ai_optimization.get('smart_cropping', False)
        self.enable_content_analysis = self.ai_optimization.get('content_analysis', True)
        self.enable_format_conversion = self.ai_optimization.get('format_conversion', True)
    
    def detect_format(self, image_data: bytes, url: str = '') -> str:
        """Интеллектуальное определение формата изображения"""
        # Проверяем по магическим байтам
        format_signatures = {
            b'\xFF\xD8\xFF': 'jpg',
            b'\x89PNG\r\n\x1a\n': 'png',
            b'GIF87a': 'gif',
            b'GIF89a': 'gif',
            b'RIFF': 'webp',  # Нужна дополнительная проверка
            b'BM': 'bmp',
            b'II*\x00': 'tiff',
            b'MM\x00*': 'tiff',
            b'<svg': 'svg',
            b'<?xml': 'svg',  # Возможно SVG
            b'\x00\x00\x00\x20ftypavif': 'avif',
            b'\x00\x00\x00\x18ftypheic': 'heic',
            b'\x00\x00\x00\x20ftypheif': 'heif',
            b'\xFF\x0A': 'jxl',  # JPEG XL
        }
        
        for signature, format_name in format_signatures.items():
            if image_data.startswith(signature):
                if format_name == 'webp' and b'WEBP' in image_data[:12]:
                    return 'webp'
                elif format_name == 'svg' and (b'<svg' in image_data[:100] or b'svg' in image_data[:200]):
                    return 'svg'
                else:
                    return format_name
        
        # Проверяем по URL если магические байты не помогли
        if url:
            url_lower = url.lower()
            for ext in self.supported_formats.keys():
                if f'.{ext}' in url_lower:
                    return ext
        
        # Пытаемся определить через PIL
        try:
            with Image.open(io.BytesIO(image_data)) as img:
                return img.format.lower() if img.format else 'unknown'
        except:
            pass
        
        return 'unknown'
    
    def analyze_image_content(self, image_data: bytes) -> ImageMetadata:
        """AI-анализ содержимого изображения"""
        try:
            with Image.open(io.BytesIO(image_data)) as img:
                # Базовые метаданные
                format_name = self.detect_format(image_data)
                size = img.size
                mode = img.mode
                has_transparency = mode in ('RGBA', 'LA') or 'transparency' in img.info
                
                # Конвертируем в RGB для анализа
                if img.mode != 'RGB':
                    rgb_img = img.convert('RGB')
                else:
                    rgb_img = img
                
                # Анализ качества
                quality_score = self._calculate_quality_score(rgb_img)
                
                # Анализ цветов
                color_analysis = self._analyze_colors(rgb_img)
                
                # Определение типа контента
                content_type = self._classify_content_type(rgb_img)
                
                # AI теги (базовая реализация)
                ai_tags = self._generate_ai_tags(rgb_img, content_type)
                
                # Оценка сжатия
                compression_ratio = len(image_data) / (size[0] * size[1] * 3)
                
                return ImageMetadata(
                    format=format_name,
                    size=size,
                    mode=mode,
                    quality_score=quality_score,
                    compression_ratio=compression_ratio,
                    color_palette=color_analysis['palette'],
                    dominant_colors=color_analysis['dominant'],
                    has_transparency=has_transparency,
                    estimated_file_size=len(image_data),
                    ai_tags=ai_tags,
                    content_type=content_type
                )
                
        except Exception as e:
            logger.error(f"Ошибка анализа изображения: {e}")
            return ImageMetadata(
                format='unknown',
                size=(0, 0),
                mode='unknown',
                quality_score=0.0,
                compression_ratio=0.0,
                color_palette=[],
                dominant_colors=[],
                has_transparency=False,
                estimated_file_size=len(image_data),
                ai_tags=[],
                content_type='unknown'
            )
    
    def optimize_image(self, image_data: bytes, target_format: str = 'auto') -> Tuple[bytes, ImageMetadata]:
        """AI-оптимизация изображения"""
        try:
            with Image.open(io.BytesIO(image_data)) as img:
                # Анализируем исходное изображение
                original_metadata = self.analyze_image_content(image_data)
                
                # Определяем оптимальный формат
                if target_format == 'auto':
                    target_format = self._choose_optimal_format(original_metadata)
                
                # Применяем оптимизации
                optimized_img = self._apply_optimizations(img, original_metadata)
                
                # Сохраняем в оптимальном формате
                output_buffer = io.BytesIO()
                save_params = self._get_save_parameters(target_format, original_metadata)
                
                optimized_img.save(output_buffer, format=target_format.upper(), **save_params)
                optimized_data = output_buffer.getvalue()
                
                # Анализируем результат
                optimized_metadata = self.analyze_image_content(optimized_data)
                
                logger.info(f"Оптимизировано изображение: {original_metadata.format} -> {target_format}, "
                          f"размер: {len(image_data)} -> {len(optimized_data)} байт")
                
                return optimized_data, optimized_metadata
                
        except Exception as e:
            logger.error(f"Ошибка оптимизации изображения: {e}")
            return image_data, self.analyze_image_content(image_data)
    
    def _calculate_quality_score(self, img: Image.Image) -> float:
        """Вычисляет оценку качества изображения"""
        try:
            # Конвертируем в numpy array для анализа
            img_array = np.array(img)
            
            # Вычисляем различные метрики качества
            
            # 1. Резкость (Laplacian variance)
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
            laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
            sharpness_score = min(laplacian_var / 1000, 1.0)
            
            # 2. Контраст (стандартное отклонение)
            contrast_score = np.std(gray) / 128.0
            
            # 3. Яркость (среднее значение)
            brightness = np.mean(gray) / 255.0
            brightness_score = 1.0 - abs(brightness - 0.5) * 2  # Оптимальная яркость около 0.5
            
            # 4. Цветовое разнообразие
            unique_colors = len(np.unique(img_array.reshape(-1, img_array.shape[-1]), axis=0))
            max_colors = min(img.size[0] * img.size[1], 65536)
            color_diversity = unique_colors / max_colors
            
            # Комбинируем метрики
            quality_score = (
                sharpness_score * 0.3 +
                contrast_score * 0.25 +
                brightness_score * 0.2 +
                color_diversity * 0.25
            )
            
            return min(quality_score, 1.0)
            
        except Exception as e:
            logger.warning(f"Ошибка расчета оценки качества: {e}")
            return 0.5  # Средняя оценка по умолчанию
    
    def _analyze_colors(self, img: Image.Image) -> Dict[str, List[str]]:
        """Анализирует цветовую палитру изображения"""
        try:
            # Уменьшаем изображение для ускорения анализа
            small_img = img.resize((100, 100))
            img_array = np.array(small_img)
            
            # Получаем уникальные цвета
            pixels = img_array.reshape(-1, 3)
            unique_colors, counts = np.unique(pixels, axis=0, return_counts=True)
            
            # Сортируем по частоте
            sorted_indices = np.argsort(counts)[::-1]
            dominant_colors = unique_colors[sorted_indices]
            
            # Конвертируем в hex
            def rgb_to_hex(rgb):
                return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
            
            # Топ-5 доминирующих цветов
            dominant_hex = [rgb_to_hex(color) for color in dominant_colors[:5]]
            
            # Создаем палитру (кластеризация цветов)
            palette = self._create_color_palette(dominant_colors[:20])
            palette_hex = [rgb_to_hex(color) for color in palette]
            
            return {
                'dominant': dominant_hex,
                'palette': palette_hex
            }
            
        except Exception as e:
            logger.warning(f"Ошибка анализа цветов: {e}")
            return {'dominant': [], 'palette': []}
    
    def _create_color_palette(self, colors: np.ndarray) -> List[np.ndarray]:
        """Создает цветовую палитру через кластеризацию"""
        try:
            from sklearn.cluster import KMeans
            
            # Кластеризуем цвета
            n_clusters = min(8, len(colors))
            kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
            kmeans.fit(colors)
            
            return kmeans.cluster_centers_.astype(int)
            
        except ImportError:
            # Fallback без sklearn
            return colors[:8]  # Просто берем первые 8 цветов
    
    def _classify_content_type(self, img: Image.Image) -> str:
        """Классифицирует тип содержимого изображения"""
        try:
            # Базовая классификация на основе характеристик
            width, height = img.size
            aspect_ratio = width / height
            
            # Анализ цветов
            img_array = np.array(img.resize((50, 50)))
            
            # Количество уникальных цветов
            unique_colors = len(np.unique(img_array.reshape(-1, 3), axis=0))
            color_diversity = unique_colors / (50 * 50)
            
            # Анализ краев
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
            edges = cv2.Canny(gray, 50, 150)
            edge_density = np.sum(edges > 0) / (50 * 50)
            
            # Классификация на основе характеристик
            if edge_density > 0.3 and color_diversity < 0.1:
                return 'text'
            elif aspect_ratio > 2.0 or aspect_ratio < 0.5:
                return 'banner'
            elif min(width, height) < 100 and max(width, height) < 200:
                return 'icon'
            elif color_diversity < 0.2 and edge_density > 0.2:
                return 'logo'
            elif edge_density < 0.1 and color_diversity > 0.5:
                return 'photo'
            else:
                return 'illustration'
                
        except Exception as e:
            logger.warning(f"Ошибка классификации типа контента: {e}")
            return 'unknown'
    
    def _generate_ai_tags(self, img: Image.Image, content_type: str) -> List[str]:
        """Генерирует AI теги для изображения"""
        tags = []
        
        # Добавляем теги на основе типа контента
        tags.append(content_type)
        
        # Анализ размера
        width, height = img.size
        if width > 1920 or height > 1080:
            tags.append('high_resolution')
        elif width < 300 or height < 300:
            tags.append('low_resolution')
        else:
            tags.append('medium_resolution')
        
        # Анализ ориентации
        if width > height * 1.3:
            tags.append('landscape')
        elif height > width * 1.3:
            tags.append('portrait')
        else:
            tags.append('square')
        
        # Анализ цветности
        if img.mode == 'L':
            tags.append('grayscale')
        elif img.mode in ('RGBA', 'LA'):
            tags.append('transparent')
        else:
            tags.append('color')
        
        return tags
    
    def _choose_optimal_format(self, metadata: ImageMetadata) -> str:
        """Выбирает оптимальный формат для изображения"""
        content_type = metadata.content_type
        has_transparency = metadata.has_transparency
        size = metadata.size
        
        # Логика выбора формата
        if content_type == 'photo':
            if has_transparency:
                return 'webp'  # WebP поддерживает прозрачность и хорошо сжимает фото
            else:
                return 'avif' if self._format_supported('avif') else 'webp'
        
        elif content_type in ('logo', 'icon'):
            if has_transparency:
                return 'png'  # PNG лучше для логотипов с прозрачностью
            else:
                return 'webp'
        
        elif content_type == 'illustration':
            return 'webp'  # Универсальный формат
        
        elif content_type == 'text':
            return 'png'  # PNG лучше для текста
        
        else:
            # По умолчанию
            return 'webp'
    
    def _format_supported(self, format_name: str) -> bool:
        """Проверяет поддержку формата"""
        try:
            # Пытаемся создать тестовое изображение в формате
            test_img = Image.new('RGB', (1, 1), color='white')
            test_buffer = io.BytesIO()
            test_img.save(test_buffer, format=format_name.upper())
            return True
        except:
            return False
    
    def _apply_optimizations(self, img: Image.Image, metadata: ImageMetadata) -> Image.Image:
        """Применяет AI оптимизации к изображению"""
        optimized_img = img.copy()
        
        try:
            # Улучшение качества
            if self.enable_quality_enhancement and metadata.quality_score < 0.7:
                optimized_img = self._enhance_quality(optimized_img)
            
            # Умная обрезка
            if self.enable_smart_cropping:
                optimized_img = self._smart_crop(optimized_img)
            
            # Оптимизация размера
            optimized_img = self._optimize_size(optimized_img, metadata)
            
        except Exception as e:
            logger.warning(f"Ошибка применения оптимизаций: {e}")
        
        return optimized_img
    
    def _enhance_quality(self, img: Image.Image) -> Image.Image:
        """Улучшает качество изображения"""
        try:
            # Повышение резкости
            enhanced = img.filter(ImageFilter.UnsharpMask(radius=1, percent=120, threshold=3))
            
            # Улучшение контраста
            enhancer = ImageEnhance.Contrast(enhanced)
            enhanced = enhancer.enhance(1.1)
            
            # Улучшение цвета
            enhancer = ImageEnhance.Color(enhanced)
            enhanced = enhancer.enhance(1.05)
            
            return enhanced
            
        except Exception as e:
            logger.warning(f"Ошибка улучшения качества: {e}")
            return img
    
    def _smart_crop(self, img: Image.Image) -> Image.Image:
        """Умная обрезка изображения"""
        try:
            # Базовая реализация - удаление пустых краев
            bbox = img.getbbox()
            if bbox:
                return img.crop(bbox)
            return img
            
        except Exception as e:
            logger.warning(f"Ошибка умной обрезки: {e}")
            return img
    
    def _optimize_size(self, img: Image.Image, metadata: ImageMetadata) -> Image.Image:
        """Оптимизирует размер изображения"""
        try:
            width, height = img.size
            max_size = self.config.get('ai_optimization', {}).get('max_image_size', 2048)
            
            # Уменьшаем только если изображение слишком большое
            if width > max_size or height > max_size:
                ratio = min(max_size / width, max_size / height)
                new_size = (int(width * ratio), int(height * ratio))
                return img.resize(new_size, Image.Resampling.LANCZOS)
            
            return img
            
        except Exception as e:
            logger.warning(f"Ошибка оптимизации размера: {e}")
            return img
    
    def _get_save_parameters(self, format_name: str, metadata: ImageMetadata) -> Dict[str, Any]:
        """Получает параметры сохранения для формата"""
        params = {}
        
        if format_name.lower() in ('jpg', 'jpeg'):
            # Адаптивное качество JPEG
            if metadata.content_type == 'photo':
                params['quality'] = 85
            elif metadata.content_type in ('logo', 'text'):
                params['quality'] = 95
            else:
                params['quality'] = 80
            params['optimize'] = True
            
        elif format_name.lower() == 'png':
            params['optimize'] = True
            
        elif format_name.lower() == 'webp':
            if metadata.content_type == 'photo':
                params['quality'] = 80
            else:
                params['quality'] = 85
            params['method'] = 6  # Максимальное сжатие
            
        return params


class SmartImageProcessor:
    """Интеллектуальный процессор изображений"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.format_handler = NextGenFormatHandler(config)
        self.cache = {}  # Кэш для обработанных изображений
    
    def process_image(self, image_data: bytes, url: str = '') -> Dict[str, Any]:
        """Полная обработка изображения с AI анализом"""
        # Создаем уникальный ключ для кэширования
        cache_key = hashlib.md5(image_data).hexdigest()
        
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        # Анализируем изображение
        metadata = self.format_handler.analyze_image_content(image_data)
        
        # Оптимизируем если нужно
        if self.config.get('ai_optimization', {}).get('enabled', False):
            optimized_data, optimized_metadata = self.format_handler.optimize_image(image_data)
        else:
            optimized_data = image_data
            optimized_metadata = metadata
        
        result = {
            'original_data': image_data,
            'optimized_data': optimized_data,
            'original_metadata': metadata,
            'optimized_metadata': optimized_metadata,
            'url': url,
            'processing_applied': self.config.get('ai_optimization', {}).get('enabled', False)
        }
        
        # Кэшируем результат
        self.cache[cache_key] = result
        
        return result
    
    def get_supported_formats(self) -> List[str]:
        """Возвращает список поддерживаемых форматов"""
        return list(self.format_handler.supported_formats.keys())
    
    def clear_cache(self):
        """Очищает кэш обработанных изображений"""
        self.cache.clear()
