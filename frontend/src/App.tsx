import { useEffect, type ReactNode } from "react";
import { useLabAuth } from "./lab/auth";
import { Admin } from "./lab/pages/Admin";
import { Login, Signup } from "./lab/pages/Auth";
import { Dashboard } from "./lab/pages/Dashboard";
import { Landing } from "./lab/pages/Landing";
import { Forbidden, NotFound, Privacy, Terms } from "./lab/pages/Legal";
import { LessonPage, Playground } from "./lab/pages/Lesson";
import { navigate, useRoute } from "./lab/router";
import { Footer, Spinner, TopNav } from "./lab/ui";

const TITLES: Record<string, string> = {
  "/": "AI Testing Lab · Learn to test AI chatbots",
  "/login": "Log in · AI Testing Lab",
  "/signup": "Sign up · AI Testing Lab",
  "/lab": "Dashboard · AI Testing Lab",
  "/lab/playground": "Playground · AI Testing Lab",
  "/admin": "Admin · AI Testing Lab",
  "/privacy": "Privacy · AI Testing Lab",
  "/terms": "Terms · AI Testing Lab",
};

/** Signed-in lab users only; everyone else goes to /login and comes back afterwards. */
function Protected({ path, children, admin = false }: { path: string; children: ReactNode; admin?: boolean }) {
  const { user, checking } = useLabAuth();
  // path comes from the parent (not useRoute here), so this can't react to its own redirect
  useEffect(() => {
    if (!checking && !user) navigate(`/login?next=${encodeURIComponent(path)}`, true);
  }, [checking, user, path]);
  if (checking || !user) return <Spinner />;
  if (admin && user.role !== "admin") return <Forbidden />;
  return <>{children}</>;
}

function Page({ path }: { path: string }) {
  const lesson = path.match(/^\/lab\/lessons\/([a-z0-9-]+)\/?$/);
  if (lesson) return <Protected path={path}><LessonPage id={lesson[1]!} /></Protected>;
  switch (path.replace(/\/+$/, "") || "/") {
    case "/": return <Landing />;
    case "/login": return <Login />;
    case "/signup": return <Signup />;
    case "/privacy": return <Privacy />;
    case "/terms": return <Terms />;
    case "/lab": return <Protected path={path}><Dashboard /></Protected>;
    case "/lab/playground": return <Protected path={path}><Playground /></Protected>;
    case "/admin": return <Protected path={path} admin><Admin /></Protected>;
    default: return <NotFound />;
  }
}

export default function App() {
  const { path } = useRoute();
  useEffect(() => {
    document.title = TITLES[path] ?? (path.startsWith("/lab/lessons/") ? "Lesson · AI Testing Lab" : "Not found · AI Testing Lab");
  }, [path]);
  const workspace = path.startsWith("/lab/lessons/") || path === "/lab/playground";
  return (
    <div className={`app ${workspace ? "app-workspace" : ""}`}>
      <a href="#main" className="skip-link">Skip to content</a>
      <TopNav />
      <Page path={path} />
      {!workspace && <Footer />}
    </div>
  );
}
