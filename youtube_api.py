"""YouTube Data API v3 wrapper for niche discovery."""

import os
import re
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv()

# 정치 관련성 판단 키워드
_POLITICAL_KEYWORDS = [
    "정치", "시사", "뉴스", "국회", "대통령", "선거", "여당", "야당",
    "의원", "정당", "민주", "보수", "진보", "외교", "안보", "정책",
    "정부", "청와대", "대선", "총선", "당대표", "탄핵", "개혁",
]


def _build_client():
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        raise ValueError("YOUTUBE_API_KEY 환경변수가 설정되지 않았습니다.")
    return build("youtube", "v3", developerKey=api_key)


def extract_channel_id(url_or_id: str) -> Optional[str]:
    """URL 또는 채널ID 문자열에서 채널 ID를 추출합니다."""
    url_or_id = url_or_id.strip()

    if re.match(r"^UC[\w-]{22}$", url_or_id):
        return url_or_id

    handle_match = re.search(r"@([\w.-]+)", url_or_id)
    if handle_match:
        return resolve_handle_to_id(handle_match.group(1))

    channel_match = re.search(r"/channel/(UC[\w-]{22})", url_or_id)
    if channel_match:
        return channel_match.group(1)

    slug_match = re.search(r"/(?:c|user)/([\w.-]+)", url_or_id)
    if slug_match:
        return resolve_handle_to_id(slug_match.group(1))

    return None


def resolve_handle_to_id(handle: str) -> Optional[str]:
    """채널 핸들 또는 username을 채널 ID로 변환합니다."""
    try:
        youtube = _build_client()
        resp = youtube.channels().list(
            part="id",
            forHandle=f"@{handle}" if not handle.startswith("@") else handle,
        ).execute()
        items = resp.get("items", [])
        if items:
            return items[0]["id"]

        resp = youtube.channels().list(part="id", forUsername=handle).execute()
        items = resp.get("items", [])
        return items[0]["id"] if items else None
    except HttpError:
        return None


def _score_channel(detail: dict, last_upload_days: Optional[int]) -> tuple[int, list[str]]:
    """채널 우선순위 점수를 계산합니다 (100점 만점).

    Returns:
        (총점, 점수 이유 목록)
    """
    score = 0
    reasons: list[str] = []

    stats = detail.get("statistics", {})
    snippet = detail.get("snippet", {})

    # ── 1. 구독자 수 (30점) ───────────────────────────────────────────────────
    subs = int(stats.get("subscriberCount", 0))
    if 10_000 <= subs < 100_000:
        score += 30
        reasons.append(f"구독자 {subs:,}명 (니치 최적)")
    elif 100_000 <= subs < 1_000_000:
        score += 20
        reasons.append(f"구독자 {subs:,}명")
    elif 1_000 <= subs < 10_000:
        score += 15
        reasons.append(f"구독자 {subs:,}명")
    elif subs >= 1_000_000:
        score += 10
        reasons.append(f"구독자 {subs:,}명 (대형 채널)")

    # ── 2. 최근 활성도 (30점) ─────────────────────────────────────────────────
    if last_upload_days is not None:
        if last_upload_days <= 30:
            score += 30
            reasons.append("30일 내 업로드")
        elif last_upload_days <= 90:
            score += 20
            reasons.append("90일 내 업로드")
        elif last_upload_days <= 180:
            score += 10
            reasons.append("180일 내 업로드")

    # ── 3. 영상 수 (20점) ─────────────────────────────────────────────────────
    video_count = int(stats.get("videoCount", 0))
    if video_count >= 50:
        score += 20
        reasons.append(f"영상 {video_count}개")
    elif video_count >= 20:
        score += 10
        reasons.append(f"영상 {video_count}개")

    # ── 4. 정치 관련성 (20점) ─────────────────────────────────────────────────
    text = snippet.get("title", "") + " " + snippet.get("description", "")
    matched_kws = [kw for kw in _POLITICAL_KEYWORDS if kw in text]
    kw_score = min(len(matched_kws) * 5, 20)
    if kw_score > 0:
        score += kw_score
        reasons.append(f"키워드: {', '.join(matched_kws[:4])}")

    return score, reasons


def search_political_channels(keyword: str, max_results: int = 50) -> list[dict]:
    """키워드로 정치 관련 채널을 검색하고 우선순위 점수로 정렬합니다.

    점수 기준 (100점 만점):
      구독자 수 30점 / 최근 활성도 30점 / 영상 수 20점 / 정치 관련성 20점
    """
    try:
        youtube = _build_client()

        # ── 1단계: 채널 검색 ────────────────────────────────────────────────
        resp = youtube.search().list(
            part="snippet",
            q=keyword,
            type="channel",
            maxResults=min(max_results, 50),
            relevanceLanguage="ko",
            regionCode="KR",
        ).execute()

        raw_channels = [
            {
                "channel_id": item["id"]["channelId"],
                "title": item["snippet"]["channelTitle"],
                "description": item["snippet"].get("description", ""),
                "thumbnail": (
                    item["snippet"]
                    .get("thumbnails", {})
                    .get("default", {})
                    .get("url", "")
                ),
            }
            for item in resp.get("items", [])
        ]

        if not raw_channels:
            return []

        # ── 2단계: 채널 상세 정보 일괄 조회 ────────────────────────────────
        channel_ids = [ch["channel_id"] for ch in raw_channels]
        details_resp = youtube.channels().list(
            part="statistics,snippet,contentDetails",
            id=",".join(channel_ids),
        ).execute()
        details_map = {item["id"]: item for item in details_resp.get("items", [])}

        # ── 3단계: 채널별 최근 업로드 날짜 조회 + 점수 계산 ─────────────────
        scored: list[dict] = []
        for ch in raw_channels:
            cid = ch["channel_id"]
            detail = details_map.get(cid, {})

            uploads_id = (
                detail.get("contentDetails", {})
                .get("relatedPlaylists", {})
                .get("uploads", "")
            )

            last_upload_days: Optional[int] = None
            if uploads_id:
                try:
                    pl_resp = youtube.playlistItems().list(
                        part="snippet",
                        playlistId=uploads_id,
                        maxResults=1,
                    ).execute()
                    pl_items = pl_resp.get("items", [])
                    if pl_items:
                        published_at = pl_items[0]["snippet"].get("publishedAt", "")
                        if published_at:
                            pub_dt = datetime.fromisoformat(
                                published_at.replace("Z", "+00:00")
                            )
                            last_upload_days = (
                                datetime.now(timezone.utc) - pub_dt
                            ).days
                except HttpError:
                    pass

            score, reasons = _score_channel(detail, last_upload_days)

            snippet = detail.get("snippet", {})
            stats = detail.get("statistics", {})
            scored.append({
                "channel_id": cid,
                "title": snippet.get("title", ch["title"]),
                "description": snippet.get("description", ch["description"]),
                "thumbnail": (
                    snippet.get("thumbnails", {})
                    .get("default", {})
                    .get("url", ch["thumbnail"])
                ),
                "subscriber_count": int(stats.get("subscriberCount", 0)),
                "video_count": int(stats.get("videoCount", 0)),
                "score": score,
                "score_reasons": reasons,
            })

        # ── 4단계: 점수 내림차순 정렬 → 상위 max_results 반환 ───────────────
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:max_results]

    except HttpError as e:
        raise RuntimeError(f"채널 검색 실패: {e}") from e


def get_channel_info(channel_id: str) -> dict:
    """채널 기본 정보를 가져옵니다."""
    try:
        youtube = _build_client()
        resp = youtube.channels().list(
            part="snippet,statistics",
            id=channel_id,
        ).execute()
        items = resp.get("items", [])
        if not items:
            raise ValueError(f"채널을 찾을 수 없습니다: {channel_id}")

        item = items[0]
        snippet = item["snippet"]
        stats = item.get("statistics", {})
        return {
            "channel_id": channel_id,
            "title": snippet["title"],
            "description": snippet.get("description", ""),
            "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
            "subscriber_count": int(stats.get("subscriberCount", 0)),
            "video_count": int(stats.get("videoCount", 0)),
            "view_count": int(stats.get("viewCount", 0)),
        }
    except HttpError as e:
        raise RuntimeError(f"채널 정보 조회 실패: {e}") from e


def get_channel_videos(channel_id: str, max_results: int = 200) -> list[dict]:
    """채널의 최근 영상 목록을 가져옵니다 (최대 200개).

    1단계: channels().list(contentDetails)로 uploads 플레이리스트 ID 취득
    2단계: playlistItems().list()로 영상 ID 수집
    3단계: playlistItems 404 발생 시 search().list()로 폴백
    """
    if not channel_id:
        raise ValueError("채널 ID가 비어 있습니다.")

    try:
        youtube = _build_client()

        ch_resp = youtube.channels().list(
            part="contentDetails",
            id=channel_id,
        ).execute()

        items = ch_resp.get("items", [])
        if not items:
            raise ValueError(f"채널을 찾을 수 없습니다: {channel_id}")

        uploads_id = (
            items[0]
            .get("contentDetails", {})
            .get("relatedPlaylists", {})
            .get("uploads", "")
        )

        if not uploads_id:
            return _fetch_videos_via_search(youtube, channel_id, max_results)

        return _fetch_videos_from_playlist(youtube, uploads_id, channel_id, max_results)

    except HttpError as e:
        raise RuntimeError(f"영상 목록 조회 실패: {e}") from e


def _fetch_videos_from_playlist(
    youtube, uploads_id: str, channel_id: str, max_results: int
) -> list[dict]:
    """playlistItems API로 업로드 목록을 수집합니다. 404 시 search API로 폴백."""
    videos: list[dict] = []
    page_token = None
    fetched = 0

    while fetched < max_results:
        batch = min(50, max_results - fetched)
        try:
            pl_resp = youtube.playlistItems().list(
                part="contentDetails",
                playlistId=uploads_id,
                maxResults=batch,
                pageToken=page_token,
            ).execute()
        except HttpError as e:
            if int(e.resp.status) == 404:
                return _fetch_videos_via_search(youtube, channel_id, max_results)
            raise

        video_ids = [
            item["contentDetails"]["videoId"]
            for item in pl_resp.get("items", [])
            if item.get("contentDetails", {}).get("videoId")
        ]

        if not video_ids:
            break

        videos.extend(_fetch_video_details(youtube, video_ids))

        fetched += len(video_ids)
        page_token = pl_resp.get("nextPageToken")
        if not page_token:
            break

    videos.sort(key=lambda v: v["published_at"], reverse=True)
    return videos


def _fetch_videos_via_search(
    youtube, channel_id: str, max_results: int
) -> list[dict]:
    """search API로 채널의 최신 영상 ID를 수집합니다 (폴백 전용)."""
    videos: list[dict] = []
    page_token = None
    fetched = 0

    while fetched < max_results:
        batch = min(50, max_results - fetched)
        try:
            search_resp = youtube.search().list(
                part="id",
                channelId=channel_id,
                type="video",
                order="date",
                maxResults=batch,
                pageToken=page_token,
            ).execute()
        except HttpError:
            break

        video_ids = [
            item["id"]["videoId"]
            for item in search_resp.get("items", [])
            if item.get("id", {}).get("videoId")
        ]

        if not video_ids:
            break

        videos.extend(_fetch_video_details(youtube, video_ids))

        fetched += len(video_ids)
        page_token = search_resp.get("nextPageToken")
        if not page_token:
            break

    videos.sort(key=lambda v: v["published_at"], reverse=True)
    return videos


def _fetch_video_details(youtube, video_ids: list[str]) -> list[dict]:
    """videos.list API로 영상 상세 정보(통계+스니펫)를 일괄 조회합니다."""
    resp = youtube.videos().list(
        part="statistics,snippet",
        id=",".join(video_ids),
    ).execute()

    result = []
    for item in resp.get("items", []):
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        published_at = snippet.get("publishedAt", "")
        pub_dt = (
            datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            if published_at
            else None
        )
        days_ago = (
            (datetime.now(timezone.utc) - pub_dt).days
            if pub_dt
            else None
        )
        result.append({
            "video_id": item["id"],
            "title": snippet.get("title", ""),
            "published_at": published_at,
            "pub_dt": pub_dt,
            "days_ago": days_ago,
            "view_count": int(stats.get("viewCount", 0)),
            "like_count": int(stats.get("likeCount", 0)),
            "comment_count": int(stats.get("commentCount", 0)),
            "thumbnail": (
                snippet.get("thumbnails", {})
                .get("medium", {})
                .get("url", "")
            ),
            "url": f"https://www.youtube.com/watch?v={item['id']}",
        })
    return result
