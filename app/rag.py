from typing import Dict, Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_community.chat_models import ChatOpenAI
from langchain_community.llms import Ollama
from langchain_core.output_parsers import StrOutputParser

from .vectorstore import get_vectorstore
from .config import DEFAULT_TOP_K, OPENAI_API_KEY, OLLAMA_MODEL


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


def build_rag_chain(k: int = DEFAULT_TOP_K):
    vs = get_vectorstore()
    # E5 requires query prefix
    retriever = vs.as_retriever(search_kwargs={"k": k, "score_threshold": 0.0})

    llm = _get_llm()
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
        # Fallback: return concatenated context as an extractive baseline
        def run_fallback(question: str):
            docs = retriever.get_relevant_documents("query: " + question)
            context = "\n\n".join(d.page_content for d in docs)
            answer = (
                "بر اساس متون یافت‌شده، موارد مرتبط در زیر آمده است. لطفاً با دقت مطالعه کنید و در صورت نیاز سوال را دقیق‌تر مطرح نمایید.\n\n"
                + context
            )
            sources = [d.metadata.get("source", "") for d in docs]
            return {"answer": answer, "sources": sources}

        return run_fallback

    chain = (
        {"question": lambda x: x["question"], "docs": lambda x: x["question"]}
        | (
            lambda x: {
                "question": x["question"],
                "docs": get_vectorstore()
                .as_retriever(search_kwargs={"k": k})
                .get_relevant_documents("query: " + x["question"]),
            }
        )
        | (
            lambda x: {
                "question": x["question"],
                "context": "\n\n".join(d.page_content for d in x["docs"]),
                "sources": [d.metadata.get("source", "") for d in x["docs"]],
            }
        )
        | prompt
        | llm
        | StrOutputParser()
    )

    def run(question: str) -> Dict[str, Any]:
        result_text = chain.invoke({"question": question})
        # Retrieve sources again (quick)
        docs = (
            get_vectorstore()
            .as_retriever(search_kwargs={"k": k})
            .get_relevant_documents("query: " + question)
        )
        sources = [d.metadata.get("source", "") for d in docs]
        return {"answer": result_text, "sources": sources}

    return run
