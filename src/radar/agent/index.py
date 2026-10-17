"""Throwaway in-memory chunk index: split a document, embed, return the best passages for a question."""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from radar.agent.tools import Doc
from radar.embed import embed_texts

CHUNK_CHARS = 900
OVERLAP_CHARS = 150
EMBED_BATCH = 4  # small batches keep peak memory near 300 MB instead of ~2 GB (see D-049)


@dataclass
class Chunk:
    id: int  # 1-based; the number the model cites as [n]
    text: str
    page: int | None = None  # PDF page number (1-based), else None


def split_text(text: str, size: int = CHUNK_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    """Greedy paragraph/sentence packing into ~size-char chunks with a small overlap."""
    pieces = [s for s in re.split(r"(?<=[.!?])\s+|\n{2,}", text) if s and s.strip()]
    chunks: list[str] = []
    cur = ""
    for piece in pieces:
        piece = piece.strip()
        while len(piece) > size:  # a single run-on piece: hard split
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(piece[:size])
            piece = piece[size - overlap:]
        if cur and len(cur) + len(piece) + 1 > size:
            chunks.append(cur)
            cur = cur[-overlap:] + " " + piece if overlap else piece
        else:
            cur = f"{cur} {piece}".strip()
    if cur.strip():
        chunks.append(cur)
    return chunks


def chunk_doc(doc: Doc) -> list[Chunk]:
    chunks: list[Chunk] = []
    for page_no, page in enumerate(doc.pages, start=1):
        for part in split_text(page):
            chunks.append(Chunk(id=len(chunks) + 1, text=part, page=page_no if doc.kind == "pdf" else None))
    return chunks


class Index:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self._vecs = embed_texts([c.text for c in chunks], batch_size=EMBED_BATCH) if chunks else np.zeros((0, 0))

    def search(self, query: str, k: int = 6) -> list[Chunk]:
        if not self.chunks:
            return []
        q = embed_texts([query])[0]
        order = np.argsort(-(self._vecs @ q))[:k]
        return [self.chunks[i] for i in sorted(order)]  # reading order, not score order
