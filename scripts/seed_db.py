"""Create the schema and load deterministic e-commerce seed data.

Deterministic on purpose: fixed random seeds + a fixed anchor date mean order #1042 always
has the same status/items, so automated tests can assert on it.

Usage:  python -m scripts.seed_db            (drops & recreates all tables)
"""

import asyncio
import os
import random
from datetime import datetime, timedelta
from decimal import Decimal

from faker import Faker
from sqlalchemy import func, select

from shared.db.models import Base, Order, OrderItem, Product, ReturnRequest, User
from shared.db.session import make_engine, make_sessionmaker
from shared.security import hash_password

SEED = 42
ANCHOR = datetime.fromisoformat(os.getenv("SEED_ANCHOR_DATE", "2026-09-01T12:00:00"))
N_USERS = 50
N_ORDERS = 300
FIRST_ORDER_ID = 1001
DEMO_PASSWORD = "demo123"  # every seeded user; demo only

# category -> (brands, product types, adjectives, price range)
CATALOG = {
    "electronics": (
        ["Sonix", "Voltra", "Pixelon", "Auralis", "Nexa"],
        ["Wireless Earbuds", "Bluetooth Speaker", "Smartwatch", "4K Monitor", "Mechanical Keyboard",
         "Noise-Cancelling Headphones", "Portable Charger", "Webcam"],
        ["Pro", "Lite", "Max", "Air", "X"],
        (19, 499),
    ),
    "fashion": (
        ["Urban Thread", "Nordwear", "Linea", "Kasa", "Bluefield"],
        ["Cotton T-Shirt", "Denim Jacket", "Slim Fit Jeans", "Wool Sweater", "Linen Shirt",
         "Hooded Sweatshirt", "Chino Pants", "Rain Jacket"],
        ["Classic", "Essential", "Relaxed", "Premium", "Everyday"],
        (12, 149),
    ),
    "footwear": (
        ["Stride", "Peakrun", "Solea", "Trailborn", "Kicko"],
        ["Running Shoes", "Trail Running Shoes", "Leather Sneakers", "Hiking Boots",
         "Slip-On Loafers", "Training Shoes", "Sandals", "Walking Shoes"],
        ["Cloud", "Swift", "Terra", "Aero", "Flex"],
        (25, 229),
    ),
    "home_kitchen": (
        ["Casa Nova", "Brewmaster", "Kitchara", "Homely", "Ironleaf"],
        ["Coffee Maker", "Air Fryer", "Non-Stick Pan Set", "Blender", "Electric Kettle",
         "Knife Set", "Storage Containers", "Stand Mixer"],
        ["Deluxe", "Compact", "Smart", "Classic", "Pro"],
        (15, 349),
    ),
    "beauty": (
        ["Glowé", "Purelle", "Botaniq", "Lumis", "Velvra"],
        ["Face Moisturizer", "Vitamin C Serum", "Sunscreen SPF 50", "Hair Dryer", "Shampoo",
         "Lip Balm Set", "Beard Trimmer", "Perfume"],
        ["Hydrating", "Gentle", "Radiant", "Daily", "Intense"],
        (6, 129),
    ),
    "sports": (
        ["Ironcore", "Flexa", "Summit", "Aquafin", "Pacer"],
        ["Yoga Mat", "Adjustable Dumbbells", "Resistance Bands", "Cycling Helmet", "Water Bottle",
         "Fitness Tracker", "Camping Tent", "Tennis Racket"],
        ["Pro", "Active", "Endurance", "Lite", "Elite"],
        (9, 399),
    ),
}

# Realistic feature phrases so descriptions are meaningful for semantic search / RAG
FEATURES = {
    "electronics": [
        "Bluetooth 5.3 with stable multipoint pairing", "up to 30 hours of battery life",
        "USB-C fast charging", "active noise cancellation for commutes and flights",
        "IPX5 sweat and water resistance", "crisp sound with deep bass",
        "built-in microphone for calls and video meetings", "compact, travel-friendly design",
    ],
    "fashion": [
        "breathable 100% cotton fabric", "relaxed everyday fit", "machine washable",
        "water-repellent outer shell for rainy days", "soft brushed interior for warmth",
        "sustainably sourced materials", "reinforced stitching for durability",
    ],
    "footwear": [
        "responsive cushioned midsole for road running", "lightweight breathable mesh upper",
        "grippy rubber outsole for trails and wet surfaces", "waterproof leather upper",
        "wide toe box for all-day comfort", "arch support for long walks",
        "slip-resistant sole",
    ],
    "home_kitchen": [
        "keeps drinks hot for hours", "dishwasher-safe parts", "stainless steel body",
        "one-touch programmable presets", "cooks with up to 80% less oil",
        "compact footprint for small kitchens", "BPA-free materials",
    ],
    "beauty": [
        "fragrance-free formula for sensitive skin", "dermatologist tested",
        "broad-spectrum UV protection", "cruelty-free and vegan",
        "lightweight, non-greasy texture", "cordless with 90 minutes of runtime",
        "hydrates skin all day",
    ],
    "sports": [
        "non-slip surface for yoga and pilates", "adjustable resistance levels",
        "lightweight and easy to carry", "tracks heart rate, steps and sleep",
        "insulated to keep water cold for 24 hours", "weatherproof for outdoor camping",
        "certified impact protection",
    ],
}

STATUS_WEIGHTS = {
    "placed": 10,
    "shipped": 15,
    "out_for_delivery": 5,
    "delivered": 55,
    "cancelled": 8,
    "returned": 7,
}
CARRIERS = ["UPS", "FedEx", "DHL", "USPS"]


def build_products(rng: random.Random) -> list[Product]:
    products: list[Product] = []
    pid = 1
    for category, (brands, types, adjectives, (lo, hi)) in CATALOG.items():
        for ptype in types:
            # 4 uniquely named variants of each product type -> 192 products
            variants = rng.sample([(b, a) for b in brands for a in adjectives], k=4)
            for brand, adj in variants:
                name = f"{brand} {adj} {ptype}"
                price = Decimal(str(round(rng.uniform(lo, hi), 2)))
                products.append(
                    Product(
                        id=pid,
                        sku=f"{category[:3].upper()}-{pid:04d}",
                        name=name,
                        brand=brand,
                        category=category,
                        description=(
                            f"{name} by {brand}. Features: "
                            + ", ".join(rng.sample(FEATURES[category], k=3)) + "."
                        ),
                        price=price,
                        stock=rng.choice([0, 0, 3, 8, 15, 25, 40, 60, 120]),
                        rating=Decimal(str(round(rng.uniform(3.0, 5.0), 1))),
                    )
                )
                pid += 1
    return products


def build_users(fake: Faker) -> list[User]:
    users = []
    # ponytail: one hash reused by all demo users (same password); real users get their own salt
    password_hash = hash_password(DEMO_PASSWORD)
    for uid in range(1, N_USERS + 1):
        first, last = fake.first_name(), fake.last_name()
        users.append(
            User(
                id=uid,
                email=f"{first}.{last}{uid}@example.com".lower(),
                full_name=f"{first} {last}",
                city=fake.city(),
                country=fake.country(),
                password_hash=password_hash,
            )
        )
    return users


def build_orders(
    rng: random.Random, products: list[Product]
) -> tuple[list[Order], list[OrderItem]]:
    orders, items = [], []
    statuses, weights = zip(*STATUS_WEIGHTS.items(), strict=True)
    item_id = 1
    for oid in range(FIRST_ORDER_ID, FIRST_ORDER_ID + N_ORDERS):
        status = rng.choices(statuses, weights=weights)[0]
        age_days = {
            "placed": rng.randint(0, 2),
            "shipped": rng.randint(2, 6),
            "out_for_delivery": rng.randint(3, 7),
        }.get(status, rng.randint(7, 120))
        placed_at = ANCHOR - timedelta(days=age_days, hours=rng.randint(0, 23))
        delivered_at = (
            placed_at + timedelta(days=rng.randint(3, 7))
            if status in {"delivered", "returned"}
            else None
        )
        shipped = status not in {"placed", "cancelled"}

        total = Decimal("0")
        for product in rng.sample(products, k=rng.randint(1, 4)):
            qty = rng.randint(1, 3)
            items.append(
                OrderItem(
                    id=item_id, order_id=oid, product_id=product.id,
                    quantity=qty, unit_price=product.price,
                )
            )
            total += product.price * qty
            item_id += 1

        orders.append(
            Order(
                id=oid,
                user_id=rng.randint(1, N_USERS),
                status=status,
                total=total,
                carrier=rng.choice(CARRIERS) if shipped else None,
                tracking_number=f"TRK{rng.randint(10**9, 10**10 - 1)}" if shipped else None,
                placed_at=placed_at,
                delivered_at=delivered_at,
            )
        )
    return orders, items


async def seed() -> None:
    rng = random.Random(SEED)
    fake = Faker("en_US")
    Faker.seed(SEED)

    products = build_products(rng)
    users = build_users(fake)
    orders, items = build_orders(rng, products)

    engine = make_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    session_factory = make_sessionmaker(engine)
    async with session_factory() as session:
        session.add_all(users)
        session.add_all(products)
        await session.flush()
        session.add_all(orders)
        await session.flush()
        session.add_all(items)
        await session.commit()

        for model in (User, Product, Order, OrderItem, ReturnRequest):
            count = await session.scalar(select(func.count()).select_from(model))
            print(f"{model.__tablename__:<12} {count}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
