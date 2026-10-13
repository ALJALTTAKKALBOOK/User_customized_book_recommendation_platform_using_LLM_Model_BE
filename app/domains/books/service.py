# app/domains/books/service.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException
from .model import Book
from . import schema

async def create_book(db: AsyncSession, dto: schema.BookCreateRequest) -> schema.BookResponse:
    """ BookCreateRequestDto를 받아 책 데이터를 생성

    Args:
        db (AsyncSession): DB session 
        dto (schema.BookCreateRequest): 책 생성에 필요한 모든 데이터가 담긴 DTO

    Raises:
        HTTPException: 이미 존재하는 ISBN인 경우 400 에러 발생

    Returns:
        schema.BookResponse: 생성된 책 데이터
    """
    # 1. 중복 검사 (ISBN 기준)
    stmt = select(Book).where(Book.isbn == dto.isbn)
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"이미 존재하는 ISBN입니다: {dto.isbn}")
        
    # 2. Pydantic DTO를 SQLAlchemy Entity로 변환
    # model_dump()는 Pydantic객체를 딕셔너리로 변환
    # **는 딕셔너리를 언팩하여 key=value 형태로 변환함
    new_book = Book(**dto.model_dump())
    
    # 3. DB 저장 (이때 ARRAY와 Vector 타입도 알아서 예쁘게 들어갑니다)
    db.add(new_book)
    await db.commit()
    await db.refresh(new_book)
    
    # 4. 결과 리턴
    return schema.BookResponse.model_validate(new_book)