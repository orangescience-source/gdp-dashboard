"""Claude API를 이용한 니치 영상 AI 분석 모듈."""

import os

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 4096

_SYSTEM = """당신은 유튜브 정치 콘텐츠 전략 전문가입니다.
주어진 니치 영상 제목 목록을 분석해 공통 키워드·주제 패턴을 파악하고,
새로운 니치 주제 아이디어를 제안합니다.
반드시 한국어로 답변하고, 마크다운 형식을 사용하세요."""

_PROMPT_TEMPLATE = """아래는 유튜브 정치 채널에서 채널 평균 조회수 대비 {multiplier}배 이상을 기록한 "니치 영상" {count}개의 제목 목록입니다.

## 니치 영상 제목 목록
{titles}

## 분석 요청

### 1. 공통 키워드 분석
니치 영상들에서 자주 등장하는 핵심 키워드 상위 10개를 빈도와 함께 나열하세요.

### 2. 주제 패턴 분석
니치 영상들이 공통적으로 다루는 주제·프레임·감정 패턴 3~5가지를 구체적으로 설명하세요.

### 3. 성공 요인 분석
이 영상들이 높은 조회수를 기록한 이유를 시청자 심리·시사성·제목 작성 방식 측면에서 분석하세요.

### 4. 신규 니치 주제 5가지 제안
위 분석을 바탕으로 이 채널에서 높은 조회수를 기대할 수 있는 새로운 니치 주제 5가지를 제안하세요.
각 제안은 다음 형식으로 작성하세요:
- **주제**: (주제명)
- **제목 예시**: (실제 영상 제목처럼 작성)
- **이유**: (왜 높은 조회수를 기대할 수 있는지 1~2문장)
"""


def _get_api_key() -> str:
    """환경변수 → Streamlit secrets 순으로 Anthropic API 키를 가져온다."""
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        try:
            import streamlit as st
            key = st.secrets.get("ANTHROPIC_API_KEY", "")
        except Exception:
            pass
    if not key:
        raise ValueError(
            "ANTHROPIC_API_KEY 환경변수 또는 Streamlit secrets가 설정되지 않았습니다."
        )
    return key


def _build_prompt(niche_titles: list, multiplier: float, channel_name: str) -> str:
    numbered = "\n".join(f"{i+1}. {title}" for i, title in enumerate(niche_titles))
    prompt = _PROMPT_TEMPLATE.format(
        multiplier=multiplier,
        count=len(niche_titles),
        titles=numbered,
    )
    if channel_name:
        prompt = f"분석 채널: **{channel_name}**\n\n" + prompt
    return prompt


def analyze_niche_videos(
    niche_titles: list,
    multiplier: float = 3.0,
    channel_name: str = "",
) -> str:
    """니치 영상 제목을 Claude API로 분석하고 마크다운 결과를 반환합니다."""
    if not niche_titles:
        return "분석할 니치 영상이 없습니다. 먼저 분석 결과 탭에서 영상을 분석하세요."

    client = anthropic.Anthropic(api_key=_get_api_key())
    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=_SYSTEM,
        messages=[{"role": "user", "content": _build_prompt(niche_titles, multiplier, channel_name)}],
    )
    return message.content[0].text


def stream_analyze_niche_videos(
    niche_titles: list,
    multiplier: float = 3.0,
    channel_name: str = "",
):
    """스트리밍 방식으로 분석 결과를 생성합니다 (제너레이터).

    스트리밍 중 오류가 발생하면 예외를 그대로 전파합니다.
    호출부에서 그때까지 수신한 텍스트를 보존할 수 있도록 설계됩니다.
    """
    if not niche_titles:
        yield "분석할 니치 영상이 없습니다. 먼저 분석 결과 탭에서 영상을 분석하세요."
        return

    client = anthropic.Anthropic(api_key=_get_api_key())
    prompt = _build_prompt(niche_titles, multiplier, channel_name)

    with client.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for text in stream.text_stream:
            yield text
