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

# 대량 처리 설정
SAVE_INTERVAL = 100     # 중간 저장 간격 (권)
MAX_RETRIES = 3         # LLM 호출 실패 시 재시도 횟수
RETRY_DELAY = 5         # 재시도 대기 시간 (초)

# ──────────────────────────────────────────────
# LLM 프롬프트
# ──────────────────────────────────────────────
SYSTEM_PROMPT = """너는 도서 분석 전문가야. 주어진 도서 정보를 분석하여 난이도와 핵심 키워드를 JSON으로 응답해.

규칙:
- difficulty: 0~10 정수. 극단적인 점수를 주는 것을 두려워하지 마라. 쉬운 책은 반드시 낮은 점수를, 어려운 책은 반드시 높은 점수를 줘야 한다. 중간값(4~6)에 편중하지 마라.

[난이도 앵커 기준]
  0: 비전공자/일반인 대상 교양서 (예: "코딩이 뭔지 아무것도 모르는 사람을 위한 책")
  1: 완전 입문서, "혼자 공부하는" 시리즈, "Do it!" 시리즈 입문편
  2: 왕초보 입문서 (예: "누구나 아는 나만 모르는 제미나이", "처음 시작하는 ~" 시리즈)
  3: 기초 교재, 대학 1~2학년 수준 (예: 기초 프로그래밍 교재, 자격증 입문서)
  4: 기초~중급 과도기 (예: 자격증 기출문제집, 기초 개념은 알아야 읽을 수 있는 책)
  5: 중급, 실무 입문 (예: "코딩 자율학습 리액트", 실무 예제 중심 입문서)
  6: 중급~고급, 심화 학습 (예: "모던 리액트 Deep Dive", 디자인 패턴 서적)
  7: 고급, 깊은 이론 + 실무 (예: "Operating System Concepts", 대학원 교재 수준)
  8: 고급~전문가, 특정 분야 깊은 전문서 (예: 커널 프로그래밍, 고급 알고리즘)
  9: 전문가, 최신 연구/아키텍처 수준 (예: 대규모 시스템 설계, 컴파일러 구현)
  10: 최고 전문가, 논문 수준의 난해한 전문서

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
# LLM 호출 (재시도 포함)
# ──────────────────────────────────────────────
async def analyze_book(book):
    """한 권의 도서에 대해 LLM으로 difficulty와 keywords를 생성한다."""
    for attempt in range(1, MAX_RETRIES + 1):
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
            if attempt < MAX_RETRIES:
                print(f"    [재시도 {attempt}/{MAX_RETRIES}] {e}")
                await asyncio.sleep(RETRY_DELAY)
            else:
                print(f"    [에러] LLM 호출 최종 실패: {e}")
                return 5, "LLM 호출 실패로 기본값 사용", []


# ──────────────────────────────────────────────
# Resume 지원
# ──────────────────────────────────────────────
def load_existing_enriched():
    """기존 enriched_books.json이 있으면 로드한다."""
    if os.path.exists(OUTPUT_PATH):
        with open(OUTPUT_PATH, 'r', encoding='utf-8') as f:
            books = json.load(f)
        print(f"기존 데이터 로드: {len(books)}권 (이어서 처리)")
        return books
    return []


def get_enriched_isbns(books):
    """이미 처리된 도서의 ISBN set을 반환한다."""
    return set(book.get("isbn", "") for book in books)


def save_enriched(books):
    """enriched_books.json에 저장한다."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(books, f, ensure_ascii=False, indent=2)


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
    print(f"도서 {len(books)}권 로드 완료")

    # 2. 기존 데이터 로드 (resume 지원)
    enriched_books = load_existing_enriched()
    enriched_isbns = get_enriched_isbns(enriched_books)
    if enriched_isbns:
        print(f"이미 처리된 도서: {len(enriched_isbns)}권 → 스킵")

    # 처리 대상 필터링
    remaining = [b for b in books if b.get("isbn", "") not in enriched_isbns]
    print(f"처리 대상: {len(remaining)}권\n")

    if not remaining:
        print("모든 도서가 이미 처리되었습니다.")
        return

    # 3. 각 도서에 대해 LLM 호출
    save_counter = len(enriched_books)
    success_count = 0

    for i, book in enumerate(remaining):
        title_short = book['title'][:40]
        print(f"  ({i+1}/{len(remaining)}) {title_short}")

        difficulty, reason, keywords = await analyze_book(book)
        print(f"    → 난이도: {difficulty} ({reason[:50]})")
        print(f"    → 키워드: {keywords}")

        # 기존 데이터에 추가
        book["difficulty"] = difficulty
        book["difficulty_reason"] = reason
        book["keywords"] = keywords
        enriched_books.append(book)
        save_counter += 1

        if keywords:
            success_count += 1

        # SAVE_INTERVAL마다 중간 저장
        if save_counter % SAVE_INTERVAL == 0:
            save_enriched(enriched_books)
            print(f"\n  💾 중간 저장 완료: {len(enriched_books)}권\n")

    # 4. 최종 저장
    save_enriched(enriched_books)

    # 5. 최종 통계
    print(f"\n{'=' * 50}")
    print(f"완료! {len(remaining)}권 중 {success_count}권 성공")
    print(f"전체 enriched: {len(enriched_books)}권")
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