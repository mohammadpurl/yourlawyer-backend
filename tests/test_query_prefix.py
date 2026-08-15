"""Regression tests: E5 query/passage prefixes on retrieval paths."""

from __future__ import annotations

from langchain_core.documents import Document

from app.services.vectorstore import prefix_passage, prefix_query, strip_e5_prefix


def test_prefix_query_idempotent():
    assert prefix_query("طلاق چیست") == "query: طلاق چیست"
    assert prefix_query("query: طلاق چیست") == "query: طلاق چیست"
    assert prefix_query("QUERY: طلاق") == "query: طلاق"
    once = prefix_query("hello")
    assert prefix_query(once) == once
    assert not once.lower().startswith("query: query:")


def test_prefix_passage_idempotent():
    assert prefix_passage("ماده ۱") == "passage: ماده ۱"
    twice = prefix_passage(prefix_passage("ماده ۱"))
    assert twice == "passage: ماده ۱"
    assert strip_e5_prefix(twice) == "ماده ۱"


def test_enhanced_retrieval_passes_query_prefix_to_embed(monkeypatch):
    """If someone removes prefix_query from EnhancedRetriever, this must fail."""
    seen: list[str] = []

    class FakeEmbeddings:
        def embed_query(self, text: str):
            seen.append(text)
            return [0.0] * 8

        def embed_documents(self, texts):
            return [[0.0] * 8 for _ in texts]

    class FakeVS:
        def as_retriever(self, search_kwargs=None):
            emb = FakeEmbeddings()

            class R:
                def invoke(self, q):
                    emb.embed_query(q)  # what Chroma/LangChain effectively does
                    return [
                        Document(
                            page_content="passage: ماده آزمایشی قانون کار",
                            metadata={"law_name": "قانون کار", "domain": "کار_و_تامین_اجتماعی"},
                        )
                    ]

            return R()

        def similarity_search(self, query, k=5, filter=None):
            FakeEmbeddings().embed_query(query)
            seen.append(query)
            return []

    import app.services.enhanced_retrieval as er

    monkeypatch.setattr(er, "get_vectorstore", lambda collection_name=None: FakeVS())
    monkeypatch.setattr(er, "ENABLE_DOMAIN_FILTERED_RETRIEVAL", False)

    retriever = er.EnhancedRetriever()
    docs = retriever.retrieve("دوره آزمایشی حادثه کار", k=3)
    assert docs
    assert seen, "embed_query was never called"
    assert all(s.lower().startswith("query:") for s in seen)
    assert all(not s.lower().startswith("query: query:") for s in seen)


def test_rag_std_path_uses_prefix_query(monkeypatch):
    """Cover app.services.rag fallback retriever.invoke path."""
    seen: list[str] = []

    class FakeRetriever:
        def invoke(self, q):
            seen.append(q)
            return [
                Document(
                    page_content="passage: تست",
                    metadata={"source": "x", "law_name": "قانون کار"},
                )
            ]

    class FakeVS:
        def as_retriever(self, search_kwargs=None):
            return FakeRetriever()

    import app.services.rag as rag_mod

    monkeypatch.setattr(rag_mod, "get_vectorstore", lambda: FakeVS())
    monkeypatch.setattr(rag_mod, "OPENAI_API_KEY", None)
    monkeypatch.setattr(rag_mod, "OLLAMA_MODEL", None)
    monkeypatch.setattr(rag_mod, "RAG_REQUIRE_RETRIEVED_CONTEXT", False)

    # Avoid loading heavy enhanced path
    run = rag_mod.build_rag_chain(
        k=2,
        use_enhanced_retrieval=False,
        use_reranking=False,
        user=None,
        db=None,
    )
    out = run("سوال تستی دوره آزمایشی")
    assert seen
    assert all(s.startswith("query:") for s in seen)
    assert "answer" in out


def test_legacy_app_rag_uses_prefix(monkeypatch):
    seen: list[str] = []

    class FakeRetriever:
        def invoke(self, q):
            seen.append(q)
            return [Document(page_content="passage: x", metadata={"source": "s"})]

    class FakeVS:
        def as_retriever(self, search_kwargs=None):
            return FakeRetriever()

    import app.rag as legacy_rag

    monkeypatch.setattr(legacy_rag, "get_vectorstore", lambda: FakeVS())
    monkeypatch.setattr(legacy_rag, "OPENAI_API_KEY", None)
    monkeypatch.setattr(legacy_rag, "OLLAMA_MODEL", None)

    run = legacy_rag.build_rag_chain(k=2)
    run("hello")
    assert seen
    assert all(prefix_query(s) == s for s in seen)
