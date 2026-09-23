"""RAG building blocks (LangChain): load -> chunk -> embed -> store (PGVector) -> retrieve.

Two collections in Postgres/pgvector:
- knowledge_base: chunks of data/knowledge_base/*.md (policies, FAQ) -> policy answers
- products: one document per product -> semantic product search ("keep my coffee hot")
"""

from pathlib import Path

from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding, Embeddings
from langchain_ollama import OllamaEmbeddings
from langchain_postgres import PGVector
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from shared.config import Settings

from .schemas import RetrievedChunk

KB_COLLECTION = "knowledge_base"
PRODUCT_COLLECTION = "products"
CHUNK_SIZE = 600  # characters
CHUNK_OVERLAP = 80
HEADERS = [("#", "title"), ("##", "section")]


# ---------- embeddings ----------
class NomicEmbeddings(OllamaEmbeddings):
    """nomic-embed-text is trained with task prefixes; without them retrieval is noticeably
    worse. Documents and queries get different prefixes (asymmetric search)."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return super().embed_documents([f"search_document: {t}" for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return super().embed_query(f"search_query: {text}")

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return await super().aembed_documents([f"search_document: {t}" for t in texts])

    async def aembed_query(self, text: str) -> list[float]:
        return await super().aembed_query(f"search_query: {text}")


def make_embeddings(s: Settings) -> Embeddings:
    if s.embedding_provider == "fake":
        # Hash-based, deterministic, NOT semantic: for tests that don't judge retrieval quality
        return DeterministicFakeEmbedding(size=768)
    cls = NomicEmbeddings if s.embedding_model.startswith("nomic") else OllamaEmbeddings
    return cls(model=s.embedding_model, base_url=s.ollama_api_base)


def make_store(s: Settings, embeddings: Embeddings, collection: str, *,
               async_mode: bool = True, pre_delete: bool = False) -> PGVector:
    return PGVector(
        embeddings=embeddings,
        connection=s.vector_db_url,
        collection_name=collection,
        collection_metadata={"embedding_model": s.embedding_model,
                             "chunk_size": CHUNK_SIZE, "chunk_overlap": CHUNK_OVERLAP},
        use_jsonb=True,
        async_mode=async_mode,
        pre_delete_collection=pre_delete,
    )


# ---------- loading & chunking ----------
def load_kb_documents(path: str | Path) -> list[Document]:
    return [Document(page_content=f.read_text(encoding="utf-8"), metadata={"source": f.name})
            for f in sorted(Path(path).glob("*.md"))]


def split_documents(docs: list[Document], chunk_size: int = CHUNK_SIZE,
                    chunk_overlap: int = CHUNK_OVERLAP) -> list[Document]:
    """Split by markdown headers first (keeps sections together), then by size with overlap.

    Each chunk gets a stable id `<file>#<n>` so re-ingestion upserts instead of duplicating.
    """
    by_header = MarkdownHeaderTextSplitter(HEADERS, strip_headers=False)
    by_size = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    chunks: list[Document] = []
    for doc in docs:
        sections = by_header.split_text(doc.page_content)
        # Skip the preamble before the first "##" section (title + "last updated" line only)
        pieces = [c for c in by_size.split_documents(sections) if "section" in c.metadata]
        for i, chunk in enumerate(pieces):
            source = doc.metadata["source"]
            title = chunk.metadata.get("title", "")
            if title and not chunk.page_content.startswith("# "):
                # Contextual chunk header: every chunk says which document it came from
                chunk.page_content = f"# {title}\n{chunk.page_content}"
            chunk.metadata.update(
                source=source,
                section=chunk.metadata["section"],
                chunk_index=i,
                chunk_id=f"{source}#{i}",
            )
            chunks.append(chunk)
    return chunks


def product_document(p: dict) -> Document:
    text = (f"{p['name']}. Category: {p['category'].replace('_', ' ')}. Brand: {p['brand']}. "
            f"Price: ${float(p['price']):.2f}. {p['description']}")
    return Document(page_content=text, metadata={
        "source": "catalog", "section": p["category"], "chunk_id": f"product-{p['id']}",
        "product_id": p["id"], "category": p["category"], "price": float(p["price"]),
    })


# ---------- retrieval ----------
class Retriever:
    """Similarity search with relevance scores (cosine, 0..1) and two cut-offs:
    an absolute minimum score, and a margin relative to the best hit.

    Returns every candidate with its score; `used` marks the ones that pass. Keeping the
    rejected ones in debug output is what makes retrieval testable (precision/recall,
    threshold tuning).
    """

    def __init__(self, store: PGVector, collection: str, min_score: float,
                 margin: float = 1.0):
        self.store = store
        self.collection = collection
        self.min_score = min_score
        self.margin = margin

    async def search(self, query: str, k: int, filter: dict | None = None,
                     min_score: float | None = None) -> list[RetrievedChunk]:
        threshold = self.min_score if min_score is None else min_score
        hits = await self.store.asimilarity_search_with_relevance_scores(query, k=k,
                                                                         filter=filter)
        if hits:
            threshold = max(threshold, hits[0][1] - self.margin)
        return [
            RetrievedChunk(
                chunk_id=doc.metadata.get("chunk_id", ""),
                collection=self.collection,
                source=doc.metadata.get("source", ""),
                section=str(doc.metadata.get("section", "")),
                score=round(score, 4),
                used=score >= threshold,
                content=doc.page_content,
            )
            for doc, score in hits
        ]
