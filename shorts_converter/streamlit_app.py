import os
import sys
import io
import json
import uuid
import subprocess
import glob
import re
import tempfile
import logging
from pathlib import Path
from typing import Optional

import httpx

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

TEMP_DIR = Path(tempfile.gettempdir()) / "shorts_converter"
TEMP_DIR.mkdir(exist_ok=True)

st.set_page_config(
    page_title="YouTube → Shorts 변환기",
    page_icon="🎬",
    layout="wide",
)

# ── CSS ──────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  [data-testid="stAppViewContainer"] { background: #0f0f17; }
  [data-testid="stSidebar"] { background: #1a1a2e; }
  h1, h2, h3 { color: #e2e8f0 !important; }
  .stTextInput > div > div > input { background: #1a1a2e; color: #e2e8f0; border-color: #2d2d4e; }
  .clip-card {
    background: #1a1a2e; border: 1px solid #2d2d4e; border-radius: 12px;
    padding: 16px; margin-bottom: 12px;
  }
  .step-done   { color: #34d399; font-weight: 600; }
  .step-active { color: #a78bfa; font-weight: 600; }
  .step-wait   { color: #4a5568; }
  .tag { display:inline-block; background:#2d2d4e; color:#94a3b8;
         border-radius:6px; padding:2px 8px; font-size:12px; margin:2px; }
  .error-box { background:#2d1a1a; border:1px solid #7f1d1d;
               border-radius:8px; padding:12px; color:#fca5a5; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ──────────────────────────────────────────────────────────────────

def find_korean_font() -> Optional[str]:
    candidates = [
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    for pattern in ["/usr/share/fonts/**/*.ttf", "/usr/share/fonts/**/*.ttc"]:
        found = glob.glob(pattern, recursive=True)
        if found:
            return found[0]
    return None


def esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("'", "'").replace(":", "\\:").replace("%", "\\%")


def fmt_time(t: float) -> str:
    m, s = divmod(int(t), 60)
    return f"{m}:{s:02d}"


def run_cmd(cmd: list, label: str = "") -> subprocess.CompletedProcess:
    log.info("RUN %s: %s", label, " ".join(str(c) for c in cmd))
    result = subprocess.run(
        cmd,
        capture_output=True,
        encoding="utf-8",
        errors="replace",   # 디코딩 불가 바이트를 ?로 대체 (크래시 방지)
    )
    if result.returncode != 0:
        log.error("FAIL %s stderr: %s", label, result.stderr[-500:])
    return result


# ── Pipeline Steps ───────────────────────────────────────────────────────────

def step_download(url: str, job_dir: Path) -> dict:
    """yt-dlp로 영상 다운로드 후 메타데이터 반환."""
    result = run_cmd([
        sys.executable, "-m", "yt_dlp",
        "-f", "best[height<=720][ext=mp4]/best[height<=720]/best",
        "--output", str(job_dir / "video.%(ext)s"),
        "--write-info-json",
        "--no-playlist",
        "--merge-output-format", "mp4",
        url,
    ], "yt-dlp")

    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp 오류:\n{result.stderr[-600:]}")

    video_files = [
        f for f in job_dir.glob("video.*")
        if f.suffix not in (".json", ".part", ".ytdl")
    ]
    if not video_files:
        raise RuntimeError("다운로드된 영상 파일을 찾을 수 없습니다.")

    video_path = video_files[0]

    info_files = list(job_dir.glob("*.info.json"))
    info: dict = {}
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
    """ffmpeg로 16kHz 모노 WAV 추출."""
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
    """Whisper STT."""
    import whisper
    model = whisper.load_model(model_size)
    result = model.transcribe(str(audio_path), task="transcribe")
    segments = [
        {"start": round(s["start"], 2), "end": round(s["end"], 2), "text": s["text"].strip()}
        for s in result["segments"]
    ]
    return {"text": result["text"], "segments": segments}


def step_analyze(transcript: str, segments: list, duration: float, channel: str) -> list:
    """Claude API로 후킹 포인트 추출."""
    import traceback as _tb

    try:
        # ── 체크포인트 1: 환경변수 ──────────────────────────────
        st.info(f"[DEBUG 1] PYTHONIOENCODING={os.environ.get('PYTHONIOENCODING')} / PYTHONUTF8={os.environ.get('PYTHONUTF8')}")

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다.")

        def _safe(text: str) -> str:
            return text.encode("utf-8", errors="replace").decode("utf-8")

        # ── 체크포인트 2: transcript 안전 처리 ──────────────────
        st.info(f"[DEBUG 2] transcript 길이={len(transcript)}, 타입={type(transcript)}")
        safe_transcript = _safe(transcript)

        # ── 체크포인트 3: segments 처리 ─────────────────────────
        st.info(f"[DEBUG 3] segments 수={len(segments)}")
        segments_text = "\n".join(
            f"[{s['start']:.1f}s-{s['end']:.1f}s] {_safe(s['text'])}"
            for s in segments
        )

        # ── 체크포인트 4: prompt 조립 ────────────────────────────
        safe_channel = _safe(channel)
        st.info(f"[DEBUG 4] channel={safe_channel!r}, segments_text 길이={len(segments_text)}")

        prompt = f"""당신은 SNS 바이럴 콘텐츠 전문가입니다.
아래 유튜브 자막을 분석해서 쇼츠/릴스 클립으로 만들기 좋은 구간 최대 6개를 선별하세요.

영상 길이: {duration:.0f}초 | 채널: {safe_channel}

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

        # ── 체크포인트 5: Claude API 호출 ───────────────────────
        st.info(f"[DEBUG 5] prompt 길이={len(prompt)}, Claude API 호출 시작")
        # API 키를 ASCII-safe 바이트로 명시 인코딩해 httpx 헤더 오류 차단
        safe_api_key = api_key.encode("ascii", errors="replace").decode("ascii")
        http_client = httpx.Client(
            headers={"x-api-key": safe_api_key},
            timeout=120.0,
        )
        client = anthropic.Anthropic(api_key=safe_api_key, http_client=http_client)
        message = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )

        # ── 체크포인트 6: 응답 파싱 ─────────────────────────────
        text = message.content[0].text
        st.info(f"[DEBUG 6] Claude 응답 길이={len(text)}")

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

    except Exception:
        tb = _tb.format_exc()
        st.error(f"**step_analyze 전체 traceback:**\n```\n{tb}\n```")
        raise


def step_generate_clip(clip: dict, video_path: Path, segments: list,
                        job_dir: Path, layout: str, title_color: str,
                        font_size: int, show_subs: bool) -> Path:
    """ffmpeg로 세로 클립 생성."""
    output_dir = job_dir / "clips"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / f"clip_{clip['index']:02d}_{clip['clip_id']}.mp4"

    font_path = find_korean_font()
    font_opt = f":fontfile='{font_path}'" if font_path else ""
    title_e = esc(clip["title"])
    channel_e = esc(f"@{clip['channel']}" if clip.get("channel") else "")
    tags = " ".join(f"#{t.lstrip('#')}" for t in clip.get("hashtags", [])[:4])
    tags_e = esc(tags)
    c = title_color
    sz = font_size

    if layout == "letterbox":
        base = "scale=1080:-2:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black"
    else:
        base = "crop=in_h*9/16:in_h,scale=1080:1920"

    filters = [
        base,
        f"drawtext=text='{title_e}'{font_opt}:x=(w-text_w)/2:y=80:fontsize={sz}:fontcolor={c}:box=1:boxcolor=black@0.65:boxborderw=18:shadowx=2:shadowy=2:shadowcolor=black@0.8",
    ]
    if channel_e:
        filters.append(f"drawtext=text='{channel_e}'{font_opt}:x=(w-text_w)/2:y=h-130:fontsize=34:fontcolor=white@0.95:box=1:boxcolor=black@0.55:boxborderw=12")
    if tags_e:
        filters.append(f"drawtext=text='{tags_e}'{font_opt}:x=(w-text_w)/2:y=h-75:fontsize=28:fontcolor=yellow@0.9:box=1:boxcolor=black@0.4:boxborderw=8")

    # ASS 자막
    if show_subs and segments:
        ass_path = _write_ass(segments, clip["start"], clip["end"], output_dir, clip["clip_id"])
        if ass_path:
            filters.append(f"ass='{ass_path}'")

    cmd = [
        "ffmpeg",
        "-ss", str(clip["start"]),
        "-i", str(video_path),
        "-t", str(clip["end"] - clip["start"]),
        "-vf", ",".join(filters),
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart", "-r", "30",
        str(output_path), "-y",
    ]
    result = run_cmd(cmd, f"ffmpeg-clip-{clip['index']}")
    if result.returncode != 0 or not output_path.exists():
        raise RuntimeError(f"클립 생성 실패 (clip {clip['index']}):\n{result.stderr[-600:]}")
    return output_path


def _write_ass(segments, start, end, out_dir, clip_id) -> Optional[str]:
    def tf(t):
        h, r = divmod(t, 3600)
        m, s = divmod(r, 60)
        return f"{int(h)}:{int(m):02d}:{s:05.2f}"

    lines = [
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n",
        "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n",
        "Style: Default,Arial,44,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,60,60,120,1\n\n",
        "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n",
    ]
    found = False
    for seg in segments:
        if seg["end"] <= start or seg["start"] >= end:
            continue
        rs = max(0.0, seg["start"] - start)
        re_ = min(end - start, seg["end"] - start)
        text = seg["text"].strip().replace("\n", " ")
        if text:
            lines.append(f"Dialogue: 0,{tf(rs)},{tf(re_)},Default,,0,0,0,,{text}\n")
            found = True
    if not found:
        return None
    path = out_dir / f"sub_{clip_id}.ass"
    path.write_text("".join(lines), encoding="utf-8")
    return str(path)


# ── Streamlit UI ─────────────────────────────────────────────────────────────

def main():
    st.markdown("## 🎬 YouTube → Shorts / Reels 변환기")
    st.markdown("유튜브 영상을 AI가 분석해 쇼츠용 세로 클립으로 자동 변환합니다.")

    # ── 사이드바 설정 ──
    with st.sidebar:
        st.markdown("### 🔑 Anthropic API 키")
        api_key_input = st.text_input(
            "API Key",
            value=os.environ.get("ANTHROPIC_API_KEY", ""),
            type="password",
            placeholder="sk-ant-...",
            help="환경변수 ANTHROPIC_API_KEY가 설정돼 있으면 자동으로 채워집니다.",
        )
        if api_key_input:
            # 런타임 환경변수에도 반영해서 step_analyze가 읽을 수 있게
            os.environ["ANTHROPIC_API_KEY"] = api_key_input.strip()
        if not api_key_input:
            st.warning("API 키를 입력하세요.")

        st.divider()
        st.markdown("### ⚙️ 설정")
        whisper_model = st.selectbox("Whisper 모델", ["base", "small", "medium"], index=0,
                                      help="작을수록 빠르지만 정확도 낮음")
        layout = st.selectbox("레이아웃", ["letterbox", "crop"],
                               format_func=lambda x: "레터박스 (블랙바)" if x == "letterbox" else "세로 크롭 (9:16)")
        title_color = st.selectbox("제목 색상", ["white", "yellow", "#00ffcc", "#ff6b6b"],
                                    format_func=lambda x: {"white":"흰색","yellow":"노랑","#00ffcc":"민트","#ff6b6b":"빨강"}.get(x,x))
        font_size = st.slider("제목 폰트 크기", 28, 80, 52)
        show_subs = st.toggle("자막 자동 삽입", value=True)
        st.divider()
        st.markdown("**필요 패키지**")
        st.code("pip install -r requirements.txt\napt install ffmpeg", language="bash")

    # ── URL 입력 ──
    url = st.text_input("🔗 YouTube URL", placeholder="https://www.youtube.com/watch?v=...")
    run_btn = st.button("▶ 변환 시작", type="primary", use_container_width=True)

    if not run_btn or not url.strip():
        if not url.strip() and run_btn:
            st.warning("YouTube URL을 입력하세요.")
        _show_previous_results()
        return

    # ── 진행 상황 5단계 ──
    job_dir = TEMP_DIR / str(uuid.uuid4())
    job_dir.mkdir(parents=True, exist_ok=True)

    steps = ["📥 다운로드", "🔊 오디오 추출", "📝 음성 전사", "🤖 AI 분석", "🎞️ 클립 생성"]
    cols = st.columns(5)
    step_status = ["wait"] * 5

    def render_steps():
        for i, (col, label) in enumerate(zip(cols, steps)):
            s = step_status[i]
            icon = "✅" if s == "done" else ("⏳" if s == "active" else "○")
            cls = "step-done" if s == "done" else ("step-active" if s == "active" else "step-wait")
            col.markdown(f'<div class="{cls}">{icon} {label}</div>', unsafe_allow_html=True)

    result_placeholder = st.empty()

    # ── STEP 1: 다운로드 ──
    step_status[0] = "active"
    render_steps()
    with st.status("📥 영상 다운로드 중...", expanded=True) as status:
        try:
            st.write(f"URL: `{url}`")
            meta = step_download(url.strip(), job_dir)
            step_status[0] = "done"
            render_steps()
            status.update(label=f"✅ 다운로드 완료: {meta['title']}", state="complete")
            st.info(f"**채널:** {meta['channel']} | **길이:** {fmt_time(meta['duration'])} ({meta['duration']:.0f}초)")
        except Exception as e:
            status.update(label="❌ 다운로드 실패", state="error")
            st.markdown(f'<div class="error-box">❌ {e}</div>', unsafe_allow_html=True)
            log.error("Download failed: %s", e)
            return

    # ── STEP 2: 오디오 추출 ──
    step_status[1] = "active"
    render_steps()
    with st.status("🔊 오디오 추출 중...", expanded=False) as status:
        try:
            audio_path = step_extract_audio(meta["video_path"], job_dir)
            step_status[1] = "done"
            render_steps()
            status.update(label="✅ 오디오 추출 완료", state="complete")
        except Exception as e:
            status.update(label="❌ 오디오 추출 실패", state="error")
            st.markdown(f'<div class="error-box">❌ {e}</div>', unsafe_allow_html=True)
            return

    # ── STEP 3: STT ──
    step_status[2] = "active"
    render_steps()
    with st.status(f"📝 Whisper({whisper_model}) 음성 전사 중...", expanded=True) as status:
        try:
            st.write("모델 로드 후 전사를 시작합니다. 영상 길이에 따라 1~5분 소요됩니다.")
            stt = step_transcribe(audio_path, whisper_model)
            step_status[2] = "done"
            render_steps()
            seg_count = len(stt["segments"])
            status.update(label=f"✅ 전사 완료 ({seg_count}개 세그먼트)", state="complete")
            with st.expander("전사 내용 보기"):
                st.text(stt["text"][:3000] + ("..." if len(stt["text"]) > 3000 else ""))
        except Exception as e:
            status.update(label="❌ 전사 실패", state="error")
            st.markdown(f'<div class="error-box">❌ {e}</div>', unsafe_allow_html=True)
            return

    # ── STEP 4: AI 분석 ──
    step_status[3] = "active"
    render_steps()
    with st.status("🤖 Claude AI 후킹 포인트 분석 중...", expanded=False) as status:
        try:
            clips = step_analyze(stt["text"], stt["segments"], meta["duration"], meta["channel"])
            step_status[3] = "done"
            render_steps()
            status.update(label=f"✅ AI 분석 완료 ({len(clips)}개 클립 선별)", state="complete")
        except Exception as e:
            status.update(label="❌ AI 분석 실패", state="error")
            st.markdown(f'<div class="error-box">❌ {e}</div>', unsafe_allow_html=True)
            return

    # ── 클립 목록 표시 ──
    st.markdown("### 📋 선별된 후킹 포인트")
    hook_emoji = {"tip":"💡","reaction":"😮","story":"📖","fact":"📊","humor":"😂"}

    selected = []
    for clip in clips:
        emoji = hook_emoji.get(clip.get("hook_type", ""), "🎬")
        with st.expander(f"{emoji} [{clip['index']}] {clip['title']}  ·  {fmt_time(clip['start'])} ~ {fmt_time(clip['end'])}  ({clip['end']-clip['start']:.0f}초)", expanded=True):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"**이유:** {clip.get('reason','')}")
                tags_html = " ".join(f'<span class="tag">#{t.lstrip("#")}</span>' for t in clip.get("hashtags",[]))
                st.markdown(tags_html, unsafe_allow_html=True)
            with col2:
                if st.checkbox("생성", value=True, key=f"sel_{clip['clip_id']}"):
                    selected.append(clip)

    if not selected:
        st.warning("생성할 클립을 하나 이상 선택하세요.")
        return

    # ── STEP 5: 클립 생성 ──
    step_status[4] = "active"
    render_steps()
    st.markdown(f"### 🎞️ 클립 생성 중 ({len(selected)}개)")
    progress_bar = st.progress(0)
    results = []

    for i, clip in enumerate(selected):
        with st.status(f"클립 {clip['index']}: {clip['title']} 렌더링 중...", expanded=False) as status:
            try:
                out_path = step_generate_clip(
                    clip, meta["video_path"], stt["segments"],
                    job_dir, layout, title_color, font_size, show_subs,
                )
                results.append((clip, out_path))
                status.update(label=f"✅ 클립 {clip['index']} 완료 ({out_path.stat().st_size // 1024}KB)", state="complete")
            except Exception as e:
                status.update(label=f"❌ 클립 {clip['index']} 실패", state="error")
                st.markdown(f'<div class="error-box">❌ {e}</div>', unsafe_allow_html=True)
                log.error("Clip %d failed: %s", clip["index"], e)
        progress_bar.progress((i + 1) / len(selected))

    step_status[4] = "done"
    render_steps()

    # ── 결과 다운로드 ──
    st.markdown("### ⬇️ 다운로드")
    if not results:
        st.error("생성된 클립이 없습니다.")
        return

    for clip, path in results:
        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown(f"**[{clip['index']}] {clip['title']}** — {fmt_time(clip['start'])}~{fmt_time(clip['end'])}")
            tags = " ".join(f"#{t.lstrip('#')}" for t in clip.get("hashtags", []))
            st.caption(tags)
        with col2:
            with open(path, "rb") as f:
                st.download_button(
                    label=f"📥 다운로드",
                    data=f,
                    file_name=f"shorts_{clip['index']:02d}_{clip['title'][:15]}.mp4",
                    mime="video/mp4",
                    key=f"dl_{clip['clip_id']}",
                    use_container_width=True,
                )

    st.success(f"🎉 {len(results)}개 클립 생성 완료!")
    st.session_state["last_results"] = [(c["title"], str(p)) for c, p in results]


def _show_previous_results():
    if "last_results" not in st.session_state:
        return
    st.divider()
    st.markdown("#### 이전 결과")
    for title, path in st.session_state["last_results"]:
        p = Path(path)
        if p.exists():
            with open(p, "rb") as f:
                st.download_button(
                    label=f"📥 {title}",
                    data=f,
                    file_name=p.name,
                    mime="video/mp4",
                    key=f"prev_{p.name}",
                )


if __name__ == "__main__":
    main()
