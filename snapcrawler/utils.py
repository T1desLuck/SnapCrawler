"""Вспомогательные утилиты: выбор User-Agent, извлечение домена, джиттер задержки."""
from __future__ import annotations
import random
from urllib.parse import urlparse
from typing import Sequence


def pick_user_agent(agents: Sequence[str]) -> str:
    """Возвращает случайный User-Agent из списка, либо дефолтный браузерный UA."""
    if not agents:
        return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114 Safari/537.36"
    return random.choice(list(agents))


def domain_of(url: str) -> str:
    """Безопасно извлекает домен (host) из URL в нижнем регистре."""
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def jitter_delay(base: float) -> float:
    """Случайная задержка вокруг `base` (±50%), неотрицательная."""
    if base <= 0:
        return 0.0
    return max(0.0, random.uniform(0.5 * base, 1.5 * base))
