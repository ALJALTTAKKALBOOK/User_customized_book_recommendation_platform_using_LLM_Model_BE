from pydantic import BaseModel, Field
from typing import Optional, List  # 👈 List 추가

# ---------------------------------------------------------
# 1. 처음에 책을 내 서재에 담기만 할 때 (POST /read-books)
# ---------------------------------------------------------
class BookAddRequest(BaseModel):
    book_id: int = Field(..., description="선택한 도서 ID")
    category: str = Field(..., description="책의 분야/카테고리 (예: 소설, 경제, IT)")

# ---------------------------------------------------------
# 2. 나중에 다 읽고 후기/난이도를 남길 때 (PATCH /read-books/{id}/review)
# ---------------------------------------------------------
class ReviewUpdateRequest(BaseModel):
    category: str = Field(..., description="책의 분야/카테고리")
    feeling_difficulty: str = Field(
        ..., 
        max_length=20, 
        description="체감 난이도 (예: 너무 쉬웠다, 쉬웠다, 읽을만 했다, 이해가 잘 안된다, 무슨의미인지 아예모르겠다)"
    )
    
    # 구조화된 질문 2가지
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

# ---------------------------------------------------------
# 3. 과거에 읽은 책을 한 번에 등록+리뷰 할 때 (POST /read-books/direct)
# ---------------------------------------------------------
class ReviewCreate(BaseModel):
    book_id: int = Field(..., description="선택한 도서 ID")
    category: str = Field(..., description="책의 분야/카테고리")
    feeling_difficulty: str = Field(..., max_length=20, description="체감 난이도")
    learned_content: Optional[str] = Field(None, max_length=1000)
    hard_content: Optional[str] = Field(None, max_length=1000)

# ---------------------------------------------------------
# 4. 등록/수정 후 단일 응답을 보낼 때 쓰는 규격 (ReviewResponse)
# ---------------------------------------------------------
class ReviewResponse(BaseModel):
    id: int
    user_id: int
    book_id: int
    review: Optional[str] = None
    feeling_difficulty: Optional[str] = None

    class Config:
        from_attributes = True

# ---------------------------------------------------------
# 5. 🌟 [추가됨] 내 서재 목록 조회 시 도서 상세 정보를 포함한 응답 규격
# ---------------------------------------------------------
class ReadBookResponse(BaseModel):
    id: int              # 내 서재 레코드 ID
    book_id: int         # 실제 도서 ID
    title: str           # 도서 제목
    author: str          # 저자
    genre: str           # 장르
    difficulty: int      # 도서 원래 난이도
    cover_url: Optional[str] = None
    review: Optional[str] = None
    feeling_difficulty: Optional[str] = None

    class Config:
        from_attributes = True