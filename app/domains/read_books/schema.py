from pydantic import BaseModel, Field
from typing import Optional

# 1. 처음에 책을 내 서재에 담기만 할 때 (POST /read-books)
class BookAddRequest(BaseModel):
    book_id: int = Field(..., description="선택한 도서 ID")
    category: str = Field(..., description="책의 분야/카테고리 (예: 소설, 경제, IT)")

# 2. 나중에 다 읽고 후기/난이도를 남길 때 (PATCH /read-books/{id}/review)
class ReviewUpdateRequest(BaseModel):
    category: str = Field(..., description="책의 분야/카테고리")
    feeling_difficulty: str = Field(
        ..., 
        max_length=20, 
        description="체감 난이도 (예: 너무 쉬웠다, 쉬웠다, 읽을만 했다, 이해가 잘 안된다, 무슨의미인지 아예모르겠다)"
    )
    
    #  구조화된 질문 2가지
    learned_content: Optional[str] = Field(
        None, 
        max_length=1000, 
        description="Q1. 이 책에서 가장 유용했거나 새롭게 알게 된 개념은 무엇인가요? (없으면 비워두세요)"
    )
    hard_content: Optional[str] = Field(
        None, 
        max_length=1000, 
        description="Q2. 반대로 이해하기 힘들었거나 아쉬웠던 부분은 무엇인가요? (없으면 비워두세요)"
    )

# 3. 과거에 읽은 책을 한 번에 등록+리뷰 할 때 (POST /read-books/direct)
class ReviewCreate(BaseModel):
    book_id: int = Field(..., description="선택한 도서 ID")
    category: str = Field(..., description="책의 분야/카테고리")
    feeling_difficulty: str = Field(..., max_length=20, description="체감 난이도")
    
    # 구조화된 질문 2개 적용
    learned_content: Optional[str] = Field(None, max_length=1000, description="Q1. 새롭게 알게 된 개념은?")
    hard_content: Optional[str] = Field(None, max_length=1000, description="Q2. 이해하기 힘들었던 부분은?")

# 4. 프론트엔드로 응답을 보낼 때 쓰는 공통 규격 (Response)
class ReviewResponse(BaseModel):
    id: int
    user_id: int
    book_id: int
    
    # DB에는 프론트에서 받은 두 질문(learned, hard)이 하나로 예쁘게 합쳐져서 여기에 담겨 나갑니다.
    review: Optional[str] 
    
    # 처음에 책만 담았을 땐 비어있을 수 있으므로 Optional
    feeling_difficulty: Optional[str] 

    class Config:
        from_attributes = True