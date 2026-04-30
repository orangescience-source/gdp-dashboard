"""🤖 AI 인사이트 탭 - Claude API로 니치 영상 패턴 분석 및 주제 제안."""

import streamlit as st

from ai_analyzer import stream_analyze_niche_videos


def _render_ai_for_channel(channel_info: dict, result: dict, params: dict, key_suffix: str = ""):
    """단일 채널에 대한 AI 인사이트 UI를 렌더링합니다."""
    df_niche = result["df_niche"]
    multiplier = params.get("multiplier", 3.0)

    if df_niche.empty:
        st.warning("니치 영상이 없어 AI 분석을 실행할 수 없습니다.")
        return

    niche_titles = df_niche["title"].tolist()

    st.write(f"총 **{len(niche_titles)}개** 니치 영상 제목을 Claude AI로 분석합니다. (기준 배수: **{multiplier}x**)")

    with st.expander("분석 대상 니치 영상 제목 목록"):
        for i, title in enumerate(niche_titles, 1):
            st.write(f"{i}. {title}")

    run_key = f"run_ai_{key_suffix}"
    result_key = f"ai_insight_{key_suffix}"

    if st.button("Claude AI 분석 시작", type="primary", use_container_width=True, key=run_key):
        st.session_state.pop(result_key, None)
        full_text = ""
        placeholder = st.empty()

        with st.spinner("Claude AI가 분석 중입니다..."):
            try:
                for chunk in stream_analyze_niche_videos(
                    niche_titles,
                    multiplier=multiplier,
                    channel_name=channel_info.get("title", ""),
                ):
                    full_text += chunk
                    placeholder.markdown(full_text + "▌")

                placeholder.markdown(full_text)
                st.session_state[result_key] = full_text
                st.success("분석 완료!")

            except ValueError as e:
                st.error(f"API 키 오류: {e}")
            except Exception as e:
                st.error(f"AI 분석 오류: {e}")

    elif result_key in st.session_state:
        st.markdown(st.session_state[result_key])
        st.divider()
        st.download_button(
            label="분석 결과 다운로드",
            data=st.session_state[result_key].encode("utf-8"),
            file_name=f"ai_insight_{channel_info.get('title', 'channel')}.md",
            mime="text/markdown",
            key=f"dl_{key_suffix}",
        )


def render_ai_insights_tab():
    if "multi_results" not in st.session_state and "analysis_result" not in st.session_state:
        st.info("먼저 '⚙️ 채널 설정' 탭에서 채널을 선택하고 분석을 시작해주세요.", icon="👈")
        return

    params = st.session_state.get("analysis_params", {})
    multi_results: list[dict] = st.session_state.get("multi_results", [])

    # 단일 채널
    if len(multi_results) <= 1:
        channel_info = st.session_state.get("channel_info", {})
        result = st.session_state.get("analysis_result", {})
        st.header(f"🤖 AI 인사이트 — {channel_info.get('title', '')}")
        _render_ai_for_channel(channel_info, result, params, key_suffix="single")
        return

    # 다중 채널 — 채널별 탭
    st.header(f"🤖 AI 인사이트 — {len(multi_results)}개 채널")

    tab_labels = [d["channel_info"]["title"][:20] for d in multi_results]
    channel_tabs = st.tabs(tab_labels)

    for i, (tab, data) in enumerate(zip(channel_tabs, multi_results)):
        with tab:
            info = data["channel_info"]
            h_col1, h_col2 = st.columns([1, 6])
            with h_col1:
                if info.get("thumbnail"):
                    st.image(info["thumbnail"], width=60)
            with h_col2:
                st.write(f"**{info['title']}**")
            st.divider()
            _render_ai_for_channel(info, data["result"], params, key_suffix=f"ch{i}")
