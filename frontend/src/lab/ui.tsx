import { useEffect, useRef, useState, type ReactNode } from "react";
import { useLabAuth } from "./auth";
import { Link, navigate, useRoute } from "./router";

export const REPO_URL = "https://github.com/Brownwell1999/Ecomchatbot";

export function Logo() {
  return (
    <Link to="/" className="logo" aria-label="AI Testing Lab home">
      <span className="logo-mark" aria-hidden="true">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 1.7 3h10.6a2 2 0 0 0 1.7-3l-5-9V3" />
          <path d="M7.5 15h9" />
        </svg>
      </span>
      <span className="logo-text">
        AI Testing <b>Lab</b>
      </span>
    </Link>
  );
}

type Theme = "dark" | "light";

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(() => (document.documentElement.dataset.theme as Theme) || "dark");
  function toggle() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("lab.theme", next);
    } catch {
      /* per-visit only */
    }
    setTheme(next);
  }
  return (
    <button className="icon-btn" onClick={toggle} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`} data-testid="theme-toggle">
      {theme === "dark" ? (
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
        </svg>
      )}
    </button>
  );
}

/** Fades/slides children in when they scroll into view (CSS does the motion; reduced-motion users see them at once). */
export function Reveal({ children, className = "", delay = 0 }: { children: ReactNode; className?: string; delay?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || !("IntersectionObserver" in window)) return setShown(true);
    const io = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setShown(true);
        io.disconnect();
      }
    }, { threshold: 0.15 });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return (
    <div ref={ref} className={`reveal ${shown ? "in" : ""} ${className}`} style={{ transitionDelay: `${delay}ms` }}>
      {children}
    </div>
  );
}

function initials(name: string) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]!.toUpperCase()).join("");
}

function UserMenu() {
  const { user, logout } = useLabAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);
  if (!user) return null;
  return (
    <div className="user-menu" ref={ref}>
      <button className="avatar" onClick={() => setOpen((v) => !v)} aria-haspopup="menu" aria-expanded={open} data-testid="user-menu">
        {initials(user.fullName)}
      </button>
      {open && (
        <div className="menu" role="menu">
          <div className="menu-head">
            <b>{user.fullName}</b>
            <span>{user.email}</span>
            <span className={`role-pill ${user.role}`}>{user.role}</span>
          </div>
          <Link to="/lab" role="menuitem" onClick={() => setOpen(false)}>Dashboard</Link>
          <Link to="/lab/playground" role="menuitem" onClick={() => setOpen(false)}>Playground</Link>
          {user.role === "admin" && <Link to="/admin" role="menuitem" onClick={() => setOpen(false)}>Admin</Link>}
          <button
            role="menuitem"
            onClick={() => {
              logout();
              navigate("/");
            }}
            data-testid="logout"
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}

export function TopNav() {
  const { user, checking } = useLabAuth();
  const { path } = useRoute();
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  useEffect(() => setOpen(false), [path]);

  const links = user
    ? [
        { to: "/lab", label: "Dashboard" },
        { to: "/lab/playground", label: "Playground" },
        ...(user.role === "admin" ? [{ to: "/admin", label: "Admin" }] : []),
      ]
    : [
        { to: "/#features", label: "Features" },
        { to: "/#curriculum", label: "Curriculum" },
        { to: "/#faq", label: "FAQ" },
      ];

  return (
    <header className={`topnav ${scrolled ? "scrolled" : ""}`}>
      <div className="container topnav-inner">
        <Logo />
        <nav className={`nav-links ${open ? "open" : ""}`} aria-label="Main">
          {links.map((l) => (
            <Link key={l.to} to={l.to} className={path === l.to ? "active" : ""} aria-current={path === l.to ? "page" : undefined}>
              {l.label}
            </Link>
          ))}
          {!user && !checking && (
            <span className="nav-auth-mobile">
              <Link to="/login">Log in</Link>
              <Link to="/signup">Sign up</Link>
            </span>
          )}
        </nav>
        <div className="nav-actions">
          <ThemeToggle />
          {!checking &&
            (user ? (
              <UserMenu />
            ) : (
              <span className="nav-auth">
                <Link to="/login" className="btn btn-ghost" data-testid="nav-login">Log in</Link>
                <Link to="/signup" className="btn btn-primary" data-testid="nav-signup">Start free</Link>
              </span>
            ))}
          <button className="icon-btn menu-toggle" onClick={() => setOpen((v) => !v)} aria-label="Toggle menu" aria-expanded={open}>
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              {open ? <path d="M6 6l12 12M18 6L6 18" /> : <path d="M4 7h16M4 12h16M4 17h16" />}
            </svg>
          </button>
        </div>
      </div>
    </header>
  );
}

export function Footer() {
  return (
    <footer className="footer">
      <div className="container footer-inner">
        <div className="footer-brand">
          <Logo />
          <p>Learn to test LLM apps on a real RAG chatbot: relevancy, retrieval, hallucination, memory, tools and guardrails.</p>
        </div>
        <div className="footer-cols">
          <div>
            <h4>Product</h4>
            <Link to="/#features">Features</Link>
            <Link to="/#curriculum">Curriculum</Link>
            <Link to="/lab/playground">Playground</Link>
          </div>
          <div>
            <h4>Resources</h4>
            <a href={REPO_URL} target="_blank" rel="noreferrer">Source code</a>
            <a href="https://deepeval.com/docs/metrics-introduction" target="_blank" rel="noreferrer">DeepEval metrics</a>
            <Link to="/#faq">FAQ</Link>
          </div>
          <div>
            <h4>Company</h4>
            <Link to="/privacy">Privacy</Link>
            <Link to="/terms">Terms</Link>
            <a href={`${REPO_URL}/issues`} target="_blank" rel="noreferrer">Contact</a>
          </div>
        </div>
      </div>
      <div className="container footer-bottom">
        <span>© {new Date().getFullYear()} AI Testing Lab. All rights reserved.</span>
        <span>ShopBot and ShopEase are fictional; all store data is demo data.</span>
      </div>
    </footer>
  );
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="spinner-wrap" role="status">
      <span className="spinner" aria-hidden="true" />
      <span className="sr-only">{label}</span>
    </div>
  );
}
