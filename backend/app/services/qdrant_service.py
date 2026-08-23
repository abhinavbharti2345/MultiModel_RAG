from __future__ import annotations
import logging
import time
from typing import Optional
from uuid import UUID

from qdrant_client import QdrantClient, models
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.services.embedding_service import embedding_service

logger = logging.getLogger(__name__)


class QdrantService:
    def __init__(self):
        self.host = settings.QDRANT_HOST
        self.port = settings.QDRANT_PORT
        self.grpc_port = settings.QDRANT_GRPC_PORT
        self.collection = settings.QDRANT_COLLECTION
        self._client: Optional[QdrantClient] = None
        self._collection_ready = False

    def _get_client(self) -> QdrantClient:
        if self._client is None:
            try:
                if settings.QDRANT_URL and settings.QDRANT_API_KEY:
                    candidate = QdrantClient(
                        url=settings.QDRANT_URL,
                        api_key=settings.QDRANT_API_KEY,
                        timeout=10,
                    )
                else:
                    candidate = QdrantClient(
                        host=self.host,
                        port=self.port,
                        grpc_port=self.grpc_port,
                        prefer_grpc=False,
                        timeout=3,
                    )
                candidate.get_collections()
                self._client = candidate
                logger.info(f"Connected to Qdrant at {self.host}:{self.port}")
            except Exception as e:
                logger.warning(f"Could not connect to Qdrant server ({e}); using in-memory client")
                self._client = QdrantClient(location=":memory:")
        self._ensure_collection()
        return self._client

    def _ensure_collection(self) -> None:
        if self._collection_ready:
            return
        client = self._client
        if client is None:
            return
        try:
            collections = client.get_collections().collections
            names = [c.name for c in collections]
            dim = embedding_service.vector_size
            if self.collection not in names:
                logger.info(f"Creating Qdrant collection '{self.collection}' (dim={dim})")
                client.create_collection(
                    collection_name=self.collection,
                    vectors_config=models.VectorParams(
                        size=dim,
                        distance=models.Distance.COSINE,
                    ),
                )
                client.create_payload_index(
                    collection_name=self.collection,
                    field_name="source_id",
                    field_schema=models.PayloadSchemaType.UUID,
                )
                client.create_payload_index(
                    collection_name=self.collection,
                    field_name="modality",
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
            else:
                logger.info(f"Qdrant collection '{self.collection}' already exists")
            self._collection_ready = True
        except Exception as e:
            logger.warning(f"Could not ensure Qdrant collection: {e}")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def upsert_evidence(
        self,
        evidence_id: UUID,
        content: str,
        vector: list[float],
        payload: dict,
    ) -> UUID:
        point_id = UUID(bytes=evidence_id.bytes, version=4) if evidence_id.version != 4 else evidence_id
        point = models.PointStruct(
            id=str(point_id),
            vector=vector,
            payload={"evidence_id": str(evidence_id), **(payload or {})},
        )
        client = self._get_client()
        client.upsert(collection_name=self.collection, points=[point], wait=True)
        return point_id

    def upsert_many(
        self,
        items: list[tuple[UUID, str, list[float], dict]],
        batch_size: int = 64,
    ) -> list[UUID]:
        point_ids: list[UUID] = []
        client = self._get_client()
        for start in range(0, len(items), batch_size):
            batch = items[start : start + batch_size]
            points = []
            batch_ids: list[UUID] = []
            for evidence_id, content, vector, payload in batch:
                point_id = UUID(bytes=evidence_id.bytes, version=4) if evidence_id.version != 4 else evidence_id
                points.append(models.PointStruct(
                    id=str(point_id),
                    vector=vector,
                    payload={"evidence_id": str(evidence_id), **(payload or {})},
                ))
                batch_ids.append(point_id)
            try:
                client.upsert(collection_name=self.collection, points=points, wait=True)
            except Exception as e:
                logger.error(f"Qdrant batch upsert failed: {e}")
                for evidence_id, content, vector, payload in batch:
                    try:
                        pid = self.upsert_evidence(evidence_id, content, vector, payload)
                        batch_ids.append(pid)
                    except Exception as inner:
                        logger.error(f"Single upsert also failed: {inner}")
            point_ids.extend(batch_ids)
        return point_ids

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
    def search(
        self,
        query_vector: list[float],
        top_k: int = 10,
        score_threshold: float = 0.3,
        source_ids: Optional[list[UUID]] = None,
        modalities: Optional[list[str]] = None,
    ) -> list[tuple[UUID, float, dict]]:
        client = self._get_client()
        filters = []
        if source_ids:
            filters.append(models.FieldCondition(
                key="source_id",
                match=models.MatchAny(any=[str(s) for s in source_ids]),
            ))
        if modalities:
            filters.append(models.FieldCondition(
                key="modality",
                match=models.MatchAny(any=modalities),
            ))
        query_filter = models.Filter(must=filters) if filters else None

        results = client.query_points(
            collection_name=self.collection,
            query=query_vector,
            query_filter=query_filter,
            limit=top_k,
            score_threshold=score_threshold,
            with_payload=True,
        ).points
        hits: list[tuple[UUID, float, dict]] = []
        for hit in results:
            try:
                evidence_id = UUID(str(hit.payload.get("evidence_id") or hit.id))
            except Exception:
                evidence_id = UUID(str(hit.id))
            hits.append((evidence_id, float(hit.score), hit.payload or {}))
        return hits


qdrant_service = QdrantService()
