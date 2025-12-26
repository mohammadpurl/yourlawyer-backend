from typing import List, Optional
from langchain.memory import ConversationBufferMemory
from langchain_core.messages import HumanMessage, AIMessage

from app.models.user import Message


def create_memory_from_messages(messages: List[Message]) -> ConversationBufferMemory:
    """
    ایجاد یک ConversationBufferMemory از لیست پیام‌های دیتابیس.
    
    Args:
        messages: لیست پیام‌های یک گفتگو از دیتابیس
        
    Returns:
        ConversationBufferMemory که شامل تمام history است
    """
    memory = ConversationBufferMemory(
        memory_key="chat_history",
        return_messages=True,
        output_key="answer"
    )
    
    # اضافه کردن تمام پیام‌های قبلی به memory
    for msg in messages:
        if msg.role == "user":
            memory.chat_memory.add_user_message(msg.content)
        elif msg.role == "assistant":
            memory.chat_memory.add_ai_message(msg.content)
    
    return memory


def get_memory_messages(memory: ConversationBufferMemory) -> List:
    """
    دریافت لیست messages از memory برای استفاده در chain.
    
    Args:
        memory: ConversationBufferMemory instance
        
    Returns:
        لیست messages (HumanMessage, AIMessage)
    """
    return memory.chat_memory.messages

