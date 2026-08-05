from unittest.mock import MagicMock

import config
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


def test_ingest_reference_skips_empty_chunks(monkeypatch, tmp_path):
    """Test that chunks with empty extracted text are skipped."""
    ada_dir = tmp_path / "rag"
    ada_dir.mkdir()
    # ADA file with only HYPERGLYCEMIA, missing HYPOGLYCEMIA section
    ada_file = ada_dir / "ada_diabetes_association.txt"
    ada_file.write_text("## HYPERGLYCEMIA\nhigh info only", encoding="utf-8")
    niddk_file = ada_dir / "niddk_hypoglycemia.txt"
    niddk_file.write_text("niddk low info", encoding="utf-8")

    monkeypatch.setattr(pinecone_ingest, "DATA_DIR", tmp_path)
    monkeypatch.setattr(pinecone_ingest, "embed_text", lambda client, text: [0.1, 0.2, 0.3])
    fake_index = MagicMock()

    count = pinecone_ingest.ingest_reference(fake_index, embed_client=object())

    # Should only have 2 chunks: high from ADA (HYPOGLYCEMIA section is missing),
    # low from NIDDK (ADA's low section is empty and skipped)
    assert count == 2
    kwargs = fake_index.upsert.call_args.kwargs
    assert len(kwargs["vectors"]) == 2
    assert kwargs["namespace"] == "reference"
    directions = {v["metadata"]["direction"] for v in kwargs["vectors"]}
    assert directions == {"high", "low"}


def test_ingest_causes_batches_upserts_over_the_batch_size(monkeypatch):
    """A single upsert of every vector would approach Pinecone's ~2MB request
    ceiling, so vectors must go out in batches."""
    monkeypatch.setattr(pinecone_ingest, "embed_text", lambda client, text: [0.1, 0.2, 0.3])
    monkeypatch.setattr(
        pinecone_ingest, "load_table",
        lambda: [
            {"state": "היפר", "category": f"cat{i}", "cause": f"cause{i}",
             "explanation": f"exp{i}", "time_to_effect": "5m"}
            for i in range(120)
        ],
    )
    fake_index = MagicMock()

    count = pinecone_ingest.ingest_causes(fake_index, embed_client=object())

    assert count == 120
    batch_sizes = [len(c.kwargs["vectors"]) for c in fake_index.upsert.call_args_list]
    assert batch_sizes == [50, 50, 20]
    assert all(c.kwargs["namespace"] == "causes" for c in fake_index.upsert.call_args_list)
    # Every vector must still be sent exactly once, in order.
    sent_ids = [v["id"] for c in fake_index.upsert.call_args_list for v in c.kwargs["vectors"]]
    assert sent_ids == [f"cause-{i}" for i in range(120)]


def _fake_pinecone_factory(existing_names, created):
    def factory(api_key):
        pc = MagicMock()
        pc.list_indexes.return_value.names.return_value = existing_names
        pc.create_index.side_effect = lambda **kwargs: created.append(kwargs)
        return pc
    return factory


def test_ensure_index_exists_creates_index_when_absent(monkeypatch):
    monkeypatch.setattr(config, "PINECONE_API_KEY", "test-key")
    monkeypatch.setattr(config, "PINECONE_INDEX_NAME", "sugarbuddy-causes")
    created: list[dict] = []
    monkeypatch.setattr(
        pinecone_ingest, "Pinecone", _fake_pinecone_factory(["some-other-index"], created)
    )

    pinecone_ingest.ensure_index_exists()

    assert len(created) == 1
    assert created[0]["name"] == "sugarbuddy-causes"
    assert created[0]["dimension"] == 1536  # text-embedding-3-small
    assert created[0]["metric"] == "cosine"
    assert created[0]["spec"].cloud == "aws"
    assert created[0]["spec"].region == "us-east-1"


def test_ensure_index_exists_is_a_no_op_when_index_already_present(monkeypatch):
    monkeypatch.setattr(config, "PINECONE_API_KEY", "test-key")
    monkeypatch.setattr(config, "PINECONE_INDEX_NAME", "sugarbuddy-causes")
    created: list[dict] = []
    monkeypatch.setattr(
        pinecone_ingest, "Pinecone",
        _fake_pinecone_factory(["sugarbuddy-causes", "other"], created),
    )

    pinecone_ingest.ensure_index_exists()

    assert created == []
