from typing import List
from langchain_classic.memory import ConversationBufferMemory

from app.core.config import MAX_CHAT_HISTORY_MESSAGES
from app.models.user import Message


def create_memory_from_messages(messages: List[Message]) -> ConversationBufferMemory:
    """
    ایجاد یک ConversationBufferMemory از لیست پیام‌های دیتابیس.

    فقط آخرین ``MAX_CHAT_HISTORY_MESSAGES`` پیام فرستاده می‌شود تا
    پرامپت کوتاه‌تر و پاسخ سریع‌تر باشد.
    """
    memory = ConversationBufferMemory(
        memory_key="chat_history",
        return_messages=True,
        output_key="answer",
    )

    recent = messages
    limit = max(0, MAX_CHAT_HISTORY_MESSAGES)
    if limit and len(messages) > limit:
        recent = messages[-limit:]

    for msg in recent:
        if msg.role == "user":
            memory.chat_memory.add_user_message(msg.content)
        elif msg.role == "assistant":
            memory.chat_memory.add_ai_message(msg.content)

    return memory


def get_memory_messages(memory: ConversationBufferMemory) -> List:
    """دریافت لیست messages از memory برای استفاده در chain."""
    return memory.chat_memory.messages
