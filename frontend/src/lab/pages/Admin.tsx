import { useCallback, useEffect, useMemo, useState } from "react";
import { ApolloError, useApolloClient } from "@apollo/client";
import { LAB_UPDATE_USER, LAB_USERS } from "../../graphql";
import type { LabUserAdmin } from "../../types";
import { useLabAuth } from "../auth";
import { LESSONS } from "../lessons";
import { Spinner } from "../ui";

const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "Never");

export function Admin() {
  const client = useApolloClient();
  const { user: me } = useLabAuth();
  const [users, setUsers] = useState<LabUserAdmin[] | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(() => {
    client
      .query({ query: LAB_USERS })
      .then(({ data }) => setUsers(data.labUsers))
      .catch(() => setError("Couldn't load users."));
  }, [client]);
  useEffect(load, [load]);

  async function update(id: number, changes: { role?: string; active?: boolean }) {
    setBusyId(id);
    setError(null);
    try {
      const { data } = await client.mutate({ mutation: LAB_UPDATE_USER, variables: { id, ...changes } });
      setUsers((list) => list?.map((u) => (u.id === id ? { ...u, ...data.labUpdateUser } : u)) ?? null);
    } catch (err) {
      setError(err instanceof ApolloError ? err.graphQLErrors[0]?.message ?? "Update failed." : "Update failed.");
    }
    setBusyId(null);
  }

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (users ?? []).filter((u) => !q || u.fullName.toLowerCase().includes(q) || u.email.toLowerCase().includes(q));
  }, [users, query]);

  const stats = users && {
    total: users.length,
    active: users.filter((u) => u.active).length,
    admins: users.filter((u) => u.role === "admin").length,
    completions: users.reduce((n, u) => n + u.lessonsCompleted, 0),
  };

  return (
    <main id="main" className="container page-pad">
      <header className="page-head fade-up">
        <span className="eyebrow">Admin</span>
        <h1>Users & progress</h1>
        <p className="muted">Manage roles and access. Disabled users are signed out on their next request.</p>
      </header>

      {!users && !error ? (
        <Spinner label="Loading users…" />
      ) : (
        <>
          {stats && (
            <div className="stat-cards">
              {[
                ["Learners", stats.total],
                ["Active", stats.active],
                ["Admins", stats.admins],
                ["Lessons completed", stats.completions],
              ].map(([label, value]) => (
                <div key={label} className="stat-card glass fade-up">
                  <span>{label}</span>
                  <b>{value}</b>
                </div>
              ))}
            </div>
          )}

          <div className="table-tools">
            <input
              type="search"
              placeholder="Search name or email…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Search users"
              data-testid="admin-search"
            />
            <button className="btn btn-ghost" onClick={load}>Refresh</button>
          </div>
          {error && <p className="form-error" role="alert">{error}</p>}

          <div className="table-wrap glass">
            <table className="table" data-testid="admin-users">
              <thead>
                <tr>
                  <th>User</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Progress</th>
                  <th>Joined</th>
                  <th>Last login</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((u) => {
                  const self = u.id === me?.id;
                  return (
                    <tr key={u.id} data-testid="admin-user-row" data-email={u.email}>
                      <td>
                        <b>{u.fullName}</b>
                        {self && <span className="muted"> (you)</span>}
                        <div className="muted small">{u.email}</div>
                      </td>
                      <td>
                        <select
                          value={u.role}
                          disabled={self || busyId === u.id}
                          onChange={(e) => update(u.id, { role: e.target.value })}
                          aria-label={`Role for ${u.email}`}
                        >
                          <option value="learner">Learner</option>
                          <option value="admin">Admin</option>
                        </select>
                      </td>
                      <td>
                        <button
                          className={`switch ${u.active ? "on" : ""}`}
                          role="switch"
                          aria-checked={u.active}
                          aria-label={`${u.active ? "Disable" : "Enable"} ${u.email}`}
                          disabled={self || busyId === u.id}
                          onClick={() => update(u.id, { active: !u.active })}
                          data-testid="admin-toggle-active"
                        >
                          <span />
                        </button>
                        <span className="muted small"> {u.active ? "Active" : "Disabled"}</span>
                      </td>
                      <td>
                        <div className="mini-progress" title={`${u.lessonsCompleted}/${LESSONS.length}`}>
                          <span style={{ width: `${(u.lessonsCompleted / LESSONS.length) * 100}%` }} />
                        </div>
                        <span className="muted small">{u.lessonsCompleted}/{LESSONS.length}</span>
                      </td>
                      <td className="nowrap">{fmt(u.createdAt)}</td>
                      <td className="nowrap">{fmt(u.lastLoginAt)}</td>
                    </tr>
                  );
                })}
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={6} className="muted center">No users match “{query}”.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </main>
  );
}
