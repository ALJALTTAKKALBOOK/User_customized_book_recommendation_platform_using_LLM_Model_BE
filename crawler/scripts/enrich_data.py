import asyncio
import json
import os
import re
from openai import AsyncOpenAI
from dotenv import load_dotenv

# .env에서 OPENAI_API_KEY 로드 (프로젝트 최상위 .env)
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# 파일 경로
DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
INPUT_PATH = os.path.join(DATA_DIR, 'cleaned_books.json')
OUTPUT_PATH = os.path.join(DATA_DIR, 'enriched_books.json')

# ──────────────────────────────────────────────
# LLM 프롬프트
# ──────────────────────────────────────────────
SYSTEM_PROMPT = """너는 도서 분석 전문가야. 주어진 도서 정보를 분석하여 난이도와 핵심 키워드를 JSON으로 응답해.

규칙:
- difficulty: 0~10 정수. 도서의 카테고리와 내용을 고려하여 판정.
  0~2: 입문 (해당 분야를 전혀 모르는 사람도 읽을 수 있는 수준)
  3~4: 초급 (기초 개념을 알면 읽을 수 있는 수준)
  5~6: 중급 (실무 경험이 있는 사람에게 적합한 수준)
  7~8: 고급 (깊은 이해와 경험이 필요한 수준)
  9~10: 전문가 (해당 분야 전문가 수준)
- difficulty_reason: 난이도를 그렇게 판정한 근거를 한 문장으로 설명.
- keywords: 도서의 핵심 주제/개념을 나타내는 구체적 키워드 3~5개. 너무 일반적인 단어는 제외.

JSON 형식으로만 응답해:
{"difficulty": 5, "difficulty_reason": "근거 설명", "keywords": ["키워드1", "키워드2", "키워드3"]}"""


# ──────────────────────────────────────────────
# 리뷰 필터링 (규칙 기반)
# ──────────────────────────────────────────────
JUNK_PATTERNS = [
    r'^(좋아요|추천합니다|만족합니다|잘 읽었습니다|감사합니다)',
    r'^(좋아요|굿|최고|대박|강추|별로|그냥)',
    r'^\d+$',                      # 숫자만
    r'^[ㄱ-ㅎㅏ-ㅣ]+$',            # 자음/모음만
    r'다음이전$',                    # 교보 페이지네이션 잔해
    r'^.{0,3}~+.{0,3}$',           # "만족합니다~~" 같은 패턴
]
JUNK_RE = re.compile('|'.join(JUNK_PATTERNS))
MIN_REVIEW_LENGTH = 20


def filter_reviews(reviews):
    """쓰레기 리뷰를 규칙 기반으로 제거한다."""
    if not reviews or not isinstance(reviews, list):
        return []

    filtered = []
    for r in reviews:
        if not isinstance(r, str):
            continue
        text = r.strip()
        # "다음이전" 접미사 제거
        text = re.sub(r'다음이전$', '', text).strip()
        # 길이 필터
        if len(text) < MIN_REVIEW_LENGTH:
            continue
        # 무의미 패턴 필터
        if JUNK_RE.search(text):
            continue
        filtered.append(text)

    return filtered


# ──────────────────────────────────────────────
# User Prompt 생성
# ──────────────────────────────────────────────
def build_user_prompt(book):
    """도서 정보를 LLM에 전달할 프롬프트로 변환한다."""
    parts = [
        f"제목: {book['title']}",
        f"저자: {book['author']}",
        f"카테고리: {book['sub_category']}",
        f"쪽수: {book.get('page_count') or '정보 없음'}",
        f"\n[책소개]\n{book['summary']}",
    ]

    # 목차 (필수 데이터)
    toc = book.get('table_of_contents') or ''
    if toc.strip():
        # 너무 길면 앞부분만 (토큰 절약)
        if len(toc) > 2000:
            toc = toc[:2000] + "\n... (이하 생략)"
        parts.append(f"\n[목차]\n{toc}")

    # 리뷰 (선택적 데이터, 필터링 후)
    reviews = filter_reviews(book.get('reviews', []))
    if reviews:
        # 최대 10개만
        reviews = reviews[:10]
        reviews_text = "\n".join(f"- {r}" for r in reviews)
        parts.append(f"\n[독자 리뷰]\n{reviews_text}")

    return "\n".join(parts)


# ──────────────────────────────────────────────
# LLM 호출
# ──────────────────────────────────────────────
async def analyze_book(book):
    """한 권의 도서에 대해 LLM으로 difficulty와 keywords를 생성한다."""
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(book)}
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )

        result = json.loads(response.choices[0].message.content)

        difficulty = result.get("difficulty")
        difficulty_reason = result.get("difficulty_reason", "")
        keywords = result.get("keywords", [])

        # 유효성 검사: difficulty
        if not isinstance(difficulty, int) or not (0 <= difficulty <= 10):
            print(f"    [경고] difficulty 범위 초과: {difficulty} → 5로 보정")
            difficulty = 5

        # 유효성 검사: keywords
        if not isinstance(keywords, list) or len(keywords) == 0:
            print(f"    [경고] keywords 비정상: {keywords} → 빈 리스트")
            keywords = []

        return difficulty, difficulty_reason, keywords

    except Exception as e:
        print(f"    [에러] LLM 호출 실패: {e}")
        return 5, "LLM 호출 실패로 기본값 사용", []


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────
async def main():
    print("=" * 50)
    print("BookFit 크롤러 - Step 3.5: 난이도/키워드 생성")
    print("=" * 50)

    # 1. 데이터 로드
    if not os.path.exists(INPUT_PATH):
        print(f"cleaned_books.json이 없습니다. clean_data.py를 먼저 실행하세요.")
        return

    with open(INPUT_PATH, 'r', encoding='utf-8') as f:
        books = json.load(f)
    print(f"도서 {len(books)}권 로드 완료\n")

    # 2. 각 도서에 대해 LLM 호출
    enriched_books = []
    success_count = 0

    for i, book in enumerate(books):
        title_short = book['title'][:40]
        print(f"  ({i+1}/{len(books)}) {title_short}")

        difficulty, reason, keywords = await analyze_book(book)
        print(f"    → 난이도: {difficulty} ({reason[:50]})")
        print(f"    → 키워드: {keywords}")

        # 기존 데이터에 추가
        book["difficulty"] = difficulty
        book["difficulty_reason"] = reason
        book["keywords"] = keywords
        enriched_books.append(book)

        if keywords:  # 키워드가 있으면 성공
            success_count += 1

    # 3. 결과 저장
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(enriched_books, f, ensure_ascii=False, indent=2)

    # 4. 최종 통계
    print(f"\n{'=' * 50}")
    print(f"완료! {len(enriched_books)}권 중 {success_count}권 성공")
    print(f"저장 위치: {OUTPUT_PATH}")

    print(f"\n[난이도 분포]")
    difficulties = [b["difficulty"] for b in enriched_books]
    for level in sorted(set(difficulties)):
        count = difficulties.count(level)
        label = {0: "입문", 1: "입문", 2: "입문",
                 3: "초급", 4: "초급",
                 5: "중급", 6: "중급",
                 7: "고급", 8: "고급",
                 9: "전문가", 10: "전문가"}.get(level, "")
        print(f"  난이도 {level} ({label}): {count}권")

    print(f"\n[리뷰 필터링 통계]")
    total_raw = sum(len(b.get('reviews', []) or []) for b in books)
    total_filtered = sum(len(filter_reviews(b.get('reviews', []) or [])) for b in books)
    print(f"  원본 리뷰: {total_raw}개")
    print(f"  필터링 후: {total_filtered}개 (제거: {total_raw - total_filtered}개)")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    asyncio.run(main())