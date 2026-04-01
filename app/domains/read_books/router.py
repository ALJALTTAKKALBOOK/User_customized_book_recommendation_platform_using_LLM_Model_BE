from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.domains.read_books.schema import ReviewCreate, ReviewResponse
from app.domains.read_books.service import create_review_service
from app.domains.users.model import User 
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/reviews", tags=["reviews"])

@router.post("/", response_model=ReviewResponse)
async def post_review(
    data: ReviewCreate, 
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return await create_review_service(db, current_user.id, data, background_tasks)