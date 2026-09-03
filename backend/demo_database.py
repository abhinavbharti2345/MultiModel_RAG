import os
import sys
from pathlib import Path

# Add backend directory to path so we can import app modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.db_models import Evidence, Relationship, Source

def print_demo():
    print("=" * 80)
    print("MULTIMODAL RAG - DATABASE TRACE DEMO")
    print("=" * 80)
    
    db: Session = SessionLocal()
    
    try:
        # Get all sources
        sources = db.query(Source).all()
        print(f"\n[1] SOURCES INGESTED ({len(sources)} total):")
        for s in sources:
            print(f"  - {s.source_type.value.upper()}: '{s.name}' (Status: {s.status.value})")

        # Get relationships to demonstrate cross-modal graph
        relationships = db.query(Relationship).all()
        print(f"\n[2] CROSS-MODAL GRAPH RELATIONSHIPS ({len(relationships)} edges):")
        
        # Display a few interesting relationships (like EXPLAINS or SAME_SOURCE)
        for i, rel in enumerate(relationships[:10]):
            from_ev = rel.from_evidence
            to_ev = rel.to_evidence
            
            # Format temporal data
            from_ts = f"{from_ev.timestamp_start}s" if from_ev.timestamp_start is not None else "N/A"
            to_ts = f"{to_ev.timestamp_start}s" if to_ev.timestamp_start is not None else "N/A"
            
            print(f"\n  --- Relationship #{i+1} [{rel.relationship_type}] ---")
            print(f"  From ({from_ev.modality.value.upper()} @ {from_ts}): {from_ev.content[:80]}...")
            print(f"   => To ({to_ev.modality.value.upper()} @ {to_ts}): {to_ev.content[:80]}...")
            print(f"  Graph Metadata: {rel.rel_metadata}")

        if len(relationships) > 10:
            print(f"\n  ... and {len(relationships) - 10} more graph edges ...")

        # Pick one specific evidence to show full depth (Explanation/OCR)
        if relationships:
            print("\n[3] DEEP DIVE: EVIDENCE EXPLANATION & PROVENANCE")
            sample_ev = relationships[0].from_evidence
            print(f"  Evidence ID: {sample_ev.id}")
            print(f"  Modality: {sample_ev.modality.value.upper()}")
            print(f"  Source: {sample_ev.source.name}")
            print(f"  Content:")
            print(f"    {sample_ev.content}")
            print(f"  Provenance Metadata (JSON):")
            print(f"    {sample_ev.provenance}")
            
            # Show attached entities
            entities = [e.name for e in sample_ev.entities]
            if entities:
                print(f"  Extracted Entities: {', '.join(entities)}")

    finally:
        db.close()
        print("\n" + "=" * 80)

if __name__ == "__main__":
    print_demo()
