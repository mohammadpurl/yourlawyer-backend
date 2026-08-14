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
from app.services.question_classifier import get_domain_label
from app.services.reranker import rerank_documents, score_documents, filter_by_min_score
from app.services.pipeline_timing import PipelineTimer
from app.core.config import (
    DEFAULT_TOP_K,
    OPENAI_API_KEY,
    OLLAMA_MODEL,
    DEFAULT_LLM_MODEL,
    LLM_MAX_COMPLETION_TOKENS,
    RAG_REQUIRE_RETRIEVED_CONTEXT,
    RAG_NO_CONTEXT_MESSAGE,
    RERANKER_ENABLED,
    ENABLE_DOMAIN_FILTERED_RETRIEVAL,
)
from app.core.cache import (
    cache_rag_result,
    get_cached_rag_result,
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
from app.config.expert_opinion_domains import (
    detect_expert_opinion_domain,
    expert_opinion_api_payload,
    expert_opinion_prompt_addon,
)


PERSIAN_LEGAL_SYSTEM_PROMPT = """
شما یک دستیار حقوقی متخصص در قوانین و مقررات جمهوری اسلامی ایران هستید.

محدودیت‌های اجباری (Citation Grounding):
- پاسخ را بر اساس متن‌های بخش «منابع بازیابی‌شده» بنویس؛ از دانش عمومی و حافظهٔ خودت درباره قوانین استفاده نکن.
- اگر حتی بخشی از منابع به سوال مربوط است (مثلاً ایمنی کار، حفاظت فنی، بیمه کارگران ساختمانی، مسئولیت کارفرما)،
  حق نداری پاسخ را با جملهٔ کامل امتناع شروع کنی. باید پاسخ جزئی بدهی.
- ساختار پاسخ جزئی وقتی پوشش کامل نیست (اجباری):
  1) «آنچه از منابع برمی‌آید»: نکات قابل استناد از همان منابع
  2) «آنچه در منابع نیست»: صریح بگو چه بخشی از سوال (مثلاً درصد تقصیر، تفکیک مالک و پیمانکار جزء) در منابع نبود
  3) فهرست منابع فقط موادی که در بخش ۱ واقعاً استفاده کردی
- فقط وقتی هیچ‌یک از منابع حتی به‌صورت جزئی به موضوع سوال مربوط نیست، بگو:
  «اطلاعات کافی در منابع موجود برای پاسخ دقیق به این سؤال یافت نشد.»
  و کوتاه بگو چه نوع منبعی لازم است. در این حالت فهرست منابع ننویس.
- هر جا به ماده یا تبصره اشاره می‌کنی، شماره را فقط از متن منبع بیاور، نه از حافظه.
- هیچ شرط یا مرحله‌ای را که در منابع پشتوانه ندارد — حتی اگر «معمولاً درست» به نظر برسد — ذکر نکن.
- اگر در سوال placeholderهایی مانند [PII_NAME_1] دیدی، آن‌ها را عیناً در پاسخ نگه دار.
- برای سؤال درباره «درصد تقصیر»: اگر منابع عدد درصد نداده‌اند، درصد اختراع نکن؛ چارچوب تعهدات/ایمنی/بیمه موجود را بگو و نبود درصد را اعلام کن.

جامعیت برای سوالات «شرایط» / «مراحل» / «شرایط و مراحل»:
- اگر منابع هم شرایط ماهوی و هم مراحل اجرایی را پوشش می‌دهند، پاسخ را در دو بخش جدا با عناوین دقیق «شرایط» و «مراحل اجرایی» بنویس.
- اگر منابع فقط یکی از این دو را پوشش می‌دهند، همان بخش موجود را با استناد کامل بنویس و صریحاً اعلام کن که برای بخش دیگر در منابع بازیابی‌شده اطلاعات کافی نبود — نه سکوت کن و نه از دانش عمومی پر کن.

فرمت پاسخ:
- ابتدا پاسخ اصلی (یا دو بخش آنچه برمی‌آید / آنچه نیست)
- سپس جزئیات و استدلال حقوقی بر اساس منابع
- در پایان فقط فهرست منابع واقعاً استفاده‌شده
""".strip()

PARTIAL_ANSWER_RETRY_INSTRUCTION = """
منابع بازیابی‌شده خالی نیستند و به موضوع کارگر/ساختمان/ایمنی/بیمه مرتبط‌اند.
حق نداری پاسخ را با «اطلاعات کافی در منابع موجود برای پاسخ دقیق به این سؤال یافت نشد» شروع کنی.
حتماً با دو عنوان بنویس: «آنچه از منابع برمی‌آید» و «آنچه در منابع نیست».
درصد تقصیر را اگر در منابع نیست ننویس. فهرست منابع فقط برای استنادهای بخش اول.
""".strip()

NO_CONTEXT_ANSWER = RAG_NO_CONTEXT_MESSAGE

_WORKPLACE_QUERY_CUES = (
    "کارگر",
    "ساختمان",
    "سقوط",
    "ایمنی",
    "کارفرما",
    "حادثه",
    "حفاظت",
    "پیمانکار",
    "مالک",
    "ارتفاع",
)

_WORKPLACE_EXTRA_QUERIES = (
    "مسئولیت کارفرما ایمنی کارگاه حفاظت فنی قانون کار",
    "آیین نامه حفاظت فنی وسایل ایمنی ساختمان سقوط از ارتفاع",
    "بیمه اجباری کارگران ساختمانی تعهدات کارفرما",
)


def _is_full_refuse_answer(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    marker = (RAG_NO_CONTEXT_MESSAGE or "").strip()
    if marker and marker in t[:180]:
        return True
    return t.startswith("اطلاعات کافی در منابع موجود")


def _needs_workplace_expansion(question: str) -> bool:
    q = (question or "").replace("\u200c", " ")
    hits = sum(1 for c in _WORKPLACE_QUERY_CUES if c in q)
    return hits >= 2


def _dedupe_docs(docs: list) -> list:
    seen: set[str] = set()
    out = []
    for doc in docs:
        meta = getattr(doc, "metadata", None) or {}
        key = str(meta.get("content_hash") or "") or (
            (getattr(doc, "page_content", "") or "")[:240]
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(doc)
    return out


def rag_error_payload(message: str, status_code: int = 400) -> Dict[str, Any]:
    """Structured RAG failure returned as HTTP 200 so chat UIs can show the message."""
    return {
        "answer": message,
        "sources": [],
        "is_error": True,
        "error_code": status_code,
    }


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
    expert_opinion_required: dict | None = None,
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
    if expert_opinion_required:
        payload["expert_opinion_required"] = expert_opinion_required
    return payload


def _get_llm():
    if OPENAI_API_KEY:
        # Kept for Ollama/fallback detection; OpenAI path goes through quota wrapper.
        return ChatOpenAI(model=DEFAULT_LLM_MODEL, temperature=0)
    if OLLAMA_MODEL:
        return OllamaLLM(model=OLLAMA_MODEL, temperature=0)
    return None


def _citation_label(metadata: dict | None) -> str:
    """Human-readable citation, e.g. «ماده 114 قانون مدنی» — not the upload filename."""
    meta = metadata or {}
    kind = str(meta.get("unit_kind") or "").strip()
    num = str(
        meta.get("article_number") or meta.get("unit_title") or ""
    ).strip()
    law = str(meta.get("law_name") or "").strip()

    if kind and num and law:
        return f"{kind} {num} {law}"
    if kind and num:
        return f"{kind} {num}"
    if law:
        return law

    # Last resort: strip path/extension and numeric id prefix from filename
    raw = str(meta.get("source") or "").strip()
    if not raw:
        return ""
    from pathlib import Path
    import re

    stem = Path(raw).stem
    match = re.match(r"^(\d+)[_.\-\s]+(.+)$", stem)
    if match:
        return match.group(2).strip() or stem
    return stem


def _extract_citations(answer: str, docs: list) -> list[str]:
    """Build unique human-readable citation labels from retrieved chunks."""
    sources: list[str] = []
    seen: set[str] = set()

    for doc in docs:
        label = _citation_label(getattr(doc, "metadata", None) or {})
        if not label:
            continue
        key = " ".join(label.split())
        if key in seen:
            continue
        seen.add(key)
        sources.append(label)

    return sources


def _format_context(docs: list) -> str:
    """Join retrieved chunks with citation labels so the LLM cites articles, not files."""
    parts: list[str] = []
    for i, doc in enumerate(docs, 1):
        content = (getattr(doc, "page_content", "") or "").strip()
        if not content:
            continue
        label = _citation_label(getattr(doc, "metadata", None) or {})
        if label:
            parts.append(f"[منبع {i}: {label}]\n{content}")
        else:
            parts.append(content)
    return "\n\n".join(parts)


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
    use_reranking: bool | None = None,
    user: Optional[User] = None,
    db: Optional[Session] = None,
):
    """Build RAG chain with optional enhanced retrieval, reranking, and conversation memory.

    When OpenAI is used, generation goes through ``call_llm_with_quota_check``
    (requires ``user`` + ``db``). Classify/rerank today are local (zero OpenAI cost);
    if they later call paid models, route them through the same wrapper with
    pipeline_stage='classify'|'rerank'.
    """
    if use_reranking is None:
        use_reranking = RERANKER_ENABLED
    llm = _get_llm()
    use_openai = bool(OPENAI_API_KEY)

    # Initialize retrievers outside of closures to avoid cell issues
    if use_enhanced_retrieval:
        # Domain metadata in current corpus is mostly "unknown"; filtering
        # previously returned 0 docs and triggered the no-context refusal.
        enhanced_retriever = EnhancedRetriever(enable_domain_filter=False)
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
        separately (classify is taxonomy+heuristic; retrieve is Chroma+embed).
        """
        retrieve_k = k_val * 2 if use_rerank else k_val
        retrieved_before_rerank = 0
        tax_meta: Dict[str, Any] = {}

        if use_enhanced and enh_retriever:
            from app.services.taxonomy import classify_confident
            from app.services.question_classifier import taxonomy_to_legacy

            tax = classify_confident(question)
            tax_meta = tax
            domain = taxonomy_to_legacy(tax.get("domain"))
            confidence = float(tax.get("confidence") or 0.0)
            if timer:
                timer.mark("classify")
                timer.set_meta(
                    taxonomy_domain=tax.get("domain"),
                    taxonomy_subdomain=tax.get("subdomain"),
                    taxonomy_confidence=tax.get("confidence"),
                    taxonomy_confident=tax.get("confident"),
                )

            tax_domain = tax.get("domain") if tax.get("confident") else None
            tax_sub = tax.get("subdomain") if tax.get("confident") else None

            docs = enh_retriever.retrieve(
                question,
                k=retrieve_k,
                taxonomy_domain=tax_domain if ENABLE_DOMAIN_FILTERED_RETRIEVAL else None,
                taxonomy_subdomain=tax_sub if ENABLE_DOMAIN_FILTERED_RETRIEVAL else None,
            )
            # Workplace-accident questions: pull safety / employer-duty chunks too
            if _needs_workplace_expansion(question):
                expanded: list = list(docs or [])
                for extra_q in _WORKPLACE_EXTRA_QUERIES:
                    extra_docs = enh_retriever.retrieve(
                        extra_q,
                        k=max(4, retrieve_k // 2),
                        taxonomy_domain=(
                            tax_domain if ENABLE_DOMAIN_FILTERED_RETRIEVAL else None
                        ),
                        taxonomy_subdomain=(
                            tax_sub if ENABLE_DOMAIN_FILTERED_RETRIEVAL else None
                        ),
                    )
                    expanded.extend(extra_docs or [])
                docs = _dedupe_docs(expanded)
                if timer:
                    timer.set_meta(workplace_query_expansion=True)
            if timer:
                timer.mark("retrieve")
        elif std_retriever:
            if timer:
                timer.mark("classify")
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

        # Always apply relevance score filter (CrossEncoder or keyword fallback)
        if docs:
            if use_rerank:
                docs = rerank_documents(question, docs, top_k=k_val)
            else:
                scored = score_documents(question, docs)
                docs = filter_by_min_score(scored)[:k_val]
        if timer:
            timer.mark("rerank")
            timer.set_meta(
                retrieved_count=retrieved_before_rerank,
                reranked_count=len(docs) if docs else 0,
                low_trust_retrieval=not bool(tax_meta.get("confident")),
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

        context = _format_context(docs)
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
            # Parallel to taxonomy classify: keyword detect expert-opinion domains
            expert_domain = detect_expert_opinion_domain(question)
            expert_payload = expert_opinion_api_payload(expert_domain)
            if expert_domain:
                timer.set_meta(
                    expert_opinion_domain=expert_domain.get("id"),
                    expert_opinion_required=True,
                )

            anonymizer = get_pii_anonymizer()
            anon_question, mappings = anonymizer.anonymize(question)
            timer.mark("anonymize")

            cached_result = get_cached_rag_result(
                anon_question, k, use_enhanced_retrieval
            )
            cached_answer = (
                cached_result.get("answer")
                if isinstance(cached_result, dict)
                else None
            )
            skip_refuse_cache = isinstance(cached_answer, str) and _is_full_refuse_answer(
                cached_answer
            )
            if cached_result and not skip_refuse_cache:
                timer.mark("cache_lookup")
                timer.set_meta(cache_hit=True)
                logger.info(
                    "Cache hit for question: %s...",
                    anonymizer.anonymize_for_logging(question, max_len=50),
                )
                cached = dict(cached_result)
                if isinstance(cached.get("answer"), str):
                    cached["answer"] = anonymizer.restore(cached["answer"], mappings)
                if expert_payload:
                    cached["expert_opinion_required"] = expert_payload
                return cached
            timer.mark("cache_lookup")
            timer.set_meta(cache_hit=False, cache_skipped_refuse=skip_refuse_cache)

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
                retrieved_n = timer.meta.get("retrieved_count", 0)
                kept_n = timer.meta.get("reranked_count", len(docs) if docs else 0)
                timer.set_meta(no_context=True, kept_count=kept_n)
                logger.warning(
                    "RAG no-context gate | request_id=%s | retrieved=%s | kept=%s | "
                    "domain=%s | taxonomy=%s/%s",
                    timer.request_id,
                    retrieved_n,
                    kept_n,
                    getattr(domain, "value", domain),
                    timer.meta.get("taxonomy_domain"),
                    timer.meta.get("taxonomy_subdomain"),
                )
                return _no_context_response(
                    start_time=start_time,
                    anonymizer=anonymizer,
                    mappings=mappings,
                    domain=domain,
                    confidence=confidence,
                    expert_opinion_required=expert_payload,
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

            # System prompt: base + optional expert-opinion guidance
            system_text = PERSIAN_LEGAL_SYSTEM_PROMPT
            if expert_domain:
                system_text = (
                    f"{PERSIAN_LEGAL_SYSTEM_PROMPT}\n\n"
                    f"{expert_opinion_prompt_addon(expert_domain)}"
                )
            if memory:
                gen_prompt = ChatPromptTemplate.from_messages(
                    [
                        ("system", system_text),
                        MessagesPlaceholder(variable_name="chat_history"),
                        (
                            "human",
                            "سوال: {question}\n\nمنابع بازیابی‌شده:\n{context}\n\n"
                            "پاسخ دقیق و مستند:",
                        ),
                    ]
                )
            else:
                gen_prompt = ChatPromptTemplate.from_messages(
                    [
                        ("system", system_text),
                        (
                            "human",
                            "سوال: {question}\n\nمنابع بازیابی‌شده:\n{context}\n\n"
                            "پاسخ دقیق و مستند:",
                        ),
                    ]
                )

            # Format prompt → messages, then billable generate via quota wrapper
            messages = gen_prompt.format_messages(**chain_inputs)
            usage_out: Dict[str, Any] = {}

            if use_openai:
                if user is None or db is None:
                    return rag_error_payload(
                        "پیکربندی ناقص محدودیت مصرف برای فراخوانی مدل",
                        500,
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
                except HTTPException as e:
                    detail = e.detail if isinstance(e.detail, str) else str(e.detail)
                    return rag_error_payload(detail, e.status_code)
                except QuotaExceeded as e:
                    return rag_error_payload(e.message, e.status_code)
            else:
                ollama_chain = gen_prompt | llm | StrOutputParser()
                result_text = ollama_chain.invoke(chain_inputs)

            # If model full-refused despite retrieved docs, one forced partial retry
            if docs and _is_full_refuse_answer(result_text):
                logger.warning(
                    "Partial-answer retry | request_id=%s | retrieved=%s",
                    timer.request_id,
                    len(docs),
                )
                timer.set_meta(partial_answer_retry=True)
                retry_messages = list(messages) + [
                    HumanMessage(content=PARTIAL_ANSWER_RETRY_INSTRUCTION)
                ]
                if use_openai:
                    if user is not None and db is not None:
                        try:
                            result_text = call_llm_with_quota_check(
                                messages=retry_messages,
                                user=user,
                                db=db,
                                model=DEFAULT_LLM_MODEL,
                                pipeline_stage="generate_partial_retry",
                                max_completion_tokens=LLM_MAX_COMPLETION_TOKENS,
                                request_id=timer.request_id,
                                usage_out=usage_out,
                            )
                        except (HTTPException, QuotaExceeded):
                            pass
                else:
                    retry_inputs = dict(chain_inputs)
                    retry_inputs["question"] = (
                        f"{anon_question}\n\n{PARTIAL_ANSWER_RETRY_INSTRUCTION}"
                    )
                    result_text = (gen_prompt | llm | StrOutputParser()).invoke(
                        retry_inputs
                    )

            timer.mark("generate")
            if usage_out:
                timer.set_meta(
                    prompt_tokens=usage_out.get("prompt_tokens"),
                    completion_tokens=usage_out.get("completion_tokens"),
                    cost_usd=usage_out.get("cost_usd"),
                )

            sources = _extract_citations(result_text, docs)
            # Don't show contradictory source list under a full refuse
            if _is_full_refuse_answer(result_text):
                sources = []
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
            if expert_payload:
                cached_payload["expert_opinion_required"] = expert_payload

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
