import os
import re
from datetime import datetime
import streamlit as st
import anthropic

from channel_manager import get_merged_channel_db
from prompts import PROMPT_4_FRONT_SYSTEM, PROMPT_4_BACK_SYSTEM
from session_state_manager import (
    P1_CHANNEL, P1_TOPIC_TITLE, P1_CORE_MESSAGE, P1_EMOTION,
    P2_TITLE, P2_THUMBNAIL, P2_HOOK_30SEC,
    P3_STRUCTURE, P3_MINI_HOOKS,
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
# 채널 페르소나 블록 (old/new schema 모두 지원)
# ──────────────────────────────────────────

def _build_persona_block(channel_name: str) -> str:
    db = get_merged_channel_db()
    if channel_name not in db:
        return "채널 정보 없음 — 중립적 분석가 페르소나 적용"
    info = db[channel_name]
    # 신규 스키마(character_name) 우선, 구 스키마(host) fallback
    char_name = info.get("character_name") or info.get("host", "")
    char_desc = info.get("character_desc") or info.get("host_desc", "")
    target    = info.get("target_audience") or info.get("target", "")
    return (
        f"채널명: {channel_name}\n"
        f"주인공: {char_name} ({char_desc})\n"
        f"색상: {info.get('color_primary', '')} / {info.get('color_secondary', '')}\n"
        f"톤앤매너: {info.get('tone', '')}\n"
        f"타겟: {target}\n"
        f"시그니처 훅: {info.get('signature_hook', '')}"
    )


# ──────────────────────────────────────────
# 파이프라인 컨텍스트 추출
# ──────────────────────────────────────────

def _build_context(session) -> dict:
    """세션에서 파이프라인 컨텍스트 추출. p3_structure 리스트 기반."""
    structure  = session.get("p3_structure", [])
    mini_hooks = session.get("p3_mini_hooks", [])

    def get_stage(stage_num: int) -> dict:
        if isinstance(structure, list):
            for s in structure:
                if s.get("stage") == stage_num:
                    return s
        return {}

    def mh(tc: str) -> str:
        for m in mini_hooks:
            if m.get("timestamp") == tc:
                return str(m.get("hook_line", ""))
        return ""

    s2 = get_stage(2)   # PROBLEM  → BODY 1
    s3 = get_stage(3)   # CONTEXT  → BODY 2
    s5 = get_stage(5)   # DEEP DIVE→ BODY 3
    s6 = get_stage(6)   # IMPLICATION → BODY 4
    s7 = get_stage(7)   # ACTION   → REVEAL / IMPACT
    s8 = get_stage(8)   # END

    return {
        "channel_name":        session.get("p1_channel", ""),
        "topic_title":         session.get("p1_topic_title", ""),
        "core_message":        session.get("p1_core_message", ""),
        "target_emotion":      session.get("p1_emotion", ""),
        "confirmed_title":     session.get("p2_title", ""),
        "confirmed_thumbnail": session.get("p2_thumbnail", ""),
        "hook_30sec":          session.get("p2_hook_30sec", ""),
        "body1_topic":         s2.get("content_guide") or s2.get("title", ""),
        "body2_topic":         s3.get("content_guide") or s3.get("title", ""),
        "body3_topic":         s5.get("content_guide") or s5.get("title", ""),
        "body4_topic":         s6.get("content_guide") or s6.get("title", ""),
        "reveal_truth":        s7.get("content_guide") or s7.get("title", ""),
        "reveal_emotion":      s7.get("emotion_target", ""),
        "impact_connection":   s8.get("purpose", ""),
        "end_message":         s8.get("content_guide") or s8.get("title", ""),
        "end_action":          (s8.get("key_lines") or [""])[0],
        "mini_hook1_sentence": mh("07:00"),
        "mini_hook2_sentence": mh("10:15"),
        "mini_hook3_sentence": mh("13:30"),
    }


# ──────────────────────────────────────────
# 시각화 메모 분리
# ──────────────────────────────────────────

def _split_viz_memo(back_text: str) -> tuple:
    """뒷부분에서 ## [시각화 연동 메모] 구분자를 기준으로 분리."""
    if _VIZ_SEPARATOR in back_text:
        parts = back_text.split(_VIZ_SEPARATOR, 1)
        return parts[0].strip(), (_VIZ_SEPARATOR + parts[1]).strip()
    return back_text.strip(), ""


# ──────────────────────────────────────────
# TTS 글자 수 측정 (헤더/타임코드 제거 후)
# ──────────────────────────────────────────

def _measure_tts(text: str) -> int:
    """순수 TTS 글자 수 측정. 헤더·타임코드·마크다운 제거 후 계산."""
    t = re.sub(r"##\s*\[시각화 연동 메모\].*", "", text, flags=re.DOTALL)
    t = re.sub(r"##\s*\[[\d:]+\].*?\n", "\n", t)
    t = re.sub(r"^\s*\[[\d:]+\].*?\n", "\n", t, flags=re.MULTILINE)
    t = re.sub(r"\[장면[^\]]*\][^\n]*\n", "\n", t)
    t = re.sub(r"[*#>-]\s", "", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return len(t.strip())


# ──────────────────────────────────────────
# 한글 독음 숫자 → 아라비아 숫자 복원
# (이미지 프롬프트용 — tab_visualization에서 import)
# ──────────────────────────────────────────

def _restore_numbers(text: str) -> str:
    """TTS용 한글 독음 숫자를 이미지 프롬프트용 아라비아 숫자로 복원."""
    replacements = [
        # 연도 (긴 것 먼저)
        ("이천이십오 년", "2025년"), ("이천이십오년", "2025년"),
        ("이천이십사 년", "2024년"), ("이천이십사년", "2024년"),
        ("이천이십삼 년", "2023년"),
        ("이천이십이 년", "2022년"),
        ("이천이십일 년", "2021년"),
        ("이천이십 년",  "2020년"),
        ("이천십구 년",  "2019년"),
        ("이천십팔 년",  "2018년"),
        ("이천십칠 년",  "2017년"),
        ("이천십육 년",  "2016년"),
        ("이천십오 년",  "2015년"),
        ("이천십 년",    "2010년"),
        ("이천 년",      "2000년"),
        ("천구백구십팔 년", "1998년"),
        ("천구백구십칠 년", "1997년"),
        ("천구백구십 년",   "1990년"),
        ("천구백팔십 년",   "1980년"),
        ("천구백칠십 년",   "1970년"),
        ("천구백육십 년",   "1960년"),
        ("천구백오십 년",   "1950년"),
        ("천구백 년",       "1900년"),
        # 퍼센트 (소수점 먼저)
        ("삼 점 오 퍼센트", "3.5%"),
        ("오 점 오 퍼센트", "5.5%"),
        ("육 점 오 퍼센트", "6.5%"),
        ("영 점 오 퍼센트", "0.5%"),
        ("일 점 오 퍼센트", "1.5%"),
        ("이 점 오 퍼센트", "2.5%"),
        ("백 퍼센트",       "100%"),
        ("구십오 퍼센트",   "95%"),
        ("구십 퍼센트",     "90%"),
        ("팔십 퍼센트",     "80%"),
        ("칠십 퍼센트",     "70%"),
        ("육십 퍼센트",     "60%"),
        ("오십 퍼센트",     "50%"),
        ("사십오 퍼센트",   "45%"),
        ("사십 퍼센트",     "40%"),
        ("삼십오 퍼센트",   "35%"),
        ("삼십 퍼센트",     "30%"),
        ("이십오 퍼센트",   "25%"),
        ("이십 퍼센트",     "20%"),
        ("십오 퍼센트",     "15%"),
        ("십이 퍼센트",     "12%"),
        ("십 퍼센트",       "10%"),
        ("오 퍼센트",       "5%"),
        ("삼 퍼센트",       "3%"),
        ("일 퍼센트",       "1%"),
        # 단위 (큰 단위 먼저)
        ("오백조 원",    "500조 원"),
        ("삼십칠조 원",  "37조 원"),
        ("삼십조 원",    "30조 원"),
        ("이십조 원",    "20조 원"),
        ("십조 원",      "10조 원"),
        ("오조 원",      "5조 원"),
        ("삼조 원",      "3조 원"),
        ("이조 원",      "2조 원"),
        ("일조 원",      "1조 원"),
        ("오천만 명",    "5,000만 명"),
        ("천만 명",      "1,000만 명"),
        ("오백만 명",    "500만 명"),
        ("백만 명",      "100만 명"),
        ("오십만 명",    "50만 명"),
        ("이십만 명",    "20만 명"),
        ("십만 명",      "10만 명"),
        ("오만 명",      "5만 명"),
        ("일만 명",      "1만 명"),
        ("이백사십삼만", "243만"),
        ("천이백만",     "1,200만"),
        ("천 명",        "1,000명"),
        ("오백 명",      "500명"),
        ("열 명",        "10명"),
        ("아홉 명",      "9명"),
        ("여덟 명",      "8명"),
        ("일곱 명",      "7명"),
        ("여섯 명",      "6명"),
        ("다섯 명",      "5명"),
        ("네 명",        "4명"),
        ("세 명",        "3명"),
        ("두 명",        "2명"),
        ("한 명",        "1명"),
        # 배수
        ("열 배",   "10배"),
        ("다섯 배", "5배"),
        ("네 배",   "4배"),
        ("세 배",   "3배"),
        ("두 배",   "2배"),
        # 나이
        ("육십오 세", "65세"),
        ("육십 세",   "60세"),
        ("오십 세",   "50세"),
        ("사십 세",   "40세"),
        ("삼십 세",   "30세"),
        ("이십 세",   "20세"),
    ]
    for kor, num in replacements:
        text = text.replace(kor, num)
    return text


# ──────────────────────────────────────────
# 메인 탭 렌더링
# ──────────────────────────────────────────

def render_script_tab():
    render_pipeline_status()

    st.header("📝 대본 작성")
    st.caption(
        "프롬프트 4 — 헤더·타임코드 없는 순수 TTS 대본 작성기\n"
        "확정된 구조 설계를 바탕으로 TTS에 바로 입력 가능한 대본을 완성합니다."
    )

    # ── 이전 단계 확인 ──
    if not render_p1_confirmed_card(editable=False):
        return
    if not render_p2_confirmed_card(editable=False):
        return
    if not render_p3_confirmed_card():
        return

    session = st.session_state
    ctx     = _build_context(session)
    persona = _build_persona_block(ctx["channel_name"])

    can_run = bool(
        ctx["channel_name"] and ctx["topic_title"]
        and ctx["confirmed_title"] and session.get(P3_STRUCTURE)
    )
    if not can_run:
        st.warning("⚠️ 1~3단계를 모두 완료해야 대본 작성을 진행할 수 있습니다.")
        return

    st.divider()

    # ── 추가 요구사항 ──
    with st.expander("⚙️ 추가 요구사항 (선택)", expanded=False):
        extra = st.text_area(
            "대본 작성 시 추가로 고려할 사항",
            placeholder="예) BODY 1에서 이천삼십 년 수치 강조 / 전체적으로 더 공격적인 톤으로",
            height=80,
            key="p4_extra",
        )

    # ── 생성 버튼 ──
    col_f, col_b = st.columns(2)
    with col_f:
        front_btn = st.button(
            "✍️ 앞부분 생성 (HOOK~BODY 2)",
            type="primary",
            use_container_width=True,
            disabled=not can_run,
            key="btn_front",
            help="순수 TTS 구어체 대본 약 5,000자",
        )
    with col_b:
        back_btn = st.button(
            "✍️ 뒷부분 생성 (BODY 3~END)",
            type="primary",
            use_container_width=True,
            disabled=not bool(session.get(P4_SCRIPT_FRONT)),
            key="btn_back",
            help="앞부분 생성 후 활성화. 약 5,000자 + 시각화 메모",
        )

    # ── 앞부분 생성 ──
    if front_btn:
        try:
            system_prompt = PROMPT_4_FRONT_SYSTEM.format(
                persona_block=persona, **ctx
            )
        except KeyError as e:
            st.error(f"프롬프트 포맷 오류: {e}")
            return

        extra_text = session.get("p4_extra", "")
        user_msg = (
            "위 기획 정보를 바탕으로 앞부분 대본을 작성해주세요."
            " 총 5,000자 이상, 헤더·타임코드 없는 순수 구어체로만 작성합니다."
        )
        if extra_text.strip():
            user_msg += f"\n\n추가 요구사항: {extra_text}"

        progress   = st.empty()
        result_box = st.empty()
        try:
            client    = _get_client()
            full_text = ""
            progress.info("✍️ 앞부분 대본 작성 중... (약 2~4분 소요)")

            with client.messages.stream(
                model="claude-sonnet-4-6",
                max_tokens=8000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_msg}],
            ) as stream:
                for chunk in stream.text_stream:
                    full_text += chunk
                    if len(full_text) % 300 == 0:
                        result_box.text_area(
                            "생성 중...",
                            value=full_text[-1500:],
                            height=300,
                            disabled=True,
                        )

            session[P4_SCRIPT_FRONT] = full_text
            session[P4_SCRIPT_FULL]  = ""
            session[P4_CONFIRMED]    = False
            tts_len = _measure_tts(full_text)
            progress.success(
                f"✅ 앞부분 완료! TTS 기준 {tts_len:,}자 "
                f"{'(✅ 목표 달성)' if tts_len >= 5000 else f'(⚠️ {5000 - tts_len:,}자 부족)'}"
            )
            st.rerun()

        except Exception as e:
            progress.error(f"생성 중 오류: {str(e)[:200]}")

    # ── 뒷부분 생성 ──
    if back_btn:
        front_text = session.get(P4_SCRIPT_FRONT, "")
        front_tail = front_text[-300:] if front_text else ""

        try:
            system_prompt = PROMPT_4_BACK_SYSTEM.format(
                persona_block=persona, **ctx
            )
        except KeyError as e:
            st.error(f"프롬프트 포맷 오류: {e}")
            return

        extra_text = session.get("p4_extra", "")
        user_msg = (
            f"앞부분 마지막 내용:\n---\n{front_tail}\n---\n\n"
            "위 앞부분에 이어서 뒷부분 대본을 작성해주세요. "
            "총 5,000자 이상, 헤더·타임코드 없는 순수 구어체로만 작성합니다. "
            "앞부분 내용을 반복하지 말고 흐름만 이어받아 시작하세요."
        )
        if extra_text.strip():
            user_msg += f"\n\n추가 요구사항: {extra_text}"

        progress   = st.empty()
        result_box = st.empty()
        try:
            client    = _get_client()
            full_text = ""
            progress.info("✍️ 뒷부분 대본 작성 중... (약 2~4분 소요)")

            with client.messages.stream(
                model="claude-sonnet-4-6",
                max_tokens=8000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_msg}],
            ) as stream:
                for chunk in stream.text_stream:
                    full_text += chunk
                    if len(full_text) % 300 == 0:
                        result_box.text_area(
                            "생성 중...",
                            value=full_text[-1500:],
                            height=300,
                            disabled=True,
                        )

            back_script, viz_memo = _split_viz_memo(full_text)
            session[P4_SCRIPT_BACK] = back_script
            session[P4_VIZ_MEMO]    = viz_memo
            session[P4_SCRIPT_FULL] = (
                session.get(P4_SCRIPT_FRONT, "") + "\n\n" + back_script
            )

            front_len = _measure_tts(session.get(P4_SCRIPT_FRONT, ""))
            back_len  = _measure_tts(back_script)
            total     = front_len + back_len
            grade_icon = "🏆" if total >= 12000 else "✅" if total >= 10000 else "⚠️"
            progress.success(
                f"✅ 뒷부분 완료! "
                f"앞 {front_len:,}자 + 뒤 {back_len:,}자 = 전체 {total:,}자 {grade_icon}"
            )
            st.rerun()

        except Exception as e:
            progress.error(f"생성 중 오류: {str(e)[:200]}")

    # ── 결과 없으면 안내 ──
    front_text = session.get(P4_SCRIPT_FRONT, "")
    back_text  = session.get(P4_SCRIPT_BACK,  "")
    full_text  = session.get(P4_SCRIPT_FULL,  "")
    viz_memo   = session.get(P4_VIZ_MEMO,     "")

    if not front_text:
        st.info("위 버튼을 눌러 대본을 생성하세요. 앞부분 → 뒷부분 순서로 생성합니다.")
        return

    st.divider()

    # ── 분량 현황 메트릭 ──
    front_tts = _measure_tts(front_text)
    back_tts  = _measure_tts(back_text) if back_text else 0
    total_tts = front_tts + back_tts

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "앞부분 TTS", f"{front_tts:,}자",
        "✅" if front_tts >= 5000 else f"⚠️ {5000 - front_tts:,}자 부족",
    )
    c2.metric(
        "뒷부분 TTS", f"{back_tts:,}자",
        "✅" if back_tts >= 5000 else ("⚠️ 부족" if back_text else "미생성"),
    )
    c3.metric("전체 합산", f"{total_tts:,}자")
    grade = (
        "🏆 최고" if total_tts >= 12000 else
        "✅ 목표" if total_tts >= 10000 else
        "⚠️ 양호" if total_tts >=  8000 else
        "❌ 부족"
    )
    c4.metric("분량 등급", grade)

    if total_tts > 0:
        st.progress(min(total_tts / 12000, 1.0))
        st.caption(
            f"목표 10,000자 기준 {min(total_tts / 10000 * 100, 100):.0f}% 달성"
        )

    # ── 대본 4탭 ──
    tab_front, tab_back, tab_full, tab_viz = st.tabs([
        "📄 앞부분 대본",
        "📄 뒷부분 대본",
        "📋 전체 합본 (확정용)",
        "🎨 시각화 메모 (프롬프트 5용)",
    ])

    with tab_front:
        st.caption("헤더·타임코드 없는 순수 TTS 구어체 대본")
        edited_front = st.text_area(
            "", value=front_text, height=500, key="edit_front",
        )
        if st.button("💾 앞부분 수정 저장", key="save_front"):
            session[P4_SCRIPT_FRONT] = edited_front
            session[P4_SCRIPT_FULL]  = (
                edited_front + "\n\n" + session.get(P4_SCRIPT_BACK, "")
            )
            st.success("✅ 저장됨")
            st.rerun()

    with tab_back:
        if back_text:
            st.caption("앞부분에 자연스럽게 이어지는 순수 TTS 구어체 대본")
            edited_back = st.text_area(
                "", value=back_text, height=500, key="edit_back",
            )
            if st.button("💾 뒷부분 수정 저장", key="save_back"):
                session[P4_SCRIPT_BACK] = edited_back
                session[P4_SCRIPT_FULL] = (
                    session.get(P4_SCRIPT_FRONT, "") + "\n\n" + edited_back
                )
                st.success("✅ 저장됨")
                st.rerun()
        else:
            st.info("뒷부분 생성 후 확인 가능합니다.")

    with tab_full:
        if full_text:
            st.caption("앞+뒤 합본 — 이 텍스트가 탭6·7에 전달됩니다")
            edited_full = st.text_area(
                "", value=full_text, height=600, key="edit_full",
            )
            if st.button(
                "✅ 전체 대본 확정 저장",
                type="primary",
                use_container_width=True,
                key="confirm_script",
            ):
                session[P4_SCRIPT_FULL] = edited_full
                session[P4_CONFIRMED]   = True
                st.success(
                    "✅ 대본 확정 완료!\n\n"
                    "👆 상단에서 📦 업로드 패키지 탭으로 이동하세요."
                )
                st.rerun()
        else:
            st.info("앞+뒤 모두 생성 후 확인 가능합니다.")

    with tab_viz:
        if viz_memo:
            st.caption(
                "이 메모를 프롬프트 5(시각화) 탭에 함께 참고하면 정확도가 높아집니다."
            )
            st.text_area("", value=viz_memo, height=400, key="viz_memo_view")
        else:
            st.info("뒷부분 생성 완료 후 자동으로 생성됩니다.")

    # ── 재생성 옵션 ──
    st.divider()
    st.subheader("🔄 부분 재생성")
    rc1, rc2 = st.columns(2)
    with rc1:
        if st.button("🔄 앞부분만 재생성", use_container_width=True, key="regen_front"):
            session[P4_SCRIPT_FRONT] = ""
            session[P4_SCRIPT_FULL]  = ""
            session[P4_CONFIRMED]    = False
            st.rerun()
    with rc2:
        if st.button("🔄 뒷부분만 재생성", use_container_width=True, key="regen_back"):
            session[P4_SCRIPT_BACK] = ""
            session[P4_SCRIPT_FULL] = ""
            session[P4_VIZ_MEMO]    = ""
            session[P4_CONFIRMED]   = False
            st.rerun()

    # ── 다운로드 ──
    if full_text:
        st.divider()
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        ch = ctx["channel_name"]
        dl_content = (
            f"채널: {ch}\n"
            f"확정 제목: {ctx['confirmed_title']}\n"
            f"생성일시: {ts}\n"
            f"{'━' * 40}\n\n"
            f"{full_text}\n\n"
            f"{'━' * 40}\n"
            f"{viz_memo}"
        )
        st.download_button(
            "📥 전체 대본 TXT 다운로드",
            data=dl_content.encode("utf-8"),
            file_name=f"대본_{ch}_{ts}.txt",
            mime="text/plain",
            use_container_width=True,
            key="dl_script_txt",
        )

    if session.get(P4_CONFIRMED):
        st.success("✅ 대본 확정 완료! 📦 업로드 패키지 탭으로 이동하세요.")
