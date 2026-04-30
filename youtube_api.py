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
            maxResults=max_results,
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
    """채널의 최근 영상 목록을 가져옵니다 (최대 200개)."""
    try:
        youtube = _build_client()

        # uploads 플레이리스트 ID 가져오기
        ch_resp = youtube.channels().list(
            part="contentDetails",
            id=channel_id,
        ).execute()
        items = ch_resp.get("items", [])
        if not items:
            raise ValueError(f"채널을 찾을 수 없습니다: {channel_id}")

        uploads_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

        videos = []
        page_token = None
        fetched = 0

        while fetched < max_results:
            batch = min(50, max_results - fetched)
            pl_resp = youtube.playlistItems().list(
                part="snippet,contentDetails",
                playlistId=uploads_id,
                maxResults=batch,
                pageToken=page_token,
            ).execute()

            video_ids = [
                item["contentDetails"]["videoId"]
                for item in pl_resp.get("items", [])
            ]

            if not video_ids:
                break

            # 조회수 등 상세 정보 일괄 조회
            stats_resp = youtube.videos().list(
                part="statistics,snippet",
                id=",".join(video_ids),
            ).execute()

            for item in stats_resp.get("items", []):
                snippet = item["snippet"]
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
                videos.append({
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

            fetched += len(video_ids)
            page_token = pl_resp.get("nextPageToken")
            if not page_token:
                break

        # 최신순 정렬
        videos.sort(key=lambda v: v["published_at"], reverse=True)
        return videos

    except HttpError as e:
        raise RuntimeError(f"영상 목록 조회 실패: {e}") from e
