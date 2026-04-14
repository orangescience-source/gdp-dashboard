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
P3_RESULT        = "p3_result"         # Claude API 전체 응답 dict
P3_STRUCTURE     = "p3_structure"      # 확정된 8단계 구조 리스트
P3_EMOTION_MAP   = "p3_emotion_map"    # 확정된 감정 지도 리스트
P3_MINI_HOOKS    = "p3_mini_hooks"     # 확정된 미니훅 4개 리스트
P3_SCENE_META    = "p3_scene_meta"     # 확정된 장면 설계 메타 리스트

# 프롬프트 4: 대본 작성 결과
P4_RESULT        = "p4_result"         # 하위 호환용 (미사용 시 빈값)
P4_SCRIPT_FRONT  = "p4_script_front"   # 앞부분 대본 (STAGE 1~4)
P4_SCRIPT_BACK   = "p4_script_back"    # 뒷부분 대본 (STAGE 5~8)
P4_SCRIPT_FULL   = "p4_script_full"    # 앞+뒤 합친 전체 대본
P4_VIZ_MEMO      = "p4_viz_memo"       # 시각화 연동 메모 (## [시각화 연동 메모] 이하)
P4_CONFIRMED     = "p4_confirmed"      # 확정 여부 (bool)

# 프롬프트 6: 업로드 패키지 결과
P6_RESULT        = "p6_result"         # Claude API 전체 응답 dict
P6_FINAL_TITLE   = "p6_final_title"    # SEO 최적화 최종 제목
P6_DESCRIPTION   = "p6_description"    # 유튜브 설명란
P6_HASHTAGS      = "p6_hashtags"       # 해시태그 목록 (list)
P6_CONFIRMED     = "p6_confirmed"      # 확정 여부 (bool)

# 프롬프트 5 (탭7): 시각화 프롬프트 결과
P5_RESULT_RAW    = "p5_result_raw"     # 스트리밍 원문 전체
P5_RESULT_SCENES = "p5_result_scenes"  # 파싱된 씬 리스트 [{"num":1,"korean":"...","prompt":"..."}]
P5_LAST_NUM      = "p5_last_num"       # 마지막으로 생성한 씬 수
P5_GENERATING    = "p5_generating"     # 생성 중 여부 (bool)

# ──────────────────────────────────────────
# 전체 파이프라인 기본값 정의
# ──────────────────────────────────────────

_DEFAULTS: dict = {
    # P1
    P1_CHANNEL:       "",
    P1_BENCHMARK:     "",
    P1_RESULT:        None,
    P1_TOPIC_RANK:    0,
    P1_TOPIC_TITLE:   "",
    P1_CORE_MESSAGE:  "",
    P1_EMOTION:       "",
    P1_HOOK:          "",
    "p1_confirmed":   False,
    # P2
    P2_RESULT:        None,
    P2_TITLE:         "",
    P2_THUMBNAIL:     "",
    P2_HOOK_30SEC:    "",
    P2_IMAGE_PROMPT:  "",
    "p2_confirmed":   False,
    # P3
    P3_RESULT:        None,
    P3_STRUCTURE:     [],
    P3_EMOTION_MAP:   [],
    P3_MINI_HOOKS:    [],
    P3_SCENE_META:    [],
    "p3_confirmed":   False,
    # P4
    P4_RESULT:        None,
    P4_SCRIPT_FRONT:  "",
    P4_SCRIPT_BACK:   "",
    P4_SCRIPT_FULL:   "",
    P4_VIZ_MEMO:      "",
    P4_CONFIRMED:     False,
    # P5
    P5_RESULT_RAW:    "",
    P5_RESULT_SCENES: [],
    P5_LAST_NUM:      1,
    P5_GENERATING:    False,
    # P6
    P6_RESULT:        None,
    P6_FINAL_TITLE:   "",
    P6_DESCRIPTION:   "",
    P6_HASHTAGS:      [],
    P6_CONFIRMED:     False,
    # YouTube 발굴
    "yt_search_results": [],
    "benchmark_input":   "",
    "benchmark_title":   "",
}


def init_session_state() -> None:
    """앱 첫 로드 시 모든 파이프라인 키를 기본값으로 초기화한다 (이미 존재하는 키는 건드리지 않는다)."""
    for key, default in _DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = default


def reset_pipeline() -> None:
    """파이프라인 전체를 초기 상태로 되돌린다 (API 키는 유지)."""
    for key, default in _DEFAULTS.items():
        st.session_state[key] = default


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
    p4_done = bool(st.session_state.get(P4_CONFIRMED))
    p6_done = bool(st.session_state.get(P6_CONFIRMED))

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
    p6_active = p4_done and not p6_done

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
            <span style="color:#ccc; margin:0 4px;">→</span>
            {step_badge("5. 업로드 패키지", p6_done, p6_active)}
        </div>
        """,
        unsafe_allow_html=True,
    )


# ──────────────────────────────────────────
# 프롬프트 1 확정 내용 카드 (프롬프트 2, 3, 4에서 공통 사용)
# ──────────────────────────────────────────

def render_p1_confirmed_card(editable=False, key_suffix=""):
    """
    프롬프트 1에서 확정된 내용을 카드 형태로 표시한다.
    editable=True 이면 각 항목을 직접 수정할 수 있다.
    key_suffix: 동일 함수를 여러 탭에서 호출 시 위젯 key 충돌 방지용 접미사.
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
                key=f"edit_p1_topic{key_suffix}",
            )
            new_message = st.text_area(
                "핵심 메시지",
                value=message,
                height=70,
                key=f"edit_p1_message{key_suffix}",
            )
            new_emotion = st.text_input(
                "타겟 감정",
                value=emotion,
                key=f"edit_p1_emotion{key_suffix}",
            )
            new_hook = st.text_area(
                "Hook 문장",
                value=hook,
                height=70,
                key=f"edit_p1_hook{key_suffix}",
            )

            if st.button("✅ 수정 내용 확정", key=f"confirm_p1_edit{key_suffix}", type="primary"):
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

def render_p2_confirmed_card(editable=False, key_suffix=""):
    """
    프롬프트 2에서 확정된 썸네일 문구와 제목을 카드로 표시한다.
    key_suffix: 동일 함수를 여러 탭에서 호출 시 위젯 key 충돌 방지용 접미사.
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
                key=f"edit_p2_title{key_suffix}",
            )
            new_thumbnail = st.text_area(
                "확정 썸네일 문구",
                value=thumbnail,
                height=80,
                key=f"edit_p2_thumbnail{key_suffix}",
            )
            new_hook = st.text_area(
                "초반 30초 Hook 전략",
                value=hook_30,
                height=80,
                key=f"edit_p2_hook{key_suffix}",
            )

            if st.button("✅ 수정 내용 확정", key=f"confirm_p2_edit{key_suffix}", type="primary"):
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
# 프롬프트 3 확정 내용 카드 (프롬프트 4에서 사용)
# ──────────────────────────────────────────

def render_p3_confirmed_card(editable=False):
    """
    프롬프트 3에서 확정된 대본 구조 요약을 카드로 표시한다.
    """
    structure = st.session_state.get(P3_STRUCTURE, [])
    emotion_map = st.session_state.get(P3_EMOTION_MAP, [])
    mini_hooks = st.session_state.get(P3_MINI_HOOKS, [])

    if not structure:
        st.warning("⚠️ 프롬프트 3(대본 구조)를 먼저 완료해주세요.")
        return False

    with st.expander("📌 3단계 확정 내용 확인", expanded=True):
        st.caption(f"8단계 구조 · 감정 지도 {len(emotion_map)}개 · 미니훅 {len(mini_hooks)}개")
        for s in structure:
            st.markdown(
                f"**[{s.get('timestamp_start','')}] {s.get('section','')}** — {s.get('title','')}"
            )

    return True


# ──────────────────────────────────────────
# 프롬프트 4 확정 내용 카드 (탭6·7에서 사용)
# ──────────────────────────────────────────

def render_p4_confirmed_card():
    """
    프롬프트 4에서 확정된 대본 요약을 카드로 표시한다.
    """
    confirmed  = st.session_state.get(P4_CONFIRMED, False)
    full_script = st.session_state.get(P4_SCRIPT_FULL, "")

    if not confirmed or not full_script:
        st.warning("⚠️ 프롬프트 4(대본 작성)를 먼저 완료해주세요.")
        return False

    char_count = len(full_script)
    with st.expander("📌 4단계 확정 내용 확인", expanded=True):
        st.caption(f"전체 대본 확정 완료 · {char_count:,}자")
        st.markdown(f"**글자 수:** {char_count:,}자")
        preview = full_script[:300].replace("\n", " ")
        st.markdown(f"**앞부분 미리보기:** {preview}...")

    return True


# ──────────────────────────────────────────
# 프롬프트 6 확정 내용 카드 (향후 탭에서 사용)
# ──────────────────────────────────────────

def render_p6_confirmed_card():
    """
    탭6에서 확정된 업로드 패키지 요약을 카드로 표시한다.
    """
    confirmed   = st.session_state.get(P6_CONFIRMED, False)
    final_title = st.session_state.get(P6_FINAL_TITLE, "")

    if not confirmed or not final_title:
        st.warning("⚠️ 탭6(업로드 패키지)를 먼저 완료해주세요.")
        return False

    hashtags = st.session_state.get(P6_HASHTAGS, [])
    with st.expander("📌 5단계 업로드 패키지 확인", expanded=True):
        st.caption(f"업로드 패키지 확정 완료 · 해시태그 {len(hashtags)}개")
        st.markdown(f"**최종 제목:** {final_title}")
        if hashtags:
            st.markdown(f"**해시태그:** {' '.join(hashtags[:5])} ...")

    return True
