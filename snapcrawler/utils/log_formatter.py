"""
Утилиты для форматирования логов в человекопонятный вид
Сохраняет всю логику, только улучшает читаемость вывода
"""
import os
from urllib.parse import urlparse

def format_url_short(url):
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

def format_process_status(action, details=""):
    """
    Форматирует статус процесса в человекопонятный вид
    """
    status_map = {
        # Основные действия
        'download': '[ЗАГРУЗКА]',
        'skip': '[ПРОПУСК]', 
        'error': '[ОШИБКА]',
        'success': '[УСПЕХ]',
        'duplicate': '[ДУБЛИКАТ]',
        'filter_fail': '[ОТКЛОНЕН]',
        'processing': '[ОБРАБОТКА]',
        
        # Фильтры
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
