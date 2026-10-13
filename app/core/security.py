from datetime import datetime, timedelta, timezone
from typing import Any
from jose import jwt
import bcrypt
from app.core.config import settings


def get_password_hash(password: str) -> str:
    """
    회원가입 시 평문 비밀번호(plain text)를 받아서 Bcrypt 해시 문자열로 변환합니다.
    """
    # 1. 비밀번호를 바이트(bytes)로 변환
    pwd_bytes = password.encode('utf-8')
    # 2. bcrypt 순정 함수로 해싱 (Salt 자동 생성)
    hashed_bytes = bcrypt.hashpw(pwd_bytes, bcrypt.gensalt())
    # 3. DB에 저장하기 위해 다시 문자열(str)로 디코딩해서 리턴
    return hashed_bytes.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    로그인 시 유저가 입력한 평문 비밀번호와, DB에 저장된 해시 비밀번호를 비교합니다.
    """
    # 둘 다 바이트(bytes)로 변환해서 순정 함수로 비교
    return bcrypt.checkpw(
        plain_password.encode('utf-8'),
        hashed_password.encode('utf-8')
    )

def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """JWT Access Token을 생성하는 유틸리티 함수입니다.

    Args:
        data (dict[str, Any]): 토큰의 페이로드(Claims)에 담길 데이터. 
            반드시 'sub' 키에 유저의 고유 식별자(PK)가 문자열로 포함되어야 합니다.
            예: {"sub": "123", "role": "admin"}
        expires_delta (timedelta | None, optional): 토큰의 만료 시간 간격.
            값을 넘기지 않으면 환경변수의 기본값이 사용됩니다. Defaults to None.

    Returns:
        str: HS256 알고리즘으로 서명된 JWT 인코딩 문자열.
    """
    # 딕셔너리 얕은 복사 (파라미터 원본 데이터 오염 방지)
    to_encode = data.copy()
    
    # 토큰 만료 시간(exp) 설정
    if expires_delta:
        # utcnow()는 Python 3.12에서 deprecated 되어 timezone.utc를 쓰는 것이 최신 표준입니다.
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        
    # 페이로드(Claims)에 만료 시간 추가
    to_encode.update({"exp": expire})
    
    # JWT 인코딩 (HS256 대칭키 알고리즘 사용)
    encoded_jwt = jwt.encode(
        to_encode, 
        settings.JWT_SECRET_KEY, 
        algorithm=settings.ALGORITHM
    )
    
    return encoded_jwt