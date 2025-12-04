import time
from functools import partial
from typing import Dict, Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_community.chat_models import ChatOpenAI
from langchain_community.llms import Ollama
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda

from app.services.vectorstore import get_vectorstore
from app.services.enhanced_retrieval import EnhancedRetriever
from app.services.question_classifier import classify_question, get_domain_label
from app.core.config import DEFAULT_TOP_K, OPENAI_API_KEY, OLLAMA_MODEL


PERSIAN_LEGAL_SYSTEM_PROMPT = """
شما یک دستیار حقوقی متخصص در قوانین و مقررات ایران هستید. 
با تکیه بر متون بازیابی‌شده، به پرسش پاسخ دقیق و مستند بده. اگر پاسخ قطعی نیست، عدم قطعیت را بیان کن و به منابع اشاره کن.
از حدس زدن خودداری کن و فقط بر اساس مدارک ارائه شده پاسخ بده. در پایان، مواد قانونی و منبع را فهرست کن.
زبان پاسخ: فارسی رسمی و روان.
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


def build_rag_chain(k: int = DEFAULT_TOP_K, use_enhanced_retrieval: bool = True):
    """Build RAG chain with optional enhanced retrieval."""
    llm = _get_llm()

    # Initialize retrievers outside of closures to avoid cell issues
    if use_enhanced_retrieval:
        enhanced_retriever = EnhancedRetriever(enable_domain_filter=True)
        retriever = None
    else:
        vs = get_vectorstore()
        retriever = vs.as_retriever(search_kwargs={"k": k})
        enhanced_retriever = None

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
    ):
        """Retrieve documents based on configuration."""
        if use_enhanced and enh_retriever:
            docs, domain, confidence = enh_retriever.retrieve_with_classification(
                question, k=k_val
            )
            return docs, domain, confidence
        elif std_retriever:
            docs = std_retriever.invoke("query: " + question)
            return docs, None, 0.0
        else:
            # Fallback
            vs = get_vectorstore()
            basic_retriever = vs.as_retriever(search_kwargs={"k": k_val})
            docs = basic_retriever.invoke("query: " + question)
            return docs, None, 0.0

    def _prepare_inputs(
        x: Dict[str, Any],
        k_val: int,
        use_enhanced: bool,
        enh_ret: EnhancedRetriever | None,
        std_ret: Any | None,
    ) -> Dict[str, Any]:
        question = x["question"]
        docs, domain, confidence = _retrieve_docs(
            question, k_val, use_enhanced, enh_ret, std_ret
        )

        if domain is not None:
            x["detected_domain"] = domain
            x["domain_confidence"] = confidence

        context = "\n\n".join(d.page_content for d in docs)
        x["context"] = context
        x["retrieved_docs"] = docs
        return x

    # Use partial to bind parameters and avoid closure variable issues
    _prepare_inputs_bound = partial(
        _prepare_inputs,
        k_val=k,
        use_enhanced=use_enhanced_retrieval,
        enh_ret=enhanced_retriever,
        std_ret=retriever,
    )

    chain = RunnableLambda(_prepare_inputs_bound) | prompt | llm | StrOutputParser()

    def run(question: str) -> Dict[str, Any]:
        start_time = time.time()

        # Prepare inputs (includes retrieval)
        inputs = {"question": question}
        prepared = _prepare_inputs_bound(inputs)
        docs = prepared.get("retrieved_docs", [])

        # Generate answer
        result_text = chain.invoke({"question": question})

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

        return response

    return run
