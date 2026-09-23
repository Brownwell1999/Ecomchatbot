import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage, DebugInfo } from "../types";
import { OrderCard, ProductCards, Sources } from "./Cards";

interface Props {
  messages: ChatMessage[];
  pending: boolean;
  onRetry: (message: ChatMessage) => void;
  onSuggestion: (text: string) => void;
  onFeedback: (messageId: string, rating: 1 | -1) => Promise<boolean>;
}

export function MessageList({ messages, pending, onRetry, onSuggestion, onFeedback }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const last = messages[messages.length - 1];
  const streaming = last?.status === "streaming";

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length, pending, last?.content]);

  return (
    <div className="messages" data-testid="message-list" aria-live="polite">
      {messages.map((m) => (
        <MessageBubble key={m.id} message={m} onRetry={onRetry} onFeedback={onFeedback} />
      ))}
      {pending && !streaming && (
        <div className="bubble-row assistant" data-testid="typing-indicator" aria-label="ShopBot is typing">
          <div className="bubble typing">
            <span />
            <span />
            <span />
          </div>
        </div>
      )}
      {/* Quick replies only for the latest bot message */}
      {!pending && last?.role === "assistant" && last.suggestions?.length ? (
        <div className="quick-replies" data-testid="quick-replies">
          {last.suggestions.map((s) => (
            <button key={s} className="chip" onClick={() => onSuggestion(s)} data-testid="quick-reply">
              {s}
            </button>
          ))}
        </div>
      ) : null}
      <div ref={bottomRef} />
    </div>
  );
}

function MessageBubble({ message, onRetry, onFeedback }: { message: ChatMessage; onRetry: Props["onRetry"]; onFeedback: Props["onFeedback"] }) {
  const [showDebug, setShowDebug] = useState(false);
  const [rated, setRated] = useState<1 | -1 | null>(null);
  const canRate = message.role === "assistant" && !message.status;

  async function rate(rating: 1 | -1) {
    if (rated) return;
    setRated(rating);
    if (!(await onFeedback(message.id, rating))) setRated(null);
  }
  const time = new Date(message.createdAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  return (
    <div
      className={`bubble-row ${message.role}`}
      data-testid={message.role === "user" ? "user-message" : "bot-message"}
      data-message-id={message.id}
      data-status={message.status ?? "sent"}
      data-intent={message.debug?.intent}
    >
      <div className={`bubble ${message.status === "failed" ? "failed" : ""}`}>
        <div className={`bubble-text ${message.role}`} data-testid="message-text">
          {/* Bot replies are Markdown; user text stays literal. react-markdown escapes raw HTML. */}
          {message.role === "assistant" ? <Markdown remarkPlugins={[remarkGfm]}>{message.content}</Markdown> : message.content}
        </div>
        {message.products?.length ? <ProductCards products={message.products} /> : null}
        {message.order ? <OrderCard order={message.order} /> : null}
        {message.sources?.length ? <Sources sources={message.sources} /> : null}
        <div className="bubble-meta">
          <time dateTime={message.createdAt}>{time}</time>
          {message.status === "failed" && (
            <button className="link" onClick={() => onRetry(message)} data-testid="retry-button">
              Not sent · Retry
            </button>
          )}
          {canRate && (
            <span className="feedback" data-testid="feedback" data-rated={rated ?? ""}>
              <button className={rated === 1 ? "on" : ""} onClick={() => rate(1)} disabled={rated !== null} aria-label="Helpful" data-testid="feedback-up">
                👍
              </button>
              <button className={rated === -1 ? "on" : ""} onClick={() => rate(-1)} disabled={rated !== null} aria-label="Not helpful" data-testid="feedback-down">
                👎
              </button>
            </span>
          )}
          {message.debug && (
            <button className="link" onClick={() => setShowDebug((v) => !v)} data-testid="debug-toggle">
              {showDebug ? "hide details" : "details"}
            </button>
          )}
        </div>
        {showDebug && message.debug && <DebugPanel debug={message.debug} />}
      </div>
    </div>
  );
}

function DebugPanel({ debug }: { debug: DebugInfo }) {
  return (
    <div className="debug" data-testid="message-debug">
      <div>
        <b>intent</b> <span data-testid="debug-intent">{debug.intent}</span> ({debug.confidence.toFixed(2)}, {debug.nluSource}) → <b>route</b> {debug.route}
      </div>
      {Object.keys(debug.entities).length > 0 && (
        <div>
          <b>entities</b> <span className="mono">{JSON.stringify(debug.entities)}</span>
        </div>
      )}
      {debug.toolCalls.map((t, i) => (
        <div key={i} data-testid="debug-tool-call">
          <b>tool</b> <span className="mono">{t.name}({JSON.stringify(t.args)})</span> {t.ok ? "✓" : "✗"} {t.latencyMs} ms
        </div>
      ))}
      {debug.retrievedChunks.map((c) => (
        <div key={c.chunkId} className={c.used ? "" : "muted"} data-testid="debug-chunk">
          <b>chunk</b> <span className="mono">{c.chunkId}</span> {c.score.toFixed(3)} {c.used ? "used" : "below threshold"}
        </div>
      ))}
      {debug.guardrails.map((g, i) => (
        <div key={i} className={g.passed ? "muted" : "guard-hit"} data-testid="debug-guardrail">
          <b>guard</b> {g.stage}/{g.name} → {g.action}
          {g.score !== null ? ` (${g.score})` : ""} {g.detail}
        </div>
      ))}
      {debug.llmCalls.map((c, i) => (
        <div key={i}>
          <b>llm</b> {c.step}: {c.provider}/{c.model} · {c.latencyMs} ms · {c.inputTokens ?? "?"}→{c.outputTokens ?? "?"} tokens
        </div>
      ))}
      <div>
        <b>total</b> {debug.latencyMs} ms{debug.fallbackUsed ? " · fallback used" : ""} · prompt {debug.promptVersion} ·{" "}
        <span className="mono">{debug.requestId}</span>
      </div>
    </div>
  );
}
