import os
import json
import uuid
import asyncio
import subprocess
import glob
import re
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import anthropic

TEMP_DIR = Path("temp")
TEMP_DIR.mkdir(exist_ok=True)
STATIC_DIR = Path("static")

jobs: dict = {}
clips: dict = {}

app = FastAPI(title="YouTube Shorts Converter")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pydantic models ──────────────────────────────────────────────────────────

class DownloadRequest(BaseModel):
    url: str

class TranscribeRequest(BaseModel):
    job_id: str
    model: str = "base"

class AnalyzeRequest(BaseModel):
    job_id: str
    transcript: str
    segments: List[dict]

class ClipConfig(BaseModel):
    job_id: str
    clip_id: str
    start: float
    end: float
    title: str
    channel_name: str = ""
    hashtags: List[str] = []
    layout: str = "letterbox"   # "letterbox" | "crop"
    title_color: str = "white"
    title_size: int = 52
    show_subtitles: bool = True
    subtitle_color: str = "white"


# ── Helpers ──────────────────────────────────────────────────────────────────

def find_korean_font() -> Optional[str]:
    candidates = [
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    patterns = [
        "/usr/share/fonts/**/*anum*.ttf",
        "/usr/share/fonts/**/*oto*CJK*.ttc",
        "/usr/share/fonts/**/*.ttf",
    ]
    for pattern in patterns:
        found = glob.glob(pattern, recursive=True)
        if found:
            return found[0]
    return None


def esc_drawtext(text: str) -> str:
    return (
        text
        .replace("\\", "\\\\")
        .replace("'", "’")
        .replace(":", "\\:")
        .replace("%", "\\%")
    )


def make_ass_header(font_name: str) -> str:
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},46,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,60,60,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def fmt_ass_time(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def generate_ass(segments: list, start: float, end: float) -> str:
    font_path = find_korean_font()
    font_name = "NanumGothic"
    if font_path:
        base = Path(font_path).stem
        if "Noto" in base:
            font_name = "Noto Sans CJK KR"
        elif "DejaVu" in base:
            font_name = "DejaVu Sans"

    lines = [make_ass_header(font_name)]
    for seg in segments:
        if seg["end"] <= start or seg["start"] >= end:
            continue
        rel_s = max(0.0, seg["start"] - start)
        rel_e = min(end - start, seg["end"] - start)
        text = seg["text"].strip().replace("\n", " ")
        if text:
            lines.append(
                f"Dialogue: 0,{fmt_ass_time(rel_s)},{fmt_ass_time(rel_e)},"
                f"Default,,0,0,0,,{text}"
            )
    return "\n".join(lines)


def build_ffmpeg_vf(config: ClipConfig, font_path: Optional[str], ass_path: Optional[str]) -> str:
    title_e = esc_drawtext(config.title)
    channel_e = esc_drawtext(f"@{config.channel_name}" if config.channel_name else "")
    hashtags_str = " ".join(f"#{t.lstrip('#')}" for t in config.hashtags[:4])
    hashtags_e = esc_drawtext(hashtags_str)

    font_opt = f":fontfile='{font_path}'" if font_path else ""
    color = config.title_color
    size = config.title_size

    if config.layout == "letterbox":
        scale = "scale=1080:-2:force_original_aspect_ratio=decrease"
        pad = "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black"
        base_vf = f"{scale},{pad}"
    else:
        base_vf = "crop=in_h*9/16:in_h,scale=1080:1920"

    overlays = [base_vf]

    # Title
    overlays.append(
        f"drawtext=text='{title_e}'{font_opt}"
        f":x=(w-text_w)/2:y=80"
        f":fontsize={size}:fontcolor={color}"
        f":box=1:boxcolor=black@0.65:boxborderw=18"
        f":shadowx=2:shadowy=2:shadowcolor=black@0.8"
    )

    # Channel name
    if config.channel_name:
        overlays.append(
            f"drawtext=text='{channel_e}'{font_opt}"
            f":x=(w-text_w)/2:y=h-130"
            f":fontsize=34:fontcolor=white@0.95"
            f":box=1:boxcolor=black@0.55:boxborderw=12"
        )

    # Hashtags
    if hashtags_str:
        overlays.append(
            f"drawtext=text='{hashtags_e}'{font_opt}"
            f":x=(w-text_w)/2:y=h-75"
            f":fontsize=28:fontcolor=yellow@0.9"
            f":box=1:boxcolor=black@0.4:boxborderw=8"
        )

    # Subtitles
    if config.show_subtitles and ass_path:
        overlays.append(f"ass='{ass_path}'")

    return ",".join(overlays)


# ── API Endpoints ────────────────────────────────────────────────────────────

@app.get("/api/status/{job_id}")
def get_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    return jobs[job_id]


@app.post("/api/download")
async def download_video(req: DownloadRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "downloading", "progress": 0, "error": None}
    background_tasks.add_task(_do_download, job_id, req.url)
    return {"job_id": job_id}


async def _do_download(job_id: str, url: str):
    try:
        job_dir = TEMP_DIR / job_id
        job_dir.mkdir(exist_ok=True)

        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "-f", "best[height<=720][ext=mp4]/best[height<=720]/best",
            "--output", str(job_dir / "video.%(ext)s"),
            "--write-info-json",
            "--no-playlist",
            "--merge-output-format", "mp4",
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            jobs[job_id].update({"status": "error", "error": stderr.decode()[:800]})
            return

        video_files = [
            f for f in job_dir.glob("video.*")
            if f.suffix not in (".json", ".part", ".ytdl")
        ]
        if not video_files:
            jobs[job_id].update({"status": "error", "error": "No video file found after download"})
            return

        video_path = video_files[0]

        # Extract mono 16 kHz WAV for Whisper
        audio_path = job_dir / "audio.wav"
        await asyncio.create_subprocess_exec(
            "ffmpeg", "-i", str(video_path),
            "-vn", "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le",
            str(audio_path), "-y",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

        # Video metadata
        info_files = list(job_dir.glob("*.info.json"))
        info: dict = {}
        if info_files:
            with open(info_files[0], encoding="utf-8") as f:
                info = json.load(f)

        probe = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", str(video_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        probe_out, _ = await probe.communicate()
        probe_data = json.loads(probe_out or b"{}")
        duration = float(probe_data.get("format", {}).get("duration", 0))

        jobs[job_id].update({
            "status": "downloaded",
            "video_path": str(video_path),
            "audio_path": str(audio_path),
            "duration": duration,
            "title": info.get("title", "Unknown"),
            "channel": info.get("uploader", "Unknown"),
            "thumbnail": info.get("thumbnail", ""),
        })

    except Exception as exc:
        jobs[job_id].update({"status": "error", "error": str(exc)})


@app.post("/api/transcribe")
async def transcribe_video(req: TranscribeRequest, background_tasks: BackgroundTasks):
    if req.job_id not in jobs:
        raise HTTPException(404, "Job not found")
    jobs[req.job_id]["status"] = "transcribing"
    background_tasks.add_task(_do_transcribe, req.job_id, req.model)
    return {"status": "transcribing"}


async def _do_transcribe(job_id: str, model_name: str):
    try:
        audio_path = jobs[job_id]["audio_path"]
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _run_whisper, audio_path, model_name)
        jobs[job_id].update({
            "status": "transcribed",
            "transcript": result["text"],
            "segments": result["segments"],
        })
    except Exception as exc:
        jobs[job_id].update({"status": "error", "error": str(exc)})


def _run_whisper(audio_path: str, model_name: str) -> dict:
    import whisper  # imported here to avoid slow startup
    model = whisper.load_model(model_name)
    result = model.transcribe(audio_path, task="transcribe")
    segments = [
        {"start": round(s["start"], 2), "end": round(s["end"], 2), "text": s["text"].strip()}
        for s in result["segments"]
    ]
    return {"text": result["text"], "segments": segments}


@app.post("/api/analyze")
async def analyze_transcript(req: AnalyzeRequest):
    if req.job_id not in jobs:
        raise HTTPException(404, "Job not found")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(500, "ANTHROPIC_API_KEY not set")

    job = jobs[req.job_id]
    duration = job.get("duration", 0)
    channel = job.get("channel", "Unknown")

    segments_text = "\n".join(
        f"[{s['start']:.1f}s - {s['end']:.1f}s] {s['text']}"
        for s in req.segments
    )

    prompt = f"""당신은 SNS 바이럴 콘텐츠 전문가입니다.
아래 유튜브 영상 자막을 분석하여 쇼츠/릴스용 짧은 클립으로 만들기 좋은
가장 흥미로운 구간을 최대 6개 선별해주세요.

영상 길이: {duration:.0f}초 | 채널: {channel}

자막 (타임스탬프 포함):
{segments_text}

선택 기준:
- 각 구간은 15~60초 사이
- 시청자가 멈춰서 볼 만한 후킹 포인트 (반전, 유용한 팁, 감동, 논란, 재미)
- 서로 겹치지 않는 구간

아래 JSON 형식으로만 응답하세요 (다른 텍스트 없이):
{{
  "clips": [
    {{
      "start": 시작시간(초, 소수점1자리),
      "end": 종료시간(초, 소수점1자리),
      "title": "제목 (20자 이내)",
      "reason": "이 구간을 선택한 이유 (50자 이내)",
      "hashtags": ["태그1", "태그2", "태그3", "태그4", "태그5"],
      "hook_type": "tip|reaction|story|fact|humor"
    }}
  ]
}}"""

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    response_text = message.content[0].text
    json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
    if not json_match:
        raise HTTPException(500, f"Failed to parse Claude response: {response_text[:200]}")

    result = json.loads(json_match.group())

    for i, clip in enumerate(result.get("clips", [])):
        clip["clip_id"] = f"{req.job_id}_clip_{i}"
        clip["channel_name"] = channel

    jobs[req.job_id]["clips"] = result.get("clips", [])
    return result


@app.post("/api/generate-clip")
async def generate_clip(config: ClipConfig, background_tasks: BackgroundTasks):
    clip_key = config.clip_id
    clips[clip_key] = {"status": "processing"}
    background_tasks.add_task(_do_generate_clip, config)
    return {"clip_id": clip_key, "status": "processing"}


async def _do_generate_clip(config: ClipConfig):
    clip_key = config.clip_id
    try:
        job = jobs.get(config.job_id)
        if not job:
            clips[clip_key] = {"status": "error", "error": "Job not found"}
            return

        video_path = job["video_path"]
        output_dir = TEMP_DIR / config.job_id / "clips"
        output_dir.mkdir(parents=True, exist_ok=True)

        safe_name = re.sub(r"[^\w-]", "_", config.clip_id)
        output_path = output_dir / f"{safe_name}.mp4"
        duration = config.end - config.start

        # Build ASS subtitle file for this clip
        ass_path: Optional[str] = None
        if config.show_subtitles and "segments" in job:
            ass_content = generate_ass(job["segments"], config.start, config.end)
            ass_file = output_dir / f"{safe_name}.ass"
            ass_file.write_text(ass_content, encoding="utf-8")
            ass_path = str(ass_file)

        font_path = find_korean_font()
        vf = build_ffmpeg_vf(config, font_path, ass_path)

        cmd = [
            "ffmpeg",
            "-ss", str(config.start),
            "-i", video_path,
            "-t", str(duration),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            "-r", "30",
            str(output_path), "-y",
        ]

        loop = asyncio.get_event_loop()
        proc_result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(cmd, capture_output=True, text=True),
        )

        if proc_result.returncode != 0 or not output_path.exists():
            err = proc_result.stderr[-600:] if proc_result.stderr else "Unknown ffmpeg error"
            clips[clip_key] = {"status": "error", "error": err}
            return

        clips[clip_key] = {
            "status": "ready",
            "path": str(output_path),
            "size": output_path.stat().st_size,
        }

    except Exception as exc:
        clips[clip_key] = {"status": "error", "error": str(exc)}


@app.get("/api/clip-status/{clip_id:path}")
def get_clip_status(clip_id: str):
    if clip_id not in clips:
        raise HTTPException(404, "Clip not found")
    status = clips[clip_id].copy()
    status.pop("path", None)  # don't expose server path
    return status


@app.get("/api/preview/{clip_id:path}")
def preview_clip(clip_id: str, request: Request):
    if clip_id not in clips or clips[clip_id]["status"] != "ready":
        raise HTTPException(404, "Clip not ready")

    path = Path(clips[clip_id]["path"])
    file_size = path.stat().st_size
    range_header = request.headers.get("range")

    if range_header:
        start_str, _, end_str = range_header.replace("bytes=", "").partition("-")
        start = int(start_str)
        end = int(end_str) if end_str else file_size - 1
        chunk = end - start + 1

        def _iter():
            with open(path, "rb") as f:
                f.seek(start)
                yield f.read(chunk)

        return StreamingResponse(
            _iter(),
            status_code=206,
            media_type="video/mp4",
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(chunk),
            },
        )

    return FileResponse(path, media_type="video/mp4")


@app.get("/api/download-clip/{clip_id:path}")
def download_clip(clip_id: str):
    if clip_id not in clips or clips[clip_id]["status"] != "ready":
        raise HTTPException(404, "Clip not ready")

    path = Path(clips[clip_id]["path"])
    idx = clip_id.split("_clip_")[-1] if "_clip_" in clip_id else "0"
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=f"shorts_clip_{idx}.mp4",
    )


# ── Static / index ───────────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def index():
    return FileResponse("static/index.html")
