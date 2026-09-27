import { useSyncExternalStore, type AnchorHTMLAttributes, type MouseEvent } from "react";

// ponytail: History-API router for ~10 static routes; swap in react-router if routes get nested layouts or loaders.
const EVENT = "lab:navigate";

export function navigate(to: string, replace = false) {
  if (replace) history.replaceState(null, "", to);
  else history.pushState(null, "", to);
  window.dispatchEvent(new Event(EVENT));
  const hash = to.split("#")[1];
  if (hash) setTimeout(() => document.getElementById(hash)?.scrollIntoView({ behavior: "smooth" }), 50);
  else window.scrollTo(0, 0);
}

function subscribe(onChange: () => void) {
  window.addEventListener("popstate", onChange);
  window.addEventListener(EVENT, onChange);
  return () => {
    window.removeEventListener("popstate", onChange);
    window.removeEventListener(EVENT, onChange);
  };
}

const snapshot = () => window.location.pathname + window.location.search;

/** useSyncExternalStore re-reads the URL on subscribe, so a redirect fired by a child's effect
 *  (which runs before the parent subscribes) is never missed. */
export function useRoute() {
  const url = useSyncExternalStore(subscribe, snapshot);
  const q = url.indexOf("?");
  return { path: q < 0 ? url : url.slice(0, q), search: q < 0 ? "" : url.slice(q) };
}

/** <a> that navigates without a page reload (still a real link: middle-click, copy link, SEO). */
export function Link({ to, onClick, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement> & { to: string }) {
  function handle(e: MouseEvent<HTMLAnchorElement>) {
    onClick?.(e);
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    navigate(to);
  }
  return <a href={to} onClick={handle} {...rest} />;
}
