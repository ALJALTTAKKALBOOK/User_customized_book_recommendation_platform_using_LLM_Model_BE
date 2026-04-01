from sqlalchemy.orm import Mapped, mapped_column,relationship
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base
from app.domains.read_books.model import ReadBook
from app.domains.recommendations.model import Recommendation

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    nickname: Mapped[str] = mapped_column(String(50), nullable=False)
    
    # 기본값으로 빈 딕셔너리 {} 를 넣어줍니다.
    domain_levels: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict, nullable=False)
    
    
    # 매핑: User에서 바로 ReadBook과 Recommendation에 접근가능
    read_books: Mapped[list["ReadBook"]] = relationship(cascade="all, delete-orphan")
    recommendations: Mapped[list["Recommendation"]] = relationship(cascade="all, delete-orphan")