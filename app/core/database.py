from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from datetime import datetime, timezone
from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column
#sqlalchemy는 자바의 하이버네이트 위치에 있는 orm 구현체이다

from app.core.config import settings

# 1. 비동기 엔진 생성 (Spring의 DataSource + Connection Pool / 싱글톤)
# echo=True 로 설정하면 Hibernate의 show-sql=true 처럼 실행되는 SQL이 콘솔에 출력됩니다.
# db와 물리적 tcp통신담당, 커넥션 풀, 트랜잭션 관리 등등을 담당하는 객체/alchemy가 만든 파이썬 쿼리를 sql로 변역후 쏴줌
engine = create_async_engine(
    settings.DATABASE_URL, 
    echo=True,       # 개발 단계에서는 True, 운영 환경에서는 False로 변경
    future=True,     # SQLAlchemy 2.0 API 사용 강제
    pool_size=settings.CONNECTION_POOL_SIZE,     # 커넥션 풀 기본 개수 (필요에 따라 조절)
    max_overflow=settings.MAX_OVERFLOW  # 풀이 꽉 찼을 때 추가로 허용할 커넥션 수
)

# 2. 세션 팩토리 생성 (Spring의 EntityManagerFactory)
# expire_on_commit=False: 비동기 환경에서 트랜잭션 커밋 후 객체 필드에 접근할 때,
# DB에 다시 쿼리를 날리는(Lazy Loading) 것을 방지하여 에러를 막습니다.
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)

# 3. 최상위 엔티티 클래스 (Spring의 @Entity들이 상속받을 기준점)
class Base(DeclarativeBase):
    """
    모든 도메인의 DB 모델(엔티티) 클래스는 이 Base 클래스를 상속받아야 합니다.
    그래야 SQLAlchemy가 어떤 테이블들을 DB에 만들어야 할지 스캔할 수 있습니다.
    """
    # 1. 생성일 (created_at): row가 처음 INSERT 될 때의 현재 시간을 자동으로 넣음
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc), # 파이썬 레벨에서 시간 주입
        nullable=False
    )

    # 2. 수정일 (updated_at): 처음 INSERT 될 때 들어가고, UPDATE 될 때마다 갱신됨
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), 
        nullable=False
    )


# 4. 의존성 주입(DI)용 세션 제너레이터
# Session =  EntityManager + 1차 캐시 (영속성 컨텍스트) 
# 1번의 API 요청(또는 1번의 비즈니스 트랜잭션) 동안 데이터베이스 작업들을 모아두는
# 논리적인 작업 공간이자 1차 캐시 메모리/ commit시 모아둔 작업을 한번에 DB에 반영
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI의 Depends()를 통해 각 API 요청마다 비동기 DB 세션을 하나씩 할당하고,
    요청이 끝나면 (에러 여부와 상관없이) 안전하게 커넥션 풀로 반납(close)합니다.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            # 예외가 터져도 무조건 실행됨 (메모리 및 커넥션 누수 완벽 차단)
            await session.close()