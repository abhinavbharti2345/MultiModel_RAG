import time
from typing import Dict, Any, Optional

class HealthTracker:
    def __init__(self):
        # Initial states
        self.services = {
            "llm": {"status": "ready", "retry_after": None, "last_updated": time.time()},
            "vlm": {"status": "ready", "retry_after": None, "last_updated": time.time()},
            "stt": {"status": "ready", "retry_after": None, "last_updated": time.time()},
            "embeddings": {"status": "ready", "retry_after": None, "last_updated": time.time()},
            "qdrant": {"status": "connected", "retry_after": None, "last_updated": time.time()}
        }

    def update_status(self, service: str, status_code: int, retry_after: Optional[int] = None):
        if service not in self.services:
            return

        status_str = "ready"
        if status_code == 200:
            if service == "qdrant":
                status_str = "connected"
            else:
                status_str = "ready"
        elif status_code == 429:
            status_str = "rate_limited"
        elif status_code == 401:
            status_str = "auth_error"
        elif status_code == 400:
            status_str = "invalid_request"
        elif status_code == 403:
            status_str = "access_denied"
        elif status_code >= 500:
            status_str = "unavailable"
        else:
            status_str = "unreachable"

        self.services[service] = {
            "status": status_str,
            "retry_after": retry_after,
            "last_updated": time.time()
        }

    def get_status(self) -> Dict[str, Any]:
        result = {}
        now = time.time()
        for svc, data in self.services.items():
            retry_after = data.get("retry_after")
            status = data.get("status")
            
            # Auto-clear rate limit if time has passed
            if status == "rate_limited" and retry_after:
                elapsed = now - data.get("last_updated", now)
                if elapsed >= retry_after:
                    status = "ready"
                    retry_after = None
                else:
                    retry_after = int(retry_after - elapsed)

            result[svc] = {
                "status": status,
            }
            if retry_after is not None:
                result[svc]["retry_after"] = retry_after
        return result

health_tracker = HealthTracker()
