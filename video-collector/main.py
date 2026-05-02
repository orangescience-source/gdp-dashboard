import sys
from modules.srt_parser import parse_srt
from modules.claude_analyzer import analyze_scenes
from modules.video_searcher import search_videos
from modules.sheets_writer import write_to_sheets
from config import SPREADSHEET_ID


def main():
    if len(sys.argv) < 2:
        print("사용법: python main.py subtitles.srt")
        sys.exit(1)

    srt_path = sys.argv[1]

    print("📄 SRT 파싱 중...")
    subtitles = parse_srt(srt_path)
    print(f"  → {len(subtitles)}개 자막 블록 파싱됨")

    print("🤖 Claude로 장면 분석 중...")
    scenes = analyze_scenes(subtitles)
    print(f"  → {len(scenes)}개 장면 추출됨")

    print("🎬 영상 검색 중...")
    for scene in scenes:
        scene["videos"] = search_videos(scene)
        print(f"  → 장면 {scene['scene_number']}: {len(scene['videos'])}개 후보")

    print("📊 Google Sheets에 저장 중...")
    write_to_sheets(scenes, SPREADSHEET_ID)

    print("✅ 완료!")


if __name__ == "__main__":
    main()
