from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import DEFAULT_TOP_K
from app.models.user import User, Conversation, Message
from app.schemas.conversation import (
    ConversationSummary,
    ConversationDetail,
    CreateConversationRequest,
    ChatRequest,
    ChatResponse,
)
from app.schemas.rag import AskResponse
from app.services.auth import get_current_user
from app.services.rag import build_rag_chain
from app.services.memory import create_memory_from_messages


router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("/", response_model=List[ConversationSummary])
def list_conversations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    لیست تمام گفتگوهای مربوط به کاربر لاگین‌شده.
    """
    convs = (
        db.query(Conversation)
        .filter(Conversation.user_id == current_user.id)
        .order_by(Conversation.created_at.desc())
        .all()
    )
    return convs


@router.post("/", response_model=ConversationSummary)
def create_conversation(
    payload: CreateConversationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    ایجاد یک گفتگو‌ی جدید خالی برای کاربر.
    """
    conv = Conversation(user_id=current_user.id, title=payload.title)
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    جزییات یک گفتگو به همراه تمام پیام‌ها.
    """
    conv = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id,
        )
        .first()
    )
    if not conv:
        raise HTTPException(status_code=404, detail="گفتگو پیدا نشد")
    # دسترسی به messages از طریق رابطه SQLAlchemy انجام می‌شود
    return conv


@router.post("/{conversation_id}/ask", response_model=ChatResponse)
def ask_in_conversation(
    conversation_id: int,
    payload: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    ارسال یک سوال در دل یک گفتگو؛ سوال و پاسخ به صورت پیام ذخیره می‌شوند
    و تاریخچه گفتگو به همراه سوال جدید به زنجیره RAG ارسال می‌شود.
    """
    import logging

    logger = logging.getLogger(__name__)
    logger.info(
        "Conversation /ask received",
        extra={
            "conversation_id": conversation_id,
            "top_k": payload.top_k,
            "use_enhanced": payload.use_enhanced_retrieval,
            "question_preview": (payload.question or "")[:200],
        },
    )
    conv = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id,
        )
        .first()
    )
    if not conv:
        raise HTTPException(status_code=404, detail="گفتگو پیدا نشد")

    # ذخیره پیام کاربر در دیتابیس (با conversation_id)
    user_msg = Message(
        conversation_id=conv.id,  # ذخیره با conversation_id مربوط به این گفتگو
        user_id=current_user.id,
        role="user",
        content=payload.question,
    )
    db.add(user_msg)
    db.commit()
    db.refresh(user_msg)

    # خواندن تاریخچه گفتگو از دیتابیس (بدون سوال جدید که تازه اضافه کردیم)
    previous_messages: List[Message] = (
        db.query(Message)
        .filter(
            Message.conversation_id == conv.id,
            Message.id != user_msg.id,  # سوال جدید را حذف می‌کنیم
        )
        .order_by(Message.created_at.asc())
        .all()
    )

    # ایجاد memory از تاریخچه قبلی (بدون سوال جدید)
    # سوال جدید بعداً در human message اضافه می‌شود
    memory = create_memory_from_messages(previous_messages)

    # ساخت زنجیره RAG با memory
    k = payload.top_k or DEFAULT_TOP_K
    use_enhanced = (
        payload.use_enhanced_retrieval
        if payload.use_enhanced_retrieval is not None
        else True
    )
    rag = build_rag_chain(k=k, use_enhanced_retrieval=use_enhanced, memory=memory)

    # ارسال سوال (memory به صورت خودکار history + سوال جدید را به مدل می‌فرستد)
    result: AskResponse | dict = rag(payload.question)  # type: ignore[assignment]

    # خروجی ممکن است دیکشنری ساده (fallback) یا پاسخ با فیلدهای بیشتر باشد
    answer = result.get("answer") or ""  # type: ignore[union-attr]
    sources = result.get("sources", [])  # type: ignore[union-attr]

    # ذخیره پاسخ دستیار (حتماً با conversation_id ذخیره می‌شود)
    assistant_msg = Message(
        conversation_id=conv.id,  # ذخیره با conversation_id
        user_id=current_user.id,
        role="assistant",
        content=answer or "پاسخی دریافت نشد",  # جلوگیری از None
    )
    db.add(assistant_msg)
    db.commit()
    db.refresh(assistant_msg)

    return ChatResponse(
        conversation_id=conv.id,
        answer=answer or "",  # type: ignore[arg-type] # noqa: E501
        sources=sources,
        response_time_seconds=result.get("response_time_seconds"),  # type: ignore[union-attr] # noqa: E501
        citation_count=result.get("citation_count"),  # type: ignore[union-attr] # noqa: E501
        citation_accuracy=result.get("citation_accuracy"),  # type: ignore[union-attr] # noqa: E501
        domain=result.get("domain"),  # type: ignore[union-attr] # noqa: E501
        domain_label=result.get("domain_label"),  # type: ignore[union-attr] # noqa: E501
        domain_confidence=result.get("domain_confidence"),  # type: ignore[union-attr] # noqa: E501
    )
