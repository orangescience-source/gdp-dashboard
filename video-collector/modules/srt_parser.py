import re


def parse_srt(filepath: str) -> list[dict]:
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    blocks = re.split(r"\n\n+", content.strip())
    subtitles = []

    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue

        index_line = lines[0].strip()
        time_line = lines[1].strip()
        text = " ".join(line.strip() for line in lines[2:])

        if not index_line.isdigit():
            continue

        match = re.match(
            r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})",
            time_line,
        )
        if not match:
            continue

        subtitles.append(
            {
                "index": int(index_line),
                "start": match.group(1),
                "end": match.group(2),
                "text": text,
            }
        )

    return subtitles
