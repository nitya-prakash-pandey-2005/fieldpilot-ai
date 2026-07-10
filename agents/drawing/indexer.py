import os
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams, PointStruct
from sentence_transformers import SentenceTransformer
import uuid

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION_NAME = "drawings_vectors"

class DocumentIndexer:
    def __init__(self):
        # We initialize the model lazily
        self.model = None
        self.qdrant_client = QdrantClient(url=QDRANT_URL)
        self._ensure_collection()

    def _get_model(self):
        if self.model is None:
            # BAAI/bge-small-en-v1.5 is lightweight and fast for local MVP (384 dimensions)
            self.model = SentenceTransformer('BAAI/bge-small-en-v1.5')
        return self.model

    def _ensure_collection(self):
        try:
            collections = self.qdrant_client.get_collections().collections
            if not any(c.name == COLLECTION_NAME for c in collections):
                self.qdrant_client.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config=VectorParams(size=384, distance=Distance.COSINE)
                )
        except Exception as e:
            print(f"Error ensuring Qdrant collection: {e}")

    def chunk_text(self, text: str, chunk_size: int = 500, overlap: int = 50):
        # Simple character-based chunking for MVP
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunks.append(text[start:end])
            start = end - overlap
        return chunks

    def index_document(self, document_id: str, text: str):
        if not text:
            return 0
            
        chunks = self.chunk_text(text)
        model = self._get_model()
        
        # Generate embeddings
        embeddings = model.encode(chunks)
        
        points = []
        for idx, (chunk, emb) in enumerate(zip(chunks, embeddings)):
            points.append(PointStruct(
                id=str(uuid.uuid4()),
                vector=emb.tolist(),
                payload={"document_id": document_id, "text": chunk, "chunk_index": idx}
            ))
            
        try:
            self.qdrant_client.upsert(
                collection_name=COLLECTION_NAME,
                points=points
            )
            return len(points)
        except Exception as e:
            print(f"Qdrant indexing error: {e}")
            return 0
