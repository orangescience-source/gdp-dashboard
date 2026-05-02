import re


def parse_txt(filepath: str) -> list[dict]:
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    blocks = re.split(r"\n{2,}", content.strip())
    subtitles = []
    index = 0

    for block in blocks:
        lines = [l.strip() for l in block.strip().splitlines() if l.strip()]
        if not lines:
            continue

        # 첫 줄이 순번(숫자)인 경우 제거
        start = 0
        if lines[0].isdigit():
            start = 1

        korean = ""
        image_prompt = ""

        for line in lines[start:]:
            lower = line.lower()
            if lower.startswith("[한국어 번역]"):
                korean = line[len("[한국어 번역]"):].strip()
            elif lower.startswith("[영어 이미지 프롬프트]"):
                image_prompt = line[len("[영어 이미지 프롬프트]"):].strip()
            elif not korean:
                korean = line
            elif not image_prompt:
                image_prompt = line

        if not korean and not image_prompt:
            continue

        index += 1
        subtitles.append(
            {
                "index": index,
                "start": "",
                "end": "",
                "text": korean,
                "image_prompt": image_prompt,
            }
        )

    return subtitles
