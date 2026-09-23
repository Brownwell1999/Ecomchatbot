import type { Order, Product, Source } from "../types";

const money = (n: number) => `$${n.toFixed(2)}`;
const date = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString() : "—");
const label = (s: string) => s.replace(/_/g, " ");

export function ProductCards({ products }: { products: Product[] }) {
  return (
    <div className="cards" data-testid="product-cards">
      {products.map((p) => (
        <article key={p.id} className="card product" data-testid="product-card" data-product-id={p.id}>
          <div className="card-kicker">{label(p.category)}</div>
          <h3>{p.name}</h3>
          <div className="product-meta">
            <span className="price" data-testid="product-price">{money(p.price)}</span>
            <span aria-label={`Rated ${p.rating} out of 5`}>★ {p.rating.toFixed(1)}</span>
          </div>
          <div className={`stock ${p.stock > 0 ? "in" : "out"}`} data-testid="product-stock">
            {p.stock > 0 ? `${p.stock} in stock` : "Out of stock"}
          </div>
        </article>
      ))}
    </div>
  );
}

export function OrderCard({ order }: { order: Order }) {
  return (
    <article className="card order" data-testid="order-card" data-order-id={order.id}>
      <header>
        <h3>Order #{order.id}</h3>
        <span className={`status status-${order.status}`} data-testid="order-status">
          {label(order.status)}
        </span>
      </header>
      <dl>
        <dt>Placed</dt>
        <dd>{date(order.placedAt)}</dd>
        {order.deliveredAt && (
          <>
            <dt>Delivered</dt>
            <dd>{date(order.deliveredAt)}</dd>
          </>
        )}
        {order.carrier && (
          <>
            <dt>Carrier</dt>
            <dd>
              {order.carrier} · <span className="mono" data-testid="order-tracking">{order.trackingNumber}</span>
            </dd>
          </>
        )}
        <dt>Total</dt>
        <dd>{money(order.total)}</dd>
      </dl>
      <ul className="order-items">
        {order.items.map((i) => (
          <li key={i.name}>
            {i.quantity} × {i.name} <span>{money(i.unitPrice)}</span>
          </li>
        ))}
      </ul>
    </article>
  );
}

export function Sources({ sources }: { sources: Source[] }) {
  // One chip per document section, even if several chunks came from it
  const unique = [...new Map(sources.map((s) => [`${s.source}›${s.section}`, s])).values()];
  return (
    <div className="sources" data-testid="sources">
      <span>Sources:</span>
      {unique.map((s) => (
        <span key={s.chunkId} className="source-chip" data-testid="source-chip" title={`relevance ${s.score.toFixed(3)}`}>
          {s.source.replace(".md", "").replace(/_/g, " ")} › {s.section}
        </span>
      ))}
    </div>
  );
}
