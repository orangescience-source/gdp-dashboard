import json
import re
import time
import anthropic
from config import ANTHROPIC_API_KEY

_client = None

INPUT_PRICE_PER_M = 3.0    # $3 / 1M input tokens (claude-sonnet-4-5)
OUTPUT_PRICE_PER_M = 15.0  # $15 / 1M output tokens
KRW_RATE = 1380


def _extract_json_array(text: str) -> list:
    # 1순위: ```json ... ``` 블록 명시적 추출
    json_block = re.search(r"```json\s*([\s\S]*?)```", text)
    if json_block:
        candidate = json_block.group(1).strip()
        try:
            result = json.loads(candidate)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    # 2순위: ``` ... ``` 일반 코드 블록 추출
    code_block = re.search(r"```\s*([\s\S]*?)```", text)
    if code_block:
        candidate = code_block.group(1).strip()
        try:
            result = json.loads(candidate)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    # 3순위: 텍스트 전체에서 첫 '[' ~ 마지막 ']' 범위 추출
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        try:
            result = json.loads(candidate)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    # 4순위: 중첩 괄호를 직접 추적해 가장 바깥 배열 추출
    depth = 0
    array_start = None
    for i, ch in enumerate(text):
        if ch == "[" and array_start is None:
            array_start = i
            depth = 1
        elif ch == "[" and array_start is not None:
            depth += 1
        elif ch == "]" and array_start is not None:
            depth -= 1
            if depth == 0:
                candidate = text[array_start : i + 1]
                try:
                    result = json.loads(candidate)
                    if isinstance(result, list):
                        return result
                except json.JSONDecodeError:
                    pass
                array_start = None

    raise ValueError(f"응답에서 JSON 배열을 찾을 수 없습니다. 원문 앞 200자: {text[:200]}")


def _calc_cost(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens / 1_000_000 * INPUT_PRICE_PER_M
            + output_tokens / 1_000_000 * OUTPUT_PRICE_PER_M)


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def analyze_scenes(
    subtitles: list[dict], max_retries: int = 3, chunk_size: int = 50
) -> tuple[list[dict], dict]:
    chunks = [subtitles[i : i + chunk_size] for i in range(0, len(subtitles), chunk_size)]
    all_scenes = []
    scene_offset = 0
    total_input = 0
    total_output = 0

    for chunk_idx, chunk in enumerate(chunks):
        print(f"  → 청크 {chunk_idx + 1}/{len(chunks)} 처리 중 (자막 {len(chunk)}개)...")
        chunk_scenes, in_tok, out_tok = _analyze_chunk(chunk, scene_offset, max_retries)
        all_scenes.extend(chunk_scenes)
        scene_offset += len(chunk_scenes)
        total_input += in_tok
        total_output += out_tok
        print(f"     입력 {in_tok:,} | 출력 {out_tok:,} 토큰")

    cost_usd = _calc_cost(total_input, total_output)
    usage_stats = {
        "input_tokens": total_input,
        "output_tokens": total_output,
        "cost_usd": round(cost_usd, 4),
        "cost_krw": round(cost_usd * KRW_RATE),
    }
    print(f"  💰 총 비용: ${cost_usd:.4f} (약 {usage_stats['cost_krw']:,}원)")
    return all_scenes, usage_stats


def _analyze_chunk(
    subtitles: list[dict], scene_offset: int, max_retries: int
) -> tuple[list[dict], int, int]:
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
        f"다음 자막을 장면 단위로 분석해주세요. scene_number는 {scene_offset + 1}부터 시작합니다:\n\n"
        f"{subtitle_text}\n\n"
        "반환 형식 (JSON 배열만):\n"
        "[\n"
        "  {\n"
        f'    "scene_number": {scene_offset + 1},\n'
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
            scenes = _extract_json_array(raw)

            for i, scene in enumerate(scenes):
                scene["scene_number"] = scene_offset + i + 1

            in_tok = response.usage.input_tokens
            out_tok = response.usage.output_tokens
            return scenes, in_tok, out_tok

        except (json.JSONDecodeError, ValueError) as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"  ⚠ JSON 파싱 실패 (시도 {attempt + 1}/{max_retries}), {wait}초 후 재시도: {e}")
                time.sleep(wait)
            else:
                raise RuntimeError(f"Claude 응답 파싱 최종 실패: {e}") from e
