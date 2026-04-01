"""
embedder.py — enriched_books.json → embedded_books.json

enriched_books.json을 읽어 팀장 확정 벡터화 포맷으로 텍스트를 조합한 뒤,
OpenAI text-embedding-3-small 모델로 1536차원 임베딩 벡터를 생성한다.

실행 방법:
    cd BE/crawler
    python scripts/embedder.py

입력: data/enriched_books.json
출력: data/embedded_books.json
"""

import asyncio
import json
import os
import sys
import logging
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI

# 설정
EMBEDDING_MODEL = "text-embedding-3-small"   # 1536차원, 백엔드 part와 통일
BATCH_SIZE = 100                              # 배치당 도서 수 (rate limit 대비)
MAX_CONCURRENT = 3                            # 동시 API 호출 수

# 경로 (crawler/ 기준 상대 경로)
BASE_DIR = Path(__file__).resolve().parent.parent  # crawler/
INPUT_PATH = BASE_DIR / "data" / "enriched_books.json"
OUTPUT_PATH = BASE_DIR / "data" / "embedded_books.json"

# 로깅
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# 벡터화 텍스트 조합 (확정 포맷)
def build_embedding_text(book: dict) -> str:
    """
    확정 벡터화 포맷:
    f"카테고리: {sub_category}\\n난이도: {difficulty}\\n키워드: {keywords_str}\\n줄거리: {summary}"
    """
    sub_category = book.get("sub_category", "")
    difficulty = book.get("difficulty", "")
    keywords = book.get("keywords", [])
    summary = book.get("summary", "")

    keywords_str = ", ".join(keywords)

    return (
        f"카테고리: {sub_category}\n"
        f"난이도: {difficulty}\n"
        f"키워드: {keywords_str}\n"
        f"줄거리: {summary}"
    )

# 임베딩 생성 (배치 + 비동기)
async def embed_batch(
    client: AsyncOpenAI,
    texts: list[str],
    semaphore: asyncio.Semaphore,
) -> list[list[float]]:
    """텍스트 리스트를 한 번의 API 호출로 임베딩. semaphore로 동시 호출 제한."""
    async with semaphore:
        response = await client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=texts,
        )
        return [item.embedding for item in response.data]


async def generate_all_embeddings(
    client: AsyncOpenAI,
    books: list[dict],
) -> list[list[float]]:
    """전체 도서 목록을 BATCH_SIZE 단위로 분할하여 임베딩 생성."""
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    all_embeddings: list[list[float]] = []

    # 벡터화 텍스트 미리 생성
    texts = [build_embedding_text(book) for book in books]
    total = len(texts)

    logger.info(f"총 {total}권 임베딩 시작 (배치 크기: {BATCH_SIZE})")

    # 배치 분할
    tasks = []
    for i in range(0, total, BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        tasks.append(embed_batch(client, batch, semaphore))

    # 비동기 실행
    results = await asyncio.gather(*tasks)

    for result in results:
        all_embeddings.extend(result)

    logger.info(f"임베딩 생성 완료: {len(all_embeddings)}건")
    return all_embeddings


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────
async def main():
    # .env 로드 (프로젝트 최상단 BE/.env)
    env_path = BASE_DIR.parent / ".env"
    load_dotenv(dotenv_path=env_path)

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY가 .env에 설정되어 있지 않습니다.")
        sys.exit(1)

    client = AsyncOpenAI(api_key=api_key)

    # 1) 입력 파일 읽기
    if not INPUT_PATH.exists():
        logger.error(f"입력 파일이 없습니다: {INPUT_PATH}")
        sys.exit(1)

    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        books = json.load(f)

    logger.info(f"입력 파일 로드 완료: {len(books)}권")

    # 2) 임베딩 생성
    embeddings = await generate_all_embeddings(client, books)

    # 3) 각 도서에 embedding 필드 추가
    for book, embedding in zip(books, embeddings):
        book["embedding"] = embedding

    # 4) 출력 파일 저장
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(books, f, ensure_ascii=False, indent=2)

    logger.info(f"출력 파일 저장 완료: {OUTPUT_PATH}")

    # 5) 검증 로그
    sample = books[0]
    emb = sample["embedding"]
    logger.info(
        f"검증 — 첫 번째 도서: '{sample['title']}', "
        f"임베딩 차원: {len(emb)}, "
        f"벡터 앞 3개: {emb[:3]}"
    )


if __name__ == "__main__":
    asyncio.run(main())