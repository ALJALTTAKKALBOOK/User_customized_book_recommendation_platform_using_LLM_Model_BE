from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.domains.read_books.model import ReadBook
from app.domains.users.model import User
from app.core.llm_helper import generate_json_with_llm
from app.core.database import AsyncSessionLocal
from app.domains.read_books.schema import ReviewCreate
import logging

logger = logging.getLogger(__name__)

# 💡 프롬프트 고도화: LLM이 "배운 점"과 "어려웠던 점"을 구분해서 평가하도록 지시합니다.
READ_BOOK_EVALUATION_PROMPT = """너는 사용자의 독서 근력을 평가하는 '독서 수준 평가 전문가'야. 
사용자가 구조화하여 작성한 [배운 점]과 [어려웠던 점], 그리고 [체감 난이도]를 종합하여 순수한 JSON 객체로 응답해.

1. "domain": 독후감의 핵심 분야
2. "change": 사용자의 이해도 성장 수치 (-5 ~ +5 정수)

[구조화된 텍스트 평가 가이드 (매우 중요)]
* 메타인지 보너스: 사용자가 [어려웠던 점]을 명확히 인지하고 구체적인 기술/개념(예: "스프링 시큐리티 부분이 어려웠다")을 적어냈다면, 그것은 자신의 한계를 아는 훌륭한 독서이므로 감점하지 말고 오히려 가산점(+1~+2)을 줘.
* 지식 습득 보너스: [배운 점]에 책의 핵심 내용이나 본인의 삶에 적용할 인사이트가 구체적으로 적혀있다면 높은 점수(+3~+5)를 줘.
* 무의미한 답변: 질문에 안 맞게 "없음", "ㅋㅋ", "모름" 등으로 대충 적었다면 그 항목은 없는 것으로 간주하고, 둘 다 대충 적었다면 무조건 감점(-1~-2) 처리해.
"""

DIFFICULTY_SCORE_MAP = {
    "너무 쉬웠다": 2, "1": 2,
    "쉬웠다": 1, "2": 1,
    "읽을만 했다": 0, "3": 0,
    "이해가 잘 안된다": -1, "4": -1,
    "무슨의미인지 아예모르겠다": -2, "5": -2
}

async def create_review_service(db: AsyncSession, user_id: int, data: ReviewCreate, background_tasks: BackgroundTasks):
    
    # 1. 프론트엔드에서 온 2개의 구조화된 답변을 하나의 텍스트로 예쁘게 조립합니다.
    review_parts = []
    if data.learned_content and data.learned_content.strip():
        review_parts.append(f"[새롭게 배운 점/유용한 점]\n{data.learned_content.strip()}")
    if data.hard_content and data.hard_content.strip():
        review_parts.append(f"[어려웠던 점/아쉬운 점]\n{data.hard_content.strip()}")
    
    # 두 항목 중 하나라도 작성했다면 "\n\n"으로 이어서 문자열 생성, 둘 다 안 썼으면 None
    full_review_text = "\n\n".join(review_parts) if review_parts else None

    # 2. 조립된 최종 텍스트를 DB의 review(TEXT) 컬럼에 저장합니다.
    new_review = ReadBook(
        user_id=user_id,
        book_id=data.book_id, 
        review=full_review_text, # 조립된 텍스트 저장!
        feeling_difficulty=data.feeling_difficulty
    )
    db.add(new_review)
    await db.commit()
    await db.refresh(new_review)
    
    # 3. 백그라운드 태스크에도 조립된 텍스트를 넘깁니다.
    background_tasks.add_task(
        run_profiling_task, 
        user_id=user_id, 
        content=full_review_text, # 조립된 텍스트!
        feeling_difficulty=data.feeling_difficulty,
        default_category=data.category 
    )
    
    return new_review

async def run_profiling_task(user_id: int, content: str | None, feeling_difficulty: str, default_category: str):
    async with AsyncSessionLocal() as session:
        change = 0
        domain = default_category 

        # 후기가 있는 경우 (LLM 호출)
        if content and content.strip(): 
            user_prompt = f"[체감 난이도]: {feeling_difficulty}\n[독후감 내용]:\n{content}"
            
            analysis_result = await generate_json_with_llm(
                system_prompt=READ_BOOK_EVALUATION_PROMPT,
                user_prompt=user_prompt
            )
            
            if analysis_result:
                domain = str(analysis_result.get("domain", default_category)).strip()
                try:
                    change = max(-5, min(5, int(analysis_result.get("change", 0))))
                except ValueError:
                    change = 0 
            else:
                logger.warning(f"User {user_id} LLM 분석 실패, 고정 점수 로직으로 Fallback")
                # 문자열 공백 제거나 소문자 변환 등으로 안전하게 매핑
                safe_difficulty_key = feeling_difficulty.replace(" ", "").strip()
                # 띄어쓰기가 제거된 텍스트용 매핑을 한 번 더 거침
                fallback_score = {
                    "너무쉬웠다": 2, "쉬웠다": 1, "읽을만했다": 0, 
                    "이해가잘안된다": -1, "무슨의미인지아예모르겠다": -2
                }.get(safe_difficulty_key, 0)
                change = DIFFICULTY_SCORE_MAP.get(feeling_difficulty, fallback_score)

        # 후기가 없는 경우 (고정 점수 부여)
        else:
            safe_difficulty_key = feeling_difficulty.replace(" ", "").strip()
            fallback_score = {
                "너무쉬웠다": 2, "쉬웠다": 1, "읽을만했다": 0, 
                "이해가잘안된다": -1, "무슨의미인지아예모르겠다": -2
            }.get(safe_difficulty_key, 0)
            
            change = DIFFICULTY_SCORE_MAP.get(feeling_difficulty, fallback_score)
            logger.info(f"User {user_id} 후기 없음, 난이도({feeling_difficulty}) 기반 {change}점 부여")

        # --- 아래는 공통 레벨 업데이트 로직 ---
        result = await session.execute(select(User).filter(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if user:
            levels = dict(user.domain_levels or {})
            current_level = levels.get(domain, 0)
            
            new_level = current_level + change
            new_level = max(0, min(10, new_level)) 

            levels[domain] = new_level
            user.domain_levels = levels
            
            await session.commit()