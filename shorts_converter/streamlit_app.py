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

import httpx
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
        .replace("\n", "\\n")
    )


def _wrap_and_esc(text: str, max_chars: int = 15) -> str:
    """단어 단위로 줄바꿈 후 이스케이프 (ffmpeg drawtext용 \\n)."""
    words = text.split()
    lines, line = [], ""
    for word in words:
        if not line:
            line = word
        elif len(line) + 1 + len(word) <= max_chars:
            line += " " + word
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return "\\n".join(_esc(l) for l in lines)


def run_cmd(cmd: list, label: str = "") -> subprocess.CompletedProcess:
    log.info("RUN %s", label)
    result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        log.error("FAIL %s | %s", label, result.stderr[-400:])
    return result


# ── 자막 필터 생성 ────────────────────────────────────────────────────────────

def _subtitle_filters(segments: list, clip_start: float, clip_end: float,
                       fopt: str, sub_size: int, sub_color: str,
                       sub_box: bool, sub_position: str) -> list:
    """Whisper 세그먼트 → ffmpeg drawtext 필터 리스트."""
    duration = clip_end - clip_start
    y_expr = "h*2/3" if sub_position == "bottom" else "(h-text_h)/2+h/6"
    box_part = ":box=1:boxcolor=black@0.55:boxborderw=10" if sub_box else ""
    filters = []

    for seg in segments:
        if seg["end"] <= clip_start or seg["start"] >= clip_end:
            continue
        rel_s = max(0.0, seg["start"] - clip_start)
        rel_e = min(duration, seg["end"] - clip_start)
        text = seg.get("text", "").strip()
        if not text:
            continue

        wrapped = _wrap_and_esc(text, max_chars=15)
        # enable 안의 콤마는 단따옴표로 보호되므로 그냥 사용
        f = (
            f"drawtext=text='{wrapped}'{fopt}"
            f":x=(w-text_w)/2:y={y_expr}"
            f":fontsize={sub_size}:fontcolor={sub_color}"
            f":borderw=2:bordercolor=black@0.9"
            f"{box_part}"
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
      "hook_type": "tip|reaction|story|fact|humor"
    }}
  ]
}}"""

    safe_key = api_key.encode("ascii", errors="replace").decode("ascii")
    http_client = httpx.Client(headers={"x-api-key": safe_key}, timeout=120.0)
    client = anthropic.Anthropic(api_key=safe_key, http_client=http_client)
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
    return clips


def step_generate_clip(video_path: str, clip: dict, clips_dir: str,
                        layout: str, title_color: str, title_font_size: int,
                        segments: list, sub_font_size: int, sub_color: str,
                        sub_box: bool, sub_position: str,
                        start_override: Optional[float] = None,
                        end_override: Optional[float] = None) -> Optional[str]:
    """9:16 세로 클립 생성 (제목·채널명·나레이션 자막 오버레이)."""
    try:
        start    = start_override if start_override is not None else clip["start"]
        end      = end_override   if end_override   is not None else clip["end"]
        duration = end - start
        out_path = os.path.join(clips_dir, f"clip_{clip['index']:02d}_{clip['clip_id']}.mp4")

        font_path = _find_font()
        fopt = _font_opt(font_path)

        title_e   = _esc(clip.get("title", ""))
        channel_e = _esc(f"@{clip['channel']}" if clip.get("channel") else "")

        # ── 레이아웃 ───────────────────────────────────────────
        if layout == "crop":
            layout_vf = "crop=in_h*9/16:in_h,scale=1080:1920"
        else:
            layout_vf = (
                "scale=1080:-2:force_original_aspect_ratio=decrease,"
                "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black"
            )

        filters = [layout_vf]

        # ── 상단 제목 ──────────────────────────────────────────
        if title_e:
            filters.append(
                f"drawtext=text='{title_e}'{fopt}"
                f":x=(w-text_w)/2:y=60"
                f":fontsize={title_font_size}:fontcolor={title_color}"
                f":borderw=3:bordercolor=black"
                f":shadowx=2:shadowy=2:shadowcolor=black@0.7"
            )

        # ── 하단 채널명 ────────────────────────────────────────
        if channel_e:
            filters.append(
                f"drawtext=text='{channel_e}'{fopt}"
                f":x=(w-text_w)/2:y=h-80"
                f":fontsize=36:fontcolor=white@0.9"
                f":borderw=2:bordercolor=black"
            )

        # ── 나레이션 자막 (Whisper 세그먼트) ─────────────────
        sub_filters = _subtitle_filters(
            segments, start, end, fopt,
            sub_font_size, sub_color, sub_box, sub_position,
        )
        filters.extend(sub_filters)

        vf = ",".join(filters)

        cmd = [
            "ffmpeg",
            "-ss", str(start),
            "-i", video_path,
            "-t", str(duration),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            "-y", out_path,
        ]
        result = subprocess.run(
            cmd, capture_output=True, encoding="utf-8", errors="replace"
        )
        log.info("ffmpeg exit=%d | %s", result.returncode, result.stderr[-200:])

        return out_path if os.path.exists(out_path) else None
    except Exception:
        log.exception("step_generate_clip failed")
        return None


# ── ZIP ───────────────────────────────────────────────────────────────────────

def create_zip_bytes(results: list) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for clip, path in results:
            fname = f"clip_{clip['index']:02d}_{clip['title'][:12]}.mp4"
            zf.write(str(path), fname)
    return buf.getvalue()


# ── 파이프라인 실행 + 세션 저장 ──────────────────────────────────────────────

def run_pipeline(url: str, whisper_model: str):
    """다운로드 → 오디오 → STT → AI 분석 후 st.session_state에 저장."""
    job_dir = TEMP_DIR / str(uuid.uuid4())
    job_dir.mkdir(parents=True, exist_ok=True)

    steps = ["📥 다운로드", "🔊 오디오 추출", "📝 음성 전사", "🤖 AI 분석"]
    cols = st.columns(len(steps))
    status_flags = ["wait"] * len(steps)

    def render():
        for i, (col, label) in enumerate(zip(cols, steps)):
            s = status_flags[i]
            icon = "✅" if s == "done" else ("⏳" if s == "active" else "○")
            cls = "step-done" if s == "done" else ("step-active" if s == "active" else "step-wait")
            col.markdown(f'<div class="{cls}">{icon} {label}</div>', unsafe_allow_html=True)

    # ① 다운로드
    status_flags[0] = "active"; render()
    with st.status("📥 영상 다운로드 중...", expanded=True) as s:
        try:
            meta = step_download(url, job_dir)
            status_flags[0] = "done"; render()
            s.update(label=f"✅ {meta['title']}", state="complete")
            st.info(f"채널: {meta['channel']} | 길이: {fmt_time(meta['duration'])}")
        except Exception as e:
            s.update(label="❌ 다운로드 실패", state="error")
            st.markdown(f'<div class="error-box">❌ {e}</div>', unsafe_allow_html=True)
            return

    # ② 오디오 추출
    status_flags[1] = "active"; render()
    with st.status("🔊 오디오 추출 중...", expanded=False) as s:
        try:
            audio_path = step_extract_audio(meta["video_path"], job_dir)
            status_flags[1] = "done"; render()
            s.update(label="✅ 오디오 추출 완료", state="complete")
        except Exception as e:
            s.update(label="❌ 오디오 추출 실패", state="error")
            st.markdown(f'<div class="error-box">❌ {e}</div>', unsafe_allow_html=True)
            return

    # ③ 전사
    status_flags[2] = "active"; render()
    with st.status(f"📝 Whisper({whisper_model}) 전사 중...", expanded=True) as s:
        try:
            st.write("영상 길이에 따라 1~5분 소요됩니다.")
            stt = step_transcribe(audio_path, whisper_model)
            status_flags[2] = "done"; render()
            s.update(label=f"✅ 전사 완료 ({len(stt['segments'])}개 세그먼트)", state="complete")
            with st.expander("전사 내용 보기"):
                st.text(stt["text"][:3000] + ("..." if len(stt["text"]) > 3000 else ""))
        except Exception as e:
            s.update(label="❌ 전사 실패", state="error")
            st.markdown(f'<div class="error-box">❌ {e}</div>', unsafe_allow_html=True)
            return

    # ④ AI 분석
    status_flags[3] = "active"; render()
    with st.status("🤖 Claude AI 분석 중...", expanded=False) as s:
        try:
            clips = step_analyze(stt["text"], stt["segments"], meta["duration"], meta["channel"])
            status_flags[3] = "done"; render()
            s.update(label=f"✅ {len(clips)}개 후킹 포인트 선별", state="complete")
        except Exception as e:
            s.update(label="❌ AI 분석 실패", state="error")
            st.markdown(f'<div class="error-box">❌ {e}</div>', unsafe_allow_html=True)
            return

    # 캐시 저장
    st.session_state.update({
        "cached_url":     url,
        "cached_meta":    meta,
        "cached_stt":     stt,
        "cached_clips":   clips,
        "cached_job_dir": str(job_dir),
    })
    st.session_state.pop("gen_results", None)  # 이전 결과 초기화


# ── 메인 UI ───────────────────────────────────────────────────────────────────

def main():
    st.markdown("## 🎬 YouTube → Shorts / Reels 변환기")

    # ── 사이드바 ──────────────────────────────────────────────
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
        whisper_model  = st.selectbox("Whisper 모델", ["base", "small", "medium"])
        layout         = st.selectbox("레이아웃",
                            ["letterbox", "crop"],
                            format_func=lambda x: "레터박스" if x == "letterbox" else "세로 크롭")
        title_color    = st.selectbox("제목 색상",
                            ["white", "yellow", "#00ffcc", "#ff6b6b"],
                            format_func=lambda x: {"white":"흰색","yellow":"노랑","#00ffcc":"민트","#ff6b6b":"빨강"}.get(x, x))
        title_font_size = st.slider("제목 폰트 크기", 28, 80, 60)

        st.divider()
        st.markdown("### 💬 자막 설정")
        sub_font_size = st.slider("자막 폰트 크기", 30, 80, 44)
        sub_color     = st.selectbox("자막 색상",
                            ["white", "yellow", "#74b9ff"],
                            format_func=lambda x: {"white":"흰색","yellow":"노랑","#74b9ff":"하늘색"}.get(x, x))
        sub_box       = st.toggle("자막 배경 박스", value=True)
        sub_position  = st.selectbox("자막 위치", ["bottom", "center"],
                            format_func=lambda x: "하단" if x == "bottom" else "중앙")

        st.divider()
        st.caption("pip install -r requirements.txt")

    # ── URL 입력 + 분석 버튼 ──────────────────────────────────
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

    # ── 분석 결과 없으면 종료 ─────────────────────────────────
    if "cached_clips" not in st.session_state:
        return

    meta   = st.session_state["cached_meta"]
    stt    = st.session_state["cached_stt"]
    clips  = st.session_state["cached_clips"]
    job_dir = Path(st.session_state["cached_job_dir"])
    clips_dir = str(job_dir / "clips")
    os.makedirs(clips_dir, exist_ok=True)

    # ── 클립 편집기 ───────────────────────────────────────────
    st.divider()
    st.markdown(f"### 📋 클립 편집  ·  {meta['title']}")

    hook_emoji = {"tip":"💡","reaction":"😮","story":"📖","fact":"📊","humor":"😂"}
    selected_ids: list[str] = []

    for clip in clips:
        emoji = hook_emoji.get(clip.get("hook_type", ""), "🎬")
        with st.expander(
            f"{emoji} [{clip['index']}] {clip['title']}  "
            f"·  {fmt_time(clip['start'])}~{fmt_time(clip['end'])}  "
            f"({clip['end']-clip['start']:.0f}초)",
            expanded=True,
        ):
            info_col, ctrl_col = st.columns([3, 2])

            with info_col:
                st.markdown(f"**이유:** {clip.get('reason','')}")
                tags_html = " ".join(
                    f'<span class="tag">#{t.lstrip("#")}</span>'
                    for t in clip.get("hashtags", [])
                )
                st.markdown(tags_html, unsafe_allow_html=True)

            with ctrl_col:
                # ④ 구간 미세 조정
                adj_start = st.number_input(
                    "시작(초)", min_value=0.0, max_value=float(meta["duration"]),
                    value=float(clip["start"]), step=1.0,
                    key=f"s_{clip['clip_id']}",
                )
                adj_end = st.number_input(
                    "끝(초)", min_value=0.0, max_value=float(meta["duration"]),
                    value=float(clip["end"]), step=1.0,
                    key=f"e_{clip['clip_id']}",
                )
                if adj_end - adj_start < 3:
                    st.warning("구간이 너무 짧습니다 (최소 3초)")

                sel = st.checkbox("생성 대상", value=True, key=f"sel_{clip['clip_id']}")
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

    # ── 클립 생성 ─────────────────────────────────────────────
    if gen_btn and selected_ids:
        st.markdown("### 🎞️ 클립 생성 중")
        progress = st.progress(0)
        results = []

        selected_clips = [c for c in clips if c["clip_id"] in selected_ids]

        for i, clip in enumerate(selected_clips):
            adj_start = st.session_state.get(f"s_{clip['clip_id']}", clip["start"])
            adj_end   = st.session_state.get(f"e_{clip['clip_id']}", clip["end"])

            with st.status(f"클립 {clip['index']}: {clip['title']}", expanded=False) as s:
                out_path = step_generate_clip(
                    str(meta["video_path"]), clip, clips_dir,
                    layout, title_color, title_font_size,
                    stt["segments"], sub_font_size, sub_color, sub_box, sub_position,
                    start_override=adj_start, end_override=adj_end,
                )
                if out_path:
                    results.append((clip, Path(out_path)))
                    size_kb = os.path.getsize(out_path) // 1024
                    s.update(label=f"✅ 클립 {clip['index']} ({size_kb}KB)", state="complete")
                else:
                    s.update(label=f"❌ 클립 {clip['index']} 실패", state="error")

            progress.progress((i + 1) / len(selected_clips))

        st.session_state["gen_results"] = [
            {"clip": c, "path": str(p)} for c, p in results
        ]

    # ── 결과 표시 ─────────────────────────────────────────────
    if "gen_results" not in st.session_state or not st.session_state["gen_results"]:
        return

    results_data = st.session_state["gen_results"]
    results_pairs = [(d["clip"], Path(d["path"])) for d in results_data if Path(d["path"]).exists()]

    if not results_pairs:
        return

    st.divider()
    st.markdown(f"### ⬇️ 생성된 클립 ({len(results_pairs)}개)")

    # ⑤ ZIP 일괄 다운로드
    zip_bytes = create_zip_bytes(results_pairs)
    st.download_button(
        label=f"📦 전체 ZIP 다운로드 ({len(results_pairs)}개)",
        data=zip_bytes,
        file_name="shorts_clips.zip",
        mime="application/zip",
        use_container_width=True,
    )

    st.divider()

    # ③ 클립별 미리보기 + 개별 다운로드 + 재생성
    for clip, path in results_pairs:
        with st.expander(
            f"[{clip['index']}] {clip['title']}  ·  "
            f"{fmt_time(clip['start'])}~{fmt_time(clip['end'])}",
            expanded=True,
        ):
            vid_col, info_col = st.columns([1, 1])

            with vid_col:
                st.video(str(path))  # ③ 인라인 미리보기

            with info_col:
                st.markdown(f"**{clip['title']}**")
                st.caption(
                    f"{fmt_time(clip['start'])} ~ {fmt_time(clip['end'])}  "
                    f"({clip['end']-clip['start']:.0f}초)"
                )
                tags_html = " ".join(
                    f'<span class="tag">#{t.lstrip("#")}</span>'
                    for t in clip.get("hashtags", [])
                )
                st.markdown(tags_html, unsafe_allow_html=True)

                with open(path, "rb") as f:
                    st.download_button(
                        label="📥 다운로드",
                        data=f,
                        file_name=f"shorts_{clip['index']:02d}.mp4",
                        mime="video/mp4",
                        key=f"dl_{clip['clip_id']}",
                        use_container_width=True,
                    )

                # ④ 재생성
                st.markdown("**구간 재조정 후 재생성**")
                rc1, rc2 = st.columns(2)
                re_start = rc1.number_input(
                    "시작(초)", min_value=0.0, max_value=float(meta["duration"]),
                    value=float(clip["start"]), step=1.0,
                    key=f"re_s_{clip['clip_id']}",
                )
                re_end = rc2.number_input(
                    "끝(초)", min_value=0.0, max_value=float(meta["duration"]),
                    value=float(clip["end"]), step=1.0,
                    key=f"re_e_{clip['clip_id']}",
                )
                if st.button("🔄 재생성", key=f"regen_{clip['clip_id']}"):
                    with st.spinner("재생성 중..."):
                        new_path = step_generate_clip(
                            str(meta["video_path"]), clip, clips_dir,
                            layout, title_color, title_font_size,
                            stt["segments"], sub_font_size, sub_color, sub_box, sub_position,
                            start_override=re_start, end_override=re_end,
                        )
                    if new_path:
                        # 세션 결과 업데이트
                        for d in st.session_state["gen_results"]:
                            if d["clip"]["clip_id"] == clip["clip_id"]:
                                d["path"] = new_path
                                d["clip"]["start"] = re_start
                                d["clip"]["end"]   = re_end
                        st.success("재생성 완료!")
                        st.rerun()
                    else:
                        st.error("재생성 실패")

    st.success(f"🎉 {len(results_pairs)}개 클립 완료!")


if __name__ == "__main__":
    main()
