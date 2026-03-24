from sqlalchemy import String, Integer, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

from app.core.database import Base # 우리가 만든 BaseTimeEntity 상속

class ReadBook(Base):
    __tablename__ = "read_books"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    book_id: Mapped[int] = mapped_column(nullable=False) # 도서 ID
    review: Mapped[str] = mapped_column(Text, nullable=True) # 독후감(Text 타입은 긴 글 가능)
    rating: Mapped[int] = mapped_column(Integer, nullable=True)
    # felt_difficulty: Mapped[int] = mapped_column(Integer, nullable=False, default=3)