from sqlalchemy import String, ForeignKey, Text, BigInteger
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

class ReadBook(Base):
    __tablename__ = "read_books"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    book_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("books.id"), nullable=False)  
    review: Mapped[str] = mapped_column(Text, nullable=True) 
    feeling_difficulty: Mapped[str] = mapped_column(String(20), nullable=True)
