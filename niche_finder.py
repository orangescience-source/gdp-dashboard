"""정치 유튜브 니치 주제 발굴 - 독립 앱."""

import streamlit as st

from tab_settings import render_settings_tab
from tab_analysis import render_analysis_tab
from tab_ai_insights import render_ai_insights_tab

st.set_page_config(
    page_title="정치 유튜브 니치 발굴기",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.title("📡 정치 유튜브 니치 발굴기")
st.caption("YouTube Data API v3 + Claude AI로 고성과 콘텐츠 패턴을 분석합니다.")

tab_set, tab_ana, tab_ai = st.tabs(
    ["⚙️ 채널 설정", "📊 분석결과", "🤖 AI 인사이트"]
)

with tab_set:
    render_settings_tab()

with tab_ana:
    render_analysis_tab()

with tab_ai:
    render_ai_insights_tab()
