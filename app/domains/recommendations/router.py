from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.domains.users.model import User
from .schema import RecommendRequest
from .service import stream_book_recommendation_service

router = APIRouter(prefix="/api/recommendations", tags=["Recommendations"])

@router.post("/stream")
async def stream_recommendation(
    request: RecommendRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    
    # Service 함수를 호출하고, 그 결과(Generator)를 SSE 스트리밍으로 쏴줍니다.
    return StreamingResponse(
        stream_book_recommendation_service(request.query, current_user,db), 
        media_type="text/event-stream"
    )