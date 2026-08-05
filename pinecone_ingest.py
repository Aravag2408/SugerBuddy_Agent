"""One-time script: create the Pinecone index if it does not exist yet, then
embed investigation_table.json + RAG text chunks into it. Run manually after
LLMod.ai and Pinecone credentials are set in .env:

    python pinecone_ingest.py

Re-run only when data/investigation_table.json or data/rag/*.txt change;
this is not part of the request-time path.
"""
from __future__ import annotations

from pinecone import Pinecone, ServerlessSpec

import config
from llm_client import embed_text, get_llm_client
from retrieval import DATA_DIR, extract_rag_section, get_pinecone_index, load_table

# text-embedding-3-small emits 1536-dimensional vectors.
EMBED_DIMENSION = 1536
PINECONE_METRIC = "cosine"
PINECONE_CLOUD = "aws"
PINECONE_REGION = "us-east-1"

# Pinecone caps a single upsert request at ~2MB; 50 vectors of 1536 floats
# stays comfortably under it.
UPSERT_BATCH_SIZE = 50


def ensure_index_exists() -> None:
    """Create the configured Pinecone index if it does not exist yet.

    `retrieval.get_pinecone_index()` only opens an already-existing index, so
    creation lives here with the rest of the one-time setup concerns.
    """
    pc = Pinecone(api_key=config.require(config.PINECONE_API_KEY, "PINECONE_API_KEY"))
    if config.PINECONE_INDEX_NAME in pc.list_indexes().names():
        return
    pc.create_index(
        name=config.PINECONE_INDEX_NAME,
        dimension=EMBED_DIMENSION,
        metric=PINECONE_METRIC,
        spec=ServerlessSpec(cloud=PINECONE_CLOUD, region=PINECONE_REGION),
    )


def _upsert_in_batches(index, vectors: list[dict], namespace: str) -> None:
    for start in range(0, len(vectors), UPSERT_BATCH_SIZE):
        index.upsert(vectors=vectors[start:start + UPSERT_BATCH_SIZE], namespace=namespace)


def ingest_causes(index, embed_client) -> int:
    rows = load_table()
    vectors = []
    for i, row in enumerate(rows):
        text = f"{row['category']} {row['cause']} {row['explanation']}"
        vector = embed_text(embed_client, text)
        vectors.append({
            "id": f"cause-{i}",
            "values": vector,
            "metadata": {
                "state": row["state"],
                "category": row["category"],
                "cause": row["cause"],
                "explanation": row["explanation"],
                "time_to_effect": row.get("time_to_effect", ""),
            },
        })
    _upsert_in_batches(index, vectors, "causes")
    return len(vectors)


def ingest_reference(index, embed_client) -> int:
    ada_text = (DATA_DIR / "rag" / "ada_diabetes_association.txt").read_text(encoding="utf-8")
    niddk_text = (DATA_DIR / "rag" / "niddk_hypoglycemia.txt").read_text(encoding="utf-8")

    chunks = [
        ("high", extract_rag_section(ada_text, "high"), "ada_diabetes_association.txt"),
        ("low", extract_rag_section(ada_text, "low"), "ada_diabetes_association.txt"),
        ("low", niddk_text.strip(), "niddk_hypoglycemia.txt"),
    ]

    vectors = []
    for i, (direction, text, source_file) in enumerate(chunks):
        if not text:
            continue
        vector = embed_text(embed_client, text)
        vectors.append({
            "id": f"reference-{i}",
            "values": vector,
            "metadata": {"direction": direction, "source_file": source_file, "text": text},
        })
    _upsert_in_batches(index, vectors, "reference")
    return len(vectors)


def main() -> None:
    embed_client = get_llm_client()
    ensure_index_exists()
    index = get_pinecone_index()
    causes_count = ingest_causes(index, embed_client)
    reference_count = ingest_reference(index, embed_client)
    print(f"Ingested {causes_count} cause rows and {reference_count} reference chunks.")


if __name__ == "__main__":
    main()
