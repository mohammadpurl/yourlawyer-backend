import time
from functools import partial
from typing import Dict, Any, Optional

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_community.chat_models import ChatOpenAI
from langchain_community.llms import Ollama
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda
from langchain.memory import ConversationBufferMemory

from app.services.vectorstore import get_vectorstore
from app.services.enhanced_retrieval import EnhancedRetriever
from app.services.question_classifier import classify_question, get_domain_label
from app.services.reranker import rerank_documents
from app.core.config import DEFAULT_TOP_K, OPENAI_API_KEY, OLLAMA_MODEL
from app.core.cache import (
    cache_rag_result,
    get_cached_rag_result,
    cache_classification,
    get_cached_classification,
)


PERSIAN_LEGAL_SYSTEM_PROMPT = """
شما یک دستیار حقوقی متخصص و باتجربه در قوانین و مقررات جمهوری اسلامی ایران هستید.

وظایف شما:
1. تحلیل دقیق سوال کاربر و شناسایی حوزه حقوقی مرتبط (کیفری، مدنی، خانواده، تجاری)
2. استخراج و ارائه اطلاعات دقیق از متون قانونی بازیابی‌شده
3. ارائه پاسخ مستند با ذکر دقیق مواد قانونی، اصول و مقررات مرتبط
4. در صورت عدم قطعیت، صراحتاً بیان کنید که پاسخ بر اساس مدارک موجود است و ممکن است نیاز به مشورت با وکیل داشته باشد

قوانین پاسخ‌دهی:
- فقط بر اساس متون بازیابی‌شده پاسخ بده و از حدس زدن یا اطلاعات خارج از متن خودداری کن
- همیشه مواد قانونی، شماره اصل، نام قانون و منبع را به صورت دقیق ذکر کن
- اگر اطلاعات کافی نیست، صادقانه بگو که نیاز به اطلاعات بیشتر است
- پاسخ را به زبان فارسی رسمی، واضح و قابل فهم بنویس
- در پایان، فهرست کاملی از منابع و مواد قانونی استفاده شده را ارائه کن

فرمت پاسخ:
- ابتدا پاسخ اصلی را به صورت خلاصه و واضح ارائه کن
- سپس جزئیات و استدلال‌های حقوقی را شرح بده
- در پایان، فهرست منابع را به این صورت ارائه کن:
  * ماده X قانون Y
  * اصل Z قانون اساسی
  * منبع: [نام فایل/سند]
""".strip()


def _get_llm():
    if OPENAI_API_KEY:
        return ChatOpenAI(model="gpt-4o-mini", temperature=0)
    if OLLAMA_MODEL:
        return Ollama(model=OLLAMA_MODEL, temperature=0)
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


def build_rag_chain(
    k: int = DEFAULT_TOP_K,
    use_enhanced_retrieval: bool = True,
    memory: Optional[ConversationBufferMemory] = None,
    use_reranking: bool = True,
):
    """Build RAG chain with optional enhanced retrieval, reranking, and conversation memory."""
    llm = _get_llm()

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
        # اگر memory داریم، از MessagesPlaceholder استفاده می‌کنیم
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", PERSIAN_LEGAL_SYSTEM_PROMPT),
                MessagesPlaceholder(variable_name="chat_history"),
                (
                    "human",
                    "سوال: {question}\n\nمتون بازیابی‌شده:\n{context}\n\nپاسخ دقیق و مستند:",
                ),
            ]
        )
    else:
        # بدون memory، prompt ساده
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", PERSIAN_LEGAL_SYSTEM_PROMPT),
                (
                    "human",
                    "سوال: {question}\n\nمتون بازیابی‌شده:\n{context}\n\nپاسخ دقیق و مستند:",
                ),
            ]
        )

    if llm is None:

        def run_fallback(question: str):
            start_time = time.time()

            if use_enhanced_retrieval and enhanced_retriever:
                docs, domain, confidence = (
                    enhanced_retriever.retrieve_with_classification(question, k=k)
                )
            elif retriever:
                docs = retriever.invoke("query: " + question)
                domain, confidence = None, 0.0
            else:
                # Fallback: create a basic retriever
                vs = get_vectorstore()
                basic_retriever = vs.as_retriever(search_kwargs={"k": k})
                docs = basic_retriever.invoke("query: " + question)
                domain, confidence = None, 0.0

            context = "\n\n".join(d.page_content for d in docs)
            sources = _extract_citations(context, docs)
            answer = (
                "بر اساس متون یافت‌شده، موارد مرتبط در زیر آمده است. لطفاً با دقت مطالعه کنید و در صورت نیاز سوال را دقیق‌تر مطرح نمایید.\n\n"
                + context
            )

            elapsed = time.time() - start_time
            return {
                "answer": answer,
                "sources": sources,
                "response_time_seconds": elapsed,
                "domain": domain.value if domain else None,
                "domain_confidence": confidence,
            }

        return run_fallback

    # Create a helper function that accepts retrievers as parameters to avoid closure issues
    def _retrieve_docs(
        question: str,
        k_val: int,
        use_enhanced: bool,
        enh_retriever: EnhancedRetriever | None,
        std_retriever: Any | None,
        use_rerank: bool = True,
    ):
        """Retrieve documents based on configuration."""
        # Retrieve more documents if reranking is enabled (to get better candidates)
        retrieve_k = k_val * 2 if use_rerank else k_val

        if use_enhanced and enh_retriever:
            docs, domain, confidence = enh_retriever.retrieve_with_classification(
                question, k=retrieve_k
            )
        elif std_retriever:
            docs = std_retriever.invoke("query: " + question)
            domain, confidence = None, 0.0
        else:
            # Fallback
            vs = get_vectorstore()
            basic_retriever = vs.as_retriever(search_kwargs={"k": retrieve_k})
            docs = basic_retriever.invoke("query: " + question)
            domain, confidence = None, 0.0

        # Apply reranking if enabled
        if use_rerank and docs:
            docs = rerank_documents(question, docs, top_k=k_val)

        return docs, domain, confidence

    def _prepare_inputs(
        x: Dict[str, Any],
        k_val: int,
        use_enhanced: bool,
        enh_ret: EnhancedRetriever | None,
        std_ret: Any | None,
        mem: Optional[ConversationBufferMemory] = None,
        use_rerank: bool = True,
    ) -> Dict[str, Any]:
        question = x["question"]
        docs, domain, confidence = _retrieve_docs(
            question, k_val, use_enhanced, enh_ret, std_ret, use_rerank
        )

        if domain is not None:
            x["detected_domain"] = domain
            x["domain_confidence"] = confidence

        context = "\n\n".join(d.page_content for d in docs)
        x["context"] = context
        x["retrieved_docs"] = docs
        # توجه: history از memory مستقیماً در run function خوانده می‌شود
        return x

    # Use partial to bind parameters and avoid closure variable issues
    _prepare_inputs_bound = partial(
        _prepare_inputs,
        k_val=k,
        use_enhanced=use_enhanced_retrieval,
        enh_ret=enhanced_retriever,
        std_ret=retriever,
        mem=memory,
        use_rerank=use_reranking,
    )

    chain = RunnableLambda(_prepare_inputs_bound) | prompt | llm | StrOutputParser()

    def run(question: str) -> Dict[str, Any]:
        start_time = time.time()

        # Check cache first
        cache_key_params = (question, k, use_enhanced_retrieval)
        cached_result = get_cached_rag_result(question, k, use_enhanced_retrieval)
        if cached_result:
            import logging

            logger = logging.getLogger(__name__)
            logger.info(f"Cache hit for question: {question[:50]}...")
            return cached_result

        # Prepare inputs (includes retrieval and memory)
        inputs = {"question": question}
        prepared = _prepare_inputs_bound(inputs)
        docs = prepared.get("retrieved_docs", [])

        # Generate answer with memory context
        chain_inputs = {
            "question": question,
            "context": prepared.get("context", ""),
        }
        # اضافه کردن history اگر memory وجود داشته باشد (مستقیماً از memory بخوانیم)
        if memory:
            # باید history را مستقیماً از memory بخوانیم (نه از prepared)
            # چون memory ممکن است بعد از prepared به‌روز شده باشد
            history_messages = memory.chat_memory.messages
            chain_inputs["chat_history"] = history_messages
            # لاگ برای دیباگ (می‌توانید بعداً حذف کنید)
            import logging

            logger = logging.getLogger(__name__)
            logger.info(f"Memory history contains {len(history_messages)} messages")

        result_text = chain.invoke(chain_inputs)

        # توجه: سوال و پاسخ در دیتابیس ذخیره می‌شوند
        # memory فقط برای این درخواست استفاده می‌شود و بعد از آن از بین می‌رود
        # دفعه بعد که کاربر سوال بپرسد، memory دوباره از دیتابیس ساخته می‌شود

        # Extract citations
        sources = _extract_citations(result_text, docs)

        # Calculate metrics
        elapsed = time.time() - start_time
        citation_count = len(sources)
        has_citations = citation_count > 0

        # Check if answer contains citations (simple heuristic)
        answer_has_citations = any(
            keyword in result_text
            for keyword in ["ماده", "اصل", "قانون", "منبع", "منابع"]
        )
        citation_accuracy = 1.0 if (has_citations and answer_has_citations) else 0.5

        response = {
            "answer": result_text,
            "sources": sources,
            "response_time_seconds": round(elapsed, 3),
            "citation_count": citation_count,
            "citation_accuracy": citation_accuracy,
        }

        if use_enhanced_retrieval:
            domain = prepared.get("detected_domain")
            confidence = prepared.get("domain_confidence", 0.0)
            response["domain"] = domain.value if domain else None
            response["domain_label"] = get_domain_label(domain) if domain else None
            response["domain_confidence"] = round(confidence, 2)

        # Cache the result
        cache_rag_result(question, k, use_enhanced_retrieval, response, ttl=3600)

        return response

    return run
