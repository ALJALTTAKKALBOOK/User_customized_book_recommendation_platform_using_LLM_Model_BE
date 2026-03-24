from pydantic import BaseModel, Field
from typing import Optional

class ReviewCreate(BaseModel):
    book_id: int
    review: str = Field(..., max_length=2000)
    rating: int = Field(..., ge=1, le=5)
    # felt_difficulty: int = Field(..., ge=1, le=5, description="1: 매우 쉬움, 5: 매우 어려움")
    # 응답용 스키마 추가
class ReviewResponse(BaseModel):
    id: int
    user_id: int
    book_id: int
    review: str
    rating: int
    # created_at: datetime  (필요하다면 BaseTimeEntity의 필드 추가)

    class Config:
        from_attributes = True # SQLAlchemy 객체를 Pydantic 모델로 변환 (orm_mode의 새 이름)