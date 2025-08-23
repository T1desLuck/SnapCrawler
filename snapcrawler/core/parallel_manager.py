"""
Параллельный менеджер (Parallel Manager) — оркестрирует параллельные модули обхода и фильтрации
Реализует двухмодульную архитектуру, заданную в ТЗ
"""
import multiprocessing
import queue
import time
import logging
import os
import yaml
from typing import Dict, Any
from .crawling_module import run_crawling_module
from .filtering_module import run_filtering_module

class ParallelManager:
    """
    Главный оркестратор параллельной архитектуры обхода и фильтрации
    Управляет взаимодействием модулей через очереди multiprocessing
    """
    
    def __init__(self, config_path: str):
        self.config_path = config_path
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)
        
        # Настройка логирования с UTF-8 кодировкой
        import sys
        import contextlib
        
        # Попытка настроить UTF-8 для консоли Windows
        with contextlib.suppress(Exception):
            if hasattr(sys.stdout, 'reconfigure'):
                sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            if hasattr(sys.stderr, 'reconfigure'):
                sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        
        logging.basicConfig(
            level=getattr(logging, self.config['general']['log_level'].upper()),
            format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
            handlers=[
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger('parallel_manager')
        
        # Компоненты multiprocessing
        self.manager = multiprocessing.Manager()
        queue_maxsize = self.config.get('crawling', {}).get('timeouts', {}).get('queue_maxsize', 1000)
        self.image_queue = multiprocessing.Queue(maxsize=queue_maxsize)  # Изображения от обхода к фильтрации
        self.stats_queue = multiprocessing.Queue()  # Статистика от обоих модулей
        self.visited_urls = self.manager.dict()  # Общий учёт посещённых URL
        
        # Ссылки на процессы
        self.crawling_process = None
        self.filtering_process = None
        
        # Учёт статистики
        self.stats = {
            'crawling': {'pages_crawled': 0, 'images_found': 0, 'queue_size': 0},
            'filtering': {'downloaded': 0, 'processed': 0, 'filtered_out': 0, 'folder_size_mb': 0}
        }
        
    def start(self):
        """Запустить модули обхода и фильтрации в параллельном режиме"""
        self.logger.info("Запуск SnapCrawler в параллельном режиме")
        self.logger.info("Архитектура: Crawling Module + Filtering Module (согласно ТЗ)")
        
        try:
            # Сначала запускаем модуль фильтрации (consumer)
            self.filtering_process = multiprocessing.Process(
                target=run_filtering_module,
                args=(self.config_path, self.image_queue, self.stats_queue),
                name="FilteringModule"
            )
            self.filtering_process.start()
            self.logger.info("Модуль фильтрации запущен")
            
            # Затем запускаем модуль обхода (producer)
            self.crawling_process = multiprocessing.Process(
                target=run_crawling_module,
                args=(self.config_path, self.image_queue, self.stats_queue),
                name="CrawlingModule"
            )
            self.crawling_process.start()
            self.logger.info("Модуль обхода запущен")
            
            # Мониторим оба процесса
            self.monitor_processes()
            
        except KeyboardInterrupt:
            # Разорвать компактную строку перед сообщением о прерывании
            try:
                print()
            except Exception:
                pass
            self.logger.info("Получен сигнал прерывания, начинается завершение работы...")
            self.shutdown()
        except Exception as e:
            # Разорвать компактную строку перед сообщением об ошибке
            try:
                print()
            except Exception:
                pass
            self.logger.error(f"Ошибка в параллельном менеджере: {e}")
            self.shutdown()
    
    def monitor_processes(self):
        """Мониторить оба процесса и собирать статистику"""
        last_stats_time = time.time()
        stats_interval = 10  # секунд
        
        while True:
            # Проверяем, живы ли процессы
            if not self.crawling_process.is_alive() and not self.filtering_process.is_alive():
                # Разорвать компактную строку перед завершающим сообщением
                try:
                    print()
                except Exception:
                    pass
                self.logger.info("Оба модуля завершили работу")
                break
            
            # Собираем статистику
            try:
                while True:
                    try:
                        stat = self.stats_queue.get_nowait()
                        if stat['type'] == 'crawling_stats':
                            self.stats['crawling'].update({
                                'pages_crawled': stat['pages_crawled'],
                                'images_found': stat['images_found'],
                                'queue_size': stat['queue_size']
                            })
                        elif stat['type'] == 'filtering_stats':
                            self.stats['filtering'].update({
                                'downloaded': stat['downloaded'],
                                'processed': stat['processed'],
                                'filtered_out': stat['filtered_out'],
                                'folder_size_mb': stat['folder_size_mb']
                            })
                    except queue.Empty:
                        break
            except:
                pass
            
            # Периодически выводим статистику
            current_time = time.time()
            if current_time - last_stats_time >= stats_interval:
                self.print_statistics()
                last_stats_time = current_time
            
            time.sleep(1)
        
        # Финальная статистика
        self.print_final_statistics()
    
    def print_statistics(self):
        """Вывести текущую статистику"""
        # Гарантируем перевод строки перед пачкой логов статистики,
        # чтобы не "приклеиваться" к компактной строке без перевода
        try:
            print()
        except Exception:
            pass
        crawl_stats = self.stats['crawling']
        filter_stats = self.stats['filtering']
        
        self.logger.info("=== СТАТИСТИКА ПАРАЛЛЕЛЬНОГО ОБХОДА ===")
        self.logger.info(f"Обход: {crawl_stats['pages_crawled']} страниц, "
                        f"найдено {crawl_stats['images_found']} изображений, "
                        f"очередь: {crawl_stats['queue_size']}")
        self.logger.info(f"Фильтрация: скачано {filter_stats['downloaded']}, "
                        f"обработано {filter_stats['processed']}, "
                        f"отфильтровано {filter_stats['filtered_out']}")
        self.logger.info(f"Хранилище: использовано {filter_stats['folder_size_mb']:.1f} MB")
        
        # Подсчёт эффективности
        if filter_stats['downloaded'] > 0:
            success_rate = (filter_stats['processed'] / filter_stats['downloaded']) * 100
            self.logger.info(f"Доля успешно прошедших фильтры: {success_rate:.1f}%")
    
    def print_final_statistics(self):
        """Вывести финальную статистику и анализ «роста дерева»"""
        # Разорвать возможную компактную строку перед финальным блоком
        try:
            print()
        except Exception:
            pass
        crawl_stats = self.stats['crawling']
        filter_stats = self.stats['filtering']
        
        self.logger.info("=== ФИНАЛЬНАЯ СТАТИСТИКА ===")
        self.logger.info(f"Всего страниц обработано: {crawl_stats['pages_crawled']}")
        self.logger.info(f"Всего изображений обнаружено: {crawl_stats['images_found']}")
        self.logger.info(f"Скачано изображений: {filter_stats['downloaded']}")
        self.logger.info(f"Изображений прошло фильтры: {filter_stats['processed']}")
        self.logger.info(f"Изображений отфильтровано: {filter_stats['filtered_out']}")
        self.logger.info(f"Итоговый объём хранилища: {filter_stats['folder_size_mb']:.1f} MB")
        
        # Анализ «роста дерева»
        total_urls = len(self.visited_urls)
        self.logger.info(f"Всего уникальных URL обнаружено: {total_urls}")
        
        if crawl_stats['images_found'] > 0:
            images_per_page = crawl_stats['images_found'] / crawl_stats['pages_crawled']
            self.logger.info(f"Среднее количество изображений на страницу: {images_per_page:.2f}")
        
        if filter_stats['downloaded'] > 0:
            success_rate = (filter_stats['processed'] / filter_stats['downloaded']) * 100
            self.logger.info(f"Общая доля успешно прошедших фильтры: {success_rate:.1f}%")
    
    def shutdown(self):
        """Корректно завершить оба процесса"""
        # Разорвать компактную строку перед блоком завершения
        try:
            print()
        except Exception:
            pass
        self.logger.info("Завершение работы параллельных модулей...")
        
        if self.crawling_process and self.crawling_process.is_alive():
            self.crawling_process.terminate()
            timeout = self.config.get('crawling', {}).get('timeouts', {}).get('process_join_timeout', 10)
            self.crawling_process.join(timeout=timeout)
            if self.crawling_process.is_alive():
                self.crawling_process.kill()
        
        if self.filtering_process and self.filtering_process.is_alive():
            self.filtering_process.terminate()
            timeout = self.config.get('crawling', {}).get('timeouts', {}).get('process_join_timeout', 10)
            self.filtering_process.join(timeout=timeout)
            if self.filtering_process.is_alive():
                self.filtering_process.kill()
        
        # Отделить финальное сообщение от возможных потоковых обновлений
        try:
            print()
        except Exception:
            pass
        self.logger.info("Завершение выполнено")


def main():
    """Основная точка входа для параллельного краулера"""
    import sys
    
    if len(sys.argv) > 1:
        config_path = sys.argv[1]
    else:
        config_path = os.path.join(os.path.dirname(__file__), '..', '..', 'config.yaml')
    
    if not os.path.exists(config_path):
        print(f"Файл конфигурации не найден: {config_path}")
        sys.exit(1)
    
    manager = ParallelManager(config_path)
    manager.start()


if __name__ == "__main__":
    main()
