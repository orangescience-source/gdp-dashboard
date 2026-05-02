#!/bin/bash
# YouTube Shorts Converter - 실행 스크립트
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# .env 파일이 있으면 로드
if [ -f ".env" ]; then
  export $(grep -v '^#' .env | xargs)
fi

if [ -z "$ANTHROPIC_API_KEY" ]; then
  echo "⚠️  ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다."
  echo "   export ANTHROPIC_API_KEY=your_key 또는 .env 파일을 생성하세요."
  exit 1
fi

# 의존성 확인
for cmd in ffmpeg ffprobe yt-dlp; do
  if ! command -v "$cmd" &> /dev/null; then
    echo "❌ $cmd 가 설치되어 있지 않습니다."
    exit 1
  fi
done

echo "✅ 의존성 확인 완료"
echo "🚀 서버 시작: http://localhost:8000"
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
