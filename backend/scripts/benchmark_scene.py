import cv2
import numpy as np
import time
from pathlib import Path
import sys
import json

# Get a test video
video_path = next(Path("storage/uploads").glob("*.mp4"), None)
if not video_path:
    print("No video found for benchmarking.")
    sys.exit(1)
print(f"Benchmarking video: {video_path}")

def old_diff(prev_gray, curr_gray):
    if prev_gray.shape != curr_gray.shape:
        return 100.0
    diff = cv2.absdiff(prev_gray, curr_gray)
    return float(np.mean(diff))

def new_features(frame):
    small = cv2.resize(frame, (320, 180))
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [32, 32], [0, 180, 0, 256])
    cv2.normalize(hist, hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    return hist, gray

def new_diff(feat1, feat2):
    hist1, gray1 = feat1
    hist2, gray2 = feat2
    
    hist_corr = cv2.compareHist(hist1, hist2, cv2.HISTCMP_CORREL)
    
    diff = cv2.absdiff(gray1, gray2)
    _, thresh = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)
    changed_pixels = cv2.countNonZero(thresh) / thresh.size
    
    return hist_corr, changed_pixels

def run_benchmark():
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    
    frame_step = max(1, int(fps * 3)) # Sample every 3 seconds (as configured in app)
    
    old_scores = []
    
    prev_gray_old = None
    prev_feat_new = None
    
    frame_idx = 0
    t0_old = 0
    t0_new = 0
    
    saved_new_frames = [] # To test deduplication
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        if frame_idx % frame_step == 0:
            timestamp = frame_idx / fps
            
            # --- OLD ---
            t = time.time()
            gray_old = cv2.cvtColor(cv2.resize(frame, (320, int(320 * frame.shape[0] / frame.shape[1]))), cv2.COLOR_BGR2GRAY)
            s_old = old_diff(prev_gray_old, gray_old) if prev_gray_old is not None else 0.0
            prev_gray_old = gray_old
            old_scores.append(s_old)
            t0_old += (time.time() - t)
            
            # --- NEW ---
            t = time.time()
            feat_new = new_features(frame)
            if prev_feat_new is None:
                saved_new_frames.append(feat_new)
            else:
                h_corr, p_diff = new_diff(prev_feat_new, feat_new)
                
                # Check if it's a scene change
                is_scene_change = (h_corr < 0.85) or (p_diff > 0.05)
                
                if is_scene_change:
                    # Deduplicate: check against recently saved frames
                    is_dup = False
                    for saved_feat in reversed(saved_new_frames[-5:]): # Check last 5 keyframes
                        c, p = new_diff(saved_feat, feat_new)
                        if c > 0.95 and p < 0.02:
                            is_dup = True
                            break
                    if not is_dup:
                        saved_new_frames.append(feat_new)
                        
            prev_feat_new = feat_new
            t0_new += (time.time() - t)
            
        frame_idx += 1
            
    cap.release()
    
    # Old selection
    scores_arr = np.array(old_scores)
    z_scores_old = (scores_arr - scores_arr.mean()) / (scores_arr.std() + 1e-6)
    old_important = np.sum(z_scores_old > 1.5)
    
    new_important = len(saved_new_frames)
    
    report = {
        "old_frames": int(old_important),
        "new_frames": new_important,
        "old_time_ms": t0_old * 1000,
        "new_time_ms": t0_new * 1000,
        "processed_frames": frame_idx // frame_step
    }
    print(json.dumps(report, indent=2))

if __name__ == '__main__':
    run_benchmark()
