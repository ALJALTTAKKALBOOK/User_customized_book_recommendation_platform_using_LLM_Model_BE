from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.users.model import User
from app.core.config import settings
from app.core.database import get_db

# Swagger UI(docs) 우측 상단에 'Authorize(자물쇠)' 버튼이 자동 생성시킴
# tokenUrl="/api/users/auth/login" 은 "로그인 하려면 이 URL로 POST 요청을 보내라"는 뜻입니다.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/users/auth/swagger-login")

async def get_current_user(
    # 1. 헤더에서 토큰 추출 (FastAPI가 알아서 해줌)
    token: str = Depends(oauth2_scheme), 
    # 2. DB에서 진짜 유저를 꺼내고 싶다면 DB 세션도 같이 주입받음
    db: AsyncSession = Depends(get_db)
)->User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="토큰이 유효하지 않거나 만료되었습니다.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # 1. 토큰 디코딩 및 검증 (서명, 만료시간 자동 체크)
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.ALGORITHM])
        
        # 2. 페이로드에서 유저 ID(sub) 추출
        user_id_str: str | None = payload.get("sub")
        if user_id_str is None:
            raise credentials_exception
            
        user_id = int(user_id_str)
        
    except JWTError:
        raise credentials_exception

    user = await db.get(User, user_id)
    if user is None:
        raise credentials_exception
    
    return user