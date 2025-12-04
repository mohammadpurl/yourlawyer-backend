from pydantic import BaseModel, Field
from typing import List, Optional


class AskRequest(BaseModel):
    question: str = Field(..., description="Persian legal question")
    top_k: Optional[int] = Field(5, description="Number of chunks to retrieve")
    use_enhanced_retrieval: Optional[bool] = Field(
        True, description="Use domain-aware retrieval"
    )


class AskResponse(BaseModel):
    answer: str
    sources: List[str] = []
    response_time_seconds: Optional[float] = None
    citation_count: Optional[int] = None
    citation_accuracy: Optional[float] = None
    domain: Optional[str] = None
    domain_label: Optional[str] = None
    domain_confidence: Optional[float] = None
