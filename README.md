<div align="center">

<h1>SnapCrawler</h1>

<p>
Мощный веб‑паук для поиска, скачивания и фильтрации изображений. Архитектура «древесного роста корней» + параллельные модули.
</p>

<p>
  <a href="https://github.com/T1desLuck/SnapCrawler"><img alt="Repo" src="https://img.shields.io/badge/GitHub-Repository-black?logo=github"></a>
  <a href="https://www.python.org/"><img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white"></a>
  <a href="https://scrapy.org/"><img alt="Scrapy" src="https://img.shields.io/badge/Scrapy-ready-60A839?logo=scrapy&logoColor=white"></a>
  <a href="https://playwright.dev/python/"><img alt="Playwright" src="https://img.shields.io/badge/Playwright-optional-2EAD33?logo=microsoftedge&logoColor=white"></a>
  <img alt="OS" src="https://img.shields.io/badge/OS-Windows%20|%20macOS%20|%20Linux-555">
</p>

<p>
  <a href="INSTRUCTIONS_RU.md#1-установка"><img alt="Install" src="https://img.shields.io/badge/Установка-быстрый%20старт-blue"></a>
  <a href="INSTRUCTIONS_RU.md#2-быстрый-старт"><img alt="Quick Start" src="https://img.shields.io/badge/Быстрый%20старт-run-success"></a>
  <a href="INSTRUCTIONS_RU.md#3-конфигурация-configyaml"><img alt="Config" src="https://img.shields.io/badge/Конфигурация-config.yaml-orange"></a>
  <a href="INSTRUCTIONS_RU.md#7-отладка"><img alt="Debug" src="https://img.shields.io/badge/Отладка-logs%20%26%20profiling-lightgrey"></a>
</p>

</div>

---

SnapCrawler — это продвинутый веб‑паук для автоматизированного поиска, скачивания и фильтрации изображений с веб‑сайтов. Реализует архитектуру «древесного роста корней» с параллельными модулями обхода и фильтрации согласно техническому заданию.

<details>
  <summary><b>Содержание</b></summary>

  - [🏗️ Архитектура](#-архитектура)
  - [✨ Основные возможности](#-основные-возможности)
  - [📖 Инструкции](#-инструкции)
  - [🏗️ Архитектурные особенности](#-архитектурные-особенности)
  - [📈 Производительность](#-производительность)
  - [Структура проекта](#структура-проекта)
  - [📁 Дерево проекта](#-дерево-проекта)
  - [Связь](#связь)
  - [Лицензия](#лицензия)

</details>

## 🏗️ Архитектура

**Двухмодульная параллельная архитектура:**
- **Crawling Module** — обход сайтов и поиск изображений
- **Filtering Module** — скачивание и фильтрация изображений
- **Parallel Manager** — координация модулей через multiprocessing

**Режимы работы:**
- `scrapy` — стандартный режим через Scrapy framework
- `parallel` — параллельная архитектура (как в ТЗ)

## ✨ Основные возможности

### 🕷️ Продвинутый обход сайтов
- **Древесный обход** с детекцией замыкания циклов
- **JavaScript рендеринг** через Playwright
- **Детекция дублей страниц** через MD5-хеширование
- **Статистика по глубинам** обхода

### 🖼️ Расширенное извлечение изображений (2025)
- **Responsive Images**: `<picture>`, `srcset`, адаптивные форматы (WebP/AVIF fallback)
- **Lazy Loading**: `loading="lazy"`, `data-src`, `data-lazy-src`, `data-original`
- **CSS Advanced**: `background-image`, `image-set()`, CSS custom properties
- **JavaScript/API**: fetch запросы, JSON payloads, WebSocket мониторинг
- **Hidden Images**: base64 data-URI, canvas рендеринг, shadow DOM
- **Network Capture**: перехват всех image-запросов через Playwright
- **Human Emulation**: скролл, клики, hover для раскрытия контента

### 🎯 Интеллектуальная фильтрация
- **Современные форматы**: AVIF, HEIC, JXL, WebP2 с автоконвертацией
- **AI-анализ**: качество изображений, content classification
- **Smart Processing**: автоматическая оптимизация и кроппинг
- **Advanced Filters**: размер, DPI, цветность, ориентация, aspect ratio
- **Дедупликация**: perceptual hashing (pHash) для точного поиска дублей
- **Watermark Detection**: OpenCV MSER с возможностью auto-inpainting
- **Quality Assessment**: метаданные, compression artifacts detection

### 🛡️ Обход защиты (Anti-Scraping 2025)
- **Advanced Fingerprinting**: спуфинг canvas, WebGL, audio отпечатков
- **Browser Emulation**: полная эмуляция реального браузера
- **Dynamic Throttling**: адаптивные задержки по server response
- **CAPTCHA Integration**: автоматическое решение через API сервисы
- **Stealth Navigation**: автоматическая детекция пагинации и sitemap
- **Human Behavior**: случайные движения мыши, realistic timing

### 📊 Управление ресурсами
- **Лимиты**: количество запросов, изображений, размер папки
- **Мониторинг**: статистика в реальном времени
- **Автоостановка**: при достижении лимитов
- **Компактное логирование**: краткая статистика в одной строке
- **Подробное логирование**: детальные логи для отладки

## 📖 Инструкции

Подробные разделы по установке, конфигурации, примерам использования, мониторингу, расширенным возможностям и отладке вынесены в отдельный файл:

- См. `INSTRUCTIONS_RU.md`

## 🏗️ Архитектурные особенности

### Древесный обход с AI-навигацией
- Начинает с seed URLs
- Извлекает все внутренние ссылки + автоматическая детекция пагинации
- Отслеживает новые ссылки по глубинам с ML-анализом релевантности
- Останавливается при замыкании (нет новых ссылок) или достижении лимитов
- Поддержка sitemap.xml и автоматического обнаружения навигационных паттернов

### Параллельная обработка с современными технологиями
```mermaid
flowchart LR
    A["Crawling Module<br/>Scrapy/Playwright<br/>+ Human Emulation"] -->|ссылки/URL изображений| Q[(Queue)]
    Q --> B["Filtering Module<br/>AI Analysis/Filters<br/>+ Modern Formats"]
    A -. статиcтика .-> S["Statistics<br/>Compact/Verbose"]
    B -. статиcтика .-> S
    S --> M["Parallel Manager"]
    N["Network Capture<br/>API/WebSocket"] --> A
    H["Hidden Images<br/>Canvas/Shadow DOM"] --> A
```

## 📈 Производительность

- **Параллельность**: до 8 потоков скачивания
- **Асинхронность**: неблокирующие операции
- **Память**: эффективное использование через очереди
- **Дисковое пространство**: контроль лимитов

 

## Структура проекта

- `snapcrawler/spiders/image_spider.py`: Основной код паука.
- `snapcrawler/pipelines.py`: Пайплайны для обработки и фильтрации изображений.
- `snapcrawler/middlewares.py`: Промежуточные обработчики для ротации User-Agent и прокси.
- `snapcrawler/settings.py`: Настройки Scrapy, которые загружают конфигурацию из `config.yaml`.
- `config.yaml`: Главный конфигурационный файл.
- `requirements.txt`: Список зависимостей Python.
- `scrapy.cfg`: Файл конфигурации Scrapy.
- `test_runner.py`: Единый тестовый раннер (список команд, проверки окружения, сводка конфига, юнит‑проверки, smoke‑запуски Scrapy/parallel).

## 📁 Дерево проекта

```text
SnapCrawler/                                     - Корень проекта
├─ README.md                                     - Обзор проекта и архитектуры
├─ INSTRUCTIONS_RU.md                            - Подробные инструкции по установке/настройке/запуску
├─ LICENSE                                       - Лицензия проекта (Proprietary)
├─ config.yaml                                   - Главный конфигурационный файл (режимы, лимиты, фильтры, прокси)
├─ requirements.txt                              - Список Python-зависимостей
├─ run_parallel.py                               - Запуск параллельной архитектуры (manager + модули)
├─ scrapy.cfg                                    - Конфигурация Scrapy
├─ snapcrawler.log                               - Лог-файл выполнения (создается автоматически)
├─ test_runner.py                                - Единый тестовый раннер (CLI для проверок и smoke-тестов)
├─ downloads/                                    - Каталог загрузок (указывается в general.output_dir)
│  ├─ raw/                                       - Сырые изображения (до фильтрации)
│  └─ processed/                                 - Отфильтрованные и принятые изображения
└─ snapcrawler/                                  - Пакет Python с исходниками паука
   ├─ __init__.py                                - Инициализация пакета
   ├─ items.py                                   - Описание Item-структур (если используется в Scrapy)
   ├─ middlewares.py                             - Scrapy middlewares (UA/прокси и пр.)
   ├─ middlewares_advanced.py                    - Продвинутые middlewares (fingerprint spoofing, stealth)
   ├─ middlewares_modern.py                      - Современные middlewares (2025 stealth capabilities)
   ├─ pipelines.py                               - Scrapy pipelines (обработка после скачивания)
   ├─ settings.py                                - Настройки Scrapy (чтение config.yaml, параметры фреймворка)
   ├─ core/                                      - Ядро параллельной архитектуры (ТЗ)
   │  ├─ __init__.py                             - Инициализация подмодуля core
   │  ├─ crawling_module.py                      - Модуль обхода: извлечение ссылок/изображений, статистика
   │  ├─ filtering_module.py                     - Модуль фильтрации: скачивание, фильтры, дедупликация, метрики
   │  ├─ parallel_manager.py                     - Оркестратор процессов, очереди и сбор финальной статистики
   │  ├─ human_emulation.py                      - Эмуляция человеческого поведения: скролл, клики, движения мыши
   │  ├─ human_emulation_backup.py               - Резервная копия модуля эмуляции (backup)
   │  ├─ human_emulation_fixed.py                - Исправленная версия модуля эмуляции (fixed)
   │  ├─ advanced_formats.py                     - Поддержка AVIF, HEIC, JXL, AI-анализ изображений
   │  ├─ navigation_module.py                    - Автоматическая навигация: пагинация, sitemap, ML-анализ
   │  └─ network_capture.py                      - Захват сетевого трафика: API responses, WebSocket monitoring
   ├─ spiders/                                   - Пауки Scrapy
   │  ├─ __init__.py                             - Инициализация подмодуля spiders
   │  └─ image_spider.py                         - Основной паук: логика обхода и извлечения изображений
   └─ utils/                                     - Утилиты и вспомогательные модули
      ├─ __init__.py                             - Инициализация подмодуля utils
      ├─ log_formatter.py                        - Форматирование логов/статусов, удобный вывод
      └─ svg_processor.py                        - Обработка и конвертация SVG (CairoSVG/Wand), извлечение размеров
```

## Связь

- GitHub: https://github.com/T1desLuck
- Email: <tidesluck@icloud.com>

## Лицензия

[SnapCrawler License (Proprietary)](LICENSE)

Кратко о ключевых условиях:
- Использование только в неизменном виде; модификации и производные работы запрещены.
- Перераспространение допускается только некоммерчески, без изменений, с сохранением лицензии и указанием автора (GitHub и e‑mail).
- Коммерческое использование, сублицензирование, публикация кода, размещение как сервис — только по письменному разрешению правообладателя.
