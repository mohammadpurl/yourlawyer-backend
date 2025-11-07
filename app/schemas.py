from pydantic import BaseModel, Field
from typing import List, Optional


class AskRequest(BaseModel):
    question: str = Field(..., description="Persian legal question")
    top_k: Optional[int] = Field(5, description="Number of chunks to retrieve")


class AskResponse(BaseModel):
    answer: str
    sources: List[str] = []

