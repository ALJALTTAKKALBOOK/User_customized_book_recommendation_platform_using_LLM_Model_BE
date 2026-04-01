from sqlalchemy import BigInteger, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

class Recommendation(Base):
    __tablename__ = "recommendations"

    recommend_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    book_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("books.id"), nullable=False)

    # AI 에이전트가 최종 추천 사유 저장
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    