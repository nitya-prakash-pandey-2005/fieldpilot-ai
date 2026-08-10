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

EMBEDDED FALLBACK. Follow.md §4 asks for "Qdrant (Docker or in-memory
qdrant-client local mode — use local mode to avoid a Docker dependency during
the demo)". Every call site used to hardcode a server URL, so with the container
down the entire RAG path returned nothing and Agent 6 drafted RFIs with no
citations. That is the honest degradation, but it is a degradation nobody needs
to accept: qdrant-client can run the same engine embedded, against a local
directory, with no container at all.

So `get_client()` probes the configured server first and falls back to embedded
storage under `data/qdrant_local`. Retrieval quality is identical; it is the
same index, just in-process.

ONE PROCESS AT A TIME. Embedded mode takes an exclusive lock on its directory —
that is a property of the storage engine, not a choice made here. The API server
normally holds it, which is why `scripts/ingest_spec.py` ingests over HTTP
rather than writing directly. A script that opens the store while the API is
running gets a clear error saying so rather than a confusing lock trace.
"""

import os
import socket
import threading
from pathlib import Path
from urllib.parse import urlparse

TIMEOUT_S = float(os.getenv("QDRANT_TIMEOUT", "2.0"))

REPO_ROOT = Path(__file__).resolve().parents[1]
LOCAL_PATH = Path(os.getenv("QDRANT_LOCAL_PATH") or (REPO_ROOT / "data" / "qdrant_local"))

_lock = threading.Lock()
_client = None
_mode = "uninitialised"
_error: str | None = None


def url() -> str:
    return os.getenv("QDRANT_URL", "http://localhost:6333")


def client_kwargs() -> dict:
    """Spread as **client_kwargs() into QdrantClient(...)."""
    return {"url": url(), "timeout": TIMEOUT_S}


def _server_reachable(timeout: float = 1.0) -> bool:
    """TCP-probe before handing the URL to QdrantClient.

    The client's own failure path retries with a backoff and takes ~4s. A probe
    costs a connection refusal, which is immediate.
    """
    try:
        parsed = urlparse(url())
        host, port = parsed.hostname, parsed.port or 6333
        if not host:
            return False
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def get_client():
    """Process-wide Qdrant client: server if reachable, embedded otherwise.

    Must be the single construction point. Two embedded clients in one process
    would contend for the same directory lock, and the second one to open it
    fails — which is exactly what happened when each agent built its own.
    """
    global _client, _mode, _error
    if _client is not None:
        return _client

    with _lock:
        if _client is not None:
            return _client

        from qdrant_client import QdrantClient

        if os.getenv("QDRANT_FORCE_LOCAL", "").lower() not in ("1", "true", "yes") \
                and _server_reachable():
            _client = QdrantClient(**client_kwargs())
            _mode = "server"
            return _client

        LOCAL_PATH.mkdir(parents=True, exist_ok=True)
        try:
            _client = QdrantClient(path=str(LOCAL_PATH))
            _mode = "embedded"
            print(f"[Qdrant] server unreachable at {url()} — using embedded storage "
                  f"at {LOCAL_PATH}. Retrieval is fully functional; only one process "
                  f"may hold this store at a time.")
        except Exception as e:
            _error = f"{type(e).__name__}: {e}"
            _mode = "unavailable"
            if "already accessed" in str(e).lower() or "lock" in str(e).lower():
                print(f"[Qdrant] embedded store at {LOCAL_PATH} is locked by another "
                      f"process. The API server normally holds it — stop it, or ingest "
                      f"over HTTP instead of writing directly.")
            else:
                print(f"[Qdrant] embedded storage unavailable: {_error}")
            raise

        # Close before interpreter teardown. qdrant-client's __del__ imports on
        # its way out, which fails once sys.meta_path is gone and prints an
        # ImportError traceback after every clean exit -- noise that reads like
        # a crash in logs and in CI output.
        import atexit
        atexit.register(_close)

        return _client


def _close() -> None:
    global _client
    try:
        if _client is not None:
            _client.close()
    except Exception:
        pass
    finally:
        _client = None


def status() -> dict:
    """Which backend is actually serving retrieval, for the health endpoints."""
    return {
        "mode": _mode,
        "url": url() if _mode == "server" else None,
        "local_path": str(LOCAL_PATH) if _mode == "embedded" else None,
        "error": _error,
    }
