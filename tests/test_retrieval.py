from types import SimpleNamespace

import retrieval


def test_retrieve_context_keyword_no_direction_returns_empty():
    assert retrieval.retrieve_context_keyword(None, {}) == {"table_matches": [], "rag_snippet": ""}


def test_retrieve_context_keyword_matches_on_yes_answer(monkeypatch):
    fake_table = [
        {"state": "היפו", "category": "פעילות גופנית", "cause": "ריצה", "explanation": "..."},
        {"state": "היפו", "category": "אחר", "cause": "לא רלוונטי", "explanation": "..."},
    ]
    monkeypatch.setattr(retrieval, "load_table", lambda: fake_table)
    monkeypatch.setattr(retrieval, "RAG_FILES", {"low": []})

    result = retrieval.retrieve_context_keyword("low", {"exercised_last_4h": True})

    assert len(result["table_matches"]) == 1
    assert result["table_matches"][0]["cause"] == "ריצה"


def test_extract_rag_section_splits_on_headers():
    text = "## HYPERGLYCEMIA\nhigh stuff\n## HYPOGLYCEMIA\nlow stuff"
    assert retrieval.extract_rag_section(text, "high") == "high stuff"
    assert retrieval.extract_rag_section(text, "low") == "low stuff"


def test_retrieve_context_pinecone_no_direction_returns_empty():
    result = retrieval.retrieve_context_pinecone(None, {}, embed_client=None, pinecone_index=None)
    assert result == {"table_matches": [], "rag_snippet": ""}


def test_retrieve_context_pinecone_queries_both_namespaces(monkeypatch):
    monkeypatch.setattr(retrieval, "embed_text", lambda client, text: [0.1, 0.2])

    causes_response = SimpleNamespace(matches=[SimpleNamespace(metadata={"cause": "ריצה"})])
    reference_response = SimpleNamespace(matches=[SimpleNamespace(metadata={"text": "some medical text"})])

    class FakeIndex:
        def query(self, vector, top_k, namespace, filter, include_metadata):
            if namespace == "causes":
                assert filter == {"state": {"$eq": "היפו"}}
                return causes_response
            assert namespace == "reference"
            assert filter == {"direction": {"$eq": "low"}}
            return reference_response

    result = retrieval.retrieve_context_pinecone(
        "low", {"exercised_last_4h": True}, embed_client=None, pinecone_index=FakeIndex()
    )

    assert result == {"table_matches": [{"cause": "ריצה"}], "rag_snippet": "some medical text"}


def test_retrieve_context_pinecone_falls_back_on_error(monkeypatch):
    def raise_error(client, text):
        raise RuntimeError("embedding service down")

    monkeypatch.setattr(retrieval, "embed_text", raise_error)
    monkeypatch.setattr(
        retrieval, "retrieve_context_keyword",
        lambda direction, answers: {"table_matches": ["fallback"], "rag_snippet": ""},
    )

    result = retrieval.retrieve_context_pinecone("low", {}, embed_client=None, pinecone_index=object())

    assert result == {"table_matches": ["fallback"], "rag_snippet": ""}


def test_get_pinecone_index_safe_returns_none_when_unconfigured(monkeypatch):
    import config
    monkeypatch.setattr(config, "PINECONE_API_KEY", None)
    assert retrieval.get_pinecone_index_safe() is None
