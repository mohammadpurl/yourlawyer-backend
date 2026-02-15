from datetime import datetime, date

from sqlalchemy import (
    String,
    Integer,
    ForeignKey,
    DateTime,
    Text,
    Date,
    Enum as SQLEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from app.core.database import Base


class PlanType(str, enum.Enum):
    FREE = "free"
    SILVER = "silver"
    GOLD = "gold"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    email: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True, index=True
    )
    mobile: Mapped[str | None] = mapped_column(
        String(20), unique=True, nullable=True, index=True
    )

    # Plan fields
    plan_type: Mapped[PlanType] = mapped_column(
        SQLEnum(
            PlanType, native_enum=False
        ),  # استفاده از VARCHAR به جای ENUM بومی PostgreSQL
        default=PlanType.FREE,
        nullable=False,
        index=True,
        server_default="'free'",  # مقدار پیش‌فرض در دیتابیس (با کوتیشن)
    )
    questions_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    plan_reset_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, index=True
    )

    # Relationships
    conversations: Mapped[list["Conversation"]] = relationship(
        "Conversation", back_populates="user", cascade="all, delete-orphan"
    )


class Conversation(Base):
    """
    یک گفتگو که به یک کاربر تعلق دارد.
    """

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
    user: Mapped["User"] = relationship("User", back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(Base):
    """
    یک پیام داخل یک گفتگو (سوال کاربر یا پاسخ دستیار).
    """

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id"), index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    role: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # "user" / "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    conversation: Mapped["Conversation"] = relationship(
        "Conversation", back_populates="messages"
    )
    user: Mapped["User"] = relationship("User")
