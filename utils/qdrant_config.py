"""
Shared Qdrant client settings.

Measured: with Qdrant not running, every call through the default client takes
~4.08 seconds before failing — the client retries internally with a backoff.
That is fine for a background job and bad for anything a worker is waiting on:
the compliance path and the Ask-AI panel both touch Qdrant, so a stopped
container turns a sub-second response into a 4-second stall, against the <5s
end-to-end alert budget in system_prompt.md §13.1.

Nothing here changes behaviour when Qdrant IS running — it only bounds how long
failure takes, so the degradation paths (which already return correct, clearly
labelled "store unreachable" responses) get to run promptly.
"""

import os

TIMEOUT_S = float(os.getenv("QDRANT_TIMEOUT", "2.0"))


def url() -> str:
    return os.getenv("QDRANT_URL", "http://localhost:6333")


def client_kwargs() -> dict:
    """Spread as **client_kwargs() into QdrantClient(...)."""
    return {"url": url(), "timeout": TIMEOUT_S}
