from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status
from sqlalchemy.orm.attributes import flag_modified
from .model import User
from .schema import OnboardingRequest


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


async def set_initial_proficiency(db: AsyncSession, user: User, dto: OnboardingRequest) -> schema.UserResponse:
    """ 온보딩에서 유저가 선택한 세부 카테고리와 숙련도 점수를 JSONB 컬럼에 저장하는 함수

    Args:
        db (AsyncSession): DB 세션
        user (User): 온보딩 대상 유저 객체
        dto (OnboardingRequest): 온보딩 요청 데이터

    Returns:
        schema.UserResponse: 업데이트된 유저 객체
    """
    # 온보딩은 기존 데이터를 무시하고 통째로 덮어씌웁니다.
    user.domain_levels = dto.proficiencies
    
    # 통째로 갈아끼웠기 때문에 SQLAlchemy가 변경을 자동 감지(Dirty Checking)합니다.
    await db.commit()
    return schema.UserResponse.model_validate(user)

async def update_proficiency(db: AsyncSession, user: User, sub_category: str, score_change: int) :
    """ AI가 독후감을 분석한 뒤, 특정 카테고리의 점수를 올리거나 내릴 때 호출

    Args:
        db (AsyncSession): DB 세션
        user (User): 대상 유저 객체
        sub_category (str): 수정할 서브 카테고리
        score_change (int): 점수 변경량
        
    """

    # 1. 현재 유저의 JSONB 딕셔너리를 가져옵니다.
    current_levels = user.domain_levels
    
    # 2. 해당 카테고리가 기존에 있으면 점수 가져오고, 없으면 기본값(예: 5)에서 시작
    current_score = current_levels.get(sub_category, 5)
    
    # 3. 새 점수 계산 (0점 미만, 10점 초과 방지)
    new_score = max(0, min(10, current_score + score_change))
    
    # 4. 딕셔너리 내부 값 변경
    current_levels[sub_category] = new_score
    
    #  [CS 경고] 파이썬 딕셔너리 내부의 값을 변경해도, 
    # SQLAlchemy는 "어? 객체 주소(포인터)는 그대로네?" 하고 업데이트 쿼리를 날리지 않습니다!!
    
    #  [해결책] "이 JSONB 컬럼 내용물 바뀌었으니까 무조건 UPDATE 쿼리 쏴라!" 라고 수동 마킹
    flag_modified(user, "domain_levels")
    
    await db.commit()