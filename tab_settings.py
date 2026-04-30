"""⚙️ 설정 탭 - 채널 입력 및 분석 파라미터 설정."""

import streamlit as st

from youtube_api import (
    extract_channel_id,
    get_channel_info,
    get_channel_videos,
    search_political_channels,
)
from analyzer import run_analysis


def render_settings_tab():
    st.header("채널 설정")

    input_method = st.radio(
        "채널 입력 방식",
        ["직접 입력 (URL 또는 채널 ID)", "키워드로 채널 검색"],
        horizontal=True,
    )

    channel_id = None
    channel_info = None

    # ── 직접 입력 ────────────────────────────────────────────────────────────
    if input_method == "직접 입력 (URL 또는 채널 ID)":
        raw = st.text_input(
            "채널 URL 또는 채널 ID",
            placeholder="예: https://www.youtube.com/@channelname 또는 UCxxxxxxx",
        )
        if raw:
            with st.spinner("채널 ID 확인 중..."):
                channel_id = extract_channel_id(raw)
            if not channel_id:
                st.error("채널 ID를 추출할 수 없습니다. URL 또는 채널 ID를 확인해 주세요.")

    # ── 키워드 검색 ──────────────────────────────────────────────────────────
    else:
        col_kw, col_btn = st.columns([3, 1])
        with col_kw:
            keyword = st.text_input(
                "검색 키워드",
                placeholder="예: 한국 정치, 시사, 국회",
                value="한국 정치",
            )
        with col_btn:
            st.write("")
            search_clicked = st.button("채널 검색", type="primary")

        if search_clicked and keyword:
            with st.spinner(f'"{keyword}" 채널 검색 중...'):
                try:
                    channels = search_political_channels(keyword, max_results=10)
                    st.session_state["search_channels"] = channels
                except Exception as e:
                    st.error(f"검색 오류: {e}")

        if "search_channels" in st.session_state:
            channels = st.session_state["search_channels"]
            if not channels:
                st.warning("검색 결과가 없습니다.")
            else:
                options = {
                    f"{ch['title']}": ch["channel_id"] for ch in channels
                }
                selected_name = st.selectbox("채널 선택", list(options.keys()))
                channel_id = options[selected_name]

                # 선택된 채널 미리보기
                selected_ch = next(
                    ch for ch in channels if ch["channel_id"] == channel_id
                )
                with st.expander("채널 미리보기"):
                    img_col, desc_col = st.columns([1, 3])
                    with img_col:
                        if selected_ch["thumbnail"]:
                            st.image(selected_ch["thumbnail"], width=80)
                    with desc_col:
                        st.write(
                            selected_ch["description"][:200] + "..."
                            if len(selected_ch["description"]) > 200
                            else selected_ch["description"]
                        )

    st.divider()

    # ── 분석 파라미터 ─────────────────────────────────────────────────────────
    st.subheader("분석 파라미터")

    col1, col2 = st.columns(2)
    with col1:
        multiplier = st.slider(
            "니치 기준 배수",
            min_value=1.5,
            max_value=10.0,
            value=3.0,
            step=0.5,
            help="채널 평균 조회수 대비 이 배수 이상이면 니치 영상으로 분류합니다.",
        )
        max_videos = st.select_slider(
            "분석 영상 수 (최대)",
            options=[50, 100, 150, 200],
            value=100,
            help="최근 업로드된 영상을 기준으로 분석합니다.",
        )
    with col2:
        recent_only = st.toggle(
            "최근 90일 이내 영상만 분석",
            value=False,
            help="오래된 영상은 자연스럽게 조회수가 높을 수 있으므로 최근 영상에 집중합니다.",
        )
        if recent_only:
            max_days = st.slider(
                "기준 기간 (일)",
                min_value=30,
                max_value=180,
                value=90,
                step=10,
            )
        else:
            max_days = 9999

    st.divider()

    # ── 분석 실행 버튼 ────────────────────────────────────────────────────────
    analyze_clicked = st.button(
        "분석 시작",
        type="primary",
        use_container_width=True,
        disabled=channel_id is None,
    )

    if analyze_clicked and channel_id:
        with st.spinner("채널 정보 가져오는 중..."):
            try:
                channel_info = get_channel_info(channel_id)
                st.session_state["channel_info"] = channel_info
            except Exception as e:
                st.error(f"채널 정보 조회 실패: {e}")
                return

        with st.spinner(f"최근 영상 {max_videos}개 수집 중... (잠시 기다려 주세요)"):
            try:
                videos = get_channel_videos(channel_id, max_results=max_videos)
                st.session_state["videos"] = videos
            except Exception as e:
                st.error(f"영상 목록 조회 실패: {e}")
                return

        with st.spinner("니치 분석 중..."):
            result = run_analysis(
                videos,
                multiplier=multiplier,
                recent_only=recent_only,
                max_days=max_days,
            )
            st.session_state["analysis_result"] = result
            st.session_state["analysis_params"] = {
                "multiplier": multiplier,
                "recent_only": recent_only,
                "max_days": max_days,
            }

        st.success(
            f"분석 완료! 총 {result['total_count']}개 영상 중 "
            f"**{result['niche_count']}개 니치 영상** 발견됨. "
            "'📊 분석결과' 탭에서 확인하세요."
        )

    # ── 채널 정보 표시 ────────────────────────────────────────────────────────
    if "channel_info" in st.session_state:
        info = st.session_state["channel_info"]
        st.divider()
        st.subheader("현재 분석 채널")
        ci_col1, ci_col2 = st.columns([1, 4])
        with ci_col1:
            if info.get("thumbnail"):
                st.image(info["thumbnail"], width=100)
        with ci_col2:
            st.write(f"**{info['title']}**")
            c1, c2, c3 = st.columns(3)
            c1.metric("구독자", f"{info['subscriber_count']:,}")
            c2.metric("총 영상", f"{info['video_count']:,}")
            c3.metric("총 조회수", f"{info['view_count']:,}")
