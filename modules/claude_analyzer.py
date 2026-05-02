import json
import time
import anthropic
from config import ANTHROPIC_API_KEY

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def analyze_scenes(subtitles: list[dict], max_retries: int = 3) -> list[dict]:
    subtitle_text = "\n".join(
        f"[{s['index']}] {s['start']} --> {s['end']}\n{s['text']}"
        for s in subtitles
    )

    system_prompt = (
        "당신은 영상 편집 전문가입니다.\n"
        "주어진 자막을 분석해서 시각적으로 다른 장면이 필요한 의미 단위로 묶어주세요.\n"
        "각 장면에 대해 다음을 JSON 배열로 반환하세요. 다른 텍스트는 절대 포함하지 마세요."
    )

    user_prompt = (
        "다음 자막을 장면 단위로 분석해주세요:\n\n"
        f"{subtitle_text}\n\n"
        "반환 형식 (JSON 배열만):\n"
        "[\n"
        "  {\n"
        '    "scene_number": 1,\n'
        '    "start_time": "00:00:00,080",\n'
        '    "end_time": "00:00:13,670",\n'
        '    "summary_ko": "장면 요약 (한국어)",\n'
        '    "search_keywords": ["keyword1", "keyword2", "keyword3"],\n'
        '    "suggested_filename": "01_scene_description",\n'
        '    "description": "상세 설명 (한국어)",\n'
        '    "tags": ["tag1", "tag2", "tag3"]\n'
        "  }\n"
        "]\n\n"
        "주의사항:\n"
        "- search_keywords는 반드시 영어로 (Pexels/Pixabay 검색용)\n"
        "- 키워드는 장면당 3개, 구체적이고 시각적인 표현\n"
        "- suggested_filename은 {장면번호}_{핵심내용} 형식, 소문자+언더스코어\n"
        "- JSON 배열만 반환, 다른 텍스트 없음"
    )

    client = _get_client()

    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model="claude-opus-4-5",
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )

            raw = response.content[0].text.strip()

            # JSON 블록 추출 (```json ... ``` 감싸진 경우 대비)
            if raw.startswith("```"):
                lines = raw.splitlines()
                raw = "\n".join(
                    line for line in lines
                    if not line.startswith("```")
                )

            scenes = json.loads(raw)
            if not isinstance(scenes, list):
                raise ValueError("응답이 JSON 배열이 아닙니다.")
            return scenes

        except (json.JSONDecodeError, ValueError) as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"  ⚠ JSON 파싱 실패 (시도 {attempt + 1}/{max_retries}), {wait}초 후 재시도: {e}")
                time.sleep(wait)
            else:
                raise RuntimeError(f"Claude 응답 파싱 최종 실패: {e}") from e
