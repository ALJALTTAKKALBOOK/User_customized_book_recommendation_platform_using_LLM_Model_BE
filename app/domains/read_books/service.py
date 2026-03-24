from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.domains.read_books.model import ReadBook
from app.domains.users.model import User
from app.core.llm_helper import analyze_review_with_llm
from app.core.database import AsyncSessionLocal
from app.domains.read_books.schema import ReviewCreate

async def create_review_service(db: AsyncSession, user_id: int, data: ReviewCreate, background_tasks: BackgroundTasks):
    new_review = ReadBook(
        user_id=user_id,
        book_id=data.book_id, 
        review=data.review, 
        rating=data.rating,
        # 1. DB에 체감 난이도 저장
        felt_difficulty=data.felt_difficulty 
    )
    db.add(new_review)
    await db.commit()
    await db.refresh(new_review)
    
    # 비동기 작업 예약 
    background_tasks.add_task(run_profiling_task, user_id, data.review, data.felt_difficulty)
    
    return new_review


async def run_profiling_task(user_id: int, content: str, felt_difficulty: int):
    async with AsyncSessionLocal() as session:
        # 2. LLM 함수를 호출할 때 텍스트뿐만 아니라 체감 난이도도 같이 던져줌
        analysis = await analyze_review_with_llm(content, felt_difficulty)
        
        # 유저 데이터 업데이트
        result = await session.execute(select(User).filter(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if user:
            levels = dict(user.domain_levels or {})
            domain = str(analysis.get("domain", "기타"))
            change = int(analysis.get("change", 0))
            
            # 작성하신 완벽한 레벨 제한 로직 적용
            current_level = levels.get(domain, 0)
            new_level = current_level + change
            new_level = max(0, min(10, new_level)) # 0 ~ 10 방어 로직

            levels[domain] = new_level
            user.domain_levels = levels
            
            await session.commit()