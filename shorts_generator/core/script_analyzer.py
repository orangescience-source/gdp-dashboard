"""
Script analyzer using Anthropic Claude (claude-sonnet-4-6).
Splits a Korean YouTube Shorts script into structured scenes with metadata.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import anthropic
from rich.console import Console

from config import get_api_key

console = Console()

# ─── Data models ──────────────────────────────────────────────────────────────

@dataclass
class Scene:
    index: int
    type: str               # "HOOK" | "BODY" | "CTA" | "BUMP"
    text: str
    duration_estimate: float  # seconds
    keywords: list[str]
    mood: str
    visual_description: str  # used for Pexels / AI video search


@dataclass
class ScriptAnalysis:
    scenes: list[Scene]
    total_duration_estimate: float
    overall_mood: str
    hook_score: int           # 1–10; how grabby the hook is
    thumbnail_keywords: list[str]   # top 3 for thumbnail generation
    title_suggestions: list[str]    # 3 title suggestions
    description: str                # YouTube description body (without footer)


# ─── Prompt ───────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
당신은 YouTube Shorts 영상 제작 전문가입니다.
사용자가 제공하는 한국어 대본을 분석하여 장면(scene) 단위로 분리하고, 각 장면의 메타데이터를 JSON으로 반환합니다.

반드시 아래 JSON 스키마를 정확히 따라 응답하세요. JSON 이외의 텍스트는 절대 포함하지 마세요.

응답 JSON 스키마:
{
  "scenes": [
    {
      "index": 0,
      "type": "HOOK",
      "text": "장면 대사 텍스트",
      "duration_estimate": 3.5,
      "keywords": ["키워드1", "키워드2", "키워드3"],
      "mood": "dramatic",
      "visual_description": "Pexels 또는 AI 이미지 검색에 사용할 영어 시각 설명"
    }
  ],
  "total_duration_estimate": 45.0,
  "overall_mood": "dramatic",
  "hook_score": 8,
  "thumbnail_keywords": ["키워드1", "키워드2", "키워드3"],
  "title_suggestions": ["제목1", "제목2", "제목3"],
  "description": "유튜브 설명란에 사용할 본문 텍스트 (해시태그 포함, 푸터 제외)"
}

규칙:
- scene type: HOOK(첫 3초 후크), BODY(본문 정보), CTA(행동 유도), BUMP(브랜드 범프)
- duration_estimate: 해당 장면 텍스트를 자연스럽게 읽는 데 걸리는 초 단위 시간 (실제 계산)
- keywords: Pexels 영상 검색에 쓸 한국어 키워드 2~4개
- visual_description: 영어로 작성, Pexels portrait video 검색 최적화
- mood: dramatic/business/upbeat/emotional/epic/calm/suspense/motivational/fun/cinematic 중 하나
- hook_score: 1(약함)~10(매우 강함), 시청자 이탈 방지 관점에서 평가
- title_suggestions: 알고리즘 최적화된 유튜브 제목 3개 (50자 이하, 이모지 포함)
- description: 최소 3문단, 해시태그 최소 10개 포함
"""

_USER_PROMPT_TEMPLATE = """\
아래 YouTube Shorts 대본을 분석해 주세요:

---
{script}
---

총 영상 길이가 59초를 넘지 않도록 장면을 설계하세요.
"""


# ─── Analyzer class ──────────────────────────────────────────────────────────

class ScriptAnalyzer:
    """Analyzes a Korean script using Claude and returns structured scenes."""

    def __init__(self) -> None:
        self._client: anthropic.Anthropic | None = None

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic(api_key=get_api_key("anthropic"))
        return self._client

    def analyze(self, script: str) -> ScriptAnalysis:
        """
        Analyze the script and return a ScriptAnalysis.

        Args:
            script: Raw Korean script text.

        Returns:
            Populated ScriptAnalysis dataclass.

        Raises:
            ValueError: If Claude returns invalid JSON or unexpected structure.
            anthropic.APIError: On API communication errors.
        """
        console.print("[cyan]🤖 Claude로 대본 분석 중...[/cyan]")

        response = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": _USER_PROMPT_TEMPLATE.format(script=script),
                }
            ],
        )

        raw_text = response.content[0].text.strip()

        # Strip markdown code fences if present
        raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
        raw_text = re.sub(r"\s*```$", "", raw_text)

        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Claude가 유효하지 않은 JSON을 반환했습니다: {exc}\n\n원문:\n{raw_text}"
            ) from exc

        scenes = [
            Scene(
                index=s["index"],
                type=s["type"],
                text=s["text"],
                duration_estimate=float(s["duration_estimate"]),
                keywords=s["keywords"],
                mood=s["mood"],
                visual_description=s["visual_description"],
            )
            for s in data["scenes"]
        ]

        analysis = ScriptAnalysis(
            scenes=scenes,
            total_duration_estimate=float(data["total_duration_estimate"]),
            overall_mood=data["overall_mood"],
            hook_score=int(data["hook_score"]),
            thumbnail_keywords=data["thumbnail_keywords"],
            title_suggestions=data["title_suggestions"],
            description=data["description"],
        )

        console.print(
            f"[green]✓ 분석 완료[/green]  "
            f"{len(scenes)}개 장면 / "
            f"예상 {analysis.total_duration_estimate:.1f}초 / "
            f"후크 점수 {analysis.hook_score}/10"
        )
        return analysis
