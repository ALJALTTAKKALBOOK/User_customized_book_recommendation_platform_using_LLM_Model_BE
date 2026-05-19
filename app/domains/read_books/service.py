import logging
from typing import List, Optional
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.domains.read_books.model import ReadBook
from app.domains.books.model import Book 
from app.domains.users.model import User
from app.core.llm_helper import generate_json_with_llm
from app.core.database import AsyncSessionLocal
from app.domains.read_books.schema import BookAddRequest, ReviewUpdateRequest, ReviewCreate
from app.core.constants import ALL_SUB_CATEGORIES 

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# 1. 상수 및 프롬프트
# -----------------------------------------------------------------------------

READ_BOOK_EVALUATION_PROMPT = f"""너는 사용자의 기술적 숙련도를 분석하는 'Expert Profiler'야. 
사용자의 리뷰를 분석하여 아래의 [허용된 카테고리 목록] 중 가장 관련 깊은 하나를 선택하고 성취 점수를 부여해.

[허용된 카테고리 목록]:
{", ".join(ALL_SUB_CATEGORIES)}

출력 형식 (순수 JSON만 응답):
{{
  "domain": "목록 중 선택한 카테고리 이름",
  "change": 1~5 사이의 성취 점수
}}
"""

DIFFICULTY_SCORE_MAP = {
    "너무 쉬웠다": 1, "쉬웠다": 2, "읽을만 했다": 3, "이해가 잘 안된다": 2, "무슨의미인지 아예모르겠다": 1
}

# -----------------------------------------------------------------------------
# 2. 비즈니스 로직 (라우터에서 부르는 함수 이름들)
# -----------------------------------------------------------------------------

# 🌟 1. 내 서재 목록 조회 함수
async def get_read_books_service(db: AsyncSession, user_id: int):
    stmt = (
        select(ReadBook, Book)
        .join(Book, ReadBook.book_id == Book.id)
        .where(ReadBook.user_id == user_id)
    )
    result = await db.execute(stmt)
    
    books = []
    for read_book, book in result.all():
        books.append({
            "id": read_book.id,
            "book_id": book.id,
            "title": book.title,
            "author": book.author,
            "genre": book.genre,
            "sub_category": book.sub_category,
            "difficulty": book.difficulty,
            "review": read_book.review,
            "feeling_difficulty": read_book.feeling_difficulty,
            "cover_url": book.cover_url
        })
    return books

# 🌟 2. 내 서재 담기 함수 (ImportError의 주범)
async def add_book_to_library_service(db: AsyncSession, user_id: int, data: BookAddRequest):
    new_book = ReadBook(
        user_id=user_id,
        book_id=data.book_id,
        feeling_difficulty=None,
        review=None
    )
    db.add(new_book)
    await db.commit()
    await db.refresh(new_book)
    return new_book

# 🌟 3. 리뷰 업데이트 함수
async def update_review_service(
    db: AsyncSession, 
    read_book_id: int, 
    user_id: int, 
    data: ReviewUpdateRequest, 
    background_tasks: BackgroundTasks
):
    stmt = (
        select(ReadBook, Book)
        .join(Book, ReadBook.book_id == Book.id)
        .filter(ReadBook.id == read_book_id, ReadBook.user_id == user_id)
    )
    result = await db.execute(stmt)
    row = result.first()
    
    if not row:
        raise HTTPException(status_code=404, detail="기록을 찾을 수 없습니다.")

    rb, b = row
    review_parts = []
    if data.learned_content: review_parts.append(f"[배운 점]: {data.learned_content}")
    if data.hard_content: review_parts.append(f"[어려웠던 점]: {data.hard_content}")
    full_review_text = "\n\n".join(review_parts) if review_parts else ""

    rb.review = full_review_text
    rb.feeling_difficulty = data.feeling_difficulty
    await db.commit()
    
    background_tasks.add_task(
        run_profiling_task, 
        user_id=user_id, 
        content=full_review_text, 
        feeling_difficulty=data.feeling_difficulty,
        default_category=b.sub_category 
    )
    return rb

# 🌟 4. 직접 등록 함수
async def create_review_service(db: AsyncSession, user_id: int, data: ReviewCreate, background_tasks: BackgroundTasks):
    book_stmt = select(Book).where(Book.id == data.book_id)
    book_result = await db.execute(book_stmt)
    book = book_result.scalar_one_or_none()
    
    if not book:
        raise HTTPException(status_code=404, detail="도서 정보가 없습니다.")

    review_parts = []
    if data.learned_content: review_parts.append(f"[배운 점]: {data.learned_content}")
    if data.hard_content: review_parts.append(f"[어려웠던 점]: {data.hard_content}")
    full_review_text = "\n\n".join(review_parts) if review_parts else ""

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
        default_category=book.sub_category 
    )
    return new_review

# -----------------------------------------------------------------------------
# 3. 백그라운드 태스크 (내부 호출용)
# -----------------------------------------------------------------------------

async def run_profiling_task(user_id: int, content: str, feeling_difficulty: str, default_category: str):
    async with AsyncSessionLocal() as session:
        base_change = DIFFICULTY_SCORE_MAP.get(feeling_difficulty, 1)
        domain = default_category 
        change = base_change

        if content and len(content.strip()) > 5:
            user_prompt = f"분야: {default_category}\n난이도: {feeling_difficulty}\n리뷰: {content}"
            analysis_result = await generate_json_with_llm(
                system_prompt=READ_BOOK_EVALUATION_PROMPT,
                user_prompt=user_prompt
            )
            if analysis_result:
                ai_domain = str(analysis_result.get("domain", "")).strip()
                if ai_domain in ALL_SUB_CATEGORIES:
                    domain = ai_domain
                try:
                    change = int(analysis_result.get("change", base_change))
                except:
                    change = base_change
        
        change = max(0, min(5, change))

        result = await session.execute(select(User).filter(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if user:
            current_levels = dict(user.domain_levels or {})
            old_val = current_levels.get(domain, 0)
            new_val = min(10, old_val + change)
            current_levels[domain] = new_val
            user.domain_levels = current_levels
            await session.commit()
            logger.info(f"✅ [레벨업] {domain}: {old_val} -> {new_val}")