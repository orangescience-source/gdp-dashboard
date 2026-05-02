# SRT 자막 기반 영상 후보 수집기

SRT 자막 파일을 입력받아 Claude API로 의미 단위 장면을 분석하고,
Pexels + Pixabay에서 어울리는 영상을 자동 검색한 뒤
결과를 Google Sheets에 저장하는 CLI 도구.

## 설치

```bash
pip install -r requirements.txt
```

## 환경 설정

`.env.example`을 복사해 `.env` 파일을 생성하고 API 키를 입력합니다:

```bash
cp .env.example .env
```

| 변수 | 설명 |
|------|------|
| `ANTHROPIC_API_KEY` | Anthropic Console에서 발급 |
| `PEXELS_API_KEY` | pexels.com/api 에서 발급 (무료) |
| `PIXABAY_API_KEY` | pixabay.com/api/docs 에서 발급 (무료) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | 서비스 계정 JSON 키 파일 경로 |
| `SPREADSHEET_ID` | Google Sheets URL의 `/d/{ID}/` 부분 |

### Google Sheets 연동

1. Google Cloud Console → 새 프로젝트 생성
2. Google Sheets API + Google Drive API 활성화
3. 서비스 계정 생성 → JSON 키 다운로드 → `service_account.json`으로 저장
4. 사용할 구글 시트를 서비스 계정 이메일에 편집자 권한으로 공유

## 실행

```bash
python main.py subtitles.srt
```

## 출력 형식 (Google Sheets)

| 컬럼 | 내용 |
|------|------|
| A | 장면 번호 |
| B | 시작 시간 |
| C | 끝 시간 |
| D | 자막 요약 (한국어) |
| E | 검색 키워드 |
| F | 소스 (pexels/pixabay) |
| G | 영상 제목 |
| H | 영상 URL (클릭 가능) |
| I | 썸네일 URL |
| J | 길이(초) |
| K | 제안 파일명 |
| L | 설명 |
| M | 태그 |
| N | 선택 여부 (직접 입력) |

장면 1개당 최대 6행 (Pexels 3개 + Pixabay 3개), 장면별 교대 배경색 적용.

## 예상 실행 시간 (자막 10분 기준)

- Claude 분석: ~10초
- 영상 검색 (20장면 × 2곳): ~30~60초
- Sheets 저장: ~5초
- **총 약 1~2분**
