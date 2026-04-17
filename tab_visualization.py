"""
탭7: 🖼️ 시각화 프롬프트
확정된 대본(또는 직접 입력한 씬 목록)을 기반으로
채널 페르소나가 반영된 이미지 생성 프롬프트를 스트리밍으로 생성한다.
"""

import re
import streamlit as st
import anthropic

from session_state_manager import (
    P1_CHANNEL,
    P4_SCRIPT_FULL,
    P4_CONFIRMED,
    P5_RESULT_RAW,
    P5_RESULT_SCENES,
    P5_LAST_NUM,
    P5_GENERATING,
    render_pipeline_status,
    render_p4_confirmed_card,
)
from prompts import build_p5_system_prompt


# ──────────────────────────────────────────
# 내부 유틸
# ──────────────────────────────────────────

def _get_client() -> anthropic.Anthropic:
    key = st.session_state.get("api_key", "")
    if not key:
        raise ValueError("API 키가 설정되지 않았습니다.")
    return anthropic.Anthropic(api_key=key)


def _parse_scenes(raw_text: str) -> list[dict]:
    """
    출력 형식:
        번호
        [한국어 번역] ...
        [영어 이미지 프롬프트] ...
    를 파싱하여 [{"num": int, "korean": str, "prompt": str}, ...] 반환.
    """
    scenes = []
    blocks = re.split(r"\n(?=\d+\n)", raw_text.strip())
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        lines = block.splitlines()
        if not lines:
            continue
        # 첫 줄: 번호
        try:
            num = int(lines[0].strip())
        except ValueError:
            continue
        korean = ""
        prompt = ""
        for line in lines[1:]:
            if line.startswith("[한국어 번역]"):
                korean = line.replace("[한국어 번역]", "").strip()
            elif line.startswith("[영어 이미지 프롬프트]"):
                prompt = line.replace("[영어 이미지 프롬프트]", "").strip()
        if prompt:
            scenes.append({"num": num, "korean": korean, "prompt": prompt})
    return scenes


def _extract_scenes_from_script(script: str, num_scenes: int) -> str:
    """
    대본을 num_scenes 단락 단위로 분할하여 씬 목록을 만든다.
    TTS 순수 구어체 대본(헤더 없음)과 기존 STAGE 헤더 대본 모두 지원한다.
    """
    lines = []

    # 시각화 메모 분리 — 메모 이후는 씬 추출 대상에서 제외
    viz_sep = "[시각화 연동 메모]"
    script_body = script.split(viz_sep)[0].strip()

    # STAGE 헤더 패턴 (기존 대본 호환)
    stage_pattern = re.compile(r"\[?STAGE\s*(\d+)[^\]]*\]?[^\n]*", re.IGNORECASE)
    matches = list(stage_pattern.finditer(script_body))

    if matches:
        # 기존 STAGE 헤더 기반 추출
        step = max(1, len(matches) // num_scenes)
        for i in range(num_scenes):
            idx = min(i * step, len(matches) - 1)
            m = matches[idx]
            snippet = script_body[m.end(): m.end() + 200].replace("\n", " ").strip()
            lines.append(f"{i+1}. {m.group(0).strip()} — {snippet[:100]}")
        return "\n".join(lines[:num_scenes])

    # TTS 대본 — 단락(빈 줄 기준) 분할 후 균등 배분
    paragraphs = [p.strip() for p in script_body.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [script_body]

    step = max(1, len(paragraphs) // num_scenes)
    for i in range(num_scenes):
        idx = min(i * step, len(paragraphs) - 1)
        snippet = paragraphs[idx].replace("\n", " ")[:150]
        lines.append(f"{i+1}. {snippet}")
    return "\n".join(lines)


# ──────────────────────────────────────────
# 스트리밍 생성
# ──────────────────────────────────────────

def _stream_visualization(
    channel_name: str,
    scene_text: str,
    num_scenes: int,
    placeholder,
    image_purpose: str = "본문 삽입 이미지",
) -> str:
    """
    Claude API 스트리밍으로 이미지 프롬프트를 생성하고
    placeholder에 실시간으로 출력한다.
    생성 완료 후 전체 텍스트를 반환한다.
    """
    system_prompt = build_p5_system_prompt(
        channel_name=channel_name,
        image_purpose=image_purpose,
    )

    user_message = f"""아래 씬 목록 전체에 대해 이미지 생성 프롬프트를 생성해주세요.

[씬 목록 — 총 {num_scenes}개]
{scene_text}

출력 규칙:
- 지정된 형식 고정: 번호 / [한국어 번역] / [영어 이미지 프롬프트]
- [한국어 번역]: 대본 한글 독음 숫자 그대로 유지
- [영어 이미지 프롬프트]: 숫자를 아라비아 숫자로 복원
- STANDARD_SCENE 또는 DATA_SKETCH_SCENE 분류 적용
- DATA_SKETCH_SCENE은 전체의 25% 이내로 제한
- 10개마다 "계속 생성할까요?" 확인 후 이어서 생성
- 대본 내용이 빠짐없이 처리되어야 함"""

    client = _get_client()
    full_text = ""

    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        for chunk in stream.text_stream:
            full_text += chunk
            placeholder.markdown(
                f"```\n{full_text}\n```",
                unsafe_allow_html=False,
            )

    return full_text


# ──────────────────────────────────────────
# 결과 표시 서브탭
# ──────────────────────────────────────────

def _render_result_tabs(scenes: list[dict], raw_text: str, channel_name: str):
    """카드 보기 / 원문 / 통계 서브탭"""
    sub1, sub2, sub3 = st.tabs(["🃏 카드 보기", "📄 원문", "📊 통계"])

    with sub1:
        if not scenes:
            st.info("파싱된 씬이 없습니다. 원문 탭에서 직접 확인하세요.")
        else:
            cols_per_row = 2
            for i in range(0, len(scenes), cols_per_row):
                row_scenes = scenes[i : i + cols_per_row]
                cols = st.columns(cols_per_row)
                for col, scene in zip(cols, row_scenes):
                    with col:
                        st.markdown(
                            f"""<div style="
                                border:1px solid #e0e0e0;
                                border-radius:10px;
                                padding:14px 16px;
                                margin-bottom:12px;
                                background:#fafafa;
                            ">
                            <div style="font-size:12px;color:#888;margin-bottom:4px;">씬 {scene['num']}</div>
                            <div style="font-weight:700;margin-bottom:8px;color:#1a1a1a;">{scene['korean']}</div>
                            <div style="font-size:12px;color:#444;line-height:1.6;">{scene['prompt']}</div>
                            </div>""",
                            unsafe_allow_html=True,
                        )

    with sub2:
        st.text_area(
            "생성 원문",
            value=raw_text,
            height=500,
            key="p5_raw_display",
        )
        # TXT 다운로드
        txt_bytes = raw_text.encode("utf-8")
        st.download_button(
            label="⬇️ TXT 다운로드",
            data=txt_bytes,
            file_name=f"visualization_prompts_{channel_name}.txt",
            mime="text/plain",
            key="p5_download_txt",
        )

    with sub3:
        if scenes:
            st.metric("생성된 씬 수", f"{len(scenes)}개")
            avg_len = sum(len(s["prompt"].split()) for s in scenes) // max(1, len(scenes))
            st.metric("프롬프트 평균 단어 수", f"{avg_len}단어")
            total_chars = sum(len(s["prompt"]) for s in scenes)
            st.metric("총 영어 프롬프트 길이", f"{total_chars:,}자")
        else:
            st.info("파싱된 씬 데이터가 없습니다.")


# ──────────────────────────────────────────
# 메인 렌더 함수
# ──────────────────────────────────────────

def render_visualization_tab():
    render_pipeline_status()

    st.subheader("🖼️ 시각화 프롬프트 생성")
    st.caption("확정된 대본을 기반으로 각 씬의 이미지 생성 프롬프트를 자동 생성합니다.")

    # ── 4단계 확정 카드 ──────────────────────────────
    render_p4_confirmed_card()

    st.divider()

    # ── 입력 모드 선택 ────────────────────────────────
    channel_name = st.session_state.get(P1_CHANNEL, "")
    if not channel_name:
        st.warning("⚠️ 주제 발굴(탭2)에서 채널을 먼저 선택해주세요.")
        return

    st.markdown(f"**선택된 채널:** {channel_name}")

    col_purpose, col_mode = st.columns([1, 2])
    with col_purpose:
        image_purpose = st.selectbox(
            "🎯 이미지 목적",
            ["본문 삽입 이미지", "썸네일"],
            key="p5_image_purpose",
            help="본문 삽입: 하단 텍스트 금지 / 썸네일: 하단 2줄 레이아웃 허용",
        )
    with col_mode:
        input_mode = st.radio(
            "씬 입력 방식",
            ["📝 대본에서 자동 추출", "✏️ 직접 씬 목록 입력"],
            horizontal=True,
            key="p5_input_mode",
        )

    num_scenes = st.slider(
        "생성할 씬 수",
        min_value=4,
        max_value=20,
        value=8,
        step=1,
        key="p5_num_scenes",
        help="대본 구조에 맞게 씬 수를 조절하세요.",
    )

    # ── 씬 텍스트 준비 ────────────────────────────────
    scene_text = ""

    if input_mode == "📝 대본에서 자동 추출":
        script = st.session_state.get(P4_SCRIPT_FULL, "")
        confirmed = st.session_state.get(P4_CONFIRMED, False)
        if not confirmed or not script:
            st.warning("⚠️ 대본 작성(탭5)을 먼저 완료하고 확정해주세요.")
        else:
            scene_text = _extract_scenes_from_script(script, num_scenes)
            with st.expander("📋 추출된 씬 목록 미리보기", expanded=False):
                st.text(scene_text)
    else:
        default_scenes = "\n".join(
            [f"{i+1}. 씬 {i+1} 내용을 여기에 입력하세요." for i in range(num_scenes)]
        )
        scene_text = st.text_area(
            "씬 목록 직접 입력 (번호. 씬 설명 형식)",
            value=st.session_state.get("p5_manual_scenes", default_scenes),
            height=250,
            key="p5_manual_scenes_input",
            help="각 줄에 '번호. 씬 설명' 형식으로 입력하세요.",
        )
        st.session_state["p5_manual_scenes"] = scene_text

    # ── 생성 버튼 ─────────────────────────────────────
    st.divider()

    col_btn, col_reset = st.columns([3, 1])
    with col_btn:
        generate_btn = st.button(
            "🎨 이미지 프롬프트 생성",
            type="primary",
            disabled=not scene_text.strip(),
            key="p5_generate_btn",
        )
    with col_reset:
        if st.button("🔄 초기화", key="p5_reset_btn"):
            for key in [P5_RESULT_RAW, P5_RESULT_SCENES, P5_LAST_NUM]:
                st.session_state.pop(key, None)
            st.rerun()

    # ── 생성 실행 ─────────────────────────────────────
    if generate_btn and scene_text.strip():
        st.session_state[P5_GENERATING] = True
        stream_placeholder = st.empty()
        stream_placeholder.info("⏳ 이미지 프롬프트를 생성하고 있습니다...")

        try:
            raw_text = _stream_visualization(
                channel_name=channel_name,
                scene_text=scene_text,
                num_scenes=num_scenes,
                placeholder=stream_placeholder,
                image_purpose=image_purpose,
            )
            scenes = _parse_scenes(raw_text)
            st.session_state[P5_RESULT_RAW]    = raw_text
            st.session_state[P5_RESULT_SCENES] = scenes
            st.session_state[P5_LAST_NUM]      = num_scenes
            st.session_state[P5_GENERATING]    = False
            st.success(f"✅ {len(scenes)}개 씬 프롬프트 생성 완료!")
        except Exception as e:
            st.session_state[P5_GENERATING] = False
            st.error(f"생성 중 오류가 발생했습니다: {e}")
            return

    # ── 결과 표시 ─────────────────────────────────────
    raw_text = st.session_state.get(P5_RESULT_RAW, "")
    scenes   = st.session_state.get(P5_RESULT_SCENES, [])

    if raw_text:
        st.divider()
        st.subheader("📊 생성 결과")
        _render_result_tabs(scenes, raw_text, channel_name)
