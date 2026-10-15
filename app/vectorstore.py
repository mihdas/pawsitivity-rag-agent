"""Embeddings + Qdrant vector store."""

from functools import lru_cache

from langchain_core.embeddings import Embeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

from app.config import get_settings


class FastEmbedEmbeddings(Embeddings):
    """Small ONNX embedding model that runs on CPU inside the container (no GPU, no API key)."""

    def __init__(self, model_name: str):
        from fastembed import TextEmbedding  # imported lazily: heavy import

        self._model = TextEmbedding(model_name=model_name)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return next(iter(self._model.embed([text]))).tolist()


@lru_cache
def get_embeddings() -> Embeddings:
    return FastEmbedEmbeddings(get_settings().embedding_model)


@lru_cache
def get_client() -> QdrantClient:
    s = get_settings()
    return QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key, timeout=10)


def get_vectorstore() -> QdrantVectorStore:
    s = get_settings()
    return QdrantVectorStore(client=get_client(), collection_name=s.collection, embedding=get_embeddings())
