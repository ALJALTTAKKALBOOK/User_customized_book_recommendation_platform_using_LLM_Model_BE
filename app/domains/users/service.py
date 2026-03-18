from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status

from app.domains.users.model import User
from app.core.security import get_password_hash, verify_password, create_access_token
from . import schema

async def create_user(db: AsyncSession, dto: schema.UserCreateRequest) -> schema.UserResponse:
    # 1. 이메일 중복 체크
    stmt = select(User).where(User.email == dto.email)
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="이미 존재하는 이메일입니다.")

    # 2. 비밀번호 해싱 및 Entity 생성
    new_user = User(
        email=dto.email,
        hashed_password=get_password_hash(dto.password),
        nickname=dto.nickname,
        # domain_levels는 model.py에서 default=dict 로 설정했으므로 생략 시 {} 가 들어갑니다.
    )

    # 3. DB 저장
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user) # DB에서 생성된 id를 가져옴
    
    # model_validate는 파라미터로 받은 객체의 __dict__를 뒤져 나(dto)와 이름이 같은 변수가 있으면
    # 그 값을 뽑아 새로운 dto객체를 찍어내 변환함
    return schema.UserResponse.model_validate(new_user)

async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    # id(PK)로 단건 조회할 때는 get()이 제일 빠릅니다.
    return await db.get(User, user_id)

async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    stmt = select(User).where(User.email == email)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()

#  1. 로그인 비즈니스 로직을 통째로 서비스로 가져옴!
async def login_user(db: AsyncSession, dto: schema.LoginRequest) -> schema.TokenResponse:
    # 1. DB 조회
    user = await get_user_by_email(db, dto.email)
    
    # 2.  검증 로직 (실패 시 에러 던지기)
    if not user or not verify_password(dto.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 틀렸습니다."
        )
    
    # 3. 토큰 발급 로직
    access_token = create_access_token(data={"sub": str(user.id)})
    
    # 4. 결과 DTO 반환
    return schema.TokenResponse(access_token=access_token)