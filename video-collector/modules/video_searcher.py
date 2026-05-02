import time
import requests
from config import PEXELS_API_KEY, PIXABAY_API_KEY

PEXELS_ENDPOINT = "https://api.pexels.com/videos/search"
PIXABAY_ENDPOINT = "https://pixabay.com/api/videos/"
REQUEST_DELAY = 0.3


def _search_pexels(keyword: str) -> list[dict]:
    headers = {"Authorization": PEXELS_API_KEY}
    params = {"query": keyword, "per_page": 3, "orientation": "landscape"}

    resp = requests.get(PEXELS_ENDPOINT, headers=headers, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    results = []
    for video in data.get("videos", []):
        thumbnail = ""
        if video.get("image"):
            thumbnail = video["image"]

        results.append(
            {
                "source": "pexels",
                "video_id": str(video.get("id", "")),
                "title": video.get("url", "").split("/")[-2].replace("-", " ").title(),
                "url": video.get("url", ""),
                "thumbnail": thumbnail,
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

        width = large.get("width", 0)
        height = large.get("height", 0)

        results.append(
            {
                "source": "pixabay",
                "video_id": str(hit.get("id", "")),
                "title": " ".join(hit.get("tags", "").split(",")[:3]).title(),
                "url": hit.get("pageURL", ""),
                "thumbnail": hit.get("userImageURL", ""),
                "duration": hit.get("duration", 0),
                "width": width,
                "height": height,
                "photographer": hit.get("user", ""),
                "license": "Pixabay License",
            }
        )
    return results


def _search_with_fallback(
    search_fn, keywords: list[str]
) -> list[dict]:
    for keyword in keywords:
        time.sleep(REQUEST_DELAY)
        try:
            results = search_fn(keyword)
            if results:
                return results
        except requests.HTTPError as e:
            # 429 rate limit: 대기 후 재시도
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

    return pexels_results + pixabay_results
