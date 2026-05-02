import gspread
from google.oauth2.service_account import Credentials
from config import GOOGLE_SERVICE_ACCOUNT_JSON

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

HEADERS = [
    "장면#",
    "시작",
    "끝",
    "자막 요약",
    "검색 키워드",
    "소스",
    "영상 제목",
    "영상 URL",
    "썸네일 URL",
    "길이(초)",
    "제안 파일명",
    "설명",
    "태그",
    "선택 여부",
]

# 교대 배경색: 연회색(짝수 장면) / 흰색(홀수 장면)
COLOR_GRAY = {"red": 0.9, "green": 0.9, "blue": 0.9}
COLOR_WHITE = {"red": 1.0, "green": 1.0, "blue": 1.0}


def _get_sheet(spreadsheet_id: str):
    creds = Credentials.from_service_account_file(
        GOOGLE_SERVICE_ACCOUNT_JSON, scopes=SCOPES
    )
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(spreadsheet_id)

    try:
        sheet = spreadsheet.worksheet("영상후보")
    except gspread.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title="영상후보", rows=1000, cols=14)

    return sheet


def _make_hyperlink(url: str, title: str) -> str:
    safe_title = title.replace('"', "'")
    return f'=HYPERLINK("{url}","{safe_title}")'


def write_to_sheets(scenes: list[dict], spreadsheet_id: str) -> None:
    sheet = _get_sheet(spreadsheet_id)
    sheet.clear()

    # 헤더 행 작성
    sheet.append_row(HEADERS)

    # 헤더 굵게 적용
    sheet.format(
        "A1:N1",
        {
            "textFormat": {"bold": True},
            "backgroundColor": {"red": 0.2, "green": 0.4, "blue": 0.8},
        },
    )

    current_row = 2  # 데이터 시작 행

    for scene in scenes:
        videos = scene.get("videos", [])
        scene_number = scene.get("scene_number", "")
        start_time = scene.get("start_time", "")
        end_time = scene.get("end_time", "")
        summary_ko = scene.get("summary_ko", "")
        keywords_str = ", ".join(scene.get("search_keywords", []))
        suggested_filename = scene.get("suggested_filename", "")
        description = scene.get("description", "")
        tags_str = ", ".join(scene.get("tags", []))

        bg_color = COLOR_GRAY if scene_number % 2 == 0 else COLOR_WHITE

        if not videos:
            row = [
                scene_number,
                start_time,
                end_time,
                summary_ko,
                keywords_str,
                "검색 결과 없음",
                "",
                "",
                "",
                "",
                suggested_filename,
                description,
                tags_str,
                "",
            ]
            sheet.append_row(row, value_input_option="USER_ENTERED")
            sheet.format(
                f"A{current_row}:N{current_row}",
                {"backgroundColor": bg_color},
            )
            current_row += 1
            continue

        for i, video in enumerate(videos):
            url = video.get("url", "")
            title = video.get("title", "")
            thumbnail = video.get("thumbnail", "")

            url_cell = _make_hyperlink(url, title) if url else ""
            thumbnail_cell = _make_hyperlink(thumbnail, "썸네일") if thumbnail else ""

            if i == 0:
                row = [
                    scene_number,
                    start_time,
                    end_time,
                    summary_ko,
                    keywords_str,
                    video.get("source", ""),
                    title,
                    url_cell,
                    thumbnail_cell,
                    video.get("duration", ""),
                    suggested_filename,
                    description,
                    tags_str,
                    "",
                ]
            else:
                row = [
                    "",
                    "",
                    "",
                    "",
                    "",
                    video.get("source", ""),
                    title,
                    url_cell,
                    thumbnail_cell,
                    video.get("duration", ""),
                    "",
                    "",
                    "",
                    "",
                ]

            sheet.append_row(row, value_input_option="USER_ENTERED")
            sheet.format(
                f"A{current_row}:N{current_row}",
                {"backgroundColor": bg_color},
            )
            current_row += 1
