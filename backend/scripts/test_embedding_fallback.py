"""
Tests to verify that embedding failures raise exceptions and do not
silently generate garbage fallback vectors.
"""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import asyncio
from app.services.embedding_service import embedding_service
from app.config import settings

def test_api_failure_raises():
    print("Testing API failure raises RuntimeError...")
    
    # Save original settings
    orig_api = settings.EMBEDDING_API_URL
    orig_key = settings.EMBEDDING_API_KEY
    
    # Force failure by using a bad URL or removing the provider
    embedding_service.api_url = None
    embedding_service.api_key = None
    embedding_service._use_local = False
    
    try:
        embedding_service.embed_texts(["This should fail"])
        print("FAIL: Expected RuntimeError, but got vectors!")
        sys.exit(1)
    except RuntimeError as e:
        assert "No embedding provider configured" in str(e)
        print("PASS: Missing provider raised RuntimeError correctly.")
    finally:
        embedding_service.api_url = orig_api
        embedding_service.api_key = orig_key
        embedding_service._use_local = not (orig_api and orig_key)


def test_local_model_failure_raises():
    print("Testing local model load failure raises RuntimeError...")
    
    embedding_service.api_url = None
    embedding_service.api_key = None
    embedding_service._use_local = True
    embedding_service.model = "invalid-model-name-12345"
    embedding_service._local_model = None
    
    try:
        embedding_service.embed_texts(["This should fail"])
        print("FAIL: Expected RuntimeError, but got vectors!")
        sys.exit(1)
    except RuntimeError as e:
        assert "Embedding configuration error" in str(e)
        print("PASS: Local model load failure raised RuntimeError correctly.")

if __name__ == "__main__":
    test_api_failure_raises()
    test_local_model_failure_raises()
    print("All tests passed!")
