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
RETRY_DELAY = 10         # 재시도 대기 시간 (초)
CONCURRENT_LIMIT = 3   # 동시 처리할 도서 수

# ──────────────────────────────────────────────
# LLM 프롬프트 (1) - 난이도/키워드 추출
# ──────────────────────────────────────────────
# ⚠️ 이 키워드 스키마는 app/domains/recommendations/...의 generate_hyde_node와
#    반드시 동일하게 유지해야 한다. 한 쪽 수정 시 다른 쪽도 반드시 같이 수정할 것.
SYSTEM_PROMPT = """너는 도서 분석 전문가야. 주어진 도서 정보를 분석하여 난이도와 핵심 키워드를 JSON으로 응답해.

[난이도 - difficulty]
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

[키워드 - keywords]
도서를 다각도로 표현하는 키워드 정확히 5개를 추출한다. 아래 3개 축을 반드시 모두 포함시켜라.

1. 주제 (topic) — 2개
   책이 다루는 핵심 개념/기술/언어. 구체적으로 작성하라.
   예: "인공지능", "기계학습", "리액트", "운영체제", "TCP/IP", "SQL", "디자인 패턴"
   ※ 너무 일반적인 단어("프로그래밍", "컴퓨터")는 피하라.

2. 접근방식 (approach) — 1~2개
   책의 서술 관점/형식. 아래 어휘 중에서만 선택하라:
   ["역사적 관점", "사례 중심", "이론 중심", "실습 중심", "개념 정리",
    "튜토리얼", "레퍼런스", "프로젝트 기반", "비교 분석", "시각적 설명",
    "딥다이브", "문제 해결 중심"]

3. 대상/성격 (target) — 1~2개
   독자층 또는 책의 성격. 아래 어휘 중에서만 선택하라:
   ["비전공자 교양서", "입문자용", "중급자용", "실무자용", "연구자용",
    "수험서", "참고서", "기초 학습서", "심화 학습서"]

[중요 지침]
- 줄거리/목차/리뷰에 "역사", "사례", "처음 배우는", "그림으로", "쉽게" 같은 표현이 보이면 반드시 approach/target에 명시적으로 반영하라.
- 메타 키워드("역사적 관점", "비전공자 교양서")가 "일반적"이라는 이유로 빼지 마라. 그게 책의 정체성이다.
- 5개를 하나의 리스트로 합쳐서 응답하라. 축 라벨은 붙이지 않는다.
- approach/target은 반드시 위 어휘 목록 안에서만 선택하라. 새 표현을 만들지 마라.

[키워드 예시]
- "기계는 어떻게 생각하는가?" (AI 역사 5가지 사건을 비전공자에게 설명)
  → ["인공지능", "기계학습", "역사적 관점", "사례 중심", "비전공자 교양서"]
- "모던 리액트 Deep Dive" (리액트 내부 동작 원리 심화)
  → ["리액트", "프론트엔드", "이론 중심", "딥다이브", "실무자용"]
- "혼자 공부하는 파이썬" (파이썬 기초 문법 단계별)
  → ["파이썬", "프로그래밍 언어", "튜토리얼", "실습 중심", "입문자용"]
- "OSI 7계층 그림으로 이해하기" (네트워크 기초 시각화)
  → ["네트워크 기초", "OSI 7계층", "시각적 설명", "개념 정리", "입문자용"]

JSON 형식으로만 응답해:
{"difficulty": 5, "difficulty_reason": "근거 설명", "keywords": ["키워드1", "키워드2", "키워드3", "키워드4", "키워드5"]}"""

# ──────────────────────────────────────────────
# LLM 프롬프트 (2) - short_summary 생성  [v1 신규]
# ──────────────────────────────────────────────
# short_summary는 임베딩 텍스트 생성 전용. 키워드/난이도 추출과는 독립이다.
# v2에서는 이 short_summary가 키워드/난이도 추출의 입력으로도 사용될 예정.
SHORT_SUMMARY_PROMPT = """너는 도서 요약 전문가야. 주어진 책 정보를 100자 이내의 한 문장으로 압축한다.

[작성 규칙]
- 100자 이내, 한 문장.
- 다음 3가지를 반드시 포함:
  1. 주제 (어떤 기술/개념을 다루는가)
  2. 대상 (누구를 위한 책인가 — 입문자/실무자/연구자/비전공자 등)
  3. 접근법 (어떻게 가르치는가 — 사례 중심/실습 중심/이론 중심/역사적 관점/튜토리얼 등)

[절대 금지]
- 출판사 마케팅 문구 ("최고의", "필독서", "베스트셀러", "쉽게 배우는", "당신의 인생을 바꿀")
- 추상적 표현 ("새 시대의", "혁신적인", "독보적인")
- 단순 칭찬어 ("정말 좋은", "훌륭한")

[좋은 예시]
- "AI의 5가지 역사적 사건을 통해 인공지능과 기계학습의 발전사를 비전공자에게 설명하는 교양서."
- "리액트의 내부 동작 원리와 렌더링 메커니즘을 실무자 대상으로 심화 분석한 책."
- "플러터로 안드로이드와 iOS 앱을 동시 개발하는 방법을 입문자에게 단계별로 가르치는 튜토리얼."
- "OSI 7계층과 TCP/IP 프로토콜을 그림과 비유로 설명한 네트워크 입문서."

[나쁜 예시 - 피할 것]
- "정말 멋진 책으로, 모든 개발자가 꼭 읽어야 할 필독서." (마케팅 문구, 정보 없음)
- "당신의 인생을 바꿀 프로그래밍 책." (추상적, 무엇을 가르치는지 불명)
- "이 책은 좋은 책입니다." (정보 없음)

JSON 형식으로만 응답:
{"short_summary": "100자 이내 한 문장"}"""

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
# User Prompt 생성 (1) - 난이도/키워드용
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
# User Prompt 생성 (2) - short_summary용  [v1 신규]
# ──────────────────────────────────────────────
def build_short_summary_input(book):
    """short_summary 생성용 LLM 입력.
    리뷰는 주관적 노이즈가 클 수 있어 제외, 목차+책소개만 사용한다.
    """
    parts = [
        f"제목: {book['title']}",
        f"저자: {book['author']}",
        f"카테고리: {book['sub_category']}",
        f"\n[원본 책소개]\n{book['summary']}",
    ]
    toc = book.get('table_of_contents') or ''
    if toc.strip():
        if len(toc) > 1500:
            toc = toc[:1500] + "\n... (이하 생략)"
        parts.append(f"\n[목차]\n{toc}")
    return "\n".join(parts)


# ──────────────────────────────────────────────
# LLM 호출 (1) - 난이도/키워드 추출
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
                print(f"    [재시도 {attempt}/{MAX_RETRIES}] analyze: {e}")
                await asyncio.sleep(RETRY_DELAY)
            else:
                print(f"    [에러] analyze 최종 실패: {e}")
                return 5, "LLM 호출 실패로 기본값 사용", []


# ──────────────────────────────────────────────
# LLM 호출 (2) - short_summary 생성  [v1 신규]
# ──────────────────────────────────────────────
async def generate_short_summary(book):
    """한 권의 도서에 대해 100자 이내 short_summary를 생성한다.
    임베딩 텍스트 전용. 키워드/난이도 추출과는 독립적인 LLM 호출.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": SHORT_SUMMARY_PROMPT},
                    {"role": "user", "content": build_short_summary_input(book)}
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
            )

            result = json.loads(response.choices[0].message.content)
            short = result.get("short_summary", "").strip()

            # 길이 검사 및 fallback
            if len(short) > 120:
                print(f"    [경고] short_summary 길이 초과: {len(short)}자 → 100자로 절단")
                short = short[:100]
            if not short:
                print(f"    [경고] short_summary 비어있음 → 제목으로 대체")
                short = book['title']

            return short

        except Exception as e:
            if attempt < MAX_RETRIES:
                print(f"    [재시도 {attempt}/{MAX_RETRIES}] short_summary: {e}")
                await asyncio.sleep(RETRY_DELAY)
            else:
                print(f"    [에러] short_summary 최종 실패: {e}")
                return book['title']  # fallback


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
    """이미 처리된 도서의 ISBN set을 반환한다.
    short_summary까지 모두 있는 책만 '완료'로 간주한다.
    """
    return set(
        book.get("isbn", "")
        for book in books
        if book.get("short_summary")  # short_summary 있어야 완료
    )


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
    print("BookFit 크롤러 - Step 3.5: 난이도/키워드/short_summary 생성")
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
    print(f"처리 대상: {len(remaining)}권")
    print(f"동시 처리: {CONCURRENT_LIMIT}권\n")

    if not remaining:
        print("모든 도서가 이미 처리되었습니다.")
        return

    # 3. 병렬 처리 준비
    sem = asyncio.Semaphore(CONCURRENT_LIMIT)
    save_lock = asyncio.Lock()  # 중간 저장 시 동시 쓰기 방지
    completed_count = [0]  # 완료 카운터 (리스트로 감싸서 클로저에서 mutate 가능)
    total = len(remaining)

    async def process_one(book, index):
        """한 권을 처리하고 결과를 enriched_books에 추가한다.
        두 LLM 호출(analyze + short_summary)을 병렬로 실행한다.
        """
        async with sem:  # 동시 실행 수 제한
            title_short = book['title'][:40]

            # 두 LLM 호출을 병렬로 (총 시간은 단일 호출과 비슷)
            (difficulty, reason, keywords), short_summary = await asyncio.gather(
                analyze_book(book),
                generate_short_summary(book)
            )

            book["difficulty"] = difficulty
            book["difficulty_reason"] = reason
            book["keywords"] = keywords
            book["short_summary"] = short_summary

            async with save_lock:
                enriched_books.append(book)
                completed_count[0] += 1
                done = completed_count[0]

                # 진행률 출력 (10권마다)
                if done % 10 == 0 or done == total:
                    print(
                        f"  [{done}/{total}] {title_short} → "
                        f"난이도 {difficulty}, 키워드 {len(keywords)}개, short {len(short_summary)}자"
                    )

                # 중간 저장
                if done % SAVE_INTERVAL == 0:
                    save_enriched(enriched_books)
                    print(f"\n  💾 중간 저장 완료: {len(enriched_books)}권\n")

            return keywords  # 성공 여부 판단용

    # 4. 모든 책을 병렬로 처리
    tasks = [process_one(book, i) for i, book in enumerate(remaining)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 5. 최종 저장
    save_enriched(enriched_books)

    # 6. 통계
    success_count = sum(1 for r in results if isinstance(r, list) and len(r) > 0)
    error_count = sum(1 for r in results if isinstance(r, Exception))

    print(f"\n{'=' * 50}")
    print(f"완료! {len(remaining)}권 중 {success_count}권 성공, {error_count}권 실패")
    print(f"전체 enriched: {len(enriched_books)}권")
    print(f"저장 위치: {OUTPUT_PATH}")

    if error_count > 0:
        print(f"\n[실패한 작업]")
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                print(f"  - {remaining[i]['title'][:40]}: {r}")

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

    # ── v1 신규: short_summary 길이 분포
    print(f"\n[short_summary 길이 분포]")
    short_lengths = [len(b.get('short_summary', '')) for b in enriched_books]
    if short_lengths:
        avg_len = sum(short_lengths) / len(short_lengths)
        over_100 = sum(1 for l in short_lengths if l > 100)
        empty = sum(1 for l in short_lengths if l == 0)
        print(f"  평균: {avg_len:.1f}자")
        print(f"  최소: {min(short_lengths)}자  /  최대: {max(short_lengths)}자")
        print(f"  100자 초과: {over_100}권 ({over_100/len(short_lengths)*100:.1f}%)")
        print(f"  비어있음: {empty}권")

    print(f"\n[리뷰 필터링 통계]")
    total_raw = sum(len(b.get('reviews', []) or []) for b in books)
    total_filtered = sum(len(filter_reviews(b.get('reviews', []) or [])) for b in books)
    print(f"  원본 리뷰: {total_raw}개")
    print(f"  필터링 후: {total_filtered}개 (제거: {total_raw - total_filtered}개)")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    asyncio.run(main())