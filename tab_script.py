import os
import io
import streamlit as st
import anthropic
from datetime import datetime

from channel_db import CHANNEL_DB
from prompts import PROMPT_4_SYSTEM_BASE, PROMPT_4_FRONT_SUFFIX, PROMPT_4_BACK_SUFFIX
from session_state_manager import (
    P1_CHANNEL, P1_TOPIC_TITLE, P1_CORE_MESSAGE, P1_EMOTION, P1_HOOK,
    P2_TITLE, P2_THUMBNAIL, P2_HOOK_30SEC,
    P3_RESULT, P3_VIDEO_LENGTH, P3_STRUCTURE,
    P3_EMOTION_MAP, P3_MINI_HOOKS, P3_SCENE_META,
    P4_RESULT, P4_SCRIPT_FRONT, P4_SCRIPT_BACK,
    P4_SCRIPT_FULL, P4_VIZ_MEMO, P4_CONFIRMED,
    render_pipeline_status,
    render_p1_confirmed_card,
    render_p2_confirmed_card,
    render_p3_confirmed_card,
)


# ──────────────────────────────────────────
# 클라이언트 (module-level 방지)
# ──────────────────────────────────────────

def _get_client() -> anthropic.Anthropic:
    try:
        key = st.secrets.get("ANTHROPIC_API_KEY", "")
    except Exception:
        key = ""
    key = key or os.environ.get("ANTHROPIC_API_KEY", "")
    return anthropic.Anthropic(api_key=key)


# ──────────────────────────────────────────
# 헬퍼: 채널 페르소나 블록
# ──────────────────────────────────────────

def build_persona_block(channel_name: str) -> str:
    if channel_name not in CHANNEL_DB:
        return "채널 정보 없음 — 중립적 분석가 페르소나 적용"
    info = CHANNEL_DB[channel_name]
    return (
        f"채널명: {channel_name}\n"
        f"주인공: {info['host']} ({info['host_desc']})\n"
        f"색상: {info['color_primary']} / {info['color_secondary']}\n"
        f"톤앤매너: {info['tone']}\n"
        f"타겟: {info['target']}\n"
        f"시각 무드: {info['visual_mood']}"
    )


# ──────────────────────────────────────────
# 헬퍼: 구조 메타 추출
# ──────────────────────────────────────────

def get_section(structure: dict, key: str, field: str, default: str = "") -> str:
    return str(structure.get(key, {}).get(field, default))


def get_mini_hook(mini_hooks: list, timecode: str, field: str, default: str = "") -> str:
    for mh in mini_hooks:
        if mh.get("timecode") == timecode:
            return str(mh.get(field, default))
    return default


def build_section_scene_types_str(structure: dict) -> str:
    keys = ["hook", "teaser", "big_idea", "intro",
            "body1", "body2", "body3", "body4", "reveal", "impact", "end"]
    lines = [f"- {k.upper()}: {structure.get(k, {}).get('scene_type', '')}" for k in keys]
    return "\n".join(lines)


def build_protagonist_roles_str(scene_meta: dict) -> str:
    roles = scene_meta.get("protagonist_roles", {})
    return (
        f"직접 설명: {roles.get('direct_explain_sections', '')}\n"
        f"관찰자: {roles.get('observer_sections', '')}\n"
        f"추적자: {roles.get('tracker_sections', '')}\n"
        f"미등장 가능: {roles.get('absent_sections', '')}"
    )


def build_supporting_cast_str(scene_meta: dict) -> str:
    cast = scene_meta.get("supporting_cast", [])
    lines = [f"- {c.get('name','')}: {c.get('role','')} ({c.get('emotion','')})" for c in cast]
    return "\n".join(lines) if lines else "없음"


def build_key_objects_str(scene_meta: dict) -> str:
    objs = scene_meta.get("key_visual_objects", [])
    return ", ".join(objs) if objs else "없음"


# ──────────────────────────────────────────
# 시스템 프롬프트 빌드
# ──────────────────────────────────────────

def build_system_prompt(
    channel_name, topic_title, core_message, target_emotion,
    confirmed_title, confirmed_thumbnail, hook_30sec, video_length,
    structure, scene_meta, mini_hooks, promise
) -> str:
    persona_block = build_persona_block(channel_name)
    section_types_str = build_section_scene_types_str(structure)
    protagonist_str = build_protagonist_roles_str(scene_meta)
    supporting_str = build_supporting_cast_str(scene_meta)
    key_objects_str = build_key_objects_str(scene_meta)

    hook_design = st.session_state.get(P3_RESULT, {}).get("hook_design", {})
    p1 = hook_design.get("phase1_0_20sec", {})

    return PROMPT_4_SYSTEM_BASE.format(
        persona_block=persona_block,
        channel_name=channel_name,
        topic_title=topic_title,
        core_message=core_message,
        target_emotion=target_emotion,
        confirmed_title=confirmed_title,
        confirmed_thumbnail=confirmed_thumbnail,
        hook_30sec=hook_30sec,
        video_length=video_length,
        core_promise=promise.get("core_promise", ""),
        scene_recovery=promise.get("scene_recovery", ""),
        explain_recovery=promise.get("explain_recovery", ""),
        phase1_scene=p1.get("core_scene", ""),
        phase1_sentence=p1.get("core_sentence", ""),
        section_scene_types=section_types_str,
        protagonist_roles=protagonist_str,
        supporting_cast=supporting_str,
        key_visual_objects=key_objects_str,
        consequence_sections=scene_meta.get("consequence_sections", ""),
        crowd_reaction_sections=scene_meta.get("crowd_reaction_sections", ""),
        evidence_sections=scene_meta.get("evidence_sections", ""),
        prompt4_instruction=scene_meta.get("prompt4_instruction", ""),
    )


def build_front_user_msg(structure: dict, mini_hooks: list) -> str:
    return PROMPT_4_FRONT_SUFFIX.format(
        body1_topic=get_section(structure, "body1", "core_topic"),
        body1_scene_type=get_section(structure, "body1", "scene_type"),
        body1_supporting=get_section(structure, "body1", "supporting_characters"),
        body1_key_objects=get_section(structure, "body1", "key_objects"),
        body1_consequence=get_section(structure, "body1", "consequence"),
        mini_hook1_tc=get_mini_hook(mini_hooks, "07:00", "timecode", "07:00"),
        mini_hook1_sentence=get_mini_hook(mini_hooks, "07:00", "sentence"),
        body2_topic=get_section(structure, "body2", "core_topic"),
        body2_scene_type=get_section(structure, "body2", "scene_type"),
        body2_supporting=get_section(structure, "body2", "supporting_characters"),
        body2_key_objects=get_section(structure, "body2", "key_objects"),
        body2_consequence=get_section(structure, "body2", "consequence"),
        mini_hook2_tc=get_mini_hook(mini_hooks, "10:15", "timecode", "10:15"),
        mini_hook2_sentence=get_mini_hook(mini_hooks, "10:15", "sentence"),
    )


def build_back_user_msg(structure: dict, mini_hooks: list) -> str:
    return PROMPT_4_BACK_SUFFIX.format(
        body3_topic=get_section(structure, "body3", "core_topic"),
        body3_scene_type=get_section(structure, "body3", "scene_type"),
        body3_supporting=get_section(structure, "body3", "supporting_characters"),
        body3_key_objects=get_section(structure, "body3", "key_objects"),
        body3_consequence=get_section(structure, "body3", "consequence"),
        mini_hook3_tc=get_mini_hook(mini_hooks, "13:30", "timecode", "13:30"),
        mini_hook3_sentence=get_mini_hook(mini_hooks, "13:30", "sentence"),
        body4_topic=get_section(structure, "body4", "core_topic"),
        body4_scene_type=get_section(structure, "body4", "scene_type"),
        body4_supporting=get_section(structure, "body4", "supporting_characters"),
        body4_key_objects=get_section(structure, "body4", "key_objects"),
        body4_consequence=get_section(structure, "body4", "consequence"),
        mini_hook4_tc=get_mini_hook(mini_hooks, "16:45", "timecode", "16:45"),
        mini_hook4_sentence=get_mini_hook(mini_hooks, "16:45", "sentence"),
        reveal_truth=get_section(structure, "reveal", "strongest_truth"),
        reveal_emotion=get_section(structure, "reveal", "emotion_goal"),
        reveal_scene_type=get_section(structure, "reveal", "scene_type"),
        reveal_protagonist=get_section(structure, "reveal", "protagonist_role"),
        impact_connection=get_section(structure, "impact", "life_connection"),
        impact_emotion=get_section(structure, "impact", "emotion_goal"),
        end_message=get_section(structure, "end", "final_message"),
        end_action=get_section(structure, "end", "action_suggestion"),
        end_emotion=get_section(structure, "end", "emotion_close"),
        end_protagonist=get_section(structure, "end", "protagonist_role"),
    )


# ──────────────────────────────────────────
# Claude API 호출: 스트리밍 텍스트
# ──────────────────────────────────────────

def call_claude_script(
    system_prompt: str,
    user_message: str,
    max_tokens: int = 8000,
    stream_container=None,
) -> str:
    """
    스트리밍으로 대본을 수신한다.
    stream_container가 주어지면 실시간으로 텍스트를 화면에 표시한다.
    """
    client = _get_client()
    full_text = ""
    placeholder = stream_container.empty() if stream_container else None

    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        for text in stream.text_stream:
            full_text += text
            if placeholder:
                placeholder.markdown(
                    f"<div style='font-size:13px; color:#555; "
                    f"background:#f8f9fa; padding:10px; border-radius:6px; "
                    f"max-height:200px; overflow:auto;'>{full_text[-800:]}</div>",
                    unsafe_allow_html=True,
                )

    if placeholder:
        placeholder.empty()
    return full_text


# ──────────────────────────────────────────
# 시각화 연동 메모 분리
# ──────────────────────────────────────────

def split_script_and_memo(back_text: str) -> tuple:
    separator = "## [시각화 연동 메모]"
    if separator in back_text:
        parts = back_text.split(separator, 1)
        return parts[0].strip(), (separator + parts[1]).strip()
    return back_text.strip(), ""


# ──────────────────────────────────────────
# 섹션별 대본 파싱
# ──────────────────────────────────────────

SECTION_ORDER = [
    ("hook",     "[00:00]", "🔥 HOOK",      "#E53935", 200),
    ("teaser",   "[01:00]", "📺 TEASER",    "#FB8C00", 200),
    ("big_idea", "[02:00]", "💡 BIG IDEA",  "#F9A825", 200),
    ("intro",    "[03:00]", "🎬 INTRO",     "#43A047", 200),
    ("body1",    "[04:00]", "📦 BODY 1",    "#00897B", 400),
    ("body2",    "[07:00]", "📦 BODY 2",    "#039BE5", 400),
    ("body3",    "[10:15]", "📦 BODY 3",    "#1E88E5", 400),
    ("body4",    "[13:30]", "📦 BODY 4",    "#5E35B1", 400),
    ("reveal",   "[17:00]", "💥 REVEAL",    "#8E24AA", 300),
    ("impact",   "[18:30]", "⚡ IMPACT",    "#D81B60", 150),
    ("end",      "[19:00]", "🎯 END",       "#546E7A", 200),
]


def parse_script_by_sections(full_script: str) -> dict:
    positions = []
    for key, header, *_ in SECTION_ORDER:
        idx = full_script.find(header)
        if idx != -1:
            positions.append((idx, key))

    positions.sort(key=lambda x: x[0])

    sections = {}
    for i, (pos, key) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(full_script)
        sections[key] = full_script[pos:end].strip()

    return sections


# ──────────────────────────────────────────
# 섹션별 편집 UI
# ──────────────────────────────────────────

def render_script_editor(full_script: str) -> str:
    parsed = parse_script_by_sections(full_script)
    edited_parts = []

    for key, header, emoji_label, color, height in SECTION_ORDER:
        content = parsed.get(key, "")

        st.markdown(
            f"""
            <div style="
                border-left: 5px solid {color};
                padding: 6px 14px;
                margin: 16px 0 4px 0;
                background: #fafafa;
                border-radius: 0 6px 6px 0;
            ">
                <span style="font-size:15px; font-weight:700; color:{color};">
                    {emoji_label}
                </span>
                <span style="font-size:12px; color:#888; margin-left:8px;">
                    {header}
                </span>
                <span style="font-size:11px; color:#aaa; margin-left:6px;">
                    ({len(content)}자)
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        edited = st.text_area(
            label=emoji_label,
            value=content,
            height=height,
            key=f"script_edit_{key}",
            label_visibility="collapsed",
        )
        edited_parts.append(edited)

    return "\n\n".join(edited_parts)


# ──────────────────────────────────────────
# 다운로드 파일 생성
# ──────────────────────────────────────────

def build_script_txt(
    channel_name: str,
    title: str,
    script: str,
    memo: str,
) -> bytes:
    content = (
        f"채널: {channel_name}\n"
        f"확정 제목: {title}\n"
        f"생성일시: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"{'━' * 40}\n\n"
        f"{script}\n\n"
        f"{'━' * 40}\n"
        f"{memo}\n"
    )
    return content.encode("utf-8")


# ──────────────────────────────────────────
# 메인 탭 렌더링
# ──────────────────────────────────────────

def render_script_tab():
    render_pipeline_status()

    st.header("📝 대본 작성", divider="gray")
    st.caption(
        "프롬프트 4 — 채널 페르소나 10,000자 롱폼 대본 작성기  \n"
        "확정된 구조 설계를 바탕으로 장면이 살아 있는 최종 대본을 완성합니다."
    )

    # ── 이전 단계 확정 카드 ───────────────────────────────────────────────────
    if not render_p1_confirmed_card(editable=False):
        return
    if not render_p2_confirmed_card(editable=False):
        return
    if not render_p3_confirmed_card(editable=False):
        return

    # ── 확정값 읽기 ───────────────────────────────────────────────────────────
    channel_name        = st.session_state.get(P1_CHANNEL, "")
    topic_title         = st.session_state.get(P1_TOPIC_TITLE, "")
    core_message        = st.session_state.get(P1_CORE_MESSAGE, "")
    target_emotion      = st.session_state.get(P1_EMOTION, "")
    confirmed_title     = st.session_state.get(P2_TITLE, "")
    confirmed_thumbnail = st.session_state.get(P2_THUMBNAIL, "")
    hook_30sec          = st.session_state.get(P2_HOOK_30SEC, "")
    video_length        = st.session_state.get(P3_VIDEO_LENGTH, "20분 내외 (10,000자)")
    structure           = st.session_state.get(P3_STRUCTURE, {})
    scene_meta          = st.session_state.get(P3_SCENE_META, {})
    mini_hooks          = st.session_state.get(P3_MINI_HOOKS, [])
    p3_result           = st.session_state.get(P3_RESULT, {})
    promise             = p3_result.get("thumbnail_promise", {})

    can_run = bool(channel_name and topic_title and confirmed_title
                   and confirmed_thumbnail and structure)

    if not can_run:
        st.warning("⚠️ 1~3단계를 모두 완료해야 대본 작성을 진행할 수 있습니다.")
        return

    st.divider()

    # ── 추가 요구사항 ─────────────────────────────────────────────────────────
    with st.expander("⚙️ 추가 요구사항 (선택)", expanded=False):
        extra_note = st.text_area(
            "대본 작성 시 추가로 고려할 사항",
            placeholder=(
                "예) BODY 1에서 구체적 수치 강조 / "
                "BODY 3 대조 인물을 30대 직장인으로 / "
                "전체적으로 더 공격적인 톤으로"
            ),
            height=80,
            key="p4_extra",
        )

    # ── 앞/뒤 분할 생성 버튼 ─────────────────────────────────────────────────
    front_done = bool(st.session_state.get(P4_SCRIPT_FRONT))
    col_front, col_back = st.columns(2)

    with col_front:
        front_btn = st.button(
            "✍️ 앞부분 생성 (HOOK~BODY 2)",
            type="primary",
            use_container_width=True,
            help="HOOK, TEASER, BIG IDEA, INTRO, BODY1, BODY2 — 약 5,000자",
        )

    with col_back:
        back_btn = st.button(
            "✍️ 뒷부분 생성 (BODY 3~END)",
            type="primary" if front_done else "secondary",
            use_container_width=True,
            disabled=not front_done,
            help="앞부분 생성 후 활성화 — BODY3, BODY4, REVEAL, IMPACT, END + 시각화 메모",
        )

    # ── 앞부분 생성 ───────────────────────────────────────────────────────────
    if front_btn:
        system_prompt = build_system_prompt(
            channel_name, topic_title, core_message, target_emotion,
            confirmed_title, confirmed_thumbnail, hook_30sec, video_length,
            structure, scene_meta, mini_hooks, promise,
        )
        user_msg = build_front_user_msg(structure, mini_hooks)
        extra = st.session_state.get("p4_extra", "")
        if extra.strip():
            user_msg += f"\n\n추가 요구사항: {extra}"

        st.info("Claude AI가 앞부분 대본을 스트리밍으로 작성 중입니다 (HOOK~BODY 2, 약 30~60초)...")
        stream_box = st.container()
        try:
            front_text = call_claude_script(
                system_prompt, user_msg,
                max_tokens=8000,
                stream_container=stream_box,
            )
            st.session_state[P4_SCRIPT_FRONT] = front_text
            st.session_state[P4_RESULT] = True
            st.success(f"✅ 앞부분 생성 완료! ({len(front_text):,}자) 이제 뒷부분을 생성하세요.")
            st.rerun()
        except Exception as e:
            st.error(f"생성 중 오류: {e}")

    # ── 뒷부분 생성 ───────────────────────────────────────────────────────────
    if back_btn:
        front_text = st.session_state.get(P4_SCRIPT_FRONT, "")
        system_prompt = build_system_prompt(
            channel_name, topic_title, core_message, target_emotion,
            confirmed_title, confirmed_thumbnail, hook_30sec, video_length,
            structure, scene_meta, mini_hooks, promise,
        )
        user_msg = (
            f"앞부분 대본(참고용, 연속성 유지):\n---\n{front_text[-1200:]}\n---\n\n"
            + build_back_user_msg(structure, mini_hooks)
        )
        extra = st.session_state.get("p4_extra", "")
        if extra.strip():
            user_msg += f"\n\n추가 요구사항: {extra}"

        st.info("Claude AI가 뒷부분 대본을 스트리밍으로 작성 중입니다 (BODY 3~END + 시각화 메모, 약 30~60초)...")
        stream_box = st.container()
        try:
            back_raw = call_claude_script(
                system_prompt, user_msg,
                max_tokens=8000,
                stream_container=stream_box,
            )
            back_script, viz_memo = split_script_and_memo(back_raw)
            full_script = front_text + "\n\n" + back_script

            st.session_state[P4_SCRIPT_BACK]  = back_script
            st.session_state[P4_VIZ_MEMO]     = viz_memo
            st.session_state[P4_SCRIPT_FULL]  = full_script
            st.success(f"✅ 뒷부분 생성 완료! 전체 대본 {len(full_script):,}자 완성.")
            st.rerun()
        except Exception as e:
            st.error(f"생성 중 오류: {e}")

    # ── 결과 표시 ─────────────────────────────────────────────────────────────
    front_text  = st.session_state.get(P4_SCRIPT_FRONT, "")
    full_script = st.session_state.get(P4_SCRIPT_FULL, "")
    viz_memo    = st.session_state.get(P4_VIZ_MEMO, "")

    if not front_text:
        st.info("위 버튼을 눌러 대본을 생성하세요. 앞부분 → 뒷부분 순서로 생성합니다.")
        return

    st.divider()

    # 탭: 전체 보기 / 섹션별 편집 / 시각화 메모
    tab_view, tab_edit, tab_memo = st.tabs([
        "📄 전체 대본 보기",
        "✏️ 섹션별 편집",
        "🎨 시각화 연동 메모 (프롬프트 5용)",
    ])

    # ── 전체 보기 ─────────────────────────────────────────────────────────────
    with tab_view:
        display_script = full_script if full_script else front_text

        char_count = len(display_script)
        est_min = round(char_count / 500)
        target_chars = 10000
        pct = min(100, int(char_count / target_chars * 100))

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("총 글자 수", f"{char_count:,}자")
        c2.metric("예상 러닝타임", f"약 {est_min}분")
        c3.metric("목표 대비", f"{pct}%")
        c4.metric("확정 상태",
                  "✅ 확정" if st.session_state.get(P4_CONFIRMED) else "⚠️ 미확정")

        if not full_script:
            st.warning("앞부분만 생성되었습니다. '뒷부분 생성' 버튼을 눌러 완성하세요.")

        st.text_area(
            "전체 대본 (편집은 '섹션별 편집' 탭 사용)",
            value=display_script,
            height=600,
            disabled=True,
            key="p4_full_view",
        )

    # ── 섹션별 편집 ───────────────────────────────────────────────────────────
    with tab_edit:
        if not full_script:
            st.info("전체 대본이 완성된 후 섹션별 편집이 가능합니다.")
        else:
            st.caption("각 섹션을 직접 편집한 후 '전체 대본 확정 저장' 버튼을 누르세요.")
            edited_full = render_script_editor(full_script)

            st.markdown("&nbsp;", unsafe_allow_html=True)
            if st.button(
                "✅ 전체 대본 확정 저장",
                type="primary",
                use_container_width=True,
                key="p4_confirm_save",
            ):
                st.session_state[P4_SCRIPT_FULL] = edited_full
                st.session_state[P4_CONFIRMED] = True
                st.success("✅ 대본이 확정되었습니다! '📦 업로드 패키지' 탭으로 이동하세요.")
                st.rerun()

    # ── 시각화 연동 메모 ──────────────────────────────────────────────────────
    with tab_memo:
        if not viz_memo:
            st.info("뒷부분 대본 생성이 완료되면 시각화 연동 메모가 자동으로 생성됩니다.")
        else:
            st.subheader("🎨 시각화 연동 메모 (프롬프트 5용)")
            st.caption(
                "이 메모는 프롬프트 5(스틱맨 시각화 프롬프트 생성기)에 함께 입력하면 "
                "DATA_SKETCH_SCENE 자동 감지 정확도가 높아집니다."
            )
            edited_memo = st.text_area(
                "시각화 연동 메모",
                value=viz_memo,
                height=500,
                key="viz_memo_edit",
            )
            if st.button("💾 메모 저장", key="save_viz_memo"):
                st.session_state[P4_VIZ_MEMO] = edited_memo
                st.success("시각화 메모가 저장되었습니다!")

    # ── 부분 재생성 ───────────────────────────────────────────────────────────
    st.divider()
    st.subheader("🔄 부분 재생성")
    regen_col1, regen_col2 = st.columns(2)

    with regen_col1:
        if st.button("🔄 앞부분만 재생성", use_container_width=True, key="regen_front"):
            for key in [P4_SCRIPT_FRONT, P4_SCRIPT_FULL, P4_CONFIRMED]:
                st.session_state[key] = "" if key != P4_CONFIRMED else False
            st.info("앞부분이 초기화되었습니다. 위 '앞부분 생성' 버튼을 다시 누르세요.")
            st.rerun()

    with regen_col2:
        if st.button("🔄 뒷부분만 재생성", use_container_width=True, key="regen_back"):
            for key in [P4_SCRIPT_BACK, P4_SCRIPT_FULL, P4_VIZ_MEMO]:
                st.session_state[key] = ""
            st.session_state[P4_CONFIRMED] = False
            st.info("뒷부분이 초기화되었습니다. 위 '뒷부분 생성' 버튼을 다시 누르세요.")
            st.rerun()

    # ── 내보내기 ──────────────────────────────────────────────────────────────
    st.divider()
    st.subheader("📥 다운로드")
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    export_script = full_script or front_text

    dc1, dc2 = st.columns(2)
    with dc1:
        txt_bytes = build_script_txt(
            channel_name, confirmed_title, export_script, viz_memo
        )
        st.download_button(
            "📥 대본 전체 TXT",
            data=txt_bytes,
            file_name=f"대본_{channel_name}_{ts}.txt",
            mime="text/plain; charset=utf-8",
            use_container_width=True,
        )
    with dc2:
        if viz_memo:
            memo_bytes = viz_memo.encode("utf-8")
            st.download_button(
                "📥 시각화 메모 TXT",
                data=memo_bytes,
                file_name=f"시각화메모_{channel_name}_{ts}.txt",
                mime="text/plain; charset=utf-8",
                use_container_width=True,
            )

    # ── 확정 안내 ─────────────────────────────────────────────────────────────
    st.divider()
    if st.session_state.get(P4_CONFIRMED):
        st.success(
            "✅ 대본 확정 완료!\n\n"
            "👉 다음 단계 **'📦 업로드 패키지'** 탭으로 이동하세요."
        )
    elif full_script:
        st.warning(
            "⚠️ 대본을 검토한 후 '섹션별 편집' 탭에서 "
            "'전체 대본 확정 저장' 버튼을 눌러 확정하세요."
        )
