"""
Утилиты для форматирования логов в человекопонятный вид
Сохраняет всю логику, только улучшает читаемость вывода
"""
import os
import hashlib
from typing import Dict, Any
from urllib.parse import urlparse

class CompactStatsFormatter:
    """Компактный форматтер статистики для краткого вывода"""
    
    def __init__(self):
        self.reset_stats()
    
    def reset_stats(self):
        """Сброс всех счетчиков"""
        self.pages_found = 0
        self.images_found = 0
        self.images_failed = 0
        self.images_downloaded = 0
        self.images_saved = 0
        self.folder_size_mb = 0.0
        self.has_errors = False
        self.error_code = None
        self.last_update_line = ""
    
    def update_stats(self, **kwargs):
        """Обновление статистики"""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
    
    def format_compact_line(self) -> str:
        """Форматирует компактную строку статистики"""
        error_status = f"Ошибка: {self.error_code}" if self.has_errors else "Ошибка: Нет"
        
        line = (f"Страниц: {self.pages_found} | "
                f"Найдено: {self.images_found} | "
                f"Не пройдено: {self.images_failed} | "
                f"Загружено: {self.images_downloaded} | "
                f"Сохранено: {self.images_saved} | "
                f"Вес папки: {self.folder_size_mb:.1f}MB | "
                f"{error_status}")
        
        return line
    
    def print_update(self):
        """Печатает обновленную строку статистики (перезаписывает предыдущую)"""
        current_line = self.format_compact_line()
        if current_line != self.last_update_line:
            # Очищаем предыдущую строку и печатаем новую
            print(f"\r{' ' * 120}\r{current_line}", end='', flush=True)
            self.last_update_line = current_line


def format_url_short(url: str, max_length: int = 50) -> str:
    """
    Сокращает URL до последних 5 символов + расширение
    Пример: 'https://example.com/image123.jpg' -> '23.jpg'
    """
    if not url:
        return "???"

    try:
        parsed = urlparse(url)
        path = parsed.path
        
        # Извлекаем имя файла
        filename = os.path.basename(path)
        if not filename:
            # Если нет имени файла, берем последние символы домена
            domain = parsed.netloc
            return domain[-5:] if len(domain) >= 5 else domain
        
        # Разделяем имя и расширение
        name, ext = os.path.splitext(filename)
        
        if ext:
            # Есть расширение - берем последние 5 символов имени + расширение
            short_name = name[-5:] if len(name) >= 5 else name
            return f"{short_name}{ext}"
        else:
            # Нет расширения - просто последние 5 символов
            return filename[-5:] if len(filename) >= 5 else filename

    except Exception:
        # В случае ошибки возвращаем последние 5 символов URL
        return url[-5:] if len(url) >= 5 else url

def format_process_status(action: str, details: str = "") -> str:
    """Форматирует статус процесса с цветными эмодзи"""
    status_map = {
        'loading': '[LOADING]',
        'error': '[ERROR]',
        'success': '[SUCCESS]',
        'duplicate': '[DUPLICATE]',
        'filtered': '[FILTERED]',
        'size_fail': '[РАЗМЕР]',
        'format_fail': '[ФОРМАТ]',
        'dpi_fail': '[DPI]',
        'color_fail': '[ЦВЕТ]',
        'orientation_fail': '[ОРИЕНТАЦИЯ]',
        'aspect_fail': '[ПРОПОРЦИИ]',
        'watermark_fail': '[ВОДЯНОЙ_ЗНАК]',
        'banner_fail': '[БАННЕР]',
        
        # Сеть
        'captcha': '[CAPTCHA]',
        'throttle': '[ЗАМЕДЛЕНИЕ]',
        'connection_error': '[СОЕДИНЕНИЕ]',
        
        # Обход
        'crawl_start': '[СТАРТ]',
        'crawl_complete': '[ЗАВЕРШЕН]',
        'new_links': '[ССЫЛКИ]',
        'depth_complete': '[УРОВЕНЬ]'
    }
    
    status = status_map.get(action, f"[{action.upper()}]")
    return f"{status} {details}".strip()

def format_image_info(img_size=None, img_format=None, file_size=None):
    """
    Форматирует информацию об изображении компактно
    """
    info_parts = []
    
    if img_size:
        info_parts.append(f"{img_size[0]}x{img_size[1]}")
    
    if img_format:
        info_parts.append(img_format.upper())
        
    if file_size:
        if file_size < 1024:
            info_parts.append(f"{file_size}B")
        elif file_size < 1024*1024:
            info_parts.append(f"{file_size//1024}KB")
        else:
            info_parts.append(f"{file_size//(1024*1024)}MB")
    
    return " | ".join(info_parts) if info_parts else ""

def format_stats_compact(pages=0, images=0, processed=0, errors=0):
    """
    Компактная статистика в одну строку
    """
    return f"Страниц: {pages} | Изображений: {images} | Обработано: {processed} | Ошибок: {errors}"
