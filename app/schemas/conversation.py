from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class MessageResponse(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationSummary(BaseModel):
    id: int
    title: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationDetail(ConversationSummary):
    messages: List[MessageResponse] = []


class CreateConversationRequest(BaseModel):
    title: Optional[str] = None


class ChatRequest(BaseModel):
    question: str
    top_k: Optional[int] = None
    use_enhanced_retrieval: Optional[bool] = None


class ChatResponse(BaseModel):
    conversation_id: int
    answer: str
    sources: List[str] = []
    response_time_seconds: Optional[float] = None
    citation_count: Optional[int] = None
    citation_accuracy: Optional[float] = None
    domain: Optional[str] = None
    domain_label: Optional[str] = None
    domain_confidence: Optional[float] = None
