# app/domains/users/router.py
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from . import schema, service  

router = APIRouter(prefix="/users/auth", tags=["Auth"])

# [회원가입 API]
# response_model을 지정하면, Service에서 리턴한 Entity가 DTO로 자동 변환되어 JSON으로 반환됩니다!
@router.post("/signup", response_model=schema.UserResponse, status_code=status.HTTP_201_CREATED)
async def signup(dto: schema.UserCreateRequest, db: AsyncSession = Depends(get_db)):
    return await service.create_user(db, dto)

# [로그인 API]
@router.post("/login", response_model=schema.TokenResponse)
async def login(dto: schema.LoginRequest, db: AsyncSession = Depends(get_db)):
    return await service.login_user(db, dto)