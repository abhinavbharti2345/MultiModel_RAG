import time
import random
import uuid
import sys
from pathlib import Path
from collections import defaultdict

# Mock classes
class Evidence:
    def __init__(self, id, modality, timestamp_start, timestamp_end):
        self.id = id
        self.modality = modality
        self.timestamp_start = timestamp_start
        self.timestamp_end = timestamp_end

class EvidenceEntity:
    def __init__(self, evidence_id, entity_id):
        self.evidence_id = evidence_id
        self.entity_id = entity_id

def benchmark_old(num_evidence):
    # Setup
    evidence_list = []
    entities_db = []
    
    for i in range(num_evidence):
        modality = random.choice(["audio", "visual", "text"])
        t = random.uniform(0, 3600)
        e = Evidence(i, modality, t, t + 5)
        evidence_list.append(e)
        
        # assign 2 random entities (out of 50 possible)
        for _ in range(2):
            entities_db.append(EvidenceEntity(i, random.randint(0, 50)))
            
    print(f"\nBenchmarking N={num_evidence}")
    
    # OLD shared_entity O(N^2)
    t0 = time.time()
    pairs = 0
    
    # Simulate DB index
    db_index = defaultdict(set)
    for ee in entities_db:
        db_index[ee.evidence_id].add(ee.entity_id)
        
    for i, a in enumerate(evidence_list):
        for b in evidence_list[i + 1:]:
            if a.modality != b.modality:
                a_ents = db_index[a.id] # simulated DB query
                b_ents = db_index[b.id] # simulated DB query
                if len(a_ents & b_ents) >= 1:
                    pairs += 1
    t1 = time.time()
    print(f"Old approach shared_entity: {pairs} pairs in {t1-t0:.4f}s")
    
    # NEW shared_entity using inverted index
    t0 = time.time()
    pairs_new = 0
    entity_to_evs = defaultdict(list)
    for ee in entities_db:
        entity_to_evs[ee.entity_id].append(ee.evidence_id)
        
    pair_counts = defaultdict(int)
    for entity_id, evidence_ids in entity_to_evs.items():
        for i in range(len(evidence_ids)):
            for j in range(i + 1, len(evidence_ids)):
                a, b = evidence_ids[i], evidence_ids[j]
                if a > b:
                    a, b = b, a
                pair_counts[(a, b)] += 1
                
    modality_map = {e.id: e.modality for e in evidence_list}
    for (a_id, b_id), count in pair_counts.items():
        if count >= 1 and modality_map[a_id] != modality_map[b_id]:
            pairs_new += 1
    t1 = time.time()
    print(f"New approach shared_entity: {pairs_new} pairs in {t1-t0:.4f}s")

if __name__ == "__main__":
    benchmark_old(100)
    benchmark_old(1000)
    benchmark_old(5000)
