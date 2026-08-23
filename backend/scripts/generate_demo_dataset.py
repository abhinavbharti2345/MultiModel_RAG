"""Generate a realistic multimodal demo dataset for the hackathon.

Produces four REAL files covering every modality required by the problem statement:

  1. design_doc.pdf        - text-based multi-page PDF (extracted with pypdf at ingest)
  2. caching_diagram.png   - rendered architecture diagram image (OCR'd/VLM-analyzed at ingest)
  3. meeting_narration.wav - spoken narration of the meeting (Windows SAPI TTS)
  4. meeting_recording.mp4 - video = diagram slideshow + narration track (requires FFmpeg;
                             skipped automatically when FFmpeg is unavailable)

All artifacts share ONE story (the Redis caching proposal from the architecture review),
so cross-modal questions have answers distributed across modalities.

Usage:
    python scripts/generate_demo_dataset.py
Output goes to storage/demo_dataset/.
"""
from __future__ import annotations

import sys
import shutil
import subprocess
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.config import settings  # noqa: E402

OUT_DIR = settings.STORAGE_PATH / "demo_dataset"

SLIDE_TIMELINE = [
    (0.0, 8.0, "welcome"),
    (8.0, 20.0, "problem"),
    (20.0, 40.0, "proposal"),
    (40.0, 55.0, "diagram"),
    (55.0, 70.0, "numbers"),
]

NARRATION_LINES = [
    "Welcome everyone to the quarterly architecture review. I am Sarah Chen, principal engineer on the platform team.",
    "Our PostgreSQL cluster is under heavy load during peak hours. Read traffic has grown three hundred percent since last quarter.",
    "I propose we introduce a Redis caching layer in front of PostgreSQL. Reads check Redis first, and cache misses fall through to the database.",
    "On this slide you can see the full data flow. Clients hit the API gateway, then application servers consult the Redis cache before touching PostgreSQL. Writes go through Postgres first and invalidate the cache, which is our write-through pattern.",
    "With a five minute time to live on cached entries we expect roughly sixty percent of read traffic to be absorbed by Redis. Action items are in the design document, section three point two, and the full diagram is in appendix page seven.",
]


def _wrap(draw, text, font, max_width):
    lines, line = [], ""
    for word in text.split():
        trial = (line + " " + word).strip()
        if draw.textlength(trial, font=font) <= max_width:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def make_pdf(path: Path) -> None:
    """Write a simple but valid multi-page text PDF (Helvetica, no compression)."""
    pages = [
        ("Multimodal RAG Platform - Architecture Design Document",
         ["Version 2.4 - Platform Team",
          "",
          "1. Executive Summary",
          "This document specifies the caching architecture agreed during the",
          "quarterly architecture review led by Sarah Chen (Principal Engineer).",
          "It accompanies the recorded meeting session and the annotated",
          "caching diagram distributed to the team."]),
        ("2. Background and Problem Statement",
         ["PostgreSQL read traffic grew 300% over the last quarter.",
          "Peak-hour CPU utilization on the primary replica reached 85% and P95",
          "query latency exceeded 1.2 seconds, violating our 200ms target.",
          "",
          "Root cause: repeated execution of hot read queries that change rarely,",
          "including product catalog lookups and user session joins."]),
        ("3. Proposed Solution: Redis Caching Layer",
         ["Section 3.2 - Data Flow",
          "A Redis cache sits between application servers and PostgreSQL.",
          "",
          "Read path:  App Server -> Redis -> (on miss) -> PostgreSQL,",
          "            then populate Redis with TTL of 300 seconds (5 minutes).",
          "Write path: App Server -> PostgreSQL first, then synchronously",
          "            invalidate and refresh the matching Redis key",
          "            (write-through pattern).",
          "",
          "Expected impact: about 60% of read queries served from Redis,",
          "reducing database load proportionally. See Figure 7-1, appendix page 7",
          "for the complete annotated data-flow diagram discussed in the meeting."]),
        ("4. Operational Notes",
         ["QPS target: 10,000 sustained. SLA: 99.9% availability.",
          "If Redis is unavailable all traffic falls back to PostgreSQL;",
          "Redis sits on the performance critical path, not the availability path.",
          "",
          "Appendix reference: Figure 7-1 on page 7 mirrors the slide shown at",
          "minute 00:40 in the recorded review session."]),
        ("7. Appendix: Data Flow Diagram (Figure 7-1)",
         ["Redis + PostgreSQL Caching Architecture",
          "",
          "[Clients] -> [API Gateway] -> [Load Balancers] -> [App Servers]",
          "                                             /             \\",
          "                              [Redis Cache] <             > [PostgreSQL]",
          "                                TTL 300s                  write-through",
          "",
          "Annotations:",
          "- Read reduction target: 60%",
          "- TTL: 5 minutes",
          "- Proposed by: Sarah Chen, Principal Engineer",
          "- Presented in meeting_recording.mp4 at 00:40"]),

    ]

    def esc(s: str) -> str:
        return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")

    objects: list[bytes] = []

    def add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)

    font_id = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    font_bold_id = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")

    content_ids, page_ids = [], []
    pages_node_id_placeholder = len(objects) + 2 * len(pages) + 1

    for title, lines in pages:
        stream_lines = []
        y = 760
        stream_lines.append(f"BT /F2 16 Tf 60 {y} Td ({esc(title)}) Tj ET")
        y -= 34
        body = lines
        for ln in body:
            stream_lines.append(f"BT /F1 11 Tf 60 {y} Td ({esc(ln) if ln else ''}) Tj ET")
            y -= 18
        stream = "\n".join(stream_lines).encode("latin-1", errors="replace")
        cid = add(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
        content_ids.append(cid)

    pages_kids = b""
    for idx, (title, lines) in enumerate(pages):
        pid = add(
            b"<< /Type /Page /Parent 3 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 " + str(font_id).encode() + b" 0 R /F2 "
            + str(font_bold_id).encode() + b" 0 R >> >> /Contents "
            + str(content_ids[idx]).encode() + b" 0 R >>"
        )
        page_ids.append(pid)
        pages_kids += str(pid).encode() + b" 0 R "

    pages_id = add(b"<< /Type /Pages /Kids [" + pages_kids + b"] /Count " + str(len(pages)).encode() + b" >>")
    catalog_id = add(b"<< /Type /Catalog /Pages " + str(pages_id).encode() + b" 0 R >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += str(i).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n"
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        b"trailer\n<< /Size " + str(len(objects) + 1).encode()
        + b" /Root " + str(catalog_id).encode() + b" 0 R >>\nstartxref\n"
        + str(xref_pos).encode() + b"\n%%EOF\n"
    )
    path.write_bytes(bytes(out))
    print(f"[+] Wrote {path.name} ({path.stat().st_size} bytes, {len(pages)} pages)")


def make_image(path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    W, H = 1280, 720
    img = Image.new("RGB", (W, H), "#0f172a")
    d = ImageDraw.Draw(img)

    def font(size, bold=False):
        for name in (["segoeuib.ttf", "arialbd.ttf"] if bold else ["segoeui.ttf", "arial.ttf"]):
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        return ImageFont.load_default()

    title_f, box_f, small_f = font(30, bold=True), font(17), font(14)

    d.text((W // 2 - d.textlength("Data Layer Caching Strategy", font=title_f) / 2, 24),
           "Data Layer Caching Strategy", fill="white", font=title_f)
    d.text((W // 2 - d.textlength("Architecture Review - presented by Sarah Chen", font=small_f) / 2, 66),
           "Architecture Review - presented by Sarah Chen", fill="#94a3b8", font=small_f)

    boxes = {
        "clients": (60, 160, 240, 230, "[Clients]", "#334155"),
        "gateway": (330, 160, 510, 230, "[API Gateway]", "#334155"),
        "lb": (600, 160, 780, 230, "[Load Balancers]", "#334155"),
        "app": (870, 160, 1080, 230, "[App Servers]", "#334155"),
        "redis": (700, 400, 920, 500, "[Redis Cache]\nTTL 300s (5 min)", "#7c2d12"),
        "pg": (1010, 400, 1230, 500, "[PostgreSQL]\npersistence", "#164e63"),
    }
    for x0, y0, x1, y1, label, color in boxes.values():
        d.rounded_rectangle([x0, y0, x1, y1], radius=10, fill=color, outline="#38bdf8", width=2)
        ty = y0 + (y1 - y0) // 2 - 12 * (label.count("\n") + 1)
        for ln in label.split("\n"):
            tw = d.textlength(ln, font=box_f)
            d.text((x0 + ((x1 - x0) - tw) / 2, ty), ln, fill="white", font=box_f)
            ty += 24

    def arrow(p1, p2, label=None):
        d.line([p1, p2], fill="#38bdf8", width=3)
        ax, ay = p2
        d.polygon([(ax - 6, ay - 10), (ax + 6, ay - 10), (ax, ay)], fill="#38bdf8")
        if label:
            mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2 - 22
            d.text((mx - d.textlength(label, font=small_f) / 2, my), label,
                   fill="#fbbf24", font=small_f)

    arrow((240, 195), (328, 195))
    arrow((512, 195), (598, 195))
    arrow((782, 195), (868, 195))
    arrow((975, 232), (800, 398), "read: check cache first")
    arrow((1120, 232), (1115, 398), "on miss / writes")
    arrow((922, 450), (1008, 450), "hydrate on miss")
    arrow((1064, 498), (958, 498), "write-through invalidate+refresh")

    d.rectangle([50, 580, W - 50, 690], outline="#475569", width=1)
    notes = [
        "Read path:  App Servers -> Redis Cache -> (MISS) -> PostgreSQL  |  populate Redis, TTL 5 min",
        "Write path: App Servers -> PostgreSQL -> invalidate + refresh Redis key (write-through)",
        "Expected read reduction: ~60%   QPS target: 10k   SLA: 99.9%   Full detail: design_doc.pdf page 7",
    ]
    for i, n in enumerate(notes):
        d.text((70, 594 + i * 30), n, fill="#cbd5e1", font=small_f)

    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, quality=92)
    print(f"[+] Wrote {path.name} ({path.stat().st_size} bytes)")


def make_audio_wav(path: Path) -> bool:
    """Narrate the meeting with Windows SAPI TTS. Returns False when unavailable."""
    import json
    import tempfile

    tmp_dir = path.parent / "_tts_parts"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    ps1: Path | None = None  # type: ignore[annotation-unchecked]

    json_lines = json.dumps(NARRATION_LINES).replace("'", "''")
    ps_script = f"""
$raw = '{json_lines}'
$lines = $raw | ConvertFrom-Json
$outDir = "{tmp_dir.resolve().as_posix()}"
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.Rate = -1
$idx = 1
foreach ($line in $lines) {{
    $out = Join-Path $outDir ("narration_{{0:d2}}.wav" -f $idx)
    $synth.SetOutputToWaveFile($out)
    $synth.Speak($line)
    $synth.SetOutputToNull()
    $idx++
}}
"""
    try:
        with tempfile.NamedTemporaryFile(suffix=".ps1", delete=False) as tf:
            tf.write(ps_script.encode("utf-8-sig"))
            ps1 = Path(tf.name)
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)],
            capture_output=True, text=True, timeout=300,
        )
        parts = sorted(tmp_dir.glob("narration_*.wav"))
        if not parts:
            print(f"[!] SAPI TTS produced no audio; skipping WAV. {(result.stderr or '')[:300]}")
            return False

        wav_path = path.with_suffix(".wav")
        if shutil.which(settings.FFMPEG_PATH):
            concat_args = []
            for p in parts:
                concat_args += ["-i", str(p)]
            cmd = [settings.FFMPEG_PATH, "-y", *concat_args,
                   "-filter_complex", f"concat=n={len(parts)}:v=0:a=1[aout]",
                   "-map", "[aout]", "-ar", "16000", "-ac", "1", str(wav_path)]
            subprocess.run(cmd, capture_output=True, check=True, timeout=300)
        else:
            import wave
            frames = []
            params = None
            for p in parts:
                with wave.open(str(p), "rb") as w:
                    if params is None:
                        params = w.getparams()
                    frames.append(w.readframes(w.getnframes()))
            with wave.open(str(wav_path), "wb") as w:
                w.setparams(params)
                for fr in frames:
                    w.writeframes(fr)
        print(f"[+] Wrote {wav_path.name} ({wav_path.stat().st_size} bytes)")
        return True
    except Exception as e:
        print(f"[!] TTS generation failed ({e}); skipping WAV.")
        return False
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        if ps1 is not None:
            try:
                ps1.unlink(missing_ok=True)
            except Exception:
                pass


def make_video(mp4_path: Path, wav_path: Path) -> bool:
    """Slideshow of diagram frames + narration -> mp4. Requires FFmpeg."""
    if not shutil.which(settings.FFMPEG_PATH):
        print("[!] FFmpeg not found; skipping mp4 generation (run inside Docker or install FFmpeg).")
        return False
    try:
        from PIL import Image, ImageDraw, ImageFont
        tmp = mp4_path.parent / "_video_frames"
        tmp.mkdir(parents=True, exist_ok=True)

        base = Image.open(mp4_path.parent / "caching_diagram.png").convert("RGB")
        caption_font = None
        for name in ("segoeuib.ttf", "arialbd.ttf"):
            try:
                caption_font = ImageFont.truetype(name, 28)
                break
            except OSError:
                continue
        caption_font = caption_font or ImageFont.load_default()

        captions = [
            "Quarterly Architecture Review",
            "Problem: PostgreSQL under heavy peak-hour load",
            "Proposal: introduce a Redis caching layer",
            "The full data flow: gateway, cache-first reads, write-through",
            "TTL 5 minutes, expected 60% read reduction",
        ]
        frame_files = []
        for i, cap in enumerate(captions):
            frame = base.copy()
            d = ImageDraw.Draw(frame)
            d.rectangle([0, 660, 1280, 720], fill="#000000")
            d.text((30, 668), cap, fill="white", font=caption_font)
            fp = tmp / f"slide_{i}.png"
            frame.save(fp)
            frame_files.append(fp)

        if not wav_path.exists():
            silent = tmp / "silence.wav"
            subprocess.run(
                [settings.FFMPEG_PATH, "-y", "-f", "lavfi", "-i",
                 "anullsrc=r=16000:cl=mono", "-t", "70", str(silent)],
                capture_output=True, check=True, timeout=120,
            )
            wav_path = silent

        seg_args = []
        n_per = 70.0 / len(frame_files)
        for i, fp in enumerate(frame_files):
            start = i * n_per
            dur = n_per + (0.5 if i == len(frame_files) - 1 else 0)
            seg_args += ["-loop", "1", "-t", f"{dur:.2f}", "-i", str(fp)]
        seg_args += ["-i", str(wav_path)]

        n = len(frame_files)
        filter_parts = "".join(
            f"[{i}:v]scale=1280:720,setsar=1,fps=25[v{i}];" for i in range(n)
        )
        concat_in = "".join(f"[v{i}]" for i in range(n))
        filter_complex = (
            filter_parts
            + f"{concat_in}concat=n={n}:v=1:a=0[vout];"
            + f"[{n}:a]aresample=16000[aout]"
        )

        cmd = [settings.FFMPEG_PATH, "-y", *seg_args,
               "-filter_complex", filter_complex,
               "-map", "[vout]", "-map", "[aout]",
               "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-shortest", str(mp4_path)]
        subprocess.run(cmd, capture_output=True, check=True, timeout=900)
        shutil.rmtree(tmp, ignore_errors=True)
        size_mb = mp4_path.stat().st_size / 1e6
        print(f"[+] Wrote {mp4_path.name} ({size_mb:.1f} MB)")
        return True
    except Exception as e:
        print(f"[!] Video generation failed ({e}); skipping mp4.")
        return False


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Generating demo dataset in {OUT_DIR}\n")

    make_pdf(OUT_DIR / "design_doc.pdf")
    make_image(OUT_DIR / "caching_diagram.png")
    has_audio = make_audio_wav(OUT_DIR / "meeting_narration.wav")
    make_video(OUT_DIR / "meeting_recording.mp4",
               OUT_DIR / "meeting_narration.wav")

    print("\nDemo dataset ready. Ingest each file via POST /api/upload:")
    for f in sorted(OUT_DIR.iterdir()):
        if not f.name.startswith("_"):
            print(f"    {f.name}")


if __name__ == "__main__":
    main()
