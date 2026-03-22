# app/domains/users/router.py
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.security import OAuth2PasswordRequestForm

from app.core.database import get_db
from app.domains.users.model import User
from app.domains.users.schema import OnboardingRequest
from app.core.dependencies import get_current_user
from . import schema, service  

router = APIRouter(prefix="/users", tags=["Users"])

# [회원가입 API]
# response_model을 지정하면, Service에서 리턴한 Entity가 DTO로 자동 변환되어 JSON으로 반환됩니다!
@router.post("/auth/signup", response_model=schema.UserResponse, status_code=status.HTTP_201_CREATED)
async def signup(dto: schema.UserCreateRequest, db: AsyncSession = Depends(get_db)):
    return await service.create_user(db, dto)

# [로그인 API]
@router.post("/auth/login", response_model=schema.TokenResponse)
async def login(dto: schema.LoginRequest, db: AsyncSession = Depends(get_db)):
    return await service.login_user(db, dto)

# [Swagger UI 자물쇠 전용 (Form Data 방식)]
# include_in_schema=False 를 주면 이 API가 Swagger 문서 목록에는 안 뜹니다 (지저분함 방지).
@router.post("/auth/swagger-login", include_in_schema=False) 
async def swagger_login(
    form_data: OAuth2PasswordRequestForm = Depends(), 
    db: AsyncSession = Depends(get_db)
):
    """
    이 API는 오직 Swagger 우측 상단의 'Authorize' 버튼을 위해 존재합니다.
    Form 데이터(username, password)를 받아서 기존 JSON DTO로 강제 변환 후 
    기존 비즈니스 로직에 태워버립니다.
    """
    # Form의 username(이메일)과 password를, 우리가 만든 JSON DTO로 변환(어댑터 패턴!)
    adapter_dto = schema.LoginRequest(
        email=form_data.username, 
        password=form_data.password
    )
    
    # 변환된 DTO를 기존 서비스 로직에 그대로 밀어 넣습니다. 
    return await service.login_user(db, adapter_dto)

# [온보딩 API]
@router.post("/me/onboarding", response_model=schema.UserResponse)
async def onboarding(dto: OnboardingRequest, db: AsyncSession = Depends(get_db), current_user : User = Depends(get_current_user)):
    return await service.set_initial_proficiency(db, current_user, dto)