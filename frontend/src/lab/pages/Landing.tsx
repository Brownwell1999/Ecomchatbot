import { useEffect, useState } from "react";
import { useLabAuth } from "../auth";
import { LESSONS } from "../lessons";
import { Link } from "../router";
import { Reveal } from "../ui";

const DEMO = {
  question: "What is your return policy for electronics?",
  answer: "Electronics can be returned within 15 days of delivery, with all original accessories and packaging.",
  scores: [
    { name: "Answer Relevancy", value: 0.96 },
    { name: "Faithfulness", value: 1.0 },
    { name: "Contextual Recall", value: 1.0 },
  ],
};

const reduceMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** Hero animation: the question types in, ShopBot "thinks", answers, then judge scores fill in. Loops. */
function HeroDemo() {
  const [step, setStep] = useState(() => (reduceMotion() ? 4 : 0)); // 0 typing q · 1 thinking · 2 answer · 3 scoring · 4 done
  const [typed, setTyped] = useState(() => (reduceMotion() ? DEMO.question.length : 0));

  useEffect(() => {
    if (reduceMotion()) return;
    let timer: number;
    if (step === 0) {
      timer = window.setTimeout(() => (typed < DEMO.question.length ? setTyped(typed + 1) : setStep(1)), typed ? 35 : 700);
    } else if (step < 4) {
      timer = window.setTimeout(() => setStep(step + 1), [0, 1100, 900, 1600][step]);
    } else {
      timer = window.setTimeout(() => {
        setTyped(0);
        setStep(0);
      }, 4200);
    }
    return () => window.clearTimeout(timer);
  }, [step, typed]);

  return (
    <div className="demo-card glass" aria-label="Example: ShopBot answer scored by evaluation metrics" role="img">
      <div className="demo-bar">
        <span className="dot r" />
        <span className="dot y" />
        <span className="dot g" />
        <span className="demo-title">ShopBot · live evaluation</span>
      </div>
      <div className="demo-body">
        <div className="demo-msg user">
          {DEMO.question.slice(0, typed)}
          {step === 0 && <span className="caret" />}
        </div>
        {step === 1 && (
          <div className="demo-msg bot typing-dots" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
        )}
        {step >= 2 && <div className="demo-msg bot fade-in">{DEMO.answer}</div>}
        {step >= 2 && (
          <div className="demo-trace fade-in">
            <span className="tag">intent: policy_question</span>
            <span className="tag">route: rag</span>
            <span className="tag">4 chunks · top 0.74</span>
          </div>
        )}
        <div className={`demo-scores ${step >= 3 ? "on" : ""}`}>
          {DEMO.scores.map((s, i) => (
            <div key={s.name} className="score-row">
              <span>{s.name}</span>
              <span className="bar">
                <span style={{ width: step >= 3 ? `${s.value * 100}%` : 0, transitionDelay: `${i * 180}ms` }} />
              </span>
              <b>{step >= 3 ? s.value.toFixed(2) : "–"}</b>
            </div>
          ))}
          <div className={`verdict ${step >= 4 ? "on" : ""}`}>✓ PASS · threshold 0.70</div>
        </div>
      </div>
    </div>
  );
}

const FEATURES = [
  { icon: "🤖", title: "A real RAG chatbot", text: "ShopBot runs NLU, LangGraph, pgvector retrieval, store tools and guardrails. It's a production-style target, not a toy." },
  { icon: "🔍", title: "Live inspector", text: "See intent, entities, retrieved chunks with scores, tool calls, guardrails and every LLM call behind each answer." },
  { icon: "🧭", title: "Guided lessons", text: "Eight hands-on lessons from answer relevancy to prompt injection, each with prompts to try and what to look for." },
  { icon: "🧪", title: "DeepEval-ready code", text: "Every lesson ends with a copy-paste pytest + DeepEval snippet you can run against ShopBot." },
  { icon: "🐞", title: "Planted bugs to find", text: "A wrong knowledge-base document and a flaky memory bug, so you practise catching real failures." },
  { icon: "📈", title: "Track your progress", text: "Mark lessons complete and pick up where you left off, on any device." },
];

const STEPS = [
  { title: "Create your account", text: "Sign up in seconds. Your lab account unlocks ShopBot and every lesson." },
  { title: "Probe the chatbot", text: "Send the lesson's prompts and watch the inspector explain what happened." },
  { title: "Write the eval", text: "Turn what you saw into an automated test with a metric and a threshold." },
];

const FAQ = [
  { q: "Do I need to know machine learning?", a: "No. If you can write a pytest test and read JSON, you can follow every lesson. The lessons explain each metric in plain language." },
  { q: "Which tools does the lab teach?", a: "pytest, httpx and DeepEval (LLM-as-judge metrics), plus deterministic checks such as Top-K retrieval, intent accuracy and guardrail block rate." },
  { q: "Is ShopBot a real store?", a: "No. ShopEase and its customers, products and orders are fictional demo data. Never enter real card numbers or passwords in the chat." },
  { q: "Why are answers different each time?", a: "LLMs are non-deterministic. Handling that is the core skill of AI testing, and lesson 1 covers it." },
  { q: "Is it free?", a: "Yes. Create an account and start learning." },
];

const METRICS = ["Answer Relevancy", "Faithfulness", "Contextual Relevancy", "Contextual Precision", "Contextual Recall", "Top-K / Hit@K", "Turn Relevancy", "Knowledge Retention", "Conversation Completeness", "GEval", "Tool Correctness", "Intent accuracy", "Guardrail block rate"];

export function Landing() {
  const { user } = useLabAuth();
  const start = user ? "/lab" : "/signup";
  return (
    <main id="main">
      <section className="hero">
        <div className="hero-glow" aria-hidden="true" />
        <div className="container hero-grid">
          <div className="hero-copy">
            <span className="eyebrow fade-up">New · Hands-on AI QA training</span>
            <h1 className="fade-up d1">
              Learn to test <span className="gradient-text">AI chatbots</span> the way teams test them in production
            </h1>
            <p className="lead fade-up d2">
              Probe a real RAG chatbot, see exactly why it answered the way it did, and turn it into automated evaluations with pytest and DeepEval.
            </p>
            <div className="hero-cta fade-up d3">
              <Link to={start} className="btn btn-primary btn-lg" data-testid="hero-cta">
                {user ? "Go to your dashboard" : "Start learning free"} →
              </Link>
              <Link to="/#curriculum" className="btn btn-ghost btn-lg">View curriculum</Link>
            </div>
            <ul className="hero-stats fade-up d4">
              <li><b>8</b> lessons</li>
              <li><b>13</b> metrics</li>
              <li><b>1</b> live chatbot</li>
            </ul>
          </div>
          <div className="fade-up d2">
            <HeroDemo />
          </div>
        </div>
      </section>

      <section id="features" className="section">
        <div className="container">
          <Reveal className="section-head">
            <span className="eyebrow">Why this lab</span>
            <h2>Everything you need to test LLM apps</h2>
            <p>Most AI testing courses stop at theory. Here every concept is something you can trigger, inspect and measure.</p>
          </Reveal>
          <div className="feature-grid">
            {FEATURES.map((f, i) => (
              <Reveal key={f.title} delay={i * 60}>
                <article className="feature glass">
                  <span className="feature-icon" aria-hidden="true">{f.icon}</span>
                  <h3>{f.title}</h3>
                  <p>{f.text}</p>
                </article>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <section className="section alt">
        <div className="container">
          <Reveal className="section-head">
            <span className="eyebrow">How it works</span>
            <h2>From question to automated test in three steps</h2>
          </Reveal>
          <ol className="steps">
            {STEPS.map((s, i) => (
              <Reveal key={s.title} delay={i * 100}>
                <li className="step glass">
                  <span className="step-num">{i + 1}</span>
                  <h3>{s.title}</h3>
                  <p>{s.text}</p>
                </li>
              </Reveal>
            ))}
          </ol>
        </div>
      </section>

      <section id="curriculum" className="section">
        <div className="container">
          <Reveal className="section-head">
            <span className="eyebrow">Curriculum</span>
            <h2>Eight lessons, beginner to advanced</h2>
          </Reveal>
          <div className="curriculum">
            {LESSONS.map((l, i) => (
              <Reveal key={l.id} delay={i * 40}>
                <Link to={user ? `/lab/lessons/${l.id}` : "/signup"} className="lesson-row glass">
                  <span className="lesson-num">{String(l.number).padStart(2, "0")}</span>
                  <span className="lesson-row-main">
                    <b>{l.title}</b>
                    <span>{l.summary}</span>
                  </span>
                  <span className={`level ${l.level.toLowerCase()}`}>{l.level}</span>
                  <span className="muted nowrap">{l.minutes} min</span>
                </Link>
              </Reveal>
            ))}
          </div>
          <Reveal className="metric-cloud">
            {METRICS.map((m) => (
              <span key={m} className="tag">{m}</span>
            ))}
          </Reveal>
        </div>
      </section>

      <section id="faq" className="section alt">
        <div className="container narrow">
          <Reveal className="section-head">
            <span className="eyebrow">FAQ</span>
            <h2>Questions, answered</h2>
          </Reveal>
          <div className="faq">
            {FAQ.map((f) => (
              <details key={f.q} className="glass">
                <summary>{f.q}</summary>
                <p>{f.a}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      <section className="section">
        <div className="container">
          <Reveal>
            <div className="cta glass">
              <h2>Ready to catch your first hallucination?</h2>
              <p>Create a free account and send your first prompt in under a minute.</p>
              <Link to={start} className="btn btn-primary btn-lg">{user ? "Continue learning" : "Create free account"} →</Link>
            </div>
          </Reveal>
        </div>
      </section>
    </main>
  );
}
