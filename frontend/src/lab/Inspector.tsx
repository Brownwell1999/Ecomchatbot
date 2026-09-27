import { useCallback, useState, type ReactNode } from "react";
import { ChatWidget } from "../components/ChatWidget";
import type { DebugInfo } from "../types";

const TABS = ["Overview", "Retrieval", "Tools", "Guardrails", "LLM calls"] as const;
type Tab = (typeof TABS)[number];

function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="stat" title={hint}>
      <span>{label}</span>
      <b>{value}</b>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <p className="inspector-empty">{text}</p>;
}

export function Inspector({ debug }: { debug: DebugInfo | null }) {
  const [tab, setTab] = useState<Tab>("Overview");
  const counts: Partial<Record<Tab, number>> = debug
    ? {
        Retrieval: debug.retrievedChunks.length,
        Tools: debug.toolCalls.length,
        Guardrails: debug.guardrails.length,
        "LLM calls": debug.llmCalls.length,
      }
    : {};

  return (
    <aside className="inspector glass" aria-label="Response inspector" data-testid="inspector">
      <header className="inspector-head">
        <div>
          <h2>Inspector</h2>
          <p className="muted">What happened behind the latest reply</p>
        </div>
        {debug && <span className="tag mono" title="Request id">{debug.requestId.slice(0, 8)}</span>}
      </header>
      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "active" : ""} onClick={() => setTab(t)} data-testid={`inspector-tab-${t}`}>
            {t}
            {counts[t] ? <span className="count">{counts[t]}</span> : null}
          </button>
        ))}
      </div>
      <div className="tab-body" role="tabpanel">
        {!debug ? (
          <Empty text="Send a message to ShopBot. Its intent, retrieved chunks, tool calls, guardrails and LLM calls appear here." />
        ) : tab === "Overview" ? (
          <div className="overview">
            <div className="stats">
              <Stat label="Intent" value={<span data-testid="inspector-intent">{debug.intent}</span>} />
              <Stat label="Confidence" value={debug.confidence.toFixed(2)} />
              <Stat label="NLU source" value={debug.nluSource} hint="llm = model classified it; rules = regex fallback" />
              <Stat label="Route" value={debug.route} />
              <Stat label="Latency" value={`${(debug.latencyMs / 1000).toFixed(1)} s`} />
              <Stat label="History used" value={`${debug.historyMessagesUsed ?? 0} msgs`} />
              <Stat label="Fallback LLM" value={debug.fallbackUsed ? "yes" : "no"} />
              <Stat label="Prompt" value={debug.promptVersion} />
            </div>
            <h3>Entities</h3>
            {Object.keys(debug.entities).length ? (
              <pre className="code small">{JSON.stringify(debug.entities, null, 2)}</pre>
            ) : (
              <Empty text="No entities extracted." />
            )}
          </div>
        ) : tab === "Retrieval" ? (
          debug.retrievedChunks.length ? (
            <ol className="chunk-list">
              {debug.retrievedChunks.map((c, i) => (
                <li key={c.chunkId} className={c.used ? "" : "unused"} data-testid="inspector-chunk">
                  <div className="chunk-head">
                    <span className="rank">#{i + 1}</span>
                    <span className="mono">{c.chunkId}</span>
                    <span className={`pill ${c.used ? "ok" : ""}`}>{c.used ? "used" : "not used"}</span>
                  </div>
                  <div className="score-line">
                    <span className="bar"><span style={{ width: `${Math.max(0, Math.min(1, c.score)) * 100}%` }} /></span>
                    <b>{c.score.toFixed(3)}</b>
                  </div>
                  <details>
                    <summary>{c.section || "chunk text"}</summary>
                    <p className="chunk-text">{c.content}</p>
                  </details>
                </li>
              ))}
            </ol>
          ) : (
            <Empty text="No chunks retrieved: this reply didn't use the knowledge base (try a policy question)." />
          )
        ) : tab === "Tools" ? (
          debug.toolCalls.length ? (
            <ul className="call-list">
              {debug.toolCalls.map((t, i) => (
                <li key={i} data-testid="inspector-tool">
                  <div className="chunk-head">
                    <span className="mono">{t.name}</span>
                    <span className={`pill ${t.ok ? "ok" : "bad"}`}>{t.ok ? "ok" : "failed"}</span>
                    <span className="muted">{t.latencyMs} ms</span>
                  </div>
                  <pre className="code small">args: {JSON.stringify(t.args, null, 2)}</pre>
                  {t.error && <p className="form-error">{t.error}</p>}
                  {t.output != null && (
                    <details>
                      <summary>output</summary>
                      <pre className="code small">{JSON.stringify(t.output, null, 2)}</pre>
                    </details>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <Empty text="No tools called. Order and product questions call tools; order tools need a signed-in demo customer." />
          )
        ) : tab === "Guardrails" ? (
          debug.guardrails.length ? (
            <ul className="call-list">
              {debug.guardrails.map((g, i) => (
                <li key={i} className={g.passed ? "" : "hit"} data-testid="inspector-guardrail">
                  <div className="chunk-head">
                    <span className="mono">{g.stage}/{g.name}</span>
                    <span className={`pill ${g.passed ? "ok" : "bad"}`}>{g.action}</span>
                    {g.score !== null && <span className="muted">score {g.score}</span>}
                  </div>
                  {g.detail && <p className="muted small">{g.detail}</p>}
                </li>
              ))}
            </ul>
          ) : (
            <Empty text="No guardrail fired: the message and reply passed every check." />
          )
        ) : debug.llmCalls.length ? (
          <table className="table small">
            <thead>
              <tr><th>Step</th><th>Model</th><th>Latency</th><th>Tokens in→out</th></tr>
            </thead>
            <tbody>
              {debug.llmCalls.map((c, i) => (
                <tr key={i}>
                  <td>{c.step}</td>
                  <td className="mono">{c.provider}/{c.model}</td>
                  <td>{c.latencyMs} ms</td>
                  <td>{c.inputTokens ?? "?"} → {c.outputTokens ?? "?"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty text="No LLM calls (answered by rules or blocked by a guardrail)." />
        )}
      </div>
    </aside>
  );
}

/** ShopBot chat + inspector side by side: the lab's working area. */
export function Workspace({ prompts }: { prompts?: string[] }) {
  const [debug, setDebug] = useState<DebugInfo | null>(null);
  const onDebug = useCallback((d: DebugInfo | null) => setDebug(d), []);
  return (
    <div className="workspace">
      <ChatWidget prompts={prompts} onDebug={onDebug} />
      <Inspector debug={debug} />
    </div>
  );
}
