"""Interactive end-to-end smoke test for the SugarBuddy agent pipeline.

Run manually once LLMOD_API_KEY / LLMOD_BASE_URL are set in .env (and,
optionally, PINECONE_API_KEY for Pinecone-backed retrieval instead of the
keyword fallback):

    python local_prototype.py

Drives the full multi-turn flow via input(): describe a CGM event, answer
the 10 questions, optionally answer one follow-up question, and read the
final parent summary. This is a manual verification tool, not part of the
automated test suite (see tests/) — it makes real network calls.
"""
from __future__ import annotations
import json

from agent_pipeline import PipelineClients, run_pipeline
from llm_client import get_llm_client
from retrieval import get_pinecone_index_safe


def main() -> None:
    llm_client = get_llm_client()
    pinecone_index = get_pinecone_index_safe()
    if pinecone_index is None:
        print("[info] Pinecone not configured — falling back to keyword-matching retrieval.\n")

    clients = PipelineClients(llm_client=llm_client, pinecone_index=pinecone_index, embed_client=llm_client)

    print("Describe the CGM event (e.g. 'glucose spiked to 260 mg/dL and is rising fast'):")
    transcript = input("> ").strip()

    while True:
        result = run_pipeline(transcript, clients)

        print("\n=== Agent response ===")
        print(result["response"])
        print("\n=== Steps ===")
        print(json.dumps(result["steps"], ensure_ascii=False, indent=2))

        if "SUGARBUDDY_CONTEXT" not in result["response"]:
            print("\n=== Done: final parent summary reached ===")
            break

        print("\nYour reply (questionnaire answers or the follow-up answer):")
        reply = input("> ").strip()
        transcript = f"{transcript}\n{result['response']}\n{reply}"


if __name__ == "__main__":
    main()
