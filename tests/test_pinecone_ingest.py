from unittest.mock import MagicMock

import pinecone_ingest


def test_ingest_causes_upserts_all_rows(monkeypatch):
    monkeypatch.setattr(pinecone_ingest, "embed_text", lambda client, text: [0.1, 0.2, 0.3])
    monkeypatch.setattr(
        pinecone_ingest, "load_table",
        lambda: [
            {"state": "היפר", "category": "cat1", "cause": "cause1", "explanation": "exp1", "time_to_effect": "5m"},
            {"state": "היפו", "category": "cat2", "cause": "cause2", "explanation": "exp2", "time_to_effect": "10m"},
        ],
    )
    fake_index = MagicMock()

    count = pinecone_ingest.ingest_causes(fake_index, embed_client=object())

    assert count == 2
    fake_index.upsert.assert_called_once()
    kwargs = fake_index.upsert.call_args.kwargs
    assert kwargs["namespace"] == "causes"
    assert len(kwargs["vectors"]) == 2
    assert kwargs["vectors"][0]["metadata"]["state"] == "היפר"
    assert kwargs["vectors"][0]["values"] == [0.1, 0.2, 0.3]


def test_ingest_reference_upserts_chunks_with_direction_metadata(monkeypatch, tmp_path):
    ada_dir = tmp_path / "rag"
    ada_dir.mkdir()
    ada_file = ada_dir / "ada_diabetes_association.txt"
    ada_file.write_text("## HYPERGLYCEMIA\nhigh info\n## HYPOGLYCEMIA\nlow info", encoding="utf-8")
    niddk_file = ada_dir / "niddk_hypoglycemia.txt"
    niddk_file.write_text("niddk low info", encoding="utf-8")

    monkeypatch.setattr(pinecone_ingest, "DATA_DIR", tmp_path)
    monkeypatch.setattr(pinecone_ingest, "embed_text", lambda client, text: [0.1, 0.2, 0.3])
    fake_index = MagicMock()

    count = pinecone_ingest.ingest_reference(fake_index, embed_client=object())

    assert count == 3  # high chunk, low chunk from ADA, low chunk from NIDDK
    kwargs = fake_index.upsert.call_args.kwargs
    assert kwargs["namespace"] == "reference"
    directions = {v["metadata"]["direction"] for v in kwargs["vectors"]}
    assert directions == {"high", "low"}
