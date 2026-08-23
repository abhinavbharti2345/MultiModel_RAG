from __future__ import annotations
import logging
from typing import Optional

from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are an expert multimodal RAG assistant for technical meetings, architecture reviews, and documentation. Answer ONLY using the evidence provided below.

Rules:
1. If the evidence does not contain enough information to answer the question with confidence, say "I do not have enough evidence to answer this question fully" and explain what is missing.
2. Include specific provenance citations with every factual claim: (Source: [source_id], Timestamp: [HH:MM:SS], Page: [N], Evidence ID: [id]).
3. When multiple modalities (audio transcript, visual frame, document page, OCR) agree or disagree, acknowledge that and weight visual + written evidence over speech when the question is about a diagram or written text.
4. If asked "who" explained something, check transcript Speaker fields and any evidence with speaker provenance.
5. If asked "where" a diagram was shown, look for visual evidence, frames, OCR, and page references.
6. Preserve exact technical terms and architecture component names from the evidence.
7. Structure the answer clearly: Short direct answer first, then supporting details, then a "Provenance" bullet list summarizing the key evidence used.
8. Do not invent timestamps, page numbers, or evidence IDs not present in the input.
"""


class GroqLLM:
    def __init__(self):
        self.api_key = settings.GROQ_API_KEY
        self.base_url = settings.GROQ_API_BASE_URL
        self.model = settings.GROQ_LLM_MODEL

    def _api_configured(self) -> bool:
        return bool(self.api_key) and bool(self.base_url)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def generate_answer(
        self,
        question: str,
        evidence_context: str,
    ) -> str:
        if not self._api_configured():
            logger.warning("Groq LLM API not configured. Running deterministic mock answer generator.")
            return self._mock_answer(question, evidence_context)

        import httpx

        user_prompt = (
            f"Question: {question}\n\n"
            f"Retrieved evidence (only use information from below):\n"
            f"---------------------\n"
            f"{evidence_context}\n"
            f"---------------------\n\n"
            f"Answer the question strictly from the provided evidence."
        )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 1200,
            "top_p": 0.9,
        }

        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(base_url=self.base_url, timeout=180.0) as client:
            resp = await client.post("/chat/completions", json=payload, headers=headers)

        if resp.status_code != 200:
            logger.error(f"Groq LLM error {resp.status_code}: {resp.text}")
            raise RuntimeError(f"LLM generation failed: {resp.status_code}")

        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()

    def _mock_answer(self, question: str, evidence_context: str) -> str:
        q = question.lower()
        answer_lines = []
        prov = []

        has_redis = "redis" in evidence_context.lower()
        has_pg = "postgre" in evidence_context.lower() or "postgres" in evidence_context.lower()
        has_speaker = "speaker" in evidence_context.lower()
        has_page = "page_number: 7" in evidence_context or "page: 7" in evidence_context.lower()
        has_diagram = ("diagram" in evidence_context.lower() or
                       "architecture" in evidence_context.lower() or
                       "visual" in evidence_context.lower())

        # Dynamic fallback that summarizes extracted chunks
        answer_lines.append(
            "## Answer\n\n"
            "Based on the retrieved evidence, here are the most relevant facts. Please note this is a "
            "deterministic answer generated while a Groq API key is not configured — add GROQ_API_KEY to "
            ".env for production-quality natural language generation tailored exactly to your question.\n"
        )
        
        key_chunks = []
        for chunk in evidence_context.split("---"):
            chunk = chunk.strip()
            if not chunk:
                continue
            content_line = [l for l in chunk.splitlines() if l.startswith("Content:")]
            if content_line:
                text = content_line[0].split(":", 1)[1].strip()
                if len(text) > 150:
                    text = text[:150] + "…"
                key_chunks.append(f"- {text}")
            
            # extract provenance for citation
            ev_id_line = [l for l in chunk.splitlines() if "[Evidence ID:" in l]
            mod_line = [l for l in chunk.splitlines() if l.startswith("Modality:")]
            ts_line = [l for l in chunk.splitlines() if l.startswith("Timestamp:")]
            pg_line = [l for l in chunk.splitlines() if l.startswith("Page:")]
            if ev_id_line:
                ev_id = ev_id_line[0].split("[Evidence ID:")[1].split("]")[0].strip()
                summary_bits = []
                if mod_line: summary_bits.append(mod_line[0].split(":", 1)[1].strip())
                if ts_line: summary_bits.append(f"ts {ts_line[0].split(':', 1)[1].strip()}")
                if pg_line: summary_bits.append(f"pg {pg_line[0].split(':', 1)[1].strip()}")
                
                prov_str = f"- Evidence {ev_id[:8]}... "
                if summary_bits:
                    prov_str += f"({', '.join(summary_bits)})"
                if prov_str not in prov:
                    prov.append(prov_str)
                    
            if len(key_chunks) >= 8:
                break
                
        answer_lines.extend(key_chunks)


        answer_lines.append("\n### Provenance")
        answer_lines.extend(prov[:8])
        return "\n".join(answer_lines)


llm_service = GroqLLM()
