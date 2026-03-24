from fastapi import FastAPI
from contextlib import asynccontextmanager
from sqlalchemy import text

from app.domains.users.router import router as user_router
from app.domains.books.router import router as book_router
from app.core.database import engine, Base

# 1. 엔티티(Model)들을 무조건 임포트!!! 
# 이걸 임포트 안 하면 SQLAlchemy(Base)가 "어떤 테이블을 만들어야 하는지" 모름
import app.domains.users.model # type: ignore
import app.domains.books.model # type: ignore

# 2. 서버 생명주기(Lifecycle) 관리자
@asynccontextmanager
async def lifespan(app: FastAPI):
    # engine.begin()으로 트랜잭션을 열고, Base에 연결된 모든 모델의 DDL(CREATE TABLE)을 실행합니다.
    async with engine.begin() as conn:
         #테이블 만들기 전에 vector 확장을 먼저 활성화
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        
        # 이미 테이블이 있으면 무시하고, 없으면 새로 만듭니다 (ddl-auto: update 와 유사)
        await conn.run_sync(Base.metadata.create_all)
        
    print("데이터베이스 테이블 생성 완료")
    
    # 이 yield를 기점으로 서버가 켜지고 유저 요청을 받기 시작합니다.
    yield 
    
    # --- 서버 종료 후 (Shutdown) ---
    print("🛑 서버가 종료됩니다.")

app = FastAPI(
    title="BookAgent API 서버", 
    version="1.0",
    lifespan=lifespan  
)
# 컨트롤러(라우터) 조립하기
app.include_router(user_router, prefix="/api")
app.include_router(book_router, prefix="/api")

@app.get("/")
def health_check():
    return {"status": "서버가 정상적으로 켜졌습니다!"}