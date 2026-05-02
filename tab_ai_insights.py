"""🤖 AI 인사이트 탭 - Claude API로 니치 영상 패턴 분석 및 주제 제안."""

import io
from datetime import datetime

import pandas as pd
import streamlit as st

from ai_analyzer import analyze_niche_videos, stream_analyze_niche_videos


def _build_ai_excel(channel_info: dict, analysis_text: str, niche_titles: list[str], multiplier: float) -> bytes:
    """AI 분석 결과를 엑셀 파일로 생성합니다."""
    output = io.BytesIO()
    today = datetime.now().strftime("%Y-%m-%d")

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame({
            "항목": ["채널명", "분석일자", "기준배수", "니치영상수", "분석결과"],
            "내용": [
                channel_info.get("title", ""),
                today,
                f"{multiplier}x",
                len(niche_titles),
                analysis_text,
            ],
        }).to_excel(writer, sheet_name="AI 분석 결과", index=False)

        pd.DataFrame({
            "번호": range(1, len(niche_titles) + 1),
            "니치 영상 제목": niche_titles,
        }).to_excel(writer, sheet_name="니치 영상 목록", index=False)

    return output.getvalue()


def _render_ai_for_channel(channel_info: dict, result: dict, params: dict, key_suffix: str = ""):
    """단일 채널에 대한 AI 인사이트 UI를 렌더링합니다."""
    df_niche = result["df_niche"]
    multiplier = params.get("multiplier", 3.0)

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
                placeholder.empty()
                st.error(f"API 키 오류: {e}")

            except Exception as stream_err:
                if full_text:
                    # 부분 결과가 있으면 표시하고 저장
                    placeholder.markdown(full_text)
                    st.session_state[result_key] = full_text
                    st.warning(
                        f"스트리밍이 중간에 중단되었습니다. 수신된 내용까지 표시합니다. "
                        f"({stream_err})"
                    )
                else:
                    # 수신된 내용이 없으면 non-streaming 방식으로 재시도
                    placeholder.empty()
                    st.warning("스트리밍 연결 실패. 일반 방식으로 재시도합니다...")
                    try:
                        result_text = analyze_niche_videos(
                            niche_titles,
                            multiplier=multiplier,
                            channel_name=channel_info.get("title", ""),
                        )
                        st.session_state[result_key] = result_text
                        st.markdown(result_text)
                        st.success("분석 완료! (일반 방식)")
                    except Exception as fallback_err:
                        st.error(f"AI 분석 오류: {fallback_err}")

    elif result_key in st.session_state:
        st.markdown(st.session_state[result_key])
        st.divider()
        today = datetime.now().strftime("%Y%m%d")
        ch_name = channel_info.get("title", "channel")
        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            st.download_button(
                label="📥 AI 분석 결과 다운로드 (Excel)",
                data=_build_ai_excel(channel_info, st.session_state[result_key], niche_titles, multiplier),
                file_name=f"시사콘텐츠_AI인사이트_{ch_name}_{today}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key=f"dl_excel_{key_suffix}",
            )
        with dl_col2:
            st.download_button(
                label="📄 마크다운 다운로드",
                data=st.session_state[result_key].encode("utf-8"),
                file_name=f"ai_insight_{ch_name}.md",
                mime="text/markdown",
                use_container_width=True,
                key=f"dl_{key_suffix}",
            )


def render_ai_insights_tab():
    if "multi_results" not in st.session_state and "analysis_result" not in st.session_state:
        st.info("먼저 '⚙️ 채널 설정' 탭에서 채널을 선택하고 분석을 시작해주세요.", icon="👈")
        return

    params = st.session_state.get("analysis_params", {})
    multi_results: list[dict] = st.session_state.get("multi_results", [])

    # 니치 영상이 있는 채널만 필터링
    niche_results = [d for d in multi_results if not d["result"]["df_niche"].empty]

    # ── 단일 채널 또는 니치 채널 1개 ─────────────────────────────────────────
    if len(niche_results) <= 1:
        if not niche_results:
            st.header("🤖 AI 인사이트")
            st.warning(
                "니치 영상이 발견된 채널이 없습니다. "
                "기준 배수를 낮추거나 분석 기간을 늘린 후 다시 분석해주세요."
            )
            return
        data = niche_results[0]
        channel_info = data["channel_info"]
        st.header(f"🤖 AI 인사이트 — {channel_info.get('title', '')}")
        _render_ai_for_channel(channel_info, data["result"], params, key_suffix="single")
        return

    # ── 다중 채널 — 니치 영상 있는 채널만 드롭다운으로 선택 ─────────────────
    st.header(f"🤖 AI 인사이트 — {len(niche_results)}개 채널")

    channel_options = {d["channel_info"]["title"]: i for i, d in enumerate(niche_results)}
    selected_name = st.selectbox(
        "분석할 채널 선택",
        options=list(channel_options.keys()),
        key="ai_channel_select",
    )

    selected_idx = channel_options[selected_name]
    data = niche_results[selected_idx]
    info = data["channel_info"]

    h_col1, h_col2 = st.columns([1, 6])
    with h_col1:
        if info.get("thumbnail"):
            st.image(info["thumbnail"], width=60)
    with h_col2:
        st.write(f"**{info['title']}**")
        niche_count = data["result"]["niche_count"]
        st.caption(f"니치 영상 {niche_count}개")
    st.divider()

    _render_ai_for_channel(info, data["result"], params, key_suffix=f"ch{selected_idx}")
