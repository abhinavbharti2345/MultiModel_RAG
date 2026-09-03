import httpx
import json

resp = httpx.post('http://localhost:8000/api/query', json={
    'query': 'Are there any diagrams in the PDF? What do they show?',
    'top_k': 5,
    'expand_relationships': True,
    'include_multimodal': True
}, timeout=60.0)

if resp.status_code == 200:
    data = resp.json()
    print("ANSWER:")
    print(data['answer'])
    print("\nEVIDENCE:")
    for i, e in enumerate(data['evidence']):
        ev = e['evidence']
        print(f"[{i+1}] {ev['modality']} (sim {e['similarity_score']:.2f}): {ev['content'][:150]}...")
else:
    print('Failed:', resp.text)
