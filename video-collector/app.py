import streamlit as st
import tempfile
import os
import csv
import io

from modules.srt_parser import parse_srt
from modules.txt_parser import parse_txt
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
    if export_mode in ["Google Sheets만", "둘 다"]:
        spreadsheet_id = st.text_input(
            "Spreadsheet ID", value=os.getenv("SPREADSHEET_ID", "")
        )
        sa_file = st.file_uploader("service_account.json 업로드", type=["json"])
        if sa_file:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tmp:
                tmp.write(sa_file.read())
            os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"] = tmp.name


# ── 공통 헬퍼 ─────────────────────────────────────────
def render_video_grid(videos: list[dict]):
    if not videos:
        st.warning("검색 결과 없음")
        return
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
            if video.get("url"):
                st.link_button("🔗 영상 보기", video["url"])


def scenes_to_csv(scenes: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        ["장면#", "시작", "끝", "자막요약", "검색키워드", "소스",
         "영상제목", "영상URL", "썸네일URL", "길이(초)",
         "제안파일명", "설명", "태그", "선택여부"]
    )
    for s in scenes:
        videos = s.get("videos", [])
        if not videos:
            w.writerow([
                s["scene_number"], s.get("start_time", ""), s.get("end_time", ""),
                s.get("summary_ko", ""), ", ".join(s.get("search_keywords", [])),
                "검색 결과 없음", "", "", "", "",
                s.get("suggested_filename", ""), s.get("description", ""),
                ", ".join(s.get("tags", [])), "",
            ])
        else:
            for v in videos:
                w.writerow([
                    s["scene_number"], s.get("start_time", ""), s.get("end_time", ""),
                    s.get("summary_ko", ""), ", ".join(s.get("search_keywords", [])),
                    v["source"], v["title"], v["url"], v["thumbnail"],
                    v["duration"], s.get("suggested_filename", ""),
                    s.get("description", ""), ", ".join(s.get("tags", [])), "",
                ])
    return buf.getvalue()


def videos_to_csv(keyword: str, videos: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["키워드", "소스", "영상제목", "영상URL", "썸네일URL", "길이(초)", "해상도"])
    for v in videos:
        w.writerow([
            keyword, v["source"], v["title"], v["url"], v["thumbnail"],
            v["duration"], f"{v['width']}×{v['height']}",
        ])
    return buf.getvalue()


# ── 탭 구성 ───────────────────────────────────────────
tab_subtitle, tab_keyword = st.tabs(["📄 자막 분석", "🔍 키워드 영상 검색"])


# ════════════════════════════════════════════════════════
# 탭 1: 자막 분석 (SRT / TXT)
# ════════════════════════════════════════════════════════
with tab_subtitle:
    uploaded_file = st.file_uploader("자막 파일 업로드 (.srt 또는 .txt)", type=["srt", "txt"])

    if uploaded_file:
        ext = uploaded_file.name.rsplit(".", 1)[-1].lower()
        suffix = f".{ext}"

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, mode="wb") as tmp:
            tmp.write(uploaded_file.read())
            tmp_path = tmp.name

        if ext == "srt":
            subtitles = parse_srt(tmp_path)
        else:
            subtitles = parse_txt(tmp_path)
        os.unlink(tmp_path)

        with st.expander(f"📄 자막 미리보기 — 총 {len(subtitles)}개 블록"):
            for sub in subtitles[:10]:
                if sub.get("start"):
                    st.text(f"[{sub['start']} → {sub['end']}] {sub['text']}")
                else:
                    prompt_preview = f" | 프롬프트: {sub['image_prompt'][:40]}..." if sub.get("image_prompt") else ""
                    st.text(f"[{sub['index']}] {sub['text'][:60]}...{prompt_preview}")
            if len(subtitles) > 10:
                st.caption(f"... 외 {len(subtitles) - 10}개")

        if st.button("▶ 분석 시작", type="primary", key="btn_analyze"):
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

    if "scenes" in st.session_state:
        scenes = st.session_state["scenes"]
        total_videos = sum(len(s.get("videos", [])) for s in scenes)
        st.success(f"총 {len(scenes)}개 장면 / {total_videos}개 영상 후보 수집 완료")

        for scene in scenes:
            time_range = (
                f"{scene.get('start_time', '')} ~ {scene.get('end_time', '')}"
                if scene.get("start_time")
                else f"장면 {scene['scene_number']}"
            )
            label = f"[장면 {scene['scene_number']}] {time_range}  |  {scene.get('summary_ko', '')}"
            with st.expander(label):
                st.markdown(f"🔑 **키워드**: `{'`, `'.join(scene.get('search_keywords', []))}`")
                st.markdown(f"📁 **파일명**: `{scene.get('suggested_filename', '')}`")
                st.markdown(f"🏷️ **태그**: {', '.join(scene.get('tags', []))}")
                st.markdown(f"📝 {scene.get('description', '')}")
                render_video_grid(scene.get("videos", []))

        if export_mode in ["CSV 다운로드만", "둘 다"]:
            st.download_button(
                label="📥 CSV 다운로드",
                data=scenes_to_csv(scenes),
                file_name="video_candidates.csv",
                mime="text/csv",
            )


# ════════════════════════════════════════════════════════
# 탭 2: 키워드 직접 영상 검색
# ════════════════════════════════════════════════════════
with tab_keyword:
    st.subheader("🔍 키워드로 영상 검색")
    st.caption("Pexels + Pixabay에서 키워드로 바로 영상을 검색합니다.")

    kw_col, btn_col = st.columns([4, 1])
    with kw_col:
        keyword_input = st.text_input(
            "검색 키워드 (영어 권장)",
            placeholder="예: robot factory automation",
            label_visibility="collapsed",
        )
    with btn_col:
        search_clicked = st.button("🔍 검색", type="primary", key="btn_keyword_search")

    if search_clicked and keyword_input.strip():
        keyword = keyword_input.strip()
        with st.spinner(f'"{keyword}" 검색 중...'):
            dummy_scene = {"search_keywords": [keyword]}
            results = search_videos(dummy_scene)
        st.session_state["kw_results"] = results
        st.session_state["kw_keyword"] = keyword

    if "kw_results" in st.session_state:
        results = st.session_state["kw_results"]
        keyword = st.session_state.get("kw_keyword", "")
        st.success(f'"{keyword}" 검색 결과: {len(results)}개')
        render_video_grid(results)

        if results:
            st.download_button(
                label="📥 CSV 다운로드",
                data=videos_to_csv(keyword, results),
                file_name=f"videos_{keyword.replace(' ', '_')}.csv",
                mime="text/csv",
            )
    elif search_clicked and not keyword_input.strip():
        st.warning("키워드를 입력해주세요.")
