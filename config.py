from __future__ import annotations
import os

from dotenv import load_dotenv

load_dotenv()

LLMOD_API_KEY = os.environ.get("LLMOD_API_KEY")
LLMOD_BASE_URL = os.environ.get("LLMOD_BASE_URL")
PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.environ.get("PINECONE_INDEX_NAME", "sugarbuddy-causes")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

TEXT_MODEL = "MB5R2CF-azure/gpt-5.4-mini"
EMBED_MODEL = "MB5R2CF-azure/text-embedding-3-small"


def require(value: str | None, var_name: str) -> str:
    if not value:
        raise RuntimeError(
            f"{var_name} is not set. Copy .env.example to .env and fill it in."
        )
    return value
