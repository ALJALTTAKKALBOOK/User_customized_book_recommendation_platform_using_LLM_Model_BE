from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.domains.users.model import User
from .schema import RecommendRequest
from .service import get_book_recommendation_service_test, stream_book_recommendation_service

router = APIRouter(prefix="/recommendations", tags=["Recommendations"])

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


@router.post("/test")
async def recommend_books_test(
    request: RecommendRequest, # query가 들어있는 Pydantic 모델
    current_user: User = Depends(get_current_user), # JWT 검증으로 유저 가져오기
    db: AsyncSession = Depends(get_db)
):
    """
    [Swagger 테스트용] 에이전트의 추천 결과를 한 번에 JSON으로 받아보는 API
    """
    # 🌟 StreamingResponse 없이, 일반 함수 실행 후 딕셔너리 리턴!
    # FastAPI가 알아서 이 딕셔너리를 예쁜 JSON으로 바꿔서 화면에 뿌려줍니다.
    result = await get_book_recommendation_service_test(
        query=request.query,
        current_user=current_user,
        db=db
    )
    
    return result