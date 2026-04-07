# 크롤러가 접속할 URL들 ex) crawl_list.py에서 카테고리 목록 페이지에 접속할 때 f"{CATEGORY_URL}/3301"처럼 사용
KYOBO_BASE_URL = "https://product.kyobobook.co.kr"
CATEGORY_URL = f"{KYOBO_BASE_URL}/category/KOR"
DETAIL_URL = f"{KYOBO_BASE_URL}/detail"

# 교보문고 카테고리 코드 매핑 - app.core.contants.py의 세부 카테고리 명과 일치해야함.
KYOBO_CATEGORY_CODES = {
    "컴퓨터공학": "3301",
    "IT일반": "3302",
    "OS": "3307",
    "네트워크": "3309",
    "보안/해킹": "3310",
    "데이터베이스": "3311",
    "개발방법론": "3312",
    "웹프로그래밍": "3314",
    "프로그래밍 언어": "3315",
    "모바일프로그래밍": "3316",
}

# ── 크롤링 설정 ──
CRAWL_DELAY = 2             # 요청 간격 (초), 페이지 요청 사이 delay(IP 차단 방지)
MAX_PER_CATEGORY = 700      # 카테고리당 최대 수집 권수
SAVE_INTERVAL = 500         # crawl_detail 중간 저장 간격 (권)
HEADLESS = True             # True: 브라우저 창 숨김 (대량 수집용), False: 디버깅용