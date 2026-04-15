import os
import re
import streamlit as st
import anthropic

from channel_manager import get_merged_channel_db
CHANNEL_DB = get_merged_channel_db()
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
# 분량 보완 (자동 확장)
# ──────────────────────────────────────────

def _run_boswan(part: str):
    """대본 분량이 부족할 때 Claude로 해당 파트를 자동 확장한다."""
    channel_name   = st.session_state.get(P1_CHANNEL, "")
    topic_title    = st.session_state.get(P1_TOPIC_TITLE, "")
    core_message   = st.session_state.get(P1_CORE_MESSAGE, "")
    target_emotion = st.session_state.get(P1_EMOTION, "")
    video_title    = st.session_state.get(P2_TITLE, "")

    if part == "front":
        current_script = st.session_state.get(P4_SCRIPT_FRONT, "")
        key   = P4_SCRIPT_FRONT
        label = "앞부분"
    else:
        current_script = st.session_state.get(P4_SCRIPT_BACK, "")
        key   = P4_SCRIPT_BACK
        label = "뒷부분"

    if not current_script:
        st.error(f"{label} 대본이 없습니다.")
        return

    expansion_system = (
        f"[채널 페르소나]\n{_build_persona_block(channel_name)}\n\n"
        f"[확정된 영상 정보]\n"
        f"채널명: {channel_name}\n"
        f"확정 주제: {topic_title}\n"
        f"핵심 메시지: {core_message}\n"
        f"타겟 감정: {target_emotion}\n"
        f"확정 제목: {video_title}\n\n"
        f"[기존 {label} 대본]\n{current_script}\n\n"
        "# 분량 보완 지침\n"
        "위 대본을 아래 5가지 방법으로 확장하라. 기존 내용을 삭제하지 말고 풍부하게 덧붙여라.\n"
        "1. 구체적 수치·데이터·사례를 3개 이상 추가\n"
        "2. 시청자에게 말 걸기(질문·공감·호명) 대사 3줄 이상 추가\n"
        "3. 감정 전환 장면에 구체적 묘사 2단락 추가\n"
        "4. 각 STAGE 말미에 다음 내용 예고 멘트 1줄 추가\n"
        "5. 핵심 포인트마다 구체적 예시·일화 1개씩 추가\n"
        "최종 출력은 완전한 대본 텍스트만 출력하라 (JSON 불필요)."
    )
    user_message = (
        f"{label} 대본을 5가지 방법으로 확장하여 최소 5,000자 이상으로 만들어라.\n"
        "기존 구조와 흐름을 유지하면서 내용을 풍부하게 늘려라."
    )

    st.subheader(f"🔧 {label} 자동 보완 중...")
    placeholder = st.empty()
    try:
        with st.spinner(f"Claude AI가 {label} 대본을 보완하는 중... (30~60초 소요)"):
            expanded = _stream_script(expansion_system, user_message, placeholder)
        st.session_state[key] = expanded
        st.success(f"✅ {label} 보완 완료! ({len(expanded):,}자)")
        st.rerun()
    except RuntimeError as e:
        st.error(str(e))


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

    context_block = (
        f"[채널 페르소나]\n{_build_persona_block(channel_name)}\n\n"
        f"[확정된 영상 정보]\n"
        f"채널명: {channel_name}\n"
        f"확정 주제: {topic_title}\n"
        f"핵심 메시지: {core_message}\n"
        f"타겟 감정: {target_emotion}\n"
        f"확정 제목: {video_title}\n"
        f"확정 썸네일: {thumbnail_text}\n"
        f"초반 30초 Hook: {hook_30sec}\n\n"
        f"[확정된 대본 구조]\n{_structure_to_text(front_stages)}\n\n"
        f"[감정 지도 요약]\n{_emotion_map_to_text(emotion_map)}\n\n"
        f"[미니훅 위치]\n{_mini_hooks_to_text(front_hooks)}\n\n"
        f"[장면 메타]\n{_scene_meta_to_text(front_scenes)}\n\n"
        "[출력 형식 엄수]\n"
        "- 헤더(## STAGE), 타임코드([00:00]), 마크다운(*,#,-), 괄호 지문 절대 금지\n"
        "- 숫자는 모두 한글 독음으로 표기\n"
        "  예: 2025년→이천이십오 년, 10%→십 퍼센트\n"
        "- 순수 구어체 문장만 출력\n"
        "- 최소 5,000자 이상 작성\n"
        "- 분량 부족 시 즉시 보완하여 계속 작성\n"
    )
    system_prompt = context_block + PROMPT_4_FRONT_SYSTEM
    user_message = (
        f"채널: {channel_name} / 주제: {topic_title} / 제목: {video_title}\n"
        "앞부분(STAGE 1~4) 대본을 작성하라. 순수 구어체로 5,000자 이상."
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

    context_block = (
        f"[채널 페르소나]\n{_build_persona_block(channel_name)}\n\n"
        f"[확정된 영상 정보]\n"
        f"채널명: {channel_name}\n"
        f"확정 주제: {topic_title}\n"
        f"확정 제목: {video_title}\n"
        f"핵심 메시지: {core_message}\n\n"
        f"[앞부분 대본 (참고용 — 마지막 200자)]\n{front_tail}\n\n"
        f"[확정된 대본 구조 — 뒷부분]\n{_structure_to_text(back_stages)}\n\n"
        f"[미니훅 위치 — 뒷부분]\n{_mini_hooks_to_text(back_hooks)}\n\n"
        f"[장면 메타 — 뒷부분]\n{_scene_meta_to_text(back_scenes)}\n\n"
        "[출력 형식 엄수]\n"
        "- 헤더(## STAGE), 타임코드([00:00]), 마크다운(*,#,-), 괄호 지문 절대 금지\n"
        "- 숫자는 모두 한글 독음으로 표기\n"
        "  예: 2025년→이천이십오 년, 10%→십 퍼센트\n"
        "- 순수 구어체 문장만 출력\n"
        "- 최소 5,000자 이상 작성\n"
        "- 분량 부족 시 즉시 보완하여 계속 작성\n"
    )
    system_prompt = context_block + PROMPT_4_BACK_SYSTEM
    user_message = (
        f"채널: {channel_name} / 주제: {topic_title} / 제목: {video_title}\n"
        "뒷부분(STAGE 5~8) 대본을 작성하라. 순수 구어체로 5,000자 이상."
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
    if not st.session_state.get("p3_confirmed"):
        st.warning(
            "⚠️ **탭4 (대본 구조)** 에서 "
            "'확정하고 대본 작성 단계로 →' "
            "버튼을 눌러주세요."
        )
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

    # ── 결과 표시 (접힘) ──
    front_script = st.session_state.get(P4_SCRIPT_FRONT, "")
    back_script  = st.session_state.get(P4_SCRIPT_BACK, "")

    if front_script:
        with st.expander("📄 앞부분 대본 (STAGE 1~4) 보기", expanded=False):
            st.text_area(
                "",
                value=front_script,
                height=400,
                key="front_view",
                label_visibility="collapsed",
            )
            st.caption(f"글자수: {len(front_script):,}자")
        # ── 앞부분 분량 검증 ──
        front_chars = len(front_script)
        col_fv1, col_fv2 = st.columns([3, 1])
        with col_fv1:
            if front_chars >= 5000:
                st.success(f"✅ 앞부분: {front_chars:,}자 (5,000자 이상 달성)")
            else:
                st.warning(
                    f"⚠️ 앞부분: {front_chars:,}자 — 5,000자 권장 "
                    f"({5000 - front_chars:,}자 부족)"
                )
        with col_fv2:
            if front_chars < 5000:
                if st.button(
                    "🔧 앞부분 자동 보완",
                    key="btn_boswan_front",
                    use_container_width=True,
                ):
                    _run_boswan("front")

    if back_script:
        with st.expander("📄 뒷부분 대본 (STAGE 5~8) + 시각화 메모 보기", expanded=False):
            st.text_area(
                "",
                value=back_script,
                height=400,
                key="back_view",
                label_visibility="collapsed",
            )
            st.caption(f"글자수: {len(back_script):,}자")
        # ── 뒷부분 분량 검증 ──
        back_chars = len(back_script)
        col_bv1, col_bv2 = st.columns([3, 1])
        with col_bv1:
            if back_chars >= 5000:
                st.success(f"✅ 뒷부분: {back_chars:,}자 (5,000자 이상 달성)")
            else:
                st.warning(
                    f"⚠️ 뒷부분: {back_chars:,}자 — 5,000자 권장 "
                    f"({5000 - back_chars:,}자 부족)"
                )
        with col_bv2:
            if back_chars < 5000:
                if st.button(
                    "🔧 뒷부분 자동 보완",
                    key="btn_boswan_back",
                    use_container_width=True,
                ):
                    _run_boswan("back")

    if not front_script:
        return

    st.divider()

    # ── 확정 버튼 (1개로 통일) ──
    front_chars = len(front_script)
    back_chars  = len(back_script)
    total = front_chars + back_chars

    if front_script and back_script:
        # 3-col 분량 메트릭
        col_m1, col_m2, col_m3 = st.columns(3)
        with col_m1:
            st.metric(
                "앞부분 (STAGE 1~4)",
                f"{front_chars:,}자",
                delta="✅ 달성" if front_chars >= 5000 else f"{5000 - front_chars:,}자 부족",
            )
        with col_m2:
            st.metric(
                "뒷부분 (STAGE 5~8)",
                f"{back_chars:,}자",
                delta="✅ 달성" if back_chars >= 5000 else f"{5000 - back_chars:,}자 부족",
            )
        with col_m3:
            if total >= 12000:
                total_delta = "🏆 목표 초과"
            elif total >= 10000:
                total_delta = "✅ 목표 달성"
            else:
                total_delta = f"{10000 - total:,}자 부족"
            st.metric("전체 합계", f"{total:,}자", delta=total_delta)

        # 등급 + 진행 바
        if total >= 12000:
            grade = "🏆 훌륭함 (12,000자 이상)"
        elif total >= 10000:
            grade = "✅ 목표 달성 (10,000자 이상)"
        elif total >= 8000:
            grade = "⚠️ 권장 미달 (8,000~10,000자)"
        else:
            grade = "❌ 분량 부족 (8,000자 미만)"

        st.progress(min(total / 12000, 1.0), text=f"분량 등급: {grade}")

        if total < 8000:
            st.warning(
                f"⚠️ 현재 {total:,}자입니다. "
                "위 '자동 보완' 버튼으로 분량을 늘려주세요."
            )

        if st.button(
            "✅ 대본 확정하고 업로드 패키지 단계로 →",
            type="primary",
            use_container_width=True,
            key="confirm_script",
            disabled=(total < 1000),
        ):
            full = front_script + "\n\n" + back_script
            # 시각화 메모 분리 후 저장
            full_body, full_memo = _split_script_and_memo(full)
            full_with_memo = full_body
            if full_memo:
                full_with_memo += f"\n\n{_VIZ_SEPARATOR}\n{full_memo}"
            st.session_state[P4_SCRIPT_FULL] = full_with_memo
            st.session_state[P4_VIZ_MEMO]    = full_memo
            st.session_state[P4_CONFIRMED]    = True
            st.info("👆 상단에서 **📦 업로드 패키지** 탭을 클릭하세요.")
            st.rerun()

    if st.session_state.get(P4_CONFIRMED):
        saved_chars = len(st.session_state.get(P4_SCRIPT_FULL, ""))
        st.success(
            f"✅ 대본 확정 완료! ({saved_chars:,}자) "
            "**📦 업로드 패키지** 탭으로 이동하세요."
        )

        # TXT 다운로드
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
