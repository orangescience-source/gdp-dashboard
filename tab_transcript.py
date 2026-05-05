"""📝 대본 받아쓰기 탭 - YouTube 자막 추출 및 AI 요약."""

import os
import re
import tempfile
from datetime import datetime

import streamlit as st


def _extract_video_id(url: str) -> str | None:
    """YouTube URL에서 video ID를 추출합니다."""
    match = re.search(r"(?:v=|youtu\.be/|embed/)([a-zA-Z0-9_-]{11})", url)
    return match.group(1) if match else None


def _get_transcript_via_api(video_id: str) -> str:
    """youtube_transcript_api로 자막을 가져옵니다. 한국어 → 영어 → 자동생성 순으로 시도합니다."""
    from youtube_transcript_api import YouTubeTranscriptApi

    data = None
    for lang in ["ko", "en"]:
        try:
            data = YouTubeTranscriptApi.get_transcript(video_id, languages=[lang])
            break
        except Exception:
            continue

    if data is None:
        data = YouTubeTranscriptApi.get_transcript(video_id)

    lines = []
    for entry in data:
        start = entry["start"]
        ts = f"[{int(start // 60):02d}:{int(start % 60):02d}]"
        lines.append(f"{ts} {entry['text'].strip()}")
    return "\n".join(lines)


def _get_transcript_via_whisper(url: str) -> str:
    """yt-dlp로 오디오를 받고 Whisper로 음성 인식합니다."""
    import yt_dlp
    import whisper

    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = os.path.join(tmpdir, "audio.%(ext)s")
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": audio_path,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "128",
            }],
            "quiet": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        mp3_path = os.path.join(tmpdir, "audio.mp3")
        model = whisper.load_model("base")
        result = model.transcribe(mp3_path)

        lines = []
        for seg in result.get("segments", []):
            start = seg["start"]
            ts = f"[{int(start // 60):02d}:{int(start % 60):02d}]"
            lines.append(f"{ts} {seg['text'].strip()}")
        return "\n".join(lines) if lines else result.get("text", "")


def _summarize_with_claude(transcript_text: str, video_url: str) -> str:
    """Claude API로 대본을 요약합니다."""
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        try:
            api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
        except Exception:
            pass
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY가 설정되지 않았습니다.")

    sample = transcript_text[:6000]
    if len(transcript_text) > 6000:
        sample += "\n\n[... 이하 생략 ...]"

    prompt = f"""다음은 YouTube 영상의 대본입니다.

영상 URL: {video_url}

대본:
{sample}

아래 형식으로 분석해주세요:

## 📌 영상 주제 (한 줄)
영상의 핵심 주제를 한 문장으로 정리해주세요.

## 📝 핵심 내용 요약 (3~5줄)
영상의 주요 내용을 3~5줄로 요약해주세요.

## 🔑 주요 키워드
핵심 키워드 5~10개를 추출해주세요.

## 💡 인사이트
이 영상에서 얻을 수 있는 핵심 인사이트나 시사점을 2~3가지 제시해주세요.
"""
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def render_transcript_tab():
    st.header("📝 대본 받아쓰기")
    st.caption("YouTube 영상의 자막을 추출하고 Claude AI로 요약합니다.")

    url = st.text_input(
        "YouTube URL",
        placeholder="예: https://www.youtube.com/watch?v=xxxxx",
        key="transcript_url_input",
    )

    start_btn = st.button(
        "받아쓰기 시작",
        type="primary",
        use_container_width=True,
        disabled=not bool(url),
    )

    if start_btn and url:
        video_id = _extract_video_id(url)
        if not video_id:
            st.error("유효한 YouTube URL을 입력해주세요.")
            return

        transcript_text = None
        method_used = ""

        # 1단계: youtube_transcript_api
        with st.spinner("자막 추출 중..."):
            try:
                transcript_text = _get_transcript_via_api(video_id)
                method_used = "YouTube 자막 (CC)"
            except Exception as e:
                st.info(f"YouTube 자막 없음 ({type(e).__name__}). Whisper로 시도합니다...")

        # 2단계: Whisper
        if not transcript_text:
            with st.spinner("Whisper로 음성 인식 중... (시간이 걸릴 수 있습니다)"):
                try:
                    transcript_text = _get_transcript_via_whisper(url)
                    method_used = "Whisper AI 음성 인식"
                except Exception as e:
                    st.error(f"음성 인식도 실패했습니다: {e}")
                    st.warning("자막이 없거나 비공개 영상일 수 있습니다.")
                    return

        if not transcript_text:
            st.error("대본을 추출할 수 없습니다.")
            return

        # AI 요약
        summary_text = None
        with st.spinner("AI 요약 중..."):
            try:
                summary_text = _summarize_with_claude(transcript_text, url)
            except Exception as e:
                summary_text = f"AI 요약 실패: {e}"

        st.session_state["transcript_result"] = {
            "url": url,
            "video_id": video_id,
            "transcript": transcript_text,
            "summary": summary_text,
            "method": method_used,
            "timestamp": datetime.now().strftime("%Y%m%d_%H%M"),
        }

    # 결과 표시
    if "transcript_result" in st.session_state:
        res = st.session_state["transcript_result"]

        st.success(f"추출 완료! — **{res['method']}** 사용")

        orig_tab, summary_tab = st.tabs(["📄 원문", "🤖 AI 요약"])

        with orig_tab:
            st.text_area(
                "전체 대본 (타임스탬프 포함)",
                value=res["transcript"],
                height=480,
                key="transcript_display",
            )
            st.download_button(
                label="📥 원문 텍스트 다운로드 (.txt)",
                data=res["transcript"].encode("utf-8"),
                file_name=f"transcript_{res['video_id']}_{res['timestamp']}.txt",
                mime="text/plain",
                use_container_width=True,
            )

        with summary_tab:
            if res.get("summary"):
                st.markdown(res["summary"])
                st.divider()
                st.download_button(
                    label="📥 요약 텍스트 다운로드 (.txt)",
                    data=res["summary"].encode("utf-8"),
                    file_name=f"summary_{res['video_id']}_{res['timestamp']}.txt",
                    mime="text/plain",
                    use_container_width=True,
                )
            else:
                st.info("AI 요약 결과가 없습니다.")

    elif not start_btn:
        st.info("YouTube URL을 입력하고 '받아쓰기 시작' 버튼을 클릭하세요.", icon="👆")
        st.markdown("""
        ### 동작 방식
        | 단계 | 방법 | 속도 |
        |------|------|------|
        | 1순위 | YouTube 자막(CC) 자동 추출 | 빠름 (수 초) |
        | 2순위 | Whisper AI 음성 인식 | 느림 (수 분) |

        > **팁:** 자막이 있는 영상은 수 초 안에 완료됩니다.
        > Whisper는 자막이 없는 영상에 사용되며 시간이 걸릴 수 있습니다.
        """)
