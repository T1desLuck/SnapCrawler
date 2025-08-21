import yaml
import os

# ==============================================================================
# КОНФИГУРАЦИЯ ПРОЕКТА
# ==============================================================================

# Загружаем файл пользовательской конфигурации
CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')
with open(CONFIG_PATH, 'r') as f:
    config = yaml.safe_load(f)

# Делаем конфиг доступным глобально в Scrapy
SNAPCRAWLER_CONFIG = config

# ==============================================================================
# БАЗОВЫЕ НАСТРОЙКИ SCRAPY
# ==============================================================================

BOT_NAME = "snapcrawler"
SPIDER_MODULES = ["snapcrawler.spiders"]
NEWSPIDER_MODULE = "snapcrawler.spiders"

# ==============================================================================
# ПОЛИТИКА СКАНИРОВАНИЯ (из config.yaml)
# ==============================================================================

# Настраиваем User-Agent из конфига
if config['crawling']['stealth_mode'] and config['crawling']['user_agents']:
    USER_AGENTS = config['crawling']['user_agents']
else:
    USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36'

ROBOTSTXT_OBEY = config['crawling']['respect_robots_txt']

# ==============================================================================
# ПАРАЛЛЕЛИЗМ И ДРОССЕЛИРОВАНИЕ (из config.yaml)
# ==============================================================================

CONCURRENT_REQUESTS = config['crawling']['max_threads']
DOWNLOAD_DELAY = config['crawling']['request_delay']
# CONCURRENT_REQUESTS_PER_DOMAIN = config['crawling']['max_threads'] # Можно включить при необходимости

# Расширение AutoThrottle
AUTOTHROTTLE_ENABLED = config['crawling']['auto_throttle']
AUTOTHROTTLE_START_DELAY = 5
AUTOTHROTTLE_MAX_DELAY = 60
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0
AUTOTHROTTLE_DEBUG = False # Поставьте True для отладки

# ==============================================================================
# ПОСРЕДНИКИ ЗАГРУЗЧИКА (DOWNLOADER MIDDLEWARES) (из config.yaml)
# ==============================================================================

DOWNLOADER_MIDDLEWARES = {
    'scrapy.downloadermiddlewares.useragent.UserAgentMiddleware': None,  # Отключаем стандартный
}

# Условно включаем stealth и рендеринг JS
if config['crawling']['stealth_mode']:
    if config['crawling'].get('user_agents'):
        DOWNLOADER_MIDDLEWARES['snapcrawler.middlewares.RotateUserAgentMiddleware'] = 400
    if config['crawling'].get('proxies'):
        DOWNLOADER_MIDDLEWARES['snapcrawler.middlewares.ProxyMiddleware'] = 350

# Всегда включаем RetryMiddleware для надёжности
DOWNLOADER_MIDDLEWARES['scrapy.downloadermiddlewares.retry.RetryMiddleware'] = 550
DOWNLOADER_MIDDLEWARES['snapcrawler.middlewares.AdaptiveDelayMiddleware'] = 585
DOWNLOADER_MIDDLEWARES['snapcrawler.middlewares.CaptchaDetectionMiddleware'] = 590
DOWNLOADER_MIDDLEWARES['snapcrawler.middlewares.AjaxInterceptorMiddleware'] = 595
RETRY_TIMES = 3
RETRY_HTTP_CODES = [500, 502, 503, 504, 408, 429]

if config['crawling']['js_enabled']:
    DOWNLOADER_MIDDLEWARES['scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler'] = 900

# ==============================================================================
# РЕСУРСНЫЕ ЛИМИТЫ (из config.yaml)
# ==============================================================================

CLOSESPIDER_ITEMCOUNT = config.get('limits', {}).get('max_images', 0)
CLOSESPIDER_REQUESTCOUNT = config.get('crawling', {}).get('max_requests', 0)

# ==============================================================================
# ПАЙПЛАЙНЫ ЭЛЕМЕНТОВ (ITEM PIPELINES) (из config.yaml)
# ==============================================================================

# Динамически настраиваем пайплайны на основе config.yaml
ITEM_PIPELINES = {}

# Используем только наш кастомный пайплайн для загрузки и фильтрации изображений
# Встроенный ImagesPipeline отключён из-за особенностей работы с бинарным контентом
ITEM_PIPELINES['snapcrawler.pipelines.ImageFilteringPipeline'] = 1

# Настройки для корректной обработки бинарного контента
IMAGES_RESULT_FIELD = 'images'
IMAGES_URLS_FIELD = 'image_urls'

# Принудительно перезагружать все изображения
IMAGES_EXPIRES = 0

IMAGES_STORE = os.path.join(os.path.dirname(__file__), '..', '..', config['general']['output_dir'], 'raw')

# ==============================================================================
# НАСТРОЙКИ PLAYWRIGHT (для рендеринга JS)
# ==============================================================================

TWISTED_REACTOR = 'twisted.internet.asyncioreactor.AsyncioSelectorReactor'
DOWNLOAD_HANDLERS = {
    "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
}

PLAYWRIGHT_BROWSER_TYPE = 'chromium'
PLAYWRIGHT_LAUNCH_OPTIONS = {
    'headless': True
}

# ==============================================================================
# ЛОГИРОВАНИЕ И ПРОЧИЕ НАСТРОЙКИ
# ==============================================================================

LOG_LEVEL = config['general']['log_level'].upper()
FEED_EXPORT_ENCODING = "utf-8"
