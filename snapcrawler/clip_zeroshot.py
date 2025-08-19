"""Zero-shot photo vs non-photo scoring using CLIP ViT-B/32 ONNX.

Downloads the ONNX model and tokenizer from HuggingFace (once) and runs
logits_per_image over a set of text prompts. Returns a probability-like
score that the image is a real photo.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import numpy as np
from PIL import Image

try:
    import onnxruntime as ort  # type: ignore
except Exception:
    ort = None  # type: ignore

try:
    from huggingface_hub import hf_hub_download  # type: ignore
except Exception:
    hf_hub_download = None  # type: ignore

try:
    from tokenizers import Tokenizer  # type: ignore
except Exception:
    Tokenizer = None  # type: ignore

from .logging_setup import get_logger


_CLIP_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
_CLIP_STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)


@dataclass
class ClipConfig:
    repo_id: str = "openai/clip-vit-base-patch32"
    model_filename: str = "onnx/model.onnx"
    tokenizer_filename: str = "tokenizer.json"
    cache_dir: str = "./models/clip"
    prompts: List[str] = None  # type: ignore
    positive_index: int = 0

    def __post_init__(self) -> None:
        if self.prompts is None:
            self.prompts = [
                "a photo",
                "a painting",
                "an illustration",
                "a 3D render",
                "AI generated image",
                "a cartoon",
            ]
            self.positive_index = 0


class ClipZeroShot:
    def __init__(self, cfg: ClipConfig) -> None:
        self.cfg = cfg
        self._log = get_logger()
        self._session = None
        self._tokenizer = None
        self._ready = False
        self._init()

    @property
    def enabled(self) -> bool:
        return self._ready

    def _init(self) -> None:
        if ort is None:
            self._log.warning("onnxruntime недоступен; CLIP-постфильтр отключён.")
            return
        if hf_hub_download is None or Tokenizer is None:
            self._log.warning("huggingface_hub/tokenizers недоступны; CLIP-постфильтр отключён.")
            return
        cache_dir = Path(self.cfg.cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            model_path = hf_hub_download(
                repo_id=self.cfg.repo_id, filename=self.cfg.model_filename, cache_dir=str(cache_dir)
            )
            tok_path = hf_hub_download(
                repo_id=self.cfg.repo_id, filename=self.cfg.tokenizer_filename, cache_dir=str(cache_dir)
            )
        except Exception as e:
            self._log.warning("Не удалось скачать файлы CLIP: %s", e)
            return
        try:
            sess_opts = ort.SessionOptions()
            sess_opts.intra_op_num_threads = 1
            sess_opts.inter_op_num_threads = 1
            self._session = ort.InferenceSession(str(model_path), sess_options=sess_opts, providers=["CPUExecutionProvider"])  # type: ignore
        except Exception as e:
            self._log.warning("Не удалось инициализировать ONNX CLIP: %s", e)
            self._session = None
            return
        # Resolve I/O names dynamically
        try:
            self._in_names = {i.name: i for i in self._session.get_inputs()}  # type: ignore
            self._out_names = {o.name: o for o in self._session.get_outputs()}  # type: ignore
            # Heuristic mapping
            self._name_pixel = self._pick_name(self._in_names.keys(), ["pixel_values", "pixel", "image", "images"])  # type: ignore
            self._name_input_ids = self._pick_name(self._in_names.keys(), ["input_ids", "input", "text_input_ids"])  # type: ignore
            self._name_attn = self._pick_name(self._in_names.keys(), ["attention_mask", "attn_mask", "attention"])  # type: ignore
            self._name_logits = self._pick_name(self._out_names.keys(), ["logits_per_image", "logits", "output", "probs"])  # type: ignore
            if not (self._name_pixel and self._name_input_ids and self._name_attn and self._name_logits):
                self._log.warning("Не удалось сопоставить имена входов/выходов CLIP-ONNX; отключаем.")
                self._session = None
                return
        except Exception as e:
            self._log.warning("Ошибка при определении I/O имён CLIP: %s", e)
            self._session = None
            return
        try:
            self._tokenizer = Tokenizer.from_file(tok_path)
        except Exception as e:
            self._log.warning("Не удалось загрузить tokenizer: %s", e)
            self._session = None
            return
        self._ready = True
        self._log.info("CLIP ONNX готов: %s", model_path)

    def _preprocess_image(self, im: Image.Image) -> np.ndarray:
        # Resize to 224x224 with bicubic, normalize with CLIP mean/std, NCHW
        im = im.convert("RGB").resize((224, 224), Image.BICUBIC)
        arr = np.asarray(im, dtype=np.float32) / 255.0
        arr = (arr - _CLIP_MEAN) / _CLIP_STD
        arr = np.transpose(arr, (2, 0, 1))  # HWC -> CHW
        arr = np.expand_dims(arr, 0)  # NCHW
        return arr

    def _tokenize(self, texts: List[str]) -> Tuple[np.ndarray, np.ndarray]:
        assert self._tokenizer is not None
        encs = [self._tokenizer.encode(t) for t in texts]
        max_len = min(77, max(e.n_tokens for e in encs))
        input_ids = np.zeros((len(encs), max_len), dtype=np.int64)
        attention_mask = np.zeros((len(encs), max_len), dtype=np.int64)
        for i, e in enumerate(encs):
            ids = np.array(e.ids[:max_len], dtype=np.int64)
            att = np.ones_like(ids, dtype=np.int64)
            input_ids[i, : len(ids)] = ids
            attention_mask[i, : len(ids)] = att
        return input_ids, attention_mask

    def photo_score(self, im: Image.Image) -> float:
        if not self.enabled:
            return 0.5
        assert self._session is not None
        pixel_values = self._preprocess_image(im)
        input_ids, attention_mask = self._tokenize(self.cfg.prompts)
        # Broadcast image to match text batch if necessary handled by model as separate axes
        try:
            outputs = self._session.run(
                [self._name_logits],
                {
                    self._name_input_ids: input_ids,
                    self._name_attn: attention_mask,
                    self._name_pixel: pixel_values,
                },
            )
            logits = outputs[0]  # shape: [1, num_prompts]
            logits = np.asarray(logits, dtype=np.float32).reshape(-1)
            # Softmax over prompts to get probability-like scores
            exps = np.exp(logits - float(np.max(logits)))
            probs = exps / np.sum(exps)
            p_photo = float(probs[self.cfg.positive_index])
            return p_photo
        except Exception:
            return 0.5

    @staticmethod
    def _pick_name(names, candidates: List[str]) -> str:
        low = {n.lower(): n for n in names}
        for c in candidates:
            if c.lower() in low:
                return low[c.lower()]
        # fallback: partial match
        for n in names:
            for c in candidates:
                if c.lower() in n.lower():
                    return n
        return ""
