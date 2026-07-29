import os
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams, PointStruct
from sentence_transformers import SentenceTransformer
import uuid

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
# Standardized to match agents/memory/retriever.py's collection-naming
# scheme (project_{project_id}_drawings) — previously this indexed into a
# single global "drawings_vectors" collection while the memory retriever
# searched "project_{project_id}", two paths that never saw each other's
# data even though both talk to the same Qdrant instance.
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384


def collection_name(project_id: str) -> str:
    return f"project_{project_id}_drawings"


class DocumentIndexer:
    def __init__(self):
        # We initialize the model lazily
        self.model = None
        self.qdrant_client = QdrantClient(url=QDRANT_URL)

    def _get_model(self):
        if self.model is None:
            # BAAI/bge-small-en-v1.5 — same embedding model used by
            # agents/memory/retriever.py, so a drawing indexed here is
            # actually retrievable through the Project Memory Q&A path.
            self.model = SentenceTransformer(EMBEDDING_MODEL)
        return self.model

    def _ensure_collection(self, name: str):
        try:
            collections = self.qdrant_client.get_collections().collections
            if not any(c.name == name for c in collections):
                self.qdrant_client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE)
                )
        except Exception as e:
            print(f"Error ensuring Qdrant collection '{name}': {e}")

    def chunk_text(self, text: str, chunk_size: int = 500, overlap: int = 50):
        # Simple character-based chunking for MVP
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunks.append(text[start:end])
            start = end - overlap
        return chunks

    def index_document(self, document_id: str, text: str, project_id: str = "default-project", source: str = None):
        if not text:
            return 0

        name = collection_name(project_id)
        self._ensure_collection(name)

        chunks = self.chunk_text(text)
        model = self._get_model()

        # Generate embeddings
        embeddings = model.encode(chunks)

        points = []
        for idx, (chunk, emb) in enumerate(zip(chunks, embeddings)):
            points.append(PointStruct(
                id=str(uuid.uuid4()),
                vector=emb.tolist(),
                payload={
                    "document_id": document_id,
                    "text": chunk,
                    "chunk_index": idx,
                    # "source" matches what agents/memory/retriever.py reads
                    # back out (r.payload.get("source", "")) for citations.
                    "source": source or document_id,
                    "project_id": project_id,
                }
            ))

        try:
            self.qdrant_client.upsert(
                collection_name=name,
                points=points
            )
            return len(points)
        except Exception as e:
            print(f"Qdrant indexing error: {e}")
            return 0
