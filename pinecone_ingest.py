"""One-time script: embed investigation_table.json + RAG text chunks into
Pinecone. Run manually after LLMod.ai and Pinecone credentials are set in
.env:

    python pinecone_ingest.py

Re-run only when data/investigation_table.json or data/rag/*.txt change;
this is not part of the request-time path.
"""
from __future__ import annotations

from llm_client import embed_text, get_llm_client
from retrieval import DATA_DIR, extract_rag_section, get_pinecone_index, load_table


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
    index.upsert(vectors=vectors, namespace="causes")
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
    index.upsert(vectors=vectors, namespace="reference")
    return len(vectors)


def main() -> None:
    embed_client = get_llm_client()
    index = get_pinecone_index()
    causes_count = ingest_causes(index, embed_client)
    reference_count = ingest_reference(index, embed_client)
    print(f"Ingested {causes_count} cause rows and {reference_count} reference chunks.")


if __name__ == "__main__":
    main()
