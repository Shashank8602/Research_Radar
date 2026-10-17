"""CPU embeddings via FastEmbed (no hosted embedding cost)."""

from __future__ import annotations

from functools import lru_cache

import numpy as np

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"


@lru_cache(maxsize=2)
def _model(name: str):
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=name)


def embed_texts(
    texts: list[str], model: str = DEFAULT_MODEL, batch_size: int | None = None
) -> np.ndarray:
    """Return an (n, dim) float32 array of L2-normalised embeddings.

    `batch_size` defaults to FastEmbed's 256, which spikes memory to ~2 GB on a long paper; the
    deep-dive app passes a small value so it fits a 512 MB free host."""
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)
    kwargs = {"batch_size": batch_size} if batch_size else {}
    vecs = np.array(list(_model(model).embed(texts, **kwargs)), dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs / np.clip(norms, 1e-12, None)


def as_list(emb) -> list[float]:
    """pgvector returns Vector objects; freshly computed embeddings are numpy arrays."""
    if hasattr(emb, "to_list"):
        return [float(x) for x in emb.to_list()]
    return [float(x) for x in emb]


def item_text(title: str, snippet: str, max_chars: int = 1000) -> str:
    return f"{title}. {snippet[:max_chars]}".strip()
