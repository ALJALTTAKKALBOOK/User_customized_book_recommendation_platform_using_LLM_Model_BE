from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base # 우리가 만든 BaseTimeEntity 상속

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    nickname: Mapped[str] = mapped_column(String(50), nullable=False)
    
    # 기본값으로 빈 딕셔너리 {} 를 넣어줍니다.
    domain_levels: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict, nullable=False)