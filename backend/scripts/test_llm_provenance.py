import json
from app.services.llm_service import llm_service

EVIDENCE_CONTEXT = """
[00:20-00:25 AUDIO]  (Evidence ID: 11111111-1111-1111-1111-111111111111)
  Content: The system uses a PostgreSQL database.
---
[00:21-00:21 VISUAL]  (Evidence ID: 22222222-2222-2222-2222-222222222222)
  Content: Architecture diagram shows PostgreSQL connected to API.
---
"""

def test_valid_json_response():
    model_output = json.dumps({
        "answer": "The system uses PostgreSQL.",
        "citations": [
            {
                "evidence_id": "11111111-1111-1111-1111-111111111111",
                "timestamp_start": 20.0,
                "timestamp_end": 25.0,
                "reason": "Mentioned database type"
            }
        ]
    })
    
    result = llm_service._parse_and_format_response(model_output, EVIDENCE_CONTEXT)
    assert "The system uses PostgreSQL." in result
    assert "### Provenance" in result
    assert "Evidence 11111111" in result

def test_hallucinated_evidence_id():
    model_output = json.dumps({
        "answer": "The system uses PostgreSQL.",
        "citations": [
            {
                "evidence_id": "33333333-3333-3333-3333-333333333333",
                "reason": "I made this up"
            },
            {
                "evidence_id": "22222222-2222-2222-2222-222222222222",
                "reason": "Diagram"
            }
        ]
    })
    
    result = llm_service._parse_and_format_response(model_output, EVIDENCE_CONTEXT)
    assert "The system uses PostgreSQL." in result
    assert "Evidence 22222222" in result
    assert "Evidence 33333333" not in result

def test_malformed_json_fallback():
    model_output = "I couldn't generate JSON. The answer is PostgreSQL."
    result = llm_service._parse_and_format_response(model_output, EVIDENCE_CONTEXT)
    assert result == model_output

def test_json_missing_citations_field():
    model_output = json.dumps({
        "answer": "No citations provided."
    })
    result = llm_service._parse_and_format_response(model_output, EVIDENCE_CONTEXT)
    assert "No citations provided." in result
    assert "### Provenance" not in result

def test_multiple_citations():
    model_output = json.dumps({
        "answer": "It uses PostgreSQL.",
        "citations": [
            {
                "evidence_id": "11111111-1111-1111-1111-111111111111",
            },
            {
                "evidence_id": "22222222-2222-2222-2222-222222222222",
            }
        ]
    })
    result = llm_service._parse_and_format_response(model_output, EVIDENCE_CONTEXT)
    assert "Evidence 11111111" in result
    assert "Evidence 22222222" in result

if __name__ == "__main__":
    print("Running tests...")
    test_valid_json_response()
    test_hallucinated_evidence_id()
    test_malformed_json_fallback()
    test_json_missing_citations_field()
    test_multiple_citations()
    print("All tests passed!")
