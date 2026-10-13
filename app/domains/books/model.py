# app/domains/books/model.py
from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Integer, Text, BigInteger, DateTime
from sqlalchemy.dialects.postgresql import ARRAY
from pgvector.sqlalchemy import Vector # type: ignore

from app.core.database import Base

class Book(Base):
    __tablename__ = "books"

    # --- 기본 식별자 ---
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    isbn: Mapped[str] = mapped_column(String(20), unique=True, index=True) # 책 고유번호
    
    # --- 핵심 메타데이터 (SQL WHERE 필터링용) ---
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    author: Mapped[str] = mapped_column(String(100), nullable=True)
    genre: Mapped[str] = mapped_column(String(50))           # 대분류 (예: IT)
    sub_category: Mapped[str] = mapped_column(String(50))    # 소분류 (예: 웹/백엔드)
    difficulty: Mapped[int] = mapped_column(Integer)      # 난이도 (예: 0~10)
    
    # --- AI 검색용 데이터 (JSON & 텍스트) ---
    summary: Mapped[str] = mapped_column(Text)               # 줄거리
    keywords: Mapped[list[str]] = mapped_column(ARRAY(String))       # AI가 뽑은 핵심 키워드 배열
    
    #  임베딩 벡터 컬럼 (OpenAI text-embedding-3-small 기준 1536차원)
    embedding: Mapped[list[float]] = mapped_column(Vector(1536))
    
    # --- 부가 메타데이터 (단순 전시용, 임베딩 제외) ---
    language: Mapped[str] = mapped_column(String(20), nullable=True)
    grade_point: Mapped[int] = mapped_column(Integer, nullable=True)        # 평점 (예: 1~100)
    page_count: Mapped[int] = mapped_column(Integer, nullable=True)         # 쪽수
    cover_url: Mapped[str] = mapped_column(String(500), nullable=True)      # 이미지 링크
    total_readers: Mapped[int] = mapped_column(BigInteger, nullable=True)   # 누적 독자수
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True) # 출판일시
    
