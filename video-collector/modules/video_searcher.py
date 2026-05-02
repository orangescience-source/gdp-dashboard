import time
import requests
from config import PEXELS_API_KEY, PIXABAY_API_KEY, YOUTUBE_API_KEY

PEXELS_ENDPOINT = "https://api.pexels.com/videos/search"
PIXABAY_ENDPOINT = "https://pixabay.com/api/videos/"
YOUTUBE_SEARCH_ENDPOINT = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_ENDPOINT = "https://www.googleapis.com/youtube/v3/videos"
REQUEST_DELAY = 0.3

YOUTUBE_CHANNELS = {
    "KTV": "UCbCjBOcGYMmFOlMuanDSMhw",
    "국회방송": "UCbmm3GpGbrh8R-XTAX9HL4g",
    "국방TV": "UCfFbUo5yMFpRTrAT36yKmJA",
}


def _search_pexels(keyword: str) -> list[dict]:
    headers = {"Authorization": PEXELS_API_KEY}
    params = {"query": keyword, "per_page": 3, "orientation": "landscape"}

    resp = requests.get(PEXELS_ENDPOINT, headers=headers, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    results = []
    for video in data.get("videos", []):
        results.append(
            {
                "source": "pexels",
                "video_id": str(video.get("id", "")),
                "title": video.get("url", "").split("/")[-2].replace("-", " ").title(),
                "url": video.get("url", ""),
                "thumbnail": video.get("image", ""),
                "duration": video.get("duration", 0),
                "width": video.get("width", 0),
                "height": video.get("height", 0),
                "photographer": video.get("user", {}).get("name", ""),
                "license": "Pexels License",
            }
        )
    return results


def _search_pixabay(keyword: str) -> list[dict]:
    params = {
        "key": PIXABAY_API_KEY,
        "q": keyword,
        "per_page": 3,
        "video_type": "film",
    }

    resp = requests.get(PIXABAY_ENDPOINT, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    results = []
    for hit in data.get("hits", []):
        videos = hit.get("videos", {})
        large = videos.get("large") or videos.get("medium") or {}

        results.append(
            {
                "source": "pixabay",
                "video_id": str(hit.get("id", "")),
                "title": " ".join(hit.get("tags", "").split(",")[:3]).title(),
                "url": hit.get("pageURL", ""),
                "thumbnail": hit.get("userImageURL", ""),
                "duration": hit.get("duration", 0),
                "width": large.get("width", 0),
                "height": large.get("height", 0),
                "photographer": hit.get("user", ""),
                "license": "Pixabay License",
            }
        )
    return results


def _parse_iso8601_duration(duration: str) -> int:
    import re
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
    if not match:
        return 0
    h = int(match.group(1) or 0)
    m = int(match.group(2) or 0)
    s = int(match.group(3) or 0)
    return h * 3600 + m * 60 + s


def _fetch_video_durations(video_ids: list[str]) -> dict[str, int]:
    if not video_ids or not YOUTUBE_API_KEY:
        return {}
    params = {
        "key": YOUTUBE_API_KEY,
        "id": ",".join(video_ids),
        "part": "contentDetails",
    }
    try:
        resp = requests.get(YOUTUBE_VIDEOS_ENDPOINT, params=params, timeout=10)
        resp.raise_for_status()
        return {
            item["id"]: _parse_iso8601_duration(
                item["contentDetails"]["duration"]
            )
            for item in resp.json().get("items", [])
        }
    except Exception:
        return {}


def _search_youtube_channel(keyword: str, channel_name: str, channel_id: str) -> list[dict]:
    if not YOUTUBE_API_KEY:
        return []

    params = {
        "key": YOUTUBE_API_KEY,
        "channelId": channel_id,
        "q": keyword,
        "type": "video",
        "maxResults": 2,
        "part": "snippet",
        "videoEmbeddable": "true",
    }

    resp = requests.get(YOUTUBE_SEARCH_ENDPOINT, params=params, timeout=10)
    resp.raise_for_status()
    items = resp.json().get("items", [])

    if not items:
        return []

    video_ids = [item["id"]["videoId"] for item in items]
    durations = _fetch_video_durations(video_ids)

    results = []
    for item in items:
        vid = item["id"]["videoId"]
        snippet = item["snippet"]
        thumbnail = (
            snippet.get("thumbnails", {})
            .get("high", snippet.get("thumbnails", {}).get("default", {}))
            .get("url", "")
        )
        results.append(
            {
                "source": f"youtube_{channel_name}",
                "video_id": vid,
                "title": snippet.get("title", ""),
                "url": f"https://www.youtube.com/watch?v={vid}",
                "thumbnail": thumbnail,
                "duration": durations.get(vid, 0),
                "width": 1280,
                "height": 720,
                "photographer": snippet.get("channelTitle", channel_name),
                "license": "YouTube - 공공저작물",
            }
        )
    return results


def _search_youtube_all_channels(keyword: str) -> list[dict]:
    results = []
    for channel_name, channel_id in YOUTUBE_CHANNELS.items():
        time.sleep(REQUEST_DELAY)
        try:
            ch_results = _search_youtube_channel(keyword, channel_name, channel_id)
            results.extend(ch_results)
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 403:
                print(f"  ⚠ YouTube API 할당량 초과 또는 키 오류 ({channel_name})")
            else:
                print(f"  ⚠ YouTube 검색 실패 ({channel_name}): {e}")
    return results


def _search_with_fallback(search_fn, keywords: list[str]) -> list[dict]:
    for keyword in keywords:
        time.sleep(REQUEST_DELAY)
        try:
            results = search_fn(keyword)
            if results:
                return results
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 429:
                print(f"  ⚠ Rate limit 도달, 60초 대기 중...")
                time.sleep(60)
                results = search_fn(keyword)
                if results:
                    return results
    return []


def search_videos(scene: dict) -> list[dict]:
    keywords = scene.get("search_keywords", [])
    if not keywords:
        return []

    pexels_results = _search_with_fallback(_search_pexels, keywords)
    pixabay_results = _search_with_fallback(_search_pixabay, keywords)
    youtube_results = _search_youtube_all_channels(keywords[0])

    return pexels_results + pixabay_results + youtube_results
