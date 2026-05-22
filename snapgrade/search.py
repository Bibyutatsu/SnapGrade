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


# Per-scope cache of the stacked embedding matrix. Rebuilding it (SQL + np.stack
# of a 100k×512 float32 = 200 MB array) on every keystroke of a search-as-you-type
# UI is wasteful, so we memoize keyed on a cheap (count, max_image_id) signature
# and rebuild only when the embedding set changes. {library_id: (sig, mat, ids)}.
_MAT_CACHE: dict[int | None, tuple[tuple[int, int], np.ndarray, np.ndarray]] = {}


def _embedding_matrix(
    conn: sqlite3.Connection, library_id: int | None,
) -> tuple[np.ndarray | None, np.ndarray | None]:
    """Return (matrix, ids) for the scope, served from cache when unchanged."""
    if library_id is None:
        sig_row = conn.execute(
            "SELECT COUNT(*) AS c, MAX(image_id) AS m FROM image_embeddings"
        ).fetchone()
    else:
        sig_row = conn.execute(
            "SELECT COUNT(*) AS c, MAX(e.image_id) AS m FROM image_embeddings e "
            "JOIN images i ON i.id = e.image_id WHERE i.library_id = ?",
            (library_id,),
        ).fetchone()
    sig = (int(sig_row["c"] or 0), int(sig_row["m"] or 0))
    if sig[0] == 0:
        return None, None
    cached = _MAT_CACHE.get(library_id)
    if cached is not None and cached[0] == sig:
        return cached[1], cached[2]

    sql = "SELECT e.image_id, e.embedding FROM image_embeddings e"
    params: list = []
    if library_id is not None:
        sql += " JOIN images i ON i.id = e.image_id WHERE i.library_id = ?"
        params.append(library_id)
    rows = conn.execute(sql, params).fetchall()
    if not rows:
        return None, None
    ids = np.fromiter((int(r["image_id"]) for r in rows), dtype=np.int64, count=len(rows))
    mat = np.stack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
    _MAT_CACHE[library_id] = (sig, mat, ids)
    return mat, ids


def search(
    conn: sqlite3.Connection, query: str, k: int = 20, library_id: int | None = None,
) -> list[tuple[int, float]]:
    """Return [(image_id, cosine_similarity)] for the top-k matches.

    Empty list if the text model isn't available or no embeddings exist yet.
    """
    qvec = encode_text(query)
    if qvec is None:
        return []
    mat, ids = _embedding_matrix(conn, library_id)
    if mat is None:
        return []
    # Embeddings are pre-normalized so this is true cosine similarity.
    sims = mat @ qvec
    k = min(k, len(sims))
    top_idx = np.argpartition(-sims, k - 1)[:k]
    top_idx = top_idx[np.argsort(-sims[top_idx])]
    return [(int(ids[i]), float(sims[i])) for i in top_idx]
