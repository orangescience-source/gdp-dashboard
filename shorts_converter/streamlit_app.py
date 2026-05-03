import os
import sys
import io
import json
import uuid
import subprocess
import glob
import re
import zipfile
import logging
from pathlib import Path
from typing import Optional
from datetime import datetime

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"] = "1"
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import streamlit as st
import anthropic

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


# ── 작업 디렉터리 ─────────────────────────────────────────────────────────────

def _ascii_workdir() -> Path:
    base = Path("C:/shorts_output") if sys.platform == "win32" else Path("/tmp/shorts_output")
    base.mkdir(parents=True, exist_ok=True)
    return base

TEMP_DIR = _ascii_workdir()

# ── 페이지 설정 ───────────────────────────────────────────────────────────────

st.set_page_config(page_title="YouTube → Shorts 변환기", page_icon="🎬", layout="wide")

st.markdown("""
<style>
  [data-testid="stAppViewContainer"] { background: #0f0f17; }
  [data-testid="stSidebar"] { background: #1a1a2e; }
  h1,h2,h3 { color: #e2e8f0 !important; }
  .step-done   { color: #34d399; font-weight: 600; }
  .step-active { color: #a78bfa; font-weight: 600; }
  .step-wait   { color: #4a5568; }
  .tag { display:inline-block; background:#2d2d4e; color:#94a3b8;
         border-radius:6px; padding:2px 8px; font-size:12px; margin:2px; }
  .error-box { background:#2d1a1a; border:1px solid #7f1d1d;
               border-radius:8px; padding:12px; color:#fca5a5; }
  .score-badge { display:inline-block; background:#6d28d9; color:white;
                 border-radius:12px; padding:3px 10px; font-size:14px; font-weight:bold; }
  .timeline-wrap { background:#1e1e2e; border-radius:8px; padding:12px; margin:8px 0; }
</style>
""", unsafe_allow_html=True)


# ── 유틸 함수 ─────────────────────────────────────────────────────────────────

def fmt_time(t: float) -> str:
    m, s = divmod(int(t), 60)
    return f"{m}:{s:02d}"


def _find_font() -> str:
    candidates = [
        r"C:/Windows/Fonts/malgun.ttf",
        r"C:/Windows/Fonts/malgunbd.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    for pattern in ["/usr/share/fonts/**/*.ttf", "/usr/share/fonts/**/*.ttc"]:
        found = glob.glob(pattern, recursive=True)
        if found:
            return found[0]
    return ""


def _font_opt(font_path: str) -> str:
    if not font_path:
        return ""
    ff = font_path.replace("\\", "/").replace(":", "\\:")
    return f":fontfile='{ff}'"


def _esc(text: str) -> str:
    """ffmpeg drawtext 특수문자 이스케이프."""
    return (
        text
        .replace("\\", "\\\\")
        .replace("'",  "’")
        .replace(":",  "\\:")
        .replace("%",  "\\%")
        .replace("\n", " ")
    )


# ── Feature 1: 2줄 분리 ──────────────────────────────────────────────────────

def _split_lines(text: str, max_chars: int = 16) -> list:
    """단어 단위로 최대 2줄 분리. 2줄 초과분은 말줄임표 처리."""
    words = text.split()
    if not words:
        return [""]

    all_lines = []
    line = ""
    for word in words:
        if not line:
            line = word
        elif len(line) + 1 + len(word) <= max_chars:
            line += " " + word
        else:
            all_lines.append(line)
            line = word
    if line:
        all_lines.append(line)

    overflow = len(all_lines) > 2
    result = all_lines[:2]

    # 단일 단어가 max_chars 초과하는 경우 강제 자르기
    trimmed = []
    for l in result:
        if len(l) > max_chars:
            l = l[:max_chars - 1] + "…"
        trimmed.append(l)
    result = trimmed

    if overflow and result:
        last = result[-1]
        if len(last) < max_chars:
            result[-1] = last + "…"
        else:
            result[-1] = last[:max_chars - 1] + "…"

    return result if result else [""]


def run_cmd(cmd: list, label: str = "") -> subprocess.CompletedProcess:
    log.info("RUN %s", label)
    result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        log.error("FAIL %s | %s", label, result.stderr[-400:])
    return result


# ── 자막 필터 생성 (Feature 1: drawtext 2개 분리) ────────────────────────────

def _subtitle_filters(segments: list, clip_start: float, clip_end: float,
                       fopt: str, sub_size: int, sub_color: str,
                       sub_box: bool, sub_position: str,
                       sub_opacity: float = 0.55,
                       box_color: str = "black",
                       border_width: int = 2,
                       sub_fade: bool = False) -> list:
    duration = clip_end - clip_start
    line_h = int(sub_size * 1.35)

    if sub_position == "bottom":
        y1 = f"h*3/4-{line_h}"
        y2 = f"h*3/4"
    elif sub_position == "center":
        y1 = f"(h-{line_h * 2})/2"
        y2 = f"(h-{line_h * 2})/2+{line_h}"
    else:  # top
        y1 = f"h/4-{line_h}"
        y2 = f"h/4"

    box_part = ""
    if sub_box:
        box_part = f":box=1:boxcolor={box_color}@{sub_opacity:.2f}:boxborderw=10"

    filters = []
    for seg in segments:
        if seg["end"] <= clip_start or seg["start"] >= clip_end:
            continue
        rel_s = max(0.0, seg["start"] - clip_start)
        rel_e = min(duration, seg["end"] - clip_start)
        text = seg.get("text", "").strip()
        if not text:
            continue

        lines = _split_lines(text, max_chars=16)

        fade_part = ""
        if sub_fade:
            fd = min(0.3, (rel_e - rel_s) * 0.3)
            if fd > 0:
                fade_part = f":alpha='if(lt(t-{rel_s:.2f},{fd:.2f}),(t-{rel_s:.2f})/{fd:.2f},1)'"

        for li, line_text in enumerate(lines):
            esc_text = _esc(line_text)
            y_expr = y1 if li == 0 else y2
            f = (
                f"drawtext=text='{esc_text}'{fopt}"
                f":x=(w-text_w)/2:y={y_expr}"
                f":fontsize={sub_size}:fontcolor={sub_color}"
                f":borderw={border_width}:bordercolor=black@0.9"
                f"{box_part}"
                f"{fade_part}"
                f":enable='between(t,{rel_s:.2f},{rel_e:.2f})'"
            )
            filters.append(f)

    return filters


# ── 파이프라인 단계 ───────────────────────────────────────────────────────────

def step_download(url: str, job_dir: Path) -> dict:
    result = run_cmd([
        sys.executable, "-m", "yt_dlp",
        "-f", "best[height<=720][ext=mp4]/best[height<=720]/best",
        "--output", str(job_dir / "video.%(ext)s"),
        "--write-info-json", "--no-playlist",
        "--merge-output-format", "mp4",
        url,
    ], "yt-dlp")

    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp 오류:\n{result.stderr[-600:]}")

    video_files = [f for f in job_dir.glob("video.*")
                   if f.suffix not in (".json", ".part", ".ytdl")]
    if not video_files:
        raise RuntimeError("다운로드된 영상 파일을 찾을 수 없습니다.")

    video_path = video_files[0]
    info: dict = {}
    info_files = list(job_dir.glob("*.info.json"))
    if info_files:
        with open(info_files[0], encoding="utf-8") as f:
            info = json.load(f)

    probe = run_cmd([
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", str(video_path),
    ], "ffprobe")
    probe_data = json.loads(probe.stdout or "{}")
    duration = float(probe_data.get("format", {}).get("duration", 0))

    return {
        "video_path": video_path,
        "title": info.get("title", "Unknown"),
        "channel": info.get("uploader", "Unknown"),
        "thumbnail": info.get("thumbnail", ""),
        "duration": duration,
    }


def step_extract_audio(video_path: Path, job_dir: Path) -> Path:
    audio_path = job_dir / "audio.wav"
    result = run_cmd([
        "ffmpeg", "-i", str(video_path),
        "-vn", "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le",
        str(audio_path), "-y",
    ], "ffmpeg-audio")
    if result.returncode != 0:
        raise RuntimeError(f"오디오 추출 실패:\n{result.stderr[-400:]}")
    return audio_path


def step_transcribe(audio_path: Path, model_size: str = "base") -> dict:
    import whisper
    model = whisper.load_model(model_size)
    result = model.transcribe(str(audio_path), task="transcribe")
    segments = [
        {"start": round(s["start"], 2), "end": round(s["end"], 2), "text": s["text"].strip()}
        for s in result["segments"]
    ]
    return {"text": result["text"], "segments": segments}


def step_analyze(transcript: str, segments: list, duration: float, channel: str) -> list:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다.")

    def _safe(t: str) -> str:
        return t.encode("utf-8", errors="replace").decode("utf-8")

    segments_text = "\n".join(
        f"[{s['start']:.1f}s-{s['end']:.1f}s] {_safe(s['text'])}"
        for s in segments
    )

    prompt = f"""당신은 SNS 바이럴 콘텐츠 전문가입니다.
아래 유튜브 자막을 분석해서 쇼츠/릴스 클립으로 만들기 좋은 구간 최대 6개를 선별하세요.

영상 길이: {duration:.0f}초 | 채널: {_safe(channel)}

자막:
{segments_text}

조건:
- 각 구간 15~60초
- 서로 겹치지 않음
- 후킹력 높은 순서 (반전/팁/감동/논란/재미)

JSON만 응답 (다른 텍스트 없이):
{{
  "clips": [
    {{
      "start": 시작초(숫자),
      "end": 종료초(숫자),
      "title": "제목(20자이내)",
      "reason": "선택이유(40자이내)",
      "hashtags": ["태그1","태그2","태그3","태그4","태그5"],
      "hook_type": "tip|reaction|story|fact|humor",
      "viral_score": 바이럴점수(1~10 정수)
    }}
  ]
}}"""

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    text = message.content[0].text
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise RuntimeError(f"Claude 응답 파싱 실패: {text[:200]}")

    data = json.loads(match.group())
    clips = data.get("clips", [])
    for i, c in enumerate(clips):
        c["clip_id"] = str(uuid.uuid4())[:8]
        c["index"] = i + 1
        c["channel"] = channel
        c.setdefault("viral_score", 7)
    return clips


def step_generate_clip(video_path: str, clip: dict, clips_dir: str,
                        layout: str, title_color: str, title_font_size: int,
                        title_align: str,
                        segments: list, sub_font_size: int, sub_color: str,
                        sub_box: bool, sub_position: str,
                        sub_opacity: float = 0.55,
                        box_color: str = "black",
                        border_width: int = 2,
                        sub_fade: bool = False,
                        sub_on: bool = True,
                        start_override: Optional[float] = None,
                        end_override: Optional[float] = None) -> Optional[str]:
    try:
        start    = start_override if start_override is not None else clip["start"]
        end      = end_override   if end_override   is not None else clip["end"]
        duration = end - start

        safe_title = re.sub(r'[\\/:*?"<>|]', '', clip.get("title", "clip"))[:20]
        out_path = os.path.join(clips_dir, f"{clip['index']:02d}_{safe_title}.mp4")

        font_path = _find_font()
        fopt = _font_opt(font_path)

        title_e   = _esc(clip.get("title", ""))
        channel_e = _esc(f"@{clip['channel']}" if clip.get("channel") else "")

        if layout == "crop":
            layout_vf = "crop=in_h*9/16:in_h,scale=1080:1920"
        else:
            layout_vf = (
                "scale=1080:-2:force_original_aspect_ratio=decrease,"
                "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black"
            )

        filters = [layout_vf]

        if title_e:
            x_expr = {"left": "20", "right": "w-text_w-20"}.get(title_align, "(w-text_w)/2")
            filters.append(
                f"drawtext=text='{title_e}'{fopt}"
                f":x={x_expr}:y=60"
                f":fontsize={title_font_size}:fontcolor={title_color}"
                f":borderw=3:bordercolor=black"
                f":shadowx=2:shadowy=2:shadowcolor=black@0.7"
            )

        if channel_e:
            filters.append(
                f"drawtext=text='{channel_e}'{fopt}"
                f":x=(w-text_w)/2:y=h-80"
                f":fontsize=36:fontcolor=white@0.9"
                f":borderw=2:bordercolor=black"
            )

        if sub_on:
            filters.extend(_subtitle_filters(
                segments, start, end, fopt,
                sub_font_size, sub_color, sub_box, sub_position,
                sub_opacity, box_color, border_width, sub_fade,
            ))

        cmd = [
            "ffmpeg",
            "-ss", str(start),
            "-i", video_path,
            "-t", str(duration),
            "-vf", ",".join(filters),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            "-y", out_path,
        ]
        result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
        log.info("ffmpeg exit=%d | %s", result.returncode, result.stderr[-200:])
        return out_path if os.path.exists(out_path) else None
    except Exception:
        log.exception("step_generate_clip failed")
        return None


# ── Feature 6: ZIP + metadata TXT ────────────────────────────────────────────

def create_zip_bytes(results: list) -> bytes:
    buf = io.BytesIO()
    meta_lines = ["YouTube Shorts 클립 메타데이터\n" + "=" * 40]
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for clip, path in results:
            safe_title = re.sub(r'[\\/:*?"<>|]', '', clip.get("title", "clip"))[:20]
            fname = f"{clip['index']:02d}_{safe_title}.mp4"
            zf.write(str(path), fname)
            tags = " ".join(f"#{t.lstrip('#')}" for t in clip.get("hashtags", []))
            meta_lines.append(
                f"\n[클립 {clip['index']:02d}] {clip['title']}\n"
                f"구간: {fmt_time(clip['start'])} ~ {fmt_time(clip['end'])} "
                f"({clip['end'] - clip['start']:.0f}초)\n"
                f"후킹 유형: {clip.get('hook_type', '')}\n"
                f"선택 이유: {clip.get('reason', '')}\n"
                f"바이럴 점수: {clip.get('viral_score', '?')}/10\n"
                f"해시태그: {tags}\n"
                f"파일명: {fname}"
            )
        zf.writestr("metadata.txt", "\n".join(meta_lines))
    return buf.getvalue()


# ── 파이프라인 실행 ───────────────────────────────────────────────────────────

def run_pipeline(url: str, whisper_model: str):
    job_dir = TEMP_DIR / str(uuid.uuid4())
    job_dir.mkdir(parents=True, exist_ok=True)

    steps = ["📥 다운로드", "🔊 오디오 추출", "📝 음성 전사", "🤖 AI 분석"]
    cols = st.columns(len(steps))
    flags = ["wait"] * len(steps)

    def render():
        for i, (col, label) in enumerate(zip(cols, steps)):
            s = flags[i]
            icon = "✅" if s == "done" else ("⏳" if s == "active" else "○")
            cls = "step-done" if s == "done" else ("step-active" if s == "active" else "step-wait")
            col.markdown(f'<div class="{cls}">{icon} {label}</div>', unsafe_allow_html=True)

    flags[0] = "active"; render()
    with st.status("📥 영상 다운로드 중...", expanded=True) as s:
        try:
            meta = step_download(url, job_dir)
            flags[0] = "done"; render()
            s.update(label=f"✅ {meta['title']}", state="complete")
            st.info(f"채널: {meta['channel']} | 길이: {fmt_time(meta['duration'])}")
        except Exception as e:
            s.update(label="❌ 다운로드 실패", state="error")
            st.markdown(f'<div class="error-box">❌ {e}</div>', unsafe_allow_html=True)
            return

    flags[1] = "active"; render()
    with st.status("🔊 오디오 추출 중...", expanded=False) as s:
        try:
            audio_path = step_extract_audio(meta["video_path"], job_dir)
            flags[1] = "done"; render()
            s.update(label="✅ 오디오 추출 완료", state="complete")
        except Exception as e:
            s.update(label="❌ 오디오 추출 실패", state="error")
            st.markdown(f'<div class="error-box">❌ {e}</div>', unsafe_allow_html=True)
            return

    flags[2] = "active"; render()
    with st.status(f"📝 Whisper({whisper_model}) 전사 중...", expanded=True) as s:
        try:
            st.write("영상 길이에 따라 1~5분 소요됩니다.")
            stt = step_transcribe(audio_path, whisper_model)
            flags[2] = "done"; render()
            s.update(label=f"✅ 전사 완료 ({len(stt['segments'])}개 세그먼트)", state="complete")
            with st.expander("전사 내용 보기"):
                st.text(stt["text"][:3000] + ("..." if len(stt["text"]) > 3000 else ""))
        except Exception as e:
            s.update(label="❌ 전사 실패", state="error")
            st.markdown(f'<div class="error-box">❌ {e}</div>', unsafe_allow_html=True)
            return

    flags[3] = "active"; render()
    with st.status("🤖 Claude AI 분석 중...", expanded=False) as s:
        try:
            clips = step_analyze(stt["text"], stt["segments"], meta["duration"], meta["channel"])
            flags[3] = "done"; render()
            s.update(label=f"✅ {len(clips)}개 후킹 포인트 선별", state="complete")
        except Exception as e:
            s.update(label="❌ AI 분석 실패", state="error")
            st.markdown(f'<div class="error-box">❌ {e}</div>', unsafe_allow_html=True)
            return

    st.session_state.update({
        "cached_url":     url,
        "cached_meta":    meta,
        "cached_stt":     stt,
        "cached_clips":   clips,
        "cached_job_dir": str(job_dir),
    })
    st.session_state.pop("gen_results", None)

    # Feature 7: 히스토리 저장
    history = st.session_state.get("history", [])
    history.insert(0, {
        "url":       url,
        "title":     meta["title"],
        "clip_count": len(clips),
        "ts":        datetime.now().strftime("%H:%M"),
        "snapshot":  {
            "cached_url":     url,
            "cached_meta":    {k: str(v) if isinstance(v, Path) else v for k, v in meta.items()},
            "cached_stt":     stt,
            "cached_clips":   clips,
            "cached_job_dir": str(job_dir),
        },
    })
    st.session_state["history"] = history[:10]


# ── Feature 5: 타임라인 시각화 ───────────────────────────────────────────────

def render_timeline(clips: list, duration: float):
    if duration <= 0:
        return
    colors = ["#6d28d9", "#2563eb", "#059669", "#d97706", "#dc2626", "#7c3aed"]
    segs_html = ""
    for i, clip in enumerate(clips):
        left  = clip["start"] / duration * 100
        width = max(0.5, (clip["end"] - clip["start"]) / duration * 100)
        label = (clip["title"][:6] + "…") if len(clip["title"]) > 6 else clip["title"]
        segs_html += (
            f'<div style="position:absolute;left:{left:.1f}%;width:{width:.1f}%;'
            f'height:100%;background:{colors[i % len(colors)]};border-radius:3px;'
            f'display:flex;align-items:center;justify-content:center;overflow:hidden;" '
            f'title="{clip["title"]}">'
            f'<span style="font-size:9px;color:#fff;padding:0 3px;white-space:nowrap;'
            f'overflow:hidden;text-overflow:ellipsis;">{label}</span></div>'
        )
    st.markdown(
        f'<div class="timeline-wrap">'
        f'<div style="font-size:12px;color:#94a3b8;margin-bottom:6px;">'
        f'📊 타임라인 · 전체 {fmt_time(duration)}</div>'
        f'<div style="position:relative;height:34px;background:#2d2d4e;'
        f'border-radius:6px;overflow:hidden;">{segs_html}</div>'
        f'<div style="display:flex;justify-content:space-between;'
        f'font-size:10px;color:#4a5568;margin-top:4px;">'
        f'<span>0:00</span><span>{fmt_time(duration / 2)}</span>'
        f'<span>{fmt_time(duration)}</span></div></div>',
        unsafe_allow_html=True,
    )


# ── Feature 2: 실시간 자막 미리보기 ─────────────────────────────────────────

def render_subtitle_preview(
    preview_title: str, preview_sub: str,
    title_font_size: int, title_color: str, title_align: str,
    sub_font_size: int, sub_color: str,
    sub_box: bool, sub_position: str,
    sub_opacity: float, box_color: str,
):
    color_map = {
        "white": "#ffffff", "yellow": "#ffff00",
        "#74b9ff": "#74b9ff", "#00ffcc": "#00ffcc",
        "#ff6b6b": "#ff6b6b", "#55efc4": "#55efc4",
    }
    sub_css   = color_map.get(sub_color,   sub_color)
    title_css = color_map.get(title_color, title_color)

    box_rgba = {
        "black": f"rgba(0,0,0,{sub_opacity:.2f})",
        "navy":  f"rgba(0,0,128,{sub_opacity:.2f})",
        "gray":  f"rgba(64,64,64,{sub_opacity:.2f})",
    }.get(box_color, f"rgba(0,0,0,{sub_opacity:.2f})")

    title_align_css = {"left": "left", "right": "right"}.get(title_align, "center")

    if sub_position == "center":
        sub_pos = "top:50%;left:50%;transform:translate(-50%,-50%);"
    elif sub_position == "top":
        sub_pos = "top:25%;left:50%;transform:translateX(-50%);"
    else:
        sub_pos = "bottom:15%;left:50%;transform:translateX(-50%);"

    pt = max(8, title_font_size // 5)
    ps = max(7, sub_font_size // 5)

    sub_bg = f"background:{box_rgba};padding:2px 5px;border-radius:2px;" if sub_box else ""
    lines = _split_lines(preview_sub or "자막 텍스트", max_chars=16)
    sub_html = "<br>".join(f'<span style="{sub_bg}">{l}</span>' for l in lines)

    st.markdown(
        f'<div style="width:90px;height:160px;background:#111;border-radius:6px;'
        f'position:relative;overflow:hidden;margin:0 auto;border:1px solid #333;">'
        f'<div style="position:absolute;top:8px;left:0;right:0;'
        f'font-size:{pt}px;color:{title_css};text-align:{title_align_css};'
        f'padding:0 4px;text-shadow:1px 1px 2px #000;font-weight:bold;">'
        f'{(preview_title or "제목 텍스트")[:20]}</div>'
        f'<div style="position:absolute;{sub_pos}width:88%;text-align:center;'
        f'font-size:{ps}px;color:{sub_css};text-shadow:1px 1px 2px #000;line-height:1.4;">'
        f'{sub_html}</div>'
        f'<div style="position:absolute;bottom:5px;left:0;right:0;'
        f'font-size:6px;color:rgba(255,255,255,0.5);text-align:center;">@채널명</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


# ── 메인 UI ───────────────────────────────────────────────────────────────────

def main():
    st.markdown("## 🎬 YouTube → Shorts / Reels 변환기")

    with st.sidebar:
        st.markdown("### 🔑 API 키")
        api_key_input = st.text_input(
            "Anthropic API Key",
            value=os.environ.get("ANTHROPIC_API_KEY", ""),
            type="password",
            placeholder="sk-ant-...",
        )
        if api_key_input:
            os.environ["ANTHROPIC_API_KEY"] = api_key_input.strip()
        if not api_key_input:
            st.warning("API 키를 입력하세요.")

        st.divider()
        st.markdown("### ⚙️ 영상 설정")
        whisper_model = st.selectbox("Whisper 모델", ["base", "small", "medium"])
        layout = st.selectbox(
            "레이아웃", ["letterbox", "crop"],
            format_func=lambda x: "레터박스" if x == "letterbox" else "세로 크롭",
        )

        # ── Feature 3: 제목 스타일 ────────────────────────────
        st.divider()
        st.markdown("### 🔤 제목 스타일")
        title_color = st.selectbox(
            "제목 색상", ["white", "yellow", "#00ffcc", "#ff6b6b"],
            format_func=lambda x: {"white":"흰색","yellow":"노랑","#00ffcc":"민트","#ff6b6b":"빨강"}.get(x, x),
        )
        title_font_size = st.slider("제목 폰트 크기", 40, 100, 60)
        title_align = st.selectbox(
            "제목 정렬", ["center", "left", "right"],
            format_func=lambda x: {"center":"가운데","left":"왼쪽","right":"오른쪽"}.get(x, x),
        )

        # ── Feature 3: 자막 스타일 ────────────────────────────
        st.divider()
        st.markdown("### 💬 자막 스타일")
        sub_font_size = st.slider("자막 폰트 크기", 30, 80, 50)
        sub_color = st.selectbox(
            "자막 색상", ["white", "yellow", "#74b9ff", "#55efc4"],
            format_func=lambda x: {"white":"흰색","yellow":"노랑","#74b9ff":"하늘색","#55efc4":"초록색"}.get(x, x),
        )
        sub_box = st.toggle("자막 배경 박스", value=True)
        sub_opacity = st.slider("박스 투명도 (%)", 0, 100, 55, disabled=not sub_box) / 100.0
        box_color = st.selectbox(
            "박스 색상", ["black", "navy", "gray"],
            format_func=lambda x: {"black":"검정","navy":"남색","gray":"회색"}.get(x, x),
            disabled=not sub_box,
        )
        border_width = st.slider("자막 외곽선 두께", 0, 5, 2)
        sub_fade     = st.toggle("페이드인 효과", value=False)
        sub_position = st.selectbox(
            "자막 위치", ["bottom", "center", "top"],
            format_func=lambda x: {"bottom":"하단","center":"중앙","top":"상단 1/3"}.get(x, x),
        )

        # ── Feature 2: 실시간 미리보기 ───────────────────────
        st.divider()
        st.markdown("### 👁️ 자막 미리보기")
        prev_title = st.text_input("미리보기 제목", value="제목 텍스트", key="prev_title")
        prev_sub   = st.text_input("미리보기 자막", value="이것은 자막 텍스트입니다", key="prev_sub")
        render_subtitle_preview(
            prev_title, prev_sub,
            title_font_size, title_color, title_align,
            sub_font_size, sub_color,
            sub_box, sub_position, sub_opacity, box_color,
        )

        # ── Feature 7: 세션 히스토리 ─────────────────────────
        history = st.session_state.get("history", [])
        if history:
            st.divider()
            st.markdown("### 📜 세션 히스토리")
            for idx, h in enumerate(history):
                short = h["title"][:16] + ("…" if len(h["title"]) > 16 else "")
                if st.button(
                    f"🎬 {short}\n{h['ts']} · {h['clip_count']}클립",
                    key=f"hist_{idx}",
                    use_container_width=True,
                ):
                    snap = h["snapshot"]
                    m = dict(snap["cached_meta"])
                    m["video_path"] = Path(str(m["video_path"]))
                    st.session_state.update({
                        "cached_url":     snap["cached_url"],
                        "cached_meta":    m,
                        "cached_stt":     snap["cached_stt"],
                        "cached_clips":   snap["cached_clips"],
                        "cached_job_dir": snap["cached_job_dir"],
                    })
                    st.session_state.pop("gen_results", None)
                    st.rerun()

        st.divider()
        st.caption("pip install -r requirements.txt")

    # ── URL 입력 ──────────────────────────────────────────────
    url = st.text_input("🔗 YouTube URL", placeholder="https://www.youtube.com/watch?v=...")
    col_btn, col_cache = st.columns([2, 5])
    analyze_btn = col_btn.button("🔍 분석 시작", type="primary", use_container_width=True)

    cached_url = st.session_state.get("cached_url", "")
    if url.strip() and url.strip() == cached_url and "cached_clips" in st.session_state:
        col_cache.success("✅ 캐시 있음 — 재다운로드 없이 편집 가능")

    if analyze_btn:
        if not url.strip():
            st.warning("URL을 입력하세요.")
        elif url.strip() == cached_url and "cached_clips" in st.session_state:
            st.toast("캐시된 분석 결과를 사용합니다.")
        else:
            run_pipeline(url.strip(), whisper_model)

    if "cached_clips" not in st.session_state:
        return

    meta      = st.session_state["cached_meta"]
    stt       = st.session_state["cached_stt"]
    clips     = st.session_state["cached_clips"]
    job_dir   = Path(st.session_state["cached_job_dir"])
    clips_dir = str(job_dir / "clips")
    os.makedirs(clips_dir, exist_ok=True)

    # ── Feature 5: 타임라인 바 ────────────────────────────────
    st.divider()
    render_timeline(clips, meta["duration"])

    # ── 클립 편집기 ───────────────────────────────────────────
    st.markdown(f"### 📋 클립 편집  ·  {meta['title']}")

    hook_emoji = {"tip": "💡", "reaction": "😮", "story": "📖", "fact": "📊", "humor": "😂"}
    selected_ids = []

    for clip in clips:
        emoji = hook_emoji.get(clip.get("hook_type", ""), "🎬")
        score = clip.get("viral_score", 7)
        with st.expander(
            f"{emoji} [{clip['index']}] {clip['title']}  "
            f"·  {fmt_time(clip['start'])}~{fmt_time(clip['end'])}  "
            f"({clip['end'] - clip['start']:.0f}초)  ⭐{score}/10",
            expanded=True,
        ):
            # Feature 5: 바이럴 점수 + 이유
            sc_col, rs_col = st.columns([1, 3])
            with sc_col:
                fire = "🔥" * min(score, 5) + "·" * max(0, 5 - min(score, 5))
                st.markdown(
                    f'<span class="score-badge">바이럴 {score}/10</span><br>'
                    f'<small style="color:#94a3b8">{fire}</small>',
                    unsafe_allow_html=True,
                )
            with rs_col:
                st.markdown(f"**선택 이유:** {clip.get('reason', '')}")
                tags_html = " ".join(
                    f'<span class="tag">#{t.lstrip("#")}</span>'
                    for t in clip.get("hashtags", [])
                )
                st.markdown(tags_html, unsafe_allow_html=True)

            # Feature 4: 편집 패널
            with st.expander("✏️ 편집", expanded=False):
                ec1, ec2 = st.columns(2)
                with ec1:
                    new_title = st.text_input(
                        "제목", value=clip.get("title", ""),
                        key=f"et_{clip['clip_id']}",
                    )
                    new_tags = st.text_input(
                        "해시태그 (쉼표 구분)",
                        value=", ".join(f"#{t.lstrip('#')}" for t in clip.get("hashtags", [])),
                        key=f"eht_{clip['clip_id']}",
                    )
                    if st.button("적용", key=f"eapply_{clip['clip_id']}"):
                        clip["title"] = new_title
                        clip["hashtags"] = [
                            t.strip().lstrip("#") for t in new_tags.split(",") if t.strip()
                        ]
                        st.rerun()

                with ec2:
                    es = st.slider(
                        "시작 (초)", 0.0, float(meta["duration"]),
                        float(clip["start"]), 1.0, key=f"es_{clip['clip_id']}",
                    )
                    ee = st.slider(
                        "끝 (초)", 0.0, float(meta["duration"]),
                        float(clip["end"]), 1.0, key=f"ee_{clip['clip_id']}",
                    )
                    sub_on_edit = st.toggle("자막 표시", value=True, key=f"soe_{clip['clip_id']}")

                    if st.button("🔄 이 클립만 재생성", key=f"rge_{clip['clip_id']}"):
                        with st.spinner(f"클립 {clip['index']} 재생성 중..."):
                            np = step_generate_clip(
                                str(meta["video_path"]), clip, clips_dir,
                                layout, title_color, title_font_size, title_align,
                                stt["segments"], sub_font_size, sub_color, sub_box,
                                sub_position, sub_opacity, box_color, border_width,
                                sub_fade, sub_on_edit,
                                start_override=es, end_override=ee,
                            )
                        if np:
                            gr = st.session_state.get("gen_results", [])
                            updated = any(
                                d for d in gr if d["clip"]["clip_id"] == clip["clip_id"]
                                and not d.update({"path": np})
                            )
                            if not updated:
                                gr.append({"clip": clip, "path": np})
                            st.session_state["gen_results"] = gr
                            st.success("재생성 완료!")
                            st.rerun()
                        else:
                            st.error("재생성 실패")

            # 구간 조정 + 선택
            mc1, mc2, mc3 = st.columns([2, 2, 1])
            with mc1:
                adj_s = st.number_input(
                    "시작(초)", 0.0, float(meta["duration"]),
                    float(clip["start"]), 1.0, key=f"s_{clip['clip_id']}",
                )
            with mc2:
                adj_e = st.number_input(
                    "끝(초)", 0.0, float(meta["duration"]),
                    float(clip["end"]), 1.0, key=f"e_{clip['clip_id']}",
                )
            with mc3:
                st.markdown("<br>", unsafe_allow_html=True)
                sel = st.checkbox("생성 대상", value=True, key=f"sel_{clip['clip_id']}")

            if adj_e - adj_s < 3:
                st.warning("구간이 너무 짧습니다 (최소 3초)")
            if sel:
                selected_ids.append(clip["clip_id"])

    if not selected_ids:
        st.warning("생성할 클립을 하나 이상 선택하세요.")

    gen_btn = st.button(
        f"🎬 선택한 클립 생성 ({len(selected_ids)}개)",
        type="primary",
        disabled=not selected_ids,
        use_container_width=True,
    )

    if gen_btn and selected_ids:
        st.markdown("### 🎞️ 클립 생성 중")
        progress = st.progress(0)
        results = []
        selected_clips = [c for c in clips if c["clip_id"] in selected_ids]

        for i, clip in enumerate(selected_clips):
            adj_s = st.session_state.get(f"s_{clip['clip_id']}", clip["start"])
            adj_e = st.session_state.get(f"e_{clip['clip_id']}", clip["end"])
            sub_on = st.session_state.get(f"soe_{clip['clip_id']}", True)

            with st.status(f"클립 {clip['index']}: {clip['title']}", expanded=False) as s:
                out = step_generate_clip(
                    str(meta["video_path"]), clip, clips_dir,
                    layout, title_color, title_font_size, title_align,
                    stt["segments"], sub_font_size, sub_color, sub_box,
                    sub_position, sub_opacity, box_color, border_width,
                    sub_fade, sub_on,
                    start_override=adj_s, end_override=adj_e,
                )
                if out:
                    results.append((clip, Path(out)))
                    s.update(label=f"✅ 클립 {clip['index']} ({os.path.getsize(out)//1024}KB)", state="complete")
                else:
                    s.update(label=f"❌ 클립 {clip['index']} 실패", state="error")
            progress.progress((i + 1) / len(selected_clips))

        st.session_state["gen_results"] = [{"clip": c, "path": str(p)} for c, p in results]

    # ── 결과 표시 ─────────────────────────────────────────────
    if not st.session_state.get("gen_results"):
        return

    results_pairs = [
        (d["clip"], Path(d["path"]))
        for d in st.session_state["gen_results"]
        if Path(d["path"]).exists()
    ]
    if not results_pairs:
        return

    st.divider()
    st.markdown(f"### ⬇️ 생성된 클립 ({len(results_pairs)}개)")

    zip_bytes = create_zip_bytes(results_pairs)
    st.download_button(
        label=f"📦 전체 ZIP 다운로드 ({len(results_pairs)}개 + metadata.txt)",
        data=zip_bytes,
        file_name="shorts_clips.zip",
        mime="application/zip",
        use_container_width=True,
    )

    st.divider()

    for clip, path in results_pairs:
        with st.expander(
            f"[{clip['index']}] {clip['title']}  ·  "
            f"{fmt_time(clip['start'])}~{fmt_time(clip['end'])}",
            expanded=True,
        ):
            vc, ic = st.columns([1, 1])
            with vc:
                st.video(str(path))
            with ic:
                st.markdown(f"**{clip['title']}**")
                st.caption(
                    f"{fmt_time(clip['start'])} ~ {fmt_time(clip['end'])}  "
                    f"({clip['end'] - clip['start']:.0f}초)"
                )
                vs = clip.get("viral_score", 7)
                st.markdown(
                    f'<span class="score-badge">바이럴 {vs}/10</span>',
                    unsafe_allow_html=True,
                )
                tags_html = " ".join(
                    f'<span class="tag">#{t.lstrip("#")}</span>'
                    for t in clip.get("hashtags", [])
                )
                st.markdown(tags_html, unsafe_allow_html=True)

                safe_title = re.sub(r'[\\/:*?"<>|]', '', clip.get("title", "clip"))[:20]
                with open(path, "rb") as f:
                    st.download_button(
                        label="📥 다운로드",
                        data=f,
                        file_name=f"{clip['index']:02d}_{safe_title}.mp4",
                        mime="video/mp4",
                        key=f"dl_{clip['clip_id']}",
                        use_container_width=True,
                    )

                st.markdown("**구간 재조정 후 재생성**")
                rc1, rc2 = st.columns(2)
                re_s = rc1.number_input(
                    "시작(초)", 0.0, float(meta["duration"]),
                    float(clip["start"]), 1.0, key=f"re_s_{clip['clip_id']}",
                )
                re_e = rc2.number_input(
                    "끝(초)", 0.0, float(meta["duration"]),
                    float(clip["end"]), 1.0, key=f"re_e_{clip['clip_id']}",
                )
                sub_on_r = st.toggle("자막 표시", value=True, key=f"sor_{clip['clip_id']}")
                if st.button("🔄 재생성", key=f"regen_{clip['clip_id']}"):
                    with st.spinner("재생성 중..."):
                        np2 = step_generate_clip(
                            str(meta["video_path"]), clip, clips_dir,
                            layout, title_color, title_font_size, title_align,
                            stt["segments"], sub_font_size, sub_color, sub_box,
                            sub_position, sub_opacity, box_color, border_width,
                            sub_fade, sub_on_r,
                            start_override=re_s, end_override=re_e,
                        )
                    if np2:
                        for d in st.session_state["gen_results"]:
                            if d["clip"]["clip_id"] == clip["clip_id"]:
                                d["path"] = np2
                                d["clip"]["start"] = re_s
                                d["clip"]["end"]   = re_e
                        st.success("재생성 완료!")
                        st.rerun()
                    else:
                        st.error("재생성 실패")

    st.success(f"🎉 {len(results_pairs)}개 클립 완료!")


if __name__ == "__main__":
    main()
