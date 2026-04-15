import re
import json
import os
import streamlit as st
import anthropic

from channel_manager import get_merged_channel_db
CHANNEL_DB = get_merged_channel_db()
from prompts import PROMPT_3_SYSTEM
from session_state_manager import (
    P1_CHANNEL, P1_TOPIC_TITLE, P1_CORE_MESSAGE, P1_EMOTION, P1_HOOK,
    P2_TITLE, P2_THUMBNAIL, P2_HOOK_30SEC,
    P3_RESULT, P3_STRUCTURE, P3_EMOTION_MAP, P3_MINI_HOOKS, P3_SCENE_META,
    render_pipeline_status, render_p1_confirmed_card, render_p2_confirmed_card,
)


# ──────────────────────────────────────────
# API 클라이언트
# ──────────────────────────────────────────

def _get_client():
    try:
        key = st.secrets.get("ANTHROPIC_API_KEY", "")
    except Exception:
        key = ""
    key = key or os.environ.get("ANTHROPIC_API_KEY", "")
    return anthropic.Anthropic(api_key=key)


# ──────────────────────────────────────────
# JSON 파싱 3단계 방어 로직 (tab_topic.py 방식 동일)
# ──────────────────────────────────────────

def _extract_json(raw: str) -> dict:
    text = raw.strip()

    # 1단계: 마크다운 코드펜스 제거 후 파싱
    if text.startswith("```"):
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            try:
                return json.loads(part)
            except json.JSONDecodeError:
                continue

    # 2단계: 전체 텍스트 직접 파싱
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 3단계: 중괄호 균형 탐색으로 JSON 객체 추출
    start = text.find("{")
    if start == -1:
        raise json.JSONDecodeError("No JSON object found", text, 0)

    depth = 0
    end = -1
    in_string = False
    escape = False
    for i, ch in enumerate(text[start:], start):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break

    if end == -1:
        raise json.JSONDecodeError("Unbalanced braces", text, start)

    return json.loads(text[start:end + 1])


# ──────────────────────────────────────────
# 채널 페르소나 블록 생성
# ──────────────────────────────────────────

def build_persona_block(channel_name: str) -> str:
    if channel_name not in CHANNEL_DB:
        return "채널 정보 없음 — 중립적 분석가 페르소나 적용"
    info = CHANNEL_DB[channel_name]
    return (
        f"채널명: {channel_name}\n"
        f"주인공: {info['host']} ({info['host_desc']})\n"
        f"톤앤매너: {info['tone']}\n"
        f"타겟: {info['target']}\n"
        f"시각 무드: {info['visual_mood']}"
    )


# ──────────────────────────────────────────
# Claude API 호출 (3회 재시도 방어)
# ──────────────────────────────────────────

def call_claude_prompt3(
    channel_name, topic_title, core_message, target_emotion,
    video_title, thumbnail_text, hook_30sec, extra_req=""
):
    persona_block = build_persona_block(channel_name)
    system_prompt = PROMPT_3_SYSTEM.format(
        channel_name=channel_name,
        persona_block=persona_block,
        topic_title=topic_title,
        core_message=core_message,
        target_emotion=target_emotion,
        video_title=video_title,
        thumbnail_text=thumbnail_text,
        hook_30sec=hook_30sec,
    )

    user_message = (
        f"채널명: {channel_name}\n"
        f"확정 주제: {topic_title}\n"
        f"핵심 메시지: {core_message}\n"
        f"타겟 감정: {target_emotion}\n"
        f"확정 제목: {video_title}\n"
        f"확정 썸네일: {thumbnail_text}\n"
        f"초반 30초 Hook: {hook_30sec}\n"
        f"추가 요구사항: {extra_req if extra_req else '없음'}\n\n"
        "위 정보로 20분 영상 대본 구조를 설계하고 JSON만 반환하라.\n"
        "응답은 반드시 {{ 로 시작하고 }} 로 끝나야 한다."
    )

    MAX_ATTEMPTS = 3
    last_raw = ""
    last_error = None
    client = _get_client()

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=8000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            last_raw = response.content[0].text
            return _extract_json(last_raw)

        except json.JSONDecodeError as e:
            last_error = e
            if attempt < MAX_ATTEMPTS:
                user_message = (
                    f"이전 응답이 유효한 JSON이 아니었다.\n"
                    f"오류: {str(e)}\n"
                    f"이전 응답 앞부분: {last_raw[:300]}\n\n"
                    "규칙 재확인 후 올바른 JSON만 반환하라:\n"
                    "1. 응답 첫 글자는 반드시 { 이어야 한다\n"
                    "2. 마크다운 코드블록(```) 절대 사용 금지\n"
                    "3. 설명 텍스트 절대 금지\n\n"
                    f"채널명: {channel_name} / 주제: {topic_title}\n"
                    "JSON만 반환하라."
                )

        except Exception as e:
            raise RuntimeError(f"API 호출 오류: {str(e)}")

    raise ValueError(
        f"Claude API가 {MAX_ATTEMPTS}회 시도 후에도 유효한 JSON을 반환하지 못했습니다.\n"
        f"마지막 오류: {str(last_error)}\n"
        "해결 방법: 입력 내용을 더 간결하게 줄이거나 잠시 후 재시도하세요."
    )


# ──────────────────────────────────────────
# UI 컴포넌트: 감정 강도 바
# ──────────────────────────────────────────

def _emotion_bar(intensity: int) -> str:
    filled = "█" * intensity
    empty = "░" * (10 - intensity)
    if intensity >= 8:
        color = "#e74c3c"
    elif intensity >= 5:
        color = "#f39c12"
    else:
        color = "#3498db"
    return (
        f'<span style="font-family:monospace; color:{color}; font-size:13px;">'
        f'{filled}{empty}</span>'
        f'<span style="font-size:12px; color:#666; margin-left:6px;">{intensity}/10</span>'
    )


# ──────────────────────────────────────────
# UI 컴포넌트: 8단계 구조 카드
# ──────────────────────────────────────────

SECTION_COLORS = {
    "HOOK":      ("#fff3e0", "#e65100"),
    "PROBLEM":   ("#fce4ec", "#880e4f"),
    "CONTEXT":   ("#e8eaf6", "#1a237e"),
    "TWIST":     ("#f3e5f5", "#4a148c"),
    "DEEP DIVE": ("#e3f2fd", "#0d47a1"),
    "IMPLICATION": ("#e8f5e9", "#1b5e20"),
    "ACTION":    ("#fff8e1", "#f57f17"),
    "END":       ("#e0f2f1", "#004d40"),
}


def render_structure_card(stage: dict, scene: dict | None = None):
    section = stage.get("section", "")
    bg, accent = SECTION_COLORS.get(section, ("#f8f9fa", "#333"))
    ts_start = stage.get("timestamp_start", "")
    ts_end = stage.get("timestamp_end", "")
    intensity = stage.get("emotion_intensity", 5)

    key_lines_html = "".join(
        f'<li style="margin-bottom:4px;">{line}</li>'
        for line in stage.get("key_lines", [])
    )
    avoid = stage.get("avoid", "")

    scene_html = ""
    if scene:
        props = " / ".join(scene.get("key_props", []))
        scene_html = f"""
        <div style="margin-top:10px; padding:8px 12px; background:rgba(0,0,0,0.04);
                    border-radius:6px; font-size:12px; color:#444;">
            🎬 <b>장면:</b> {scene.get('visual_type','')} &nbsp;|&nbsp;
            🎨 무드: {scene.get('bg_mood','')} &nbsp;|&nbsp;
            🧩 소품: {props}<br>
            ✍️ 대본 주의: {scene.get('prompt4_note','')}<br>
            ✂️ 편집 주의: {scene.get('prompt5_note','')}
        </div>
        """

    st.markdown(
        f"""
        <div style="
            border-left: 5px solid {accent};
            background:{bg}; border-radius:10px;
            padding:16px 18px; margin-bottom:14px;
            color:#1a1a1a;
        ">
            <div style="display:flex; justify-content:space-between; align-items:center;
                        margin-bottom:10px;">
                <span style="font-size:15px; font-weight:700; color:{accent};">
                    [{ts_start}~{ts_end}] STAGE {stage.get('stage','')} · {section}
                </span>
                <span style="font-size:13px; color:#555; font-weight:600;">
                    {stage.get('title','')}
                </span>
            </div>
            <div style="font-size:13px; color:#333; margin-bottom:6px;">
                🎯 <b>목적:</b> {stage.get('purpose','')}
            </div>
            <div style="font-size:13px; color:#333; margin-bottom:6px;">
                📋 <b>내용 가이드:</b> {stage.get('content_guide','')}
            </div>
            <div style="font-size:13px; margin-bottom:8px;">
                💢 <b>감정:</b> {stage.get('emotion_target','')} &nbsp;
                {_emotion_bar(intensity)}
            </div>
            <div style="font-size:13px; color:#333; margin-bottom:4px;">
                🗣️ <b>핵심 포인트:</b>
                <ul style="margin:4px 0 0 16px; padding:0;">
                    {key_lines_html}
                </ul>
            </div>
            {"<div style='font-size:12px; color:#c0392b; margin-top:8px;'>🚫 금지: " + avoid + "</div>" if avoid else ""}
            {scene_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


# ──────────────────────────────────────────
# UI 컴포넌트: 감정 지도 타임라인
# ──────────────────────────────────────────

def render_emotion_map(emotion_map: list):
    st.subheader("💓 감정 지도 타임라인")
    st.caption("전체 영상의 감정 흐름 — 강도 변화가 시청 지속률을 결정합니다.")

    for em in emotion_map:
        intensity = em.get("intensity", 5)
        bar_width = intensity * 10
        if intensity >= 8:
            bar_color = "#e74c3c"
        elif intensity >= 5:
            bar_color = "#f39c12"
        else:
            bar_color = "#3498db"

        st.markdown(
            f"""
            <div style="display:flex; align-items:center; margin-bottom:8px; gap:10px;">
                <span style="font-size:12px; color:#555; width:45px; text-align:right;
                             font-weight:600;">{em.get('timestamp','')}</span>
                <div style="flex:1; background:#f0f0f0; border-radius:4px; height:22px;
                            position:relative;">
                    <div style="width:{bar_width}%; background:{bar_color}; height:100%;
                                border-radius:4px; transition:width 0.3s;"></div>
                    <span style="position:absolute; left:8px; top:3px; font-size:12px;
                                 color:#fff; font-weight:600; text-shadow:0 1px 2px rgba(0,0,0,0.5);">
                        {em.get('emotion','')} {intensity}/10
                    </span>
                </div>
                <span style="font-size:11px; color:#777; width:160px;">
                    {em.get('trigger','')}
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ──────────────────────────────────────────
# UI 컴포넌트: 미니훅 카드
# ──────────────────────────────────────────

TYPE_LABELS = {
    "cliffhanger": ("🎣", "#e74c3c", "#fce4ec"),
    "reveal":      ("🔓", "#9b59b6", "#f3e5f5"),
    "question":    ("❓", "#2980b9", "#e3f2fd"),
    "promise":     ("🤝", "#27ae60", "#e8f5e9"),
}


def render_mini_hooks(mini_hooks: list):
    st.subheader("🪝 미니훅 4개")
    st.caption("이탈 방지 핵심 문장 — 타임스탬프에 정확히 배치하세요.")

    cols = st.columns(2)
    for i, hook in enumerate(mini_hooks):
        hook_type = hook.get("type", "cliffhanger")
        icon, accent, bg = TYPE_LABELS.get(hook_type, ("🔗", "#555", "#f8f9fa"))
        with cols[i % 2]:
            st.markdown(
                f"""
                <div style="
                    border:2px solid {accent}; border-radius:10px;
                    padding:14px; margin-bottom:12px;
                    background:{bg}; color:#1a1a1a;
                ">
                    <div style="font-size:12px; color:{accent}; font-weight:700;
                                margin-bottom:6px;">
                        {icon} [{hook.get('timestamp','')}] {hook_type.upper()}
                    </div>
                    <div style="font-size:15px; font-weight:700; color:#111;
                                line-height:1.5; margin-bottom:8px;">
                        "{hook.get('hook_line','')}"
                    </div>
                    <div style="font-size:12px; color:#555;">
                        📌 {hook.get('purpose','')}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )


# ──────────────────────────────────────────
# 메인 탭 렌더링
# ──────────────────────────────────────────

def render_structure_tab():
    if not st.session_state.get("p2_title"):
        st.info("🎨 탭3에서 썸네일·제목을 먼저 확정해주세요.")
        st.stop()

    render_pipeline_status()

    st.header("📐 대본 구조 설계")
    st.caption(
        "확정된 주제·썸네일·제목을 바탕으로 20분 영상의 8단계 구조, "
        "감정 지도, 미니훅, 장면 메타를 설계합니다."
    )

    # ── 1·2단계 확정 내용 확인 ──
    p1_ready = render_p1_confirmed_card(editable=True)
    if not p1_ready:
        return

    p2_ready = render_p2_confirmed_card(editable=True)
    if not p2_ready:
        return

    # 세션에서 확정 값 읽기
    channel_name   = st.session_state.get(P1_CHANNEL, "")
    topic_title    = st.session_state.get(P1_TOPIC_TITLE, "")
    core_message   = st.session_state.get(P1_CORE_MESSAGE, "")
    target_emotion = st.session_state.get(P1_EMOTION, "")
    video_title    = st.session_state.get(P2_TITLE, "")
    thumbnail_text = st.session_state.get(P2_THUMBNAIL, "")
    hook_30sec     = st.session_state.get(P2_HOOK_30SEC, "")

    st.divider()

    # ── 추가 요구사항 ──
    with st.expander("⚙️ 추가 요구사항 (선택)", expanded=False):
        extra_req = st.text_area(
            "이번 대본 구조에 추가할 요구사항",
            placeholder="예) 15분 영상으로 짧게, 유머 요소 강화, 인터뷰 형식 포함",
            height=80,
            key="p3_extra",
        )

    # ── 생성 버튼 ──
    run_btn = st.button(
        "📐 대본 구조 생성",
        type="primary",
        use_container_width=True,
        disabled=not (channel_name and topic_title and video_title),
    )

    if run_btn:
        with st.spinner("Claude AI가 대본 구조를 설계하는 중... (15~25초 소요)"):
            try:
                extra = st.session_state.get("p3_extra", "")
                result = call_claude_prompt3(
                    channel_name, topic_title, core_message, target_emotion,
                    video_title, thumbnail_text, hook_30sec, extra,
                )
                st.session_state[P3_RESULT] = result
                st.success("✅ 대본 구조 설계 완료!")

            except ValueError as e:
                st.error(str(e))
                st.info("💡 팁: 추가 요구사항을 비워두고 재시도해보세요.")
                return
            except RuntimeError as e:
                st.error(f"API 오류: {str(e)}")
                return
            except Exception as e:
                st.error(f"예기치 않은 오류: {str(e)}")
                return

    result = st.session_state.get(P3_RESULT)
    if not result:
        st.info("위 버튼을 눌러 대본 구조를 생성하세요.")
        return

    st.divider()

    # ── 영상 메타 요약 ──
    meta = result.get("video_meta", {})
    overall = result.get("overall_strategy", {})

    m_col1, m_col2, m_col3, m_col4 = st.columns(4)
    m_col1.metric("⏱️ 총 길이", meta.get("total_duration", "20:00"))
    m_col2.metric("📊 목표 지속률", meta.get("target_retention", "-"))
    m_col3.metric("💓 감정 변화", f"{meta.get('emotion_change_count', 0)}회")
    m_col4.metric("🪝 미니훅", f"{meta.get('mini_hook_count', 0)}개")

    if overall.get("emotion_arc"):
        st.info(f"🎭 감정 호: {overall.get('emotion_arc','')}")

    with st.expander("📊 전략 요약", expanded=False):
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown(f"**지속률 핵심 전략:** {overall.get('retention_key','')}")
            st.markdown(f"**가장 강렬한 장면:** {overall.get('strongest_moment','')}")
        with col_b:
            st.markdown(f"**이탈 위험 구간:** {overall.get('risk_point','')}")

    st.divider()

    # ── 8단계 구조 카드 ──
    st.subheader("🗂️ 8단계 대본 구조")
    st.caption("각 섹션의 목적·내용 가이드·감정 강도를 확인하세요.")

    structure = result.get("structure", [])
    scene_meta = result.get("scene_meta", [])
    # scene_meta를 stage 번호로 인덱싱
    scene_by_stage = {s.get("stage"): s for s in scene_meta}

    for stage in structure:
        scene = scene_by_stage.get(stage.get("stage"))
        render_structure_card(stage, scene)

    st.divider()

    # ── 감정 지도 ──
    emotion_map = result.get("emotion_map", [])
    render_emotion_map(emotion_map)

    st.divider()

    # ── 미니훅 ──
    mini_hooks = result.get("mini_hooks", [])
    render_mini_hooks(mini_hooks)

    st.divider()

    # ── 대본 구조 확정 버튼 ──
    st.subheader("✅ 대본 구조 확정")
    st.caption("확정하면 다음 단계(대본 작성)에서 이 구조를 기반으로 상세 대본을 작성합니다.")

    already_confirmed = bool(st.session_state.get(P3_STRUCTURE))
    if already_confirmed:
        st.success("✅ 이미 확정된 대본 구조가 있습니다. 재확정하려면 아래 버튼을 누르세요.")

    if st.button(
        "📐 이 대본 구조로 확정",
        type="primary",
        use_container_width=True,
        key="confirm_p3",
    ):
        st.session_state[P3_STRUCTURE]   = structure
        st.session_state[P3_EMOTION_MAP] = emotion_map
        st.session_state[P3_MINI_HOOKS]  = mini_hooks
        st.session_state[P3_SCENE_META]  = scene_meta
        st.success(
            f"✅ 대본 구조 확정 완료! "
            f"8단계 구조 · 감정 지도 {len(emotion_map)}개 · 미니훅 {len(mini_hooks)}개"
        )
        st.balloons()
