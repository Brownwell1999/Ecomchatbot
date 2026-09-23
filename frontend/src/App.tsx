import { ChatWidget } from "./components/ChatWidget";

export default function App() {
  return (
    <div className="page">
      <header className="store-header">
        <span className="store-logo">ShopEase</span>
        <span className="store-tagline">Customer support</span>
      </header>
      <main className="page-main">
        <ChatWidget />
      </main>
    </div>
  );
}
