<div align="center">

<h1>Инструкции по SnapCrawler</h1>

<p>
Практическое руководство: установка, запуск, конфигурация, примеры, мониторинг, отладка и расширенные возможности.
</p>

<p>
  <a href="#1-установка"><img alt="Install" src="https://img.shields.io/badge/Установка-локально%20%7C%20Vast.ai%20%7C%20Colab-blue"></a>
  <a href="#2-быстрый-старт"><img alt="Quick Start" src="https://img.shields.io/badge/Быстрый%20старт-run-success"></a>
  <a href="#3-конфигурация-configyaml"><img alt="Config" src="https://img.shields.io/badge/Конфигурация-config.yaml-orange"></a>
  <a href="#7-отладка"><img alt="Debug" src="https://img.shields.io/badge/Отладка-logs%20%26%20profiling-lightgrey"></a>
</p>

</div>

---

Для общего обзора архитектуры и возможностей смотрите `README.md`.

## Навигация

<details>
  <summary><b>Оглавление</b></summary>

  - По обзору (README):
    - [Архитектура](README.md#архитектура)
    - [Основные возможности](README.md#основные-возможности)
    - [Инструкции (ссылка на этот файл)](README.md#инструкции)
    - [Архитектурные особенности](README.md#архитектурные-особенности)
    - [Производительность](README.md#производительность)
    - [Структура проекта](README.md#структура-проекта)
    - [Дерево проекта](README.md#дерево-проекта)

  - По этому документу:
    - [1) Установка](#1-установка)
      - [1.1 Локально (по умолчанию)](#11-локально-по-умолчанию)
      - [1.2 Установка и запуск на Vast.ai](#12-установка-и-запуск-на-vastai)
      - [1.3 Установка и запуск в Google Colab](#13-установка-и-запуск-в-google-colab)
    - [2) Быстрый старт](#2-быстрый-старт)
    - [3) Конфигурация (configyaml)](#3-конфигурация-configyaml)
    - [4) Примеры конфигураций](#4-примеры-конфигураций)
    - [5) Мониторинг и статистика](#5-мониторинг-и-статистика)
    - [6) Расширенные возможности](#6-расширенные-возможности)
    - [7) Отладка](#7-отладка)
    - [8) Запуск (коротко)](#8-запуск-коротко)
    - [9) Разработка и расширение](#9-разработка-и-расширение)
    - [10) Тестовый раннер (test_runnerpy)](#10-тестовый-раннер-test_runnerpy)

</details>
 

## 1) Установка

### 1.1 Локально (по умолчанию)

1. Клонируйте репозиторий:
```bash
git clone https://github.com/T1desLuck/SnapCrawler.git
cd SnapCrawler
```

2. Создайте и активируйте виртуальное окружение:
```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate
```

3. Установите зависимости:
```bash
pip install -r requirements.txt
```

4. Установите Playwright (для JS-рендеринга):
```bash
playwright install chromium
```

### 1.2 Установка и запуск на Vast.ai

Ниже приведён базовый сценарий для запуска в арендованном инстансе Vast.ai (GPU/CPU подойдёт; если нужен рендеринг JS — берите образ с браузером или установите Playwright).

#### A. Подготовка инстанса
- Выберите образ на базе Ubuntu с предустановленным Python (например, pytorch/pytorch) или любой совместимый.
- Включите SSH-доступ и (по желанию) смонтируйте папку для данных (downloads) как volume.

#### B. Установка зависимостей
```bash
# Обновление пакетов (опционально)
sudo apt-get update -y

# Установка git и системных зависимостей
sudo apt-get install -y git

# Клонирование проекта
git clone https://github.com/T1desLuck/SnapCrawler.git
cd SnapCrawler

# Виртуальное окружение (рекомендуется)
python -m venv venv && source venv/bin/activate

# Python-зависимости
pip install -r requirements.txt

# Playwright (для JS-рендеринга)
playwright install chromium
```

#### C. Конфигурация и запуск
```bash
# Отредактируйте конфиг
nano config.yaml

# Scrapy режим
python -m scrapy crawl image_spider

# Параллельный режим (архитектура ТЗ)
python run_parallel.py
```

Примечания:
- Если нужен headless-режим Chromium по умолчанию — Playwright уже запускается без UI.
- Для использования прокси укажите их в `crawling.proxies`.

> [!TIP]
> Смонтируйте volume к каталогу проекта `downloads/` для сохранения результатов между перезапусками контейнера/инстанса.

### 1.3 Установка и запуск в Google Colab

В Colab удобно запускать пайплайн без локальной установки. Ниже пример минимальных ячеек.

#### A. Установка и клонирование
```python
# В ячейке Colab
!git clone https://github.com/T1desLuck/SnapCrawler.git
%cd SnapCrawler
!pip install -r requirements.txt
!playwright install chromium
```

Опционально подключите Google Drive для сохранения результатов:
```python
from google.colab import drive
drive.mount('/content/drive')

# Пример: сменить директорию вывода на Google Drive
import yaml
cfg = yaml.safe_load(open('config.yaml', 'r'))
cfg['general']['output_dir'] = '/content/drive/MyDrive/snapcrawler_downloads'
yaml.safe_dump(cfg, open('config.yaml', 'w'), allow_unicode=True)
```

#### B. Запуск
```python
# Scrapy (через шебанг в Colab)
!python -m scrapy crawl image_spider -s LOG_LEVEL=INFO

# Параллельный режим
!python run_parallel.py
```

Советы:
- Для долгих задач используйте screen/tmux на сервере, а в Colab — планируйте время сессии.
- Если сайты требуют JS-рендеринг: убедитесь, что `js_enabled: true` в `crawling` и Playwright установлен.
> [!NOTE]
> В Colab браузер запускается в headless-режиме. Графический интерфейс не требуется.

## 2) Быстрый старт

### Стандартный режим (Scrapy)
```bash
# Запуск с настройками по умолчанию
python -m scrapy crawl image_spider

# Запуск с кастомной конфигурацией
# Внимание: Scrapy читает конфигурацию из файла `config.yaml` в корне проекта.
# Чтобы использовать свой файл, временно замените его на ваш (Windows):
copy my_config.yaml config.yaml
python -m scrapy crawl image_spider
```

### Параллельный режим (архитектура из ТЗ)
```bash
# Запуск параллельных модулей
python run_parallel.py

# Запуск с пользовательским конфигом
python run_parallel.py custom_config.yaml
```

## 3) Конфигурация (config.yaml)

Основные секции:
```yaml
# Режим работы
general:
  mode: 'scrapy'  # или 'parallel'
  output_dir: 'downloads'
  log_level: 'info'
  verbose_logging: false  # true = детальные логи, false = компактная статистика

# Настройки обхода
crawling:
  start_urls:
    - https://example.com
  max_depth: 5
  js_enabled: true
  stealth_mode: true
  intercept_ajax: true
  infinite_scroll: true

# Фильтрация изображений
images:
  min_side_size: 200
  formats: ['jpg', 'png', 'webp']
  deduplication: true
  allow_watermarks: false
```

## 4) Примеры конфигураций

### Фотостоки (Unsplash, Pexels) - 2025
```yaml
crawling:
  start_urls: ['https://unsplash.com/t/nature']
  stealth_mode: true
  js_enabled: true
  human_emulation:
    enabled: true
    scroll_speed: 800
    max_interactions: 30
  network_capture:
    enabled: true
    capture_json: true
  hidden_images:
    enabled: true

images:
  min_side_size: 1920
  formats: ['jpg', 'webp', 'avif', 'heic']
  ai_optimization:
    enabled: true
    content_analysis: true
```

### Интернет‑магазины
```yaml
crawling:
  start_urls: ['https://shop.example.com/catalog']
  max_depth: 3
  js_enabled: true

images:
  min_side_size: 500
  aspect_ratio_min: 0.5
  aspect_ratio_max: 2.0
  allow_logos_banners: false
```

### Новостные сайты
```yaml
crawling:
  start_urls: ['https://news.example.com']
  max_depth: 2
  infinite_scroll: true

images:
  min_side_size: 300
  color_mode: 'color'
  deduplication: true
```

## 5) Мониторинг и статистика

### Компактная статистика (по умолчанию)
При `verbose_logging: false` отображается одна обновляющаяся строка:
```
Страниц: 156 | Найдено: 1247 | Не пройдено: 66 | Загружено: 300 | Сохранено: 234 | Вес папки: 512.0MB | Ошибка: Нет
```

### Подробные логи (для отладки)
При `verbose_logging: true` выводятся детальные логи:
```
[crawling_module] INFO: Обход: 120 страниц, найдено 850 изображений, очередь: 34
[filtering_module] INFO: ✅ [image123.jpg] Прошел все фильтры: (1920, 1080), RGB
[filtering_module] INFO: ❌ [banner.png] Дубликат по perceptual hash
[parallel_manager] INFO: Доля успешно прошедших фильтры: 59.3%
```

### Переключение режимов логирования
```yaml
general:
  verbose_logging: false  # Компактная статистика (рекомендуется)
  verbose_logging: true   # Детальные логи (для отладки)
```

## 6) Расширенные возможности (2025)

### Эмуляция человеческого поведения
```yaml
crawling:
  human_emulation:
    enabled: true
    scroll_speed: 1000  # пикселей в секунду
    click_delay: [1.0, 3.0]  # диапазон задержек
    max_interactions: 50  # лимит взаимодействий на страницу
```

### Захват сетевого трафика
```yaml
crawling:
  network_capture:
    enabled: true
    capture_json: true  # API responses
    capture_websockets: false  # WebSocket сообщения
    max_captured_urls: 1000
```

### Извлечение скрытых изображений
```yaml
crawling:
  hidden_images:
    enabled: true
    extract_base64: true  # data-URI
    extract_canvas: true  # canvas элементы
    extract_shadow_dom: true  # shadow DOM
```

### Современные форматы изображений
```yaml
images:
  ai_optimization:
    enabled: true
    enhance_quality: false
    smart_cropping: false
    content_analysis: true
  formats: ['jpg', 'png', 'webp', 'avif', 'heic', 'jxl']
```

### Advanced Anti-Scraping
```yaml
crawling:
  stealth_mode: true
  captcha_api_key: 'your_2captcha_key'
  proxies:
    - 'http://user:pass@proxy1:8000'
    - 'http://user:pass@proxy2:8000'
```

## 7) Отладка

### Включение подробных логов
```yaml
# В config.yaml
general:
  verbose_logging: true  # Включить детальные логи
  log_level: 'debug'     # Максимальная детализация
```

### Scrapy отладка
```bash
# Детальные логи (через параметр Scrapy)
python -m scrapy crawl image_spider -s LOG_LEVEL=DEBUG

# Профилирование памяти
python -m scrapy crawl image_spider -s MEMUSAGE_ENABLED=True
```

### Анализ проблем
- **Компактная статистика не обновляется**: проверьте `verbose_logging: false` в config.yaml
- **Слишком много логов**: установите `verbose_logging: false` для краткого вывода
- **Ошибки фильтрации**: включите `verbose_logging: true` для детального анализа

## 8) Запуск (коротко)

Смотрите раздел [2) Быстрый старт](#2-быстрый-старт) для команд запуска (Scrapy и параллельный режим).

> [!TIP]
> Результаты сохраняются в `general.output_dir` (по умолчанию `downloads/processed/`).

## 9) Разработка и расширение

### Кастомные фильтры
```python
class CustomFilter:
    def is_valid_image(self, img_path, img_obj):
        # Ваша логика фильтрации
        return True
```

### Кастомные источники
```python
class CustomSpider(ImageSpider):
    def extract_custom_images(self, response):
        # Специфичная логика для сайта
        return image_urls
```

## 10) Тестовый раннер (test_runner.py)

Единый тестовый файл `test_runner.py` в корне проекта. Не требует изменений кода, использует только стандартную библиотеку и существующие интерфейсы. Нужен для быстрой проверки среды, конфигурации и smoke‑запусков.

Основные команды:

- list — список команд с краткими описаниями и примерами
- env:check — проверка структуры и базовых зависимостей
- config:print — печать краткой сводки из `config.yaml`
- unit:crawling_module — локальная проверка извлечения изображений/ссылок на HTML-примере
- smoke:spider — короткий запуск паука Scrapy с лимитами
- smoke:parallel — короткий запуск параллельной архитектуры (`run_parallel.py`)

Примеры (Windows PowerShell):

```powershell
python test_runner.py list
python test_runner.py env:check
python test_runner.py config:print --config config.yaml
python test_runner.py unit:crawling_module
python test_runner.py smoke:spider --timeout 60 --log INFO --item-limit 1 --depth 1
python test_runner.py smoke:parallel --timeout 60 --config config.yaml
```

Подсказки:

- Для оффлайн-режима (без сети) добавьте флаг `--offline` к smoke‑командам.
- Если в консоли отображаются «кракозябры», переключите кодировку на UTF‑8:
  - PowerShell 7+: `$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()`
  - PowerShell 5: `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8`
  - CMD: `chcp 65001`
  - Или используйте Windows Terminal.
