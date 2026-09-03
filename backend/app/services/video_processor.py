from __future__ import annotations
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ExtractedFrame:
    timestamp_seconds: float
    frame_path: str
    frame_number: int
    width: int
    height: int
    scene_score: float = 0.0
    is_important: bool = False


class VideoProcessor:
    def __init__(self):
        self.ffmpeg_path = settings.FFMPEG_PATH
        self.sample_interval = settings.FRAME_SAMPLE_INTERVAL
        self.scene_threshold = settings.SCENE_CHANGE_THRESHOLD
        self.max_important_frames = getattr(settings, "MAX_IMPORTANT_FRAMES", 30)
        self.corr_thresh = getattr(settings, "SCENE_CORR_THRESHOLD", 0.80)
        self.pixel_diff_thresh = getattr(settings, "SCENE_PIXEL_DIFF_THRESHOLD", 0.08)

    def _check_tools(self) -> None:
        if shutil.which(self.ffmpeg_path) is None:
            raise RuntimeError(f"FFmpeg not found at '{self.ffmpeg_path}'. Please install FFmpeg.")

    def get_video_info(self, video_path: Path) -> dict:
        if shutil.which(self.ffmpeg_path) is not None:
            cmd = [
                self.ffmpeg_path, "-i", str(video_path),
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height,r_frame_rate,duration,nb_frames",
                "-show_entries", "format=duration,size",
                "-of", "json",
            ]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=60)
                import json
                info = json.loads(result.stdout)
                stream = info.get("streams", [{}])[0]
                fmt = info.get("format", {})
                r_frame_rate = stream.get("r_frame_rate", "0/1")
                num, den = map(int, r_frame_rate.split("/"))
                fps = num / den if den > 0 else 0.0
                return {
                    "width": int(stream.get("width", 0)),
                    "height": int(stream.get("height", 0)),
                    "fps": fps,
                    "duration_seconds": float(fmt.get("duration", stream.get("duration", 0))),
                    "total_frames": int(stream.get("nb_frames", 0)),
                    "file_size": int(fmt.get("size", 0)) if "size" in fmt else video_path.stat().st_size,
                }
            except Exception as e:
                logger.warning(f"Could not get video info via ffmpeg: {e}")
        
        # Fallback to OpenCV
        try:
            cap = cv2.VideoCapture(str(video_path))
            if not cap.isOpened():
                return {}
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            duration = total_frames / fps if fps > 0 else 0.0
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            cap.release()
            return {
                "width": width,
                "height": height,
                "fps": fps,
                "duration_seconds": duration,
                "total_frames": total_frames,
                "file_size": video_path.stat().st_size,
            }
        except Exception as e:
            logger.warning(f"Could not get video info via opencv: {e}")
            return {}

    def extract_audio(self, video_path: Path, output_audio_path: Path) -> Path:
        self._check_tools()
        output_audio_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            self.ffmpeg_path, "-y", "-i", str(video_path),
            "-vn", "-acodec", "libmp3lame", "-ar", "16000", "-ac", "1",
            str(output_audio_path),
        ]
        logger.info(f"Extracting audio: {' '.join(cmd)}")
        subprocess.run(cmd, capture_output=True, check=True, timeout=600)
        return output_audio_path

    def _extract_features(self, frame: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        small = cv2.resize(frame, (320, int(320 * frame.shape[0] / max(1, frame.shape[1]))))
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [32, 32], [0, 180, 0, 256])
        cv2.normalize(hist, hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        return hist, gray

    def _compare_features(self, feat1, feat2) -> tuple[float, float]:
        hist1, gray1 = feat1
        hist2, gray2 = feat2
        hist_corr = cv2.compareHist(hist1, hist2, cv2.HISTCMP_CORREL)
        diff = cv2.absdiff(gray1, gray2)
        _, thresh = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)
        changed_pixels = cv2.countNonZero(thresh) / thresh.size
        return hist_corr, changed_pixels

    def sample_frames(
        self,
        video_path: Path,
        output_frames_dir: Path,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> list[ExtractedFrame]:
        output_frames_dir.mkdir(parents=True, exist_ok=True)

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video: {video_path}")

        try:
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            duration = total_frames / fps if fps > 0 else 0
            frame_step = max(1, int(fps * self.sample_interval))

            logger.info(f"Video: {total_frames} frames, {fps:.2f} fps, {duration:.1f}s, step={frame_step}")

            sampled_frames: list[ExtractedFrame] = []
            prev_feat = None
            saved_features = []
            
            frame_idx = 0
            saved_idx = 0
            num_important = 0

            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                if frame_idx % frame_step == 0:
                    timestamp = frame_idx / fps if fps > 0 else frame_idx / 30.0
                    height, width = frame.shape[:2]

                    feat = self._extract_features(frame)
                    
                    is_important = False
                    scene_score = 0.0
                    
                    if prev_feat is None:
                        is_important = True
                    else:
                        h_corr, p_diff = self._compare_features(prev_feat, feat)
                        scene_score = (1.0 - h_corr) * 10.0 + (p_diff * 10.0)
                        
                        if h_corr < self.corr_thresh or p_diff > self.pixel_diff_thresh:
                            is_dup = False
                            for s_feat in saved_features[-5:]:
                                ch, cp = self._compare_features(s_feat, feat)
                                if ch > 0.95 and cp < 0.02:
                                    is_dup = True
                                    break
                            if not is_dup:
                                is_important = True

                    if is_important:
                        if num_important >= self.max_important_frames:
                            is_important = False
                        else:
                            num_important += 1
                            saved_features.append(feat)

                    prev_feat = feat

                    frame_filename = f"frame_{saved_idx:06d}_{timestamp:.1f}s.jpg"
                    frame_path = output_frames_dir / frame_filename
                    cv2.imwrite(str(frame_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])

                    sampled_frames.append(ExtractedFrame(
                        timestamp_seconds=timestamp,
                        frame_path=str(frame_path),
                        frame_number=frame_idx,
                        width=width,
                        height=height,
                        scene_score=scene_score,
                        is_important=is_important,
                    ))
                    saved_idx += 1

                    if progress_callback and total_frames > 0:
                        pct = min(99.0, (frame_idx / total_frames) * 100)
                        progress_callback(pct, f"Sampled {saved_idx} frames")

                frame_idx += 1
        finally:
            cap.release()

        logger.info(f"Sampled {len(sampled_frames)} frames total. {num_important} important.")
        if progress_callback:
            progress_callback(100.0, f"Finished frame sampling")
        
        # If no important frames were selected (e.g. static video with no changes), select the first one
        if num_important == 0 and len(sampled_frames) > 0:
            sampled_frames[0].is_important = True
            
        return sampled_frames


video_processor = VideoProcessor()
