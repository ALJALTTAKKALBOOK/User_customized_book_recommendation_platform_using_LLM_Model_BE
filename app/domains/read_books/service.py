import logging
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.domains.read_books.model import ReadBook
from app.domains.users.model import User
from app.core.llm_helper import generate_json_with_llm
from app.core.database import AsyncSessionLocal
from app.domains.read_books.schema import BookAddRequest, ReviewUpdateRequest, ReviewCreate

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# 1. 상수 정의 (프롬프트 및 점수 매핑표)
# -----------------------------------------------------------------------------

READ_BOOK_EVALUATION_PROMPT = """너는 사용자의 독서 근력을 평가하는 '독서 수준 평가 전문가'야. 
사용자가 구조화하여 작성한 [배운 점]과 [어려웠던 점], 그리고 [체감 난이도] 텍스트를 종합하여 순수한 JSON 객체로 응답해.

1. "domain": 독후감의 핵심 분야 (예: 경제, 소설, 과학 등)
2. "change": 사용자의 이해도 성장 수치 (-5 ~ +5 정수)

[구조화된 텍스트 평가 가이드]
* 메타인지 보너스: 사용자가 [어려웠던 점]을 명확히 인지하고 구체적으로 적었다면, 한계를 아는 훌륭한 독서이므로 가산점(+1~+2)을 줘.
* 지식 습득 보너스: [배운 점]에 핵심 내용이나 인사이트가 잘 적혀있다면 높은 점수(+3~+5)를 줘.
* 체감 난이도 보정: 체감 난이도가 '어려웠다'일 때 포기하지 않은 흔적이 보이면 점수를 후하게 주고, '쉬웠다'일 때는 평가 기준을 조금 엄격하게 잡아.
* 무조건 감점 (-1 ~ -5): 질문에 맞지 않는 대충 쓴 텍스트("없음", "ㅋㅋ"), 책 내용 왜곡, 욕설 등은 가차 없이 감점해.
"""

# 후기가 없을 때(Track 2) 또는 LLM 에러 시 사용할 고정 점수 매핑표
DIFFICULTY_SCORE_MAP = {
    "너무 쉬웠다": 2,    "1": 2,
    "쉬웠다": 1,        "2": 1,
    "읽을만 했다": 0,    "3": 0,
    "이해가 잘 안된다": -1, "4": -1,
    "무슨의미인지 아예모르겠다": -2, "5": -2
}

# -----------------------------------------------------------------------------
# 2. 비즈니스 로직 (서비스 함수들)
# -----------------------------------------------------------------------------

# 처음에 책을 서재에 담기만 할 때 (난이도, 후기 없음)
async def add_book_to_library_service(db: AsyncSession, user_id: int, data: BookAddRequest):
    new_book = ReadBook(
        user_id=user_id,
        book_id=data.book_id,
        feeling_difficulty=None, # 아직 안 읽었으므로 비워둠
        review=None              # 아직 후기 없음
    )
    db.add(new_book)
    await db.commit()
    await db.refresh(new_book)
    
    #  책만 담았을 경우 레벨 업데이트를 하지 않음
    return new_book


#  나중에 다 읽고 후기/난이도를 남길 때 (업데이트 및 레벨 반영)
async def update_review_service(
    db: AsyncSession, 
    read_book_id: int, 
    user_id: int, 
    data: ReviewUpdateRequest, 
    background_tasks: BackgroundTasks
):
    # 1. 서재에 책이 있는지 확인
    result = await db.execute(
        select(ReadBook).filter(ReadBook.id == read_book_id, ReadBook.user_id == user_id)
    )
    book_entry = result.scalar_one_or_none()
    
    if not book_entry:
        raise HTTPException(status_code=404, detail="내 서재에서 해당 책을 찾을 수 없습니다.")

    # 2. 구조화된 2개의 답변을 하나의 텍스트로 예쁘게 조립
    review_parts = []
    if data.learned_content and data.learned_content.strip():
        review_parts.append(f"[새롭게 배운 점]\n{data.learned_content.strip()}")
    if data.hard_content and data.hard_content.strip():
        review_parts.append(f"[어려웠던 점]\n{data.hard_content.strip()}")
    
    full_review_text = "\n\n".join(review_parts) if review_parts else None

    # 3. DB 정보 업데이트 (난이도 및 조립된 리뷰)
    book_entry.review = full_review_text
    book_entry.feeling_difficulty = data.feeling_difficulty
    await db.commit()
    await db.refresh(book_entry)
    
    # 4. 백그라운드로 유저 레벨 업데이트 던지기
    background_tasks.add_task(
        run_profiling_task, 
        user_id=user_id, 
        content=full_review_text, 
        feeling_difficulty=data.feeling_difficulty,
        default_category=data.category 
    )
    
    return book_entry


# 과거에 읽은 책을 "등록과 동시에" 후기까지 작성할 때
async def create_review_service(
    db: AsyncSession, 
    user_id: int, 
    data: ReviewCreate, 
    background_tasks: BackgroundTasks
):
    # 텍스트 조립
    review_parts = []
    if data.learned_content and data.learned_content.strip():
        review_parts.append(f"[새롭게 배운 점]\n{data.learned_content.strip()}")
    if data.hard_content and data.hard_content.strip():
        review_parts.append(f"[어려웠던 점]\n{data.hard_content.strip()}")
    
    full_review_text = "\n\n".join(review_parts) if review_parts else None

    new_review = ReadBook(
        user_id=user_id,
        book_id=data.book_id, 
        review=full_review_text, 
        feeling_difficulty=data.feeling_difficulty 
    )
    db.add(new_review)
    await db.commit()
    await db.refresh(new_review)
    
    background_tasks.add_task(
        run_profiling_task, 
        user_id=user_id, 
        content=full_review_text, 
        feeling_difficulty=data.feeling_difficulty,
        default_category=data.category 
    )
    return new_review

# -----------------------------------------------------------------------------
# 3. 백그라운드 태스크 (LLM & 유저 레벨 DB 업데이트 로직)
# -----------------------------------------------------------------------------

async def run_profiling_task(user_id: int, content: str | None, feeling_difficulty: str, default_category: str):
    async with AsyncSessionLocal() as session:
        change = 0
        domain = default_category 

        # 후기가 작성된 경우 (조립된 텍스트가 있을 때) -> LLM 분석
        if content and content.strip(): 
            user_prompt = f"[체감 난이도]: {feeling_difficulty}\n[작성된 리뷰]:\n{content}"
            
            analysis_result = await generate_json_with_llm(
                system_prompt=READ_BOOK_EVALUATION_PROMPT,
                user_prompt=user_prompt,
                temperature=0.3
            )
            
            if analysis_result:
                domain = str(analysis_result.get("domain", default_category)).strip()
                try:
                    change = max(-5, min(5, int(analysis_result.get("change", 0))))
                except ValueError:
                    change = 0 
            else:
                logger.warning(f"User {user_id} LLM 분석 실패, 고정 점수로 Fallback")
                safe_key = feeling_difficulty.replace(" ", "").strip()
                fallback_score = {"너무쉬웠다": 2, "쉬웠다": 1, "읽을만했다": 0, "이해가잘안된다": -1, "무슨의미인지아예모르겠다": -2}.get(safe_key, 0)
                change = DIFFICULTY_SCORE_MAP.get(feeling_difficulty, fallback_score)

        # 후기가 없는 경우 -> LLM 안 부르고 매핑표 점수 즉시 반영
        else:
            safe_key = feeling_difficulty.replace(" ", "").strip()
            fallback_score = {"너무쉬웠다": 2, "쉬웠다": 1, "읽을만했다": 0, "이해가잘안된다": -1, "무슨의미인지아예모르겠다": -2}.get(safe_key, 0)
            change = DIFFICULTY_SCORE_MAP.get(feeling_difficulty, fallback_score)
            logger.info(f"User {user_id} 후기 없음, 체감 난이도({feeling_difficulty}) 기반 {change}점 부여")

        # [공통] 유저 레벨 업데이트
        result = await session.execute(select(User).filter(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if user:
            levels = dict(user.domain_levels or {})
            current_level = levels.get(domain, 0)
            
            # 최종 점수가 0 밑으로 가거나 10을 초과하지 않도록 방어
            new_level = current_level + change
            new_level = max(0, min(10, new_level)) 

            levels[domain] = new_level
            user.domain_levels = levels
            
            await session.commit()