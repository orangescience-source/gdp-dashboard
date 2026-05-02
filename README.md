# 📡 정치 유튜브 니치 발굴기

YouTube Data API v3와 Claude AI를 활용해 정치 채널의 고성과 콘텐츠(니치 영상)를 자동 분석하고, 새로운 주제를 제안하는 Streamlit 앱입니다.


## 주요 기능

| 탭 | 기능 |
|---|---|
| ⚙️ 채널 설정 | URL/채널ID 직접 입력 또는 키워드로 채널 검색 |
| 📊 분석결과 | 니치 영상 카드 목록 + 조회수 분포 bar chart |
| 🤖 AI 인사이트 | Claude API로 패턴 분석 및 신규 니치 주제 5개 제안 |

### 니치 분석 방식
- YouTube Data API v3로 채널 최근 영상 최대 200개 수집
- 채널 평균 조회수 대비 설정 배수(기본 3x) 이상 → 니치 영상으로 분류
- 최근 N일 이내 영상만 분석하는 필터 옵션 제공

---

## 로컬 실행

### 1. 저장소 클론

```bash
git clone https://github.com/orangescience-source/gdp-dashboard.git
cd gdp-dashboard
```

### 2. 패키지 설치

```bash
pip install -r requirements.txt
```

### 3. 환경변수 설정

```bash
cp .env.example .env
# .env 파일을 열어 API 키를 입력하세요
```

`.env` 파일 내용:

```env
YOUTUBE_API_KEY=AIza...        # Google Cloud Console에서 발급
ANTHROPIC_API_KEY=sk-ant-...   # Anthropic Console에서 발급
```

### 4. 앱 실행

```bash
streamlit run streamlit_app.py
```

---

## API 키 발급 방법

### YouTube Data API v3
1. [Google Cloud Console](https://console.cloud.google.com) 접속
2. 새 프로젝트 생성 (또는 기존 프로젝트 선택)
3. **API 및 서비스 → 라이브러리** → `YouTube Data API v3` 검색 후 활성화
4. **API 및 서비스 → 사용자 인증 정보 → API 키 만들기**
5. (선택) API 키 제한: YouTube Data API v3만 허용

> **할당량**: 기본 하루 10,000 단위. 채널 1개 전체 분석 시 약 300~500 단위 소모.

### Anthropic Claude API
1. [Anthropic Console](https://console.anthropic.com) 접속
2. **API Keys** 메뉴에서 새 키 생성

---

## Streamlit Cloud 배포

### 1. GitHub에 코드 푸시

```bash
git push origin main
```

### 2. Streamlit Cloud 연결

1. [share.streamlit.io](https://share.streamlit.io) 접속 후 GitHub 연동
2. 저장소 선택 → Main file: `streamlit_app.py` 지정 → **Deploy**

### 3. Secrets 설정 (중요)

Streamlit Cloud 앱 설정 → **Secrets** 탭에서 아래 형식으로 입력합니다.

```toml
# .streamlit/secrets.toml 구조 (Streamlit Cloud Secrets 입력란에 붙여넣기)

YOUTUBE_API_KEY = "AIza..."
ANTHROPIC_API_KEY = "sk-ant-..."
```

> Streamlit Cloud는 `st.secrets`를 통해 환경변수를 읽습니다. `.env` 파일은 로컬 전용이므로 절대 GitHub에 커밋하지 마세요.

### 4. 로컬 secrets.toml (선택)

로컬에서도 `secrets.toml`을 사용하려면:

```bash
mkdir -p .streamlit
cat > .streamlit/secrets.toml << 'EOF'
YOUTUBE_API_KEY = "AIza..."
ANTHROPIC_API_KEY = "sk-ant-..."
EOF
```

---

## 파일 구조

```
.
├── streamlit_app.py       # 메인 진입점 (탭 라우팅)
├── tab_settings.py        # ⚙️ 채널 설정 탭
├── tab_analysis.py        # 📊 분석결과 탭
├── tab_ai_insights.py     # 🤖 AI 인사이트 탭
├── youtube_api.py         # YouTube Data API v3 래퍼
├── analyzer.py            # 니치 분석 로직
├── ai_analyzer.py         # Claude API 분석 모듈
├── requirements.txt       # 패키지 의존성
├── .env.example           # 환경변수 템플릿
└── .gitignore             # .env 등 민감파일 제외
```

---

## 기술 스택

- **[Streamlit](https://streamlit.io)** — UI 프레임워크
- **[google-api-python-client](https://github.com/googleapis/google-api-python-client)** — YouTube Data API v3
- **[anthropic](https://github.com/anthropics/anthropic-sdk-python)** — Claude API (claude-sonnet-4-6)
- **[pandas](https://pandas.pydata.org)** — 데이터 처리
- **[plotly](https://plotly.com/python/)** — 인터랙티브 차트
- **[python-dotenv](https://github.com/theskumar/python-dotenv)** — 환경변수 관리

---

## 주의사항

- `.env` 파일은 절대 GitHub에 커밋하지 마세요 (`.gitignore`에 포함되어 있습니다).
- YouTube API 할당량을 확인하며 사용하세요.
- 채널 분석 시 영상 수가 많을수록 API 할당량 소모가 늘어납니다.
