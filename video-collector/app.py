import streamlit as st
import tempfile
import os
import csv
import io

from modules.srt_parser import parse_srt
from modules.claude_analyzer import analyze_scenes
from modules.video_searcher import search_videos
from modules.sheets_writer import write_to_sheets

st.set_page_config(page_title="SRT 영상 후보 수집기", page_icon="🎬", layout="wide")
st.title("🎬 SRT 영상 후보 수집기")

# ── 사이드바: API 키 입력 ──────────────────────────────
with st.sidebar:
    st.header("⚙️ API 설정")
    anthropic_key = st.text_input(
        "Anthropic API Key", type="password", value=os.getenv("ANTHROPIC_API_KEY", "")
    )
    pexels_key = st.text_input(
        "Pexels API Key", type="password", value=os.getenv("PEXELS_API_KEY", "")
    )
    pixabay_key = st.text_input(
        "Pixabay API Key", type="password", value=os.getenv("PIXABAY_API_KEY", "")
    )

    # 입력값을 환경변수에 즉시 반영 (modules가 os.getenv로 읽으므로)
    if anthropic_key:
        os.environ["ANTHROPIC_API_KEY"] = anthropic_key
    if pexels_key:
        os.environ["PEXELS_API_KEY"] = pexels_key
    if pixabay_key:
        os.environ["PIXABAY_API_KEY"] = pixabay_key

    st.divider()
    st.header("📤 내보내기 방식")
    export_mode = st.radio("", ["CSV 다운로드만", "Google Sheets만", "둘 다"])

    spreadsheet_id = None
    sa_json_path = None
    if export_mode in ["Google Sheets만", "둘 다"]:
        spreadsheet_id = st.text_input(
            "Spreadsheet ID", value=os.getenv("SPREADSHEET_ID", "")
        )
        sa_file = st.file_uploader("service_account.json 업로드", type=["json"])
        if sa_file:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tmp:
                tmp.write(sa_file.read())
                sa_json_path = tmp.name
            os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"] = sa_json_path

# ── 메인: SRT 업로드 ──────────────────────────────────
uploaded_srt = st.file_uploader("SRT 파일 업로드", type=["srt"])

if uploaded_srt:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".srt", mode="wb") as tmp:
        tmp.write(uploaded_srt.read())
        srt_tmp_path = tmp.name

    subtitles = parse_srt(srt_tmp_path)
    os.unlink(srt_tmp_path)

    with st.expander(f"📄 자막 미리보기 — 총 {len(subtitles)}개 블록"):
        for sub in subtitles[:10]:
            st.text(f"[{sub['start']} → {sub['end']}] {sub['text']}")
        if len(subtitles) > 10:
            st.caption(f"... 외 {len(subtitles) - 10}개")

    if st.button("▶ 분석 시작", type="primary"):
        progress = st.progress(0, text="🤖 장면 분석 중...")

        scenes = analyze_scenes(subtitles)
        progress.progress(30, text=f"✅ {len(scenes)}개 장면 완료. 🎬 영상 검색 중...")

        for i, scene in enumerate(scenes):
            scene["videos"] = search_videos(scene)
            pct = 30 + int(60 * (i + 1) / len(scenes))
            progress.progress(pct, text=f"🎬 영상 검색 중... ({i + 1}/{len(scenes)})")

        progress.progress(95, text="💾 저장 중...")

        if export_mode in ["Google Sheets만", "둘 다"]:
            write_to_sheets(scenes, spreadsheet_id)

        progress.progress(100, text="✅ 완료!")
        st.session_state["scenes"] = scenes

# ── 결과 표시 ─────────────────────────────────────────
if "scenes" in st.session_state:
    scenes = st.session_state["scenes"]
    total_videos = sum(len(s.get("videos", [])) for s in scenes)
    st.success(f"총 {len(scenes)}개 장면 / {total_videos}개 영상 후보 수집 완료")

    for scene in scenes:
        label = (
            f"[장면 {scene['scene_number']}] "
            f"{scene['start_time']} ~ {scene['end_time']}  |  "
            f"{scene['summary_ko']}"
        )
        with st.expander(label):
            st.markdown(f"🔑 **키워드**: `{'`, `'.join(scene['search_keywords'])}`")
            st.markdown(f"📁 **파일명**: `{scene['suggested_filename']}`")
            st.markdown(f"🏷️ **태그**: {', '.join(scene['tags'])}")
            st.markdown(f"📝 {scene['description']}")

            videos = scene.get("videos", [])
            if videos:
                cols = st.columns(min(3, len(videos)))
                for idx, video in enumerate(videos):
                    with cols[idx % 3]:
                        if video.get("thumbnail"):
                            st.image(video["thumbnail"], use_column_width=True)
                        st.caption(f"**{video['title']}**")
                        st.caption(
                            f"{video['source'].upper()} | {video['duration']}초 | "
                            f"{video['width']}×{video['height']}"
                        )
                        st.link_button("🔗 영상 보기", video["url"])
            else:
                st.warning("검색 결과 없음")

    # ── CSV 다운로드 ─────────────────────────────────
    if export_mode in ["CSV 다운로드만", "둘 다"]:
        def scenes_to_csv(scenes):
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(
                [
                    "장면#", "시작", "끝", "자막요약", "검색키워드", "소스",
                    "영상제목", "영상URL", "썸네일URL", "길이(초)",
                    "제안파일명", "설명", "태그", "선택여부",
                ]
            )
            for s in scenes:
                videos = s.get("videos", [])
                if not videos:
                    w.writerow(
                        [
                            s["scene_number"], s["start_time"], s["end_time"],
                            s["summary_ko"], ", ".join(s["search_keywords"]),
                            "검색 결과 없음", "", "", "", "",
                            s["suggested_filename"], s["description"],
                            ", ".join(s["tags"]), "",
                        ]
                    )
                else:
                    for v in videos:
                        w.writerow(
                            [
                                s["scene_number"], s["start_time"], s["end_time"],
                                s["summary_ko"], ", ".join(s["search_keywords"]),
                                v["source"], v["title"], v["url"], v["thumbnail"],
                                v["duration"], s["suggested_filename"],
                                s["description"], ", ".join(s["tags"]), "",
                            ]
                        )
            return buf.getvalue()

        st.download_button(
            label="📥 CSV 다운로드",
            data=scenes_to_csv(scenes),
            file_name="video_candidates.csv",
            mime="text/csv",
        )
