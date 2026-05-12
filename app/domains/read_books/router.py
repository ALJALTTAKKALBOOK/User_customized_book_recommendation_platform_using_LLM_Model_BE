from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.domains.read_books.schema import BookAddRequest, ReviewUpdateRequest, ReviewCreate, ReviewResponse
from app.domains.read_books.service import add_book_to_library_service, update_review_service, create_review_service
from app.domains.users.model import User 
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/read-books", tags=["Read Books (내 서재)"])


# ---------------------------------------------------------
# 1. [타임라인 1] 추천받은 책을 내 서재에 '담기'만 할 때
# ---------------------------------------------------------
@router.post("/", response_model=ReviewResponse, summary="내 서재에 책 담기 (리뷰/난이도 없음)")
async def add_book_to_library(
    data: BookAddRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    추천 화면에서 선택한 책을 내 서재에 등록합니다.
    (아직 읽기 전이므로 난이도나 후기는 작성하지 않으며, 레벨도 오르지 않습니다.)
    """
    return await add_book_to_library_service(db, current_user.id, data)


# ---------------------------------------------------------
# 2. [타임라인 2&3] 나중에 다 읽고 '리뷰/난이도'를 추가할 때
# ---------------------------------------------------------
@router.patch("/{read_book_id}/review", response_model=ReviewResponse, summary="서재의 책에 리뷰/난이도 업데이트")
async def update_book_review(
    read_book_id: int,
    data: ReviewUpdateRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    내 서재에 이미 등록된 책을 다 읽은 후, 체감 난이도와 후기를 남깁니다.
    이 API가 호출되면 백그라운드에서 유저의 레벨이 자동으로 업데이트(LLM) 됩니다.
    """
    return await update_review_service(db, read_book_id, current_user.id, data, background_tasks)


# ---------------------------------------------------------
# 3. 과거에 읽은 책을 '등록+리뷰' 할 때
# ---------------------------------------------------------
@router.post("/direct", response_model=ReviewResponse, summary="책 등록과 동시에 리뷰 작성")
async def create_book_and_review_direct(
    data: ReviewCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    과거에 읽었던 책을 직접 검색해서, 책 등록과 난이도 평가/후기 작성을 한 번에 처리합니다.
    """
    return await create_review_service(db, current_user.id, data, background_tasks)