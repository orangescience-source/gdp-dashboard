import os
import re
import streamlit as st
import anthropic

from channel_db import CHANNEL_DB
from prompts import PROMPT_4_FRONT_SYSTEM, PROMPT_4_BACK_SYSTEM
from session_state_manager import (
    P1_CHANNEL, P1_TOPIC_TITLE, P1_CORE_MESSAGE, P1_EMOTION, P1_HOOK,
    P2_TITLE, P2_THUMBNAIL, P2_HOOK_30SEC,
    P3_STRUCTURE, P3_EMOTION_MAP, P3_MINI_HOOKS, P3_SCENE_META,
    P4_SCRIPT_FRONT, P4_SCRIPT_BACK, P4_SCRIPT_FULL,
    P4_VIZ_MEMO, P4_CONFIRMED,
    render_pipeline_status,
    render_p1_confirmed_card, render_p2_confirmed_card, render_p3_confirmed_card,
)

_VIZ_SEPARATOR = "## [시각화 연동 메모]"


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
# 채널 페르소나 블록
# ──────────────────────────────────────────

def _build_persona_block(channel_name: str) -> str:
    if channel_name not in CHANNEL_DB:
        return "채널 정보 없음 — 중립적 전문가 페르소나 적용"
    info = CHANNEL_DB[channel_name]
    return (
        f"채널명: {channel_name}\n"
        f"주인공: {info['host']} ({info['host_desc']})\n"
        f"톤앤매너: {info['tone']}\n"
        f"타겟: {info['target']}\n"
        f"시각 무드: {info['visual_mood']}"
    )


# ──────────────────────────────────────────
# 구조 정보 → 텍스트 변환 헬퍼
# ──────────────────────────────────────────

def _structure_to_text(stages: list) -> str:
    lines = []
    for s in stages:
        lines.append(
            f"[{s.get('timestamp_start','')}~{s.get('timestamp_end','')}] "
            f"STAGE {s.get('stage','')} {s.get('section','')} — {s.get('title','')}\n"
            f"  목적: {s.get('purpose','')}\n"
            f"  내용 가이드: {s.get('content_guide','')}\n"
            f"  감정: {s.get('emotion_target','')} ({s.get('emotion_intensity',0)}/10)\n"
            f"  핵심 포인트: {' / '.join(s.get('key_lines', []))}"
        )
    return "\n\n".join(lines)


def _emotion_map_to_text(emotion_map: list) -> str:
    return " → ".join(
        f"[{e.get('timestamp','')}]{e.get('emotion','')}{e.get('intensity',0)}"
        for e in emotion_map
    )


def _mini_hooks_to_text(mini_hooks: list) -> str:
    return "\n".join(
        f"[{h.get('timestamp','')}] {h.get('type','').upper()}: \"{h.get('hook_line','')}\""
        for h in mini_hooks
    )


def _scene_meta_to_text(scene_meta: list) -> str:
    lines = []
    for s in scene_meta:
        lines.append(
            f"STAGE {s.get('stage','')}: {s.get('visual_type','')} / "
            f"무드:{s.get('bg_mood','')} / "
            f"대본:{s.get('prompt4_note','')}"
        )
    return "\n".join(lines)


# ──────────────────────────────────────────
# 시각화 메모 분리
# ──────────────────────────────────────────

def _split_script_and_memo(text: str) -> tuple[str, str]:
    """대본 텍스트를 본문과 시각화 메모로 분리한다."""
    parts = text.split(_VIZ_SEPARATOR)
    if len(parts) == 1:
        return text.strip(), ""
    # 첫 번째 파트가 대본 본문, 나머지가 시각화 메모
    body = parts[0].strip()
    memo_parts = []
    for i, part in enumerate(parts[1:], 1):
        # 첫 줄에서 STAGE 번호 추출
        first_line = part.strip().split("\n")[0].strip()
        memo_parts.append(f"{_VIZ_SEPARATOR} {first_line}\n" + "\n".join(part.strip().split("\n")[1:]))
    return body, "\n\n".join(memo_parts)


def _extract_sections(script_text: str) -> list[dict]:
    """## [타임코드] STAGE N - SECTION_NAME 헤더로 섹션 분리."""
    pattern = re.compile(r"(^## \[\d{2}:\d{2}\] STAGE \d+.*$)", re.MULTILINE)
    matches = list(pattern.finditer(script_text))
    if not matches:
        return [{"header": "전체 대본", "body": script_text}]

    sections = []
    for i, m in enumerate(matches):
        header = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(script_text)
        body = script_text[start:end].strip()
        # 본문에서 시각화 메모 제거
        body_only = body.split(_VIZ_SEPARATOR)[0].strip()
        sections.append({"header": header, "body": body_only})
    return sections


# ──────────────────────────────────────────
# Claude 스트리밍 호출
# ──────────────────────────────────────────

def _stream_script(system_prompt: str, user_message: str, placeholder) -> str:
    """스트리밍으로 대본을 생성하고 placeholder에 실시간 표시한다."""
    client = _get_client()
    full_text = ""
    try:
        with client.messages.stream(
            model="claude-sonnet-4-6",
            max_tokens=6000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            for text_chunk in stream.text_stream:
                full_text += text_chunk
                placeholder.markdown(full_text + "▌")
        placeholder.markdown(full_text)
    except Exception as e:
        if full_text:
            placeholder.markdown(full_text)
            st.warning(f"⚠️ 스트리밍 중 오류 발생 — 지금까지 생성된 내용을 저장합니다.\n오류: {e}")
        else:
            raise RuntimeError(f"API 호출 오류: {e}")
    return full_text


# ──────────────────────────────────────────
# 앞부분 대본 생성
# ──────────────────────────────────────────

def generate_front_script(
    channel_name, topic_title, core_message, target_emotion,
    video_title, thumbnail_text, hook_30sec,
    structure, emotion_map, mini_hooks, scene_meta,
    placeholder,
) -> str:
    front_stages = [s for s in structure if s.get("stage", 0) <= 4]
    front_hooks  = [h for h in mini_hooks if h.get("stage", 0) <= 4]
    front_scenes = [s for s in scene_meta  if s.get("stage", 0) <= 4]

    system_prompt = PROMPT_4_FRONT_SYSTEM.format(
        persona_block    = _build_persona_block(channel_name),
        channel_name     = channel_name,
        topic_title      = topic_title,
        core_message     = core_message,
        target_emotion   = target_emotion,
        video_title      = video_title,
        thumbnail_text   = thumbnail_text,
        hook_30sec       = hook_30sec,
        structure_text   = _structure_to_text(front_stages),
        emotion_map_text = _emotion_map_to_text(emotion_map),
        mini_hooks_text  = _mini_hooks_to_text(front_hooks),
        scene_meta_text  = _scene_meta_to_text(front_scenes),
    )
    user_message = (
        f"채널: {channel_name} / 주제: {topic_title} / 제목: {video_title}\n"
        "앞부분(STAGE 1~4) 대본을 작성하라. 4,500자 이상."
    )
    return _stream_script(system_prompt, user_message, placeholder)


# ──────────────────────────────────────────
# 뒷부분 대본 생성
# ──────────────────────────────────────────

def generate_back_script(
    channel_name, topic_title, core_message, target_emotion,
    video_title, thumbnail_text, hook_30sec,
    structure, mini_hooks, scene_meta,
    front_script: str,
    placeholder,
) -> str:
    back_stages = [s for s in structure if s.get("stage", 0) >= 5]
    back_hooks  = [h for h in mini_hooks if h.get("stage", 0) >= 5]
    back_scenes = [s for s in scene_meta  if s.get("stage", 0) >= 5]

    # 앞부분 마지막 200자만 전달
    front_tail = front_script[-200:] if len(front_script) > 200 else front_script

    system_prompt = PROMPT_4_BACK_SYSTEM.format(
        persona_block        = _build_persona_block(channel_name),
        channel_name         = channel_name,
        topic_title          = topic_title,
        core_message         = core_message,
        target_emotion       = target_emotion,
        video_title          = video_title,
        thumbnail_text       = thumbnail_text,
        hook_30sec           = hook_30sec,
        front_tail           = front_tail,
        back_structure_text  = _structure_to_text(back_stages),
        back_mini_hooks_text = _mini_hooks_to_text(back_hooks),
        back_scene_meta_text = _scene_meta_to_text(back_scenes),
    )
    user_message = (
        f"채널: {channel_name} / 주제: {topic_title} / 제목: {video_title}\n"
        "뒷부분(STAGE 5~8) 대본을 작성하라. 4,500자 이상."
    )
    return _stream_script(system_prompt, user_message, placeholder)


# ──────────────────────────────────────────
# UI 컴포넌트: 결과 3탭 표시
# ──────────────────────────────────────────

def _render_result_tabs(front: str, back: str):
    full_script = (front + "\n\n" + back).strip() if back else front.strip()

    # 본문 / 시각화 메모 분리
    front_body, front_memo = _split_script_and_memo(front)
    back_body,  back_memo  = _split_script_and_memo(back)
    full_body  = (front_body + "\n\n" + back_body).strip()
    full_memo  = (front_memo + "\n\n" + back_memo).strip()

    char_count = len(full_body)
    st.info(
        f"📊 현재 대본 분량: **{char_count:,}자** "
        f"{'✅ 8,000자 이상 달성' if char_count >= 8000 else '⚠️ 목표 8,000자 미달'}"
    )

    tab_full, tab_edit, tab_viz = st.tabs(["📄 전체 대본", "✏️ 섹션별 편집", "🔗 시각화 메모"])

    with tab_full:
        st.text_area(
            "전체 대본 (읽기 전용 — 복사 가능)",
            value=full_body,
            height=600,
            key="script_full_view",
            disabled=True,
        )

    with tab_edit:
        st.caption("각 섹션을 개별 수정하세요. 수정 후 '✅ 전체 확정 저장' 버튼을 누르면 합쳐서 저장됩니다.")
        sections = _extract_sections(full_body)
        edited_parts = []
        for i, sec in enumerate(sections):
            with st.expander(sec["header"], expanded=False):
                edited = st.text_area(
                    "섹션 편집",
                    value=sec["body"],
                    height=200,
                    key=f"sec_edit_{i}",
                    label_visibility="collapsed",
                )
                edited_parts.append(f"{sec['header']}\n{edited}")

        # 편집 결과를 세션에 임시 저장
        if st.button("💾 편집 내용 미리 합치기", key="merge_edits"):
            merged = "\n\n".join(edited_parts)
            st.session_state["_p4_edit_merged"] = merged
            st.success(f"합치기 완료 — {len(merged):,}자")

    with tab_viz:
        if full_memo:
            st.markdown(full_memo)
        else:
            st.info("시각화 메모가 아직 생성되지 않았습니다.")

    return full_body, full_memo


# ──────────────────────────────────────────
# 메인 탭 렌더링
# ──────────────────────────────────────────

def render_script_tab():
    if not st.session_state.get("p3_structure"):
        st.info("📐 탭4에서 대본 구조를 먼저 확정해주세요.")
        st.stop()

    render_pipeline_status()

    st.header("📝 대본 작성")
    st.caption(
        "확정된 구조를 바탕으로 10,000자 이상의 롱폼 대본을 앞/뒤 분할 생성합니다. "
        "스트리밍으로 실시간 표시됩니다."
    )

    # ── 1·2·3단계 확정 내용 확인 ──
    p1_ready = render_p1_confirmed_card(editable=False)
    if not p1_ready:
        return

    p2_ready = render_p2_confirmed_card(editable=False)
    if not p2_ready:
        return

    p3_ready = render_p3_confirmed_card()
    if not p3_ready:
        return

    # 세션 값 읽기
    channel_name   = st.session_state.get(P1_CHANNEL, "")
    topic_title    = st.session_state.get(P1_TOPIC_TITLE, "")
    core_message   = st.session_state.get(P1_CORE_MESSAGE, "")
    target_emotion = st.session_state.get(P1_EMOTION, "")
    video_title    = st.session_state.get(P2_TITLE, "")
    thumbnail_text = st.session_state.get(P2_THUMBNAIL, "")
    hook_30sec     = st.session_state.get(P2_HOOK_30SEC, "")
    structure      = st.session_state.get(P3_STRUCTURE, [])
    emotion_map    = st.session_state.get(P3_EMOTION_MAP, [])
    mini_hooks     = st.session_state.get(P3_MINI_HOOKS, [])
    scene_meta     = st.session_state.get(P3_SCENE_META, [])

    can_generate = bool(channel_name and topic_title and video_title and structure)

    st.divider()

    # ── 앞/뒤 생성 버튼 행 ──
    col_front, col_back = st.columns(2)

    with col_front:
        front_btn = st.button(
            "✍️ 앞부분 생성 (STAGE 1~4)",
            type="primary",
            use_container_width=True,
            disabled=not can_generate,
            key="btn_front",
        )

    with col_back:
        front_exists = bool(st.session_state.get(P4_SCRIPT_FRONT, ""))
        back_btn = st.button(
            "✍️ 뒷부분 생성 (STAGE 5~8)",
            type="primary",
            use_container_width=True,
            disabled=not (can_generate and front_exists),
            key="btn_back",
            help="앞부분을 먼저 생성해야 활성화됩니다." if not front_exists else "",
        )

    if not front_exists and not front_btn:
        st.info("'앞부분 생성' 버튼을 눌러 대본 작성을 시작하세요.")

    # ── 앞부분 생성 ──
    if front_btn:
        if not can_generate:
            st.error("탭2(주제 발굴)와 탭4(대본 구조)를 먼저 완료해주세요.")
            return
        st.subheader("✍️ 앞부분 생성 중... (STAGE 1~4)")
        placeholder = st.empty()
        try:
            with st.spinner("Claude AI가 앞부분 대본을 작성하는 중... (30~60초 소요)"):
                front_text = generate_front_script(
                    channel_name, topic_title, core_message, target_emotion,
                    video_title, thumbnail_text, hook_30sec,
                    structure, emotion_map, mini_hooks, scene_meta,
                    placeholder,
                )
            st.session_state[P4_SCRIPT_FRONT] = front_text
            st.success(f"✅ 앞부분 완성! ({len(front_text):,}자)")
        except RuntimeError as e:
            st.error(str(e))
            return

    # ── 뒷부분 생성 ──
    if back_btn:
        front_text = st.session_state.get(P4_SCRIPT_FRONT, "")
        if not front_text:
            st.warning("⚠️ 앞부분을 먼저 생성해주세요.")
            return
        st.subheader("✍️ 뒷부분 생성 중... (STAGE 5~8)")
        placeholder = st.empty()
        try:
            with st.spinner("Claude AI가 뒷부분 대본을 작성하는 중... (30~60초 소요)"):
                back_text = generate_back_script(
                    channel_name, topic_title, core_message, target_emotion,
                    video_title, thumbnail_text, hook_30sec,
                    structure, mini_hooks, scene_meta,
                    front_text,
                    placeholder,
                )
            st.session_state[P4_SCRIPT_BACK] = back_text
            st.success(f"✅ 뒷부분 완성! ({len(back_text):,}자)")
        except RuntimeError as e:
            st.error(str(e))
            return

    # ── 결과 표시 ──
    front_script = st.session_state.get(P4_SCRIPT_FRONT, "")
    back_script  = st.session_state.get(P4_SCRIPT_BACK, "")

    if not front_script:
        return

    st.divider()
    st.subheader("📋 생성된 대본")

    full_body, full_memo = _render_result_tabs(front_script, back_script)

    st.divider()

    # ── 확정 저장 버튼 ──
    st.subheader("✅ 전체 대본 확정 저장")
    already = st.session_state.get(P4_CONFIRMED, False)
    if already:
        saved_chars = len(st.session_state.get(P4_SCRIPT_FULL, ""))
        st.success(f"✅ 이미 확정된 대본이 있습니다. ({saved_chars:,}자) 재확정하려면 아래 버튼을 누르세요.")

    col_confirm, col_dl = st.columns([2, 1])

    with col_confirm:
        if st.button(
            "✅ 전체 대본 확정 저장",
            type="primary",
            use_container_width=True,
            key="confirm_script",
            disabled=not back_script,
        ):
            # 편집 탭에서 합친 내용이 있으면 우선 적용
            merged = st.session_state.pop("_p4_edit_merged", None)
            final_body = merged if merged else full_body
            full_script = final_body
            if full_memo:
                full_script += f"\n\n{_VIZ_SEPARATOR}\n{full_memo}"

            st.session_state[P4_SCRIPT_FULL] = full_script
            st.session_state[P4_VIZ_MEMO]    = full_memo
            st.session_state[P4_CONFIRMED]    = True
            char_count = len(final_body)
            st.success(
                f"✅ 대본 확정 완료! {char_count:,}자 "
                f"{'— 목표 달성!' if char_count >= 8000 else '(8,000자 미달 — 재생성 권장)'}"
            )
            if char_count >= 8000:
                st.balloons()

    with col_dl:
        # TXT 다운로드 (앞+뒤 합본)
        dl_text = front_script
        if back_script:
            dl_text += "\n\n" + back_script
        st.download_button(
            label="📥 전체 대본 TXT 다운로드",
            data=dl_text.encode("utf-8"),
            file_name=f"script_{topic_title[:20]}.txt",
            mime="text/plain",
            use_container_width=True,
            key="dl_script_txt",
        )
        st.caption("앞부분 + 뒷부분 + 시각화 메모 포함")
