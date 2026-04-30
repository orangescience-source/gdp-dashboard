"""🤖 AI 인사이트 탭 - Claude API로 니치 영상 패턴 분석 및 주제 제안."""

import streamlit as st

from ai_analyzer import stream_analyze_niche_videos


def render_ai_insights_tab():
    if "analysis_result" not in st.session_state:
        st.info("먼저 '⚙️ 설정' 탭에서 채널을 선택하고 분석을 시작해주세요.", icon="👈")
        return

    result = st.session_state["analysis_result"]
    params = st.session_state.get("analysis_params", {})
    channel_info = st.session_state.get("channel_info", {})
    df_niche = result["df_niche"]
    multiplier = params.get("multiplier", 3.0)

    st.header(f"🤖 AI 인사이트 — {channel_info.get('title', '')}")

    if df_niche.empty:
        st.warning("니치 영상이 없어 AI 분석을 실행할 수 없습니다. '📊 분석결과' 탭을 먼저 확인해주세요.")
        return

    niche_titles = df_niche["title"].tolist()

    st.write(
        f"총 **{len(niche_titles)}개** 니치 영상 제목을 Claude AI로 분석합니다. "
        f"(기준 배수: **{multiplier}x**)"
    )

    with st.expander("분석 대상 니치 영상 제목 목록 보기"):
        for i, title in enumerate(niche_titles, 1):
            st.write(f"{i}. {title}")

    st.divider()

    run_ai = st.button(
        "Claude AI 분석 시작",
        type="primary",
        use_container_width=True,
        disabled=not niche_titles,
    )

    if run_ai:
        # 이전 결과 초기화
        st.session_state.pop("ai_insight_result", None)

        st.subheader("분석 결과")
        result_placeholder = st.empty()
        full_text = ""

        with st.spinner("Claude AI가 분석 중입니다..."):
            try:
                for chunk in stream_analyze_niche_videos(
                    niche_titles,
                    multiplier=multiplier,
                    channel_name=channel_info.get("title", ""),
                ):
                    full_text += chunk
                    result_placeholder.markdown(full_text + "▌")

                result_placeholder.markdown(full_text)
                st.session_state["ai_insight_result"] = full_text
                st.success("분석 완료!")

            except ValueError as e:
                st.error(f"API 키 오류: {e}")
            except Exception as e:
                st.error(f"AI 분석 오류: {e}")

    elif "ai_insight_result" in st.session_state:
        st.subheader("분석 결과 (이전 실행)")
        st.markdown(st.session_state["ai_insight_result"])

        # 결과 다운로드
        st.divider()
        st.download_button(
            label="분석 결과 텍스트 다운로드",
            data=st.session_state["ai_insight_result"].encode("utf-8"),
            file_name=f"ai_insight_{channel_info.get('title', 'channel')}.md",
            mime="text/markdown",
        )
