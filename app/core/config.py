# 환경변수(Env) 로드 및 글로벌 설정 관리
from pydantic_settings import BaseSettings
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE_PATH = BASE_DIR / ".env"

class Settings(BaseSettings):
    # .env 파일에 있는 변수명과 아래 변수명이 똑같으면 Pydantic이 자동으로 매핑해줍니다!
    PROJECT_NAME: str = "BookAgent API" # 디폴트값
    
    DB_USER: str = "root"
    DB_PASSWORD: str = ""
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "bookfit"
    
    CONNECTION_POOL_SIZE: int = 10
    MAX_OVERFLOW: int = 10
    
    JWT_SECRET_KEY: str = ""
    OPENAI_API_KEY: str = ""
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7
    ALGORITHM: str = "HS256"

    @property
    def DATABASE_URL(self) -> str:
        # 형식: postgresql+asyncpg://아이디:비번@호스트:포트/DB이름
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE_PATH), # 위에서 계산한 완벽한 절대경로 주입!
        env_file_encoding="utf-8",
        extra="ignore" # .env에 정의되지 않은 여분 변수가 있어도 에러 안 내게 함
    )

# 싱글톤(Singleton)으로 Settings 객체를 딱 하나만 생성해 둡니다.
settings = Settings()

if "__main__" == __name__:
    print(f" Loading Environment from: {ENV_FILE_PATH}")