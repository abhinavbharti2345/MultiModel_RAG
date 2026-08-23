from __future__ import annotations
import base64
import logging
from pathlib import Path
from typing import Optional

from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.schemas.evidence_schemas import VisualAnalysisResult

logger = logging.getLogger(__name__)


class VisualAnalyzer:
    def __init__(self):
        self.api_url = settings.VLM_API_URL
        self.api_key = settings.VLM_API_KEY
        self.model = settings.VLM_MODEL

    def _encode_image(self, image_path: Path) -> str:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def analyze_frame(self, frame_path: Path, context_hint: Optional[str] = None) -> VisualAnalysisResult:
        has_api = bool(self.api_url and self.api_key and self.model)

        if not has_api:
            logger.info(f"No VLM API configured. Using mock analysis for {frame_path.name}")
            return self._mock_analysis(frame_path, context_hint)

        logger.info(f"Analyzing frame {frame_path.name} with VLM API...")
        import httpx

        b64 = self._encode_image(frame_path)
        mime = "image/jpeg"
        data_url = f"data:{mime};base64,{b64}"

        prompt = """Describe this image in detail, focusing on:
1. Overall scene / context (meeting slide, diagram, screenshot, whiteboard, etc.)
2. All visible text (exact OCR transcription if readable)
3. Diagrams, architecture components, logos, or technical elements visible
4. Any people present and what they are doing
5. Key entities (technology names, product names, acronyms)

Respond in JSON format with keys: description (string), ocr_text (string or null), entities (list of strings), objects_detected (list of strings)."""

        if context_hint:
            prompt += f"\n\nContext from surrounding transcription: '{context_hint}'"

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            "max_tokens": 800,
            "temperature": 0.1,
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
            resp = await client.post(self.api_url, json=payload, headers=headers)

        if resp.status_code != 200:
            logger.error(f"VLM API error {resp.status_code}: {resp.text}")
            raise RuntimeError(f"VLM API failed: {resp.status_code}")

        try:
            result = resp.json()
            content = result["choices"][0]["message"]["content"]
            return self._parse_vlm_response(content)
        except Exception as e:
            logger.error(f"Failed to parse VLM response: {e}")
            return VisualAnalysisResult(
                description=f"VLM analysis parsed (raw): {resp.text[:500]}",
                entities=[],
                objects_detected=[],
            )

    def _parse_vlm_response(self, content: str) -> VisualAnalysisResult:
        import json
        try:
            if content.strip().startswith("```"):
                content = content.strip().strip("`")
                if content.lower().startswith("json"):
                    content = content[4:]
            parsed = json.loads(content.strip())
            return VisualAnalysisResult(
                description=str(parsed.get("description", content)),
                ocr_text=parsed.get("ocr_text") or None,
                entities=list(parsed.get("entities", []) or []),
                objects_detected=list(parsed.get("objects_detected", []) or []),
            )
        except Exception:
            return VisualAnalysisResult(
                description=content,
                entities=[],
                objects_detected=[],
            )

    def _mock_analysis(self, frame_path: Path, context_hint: Optional[str]) -> VisualAnalysisResult:
        import hashlib
        h = int(hashlib.md5(frame_path.name.encode()).hexdigest()[:8], 16)
        mock_scenarios = [
            VisualAnalysisResult(
                description="A presentation slide showing a three-tier web architecture diagram. Boxes labeled 'API Gateway', 'Load Balancers', and 'Application Servers' are connected with arrows. The slide title reads 'System Architecture Overview - Phase 1'.",
                ocr_text="System Architecture Overview - Phase 1\nAPI Gateway -> Load Balancers -> Application Servers\nScalable, resilient, observable",
                entities=["API Gateway", "Load Balancers", "Application Servers", "Phase 1"],
                objects_detected=["presentation slide", "architecture diagram", "boxes", "arrows"],
            ),
            VisualAnalysisResult(
                description="A technical architecture diagram focusing on the data layer. Shows Redis Cache box connected to PostgreSQL Database box with arrows labeled 'read path' and 'write-through'. Includes TTL annotations.",
                ocr_text="Data Layer: Caching Strategy\nRedis Cache (TTL 5min)\nPostgreSQL DB\nRead Path: App -> Redis -> PG\nWrite Path: App -> PG -> Redis",
                entities=["Redis", "PostgreSQL", "TTL", "Caching Strategy", "Data Layer"],
                objects_detected=["architecture diagram", "boxes", "arrows", "annotations"],
            ),
            VisualAnalysisResult(
                description="A presenter at a whiteboard discussing a system design. Whiteboard has drawings of server icons and database symbols. Estimated 2-3 people in the frame.",
                ocr_text="QPS Target: 10k\nSLA: 99.9%\nP95 Latency < 200ms",
                entities=["QPS", "SLA", "Latency", "P95"],
                objects_detected=["person", "whiteboard", "marker", "diagram"],
            ),
            VisualAnalysisResult(
                description="A screenshot of a monitoring dashboard showing database metrics. CPU utilization graph at 85%, connection pool near max, query latency spike at 14:30.",
                ocr_text="DB Metrics - 14:00-15:00\nCPU: 85%\nConnections: 480/500\nP95 Query Time: 1.2s",
                entities=["CPU", "connection pool", "query latency", "P95 Query Time"],
                objects_detected=["dashboard", "graph", "metrics"],
            ),
            VisualAnalysisResult(
                description="A camera view of a meeting room. Two people visible. Projector in background showing a slide. Table has laptops, notebooks, and water bottles.",
                ocr_text=None,
                entities=["meeting room"],
                objects_detected=["person", "laptop", "projector", "table", "water bottle"],
            ),
        ]
        scenario = mock_scenarios[h % len(mock_scenarios)]
        if context_hint and "redis" in context_hint.lower():
            scenario = mock_scenarios[1]
        elif context_hint and ("question" in context_hint.lower() or "ask" in context_hint.lower()):
            scenario = mock_scenarios[4]
        return scenario


visual_analyzer = VisualAnalyzer()
