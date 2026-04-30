"""YouTube Data API v3 wrapper for niche discovery."""

import os
import re
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv()


def _build_client():
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        raise ValueError("YOUTUBE_API_KEY 환경변수가 설정되지 않았습니다.")
    return build("youtube", "v3", developerKey=api_key)


def extract_channel_id(url_or_id: str) -> Optional[str]:
    """URL 또는 채널ID 문자열에서 채널 ID를 추출합니다."""
    url_or_id = url_or_id.strip()

    # 이미 채널 ID 형식 (UC로 시작하는 24자)
    if re.match(r"^UC[\w-]{22}$", url_or_id):
        return url_or_id

    # @핸들 형식
    handle_match = re.search(r"@([\w.-]+)", url_or_id)
    if handle_match:
        return resolve_handle_to_id(handle_match.group(1))

    # /channel/UC... 형식
    channel_match = re.search(r"/channel/(UC[\w-]{22})", url_or_id)
    if channel_match:
        return channel_match.group(1)

    # /c/ 또는 /user/ 형식
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

        # forHandle이 안 되면 forUsername 시도
        resp = youtube.channels().list(part="id", forUsername=handle).execute()
        items = resp.get("items", [])
        return items[0]["id"] if items else None
    except HttpError:
        return None


def search_political_channels(keyword: str, max_results: int = 10) -> list[dict]:
    """키워드로 정치 관련 채널을 검색합니다."""
    try:
        youtube = _build_client()
        resp = youtube.search().list(
            part="snippet",
            q=keyword,
            type="channel",
            maxResults=min(max_results, 50),
            relevanceLanguage="ko",
            regionCode="KR",
        ).execute()

        channels = []
        for item in resp.get("items", []):
            snippet = item["snippet"]
            channels.append({
                "channel_id": item["id"]["channelId"],
                "title": snippet["channelTitle"],
                "description": snippet.get("description", ""),
                "thumbnail": snippet.get("thumbnails", {}).get("default", {}).get("url", ""),
            })
        return channels
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

        # ── 1단계: channels API로 uploads 플레이리스트 ID 취득 ─────────────
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
            # uploads 플레이리스트가 없는 채널 → search API로 직접 수집
            return _fetch_videos_via_search(youtube, channel_id, max_results)

        # ── 2단계: playlistItems로 영상 수집 ─────────────────────────────
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
                # 플레이리스트 접근 불가 → search API 폴백
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
