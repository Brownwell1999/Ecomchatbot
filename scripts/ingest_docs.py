"""Build the vector store: chunk + embed the knowledge base and the product catalog.

Usage:  python -m scripts.ingest_docs      (re-creates both collections; run after seed_db)
"""

import asyncio
import statistics
import time

from sqlalchemy import select

from services.chat_service.app.rag import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    KB_COLLECTION,
    PRODUCT_COLLECTION,
    load_kb_documents,
    make_embeddings,
    make_store,
    product_document,
    split_documents,
)
from shared.config import get_settings
from shared.db.models import Product
from shared.db.session import make_engine, make_sessionmaker


async def load_products() -> list[dict]:
    engine = make_engine()
    async with make_sessionmaker(engine)() as session:
        rows = (await session.scalars(select(Product).order_by(Product.id))).all()
    await engine.dispose()
    return [{"id": p.id, "name": p.name, "brand": p.brand, "category": p.category,
             "price": p.price, "description": p.description} for p in rows]


async def main() -> None:
    s = get_settings()
    embeddings = make_embeddings(s)

    docs = load_kb_documents(s.kb_path)
    chunks = split_documents(docs)
    sizes = [len(c.page_content) for c in chunks]
    print(f"knowledge base: {len(docs)} files -> {len(chunks)} chunks "
          f"(size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP}, "
          f"chars min/median/max={min(sizes)}/{int(statistics.median(sizes))}/{max(sizes)})")

    products = [product_document(p) for p in await load_products()]

    for name, items in ((KB_COLLECTION, chunks), (PRODUCT_COLLECTION, products)):
        start = time.perf_counter()
        store = make_store(s, embeddings, name, async_mode=False, pre_delete=True)
        store.add_documents(items, ids=[d.metadata["chunk_id"] for d in items])
        print(f"{name:<15} {len(items):>4} vectors embedded with {s.embedding_model} "
              f"in {time.perf_counter() - start:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
