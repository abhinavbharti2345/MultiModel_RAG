import httpx, time, sys

print('Uploading Video...')
with open('test_video.mp4', 'rb') as f:
    resp = httpx.post('http://localhost:8000/api/upload', files={'file': f}, timeout=10.0)
    
if resp.status_code not in (200, 202):
    print('Failed to upload:', resp.text)
    sys.exit(1)

data = resp.json()
print('Upload successful:', data)
source_id = data['source_id']

print('Polling status...')
for _ in range(60):
    status_resp = httpx.get(f'http://localhost:8000/api/sources/{source_id}/status')
    if status_resp.status_code == 200:
        status_data = status_resp.json()
        print(f"{status_data['status']}: {status_data['status_message']} ({status_data['progress_percent']}%)")
        if status_data['status'] in ['completed', 'failed']:
            break
    time.sleep(2)
