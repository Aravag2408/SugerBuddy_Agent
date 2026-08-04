class PipelineError(Exception):
    """Raised for any unrecoverable failure in the agent reasoning pipeline.

    The (future) FastAPI layer catches this and maps it to
    {"status": "error", "error": str(e), "response": null, "steps": []}.
    """
