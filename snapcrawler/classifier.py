"""Классификатор фото/не‑фото на базе ONNXRuntime (CPU).

`PhotoClassifier` загружает модель ONNX, подготавливает вход (224×224, NCHW),
и возвращает уверенность, что кадр является фотографией. Если модель/onnxruntime
недоступны или отключены через конфиг — классификация пропускается.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from pathlib import Path
import urllib.request
import os
import numpy as np
from PIL import Image

from .logging_setup import get_logger

try:
    import onnxruntime as ort  # type: ignore
except Exception:  # pragma: no cover
    ort = None  # type: ignore


@dataclass
class ClassifierConfig:
    enable: bool
    model_path: str
    batch_size: int
    threshold: float
    auto_download: bool = False
    download_url: str = ""


class PhotoClassifier:
    def __init__(self, cfg: ClassifierConfig) -> None:
        self.cfg = cfg
        self._session: Optional["ort.InferenceSession"] = None
        self._input_name: Optional[str] = None
        self._output_name: Optional[str] = None
        self._ready: bool = False
        self._init_model()

    @property
    def enabled(self) -> bool:
        return self._ready and self.cfg.enable

    def _init_model(self) -> None:
        log = get_logger()
        if not self.cfg.enable:
            log.info("Классификатор отключён в конфиге.")
            return
        if ort is None:
            log.warning("onnxruntime недоступен; классификатор будет отключён.")
            return
        # Anchor model path to project root if relative
        project_root = Path(__file__).resolve().parents[1]
        mp = Path(self.cfg.model_path)
        if not mp.is_absolute():
            mp = (project_root / mp).resolve()
        if not mp.exists():
            # Попытаться авто-загрузить, если разрешено и задан URL
            if self.cfg.auto_download and self.cfg.download_url:
                try:
                    mp.parent.mkdir(parents=True, exist_ok=True)
                    log.info("Загружаю модель из %s -> %s", self.cfg.download_url, mp)
                    tmp_path = mp.with_suffix(mp.suffix + ".part")
                    urllib.request.urlretrieve(self.cfg.download_url, tmp_path)
                    os.replace(tmp_path, mp)
                    log.info("Модель сохранена: %s", mp)
                except Exception as e:
                    log.warning("Не удалось скачать модель: %s", e)
                    return
            else:
                log.warning("Файл модели не найден: %s; классификатор будет отключён.", mp)
                return
        try:
            sess_opts = ort.SessionOptions()
            sess_opts.intra_op_num_threads = 1
            sess_opts.inter_op_num_threads = 1
            self._session = ort.InferenceSession(str(mp), sess_options=sess_opts, providers=["CPUExecutionProvider"])  # type: ignore
            inputs = self._session.get_inputs()
            outputs = self._session.get_outputs()
            self._input_name = inputs[0].name
            self._output_name = outputs[0].name
            self._ready = True
            log.info("Классификатор инициализирован: %s", mp)
        except Exception as e:
            log.warning("Не удалось инициализировать классификатор: %s", e)
            self._session = None
            self._ready = False

    def _preprocess(self, im: Image.Image) -> np.ndarray:
        # Изменяем размер до 224x224, нормируем в [0,1], формат NCHW
        im_resized = im.resize((224, 224))
        arr = np.asarray(im_resized, dtype=np.float32) / 255.0
        # Простая нормализация; при необходимости адаптируйте под статистики ImageNet
        arr = np.transpose(arr, (2, 0, 1))  # HWC->CHW
        arr = np.expand_dims(arr, 0)  # NCHW
        return arr

    def is_photo(self, im: Image.Image) -> Optional[float]:
        if not self.enabled:
            return None
        assert self._session is not None and self._input_name is not None and self._output_name is not None
        x = self._preprocess(im)
        try:
            out = self._session.run([self._output_name], {self._input_name: x})[0]
            # Предполагается выход формы [N, 2] — softmax: [не‑фото, фото]
            if out.ndim == 2 and out.shape[1] >= 2:
                score = float(out[0, 1])
            else:
                # Запасной вариант: бинарный выход сигмоиды (один канал)
                score = float(out.ravel()[0])
            return score
        except Exception:
            return None
