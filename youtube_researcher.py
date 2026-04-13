import streamlit as st
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import re

# ── 채널별 검색 기준 키워드 ──
CHANNEL_SEARCH_KEYWORDS = {
    "거침없는 경제학": [
        "경제위기", "주식폭락", "부동산붕괴",
        "금리쇼크", "경제경고"
    ],
    "머니매커니즘": [
        "금융구조", "자본주의시스템", "투자전략",
        "돈의흐름", "경제메커니즘"
    ],
    "친절한 경제학자": [
        "글로벌경제", "환율전망", "금리분석",
        "경제전망", "미국경제"
    ],
    "남몰래 경제학": [
        "경제비밀", "가격담합", "유통마진",
        "숨겨진경제", "폭로경제"
    ],
    "사이언스로그": [
        "과학최신연구", "AI기술", "뇌과학",
        "우주과학", "물리학"
    ],
    "사이언스툰": [
        "신기한과학", "과학실험", "과학상식",
        "재미있는과학", "생활과학"
    ],
    "미래인사이트": [
        "미래기술", "AI미래", "로봇기술",
        "자율주행", "미래직업"
    ],
    "히스토리프로파일러": [
        "역사미스터리", "역사사건", "미제사건",
        "역사비밀", "세계사"
    ],
    "친절한 심리학자": [
        "심리학", "자존감", "인간관계심리",
        "감정조절", "정신건강"
    ],
    "거리의 경제학": [
        "물가상승", "장바구니물가", "서민경제",
        "최저임금", "생활비"
    ],
    "친절한 공학자": [
        "작동원리", "제품설계", "공학기술",
        "기계원리", "기술리뷰"
    ],
    "친절한 과학자": [
        "일상과학", "생활과학원리", "생명과학",
        "과학실험일상", "자연과학"
    ],
    "친절한 사회학자": [
        "사회현상", "인간관계", "사회문제",
        "공동체", "사회구조"
    ],
}

# ── 발굴 기준 설정 ──
SEARCH_CRITERIA = {
    "period_days": 90,          # 최근 90일 이내
    "min_views": 50000,         # 최소 조회수 5만
    "max_results": 20,          # 키워드당 최대 20개
    "order": "viewCount",       # 조회수 순 정렬
    "region": "KR",             # 한국 지역
    "language": "ko",           # 한국어
    "video_duration": "medium", # 4~20분 (롱폼 기준)
}


def get_youtube_client():
    """YouTube Data API v3 클라이언트 생성"""
    try:
        api_key = st.secrets["YOUTUBE_API_KEY"]
        return build("youtube", "v3", developerKey=api_key)
    except KeyError:
        return None


def search_trending_videos(
    channel_name: str,
    max_topics: int = 5
) -> list:
    """
    채널 페르소나에 맞는 인기 영상을 검색하여
    벤치마킹 주제 후보를 반환한다.

    반환 형식:
    [
        {
            "title": "영상 제목",
            "view_count": 조회수,
            "channel": "채널명",
            "published_at": "업로드일",
            "video_id": "영상 ID",
            "url": "영상 URL",
            "keyword": "검색 키워드",
            "daily_views": 일평균조회수,
            "hit_score": 히트점수,
        }
    ]
    """
    youtube = get_youtube_client()
    if not youtube:
        return []

    keywords = CHANNEL_SEARCH_KEYWORDS.get(channel_name, [])
    if not keywords:
        return []

    # 검색 기간 설정
    published_after = (
        datetime.utcnow() -
        timedelta(days=SEARCH_CRITERIA["period_days"])
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    all_videos = []

    for keyword in keywords:
        try:
            # 1단계: 영상 검색
            search_response = youtube.search().list(
                q=keyword,
                part="id,snippet",
                type="video",
                order=SEARCH_CRITERIA["order"],
                publishedAfter=published_after,
                regionCode=SEARCH_CRITERIA["region"],
                relevanceLanguage=SEARCH_CRITERIA["language"],
                videoDuration=SEARCH_CRITERIA["video_duration"],
                maxResults=SEARCH_CRITERIA["max_results"]
            ).execute()

            video_ids = [
                item["id"]["videoId"]
                for item in search_response.get("items", [])
            ]

            if not video_ids:
                continue

            # 2단계: 조회수 등 상세 정보 수집
            stats_response = youtube.videos().list(
                part="statistics,snippet,contentDetails",
                id=",".join(video_ids)
            ).execute()

            for item in stats_response.get("items", []):
                stats = item.get("statistics", {})
                snippet = item.get("snippet", {})

                view_count = int(
                    stats.get("viewCount", 0)
                )

                # 최소 조회수 필터
                if view_count < SEARCH_CRITERIA["min_views"]:
                    continue

                # 업로드 후 경과일 계산
                published_at = snippet.get(
                    "publishedAt", ""
                )
                try:
                    pub_date = datetime.strptime(
                        published_at,
                        "%Y-%m-%dT%H:%M:%SZ"
                    )
                    days_since = max(
                        (datetime.utcnow() - pub_date).days,
                        1
                    )
                    daily_views = view_count // days_since
                except Exception:
                    days_since = 30
                    daily_views = view_count // 30

                # 히트 점수 계산
                # (조회수 + 일평균 조회수 가중치)
                hit_score = (
                    view_count * 0.5 +
                    daily_views * 500
                )

                all_videos.append({
                    "title": snippet.get("title", ""),
                    "view_count": view_count,
                    "channel": snippet.get(
                        "channelTitle", ""
                    ),
                    "published_at": published_at[:10],
                    "video_id": item["id"],
                    "url": f"https://youtube.com/watch?v={item['id']}",
                    "keyword": keyword,
                    "daily_views": daily_views,
                    "days_since": days_since,
                    "hit_score": hit_score,
                    "like_count": int(
                        stats.get("likeCount", 0)
                    ),
                    "comment_count": int(
                        stats.get("commentCount", 0)
                    ),
                })

        except Exception as e:
            st.warning(
                f"'{keyword}' 검색 중 오류: {str(e)[:100]}"
            )
            continue

    # 히트 점수 기준 정렬 후 상위 N개 반환
    all_videos.sort(
        key=lambda x: x["hit_score"],
        reverse=True
    )

    # 중복 제목 제거
    seen_titles = set()
    unique_videos = []
    for v in all_videos:
        title_key = v["title"][:20]
        if title_key not in seen_titles:
            seen_titles.add(title_key)
            unique_videos.append(v)

    return unique_videos[:max_topics]


def format_view_count(count: int) -> str:
    """조회수를 읽기 쉬운 형식으로 변환"""
    if count >= 10000000:
        return f"{count // 10000000}천만"
    elif count >= 10000:
        return f"{count // 10000}만"
    elif count >= 1000:
        return f"{count // 1000}천"
    return str(count)
