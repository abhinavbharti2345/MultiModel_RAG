from __future__ import annotations
import logging
from typing import Optional

from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.services.health_tracker import health_tracker

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are an expert multimodal RAG assistant for technical meetings, architecture reviews, and documentation. Answer ONLY using the evidence provided below.

Rules:
1. Base your summaries and answers on the combined evidence provided, respecting the chronological order to preserve temporal context.
2. If the evidence does not contain enough information to answer the question with confidence, explicitly say "I do not have enough evidence to answer this question fully" and do not guess or hallucinate details, numbers, names, or dates.
3. You must output ONLY a valid JSON object matching the following structure:
{
  "answer": "your detailed answer here",
  "citations": [
    {
      "evidence_id": "uuid-from-evidence-exactly-as-provided",
      "timestamp_start": 20.5,
      "timestamp_end": 25.2,
      "reason": "why this was cited"
    }
  ]
}
4. Every citation must use an exact 'Evidence ID' provided in the context. Do not invent timestamps, page numbers, or evidence IDs not present in the input.
5. Use OCR and Transcript content as primary evidence for factual claims, while using visual frames to add relevant context.
"""

# Context windows for models we know about.  Values are total input+output token limits.
# Source: Groq documentation (https://console.groq.com/docs/models).
# Add entries as new models are deployed.
_KNOWN_MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "llama-3.3-70b-versatile": 131_072,
    "llama-3.1-70b-versatile": 131_072,
    "llama-3.1-8b-instant": 131_072,
    "llama3-70b-8192": 8_192,
    "llama3-8b-8192": 8_192,
    "mixtral-8x7b-32768": 32_768,
    "gemma2-9b-it": 8_192,
    "gemma-7b-it": 8_192,
}

# Chars-per-token estimate used throughout for lightweight budgeting.
# English prose averages ~4 chars/token (OpenAI GPT tokenisers).
# We use 3.5 to be slightly conservative (evidence contains UUIDs, timestamps, etc.).
_CHARS_PER_TOKEN: float = 3.5


class GroqLLM:
    def __init__(self):
        keys = [settings.GROQ_API_KEY, settings.GROQ_API_KEY_1]
        self.api_keys = [k.strip() for k in keys if k and k.strip()]
        self.active_key_index = 0
        self.base_url = settings.GROQ_API_BASE_URL
        self.model = settings.GROQ_LLM_MODEL

    def _api_configured(self) -> bool:
        return bool(self.api_keys) and bool(self.base_url)

    @property
    def context_window_tokens(self) -> int:
        """
        Total context window (tokens) for the active LLM.

        Priority:
        1. LLM_CONTEXT_WINDOW_TOKENS env override (non-zero) — use as-is.
        2. Known model table look-up.
        3. Conservative fallback: 8,192 tokens (smallest common Groq model window).
        """
        override = settings.LLM_CONTEXT_WINDOW_TOKENS
        if override and override > 0:
            return override
        # Normalise model name: strip provider prefixes like "groq/"
        model_key = self.model.split("/")[-1].lower()
        return _KNOWN_MODEL_CONTEXT_WINDOWS.get(model_key, 8_192)

    @property
    def evidence_token_budget(self) -> int:
        """
        Tokens available for evidence context after reserving space for the
        question, system prompt, framing text, and the generated answer.
        """
        reserved = settings.LLM_ANSWER_RESERVE_TOKENS
        budget = self.context_window_tokens - reserved
        return max(budget, 512)  # always leave at least 512 tokens for evidence

    @property
    def evidence_char_budget(self) -> int:
        """Approximate character budget for evidence, derived from token budget."""
        return int(self.evidence_token_budget * _CHARS_PER_TOKEN)

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
    async def generate_answer(
        self,
        question: str,
        evidence_context: str,
    ) -> str:
        if not self._api_configured():
            logger.warning("Groq LLM API not configured. Running deterministic mock answer generator.")
            return self._mock_answer(question, evidence_context)

        import httpx

        # HARD CAP: prevent 413 Payload Too Large on highly restricted models
        max_evidence_chars = 6000
        safe_evidence = evidence_context
        if len(safe_evidence) > max_evidence_chars:
            safe_evidence = safe_evidence[:max_evidence_chars] + "\n\n... [Evidence truncated to fit LLM safety limits]"

        user_prompt = (
            f"Question: {question}\n\n"
            f"Retrieved evidence (only use information from below):\n"
            f"---------------------\n"
            f"{safe_evidence}\n"
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
            "response_format": {"type": "json_object"},
        }

        active_key = self.api_keys[self.active_key_index]
        headers = {"Authorization": f"Bearer {active_key}"}
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=180.0) as client:
                resp = await client.post("/chat/completions", json=payload, headers=headers)
        except Exception as e:
            health_tracker.update_status("llm", 503)
            raise RuntimeError(f"LLM network error: {e}")

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
                retry_after = 60

            health_tracker.update_status("llm", 429, retry_after)
            logger.warning(f"LLM Rate Limited on key index {old_index}. Automatically rotated to key index {self.active_key_index}. Next retry in {retry_after}s if same key is hit.")
            raise RuntimeError(f"LLM Rate Limited (HTTP 429). Will retry with new key.")

        health_tracker.update_status("llm", resp.status_code)

        if resp.status_code != 200:
            logger.error(f"Groq LLM error {resp.status_code}: {resp.text}")
            raise RuntimeError(f"LLM generation failed: {resp.status_code}")

        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()
        return self._parse_and_format_response(content, evidence_context)

    def _parse_and_format_response(self, content: str, evidence_context: str) -> str:
        import json
        import re
        from pydantic import BaseModel, ValidationError, Field

        class Citation(BaseModel):
            evidence_id: str
            timestamp_start: Optional[float] = None
            timestamp_end: Optional[float] = None
            reason: Optional[str] = None

        class StructuredOutput(BaseModel):
            answer: str
            citations: list[Citation] = Field(default_factory=list)
            
        try:
            parsed = StructuredOutput.model_validate_json(content)
        except ValidationError:
            try:
                raw = json.loads(content)
                parsed = StructuredOutput(
                    answer=raw.get("answer", content),
                    citations=[]
                )
            except Exception:
                return content
                
        valid_ids = set(re.findall(r"\(Evidence ID:\s*([a-f0-9\-]{36})\)", evidence_context))
        
        valid_citations = []
        for c in parsed.citations:
            if c.evidence_id in valid_ids:
                valid_citations.append(c)
                
        answer_lines = [parsed.answer]
        if valid_citations:
            answer_lines.append("\n### Provenance")
            for c in valid_citations:
                ts = ""
                if c.timestamp_start is not None:
                    ts = f" (ts: {c.timestamp_start}s"
                    if c.timestamp_end is not None:
                        ts += f"-{c.timestamp_end}s"
                    ts += ")"
                reason = f" - {c.reason}" if c.reason else ""
                answer_lines.append(f"- Evidence {c.evidence_id}{ts}{reason}")
                
        return "\n".join(answer_lines)

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
