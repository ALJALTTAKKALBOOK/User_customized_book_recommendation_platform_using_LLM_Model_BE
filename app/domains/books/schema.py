# app/domains/books/schema.py
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

# --- Request DTO ---
class BookCreateRequest(BaseModel):
    isbn: str
    title: str
    author: str | None = None
    genre: str = Field(..., description="예: IT/프로그래밍")
    sub_category: str = Field(..., description="예: 웹/백엔드")
    difficulty: int = Field(..., description="예: 0~10")

    language: str | None = None
    grade_point: int | None = None
    page_count: int | None = None
    cover_url: str | None = None
    total_readers: int | None = None
    published_at: datetime | None = None
    
    summary: str
    keywords: list[str] = Field(..., description="LLM이 뽑아낸 핵심 키워드 리스트")
    #  OpenAI 임베딩 결과인 1536개의 실수(float) 배열
    embedding: list[float] = Field(..., description="1536차원의 임베딩 벡터 배열")

# --- Response DTO  ---
class BookResponse(BookCreateRequest):
    id: int
    created_at: datetime
    updated_at: datetime
    
    # SQLAlchemy Entity -> DTO 자동 변환
    model_config = ConfigDict(from_attributes=True)