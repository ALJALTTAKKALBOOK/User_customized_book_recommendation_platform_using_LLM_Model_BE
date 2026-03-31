"""
load_to_db.py — embedded_books.json → POST /books/ API → DB 적재

embedded_books.json을 읽어 BookCreateRequest 형식으로 변환한 뒤,
FastAPI 서버의 POST /books/ 엔드포인트를 호출하여 DB에 적재한다.

선행 조건:
    1. docker-compose up -d  (PostgreSQL + pgvector 실행)
    2. uvicorn app.main:app --reload  (FastAPI 서버 실행)

실행 방법:
    cd BE/crawler
    python scripts/load_to_db.py

입력: data/embedded_books.json
"""

import asyncio
import json
import sys
import logging
from pathlib import Path

import httpx

# 설정
API_BASE_URL = "http://localhost:8000"
BOOKS_ENDPOINT = f"{API_BASE_URL}/api/books/"
MAX_CONCURRENT = 5          # 동시 API 요청 수
REQUEST_TIMEOUT = 30.0      # 요청 타임아웃 (초)

# 경로
BASE_DIR = Path(__file__).resolve().parent.parent  # crawler/
INPUT_PATH = BASE_DIR / "data" / "embedded_books.json"

# BookCreateRequest에 없는 필드 (제외 대상)
EXCLUDE_FIELDS = {"table_of_contents", "reviews", "url", "difficulty_reason"}

# 로깅
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# 데이터 변환
def transform_book(book: dict) -> dict:
    """
    enriched/embedded 데이터를 BookCreateRequest 형식으로 변환.

    변환 사항:
    - grade_point: float(10점 만점) → int(100점 만점), null은 None 유지
    - published_at: "2025-08-12" → "2025-08-12T00:00:00" (ISO 형식)
    - EXCLUDE_FIELDS에 해당하는 필드 제거
    """
    payload = {}

    for key, value in book.items():
        # 스키마에 없는 필드 제외
        if key in EXCLUDE_FIELDS:
            continue

        # grade_point 변환: 9.7 → 97, null → None
        if key == "grade_point":
            payload[key] = round(value * 10) if value is not None else None
            continue

        # published_at 변환: "2025-08-12" → "2025-08-12T00:00:00"
        if key == "published_at":
            payload[key] = f"{value}T00:00:00" if value is not None else None
            continue

        payload[key] = value

    return payload

# API 호출
async def post_book(
    client: httpx.AsyncClient,
    payload: dict,
    semaphore: asyncio.Semaphore,
    index: int,
) -> dict:
    """단일 도서 POST 요청. 결과를 dict로 반환."""
    title = payload.get("title", "제목 없음")

    async with semaphore:
        try:
            response = await client.post(BOOKS_ENDPOINT, json=payload)

            if response.status_code == 201:
                logger.info(f"[{index}] ✅ 성공: {title}")
                return {"title": title, "status": "success"}

            elif response.status_code == 400:
                detail = response.json().get("detail", "")
                if "이미 존재하는 ISBN" in detail:
                    logger.warning(f"[{index}] ⏭️ 중복 스킵: {title} ({detail})")
                    return {"title": title, "status": "duplicate"}
                else:
                    logger.error(f"[{index}] ❌ 실패: {title} — 400: {detail}")
                    return {"title": title, "status": "error", "detail": detail}

            else:
                detail = response.text[:200]
                logger.error(f"[{index}] ❌ 실패: {title} — {response.status_code}: {detail}")
                return {"title": title, "status": "error", "detail": detail}

        except httpx.RequestError as e:
            logger.error(f"[{index}] ❌ 요청 에러: {title} — {e}")
            return {"title": title, "status": "error", "detail": str(e)}


async def load_all_books(books: list[dict]):
    """전체 도서를 비동기로 POST 요청."""
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        tasks = [
            post_book(client, transform_book(book), semaphore, i + 1)
            for i, book in enumerate(books)
        ]
        results = await asyncio.gather(*tasks)

    return results

# 결과 리포트
def print_report(results: list[dict]):
    """적재 결과 요약 출력."""
    success = [r for r in results if r["status"] == "success"]
    duplicate = [r for r in results if r["status"] == "duplicate"]
    error = [r for r in results if r["status"] == "error"]

    logger.info("=" * 50)
    logger.info(f"적재 결과: 성공 {len(success)} / 중복 {len(duplicate)} / 실패 {len(error)} (총 {len(results)})")
    logger.info("=" * 50)

    if error:
        logger.error("실패 목록:")
        for r in error:
            logger.error(f"  - {r['title']}: {r.get('detail', '')}")

# 메인
async def main():
    # 1) 입력 파일 읽기
    if not INPUT_PATH.exists():
        logger.error(f"입력 파일이 없습니다: {INPUT_PATH}")
        logger.error("embedder.py를 먼저 실행하세요.")
        sys.exit(1)

    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        books = json.load(f)

    logger.info(f"입력 파일 로드: {len(books)}권")

    # 2) 서버 상태 확인
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            health = await client.get(f"{API_BASE_URL}/docs")
            if health.status_code != 200:
                logger.error("FastAPI 서버 응답 이상. 서버 상태를 확인하세요.")
                sys.exit(1)
    except httpx.RequestError:
        logger.error(
            "FastAPI 서버에 연결할 수 없습니다.\n"
            "  1. docker-compose up -d\n"
            "  2. uvicorn app.main:app --reload\n"
            "위 두 명령을 먼저 실행하세요."
        )
        sys.exit(1)

    logger.info("서버 연결 확인 완료")

    # 3) API 호출로 DB 적재
    results = await load_all_books(books)

    # 4) 결과 리포트
    print_report(results)


if __name__ == "__main__":
    asyncio.run(main())