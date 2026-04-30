"""⚙️ 설정 탭 - 채널 입력 및 분석 파라미터 설정."""

import streamlit as st

from youtube_api import (
    extract_channel_id,
    get_channel_info,
    get_channel_videos,
    search_political_channels,
)
from analyzer import run_analysis


def _analyze_channel(channel_id: str, multiplier: float, max_videos: int, max_days: int) -> dict | None:
    """단일 채널을 분석하고 결과 dict를 반환합니다. 실패 시 None."""
    try:
        info = get_channel_info(channel_id)
    except Exception as e:
        st.error(f"채널 정보 조회 실패 ({channel_id}): {e}")
        return None

    try:
        videos = get_channel_videos(channel_id, max_results=max_videos)
    except Exception as e:
        st.error(f"영상 목록 조회 실패 ({info.get('title', channel_id)}): {e}")
        return None

    result = run_analysis(videos, multiplier=multiplier, recent_only=True, max_days=max_days)
    return {"channel_info": info, "videos": videos, "result": result}


def _score_badge(score: int) -> str:
    """점수에 따라 색상 배지 텍스트를 반환합니다."""
    if score >= 70:
        return f"🟢 {score}점"
    elif score >= 40:
        return f"🟡 {score}점"
    else:
        return f"🔴 {score}점"


def render_settings_tab():
    st.header("채널 설정")

    input_method = st.radio(
        "채널 입력 방식",
        ["직접 입력 (URL 또는 채널 ID)", "키워드로 채널 검색"],
        horizontal=True,
    )

    # ── 직접 입력 ────────────────────────────────────────────────────────────
    if input_method == "직접 입력 (URL 또는 채널 ID)":
        raw = st.text_input(
            "채널 URL 또는 채널 ID",
            placeholder="예: https://www.youtube.com/@channelname 또는 UCxxxxxxx",
        )

        channel_id = None
        if raw:
            with st.spinner("채널 ID 확인 중..."):
                channel_id = extract_channel_id(raw)
            if not channel_id:
                st.error("채널 ID를 추출할 수 없습니다. URL 또는 채널 ID를 확인해 주세요.")

        st.divider()
        _render_params()

        analyze_clicked = st.button(
            "분석 시작",
            type="primary",
            use_container_width=True,
            disabled=channel_id is None,
        )

        if analyze_clicked and channel_id:
            params = st.session_state["_params"]
            with st.spinner("채널 분석 중..."):
                data = _analyze_channel(
                    channel_id,
                    multiplier=params["multiplier"],
                    max_videos=params["max_videos"],
                    max_days=params["max_days"],
                )
            if data:
                st.session_state["multi_results"] = [data]
                st.session_state["channel_info"] = data["channel_info"]
                st.session_state["analysis_result"] = data["result"]
                st.session_state["analysis_params"] = params
                st.success(
                    f"분석 완료! 총 {data['result']['total_count']}개 영상 중 "
                    f"**{data['result']['niche_count']}개 니치 영상** 발견. "
                    "'📊 분석결과' 탭에서 확인하세요."
                )

        if "channel_info" in st.session_state:
            _render_channel_badge(st.session_state["channel_info"])

    # ── 키워드 검색 (다중 선택) ───────────────────────────────────────────────
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
            with st.spinner(f'"{keyword}" 채널 검색 및 점수 계산 중...'):
                try:
                    channels = search_political_channels(keyword, max_results=50)
                    st.session_state["search_channels"] = channels
                    for ch in channels:
                        st.session_state[f"chk_{ch['channel_id']}"] = False
                except Exception as e:
                    st.error(f"검색 오류: {e}")

        selected_ids: list[str] = []

        if "search_channels" in st.session_state:
            channels: list[dict] = st.session_state["search_channels"]
            if not channels:
                st.warning("검색 결과가 없습니다.")
            else:
                st.write(f"**검색 결과 {len(channels)}개** (우선순위 점수 순) — 분석할 채널을 선택하세요.")

                col_all, col_none = st.columns([1, 1])
                with col_all:
                    if st.button("전체 선택", use_container_width=True):
                        for ch in channels:
                            st.session_state[f"chk_{ch['channel_id']}"] = True
                        st.rerun()
                with col_none:
                    if st.button("전체 해제", use_container_width=True):
                        for ch in channels:
                            st.session_state[f"chk_{ch['channel_id']}"] = False
                        st.rerun()

                with st.container(height=420):
                    for ch in channels:
                        col_chk, col_thumb, col_info = st.columns([0.5, 1, 6])
                        with col_chk:
                            st.write("")
                            st.checkbox(label="", key=f"chk_{ch['channel_id']}")
                        with col_thumb:
                            if ch.get("thumbnail"):
                                st.image(ch["thumbnail"], width=48)
                        with col_info:
                            score = ch.get("score", 0)
                            badge = _score_badge(score)
                            subs = ch.get("subscriber_count", 0)
                            subs_str = (
                                f"{subs // 10000}만명" if subs >= 10000 else f"{subs:,}명"
                            )
                            st.write(f"**{ch['title']}** &nbsp; {badge}")
                            reasons = ch.get("score_reasons", [])
                            reason_text = " · ".join(reasons) if reasons else "정보 없음"
                            st.caption(f"구독자 {subs_str} · {reason_text}")

                selected_ids = [
                    ch["channel_id"]
                    for ch in channels
                    if st.session_state.get(f"chk_{ch['channel_id']}", False)
                ]
                st.info(f"선택된 채널: **{len(selected_ids)}개**")

        st.divider()
        _render_params()

        analyze_clicked = st.button(
            f"선택 채널 {len(selected_ids)}개 분석 시작",
            type="primary",
            use_container_width=True,
            disabled=len(selected_ids) == 0,
        )

        if analyze_clicked and selected_ids:
            params = st.session_state["_params"]
            multi_results = []
            progress = st.progress(0, text="분석 준비 중...")

            for i, cid in enumerate(selected_ids):
                ch_name = next(
                    (c["title"] for c in st.session_state.get("search_channels", []) if c["channel_id"] == cid),
                    cid,
                )
                progress.progress(
                    i / len(selected_ids),
                    text=f"분석 중: {ch_name} ({i + 1}/{len(selected_ids)})",
                )
                data = _analyze_channel(
                    cid,
                    multiplier=params["multiplier"],
                    max_videos=params["max_videos"],
                    max_days=params["max_days"],
                )
                if data:
                    multi_results.append(data)

            progress.progress(1.0, text="완료!")

            if multi_results:
                st.session_state["multi_results"] = multi_results
                st.session_state["channel_info"] = multi_results[0]["channel_info"]
                st.session_state["analysis_result"] = multi_results[0]["result"]
                st.session_state["analysis_params"] = params
                total_niche = sum(d["result"]["niche_count"] for d in multi_results)
                st.success(
                    f"**{len(multi_results)}개 채널** 분석 완료! "
                    f"총 니치 영상 **{total_niche}개** 발견. "
                    "'📊 분석결과' 탭에서 확인하세요."
                )


def _render_params():
    """공통 분석 파라미터 UI를 렌더링하고 session_state['_params']에 저장합니다."""
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
        )

    with col2:
        max_days = st.slider(
            "분석 기간",
            min_value=1,
            max_value=180,
            value=7,
            step=1,
        )
        st.caption(f"최근 **{max_days}일** 이내 영상 분석")

    st.session_state["_params"] = {
        "multiplier": multiplier,
        "max_videos": max_videos,
        "max_days": max_days,
    }


def _render_channel_badge(info: dict):
    """채널 요약 배지를 렌더링합니다."""
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
