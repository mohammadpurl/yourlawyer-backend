from typing import List, Optional

from pydantic import BaseModel, Field


class FolderPathRequest(BaseModel):
    """درخواست برای پردازش فولدر از مسیر محلی سرور"""

    folder_path: str = Field(..., description="مسیر فولدر حاوی فایل‌های Word")
    recursive: bool = Field(True, description="آیا در زیرفولدرها هم جستجو شود")


class AskRequest(BaseModel):
    question: str = Field(..., description="Persian legal question")
    top_k: Optional[int] = Field(8, description="Number of chunks to retrieve")
    # conversation_id می‌تواند موقتاً به صورت string (مثل temp_...) از فرانت ارسال شود.
    # ما در روتر آن را به int معتبر تبدیل می‌کنیم.
    conversation_id: Optional[str] = Field(None, description="Conversation ID")
    use_enhanced_retrieval: Optional[bool] = Field(
        True, description="Use domain-aware retrieval"
    )


class ExpertOpinionRequired(BaseModel):
    """Separate from citation confidence — law defers quantum to an expert."""

    flag: bool = True
    expert_type: Optional[str] = None
    domain_label: Optional[str] = None
    domain_id: Optional[str] = None
    guidance_factors_hint: Optional[str] = None


class AskResponse(BaseModel):
    answer: str
    sources: List[str] = []
    # When quota/plan blocks the request, answer carries the Persian message for the UI.
    is_error: bool = False
    error_code: Optional[int] = None
    conversation_id: Optional[int] = None
    response_time_seconds: Optional[float] = None
    citation_count: Optional[int] = None
    citation_accuracy: Optional[float] = None
    citation_confidence: Optional[str] = None
    cited_articles: List[str] = []
    unverified_citations: List[str] = []
    domain: Optional[str] = None
    domain_label: Optional[str] = None
    domain_confidence: Optional[float] = None
    expert_opinion_required: Optional[ExpertOpinionRequired] = None


class SourceInfo(BaseModel):
    """اطلاعات یک فایل ذخیره شده"""

    source: str
    chunk_count: int


class StoredSourcesResponse(BaseModel):
    """پاسخ برای لیست فایل‌های ذخیره شده"""

    total_files: int
    total_chunks: int
    sources: List[SourceInfo]
