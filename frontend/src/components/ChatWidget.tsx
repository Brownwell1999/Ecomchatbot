import { useState } from "react";
import { useAuth } from "../hooks/useAuth";
import { useChat } from "../hooks/useChat";
import { ChatInput } from "./ChatInput";
import { LoginPanel } from "./LoginPanel";
import { MessageList } from "./MessageList";

const SUGGESTIONS = [
  "Show me running shoes under $100",
  "Where is my order?",
  "What is your return policy for electronics?",
  "I need something to keep my coffee hot",
];

export function ChatWidget() {
  const { user, checking, login, logout } = useAuth();
  const { conversationId, messages, pending, restoring, error, send, retry, sendFeedback, newChat } = useChat();
  const [showLogin, setShowLogin] = useState(false);
  const empty = messages.length === 0 && !restoring;

  // A new identity gets a fresh conversation, so one customer's context never leaks to another
  async function handleLogin(email: string, password: string) {
    const err = await login(email, password);
    if (!err) {
      setShowLogin(false);
      newChat();
    }
    return err;
  }

  function handleLogout() {
    logout();
    newChat();
  }

  return (
    <section className="chat" data-testid="chat-widget" aria-label="ShopBot chat">
      <header className="chat-header">
        <div className="chat-avatar" aria-hidden="true">S</div>
        <div className="chat-title">
          <h1>ShopBot</h1>
          <p data-testid="chat-status">{pending ? "Typing…" : "Online · AI assistant"}</p>
        </div>
        {!checking &&
          (user ? (
            <div className="user-badge" data-testid="user-badge">
              <span title={user.email}>{user.fullName}</span>
              <button className="btn-ghost" onClick={handleLogout} data-testid="logout-button">
                Sign out
              </button>
            </div>
          ) : (
            <button className="btn-ghost" onClick={() => setShowLogin(true)} data-testid="login-button">
              Sign in
            </button>
          ))}
        <button className="btn-ghost" onClick={newChat} disabled={pending || messages.length === 0} data-testid="new-chat-button">
          New chat
        </button>
      </header>

      {showLogin && !user ? (
        <LoginPanel onLogin={handleLogin} onClose={() => setShowLogin(false)} />
      ) : empty ? (
        <div className="chat-empty" data-testid="welcome-panel">
          <h2>Hi{user ? `, ${user.fullName.split(" ")[0]}` : ""}! I'm ShopBot 👋</h2>
          <p>I can find products, track orders, start returns and answer policy questions.</p>
          <div className="suggestions">
            {SUGGESTIONS.map((s) => (
              <button key={s} className="chip" onClick={() => send(s)} data-testid="suggestion-chip">
                {s}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <MessageList messages={messages} pending={pending} onRetry={retry} onSuggestion={send} onFeedback={sendFeedback} />
      )}

      {error && (
        <div className="chat-error" role="alert" data-testid="chat-error" data-error-code={error.code}>
          {error.message}
        </div>
      )}

      <ChatInput onSend={send} disabled={pending || restoring || showLogin} />
      <footer className="chat-footer" data-testid="conversation-id" data-conversation-id={conversationId ?? ""}>
        AI responses may be inaccurate. Never share card numbers or passwords.
      </footer>
    </section>
  );
}
