import streamlit as st
from channel_manager import (
    get_all_channel_names,
    get_merged_channel_db,
    is_base_channel,
    save_channel,
    delete_channel,
    validate_channel,
    BASE_CHANNEL_NAMES,
    _load_user_channels,
)


def render_channel_manager_tab():
    st.header("⚙️ 채널 페르소나 관리")
    st.caption(
        "신규 채널 추가·기존 채널 수정·삭제. "
        "변경사항은 탭1~7 전체에 즉시 반영됩니다."
    )

    # ── 내부 메뉴 ──
    menu = st.session_state.get("ch_menu", "list")

    col_m1, col_m2, col_m3 = st.columns(3)
    with col_m1:
        if st.button(
            "📋 전체 채널 목록",
            use_container_width=True,
            type="primary" if menu == "list"
                 else "secondary"
        ):
            st.session_state["ch_menu"] = "list"
            st.rerun()
    with col_m2:
        if st.button(
            "➕ 신규 채널 추가",
            use_container_width=True,
            type="primary" if menu == "add"
                 else "secondary"
        ):
            st.session_state["ch_menu"] = "add"
            st.session_state["ch_selected"] = ""
            st.rerun()
    with col_m3:
        if st.button(
            "✏️ 기존 채널 수정",
            use_container_width=True,
            type="primary" if menu == "edit"
                 else "secondary"
        ):
            st.session_state["ch_menu"] = "edit"
            st.rerun()

    st.divider()

    if menu == "list":
        _render_list()
    elif menu == "add":
        _render_form(mode="add")
    elif menu == "edit":
        _render_edit_selector()


# ──────────────────────────────────────────
def _render_list():
    st.subheader("📋 전체 채널 목록")

    all_channels  = get_all_channel_names()
    user_modified = list(_load_user_channels().keys())
    merged_db     = get_merged_channel_db()

    for ch in all_channels:
        data = merged_db.get(ch, {})
        ok, errors = validate_channel(ch)

        col1, col2, col3, col4 = st.columns([3,2,2,1])

        with col1:
            st.markdown(f"**{ch}**")
            tone = data.get("tone", "")
            if tone:
                st.caption(tone[:30])

        with col2:
            if not is_base_channel(ch):
                st.success("🆕 사용자 추가")
            elif ch in user_modified:
                st.warning("🟡 수정됨")
            else:
                st.info("🟢 기본")

        with col3:
            if ok:
                st.success("✅ 검증 통과")
            else:
                st.error(f"⚠️ {len(errors)}개 오류")

        with col4:
            if st.button(
                "수정",
                key=f"list_edit_{ch}",
                use_container_width=True
            ):
                st.session_state["ch_menu"]     = "edit"
                st.session_state["ch_selected"] = ch
                st.rerun()

        st.divider()


# ──────────────────────────────────────────
def _render_edit_selector():
    st.subheader("✏️ 수정할 채널 선택")
    all_channels = get_all_channel_names()

    current = st.session_state.get("ch_selected", "")
    idx = (all_channels.index(current) + 1
           if current in all_channels else 0)

    selected = st.selectbox(
        "채널 선택",
        [""] + all_channels,
        index=idx,
        key="ch_edit_selector"
    )

    if selected:
        st.session_state["ch_selected"] = selected
        _render_form(mode="edit", channel_name=selected)


# ──────────────────────────────────────────
def _render_form(mode: str, channel_name: str = ""):
    is_edit = (mode == "edit" and bool(channel_name))
    is_base = is_base_channel(channel_name) if is_edit else False

    if is_edit:
        st.subheader(f"✏️ 채널 수정: {channel_name}")
        if is_base:
            st.warning(
                "⚠️ 기본 채널입니다. "
                "하단 '기본 채널 수정 허용'을 체크해야 저장됩니다."
            )
        merged = get_merged_channel_db()
        ex = merged.get(channel_name, {})
    else:
        st.subheader("➕ 신규 채널 추가")
        ex = {}

    # ── 입력 폼 ──
    tab_db, tab_visual, tab_check = st.tabs([
        "🎭 기본 정보",
        "🎨 시각화 페르소나",
        "🔍 파이프라인 검증"
    ])

    with tab_db:
        st.caption(
            "탭2~6 파이프라인에서 사용되는 채널 기본 정보"
        )

        if not is_edit:
            ch_name_input = st.text_input(
                "채널명 *",
                placeholder="예: 새로운채널",
                key="new_ch_name"
            )
        else:
            ch_name_input = channel_name
            st.info(f"채널명: **{channel_name}**")

        col_a, col_b = st.columns(2)
        with col_a:
            char_name = st.text_input(
                "주인공 이름 *",
                value=ex.get("character_name", ""),
                placeholder="예: Tae-oh",
                key=f"char_name_{mode}"
            )
            color_primary = st.color_picker(
                "주 색상 *",
                value=ex.get("color_primary", "#FF6B6B"),
                key=f"color1_{mode}"
            )
            tone = st.text_input(
                "톤앤매너 *",
                value=ex.get("tone", ""),
                placeholder="예: 독설가 (공격적 팩트 폭격)",
                key=f"tone_{mode}"
            )
            signature_hook = st.text_input(
                "시그니처 훅",
                value=ex.get("signature_hook", ""),
                placeholder="예: 당신이 모르는 사이 벌어지고 있습니다",
                key=f"sig_hook_{mode}"
            )

        with col_b:
            char_desc = st.text_area(
                "주인공 외형 *",
                value=ex.get("character_desc", ""),
                height=100,
                placeholder="예: 레드 복면, 블랙 슈트",
                key=f"char_desc_{mode}"
            )
            color_secondary = st.color_picker(
                "보조 색상",
                value=ex.get("color_secondary", "#FFFFFF"),
                key=f"color2_{mode}"
            )
            target_audience = st.text_area(
                "타겟 오디언스 *",
                value=ex.get("target_audience", ""),
                height=80,
                placeholder="예: 돈을 잃고 분노하는 투자자",
                key=f"target_{mode}"
            )
            community_tone = st.text_input(
                "커뮤니티 톤",
                value=ex.get("community_tone", ""),
                placeholder="예: 강한 경고: 위기를 모르는 분들께 공유",
                key=f"comm_tone_{mode}"
            )

        seo_raw = st.text_input(
            "SEO 키워드 (쉼표 구분)",
            value=", ".join(ex.get("seo_keywords", [])),
            placeholder="예: 경제위기, 하락장, 폭락",
            key=f"seo_{mode}"
        )

        db_data = {
            "name":           ch_name_input
                              if not is_edit else channel_name,
            "character_name": char_name,
            "character_desc": char_desc,
            "color_primary":  color_primary,
            "color_secondary":color_secondary,
            "tone":           tone,
            "target_audience":target_audience,
            "signature_hook": signature_hook,
            "community_tone": community_tone,
            "seo_keywords":   [
                k.strip() for k in seo_raw.split(",")
                if k.strip()
            ],
        }

    with tab_visual:
        st.caption(
            "탭7(시각화 프롬프트)에서 사용되는 페르소나"
        )

        char_visual = st.text_area(
            "주인공 시각 묘사 (영어) *",
            value=ex.get("character_visual", ""),
            height=80,
            placeholder=(
                "예: red mask, black suit, "
                "stickman 1:1:1 ratio, single head only"
            ),
            key=f"vis_char_{mode}"
        )
        vis_mood = st.text_area(
            "시각 무드 (영어) *",
            value=ex.get("mood", ""),
            height=60,
            placeholder=(
                "예: fear, rage, red warning, "
                "sharp numeric collision"
            ),
            key=f"vis_mood_{mode}"
        )
        vis_scene = st.text_area(
            "씬 스타일 (영어) *",
            value=ex.get("scene_style", ""),
            height=80,
            placeholder=(
                "예: dark dramatic lighting, "
                "crashing red bar charts"
            ),
            key=f"vis_scene_{mode}"
        )
        vis_bg = st.text_input(
            "채널 색상 환경 연출",
            value=ex.get("bg_color_accent", ""),
            placeholder=(
                "예: #FF6B6B environment lighting only, "
                "never on text"
            ),
            key=f"vis_bg_{mode}"
        )

        visual_data = {
            "character":      char_visual,
            "mood":           vis_mood,
            "scene_style":    vis_scene,
            "bg_color_accent":vis_bg,
            "tone":           tone,
        }

    with tab_check:
        st.caption("저장 전 파이프라인 연동 가능 여부 확인")

        final_name = (
            ch_name_input if not is_edit else channel_name
        )

        if st.button(
            "🔍 검증 실행",
            key=f"validate_{mode}",
            use_container_width=True
        ):
            if not db_data.get("tone"):
                st.error("기본 정보 탭에서 톤앤매너를 입력하세요.")
            else:
                st.success("✅ 필수 항목 모두 입력됨")
                st.markdown("**파이프라인 연동 현황:**")
                steps = [
                    ("탭2 주제 발굴",    "톤앤매너·타겟 오디언스"),
                    ("탭3 썸네일·제목",  "색상·캐릭터 외형"),
                    ("탭4 대본 구조",    "시그니처 훅·감정 설계"),
                    ("탭5 대본 작성",    "페르소나 전체"),
                    ("탭6 업로드 패키지","SEO 키워드·커뮤니티 톤"),
                    ("탭7 시각화",       "시각 무드·씬 스타일"),
                ]
                for step_name, step_data in steps:
                    st.markdown(
                        f"✅ **{step_name}** — {step_data}"
                    )

    st.divider()

    # ── 저장 버튼 (1개) ──
    override = False
    if is_base:
        override = st.checkbox(
            "⚠️ 기본 채널 수정 허용",
            value=False,
            key=f"override_{mode}"
        )

    final_name = (
        st.session_state.get("new_ch_name", "")
        if not is_edit else channel_name
    )

    if st.button(
        "✅ 저장",
        type="primary",
        use_container_width=True,
        key=f"save_{mode}"
    ):
        if not final_name.strip():
            st.error("채널명을 입력해주세요.")
        elif not db_data.get("tone","").strip():
            st.error("톤앤매너를 입력해주세요.")
        elif not db_data.get("character_name","").strip():
            st.error("주인공 이름을 입력해주세요.")
        else:
            ok, msg = save_channel(
                channel_name=final_name,
                db_data=db_data,
                visual_data=visual_data,
                override_base=override
            )
            if ok:
                st.success(msg)
                st.success(
                    "🔄 탭1~7 전체에서 즉시 사용 가능합니다!"
                )
                st.rerun()
            else:
                st.error(msg)

    # ── 삭제 (수정 모드만) ──
    if is_edit:
        st.divider()
        with st.expander(
            "🗑️ 채널 삭제 / 초기화",
            expanded=False
        ):
            if is_base:
                st.info(
                    "기본 채널은 삭제 시 "
                    "커스텀 설정만 초기화됩니다."
                )
            else:
                st.warning(
                    f"'{channel_name}'을 완전히 삭제합니다."
                )

            confirm = st.text_input(
                f"확인: 채널명 '{channel_name}' 입력",
                key=f"del_confirm_{channel_name}"
            )
            if st.button(
                "🗑️ 삭제 실행",
                type="secondary",
                disabled=(confirm != channel_name),
                key=f"del_{channel_name}",
                use_container_width=True
            ):
                ok, msg = delete_channel(channel_name)
                if ok:
                    st.success(msg)
                    st.session_state["ch_menu"] = "list"
                    st.session_state["ch_selected"] = ""
                    st.rerun()
                else:
                    st.error(msg)
