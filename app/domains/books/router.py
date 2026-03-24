# app/domains/books/router.py
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from . import schema, service

router = APIRouter(prefix="/books", tags=["Books (Crawling & Search)"])

# [크롤링 데이터 적재용 API]
@router.post("/", response_model=schema.BookResponse, status_code=status.HTTP_201_CREATED)
async def create_new_book(dto: schema.BookCreateRequest, db: AsyncSession = Depends(get_db)):
    """
    크롤링 스크립트에서 책 1권의 데이터를 보낼 때 사용하는 API입니다.
    """
    return await service.create_book(db, dto)