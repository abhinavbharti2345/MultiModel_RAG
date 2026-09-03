import uuid
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.evidence_builder import EvidenceBuilder
from app.schemas.evidence_schemas import VisualAnalysisResult
from app.models.db_models import Evidence

def test_visual_evidence():
    db: Session = next(get_db())
    builder = EvidenceBuilder(db)
    
    source_id = uuid.uuid4()
    frame_id = uuid.uuid4()
    
    analysis = VisualAnalysisResult(
        description="A technical architecture diagram focusing on the data layer.",
        ocr_text="Data Layer: Caching Strategy\nRedis Cache (TTL 5min)\nPostgreSQL DB",
        entities=["Redis", "PostgreSQL", "TTL"],
        objects_detected=["architecture diagram", "boxes", "arrows"],
        relationships=["App reads from Redis", "Redis reads from PostgreSQL"],
        diagram_info="Data layer caching strategy showing read and write paths."
    )
    
    evidence = builder.create_evidence_from_visual(
        source_id=source_id,
        frame_id=frame_id,
        analysis=analysis,
        timestamp_seconds=20.5
    )
    
    print("\n=== GENERATED VISUAL EVIDENCE ===")
    print(evidence.content)
    print("\nEntities:", [ee.entity.name for ee in evidence.evidence_entities])
    print("=================================\n")

if __name__ == "__main__":
    test_visual_evidence()
