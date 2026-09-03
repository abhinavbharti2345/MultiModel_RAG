from __future__ import annotations
import base64
import logging
from pathlib import Path
from typing import Optional

from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.schemas.evidence_schemas import VisualAnalysisResult
from app.services.health_tracker import health_tracker

logger = logging.getLogger(__name__)


class VisualAnalyzer:
    def __init__(self):
        self.api_url = settings.VLM_API_URL
        keys = [
            settings.VLM_API_KEY,
            settings.VLM_API_KEY_1,
            settings.VLM_API_KEY_2,
            settings.VLM_API_KEY_3
        ]
        self.api_keys = [k.strip() for k in keys if k and k.strip()]
        self.active_key_index = 0
        self.model = settings.VLM_MODEL

    def _encode_image(self, image_path: Path) -> str:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=15), reraise=True)
    async def analyze_frame(self, frame_path: Path, context_hint: Optional[str] = None) -> VisualAnalysisResult:
        has_api = bool(self.api_url and self.model and self.api_keys)

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
3. Diagrams, architecture components, logos, or technical elements visible. Summarize the logical flow if present. Do NOT hallucinate diagram relationships.
4. Any people present and what they are doing
5. Key entities (technology names, product names, acronyms)
6. Relationships between objects when confidently identifiable (e.g., "API connects to Database")

You must respond in ONLY valid JSON format with exactly these keys:
{
  "description": "string",
  "ocr_text": "string or null",
  "entities": ["string"],
  "objects_detected": ["string"],
  "relationships": ["string"],
  "diagram_info": "string or null"
}"""

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
            "max_tokens": 1200,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                active_key = self.api_keys[self.active_key_index]
                headers = {"Authorization": f"Bearer {active_key}"}
                resp = await client.post(self.api_url, json=payload, headers=headers)
        except Exception as e:
            health_tracker.update_status("vlm", 503)
            raise RuntimeError(f"VLM network error: {e}")

        retry_after = None
        if resp.status_code == 429:
            # Rotate API Key automatically!
            old_index = self.active_key_index
            self.active_key_index = (self.active_key_index + 1) % len(self.api_keys)
            
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
                retry_after = 60 # fallback

            health_tracker.update_status("vlm", 429, retry_after)
            logger.warning(f"VLM Rate Limited on key index {old_index}. Automatically rotated to key index {self.active_key_index}. Next retry in {retry_after}s if same key is hit.")
            raise RuntimeError(f"VLM Rate Limited (HTTP 429). Will retry with new key.")

        health_tracker.update_status("vlm", resp.status_code)

        if resp.status_code != 200:
            logger.error(f"VLM API error {resp.status_code}: {resp.text}")
            if resp.status_code == 400:
                # Do not retry on 400 bad request
                return VisualAnalysisResult(description="VLM Failed: Bad Request", entities=[], objects_detected=[], relationships=[])
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
                relationships=list(parsed.get("relationships", []) or []),
                diagram_info=parsed.get("diagram_info") or None,
            )
        except Exception:
            return VisualAnalysisResult(
                description=content,
                entities=[],
                objects_detected=[],
                relationships=[],
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
                relationships=["API Gateway connects to Load Balancers", "Load Balancers connect to Application Servers"],
                diagram_info="Three-tier web architecture logical flow.",
            ),
            VisualAnalysisResult(
                description="A technical architecture diagram focusing on the data layer. Shows Redis Cache box connected to PostgreSQL Database box with arrows labeled 'read path' and 'write-through'. Includes TTL annotations.",
                ocr_text="Data Layer: Caching Strategy\nRedis Cache (TTL 5min)\nPostgreSQL DB\nRead Path: App -> Redis -> PG\nWrite Path: App -> PG -> Redis",
                entities=["Redis", "PostgreSQL", "TTL", "Caching Strategy", "Data Layer"],
                objects_detected=["architecture diagram", "boxes", "arrows", "annotations"],
                relationships=["App reads from Redis", "Redis reads from PostgreSQL", "App writes to PostgreSQL", "PostgreSQL writes through to Redis"],
                diagram_info="Data layer caching strategy showing read and write paths.",
            ),
            VisualAnalysisResult(
                description="A presenter at a whiteboard discussing a system design. Whiteboard has drawings of server icons and database symbols. Estimated 2-3 people in the frame.",
                ocr_text="QPS Target: 10k\nSLA: 99.9%\nP95 Latency < 200ms",
                entities=["QPS", "SLA", "Latency", "P95"],
                objects_detected=["person", "whiteboard", "marker", "diagram"],
                relationships=["Presenter drawing on whiteboard"],
                diagram_info="Whiteboard system design sketch.",
            ),
            VisualAnalysisResult(
                description="A screenshot of a monitoring dashboard showing database metrics. CPU utilization graph at 85%, connection pool near max, query latency spike at 14:30.",
                ocr_text="DB Metrics - 14:00-15:00\nCPU: 85%\nConnections: 480/500\nP95 Query Time: 1.2s",
                entities=["CPU", "connection pool", "query latency", "P95 Query Time"],
                objects_detected=["dashboard", "graph", "metrics"],
                relationships=[],
                diagram_info="Monitoring dashboard showing elevated CPU and connections.",
            ),
            VisualAnalysisResult(
                description="A camera view of a meeting room. Two people visible. Projector in background showing a slide. Table has laptops, notebooks, and water bottles.",
                ocr_text=None,
                entities=["meeting room"],
                objects_detected=["person", "laptop", "projector", "table", "water bottle"],
                relationships=["People sitting at table", "Projector displaying slide"],
                diagram_info=None,
            ),
        ]
        scenario = mock_scenarios[h % len(mock_scenarios)]
        if context_hint and "redis" in context_hint.lower():
            scenario = mock_scenarios[1]
        elif context_hint and ("question" in context_hint.lower() or "ask" in context_hint.lower()):
            scenario = mock_scenarios[4]
        return scenario


visual_analyzer = VisualAnalyzer()
