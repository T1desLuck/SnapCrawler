# Здесь определяются модели (Items) для извлечённых данных
#
# Документация:
# https://docs.scrapy.org/en/latest/topics/items.html

import scrapy


class SnapcrawlerItem(scrapy.Item):
    # Этот Item используется для хранения ссылок на изображения и результатов их обработки
    image_urls = scrapy.Field()
    images = scrapy.Field()
