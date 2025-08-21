#!/usr/bin/env python3
"""
Точка входа для запуска SnapCrawler в параллельном режиме.
Реализует параллельную архитектуру согласно ТЗ.
"""

import sys
import os
import logging
import multiprocessing

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def main():
    """Основная точка входа для параллельного режима"""
    # Настройка логирования
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('snapcrawler.log')
        ]
    )
    
    # Путь к файлу конфигурации
    config_path = sys.argv[1] if len(sys.argv) > 1 else 'config.yaml'
    
    if not os.path.exists(config_path):
        print(f"Файл конфигурации не найден: {config_path}")
        sys.exit(1)
    
    # Импорт здесь, чтобы избежать проблем с multiprocessing на Windows
    from snapcrawler.core.parallel_manager import ParallelManager
    
    # Создать и запустить менеджер параллельной обработки
    manager = ParallelManager(config_path)
    try:
        manager.start()
    except KeyboardInterrupt:
        print("\nКорректное завершение работы...")
        manager.shutdown()
    except Exception as e:
        print(f"Ошибка: {e}")
        manager.shutdown()
        sys.exit(1)

if __name__ == '__main__':
    # Требуется для корректной работы multiprocessing на Windows
    multiprocessing.freeze_support()
    main()
