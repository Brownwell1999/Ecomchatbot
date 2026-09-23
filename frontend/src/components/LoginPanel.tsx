import { useEffect, useState, type FormEvent } from "react";
import { useApolloClient } from "@apollo/client";
import { DEMO_USERS } from "../graphql";

interface DemoUser {
  id: number;
  email: string;
  fullName: string;
  orderCount: number;
}

interface Props {
  onLogin: (email: string, password: string) => Promise<string | null>;
  onClose: () => void;
}

export function LoginPanel({ onLogin, onClose }: Props) {
  const client = useApolloClient();
  const [demoUsers, setDemoUsers] = useState<DemoUser[]>([]);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    client.query({ query: DEMO_USERS }).then(({ data }) => setDemoUsers(data?.demoUsers ?? [])).catch(() => {});
  }, [client]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(await onLogin(email, password));
    setBusy(false);
  }

  return (
    <form className="login" onSubmit={submit} data-testid="login-panel">
      <h2>Sign in</h2>
      {demoUsers.length > 0 && (
        <label>
          Demo account
          <select
            data-testid="demo-user-select"
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
              setPassword("demo123");
            }}
          >
            <option value="">Choose a demo customer…</option>
            {demoUsers.map((u) => (
              <option key={u.id} value={u.email}>
                {u.fullName} ({u.orderCount} orders)
              </option>
            ))}
          </select>
        </label>
      )}
      <label>
        Email
        <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="username" data-testid="login-email" />
      </label>
      <label>
        Password
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="current-password" data-testid="login-password" />
      </label>
      <p className="hint">Demo accounts use the password demo123.</p>
      {error && (
        <p className="login-error" role="alert" data-testid="login-error">
          {error}
        </p>
      )}
      <div className="login-actions">
        <button type="button" className="btn-ghost" onClick={onClose}>
          Cancel
        </button>
        <button type="submit" className="btn-primary" disabled={busy} data-testid="login-submit">
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </div>
    </form>
  );
}
