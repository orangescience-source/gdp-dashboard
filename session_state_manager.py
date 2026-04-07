import streamlit as st

# ──────────────────────────────────────────
# session_state 키 상수 정의
# ──────────────────────────────────────────

# 프롬프트 1: 주제 발굴 결과
P1_CHANNEL       = "p1_channel"        # 선택한 채널명
P1_BENCHMARK     = "p1_benchmark"      # 벤치마킹 대상
P1_RESULT        = "p1_result"         # Claude API 전체 응답 dict
P1_TOPIC_RANK    = "p1_topic_rank"     # 선택한 주제 순위
P1_TOPIC_TITLE   = "p1_topic_title"    # 확정된 주제명
P1_CORE_MESSAGE  = "p1_core_message"   # 확정된 핵심 메시지
P1_EMOTION       = "p1_emotion"        # 확정된 타겟 감정
P1_HOOK          = "p1_hook"           # 확정된 Hook 문장

# 프롬프트 2: 썸네일·제목 전략 결과
P2_RESULT        = "p2_result"         # Claude API 전체 응답 dict
P2_THUMBNAIL     = "p2_thumbnail"      # 확정된 썸네일 문구 (말풍선+하단)
P2_TITLE         = "p2_title"          # 확정된 제목
P2_HOOK_30SEC    = "p2_hook_30sec"     # 확정된 초반 30초 Hook
P2_IMAGE_PROMPT  = "p2_image_prompt"   # 선택한 이미지 프롬프트

# 프롬프트 3: 대본 구조 설계 결과
P3_RESULT         = "p3_result"
P3_VIDEO_LENGTH   = "p3_video_length"
P3_STRUCTURE      = "p3_structure"       # 8단계 구조 전체 dict
P3_EMOTION_MAP    = "p3_emotion_map"     # 감정 지도 리스트
P3_MINI_HOOKS     = "p3_mini_hooks"      # 미니훅 4개 리스트
P3_SCENE_META     = "p3_scene_meta"      # 프롬프트 4·5 연동 메타

# 프롬프트 4: 대본 작성 결과
P4_RESULT         = "p4_result"
P4_SCRIPT_FRONT   = "p4_script_front"   # HOOK~BODY2 대본 텍스트
P4_SCRIPT_BACK    = "p4_script_back"    # BODY3~END 대본 텍스트
P4_SCRIPT_FULL    = "p4_script_full"    # 전체 합본 대본 텍스트
P4_VIZ_MEMO       = "p4_viz_memo"       # 시각화 연동 메모 (프롬프트 5용)
P4_CONFIRMED      = "p4_confirmed"      # 최종 확정 여부 bool


# ──────────────────────────────────────────
# 현재 기획 진행 상태 표시 컴포넌트
# ──────────────────────────────────────────

def render_pipeline_status():
    """
    모든 탭 상단에 공통으로 표시되는 기획 진행 상태 바.
    각 단계의 완료 여부를 시각적으로 보여준다.
    """
    p1_done = bool(st.session_state.get(P1_TOPIC_TITLE))
    p2_done = bool(st.session_state.get(P2_TITLE))
    p3_done = bool(st.session_state.get(P3_RESULT))
    p4_done = bool(st.session_state.get(P4_SCRIPT_FULL))

    def step_badge(label, done, active=False):
        if done:
            bg, color, icon = "#d4edda", "#155724", "✅"
        elif active:
            bg, color, icon = "#fff3cd", "#856404", "🔄"
        else:
            bg, color, icon = "#f8f9fa", "#6c757d", "⬜"
        return (
            f'<div style="background:{bg}; color:{color};'
            f' padding:6px 12px; border-radius:20px;'
            f' font-size:12px; font-weight:600;'
            f' display:inline-block; margin:2px;">{icon} {label}</div>'
        )

    p1_active = not p1_done
    p2_active = p1_done and not p2_done
    p3_active = p2_done and not p3_done
    p4_active = p3_done and not p4_done

    st.markdown(
        f"""
        <div style="
            background:#f8f9fa; padding:10px 16px;
            border-radius:10px; margin-bottom:16px;
            border: 1px solid #e0e0e0;
            color: #1a1a1a;
        ">
            <div style="font-size:11px; color:#888; margin-bottom:6px;">📋 기획 진행 상태</div>
            {step_badge("1. 주제 발굴", p1_done, p1_active)}
            <span style="color:#ccc; margin:0 4px;">→</span>
            {step_badge("2. 썸네일·제목", p2_done, p2_active)}
            <span style="color:#ccc; margin:0 4px;">→</span>
            {step_badge("3. 대본 구조", p3_done, p3_active)}
            <span style="color:#ccc; margin:0 4px;">→</span>
            {step_badge("4. 대본 작성", p4_done, p4_active)}
        </div>
        """,
        unsafe_allow_html=True,
    )


# ──────────────────────────────────────────
# 프롬프트 1 확정 내용 카드 (프롬프트 2, 3, 4에서 공통 사용)
# ──────────────────────────────────────────

def render_p1_confirmed_card(editable=False):
    """
    프롬프트 1에서 확정된 내용을 카드 형태로 표시한다.
    editable=True 이면 각 항목을 직접 수정할 수 있다.
    수정 내용은 즉시 session_state에 반영된다.
    """
    channel = st.session_state.get(P1_CHANNEL, "")
    topic   = st.session_state.get(P1_TOPIC_TITLE, "")
    message = st.session_state.get(P1_CORE_MESSAGE, "")
    emotion = st.session_state.get(P1_EMOTION, "")
    hook    = st.session_state.get(P1_HOOK, "")

    if not topic:
        st.warning("⚠️ 프롬프트 1(주제 발굴)을 먼저 완료해주세요.")
        return False

    with st.expander("📌 1단계 확정 내용 확인 및 수정", expanded=True):
        st.caption("아래 내용을 직접 수정하면 이후 단계에 자동 반영됩니다.")

        col1, col2 = st.columns([1, 2])
        with col1:
            st.markdown(f"**채널:** {channel}")

        if editable:
            new_topic = st.text_input(
                "확정 주제명",
                value=topic,
                key="edit_p1_topic",
            )
            new_message = st.text_area(
                "핵심 메시지",
                value=message,
                height=70,
                key="edit_p1_message",
            )
            new_emotion = st.text_input(
                "타겟 감정",
                value=emotion,
                key="edit_p1_emotion",
            )
            new_hook = st.text_area(
                "Hook 문장",
                value=hook,
                height=70,
                key="edit_p1_hook",
            )

            if st.button("✅ 수정 내용 확정", key="confirm_p1_edit", type="primary"):
                st.session_state[P1_TOPIC_TITLE]  = new_topic
                st.session_state[P1_CORE_MESSAGE] = new_message
                st.session_state[P1_EMOTION]      = new_emotion
                st.session_state[P1_HOOK]         = new_hook
                st.success("수정 내용이 저장되었습니다!")
        else:
            st.markdown(f"**주제:** {topic}")
            st.markdown(f"**핵심 메시지:** {message}")
            st.markdown(f"**타겟 감정:** {emotion}")
            if hook:
                st.info(f'🎤 Hook: "{hook}"')

    return True


# ──────────────────────────────────────────
# 프롬프트 2 확정 내용 카드 (프롬프트 3, 4에서 사용)
# ──────────────────────────────────────────

def render_p2_confirmed_card(editable=False):
    """
    프롬프트 2에서 확정된 썸네일 문구와 제목을 카드로 표시한다.
    """
    thumbnail = st.session_state.get(P2_THUMBNAIL, "")
    title     = st.session_state.get(P2_TITLE, "")
    hook_30   = st.session_state.get(P2_HOOK_30SEC, "")

    if not title:
        st.warning("⚠️ 프롬프트 2(썸네일·제목)를 먼저 완료해주세요.")
        return False

    with st.expander("📌 2단계 확정 내용 확인 및 수정", expanded=True):
        st.caption("아래 내용을 직접 수정하면 이후 단계에 자동 반영됩니다.")

        if editable:
            new_title = st.text_input(
                "확정 제목",
                value=title,
                key="edit_p2_title",
            )
            new_thumbnail = st.text_area(
                "확정 썸네일 문구",
                value=thumbnail,
                height=80,
                key="edit_p2_thumbnail",
            )
            new_hook = st.text_area(
                "초반 30초 Hook 전략",
                value=hook_30,
                height=80,
                key="edit_p2_hook",
            )

            if st.button("✅ 수정 내용 확정", key="confirm_p2_edit", type="primary"):
                st.session_state[P2_TITLE]      = new_title
                st.session_state[P2_THUMBNAIL]  = new_thumbnail
                st.session_state[P2_HOOK_30SEC] = new_hook
                st.success("수정 내용이 저장되었습니다!")
        else:
            st.markdown(f"**제목:** {title}")
            st.markdown(f"**썸네일 문구:** {thumbnail}")
            if hook_30:
                st.info(f"🎬 초반 30초: {hook_30}")

    return True

# ──────────────────────────────────────────
# P3 확정 카드
# ──────────────────────────────────────────

def render_p3_confirmed_card(editable=False):
    """
    프롬프트 3에서 확정된 대본 구조 요약을 카드로 표시한다.
    """
    structure = st.session_state.get(P3_STRUCTURE)
    if not structure:
        st.warning("⚠️ 프롬프트 3(대본 구조 설계)를 먼저 완료해주세요.")
        return False

    video_length = st.session_state.get(P3_VIDEO_LENGTH, "")
    mini_hooks = st.session_state.get(P3_MINI_HOOKS, [])
    scene_meta = st.session_state.get(P3_SCENE_META, {})
    p4_instr = scene_meta.get("prompt4_instruction", "")

    with st.expander("📌 3단계 확정 내용 — 대본 구조 설계", expanded=False):
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown(f"**영상 길이:** {video_length}")
            for key in ["hook", "body1", "body2", "body3", "body4", "reveal"]:
                sec = structure.get(key, {})
                info = sec.get("info_purpose", "")
                scene = sec.get("scene_type", "")
                if info:
                    st.caption(f"• **{key.upper()}**: {info[:60]}")
                    if scene:
                        st.caption(f"  └ 장면: {scene[:50]}")
        with col_b:
            if mini_hooks:
                st.markdown("**미니훅**")
                for mh in mini_hooks:
                    tc = mh.get("timecode", "")
                    sent = mh.get("sentence", "")
                    st.caption(f"🔥 [{tc}] {sent[:50]}")
            if p4_instr:
                st.markdown("**대본 작성 지시**")
                st.caption(p4_instr[:100])

    return True


# ──────────────────────────────────────────
# P4 확정 카드
# ──────────────────────────────────────────

def render_p4_confirmed_card(editable=False):
    """
    프롬프트 4에서 확정된 대본 요약을 카드로 표시한다.
    탭6(업로드 패키지)에서 사용한다.
    """
    script_full = st.session_state.get(P4_SCRIPT_FULL, "")
    if not script_full:
        st.warning("⚠️ 프롬프트 4(대본 작성)를 먼저 완료해주세요.")
        return False

    with st.expander("📌 4단계 확정 내용 — 대본 요약", expanded=True):
        st.caption("아래 대본이 업로드 패키지(탭6)에 자동으로 전달됩니다.")
        char_count = len(script_full)
        est_minutes = round(char_count / 500)
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("총 글자 수", f"{char_count:,}자")
        with col2:
            st.metric("예상 러닝타임", f"약 {est_minutes}분")
        with col3:
            st.metric("확정 상태",
                      "✅ 확정" if st.session_state.get(P4_CONFIRMED) else "⚠️ 미확정")

        if editable:
            new_script = st.text_area(
                "대본 전체 편집",
                value=script_full,
                height=300,
                key="p4_edit_full"
            )
            if st.button("✅ 편집 내용 확정", key="p4_confirm_edit", type="primary"):
                st.session_state[P4_SCRIPT_FULL] = new_script
                st.session_state[P4_CONFIRMED] = True
                st.success("대본이 저장되었습니다!")
        else:
            st.text_area(
                "대본 미리보기 (앞 500자)",
                value=script_full[:500] + ("..." if len(script_full) > 500 else ""),
                height=150,
                disabled=True
            )

    return True

# ──────────────────────────────────────────
# 초기화 / 리셋
# ──────────────────────────────────────────

def init_session_state():
    """
    앱 최초 실행 시 모든 session_state 키를 안전하게 초기화.
    streamlit_app.py 최상단에서 호출한다.
    """
    defaults = {
        P1_CHANNEL: "",
        P1_TOPIC_TITLE: "",
        P1_CORE_MESSAGE: "",
        P1_EMOTION: "",
        P1_HOOK: "",
        P1_RESULT: None,
        P2_RESULT: None,
        P2_THUMBNAIL: "",
        P2_TITLE: "",
        P2_HOOK_30SEC: "",
        P2_IMAGE_PROMPT: "",
        P3_RESULT: None,
        P3_VIDEO_LENGTH: "20분 내외 (10,000자)",
        P3_STRUCTURE: {},
        P3_EMOTION_MAP: [],
        P3_MINI_HOOKS: [],
        P3_SCENE_META: {},
        P4_RESULT: None,
        P4_SCRIPT_FRONT: "",
        P4_SCRIPT_BACK: "",
        P4_SCRIPT_FULL: "",
        P4_VIZ_MEMO: "",
        P4_CONFIRMED: False,
    }
    for key, default in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default


def reset_pipeline():
    """
    전체 파이프라인 초기화 (처음부터 다시 시작).
    """
    keys_to_clear = [
        P1_CHANNEL, P1_TOPIC_TITLE, P1_CORE_MESSAGE, P1_EMOTION,
        P1_HOOK, P1_RESULT,
        P2_RESULT, P2_THUMBNAIL, P2_TITLE, P2_HOOK_30SEC, P2_IMAGE_PROMPT,
        P3_RESULT, P3_STRUCTURE, P3_EMOTION_MAP, P3_MINI_HOOKS, P3_SCENE_META,
        P4_RESULT, P4_SCRIPT_FRONT, P4_SCRIPT_BACK,
        P4_SCRIPT_FULL, P4_VIZ_MEMO, P4_CONFIRMED,
    ]
    for key in keys_to_clear:
        if key in st.session_state:
            del st.session_state[key]
    st.rerun()
