from pydantic import BaseModel, Field
from typing import Optional

class ReviewCreate(BaseModel):
    book_id: int = Field(..., description="도서 ID")
    category: str = Field(..., description="책의 분야/카테고리")
    feeling_difficulty: str = Field(..., description="체감 난이도")

    # 구조화된 질문 2개 생성
    learned_content: Optional[str] = Field(
        None, 
        max_length=1000, 
        description="Q1. 이 책에서 가장 유용했거나 새롭게 알게 된 개념은 무엇인가요?"
    )
    hard_content: Optional[str] = Field(
        None, 
        max_length=1000, 
        description="Q2. 반대로 이해하기 힘들었거나 아쉬웠던 부분은 무엇인가요?"
    )

class ReviewResponse(BaseModel):
    id: int
    user_id: int
    book_id: int
    review: Optional[str] # DB에 조립되어 저장된 최종본이 나갑니다.
    feeling_difficulty: str

    class Config:
        from_attributes = True