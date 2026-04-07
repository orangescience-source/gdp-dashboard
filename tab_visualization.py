"""
Tab 7: 스틱맨 시각화 프롬프트 생성기
완성된 대본을 2~10문장 단위로 분할하여 나노바나나 PRO 이미지 프롬프트를 자동 생성한다.
"""
import os
import streamlit as st
import anthropic
from session_state_manager import (
    P1_CHANNEL, P1_TOPIC_TITLE,
    P4_SCRIPT_FULL, P4_VIZ_MEMO, P4_CONFIRMED,
)
from error_handler import handle_api_error


# ── 클라이언트 (모듈레벨 방지) ────────────────────────────────────────────────

def _get_client() -> anthropic.Anthropic:
    try:
        key = st.secrets.get("ANTHROPIC_API_KEY", "")
    except Exception:
        key = ""
    key = key or os.environ.get("ANTHROPIC_API_KEY", "")
    return anthropic.Anthropic(api_key=key)


# ── 채널별 시각 무드 매핑 ──────────────────────────────────────────────────────

CHANNEL_VISUAL_MOOD = {
    "거침없는 경제학": {
        "character": "Tae-oh: red mask, black suit, stickman 1:1:1 ratio",
        "mood": "fear, anger, red warning, sharp numeric conflict",
        "bg_color_hint": "#FF6B6B accent on environment only",
        "scene_style": "dark dramatic lighting, crashing red bar charts, alarming crowd reactions",
    },
    "머니매커니즘": {
        "character": "Gear Yoon: gold-rimmed glasses, emerald eyes, stickman 1:1:1 ratio",
        "mood": "system structure, gear mechanisms, capital flow blueprint",
        "bg_color_hint": "#5BC8A0 accent on environment only",
        "scene_style": "blueprint-style backgrounds, gear cogs, flow diagrams, emerald-tinted lighting",
    },
    "친절한 경제학자": {
        "character": "Saito: neat black hair, sophisticated horn-rimmed glasses, stickman 1:1:1 ratio",
        "mood": "global graphs, smart digital analysis space, modern mentor",
        "bg_color_hint": "#2C3E50 accent on environment only",
        "scene_style": "sleek dark navy background, glowing global market graphs, tablet props",
    },
    "남몰래 경제학": {
        "character": "Shadow: purple mask, giant magnifying glass, stickman 1:1:1 ratio",
        "mood": "mystery, covert revelation, hidden truth tracking",
        "bg_color_hint": "#9B72CF accent on environment only",
        "scene_style": "dark misty background, magnifying glass highlighting secrets, purple spotlight",
    },
    "사이언스로그": {
        "character": "Log: blue visor, high-tech suit, stickman 1:1:1 ratio",
        "mood": "cold data, laboratory, hologram analysis",
        "bg_color_hint": "#7DD8F5 accent on environment only",
        "scene_style": "cold blue cyber lab, hologram displays, data stream particles",
    },
    "사이언스툰": {
        "character": "Nutty: large goggles, exaggerated expressions, stickman 1:1:1 ratio",
        "mood": "pop art, joyful exaggeration, fast energy",
        "bg_color_hint": "#85D98A accent on environment only",
        "scene_style": "pop art speed lines, bright splashing liquids, comic-style impact effects",
    },
    "미래인사이트": {
        "character": "Future: cybernetic eye, neon jacket, stickman 1:1:1 ratio",
        "mood": "cyberpunk, prediction, future warning",
        "bg_color_hint": "#9B8FC8 accent on environment only",
        "scene_style": "cyberpunk neon cityscape, holographic displays, futuristic warning signals",
    },
    "히스토리프로파일러": {
        "character": "Lupus: brown fedora, trench coat, stickman 1:1:1 ratio",
        "mood": "sepia tone, clue board, historical investigation",
        "bg_color_hint": "#C4A882 accent on environment only",
        "scene_style": "sepia-toned noir setting, red string clue board, vintage documents",
    },
    "친절한 심리학자": {
        "character": "Psy: mint sweatshirt, semi-rimless glasses, stickman 1:1:1 ratio",
        "mood": "emotion interpretation, psychological prism, clean consultation space",
        "bg_color_hint": "#3EB489 accent on environment only",
        "scene_style": "clean mint-white consultation room, emotion prism light refraction, calm atmosphere",
    },
    "거리의 경제학": {
        "character": "Hyeonjang: orange beanie, shopping basket, stickman 1:1:1 ratio",
        "mood": "market scene, receipt props, everyday economic reality",
        "bg_color_hint": "#F5A55A accent on environment only",
        "scene_style": "vibrant market stall background, visible price tags and receipts, street-level crowd",
    },
    "친절한 공학자": {
        "character": "Engi: white hard hat, blue work uniform, stickman 1:1:1 ratio",
        "mood": "blueprints, operating mechanisms, precise engineering components",
        "bg_color_hint": "#4A90E2 accent on environment only",
        "scene_style": "technical blueprint grid background, mechanical parts floating, measuring tools",
    },
    "친절한 과학자": {
        "character": "Scien: neat brown hair, round glasses, stickman 1:1:1 ratio",
        "mood": "warm research lab, beakers, everyday science",
        "bg_color_hint": "#50C878 accent on environment only",
        "scene_style": "warm green-tinted lab, glowing beakers, atom symbols, friendly experiment setup",
    },
    "친절한 사회학자": {
        "character": "Socio: round glasses, brown cardigan, stickman 1:1:1 ratio",
        "mood": "social network visualization, human connection, societal structure",
        "bg_color_hint": "#D2B48C accent on environment only",
        "scene_style": "warm beige background, web of human connection nodes, diverse crowd interaction",
    },
}

_DEFAULT_MOOD = {
    "character": "neutral analyst stickman 1:1:1 ratio",
    "mood": "clear analytical visual",
    "bg_color_hint": "neutral gray accent on environment only",
    "scene_style": "clean professional analytical setting",
}



# ── 시스템 프롬프트 생성 ──────────────────────────────────────────────────────

def build_p5_system_prompt(channel_name: str) -> str:
    mood = CHANNEL_VISUAL_MOOD.get(channel_name, _DEFAULT_MOOD)
    ch   = channel_name
    lines = [
        "당신은 대한민국 유튜브 시장 Top 1% 비주얼 디렉터이자 3등신 스틱맨 전문 이미지 프롬프트 설계자입니다.",
        "",
        f"채널: {ch}",
        f"주인공(C01): {mood['character']}",
        f"시각 무드: {mood['mood']}",
        f"씬 스타일: {mood['scene_style']}",
        f"채널 색상 (환경 연출 전용): {mood['bg_color_hint']}",
        "",
        "[핵심 임무]",
        "입력된 대본을 처음부터 끝까지 빠짐없이 분석하여,",
        "모든 문장을 의미·감정·장면 전환 기준으로 2~10문장 범위에서 유연하게 묶고,",
        "각 구간마다 이미지 생성 모델에 바로 입력 가능한 영어 이미지 프롬프트를 생성합니다.",
        "",
        "데이터 정보량이 높은 구간은 DATA_SKETCH_SCENE으로 자동 전환합니다.",
        "",
        "[필수 준수 규칙]",
        "",
        "1. 출력 형식 (반드시 이 형식만 사용):",
        "번호",
        "[한국어 번역] 대본 2~10문장 내용",
        "[영어 이미지 프롬프트] 영어 프롬프트 내용",
        "",
        "2. 채널명 표기 규칙:",
        f'- 모든 이미지 좌측 상단에 채널명 "{ch}"을 흰색(White)으로 표기',
        "- 검은 외곽선 4~6px 적용",
        "- 메인 헤드라인보다 작게",
        "- 채널 고유 색상은 채널명 텍스트에 절대 사용 금지",
        "",
        "3. 텍스트 배치 규칙 (자막 겹침 방지):",
        "- 이미지 내 모든 텍스트는 하단 중앙(bottom-center) 배치 절대 금지",
        "- 허용 위치: 상단 중앙, 좌측 상단 블록(채널명 아래), 우측 상단 블록, 인물 주변 말풍선",
        "- 이유: 영상 하단은 자막 삽입 영역과 겹침",
        "",
        "4. 텍스트 언어 규칙:",
        "- 이미지 내 모든 텍스트는 한국어(한글) 사용",
        "- 영어는 브랜드명·고유명사·약어에만 허용",
        "- 한글+아라비아 숫자+한글 단위 조합 사용",
        "",
        "5. 숫자 표기 변환 규칙 (TTS 대본 → 이미지):",
        '- 대본의 한글 숫자를 아라비아 숫자로 반드시 환원',
        '- 변환 예시: "이십 퍼센트" → "20%", "일천이백구십이년" → "1292년",',
        '  "삼십칠조 원" → "37조 원", "오천만 명" → "5,000만 명"',
        "- 이미지 내 통계/수치는 항상 아라비아 숫자+한글 단위 형식",
        "",
        "6. 텍스트 색상 고정 팔레트 (전 채널 공통):",
        "- 메인 헤드라인: 노란색 또는 흰색",
        "- 강조/경고 문구: 연두색 또는 빨간색",
        "- 말풍선: 흰색 또는 노란색",
        "- 채널 고유 색상(#HEX)은 텍스트에 절대 사용 금지",
        "- 채널 색상은 배경/조명/소품/환경 연출에만 사용",
        "",
        "7. 3등신 스틱맨 시각 스타일:",
        "- 1:1:1 비율 (머리:몸통:다리)",
        "- 반드시 머리 1개만 (single-head 강제)",
        "- extra head, multiple heads, duplicated face 절대 금지",
        "- 굵은 둥근 외곽선 3.5px, bold flat colors, high contrast cell shading",
        "- No photorealism, cartoon-style illustration only",
        "",
        "8. Scene-First 원칙:",
        "- 기본값: 장면 중심 구성",
        "- 인물은 오프센터(좌측 또는 우측 1/3) 배치 우선",
        "- 인물 프레임 시각 비중 15~25% 권장",
        "- 장면 자체로 상황이 즉시 이해되어야 함",
        "",
        "9. DATA_SKETCH_SCENE 규칙:",
        "- 수치 2개 이상 밀집, 통계/비교/추세가 핵심인 구간에 적용",
        "- 등장인물 없음 (no characters, no stickman, no face)",
        "- notebook sketch / graph paper sketch 스타일",
        "- 데이터 라벨: graphite black, soft gray, red pencil highlight, pale yellow marker",
        "- 채널 조명 사용 금지",
        "",
        "10. 분량 규칙:",
        "- 한 번에 최대 10개 장면 출력",
        '- 10개 후 반드시 "계속 생성할까요?" 로 마무리',
        '- 사용자가 "계속" 답변 시 다음 번호부터 이어서 생성',
        "",
        "[영어 프롬프트 내 필수 포함 문구들]",
        "",
        "공통 (모든 STANDARD_SCENE):",
        (
            '"Premium single-head stickman visual system with 1:1:1 chibi proportion'
            " — exactly ONE head per character, never multiple heads."
            f" Channel name '{ch}' displayed in top-left corner in White text with black outline (4-6px)."
            " Place all text in the UPPER AREA of the frame"
            " (top-center, top-left block below channel name, top-right block, or speech bubble near character)."
            " NEVER place any text at the bottom-center as that area is reserved for video subtitles."
            " All visible text inside the image must be written in Korean (Hangul) using Arabic numerals for numbers"
            " (e.g., '20%', '37\uc870 \uc6d0', '1292\ub144')."
            " All text colors: main headline Yellow or White, emphasis Lime Green or Red,"
            " speech bubble White or Yellow — all with EXTRA THICK black outline (8-10px)."
            " Channel identity color may only affect background lighting, props, and environment — NEVER text."
            " Cartoon-style illustration only. Thick black outlines 3.5px."
            ' Bold flat colors. High contrast cell shading. No photorealism."'
        ),
        "",
        "DATA_SKETCH_SCENE 전용:",
        (
            '"DATA_SKETCH_SCENE mode.'
            " No characters, no people, no stickman, no mascot, no face."
            " Notebook sketch infographic style. Off-white graph paper background."
            " Pencil sketch lines and marker highlights."
            f" Channel name '{ch}' in top-left if thumbnail purpose."
            " All data labels in Korean with Arabic numerals."
            ' Top-down information-first layout. Clean negative space. No cinematic lighting."'
        ),
        "",
        "[출력 형식 예시]",
        "1",
        "[한국어 번역] 첫 번째 구간 대본 내용",
        "[영어 이미지 프롬프트] ...",
        "",
        "2",
        "[한국어 번역] 두 번째 구간 대본 내용",
        "[영어 이미지 프롬프트] ...",
        "",
        "이 형식 외에 다른 설명, 분석, 부연 문구를 섞지 않습니다.",
        "번호 / [한국어 번역] / [영어 이미지 프롬프트] 3개 항목만 출력합니다.",
    ]
    return "\n".join(lines)


# ── 사용자 메시지 빌드 ───────────────────────────────────────────────────────

def build_p5_user_message(
    script_text: str,
    viz_memo: str,
    image_purpose: str,
    viz_range: str,
    extra_requirements: str,
) -> str:
    memo_section  = f"\n\n[프롬프트 4 시각화 연동 메모]\n{viz_memo}" if viz_memo.strip() else ""
    extra_section = f"\n\n[추가 요구사항]\n{extra_requirements}" if extra_requirements.strip() else ""
    return (
        f"[시각화 범위]: {viz_range}\n"
        f"[이미지 목적]: {image_purpose}\n\n"
        f"[대본 전체]{memo_section}\n"
        f"{script_text}{extra_section}\n\n"
        "위 대본을 처음부터 끝까지 2~10문장 단위로 유연하게 분할하여\n"
        "각 구간마다 이미지 프롬프트를 생성하세요.\n"
        "번호 / [한국어 번역] / [영어 이미지 프롬프트] 형식만 사용하세요."
    )


# ── 스트리밍 생성 ────────────────────────────────────────────────────────────

def _run_p5_generation(
    channel: str,
    script_full: str,
    viz_memo: str,
    image_purpose: str,
    viz_range: str,
    start_from: int,
    extra_req: str,
) -> None:
    system_prompt = build_p5_system_prompt(channel)

    start_instruction = (
        f"\n\n[이어서 생성]: {start_from}번부터 시작하여 순서대로 번호를 부여하세요."
        if start_from > 1 else ""
    )

    user_message = build_p5_user_message(
        script_text=script_full,
        viz_memo=viz_memo,
        image_purpose=image_purpose,
        viz_range=viz_range,
        extra_requirements=extra_req + start_instruction,
    )

    st.session_state["p5_generating"]     = True
    st.session_state["p5_result_raw"]     = ""
    st.session_state["p5_result_scenes"]  = []

    result_container = st.empty()
    full_text = ""

    try:
        client = _get_client()

        with client.messages.stream(
            model="claude-sonnet-4-6",
            max_tokens=8000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            for text in stream.text_stream:
                full_text += text
                display = full_text[-3000:] if len(full_text) > 3000 else full_text
                result_container.markdown(f"```\n{display}\n```")

        scenes = _parse_p5_output(full_text)
        st.session_state["p5_result_raw"]    = full_text
        st.session_state["p5_result_scenes"] = scenes

        if scenes:
            last_num = scenes[-1].get("num", start_from + len(scenes) - 1)
            st.session_state["p5_last_scene_num"] = last_num + 1

        st.session_state["p5_generating"] = False
        st.rerun()

    except Exception as e:
        handle_api_error(e, context="프롬프트 5 - 이미지 프롬프트 생성")
        st.session_state["p5_generating"] = False


# ── 출력 파싱 ────────────────────────────────────────────────────────────────

def _parse_p5_output(raw_text: str) -> list:
    scenes = []
    lines  = raw_text.strip().split("\n")
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # 번호 감지 (단독 숫자 줄 또는 "10." 형식)
        is_num = False
        scene_num = 0
        if line and line[0].isdigit():
            candidate = line.split(".")[0].strip()
            if candidate.isdigit() and len(candidate) <= 3:
                is_num = True
                scene_num = int(candidate)

        if is_num:
            korean_text = ""
            english_prompt = ""
            i += 1

            # [한국어 번역] 수집
            while i < len(lines) and not lines[i].strip().startswith("[영어 이미지 프롬프트]"):
                if lines[i].strip().startswith("[한국어 번역]"):
                    i += 1
                    while i < len(lines) and not lines[i].strip().startswith("[영어 이미지 프롬프트]"):
                        korean_text += lines[i] + "\n"
                        i += 1
                else:
                    i += 1

            # [영어 이미지 프롬프트] 수집
            if i < len(lines) and lines[i].strip().startswith("[영어 이미지 프롬프트]"):
                i += 1
                ep_lines = []
                while i < len(lines):
                    nxt = lines[i].strip()
                    if nxt and nxt[0].isdigit() and nxt.split(".")[0].isdigit() and len(nxt.split(".")[0]) <= 3:
                        break
                    ep_lines.append(lines[i])
                    i += 1
                english_prompt = "\n".join(ep_lines).strip()

            if english_prompt:
                ep_upper = english_prompt.upper()
                is_data_scene = (
                    "DATA_SKETCH_SCENE" in ep_upper
                    or "no characters" in english_prompt.lower()
                    or "notebook sketch infographic" in english_prompt.lower()
                )
                scenes.append({
                    "num": scene_num,
                    "korean": korean_text.strip(),
                    "prompt": english_prompt,
                    "is_data_scene": is_data_scene,
                })
        else:
            i += 1

    return scenes


# ── 결과 렌더링 ──────────────────────────────────────────────────────────────

def _render_p5_results() -> None:
    scenes = st.session_state.get("p5_result_scenes", [])
    raw    = st.session_state.get("p5_result_raw", "")

    if not scenes and not raw:
        return

    st.divider()
    st.subheader(f"📋 생성 결과 ({len(scenes)}개 장면)")

    view_tab1, view_tab2, view_tab3 = st.tabs(
        ["🃏 카드뷰 (복사용)", "📄 전체 원문", "📊 통계"]
    )

    with view_tab1:
        for scene in scenes:
            scene_type = "🖼️ DATA_SKETCH" if scene["is_data_scene"] else "🎬 STANDARD"
            with st.expander(
                f"{scene_type}  장면 {scene['num']}",
                expanded=(scene["num"] <= 3),
            ):
                st.markdown("**[한국어 번역]**")
                st.info(scene["korean"])

                st.markdown("**[영어 이미지 프롬프트]**")
                st.code(scene["prompt"], language=None)

                col1, col2 = st.columns(2)
                with col1:
                    if st.button(
                        "📋 프롬프트 복사",
                        key=f"copy_prompt_{scene['num']}",
                        use_container_width=True,
                    ):
                        st.toast(f"장면 {scene['num']} 프롬프트 복사됨!")
                with col2:
                    if scene["is_data_scene"]:
                        st.caption("🗂️ DATA_SKETCH_SCENE (인물 없음)")
                    else:
                        st.caption("👤 STANDARD_SCENE (3등신 스틱맨)")

    with view_tab2:
        st.text_area(
            "전체 생성 결과 (원문)",
            value=raw,
            height=600,
            key="p5_raw_view",
        )

    with view_tab3:
        total    = len(scenes)
        data_cnt = sum(1 for s in scenes if s["is_data_scene"])
        std_cnt  = total - data_cnt

        col1, col2, col3 = st.columns(3)
        col1.metric("총 장면 수", f"{total}개")
        col2.metric("STANDARD_SCENE", f"{std_cnt}개")
        col3.metric("DATA_SKETCH_SCENE", f"{data_cnt}개")

        if total > 0:
            data_ratio = round(data_cnt / total * 100)
            st.progress(data_cnt / max(total, 1))
            st.caption(f"데이터 장면 비율: {data_ratio}% (권장: 10~25%)")

    # 다운로드
    st.divider()
    if raw:
        topic = st.session_state.get(P1_TOPIC_TITLE, "script")
        st.download_button(
            label="📥 전체 프롬프트 TXT 다운로드",
            data=raw.encode("utf-8"),
            file_name=f"visualization_prompts_{topic[:20]}.txt",
            mime="text/plain",
            use_container_width=True,
        )

    # 이어서 생성 안내
    if "계속 생성할까요?" in raw or (scenes and len(scenes) >= 10):
        st.info(
            "💡 **이어서 생성하려면:**  \n"
            "위 설정 패널의 **'이어서 생성 시작 번호'** 를 마지막 번호 +1로 설정 후  \n"
            "**'🎨 이미지 프롬프트 생성'** 버튼을 다시 누르세요."
        )


# ── 메인 렌더 함수 ───────────────────────────────────────────────────────────

def render_visualization_tab() -> None:
    st.header("🖼️ 스틱맨 시각화 프롬프트 생성기", divider="gray")
    st.caption(
        "완성된 대본을 2~10문장 단위로 분할하여  \n"
        "나노바나나 PRO 이미지 프롬프트를 자동 생성합니다."
    )

    # ── 이전 단계 확정 내용 불러오기 ─────────────────────────────────────────
    script_full = st.session_state.get(P4_SCRIPT_FULL, "")
    viz_memo    = st.session_state.get(P4_VIZ_MEMO, "")
    channel     = st.session_state.get(P1_CHANNEL, "")
    confirmed   = st.session_state.get(P4_CONFIRMED, False)

    if not confirmed or not script_full:
        st.info("📝 탭5(대본 작성)에서 대본을 완성하고 확정하면 여기서 이미지 프롬프트를 생성할 수 있습니다.")

        # 직접 입력 모드
        st.divider()
        st.subheader("✏️ 직접 대본 입력 모드")
        channel = st.selectbox(
            "채널 선택",
            options=[""] + list(CHANNEL_VISUAL_MOOD.keys()),
            key="p5_manual_channel",
        )
        script_full = st.text_area(
            "대본 입력 (전체 또는 일부)",
            height=300,
            placeholder="대본을 여기에 붙여넣으세요...",
            key="p5_manual_script",
        )
        viz_memo = st.text_area(
            "시각화 연동 메모 (선택)",
            height=100,
            placeholder="프롬프트 4의 시각화 연동 메모를 입력하면 DATA_SKETCH_SCENE 정확도가 높아집니다.",
            key="p5_manual_viz_memo",
        )
    else:
        st.success(f"✅ 확정된 대본 ({len(script_full):,}자) 불러옴")

        with st.expander("📄 확정 대본 확인/수정", expanded=False):
            script_full = st.text_area(
                "대본 (수정 가능)",
                value=script_full,
                height=400,
                key="p5_script_edit",
            )
        if viz_memo:
            with st.expander("🔗 시각화 연동 메모 확인", expanded=False):
                viz_memo = st.text_area(
                    "시각화 연동 메모",
                    value=viz_memo,
                    height=200,
                    key="p5_viz_memo_edit",
                )

    st.divider()

    # ── 설정 패널 ─────────────────────────────────────────────────────────────
    st.subheader("⚙️ 생성 설정")
    col1, col2 = st.columns(2)

    with col1:
        image_purpose = st.selectbox(
            "이미지 목적",
            ["본문 삽입 이미지", "썸네일", "장면 요약", "쇼츠용 이미지"],
            key="p5_image_purpose",
        )
        viz_range = st.selectbox(
            "시각화 범위",
            ["전체 대본", "HOOK + TEASER", "BODY 1~2", "BODY 3~4",
             "REVEAL + IMPACT + END", "특정 구간 직접 지정"],
            key="p5_viz_range",
        )

    with col2:
        start_from = st.number_input(
            "이어서 생성 시작 번호 (처음부터면 1)",
            min_value=1,
            value=int(st.session_state.get("p5_last_scene_num", 1)),
            step=1,
            key="p5_start_num",
        )
        extra_req = st.text_input(
            "추가 요구사항 (선택)",
            placeholder="예: BODY 2 구간 위주로 생성해주세요",
            key="p5_extra_req",
        )

    # ── 채널 무드 미리보기 ────────────────────────────────────────────────────
    if channel and channel in CHANNEL_VISUAL_MOOD:
        mood = CHANNEL_VISUAL_MOOD[channel]
        with st.expander(f"🎨 [{channel}] 채널 시각 무드 미리보기", expanded=False):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"**주인공(C01):** {mood['character']}")
                st.markdown(f"**시각 무드:** {mood['mood']}")
            with c2:
                st.markdown(f"**씬 스타일:** {mood['scene_style']}")
                st.markdown(f"**채널 색상 (환경 전용):** `{mood['bg_color_hint']}`")

    st.divider()

    # ── 규칙 안내 ─────────────────────────────────────────────────────────────
    with st.expander("📋 이미지 프롬프트 생성 규칙 (자동 적용)", expanded=False):
        st.markdown(
            "**자동 적용 규칙:**\n"
            "- ✅ 채널명 **좌측 상단** 흰색 고정 표기\n"
            "- ✅ 텍스트 **하단 중앙 배치 금지** (자막 영역 충돌 방지)\n"
            "- ✅ 이미지 내 텍스트 **한국어(한글) 우선**\n"
            "- ✅ 숫자는 **아라비아 숫자+한글 단위** (예: 20%, 37조 원, 1292년)\n"
            "- ✅ 텍스트 색상: 노란색/흰색/연두색/빨간색 고정 팔레트\n"
            "- ✅ 채널 고유 색상: 텍스트 금지, 배경/조명/소품에만 사용\n"
            "- ✅ 3등신 스틱맨: 머리 1개 고정 (single-head)\n"
            "- ✅ 데이터 구간: DATA_SKETCH_SCENE 자동 전환 (인물 없음)\n"
            "- ✅ 한 번에 최대 10개 장면 생성"
        )

    # ── 생성 버튼 ─────────────────────────────────────────────────────────────
    can_generate = bool(channel) and bool(script_full.strip())

    if not can_generate:
        if not channel:
            st.warning("⚠️ 채널을 먼저 선택하세요.")
        if not script_full.strip():
            st.warning("⚠️ 대본을 입력하거나 탭5에서 대본을 확정하세요.")

    if st.button(
        "🎨 이미지 프롬프트 생성",
        type="primary",
        use_container_width=True,
        disabled=not can_generate,
    ):
        _run_p5_generation(
            channel=channel,
            script_full=script_full,
            viz_memo=viz_memo,
            image_purpose=image_purpose,
            viz_range=viz_range,
            start_from=int(start_from),
            extra_req=extra_req,
        )

    # ── 결과 표시 ─────────────────────────────────────────────────────────────
    _render_p5_results()
