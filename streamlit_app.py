import os
import json
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import anthropic

st.set_page_config(
    page_title="YouTube 니치 발굴 대시보드",
    page_icon="🎬",
    layout="wide",
)

# ── API Key 처리 ──────────────────────────────────────────────────────────────

def get_api_key() -> str:
    """st.secrets → 환경변수 → 사이드바 입력 순으로 API 키를 가져온다."""
    try:
        key = st.secrets.get("ANTHROPIC_API_KEY", "")
        if key:
            return key
    except Exception:
        pass
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    return ""

# ── 프롬프트 & Claude 호출 ────────────────────────────────────────────────────

SYSTEM_PROMPT = """당신은 유튜브 채널 전략 전문가입니다.
사용자가 제공하는 키워드를 기반으로 유망한 유튜브 니치 주제를 분석하고,
반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트는 절대 포함하지 마세요."""

JSON_SCHEMA = """{
  "niches": [
    {
      "name": "니치명 (한국어)",
      "description": "이 니치에 대한 2-3문장 설명",
      "competition": 경쟁도_숫자(1-10),
      "monetization": 수익성_숫자(1-10),
      "trend": 트렌드_숫자(1-10),
      "opportunity_score": 종합기회점수_숫자(1-10),
      "estimated_monthly_views": "예상 월 조회수 범위 (예: 5만~20만)",
      "content_ideas": ["아이디어1", "아이디어2", "아이디어3", "아이디어4", "아이디어5"],
      "target_audience": "주요 시청자층 설명",
      "pros": ["장점1", "장점2", "장점3"],
      "cons": ["단점1", "단점2"],
      "recommended_format": "쇼츠 / 롱폼 / 혼합",
      "posting_frequency": "권장 업로드 빈도 (예: 주 2-3회)"
    }
  ],
  "market_summary": "전반적인 시장 분석 요약 (3-4문장)",
  "top_recommendation": "가장 추천하는 니치명"
}"""

def build_prompt(keywords: str, n: int) -> str:
    return f"""사용자 관심 키워드: {keywords}
분석할 니치 수: {n}개

위 키워드를 바탕으로 유튜브 채널 개설에 적합한 니치 주제 {n}개를 분석해주세요.

각 항목 평가 기준:
- competition (경쟁도): 1=매우 낮음(유리), 10=매우 높음(불리)
- monetization (수익성): 1=낮음, 10=매우 높음
- trend (트렌드): 1=하락 중, 10=급성장 중
- opportunity_score (종합 기회 점수): 경쟁도 낮고, 수익성 높고, 트렌드 높을수록 높은 점수

반드시 아래 JSON 형식으로만 응답하세요:
{JSON_SCHEMA}"""


def analyze_niches(api_key: str, keywords: str, n: int) -> dict:
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_prompt(keywords, n)}],
    )
    raw = response.content[0].text.strip()
    # JSON 블록이 코드 펜스로 감싸진 경우 제거
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())

# ── 차트 헬퍼 ─────────────────────────────────────────────────────────────────

def bubble_chart(df: pd.DataFrame):
    fig = px.scatter(
        df,
        x="competition",
        y="monetization",
        size="trend",
        color="opportunity_score",
        text="name",
        color_continuous_scale="RdYlGn",
        size_max=50,
        labels={
            "competition": "경쟁도 (낮을수록 유리)",
            "monetization": "수익성 (높을수록 유리)",
            "trend": "트렌드",
            "opportunity_score": "기회 점수",
        },
        title="니치 포지셔닝 맵 — 경쟁도 vs 수익성",
    )
    fig.update_traces(textposition="top center")
    fig.update_layout(height=460, coloraxis_colorbar=dict(title="기회 점수"))
    return fig


def opportunity_bar(df: pd.DataFrame):
    df_sorted = df.sort_values("opportunity_score", ascending=True)
    fig = px.bar(
        df_sorted,
        x="opportunity_score",
        y="name",
        orientation="h",
        color="opportunity_score",
        color_continuous_scale="Blues",
        text="opportunity_score",
        labels={"opportunity_score": "종합 기회 점수", "name": ""},
        title="니치별 종합 기회 점수",
    )
    fig.update_traces(texttemplate="%{text:.1f}", textposition="outside")
    fig.update_layout(height=380, showlegend=False, coloraxis_showscale=False)
    return fig


def radar_chart(niche: dict):
    categories = ["수익성", "트렌드", "기회점수", "경쟁 낮음"]
    values = [
        niche["monetization"],
        niche["trend"],
        niche["opportunity_score"],
        10 - niche["competition"] + 1,  # 경쟁도 반전
    ]
    fig = go.Figure(
        go.Scatterpolar(
            r=values + [values[0]],
            theta=categories + [categories[0]],
            fill="toself",
            fillcolor="rgba(99,110,250,0.3)",
            line_color="rgb(99,110,250)",
        )
    )
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 10])),
        showlegend=False,
        height=280,
        margin=dict(l=40, r=40, t=40, b=40),
    )
    return fig

# ── 페이지 레이아웃 ───────────────────────────────────────────────────────────

st.title("🎬 YouTube 니치 발굴 대시보드")
st.caption("Claude AI가 분석하는 유튜브 채널 니치 주제 발굴 도구")

# ── 사이드바 ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("⚙️ 분석 설정")

    api_key = get_api_key()
    if not api_key:
        api_key = st.text_input(
            "Anthropic API Key",
            type="password",
            placeholder="sk-ant-...",
            help="Anthropic 콘솔에서 발급한 API 키를 입력하세요.",
        )

    st.divider()

    keywords = st.text_area(
        "관심 키워드",
        placeholder="예: 요리, 1인 가구, 간단 레시피\n예: 재테크, 주식, 20대\n예: 헬스, 다이어트, 홈트",
        height=120,
        help="분석하고 싶은 관심사나 주제를 자유롭게 입력하세요.",
    )

    n_niches = st.slider("발굴할 니치 수", min_value=3, max_value=8, value=5)

    run_btn = st.button("🔍 니치 발굴 시작", use_container_width=True, type="primary")

    st.divider()
    st.caption(
        "점수 기준\n"
        "- 경쟁도: 낮을수록 진입 유리 (1-10)\n"
        "- 수익성: 높을수록 수익화 쉬움 (1-10)\n"
        "- 트렌드: 높을수록 성장 중 (1-10)\n"
        "- 기회 점수: 세 지표 종합 (1-10)"
    )

# ── 메인 콘텐츠 ───────────────────────────────────────────────────────────────

if run_btn:
    if not api_key:
        st.error("API 키를 입력해주세요.")
    elif not keywords.strip():
        st.warning("관심 키워드를 입력해주세요.")
    else:
        with st.spinner("Claude AI가 니치를 분석 중입니다... (10-30초 소요)"):
            try:
                result = analyze_niches(api_key, keywords.strip(), n_niches)
                st.session_state["result"] = result
            except json.JSONDecodeError as e:
                st.error(f"응답 파싱 오류: {e}\n다시 시도해주세요.")
            except Exception as e:
                st.error(f"분석 오류: {e}")

# 결과 렌더링
if "result" in st.session_state:
    result = st.session_state["result"]
    niches = result.get("niches", [])
    top_rec = result.get("top_recommendation", "")
    market_summary = result.get("market_summary", "")

    if not niches:
        st.warning("분석 결과가 없습니다. 다시 시도해주세요.")
        st.stop()

    df = pd.DataFrame(niches)

    # ── 섹션 1: 요약 메트릭 ──────────────────────────────────────────────────
    st.header("📊 분석 요약", divider="gray")

    col1, col2, col3, col4 = st.columns(4)
    avg_comp = df["competition"].mean()
    avg_mono = df["monetization"].mean()
    avg_trend = df["trend"].mean()
    best_score = df["opportunity_score"].max()

    col1.metric("🏆 최추천 니치", top_rec)
    col2.metric("📊 평균 경쟁도", f"{avg_comp:.1f} / 10", help="낮을수록 진입 유리")
    col3.metric("💰 평균 수익성", f"{avg_mono:.1f} / 10")
    col4.metric("📈 평균 트렌드", f"{avg_trend:.1f} / 10")

    if market_summary:
        with st.expander("📝 시장 분석 요약 보기"):
            st.write(market_summary)

    st.divider()

    # ── 섹션 2: 차트 ─────────────────────────────────────────────────────────
    st.header("📈 시각화 분석", divider="gray")

    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        st.plotly_chart(bubble_chart(df), use_container_width=True)
    with chart_col2:
        st.plotly_chart(opportunity_bar(df), use_container_width=True)

    st.divider()

    # ── 섹션 3: 니치 카드 ────────────────────────────────────────────────────
    st.header("🗂️ 니치 상세 분석", divider="gray")

    for niche in sorted(niches, key=lambda x: x["opportunity_score"], reverse=True):
        badge = "⭐ 최추천" if niche["name"] == top_rec else ""
        with st.expander(f"**{niche['name']}** {badge}  —  기회 점수: {niche['opportunity_score']}/10"):

            left, right = st.columns([2, 1])

            with left:
                st.write(niche["description"])
                st.write(f"**시청자층:** {niche['target_audience']}")
                st.write(f"**예상 월 조회수:** {niche['estimated_monthly_views']}")
                st.write(f"**추천 포맷:** {niche['recommended_format']}  |  **업로드 빈도:** {niche['posting_frequency']}")

                st.write("**점수**")
                score_data = {
                    "경쟁도 (낮을수록 유리)": niche["competition"],
                    "수익성": niche["monetization"],
                    "트렌드": niche["trend"],
                    "종합 기회 점수": niche["opportunity_score"],
                }
                for label, val in score_data.items():
                    st.progress(int(val * 10), text=f"{label}: {val}/10")

            with right:
                st.plotly_chart(radar_chart(niche), use_container_width=True)

            idea_col, pro_col, con_col = st.columns(3)
            with idea_col:
                st.write("**💡 콘텐츠 아이디어**")
                for idea in niche.get("content_ideas", []):
                    st.write(f"- {idea}")
            with pro_col:
                st.write("**✅ 장점**")
                for pro in niche.get("pros", []):
                    st.write(f"- {pro}")
            with con_col:
                st.write("**⚠️ 단점**")
                for con in niche.get("cons", []):
                    st.write(f"- {con}")

else:
    # 초기 안내 화면
    st.info(
        "왼쪽 사이드바에서 API 키와 관심 키워드를 입력한 후 **'니치 발굴 시작'** 버튼을 눌러주세요.",
        icon="👈",
    )
    st.markdown(
        """
        ### 이 앱으로 할 수 있는 것
        | 기능 | 설명 |
        |------|------|
        | 🔍 키워드 기반 니치 발굴 | 관심사 키워드로 유망 유튜브 니치 발견 |
        | 📊 경쟁도 분석 | 각 니치의 진입 장벽과 경쟁 강도 평가 |
        | 💰 수익성 분석 | 광고 수익 및 수익화 가능성 평가 |
        | 📈 트렌드 분석 | 현재 성장 중인 니치 파악 |
        | 🗂️ 콘텐츠 아이디어 | 각 니치별 구체적인 영상 아이디어 제공 |
        """
    )
