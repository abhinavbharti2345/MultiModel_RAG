from __future__ import annotations
import logging
import math
import re
from typing import Optional

import numpy as np
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    def __init__(self):
        self.api_url = settings.EMBEDDING_API_URL
        self.api_key = settings.EMBEDDING_API_KEY
        self.model = settings.EMBEDDING_MODEL
        self.dimension = settings.EMBEDDING_DIMENSION
        self._local_model = None
        self._use_local = not (self.api_url and self.api_key)

    def _load_local_model(self):
        if self._local_model is None and self._use_local:
            try:
                from sentence_transformers import SentenceTransformer
                logger.info(f"Loading local embedding model: {self.model}")
                self._local_model = SentenceTransformer(self.model)
                self.dimension = self._local_model.get_sentence_embedding_dimension()
                logger.info(f"Local model loaded, dim={self.dimension}")
            except Exception as e:
                logger.warning(f"Cannot load local embedding model ({e}); using hashing fallback")
                self._local_model = None
        return self._local_model

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
    async def embed_texts_async(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load_local_model()
        if model is not None:
            import asyncio
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, model.encode, texts, {"show_progress_bar": False})
            result = result.astype(float).tolist()
            return [self._normalize(v) for v in result]

        if self.api_url and self.api_key:
            import httpx
            async with httpx.AsyncClient(timeout=120.0) as client:
                payload = {"model": self.model, "input": texts}
                headers = {"Authorization": f"Bearer {self.api_key}"}
                resp = await client.post(self.api_url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            vectors = [d["embedding"] for d in data["data"]]
            return [self._normalize(v) for v in vectors]

        return [self._hash_embed(t) for t in texts]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import nest_asyncio
                    nest_asyncio.apply()
            except Exception:
                pass
            return asyncio.run(self.embed_texts_async(texts))
        except Exception as e:
            logger.warning(f"Async embed failed ({e}); falling back to hashing")
            return [self._hash_embed(t) for t in texts]

    @staticmethod
    def _normalize(vec: list[float]) -> list[float]:
        norm = math.sqrt(sum(v * v for v in vec))
        if norm < 1e-12:
            return vec
        return [v / norm for v in vec]

    def _hash_embed(self, text: str) -> list[float]:
        dim = self.dimension
        tokens = re.findall(r"[a-zA-Z0-9_]+", text.lower())
        vec = np.zeros(dim, dtype=np.float32)
        for tok in tokens:
            h = 0
            for ch in tok:
                h = (h * 131 + ord(ch)) & 0xFFFFFFFF
            idx = h % dim
            sign = 1.0 if ((h >> 16) & 1) == 0 else -1.0
            weight = 1.0 / math.sqrt(len(tokens) + 1)
            vec[idx] += sign * weight
            idx2 = (h * 7 + 3) % dim
            vec[idx2] += 0.5 * sign * weight
        norm = np.linalg.norm(vec)
        if norm > 1e-12:
            vec /= norm
        return vec.astype(float).tolist()

    @property
    def vector_size(self) -> int:
        if self._local_model is not None:
            return self.dimension
        return self.dimension

    @property
    def retrieval_score_threshold(self) -> float:
        """Neural embeddings produce cosine sims ~0.3-0.9 for related text;
        the hashing fallback yields much smaller values, so lower the bar."""
        neural = self._local_model is not None or bool(self.api_url and self.api_key)
        return 0.25 if neural else 0.02


embedding_service = EmbeddingService()
