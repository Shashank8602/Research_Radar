"""CPU embeddings via FastEmbed (no hosted embedding cost)."""

from __future__ import annotations

from functools import lru_cache

import numpy as np

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"


@lru_cache(maxsize=2)
def _model(name: str):
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=name)


def embed_texts(texts: list[str], model: str = DEFAULT_MODEL) -> np.ndarray:
    """Return an (n, dim) float32 array of L2-normalised embeddings."""
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)
    vecs = np.array(list(_model(model).embed(texts)), dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs / np.clip(norms, 1e-12, None)


def item_text(title: str, snippet: str, max_chars: int = 1000) -> str:
    return f"{title}. {snippet[:max_chars]}".strip()
