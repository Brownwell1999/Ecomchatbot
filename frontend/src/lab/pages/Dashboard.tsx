import { useLabAuth } from "../auth";
import { LESSONS } from "../lessons";
import { Link } from "../router";

function ProgressRing({ done, total }: { done: number; total: number }) {
  const r = 52;
  const c = 2 * Math.PI * r;
  const pct = total ? done / total : 0;
  return (
    <div className="ring" role="img" aria-label={`${done} of ${total} lessons complete`}>
      <svg viewBox="0 0 120 120" width="132" height="132">
        <defs>
          <linearGradient id="ringGrad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="var(--accent-1)" />
            <stop offset="100%" stopColor="var(--accent-2)" />
          </linearGradient>
        </defs>
        <circle cx="60" cy="60" r={r} className="ring-track" />
        <circle cx="60" cy="60" r={r} className="ring-value" stroke="url(#ringGrad)" strokeDasharray={c} strokeDashoffset={c * (1 - pct)} />
      </svg>
      <div className="ring-label">
        <b>{Math.round(pct * 100)}%</b>
        <span>{done}/{total} lessons</span>
      </div>
    </div>
  );
}

export function Dashboard() {
  const { user, completed } = useLabAuth();
  const next = LESSONS.find((l) => !completed.has(l.id));
  const done = LESSONS.filter((l) => completed.has(l.id)).length;
  const firstName = user?.fullName.split(" ")[0] ?? "";

  return (
    <main id="main" className="container page-pad">
      <section className="dash-hero glass fade-up">
        <div>
          <span className="eyebrow">Dashboard</span>
          <h1>Welcome{done ? " back" : ""}, {firstName} 👋</h1>
          <p className="muted">
            {next
              ? done
                ? `Next up: lesson ${next.number}, "${next.title}".`
                : "Start with lesson 1. It takes about 10 minutes."
              : "You've completed every lesson. Keep exploring in the playground."}
          </p>
          <div className="hero-cta">
            {next ? (
              <Link to={`/lab/lessons/${next.id}`} className="btn btn-primary" data-testid="continue-lesson">
                {done ? "Continue learning" : "Start lesson 1"} →
              </Link>
            ) : null}
            <Link to="/lab/playground" className="btn btn-ghost">Open playground</Link>
          </div>
        </div>
        <ProgressRing done={done} total={LESSONS.length} />
      </section>

      <h2 className="section-title">All lessons</h2>
      <div className="lesson-grid" data-testid="lesson-grid">
        {LESSONS.map((l, i) => {
          const isDone = completed.has(l.id);
          return (
            <Link
              key={l.id}
              to={`/lab/lessons/${l.id}`}
              className={`lesson-card glass fade-up ${isDone ? "done" : ""}`}
              style={{ animationDelay: `${i * 50}ms` }}
              data-testid="lesson-card"
              data-lesson-id={l.id}
              data-completed={isDone}
            >
              <div className="lesson-card-top">
                <span className="lesson-num">{String(l.number).padStart(2, "0")}</span>
                <span className={`status-pill ${isDone ? "done" : next?.id === l.id ? "next" : ""}`}>
                  {isDone ? "✓ Completed" : next?.id === l.id ? "Up next" : "Not started"}
                </span>
              </div>
              <h3>{l.title}</h3>
              <p>{l.summary}</p>
              <div className="lesson-card-meta">
                <span className={`level ${l.level.toLowerCase()}`}>{l.level}</span>
                <span className="muted">{l.minutes} min</span>
                {l.needsCustomer && <span className="muted">· demo login</span>}
              </div>
            </Link>
          );
        })}
      </div>
    </main>
  );
}
