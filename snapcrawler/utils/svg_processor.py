"""
SVG обработчик для конвертации SVG в растровые форматы
Интегрируется с существующей системой без нарушения логики
"""
import os
import tempfile
import logging
from PIL import Image
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

class SVGProcessor:
    """
    Обработчик SVG файлов с fallback стратегией
    """
    
    def __init__(self):
        self.cairosvg_available = False
        self.wand_available = False
        
        # Проверяем доступность библиотек
        try:
            import cairosvg
            self.cairosvg_available = True
            logger.debug("CairoSVG доступен для обработки SVG")
        except ImportError:
            pass
            
        try:
            from wand.image import Image as WandImage
            self.wand_available = True
            logger.debug("Wand доступен для обработки SVG")
        except ImportError:
            pass
    
    def can_process_svg(self) -> bool:
        """Проверяет, может ли система обрабатывать SVG"""
        return self.cairosvg_available or self.wand_available
    
    def convert_svg_to_png(self, svg_path: str, output_path: Optional[str] = None) -> Optional[str]:
        """
        Конвертирует SVG в PNG
        
        Args:
            svg_path: Путь к SVG файлу
            output_path: Путь для сохранения PNG (опционально)
            
        Returns:
            Путь к созданному PNG файлу или None при ошибке
        """
        if not os.path.exists(svg_path):
            logger.error(f"SVG файл не найден: {svg_path}")
            return None
        
        if output_path is None:
            # Создаем временный файл
            temp_dir = os.path.dirname(svg_path)
            base_name = os.path.splitext(os.path.basename(svg_path))[0]
            output_path = os.path.join(temp_dir, f"{base_name}.png")
        
        # Пробуем CairoSVG первым (быстрее)
        if self.cairosvg_available:
            try:
                return self._convert_with_cairosvg(svg_path, output_path)
            except Exception as e:
                logger.warning(f"CairoSVG не смог обработать {svg_path}: {e}")
        
        # Fallback на Wand
        if self.wand_available:
            try:
                return self._convert_with_wand(svg_path, output_path)
            except Exception as e:
                logger.warning(f"Wand не смог обработать {svg_path}: {e}")
        
        logger.error(f"Не удалось конвертировать SVG: {svg_path}")
        return None
    
    def _convert_with_cairosvg(self, svg_path: str, output_path: str) -> str:
        """Конвертация через CairoSVG"""
        import cairosvg
        
        # Получаем размеры из конфигурации
        from ..settings import SNAPCRAWLER_CONFIG
        svg_config = SNAPCRAWLER_CONFIG.get('images', {}).get('svg_processing', {})
        max_width = svg_config.get('max_width', 1024)
        max_height = svg_config.get('max_height', 1024)
        
        cairosvg.svg2png(
            url=svg_path,
            write_to=output_path,
            output_width=max_width,
            output_height=max_height
        )
        
        logger.debug(f"SVG конвертирован через CairoSVG: {svg_path} -> {output_path}")
        return output_path
    
    def _convert_with_wand(self, svg_path: str, output_path: str) -> str:
        """Конвертация через Wand (ImageMagick)"""
        from wand.image import Image as WandImage
        
        # Получаем размеры из конфигурации
        from ..settings import SNAPCRAWLER_CONFIG
        svg_config = SNAPCRAWLER_CONFIG.get('images', {}).get('svg_processing', {})
        max_width = svg_config.get('max_width', 1024)
        max_height = svg_config.get('max_height', 1024)
        
        with WandImage(filename=svg_path) as img:
            # Устанавливаем разумный размер
            if img.width > max_width or img.height > max_height:
                img.transform(resize=f'{max_width}x{max_height}>')
            
            img.format = 'png'
            img.save(filename=output_path)
        
        logger.debug(f"SVG конвертирован через Wand: {svg_path} -> {output_path}")
        return output_path
    
    def get_svg_info(self, svg_path: str) -> Optional[Tuple[int, int]]:
        """
        Получает размеры SVG файла
        
        Returns:
            Tuple (width, height) или None при ошибке
        """
        try:
            # Простой парсинг SVG для получения размеров
            with open(svg_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            import re
            
            # Ищем width и height в атрибутах
            width_match = re.search(r'width=["\'](\d+(?:\.\d+)?)', content)
            height_match = re.search(r'height=["\'](\d+(?:\.\d+)?)', content)
            
            if width_match and height_match:
                width = float(width_match.group(1))
                height = float(height_match.group(1))
                return (int(width), int(height))
            
            # Ищем viewBox
            viewbox_match = re.search(r'viewBox=["\'][^"\']*?(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)["\']', content)
            if viewbox_match:
                width = float(viewbox_match.group(1))
                height = float(viewbox_match.group(2))
                return (int(width), int(height))
                
        except Exception as e:
            logger.warning(f"Не удалось получить размеры SVG {svg_path}: {e}")
        
        # Возвращаем стандартный размер из конфигурации
        from ..settings import SNAPCRAWLER_CONFIG
        svg_config = SNAPCRAWLER_CONFIG.get('images', {}).get('svg_processing', {})
        default_size = svg_config.get('default_size', 512)
        return (default_size, default_size)

def is_svg_file(file_path: str) -> bool:
    """Проверяет, является ли файл SVG"""
    if not file_path:
        return False
    
    # Проверка по расширению
    if file_path.lower().endswith('.svg'):
        return True
    
    # Проверка по содержимому (первые байты)
    try:
        with open(file_path, 'rb') as f:
            header = f.read(100).decode('utf-8', errors='ignore')
            return '<svg' in header.lower() or '<?xml' in header.lower()
    except:
        return False
