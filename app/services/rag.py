import time
from typing import Dict, Any, Optional

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from langchain_ollama import OllamaLLM
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda
from langchain_classic.memory import ConversationBufferMemory

from app.services.vectorstore import get_vectorstore
from app.services.enhanced_retrieval import EnhancedRetriever
from app.services.question_classifier import classify_question, get_domain_label
from app.services.reranker import rerank_documents
from app.services.pipeline_timing import PipelineTimer
from app.core.config import (
    DEFAULT_TOP_K,
    OPENAI_API_KEY,
    OLLAMA_MODEL,
    DEFAULT_LLM_MODEL,
    LLM_MAX_COMPLETION_TOKENS,
    RAG_REQUIRE_RETRIEVED_CONTEXT,
    RAG_NO_CONTEXT_MESSAGE,
)
from app.core.cache import (
    cache_rag_result,
    get_cached_rag_result,
    cache_classification,
    get_cached_classification,
)
from app.core.pii_anonymizer import get_pii_anonymizer
from langchain_core.messages import AIMessage, HumanMessage, BaseMessage
from sqlalchemy.orm import Session

from app.models.user import User
from app.services.llm import call_llm_with_quota_check
from app.services.quota import QuotaExceeded
from app.services.citation_validator import (
    validate_citations,
    citation_accuracy_score,
)
from app.services.citation_quality import persist_citation_quality_log
from app.services.response_warnings import prepend_strong_warning
from fastapi import HTTPException


PERSIAN_LEGAL_SYSTEM_PROMPT = """
شما یک دستیار حقوقی متخصص در قوانین و مقررات جمهوری اسلامی ایران هستید.

محدودیت‌های اجباری (Citation Grounding):
- تو فقط باید بر اساس متن‌های ارائه‌شده در بخش «منابع بازیابی‌شده» پاسخ بدهی.
- هرگز از دانش عمومی یا حافظه خودت درباره قوانین ایران استفاده نکن.
- اگر اطلاعات کافی در منابع ارائه‌شده برای پاسخ به این سؤال وجود ندارد،
  دقیقاً همین جمله را بگو: «اطلاعات کافی در منابع موجود برای پاسخ دقیق به این سؤال یافت نشد.»
- هر جا به ماده یا تبصره قانونی اشاره می‌کنی، شماره دقیق آن را از متن منبع نقل کن،
  نه از حافظه خودت.
- اگر در سوال placeholderهایی مانند [PII_NAME_1] دیدی، آن‌ها را عیناً در پاسخ نگه دار.

فرمت پاسخ:
- ابتدا پاسخ اصلی را خلاصه و واضح ارائه کن
- سپس جزئیات و استدلال حقوقی بر اساس منابع
- در پایان فهرست منابع/مواد ذکرشده در متن منابع بازیابی‌شده را بیاور
""".strip()

NO_CONTEXT_ANSWER = RAG_NO_CONTEXT_MESSAGE


def _has_usable_context(docs: list, context: str) -> bool:
    """True only when retrieval returned non-empty grounded chunks."""
    if not docs:
        return False
    if not (context or "").strip():
        return False
    # Reject near-empty junk chunks
    return any((getattr(d, "page_content", "") or "").strip() for d in docs)


def _no_context_response(
    *,
    start_time: float,
    anonymizer,
    mappings,
    domain=None,
    confidence: float = 0.0,
) -> Dict[str, Any]:
    elapsed = time.time() - start_time
    answer = anonymizer.restore(NO_CONTEXT_ANSWER, mappings)
    payload: Dict[str, Any] = {
        "answer": answer,
        "sources": [],
        "response_time_seconds": round(elapsed, 3),
        "citation_count": 0,
        "citation_accuracy": 0.0,
        "citation_confidence": "unverified",
        "cited_articles": [],
        "unverified_citations": [],
        "grounded": False,
        "no_context": True,
    }
    if domain is not None:
        payload["domain"] = domain.value if hasattr(domain, "value") else domain
        payload["domain_label"] = get_domain_label(domain) if hasattr(domain, "value") else None
        payload["domain_confidence"] = round(confidence, 2)
    return payload


def _get_llm():
    if OPENAI_API_KEY:
        # Kept for Ollama/fallback detection; OpenAI path goes through quota wrapper.
        return ChatOpenAI(model=DEFAULT_LLM_MODEL, temperature=0)
    if OLLAMA_MODEL:
        return OllamaLLM(model=OLLAMA_MODEL, temperature=0)
    return None


def _extract_citations(answer: str, docs: list) -> list[str]:
    """Extract citation sources from answer and documents."""
    sources = []
    seen = set()

    for doc in docs:
        source = doc.metadata.get("source", "")
        if source and source not in seen:
            seen.add(source)
            sources.append(source)

    return sources


def _anonymize_chat_history(
    history_messages: list, anonymizer
) -> tuple[list, list]:
    """Anonymize memory messages for LLM; return new messages + mappings."""
    if not history_messages:
        return [], []

    contents = [getattr(m, "content", "") or "" for m in history_messages]
    anon_contents, mappings = anonymizer.anonymize_many(contents)
    anon_messages: list[BaseMessage] = []
    for msg, anon_content in zip(history_messages, anon_contents):
        if isinstance(msg, HumanMessage) or getattr(msg, "type", None) == "human":
            anon_messages.append(HumanMessage(content=anon_content))
        elif isinstance(msg, AIMessage) or getattr(msg, "type", None) == "ai":
            anon_messages.append(AIMessage(content=anon_content))
        else:
            try:
                anon_messages.append(msg.__class__(content=anon_content))
            except Exception:
                anon_messages.append(HumanMessage(content=anon_content))
    return anon_messages, mappings


def build_rag_chain(
    k: int = DEFAULT_TOP_K,
    use_enhanced_retrieval: bool = True,
    memory: Optional[ConversationBufferMemory] = None,
    use_reranking: bool = True,
    user: Optional[User] = None,
    db: Optional[Session] = None,
):
    """Build RAG chain with optional enhanced retrieval, reranking, and conversation memory.

    When OpenAI is used, generation goes through ``call_llm_with_quota_check``
    (requires ``user`` + ``db``). Classify/rerank today are local (zero OpenAI cost);
    if they later call paid models, route them through the same wrapper with
    pipeline_stage='classify'|'rerank'.
    """
    llm = _get_llm()
    use_openai = bool(OPENAI_API_KEY)

    # Initialize retrievers outside of closures to avoid cell issues
    if use_enhanced_retrieval:
        enhanced_retriever = EnhancedRetriever(enable_domain_filter=True)
        retriever = None
    else:
        vs = get_vectorstore()
        retriever = vs.as_retriever(search_kwargs={"k": k})
        enhanced_retriever = None

    # ساخت prompt با پشتیبانی از memory
    if memory:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", PERSIAN_LEGAL_SYSTEM_PROMPT),
                MessagesPlaceholder(variable_name="chat_history"),
                (
                    "human",
                    "سوال: {question}\n\nمنابع بازیابی‌شده:\n{context}\n\nپاسخ دقیق و مستند:",
                ),
            ]
        )
    else:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", PERSIAN_LEGAL_SYSTEM_PROMPT),
                (
                    "human",
                    "سوال: {question}\n\nمنابع بازیابی‌شده:\n{context}\n\nپاسخ دقیق و مستند:",
                ),
            ]
        )

    if llm is None:

        def run_fallback(question: str):
            start_time = time.time()
            anonymizer = get_pii_anonymizer()
            anon_question, mappings = anonymizer.anonymize(question)

            if use_enhanced_retrieval and enhanced_retriever:
                docs, domain, confidence = (
                    enhanced_retriever.retrieve_with_classification(anon_question, k=k)
                )
            elif retriever:
                docs = retriever.invoke("query: " + anon_question)
                domain, confidence = None, 0.0
            else:
                vs = get_vectorstore()
                basic_retriever = vs.as_retriever(search_kwargs={"k": k})
                docs = basic_retriever.invoke("query: " + anon_question)
                domain, confidence = None, 0.0

            context = "\n\n".join(d.page_content for d in docs)
            if RAG_REQUIRE_RETRIEVED_CONTEXT and not _has_usable_context(docs, context):
                return _no_context_response(
                    start_time=start_time,
                    anonymizer=anonymizer,
                    mappings=mappings,
                    domain=domain,
                    confidence=confidence or 0.0,
                )
            sources = _extract_citations(context, docs)
            answer = (
                "بر اساس متون یافت‌شده، موارد مرتبط در زیر آمده است. لطفاً با دقت مطالعه کنید و در صورت نیاز سوال را دقیق‌تر مطرح نمایید.\n\n"
                + context
            )
            answer = anonymizer.restore(answer, mappings)

            elapsed = time.time() - start_time
            return {
                "answer": answer,
                "sources": sources,
                "response_time_seconds": elapsed,
                "domain": domain.value if domain else None,
                "domain_confidence": confidence,
            }

        return run_fallback

    def _retrieve_docs(
        question: str,
        k_val: int,
        use_enhanced: bool,
        enh_retriever: EnhancedRetriever | None,
        std_retriever: Any | None,
        use_rerank: bool = True,
        timer: PipelineTimer | None = None,
    ):
        """Retrieve documents based on configuration.

        When ``timer`` is provided, stages classify / retrieve / rerank are marked
        separately (classify is local keyword/heuristic; retrieve is Chroma+embed).
        """
        retrieve_k = k_val * 2 if use_rerank else k_val
        retrieved_before_rerank = 0

        if use_enhanced and enh_retriever:
            # Split classify vs retrieve for timing (same logic as
            # retrieve_with_classification, including low-confidence skip +
            # empty-filter fallback inside EnhancedRetriever.retrieve).
            domain, confidence = classify_question(question)
            if timer:
                timer.mark("classify")
            apply_domain = domain
            if confidence < getattr(
                enh_retriever, "domain_filter_min_confidence", 0.35
            ):
                from app.services.question_classifier import LegalDomain as _LD

                apply_domain = _LD.UNKNOWN
            docs = enh_retriever.retrieve(question, k=retrieve_k, domain=apply_domain)
            if timer:
                timer.mark("retrieve")
        elif std_retriever:
            if timer:
                timer.mark("classify")  # skipped → ~0ms slot for schema consistency
            docs = std_retriever.invoke("query: " + question)
            domain, confidence = None, 0.0
            if timer:
                timer.mark("retrieve")
        else:
            if timer:
                timer.mark("classify")
            vs = get_vectorstore()
            basic_retriever = vs.as_retriever(search_kwargs={"k": retrieve_k})
            docs = basic_retriever.invoke("query: " + question)
            domain, confidence = None, 0.0
            if timer:
                timer.mark("retrieve")

        retrieved_before_rerank = len(docs) if docs else 0

        # Local CrossEncoder — no OpenAI cost today
        if use_rerank and docs:
            docs = rerank_documents(question, docs, top_k=k_val)
        if timer:
            timer.mark("rerank")
            timer.set_meta(
                retrieved_count=retrieved_before_rerank,
                reranked_count=len(docs) if docs else 0,
            )

        return docs, domain, confidence

    def _prepare_inputs(
        x: Dict[str, Any],
        k_val: int,
        use_enhanced: bool,
        enh_ret: EnhancedRetriever | None,
        std_ret: Any | None,
        mem: Optional[ConversationBufferMemory] = None,
        use_rerank: bool = True,
        timer: PipelineTimer | None = None,
    ) -> Dict[str, Any]:
        question = x["question"]
        docs, domain, confidence = _retrieve_docs(
            question,
            k_val,
            use_enhanced,
            enh_ret,
            std_ret,
            use_rerank,
            timer=timer,
        )

        if domain is not None:
            x["detected_domain"] = domain
            x["domain_confidence"] = confidence

        context = "\n\n".join(d.page_content for d in docs)
        x["context"] = context
        x["retrieved_docs"] = docs
        return x

    def run(question: str) -> Dict[str, Any]:
        import logging
        from uuid import uuid4

        logger = logging.getLogger(__name__)
        timer = PipelineTimer(request_id=str(uuid4()))
        timer.set_meta(
            model=DEFAULT_LLM_MODEL if use_openai else (OLLAMA_MODEL or "none"),
            use_enhanced_retrieval=use_enhanced_retrieval,
            use_reranking=use_reranking,
            top_k=k,
        )

        start_time = time.time()
        try:
            anonymizer = get_pii_anonymizer()
            anon_question, mappings = anonymizer.anonymize(question)
            timer.mark("anonymize")

            cached_result = get_cached_rag_result(
                anon_question, k, use_enhanced_retrieval
            )
            if cached_result:
                timer.mark("cache_lookup")
                timer.set_meta(cache_hit=True)
                logger.info(
                    "Cache hit for question: %s...",
                    anonymizer.anonymize_for_logging(question, max_len=50),
                )
                cached = dict(cached_result)
                if isinstance(cached.get("answer"), str):
                    cached["answer"] = anonymizer.restore(cached["answer"], mappings)
                return cached
            timer.mark("cache_lookup")
            timer.set_meta(cache_hit=False)

            inputs = {"question": anon_question}
            prepared = _prepare_inputs(
                inputs,
                k_val=k,
                use_enhanced=use_enhanced_retrieval,
                enh_ret=enhanced_retriever,
                std_ret=retriever,
                mem=memory,
                use_rerank=use_reranking,
                timer=timer,
            )
            docs = prepared.get("retrieved_docs", [])
            context = prepared.get("context", "") or ""

            # Hard gate: never call the LLM with empty / missing Chroma context
            if RAG_REQUIRE_RETRIEVED_CONTEXT and not _has_usable_context(docs, context):
                domain = prepared.get("detected_domain")
                confidence = prepared.get("domain_confidence", 0.0) or 0.0
                timer.set_meta(no_context=True)
                return _no_context_response(
                    start_time=start_time,
                    anonymizer=anonymizer,
                    mappings=mappings,
                    domain=domain,
                    confidence=confidence,
                )

            chain_inputs: Dict[str, Any] = {
                "question": anon_question,
                "context": context,
            }
            if memory:
                history_messages = memory.chat_memory.messages
                anon_history, history_maps = _anonymize_chat_history(
                    history_messages, anonymizer
                )
                mappings = list(mappings) + list(history_maps)
                chain_inputs["chat_history"] = anon_history

            # Format prompt → messages, then billable generate via quota wrapper
            messages = prompt.format_messages(**chain_inputs)
            usage_out: Dict[str, Any] = {}

            if use_openai:
                if user is None or db is None:
                    raise HTTPException(
                        status_code=500,
                        detail="پیکربندی ناقص محدودیت مصرف برای فراخوانی مدل",
                    )
                try:
                    result_text = call_llm_with_quota_check(
                        messages=messages,
                        user=user,
                        db=db,
                        model=DEFAULT_LLM_MODEL,
                        pipeline_stage="generate",
                        max_completion_tokens=LLM_MAX_COMPLETION_TOKENS,
                        request_id=timer.request_id,
                        usage_out=usage_out,
                    )
                except HTTPException:
                    raise
                except QuotaExceeded as e:
                    raise HTTPException(
                        status_code=e.status_code, detail=e.message
                    ) from e
            else:
                ollama_chain = prompt | llm | StrOutputParser()
                result_text = ollama_chain.invoke(chain_inputs)

            timer.mark("generate")
            if usage_out:
                timer.set_meta(
                    prompt_tokens=usage_out.get("prompt_tokens"),
                    completion_tokens=usage_out.get("completion_tokens"),
                    cost_usd=usage_out.get("cost_usd"),
                )

            sources = _extract_citations(result_text, docs)
            elapsed = time.time() - start_time

            chunk_texts = [getattr(d, "page_content", "") or "" for d in docs]
            citation_result = validate_citations(result_text, chunk_texts)
            citation_accuracy = citation_accuracy_score(citation_result)

            if (
                citation_result.confidence_flag == "unverified"
                and citation_result.cited_articles
            ):
                result_text = prepend_strong_warning(
                    result_text, reason="citation_unverified"
                )
            elif citation_result.confidence_flag == "partial":
                result_text = prepend_strong_warning(
                    result_text, reason="partial_citation"
                )

            if db is not None:
                persist_citation_quality_log(
                    db,
                    result=citation_result,
                    user_id=getattr(user, "id", None) if user else None,
                    request_id=timer.request_id,
                )

            cached_payload = {
                "answer": result_text,
                "sources": sources,
                "response_time_seconds": round(elapsed, 3),
                "citation_count": len(citation_result.cited_articles),
                "citation_accuracy": citation_accuracy,
                "citation_confidence": citation_result.confidence_flag,
                "cited_articles": citation_result.cited_articles,
                "unverified_citations": citation_result.unverified_citations,
                "grounded": True,
                "no_context": False,
            }

            if use_enhanced_retrieval:
                domain = prepared.get("detected_domain")
                confidence = prepared.get("domain_confidence", 0.0)
                cached_payload["domain"] = domain.value if domain else None
                cached_payload["domain_label"] = (
                    get_domain_label(domain) if domain else None
                )
                cached_payload["domain_confidence"] = round(confidence, 2)

            cache_rag_result(
                anon_question, k, use_enhanced_retrieval, cached_payload, ttl=3600
            )

            response = dict(cached_payload)
            response["answer"] = anonymizer.restore(result_text, mappings)
            return response
        finally:
            try:
                timer.log_summary(logger)
            except Exception:
                logger.exception("Failed to log PIPELINE_TIMING")

    return run
