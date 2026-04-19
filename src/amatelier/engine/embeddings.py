"""Embeddings helper for behavior selection.

Pluggable design. amatelier has no opinion about which embedder you use —
it auto-detects from your environment, falls through a priority list of
built-in providers, and finally degrades to a no-op that triggers
confidence-only ranking in the runner. Users can plug in their own
embedder via `set_embedder()`.

Priority order (auto-detect):
    1. OPENAI_API_KEY    → OpenAI `text-embedding-3-small` (1536-dim)
    2. VOYAGE_API_KEY    → Voyage AI `voyage-3-lite` (512-dim)
    3. GEMINI_API_KEY or GOOGLE_API_KEY
                          → Gemini `text-embedding-004` (768-dim)
    4. sentence-transformers importable
                          → local `all-MiniLM-L6-v2` (384-dim)
    5. otherwise          → NoOpEmbedder, returns None → runner falls
                            back to confidence-only ranking

Install offline support: `pip install amatelier[embed]`

Plug in a custom embedder:
    from amatelier.engine.embeddings import set_embedder
    class MyEmbedder:
        def embed(self, text: str) -> list[float] | None: ...
        def embed_batch(self, texts: list[str]) -> list[list[float] | None]: ...
    set_embedder(MyEmbedder())

Every embedder returns None on failure — never raises — so the hot path
can't be broken by a network blip or missing API key.
"""
from __future__ import annotations

import logging
import math
import os
from typing import Optional, Protocol, runtime_checkable

logger = logging.getLogger("embeddings")


# ---------------------------------------------------------------------------
# Protocol + registry
# ---------------------------------------------------------------------------

@runtime_checkable
class Embedder(Protocol):
    """Any object with `embed` and `embed_batch` methods qualifies."""

    def embed(self, text: str) -> Optional[list[float]]: ...

    def embed_batch(self, texts: list[str]) -> list[Optional[list[float]]]: ...


_embedder: Optional[Embedder] = None


def set_embedder(embedder: Embedder) -> None:
    """Register a custom embedder. Overrides auto-detection."""
    global _embedder
    _embedder = embedder


def get_embedder() -> Embedder:
    """Return the active embedder. Auto-detects on first call if unset."""
    global _embedder
    if _embedder is None:
        _embedder = _auto_detect()
    return _embedder


def _auto_detect() -> Embedder:
    """Pick the first available provider from the priority list."""
    if os.environ.get("OPENAI_API_KEY"):
        try:
            return OpenAIEmbedder()
        except Exception as e:
            logger.debug("OpenAI embedder unavailable: %s", e)
    if os.environ.get("VOYAGE_API_KEY"):
        try:
            return VoyageEmbedder()
        except Exception as e:
            logger.debug("Voyage embedder unavailable: %s", e)
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        try:
            return GeminiEmbedder()
        except Exception as e:
            logger.debug("Gemini embedder unavailable: %s", e)
    try:
        import sentence_transformers  # noqa: F401
        return SentenceTransformersEmbedder()
    except Exception as e:
        logger.debug("sentence-transformers unavailable: %s", e)
    return NoOpEmbedder()


# ---------------------------------------------------------------------------
# Public API — delegates to the active embedder
# ---------------------------------------------------------------------------

def embed(text: str) -> Optional[list[float]]:
    """Return an embedding vector, or None if no embedder is configured."""
    if not text or not text.strip():
        return None
    try:
        return get_embedder().embed(text)
    except Exception as e:
        logger.debug("embed() failed: %s", e)
        return None


def embed_batch(texts: list[str]) -> list[Optional[list[float]]]:
    """Batch variant; parallel list with None entries where unavailable."""
    if not texts:
        return []
    try:
        return get_embedder().embed_batch(texts)
    except Exception as e:
        logger.debug("embed_batch() failed: %s", e)
        return [None] * len(texts)


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity; 0.0 on malformed input (no NaN propagation)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    try:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Built-in providers
# ---------------------------------------------------------------------------

class NoOpEmbedder:
    """Always returns None. Signals runner to use confidence-only ranking."""

    def embed(self, text: str) -> Optional[list[float]]:
        return None

    def embed_batch(self, texts: list[str]) -> list[Optional[list[float]]]:
        return [None] * len(texts)


class OpenAIEmbedder:
    """OpenAI `text-embedding-3-small`. Requires OPENAI_API_KEY."""

    MODEL = "text-embedding-3-small"

    def __init__(self):
        from openai import OpenAI
        self._client = OpenAI()

    def embed(self, text: str) -> Optional[list[float]]:
        if not text or not text.strip():
            return None
        try:
            r = self._client.embeddings.create(model=self.MODEL, input=text.strip())
            return list(r.data[0].embedding)
        except Exception as e:
            logger.debug("OpenAI embed failed: %s", e)
            return None

    def embed_batch(self, texts: list[str]) -> list[Optional[list[float]]]:
        nonempty = [(i, t.strip()) for i, t in enumerate(texts) if t and t.strip()]
        if not nonempty:
            return [None] * len(texts)
        try:
            r = self._client.embeddings.create(
                model=self.MODEL,
                input=[t for _, t in nonempty],
            )
            out: list[Optional[list[float]]] = [None] * len(texts)
            for pos, (idx, _) in enumerate(nonempty):
                out[idx] = list(r.data[pos].embedding)
            return out
        except Exception as e:
            logger.debug("OpenAI embed_batch failed: %s", e)
            return [self.embed(t) for t in texts]


class VoyageEmbedder:
    """Voyage AI `voyage-3-lite`. Requires VOYAGE_API_KEY + voyageai pkg."""

    MODEL = "voyage-3-lite"

    def __init__(self):
        import voyageai
        self._client = voyageai.Client()

    def embed(self, text: str) -> Optional[list[float]]:
        if not text or not text.strip():
            return None
        try:
            r = self._client.embed([text.strip()], model=self.MODEL)
            return list(r.embeddings[0])
        except Exception as e:
            logger.debug("Voyage embed failed: %s", e)
            return None

    def embed_batch(self, texts: list[str]) -> list[Optional[list[float]]]:
        nonempty = [(i, t.strip()) for i, t in enumerate(texts) if t and t.strip()]
        if not nonempty:
            return [None] * len(texts)
        try:
            r = self._client.embed([t for _, t in nonempty], model=self.MODEL)
            out: list[Optional[list[float]]] = [None] * len(texts)
            for pos, (idx, _) in enumerate(nonempty):
                out[idx] = list(r.embeddings[pos])
            return out
        except Exception as e:
            logger.debug("Voyage embed_batch failed: %s", e)
            return [self.embed(t) for t in texts]


class GeminiEmbedder:
    """Gemini `text-embedding-004`. Requires GEMINI_API_KEY or GOOGLE_API_KEY."""

    MODEL = "models/text-embedding-004"

    def __init__(self):
        import google.generativeai as genai
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        genai.configure(api_key=key)
        self._genai = genai

    def embed(self, text: str) -> Optional[list[float]]:
        if not text or not text.strip():
            return None
        try:
            r = self._genai.embed_content(model=self.MODEL, content=text.strip())
            return list(r["embedding"])
        except Exception as e:
            logger.debug("Gemini embed failed: %s", e)
            return None

    def embed_batch(self, texts: list[str]) -> list[Optional[list[float]]]:
        # google-generativeai doesn't expose a first-class batch endpoint at
        # the time of writing; loop per-item. Still within free tier for
        # our backfill volumes.
        return [self.embed(t) for t in texts]


class SentenceTransformersEmbedder:
    """Local `all-MiniLM-L6-v2`. Requires `pip install amatelier[embed]`."""

    MODEL = "sentence-transformers/all-MiniLM-L6-v2"

    def __init__(self):
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(self.MODEL)

    def embed(self, text: str) -> Optional[list[float]]:
        if not text or not text.strip():
            return None
        try:
            vec = self._model.encode(text.strip(), convert_to_numpy=False)
            return [float(x) for x in vec]
        except Exception as e:
            logger.debug("sentence-transformers embed failed: %s", e)
            return None

    def embed_batch(self, texts: list[str]) -> list[Optional[list[float]]]:
        nonempty = [(i, t.strip()) for i, t in enumerate(texts) if t and t.strip()]
        if not nonempty:
            return [None] * len(texts)
        try:
            vecs = self._model.encode(
                [t for _, t in nonempty],
                convert_to_numpy=False,
            )
            out: list[Optional[list[float]]] = [None] * len(texts)
            for pos, (idx, _) in enumerate(nonempty):
                out[idx] = [float(x) for x in vecs[pos]]
            return out
        except Exception as e:
            logger.debug("sentence-transformers batch failed: %s", e)
            return [self.embed(t) for t in texts]
