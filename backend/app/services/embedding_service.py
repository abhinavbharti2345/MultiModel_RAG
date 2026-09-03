from __future__ import annotations
import logging
import math
import re
import threading
from typing import Optional

import numpy as np
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.services.health_tracker import health_tracker

logger = logging.getLogger(__name__)


class EmbeddingService:
    def __init__(self):
        self.api_url = settings.EMBEDDING_API_URL
        self.api_key = settings.EMBEDDING_API_KEY
        self.model = settings.EMBEDDING_MODEL
        self.dimension = settings.EMBEDDING_DIMENSION
        self._local_model = None
        self._use_local = not (self.api_url and self.api_key)
        self._lock = threading.Lock()

    def _load_local_model(self):
        if self._local_model is None and self._use_local:
            with self._lock:
                if self._local_model is None:
                    try:
                        from sentence_transformers import SentenceTransformer
                        logger.info(f"Loading local embedding model: {self.model}")
                        self._local_model = SentenceTransformer(self.model)
                        if hasattr(self._local_model, 'get_embedding_dimension'):
                            self.dimension = self._local_model.get_embedding_dimension()
                        else:
                            self.dimension = self._local_model.get_sentence_embedding_dimension()
                        logger.info(f"Local model loaded, dim={self.dimension}")
                    except Exception as e:
                        logger.error(f"Cannot load local embedding model '{self.model}': {e}", exc_info=True)
                        raise RuntimeError(f"Embedding configuration error: Failed to load local model '{self.model}'. Details: {e}") from e
        return self._local_model

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5), reraise=True)
    async def embed_texts_async(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load_local_model()
        if model is not None:
            import asyncio
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, lambda: model.encode(texts, show_progress_bar=False))
            result = result.astype(float).tolist()
            return [self._normalize(v) for v in result]

        if self.api_url and self.api_key:
            import httpx
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    payload = {"model": self.model, "input": texts}
                    headers = {"Authorization": f"Bearer {self.api_key}"}
                    resp = await client.post(self.api_url, json=payload, headers=headers)
            except Exception as e:
                health_tracker.update_status("embeddings", 503)
                raise RuntimeError(f"Embedding network error: {e}")

            retry_after = None
            if resp.status_code == 429:
                retry_header = resp.headers.get("retry-after")
                reset_header = resp.headers.get("x-ratelimit-reset-requests")
                if retry_header and retry_header.isdigit():
                    retry_after = int(retry_header)
                elif reset_header:
                    import re
                    match = re.search(r"(\d+(\.\d+)?)s", reset_header)
                    if match:
                        retry_after = int(float(match.group(1))) + 1
                if not retry_after:
                    retry_after = 60
                
                health_tracker.update_status("embeddings", 429, retry_after)
                logger.warning(f"Embeddings Rate Limited. Retry after {retry_after}s")
                raise RuntimeError(f"Embeddings Rate Limited (HTTP 429). Reset in {retry_after}s.")

            health_tracker.update_status("embeddings", resp.status_code)

            resp.raise_for_status()
            data = resp.json()
            vectors = [d["embedding"] for d in data["data"]]
            return [self._normalize(v) for v in vectors]

        raise RuntimeError("No embedding provider configured. Set EMBEDDING_API_URL and EMBEDDING_API_KEY, or ensure local model dependencies are installed.")

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import nest_asyncio
                nest_asyncio.apply()
        except Exception:
            pass
        return asyncio.run(self.embed_texts_async(texts))

    @staticmethod
    def _normalize(vec: list[float]) -> list[float]:
        norm = math.sqrt(sum(v * v for v in vec))
        if norm < 1e-12:
            return vec
        return [v / norm for v in vec]


    @property
    def vector_size(self) -> int:
        if self._local_model is not None:
            return self.dimension
        return self.dimension

    @property
    def retrieval_score_threshold(self) -> float:
        """Neural embeddings produce cosine sims ~0.3-0.9 for related text."""
        return 0.15


embedding_service = EmbeddingService()
