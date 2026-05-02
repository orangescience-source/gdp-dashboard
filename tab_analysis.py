"""📊 분석결과 탭 - 니치 영상 카드 목록 및 조회수 분포 차트."""

import io
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


def _build_full_excel(multi_results: list[dict]) -> bytes:
    """전체 채널 니치 영상을 두 시트로 구성한 엑셀 파일을 생성합니다."""
    output = io.BytesIO()

    # 시트 1: 전체 니치 영상 목록 (채널명 포함)
    all_rows = []
    for d in multi_results:
        ch_title = d["channel_info"]["title"]
        df_niche = d["result"]["df_niche"]
        if not df_niche.empty:
            df_copy = df_niche[
                ["title", "view_count", "ratio", "like_count", "comment_count", "days_ago", "url"]
            ].copy()
            df_copy.insert(0, "채널명", ch_title)
            all_rows.append(df_copy)

    # 시트 2: 채널별 요약
    summary_rows = []
    for d in multi_results:
        info = d["channel_info"]
        res = d["result"]
        niche_count = res["niche_count"]
        total_count = res["total_count"]
        summary_rows.append({
            "채널명": info["title"],
            "분석 영상": total_count,
            "니치 영상": niche_count,
            "니치 비율(%)": round(niche_count / total_count * 100, 1) if total_count else 0,
            "평균 조회수": round(res["avg_views"]),
            "상태": "니치 발견" if niche_count > 0 else "니치 없음",
        })

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        if all_rows:
            pd.concat(all_rows, ignore_index=True).rename(columns={
                "title": "제목", "view_count": "조회수", "ratio": "평균대비배수",
                "like_count": "좋아요", "comment_count": "댓글", "days_ago": "경과일", "url": "URL",
            }).to_excel(writer, sheet_name="전체 니치 영상", index=False)
        pd.DataFrame(summary_rows).to_excel(writer, sheet_name="채널별 요약", index=False)

    return output.getvalue()


def _view_bar_chart(df_classified: pd.DataFrame, avg_views: float, multiplier: float) -> go.Figure:
    df = df_classified.copy().reset_index(drop=True)
    df["color"] = df["is_niche"].map({True: "니치 영상", False: "일반 영상"})
    df["short_title"] = df["title"].str[:30] + "..."

    fig = px.bar(
        df.head(50),
        x="short_title",
        y="view_count",
        color="color",
        color_discrete_map={"니치 영상": "#FF4B4B", "일반 영상": "#B0C4DE"},
        labels={"short_title": "영상 제목", "view_count": "조회수", "color": "분류"},
        title=f"최근 영상 조회수 분포 (상위 50개, 기준 배수: {multiplier}x)",
    )
    fig.add_hline(
        y=avg_views,
        line_dash="dot",
        line_color="gray",
        annotation_text=f"평균 {avg_views:,.0f}",
        annotation_position="top right",
    )
    fig.add_hline(
        y=avg_views * multiplier,
        line_dash="dash",
        line_color="#FF4B4B",
        annotation_text=f"니치 기준 {avg_views * multiplier:,.0f} ({multiplier}x)",
        annotation_position="top right",
    )
    fig.update_layout(xaxis_tickangle=-45, height=420, showlegend=True, xaxis_title="")
    return fig


def _niche_video_card(row: pd.Series):
    with st.container():
        img_col, info_col = st.columns([1, 3])
        with img_col:
            if row.get("thumbnail"):
                st.image(row["thumbnail"], use_container_width=True)
        with info_col:
            st.markdown(f"**[{row['title']}]({row['url']})**")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("조회수", f"{row['view_count']:,}")
            m2.metric("평균 대비", f"{row['ratio']:.1f}x")
            m3.metric("좋아요", f"{row.get('like_count', 0):,}")
            days = row.get("days_ago")
            m4.metric("경과일", f"{days}일 전" if days is not None else "—")
        st.divider()


def _render_single_channel(channel_info: dict, result: dict, params: dict):
    df_niche = result["df_niche"]
    df_classified = result["df_classified"]
    avg_views = result["avg_views"]
    multiplier = params.get("multiplier", 3.0)
    max_days = params.get("max_days", 7)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("분석 기간", f"최근 {max_days}일")
    c2.metric("분석 영상 수", f"{result['total_count']}개")
    c3.metric("니치 영상 수", f"{result['niche_count']}개")
    c4.metric("평균 조회수", f"{avg_views:,.0f}")

    if not df_classified.empty:
        st.subheader("조회수 분포")
        fig = _view_bar_chart(df_classified, avg_views, multiplier)
        st.plotly_chart(fig, use_container_width=True)

    st.subheader(f"니치 영상 목록 ({len(df_niche)}개, 평균 {multiplier}x 이상)")

    if df_niche.empty:
        st.warning(
            f"기준 배수 {multiplier}x를 초과하는 영상이 없습니다. "
            "기준 배수를 낮추거나 분석 기간을 늘려보세요."
        )
        return

    sort_col = st.selectbox(
        "정렬 기준",
        ["ratio", "view_count", "days_ago"],
        format_func=lambda x: {
            "ratio": "평균 대비 배수",
            "view_count": "조회수",
            "days_ago": "최신순",
        }[x],
        key=f"sort_{channel_info['channel_id']}",
    )
    ascending = sort_col == "days_ago"
    df_display = df_niche.sort_values(sort_col, ascending=ascending).reset_index(drop=True)

    for _, row in df_display.iterrows():
        _niche_video_card(row)

    st.divider()
    csv = df_display[
        ["title", "view_count", "ratio", "like_count", "comment_count", "days_ago", "url"]
    ].rename(columns={
        "title": "제목", "view_count": "조회수", "ratio": "평균대비배수",
        "like_count": "좋아요", "comment_count": "댓글", "days_ago": "경과일", "url": "URL",
    }).to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")

    st.download_button(
        label="니치 영상 목록 CSV 다운로드",
        data=csv,
        file_name=f"niche_videos_{channel_info.get('title', 'channel')}.csv",
        mime="text/csv",
        key=f"dl_{channel_info['channel_id']}",
    )


def render_analysis_tab():
    if "multi_results" not in st.session_state and "analysis_result" not in st.session_state:
        st.info("먼저 '⚙️ 채널 설정' 탭에서 채널을 선택하고 분석을 시작해주세요.", icon="👈")
        return

    params = st.session_state.get("analysis_params", {})
    multi_results: list[dict] = st.session_state.get("multi_results", [])

    # ── 단일 채널 ─────────────────────────────────────────────────────────────
    if len(multi_results) <= 1:
        channel_info = st.session_state.get("channel_info", {})
        result = st.session_state.get("analysis_result", {})
        st.header(f"📊 분석 결과 — {channel_info.get('title', '')}")
        _render_single_channel(channel_info, result, params)
        return

    # ── 다중 채널 ─────────────────────────────────────────────────────────────
    st.header(f"📊 분석 결과 — {len(multi_results)}개 채널")

    # 채널별 요약 비교표 (전체 표시, 니치 0개는 회색)
    with st.expander("채널별 요약 비교", expanded=True):
        summary_rows = []
        for d in multi_results:
            info = d["channel_info"]
            res = d["result"]
            niche_count = res["niche_count"]
            total_count = res["total_count"]
            summary_rows.append({
                "채널명": info["title"],
                "분석 영상": total_count,
                "니치 영상": niche_count,
                "니치 비율(%)": round(niche_count / total_count * 100, 1) if total_count else 0,
                "평균 조회수": f"{res['avg_views']:,.0f}",
                "상태": "✅ 니치 발견" if niche_count > 0 else "⬜ 니치 없음",
            })

        df_summary = pd.DataFrame(summary_rows)

        def _row_style(row):
            if row["니치 영상"] == 0:
                return ["color: #aaaaaa"] * len(row)
            return [""] * len(row)

        st.dataframe(
            df_summary.style.apply(_row_style, axis=1),
            use_container_width=True,
            hide_index=True,
        )

    # 니치 영상 1개 이상인 채널만 탭으로 표시
    niche_results = [d for d in multi_results if d["result"]["niche_count"] > 0]

    if not niche_results:
        st.warning(
            "분석한 채널 중 니치 영상이 발견된 채널이 없습니다. "
            "기준 배수를 낮추거나 분석 기간을 늘려보세요."
        )
        return

    # 전체 니치 영상 엑셀 다운로드
    today = datetime.now().strftime("%Y%m%d")
    excel_data = _build_full_excel(multi_results)
    st.download_button(
        label="📥 전체 니치 영상 다운로드 (Excel)",
        data=excel_data,
        file_name=f"시사콘텐츠_니치영상_전체_{today}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    excluded = len(multi_results) - len(niche_results)
    if excluded > 0:
        st.info(f"니치 영상이 없는 채널 **{excluded}개**는 탭에서 제외되었습니다. (위 표의 ⬜ 채널)")

    tab_labels = [d["channel_info"]["title"][:20] for d in niche_results]
    channel_tabs = st.tabs(tab_labels)

    for tab, data in zip(channel_tabs, niche_results):
        with tab:
            info = data["channel_info"]
            h_col1, h_col2 = st.columns([1, 6])
            with h_col1:
                if info.get("thumbnail"):
                    st.image(info["thumbnail"], width=72)
            with h_col2:
                st.write(f"**{info['title']}**")
                sub_c1, sub_c2, sub_c3 = st.columns(3)
                sub_c1.metric("구독자", f"{info['subscriber_count']:,}")
                sub_c2.metric("총 영상", f"{info['video_count']:,}")
                sub_c3.metric("총 조회수", f"{info['view_count']:,}")
            st.divider()
            _render_single_channel(info, data["result"], params)
