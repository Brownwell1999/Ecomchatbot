import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { useLabAuth } from "../auth";
import { Link, navigate, useRoute } from "../router";

/** Only same-site paths are allowed as ?next= targets (no open redirects). */
function nextPath(search: string) {
  const next = new URLSearchParams(search).get("next") ?? "";
  return next.startsWith("/") && !next.startsWith("//") ? next : "/lab";
}

function AuthCard({ title, subtitle, children, footer }: { title: string; subtitle: string; children: ReactNode; footer: ReactNode }) {
  return (
    <main id="main" className="auth-page">
      <div className="hero-glow" aria-hidden="true" />
      <div className="auth-card glass fade-up">
        <h1>{title}</h1>
        <p className="muted">{subtitle}</p>
        {children}
        <p className="auth-footer">{footer}</p>
      </div>
    </main>
  );
}

function PasswordField({ value, onChange, autoComplete, testId }: { value: string; onChange: (v: string) => void; autoComplete: string; testId: string }) {
  const [show, setShow] = useState(false);
  return (
    <div className="password-field">
      <input
        id="password"
        type={show ? "text" : "password"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required
        autoComplete={autoComplete}
        data-testid={testId}
      />
      <button type="button" className="reveal-btn" onClick={() => setShow((v) => !v)} aria-label={show ? "Hide password" : "Show password"}>
        {show ? "Hide" : "Show"}
      </button>
    </div>
  );
}

const RULES = [
  { label: "8+ characters", test: (p: string) => p.length >= 8 },
  { label: "A letter", test: (p: string) => /[A-Za-z]/.test(p) },
  { label: "A number", test: (p: string) => /\d/.test(p) },
];

function useRedirectIfSignedIn(target: string) {
  const { user } = useLabAuth();
  useEffect(() => {
    if (user) navigate(target, true);
  }, [user, target]);
}

export function Login() {
  const { login } = useLabAuth();
  const { search } = useRoute();
  const target = nextPath(search);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useRedirectIfSignedIn(target);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    const err = await login(email, password);
    setBusy(false);
    setError(err); // success: useRedirectIfSignedIn moves on
  }

  return (
    <AuthCard
      title="Welcome back"
      subtitle="Log in to continue your AI testing lessons."
      footer={<>New here? <Link to={`/signup${search}`}>Create an account</Link></>}
    >
      <form className="form" onSubmit={submit} noValidate={false} data-testid="login-form">
        <label htmlFor="email">Email</label>
        <input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" autoFocus data-testid="login-email" />
        <label htmlFor="password">Password</label>
        <PasswordField value={password} onChange={setPassword} autoComplete="current-password" testId="login-password" />
        {error && <p className="form-error" role="alert" data-testid="login-error">{error}</p>}
        <button type="submit" className="btn btn-primary btn-block" disabled={busy} data-testid="login-submit">
          {busy ? "Logging in…" : "Log in"}
        </button>
      </form>
    </AuthCard>
  );
}

export function Signup() {
  const { signup } = useLabAuth();
  const { search } = useRoute();
  const target = nextPath(search);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [agree, setAgree] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useRedirectIfSignedIn(target);
  const strong = RULES.every((r) => r.test(password));

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!strong) return setError("Choose a stronger password.");
    setBusy(true);
    const err = await signup(name, email, password);
    setBusy(false);
    setError(err); // success: useRedirectIfSignedIn moves on
  }

  return (
    <AuthCard
      title="Create your account"
      subtitle="Free access to ShopBot and all eight lessons."
      footer={<>Already have an account? <Link to={`/login${search}`}>Log in</Link></>}
    >
      <form className="form" onSubmit={submit} data-testid="signup-form">
        <label htmlFor="name">Full name</label>
        <input id="name" value={name} onChange={(e) => setName(e.target.value)} required maxLength={100} autoComplete="name" autoFocus data-testid="signup-name" />
        <label htmlFor="email">Email</label>
        <input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" data-testid="signup-email" />
        <label htmlFor="password">Password</label>
        <PasswordField value={password} onChange={setPassword} autoComplete="new-password" testId="signup-password" />
        <ul className="pw-rules" aria-label="Password requirements">
          {RULES.map((r) => (
            <li key={r.label} className={r.test(password) ? "ok" : ""}>{r.label}</li>
          ))}
        </ul>
        <label className="check">
          <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} required data-testid="signup-terms" />
          <span>
            I agree to the <Link to="/terms">Terms</Link> and <Link to="/privacy">Privacy Policy</Link>
          </span>
        </label>
        {error && <p className="form-error" role="alert" data-testid="signup-error">{error}</p>}
        <button type="submit" className="btn btn-primary btn-block" disabled={busy || !agree} data-testid="signup-submit">
          {busy ? "Creating account…" : "Create account"}
        </button>
      </form>
    </AuthCard>
  );
}
