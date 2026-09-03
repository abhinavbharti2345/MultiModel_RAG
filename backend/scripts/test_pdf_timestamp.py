"""
Tests to verify that PDF and image evidence correctly handles timestamps and page numbers,
and does not fake video timestamps.
"""
import sys
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.database import SessionLocal
from app.models.db_models import Source, SourceType, ProcessingStatus, Evidence, ModalityType, Frame
from app.services.ingestion_orchestrator import IngestionOrchestrator
from app.services.document_ingestor import PDFPage, ImageText, document_ingestor

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"

def check(label: str, condition: bool, detail: str = "") -> bool:
    status = PASS if condition else FAIL
    print(f"  {status}  {label}" + (f"  [{detail}]" if detail else ""))
    return condition

def test_ingest_pdf():
    print("\n[1] Testing PDF ingestion timestamp handling")
    db = SessionLocal()
    orchestrator = IngestionOrchestrator(db)
    
    # Mock extract to return one page with an image
    original_extract = document_ingestor.extract_pdf_pages
    def mock_extract(pdf_path, progress_callback=None):
        return [PDFPage(page_number=5, text="Mock text", image_paths=["dummy.png"])]
    
    # Mock image analysis
    original_analyze = document_ingestor.analyze_image
    def mock_analyze(image_path, context=None):
        return ImageText(text="OCR", description="Visual", entities=[])
        
    document_ingestor.extract_pdf_pages = mock_extract
    document_ingestor.analyze_image = mock_analyze
    
    # Create fake image
    img_path = Path("dummy.png")
    img_path.touch()
    
    source = Source(
        id=uuid.uuid4(),
        name="test.pdf",
        source_type=SourceType.PDF,
        file_path="test.pdf",
        status=ProcessingStatus.PENDING,
    )
    db.add(source)
    db.commit()

    # Skip Qdrant indexing for test
    orchestrator._embed_and_index_evidence = lambda sid: None

    try:
        orchestrator.ingest_pdf(source.id, Path("test.pdf"))
        
        # Verify
        evs = db.query(Evidence).filter(Evidence.source_id == source.id).all()
        frames = db.query(Frame).filter(Frame.source_id == source.id).all()
        
        passed = True
        passed &= check("Evidence generated", len(evs) > 0)
        
        for ev in evs:
            passed &= check(f"{ev.modality.value} evidence has correct page number", ev.page_number == 5, f"got {ev.page_number}")
            passed &= check(f"{ev.modality.value} evidence has NO timestamp", ev.timestamp_start is None, f"got {ev.timestamp_start}")
            
        for fr in frames:
            passed &= check(f"Frame has correct page number", fr.frame_number == 5, f"got {fr.frame_number}")
            passed &= check(f"Frame has NO timestamp", fr.timestamp_seconds is None, f"got {fr.timestamp_seconds}")
            
    finally:
        document_ingestor.extract_pdf_pages = original_extract
        document_ingestor.analyze_image = original_analyze
        if img_path.exists():
            img_path.unlink()
        db.close()
    return passed


def test_ingest_image():
    print("\n[2] Testing standalone image ingestion timestamp handling")
    db = SessionLocal()
    orchestrator = IngestionOrchestrator(db)
    
    # Mock image analysis
    original_analyze = document_ingestor.analyze_image
    def mock_analyze(image_path, context=None):
        return ImageText(text="OCR", description="Visual", entities=[])
        
    document_ingestor.analyze_image = mock_analyze
    
    # Create fake image
    img_path = Path("dummy_image.png")
    img_path.touch()
    
    source = Source(
        id=uuid.uuid4(),
        name="test.png",
        source_type=SourceType.IMAGE,
        file_path=str(img_path),
        status=ProcessingStatus.PENDING,
    )
    db.add(source)
    db.commit()

    # Skip Qdrant indexing for test
    orchestrator._embed_and_index_evidence = lambda sid: None

    try:
        orchestrator.ingest_image(source.id, img_path)
        
        # Verify
        evs = db.query(Evidence).filter(Evidence.source_id == source.id).all()
        frames = db.query(Frame).filter(Frame.source_id == source.id).all()
        
        passed = True
        passed &= check("Evidence generated", len(evs) > 0)
        
        for ev in evs:
            passed &= check(f"{ev.modality.value} evidence has NO page number", ev.page_number is None, f"got {ev.page_number}")
            passed &= check(f"{ev.modality.value} evidence has NO timestamp", ev.timestamp_start is None, f"got {ev.timestamp_start}")
            
        for fr in frames:
            passed &= check(f"Frame has NO timestamp", fr.timestamp_seconds is None, f"got {fr.timestamp_seconds}")
            
    finally:
        document_ingestor.analyze_image = original_analyze
        if img_path.exists():
            img_path.unlink()
        db.close()
    return passed

if __name__ == "__main__":
    r1 = test_ingest_pdf()
    r2 = test_ingest_image()
    
    if r1 and r2:
        print("\nAll tests passed!")
        sys.exit(0)
    else:
        print("\nSome tests failed.")
        sys.exit(1)
