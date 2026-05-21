"""Semantic search over MobileCLIP-S0 image embeddings.

The text tower encodes the query once and we rank against the `image_embeddings`
table via numpy matmul. For ≤100k images this is fast enough (a 100k×512 float32
matrix is 200 MB, fits comfortably in 8 GB). No HNSW yet — switch to it when the
benchmark says so.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import numpy as np

_TEXT_MODEL = None
_TEXT_LOADED = False
_TOKENIZER = None


def _load_text_model() -> object | None:
    global _TEXT_MODEL, _TEXT_LOADED
    if _TEXT_LOADED:
        return _TEXT_MODEL
    _TEXT_LOADED = True
    path = os.environ.get("SNAPGRADE_MOBILECLIP_TEXT_MODEL")
    if not path:
        try:
            from . import models
            path = str(models.ensure("mobileclip_text"))
        except Exception:
            default = Path.home() / ".snapgrade" / "models" / "mobileclip_s0_text.mlpackage"
            if default.exists():
                path = str(default)
    if not path or not Path(path).exists():
        return None
    try:
        from . import models as _m
        _TEXT_MODEL = _m.load_coreml(path)
    except Exception:
        _TEXT_MODEL = None
    return _TEXT_MODEL


def _tokenize(text: str) -> np.ndarray:
    """OpenAI BPE tokenization, padded/truncated to 77 tokens (CLIP convention).

    MobileCLIP reuses OpenAI's tokenizer; the CoreML export expects an int32
    token tensor of shape (1, 77).
    """
    global _TOKENIZER
    if _TOKENIZER is None:
        try:
            import open_clip  # type: ignore
            _TOKENIZER = open_clip.get_tokenizer("ViT-B-16")
        except ImportError:
            try:
                import clip  # type: ignore  # OpenAI CLIP
                _TOKENIZER = clip.tokenize
            except ImportError as e:
                raise RuntimeError(
                    "Semantic search needs `open_clip_torch` or `clip` installed for "
                    "tokenization. Run: pip install open_clip_torch"
                ) from e
    toks = _TOKENIZER([text])
    # Both libs return torch.LongTensor of shape (1, 77).
    return np.asarray(toks, dtype=np.int32)


def encode_text(query: str) -> np.ndarray | None:
    """Return a 512-d L2-normalized float32 vector for the text query."""
    model = _load_text_model()
    if model is None:
        return None
    tokens = _tokenize(query)
    try:
        out = model.predict({list(model.input_description)[0]: tokens})  # type: ignore[attr-defined]
        vec = np.asarray(next(iter(out.values())), dtype=np.float32).ravel()
        n = float(np.linalg.norm(vec))
        if n < 1e-6:
            return None
        return (vec / n).astype(np.float32)
    except Exception:
        return None


def search(
    conn: sqlite3.Connection, query: str, k: int = 20, library_id: int | None = None,
) -> list[tuple[int, float]]:
    """Return [(image_id, cosine_similarity)] for the top-k matches.

    Empty list if the text model isn't available or no embeddings exist yet.
    """
    qvec = encode_text(query)
    if qvec is None:
        return []
    sql = "SELECT e.image_id, e.embedding FROM image_embeddings e"
    params: list = []
    if library_id is not None:
        sql += " JOIN images i ON i.id = e.image_id WHERE i.library_id = ?"
        params.append(library_id)
    rows = conn.execute(sql, params).fetchall()
    if not rows:
        return []
    ids = np.fromiter((int(r["image_id"]) for r in rows), dtype=np.int64, count=len(rows))
    mat = np.stack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
    # Embeddings are pre-normalized so this is true cosine similarity.
    sims = mat @ qvec
    k = min(k, len(sims))
    top_idx = np.argpartition(-sims, k - 1)[:k]
    top_idx = top_idx[np.argsort(-sims[top_idx])]
    return [(int(ids[i]), float(sims[i])) for i in top_idx]
