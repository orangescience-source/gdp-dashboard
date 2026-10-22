"""카카오 로컬 API로 교원대 주변 음식점·카페를 수집해 CSV로 저장합니다.

인증: 클라우드 환경의 네트워크 시크릿이 Authorization 헤더를 붙여 줍니다.
로컬에서 돌릴 때는 KAKAO_REST_API_KEY 환경 변수를 쓰면 됩니다.

실행: python3 knue-food/scripts/collect_kakao.py [반경km=3]
결과: knue-food/data/kakao_raw.csv (검토용, 페이지에는 아직 안 보임)
"""
import csv, json, math, os, sys, time, urllib.parse, urllib.request
from pathlib import Path

BASE_LAT, BASE_LNG = 36.6098, 127.3561  # 한국교원대
RADIUS_KM = float(sys.argv[1]) if len(sys.argv) > 1 else 3.0
CATEGORIES = {"FD6": None, "CE7": "카페"}  # 음식점, 카페
OUT = Path(__file__).resolve().parent.parent / "data" / "kakao_raw.csv"
URL = "https://dapi.kakao.com/v2/local/search/category.json"

FIELDS = ["name", "category", "menu", "price", "address", "lat", "lng", "phone",
          "hours", "break_time", "closed", "group_seats", "reservation", "parking",
          "solo", "card", "note", "checked", "show", "dist_km", "kakao_url", "kakao_category"]


def call(params):
    req = urllib.request.Request(URL + "?" + urllib.parse.urlencode(params))
    key = os.environ.get("KAKAO_REST_API_KEY")
    if key:
        req.add_header("Authorization", f"KakaoAK {key}")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def dist_km(lat, lng):
    r = math.radians
    h = (math.sin(r(lat - BASE_LAT) / 2) ** 2
         + math.cos(r(BASE_LAT)) * math.cos(r(lat)) * math.sin(r(lng - BASE_LNG) / 2) ** 2)
    return 2 * 6371 * math.asin(math.sqrt(h))


def search_rect(code, x1, y1, x2, y2, depth=0):
    """한 영역에서 최대 45곳만 주므로, 꽉 차면 4등분해 다시 검색합니다."""
    rect = f"{x1},{y1},{x2},{y2}"
    first = call({"category_group_code": code, "rect": rect, "page": 1, "size": 15})
    total = first["meta"]["pageable_count"]
    if total >= 45 and depth < 6:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        out = []
        for a in [(x1, y1, mx, my), (mx, y1, x2, my), (x1, my, mx, y2), (mx, my, x2, y2)]:
            out += search_rect(code, *a, depth + 1)
        return out
    docs, page, data = [], 1, first
    while True:
        docs += data["documents"]
        if data["meta"]["is_end"]:
            return docs
        page += 1
        time.sleep(0.1)
        data = call({"category_group_code": code, "rect": rect, "page": page, "size": 15})


def main():
    dlat = RADIUS_KM / 111.0
    dlng = RADIUS_KM / (111.0 * math.cos(math.radians(BASE_LAT)))
    box = (BASE_LNG - dlng, BASE_LAT - dlat, BASE_LNG + dlng, BASE_LAT + dlat)

    places = {}
    for code, fixed in CATEGORIES.items():
        for d in search_rect(code, *box):
            lat, lng = float(d["y"]), float(d["x"])
            km = dist_km(lat, lng)
            if km > RADIUS_KM:
                continue
            # "음식점 > 한식 > 해장국" → "한식"
            parts = [p.strip() for p in d["category_name"].split(">")]
            places[d["id"]] = {
                "name": d["place_name"],
                "category": fixed or (parts[1] if len(parts) > 1 else parts[0]),
                "address": d["road_address_name"] or d["address_name"],
                "lat": f"{lat:.6f}", "lng": f"{lng:.6f}",
                "phone": d["phone"],
                "show": "N",  # 검토 후 Y로 바꾼 곳만 페이지에 표시
                "dist_km": f"{km:.2f}",
                "kakao_url": d["place_url"],
                "kakao_category": d["category_name"],
            }

    rows = sorted(places.values(), key=lambda p: float(p["dist_km"]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)}곳 저장 → {OUT}")


if __name__ == "__main__":
    main()
