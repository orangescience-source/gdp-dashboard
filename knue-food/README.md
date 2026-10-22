# 교원대 연수생 맛집 안내

한국교원대 연수생용 주변 식당 안내 페이지입니다. 빌드 과정이 없는 정적 페이지라 Cloudflare Pages에 그대로 올리면 됩니다.

## 파일
- `index.html` : 페이지 (필터, 지도, 식당 카드)
- `data/restaurants.csv` : 식당 데이터. 이 파일만 고치면 페이지에 반영됩니다.

## 식당 데이터 열 설명
| 열 | 설명 | 예 |
|---|---|---|
| name | 상호 | 교원대 칼국수 |
| category | 한식 / 고기 / 국밥·면 / 중식 / 카페 등 | 국밥·면 |
| menu, price | 대표 메뉴, 1인 가격(원) | 칼국수, 9000 |
| address, lat, lng | 주소, 위도, 경도 (지도 앱에서 확인) | 36.61, 127.35 |
| phone | 전화번호 | 043-000-0000 |
| hours, break_time | 영업시간, 쉬는 시간 (`11:00-21:00` 형식) | 15:00-17:00 |
| closed | 휴무 요일 (여러 개는 `/`로 구분) | 월/화 |
| group_seats | 단체 수용 인원 (10명 이상이면 "저녁 단체"에 표시) | 30 |
| reservation, parking, solo, card | 예약, 주차, 1인 식사, 카드 가능 여부 (Y/N) | Y |
| note | 추천 한마디 | 점심 회전 빠름 |
| checked | 정보 확인 날짜 | 2026-10-22 |
| show | 페이지 표시 여부 (Y/N) | Y |

현재 데이터는 `[예시]` 식당입니다. 실제 식당으로 바꿔 주세요.

## Cloudflare Pages 배포
1. Cloudflare 대시보드 → Workers & Pages → Create → Pages → Connect to Git
2. 이 저장소 선택
3. Build command: 비워 둠 / Build output directory: `knue-food`
4. Save and Deploy → 나온 주소로 QR 코드를 만들면 됩니다.
